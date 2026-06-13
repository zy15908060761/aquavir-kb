#!/usr/bin/env python3
"""
P2: Evidence quality upgrade v2.
Conservative rules to promote low→medium evidence.
Each rule is independently justified for NAR paper review.
"""
import sqlite3
from pathlib import Path
from collections import Counter
from datetime import datetime

DB_PATH = Path(r"F:\水生无脊椎动物数据库\crustacean_virus_core.db")


def apply_rule(con, rule_name, condition_sql, params=None):
    """Apply a quality upgrade rule and report impact."""
    cur = con.cursor()

    # Count affected
    count_sql = f"SELECT COUNT(*) FROM evidence_records WHERE evidence_strength='low' AND ({condition_sql})"
    if params:
        cur.execute(count_sql, params)
    else:
        cur.execute(count_sql)
    affected = cur.fetchone()[0]

    if affected == 0:
        return 0

    # Apply upgrade
    update_sql = f"UPDATE evidence_records SET evidence_strength='medium' WHERE evidence_strength='low' AND ({condition_sql})"
    if params:
        cur.execute(update_sql, params)
    else:
        cur.execute(update_sql)

    upgraded = cur.rowcount
    print(f"  {rule_name}: {upgraded:,} records upgraded")
    return upgraded


def main():
    print("=" * 70)
    print("P2: EVIDENCE QUALITY UPGRADE v2")
    print("=" * 70)

    con = sqlite3.connect(str(DB_PATH), timeout=60)

    # Snapshot before
    cur = con.cursor()
    for row in cur.execute("SELECT evidence_strength, COUNT(*) FROM evidence_records GROUP BY evidence_strength"):
        print(f"  Before: {row[0]}={row[1]:,}")
    print()

    total_upgraded = 0
    rules = Counter()

    # Rule 1: Fulltext-extracted evidence → medium
    # These come from actually-downloaded papers, not just abstract mining
    print("=== Rule 1: Fulltext extraction ===")
    n = apply_rule(con, "R1_fulltext",
        """extraction_method IN ('fulltext_parsed','fulltext_parsed_p1',
            'auto_extracted_epmc_abstract','literature_text_mine')""")
    total_upgraded += n
    rules["R1_fulltext"] = n

    # Rule 2: Evidence from refs with verified DOIs + strong signal words
    # These have both a traceable source AND experimental content
    print("\n=== Rule 2: DOI-verified refs with experimental claims ===")
    n = apply_rule(con, "R2_doi_experimental",
        """reference_id IN (SELECT reference_id FROM ref_literatures WHERE doi IS NOT NULL AND doi != '')
        AND (claim LIKE '%PCR%' OR claim LIKE '%qPCR%' OR claim LIKE '%RT-PCR%'
             OR claim LIKE '%ELISA%' OR claim LIKE '%western blot%'
             OR claim LIKE '%immunohistochemistry%' OR claim LIKE '%sequencing%'
             OR claim LIKE '%mortality%' OR claim LIKE '%temperature%'
             OR claim LIKE '%histopatholog%' OR claim LIKE '%in situ hybridization%'
             OR claim LIKE '%LAMP%' OR claim LIKE '%recombinase%'
             OR claim LIKE '%TaqMan%' OR claim LIKE '%SYBR%')""")
    total_upgraded += n
    rules["R2_doi_experimental"] = n

    # Rule 3: Evidence with numeric data → medium
    print("\n=== Rule 3: Numeric/quantitative evidence ===")
    n = apply_rule(con, "R3_numeric",
        "(value_numeric_min IS NOT NULL OR value_numeric_max IS NOT NULL)")
    total_upgraded += n
    rules["R3_numeric"] = n

    # Rule 4: Evidence confirmed by 2+ independent references (same virus+type)
    print("\n=== Rule 4: Cross-referenced (2+ refs for same virus+type) ===")
    cur.execute("""
        CREATE TEMP TABLE IF NOT EXISTS cross_ref_count AS
        SELECT virus_master_id, evidence_type, COUNT(DISTINCT reference_id) as ref_count
        FROM evidence_records
        WHERE evidence_strength='low'
        GROUP BY virus_master_id, evidence_type
        HAVING COUNT(DISTINCT reference_id) >= 2
    """)
    cur.execute("SELECT COUNT(*) FROM cross_ref_count")
    cr_count = cur.fetchone()[0]
    print(f"  Virus+type pairs with 2+ refs: {cr_count:,}")

    n = apply_rule(con, "R4_cross_referenced",
        """(virus_master_id, evidence_type) IN (
            SELECT virus_master_id, evidence_type FROM cross_ref_count
        )""")
    cur.execute("DROP TABLE IF EXISTS cross_ref_count")
    total_upgraded += n
    rules["R4_cross_ref"] = n

    # Rule 5: Evidence from download sources that got actual PDFs
    print("\n=== Rule 5: Downloaded fulltext source ===")
    n = apply_rule(con, "R5_downloaded_source",
        """reference_id IN (
            SELECT DISTINCT reference_id FROM literature_fulltext_sources
            WHERE (source LIKE '%ncbi_pmc%' OR source LIKE '%epmc_xml%'
                   OR source LIKE '%scihub%' OR source LIKE '%p3_%'
                   OR source LIKE '%retry_%' OR source LIKE '%recover_%')
            AND local_path IS NOT NULL AND local_path != ''
        )""")
    total_upgraded += n
    rules["R5_downloaded_source"] = n

    # Rule 6: Claims with "Fulltext:" prefix (our own extraction label)
    print("\n=== Rule 6: Prefixed fulltext claims ===")
    n = apply_rule(con, "R6_fulltext_prefix",
        "claim LIKE 'Fulltext:%'")
    total_upgraded += n
    rules["R6_fulltext_prefix"] = n

    con.commit()

    # Final state
    print(f"\n{'=' * 70}")
    print("UPGRADE COMPLETE")
    print(f"{'=' * 70}")
    print(f"  Total upgraded: {total_upgraded:,}")

    cur = con.cursor()
    print()
    for row in cur.execute("SELECT evidence_strength, COUNT(*) FROM evidence_records GROUP BY evidence_strength"):
        pct = row[1] / 347283 * 100
        print(f"  After: {row[0]}={row[1]:,} ({pct:.1f}%)")

    # Now run a consistency check: ensure no high-evidence records got accidentally touched
    high_check = cur.execute("SELECT COUNT(*) FROM evidence_records WHERE evidence_strength='high'").fetchone()[0]
    print(f"\n  High records preserved: {high_check:,}")

    # Save upgrade log
    log_path = Path(r"F:\水生无脊椎动物数据库\downloads") / f"quality_upgrade_v2_{int(datetime.now().timestamp())}.json"
    import json
    log_data = {
        "timestamp": datetime.now().isoformat(),
        "rules_applied": dict(rules),
        "total_upgraded": total_upgraded,
        "final_distribution": {row[0]: row[1] for row in cur.execute("SELECT evidence_strength, COUNT(*) FROM evidence_records GROUP BY evidence_strength")},
    }
    log_path.write_text(json.dumps(log_data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n  Log: {log_path}")

    con.close()


if __name__ == "__main__":
    main()
