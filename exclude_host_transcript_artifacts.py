#!/usr/bin/env python3
"""
Exclude obvious host transcript/genome artifacts from target virus analyses.

NCBI XM_/XR_/NM_/NR_ accessions are model/refseq transcript records, not viral
isolate genomes. This script marks such rows as non-target at the curated
profile layer and retires master records that consist only of these artifacts.
"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any


DB_PATH = Path("crustacean_virus_core.db")
REPORTS_DIR = Path("reports")
BACKUPS_DIR = Path("backups")
TRANSCRIPT_PREFIXES = ("XM_", "XR_", "NM_", "NR_")


def stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def backup_database(db_path: Path, ts: str) -> Path:
    BACKUPS_DIR.mkdir(exist_ok=True)
    dst = BACKUPS_DIR / f"crustacean_virus_core_before_host_transcript_exclusion_{ts}.db"
    shutil.copy2(db_path, dst)
    return dst


def rows(conn: sqlite3.Connection, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def write_csv(path: Path, data: list[dict[str, Any]]) -> None:
    path.parent.mkdir(exist_ok=True)
    if not data:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(data[0].keys()))
        writer.writeheader()
        writer.writerows(data)


def transcript_where(alias: str = "vi") -> str:
    return " OR ".join(f"{alias}.accession LIKE '{prefix}%'" for prefix in TRANSCRIPT_PREFIXES)


def candidate_isolates(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    return rows(
        conn,
        f"""
        SELECT vi.isolate_id, vi.accession, vi.virus_name, vi.master_id,
               vm.canonical_name, vm.entry_type, vm.is_crustacean_virus,
               icp.profile_id, icp.host_is_target, icp.dataset_tier, icp.curation_status
        FROM viral_isolates vi
        LEFT JOIN virus_master vm ON vm.master_id = vi.master_id
        LEFT JOIN isolate_curated_profiles icp ON icp.isolate_id = vi.isolate_id
        WHERE ({transcript_where('vi')})
          AND COALESCE(icp.host_is_target, 1) != 0
        ORDER BY vi.accession
        """,
    )


def master_artifact_candidates(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    return rows(
        conn,
        f"""
        SELECT vm.master_id, vm.canonical_name, vm.entry_type, vm.is_crustacean_virus,
               COUNT(vi.isolate_id) AS isolate_count,
               SUM(CASE WHEN {transcript_where('vi')} THEN 1 ELSE 0 END) AS transcript_count
        FROM virus_master vm
        JOIN viral_isolates vi ON vi.master_id = vm.master_id
        GROUP BY vm.master_id
        HAVING isolate_count = transcript_count
           AND isolate_count > 0
           AND (
                LOWER(vm.canonical_name) IN ('portunus trituberculatus', 'procambarus clarkii')
                OR LOWER(vm.canonical_name) LIKE 'predicted:%'
                OR LOWER(vm.canonical_name) LIKE '% uncharacterized protein%'
           )
        ORDER BY vm.master_id
        """,
    )


def ensure_review_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS virus_master_review_queue (
            master_id INTEGER PRIMARY KEY,
            canonical_name TEXT NOT NULL,
            issue_type TEXT NOT NULL,
            severity TEXT NOT NULL,
            reason TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (master_id) REFERENCES virus_master(master_id)
        )
        """
    )


def upsert_profile_exclusion(conn: sqlite3.Connection, item: dict[str, Any]) -> None:
    note = "Excluded by quality audit: RefSeq transcript accession prefix indicates host transcript/model RNA, not a viral isolate genome."
    if item["profile_id"] is None:
        conn.execute(
            """
            INSERT INTO isolate_curated_profiles (
                isolate_id, accession, master_id, canonical_virus_name, raw_virus_name,
                host_is_target, metadata_source_priority, curation_status, confidence,
                dataset_tier, notes, updated_at
            ) VALUES (?, ?, ?, ?, ?, 0, 'manual_curated', 'manual_checked', 'high',
                      'host_genome_artifact', ?, CURRENT_TIMESTAMP)
            """,
            (
                item["isolate_id"],
                item["accession"],
                item["master_id"],
                item["canonical_name"],
                item["virus_name"],
                note,
            ),
        )
    else:
        old_note = rows(conn, "SELECT notes FROM isolate_curated_profiles WHERE profile_id=?", (item["profile_id"],))[0].get("notes") or ""
        new_note = old_note if note in old_note else f"{old_note}; {note}".strip("; ")
        conn.execute(
            """
            UPDATE isolate_curated_profiles
            SET host_is_target = 0,
                metadata_source_priority = 'manual_curated',
                curation_status = 'manual_checked',
                confidence = 'high',
                dataset_tier = 'host_genome_artifact',
                notes = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE profile_id = ?
            """,
            (new_note, item["profile_id"]),
        )


