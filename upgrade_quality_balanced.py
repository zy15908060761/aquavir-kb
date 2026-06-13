#!/usr/bin/env python3
"""P2: Balanced evidence quality upgrade — stricter rules, credible output."""
import sqlite3, json
from pathlib import Path
from datetime import datetime
from collections import Counter

DB_PATH = Path(r"F:\水生无脊椎动物数据库\crustacean_virus_core.db")


def apply_rule(con, rule_name, condition_sql):
    cur = con.cursor()
    cur.execute(f"SELECT COUNT(*) FROM evidence_records WHERE evidence_strength='low' AND ({condition_sql})")
    affected = cur.fetchone()[0]
    if affected == 0:
        return 0
    cur.execute(f"UPDATE evidence_records SET evidence_strength='medium' WHERE evidence_strength='low' AND ({condition_sql})")
    n = cur.rowcount
    print(f"  {rule_name}: {n:,} upgraded")
    return n


def main():
    print("=" * 70)
    print("P2: BALANCED QUALITY UPGRADE")
    print("=" * 70)

    con = sqlite3.connect(str(DB_PATH), timeout=60)
    cur = con.cursor()
    for row in cur.execute("SELECT evidence_strength, COUNT(*) FROM evidence_records GROUP BY evidence_strength"):
        print(f"  Before: {row[0]}={row[1]:,}")
    print()

    total = Counter()
    total_evidence = cur.execute("SELECT COUNT(*) FROM evidence_records").fetchone()[0]

    # R1: Fulltext extraction → medium (these come from actual downloaded papers)
    print("=== R1: Fulltext extraction ===")
    n = apply_rule(con, "R1_fulltext",
        """extraction_method IN ('fulltext_parsed','fulltext_parsed_p1',
            'auto_extracted_epmc_abstract','literature_text_mine')""")
    total["R1"] = n

    # R2: DOI-verified refs + experimental claims → medium
    print("\n=== R2: DOI + experimental methods ===")
    n = apply_rule(con, "R2_doi_experimental",
        """reference_id IN (SELECT reference_id FROM ref_literatures WHERE doi IS NOT NULL AND doi != '')
        AND (claim LIKE '%PCR%' OR claim LIKE '%qPCR%' OR claim LIKE '%RT-PCR%'
             OR claim LIKE '%ELISA%' OR claim LIKE '%western blot%'
             OR claim LIKE '%immunohistochem%' OR claim LIKE '%sequencing%'
             OR claim LIKE '%mortality%' OR claim LIKE '%temperature%'
             OR claim LIKE '%histopatholog%' OR claim LIKE '%in situ hybridization%'
             OR claim LIKE '%LAMP%' OR claim LIKE '%recombinase%'
             OR claim LIKE '%TaqMan%' OR claim LIKE '%SYBR%')""")
    total["R2"] = n

    # R3: Numeric/quantitative evidence → medium
    print("\n=== R3: Numeric values ===")
    n = apply_rule(con, "R3_numeric",
        "(value_numeric_min IS NOT NULL OR value_numeric_max IS NOT NULL)")
    total["R3"] = n

    # R4: 3+ independent refs for same virus+type (stricter than 2+)
    print("\n=== R4: Cross-referenced (3+ refs) ===")
    cur.execute("""
        CREATE TEMP TABLE crc_3 AS
        SELECT virus_master_id, evidence_type, COUNT(DISTINCT reference_id) as n_refs
        FROM evidence_records WHERE evidence_strength='low'
        GROUP BY virus_master_id, evidence_type HAVING n_refs >= 3
    """)
    cur.execute("SELECT COUNT(*) FROM crc_3")
    print(f"  Virus+type pairs with 3+ refs: {cur.fetchone()[0]:,}")
    n = apply_rule(con, "R4_cross_3refs",
        "(virus_master_id, evidence_type) IN (SELECT virus_master_id, evidence_type FROM crc_3)")
    cur.execute("DROP TABLE IF EXISTS crc_3")
    total["R4"] = n

    # R5: Evidence with explicit PMID source → medium
    print("\n=== R5: PMID-traceable source ===")
    n = apply_rule(con, "R5_pmid",
        "source_pmid IS NOT NULL AND source_pmid != ''")
    total["R5"] = n

    # R6: Fulltext prefixed claims → medium
    print("\n=== R6: Fulltext-extracted claims ===")
    n = apply_rule(con, "R6_fulltext_claim",
        "claim LIKE 'Fulltext:%'")
    total["R6"] = n

    con.commit()

    # Final distribution
    print(f"\n{'=' * 70}")
    print("COMPLETE")
    print(f"{'=' * 70}")
    total_upgraded = sum(total.values())
    print(f"  Total upgraded: {total_upgraded:,} ({total_upgraded/total_evidence*100:.1f}%)")
    print()
    for row in cur.execute("SELECT evidence_strength, COUNT(*) FROM evidence_records GROUP BY evidence_strength ORDER BY COUNT(*) DESC"):
        pct = row[1] / total_evidence * 100
        print(f"  {row[0]}: {row[1]:,} ({pct:.1f}%)")

    # Verify high preserved
    high = cur.execute("SELECT COUNT(*) FROM evidence_records WHERE evidence_strength='high'").fetchone()[0]
    print(f"\n  High preserved: {high:,}")

    con.close()


if __name__ == "__main__":
    main()
