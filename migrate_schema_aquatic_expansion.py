#!/usr/bin/env python3
"""
AquaVir-KB Schema Migration v1.0
================================
Migrate CrustaVirus DB schema for aquatic invertebrate expansion.
- Adds phylum/class fields to crustacean_hosts
- Adds host_association_method to infection_records
- Adds discovery_context to virus_master
- Backfills taxonomic data for existing crustacean hosts
- Creates expansion-related views and indexes
- Runs integrity checks

Safe to run on existing database; all changes are additive.
"""

import sqlite3
import json
import os
import sys
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "crustacean_virus_core.db")
BACKUP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "backups")

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

def run_migration(conn):
    cur = conn.cursor()

    # ===================================================================
    # PHASE 1: crustacean_hosts 扩展
    # ===================================================================
    log("Phase 1: Expanding crustacean_hosts for multi-phylum support...")

    # 1a. Add phylum column
    try:
        cur.execute("ALTER TABLE crustacean_hosts ADD COLUMN phylum VARCHAR(50)")
        log("  + Added phylum column")
    except sqlite3.OperationalError as e:
        if "duplicate column" in str(e).lower():
            log("  - phylum column already exists")
        else:
            raise

    # 1b. Add class column
    try:
        cur.execute("ALTER TABLE crustacean_hosts ADD COLUMN class VARCHAR(50)")
        log("  + Added class column")
    except sqlite3.OperationalError as e:
        if "duplicate column" in str(e).lower():
            log("  - class column already exists")
        else:
            raise

    # 1c. Backfill phylum/class for existing crustacean hosts
    # Known arthropod orders in crustacean_hosts
    crustacean_orders = (
        'Decapoda', 'Euphausiacea', 'Isopoda', 'Stomatopoda', 'Anostraca',
        'Thecostraca', 'Xiphosura', 'Hemiptera', 'Hexapoda'
    )
    mollusk_orders = (
        'Unionida', 'Veneroida', 'Architaenioglossa', 'Valvatida'
    )

    # Backfill Arthropoda
    placeholders = ','.join('?' * len(crustacean_orders))
    cur.execute(f"""
        UPDATE crustacean_hosts
        SET phylum = 'Arthropoda', class = 'Malacostraca'
        WHERE taxon_order IN ({placeholders}) AND phylum IS NULL
    """, crustacean_orders)
    n_arthro = cur.rowcount
    log(f"  Backfilled Arthropoda: {n_arthro} hosts")

    # Backfill known mollusk orders (these are non-crustacean contaminants in current DB)
    placeholders_m = ','.join('?' * len(mollusk_orders))
    cur.execute(f"""
        UPDATE crustacean_hosts
        SET phylum = 'Mollusca', class = 'Bivalvia'
        WHERE taxon_order IN ({placeholders_m}) AND phylum IS NULL
    """, mollusk_orders)
    n_moll = cur.rowcount
    if n_moll:
        log(f"  Backfilled Mollusca (non-crustacean): {n_moll} hosts")

    # Backfill remaining based on host_group patterns
    groups_map = {
        'penaeid shrimp': ('Arthropoda', 'Malacostraca', 'Decapoda'),
        'palaemonid shrimp': ('Arthropoda', 'Malacostraca', 'Decapoda'),
        'crayfish': ('Arthropoda', 'Malacostraca', 'Decapoda'),
        'lobster': ('Arthropoda', 'Malacostraca', 'Decapoda'),
        'crab': ('Arthropoda', 'Malacostraca', 'Decapoda'),
        'hermit crab': ('Arthropoda', 'Malacostraca', 'Decapoda'),
        'fairy shrimp': ('Arthropoda', 'Branchiopoda', 'Anostraca'),
        'krill': ('Arthropoda', 'Malacostraca', 'Euphausiacea'),
        'isopod': ('Arthropoda', 'Malacostraca', 'Isopoda'),
        'mantis shrimp': ('Arthropoda', 'Malacostraca', 'Stomatopoda'),
        'barnacle': ('Arthropoda', 'Thecostraca', 'Thecostraca'),
        'horseshoe crab': ('Arthropoda', 'Merostomata', 'Xiphosura'),
    }

    for group, (phylum, cls, order) in groups_map.items():
        cur.execute("""
            UPDATE crustacean_hosts
            SET phylum = ?, class = ?
            WHERE host_group = ? AND phylum IS NULL
        """, (phylum, cls, group))

    n_group = cur.rowcount
    if n_group:
        log(f"  Backfilled by host_group patterns: {n_group} hosts")

    # Count remaining nulls
    null_phylum = cur.execute(
        "SELECT COUNT(*) FROM crustacean_hosts WHERE phylum IS NULL"
    ).fetchone()[0]
    log(f"  Remaining without phylum: {null_phylum}")

    # ===================================================================
    # PHASE 2: infection_records - host_association_method
    # ===================================================================
    log("Phase 2: Adding host_association_method to infection_records...")

    try:
        cur.execute("""
            ALTER TABLE infection_records ADD COLUMN host_association_method VARCHAR(50)
            DEFAULT 'co_occurrence_metagenomic'
        """)
        log("  + Added host_association_method column")
    except sqlite3.OperationalError as e:
        if "duplicate column" in str(e).lower():
            log("  - host_association_method already exists")
        else:
            raise

    # Backfill based on existing detection_method
    cur.execute("""
        UPDATE infection_records
        SET host_association_method = 'confirmed_infection'
        WHERE detection_method IN ('PCR', 'qPCR', 'RT-PCR', 'ISH', 'TEM',
              'experimental infection', 'virus isolation', 'immunohistochemistry')
        AND host_association_method = 'co_occurrence_metagenomic'
    """)
    n_conf = cur.rowcount
    log(f"  Backfilled confirmed_infection: {n_conf} records")

    cur.execute("""
        UPDATE infection_records
        SET host_association_method = 'disease_outbreak'
        WHERE disease_symptom IS NOT NULL AND disease_symptom != ''
        AND host_association_method = 'co_occurrence_metagenomic'
    """)
    n_outbreak = cur.rowcount
    log(f"  Backfilled disease_outbreak: {n_outbreak} records")

    cur.execute("""
        UPDATE infection_records
        SET host_association_method = 'environmental_sample'
        WHERE isolation_source IN ('water', 'sediment', 'seawater', 'pond water',
              'environmental', 'plankton')
        AND host_association_method = 'co_occurrence_metagenomic'
    """)
    n_env = cur.rowcount
    log(f"  Backfilled environmental_sample: {n_env} records")

    # Summary
    for method in ('confirmed_infection', 'disease_outbreak', 'co_occurrence_metagenomic', 'environmental_sample'):
        count = cur.execute(
            "SELECT COUNT(*) FROM infection_records WHERE host_association_method = ?", (method,)
        ).fetchone()[0]
        log(f"    {method}: {count}")

    # ===================================================================
    # PHASE 3: virus_master - discovery_context
    # ===================================================================
    log("Phase 3: Adding discovery_context to virus_master...")

    try:
        cur.execute("""
            ALTER TABLE virus_master ADD COLUMN discovery_context VARCHAR(50)
            DEFAULT 'metagenomic_environmental'
        """)
        log("  + Added discovery_context column")
    except sqlite3.OperationalError as e:
        if "duplicate column" in str(e).lower():
            log("  - discovery_context already exists")
        else:
            raise

    try:
        cur.execute("""
            ALTER TABLE virus_master ADD COLUMN host_phylum VARCHAR(50)
        """)
        log("  + Added host_phylum column")
    except sqlite3.OperationalError as e:
        if "duplicate column" in str(e).lower():
            log("  - host_phylum already exists")
        else:
            raise

    # Backfill: viruses with confirmed infection records
    cur.execute("""
        UPDATE virus_master
        SET discovery_context = 'metagenomic_with_host_evidence'
        WHERE master_id IN (
            SELECT DISTINCT vm.master_id
            FROM virus_master vm
            JOIN infection_records ir ON vm.master_id = ir.record_id
            WHERE ir.host_association_method IN ('confirmed_infection', 'disease_outbreak')
        )
        AND discovery_context = 'metagenomic_environmental'
    """)
    n_evidence = cur.rowcount
    log(f"  Backfilled metagenomic_with_host_evidence: {n_evidence} species")

    # Known isolated/cultured viruses (from literature)
    known_cultured = ('white spot syndrome virus', 'yellow head virus',
                      'taura syndrome virus', 'infectious hypodermal and hematopoietic necrosis virus',
                      'Ostreid herpesvirus 1', 'Haliotid herpesvirus 1',
                      'acute viral necrosis virus')
    placeholders = ','.join('?' * len(known_cultured))
    cur.execute(f"""
        UPDATE virus_master
        SET discovery_context = 'isolated_and_cultured'
        WHERE LOWER(canonical_name) IN ({placeholders})
    """, known_cultured)
    n_cult = cur.rowcount
    log(f"  Backfilled isolated_and_cultured: {n_cult} species")

    # Backfill host_phylum for existing (all current are Arthropoda)
    cur.execute("""
        UPDATE virus_master SET host_phylum = 'Arthropoda'
        WHERE host_phylum IS NULL
    """)
    n_hp = cur.rowcount
    log(f"  Backfilled host_phylum=Arthropoda: {n_hp} species")

    # Summary
    for ctx in ('isolated_and_cultured', 'metagenomic_with_host_evidence', 'metagenomic_environmental'):
        count = cur.execute(
            "SELECT COUNT(*) FROM virus_master WHERE discovery_context = ?", (ctx,)
        ).fetchone()[0]
        log(f"    {ctx}: {count}")

    # ===================================================================
    # PHASE 4: Indexes for new fields
    # ===================================================================
    log("Phase 4: Creating indexes for new fields...")

    new_indexes = [
        ("idx_hosts_phylum", "crustacean_hosts(phylum)"),
        ("idx_hosts_class", "crustacean_hosts(class)"),
        ("idx_hosts_phylum_class", "crustacean_hosts(phylum, class)"),
        ("idx_infection_assoc_method", "infection_records(host_association_method)"),
        ("idx_virus_host_phylum", "virus_master(host_phylum)"),
        ("idx_virus_discovery_ctx", "virus_master(discovery_context)"),
    ]

    for idx_name, idx_def in new_indexes:
        try:
            cur.execute(f"CREATE INDEX IF NOT EXISTS {idx_name} ON {idx_def}")
        except sqlite3.OperationalError as e:
            log(f"  ! Failed to create {idx_name}: {e}")

    log("  Indexes created/verified")

    # ===================================================================
    # PHASE 5: Useful views
    # ===================================================================
    log("Phase 5: Creating/updating expansion views...")

    # View for host composition by phylum
    cur.execute("""
        CREATE VIEW IF NOT EXISTS v_host_composition_by_phylum AS
        SELECT
            phylum,
            class,
            COUNT(*) as host_count,
            GROUP_CONCAT(DISTINCT host_group) as host_groups
        FROM crustacean_hosts
        WHERE host_type = 'biological'
        GROUP BY phylum, class
        ORDER BY host_count DESC
    """)

    # View for virus discovery context distribution
    cur.execute("""
        CREATE VIEW IF NOT EXISTS v_virus_discovery_summary AS
        SELECT
            discovery_context,
            host_phylum,
            COUNT(*) as species_count
        FROM virus_master
        GROUP BY discovery_context, host_phylum
        ORDER BY species_count DESC
    """)

    # View for infection record quality
    cur.execute("""
        CREATE VIEW IF NOT EXISTS v_infection_quality AS
        SELECT
            host_association_method,
            COUNT(*) as record_count,
            COUNT(DISTINCT host_id) as unique_hosts,
            COUNT(DISTINCT isolate_id) as unique_isolates
        FROM infection_records
        GROUP BY host_association_method
        ORDER BY
            CASE host_association_method
                WHEN 'confirmed_infection' THEN 1
                WHEN 'disease_outbreak' THEN 2
                WHEN 'pathology_observation' THEN 3
                WHEN 'co_occurrence_metagenomic' THEN 4
                WHEN 'environmental_sample' THEN 5
                ELSE 6
            END
    """)

    # NAR-ready summary view
    cur.execute("""
        CREATE VIEW IF NOT EXISTS v_nar_database_summary AS
        SELECT
            'Total virus species' as metric,
            CAST(COUNT(*) AS TEXT) as value
        FROM virus_master
        UNION ALL
        SELECT 'Total viral isolates', CAST(COUNT(*) AS TEXT)
        FROM viral_isolates
        UNION ALL
        SELECT 'Total proteins', CAST(COUNT(*) AS TEXT)
        FROM viral_proteins
        UNION ALL
        SELECT 'Total host species (biological)', CAST(COUNT(*) AS TEXT)
        FROM crustacean_hosts WHERE host_type = 'biological'
        UNION ALL
        SELECT 'Aquatic invertebrate phyla covered',
            CAST(COUNT(DISTINCT phylum) AS TEXT)
        FROM crustacean_hosts WHERE phylum IS NOT NULL
        UNION ALL
        SELECT 'Confirmed virus-host associations',
            CAST(COUNT(*) AS TEXT)
        FROM infection_records
        WHERE host_association_method IN ('confirmed_infection', 'disease_outbreak')
        UNION ALL
        SELECT 'Geographic countries',
            CAST(COUNT(DISTINCT country) AS TEXT)
        FROM isolate_curated_profiles WHERE country IS NOT NULL
        UNION ALL
        SELECT 'Literature references', CAST(COUNT(*) AS TEXT)
        FROM ref_literatures
    """)

    log("  Views created/updated")

    # ===================================================================
    # PHASE 6: Integrity checks
    # ===================================================================
    log("Phase 6: Running integrity checks...")

    checks = []

    # Check: hosts without phylum
    no_phylum = cur.execute(
        "SELECT COUNT(*) FROM crustacean_hosts WHERE phylum IS NULL"
    ).fetchone()[0]
    checks.append(("Hosts without phylum", no_phylum, no_phylum == 0))

    # Check: non-crustacean hosts
    non_crust = cur.execute("""
        SELECT COUNT(*) FROM crustacean_hosts
        WHERE phylum IS NOT NULL AND phylum != 'Arthropoda'
        AND host_type = 'biological'
    """).fetchone()[0]
    checks.append(("Non-arthropod biological hosts", non_crust, True))

    # Check: virus species without host_phylum
    no_hp = cur.execute(
        "SELECT COUNT(*) FROM virus_master WHERE host_phylum IS NULL"
    ).fetchone()[0]
    checks.append(("Virus species without host_phylum", no_hp, no_hp == 0))

    # Check: infection records without method
    no_method = cur.execute(
        "SELECT COUNT(*) FROM infection_records WHERE host_association_method IS NULL"
    ).fetchone()[0]
    checks.append(("Infection records without association method", no_method, no_method == 0))

    # Check: confirmed infection count
    conf_count = cur.execute("""
        SELECT COUNT(*) FROM infection_records
        WHERE host_association_method IN ('confirmed_infection', 'disease_outbreak')
    """).fetchone()[0]
    checks.append(("Confirmed infection/disease records", conf_count, conf_count > 0))

    # Check: FK integrity
    cur.execute("PRAGMA foreign_key_check")
    fk_violations = cur.fetchall()
    checks.append(("Foreign key violations", len(fk_violations), len(fk_violations) == 0))
    if fk_violations:
        for v in fk_violations[:10]:
            log(f"    FK violation: {v}")

    log("\n  Integrity Check Results:")
    all_pass = True
    for name, value, passed in checks:
        status = "PASS" if passed else "WARN"
        if not passed:
            all_pass = False
        log(f"    [{status}] {name}: {value}")

    # ===================================================================
    # PHASE 7: VACUUM and ANALYZE
    # ===================================================================
    log("\nPhase 7: Database maintenance...")
    cur.execute("PRAGMA optimize")
    cur.execute("ANALYZE")
    log("  ANALYZE complete")

    return all_pass, checks

