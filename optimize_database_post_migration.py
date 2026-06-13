#!/usr/bin/env python3
"""
AquaVir-KB Database Optimization v2.0
=====================================
Post-migration optimization:
- Add host_scope_status to classify hosts by phylum
- Fix host_type for non-crustacean biological hosts
- Audit reference quality (traceless refs = no PMID AND no DOI)
- Create expansion tracking views
- Export pre-expansion baseline

Run after migrate_schema_aquatic_expansion.py
"""

import sqlite3
import json
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "crustacean_virus_core.db")

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

def main():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    cur = conn.cursor()

    # ===================================================================
    # TASK 1: Add host_scope_status column to crustacean_hosts
    # ===================================================================
    log("Task 1: Adding host_scope_status to crustacean_hosts...")

    try:
        cur.execute("""
            ALTER TABLE crustacean_hosts ADD COLUMN host_scope_status VARCHAR(30)
            DEFAULT 'needs_review'
        """)
        log("  + Added host_scope_status column")
    except sqlite3.OperationalError as e:
        if "duplicate column" in str(e).lower():
            log("  - host_scope_status already exists")
        else:
            raise

    # Backfill based on phylum + host_type
    cur.execute("""
        UPDATE crustacean_hosts
        SET host_scope_status = 'excluded_lab_host'
        WHERE host_type = 'technical_host' OR phylum = 'Proteobacteria'
    """)
    n1 = cur.rowcount
    log(f"  excluded_lab_host: {n1}")

    cur.execute("""
        UPDATE crustacean_hosts
        SET host_scope_status = 'excluded_vertebrate'
        WHERE phylum = 'Chordata'
    """)
    n2 = cur.rowcount
    log(f"  excluded_vertebrate: {n2}")

    cur.execute("""
        UPDATE crustacean_hosts
        SET host_scope_status = 'excluded_environmental'
        WHERE phylum = 'Environmental' OR host_type = 'not_species_level'
          OR scientific_name IN ('plankton', 'Bioflake', 'small fish', 'crustacean mix')
    """)
    n3 = cur.rowcount
    log(f"  excluded_environmental: {n3}")

    cur.execute("""
        UPDATE crustacean_hosts
        SET host_scope_status = 'target_crustacean'
        WHERE phylum = 'Arthropoda' AND host_type IN ('crustacean', NULL)
          AND host_scope_status = 'needs_review'
    """)
    n4 = cur.rowcount
    log(f"  target_crustacean: {n4}")

    cur.execute("""
        UPDATE crustacean_hosts
        SET host_scope_status = 'target_mollusk'
        WHERE phylum = 'Mollusca' AND host_scope_status = 'needs_review'
    """)
    n5 = cur.rowcount
    log(f"  target_mollusk: {n5}")

    cur.execute("""
        UPDATE crustacean_hosts
        SET host_scope_status = 'review_manual'
        WHERE host_scope_status = 'needs_review'
    """)
    n6 = cur.rowcount
    log(f"  review_manual: {n6}")

    # ===================================================================
    # TASK 2: Fix host_type for non-crustacean biological hosts
    # ===================================================================
    log("\nTask 2: Updating host_type for non-crustacean hosts...")

    # Vertebrates tagged as non_crustacean
    cur.execute("""
        UPDATE crustacean_hosts
        SET host_type = 'vertebrate'
        WHERE phylum = 'Chordata' AND host_type = 'non_crustacean'
    """)
    nv = cur.rowcount
    log(f"  Updated to vertebrate: {nv}")

    # Mollusks tagged as non_crustacean
    cur.execute("""
        UPDATE crustacean_hosts
        SET host_type = 'mollusk'
        WHERE phylum = 'Mollusca' AND host_type = 'non_crustacean'
    """)
    nm = cur.rowcount
    log(f"  Updated to mollusk: {nm}")

    # Summary by scope_status
    log("\n  Host scope status summary:")
    for row in cur.execute("""
        SELECT host_scope_status, COUNT(*) FROM crustacean_hosts
        GROUP BY host_scope_status ORDER BY COUNT(*) DESC
    """):
        log(f"    {row[0]}: {row[1]}")

    # ===================================================================
    # TASK 3: Create/update views that depend on new fields
    # ===================================================================
    log("\nTask 3: Creating expansion tracking views...")

    cur.execute("""
        CREATE VIEW IF NOT EXISTS v_host_scope_audit AS
        SELECT
            h.host_id,
            h.scientific_name,
            h.taxon_order,
            h.host_group,
            h.host_type,
            h.phylum,
            h.class,
            h.host_scope_status,
            COUNT(ir.record_id) as infection_record_count
        FROM crustacean_hosts h
        LEFT JOIN infection_records ir ON h.host_id = ir.host_id
        GROUP BY h.host_id
        ORDER BY h.host_scope_status, h.phylum, h.scientific_name
    """)

    cur.execute("""
        CREATE VIEW IF NOT EXISTS v_expansion_readiness AS
        SELECT 'schema_version' as metric,
               'v2.0-aquatic-expansion' as value, 'ready' as status
        UNION ALL
        SELECT 'phylum_coverage',
               GROUP_CONCAT(DISTINCT phylum),
               CASE WHEN COUNT(DISTINCT phylum) >= 3 THEN 'multi_phylum' ELSE 'limited' END
        FROM crustacean_hosts WHERE phylum IS NOT NULL
        UNION ALL
        SELECT 'target_host_phyla',
               GROUP_CONCAT(DISTINCT phylum),
               'active'
        FROM crustacean_hosts
        WHERE host_scope_status IN ('target_crustacean', 'target_mollusk')
        UNION ALL
        SELECT 'host_association_method_implemented',
               COUNT(DISTINCT host_association_method),
               'active'
        FROM infection_records
        UNION ALL
        SELECT 'discovery_context_implemented',
               COUNT(DISTINCT discovery_context),
               'active'
        FROM virus_master
    """)

    log("  Views created/updated")

    # ===================================================================
    # TASK 4: Audit references
    # ===================================================================
    log("\nTask 4: Auditing references...")

    total_refs = cur.execute("SELECT COUNT(*) FROM ref_literatures").fetchone()[0]
    traceless = cur.execute("""
        SELECT COUNT(*) FROM ref_literatures
        WHERE (pmid IS NULL OR pmid = '') AND (doi IS NULL OR doi = '')
    """).fetchone()[0]
    with_pmid = cur.execute(
        "SELECT COUNT(*) FROM ref_literatures WHERE pmid IS NOT NULL AND pmid != ''"
    ).fetchone()[0]
    with_doi = cur.execute(
        "SELECT COUNT(*) FROM ref_literatures WHERE doi IS NOT NULL AND doi != ''"
    ).fetchone()[0]

    log(f"  Total references: {total_refs}")
    log(f"  With PMID: {with_pmid}")
    log(f"  With DOI: {with_doi}")
    log(f"  Traceless (no PMID AND no DOI): {traceless}")

    # List traceless refs for manual fix
    if traceless > 0:
        traceless_list = cur.execute("""
            SELECT reference_id, title, authors, journal, year
            FROM ref_literatures
            WHERE (pmid IS NULL OR pmid = '') AND (doi IS NULL OR doi = '')
            LIMIT 20
        """).fetchall()
        log("  First 20 traceless refs:")
        for r in traceless_list:
            title = (r[1] or '')[:80]
            journal = (r[3] or '')[:30]
            log(f"    #{r[0]} [{journal} {r[4]}] {title}")

    # ===================================================================
    # TASK 5: Evidence coverage audit
    # ===================================================================
    log("\nTask 5: Auditing evidence coverage...")

    cur.execute("""
        SELECT COUNT(DISTINCT vm.master_id) as total_species,
               COUNT(DISTINCT CASE WHEN er.evidence_id IS NOT NULL THEN vm.master_id END) as with_evidence,
               ROUND(100.0 * COUNT(DISTINCT CASE WHEN er.evidence_id IS NOT NULL THEN vm.master_id END) /
                 NULLIF(COUNT(DISTINCT vm.master_id), 0), 1) as pct
        FROM virus_master vm
        LEFT JOIN evidence_records er ON vm.master_id = er.virus_master_id
    """)
    total_ev, with_ev, pct_ev = cur.fetchone()
    log(f"  Species with evidence: {with_ev}/{total_ev} ({pct_ev}%)")

    # By discovery_context
    cur.execute("""
        SELECT discovery_context,
               COUNT(*) as species,
               COUNT(DISTINCT CASE WHEN er.evidence_id IS NOT NULL THEN vm.master_id END) as with_evidence
        FROM virus_master vm
        LEFT JOIN evidence_records er ON vm.master_id = er.virus_master_id
        GROUP BY discovery_context ORDER BY species DESC
    """)
    for ctx, sp, ev in cur.fetchall():
        log(f"    {ctx}: {ev}/{sp}")

    # ===================================================================
    # TASK 6: Export baseline
    # ===================================================================
    log("\nTask 6: Creating expansion baseline...")

    # Hosts by phylum (only target scope)
    hosts_by_phylum = {}
    for row in cur.execute("""
        SELECT COALESCE(phylum, 'Unknown'), COUNT(*)
        FROM crustacean_hosts
        WHERE host_scope_status IN ('target_crustacean', 'target_mollusk')
        GROUP BY phylum
    """):
        hosts_by_phylum[row[0]] = row[1]

    baseline = {
        "timestamp": datetime.now().isoformat(),
        "database_size_mb": round(os.path.getsize(DB_PATH) / 1024 / 1024, 1),
        "virus_species": cur.execute("SELECT COUNT(*) FROM virus_master").fetchone()[0],
        "viral_isolates": cur.execute("SELECT COUNT(*) FROM viral_isolates").fetchone()[0],
        "viral_proteins": cur.execute("SELECT COUNT(*) FROM viral_proteins").fetchone()[0],
        "target_hosts": sum(hosts_by_phylum.values()),
        "hosts_by_phylum": hosts_by_phylum,
        "infection_records": {
            "total": cur.execute("SELECT COUNT(*) FROM infection_records").fetchone()[0],
            "by_method": dict(cur.execute("""
                SELECT host_association_method, COUNT(*)
                FROM infection_records GROUP BY host_association_method
            """).fetchall())
        },
        "evidence_coverage": {
            "species_with_evidence": with_ev,
            "total_species": total_ev,
            "pct": pct_ev
        },
        "literature": {
            "total": total_refs,
            "with_pmid": with_pmid,
            "with_doi": with_doi,
            "traceless": traceless
        },
        "virus_by_discovery": dict(cur.execute("""
            SELECT discovery_context, COUNT(*) FROM virus_master
            GROUP BY discovery_context
        """).fetchall())
    }

    baseline_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "expansion_baseline.json"
    )
    with open(baseline_path, 'w') as f:
        json.dump(baseline, f, indent=2, ensure_ascii=False)

    log(f"\n  === Pre-Expansion Baseline ===")
    log(f"  Database size:     {baseline['database_size_mb']} MB")
    log(f"  Virus species:     {baseline['virus_species']}")
    log(f"  Viral isolates:    {baseline['viral_isolates']}")
    log(f"  Viral proteins:    {baseline['viral_proteins']}")
    log(f"  Target hosts:      {baseline['target_hosts']} ({len(baseline['hosts_by_phylum'])} phyla)")
    for phylum, count in baseline['hosts_by_phylum'].items():
        log(f"    - {phylum}: {count}")
    log(f"  Infection records: {baseline['infection_records']['total']}")
    for method, count in baseline['infection_records']['by_method'].items():
        log(f"    - {method}: {count}")
    log(f"  Evidence coverage: {baseline['evidence_coverage']['pct']}%")
    log(f"  Literature refs:   {baseline['literature']['total']}")
    log(f"    Verifiable: {baseline['literature']['with_pmid'] + baseline['literature']['with_doi'] - baseline['literature']['total']}")
    log(f"    Traceless:  {baseline['literature']['traceless']}")
    log(f"  Baseline saved:    {baseline_path}")

    conn.commit()
    conn.close()

    log("\n=== Optimization complete ===")
    log("Database ready for Phase 1: Mollusca virus data import")

if __name__ == "__main__":
    main()
