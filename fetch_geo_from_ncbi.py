#!/usr/bin/env python3
"""Fetch country/coordinates from NCBI GenBank XML for isolates lacking geography data."""
import sqlite3, re, time, urllib.request, urllib.parse, xml.etree.ElementTree as ET, sys, json
from datetime import datetime
from db_utils import backup_database, db_connection, db_transaction

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
BATCH_SIZE = 80

COUNTRY_STD = {
    "china": "China", "chinese": "China", "japan": "Japan", "korea": "South Korea",
    "south korea": "South Korea", "usa": "United States", "united states": "United States",
    "australia": "Australia", "france": "France", "germany": "Germany",
    "brazil": "Brazil", "india": "India", "thailand": "Thailand",
    "vietnam": "Vietnam", "indonesia": "Indonesia", "mexico": "Mexico",
    "canada": "Canada", "uk": "United Kingdom", "united kingdom": "United Kingdom",
    "italy": "Italy", "spain": "Spain", "taiwan": "China", "hong kong": "China",
}

COUNTRY_CONTINENT = {
    "China": "Asia", "Japan": "Asia", "South Korea": "Asia", "Thailand": "Asia",
    "Vietnam": "Asia", "India": "Asia", "Indonesia": "Asia", "Bangladesh": "Asia",
    "Sri Lanka": "Asia", "Philippines": "Asia", "Malaysia": "Asia", "Singapore": "Asia",
    "United States": "North America", "Canada": "North America", "Mexico": "North America",
    "Brazil": "South America", "Ecuador": "South America", "Peru": "South America",
    "Colombia": "South America", "Chile": "South America", "Argentina": "South America",
    "France": "Europe", "Germany": "Europe", "United Kingdom": "Europe",
    "Italy": "Europe", "Spain": "Europe", "Norway": "Europe", "Sweden": "Europe",
    "Denmark": "Europe", "Netherlands": "Europe", "Belgium": "Europe",
    "Australia": "Oceania", "New Zealand": "Oceania",
    "South Africa": "Africa", "Egypt": "Africa", "Kenya": "Africa",
    "Madagascar": "Africa", "Tanzania": "Africa",
}


def std_country(c):
    c = c.strip().rstrip('.')
    lower = c.lower()
    for k, v in COUNTRY_STD.items():
        if lower.startswith(k):
            return v
    return c.title() if c else c


def fetch_geo_batch(accessions):
    params = urllib.parse.urlencode({
        "db": "nuccore", "id": ",".join(accessions),
        "rettype": "gb", "retmode": "xml",
        "tool": "aquavir_kb_curation"
    })
    req = urllib.request.Request(
        EUTILS + "?" + params,
        headers={"User-Agent": "aquavir-kb/1.0"}
    )
    with urllib.request.urlopen(req, timeout=90) as resp:
        return resp.read().decode('utf-8', errors='replace')


def parse_geo_from_xml(xml_text):
    geo = {}
    root = ET.fromstring(xml_text)
    for gbseq in root.findall('.//GBSeq'):
        acc = gbseq.findtext('GBSeq_accession-version') or gbseq.findtext('GBSeq_primary-accession')
        if not acc:
            continue
        base_acc = acc.split('.')[0]
        for feat in gbseq.findall('.//GBFeature'):
            if feat.findtext('GBFeature_key') != 'source':
                continue
            quals = {}
            for q in feat.findall('GBFeature_quals/GBQualifier'):
                qn = q.findtext('GBQualifier_name')
                qv = q.findtext('GBQualifier_value')
                if qn and qv:
                    quals[qn] = qv

            country_raw = quals.get('country') or quals.get('geo_loc_name') or ''
            lat_lon = quals.get('lat_lon') or ''
            country = country_raw.split(':')[0].split(',')[0].strip() if country_raw else ''
            lat = lon = None
            if lat_lon:
                lat_m = re.search(r'([+-]?\d+\.?\d*)\s*([NS])', lat_lon, re.I)
                lon_m = re.search(r'([+-]?\d+\.?\d*)\s*([EW])', lat_lon, re.I)
                if lat_m and lon_m:
                    lat = round(float(lat_m.group(1)) * (-1 if lat_m.group(2).upper() == 'S' else 1), 6)
                    lon = round(float(lon_m.group(1)) * (-1 if lon_m.group(2).upper() == 'W' else 1), 6)

            if country:
                geo[acc] = (country, lat, lon)
                if base_acc != acc:
                    geo[base_acc] = (country, lat, lon)
    return geo


