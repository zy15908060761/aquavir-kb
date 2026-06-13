#!/usr/bin/env python3
"""
Apply low-risk quality fixes found by database_quality_report.py.

The script only changes curation status/queues. It does not delete records and
does not assert new biological facts without references.
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


def stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def backup_database(db_path: Path, ts: str) -> Path:
    BACKUPS_DIR.mkdir(exist_ok=True)
    dst = BACKUPS_DIR / f"crustacean_virus_core_before_quality_fixes_{ts}.db"
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


def ensure_vocab(conn: sqlite3.Connection) -> None:
    vocab = [
        (
            "diagnostic_data_quality",
            "candidate_unreferenced",
            "Method-level diagnostic row that may be correct but lacks row-level literature support; excluded from analysis views.",
        ),
        (
            "review_issue_type",
            "missing_reference",
            "Curation claim lacks a direct literature reference.",
        ),
        (
            "review_issue_type",
            "orphan_master",
            "Virus master has no linked isolate rows.",
        ),
    ]
    for category, term, description in vocab:
        exists = conn.execute(
            "SELECT 1 FROM curation_vocab_terms WHERE category=? AND term=?",
            (category, term),
        ).fetchone()
        if not exists:
            conn.execute(
                "INSERT INTO curation_vocab_terms(category, term, description, active) VALUES (?, ?, ?, 1)",
                (category, term, description),
            )


def demote_unreferenced_diagnostics(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    targets = rows(
        conn,
        """
        SELECT dm.method_id, dm.virus_master_id, vm.canonical_name, dm.method_name,
               dm.method_category, dm.method_subcategory, dm.evidence_strength,
               dm.curation_status, dm.data_quality, dm.notes
        FROM diagnostic_methods dm
        LEFT JOIN virus_master vm ON vm.master_id = dm.virus_master_id
        WHERE dm.data_quality = 'curated'
          AND dm.curation_status = 'manual_checked'
          AND dm.reference_id IS NULL
        ORDER BY dm.virus_master_id, dm.method_name
        """,
    )
    for item in targets:
        note = (item.get("notes") or "").strip()
        suffix = "Demoted on quality audit: row lacks method-level reference; keep for manual evidence review only."
        new_note = f"{note} {suffix}".strip() if suffix not in note else note
        conn.execute(
            """
            UPDATE diagnostic_methods
            SET data_quality = 'candidate_unreferenced',
                curation_status = 'needs_review',
                evidence_strength = CASE WHEN evidence_strength = 'high' THEN 'medium' ELSE evidence_strength END,
                notes = ?
            WHERE method_id = ?
            """,
            (new_note, item["method_id"]),
        )
        exists = conn.execute(
            """
            SELECT 1 FROM diagnostic_method_review_queue
            WHERE method_id = ? AND issue_type = 'missing_reference' AND status = 'open'
            """,
            (item["method_id"],),
        ).fetchone()
        if not exists:
            conn.execute(
                """
                INSERT INTO diagnostic_method_review_queue(method_id, issue_type, recommended_action, status)
                VALUES (?, 'missing_reference', 'Attach a method-level primary reference or keep excluded from analysis views.', 'open')
                """,
                (item["method_id"],),
            )
    return targets


def resolve_unclassified_reassignment_conflicts(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    targets = rows(
        conn,
        """
        SELECT cc.conflict_id, cc.isolate_id, vi.accession, vm.canonical_name,
               cc.value_a, cc.value_b, cc.notes
        FROM curation_conflicts cc
        JOIN viral_isolates vi ON vi.isolate_id = cc.isolate_id
        JOIN virus_master vm ON vm.master_id = vi.master_id
        JOIN virus_ictv_status vis ON vis.master_id = vm.master_id
        WHERE cc.status = 'open'
          AND cc.conflict_type = 'taxonomy_mismatch'
          AND cc.field_name = 'master_id'
          AND cc.source_b = 'rdrp_family_reassignment'
          AND vis.ictv_status = 'unclassified_not_expected'
        ORDER BY cc.conflict_id
        """,
    )
    for item in targets:
        note = (item.get("notes") or "").strip()
        suffix = "Resolved by quality audit: current master is accepted as an unclassified discovery/family-level reassignment; original WSSV normalization retained only as audit trail."
        new_note = f"{note}; {suffix}" if note and suffix not in note else (note or suffix)
        conn.execute(
            """
            UPDATE curation_conflicts
            SET status = 'resolved',
                resolved_at = CURRENT_TIMESTAMP,
                notes = ?
            WHERE conflict_id = ?
            """,
            (new_note, item["conflict_id"]),
        )
        conn.execute(
            """
            UPDATE curation_priority_queue
            SET queue_status = 'resolved',
                updated_at = CURRENT_TIMESTAMP,
                notes = COALESCE(notes || '; ', '') || 'Resolved by unclassified discovery/family-level reassignment audit.'
            WHERE conflict_id = ? AND queue_status = 'open'
            """,
            (item["conflict_id"],),
        )
    return targets


def queue_orphan_masters(conn: sqlite3.Connection) -> list[dict[str, Any]]:
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
    targets = rows(
        conn,
        """
        SELECT vm.master_id, vm.canonical_name, vm.abbreviations, vm.entry_type, vm.is_crustacean_virus
        FROM virus_master vm
        LEFT JOIN viral_isolates vi ON vi.master_id = vm.master_id
        WHERE vi.isolate_id IS NULL
        ORDER BY vm.master_id
        """,
    )
    for item in targets:
        severity = "high" if item["is_crustacean_virus"] else "medium"
        reason = "Virus master has no linked isolate records; keep out of completeness claims until linked, merged, or retired."
        conn.execute(
            """
            INSERT INTO virus_master_review_queue(master_id, canonical_name, issue_type, severity, reason, updated_at)
            VALUES (?, ?, 'orphan_master', ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(master_id) DO UPDATE SET
                canonical_name = excluded.canonical_name,
                issue_type = excluded.issue_type,
                severity = excluded.severity,
                reason = excluded.reason,
                updated_at = CURRENT_TIMESTAMP
            """,
            (item["master_id"], item["canonical_name"], severity, reason),
        )
    return targets


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

    before = {
        "manual_checked_curated_without_reference": conn.execute(
            "SELECT COUNT(*) FROM diagnostic_methods WHERE data_quality='curated' AND curation_status='manual_checked' AND reference_id IS NULL"
        ).fetchone()[0],
        "open_conflicts": conn.execute("SELECT COUNT(*) FROM curation_conflicts WHERE status='open'").fetchone()[0],
        "open_priority_queue": conn.execute("SELECT COUNT(*) FROM curation_priority_queue WHERE queue_status='open'").fetchone()[0],
    }

    if args.dry_run:
        demoted = rows(
            conn,
            """
            SELECT dm.method_id, dm.virus_master_id, vm.canonical_name, dm.method_name
            FROM diagnostic_methods dm LEFT JOIN virus_master vm ON vm.master_id=dm.virus_master_id
            WHERE dm.data_quality='curated' AND dm.curation_status='manual_checked' AND dm.reference_id IS NULL
            """,
        )
        resolved = rows(
            conn,
            """
            SELECT cc.conflict_id, cc.isolate_id, vi.accession, vm.canonical_name
            FROM curation_conflicts cc
            JOIN viral_isolates vi ON vi.isolate_id=cc.isolate_id
            JOIN virus_master vm ON vm.master_id=vi.master_id
            JOIN virus_ictv_status vis ON vis.master_id=vm.master_id
            WHERE cc.status='open' AND cc.conflict_type='taxonomy_mismatch'
              AND cc.field_name='master_id' AND cc.source_b='rdrp_family_reassignment'
              AND vis.ictv_status='unclassified_not_expected'
            """,
        )
        orphaned = rows(
            conn,
            """
            SELECT vm.master_id, vm.canonical_name, vm.entry_type
            FROM virus_master vm LEFT JOIN viral_isolates vi ON vi.master_id=vm.master_id
            WHERE vi.isolate_id IS NULL
            """,
        )
    else:
        with conn:
            ensure_vocab(conn)
            demoted = demote_unreferenced_diagnostics(conn)
            resolved = resolve_unclassified_reassignment_conflicts(conn)
            orphaned = queue_orphan_masters(conn)

    after = {
        "manual_checked_curated_without_reference": conn.execute(
            "SELECT COUNT(*) FROM diagnostic_methods WHERE data_quality='curated' AND curation_status='manual_checked' AND reference_id IS NULL"
        ).fetchone()[0],
        "open_conflicts": conn.execute("SELECT COUNT(*) FROM curation_conflicts WHERE status='open'").fetchone()[0],
        "open_priority_queue": conn.execute("SELECT COUNT(*) FROM curation_priority_queue WHERE queue_status='open'").fetchone()[0],
        "integrity_check": conn.execute("PRAGMA integrity_check").fetchone()[0],
        "foreign_key_violations": len(conn.execute("PRAGMA foreign_key_check").fetchall()),
    }
    conn.close()

    demoted_csv = REPORTS_DIR / f"quality_fix_demoted_diagnostics_{ts}.csv"
    conflicts_csv = REPORTS_DIR / f"quality_fix_resolved_conflicts_{ts}.csv"
    orphans_csv = REPORTS_DIR / f"quality_fix_orphan_masters_{ts}.csv"
    write_csv(demoted_csv, demoted)
    write_csv(conflicts_csv, resolved)
    write_csv(orphans_csv, orphaned)

    summary = {
        "timestamp": ts,
        "dry_run": args.dry_run,
        "backup_path": str(backup_path) if backup_path else None,
        "before": before,
        "after": after,
        "demoted_unreferenced_diagnostics": len(demoted),
        "resolved_unclassified_reassignment_conflicts": len(resolved),
        "queued_orphan_masters": len(orphaned),
        "artifacts": {
            "demoted_diagnostics_csv": str(demoted_csv),
            "resolved_conflicts_csv": str(conflicts_csv),
            "orphan_masters_csv": str(orphans_csv),
        },
    }
    summary_path = REPORTS_DIR / f"quality_fixes_{ts}.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
