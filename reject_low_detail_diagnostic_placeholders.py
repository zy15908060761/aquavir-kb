#!/usr/bin/env python3
"""Reject low-detail diagnostic placeholder rows from early keyword mining."""

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
        backup_path = BACKUPS_DIR / f"crustacean_virus_core_before_reject_diag_placeholders_{ts}.db"
        shutil.copy2(db_path, backup_path)

    conn = connect(db_path)
    rows = [
        dict(r)
        for r in conn.execute(
            """
            SELECT dm.method_id, dm.virus_master_id, vm.canonical_name, dm.method_name,
                   dm.method_category, dm.method_subcategory, dm.reference_id,
                   dm.validation_context, dm.notes
            FROM diagnostic_methods dm
            LEFT JOIN virus_master vm ON vm.master_id = dm.virus_master_id
            WHERE dm.data_quality='placeholder'
              AND dm.curation_status='needs_review'
            ORDER BY dm.virus_master_id, dm.method_name, dm.method_id
            """
        ).fetchall()
    ]
    if not args.dry_run:
        with conn:
            for row in rows:
                old_note = row.get("notes") or ""
                note = "Rejected by quality audit: low-detail keyword placeholder; use curated/candidate diagnostic evidence rows instead."
                new_note = old_note if note in old_note else f"{old_note}; {note}".strip("; ")
                conn.execute(
                    """
                    UPDATE diagnostic_methods
                    SET curation_status='rejected',
                        notes=?
                    WHERE method_id=?
                    """,
                    (new_note, row["method_id"]),
                )
    integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
    fk_count = len(conn.execute("PRAGMA foreign_key_check").fetchall())
    conn.close()

    csv_path = REPORTS_DIR / f"rejected_diagnostic_placeholders_{ts}.csv"
    write_csv(csv_path, rows)
    summary = {
        "timestamp": ts,
        "dry_run": args.dry_run,
        "backup_path": str(backup_path) if backup_path else None,
        "rejected_or_planned": len(rows),
        "integrity_check": integrity,
        "foreign_key_violations": fk_count,
        "artifact_csv": str(csv_path),
    }
    summary_path = REPORTS_DIR / f"reject_diagnostic_placeholders_{ts}.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
