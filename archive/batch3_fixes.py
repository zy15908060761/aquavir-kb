"""
Batch 3: Combined fixes
- genome_type further filling (from virus taxonomy patterns)
- GenBank geo extraction (better XML parser)
- Database cleanup
"""
import sqlite3
import os
import re
import xml.etree.ElementTree as ET
from pathlib import Path

DB = Path("F:/甲壳动物数据库/crustacean_virus_core.db")
GB_DIR = Path("F:/甲壳动物数据库/external_data/genbank_metadata")

conn = sqlite3.connect(str(DB))
conn.execute("PRAGMA foreign_keys = ON")
cur = conn.cursor()

# ============================================================
# Part 1: Additional genome_type filling
# ============================================================
print("=" * 60)
print("PART 1: genome_type - deeper inference")
print("=" * 60)

# Strategy 1: Infer from known virus families
FAMILY_GENOME = {
    "Nimaviridae": "dsDNA",
    "Roniviridae": "ssRNA(+)",
    "Dicistroviridae": "ssRNA(+)",
    "Parvoviridae": "ssDNA",
    "Nodaviridae": "ssRNA(+)",
    "Iridoviridae": "dsDNA",
    "Artiviridae": "dsRNA",
    "Sarthroviridae": "ssRNA(+)",
    "Phenuiviridae": "ssRNA(-)",
    "Chuviridae": "ssRNA(-)",
    "Natareviridae": "ssRNA(-)",
    "Cruliviridae": "ssRNA(-)",
    "Flaviviridae": "ssRNA(+)",
    "Rhabdoviridae": "ssRNA(-)",
    "Reoviridae": "dsRNA",
    "Totiviridae": "dsRNA",
    "Bunyaviridae": "ssRNA(-)",
    "Picornaviridae": "ssRNA(+)",
    "Caliciviridae": "ssRNA(+)",
    "Tombusviridae": "ssRNA(+)",
    "Togaviridae": "ssRNA(+)",
    "Coronaviridae": "ssRNA(+)",
    "Paramyxoviridae": "ssRNA(-)",
    "Orthomyxoviridae": "ssRNA(-)",
    "Filoviridae": "ssRNA(-)",
    "Retroviridae": "ssRNA-RT",
    "Hepadnaviridae": "dsDNA-RT",
    "Circoviridae": "ssDNA",
    "Adenoviridae": "dsDNA",
    "Poxviridae": "dsDNA",
    "Herpesviridae": "dsDNA",
    "Baculoviridae": "dsDNA",
    "Nudiviridae": "dsDNA",
    "Polyomaviridae": "dsDNA",
    "Papillomaviridae": "dsDNA",
    "Mimiviridae": "dsDNA",
    "Phycodnaviridae": "dsDNA",
    "Iflaviridae": "ssRNA(+)",
    "Solinviviridae": "ssRNA(+)",
    "Astroviridae": "ssRNA(+)",
    "Hepeviridae": "ssRNA(+)",
    "Matonaviridae": "ssRNA(+)",
    "Pneumoviridae": "ssRNA(-)",
    "Peribunyaviridae": "ssRNA(-)",
    "Hantaviridae": "ssRNA(-)",
    "Nairoviridae": "ssRNA(-)",
    "Alloherpesviridae": "dsDNA",
    "Malacoherpesviridae": "dsDNA",
}

for family, gt in FAMILY_GENOME.items():
    cur.execute("""
        UPDATE viral_isolates SET genome_type = ?
        WHERE genome_type IS NULL AND taxon_family = ?
    """, (gt, family))
    n = cur.rowcount
    if n:
        print(f"  Family '{family}' -> {gt}: {n} rows")

# Strategy 2: Infer from virus name patterns
NAME_PATTERNS = [
    ("%totivirus%", "dsRNA"),
    ("%partitivirus%", "dsRNA"),
    ("%reovirus%", "dsRNA"),
    ("%birnavirus%", "dsRNA"),
    ("%picornavirus%", "ssRNA(+)"),
    ("%flavivirus%", "ssRNA(+)"),
    ("%rhabdovirus%", "ssRNA(-)"),
    ("%parvovirus%", "ssDNA"),
    ("%densovirus%", "ssDNA"),
    ("%circovirus%", "ssDNA"),
    ("%baculovirus%", "dsDNA"),
    ("%nimavirus%", "dsDNA"),
    ("%nudivirus%", "dsDNA"),
    ("%herpesvirus%", "dsDNA"),
    ("%iridovirus%", "dsDNA"),
    ("%adenovirus%", "dsDNA"),
    ("%poxvirus%", "dsDNA"),
    ("%nodavirus%", "ssRNA(+)"),
    ("%maculavirus%", "ssRNA(+)"),
    ("%bunyavirus%", "ssRNA(-)"),
    ("%hantavirus%", "ssRNA(-)"),
    ("%orthomyxovirus%", "ssRNA(-)"),
    ("%coronavirus%", "ssRNA(+)"),
    ("%dicistrovirus%", "ssRNA(+)"),
    ("%iflavirus%", "ssRNA(+)"),
    ("%calicivirus%", "ssRNA(+)"),
    ("%hepandensovirus%", "ssDNA"),
    ("%circovirus%", "ssDNA"),
    ("%nidovirus%", "ssRNA(+)"),
    ("%ranavirus%", "dsDNA"),
    ("%virophage%", "dsDNA"),
]

