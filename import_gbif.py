"""
Import GBIF (Global Biodiversity Information Facility) species occurrence data
for crustacean host species distribution mapping.

GBIF (https://www.gbif.org/) provides global species occurrence records
(lat/lon, date, source) that can be used to map host species distributions
and overlay with virus detection locations for epidemiological analysis.

Strategy:
  1. Get host species list from crustacean_hosts
  2. Query GBIF Occurrence API per species (scientific name)
  3. Aggregate occurrence points and compute distribution summaries
  4. Store in gbif_occurrences for geospatial visualization

Note: GBIF data are open and released under CC0 (https://www.gbif.org/terms). Attribution is required when redistributing or building upon GBIF-mediated data. Rate limit: ~5 req/sec.

Usage:
    python import_gbif.py                          # full run
    python import_gbif.py --dry-run                # preview only
    python import_gbif.py --limit 20               # process first N hosts
    python import_gbif.py --stats                  # coverage stats
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
CACHE_DIR = BASE_DIR / "external_data" / "gbif"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

GBIF_OCCURRENCE_API = "https://api.gbif.org/v1/occurrence/search"
GBIF_SPECIES_API = "https://api.gbif.org/v1/species/match"
GBIF_TAXON_API = "https://api.gbif.org/v1/species"

RATE_LIMIT = 0.3  # seconds between requests


def create_tables(conn: sqlite3.Connection) -> None:
    """Create GBIF occurrence tables."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS gbif_occurrences (
            occurrence_id INTEGER PRIMARY KEY AUTOINCREMENT,
            host_id INTEGER,
            scientific_name TEXT NOT NULL,
            gbif_taxon_key INTEGER,
            country TEXT,
            continent TEXT,
            decimal_latitude REAL,
            decimal_longitude REAL,
            locality TEXT,
            year INTEGER,
            basis_of_record TEXT,
            dataset_name TEXT,
            occurrence_count INTEGER DEFAULT 1,
            fetched_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (host_id) REFERENCES crustacean_hosts(host_id)
        );

        CREATE TABLE IF NOT EXISTS gbif_species_summary (
            summary_id INTEGER PRIMARY KEY AUTOINCREMENT,
            host_id INTEGER,
            scientific_name TEXT NOT NULL,
            gbif_taxon_key INTEGER,
            total_occurrences INTEGER,
            num_countries INTEGER,
            min_lat REAL,
            max_lat REAL,
            min_lon REAL,
            max_lon REAL,
            countries_json TEXT,
            first_record_year INTEGER,
            last_record_year INTEGER,
            fetched_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (host_id) REFERENCES crustacean_hosts(host_id)
        );

        CREATE INDEX IF NOT EXISTS idx_gbif_host ON gbif_occurrences(host_id);
        CREATE INDEX IF NOT EXISTS idx_gbif_name ON gbif_occurrences(scientific_name);
        CREATE INDEX IF NOT EXISTS idx_gbif_latlon ON gbif_occurrences(decimal_latitude, decimal_longitude);
    """)
    conn.commit()


def _gbif_get(url: str, timeout: int = 60) -> dict | None:
    """Fetch JSON from GBIF API."""
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
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        print(f"  [warn] GBIF HTTP {exc.code} for {url}")
        return None
    except Exception as exc:
        print(f"  [warn] GBIF request failed: {exc}")
        return None


def match_species_gbif(name: str) -> dict | None:
    """Match a scientific name to GBIF taxon key."""
    params = urllib.parse.urlencode({"name": name})
    return _gbif_get(f"{GBIF_SPECIES_API}?{params}")


def get_occurrences(taxon_key: int, limit: int = 500) -> list[dict]:
    """Get occurrence records for a GBIF taxon."""
    all_results = []
    offset = 0
    page_limit = min(300, limit)

    while offset < limit:
        params = urllib.parse.urlencode({
            "taxonKey": taxon_key,
            "limit": page_limit,
            "offset": offset,
            "hasCoordinate": "true",
        })
        data = _gbif_get(f"{GBIF_OCCURRENCE_API}?{params}")
        if not data:
            break

        results = data.get("results", [])
        all_results.extend(results)

        if len(results) < page_limit:
            break
        offset += page_limit
        time.sleep(RATE_LIMIT)

    return all_results


def get_host_species(conn: sqlite3.Connection, limit: int | None = None) -> list[tuple[int, str]]:
    """Get host species list from database."""
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


def import_gbif(
    conn: sqlite3.Connection,
    dry_run: bool = False,
    limit: int | None = None,
    max_occurrences_per_species: int = 500,
) -> int:
    """Main import logic."""
    hosts = get_host_species(conn, limit=limit)
    print(f"[gbif] {len(hosts)} host species to query")

    if dry_run:
        for hid, name in hosts[:30]:
            print(f"  [dry-run] {name}")
        return 0

    imported_occs = 0
    imported_summ = 0

    for i, (hid, name) in enumerate(hosts):
        if i % 10 == 0 and i > 0:
            print(f"  [progress] {i}/{len(hosts)} species ...")

        # Match species to GBIF taxon
        match = match_species_gbif(name)
        if not match or not match.get("usageKey"):
            time.sleep(RATE_LIMIT)
            continue

        taxon_key = match["usageKey"]
        confidence = match.get("confidence", 0)

        # Skip low-confidence matches
        if confidence < 80:
            time.sleep(RATE_LIMIT)
            continue

        # Get occurrence data
        occurrences = get_occurrences(taxon_key, max_occurrences_per_species)
        time.sleep(RATE_LIMIT)

        if not occurrences:
            continue

        # Store raw occurrences
        for occ in occurrences:
            try:
                conn.execute(
                    """
                    INSERT INTO gbif_occurrences
                        (host_id, scientific_name, gbif_taxon_key, country, continent,
                         decimal_latitude, decimal_longitude, locality, year, basis_of_record, dataset_name)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        hid,
                        name,
                        taxon_key,
                        occ.get("country"),
                        occ.get("continent"),
                        occ.get("decimalLatitude"),
                        occ.get("decimalLongitude"),
                        occ.get("locality"),
                        occ.get("year"),
                        occ.get("basisOfRecord"),
                        occ.get("datasetName"),
                    ),
                )
                imported_occs += 1
            except Exception:
                pass

        # Compute summary stats
        lats = [o.get("decimalLatitude") for o in occurrences if o.get("decimalLatitude")]
        lons = [o.get("decimalLongitude") for o in occurrences if o.get("decimalLongitude")]
        countries = set(o.get("country") for o in occurrences if o.get("country"))
        years = [o.get("year") for o in occurrences if o.get("year")]

        try:
            conn.execute(
                """
                INSERT OR REPLACE INTO gbif_species_summary
                    (host_id, scientific_name, gbif_taxon_key, total_occurrences,
                     num_countries, min_lat, max_lat, min_lon, max_lon,
                     countries_json, first_record_year, last_record_year)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    hid,
                    name,
                    taxon_key,
                    len(occurrences),
                    len(countries),
                    min(lats) if lats else None,
                    max(lats) if lats else None,
                    min(lons) if lons else None,
                    max(lons) if lons else None,
                    json.dumps(sorted(countries)),
                    min(years) if years else None,
                    max(years) if years else None,
                ),
            )
            imported_summ += 1
        except Exception:
            pass

    conn.commit()
    print(f"[gbif] Imported {imported_occs} occurrence records, {imported_summ} species summaries")
    return imported_occs


def register_source(conn: sqlite3.Connection) -> None:
    """Register GBIF in external_sources."""
    conn.execute(
        """
        INSERT INTO external_sources
            (source_key, name, category, base_url, description, update_policy, priority)
        VALUES ('gbif', 'GBIF', 'biodiversity',
                'https://www.gbif.org/',
                'Global Biodiversity Information Facility - species occurrence records for host distribution mapping.',
                'api', 100)
        ON CONFLICT(source_key) DO UPDATE SET
            name = excluded.name,
            description = excluded.description,
            priority = excluded.priority,
            updated_at = CURRENT_TIMESTAMP
        """
    )
    conn.commit()


def show_stats(conn: sqlite3.Connection) -> None:
    """Print GBIF integration stats."""
    print("\n=== GBIF Integration Stats ===")
    row = conn.execute("SELECT COUNT(*) FROM gbif_occurrences").fetchone()
    print(f"  Total occurrences: {row[0]}")
    row = conn.execute("SELECT COUNT(DISTINCT scientific_name) FROM gbif_occurrences").fetchone()
    print(f"  Species with data: {row[0]}")
    row = conn.execute("SELECT COUNT(*) FROM gbif_species_summary").fetchone()
    print(f"  Species summaries: {row[0]}")

    rows = conn.execute(
        "SELECT scientific_name, total_occurrences, num_countries FROM gbif_species_summary LIMIT 10"
    ).fetchall()
    print("  Sample species summaries:")
    for r in rows:
        print(f"    {r[0]:40s} {r[1]:6d} records, {r[2]:3d} countries")


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="Import GBIF species occurrence data")
    parser.add_argument("--dry-run", action="store_true", help="Preview only")
    parser.add_argument("--limit", type=int, default=None, help="Process first N host species")
    parser.add_argument("--max-occurrences", type=int, default=500, help="Max occurrences per species")
    parser.add_argument("--stats", action="store_true", help="Show stats only")
    args = parser.parse_args()

    conn = sqlite3.connect(str(DB_PATH))
    try:
        create_tables(conn)
        register_source(conn)

        if args.stats:
            show_stats(conn)
            return

        imported = import_gbif(
            conn,
            dry_run=args.dry_run,
            limit=args.limit,
            max_occurrences_per_species=args.max_occurrences,
        )
        print(f"\n[done] GBIF import complete: {imported} occurrence records")
        show_stats(conn)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
