"""
Batch 6: Third round of quality fixes
- Fix family inconsistency between viral_isolates and virus_master
- Normalize host names (remove parenthetical annotations)
- Drop empty tables
- protein_structures linkage via cluster_id sequence matching
"""
import sqlite3
from pathlib import Path

DB = Path("F:/甲壳动物数据库/crustacean_virus_core.db")
conn = sqlite3.connect(str(DB))
conn.execute("PRAGMA foreign_keys = ON")
cur = conn.cursor()

# ============================================================
# 1. Fix family inconsistency: sync viral_isolates.taxon_family from virus_master
# ============================================================
print("1. Syncing viral_isolates.taxon_family from virus_master")
before = cur.execute("""
    SELECT COUNT(*) FROM viral_isolates vi
    JOIN virus_master vm ON vi.master_id = vm.master_id
    WHERE (vi.taxon_family IS NULL OR TRIM(vi.taxon_family) = '')
      AND vm.virus_family IS NOT NULL AND TRIM(vm.virus_family) <> ''
""").fetchone()[0]
print("   Empty/missing family in isolates: %d" % before)

cur.execute("""
    UPDATE viral_isolates SET taxon_family = (
        SELECT vm.virus_family FROM virus_master vm
        WHERE vm.master_id = viral_isolates.master_id
          AND vm.virus_family IS NOT NULL
          AND TRIM(vm.virus_family) <> ''
    )
    WHERE (taxon_family IS NULL OR TRIM(taxon_family) = '')
""")
print("   Filled from master: %d" % cur.rowcount)

# Now check actual disagreements (both non-empty, different)
disagree = cur.execute("""
    SELECT COUNT(*) FROM viral_isolates vi
    JOIN virus_master vm ON vi.master_id = vm.master_id
    WHERE vi.taxon_family IS NOT NULL AND TRIM(vi.taxon_family) <> ''
      AND vm.virus_family IS NOT NULL AND TRIM(vm.virus_family) <> ''
      AND vi.taxon_family <> vm.virus_family
""").fetchone()[0]
print("   Still disagree: %d" % disagree)

# ============================================================
# 2. Normalize host names
# ============================================================
print()
print("2. Normalizing host scientific names")
import re

rows = cur.execute("""
    SELECT host_id, scientific_name FROM crustacean_hosts
    WHERE scientific_name LIKE '%(%)%' OR scientific_name LIKE '%(%)%'
""").fetchall()

for host_id, sci_name in rows:
    # Remove parenthetical annotations
    # "Penaeus vannamei (shrimp)" -> "Penaeus vannamei"
    # "Penaeus (Litopenaeus) vannamei" -> "Litopenaeus vannamei" (keep the subgenus form)
    # "Penaeus indicus (synonym: Fenneropenaeus indicus)" -> "Penaeus indicus"
    # "tiger shrimp (Penaeus monodon)" -> "Penaeus monodon"

    clean = sci_name.strip()

    # Pattern 1: "common (scientific)" -> use scientific
    m = re.match(r'^([a-z].*?)\s+\(([A-Z][a-z]+ [a-z]+)\)', clean)
    if m:
        clean = m.group(2)

    # Pattern 2: "Genus (Subgenus) species" -> use "Genus species"
    m = re.match(r'^([A-Z][a-z]+)\s+\(([A-Z][a-z]+)\)\s+([a-z]+.*)', clean)
    if m:
        # Keep original but remove subgenus: "Genus species"
        clean = m.group(1) + ' ' + m.group(3)

    # Pattern 3: "Scientific (synonym: Other)" -> use Scientific
    m = re.match(r'^([A-Z][a-z]+ [a-z]+)\s+\(synonym:', clean)
    if m:
        clean = m.group(1)

    # Pattern 4: "Scientific (common)" -> use Scientific
    m = re.match(r'^([A-Z][a-z]+ [a-z]+)\s+\([a-z]', clean)
    if m:
        clean = m.group(1)

    # Pattern 5: "Scientific (wild population)" -> use Scientific
    m = re.match(r'^([A-Z][a-z]+ [a-z]+)\s+\(wild', clean)
    if m:
        clean = m.group(1)

    # Remove trailing "Bate" or similar author abbreviations
    clean = re.sub(r'\s+(Bate|De Man|de Man|sp\.)\s*$', '', clean)

    if clean != sci_name.strip():
        # Check if the cleaned name already exists
        existing = cur.execute(
            "SELECT host_id FROM crustacean_hosts WHERE scientific_name = ? AND host_id <> ?",
            (clean, host_id)
        ).fetchone()

        if existing:
            # Merge: update all referencing tables first
            cur.execute("UPDATE infection_records SET host_id = ? WHERE host_id = ?", (existing[0], host_id))
            cur.execute("UPDATE host_range_evidence SET host_id = ? WHERE host_id = ?", (existing[0], host_id))
            cur.execute("UPDATE host_biology_profiles SET host_id = ? WHERE host_id = ?", (existing[0], host_id))
            cur.execute("UPDATE host_taxonomy_profiles SET host_id = ? WHERE host_id = ?", (existing[0], host_id))
            cur.execute("UPDATE host_ecological_traits SET host_id = ? WHERE host_id = ?", (existing[0], host_id))
            cur.execute("UPDATE host_aliases SET host_id = ? WHERE host_id = ?", (existing[0], host_id))
            cur.execute("UPDATE gbif_occurrences SET host_id = ? WHERE host_id = ?", (existing[0], host_id))
            cur.execute("UPDATE obis_occurrences SET host_id = ? WHERE host_id = ?", (existing[0], host_id))
            cur.execute("UPDATE pathogenicity_evidence SET host_id = ? WHERE host_id = ?", (existing[0], host_id))
            cur.execute("UPDATE outbreak_events SET host_id = ? WHERE host_id = ?", (existing[0], host_id))
            cur.execute("DELETE FROM crustacean_hosts WHERE host_id = ?", (host_id,))
            print("   Merged '%s' -> '%s' (id %d -> %d)" % (sci_name, clean, host_id, existing[0]))
        else:
            cur.execute("""
                UPDATE crustacean_hosts SET scientific_name = ?
                WHERE host_id = ?
            """, (clean, host_id))
            print("   Normalized '%s' -> '%s'" % (sci_name, clean))

