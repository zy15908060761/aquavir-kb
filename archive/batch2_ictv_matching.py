"""
Batch 2b: ICTV自动匹配扩增
利用ictv_taxonomy表17554行完整ICTV分类数据与virus_master模糊匹配
"""
import sqlite3
import re
from pathlib import Path

DB = Path("F:/甲壳动物数据库/crustacean_virus_core.db")
conn = sqlite3.connect(str(DB))
conn.execute("PRAGMA foreign_keys = ON")
cur = conn.cursor()

print("Current ICTV status distribution:")
rows = cur.execute("SELECT ictv_status, COUNT(*) FROM virus_ictv_status GROUP BY ictv_status").fetchall()
for r in rows:
    print(f"  {r[0]:30s} {r[1]}")

total_masters = cur.execute("SELECT COUNT(*) FROM virus_master WHERE is_crustacean_virus=1").fetchone()[0]
print(f"\nTotal crustacean virus masters: {total_masters}")

# Get virus_master records not yet mapped
unmapped = cur.execute("""
    SELECT vm.master_id, vm.canonical_name, vm.virus_family, vm.virus_genus
    FROM virus_master vm
    LEFT JOIN virus_ictv_status vis ON vm.master_id = vis.master_id
    WHERE (vis.ictv_status IS NULL OR vis.ictv_status IN ('unclassified_not_expected', 'pending_review'))
      AND vm.is_crustacean_virus = 1
""").fetchall()
print(f"Records to attempt matching: {len(unmapped)}")

# Extract ICTV species names and their taxonomic context
ictv_data = cur.execute("""
    SELECT DISTINCT it.species, it.genus, it.family, it.genome_composition, it.msl_version
    FROM ictv_taxonomy it
    WHERE it.species IS NOT NULL
""").fetchall()
print(f"ICTV unique species entries: {len(ictv_data)}")

# Normalize names for comparison
def normalize(name):
    """Normalize virus name for fuzzy comparison"""
    if not name:
        return ""
    n = name.lower().strip()
    n = re.sub(r'[^a-z0-9\s]', '', n)
    n = re.sub(r'\s+', ' ', n)
    return n

def match_quality(canonical, ictv_species, vm_family, ictv_family):
    """Return match quality score: 'exact', 'high', 'medium', 'low'"""
    cn = normalize(canonical)
    isp = normalize(ictv_species)

    if cn == isp:
        return "exact"

    # Check if one contains the other
    if cn in isp or isp in cn:
        return "high"

    # Check word-level Jaccard
    cn_words = set(cn.split())
    isp_words = set(isp.split())
    if not cn_words or not isp_words:
        return "low"
    overlap = cn_words & isp_words
    if len(overlap) >= 3 and len(overlap) / min(len(cn_words), len(isp_words)) >= 0.5:
        return "high"
    if len(overlap) >= 2:
        return "medium"

    # Family match bonus
    if vm_family and ictv_family and normalize(vm_family) == normalize(ictv_family):
        if len(overlap) >= 1:
            return "medium"

    return "low"

matches = []

for vm_id, vm_name, vm_family, vm_genus in unmapped:
    best_quality = 0  # 4=exact, 3=high, 2=medium, 1=low
    best_match = None

    for ictv_species, ictv_genus, ictv_family, genome_comp, msl_ver in ictv_data:
        quality = match_quality(vm_name, ictv_species, vm_family, ictv_family)
        qscore = {"exact": 4, "high": 3, "medium": 2, "low": 1}.get(quality, 0)

        if qscore > best_quality:
            best_quality = qscore
            best_match = (ictv_species, ictv_genus, ictv_family, genome_comp, msl_ver, quality)
            if qscore == 4:
                break  # exact match, stop here

    if best_match and best_quality >= 2:  # medium or better
        matches.append((vm_id, vm_name, best_match[0], best_match[1], best_match[2],
                       best_match[3], best_match[5], vm_family, best_quality))

print(f"\nMatched with medium+ confidence: {len(matches)}")
for qlvl in ["exact", "high", "medium"]:
    cnt = sum(1 for m in matches if m[6] == qlvl)
    print(f"  {qlvl}: {cnt}")

# Apply matches
count_mapped = 0
count_inserted = 0

for m in matches:
    vm_id, vm_name, ictv_species, ictv_genus, ictv_family, genome_comp, quality, vm_family, qscore = m

    # Update virus_ictv_status
    cur.execute("""
        INSERT INTO virus_ictv_status (master_id, ictv_status, mapping_count, best_confidence, reason, updated_at)
        VALUES (?, 'mapped', 1, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(master_id) DO UPDATE SET
            ictv_status = 'mapped',
            mapping_count = COALESCE(virus_ictv_status.mapping_count, 0) + 1,
            best_confidence = CASE
                WHEN ? = 'exact' THEN 'exact'
                WHEN ? = 'high' AND virus_ictv_status.best_confidence NOT IN ('exact')
                    THEN 'high'
                WHEN ? = 'medium' AND virus_ictv_status.best_confidence NOT IN ('exact','high')
                    THEN 'medium'
                ELSE virus_ictv_status.best_confidence
            END,
            reason = 'auto_matched:' || ? || ' -> ICTV ' || ?,
            updated_at = CURRENT_TIMESTAMP
    """, (vm_id, quality, f"auto_matched:{quality} -> ICTV {ictv_species}",
          quality, quality, quality,
          vm_name[:50], ictv_species[:100]))
    count_mapped += cur.rowcount if cur.rowcount else 0

    # Also create virus_ictv_mappings entry
    cur.execute("""
        INSERT INTO virus_ictv_mappings (master_id, ictv_taxon_name, ictv_family, match_confidence, match_method, created_at)
        SELECT ?, ?, ?, ?, 'fuzzy_name_match', CURRENT_TIMESTAMP
        WHERE NOT EXISTS (
            SELECT 1 FROM virus_ictv_mappings
            WHERE master_id = ? AND ictv_taxon_name = ?
        )
    """, (vm_id, ictv_species, ictv_family, quality, vm_id, ictv_species))
    count_inserted += cur.rowcount

print(f"\nUpdated virus_ictv_status: {count_mapped}")
print(f"Inserted virus_ictv_mappings: {count_inserted}")

# Report new ICTV distribution
print("\nNew ICTV status distribution:")
rows = cur.execute("SELECT ictv_status, COUNT(*) FROM virus_ictv_status GROUP BY ictv_status").fetchall()
for r in rows:
    print(f"  {r[0]:30s} {r[1]}")

conn.commit()
conn.close()
print("\nSaved.")
