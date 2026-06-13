#!/usr/bin/env python3
"""Verify results of genome comparison expansion."""
import sqlite3

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

print("=== POST-EXPANSION STATS ===")

# Pairwise identity
cnt = query("SELECT COUNT(*) as c FROM genome_pairwise_identity")[0]['c']
print(f"genome_pairwise_identity: {cnt}")

# Methods used
methods = query("SELECT method, COUNT(*) as cnt FROM genome_pairwise_identity GROUP BY method ORDER BY cnt DESC")
print("Methods:")
for m in methods:
    print(f"  {m['method']}: {m['cnt']}")

# Families covered
families = query("""
    SELECT virus_species, COUNT(*) as cnt,
           ROUND(AVG(identity_percent), 2) as avg_id
    FROM genome_pairwise_identity
    GROUP BY virus_species
    ORDER BY cnt DESC
    LIMIT 30
""")
print("Top families by comparisons:")
for f in families:
    print(f"  {f['virus_species'][:35]:35s} {f['cnt']:6d} comparisons, avg_id={f['avg_id']:6.2f}")

# Core genes
cnt = query("SELECT COUNT(*) as c FROM core_genes")[0]['c']
print(f"\ncore_genes: {cnt}")

# Core genes by taxonomic_level
levels = query("SELECT taxonomic_level, COUNT(*) as cnt FROM core_genes GROUP BY taxonomic_level ORDER BY cnt DESC")
print("Core genes by level:")
for l in levels:
    print(f"  {l['taxonomic_level']}: {l['cnt']}")

# Family-level core genes
family_cores = query("""
    SELECT taxonomic_group, COUNT(*) as cnt
    FROM core_genes
    WHERE taxonomic_level = 'family'
    GROUP BY taxonomic_group
    ORDER BY cnt DESC
    LIMIT 20
""")
print("Family-level core domains:")
for f in family_cores:
    print(f"  {f['taxonomic_group'][:30]:30s} {f['cnt']} core domains")

# GC content stats
gc = query("SELECT COUNT(*) as c FROM viral_isolates WHERE gc_content IS NOT NULL")[0]['c']
print(f"\nGC content available: {gc}")

# Synteny
cnt = query("SELECT COUNT(*) as c FROM genome_synteny_blocks")[0]['c']
print(f"genome_synteny_blocks: {cnt}")

# Check the report
import os
report = "F:/水生无脊椎动物数据库/reports/genome_comparison_summary.md"
if os.path.exists(report):
    with open(report, 'r', encoding='utf-8') as f:
        content = f.read()
    print(f"\n=== REPORT PREVIEW === ({len(content)} bytes)")
    for line in content.split('\n')[:40]:
        print(line)
else:
    print(f"\nReport not found at {report}")
