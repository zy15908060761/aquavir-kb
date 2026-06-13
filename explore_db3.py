#!/usr/bin/env python3
"""Explore viral_isolates in depth and check for existing comparison scripts."""
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

# viral_isolates stats
print("=== VIRAL ISOLATES STATS ===")
vi = query("SELECT COUNT(*) as c FROM viral_isolates")[0]['c']
print(f"Total: {vi}")

hs = query("SELECT COUNT(*) as c FROM viral_isolates WHERE has_sequence=1")[0]['c']
print(f"has_sequence=1: {hs}")

gl = query("SELECT COUNT(*) as c FROM viral_isolates WHERE genome_length IS NOT NULL AND genome_length > 0")[0]['c']
print(f"genome_length > 0: {gl}")

gc = query("SELECT COUNT(*) as c FROM viral_isolates WHERE gc_content IS NOT NULL")[0]['c']
print(f"gc_content IS NOT NULL: {gc}")

ga = query("SELECT COUNT(*) as c FROM viral_isolates WHERE genome_accession IS NOT NULL AND genome_accession != ''")[0]['c']
print(f"genome_accession NOT NULL: {ga}")

# Families distribution
print("\n=== FAMILIES WITH MOST ISOLATES (has_sequence=1) ===")
rows = query("""
    SELECT COALESCE(taxon_family, '(unassigned)') AS family, COUNT(*) AS cnt,
           SUM(CASE WHEN genome_length IS NOT NULL AND genome_length > 0 THEN 1 ELSE 0 END) AS with_length,
           SUM(CASE WHEN gc_content IS NOT NULL THEN 1 ELSE 0 END) AS with_gc,
           SUM(CASE WHEN genome_accession IS NOT NULL AND genome_accession != '' THEN 1 ELSE 0 END) AS with_accession
    FROM viral_isolates
    WHERE has_sequence = 1
    GROUP BY taxon_family
    ORDER BY cnt DESC
    LIMIT 40
""")
print(f"{'Family':30s} {'Isolates':>8s} {'Len':>6s} {'GC':>6s} {'Acc':>6s}")
print("-"*60)
for r in rows:
    print(f"{str(r['family'])[:28]:30s} {r['cnt']:8d} {r['with_length']:6d} {r['with_gc']:6d} {r['with_accession']:6d}")

# Families with >=3 complete genomes (have genome_length)
print("\n=== FAMILIES WITH >=3 COMPLETE GENOME LENGTHS ===")
rows = query("""
    SELECT COALESCE(taxon_family, '(unassigned)') AS family, COUNT(*) AS cnt,
           SUM(CASE WHEN gc_content IS NOT NULL THEN 1 ELSE 0 END) AS with_gc
    FROM viral_isolates
    WHERE has_sequence = 1 AND genome_length IS NOT NULL AND genome_length > 0
    GROUP BY taxon_family
    HAVING cnt >= 3
    ORDER BY cnt DESC
""")
print(f"{'Family':30s} {'Count':>6s} {'GC%':>6s}")
print("-"*45)
for r in rows:
    print(f"{str(r['family'])[:28]:30s} {r['cnt']:6d} {r['with_gc']:6d}")

# Genome_accession sample for NCBI fetching
print("\n=== SAMPLE GENOME ACCESSIONS (for NCBI) ===")
rows = query("""
    SELECT genome_accession, taxon_family, genome_length, gc_content
    FROM viral_isolates
    WHERE genome_accession IS NOT NULL AND genome_accession != ''
    LIMIT 10
""")
for r in rows:
    fam = str(r['taxon_family'] or '')[:20]
    print(f"  {r['genome_accession']:15s} family={fam:20s} len={r['genome_length']} gc={r['gc_content']}")

# Check if there's a sequence table
print("\n=== CHECK FOR SEQUENCE CONTENT ===")
tbls = query("SELECT name FROM sqlite_master WHERE type='table' AND (name LIKE '%seq%' OR name LIKE '%nucl%' OR name LIKE '%fasta%')")
for r in tbls:
    print(f"  {r['name']}")

# Check nucleotide_records
print("\n=== NUCLEOTIDE_RECORDS ===")
try:
    cols = query("PRAGMA table_info(nucleotide_records)")
    print("Columns:")
    for c in cols:
        print(f"  {c['name']:25s} {c['type']:10s}")
    cnt = query("SELECT COUNT(*) as c FROM nucleotide_records")[0]['c']
    print(f"Rows: {cnt}")
    samp = query("SELECT * FROM nucleotide_records LIMIT 3")
    for r in samp:
        print(f"  {r}")
except Exception as e:
    print(f"Error: {e}")

# Check host_genome_artifacts
print("\n=== HOST_GENOME_ARTIFACTS ===")
cnt = query("SELECT COUNT(*) as c FROM host_genome_artifacts")[0]['c']
print(f"Rows: {cnt}")

# Check isolate_curated_profiles genome stats
print("\n=== ISOLATE_CURATED_PROFILES genome stats ===")
gl2 = query("SELECT COUNT(*) as c FROM isolate_curated_profiles WHERE genome_length IS NOT NULL AND genome_length > 0")[0]['c']
gc2 = query("SELECT COUNT(*) as c FROM isolate_curated_profiles WHERE gc_content IS NOT NULL")[0]['c']
print(f"genome_length: {gl2}, gc_content: {gc2}")

# Check for existing genome comparison scripts
print("\n=== EXISTING SCRIPTS MENTIONING GENOME COMPARISON ===")
scripts_dir = "F:/水生无脊椎动物数据库"
for f in sorted(glob.glob(os.path.join(scripts_dir, "*.py"))):
    name = os.path.basename(f)
    try:
        with open(f, 'r', encoding='utf-8', errors='ignore') as fh:
            content = fh.read()
            if any(kw in content.lower() for kw in ['pairwise', 'synteny', 'core_gen', 'genome_comp']):
                print(f"  {name}")
    except:
        pass

# Check core_genes current data
print("\n=== CORE_GENES SAMPLE ===")
rows = query("SELECT * FROM core_genes LIMIT 5")
for r in rows:
    print(f"  species={r['virus_species']} gene={r['gene_symbol']} protein={r['protein_name']} cat={r['functional_category']} conservation={r['conservation_rate']}")

print("\n=== GENOME_PAIRWISE_IDENTITY CURRENT FAMILIES ===")
rows = query("""
    SELECT g.virus_species, COUNT(*) as cnt
    FROM genome_pairwise_identity g
    GROUP BY g.virus_species
    ORDER BY cnt DESC
    LIMIT 20
""")
for r in rows:
    print(f"  {r['virus_species'][:40]:40s} {r['cnt']} comparisons")
