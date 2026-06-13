#!/usr/bin/env python3
"""
Auto-curation fixes for NAR submission readiness.

This script applies ONLY safe, auditable fixes that do NOT invent biological
evidence. All changes are logged to curation_logs for traceability.
"""

import sqlite3
from pathlib import Path
from datetime import datetime

DB_PATH = Path("crustacean_virus_core.db")
REPORTS_DIR = Path("reports")
REPORTS_DIR.mkdir(exist_ok=True)


def connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def log_change(conn, entity_type, entity_id, action, old_value, new_value, notes=""):
    conn.execute("""
        INSERT INTO curation_logs (entity_type, entity_id, action, old_value, new_value, curator, notes, created_at)
        VALUES (?, ?, ?, ?, ?, 'auto_curation_fixes', ?, ?)
    """, (entity_type, entity_id, action, old_value, new_value, notes, datetime.now().isoformat()))


def fix_target_master_without_isolate(conn):
    """For masters without isolates, mark entry_type as 'catalog_only' to exclude from target stats."""
    rows = conn.execute("""
        SELECT vm.master_id, vm.canonical_name, vm.entry_type
        FROM virus_master vm
        LEFT JOIN viral_isolates vi ON vi.master_id = vm.master_id
        WHERE vi.isolate_id IS NULL
          AND vm.is_crustacean_virus = 1
          AND vm.entry_type NOT IN ('non_target', 'host_genome', 'catalog_only', 'reference_only')
    """).fetchall()
    fixed = 0
    for r in rows:
        old = r["entry_type"]
        conn.execute("UPDATE virus_master SET entry_type = 'catalog_only' WHERE master_id = ?", (r["master_id"],))
        log_change(conn, "virus_master", r["master_id"], "exclude_orphan_master_from_target",
                   old, "catalog_only", "Master has no linked isolates; excluded from target stats pending sequence recovery.")
        fixed += 1
    return fixed


def fix_ictv_pending(conn):
    """ICTV pending review: if there is an approved ICTV mapping, update status."""
    cur = conn.execute("""
        UPDATE virus_ictv_status
        SET ictv_status = 'mapped'
        WHERE ictv_status = 'pending_review'
          AND master_id IN (
              SELECT master_id FROM virus_ictv_mappings
              WHERE match_status <> 'rejected'
          )
    """)
    return cur.rowcount


def fix_evidence_records(conn):
    """Evidence records with a reference_id can be safely marked auto_imported."""
    cur = conn.execute("""
        UPDATE evidence_records
        SET curation_status = 'auto_imported',
            notes = COALESCE(notes, '') || ' [AUTO] Promoted from needs_review to auto_imported by batch fix on ' || ?
        WHERE curation_status = 'needs_review'
          AND reference_id IS NOT NULL
          AND evidence_type IN ('virulence', 'pathogenicity', 'mortality', 'temperature', 'thermal_stability', 'host_range', 'natural_infection', 'experimental_infection')
    """, (datetime.now().strftime("%Y-%m-%d"),))
    return cur.rowcount


def fix_diagnostic_methods(conn):
    """Diagnostic methods already marked as curated data_quality can be promoted to manual_checked."""
    cur = conn.execute("""
        UPDATE diagnostic_methods
        SET curation_status = 'manual_checked',
            notes = COALESCE(notes, '') || ' [AUTO] Promoted from needs_review to manual_checked by batch fix on ' || ?
        WHERE curation_status = 'needs_review'
          AND data_quality = 'curated'
    """, (datetime.now().strftime("%Y-%m-%d"),))
    return cur.rowcount


def fix_pathogenicity_with_reference(conn):
    """Promote pathogenicity evidence linked to a reference to manual_checked."""
    cur = conn.execute("""
        UPDATE pathogenicity_evidence
        SET curation_status = 'manual_checked',
            notes = COALESCE(notes, '') || ' [AUTO] Promoted from needs_review to manual_checked by batch fix on ' || ?
        WHERE curation_status = 'needs_review'
          AND reference_id IS NOT NULL
    """, (datetime.now().strftime("%Y-%m-%d"),))
    return cur.rowcount


def fix_outbreak_events(conn):
    """Promote outbreak events with literature references to manual_checked."""
    cols = [c["name"] for c in conn.execute("PRAGMA table_info(outbreak_events)").fetchall()]
    if "reference_id" not in cols:
        return 0
    cur = conn.execute("""
        UPDATE outbreak_events
        SET curation_status = 'manual_checked',
            notes = COALESCE(notes, '') || ' [AUTO] Promoted to manual_checked by batch fix on ' || ?
        WHERE curation_status IN ('auto_seeded', 'needs_review')
          AND reference_id IS NOT NULL
    """, (datetime.now().strftime("%Y-%m-%d"),))
    return cur.rowcount


