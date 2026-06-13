"""Analyze accession patterns in the database."""
import sqlite3
import re
from pathlib import Path

DB = Path(r"F:\水生无脊椎动物数据库\crustacean_virus_core.db")
conn = sqlite3.connect(str(DB))
conn.row_factory = sqlite3.Row
c = conn.cursor()
c.execute("""
    SELECT DISTINCT vi.accession, vi.isolate_id, vm.canonical_name
    FROM virus_ictv_status vs
    JOIN virus_master vm ON vs.master_id = vm.master_id
    JOIN viral_isolates vi ON vm.master_id = vi.master_id
    LEFT JOIN viral_proteins vp ON vi.isolate_id = vp.isolate_id
    WHERE vs.ictv_status IN ('pending_review', 'unclassified_not_expected')
      AND vm.entry_type NOT IN ('non_target', 'host_genome',
                                'duplicate_alias_placeholder',
                                'duplicate_ictv_vmr_placeholder')
      AND vp.protein_id IS NULL
      AND vi.accession IS NOT NULL AND vi.accession != ''
    ORDER BY vi.accession
""")
rows = c.fetchall()
conn.close()

print(f"Total accessions: {len(rows)}")

# Print first 30
print("\nFirst 30 accessions:")
for r in rows[:30]:
    print(f"  {r['accession']:20s}  {r['canonical_name'][:50]}")

# Print last 30
print("\nLast 30 accessions:")
for r in rows[-30:]:
    print(f"  {r['accession']:20s}  {r['canonical_name'][:50]}")

# Prefix breakdown
patterns = {}
for r in rows:
    a = r['accession']
    m = re.match(r'^([A-Z]+)', a)
    prefix = m.group(1) if m else 'OTHER'
    patterns[prefix] = patterns.get(prefix, 0) + 1

print("\nAccession prefix breakdown:")
for p, cnt in sorted(patterns.items(), key=lambda x: -x[1]):
    print(f"  {p}: {cnt}")
