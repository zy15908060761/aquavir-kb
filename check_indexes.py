import sqlite3
conn = sqlite3.connect(r'F:\甲壳动物数据库\crustacean_virus_core.db')
c = conn.cursor()

tables = ['virus_master', 'viral_isolates', 'viral_proteins', 'infection_records', 
          'sample_collections', 'ref_literatures', 'nucleotide_records', 'crustacean_hosts',
          'protein_structures', 'protein_annotation_bridge', 'interpro_annotations',
          'isolate_reference_links', 'kegg_protein_pathways']

for t in tables:
    try:
        c.execute(f"PRAGMA index_list({t})")
        idxs = c.fetchall()
        print(f"=== {t} ===")
        for row in idxs:
            print(f"  {row[1]}: unique={row[2]} origin={row[3]}")
            c.execute(f"PRAGMA index_info({row[1]})")
            cols = c.fetchall()
            print(f"    cols: {[r[2] for r in cols]}")
    except Exception as e:
        print(f"=== {t} === ERROR: {e}")
    print()

# Check FKs
c.execute("SELECT name, sql FROM sqlite_master WHERE type='table'")
print("=== FOREIGN KEYS ===")
for name, sql in c.fetchall():
    if sql and 'FOREIGN KEY' in sql.upper():
        print(f"{name}:")
        for line in sql.split('\n'):
            if 'FOREIGN' in line.upper():
                print(f"  {line.strip()}")