def retire_master(conn: sqlite3.Connection, item: dict[str, Any]) -> None:
    note = "Retired from target scope by quality audit: all linked accessions are host transcript/model RNA records."
    conn.execute(
        """
        UPDATE virus_master
        SET is_crustacean_virus = 0,
            entry_type = 'host_genome',
            notes = CASE
                WHEN notes IS NULL OR TRIM(notes) = '' THEN ?
                WHEN notes LIKE '%' || ? || '%' THEN notes
                ELSE notes || '; ' || ?
            END
        WHERE master_id = ?
        """,
        (note, note, note, item["master_id"]),
    )
    conn.execute(
        """
        UPDATE virus_ictv_status
        SET ictv_status = 'non_target',
            mapping_count = 0,
            best_confidence = NULL,
            reason = 'Host transcript/model RNA artifact; excluded from virus target scope.',
            updated_at = CURRENT_TIMESTAMP
        WHERE master_id = ?
        """,
        (item["master_id"],),
    )
    conn.execute("DELETE FROM ictv_review_priority_queue WHERE master_id = ?", (item["master_id"],))
    conn.execute(
        """
        INSERT INTO virus_master_review_queue(master_id, canonical_name, issue_type, severity, reason, updated_at)
        VALUES (?, ?, 'host_genome_artifact', 'medium', ?, CURRENT_TIMESTAMP)
        ON CONFLICT(master_id) DO UPDATE SET
            canonical_name = excluded.canonical_name,
            issue_type = excluded.issue_type,
            severity = excluded.severity,
            reason = excluded.reason,
            updated_at = CURRENT_TIMESTAMP
        """,
        (item["master_id"], item["canonical_name"], note),
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=str(DB_PATH))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    ts = stamp()
    db_path = Path(args.db)
    REPORTS_DIR.mkdir(exist_ok=True)
    backup_path = None if args.dry_run else backup_database(db_path, ts)
    conn = connect(db_path)

    before_target = conn.execute("SELECT COUNT(*) FROM analysis_target_isolates").fetchone()[0]
    isolates = candidate_isolates(conn)
    masters = master_artifact_candidates(conn)

    if not args.dry_run:
        with conn:
            ensure_review_table(conn)
            for item in isolates:
                upsert_profile_exclusion(conn, item)
            for item in masters:
                retire_master(conn, item)

    after_target = conn.execute("SELECT COUNT(*) FROM analysis_target_isolates").fetchone()[0]
    integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
    fk_count = len(conn.execute("PRAGMA foreign_key_check").fetchall())
    conn.close()

    isolates_csv = REPORTS_DIR / f"host_transcript_artifact_isolates_{ts}.csv"
    masters_csv = REPORTS_DIR / f"host_transcript_artifact_masters_{ts}.csv"
    write_csv(isolates_csv, isolates)
    write_csv(masters_csv, masters)

    summary = {
        "timestamp": ts,
        "dry_run": args.dry_run,
        "backup_path": str(backup_path) if backup_path else None,
        "candidate_isolates_excluded": len(isolates),
        "master_records_retired": len(masters),
        "analysis_target_isolates_before": before_target,
        "analysis_target_isolates_after": after_target,
        "integrity_check": integrity,
        "foreign_key_violations": fk_count,
        "artifacts": {
            "isolates_csv": str(isolates_csv),
            "masters_csv": str(masters_csv),
        },
    }
    summary_path = REPORTS_DIR / f"host_transcript_artifact_exclusion_{ts}.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
