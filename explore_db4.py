#!/usr/bin/env python3
"""Check existing genome comparison scripts and other related data."""
import sqlite3
import os
import glob

DB = "F:/水生无脊椎动物数据库/crustacean_virus_core.db"

def query(sql, params=None):
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    if params:
        cur.execute(sql, params)
    else:
        cur.execute(sql)
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows

# Check existing genome scripts for their approach
scripts_to_check = [
    "build_genome_identity_kmer.py",
    "build_genome_identity_matrix.py",
    "build_synteny_simple.py",
    "rebuild_core_genes.py",
]

for sname in scripts_to_check:
    fpath = os.path.join("F:/水生无脊椎动物数据库", sname)
    if os.path.exists(fpath):
        with open(fpath, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
        lines = content.split('\n')
        print(f"\n{'='*60}")
        print(f"  {sname}: {len(lines)} lines")
        print(f"{'='*60}")
        # Print first 50 lines
        for l in lines[:50]:
            print(l)

# Check families that have NULL taxon_family but have sequence
print("\n\n=== NULL taxon_family but has_sequence=1 ===")
rows = query("""
    SELECT COUNT(*) as cnt,
           SUM(CASE WHEN genome_length IS NOT NULL THEN 1 ELSE 0 END) as with_len,
           SUM(CASE WHEN gc_content IS NOT NULL THEN 1 ELSE 0 END) as with_gc,
           SUM(CASE WHEN genome_accession IS NOT NULL AND genome_accession != '' THEN 1 ELSE 0 END) as with_acc
    FROM viral_isolates
    WHERE (taxon_family IS NULL OR taxon_family = '') AND has_sequence = 1
""")
print(f"Total NULL-family with sequence: {rows[0]['cnt']}")
print(f"  with len: {rows[0]['with_len']}, with gc: {rows[0]['with_gc']}, with acc: {rows[0]['with_acc']}")

# Check the empty string family
print("\n=== taxon_family='' (empty string) ===")
rows = query("""
    SELECT COUNT(*) as cnt
    FROM viral_isolates
    WHERE taxon_family = ''
""")
print(f"Empty string family count: {rows[0]['cnt']}")

# Check isolates missing GC but having genome_accession
print("\n=== ISOLATES MISSING GC/BUT HAVE ACCESSION (top families) ===")
rows = query("""
    SELECT COALESCE(taxon_family, 'NULL') as family,
           COUNT(*) as cnt
    FROM viral_isolates
    WHERE has_sequence = 1
      AND (gc_content IS NULL)
      AND genome_accession IS NOT NULL AND genome_accession != ''
    GROUP BY taxon_family
    ORDER BY cnt DESC
    LIMIT 20
""")
for r in rows:
    print(f"  {str(r['family'])[:25]:25s} {r['cnt']}")

# Check isolates missing genome_length but having accession
print("\n=== ISOLATES MISSING GENOME_LENGTH/BUT HAVE ACCESSION (top families) ===")
rows = query("""
    SELECT COALESCE(taxon_family, 'NULL') as family,
           COUNT(*) as cnt
    FROM viral_isolates
    WHERE has_sequence = 1
      AND (genome_length IS NULL OR genome_length = 0)
      AND genome_accession IS NOT NULL AND genome_accession != ''
    GROUP BY taxon_family
    ORDER BY cnt DESC
    LIMIT 20
""")
for r in rows:
    print(f"  {str(r['family'])[:25]:25s} {r['cnt']}")

# Check viral_proteins for domain annotations
print("\n=== VIRAL_PROTEINS and PROTEIN_DOMAINS ===")
try:
    cnt = query("SELECT COUNT(*) as c FROM viral_proteins")[0]['c']
    print(f"viral_proteins: {cnt}")
    cnt2 = query("SELECT COUNT(*) as c FROM protein_domains")[0]['c']
    print(f"protein_domains: {cnt2}")
    cols = query("PRAGMA table_info(viral_proteins)")
    for c in cols:
        print(f"  {c['name']:25s} {c['type']:10s}")
except Exception as e:
    print(f"Error: {e}")

# Check interpro_annotations
print("\n=== INTERPRO_ANNOTATIONS ===")
try:
    cnt = query("SELECT COUNT(*) as c FROM interpro_annotations")[0]['c']
    print(f"interpro_annotations: {cnt}")
    cols = query("PRAGMA table_info(interpro_annotations)")
    for c in cols[:15]:
        print(f"  {c['name']:25s} {c['type']:10s}")
    samp = query("SELECT * FROM interpro_annotations LIMIT 3")
    for r in samp:
        print(f"  {r}")
except Exception as e:
    print(f"Error: {e}")

# Check for VIRUS_FAMILY table
print("\n=== VIRUS_FAMILY TABLE ===")
try:
    cnt = query("SELECT COUNT(*) as c FROM virus_family")[0]['c']
    print(f"virus_family: {cnt} rows")
    samp = query("SELECT * FROM virus_family LIMIT 5")
    for r in samp:
        print(f"  {r}")
except Exception as e:
    print(f"Error: {e}")

# Check how viral_isolates links to virus_master for family
print("\n=== VIRAL_ISOLATES -> MASTER -> FAMILY linkage ===")
rows = query("""
    SELECT vm.virus_family, COUNT(*) as cnt
    FROM viral_isolates vi
    JOIN virus_master vm ON vi.master_id = vm.master_id
    WHERE vi.has_sequence = 1
    GROUP BY vm.virus_family
    ORDER BY cnt DESC
    LIMIT 15
""")
for r in rows:
    print(f"  {str(r['virus_family'] or 'NULL')[:25]:25s} {r['cnt']}")