# ============================================================
# 3. Drop empty unused tables
# ============================================================
print()
print("3. Dropping empty tables")
empty_tables = []
for (name,) in cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name").fetchall():
    cnt = cur.execute("SELECT COUNT(*) FROM [" + name + "]").fetchone()[0]
    if cnt == 0:
        empty_tables.append(name)

for t in empty_tables:
    cur.execute("DROP TABLE IF EXISTS [" + t + "]")
    print("   Dropped: " + t)

# ============================================================
# 4. protein_structures linkage via cluster_id -> sequence matching
# ============================================================
print()
print("4. protein_structures -> viral_proteins via sequence matching")
# Approach: for each protein_structure, find nr_protein_clusters representative_aa_seq
# Then find reannotated_orfs with matching aa_sequence
# Then link to viral_proteins via isolate_id

# First check if representative_aa_seq and aa_sequence columns exist and have data
npc_with_seq = cur.execute(
    "SELECT COUNT(*) FROM nr_protein_clusters WHERE representative_aa_seq IS NOT NULL AND TRIM(representative_aa_seq) <> ''"
).fetchone()[0]
print("   nr clusters with AA sequences: %d" % npc_with_seq)

orf_with_seq = cur.execute(
    "SELECT COUNT(*) FROM reannotated_orfs WHERE aa_sequence IS NOT NULL AND TRIM(aa_sequence) <> ''"
).fetchone()[0]
print("   ORFs with AA sequences: %d" % orf_with_seq)

# Build a hash-based lookup for efficiency
# Take first 30 chars of AA sequence as signature
print("   Building sequence index...")
cur.execute("""
    CREATE TEMP TABLE IF NOT EXISTS orf_seq_idx AS
    SELECT reanno_id, isolate_id, aa_sequence,
           SUBSTR(aa_sequence, 1, 60) AS seq_sig
    FROM reannotated_orfs
    WHERE aa_sequence IS NOT NULL AND TRIM(aa_sequence) <> ''
      AND LENGTH(aa_sequence) >= 20
""")
cnt = cur.execute("SELECT COUNT(*) FROM orf_seq_idx").fetchone()[0]
print("   Indexed %d ORFs" % cnt)

# For each protein_structure, find matching ORF
linked_count = 0
structures = cur.execute("""
    SELECT ps.structure_id, ps.cluster_id, npc.representative_aa_seq
    FROM protein_structures ps
    JOIN nr_protein_clusters npc ON ps.cluster_id = npc.cluster_id
    WHERE ps.protein_id IS NULL
      AND npc.representative_aa_seq IS NOT NULL
""").fetchall()

for struct_id, cluster_id, aa_seq in structures:
    if not aa_seq or len(aa_seq) < 20:
        continue

    sig = aa_seq[:60]
    # Find matching ORF
    match = cur.execute("""
        SELECT reanno_id, isolate_id FROM orf_seq_idx
        WHERE seq_sig = ? AND aa_sequence = ?
        LIMIT 1
    """, (sig, aa_seq)).fetchone()

    if match:
        reanno_id, isolate_id = match
        # Now find viral_proteins for this isolate
        vp = cur.execute("""
            SELECT protein_id FROM viral_proteins
            WHERE isolate_id = ?
            ORDER BY ABS(aa_length - ?)
            LIMIT 1
        """, (isolate_id, len(aa_seq))).fetchone()

        if vp:
            cur.execute("""
                UPDATE protein_structures SET protein_id = ?, reanno_id = ?
                WHERE structure_id = ?
            """, (vp[0], reanno_id, struct_id))
            linked_count += 1

print("   Structures linked: %d/%d" % (linked_count, len(structures)))

# Clean up temp table
cur.execute("DROP TABLE IF EXISTS orf_seq_idx")

# ============================================================
# 5. Final check
# ============================================================
print()
print("=== Post-fix summary ===")
disagree = cur.execute("""
    SELECT COUNT(*) FROM viral_isolates vi
    JOIN virus_master vm ON vi.master_id = vm.master_id
    WHERE vi.taxon_family IS NOT NULL AND TRIM(vi.taxon_family) <> ''
      AND vm.virus_family IS NOT NULL AND TRIM(vm.virus_family) <> ''
      AND vi.taxon_family <> vm.virus_family
""").fetchone()[0]
print("Family inconsistencies remaining: %d" % disagree)

host_count = cur.execute("SELECT COUNT(*) FROM crustacean_hosts").fetchone()[0]
print("Host records: %d" % host_count)

ps_linked = cur.execute("SELECT COUNT(*) FROM protein_structures WHERE protein_id IS NOT NULL").fetchone()[0]
ps_total = cur.execute("SELECT COUNT(*) FROM protein_structures").fetchone()[0]
print("protein_structures linked: %d/%d" % (ps_linked, ps_total))

conn.commit()
conn.close()
print()
print("Batch 6 complete. Saved.")
