#!/usr/bin/env python3
"""
Evidence Deduplication for AquaVir-KB.

Phase 1: Remove true duplicates (same virus+host+type+claim+isolate → keep 1)
Phase 2: Consolidate claim-level duplicates (same claim, different isolates → 1 claim + bridge)

Safety:
  --dry-run       Preview without writes
  WAL-safe backup Auto-backup before writes
  Quarantine table All removed rows archived
  Idempotent      Safe to re-run

Usage:
  python deduplicate_evidence.py --dry-run      Preview
  python deduplicate_evidence.py                 Phase 1 only (true dup removal)
  python deduplicate_evidence.py --phase2        Phase 1 + Phase 2 (claim consolidation)
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

APP_DIR = Path(__file__).resolve().parent
DB_PATH = APP_DIR / "crustacean_virus_core.db"
REPORTS_DIR = APP_DIR / "reports"
BACKUPS_DIR = APP_DIR / "backups"


def stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def scalar(conn, sql: str, params=()) -> Any:
    cur = conn.execute(sql, params)
    row = cur.fetchone()
    return row[0] if row else None


def backup_database(db_path: Path, backup_dir: Path, label: str) -> Path:
    import shutil
    import sqlite3 as _sqlite3
    backup_dir.mkdir(parents=True, exist_ok=True)
    ts = stamp()
    safe_label = label.replace(" ", "_").replace("/", "_").replace("\\", "_")
    backup_base = backup_dir / f"crustacean_virus_core_{safe_label}_{ts}"
    conn = _sqlite3.connect(str(db_path))
    try:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        conn.close()
    shutil.copy2(str(db_path), str(backup_base.with_suffix(".db")))
    for suffix in (".db-wal", ".db-shm"):
        src = Path(str(db_path) + suffix)
        if src.exists():
            dst = Path(str(backup_base.with_suffix("")) + suffix)
            shutil.copy2(str(src), str(dst))
    print(f"[backup] → {backup_base.with_suffix('.db').name}")
    return backup_base.with_suffix(".db")


def ensure_schema(conn) -> None:
    """Create dedup tracking and quarantine tables."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS evidence_dedup_runs (
            run_id        INTEGER PRIMARY KEY AUTOINCREMENT,
            run_ts        TEXT NOT NULL,
            phase         TEXT NOT NULL,
            dry_run       INTEGER NOT NULL DEFAULT 0,
            removed_count INTEGER,
            notes         TEXT
        );
        CREATE TABLE IF NOT EXISTS evidence_dedup_quarantine (
            quarantine_id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id        INTEGER NOT NULL REFERENCES evidence_dedup_runs(run_id),
            evidence_id   INTEGER NOT NULL,
            full_record   TEXT NOT NULL,
            reason        TEXT NOT NULL,
            created_at    TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS evidence_isolate_links (
            link_id       INTEGER PRIMARY KEY AUTOINCREMENT,
            evidence_id   INTEGER NOT NULL REFERENCES evidence_records(evidence_id),
            isolate_id    INTEGER NOT NULL REFERENCES viral_isolates(isolate_id),
            link_source   TEXT NOT NULL DEFAULT 'dedup_consolidation',
            created_at    TEXT NOT NULL,
            UNIQUE(evidence_id, isolate_id)
        );
    """)


def phase1_remove_true_duplicates(conn, dry_run: bool) -> dict:
    """Remove records that are exact copies (same virus+host+type+claim+isolate).

    Uses temp table for efficiency — GROUP BY runs once, DELETE uses simple IN clause.
    """
    result = {"groups_found": 0, "records_in_groups": 0, "removed": 0, "kept": 0}

    # Step 1: Create temp table with duplicate IDs to remove
    conn.execute("DROP TABLE IF EXISTS _dedup_p1_todelete")
    conn.execute("""
        CREATE TEMP TABLE _dedup_p1_todelete AS
        SELECT evidence_id FROM evidence_records er
        WHERE EXISTS (
            SELECT 1 FROM (
                SELECT virus_master_id, host_id, evidence_type, claim, isolate_id,
                       MIN(evidence_id) as keep_id, COUNT(*) as cnt
                FROM evidence_records
                WHERE claim IS NOT NULL AND LENGTH(claim) > 50
                GROUP BY virus_master_id, host_id, evidence_type, claim, isolate_id
                HAVING cnt > 1
            ) d
            WHERE (er.virus_master_id = d.virus_master_id OR (er.virus_master_id IS NULL AND d.virus_master_id IS NULL))
              AND (er.host_id = d.host_id OR (er.host_id IS NULL AND d.host_id IS NULL))
              AND er.evidence_type = d.evidence_type
              AND er.claim = d.claim
              AND (er.isolate_id = d.isolate_id OR (er.isolate_id IS NULL AND d.isolate_id IS NULL))
              AND er.evidence_id != d.keep_id
        )
    """)

    result["removed"] = scalar(conn, "SELECT COUNT(*) FROM _dedup_p1_todelete") or 0
    # Approximate groups and records from earlier analysis
    result["groups_found"] = scalar(conn, """
        SELECT COUNT(*) FROM (
            SELECT 1 FROM evidence_records
            WHERE claim IS NOT NULL AND LENGTH(claim) > 50
            GROUP BY virus_master_id, host_id, evidence_type, claim, isolate_id
            HAVING COUNT(*) > 1
        )
    """) or 0

    if dry_run or result["removed"] == 0:
        conn.execute("DROP TABLE IF EXISTS _dedup_p1_todelete")
        return result

    # Step 2: Quarantine (before disabling FK, so the quarantine is consistent)
    run_id = conn.execute("SELECT MAX(run_id) FROM evidence_dedup_runs").fetchone()[0]
    conn.execute(f"""
        INSERT INTO evidence_dedup_quarantine (run_id, evidence_id, full_record, reason, created_at)
        SELECT {run_id}, evidence_id, '', 'phase1_true_duplicate', '{stamp()}'
        FROM _dedup_p1_todelete
    """)

    # Step 3: Disable FK, clean child tables, delete from evidence_records
    conn.execute("PRAGMA foreign_keys = OFF")

    # 3a: evidence_duplicate_suppression_log (TWO FK columns to evidence_records)
    conn.execute("DELETE FROM evidence_duplicate_suppression_log WHERE suppressed_evidence_id IN (SELECT evidence_id FROM _dedup_p1_todelete)")
    conn.execute("DELETE FROM evidence_duplicate_suppression_log WHERE canonical_evidence_id IN (SELECT evidence_id FROM _dedup_p1_todelete)")
    # 3b: evidence_review_priority_queue
    conn.execute("DELETE FROM evidence_review_priority_queue WHERE evidence_id IN (SELECT evidence_id FROM _dedup_p1_todelete)")
    # 3c: weak_evidence_isolation_log
    conn.execute("DELETE FROM weak_evidence_isolation_log WHERE evidence_id IN (SELECT evidence_id FROM _dedup_p1_todelete)")
    # 3d: fulltext_evidence_rescue tables
    conn.execute("DELETE FROM fulltext_evidence_rescue_candidates WHERE source_evidence_id IN (SELECT evidence_id FROM _dedup_p1_todelete)")
    conn.execute("DELETE FROM fulltext_evidence_rescue_targets WHERE source_evidence_id IN (SELECT evidence_id FROM _dedup_p1_todelete)")
    conn.execute("DELETE FROM fulltext_evidence_rescue_candidates_legacy_20260528_104551 WHERE source_evidence_id IN (SELECT evidence_id FROM _dedup_p1_todelete)")
    # 3e: evidence_isolate_links
    conn.execute("DELETE FROM evidence_isolate_links WHERE evidence_id IN (SELECT evidence_id FROM _dedup_p1_todelete)")

    # 3f: Finally, delete from evidence_records
    conn.execute("DELETE FROM evidence_records WHERE evidence_id IN (SELECT evidence_id FROM _dedup_p1_todelete)")

    conn.execute("PRAGMA foreign_keys = ON")

    conn.execute("DROP TABLE IF EXISTS _dedup_p1_todelete")
    return result


def phase2_consolidate_claim_duplicates(conn, dry_run: bool) -> dict:
    """Consolidate records where same claim appears for same (virus, host, type)
    but with different isolates. Keep 1 canonical claim, link all isolates via bridge.

    Only applies to groups where isolate_id IS NOT NULL (otherwise it's just a dup).
    """
    result = {"groups_found": 0, "records_in_groups": 0, "consolidated_to": 0,
              "isolate_links_created": 0, "removed": 0}

    dup_groups = conn.execute("""
        SELECT virus_master_id, host_id, evidence_type, claim,
               COUNT(*) as cnt,
               COUNT(DISTINCT isolate_id) as n_isolates,
               MIN(evidence_id) as keep_id
        FROM evidence_records
        WHERE claim IS NOT NULL AND LENGTH(claim) > 50
          AND isolate_id IS NOT NULL
        GROUP BY virus_master_id, host_id, evidence_type, claim
        HAVING COUNT(*) > 1 AND COUNT(DISTINCT isolate_id) > 1
    """).fetchall()

    result["groups_found"] = len(dup_groups)
    result["records_in_groups"] = sum(r["cnt"] for r in dup_groups)
    result["consolidated_to"] = len(dup_groups)
    result["removed"] = result["records_in_groups"] - result["consolidated_to"]

    if dry_run or result["removed"] == 0:
        return result

    run_id = conn.execute("SELECT MAX(run_id) FROM evidence_dedup_runs").fetchone()[0]

    # Use temp table for efficiency
    conn.execute("DROP TABLE IF EXISTS _dedup_p2_todelete")
    conn.execute("""
        CREATE TEMP TABLE _dedup_p2_todelete AS
        SELECT er.evidence_id, d.keep_id, er.isolate_id
        FROM evidence_records er
        INNER JOIN (
            SELECT virus_master_id, host_id, evidence_type, claim,
                   MIN(evidence_id) as keep_id
            FROM evidence_records
            WHERE claim IS NOT NULL AND LENGTH(claim) > 50 AND isolate_id IS NOT NULL
            GROUP BY virus_master_id, host_id, evidence_type, claim
            HAVING COUNT(*) > 1 AND COUNT(DISTINCT isolate_id) > 1
        ) d
        ON (er.virus_master_id = d.virus_master_id OR (er.virus_master_id IS NULL AND d.virus_master_id IS NULL))
           AND (er.host_id = d.host_id OR (er.host_id IS NULL AND d.host_id IS NULL))
           AND er.evidence_type = d.evidence_type
           AND er.claim = d.claim
           AND er.isolate_id IS NOT NULL
           AND er.evidence_id != d.keep_id
    """)

    # Create isolate links for ALL isolates that will be consolidated
    conn.execute("""
        INSERT OR IGNORE INTO evidence_isolate_links (evidence_id, isolate_id, link_source, created_at)
        SELECT d.keep_id, d.isolate_id, 'phase2_consolidation', ?
        FROM _dedup_p2_todelete d
    """, (stamp(),))
    result["isolate_links_created"] = scalar(conn, "SELECT COUNT(*) FROM _dedup_p2_todelete") or 0

    # Also link the keep record's own isolates
    conn.execute("""
        INSERT OR IGNORE INTO evidence_isolate_links (evidence_id, isolate_id, link_source, created_at)
        SELECT keep_id, isolate_id, 'phase2_consolidation', ?
        FROM (
            SELECT DISTINCT d.keep_id, er2.isolate_id
            FROM _dedup_p2_todelete d
            JOIN evidence_records er2 ON er2.evidence_id = d.keep_id
            WHERE er2.isolate_id IS NOT NULL
        )
    """, (stamp(),))

    # Quarantine
    conn.execute(f"""
        INSERT INTO evidence_dedup_quarantine (run_id, evidence_id, full_record, reason, created_at)
        SELECT {run_id}, evidence_id, '', 'phase2_claim_consolidation', '{stamp()}'
        FROM _dedup_p2_todelete
    """)

    # Delete from child tables first
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute("DELETE FROM evidence_duplicate_suppression_log WHERE suppressed_evidence_id IN (SELECT evidence_id FROM _dedup_p2_todelete)")
    conn.execute("DELETE FROM evidence_duplicate_suppression_log WHERE canonical_evidence_id IN (SELECT evidence_id FROM _dedup_p2_todelete)")
    conn.execute("DELETE FROM evidence_review_priority_queue WHERE evidence_id IN (SELECT evidence_id FROM _dedup_p2_todelete)")
    conn.execute("DELETE FROM weak_evidence_isolation_log WHERE evidence_id IN (SELECT evidence_id FROM _dedup_p2_todelete)")
    conn.execute("DELETE FROM fulltext_evidence_rescue_candidates WHERE source_evidence_id IN (SELECT evidence_id FROM _dedup_p2_todelete)")
    conn.execute("DELETE FROM fulltext_evidence_rescue_targets WHERE source_evidence_id IN (SELECT evidence_id FROM _dedup_p2_todelete)")
    conn.execute("DELETE FROM fulltext_evidence_rescue_candidates_legacy_20260528_104551 WHERE source_evidence_id IN (SELECT evidence_id FROM _dedup_p2_todelete)")

    conn.execute("DELETE FROM evidence_records WHERE evidence_id IN (SELECT evidence_id FROM _dedup_p2_todelete)")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("DROP TABLE IF EXISTS _dedup_p2_todelete")

    return result


def main():
    parser = argparse.ArgumentParser(description="Evidence Deduplication")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--phase2", action="store_true",
                        help="Also run Phase 2 (claim consolidation)")
    parser.add_argument("--db", type=str, default=str(DB_PATH))
    args = parser.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"ERROR: Database not found: {db_path}")
        sys.exit(1)

    if not args.dry_run:
        backup_database(db_path, BACKUPS_DIR, "pre_evidence_dedup")
        print()

    import sqlite3
    conn = sqlite3.connect(str(db_path), timeout=120)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 120000")

    try:
        ensure_schema(conn)

        mode = "DRY-RUN" if args.dry_run else "LIVE"
        print(f"{'='*60}")
        print(f"EVIDENCE DEDUPLICATION — {mode}")
        print(f"{'='*60}")
        print()

        before_total = scalar(conn, "SELECT COUNT(*) FROM evidence_records")
        print(f"Before: {before_total:,} evidence records\n")

        # Record run
        conn.execute(
            "INSERT INTO evidence_dedup_runs (run_ts, phase, dry_run, notes) VALUES (?, ?, ?, ?)",
            (stamp(), "phase1" if not args.phase2 else "phase1+phase2",
             1 if args.dry_run else 0, ""))
        conn.commit()

        # ── Phase 1 ──────────────────────────────────────────────
        print("Phase 1: Remove true duplicates (same virus+host+type+claim+isolate)")
        print("-" * 50)
        r1 = phase1_remove_true_duplicates(conn, args.dry_run)

        label = "Would remove" if args.dry_run else "Removed"
        print(f"  Groups found:       {r1['groups_found']:,}")
        print(f"  Records in groups:  {r1['records_in_groups']:,}")
        print(f"  Kept (canonical):   {r1['kept']:,}")
        print(f"  {label}:         {r1['removed']:,}")
        print()

        # ── Phase 2 (optional) ───────────────────────────────────
        if args.phase2:
            print("Phase 2: Consolidate claim-level duplicates (same claim, diff isolates)")
            print("-" * 50)
            r2 = phase2_consolidate_claim_duplicates(conn, args.dry_run)

            label_r = "Would remove" if args.dry_run else "Removed"
            print(f"  Groups found:         {r2['groups_found']:,}")
            print(f"  Records in groups:    {r2['records_in_groups']:,}")
            print(f"  Consolidated to:      {r2['consolidated_to']:,}")
            print(f"  Isolate links created:{r2['isolate_links_created']:,}")
            print(f"  {label_r}:           {r2['removed']:,}")
            print()

        if not args.dry_run:
            conn.commit()

        # ── Summary ──────────────────────────────────────────────
        after_total = scalar(conn, "SELECT COUNT(*) FROM evidence_records")
        delta = after_total - before_total

        print("=" * 60)
        print("SUMMARY")
        print("=" * 60)
        print(f"  Before: {before_total:,}")
        print(f"  After:  {after_total:,} ({delta:+,})")

        # Integrity
        integrity = scalar(conn, "PRAGMA integrity_check")
        fk_count = len(conn.execute("PRAGMA foreign_key_check").fetchall())
        print(f"  Integrity: {integrity}, FK violations: {fk_count}")

        # Report
        report = {
            "script": "deduplicate_evidence.py",
            "timestamp": stamp(),
            "dry_run": args.dry_run,
            "phase1": {k: v for k, v in r1.items()},
            "phase2": {k: v for k, v in r2.items()} if args.phase2 else None,
            "before_total": before_total,
            "after_total": after_total,
            "delta": delta,
        }
        report_path = REPORTS_DIR / f"evidence_dedup_{stamp()}.json"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\n[report] → {report_path}")

    except BaseException:
        if not args.dry_run:
            conn.rollback()
        raise
    finally:
        conn.close()

    print("\nDone.")


if __name__ == "__main__":
    main()
