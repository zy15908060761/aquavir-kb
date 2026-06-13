"""
Batch 1c: 蛋白结构关联到本地蛋白ID
策略:
  1. protein_structures.cluster_id -> viral_proteins_nr -> viral_proteins.protein_id
  2. protein_structures.reanno_id -> reannotated_orfs -> viral_proteins (via isolate_id)
  3. uniprot_structures.uniprot_id -> uniprot_protein_links -> viral_proteins.protein_id
"""
import sqlite3
from pathlib import Path

DB = Path("F:/甲壳动物数据库/crustacean_virus_core.db")
conn = sqlite3.connect(str(DB))
conn.execute("PRAGMA foreign_keys = ON")
cur = conn.cursor()

# ============================================================
# Part A: Link protein_structures
# ============================================================
print("=== protein_structures linking ===")
total_ps = cur.execute("SELECT COUNT(*) FROM protein_structures").fetchone()[0]
null_pid = cur.execute("SELECT COUNT(*) FROM protein_structures WHERE protein_id IS NULL").fetchone()[0]
print(f"protein_structures total: {total_ps}, without protein_id: {null_pid}")

# [A1] Link via viral_proteins_nr: cluster_id -> reanno_id -> viral_proteins
# viral_proteins_nr stores reanno_id (not protein_id) since NR DB was built from reannotated_orfs
cur.execute("""
    UPDATE protein_structures SET protein_id = (
        SELECT vp.protein_id FROM viral_proteins_nr vpnr
        JOIN reannotated_orfs ro ON vpnr.reanno_id = ro.reanno_id
        JOIN viral_proteins vp ON ro.isolate_id = vp.isolate_id
        WHERE vpnr.cluster_id = protein_structures.cluster_id
        ORDER BY vp.protein_id
        LIMIT 1
    )
    WHERE protein_id IS NULL
      AND cluster_id IS NOT NULL
""")
print(f"  [A1] Via viral_proteins_nr (cluster_id -> reanno_id -> vp): {cur.rowcount} rows updated")

# [A1b] Also backfill viral_proteins_nr.protein_id for future use
cur.execute("""
    UPDATE viral_proteins_nr SET protein_id = (
        SELECT vp.protein_id FROM reannotated_orfs ro
        JOIN viral_proteins vp ON ro.isolate_id = vp.isolate_id
        WHERE ro.reanno_id = viral_proteins_nr.reanno_id
        ORDER BY vp.protein_id LIMIT 1
    )
    WHERE protein_id IS NULL
""")
print(f"  [A1b] Backfilled viral_proteins_nr.protein_id: {cur.rowcount} rows")

# [A2] Link via reanno_id -> reannotated_orfs -> viral_proteins
cur.execute("""
    UPDATE protein_structures SET protein_id = (
        SELECT vp.protein_id FROM reannotated_orfs ro
        JOIN viral_proteins vp ON ro.isolate_id = vp.isolate_id
        WHERE ro.reanno_id = protein_structures.reanno_id
        ORDER BY ABS(ro.start_pos - COALESCE(vp.genome_start, 0))
        LIMIT 1
    )
    WHERE protein_id IS NULL AND reanno_id IS NOT NULL
""")
print(f"  [A2] Via reanno_id -> isolate proteins: {cur.rowcount} rows updated")

remaining_ps = cur.execute("SELECT COUNT(*) FROM protein_structures WHERE protein_id IS NULL").fetchone()[0]
print(f"  protein_structures still NULL: {remaining_ps}/{total_ps}")

# ============================================================
# Part B: Link uniprot_structures
# ============================================================
print("\n=== uniprot_structures linking ===")
total_us = cur.execute("SELECT COUNT(*) FROM uniprot_structures").fetchone()[0]
print(f"uniprot_structures total: {total_us}")

# Ensure protein_id column exists
cols_us = [d[1] for d in cur.execute("PRAGMA table_info(uniprot_structures)").fetchall()]
if "protein_id" not in cols_us:
    cur.execute("ALTER TABLE uniprot_structures ADD COLUMN protein_id INTEGER REFERENCES viral_proteins(protein_id)")
    print("  Added protein_id column to uniprot_structures")

null_us = cur.execute("SELECT COUNT(*) FROM uniprot_structures WHERE protein_id IS NULL").fetchone()[0]
print(f"  Without protein_id: {null_us}")

# [B1] Link via uniprot_protein_links
cur.execute("""
    UPDATE uniprot_structures SET protein_id = (
        SELECT upl.protein_id FROM uniprot_protein_links upl
        WHERE upl.uniprot_id = uniprot_structures.uniprot_id
        LIMIT 1
    )
    WHERE protein_id IS NULL
      AND EXISTS (
        SELECT 1 FROM uniprot_protein_links upl
        WHERE upl.uniprot_id = uniprot_structures.uniprot_id
      )
""")
print(f"  [B1] Via uniprot_protein_links: {cur.rowcount} rows updated")

# [B2] Link uniprot_structures that match but uniprot_protein_links may have multiple proteins
# Also try via uniprot_annotations for those that didn't match
cur.execute("""
    UPDATE uniprot_structures SET protein_id = (
        SELECT upl.protein_id FROM uniprot_annotations ua
        JOIN uniprot_protein_links upl ON ua.uniprot_id = upl.uniprot_id
        WHERE ua.uniprot_id = uniprot_structures.uniprot_id
        LIMIT 1
    )
    WHERE protein_id IS NULL
      AND EXISTS (
        SELECT 1 FROM uniprot_annotations ua
        JOIN uniprot_protein_links upl ON ua.uniprot_id = upl.uniprot_id
        WHERE ua.uniprot_id = uniprot_structures.uniprot_id
      )
""")
print(f"  [B2] Via uniprot_annotations -> links: {cur.rowcount} rows updated")

remaining_us = cur.execute("SELECT COUNT(*) FROM uniprot_structures WHERE protein_id IS NULL").fetchone()[0]
print(f"  uniprot_structures still NULL: {remaining_us}/{total_us}")

# ============================================================
# Part C: Summary
# ============================================================
conn.commit()
print("\n=== Summary ===")

# Count linked structures
linked_ps = cur.execute(
    "SELECT COUNT(*) FROM protein_structures WHERE protein_id IS NOT NULL"
).fetchone()[0]
print(f"protein_structures with protein_id: {linked_ps}/{total_ps}")

linked_us = cur.execute(
    "SELECT COUNT(*) FROM uniprot_structures WHERE protein_id IS NOT NULL"
).fetchone()[0]
print(f"uniprot_structures with protein_id: {linked_us}/{total_us}")

# Count unique proteins with structures
prots_with_struct = cur.execute("""
    SELECT COUNT(DISTINCT protein_id) FROM (
        SELECT protein_id FROM protein_structures WHERE protein_id IS NOT NULL
        UNION
        SELECT protein_id FROM uniprot_structures WHERE protein_id IS NOT NULL
    )
""").fetchone()[0]
print(f"Unique proteins with structures: {prots_with_struct}")

# How many now have both protein_id AND a valid structure?
total_proteins = cur.execute("SELECT COUNT(*) FROM viral_proteins").fetchone()[0]
print(f"Total viral_proteins: {total_proteins}")
print(f"Coverage: {prots_with_struct}/{total_proteins} ({prots_with_struct/total_proteins*100:.1f}%)")

conn.close()
print("\nSaved.")
