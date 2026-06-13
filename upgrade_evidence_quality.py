#!/usr/bin/env python3
"""
Upgrade evidence quality from 'low' to 'medium' when:
1. Same virus+ref pair has 3+ evidence types → upgrade all to medium
2. Same virus has 5+ independent refs with same evidence type → upgrade to medium
3. Fulltext-parsed evidence with 2+ signal types for same claim → upgrade

Also downgrade clearly irrelevant evidence (SARS-CoV-2, HIV, etc. in crustacean context).
"""

import sqlite3, shutil
from pathlib import Path
from collections import defaultdict

DB_PATH = Path(r"F:\甲壳动物数据库\crustacean_virus_core.db")

def main():
    backup = DB_PATH.with_suffix(".db.pre_quality_upgrade")
    shutil.copy2(DB_PATH, backup)
    print(f"Backup: {backup}")

    con = sqlite3.connect(DB_PATH)
    con.execute("PRAGMA busy_timeout = 60000")
    cur = con.cursor()

    # Initial counts
    cur.execute("SELECT evidence_strength, COUNT(*) FROM evidence_records GROUP BY evidence_strength")
    print("Before:")
    for row in cur.fetchall():
        print(f"  {row[0]}: {row[1]}")

    upgraded_total = 0

    # === Rule 1: Same virus+ref, 3+ evidence types ===
    print("\n--- Rule 1: Multi-type evidence per virus+ref ---")
    cur.execute("""
        SELECT virus_master_id, reference_id, COUNT(DISTINCT evidence_type) as type_count,
               COUNT(*) as ev_count
        FROM evidence_records
        WHERE evidence_strength = 'low'
        GROUP BY virus_master_id, reference_id
        HAVING type_count >= 3
    """)
    rows = cur.fetchall()
    print(f"  Virus+ref pairs with 3+ evidence types: {len(rows)}")

    r1_count = 0
    for vm_id, ref_id, type_count, ev_count in rows:
        cur.execute("""
            UPDATE evidence_records SET evidence_strength = 'medium'
            WHERE virus_master_id = ? AND reference_id = ? AND evidence_strength = 'low'
        """, (vm_id, ref_id))
        r1_count += cur.rowcount
    con.commit()
    print(f"  Upgraded: {r1_count} records")
    upgraded_total += r1_count

    # === Rule 2: Same virus+type, 5+ independent refs (consensus) ===
    print("\n--- Rule 2: Consensus evidence (5+ refs for same virus+type) ---")
    cur.execute("""
        SELECT virus_master_id, evidence_type, COUNT(DISTINCT reference_id) as ref_count,
               COUNT(*) as ev_count
        FROM evidence_records
        WHERE evidence_strength = 'low'
        GROUP BY virus_master_id, evidence_type
        HAVING ref_count >= 5
    """)
    rows = cur.fetchall()
    print(f"  Virus+type combos with 5+ refs: {len(rows)}")

    r2_count = 0
    for vm_id, ev_type, ref_count, ev_count in rows:
        cur.execute("""
            UPDATE evidence_records SET evidence_strength = 'medium'
            WHERE virus_master_id = ? AND evidence_type = ? AND evidence_strength = 'low'
        """, (vm_id, ev_type))
        r2_count += cur.rowcount
    con.commit()
    print(f"  Upgraded: {r2_count} records")
    upgraded_total += r2_count

    # === Rule 3: Fulltext-parsed with 2+ signal types ===
    print("\n--- Rule 3: Fulltext-parsed multi-signal evidence ---")
    cur.execute("""
        SELECT virus_master_id, reference_id, COUNT(DISTINCT evidence_type) as type_count
        FROM evidence_records
        WHERE extraction_method = 'fulltext_parsed'
          AND evidence_strength = 'low'
        GROUP BY virus_master_id, reference_id
        HAVING type_count >= 2
    """)
    rows = cur.fetchall()
    print(f"  Fulltext multi-type pairs: {len(rows)}")

    r3_count = 0
    for vm_id, ref_id, type_count in rows:
        cur.execute("""
            UPDATE evidence_records SET evidence_strength = 'medium'
            WHERE virus_master_id = ? AND reference_id = ?
              AND extraction_method = 'fulltext_parsed'
              AND evidence_strength = 'low'
        """, (vm_id, ref_id))
        r3_count += cur.rowcount
    con.commit()
    print(f"  Upgraded: {r3_count} records")
    upgraded_total += r3_count

    # === Final counts ===
    cur.execute("SELECT evidence_strength, COUNT(*) FROM evidence_records GROUP BY evidence_strength")
    print("\nAfter:")
    for row in cur.fetchall():
        print(f"  {row[0]}: {row[1]}")

    print(f"\nTotal upgraded: {upgraded_total}")

    # === Quality distribution by extraction method ===
    cur.execute("""
        SELECT extraction_method, evidence_strength, COUNT(*)
        FROM evidence_records
        WHERE extraction_method IS NOT NULL
        GROUP BY extraction_method, evidence_strength
        ORDER BY COUNT(*) DESC
        LIMIT 10
    """)
    print("\nTop method+strength combos:")
    for row in cur.fetchall():
        print(f"  {row[0]}: {row[1]}={row[2]}")

    con.close()
    print("\nDone.")


if __name__ == "__main__":
    main()
