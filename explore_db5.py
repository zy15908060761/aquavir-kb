#!/usr/bin/env python3
"""Check protein_domains structure, sequences directory, and NCBI fetch viability."""
import sqlite3
import os

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

# protein_domains table
print("=== PROTEIN_DOMAINS ===")
cols = query("PRAGMA table_info(protein_domains)")
for c in cols:
    print(f"  {c['name']:25s} {c['type']:10s}")
cnt = query("SELECT COUNT(*) as c FROM protein_domains")[0]['c']
print(f"Total: {cnt}")
samp = query("SELECT * FROM protein_domains LIMIT 5")
for r in samp:
    print(f"  {r}")

# Distinct domain types
print("\n=== Distinct domain source/type in protein_domains ===")
rows = query("""
    SELECT domain_source, COUNT(*) as cnt
    FROM protein_domains
    GROUP BY domain_source
    ORDER BY cnt DESC
""")
for r in rows:
    print(f"  {str(r['domain_source'])[:30]:30s} {r['cnt']}")

# Link viral_proteins to viral_isolates to get family
print("\n=== VP <-> VI <-> master_family linkage ===")
rows = query("""
    SELECT COALESCE(vm.virus_family, 'NULL') as family,
           COUNT(DISTINCT vp.protein_id) as proteins,
           COUNT(DISTINCT pd.domain_id) as domains
    FROM viral_proteins vp
    LEFT JOIN protein_domains pd ON vp.protein_id = pd.protein_id
    LEFT JOIN viral_isolates vi ON vp.isolate_id = vi.isolate_id
    LEFT JOIN virus_master vm ON vi.master_id = vm.master_id
    WHERE vm.virus_family IS NOT NULL AND vm.virus_family != '' AND vm.virus_family != 'Dataset'
    GROUP BY vm.virus_family
    ORDER BY proteins DESC
    LIMIT 20
""")
for r in rows:
    print(f"  {str(r['family'])[:25]:25s} proteins={r['proteins']:5d} domains={r['domains']:6d}")
print("\n=== SEQUENCES DIRECTORY ===")
seq_dir = "F:/水生无脊椎动物数据库/sequences"
if os.path.isdir(seq_dir):
    files = [f for f in os.listdir(seq_dir) if f.endswith('.fasta') or f.endswith('.fa')]
    print(f"Fasta files: {len(files)}")
    if files:
        print(f"  First 5: {files[:5]}")
else:
    print(f"  Directory does not exist: {seq_dir}")

# Count how many isolates have sequences in the sequences dir
print("\n=== Isolates with has_sequence=1 and their accession types ===")
rows = query("""
    SELECT COUNT(*) as cnt,
           SUM(CASE WHEN genome_accession IS NOT NULL AND genome_accession != '' THEN 1 ELSE 0 END) as has_acc
    FROM viral_isolates
    WHERE has_sequence = 1
""")
print(f"  has_sequence=1: {rows[0]['cnt']}, with accession: {rows[0]['has_acc']}")

# Check how many have accession but missing GC content
print("\n=== Candidates for NCBI fetch: have accession, missing GC ===")
rows = query("""
    SELECT COUNT(*) as candidates
    FROM viral_isolates
    WHERE genome_accession IS NOT NULL AND genome_accession != ''
      AND (gc_content IS NULL)
""")
print(f"  Candidates for GC fetch: {rows[0]['candidates']}")

rows2 = query("""
    SELECT COUNT(*) as candidates
    FROM viral_isolates
    WHERE genome_accession IS NOT NULL AND genome_accession != ''
      AND (genome_length IS NULL OR genome_length = 0)
""")
print(f"  Candidates for length fetch: {rows2['candidates']}")

# Top families that would benefit from comparisons
print("\n=== TOP FAMILIES FOR PAIRWISE COMPARISONS (have genome_length, have family) ===")
rows = query("""
    SELECT COALESCE(vm.virus_family, vi.taxon_family, '(none)') as family,
           COUNT(*) as cnt
    FROM viral_isolates vi
    LEFT JOIN virus_master vm ON vi.master_id = vm.master_id
    WHERE vi.has_sequence = 1
      AND vi.genome_length IS NOT NULL AND vi.genome_length > 0
    GROUP BY family
    HAVING cnt >= 3 AND family != '(none)' AND family != 'Dataset'
    ORDER BY cnt DESC
    LIMIT 30
""")
for r in rows:
    print(f"  {str(r['family'])[:28]:28s} {r['cnt']}")