for pattern, gt in NAME_PATTERNS:
    cur.execute("""
        UPDATE viral_isolates SET genome_type = ?
        WHERE genome_type IS NULL AND (virus_name LIKE ? OR keywords LIKE ?)
    """, (gt, pattern, pattern))
    n = cur.rowcount
    if n:
        print(f"  Pattern '{pattern}' -> {gt}: {n} rows")

# Strategy 3: ICTV genome_composition fallback (via species-level match)
cur.execute("""
    UPDATE viral_isolates SET genome_type = (
        SELECT DISTINCT it.genome_composition FROM ictv_taxonomy it
        WHERE it.genus = viral_isolates.taxon_genus
          AND it.genome_composition IS NOT NULL
        LIMIT 1
    )
    WHERE genome_type IS NULL AND taxon_genus IS NOT NULL
      AND EXISTS (
        SELECT 1 FROM ictv_taxonomy it
        WHERE it.genus = viral_isolates.taxon_genus
          AND it.genome_composition IS NOT NULL
      )
""")
print(f"  ICTV genus-level: {cur.rowcount} rows")

# Strategy 4: from nucleotide_records molecule_type
cur.execute("""
    UPDATE viral_isolates SET genome_type = (
        SELECT CASE nr.molecule_type
            WHEN 'DNA' THEN 'dsDNA'
            WHEN 'RNA' THEN NULL
            WHEN 'ssRNA' THEN 'ssRNA'
            WHEN 'dsRNA' THEN 'dsRNA'
            ELSE NULL
        END
        FROM nucleotide_records nr
        WHERE nr.isolate_id = viral_isolates.isolate_id
        LIMIT 1
    )
    WHERE genome_type IS NULL
""")
print(f"  nucleotide_records: {cur.rowcount} rows")

remaining = cur.execute("SELECT COUNT(*) FROM viral_isolates WHERE genome_type IS NULL").fetchone()[0]
total = cur.execute("SELECT COUNT(*) FROM viral_isolates").fetchone()[0]
print(f"genome_type still NULL: {remaining}/{total} ({100-remaining*100//total}% filled)")

# ============================================================
# Part 2: GenBank geo extraction - improved
# ============================================================
print("\n" + "=" * 60)
print("PART 2: GenBank geo extraction (improved)")
print("=" * 60)

def parse_genbank_xml_v2(filepath):
    """Extract geo data from GenBank XML - handle nested qualifiers"""
    try:
        tree = ET.parse(filepath)
        root = tree.getroot()
    except:
        return None

    result = {"accession": None, "country": None, "lat": None, "lon": None,
              "collection_date": None, "isolation_source": None}

    # Get primary accession
    for elem in root.iter():
        tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag

        if tag == "GBSeq_primary-accession":
            result["accession"] = elem.text
        if tag == "GBSeq_accession-version" and not result["accession"]:
            result["accession"] = elem.text

        if tag == "GBQualifier":
            qual_name = None
            qual_value = None
            for child in elem:
                ctag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
                if ctag == "GBQualifier_name":
                    qual_name = child.text
                if ctag == "GBQualifier_value":
                    qual_value = child.text

            if qual_name == "country" and qual_value and not result["country"]:
                result["country"] = qual_value
            if qual_name == "isolation_source" and qual_value and not result["isolation_source"]:
                result["isolation_source"] = qual_value
            if qual_name == "collection_date" and qual_value and not result["collection_date"]:
                result["collection_date"] = qual_value
            if qual_name == "lat_lon" and qual_value:
                # Parse "23.5 N 116.7 E" format
                text = qual_value.replace(",", " ")
                # Extract numbers with direction
                parts = re.findall(r'([\d.]+)\s*([NnSs])\s*([\d.]+)\s*([EeWw])', text)
                if parts:
                    lat_val = float(parts[0][0])
                    if parts[0][1].upper() == 'S':
                        lat_val = -lat_val
                    lon_val = float(parts[0][2])
                    if parts[0][3].upper() == 'W':
                        lon_val = -lon_val
                    result["lat"] = lat_val
                    result["lon"] = lon_val

    # Also try to extract country from lat_lon or organism
    if result["country"]:
        # Clean country - remove lat_lon often embedded
        # e.g., "China: Guangdong, 23.5N 116.7E"
        # Extract just the country part
        result["country"] = re.sub(r',?\s*\d+\.?\d*\s*[NSEW].*$', '', result["country"])
        result["country"] = result["country"].split(":")[0].strip()

    return result if result["accession"] else None

# Scan files more efficiently - process in batches
geo_data = {}
file_count = 0
geo_count = 0

