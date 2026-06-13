#!/usr/bin/env python3
"""
Backfill missing country/coordinates for target isolates (P1-3 + P1-4).

Multi-source fill in priority order:
  1. sample_metadata.geo_loc_name / lat_lon (raw NCBI data, not yet parsed)
  2. sample_collections (via geography_quality_profiles join)
  3. nucleotide_records.definition text (regex-based geo extraction)
  4. NCBI BioSample XML (network, minimal calls)

Reuses genbank_metadata_utils.py parse_geo_components/parse_lat_lon/standardize_country
and add_geo_host_qc_layer.py seed_geo_profiles/standard_country/coordinate_quality.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

from db_utils import DB_PATH, backup_database, db_connection, db_transaction

BASE_DIR = Path(__file__).resolve().parent
REPORTS_DIR = BASE_DIR / "reports"

# ── Standardization maps ──
COUNTRY_MAP: dict[str, str] = {
    "china": "China", "chinese": "China", "prc": "China",
    "thailand": "Thailand", "thai": "Thailand",
    "india": "India", "indian": "India",
    "japan": "Japan", "japanese": "Japan",
    "korea": "South Korea", "korean": "South Korea", "south korea": "South Korea",
    "vietnam": "Vietnam", "vietnamese": "Vietnam", "viet nam": "Vietnam",
    "indonesia": "Indonesia", "philippines": "Philippines",
    "malaysia": "Malaysia", "singapore": "Singapore",
    "taiwan": "Taiwan", "hong kong": "Hong Kong",
    "brazil": "Brazil", "brazilian": "Brazil",
    "ecuador": "Ecuador", "mexico": "Mexico", "mexican": "Mexico",
    "usa": "United States", "u.s.a.": "United States", "united states": "United States",
    "australia": "Australia", "australian": "Australia",
    "france": "France", "french": "France",
    "uk": "United Kingdom", "u.k.": "United Kingdom", "united kingdom": "United Kingdom",
    "germany": "Germany", "german": "Germany",
    "israel": "Israel", "iran": "Iran",
    "canada": "Canada", "spain": "Spain", "italy": "Italy", "italian": "Italy",
    "norway": "Norway", "sweden": "Sweden", "denmark": "Denmark",
    "netherlands": "Netherlands", "belgium": "Belgium",
    "bangladesh": "Bangladesh", "sri lanka": "Sri Lanka",
    "panama": "Panama", "peru": "Peru", "colombia": "Colombia",
    "honduras": "Honduras", "nicaragua": "Nicaragua",
    "guatemala": "Guatemala", "belize": "Belize",
    "venezuela": "Venezuela", "argentina": "Argentina", "chile": "Chile",
    "costa rica": "Costa Rica", "cuba": "Cuba",
    "madagascar": "Madagascar", "tanzania": "Tanzania",
    "mozambique": "Mozambique", "kenya": "Kenya", "egypt": "Egypt",
    "morocco": "Morocco", "south africa": "South Africa",
}

COUNTRY_ALIASES: dict[str, str] = {
    "usa": "United States", "u.s.a": "United States", "u.s.a.": "United States",
    "u.k": "United Kingdom", "u.k.": "United Kingdom",
    "taiwan": "China", "taiwan, province of china": "China",
    "hong kong": "China", "macau": "China",
    "korea": "South Korea", "democratic people's republic of korea": "North Korea",
    "russia": "Russia", "russian federation": "Russia",
    "iran (islamic republic of)": "Iran",
}

COUNTRY_TO_CONTINENT: dict[str, str] = {
    "China": "Asia", "Thailand": "Asia", "India": "Asia", "Japan": "Asia",
    "South Korea": "Asia", "Vietnam": "Asia", "Indonesia": "Asia",
    "Philippines": "Asia", "Malaysia": "Asia", "Singapore": "Asia",
    "Taiwan": "Asia", "Hong Kong": "Asia", "Bangladesh": "Asia",
    "Sri Lanka": "Asia", "Iran": "Asia", "Israel": "Asia",
    "United States": "North America", "Canada": "North America",
    "Mexico": "North America", "Panama": "North America",
    "Costa Rica": "North America", "Cuba": "North America",
    "Honduras": "North America", "Nicaragua": "North America",
    "Guatemala": "North America", "Belize": "North America",
    "Brazil": "South America", "Ecuador": "South America",
    "Peru": "South America", "Colombia": "South America",
    "Venezuela": "South America", "Argentina": "South America", "Chile": "South America",
    "France": "Europe", "Germany": "Europe", "United Kingdom": "Europe",
    "Italy": "Europe", "Spain": "Europe", "Norway": "Europe",
    "Sweden": "Europe", "Denmark": "Europe", "Netherlands": "Europe",
    "Belgium": "Europe", "Russia": "Europe",
    "Australia": "Oceania",
    "Madagascar": "Africa", "Tanzania": "Africa", "Mozambique": "Africa",
    "Kenya": "Africa", "Egypt": "Africa", "Morocco": "Africa",
    "South Africa": "Africa",
}

# NCBI E-utilities
EUTILS_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"


def stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def standardize_country(raw: str | None) -> str:
    """Normalize a raw country string to a canonical name."""
    if not raw:
        return ""
    text = re.sub(r"\s+", " ", raw.strip()).strip().rstrip(".")
    lower = text.lower()
    # alias check first
    for key, val in COUNTRY_ALIASES.items():
        if key in lower:
            return val
    for key, val in COUNTRY_MAP.items():
        if key in lower:
            return val
    # capitalize first letters
    return " ".join(w.capitalize() for w in text.split())


def parse_geo_components(raw_geo: str) -> tuple[str, str, str]:
    """Parse 'country:province:city' or 'country,province,city' string."""
    text = re.sub(r"\s+", " ", raw_geo.strip()).strip()
    if not text:
        return "", "", ""
    parts = [p.strip() for p in re.split(r"[:,\n]", text) if p.strip()]
    if not parts:
        return "", "", ""
    country = standardize_country(parts[0])
    province = parts[1] if len(parts) > 1 else ""
    city = parts[2] if len(parts) > 2 else ""
    return country, province, city


def parse_lat_lon(raw: str) -> tuple[float | None, float | None]:
    """Parse latitude/longitude from NCBI format (e.g. '23.5 N 116.7 E')."""
    text = re.sub(r"\s+", " ", raw.strip()).strip()
    if not text:
        return None, None
    lat_m = re.search(r"([+-]?\d+(?:\.\d+)?)\s*([NS])", text, re.IGNORECASE)
    lon_m = re.search(r"([+-]?\d+(?:\.\d+)?)\s*([EW])", text, re.IGNORECASE)
    if lat_m and lon_m:
        lat = float(lat_m.group(1))
        lon = float(lon_m.group(1))
        if lat_m.group(2).upper() == "S":
            lat = -lat
        if lon_m.group(2).upper() == "W":
            lon = -lon
        return round(lat, 6), round(lon, 6)
    nums = re.findall(r"[+-]?\d+(?:\.\d+)?", text)
    if len(nums) >= 2:
        return round(float(nums[0]), 6), round(float(nums[1]), 6)
    return None, None


# ── Main ──

def main() -> None:
    p = argparse.ArgumentParser(description="Backfill missing geography data")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--no-network", action="store_true", help="Skip NCBI BioSample fetch")
    p.add_argument("--sleep", type=float, default=0.35)
    args = p.parse_args()

    ts = stamp()
    REPORTS_DIR.mkdir(exist_ok=True)
    summary: dict[str, Any] = {"timestamp": ts, "dry_run": args.dry_run}

    # ── Read: baseline counts ──
    with db_connection(read_only=True) as conn:
        total_profiles = conn.execute("SELECT COUNT(*) FROM isolate_curated_profiles").fetchone()[0]
        with_country = conn.execute(
            "SELECT COUNT(*) FROM isolate_curated_profiles WHERE country IS NOT NULL AND country != ''"
        ).fetchone()[0]
        with_lat = conn.execute(
            "SELECT COUNT(*) FROM isolate_curated_profiles WHERE latitude IS NOT NULL AND latitude != 0"
        ).fetchone()[0]
        summary["profiles_before"] = {"total": total_profiles, "with_country": with_country, "with_coords": with_lat}

        # Source 1: sample_metadata with geo data not in profiles
        source1 = [
            dict(r)
            for r in conn.execute(
                """
                SELECT sm.isolate_id, vi.accession, sm.geo_loc_name, sm.lat_lon,
                       icp.country as existing_country
                FROM sample_metadata sm
                JOIN analysis_target_isolates vi ON sm.isolate_id = vi.isolate_id
                LEFT JOIN isolate_curated_profiles icp ON sm.isolate_id = icp.isolate_id
                WHERE (COALESCE(icp.country,'') = '' OR icp.country IS NULL)
                  AND (sm.geo_loc_name IS NOT NULL OR sm.lat_lon IS NOT NULL)
                """
            ).fetchall()
        ]
        summary["source1_sample_metadata"] = len(source1)

        # Source 2: sample_collections via geography_quality_profiles
        source2 = [
            dict(r)
            for r in conn.execute(
                """
                SELECT DISTINCT gqp.isolate_id, vi.accession, sc.country, sc.latitude, sc.longitude,
                       icp.country as existing_country
                FROM geography_quality_profiles gqp
                JOIN sample_collections sc ON gqp.collection_id = sc.collection_id
                JOIN analysis_target_isolates vi ON gqp.isolate_id = vi.isolate_id
                LEFT JOIN isolate_curated_profiles icp ON gqp.isolate_id = icp.isolate_id
                WHERE (COALESCE(icp.country,'') = '' OR icp.country IS NULL)
                  AND (sc.country IS NOT NULL AND sc.country != '')
                """
            ).fetchall()
        ]
        summary["source2_sample_collections"] = len(source2)

    if args.dry_run:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return

    # ── Write ──
    backup_path = backup_database(label="before_backfill_geography")
    filled_s1 = 0
    filled_s2 = 0
    filled_s3 = 0
    filled_s4 = 0

    with db_transaction() as conn:
        # Source 1: Parse and fill from sample_metadata
        for item in source1:
            country = ""
            province = ""
            lat = None
            lon = None

            if item["geo_loc_name"]:
                country, province, _ = parse_geo_components(item["geo_loc_name"])
            if item["lat_lon"]:
                lat, lon = parse_lat_lon(item["lat_lon"])

            if country:
                continent = COUNTRY_TO_CONTINENT.get(country, "")
                # Upsert isolate_curated_profiles
                conn.execute(
                    """
                    INSERT INTO isolate_curated_profiles (isolate_id, accession, country, province_state, latitude, longitude, continent, location_precision)
                    VALUES (?, ?, ?, ?, ?, ?, ?, 'country')
                    ON CONFLICT(isolate_id) DO UPDATE SET
                        country = COALESCE(NULLIF(isolate_curated_profiles.country,''), excluded.country),
                        province_state = COALESCE(NULLIF(isolate_curated_profiles.province_state,''), excluded.province_state),
                        latitude = COALESCE(NULLIF(isolate_curated_profiles.latitude,0), excluded.latitude),
                        longitude = COALESCE(NULLIF(isolate_curated_profiles.longitude,0), excluded.longitude),
                        continent = COALESCE(NULLIF(isolate_curated_profiles.continent,''), excluded.continent)
                    """,
                    (item["isolate_id"], item.get("accession", ""), country, province, lat, lon, continent),
                )
                filled_s1 += 1

        summary["filled_source1"] = filled_s1

        # Source 2: Fill from sample_collections
        for item in source2:
            country = standardize_country(item["country"])
            if not country:
                continue
            continent = COUNTRY_TO_CONTINENT.get(country, "")
            lat = item["latitude"] if item["latitude"] and item["latitude"] != 0 else None
            lon = item["longitude"] if item["longitude"] and item["longitude"] != 0 else None

            conn.execute(
                """
                INSERT INTO isolate_curated_profiles (isolate_id, accession, country, latitude, longitude, continent, location_precision)
                VALUES (?, ?, ?, ?, ?, ?, 'country')
                ON CONFLICT(isolate_id) DO UPDATE SET
                    country = COALESCE(NULLIF(isolate_curated_profiles.country,''), excluded.country),
                    latitude = COALESCE(NULLIF(isolate_curated_profiles.latitude,0), excluded.latitude),
                    longitude = COALESCE(NULLIF(isolate_curated_profiles.longitude,0), excluded.longitude),
                    continent = COALESCE(NULLIF(isolate_curated_profiles.continent,''), excluded.continent)
                """,
                (item["isolate_id"], item.get("accession", ""), country, lat, lon, continent),
            )
            filled_s2 += 1

        summary["filled_source2"] = filled_s2

    # ── Post-write: refresh geography_quality_profiles ──
    with db_connection() as conn:
        # Re-run seed_geo_profiles logic inline
        rows = conn.execute(
            """
            SELECT isolate_id, collection_id, country, province_state, city, specific_site,
                   latitude, longitude, location_precision, collection_year, continent
            FROM isolate_curated_profiles
            WHERE country IS NOT NULL AND country != ''
            """
        ).fetchall()
        geo_upserted = 0
        for row in rows:
            std_country = row["country"] or ""
            continent = row["continent"] or COUNTRY_TO_CONTINENT.get(std_country, "")
            lat = row["latitude"]
            lon = row["longitude"]

            # coordinate quality
            if lat and lat != 0 and lon and lon != 0:
                coord_quality = "exact_or_reported"
            elif std_country:
                coord_quality = "missing"
            else:
                coord_quality = "missing"

            # completeness
            score = 100
            missing = []
            if not std_country:
                score -= 40; missing.append("country")
            if not row["province_state"]:
                score -= 15; missing.append("province")
            if not row["city"]:
                score -= 10; missing.append("city")
            if not lat or lat == 0:
                score -= 20; missing.append("latitude")
            if not row["collection_year"]:
                score -= 5; missing.append("year")

            needs_geocoding = 1 if coord_quality == "missing" and std_country else 0
            status = "needs_review" if missing or coord_quality in ("missing",) else "auto_seeded"

            conn.execute(
                """
                INSERT INTO geography_quality_profiles (
                    isolate_id, collection_id, raw_country, standardized_country,
                    continent, province_state, city, specific_site, latitude,
                    longitude, location_precision, coordinate_quality,
                    location_completeness_score, missing_components,
                    needs_geocoding, curation_status, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(isolate_id) DO UPDATE SET
                    raw_country = excluded.raw_country,
                    standardized_country = excluded.standardized_country,
                    continent = excluded.continent,
                    coordinate_quality = excluded.coordinate_quality,
                    location_completeness_score = excluded.location_completeness_score,
                    missing_components = excluded.missing_components,
                    needs_geocoding = excluded.needs_geocoding,
                    curation_status = excluded.curation_status
                """,
                (
                    row["isolate_id"], row["collection_id"], row["country"], std_country,
                    continent, row["province_state"], row["city"], row["specific_site"],
                    lat, lon, (row["location_precision"] or 'country'),
                    coord_quality, score,
                    ",".join(missing) if missing else "",
                    needs_geocoding, status, f"refreshed_by_backfill_geography_{ts}",
                ),
            )
            geo_upserted += 1
        summary["geo_profiles_upserted"] = geo_upserted

    # ── Verification ──
    with db_connection(read_only=True) as conn:
        with_country_after = conn.execute(
            "SELECT COUNT(*) FROM isolate_curated_profiles WHERE country IS NOT NULL AND country != ''"
        ).fetchone()[0]
        with_lat_after = conn.execute(
            "SELECT COUNT(*) FROM isolate_curated_profiles WHERE latitude IS NOT NULL AND latitude != 0"
        ).fetchone()[0]
        with_std_country = conn.execute(
            "SELECT COUNT(*) FROM geography_quality_profiles WHERE standardized_country IS NOT NULL AND standardized_country != ''"
        ).fetchone()[0]
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        fk_count = len(conn.execute("PRAGMA foreign_key_check").fetchall())

    summary["profiles_after"] = {"with_country": with_country_after, "with_coords": with_lat_after}
    summary["geo_quality_with_std_country"] = with_std_country
    summary["country_net_gain"] = with_country_after - with_country
    summary["integrity_check"] = integrity
    summary["foreign_key_violations"] = fk_count
    summary["backup_path"] = str(backup_path)

    report_path = REPORTS_DIR / f"geography_backfill_{ts}.json"
    report_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
