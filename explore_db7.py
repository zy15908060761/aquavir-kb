#!/usr/bin/env python3
"""Quick final checks for script design."""
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

# Check reports directory
reports_dir = "F:/水生无脊椎动物数据库/reports"
if os.path.isdir(reports_dir):
    files = os.listdir(reports_dir)
    print(f"Reports directory exists, {len(files)} files")
else:
    print(f"Reports directory does not exist")
    os.makedirs(reports_dir, exist_ok=True)
    print(f"  Created: {reports_dir}")

# Check Biopython version and Entrez setup
try:
    import Bio
    print(f"Biopython version: {Bio.__version__}")
    from Bio import Entrez
    Entrez.email = "test@test.com"  # Just to test
    print("  Entrez import works")
except Exception as e:
    print(f"  Biopython/Entrez error: {e}")

# How many isolates without GC but with genome_length?
print("\n=== GC MISSING STATS ===")
rows = query("""
    SELECT COUNT(*) as total,
           SUM(CASE WHEN genome_length > 0 AND gc_content IS NULL THEN 1 ELSE 0 END) as missing_gc_has_length,
           SUM(CASE WHEN genome_length > 0 AND gc_content IS NOT NULL THEN 1 ELSE 0 END) as has_gc_length
    FROM viral_isolates
    WHERE has_sequence = 1
""")
print(f"  Total has_sequence=1: {rows[0]['total']}")
print(f"  Has both length and GC: {rows[0]['has_gc_length']}")
print(f"  Has length but missing GC: {rows[0]['missing_gc_has_length']}")

# What's in the curated profiles for GC
print("\n=== ISOLATE_CURATED_PROFILES GC coverage ===")
rows = query("""
    SELECT COUNT(*) as total,
           SUM(CASE WHEN genome_length IS NOT NULL AND genome_length > 0 THEN 1 ELSE 0 END) as has_len,
           SUM(CASE WHEN gc_content IS NOT NULL THEN 1 ELSE 0 END) as has_gc
    FROM isolate_curated_profiles
""")
print(f"  Total: {rows[0]['total']}, has_len: {rows[0]['has_len']}, has_gc: {rows[0]['has_gc']}")

# Check if curated_profiles also has family
print("Sample curated profile families:")
rows = query("""
    SELECT virus_family, COUNT(*) as cnt
    FROM isolate_curated_profiles
    WHERE genome_length IS NOT NULL AND genome_length > 0
    GROUP BY virus_family
    ORDER BY cnt DESC
    LIMIT 10
""")
for r in rows:
    print(f"  {str(r['virus_family'] or 'NULL')[:25]:25s} {r['cnt']}")

# Check what nucleotide_records has v.s. what's in viral_isolates
print("\n=== NUCLEOTIDE_RECORDS already has some GC/length ===")
try:
    rows = query("""
        SELECT COUNT(*) as cnt,
               SUM(CASE WHEN genome_length IS NOT NULL AND genome_length > 0 THEN 1 ELSE 0 END) as has_len,
               SUM(CASE WHEN gc_content_tags IS NOT NULL THEN 1 ELSE 0 END) as has_gc
        FROM nucleotide_records
    """)
    print(f"  Has gc_content_tags column: checking...")
except:
    pass

# Check if the GC content might be stored differently
print("\n=== GC CONTENT IN NUCLEOTIDE_RECORDS ===")
cols = query("PRAGMA table_info(nucleotide_records)")
gc_cols = [c['name'] for c in cols if 'gc' in c['name'].lower() or 'content' in c['name'].lower()]
print(f"  GC-related columns: {gc_cols}")

# Check for direct sequence content in the DB
print("\n=== SEARCH FOR FASTASEQUENCE TABLE ===")
rows = query("SELECT name FROM sqlite_master WHERE type='table' AND (name LIKE '%fasta%' OR name LIKE '%nucleotide_seq%' OR name LIKE '%genome_seq%')")
for r in rows:
    print(f"  {r['name']}")

# Best approach: Since genome_length ratios don't need actual sequences, and
# the existing build scripts use FASTA files from sequences dir, let's check
# if the 267 existing records are all from the k-mer approach
print("\n=== Existing pairwise identity = length ratio or k-mer? ===")
rows = query("""
    SELECT identity_percent, method, virus_species
    FROM genome_pairwise_identity
    LIMIT 10
""")
for r in rows:
    print(f"  id={r['identity_percent']:.3f} method={r['method']} species={r['virus_species']}")

# Count how many isolates with genome_length per species to understand grouping
print("\n=== ISOLATES PER SPECIES (with genome_length) TOP 20 ===")
rows = query("""
    SELECT vi.taxon_species, COUNT(*) as cnt,
           COUNT(DISTINCT vi.genome_length) as distinct_lengths
    FROM viral_isolates vi
    WHERE vi.genome_length IS NOT NULL AND vi.genome_length > 0
      AND vi.taxon_species IS NOT NULL AND vi.taxon_species != ''
    GROUP BY vi.taxon_species
    ORDER BY cnt DESC
    LIMIT 20
""")
for r in rows:
    print(f"  {str(r['taxon_species'])[:40]:40s} {r['cnt']:4d} isolates, {r['distinct_lengths']} distinct lengths")

# Alternative: group by virus_master species
print("\n=== ISOLATES PER MASTER SPECIES (with genome_length) ===")
rows = query("""
    SELECT vm.canonical_name, COUNT(*) as cnt,
           COUNT(DISTINCT vi.genome_length) as distinct_lengths
    FROM viral_isolates vi
    JOIN virus_master vm ON vi.master_id = vm.master_id
    WHERE vi.genome_length IS NOT NULL AND vi.genome_length > 0
      AND vm.canonical_name IS NOT NULL AND vm.canonical_name != ''
    GROUP BY vm.canonical_name
    ORDER BY cnt DESC
    LIMIT 20
""")
for r in rows:
    print(f"  {str(r['canonical_name'])[:40]:40s} {r['cnt']:4d} isolates, {r['distinct_lengths']} distinct lengths")
