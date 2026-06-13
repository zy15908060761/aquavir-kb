#!/usr/bin/env python3
"""Triage auto-extracted evidence records without pretending they are reviewed."""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path


DB_PATH = Path("crustacean_virus_core.db")
REPORTS_DIR = Path("reports")
BACKUPS_DIR = Path("backups")
CORE_ABBREVIATIONS = {"WSSV", "YHV", "TSV", "IHHNV", "IMNV", "MrNV", "CMNV", "LSNV", "DIV1"}


def stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def priority(row: dict) -> tuple[str, int, str]:
    etype = row["evidence_type"]
    abbrs = set(filter(None, (row.get("abbreviations") or "").replace(";", ",").split(",")))
    if etype in {"virulence", "mortality", "diagnosis"} and (abbrs & CORE_ABBREVIATIONS):
        return "critical", 100, "Core disease-virus evidence affecting major claims."
    if etype in {"virulence", "mortality", "diagnosis"}:
        return "high", 80, "Disease-relevant evidence type."
    if etype in {"temperature", "host_range"}:
        return "medium", 50, "Useful metadata evidence but not primary pathogenicity claim."
    return "low", 20, "Lower-priority contextual evidence."


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=str(DB_PATH))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    ts = stamp()
    db_path = Path(args.db)
    REPORTS_DIR.mkdir(exist_ok=True)
    backup_path = None
    if not args.dry_run:
        BACKUPS_DIR.mkdir(exist_ok=True)
        backup_path = BACKUPS_DIR / f"crustacean_virus_core_before_evidence_triage_{ts}.db"
        shutil.copy2(db_path, backup_path)

    conn = connect(db_path)
    no_ref = [
        dict(r)
        for r in conn.execute(
            """
            SELECT er.evidence_id, er.evidence_type, er.virus_master_id, vm.canonical_name,
                   vm.abbreviations, er.claim, er.context
            FROM evidence_records er
            LEFT JOIN virus_master vm ON vm.master_id = er.virus_master_id
            WHERE er.curation_status='needs_review'
              AND er.reference_id IS NULL
            ORDER BY er.evidence_type, er.evidence_id
            """
        ).fetchall()
    ]
    review_rows = [
        dict(r)
        for r in conn.execute(
            """
            SELECT er.evidence_id, er.evidence_type, er.virus_master_id, vm.canonical_name,
                   vm.abbreviations, er.reference_id, er.claim, er.evidence_strength
            FROM evidence_records er
            LEFT JOIN virus_master vm ON vm.master_id = er.virus_master_id
            WHERE er.curation_status='needs_review'
              AND er.reference_id IS NOT NULL
            ORDER BY er.evidence_type, er.evidence_id
            """
        ).fetchall()
    ]
    queue_rows = []
    for row in review_rows:
        band, score, reason = priority(row)
        queue_rows.append({**row, "priority": band, "priority_score": score, "reason": reason})

    if not args.dry_run:
        with conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS evidence_review_priority_queue (
                    queue_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    evidence_id INTEGER NOT NULL UNIQUE,
                    evidence_type TEXT NOT NULL,
                    virus_master_id INTEGER,
                    canonical_name TEXT,
                    priority TEXT NOT NULL,
                    priority_score INTEGER NOT NULL,
                    reason TEXT NOT NULL,
                    queue_status TEXT NOT NULL DEFAULT 'open',
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (evidence_id) REFERENCES evidence_records(evidence_id),
                    FOREIGN KEY (virus_master_id) REFERENCES virus_master(master_id)
                )
                """
            )
            for row in no_ref:
                conn.execute(
                    """
                    UPDATE evidence_records
                    SET curation_status='rejected',
                        notes=COALESCE(notes || '; ', '') || 'Rejected by quality audit: no reference_id attached.',
                        updated_at=CURRENT_TIMESTAMP
                    WHERE evidence_id=?
                    """,
                    (row["evidence_id"],),
                )
            conn.execute("DELETE FROM evidence_review_priority_queue")
            for row in queue_rows:
                conn.execute(
                    """
                    INSERT INTO evidence_review_priority_queue(
                        evidence_id, evidence_type, virus_master_id, canonical_name,
                        priority, priority_score, reason, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    """,
                    (
                        row["evidence_id"],
                        row["evidence_type"],
                        row["virus_master_id"],
                        row["canonical_name"],
                        row["priority"],
                        row["priority_score"],
                        row["reason"],
                    ),
                )
    remaining_needs_review = conn.execute("SELECT COUNT(*) FROM evidence_records WHERE curation_status='needs_review'").fetchone()[0]
    integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
    fk_count = len(conn.execute("PRAGMA foreign_key_check").fetchall())
    conn.close()

    no_ref_csv = REPORTS_DIR / f"evidence_rejected_no_reference_{ts}.csv"
    queue_csv = REPORTS_DIR / f"evidence_review_priority_queue_{ts}.csv"
    write_csv(no_ref_csv, no_ref)
    write_csv(queue_csv, queue_rows)
    summary = {
        "timestamp": ts,
        "dry_run": args.dry_run,
        "backup_path": str(backup_path) if backup_path else None,
        "rejected_no_reference": len(no_ref),
        "queued_for_review": len(queue_rows),
        "remaining_needs_review": remaining_needs_review,
        "integrity_check": integrity,
        "foreign_key_violations": fk_count,
        "artifacts": {"no_ref_csv": str(no_ref_csv), "queue_csv": str(queue_csv)},
    }
    summary_path = REPORTS_DIR / f"evidence_triage_{ts}.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
