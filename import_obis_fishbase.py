"""
Import host species data from OBIS (Ocean Biodiversity Information System)
and FishBase/SeaLifeBase for crustacean host biology enrichment.

OBIS (https://obis.org/) provides marine species occurrence data (similar to GBIF
but specialized for ocean biodiversity). FishBase (https://www.fishbase.org/)
and SeaLifeBase provide comprehensive species biology information:
  - Habitat, depth range, temperature tolerance
  - Body size, growth parameters
  - Trophic level, food items
  - Commercial importance (aquaculture, fisheries)
  - IUCN Red List status (cross-verified)

Strategy:
  1. Get crustacean host species list from database
  2. Query OBIS API for marine species occurrence data
  3. Query FishBase/SeaLifeBase for species biology profiles
  4. Store ecological and biological annotations for each host

Usage:
    python import_obis_fishbase.py                   # full run
    python import_obis_fishbase.py --dry-run         # preview only
    python import_obis_fishbase.py --limit 30         # process first N
    python import_obis_fishbase.py --stats            # coverage stats
"""

from __future__ import annotations

import json
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "crustacean_virus_core.db"
CACHE_DIR = BASE_DIR / "external_data" / "obis_fishbase"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# OBIS API endpoints
OBIS_API = "https://api.obis.org/v3"
OBIS_OCCURRENCE = f"{OBIS_API}/occurrence"

# FishBase / SeaLifeBase don't have a public REST API, but the EOL (Encyclopedia of Life)
# API provides aggregated species trait data from FishBase/SeaLifeBase/WoRMS/etc.
EOL_API = "https://api.eol.org/pages/1.0"
EOL_TRAIT_API = "https://eol.org/api/traits/1.0"
EOL_SEARCH_API = "https://eol.org/api/search/1.0"

# Also use SealifeBase data via rOpenSci's traiter package metadata
# Fallback: use WoRMS AphiaID (already in database) to get ecological traits

RATE_LIMIT = 0.3


def create_tables(conn: sqlite3.Connection) -> None:
    """Create host ecology/biology tables."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS obis_occurrences (
            obis_id INTEGER PRIMARY KEY AUTOINCREMENT,
            host_id INTEGER,
            scientific_name TEXT NOT NULL,
            aphia_id INTEGER,
            decimal_latitude REAL,
            decimal_longitude REAL,
            depth_min REAL,
            depth_max REAL,
            temperature REAL,
            salinity REAL,
            country TEXT,
            locality TEXT,
            year_collected INTEGER,
            dataset_name TEXT,
            record_count INTEGER DEFAULT 1,
            fetched_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (host_id) REFERENCES crustacean_hosts(host_id)
        );

        CREATE TABLE IF NOT EXISTS host_ecological_traits (
            trait_id INTEGER PRIMARY KEY AUTOINCREMENT,
            host_id INTEGER,
            scientific_name TEXT NOT NULL,
            source TEXT DEFAULT 'EOL',
            trait_name TEXT,
            trait_value TEXT,
            units TEXT,
            measurement_method TEXT,
            confidence TEXT DEFAULT 'medium',
            fetched_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (host_id) REFERENCES crustacean_hosts(host_id)
        );

        CREATE TABLE IF NOT EXISTS host_biology_profiles (
            profile_id INTEGER PRIMARY KEY AUTOINCREMENT,
            host_id INTEGER UNIQUE,
            scientific_name TEXT NOT NULL,
            habitat_type TEXT,
            depth_range_min REAL,
            depth_range_max REAL,
            temperature_tolerance_min REAL,
            temperature_tolerance_max REAL,
            salinity_tolerance TEXT,
            max_body_length_cm REAL,
            trophic_level REAL,
            feeding_type TEXT,
            generation_time_days INTEGER,
            longevity_days INTEGER,
            fecundity_min INTEGER,
            fecundity_max INTEGER,
            aquaculture_production_tonnes REAL,
            commercial_importance TEXT,
            data_sources_json TEXT,
            fetched_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (host_id) REFERENCES crustacean_hosts(host_id)
        );

        CREATE INDEX IF NOT EXISTS idx_obis_host ON obis_occurrences(host_id);
        CREATE INDEX IF NOT EXISTS idx_obis_latlon ON obis_occurrences(decimal_latitude, decimal_longitude);
        CREATE INDEX IF NOT EXISTS idx_traits_host ON host_ecological_traits(host_id);
        CREATE INDEX IF NOT EXISTS idx_bio_host ON host_biology_profiles(host_id);
    """)
    conn.commit()


