"""
Batch 5: Final completeness fill
- interpro_go_backfill_queue: fill protein_id via uniprot_protein_links
- interpro_annotations.go_terms: enrich from interpro_go_terms
- pathogenicity_evidence: enrich from virulence_profiles
- sample_collections: infer continent from country
- Check GO terms linked to valid proteins
"""
import sqlite3
from pathlib import Path

DB = Path("F:/甲壳动物数据库/crustacean_virus_core.db")
conn = sqlite3.connect(str(DB))
conn.execute("PRAGMA foreign_keys = ON")
cur = conn.cursor()

# ============================================================
# 1. interpro_go_backfill_queue: fill protein_id
# ============================================================
print("1. interpro_go_backfill_queue -> protein_id linking")
before = cur.execute("SELECT COUNT(*) FROM interpro_go_backfill_queue WHERE protein_id IS NULL").fetchone()[0]
print("   Before: %d NULL" % before)

# Via uniprot_id -> uniprot_protein_links
cur.execute("""
    UPDATE interpro_go_backfill_queue SET protein_id = (
        SELECT upl.protein_id FROM uniprot_protein_links upl
        WHERE upl.uniprot_id = interpro_go_backfill_queue.uniprot_id
        LIMIT 1
    )
    WHERE protein_id IS NULL
      AND uniprot_id IS NOT NULL
      AND EXISTS (
        SELECT 1 FROM uniprot_protein_links upl
        WHERE upl.uniprot_id = interpro_go_backfill_queue.uniprot_id
      )
""")
print("   Via uniprot_id: %d" % cur.rowcount)

# Via ncbi_protein_acc -> uniprot_annotations -> uniprot_protein_links
cur.execute("""
    UPDATE interpro_go_backfill_queue SET protein_id = (
        SELECT upl.protein_id FROM uniprot_annotations ua
        JOIN uniprot_protein_links upl ON ua.uniprot_id = upl.uniprot_id
        WHERE ua.ncbi_protein_acc = interpro_go_backfill_queue.ncbi_protein_acc
        LIMIT 1
    )
    WHERE protein_id IS NULL
      AND ncbi_protein_acc IS NOT NULL
""")
print("   Via ncbi_protein_acc: %d" % cur.rowcount)

after = cur.execute("SELECT COUNT(*) FROM interpro_go_backfill_queue WHERE protein_id IS NULL").fetchone()[0]
print("   After: %d NULL (linked %d)" % (after, before-after))

# ============================================================
# 2. interpro_annotations.go_terms enrichment
# ============================================================
print()
print("2. interpro_annotations.go_terms enrichment from interpro_go_terms")
before = cur.execute("SELECT COUNT(*) FROM interpro_annotations WHERE go_terms IS NULL OR TRIM(go_terms)=''").fetchone()[0]

# Try to link: interpro_annotations has protein_id now, interpro_go_terms also has protein_id
cur.execute("""
    UPDATE interpro_annotations SET go_terms = (
        SELECT GROUP_CONCAT(igt.go_name, '; ') FROM interpro_go_terms igt
        WHERE igt.protein_id = interpro_annotations.protein_id
        GROUP BY igt.protein_id
    )
    WHERE (go_terms IS NULL OR TRIM(go_terms) = '')
      AND protein_id IS NOT NULL
      AND EXISTS (
        SELECT 1 FROM interpro_go_terms igt
        WHERE igt.protein_id = interpro_annotations.protein_id
      )
""")
print("   From interpro_go_terms (by protein_id): %d" % cur.rowcount)

