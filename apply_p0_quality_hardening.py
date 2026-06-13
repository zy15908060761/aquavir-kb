#!/usr/bin/env python3
"""Apply low-risk P0 quality hardening actions.

The script only changes records where the current database already proves the
problem. It does not merge duplicate accessions or infer new biological facts.
"""

from __future__ import annotations

import csv
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from db_utils import DB_PATH, backup_database


BASE_DIR = Path(__file__).resolve().parent
REPORTS_DIR = BASE_DIR / "reports"
SCRIPT_NAME = Path(__file__).name


def stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH), timeout=120)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 120000")
    return conn


def rows(conn: sqlite3.Connection, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def write_csv(path: Path, data: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not data:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(data[0].keys()))
        writer.writeheader()
        writer.writerows(data)


def append_note(existing: str | None, note: str) -> str:
    text = (existing or "").strip()
    if note in text:
        return text
    return f"{text}; {note}" if text else note


def ensure_logs(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS quality_hardening_log (
            log_id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_ts TEXT NOT NULL,
            script_name TEXT NOT NULL,
            action TEXT NOT NULL,
            affected_count INTEGER NOT NULL,
            details_json TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )


def log_action(conn: sqlite3.Connection, run_ts: str, action: str, affected: int, details: Any = None) -> None:
    conn.execute(
        """
        INSERT INTO quality_hardening_log(run_ts, script_name, action, affected_count, details_json)
        VALUES (?, ?, ?, ?, ?)
        """,
        (run_ts, SCRIPT_NAME, action, affected, json.dumps(details, ensure_ascii=False) if details is not None else None),
    )


def reject_unlinked_evidence(conn: sqlite3.Connection, run_ts: str) -> list[dict[str, Any]]:
    targets = rows(
        conn,
        """
        SELECT evidence_id, evidence_type, curation_status, evidence_strength,
               claim, value_text, notes
        FROM evidence_records
        WHERE virus_master_id IS NULL AND host_id IS NULL AND isolate_id IS NULL
          AND reference_id IS NULL AND source_id IS NULL
          AND COALESCE(curation_status, '') <> 'rejected'
        ORDER BY evidence_id
        """,
    )
    note = "Rejected by P0 QA hardening: evidence row has no virus/host/isolate/reference/source link."
    for item in targets:
        conn.execute(
            """
            UPDATE evidence_records
            SET curation_status = 'rejected',
                evidence_strength = CASE
                    WHEN evidence_strength IS NULL OR evidence_strength = '' THEN 'low'
                    ELSE evidence_strength
                END,
                notes = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE evidence_id = ?
            """,
            (append_note(item.get("notes"), note), item["evidence_id"]),
        )
    log_action(conn, run_ts, "reject_unlinked_evidence", len(targets))
    return targets


def fix_host_scope_conflicts(conn: sqlite3.Connection, run_ts: str) -> list[dict[str, Any]]:
    targets = rows(
        conn,
        """
        SELECT host_id, scientific_name, phylum, class, host_scope_status, public_visibility
        FROM crustacean_hosts
        WHERE host_scope_status = 'target_mollusk'
          AND COALESCE(phylum, '') <> 'Mollusca'
        ORDER BY host_id
        """,
    )
    for item in targets:
        conn.execute(
            """
            UPDATE crustacean_hosts
            SET host_scope_status = 'target_other_aquatic_invert'
            WHERE host_id = ?
            """,
            (item["host_id"],),
        )
    log_action(conn, run_ts, "fix_target_mollusk_phylum_conflicts", len(targets))
    return targets


def hide_excluded_public_hosts(conn: sqlite3.Connection, run_ts: str) -> list[dict[str, Any]]:
    targets = rows(
        conn,
        """
        SELECT host_id, scientific_name, phylum, class, host_scope_status, public_visibility
        FROM crustacean_hosts
        WHERE COALESCE(host_scope_status, '') LIKE 'excluded%'
          AND COALESCE(public_visibility, 'public') = 'public'
        ORDER BY host_id
        """,
    )
    conn.execute(
        """
        UPDATE crustacean_hosts
        SET public_visibility = 'internal_only'
        WHERE COALESCE(host_scope_status, '') LIKE 'excluded%'
          AND COALESCE(public_visibility, 'public') = 'public'
        """
    )
    log_action(conn, run_ts, "hide_excluded_public_hosts", len(targets))
    return targets


def flag_bad_mortality_ranges(conn: sqlite3.Connection, run_ts: str) -> list[dict[str, Any]]:
    targets = rows(
        conn,
        """
        SELECT pathogenicity_id, virus_master_id, host_id, isolate_id, reference_id,
               mortality_rate_min, mortality_rate_max, evidence_strength,
               curation_status, notes
        FROM pathogenicity_evidence
        WHERE mortality_rate_min IS NOT NULL
          AND mortality_rate_max IS NOT NULL
          AND mortality_rate_min > mortality_rate_max
        ORDER BY pathogenicity_id
        """,
    )
    note = "Flagged by P0 QA hardening: mortality_rate_min > mortality_rate_max; numeric mortality values cleared pending source review."
    for item in targets:
        conn.execute(
            """
            UPDATE pathogenicity_evidence
            SET mortality_rate_min = NULL,
                mortality_rate_max = NULL,
                evidence_strength = 'low',
                curation_status = 'needs_review',
                notes = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE pathogenicity_id = ?
            """,
            (append_note(item.get("notes"), note), item["pathogenicity_id"]),
        )
    log_action(conn, run_ts, "flag_bad_mortality_ranges", len(targets))
    return targets


def queue_duplicate_accessions(conn: sqlite3.Connection, run_ts: str) -> list[dict[str, Any]]:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS accession_duplicate_review_queue (
            queue_id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_ts TEXT NOT NULL,
            dedupe_key TEXT NOT NULL,
            isolate_ids TEXT NOT NULL,
            accession_values TEXT NOT NULL,
            virus_names TEXT,
            master_ids TEXT,
            priority TEXT NOT NULL DEFAULT 'P0',
            status TEXT NOT NULL DEFAULT 'open',
            recommended_action TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(dedupe_key, isolate_ids)
        )
        """
    )
    targets = rows(
        conn,
        """
        SELECT lower(trim(accession)) AS dedupe_key,
               group_concat(isolate_id) AS isolate_ids,
               group_concat(accession) AS accession_values,
               group_concat(DISTINCT virus_name) AS virus_names,
               group_concat(DISTINCT COALESCE(master_id, 'NULL')) AS master_ids,
               COUNT(*) AS n
        FROM viral_isolates
        WHERE accession IS NOT NULL AND trim(accession) <> ''
        GROUP BY lower(trim(accession))
        HAVING COUNT(*) > 1
        ORDER BY dedupe_key
        """,
    )
    for item in targets:
        conn.execute(
            """
            INSERT OR IGNORE INTO accession_duplicate_review_queue(
                run_ts, dedupe_key, isolate_ids, accession_values, virus_names,
                master_ids, priority, status, recommended_action
            )
            VALUES (?, ?, ?, ?, ?, ?, 'P0', 'open',
                    'Review case-only duplicate accession rows; merge only after checking sequence/protein/evidence child records.')
            """,
            (
                run_ts,
                item["dedupe_key"],
                item["isolate_ids"],
                item["accession_values"],
                item["virus_names"],
                item["master_ids"],
            ),
        )
    log_action(conn, run_ts, "queue_duplicate_accessions", len(targets))
    return targets


def main() -> None:
    run_ts = stamp()
    backup_path = backup_database(label="before_p0_quality_hardening", quiet=True)
    conn = connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        ensure_logs(conn)
        outputs = {
            "unlinked_evidence_rejected": reject_unlinked_evidence(conn, run_ts),
            "host_scope_conflicts_fixed": fix_host_scope_conflicts(conn, run_ts),
            "excluded_public_hosts_hidden": hide_excluded_public_hosts(conn, run_ts),
            "bad_mortality_ranges_flagged": flag_bad_mortality_ranges(conn, run_ts),
            "duplicate_accessions_queued": queue_duplicate_accessions(conn, run_ts),
        }
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()

    out_dir = REPORTS_DIR / f"p0_quality_hardening_{run_ts}"
    out_dir.mkdir(parents=True, exist_ok=True)
    artifacts: dict[str, str] = {}
    for name, data in outputs.items():
        path = out_dir / f"{name}.csv"
        write_csv(path, data)
        artifacts[name] = str(path)
    summary = {
        "timestamp": run_ts,
        "backup_path": str(backup_path),
        "counts": {name: len(data) for name, data in outputs.items()},
        "artifacts": artifacts,
    }
    summary_path = out_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