def _fetch_json(url: str, timeout: int = 60) -> dict | None:
    """Fetch JSON from URL."""
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "crustacean-virus-db-curation/1.0",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except Exception as exc:
        return None


def _fetch_trait_data(eol_page_id: int) -> list[dict] | None:
    """Fetch trait data from EOL for a given page ID."""
    params = urllib.parse.urlencode({
        "id": eol_page_id,
        "format": "json",
    })
    url = f"{EOL_TRAIT_API}.json?{params}"
    data = _fetch_json(url)
    if not data:
        return None

    traits = []
    taxon_data = data.get("taxon", {})
    if isinstance(taxon_data, dict):
        all_traits = (
            taxon_data.get("dataObjects", []) +
            taxon_data.get("taxon", {}).get("dataObjects", [])
        )
        for t in all_traits:
            traits.append({
                "trait_name": t.get("predicate", "") or t.get("dwc_term", ""),
                "trait_value": t.get("object", "") or t.get("value", ""),
                "units": t.get("units", ""),
                "measurement_method": t.get("method", ""),
                "source": t.get("source", ""),
            })

    return traits


def search_eol(scientific_name: str) -> dict | None:
    """Search EOL for a species and get page ID."""
    params = urllib.parse.urlencode({
        "q": scientific_name,
        "page": 1,
        "exact": "true",
        "format": "json",
    })
    url = f"{EOL_SEARCH_API}.json?{params}"
    data = _fetch_json(url)
    if not data:
        return None

    results = data.get("results", [])
    if results and results[0].get("title", "").lower() == scientific_name.lower():
        return results[0]
    elif results:
        return results[0]  # best match
    return None


def search_obis(scientific_name: str, limit: int = 100) -> list[dict]:
    """Search OBIS for species occurrence data."""
    params = urllib.parse.urlencode({
        "scientificname": scientific_name,
        "size": limit,
    })
    url = f"{OBIS_OCCURRENCE}?{params}"
    data = _fetch_json(url)
    if not data:
        return []
    return data.get("results", [])


def get_host_species(conn: sqlite3.Connection, limit: int | None = None) -> list[tuple[int, str]]:
    """Get host species list."""
    limit_clause = f"LIMIT {limit}" if limit else ""
    rows = conn.execute(
        f"""
        SELECT host_id, scientific_name
        FROM crustacean_hosts
        WHERE scientific_name IS NOT NULL AND scientific_name != ''
        {limit_clause}
        """
    ).fetchall()
    return [(r[0], r[1]) for r in rows if r[1]]


