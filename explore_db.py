#!/usr/bin/env python3
"""Explore database structure and current genome comparison data."""
import sqlite3
import sys

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

def section(title):
    print(f"\n{'='*70}")
    print(f"  {title}")
    print(f"{'='*70}")

# --- Table schemas for relevant tables ---
section("Genome-related table schemas")
for tbl in ['genome_pairwise_identity', 'genome_synteny_blocks', 'core_genes', 'isolates', 'virus_family']:
    try:
        rows = query(f"SELECT sql FROM sqlite_master WHERE type='table' AND name='{tbl}'")
        if rows:
            print(f"\n-- {tbl}:")
            print(rows[0]['sql'])
    except Exception as e:
        print(f"  {tbl}: ERROR {e}")

# --- Current counts ---
section("Current record counts")
tables = {
    'genome_pairwise_identity': 'genome_pairwise_identity',
    'genome_synteny_blocks': 'genome_synteny_blocks',
    'core_genes': 'core_genes',
    'isolates': 'isolates',
}
for name, tbl in tables.items():
    try:
        cnt = query(f"SELECT COUNT(*) as c FROM {tbl}")[0]['c']
        print(f"  {name}: {cnt} records")
    except Exception as e:
        print(f"  {name}: ERROR {e}")

# --- Isolates stats ---
section("Isolates stats")
print("Total isolates:", query("SELECT COUNT(*) as c FROM isolates")[0]['c'])
print("Has sequence:", query("SELECT COUNT(*) as c FROM isolates WHERE has_sequence=1")[0]['c'])
print("Has genome_length:", query("SELECT COUNT(*) as c FROM isolates WHERE genome_length IS NOT NULL")[0]['c'])
print("Has gc_content:", query("SELECT COUNT(*) as c FROM isolates WHERE gc_content IS NOT NULL")[0]['c'])
print("Has genome_accession:", query("SELECT COUNT(*) as c FROM isolates WHERE genome_accession IS NOT NULL AND genome_accession != ''")[0]['c'])

# --- Families with most sequence isolates ---
section("Top 30 families by isolates with sequences")
rows = query("""
    SELECT f.name AS family_name, COUNT(*) AS cnt
    FROM isolates i
    JOIN virus_family f ON i.virus_family_id = f.virus_family_id
    WHERE i.has_sequence = 1
    GROUP BY f.name
    ORDER BY cnt DESC
    LIMIT 30
""")
for r in rows:
    print(f"  {r['family_name']}: {r['cnt']}")

# --- Families with complete genomes (have genome_length) ---
section("Top 30 families by isolates with genome_length")
rows = query("""
    SELECT f.name AS family_name, COUNT(*) AS cnt
    FROM isolates i
    JOIN virus_family f ON i.virus_family_id = f.virus_family_id
    WHERE i.genome_length IS NOT NULL AND i.genome_length > 0
    GROUP BY f.name
    ORDER BY cnt DESC
    LIMIT 30
""")
for r in rows:
    print(f"  {r['family_name']}: {r['cnt']}")

# --- Sample genome_pairwise_identity records ---
section("Sample genome_pairwise_identity records")
rows = query("SELECT * FROM genome_pairwise_identity LIMIT 10")
for r in rows:
    print(r)

section("Sample genome_synteny_blocks")
rows = query("SELECT * FROM genome_synteny_blocks LIMIT 5")
for r in rows:
    print(r)

section("Sample core_genes")
rows = query("SELECT * FROM core_genes LIMIT 5")
for r in rows:
    print(r)

# --- columns in isolates ---
section("Isolates columns")
rows = query("PRAGMA table_info(isolates)")
for r in rows:
    print(f"  {r['name']:30s} {r['type']:10s} nullable={not r['notnull']}")

# --- Check for existing scripts ---
import glob
scripts = glob.glob("F:/水生无脊椎动物数据库/*.py")
section("Existing Python scripts mentioning genome comparison")
for s in scripts:
    with open(s, 'r', encoding='utf-8', errors='ignore') as f:
        content = f.read()
        if any(kw in content.lower() for kw in ['pairwise', 'synteny', 'core_gen', 'genome_comp', 'genome_length', 'gc_content']):
            print(f"  {s.split('/')[-1]}")
