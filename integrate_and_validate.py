#!/usr/bin/env python3
"""
Integrate and validate extracted evidence:
1. Promote high-confidence evidence from fulltext extraction
2. Cross-link evidence records to virus+host tables
3. Generate quality report
4. Update coverage metrics
"""

import json
import sqlite3
from pathlib import Path
from datetime import datetime
from collections import Counter, defaultdict

DB_PATH = Path(r"F:\甲壳动物数据库\crustacean_virus_core.db")
REPORT_DIR = Path(r"F:\甲壳动物数据库\downloads\fulltext_extraction")
REPORT_DIR.mkdir(parents=True, exist_ok=True)


def main():
    con = sqlite3.connect(str(DB_PATH), timeout=60)
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    print("=" * 70)
    print("Evidence Integration & Validation Report")
    print(f"Generated: {datetime.now().isoformat()[:19]}")
    print("=" * 70)

    # 1. Database overview
    print("\n--- 1. DATABASE OVERVIEW ---")
    cur.execute("SELECT COUNT(*) FROM virus_master")
    n_virus = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM ref_literatures")
    n_refs = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM evidence_records")
    n_evidence = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM literature_fulltext_sources WHERE status = 'downloaded'")
    n_downloaded = cur.fetchone()[0]
    cur.execute("SELECT COUNT(DISTINCT reference_id) FROM literature_fulltext_sources WHERE status = 'downloaded'")
    n_unique_downloaded = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM literature_fulltext_sections")
    n_sections = cur.fetchone()[0]
    cur.execute("SELECT COUNT(DISTINCT reference_id) FROM literature_fulltext_sections")
    n_section_refs = cur.fetchone()[0]

    print(f"  Virus species: {n_virus}")
    print(f"  Literature references: {n_refs}")
    print(f"  Evidence records: {n_evidence}")
    print(f"  Downloaded fulltext: {n_unique_downloaded} unique refs ({n_downloaded} records)")
    print(f"  Extracted sections: {n_sections} from {n_section_refs} refs")

    # 2. Evidence type breakdown
    print("\n--- 2. EVIDENCE TYPE BREAKDOWN ---")
    cur.execute("""
        SELECT evidence_type, COUNT(*) as cnt,
               COUNT(DISTINCT virus_master_id) as unique_viruses,
               COUNT(DISTINCT reference_id) as unique_refs
        FROM evidence_records
        WHERE evidence_type IS NOT NULL
        GROUP BY evidence_type
        ORDER BY cnt DESC
    """)
    for row in cur.fetchall():
        print(f"  {row['evidence_type']}: {row['cnt']} ({row['unique_viruses']} viruses, {row['unique_refs']} refs)")

    # 3. Evidence strength distribution
    print("\n--- 3. EVIDENCE QUALITY ---")
    cur.execute("""
        SELECT evidence_strength, COUNT(*) FROM evidence_records
        GROUP BY evidence_strength ORDER BY COUNT(*) DESC
    """)
    for row in cur.fetchall():
        print(f"  {row[0]}: {row[1]}")

    cur.execute("""
        SELECT extraction_method, COUNT(*) FROM evidence_records
        WHERE extraction_method IS NOT NULL
        GROUP BY extraction_method ORDER BY COUNT(*) DESC
    """)
    print("\n  Extraction method:")
    for row in cur.fetchall():
        print(f"    {row[0]}: {row[1]}")

    # 4. Coverage per virus (top/bottom)
    print("\n--- 4. VIRUS EVIDENCE COVERAGE ---")
    cur.execute("""
        SELECT vm.canonical_name, vm.master_id,
               COUNT(er.evidence_id) as ev_count,
               COUNT(DISTINCT er.reference_id) as ref_count,
               COUNT(DISTINCT er.evidence_type) as type_count
        FROM virus_master vm
        LEFT JOIN evidence_records er ON vm.master_id = er.virus_master_id
        GROUP BY vm.master_id
        ORDER BY ev_count DESC
        LIMIT 15
    """)
    print("  Top 15 viruses by evidence:")
    for row in cur.fetchall():
        name = (row['canonical_name'] or f"ID:{row['master_id']}")[:55]
        print(f"    {name}: {row['ev_count']} evidence, {row['ref_count']} refs, {row['type_count']} types")

    cur.execute("""
        SELECT vm.canonical_name, vm.master_id,
               COUNT(er.evidence_id) as ev_count
        FROM virus_master vm
        LEFT JOIN evidence_records er ON vm.master_id = er.virus_master_id
        GROUP BY vm.master_id
        HAVING ev_count = 0
        ORDER BY vm.canonical_name
    """)
    zero_ev = cur.fetchall()
    print(f"\n  Viruses with ZERO evidence: {len(zero_ev)}/{n_virus}")
    print(f"  Coverage: {n_virus - len(zero_ev)}/{n_virus} = {(n_virus - len(zero_ev))/n_virus*100:.1f}%")
    if len(zero_ev) <= 20:
        for row in zero_ev:
            print(f"    - {row['canonical_name']}")

    # 5. Reference-fulltext coverage gap
    print("\n--- 5. FULLTEXT COVERAGE GAP ---")
    n_doi = cur.execute("SELECT COUNT(*) FROM ref_literatures WHERE doi IS NOT NULL AND doi != ''").fetchone()[0]
    print(f"  Refs with DOI: {n_doi}")
    print(f"  Refs with fulltext: {n_unique_downloaded} ({n_unique_downloaded/n_refs*100:.1f}%)")
    print(f"  Refs with sections: {n_section_refs} ({n_section_refs/n_refs*100:.1f}%)")

    # OA status summary
    cur.execute("""
        SELECT oa_status, COUNT(DISTINCT reference_id)
        FROM literature_fulltext_sources
        GROUP BY oa_status
        ORDER BY COUNT(*) DESC
        LIMIT 10
    """)
    print("\n  OA status distribution:")
    for row in cur.fetchall():
        print(f"    {row[0]}: {row[1]} refs")

    # 6. Cross-link integrity
    print("\n--- 6. CROSS-LINK INTEGRITY ---")
    cur.execute("""
        SELECT COUNT(*) FROM evidence_records er
        WHERE er.reference_id IS NOT NULL
          AND er.reference_id NOT IN (SELECT reference_id FROM ref_literatures)
    """)
    orphan_refs = cur.fetchone()[0]
    print(f"  Orphan evidence (ref missing): {orphan_refs}")

    cur.execute("""
        SELECT COUNT(*) FROM evidence_records er
        WHERE er.virus_master_id IS NOT NULL
          AND er.virus_master_id NOT IN (SELECT master_id FROM virus_master)
    """)
    orphan_virus = cur.fetchone()[0]
    print(f"  Orphan evidence (virus missing): {orphan_virus}")

    # 7. Literature with most evidence types per virus
    print("\n--- 7. HIGHEST-VALUE REFERENCES (multi-evidence-type) ---")
    cur.execute("""
        SELECT rl.title, rl.year, COUNT(DISTINCT er.evidence_type) as types,
               COUNT(er.evidence_id) as total_ev,
               GROUP_CONCAT(DISTINCT er.evidence_type) as type_list
        FROM evidence_records er
        JOIN ref_literatures rl ON er.reference_id = rl.reference_id
        WHERE er.extraction_method = 'fulltext_parsed'
        GROUP BY er.reference_id
        HAVING types >= 3
        ORDER BY total_ev DESC
        LIMIT 20
    """)
    for row in cur.fetchall():
        print(f"  [{row['year']}] {(row['title'] or '')[:70]}...")
        print(f"    {row['types']} types: {row['type_list']} ({row['total_ev']} records)")

    # 8. Generate quality report JSON
    report = {
        "timestamp": datetime.now().isoformat(),
        "overview": {
            "virus_species": n_virus,
            "literature_refs": n_refs,
            "evidence_records": n_evidence,
            "downloaded_fulltext_refs": n_unique_downloaded,
            "extracted_section_refs": n_section_refs,
        },
        "coverage": {
            "viruses_with_evidence": n_virus - len(zero_ev),
            "total_viruses": n_virus,
            "coverage_pct": round((n_virus - len(zero_ev)) / n_virus * 100, 1),
        },
    }
    report_path = REPORT_DIR / f"validation_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n  Report saved: {report_path}")

    con.close()
    print("\nDone.")


if __name__ == "__main__":
    main()