def main():
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    print(f"[{ts}] Starting NCBI EFetch geography backfill...")

    with db_connection(read_only=True) as conn:
        acc_rows = conn.execute("""
            SELECT DISTINCT vi.accession FROM analysis_target_isolates vi
            WHERE NOT EXISTS (
                SELECT 1 FROM isolate_curated_profiles icp
                WHERE vi.isolate_id = icp.isolate_id AND icp.country IS NOT NULL AND icp.country != ''
            ) AND NOT EXISTS (
                SELECT 1 FROM geography_quality_profiles gqp
                WHERE vi.isolate_id = gqp.isolate_id AND gqp.standardized_country IS NOT NULL AND gqp.standardized_country != ''
            ) AND NOT EXISTS (
                SELECT 1 FROM sample_metadata sm
                WHERE vi.isolate_id = sm.isolate_id AND sm.geo_loc_name IS NOT NULL AND sm.geo_loc_name != ''
            ) AND vi.accession GLOB '[A-Z][A-Z][0-9]*'
            AND vi.accession NOT LIKE 'k141%'
            AND vi.accession NOT LIKE 'RDRP%'
        """).fetchall()

    accessions = sorted(set(r[0].split('.')[0] for r in acc_rows))
    print(f"  Unique NCBI accessions to fetch: {len(accessions)}")

    # Fetch all batches
    all_geo = {}
    errors = 0
    batches = [accessions[i:i+BATCH_SIZE] for i in range(0, len(accessions), BATCH_SIZE)]

    for i, batch in enumerate(batches):
        try:
            xml_text = fetch_geo_batch(batch)
            geo = parse_geo_from_xml(xml_text)
            all_geo.update(geo)
            if (i + 1) % 5 == 0 or i == 0:
                print(f"  batch {i+1}/{len(batches)}: got {len(geo)} in batch, {len(all_geo)} total")
        except Exception as e:
            errors += 1
            print(f"  batch {i+1} ERROR: {e}", file=sys.stderr)
        time.sleep(0.35)

    print(f"  Fetched geo for {len(all_geo)} accessions ({errors} batch errors)")

    # Apply to DB
    backup_database(label="before_ncbi_geo_fetch")

    with db_connection() as conn:
        iso_rows = conn.execute("""
            SELECT vi.isolate_id, vi.accession FROM analysis_target_isolates vi
            WHERE NOT EXISTS (
                SELECT 1 FROM isolate_curated_profiles icp
                WHERE vi.isolate_id = icp.isolate_id AND icp.country IS NOT NULL AND icp.country != ''
            ) AND NOT EXISTS (
                SELECT 1 FROM geography_quality_profiles gqp
                WHERE vi.isolate_id = gqp.isolate_id AND gqp.standardized_country IS NOT NULL AND gqp.standardized_country != ''
            ) AND NOT EXISTS (
                SELECT 1 FROM sample_metadata sm
                WHERE vi.isolate_id = sm.isolate_id AND sm.geo_loc_name IS NOT NULL AND sm.geo_loc_name != ''
            )
        """).fetchall()

        filled = 0
        new_coll = 0
        for iso_id, iso_acc in iso_rows:
            geo = all_geo.get(iso_acc) or all_geo.get(iso_acc.split('.')[0])
            if not geo:
                continue
            country_raw, lat, lon = geo
            country = std_country(country_raw)
            continent = COUNTRY_CONTINENT.get(country, '')
            if not country:
                continue

            conn.execute("""
                INSERT INTO isolate_curated_profiles (isolate_id, accession, country, latitude, longitude, continent, location_precision)
                VALUES (?, ?, ?, ?, ?, ?, 'country')
                ON CONFLICT(isolate_id) DO UPDATE SET
                    country = COALESCE(NULLIF(isolate_curated_profiles.country,''), excluded.country),
                    latitude = COALESCE(NULLIF(isolate_curated_profiles.latitude,0), excluded.latitude),
                    longitude = COALESCE(NULLIF(isolate_curated_profiles.longitude,0), excluded.longitude),
                    continent = COALESCE(NULLIF(isolate_curated_profiles.continent,''), excluded.continent)
            """, (iso_id, iso_acc, country, lat, lon, continent))
            filled += 1

            if country:
                conn.execute("""
                    INSERT OR IGNORE INTO sample_collections (country, latitude, longitude, coordinate_precision, continent)
                    VALUES (?, ?, ?, 'country', ?)
                """, (country, lat, lon, continent))
                new_coll += 1

        conn.commit()
        print(f"  Isolates filled: {filled}, New collections: {new_coll}")

        # Refresh geography_quality_profiles
        rows = conn.execute("""
            SELECT icp.isolate_id, icp.collection_id, icp.country, icp.province_state, icp.city,
                   icp.specific_site, icp.latitude, icp.longitude, icp.location_precision,
                   icp.collection_year, icp.continent
            FROM isolate_curated_profiles icp
            WHERE icp.country IS NOT NULL AND icp.country != ''
              AND icp.isolate_id NOT IN (
                  SELECT isolate_id FROM geography_quality_profiles
                  WHERE standardized_country IS NOT NULL AND standardized_country != ''
              )
        """).fetchall()

        geo_up = 0
        for row in rows:
            lat, lon = row[6], row[7]
            coord_q = "exact_or_reported" if (lat and lon and lat != 0) else "missing"
            needs_gc = 1 if coord_q == "missing" and row[2] else 0
            conn.execute("""
                INSERT INTO geography_quality_profiles (
                    isolate_id, collection_id, raw_country, standardized_country,
                    continent, province_state, city, specific_site, latitude, longitude,
                    location_precision, coordinate_quality, location_completeness_score,
                    missing_components, needs_geocoding, curation_status, notes
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,80,'',?,?,'ncbi_efetch_geo_20260601')
                ON CONFLICT(isolate_id) DO UPDATE SET
                    raw_country=excluded.raw_country,
                    standardized_country=excluded.standardized_country,
                    continent=excluded.continent,
                    coordinate_quality=excluded.coordinate_quality,
                    location_completeness_score=excluded.location_completeness_score
            """, (row[0], row[1], row[2], row[2], row[10] or '', row[3], row[4],
                  row[5], lat, lon, row[8] or 'country', coord_q, needs_gc))
            geo_up += 1
        conn.commit()
        print(f"  Geo quality profiles updated: {geo_up}")

    # Final counts
    with db_connection(read_only=True) as conn:
        wc = conn.execute(
            "SELECT COUNT(*) FROM isolate_curated_profiles WHERE country IS NOT NULL AND country != ''"
        ).fetchone()[0]
        tp = conn.execute("SELECT COUNT(*) FROM isolate_curated_profiles").fetchone()[0]
        ws = conn.execute(
            "SELECT COUNT(*) FROM geography_quality_profiles WHERE standardized_country IS NOT NULL AND standardized_country != ''"
        ).fetchone()[0]

    summary = {
        "timestamp": ts, "accessions_fetched": len(accessions),
        "geo_parsed": len(all_geo), "isolates_filled": filled,
        "new_sample_collections": new_coll, "geo_quality_updated": geo_up,
        "profiles_with_country": wc, "total_profiles": tp,
        "coverage_pct": round(100 * wc / tp, 1) if tp else 0,
        "geo_quality_with_std_country": ws,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
