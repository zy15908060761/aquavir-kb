"""MARKED FOR DELETION - Temporary query script was used for sync."""
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "crustacean_virus_core.db"
conn = sqlite3.connect(str(DB_PATH))
conn.row_factory = sqlite3.Row
cur = conn.cursor()

print("=== ICTV VMR ===")
cur.execute("SELECT COUNT(*) AS cnt FROM ictv_vmr")
print(f"  total entries: {cur.fetchone()['cnt']}")

cur.execute("SELECT DISTINCT vmr_version FROM ictv_vmr")
for r in cur.fetchall():
    print(f"  vmr_version: {r['vmr_version']}")

print()
print("=== virus_ictv_mappings ===")
cur.execute("SELECT COUNT(*) AS cnt FROM virus_ictv_mappings")
print(f"  total: {cur.fetchone()['cnt']}")
cur.execute("SELECT DISTINCT match_type, confidence, COUNT(*) AS cnt FROM virus_ictv_mappings GROUP BY match_type, confidence")
for r in cur.fetchall():
    print(f"  {r['match_type']} ({r['confidence']}): {r['cnt']}")

print()
print("=== virus_vmr_mappings ===")
cur.execute("SELECT COUNT(*) AS cnt FROM virus_vmr_mappings")
print(f"  total: {cur.fetchone()['cnt']}")
cur.execute("SELECT DISTINCT match_type, COUNT(*) AS cnt FROM virus_vmr_mappings GROUP BY match_type")
for r in cur.fetchall():
    print(f"  {r['match_type']}: {r['cnt']}")

print()
print("=== virus_master ===")
cur.execute("SELECT COUNT(*) AS cnt FROM virus_master")
print(f"  total: {cur.fetchone()['cnt']}")

print()
print("=== host_source distribution (top 20) ===")
cur.execute("""
    SELECT host_source, COUNT(*) AS cnt
    FROM ictv_vmr
    WHERE host_source IS NOT NULL AND host_source != ''
    GROUP BY host_source
    ORDER BY cnt DESC
    LIMIT 20
""")
for r in cur.fetchall():
    print(f"  {r['host_source']}: {r['cnt']}")

print()
print("=== host_source counts with NULL/empty ===")
cur.execute("SELECT COUNT(*) AS cnt FROM ictv_vmr WHERE host_source IS NULL OR host_source = ''")
print(f"  NULL/empty host_source: {cur.fetchone()['cnt']}")

