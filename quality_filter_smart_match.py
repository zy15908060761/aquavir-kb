#!/usr/bin/env python3
"""
Quality filter for smart match evidence:
- Downgrade evidence based on single-token matches (too generic)
- Keep multi-token matches (2+ tokens in same sentence) as medium
- Remove single-token matches for generic words like 'shrimp', 'virus', 'crab'
"""

import re, sqlite3, shutil
from pathlib import Path
from collections import Counter

DB_PATH = Path(r"F:\甲壳动物数据库\crustacean_virus_core.db")

# Generic tokens that shouldn't count as a virus match alone
GENERIC_WORDS = {
    'virus', 'viruses', 'shrimp', 'crab', 'crayfish', 'lobster', 'prawn',
    'like', 'associated', 'novel', 'identified', 'isolate', 'sequence',
    'genome', 'rna', 'dna', 'protein', 'gene', 'host', 'infection',
    'disease', 'syndrome', 'white', 'spot', 'yellow', 'head', 'red',
    'blue', 'green', 'black', 'tiger', 'king', 'giant', 'freshwater',
    'marine', 'aquatic', 'china', 'beihai', 'wenzhou', 'qianjiang',
    'sanya', 'hangzhou', 'fushun', 'hubei', 'avon', 'heathcote',
    'estuary', 'brine', 'grass', 'pink', 'pacific', 'american',
    'australian', 'european', 'asian', 'ornamental', 'ornate',
    'mangrove', 'circul', 'penaeus', 'litopenaeus', 'macrobrachium',
    'cherax', 'procambarus', 'callinectes', 'portunus', 'scylla',
    'eriocheir', 'crassostrea', 'mytilus', 'haliotis',
}


def main():
    backup = DB_PATH.with_suffix(".db.pre_quality_filter")
    shutil.copy2(DB_PATH, backup)
    print(f"Backup: {backup}")

    con = sqlite3.connect(DB_PATH)
    con.execute("PRAGMA busy_timeout = 60000")
    cur = con.cursor()

    # Check current state
    cur.execute("SELECT COUNT(*) FROM evidence_records WHERE extraction_method = 'smart_match_re_extract'")
    total_smart = cur.fetchone()[0]
    print(f"Smart match evidence: {total_smart}")

    cur.execute("SELECT evidence_strength, COUNT(*) FROM evidence_records GROUP BY evidence_strength")
    print("Before filter:")
    for r in cur.fetchall():
        print(f"  {r[0]}: {r[1]}")

    # Analyze evidence: how many claims contain only generic words?
    print("\nAnalyzing claim quality...")
    cur.execute("""
        SELECT evidence_id, claim, virus_master_id FROM evidence_records
        WHERE extraction_method = 'smart_match_re_extract'
    """)

    downgraded = 0
    kept = 0
    removed = 0
    virus_impact = Counter()

    for ev_id, claim, vm_id in cur.fetchall():
        claim_lower = (claim or '').lower()

        # Count non-generic content words in claim
        words = set(re.findall(r'[a-zA-Z0-9]+', claim_lower))
        specific_words = words - GENERIC_WORDS

        if len(specific_words) >= 3:
            # Has enough specific content — keep as medium
            kept += 1
        elif len(specific_words) >= 1:
            # Only 1-2 specific words — downgrade to low
            con.execute("""
                UPDATE evidence_records SET evidence_strength = 'low'
                WHERE evidence_id = ?
            """, (ev_id,))
            downgraded += 1
            virus_impact[vm_id] += 1
        else:
            # All generic words — remove entirely
            con.execute("DELETE FROM evidence_records WHERE evidence_id = ?", (ev_id,))
            removed += 1
            virus_impact[vm_id] += 1

    con.commit()

    # Also apply: for evidence where virus name has < 2 unique words matching the claim, downgrade
    # Load virus names
    cur.execute("SELECT master_id, canonical_name FROM virus_master")
    virus_names = {r[0]: (r[1] or '').lower() for r in cur.fetchall()}

    additional_downgrade = 0
    cur.execute("""
        SELECT evidence_id, virus_master_id, claim FROM evidence_records
        WHERE extraction_method = 'smart_match_re_extract'
        AND evidence_strength = 'medium'
    """)
    for ev_id, vm_id, claim in cur.fetchall():
        if vm_id not in virus_names:
            continue
        vname = virus_names[vm_id]
        claim_lower = (claim or '').lower()

        # Check if at least 2 significant words from virus name appear in claim
        vname_words = set(re.findall(r'[a-zA-Z0-9]+', vname)) - GENERIC_WORDS
        matching_words = [w for w in vname_words if w.lower() in claim_lower]

        if len(vname_words) >= 2 and len(matching_words) < 2:
            # Virus name has specific words but they don't both appear in the claim context
            con.execute("""
                UPDATE evidence_records SET evidence_strength = 'low'
                WHERE evidence_id = ?
            """, (ev_id,))
            additional_downgrade += 1

    con.commit()

    # Final state
    cur.execute("SELECT evidence_strength, COUNT(*) FROM evidence_records GROUP BY evidence_strength")
    print("\nAfter filter:")
    for r in cur.fetchall():
        print(f"  {r[0]}: {r[1]}")

    print(f"\nFilter actions:")
    print(f"  Kept as medium: {kept}")
    print(f"  Downgraded to low: {downgraded}")
    print(f"  Removed (all generic): {removed}")
    print(f"  Additional downgrade (weak name match): {additional_downgrade}")

    # Coverage
    cur.execute("SELECT COUNT(DISTINCT virus_master_id) FROM evidence_records WHERE virus_master_id IS NOT NULL")
    cov = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM virus_master")
    tv = cur.fetchone()[0]
    print(f"\nCoverage: {cov}/{tv} = {cov/tv*100:.1f}%")

    # Low-evidence crustaceans
    cur.execute("""
    SELECT COUNT(*) FROM (
        SELECT vm.master_id, COUNT(er.evidence_id) as cnt
        FROM virus_master vm LEFT JOIN evidence_records er ON vm.master_id = er.virus_master_id
        WHERE vm.host_phylum LIKE '%Arthropod%'
        GROUP BY vm.master_id HAVING cnt BETWEEN 1 AND 5
    )
    """)
    low = cur.fetchone()[0]
    print(f"Low-evidence crustaceans: {low}")

    cur.execute("SELECT COUNT(*) FROM evidence_records")
    print(f"Total evidence: {cur.fetchone()[0]}")

    con.close()


if __name__ == "__main__":
    main()