def import_obis(
    conn: sqlite3.Connection,
    hosts: list[tuple[int, str]],
    dry_run: bool = False,
) -> int:
    """Import OBIS occurrence data for host species."""
    imported = 0
    for i, (hid, name) in enumerate(hosts):
        if i % 10 == 0 and i > 0:
            print(f"  [OBIS progress] {i}/{len(hosts)} species ...")

        if dry_run:
            print(f"  [dry-run] OBIS: {name}")
            continue

        occurrences = search_obis(name, limit=100)
        time.sleep(RATE_LIMIT)

        for occ in occurrences:
            try:
                conn.execute(
                    """
                    INSERT INTO obis_occurrences
                        (host_id, scientific_name, aphia_id, decimal_latitude, decimal_longitude,
                         depth_min, depth_max, temperature, salinity, country, locality,
                         year_collected, dataset_name)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        hid,
                        name,
                        occ.get("aphiaID"),
                        occ.get("decimalLatitude"),
                        occ.get("decimalLongitude"),
                        occ.get("minimumDepthInMeters"),
                        occ.get("maximumDepthInMeters"),
                        occ.get("temperature"),
                        occ.get("salinity"),
                        occ.get("country"),
                        occ.get("locality"),
                        occ.get("yearcollected"),
                        occ.get("datasetName"),
                    ),
                )
                imported += 1
            except Exception:
                pass

    conn.commit()
    return imported


def import_eol_traits(
    conn: sqlite3.Connection,
    hosts: list[tuple[int, str]],
    dry_run: bool = False,
) -> tuple[int, int]:
    """Import EOL trait and biology data for host species."""
    trait_count = 0
    profile_count = 0

    for i, (hid, name) in enumerate(hosts):
        if i % 10 == 0 and i > 0:
            print(f"  [EOL progress] {i}/{len(hosts)} species ...")

        if dry_run:
            print(f"  [dry-run] EOL: {name}")
            continue

        # Search EOL
        eol_result = search_eol(name)
        time.sleep(RATE_LIMIT)

        if not eol_result:
            continue

        eol_page_id = eol_result.get("id", 0)
        if not eol_page_id:
            continue

        # Fetch trait data
        traits = _fetch_trait_data(eol_page_id)
        time.sleep(RATE_LIMIT)

        if traits:
            for t in traits:
                if t["trait_name"] and t["trait_value"]:
                    try:
                        conn.execute(
                            """
                            INSERT INTO host_ecological_traits
                                (host_id, scientific_name, source, trait_name, trait_value, units, measurement_method)
                            VALUES (?, ?, 'EOL', ?, ?, ?, ?)
                            """,
                            (
                                hid,
                                name,
                                t["trait_name"],
                                t["trait_value"],
                                t["units"],
                                t["measurement_method"],
                            ),
                        )
                        trait_count += 1
                    except Exception:
                        pass

        # Extract key biology profile data from traits
        profile = _parse_biology_profile(traits or [])
        if profile:
            try:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO host_biology_profiles
                        (host_id, scientific_name, habitat_type, depth_range_min,
                         depth_range_max, temperature_tolerance_min, temperature_tolerance_max,
                         salinity_tolerance, max_body_length_cm, trophic_level,
                         feeding_type, generation_time_days, longevity_days,
                         fecundity_min, fecundity_max, aquaculture_production_tonnes,
                         commercial_importance, data_sources_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        hid,
                        name,
                        profile.get("habitat"),
                        profile.get("depth_min"),
                        profile.get("depth_max"),
                        profile.get("temp_min"),
                        profile.get("temp_max"),
                        profile.get("salinity"),
                        profile.get("body_length"),
                        profile.get("trophic_level"),
                        profile.get("feeding_type"),
                        profile.get("generation_time"),
                        profile.get("longevity"),
                        profile.get("fecundity_min"),
                        profile.get("fecundity_max"),
                        profile.get("aquaculture_production"),
                        profile.get("commercial_importance"),
                        json.dumps(profile.get("data_sources", [])),
                    ),
                )
                profile_count += 1
            except Exception:
                pass

    conn.commit()
    return trait_count, profile_count


def _parse_biology_profile(traits: list[dict]) -> dict | None:
    """Parse relevant biological traits from EOL trait data."""
    if not traits:
        return None

    profile: dict[str, Any] = {
        "habitat": None,
        "depth_min": None,
        "depth_max": None,
        "temp_min": None,
        "temp_max": None,
        "salinity": None,
        "body_length": None,
        "trophic_level": None,
        "feeding_type": None,
        "generation_time": None,
        "longevity": None,
        "fecundity_min": None,
        "fecundity_max": None,
        "aquaculture_production": None,
        "commercial_importance": None,
        "data_sources": [],
    }

    trait_map = {
        "habitat": ["habitat", "marine habitat", "environment", "biotope"],
        "depth_min": ["depth range lower", "minimum depth", "depth min"],
        "depth_max": ["depth range upper", "maximum depth", "depth max"],
        "temp_min": ["temperature tolerance min", "temperature min", "lower temperature"],
        "temp_max": ["temperature tolerance max", "temperature max", "upper temperature"],
        "salinity": ["salinity", "salinity tolerance"],
        "body_length": ["body length", "maximum length", "total length", "standard length"],
        "trophic_level": ["trophic level", "trophic guild"],
        "feeding_type": ["feeding type", "feeding mode", "diet"],
    }

    for t in traits:
        name = (t.get("trait_name") or "").lower()
        value = t.get("trait_value")
        if not value:
            continue

        for profile_key, patterns in trait_map.items():
            if any(p in name for p in patterns):
                if profile_key in ("body_length", "depth_min", "depth_max",
                                   "temp_min", "temp_max", "trophic_level"):
                    try:
                        # Try to extract numeric value
                        import re
                        match = re.search(r'(\d+\.?\d*)', str(value))
                        if match:
                            profile[profile_key] = float(match.group(1))
                    except Exception:
                        profile[profile_key] = str(value)[:50]
                else:
                    profile[profile_key] = str(value)[:100]

    # Only return if we found at least some data
    has_data = any(v is not None for k, v in profile.items()
                   if k != "data_sources")
    return profile if has_data else None


def register_source(conn: sqlite3.Connection) -> None:
    """Register OBIS and FishBase/SeaLifeBase in external_sources."""
    conn.executemany(
        """
        INSERT INTO external_sources
            (source_key, name, category, base_url, description, update_policy, priority)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(source_key) DO UPDATE SET
            name = excluded.name,
            description = excluded.description,
            priority = excluded.priority,
            updated_at = CURRENT_TIMESTAMP
        """,
        [
            ("obis", "OBIS", "biodiversity",
             "https://obis.org/",
             "Ocean Biodiversity Information System - marine host species occurrence records.",
             "api", 102),
            ("fishbase", "FishBase / SeaLifeBase", "host_biology",
             "https://www.fishbase.org/",
             "Host species biology: habitat, depth, temperature, fecundity, trophic levels.",
             "api", 103),
            ("eol", "Encyclopedia of Life", "host_biology",
             "https://eol.org/",
             "Aggregated species trait data from FishBase, SeaLifeBase, WoRMS, and other sources.",
             "api", 104),
        ],
    )
    conn.commit()


def show_stats(conn: sqlite3.Connection) -> None:
    """Print OBIS/FishBase integration stats."""
    print("\n=== OBIS / FishBase / EOL Stats ===")
    print("--- OBIS ---")
    row = conn.execute("SELECT COUNT(*) FROM obis_occurrences").fetchone()
    print(f"  Occurrence records: {row[0]}")
    row = conn.execute("SELECT COUNT(DISTINCT scientific_name) FROM obis_occurrences").fetchone()
    print(f"  Species with data: {row[0]}")

    print("\n--- Ecological Traits (EOL) ---")
    row = conn.execute("SELECT COUNT(*) FROM host_ecological_traits").fetchone()
    print(f"  Trait records: {row[0]}")
    rows = conn.execute(
        "SELECT trait_name, COUNT(*) FROM host_ecological_traits "
        "GROUP BY trait_name ORDER BY COUNT(*) DESC LIMIT 10"
    ).fetchall()
    print("  Top traits:")
    for r in rows:
        print(f"    {r[0]:40s} {r[1]}")

    print("\n--- Host Biology Profiles ---")
    row = conn.execute("SELECT COUNT(*) FROM host_biology_profiles").fetchone()
    print(f"  Species profiles: {row[0]}")
    rows = conn.execute(
        "SELECT scientific_name, habitat_type, temperature_tolerance_min, "
        "temperature_tolerance_max, trophic_level "
        "FROM host_biology_profiles LIMIT 10"
    ).fetchall()
    print("  Sample profiles:")
    for r in rows:
        temp = f"{r[2]}-{r[3]}C" if r[2] and r[3] else "N/A"
        print(f"    {r[0]:40s} habitat={r[1] or 'N/A':20s} temp={temp:15s} trophic={r[4] or 'N/A'}")


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="Import OBIS/FishBase host species data")
    parser.add_argument("--dry-run", action="store_true", help="Preview only")
    parser.add_argument("--limit", type=int, default=None, help="Process first N species")
    parser.add_argument("--skip-obis", action="store_true", help="Skip OBIS")
    parser.add_argument("--skip-eol", action="store_true", help="Skip EOL/FishBase traits")
    parser.add_argument("--stats", action="store_true", help="Show stats only")
    args = parser.parse_args()

    conn = sqlite3.connect(str(DB_PATH))
    try:
        create_tables(conn)
        register_source(conn)

        if args.stats:
            show_stats(conn)
            return

        hosts = get_host_species(conn, limit=args.limit)
        print(f"[hosts] {len(hosts)} species to process")

        obis_count = 0
        trait_count = 0
        profile_count = 0

        if not args.skip_obis:
            print("\n--- OBIS Occurrence Data ---")
            obis_count = import_obis(conn, hosts, dry_run=args.dry_run)
            print(f"  Imported {obis_count} OBIS records")

        if not args.skip_eol:
            print("\n--- EOL / FishBase Trait Data ---")
            trait_count, profile_count = import_eol_traits(conn, hosts, dry_run=args.dry_run)
            print(f"  Imported {trait_count} traits, {profile_count} profiles")

        print(f"\n[done] OBIS/FishBase import complete: "
              f"{obis_count} OBIS records + {trait_count} traits + {profile_count} profiles")
        show_stats(conn)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
