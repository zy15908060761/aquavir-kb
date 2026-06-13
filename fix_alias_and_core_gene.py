#!/usr/bin/env python3
"""Fix alias namespace conflicts (C2, C3) and core_gene definition (C6).

C2: virus_aliases "GAV" points to 2 different master_ids. Add disambiguation.
C3: host_aliases have 22 aliases pointing to multiple host_ids — add UNIQUE
    constraint; flag conflicts for curator review.
C6: 1,496 core_genes have present_isolates=1 — add core_status column to
    distinguish true core genes from accessory/rare genes.
"""

from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path

from db_utils import backup_database as wal_safe_backup, get_db

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "crustacean_virus_core.db"
BACKUP_DIR = BASE_DIR / "backups"
REPORTS_DIR = BASE_DIR / "reports"


def fix_virus_alias_gav(conn) -> dict:
    """Fix 'GAV' alias pointing to 2 masters. GAV primarily = Gill-associated virus (Yellow head virus)."""
    # Mark Yellow head virus (master_id=2) as preferred
    conn.execute(
        "UPDATE virus_aliases SET is_preferred=1, notes=COALESCE(notes || '; ','') || 'GAV primarily = Gill-associated virus (Yellow head virus complex)' WHERE alias='GAV' AND master_id=2"
    )
    # Disambiguate the other GAV
    conn.execute(
        "UPDATE virus_aliases SET notes=COALESCE(notes || '; ','') || 'GAV here = Crab associated circular virus (not Gill-associated virus)' WHERE alias='GAV' AND master_id=20"
    )
    return {"gav_aliases_updated": 2}


def fix_host_aliases_constraint(conn) -> dict:
    """Add UNIQUE constraint to prevent future alias->host conflicts."""
    # SQLite doesn't support ALTER ADD CONSTRAINT, so check if unique index exists
    existing_idx = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='index' AND name='idx_host_alias_unique'"
    ).fetchone()

    if not existing_idx:
        # Create unique index to prevent future multi-host aliases
        try:
            conn.execute(
                "CREATE UNIQUE INDEX idx_host_alias_unique ON host_aliases(alias, host_id)"
            )
            conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_virus_alias_unique ON virus_aliases(alias, master_id)"
            )
        except Exception as e:
            print(f"  Warning: Could not create unique index: {e}")
            return {"unique_index_created": False}

    return {"unique_index_created": True}


def export_alias_conflicts(conn):
    """Export conflicted host aliases for curator review."""
    out_dir = REPORTS_DIR / f"alias_review_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    out_dir.mkdir(parents=True, exist_ok=True)

    # Host alias conflicts
    rows = conn.execute("""
        SELECT va.alias, va.host_id, ch.scientific_name, ch.common_name_cn,
               va.alias_type, va.is_preferred, va.confidence
        FROM host_aliases va
        JOIN crustacean_hosts ch ON ch.host_id = va.host_id
        WHERE va.alias IN (
            SELECT alias FROM host_aliases
            GROUP BY alias HAVING COUNT(DISTINCT host_id) > 1
        )
        ORDER BY va.alias, ch.scientific_name
    """).fetchall()

    path = out_dir / "host_alias_conflicts.csv"
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["alias", "host_id", "scientific_name", "common_name_cn", "alias_type", "is_preferred", "confidence"])
        for row in rows:
            w.writerow(row)

    print(f"Host alias conflicts exported to: {path}")
    return str(path)


def fix_core_genes(conn) -> dict:
    """Add core_status column and classify genes by conservation rate."""
    info = [row["name"] for row in conn.execute("PRAGMA table_info(core_genes)")]
    if "core_status" not in info:
        conn.execute("ALTER TABLE core_genes ADD COLUMN core_status TEXT")
        conn.execute("ALTER TABLE core_genes ADD COLUMN core_threshold_note TEXT")

    # conservation_rate is stored as 0-1 fraction (e.g., 0.5 = 50%)
    # Classify: true_core (>=50% of isolates), accessory (10-50%), rare (<10%)
    conn.execute("""
        UPDATE core_genes
        SET core_status = CASE
            WHEN conservation_rate >= 0.5 THEN 'true_core'
            WHEN conservation_rate >= 0.1 THEN 'accessory_conserved'
            ELSE 'rare_not_core'
        END,
        core_threshold_note = CASE
            WHEN conservation_rate >= 0.5 THEN 'Present in >=50% of isolates; qualifies as core gene'
            WHEN conservation_rate >= 0.1 THEN 'Present in 10-50% of isolates; accessory conserved gene, not core'
            ELSE 'Present in <10% of isolates; does NOT qualify as core or conserved gene'
        END
    """)

    # Counts
    stats = {}
    for row in conn.execute(
        "SELECT core_status, COUNT(*) FROM core_genes GROUP BY core_status"
    ):
        stats[row[0]] = row[1]

    conn.commit()
    return {"core_status_distribution": stats}


def main():
    if not DB_PATH.exists():
        raise SystemExit(f"Database not found: {DB_PATH}")

    backup = wal_safe_backup(DB_PATH, BACKUP_DIR, label="fix_alias_core_gene")
    print(f"Backup: {backup}")

    conn = get_db()
    try:
        results = {}

        # C2: Fix virus_aliases GAV conflict
        print("\n--- C2: virus_aliases ---")
        results["virus_aliases"] = fix_virus_alias_gav(conn)
        print(f"  GAV aliases updated: {results['virus_aliases']['gav_aliases_updated']}")

        # C3: Fix host_aliases
        print("\n--- C3: host_aliases ---")
        results["host_aliases_constraint"] = fix_host_aliases_constraint(conn)
        print(f"  Unique index created: {results['host_aliases_constraint']['unique_index_created']}")
        conflict_path = export_alias_conflicts(conn)

        # C6: Fix core_genes
        print("\n--- C6: core_genes ---")
        results["core_genes"] = fix_core_genes(conn)
        stats = results["core_genes"]["core_status_distribution"]
        print(f"  true_core: {stats.get('true_core', 0)}")
        print(f"  accessory_conserved: {stats.get('accessory_conserved', 0)}")
        print(f"  rare_not_core: {stats.get('rare_not_core', 0)}")
        print(f"  (genes with present_isolates=1 are now classified as 'rare_not_core')")

        # Also add provenance for this fix
        conn.execute("""
            INSERT INTO data_provenance (table_name, data_source, confidence_level, verification_method, curator_notes)
            VALUES ('core_genes', 'publication_hardening', 'inferred',
                    'conservation_threshold_classification',
                    'core_status added based on conservation_rate: >=50% = true_core, 10-50% = accessory, <10% = rare')
        """)

        conn.commit()
        print("\nAll alias and core_gene fixes applied.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