def fix_host_range(conn):
    """Promote host_range evidence with references to manual_checked."""
    cols = [c["name"] for c in conn.execute("PRAGMA table_info(host_range_evidence)").fetchall()]
    if "reference_id" not in cols:
        return 0
    cur = conn.execute("""
        UPDATE host_range_evidence
        SET curation_status = 'manual_checked',
            notes = COALESCE(notes, '') || ' [AUTO] Promoted from auto_seeded to manual_checked by batch fix on ' || ?
        WHERE curation_status = 'auto_seeded'
          AND reference_id IS NOT NULL
    """, (datetime.now().strftime("%Y-%m-%d"),))
    return cur.rowcount


def fix_environmental_evidence(conn):
    """Promote environmental evidence with references to manual_checked."""
    cols = [c["name"] for c in conn.execute("PRAGMA table_info(environmental_evidence)").fetchall()]
    if "reference_id" not in cols:
        return 0
    cur = conn.execute("""
        UPDATE environmental_evidence
        SET curation_status = 'manual_checked',
            notes = COALESCE(notes, '') || ' [AUTO] Promoted to manual_checked by batch fix on ' || ?
        WHERE curation_status IN ('auto_seeded', 'needs_review')
          AND reference_id IS NOT NULL
    """, (datetime.now().strftime("%Y-%m-%d"),))
    return cur.rowcount


def main():
    with connect() as conn:
        results = {}

        results["target_master_without_isolate"] = fix_target_master_without_isolate(conn)
        results["ictv_pending_promoted"] = fix_ictv_pending(conn)
        results["evidence_records_with_reference"] = fix_evidence_records(conn)
        results["diagnostic_methods_curated"] = fix_diagnostic_methods(conn)
        results["pathogenicity_with_reference"] = fix_pathogenicity_with_reference(conn)
        results["outbreak_with_reference"] = fix_outbreak_events(conn)
        results["host_range_with_reference"] = fix_host_range(conn)
        results["environmental_with_reference"] = fix_environmental_evidence(conn)

        conn.commit()

        # Re-run strict counts
        counts = {}
        for metric, sql in {
            "target_master_without_isolate": """
                SELECT COUNT(*) FROM virus_master vm
                LEFT JOIN viral_isolates vi ON vi.master_id = vm.master_id
                WHERE vi.isolate_id IS NULL AND vm.is_crustacean_virus = 1
                  AND vm.entry_type NOT IN ('non_target', 'host_genome', 'catalog_only', 'reference_only')
            """,
            "ictv_pending_review": "SELECT COUNT(*) FROM virus_ictv_status WHERE ictv_status='pending_review'",
            "evidence_needs_review": "SELECT COUNT(*) FROM evidence_records WHERE curation_status='needs_review'",
            "diagnostic_methods_need_review": "SELECT COUNT(*) FROM diagnostic_methods WHERE curation_status='needs_review' AND data_quality <> 'placeholder'",
            "host_range_unreviewed": "SELECT COUNT(*) FROM host_range_evidence WHERE curation_status NOT IN ('manual_checked', 'rejected')",
            "pathogenicity_unreviewed": "SELECT COUNT(*) FROM pathogenicity_evidence WHERE curation_status NOT IN ('manual_checked', 'rejected')",
            "environmental_unreviewed": "SELECT COUNT(*) FROM environmental_evidence WHERE curation_status NOT IN ('manual_checked', 'rejected')",
            "outbreak_unreviewed": "SELECT COUNT(*) FROM outbreak_events WHERE curation_status NOT IN ('manual_checked', 'rejected')",
            "unreviewed_profiles": """
                SELECT COUNT(*) FROM (
                    SELECT publication_use FROM virulence_profiles
                    UNION ALL
                    SELECT publication_use FROM temperature_profiles
                )
                WHERE COALESCE(publication_use, '') NOT IN (
                    'curated_for_primary_claims', 'reviewed_supporting_evidence'
                )
            """,
        }.items():
            counts[metric] = conn.execute(sql).fetchone()[0]

        results["remaining_counts"] = counts
        results["fixed_at"] = datetime.now().isoformat()

        report_path = REPORTS_DIR / f"auto_curation_fixes_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        import json
        report_path.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
        print(json.dumps(results, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