for root_dir, dirs, files in os.walk(GB_DIR):
    for fname in files:
        if not fname.endswith(".xml"):
            continue
        file_count += 1
        fp = os.path.join(root_dir, fname)
        data = parse_genbank_xml_v2(str(fp))
        if data and data["accession"] and (data["country"] or data["lat"] or data["isolation_source"]):
            geo_data[data["accession"]] = data
            geo_count += 1

        if file_count % 1000 == 0:
            print(f"  Processed {file_count} files, found {geo_count} geo records...")

print(f"Total files: {file_count}, with geo/iso data: {geo_count}")

# Apply geo data to database
# First build an accession -> isolate_id map
acc_map = {}
for row in cur.execute("SELECT isolate_id, accession FROM viral_isolates").fetchall():
    acc_map[row[1]] = row[0]
    # Also store without version
    base = row[1].split(".")[0] if "." in row[1] else row[1]
    if base not in acc_map:
        acc_map[base] = row[0]

col_updated = 0
iso_updated = 0

for acc, geo in geo_data.items():
    # Find isolate
    iso_id = acc_map.get(acc)
    if not iso_id:
        base_acc = acc.split(".")[0] if "." in acc else acc
        iso_id = acc_map.get(base_acc)
    if not iso_id:
        continue

    # Find collection_id
    col_row = cur.execute(
        "SELECT collection_id FROM infection_records WHERE isolate_id = ? LIMIT 1",
        (iso_id,)
    ).fetchone()
    if not col_row:
        continue
    col_id = col_row[0]

    # Check what needs updating
    existing = cur.execute(
        "SELECT country, latitude, longitude FROM sample_collections WHERE collection_id = ?",
        (col_id,)
    ).fetchone()

    if existing:
        updated = False
        new_country = existing[0]
        new_lat = existing[1]
        new_lon = existing[2]

        if geo.get("country") and not new_country:
            new_country = geo["country"]
            updated = True
        if geo.get("lat") is not None and new_lat is None:
            new_lat = geo["lat"]
            updated = True
        if geo.get("lon") is not None and new_lon is None:
            new_lon = geo["lon"]
            updated = True

        if updated:
            cur.execute("""
                UPDATE sample_collections SET country = COALESCE(NULLIF(?,''), country),
                    latitude = COALESCE(?, latitude),
                    longitude = COALESCE(?, longitude)
                WHERE collection_id = ?
            """, (new_country, new_lat, new_lon, col_id))
            col_updated += 1

    # Also update isolation_source if available
    if geo.get("isolation_source"):
        existing_src = cur.execute(
            "SELECT isolation_source FROM infection_records WHERE isolate_id = ?",
            (iso_id,)
        ).fetchone()
        if existing_src and not existing_src[0]:
            cur.execute("""
                UPDATE infection_records SET isolation_source = ?
                WHERE isolate_id = ?
            """, (geo["isolation_source"], iso_id))
            iso_updated += 1

print(f"Collection records updated: {col_updated}")
print(f"Isolation sources updated: {iso_updated}")

remaining_country = cur.execute("""
    SELECT COUNT(*) FROM analysis_target_isolates vi
    LEFT JOIN infection_records ir ON vi.isolate_id = ir.isolate_id
    LEFT JOIN sample_collections s ON ir.collection_id = s.collection_id
    LEFT JOIN isolate_curated_profiles icp ON vi.isolate_id = icp.isolate_id
    WHERE COALESCE(NULLIF(s.country,''), NULLIF(icp.country,'')) IS NULL
""").fetchone()[0]
print(f"Target isolates still without country: {remaining_country}")

# ============================================================
# Part 3: Database cleanup
# ============================================================
print("\n" + "=" * 60)
print("PART 3: Database cleanup")
print("=" * 60)

# Remove archive/backup tables
archive_tables = cur.execute("""
    SELECT name FROM sqlite_master
    WHERE type='table'
      AND (name LIKE '\\_%' ESCAPE '\\'
           OR name LIKE '%archive%'
           OR name LIKE '%_old'
           OR name LIKE '%_backup'
           OR name LIKE '%_tmp')
""").fetchall()
for (name,) in archive_tables:
    print(f"  Dropping archive table: {name}")
    cur.execute(f"DROP TABLE IF EXISTS {name}")

# Clean up orphan records
# Orphan curation_priority_queue entries
orphan_q = cur.execute("""
    SELECT cpq.queue_id FROM curation_priority_queue cpq
    LEFT JOIN virus_master vm ON cpq.virus_master_id = vm.master_id
    WHERE vm.master_id IS NULL
""").fetchall()
if orphan_q:
    cur.execute(f"DELETE FROM curation_priority_queue WHERE queue_id IN ({','.join('?'*len(orphan_q))})",
                [r[0] for r in orphan_q])
    print(f"  Removed orphan curation_priority_queue entries: {len(orphan_q)}")

# Vacuum to reclaim space
print("  Running VACUUM...")
conn.execute("VACUUM")
print("  Database cleaned and vacuumed.")

conn.commit()
conn.close()
print("\nAll done. Saved.")
