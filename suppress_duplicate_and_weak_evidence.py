#!/usr/bin/env python3
"""Suppress duplicate evidence and create clean evidence views.

Non-destructive policy:
- keep one canonical evidence row per exact duplicate group;
- record non-canonical rows in suppression tables;
- record abstract-mention rows in weak-evidence isolation tables;
- expose clean/public analysis views that exclude suppressed and weak rows.
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


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS evidence_duplicate_suppression_log (
            log_id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_ts TEXT NOT NULL,
            duplicate_key TEXT NOT NULL,
            canonical_evidence_id INTEGER NOT NULL,
            suppressed_evidence_id INTEGER NOT NULL,
            original_status TEXT,
            original_strength TEXT,
            status TEXT NOT NULL DEFAULT 'active',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(run_ts, suppressed_evidence_id),
            FOREIGN KEY(canonical_evidence_id) REFERENCES evidence_records(evidence_id),
            FOREIGN KEY(suppressed_evidence_id) REFERENCES evidence_records(evidence_id)
        );

        CREATE TABLE IF NOT EXISTS weak_evidence_isolation_log (
            log_id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_ts TEXT NOT NULL,
            evidence_id INTEGER NOT NULL,
            original_status TEXT,
            reason TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(run_ts, evidence_id),
            FOREIGN KEY(evidence_id) REFERENCES evidence_records(evidence_id)
        );
        """
    )
    for table in ["evidence_duplicate_suppression_log", "weak_evidence_isolation_log"]:
        cols = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
        if "status" not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN status TEXT NOT NULL DEFAULT 'active'")