print()
print("=== Aquatic invertebrate relevant (crustacean/mollusk/coral) ===")
cur.execute("""
    SELECT COUNT(*) AS cnt FROM ictv_vmr
    WHERE LOWER(COALESCE(host_source, '')) LIKE '%shrimp%'
       OR LOWER(COALESCE(host_source, '')) LIKE '%crab%'
       OR LOWER(COALESCE(host_source, '')) LIKE '%crayfish%'
       OR LOWER(COALESCE(host_source, '')) LIKE '%lobster%'
       OR LOWER(COALESCE(host_source, '')) LIKE '%mollusc%'
       OR LOWER(COALESCE(host_source, '')) LIKE '%oyster%'
       OR LOWER(COALESCE(host_source, '')) LIKE '%coral%'
       OR LOWER(COALESCE(host_source, '')) LIKE '%crustacea%'
       OR LOWER(COALESCE(host_source, '')) LIKE '%decapod%'
       OR LOWER(COALESCE(host_source, '')) LIKE '%krill%'
       OR LOWER(COALESCE(host_source, '')) LIKE '%barnacle%'
       OR LOWER(COALESCE(host_source, '')) LIKE '%copepod%'
       OR LOWER(COALESCE(host_source, '')) LIKE '%amphipod%'
       OR LOWER(COALESCE(host_source, '')) LIKE '%isopod%'
       OR LOWER(COALESCE(host_source, '')) LIKE '%cladoceran%'
       OR LOWER(COALESCE(host_source, '')) LIKE '%rotifer%'
       OR LOWER(COALESCE(host_source, '')) LIKE '%sponge%'
       OR LOWER(COALESCE(host_source, '')) LIKE '%cnidaria%'
       OR LOWER(COALESCE(host_source, '')) LIKE '%anemone%'
       OR LOWER(COALESCE(host_source, '')) LIKE '%jellyfish%'
       OR LOWER(COALESCE(host_source, '')) LIKE '%echinoderm%'
       OR LOWER(COALESCE(host_source, '')) LIKE '%starfish%'
       OR LOWER(COALESCE(host_source, '')) LIKE '%urchin%'
       OR LOWER(COALESCE(host_source, '')) LIKE '%worm%'
       OR LOWER(COALESCE(host_source, '')) LIKE '%annelid%'
       OR LOWER(COALESCE(host_source, '')) LIKE '%nematode%'
       OR LOWER(COALESCE(host_source, '')) LIKE '%platyhelmint%'
       OR LOWER(COALESCE(host_source, '')) LIKE '%tunicate%'
       OR LOWER(COALESCE(host_source, '')) LIKE '%ascidian%'
       OR LOWER(COALESCE(host_source, '')) LIKE '%mosquito%'
       OR LOWER(COALESCE(host_source, '')) LIKE '%caterpillar%'
       OR LOWER(COALESCE(host_source, '')) LIKE '%lepidoptera%'
       OR LOWER(COALESCE(host_source, '')) LIKE '%diptera%'
       OR LOWER(COALESCE(host_source, '')) LIKE '%hymenoptera%'
       OR LOWER(COALESCE(host_source, '')) LIKE '%beetle%'
       OR LOWER(COALESCE(host_source, '')) LIKE '%coleoptera%'
       OR LOWER(COALESCE(host_source, '')) LIKE '%hemiptera%'
       OR LOWER(COALESCE(host_source, '')) LIKE '%aphid%'
       OR LOWER(COALESCE(host_source, '')) LIKE '%mite%'
       OR LOWER(COALESCE(host_source, '')) LIKE '%tick%'
       OR LOWER(COALESCE(host_source, '')) LIKE '%waterfowl%'
       OR LOWER(COALESCE(host_source, '')) LIKE '%aquatic%'
       OR LOWER(COALESCE(host_source, '')) LIKE '%marine%'
       OR LOWER(COALESCE(host_source, '')) LIKE '%invertebrate%'
       OR LOWER(COALESCE(host_source, '')) LIKE '%arthropod%'
""")
print(f"  aquatic-invertebrate-relevant: {cur.fetchone()['cnt']}")

print()
print("=== virus_ictv_mappings integrity check ===")
# Broken master_id links
cur.execute("""
    SELECT COUNT(*) AS cnt FROM virus_ictv_mappings vim
    LEFT JOIN virus_master vm ON vim.master_id = vm.master_id
    WHERE vm.master_id IS NULL
""")
print(f"  mappings with broken master_id: {cur.fetchone()['cnt']}")

# Check virus_master entries that have ictv_status
cur.execute("PRAGMA table_info(virus_master)")
cols = [c['name'] for c in cur.fetchall()]
print(f"  virus_master columns with 'ictv': {[c for c in cols if 'ictv' in c.lower()]}")
print(f"  virus_master columns with 'msl': {[c for c in cols if 'msl' in c.lower()]}")

print()
print("=== virus_master columns check ===")
# Check for ictv-related columns
ictv_cols = [c for c in cols if 'ictv' in c.lower() or 'msl' in c.lower() or 'vmr' in c.lower()]
print(f"  ICTV/VMR/MSL related columns: {ictv_cols}")

# count viruses with ictv references
if 'ictv_id' in cols:
    cur.execute("SELECT COUNT(*) AS cnt FROM virus_master WHERE ictv_id IS NOT NULL")
    print(f"  virus_master with ictv_id: {cur.fetchone()['cnt']}")

conn.close()
