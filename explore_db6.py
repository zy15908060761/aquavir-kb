#!/usr/bin/env python3
"""Additional exploration needed for the main script design."""
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

# Sequences directory check
print("=== SEQUENCES DIRECTORY ===")
seq_dir = "F:/水生无脊椎动物数据库/sequences"
if os.path.isdir(seq_dir):
    files = [f for f in os.listdir(seq_dir) if f.endswith('.fasta') or f.endswith('.fa')]
    print(f"Fasta files: {len(files)}")
    if files:
        print(f"  First 10: {files[:10]}")
else:
    print(f"  Directory does not exist: {seq_dir}")
    # Check alternative directory names
    for fname in os.listdir("F:/水生无脊椎动物数据库"):
        full = os.path.join("F:/水生无脊椎动物数据库", fname)
        if os.path.isdir(full) and 'seq' in fname.lower():
            print(f"  Found alternative: {full}")

# Domain sources distribution
print("\n=== PROTEIN_DOMAIN SOURCES ===")
rows = query("""
    SELECT domain_source, COUNT(*) as cnt
    FROM protein_domains
    GROUP BY domain_source
    ORDER BY cnt DESC
""")
for r in rows:
    print(f"  {str(r['domain_source'])[:30]:30s} {r['cnt']}")

# Top families with most domain-annotated isolates
print("\n=== FAMILIES WITH DOMAIN-ANNOTATED PROTEINS (for core gene analysis) ===")
rows = query("""
    SELECT COALESCE(vm.virus_family, 'NULL') as family,
           COUNT(DISTINCT vp.isolate_id) as isolates,
           COUNT(DISTINCT vp.protein_id) as proteins,
           COUNT(DISTINCT pd.domain_id) as domains
    FROM viral_proteins vp
    JOIN protein_domains pd ON vp.protein_id = pd.protein_id
    JOIN viral_isolates vi ON vp.isolate_id = vi.isolate_id
    JOIN virus_master vm ON vi.master_id = vm.master_id
    WHERE vm.virus_family IS NOT NULL AND vm.virus_family != '' AND vm.virus_family != 'Dataset'
    GROUP BY vm.virus_family
    ORDER BY isolates DESC
    LIMIT 20
""")
print(f"{'Family':25s} {'Isolates':>10s} {'Proteins':>10s} {'Domains':>8s}")
print("-"*55)
for r in rows:
    print(f"{str(r['family'])[:24]:25s} {r['isolates']:10d} {r['proteins']:10d} {r['domains']:8d}")

# Genome_accession sample - those with real GenBank accessions
print("\n=== ISOLATES WITH REAL GENBANK ACCESSION (for NCBI) ===")
rows = query("""
    SELECT genome_accession, taxon_family, genome_length, gc_content
    FROM viral_isolates
    WHERE genome_accession IS NOT NULL AND genome_accession != ''
      AND gc_content IS NULL
    ORDER BY RANDOM()
    LIMIT 10
""")
print(f"Missing GC: {len(rows)} samples:")
for r in rows:
    print(f"  {r['genome_accession']:15s} family={str(r['taxon_family'] or '')[:20]:20s} len={r['genome_length']} gc={r['gc_content']}")

rows2 = query("""
    SELECT genome_accession, taxon_family, genome_length, gc_content
    FROM viral_isolates
    WHERE genome_accession IS NOT NULL AND genome_accession != ''
      AND (genome_length IS NULL OR genome_length = 0)
    ORDER BY RANDOM()
    LIMIT 10
""")
print(f"Missing length: {len(rows2)} samples:")
for r in rows2:
    print(f"  {r['genome_accession']:15s} family={str(r['taxon_family'] or '')[:20]:20s} len={r['genome_length']} gc={r['gc_content']}")

# Check the existing pairwise identity method used
print("\n=== EXISTING PAIRWISE IDENTITY METHODS ===")
rows = query("""
    SELECT method, COUNT(*) as cnt
    FROM genome_pairwise_identity
    GROUP BY method
""")
for r in rows:
    print(f"  {str(r['method'])[:30]:30s} {r['cnt']}")

# Check if there's a valid index on genome_pairwise_identity
print("\n=== INDEXES ON genome_pairwise_identity ===")
rows = query("""
    SELECT name FROM sqlite_master
    WHERE type='index' AND tbl_name='genome_pairwise_identity'
""")
for r in rows:
    print(f"  {r['name']}")

# Check the NCBI fetch approach - do we have Biopython?
print("\n=== CHECK FOR BIOPYTHON / NCBI ACCESS ===")
try:
    from Bio import Entrez
    print("  Biopython Entrez available")
except ImportError:
    print("  Biopython Entrez NOT available")

try:
    import requests
    print("  requests available")
except ImportError:
    print("  requests NOT available")

# Count isolates by completeness
print("\n=== COMPLETENESS DISTRIBUTION ===")
rows = query("""
    SELECT completeness, COUNT(*) as cnt
    FROM viral_isolates
    GROUP BY completeness
    ORDER BY cnt DESC
    LIMIT 10
""")
for r in rows:
    print(f"  {str(r['completeness'])[:25]:25s} {r['cnt']}")

# Check if the existing scripts use actual sequence files or just metadata
print("\n=== Does genome_pairwise_identity link to sequence files? ===")
rows = query("""
    SELECT gpi.*
    FROM genome_pairwise_identity gpi
    LIMIT 3
""")
for r in rows:
    print(f"  acc_a={r['accession_a']} acc_b={r['accession_b']} id={r['identity_percent']}")
