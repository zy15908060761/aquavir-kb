"""
Batch 2d: 地理信息从GenBank XML文件回填
读取external_data/genbank_metadata/下的XML文件,提取country/lat_lon
"""
import sqlite3
import os
import xml.etree.ElementTree as ET
from pathlib import Path

DB = Path("F:/甲壳动物数据库/crustacean_virus_core.db")
GB_DIR = Path("F:/甲壳动物数据库/external_data/genbank_metadata")

conn = sqlite3.connect(str(DB))
conn.execute("PRAGMA foreign_keys = ON")
cur = conn.cursor()

def parse_genbank_xml(filepath):
    """Extract country, lat_lon, collection_date from GenBank XML"""
    try:
        tree = ET.parse(filepath)
        root = tree.getroot()
    except:
        return None

    result = {"accession": None, "country": None, "lat": None, "lon": None, "collection_date": None}

    # Find accession
    for elem in root.iter():
        tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
        if tag == "GBSeq_accession-version":
            result["accession"] = elem.text
        if tag == "GBSeq_primary-accession":
            if not result["accession"]:
                result["accession"] = elem.text

        # Look for qualifiers with country/lat_lon
        if tag == "GBQualifier":
            qual_name = None
            qual_value = None
            for child in elem:
                ctag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
                if ctag == "GBQualifier_name":
                    qual_name = child.text
                if ctag == "GBQualifier_value":
                    qual_value = child.text
            if qual_name == "country" and qual_value:
                result["country"] = qual_value
                # Sometimes country has lat_lon embedded like "China: Guangdong, 23.5N 116.7E"
            if qual_name == "lat_lon" and qual_value:
                parts = qual_value.replace(",", " ").split()
                try:
                    # Parse formats like "23.5 N 116.7 E"
                    coords = []
                    for p in parts:
                        p = p.strip().rstrip("NnSsEeWw")
                        try:
                            coords.append(float(p))
                        except:
                            pass
                    if len(coords) >= 2:
                        result["lat"] = coords[0]
                        result["lon"] = coords[1]
                except:
                    pass
            if qual_name == "collection_date" and qual_value:
                result["collection_date"] = qual_value

    return result if result["accession"] else None

# Scan all XML files
print("Scanning GenBank XML files...")
geo_updates = {}
total_files = 0
total_parsed = 0

for root, dirs, files in os.walk(GB_DIR):
    for fname in files:
        if fname.endswith(".xml"):
            total_files += 1
            fp = Path(root) / fname
            data = parse_genbank_xml(str(fp))
            if data and data["accession"] and (data["country"] or data["lat"]):
                geo_updates[data["accession"]] = data
                total_parsed += 1

print(f"Total XML files: {total_files}")
print(f"With geo data: {total_parsed}")

# Apply to sample_collections and infection_records
col_updated = 0
ir_updated = 0

for acc, geo in geo_updates.items():
    # Find isolate_id from accession
    isolate = cur.execute(
        "SELECT isolate_id FROM viral_isolates WHERE accession = ?",
        (acc if not acc.endswith(".0") else acc[:-2],)
    ).fetchone()
    if not isolate:
        # Try accession without version
        base_acc = acc.split(".")[0] if "." in acc else acc
        isolate = cur.execute(
            "SELECT isolate_id FROM viral_isolates WHERE accession LIKE ?",
            (f"{base_acc}%",)
        ).fetchone()
    if not isolate:
        continue

    iso_id = isolate[0]

    # Find or update sample_collection
    col_id = cur.execute(
        "SELECT collection_id FROM infection_records WHERE isolate_id = ?",
        (iso_id,)
    ).fetchone()
    if not col_id:
        continue

    col_id = col_id[0]

    # Check existing values
    existing = cur.execute(
        "SELECT country, latitude, collection_year FROM sample_collections WHERE collection_id = ?",
        (col_id,)
    ).fetchone()

    if existing:
        ex_country, ex_lat, ex_year = existing
        new_country = ex_country or geo["country"]
        new_lat = ex_lat or geo["lat"]
        new_lon = None
        if geo["lon"]:
            ex_lon = cur.execute("SELECT longitude FROM sample_collections WHERE collection_id = ?", (col_id,)).fetchone()[0]
            new_lon = ex_lon or geo["lon"]
        new_year = ex_year
        if not new_year and geo["collection_date"]:
            import re
            m = re.search(r"(\d{4})", geo["collection_date"])
            if m:
                new_year = m.group(1)

        if new_country != ex_country or new_lat != ex_lat or new_lon != ex_lon or new_year != ex_year:
            cur.execute("""
                UPDATE sample_collections
                SET country = COALESCE(NULLIF(?, ''), country),
                    latitude = COALESCE(?, latitude),
                    longitude = COALESCE(?, longitude),
                    collection_year = COALESCE(?, collection_year)
                WHERE collection_id = ?
            """, (new_country, new_lat, new_lon, new_year, col_id))
            col_updated += 1

print(f"\nCollection records updated: {col_updated}")

remaining_country = cur.execute("""
    SELECT COUNT(*) FROM analysis_target_isolates vi
    LEFT JOIN infection_records ir ON vi.isolate_id = ir.isolate_id
    LEFT JOIN sample_collections s ON ir.collection_id = s.collection_id
    LEFT JOIN isolate_curated_profiles icp ON vi.isolate_id = icp.isolate_id
    WHERE COALESCE(NULLIF(s.country,''), NULLIF(icp.country,'')) IS NULL
""").fetchone()[0]
print(f"Target isolates still without country: {remaining_country}")

conn.commit()
conn.close()
print("Saved.")