def main():
    import shutil
    import time

    if not os.path.exists(DB_PATH):
        log(f"ERROR: Database not found at {DB_PATH}")
        sys.exit(1)

    # Backup
    os.makedirs(BACKUP_DIR, exist_ok=True)
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_path = os.path.join(BACKUP_DIR, f"pre_expansion_backup_{ts}.db")
    log(f"Creating backup: {backup_path}")
    shutil.copy2(DB_PATH, backup_path)
    log(f"Backup created ({os.path.getsize(backup_path) / 1024 / 1024:.1f} MB)")

    # Work on a working copy to avoid lock contention with backend
    work_path = os.path.join(BACKUP_DIR, f"migration_work_{ts}.db")
    log(f"Creating working copy: {work_path}")
    shutil.copy2(DB_PATH, work_path)

    conn = sqlite3.connect(work_path, timeout=30)
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")

    try:
        all_pass, checks = run_migration(conn)
        conn.commit()
        conn.close()

        if all_pass:
            log("\n=== Migration completed successfully on working copy ===")
        else:
            log("\n=== Migration completed with warnings ===")
            log("Review the integrity check warnings above before proceeding.")

    except Exception as e:
        conn.rollback()
        conn.close()
        log(f"\nERROR: Migration failed: {e}")
        log(f"Database unchanged. Restore from backup if needed: {backup_path}")
        # Clean up work copy
        if os.path.exists(work_path):
            os.remove(work_path)
        raise

    # Replace live database with migrated copy
    log("\nReplacing live database with migrated copy...")
    final_backup = os.path.join(BACKUP_DIR, f"pre_replace_{ts}.db")
    shutil.copy2(DB_PATH, final_backup)
    log(f"  Pre-replace backup: {final_backup}")

    # Retry the replace in case of lock
    for attempt in range(5):
        try:
            shutil.copy2(work_path, DB_PATH)
            log("  Live database replaced successfully")
            break
        except PermissionError:
            log(f"  Database locked, retry {attempt+1}/5 after 3s...")
            time.sleep(3)

    # Clean up work copy
    if os.path.exists(work_path):
        os.remove(work_path)

    log("\nNext steps:")
    log("  1. Restart backend server to pick up new schema")
    log("  2. Run: python optimize_database_post_migration.py")
    log("  3. Begin Phase 1 data import (Mollusca viruses)")

    # Save report
    report = {
        "migration": "aquatic_invertebrate_expansion_v1",
        "timestamp": datetime.now().isoformat(),
        "backup_path": backup_path,
        "final_backup_path": final_backup,
        "checks": [{"name": n, "value": v, "passed": p} for n, v, p in checks]
    }
    report_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "expansion_migration_report.json")
    with open(report_path, 'w') as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    log(f"Report saved: {report_path}")

if __name__ == "__main__":
    main()