def duplicate_groups(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    return rows(
        conn,
        """
        WITH keyed AS (
            SELECT evidence_id,
                   COALESCE(evidence_type, '') || '|' ||
                   COALESCE(virus_master_id, '') || '|' ||
                   COALESCE(host_id, '') || '|' ||
                   COALESCE(isolate_id, '') || '|' ||
                   COALESCE(reference_id, '') || '|' ||
                   lower(trim(COALESCE(claim, ''))) || '|' ||
                   lower(trim(COALESCE(value_text, ''))) || '|' ||
                   COALESCE(unit, '') AS duplicate_key,
                   curation_status,
                   evidence_strength,
                   CASE
                       WHEN curation_status = 'manual_checked' THEN 0
                       WHEN curation_status = 'needs_review' THEN 1
                       WHEN curation_status = 'auto_imported' THEN 2
                       ELSE 3
                   END AS status_rank,
                   CASE
                       WHEN evidence_strength = 'high' THEN 0
                       WHEN evidence_strength = 'medium' THEN 1
                       WHEN evidence_strength = 'low' THEN 2
                       ELSE 3
                   END AS strength_rank
            FROM evidence_records
            WHERE COALESCE(curation_status, '') <> 'rejected'
              AND evidence_id NOT IN (
                  SELECT suppressed_evidence_id
                  FROM evidence_duplicate_suppression_log
                  WHERE status = 'active'
              )
              AND evidence_id NOT IN (
                  SELECT evidence_id
                  FROM weak_evidence_isolation_log
                  WHERE status = 'active'
              )
        ),
        dup AS (
            SELECT duplicate_key, COUNT(*) AS n
            FROM keyed
            GROUP BY duplicate_key
            HAVING COUNT(*) > 1
        ),
        ranked AS (
            SELECT k.*,
                   ROW_NUMBER() OVER (
                       PARTITION BY k.duplicate_key
                       ORDER BY k.status_rank, k.strength_rank, k.evidence_id
                   ) AS rn
            FROM keyed k
            JOIN dup d ON d.duplicate_key = k.duplicate_key
        )
        SELECT duplicate_key,
               MIN(CASE WHEN rn = 1 THEN evidence_id END) AS canonical_evidence_id,
               group_concat(CASE WHEN rn > 1 THEN evidence_id END) AS suppress_ids,
               COUNT(*) AS group_size
        FROM ranked
        GROUP BY duplicate_key
        ORDER BY group_size DESC, canonical_evidence_id
        """,
    )


def suppress_duplicates(conn: sqlite3.Connection, run_ts: str) -> list[dict[str, Any]]:
    groups = duplicate_groups(conn)
    suppressed_rows: list[dict[str, Any]] = []
    note = "Suppressed by duplicate evidence cleanup; canonical evidence_id={canonical}."
    for group in groups:
        suppress_ids = [int(x) for x in str(group.get("suppress_ids") or "").split(",") if x]
        canonical = int(group["canonical_evidence_id"])
        for evidence_id in suppress_ids:
            row = conn.execute(
                "SELECT evidence_id, curation_status, evidence_strength, notes FROM evidence_records WHERE evidence_id=?",
                (evidence_id,),
            ).fetchone()
            if row is None:
                continue
            conn.execute(
                """
                INSERT OR IGNORE INTO evidence_duplicate_suppression_log(
                    run_ts, duplicate_key, canonical_evidence_id, suppressed_evidence_id,
                    original_status, original_strength
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    run_ts,
                    group["duplicate_key"],
                    canonical,
                    evidence_id,
                    row["curation_status"],
                    row["evidence_strength"],
                ),
            )
            suppressed_rows.append(
                {
                    "duplicate_key": group["duplicate_key"],
                    "canonical_evidence_id": canonical,
                    "suppressed_evidence_id": evidence_id,
                    "original_status": row["curation_status"],
                    "original_strength": row["evidence_strength"],
                }
            )
    return suppressed_rows


def isolate_abstract_mention(conn: sqlite3.Connection, run_ts: str) -> list[dict[str, Any]]:
    targets = rows(
        conn,
        """
        SELECT evidence_id, curation_status, evidence_strength, notes
        FROM evidence_records
        WHERE (claim LIKE 'Abstract mentions %' OR claim LIKE 'Auto-extracted from abstract:%')
          AND COALESCE(curation_status, '') <> 'rejected'
          AND evidence_id NOT IN (
              SELECT evidence_id
              FROM weak_evidence_isolation_log
              WHERE status = 'active'
          )
        ORDER BY evidence_id
        """,
    )
    reason = "Abstract-mention evidence isolated from clean/public analysis views until fulltext sentence review confirms a specific claim."
    for item in targets:
        conn.execute(
            """
            INSERT OR IGNORE INTO weak_evidence_isolation_log(run_ts, evidence_id, original_status, reason)
            VALUES (?, ?, ?, ?)
            """,
            (run_ts, item["evidence_id"], item["curation_status"], reason),
        )
    return targets


def create_views(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        DROP VIEW IF EXISTS v_evidence_clean;
        CREATE VIEW v_evidence_clean AS
        SELECT er.*
        FROM evidence_records er
        WHERE COALESCE(er.curation_status, '') <> 'rejected'
          AND er.evidence_id NOT IN (
              SELECT suppressed_evidence_id
              FROM evidence_duplicate_suppression_log
              WHERE status = 'active'
          )
          AND er.evidence_id NOT IN (
              SELECT evidence_id
              FROM weak_evidence_isolation_log
              WHERE status = 'active'
          )
          AND er.virus_master_id IS NOT NULL
          AND er.reference_id IS NOT NULL;

        DROP VIEW IF EXISTS v_evidence_public_analysis;
        CREATE VIEW v_evidence_public_analysis AS
        SELECT er.*
        FROM v_evidence_clean er
        WHERE COALESCE(er.evidence_strength, '') IN ('high', 'medium')
          AND COALESCE(er.curation_status, '') IN ('manual_checked', 'auto_imported', 'needs_review')
          AND NOT (er.evidence_type = 'host_range' AND er.host_id IS NULL);

        DROP VIEW IF EXISTS v_evidence_excluded_from_analysis;
        CREATE VIEW v_evidence_excluded_from_analysis AS
        SELECT er.*,
               CASE
                   WHEN er.curation_status = 'rejected' THEN 'rejected'
                   WHEN er.evidence_id IN (
                       SELECT suppressed_evidence_id
                       FROM evidence_duplicate_suppression_log
                       WHERE status = 'active'
                   ) THEN 'duplicate_suppressed'
                   WHEN er.evidence_id IN (
                       SELECT evidence_id
                       FROM weak_evidence_isolation_log
                       WHERE status = 'active'
                   ) THEN 'weak_abstract_mention'
                   WHEN er.virus_master_id IS NULL THEN 'missing_virus'
                   WHEN er.reference_id IS NULL THEN 'missing_reference'
                   WHEN er.evidence_type = 'host_range' AND er.host_id IS NULL THEN 'host_range_missing_host'
                   ELSE 'other_exclusion'
               END AS exclusion_reason
        FROM evidence_records er
        WHERE er.evidence_id NOT IN (SELECT evidence_id FROM v_evidence_public_analysis);
        """
    )


def export_report(
    run_ts: str,
    suppressed: list[dict[str, Any]],
    weak: list[dict[str, Any]],
    conn: sqlite3.Connection,
) -> dict[str, str]:
    out_dir = REPORTS_DIR / f"evidence_suppression_{run_ts}"
    out_dir.mkdir(parents=True, exist_ok=True)
    artifacts = {
        "suppressed_duplicates_csv": str(out_dir / "suppressed_duplicates.csv"),
        "weak_abstract_mentions_csv": str(out_dir / "weak_abstract_mentions.csv"),
        "summary_json": str(out_dir / "summary.json"),
        "report_md": str(out_dir / "report.md"),
    }
    write_csv(Path(artifacts["suppressed_duplicates_csv"]), suppressed)
    write_csv(Path(artifacts["weak_abstract_mentions_csv"]), weak)

    status_counts = rows(
        conn,
        """
        SELECT curation_status, COUNT(*) AS n
        FROM evidence_records
        GROUP BY curation_status
        ORDER BY n DESC
        """,
    )
    view_counts = {
        "evidence_records": conn.execute("SELECT COUNT(*) FROM evidence_records").fetchone()[0],
        "v_evidence_clean": conn.execute("SELECT COUNT(*) FROM v_evidence_clean").fetchone()[0],
        "v_evidence_public_analysis": conn.execute("SELECT COUNT(*) FROM v_evidence_public_analysis").fetchone()[0],
        "v_evidence_excluded_from_analysis": conn.execute("SELECT COUNT(*) FROM v_evidence_excluded_from_analysis").fetchone()[0],
    }
    duplicate_groups_after = conn.execute(
        """
        SELECT COUNT(*) FROM (
            SELECT COALESCE(evidence_type, '') || '|' ||
                   COALESCE(virus_master_id, '') || '|' ||
                   COALESCE(host_id, '') || '|' ||
                   COALESCE(isolate_id, '') || '|' ||
                   COALESCE(reference_id, '') || '|' ||
                   lower(trim(COALESCE(claim, ''))) || '|' ||
                   lower(trim(COALESCE(value_text, ''))) || '|' ||
                   COALESCE(unit, '') AS duplicate_key,
                   COUNT(*) AS n
            FROM evidence_records
            WHERE COALESCE(curation_status, '') <> 'rejected'
              AND evidence_id NOT IN (
                  SELECT suppressed_evidence_id
                  FROM evidence_duplicate_suppression_log
                  WHERE status = 'active'
              )
              AND evidence_id NOT IN (
                  SELECT evidence_id
                  FROM weak_evidence_isolation_log
                  WHERE status = 'active'
              )
            GROUP BY duplicate_key
            HAVING COUNT(*) > 1
        )
        """
    ).fetchone()[0]
    summary = {
        "timestamp": run_ts,
        "suppressed_duplicate_rows": len(suppressed),
        "weak_abstract_mentions_isolated": len(weak),
        "duplicate_groups_after": duplicate_groups_after,
        "view_counts": view_counts,
        "status_counts": status_counts,
        "artifacts": artifacts,
    }
    Path(artifacts["summary_json"]).write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [
        "# Evidence Suppression Report",
        "",
        f"- Suppressed duplicate rows: `{len(suppressed)}`",
        f"- Weak abstract mentions isolated: `{len(weak)}`",
        f"- Active duplicate groups after cleanup: `{duplicate_groups_after}`",
        "",
        "## View Counts",
        "",
    ]
    for key, value in view_counts.items():
        lines.append(f"- `{key}`: {value}")
    lines.extend(["", "## Artifacts", ""])
    for key, value in artifacts.items():
        lines.append(f"- {key}: `{value}`")
    Path(artifacts["report_md"]).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return artifacts


def main() -> None:
    run_ts = stamp()
    backup_path = backup_database(label="before_evidence_suppression", quiet=True)
    conn = connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        ensure_schema(conn)
        suppressed = suppress_duplicates(conn, run_ts)
        weak = isolate_abstract_mention(conn, run_ts)
        create_views(conn)
        artifacts = export_report(run_ts, suppressed, weak, conn)
        conn.commit()
        print(json.dumps({
            "timestamp": run_ts,
            "backup_path": str(backup_path),
            "suppressed_duplicate_rows": len(suppressed),
            "weak_abstract_mentions_isolated": len(weak),
            "integrity_check": conn.execute("PRAGMA integrity_check").fetchone()[0],
            "foreign_key_violations": len(conn.execute("PRAGMA foreign_key_check").fetchall()),
            "artifacts": artifacts,
        }, ensure_ascii=False, indent=2))
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
