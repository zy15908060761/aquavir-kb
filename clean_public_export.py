#!/usr/bin/env python3
"""Create clean public export views and mark non-target records for exclusion."""
import sqlite3, datetime

conn = sqlite3.connect('F:/水生无脊椎动物数据库/crustacean_virus_core.db')
ts = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')

# === STEP 1: Add public_visibility column to virus_master ===
try:
    conn.execute("ALTER TABLE virus_master ADD COLUMN public_visibility TEXT DEFAULT 'public'")
except:
    pass  # already exists

try:
    conn.execute("ALTER TABLE crustacean_hosts ADD COLUMN public_visibility TEXT DEFAULT 'public'")
except:
    pass

# === STEP 2: Mark non-target records as 'internal_only' ===
# Viruses
non_target_phylum = ['non_target (algae)', 'non_target (vertebrate)', 'non_target (fungus)',
                     'non_target (plant)', 'non_target', 'non_aquatic']

for phy in non_target_phylum:
    cnt = conn.execute("""
    UPDATE virus_master SET public_visibility = 'internal_only'
    WHERE host_phylum = ?
    """, (phy,)).rowcount
    if cnt > 0:
        print(f"  Marked {cnt} virus_master as internal_only: {phy}")

# Also mark 'unknown' phylum viruses (65 total) — these are unclassified orphans
conn.execute("UPDATE virus_master SET public_visibility = 'internal_only' WHERE host_phylum = 'unknown'")

# Hosts
conn.execute("""
UPDATE crustacean_hosts SET public_visibility = 'internal_only'
WHERE phylum IN ('Chordata', 'Proteobacteria') OR phylum LIKE '%Environmental%'
""")

# === STEP 3: Create clean public VIEWS ===
# Drop existing views if any
for v in ['public_virus_master', 'public_viral_isolates', 'public_crustacean_hosts',
          'public_evidence_records', 'public_ref_literatures']:
    conn.execute(f"DROP VIEW IF EXISTS {v}")

# Public virus view (exclude internal_only)
conn.execute("""
CREATE VIEW public_virus_master AS
SELECT * FROM virus_master WHERE public_visibility = 'public'
""")

# Public host view
conn.execute("""
CREATE VIEW public_crustacean_hosts AS
SELECT * FROM crustacean_hosts WHERE public_visibility = 'public'
""")

# Public isolates (only for public viruses)
conn.execute("""
CREATE VIEW public_viral_isolates AS
SELECT vi.* FROM viral_isolates vi
JOIN virus_master vm ON vi.master_id = vm.master_id
WHERE vm.public_visibility = 'public'
""")

# Public evidence (only for public viruses)
conn.execute("""
CREATE VIEW public_evidence_records AS
SELECT er.* FROM evidence_records er
LEFT JOIN virus_master vm ON er.virus_master_id = vm.master_id
WHERE vm.public_visibility = 'public' OR er.virus_master_id IS NULL
""")

# Public references
conn.execute("""
CREATE VIEW public_ref_literatures AS
SELECT * FROM ref_literatures
""")

conn.commit()

# === STEP 4: Report ===
pub_virus = conn.execute("SELECT COUNT(*) FROM public_virus_master").fetchone()[0]
pub_host = conn.execute("SELECT COUNT(*) FROM public_crustacean_hosts").fetchone()[0]
pub_isol = conn.execute("SELECT COUNT(*) FROM public_viral_isolates").fetchone()[0]
pub_ev = conn.execute("SELECT COUNT(*) FROM public_evidence_records").fetchone()[0]
pub_ref = conn.execute("SELECT COUNT(*) FROM public_ref_literatures").fetchone()[0]

internal_v = conn.execute("SELECT COUNT(*) FROM virus_master WHERE public_visibility='internal_only'").fetchone()[0]
internal_h = conn.execute("SELECT COUNT(*) FROM crustacean_hosts WHERE public_visibility='internal_only'").fetchone()[0]

print(f"\n===== PUBLIC EXPORT READY =====")
print(f"Public virus_master:     {pub_virus} (excluded {internal_v})")
print(f"Public crustacean_hosts:  {pub_host} (excluded {internal_h})")
print(f"Public viral_isolates:   {pub_isol}")
print(f"Public evidence_records: {pub_ev}")
print(f"Public ref_literatures:  {pub_ref}")
print()
print("Excluded from public export:")
print(f"  {internal_v} viruses (algae/vertebrate/fungi/plant/non-aquatic/unknown)")
print(f"  {internal_h} hosts (Chordata/Proteobacteria/Environmental)")
print()
print("Public views created. Use these for API and download exports.")
print("Documented exclusion criteria: non_aquatic_invertebrate, non_target_organism, unknown_taxonomy")

conn.close()