after = cur.execute("SELECT COUNT(*) FROM interpro_annotations WHERE go_terms IS NULL OR TRIM(go_terms)=''").fetchone()[0]
total = cur.execute("SELECT COUNT(*) FROM interpro_annotations").fetchone()[0]
print("   Still NULL: %d/%d (%d%% filled)" % (after, total, (total-after)*100//total))

# ============================================================
# 3. pathogenicity_evidence: fill disease_symptoms from virulence_profiles
# ============================================================
print()
print("3. pathogenicity_evidence.disease_symptoms from virulence_profiles")
before = cur.execute("SELECT COUNT(*) FROM pathogenicity_evidence WHERE disease_symptoms IS NULL OR TRIM(disease_symptoms)=''").fetchone()[0]

cur.execute("""
    UPDATE pathogenicity_evidence SET disease_symptoms = (
        SELECT vp.pathogenic_mechanism FROM virulence_profiles vp
        JOIN virus_master vm ON vm.canonical_name = vp.virus_name
        WHERE vm.master_id = pathogenicity_evidence.virus_master_id
          AND vp.pathogenic_mechanism IS NOT NULL
        LIMIT 1
    )
    WHERE (disease_symptoms IS NULL OR TRIM(disease_symptoms) = '')
""")
print("   From virulence_profiles: %d" % cur.rowcount)

after = cur.execute("SELECT COUNT(*) FROM pathogenicity_evidence WHERE disease_symptoms IS NULL OR TRIM(disease_symptoms)=''").fetchone()[0]
total = cur.execute("SELECT COUNT(*) FROM pathogenicity_evidence").fetchone()[0]
print("   Still NULL: %d/%d" % (after, total))

# ============================================================
# 4. sample_collections: infer continent from country
# ============================================================
print()
print("4. sample_collections.continent inference from country")

CONTINENT_MAP = {
    "China": "Asia", "Japan": "Asia", "Korea": "Asia", "South Korea": "Asia",
    "Thailand": "Asia", "Vietnam": "Asia", "Indonesia": "Asia", "India": "Asia",
    "Malaysia": "Asia", "Philippines": "Asia", "Taiwan": "Asia", "Singapore": "Asia",
    "Bangladesh": "Asia", "Myanmar": "Asia", "Cambodia": "Asia", "Sri Lanka": "Asia",
    "Iran": "Asia", "Israel": "Asia", "Turkey": "Asia", "Saudi Arabia": "Asia",
    "United Arab Emirates": "Asia", "Oman": "Asia", "Yemen": "Asia",
    "USA": "North America", "United States": "North America", "Canada": "North America",
    "Mexico": "North America", "Costa Rica": "North America", "Panama": "North America",
    "Nicaragua": "North America", "Honduras": "North America", "Guatemala": "North America",
    "Belize": "North America", "Cuba": "North America", "Dominican Republic": "North America",
    "Jamaica": "North America", "Haiti": "North America", "Puerto Rico": "North America",
    "Brazil": "South America", "Ecuador": "South America", "Peru": "South America",
    "Colombia": "South America", "Venezuela": "South America", "Chile": "South America",
    "Argentina": "South America", "Uruguay": "South America",
    "France": "Europe", "Germany": "Europe", "Italy": "Europe", "Spain": "Europe",
    "United Kingdom": "Europe", "Netherlands": "Europe", "Belgium": "Europe",
    "Portugal": "Europe", "Greece": "Europe", "Norway": "Europe", "Sweden": "Europe",
    "Denmark": "Europe", "Ireland": "Europe", "Poland": "Europe", "Russia": "Europe",
    "Egypt": "Africa", "South Africa": "Africa", "Morocco": "Africa", "Tunisia": "Africa",
    "Nigeria": "Africa", "Madagascar": "Africa", "Kenya": "Africa", "Tanzania": "Africa",
    "Mozambique": "Africa",
    "Australia": "Oceania", "New Zealand": "Oceania", "Fiji": "Oceania",
    "Papua New Guinea": "Oceania", "New Caledonia": "Oceania", "Guam": "Oceania",
    "French Polynesia": "Oceania", "Hawaii": "Oceania",
}

before = cur.execute("SELECT COUNT(*) FROM sample_collections WHERE continent IS NULL OR TRIM(continent)=''").fetchone()[0]

for country, continent in CONTINENT_MAP.items():
    cur.execute("""
        UPDATE sample_collections SET continent = ?
        WHERE (continent IS NULL OR TRIM(continent) = '')
          AND country LIKE '%' || ? || '%'
    """, (continent, country))

after = cur.execute("SELECT COUNT(*) FROM sample_collections WHERE continent IS NULL OR TRIM(continent)=''").fetchone()[0]
total = cur.execute("SELECT COUNT(*) FROM sample_collections").fetchone()[0]
print("   Before: %d, After: %d/%d (%d%% filled)" % (before, after, total, (total-after)*100//total))

# ============================================================
# 5. Check interpro_go_terms.protein_id validity
# ============================================================
print()
print("5. interpro_go_terms.protein_id validation")
go_total = cur.execute("SELECT COUNT(*) FROM interpro_go_terms").fetchone()[0]
go_linked = cur.execute("""
    SELECT COUNT(*) FROM interpro_go_terms igt
    JOIN viral_proteins vp ON igt.protein_id = vp.protein_id
""").fetchone()[0]
print("   Total GO terms: %d, linked to valid proteins: %d (%d%%)" % (go_total, go_linked, go_linked*100//go_total if go_total else 0))

conn.commit()
conn.close()
print()
print("Batch 5 complete. Saved.")
