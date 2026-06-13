#!/usr/bin/env python3
"""
P1 Sample Metadata Enrichment for AquaVir-KB.

Identifies isolates with biosample/SRA links but missing geography_quality_profiles
or sample_collections metadata, and enriches from available source data.

The database links isolates → geography_quality_profiles (isolate_id + collection_id)
→ sample_collections (collection_id).

Usage:
  python optimize_sample_metadata.py --dry-run       Preview enrichment
  python optimize_sample_metadata.py                  Apply enrichment from source_text
  python optimize_sample_metadata.py --fetch-ncbi     Fetch BioSample XML from NCBI
  python optimize_sample_metadata.py --fetch-ncbi --dry-run   Preview NCBI fetch
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

# ── Paths ────────────────────────────────────────────────────────
APP_DIR = Path(__file__).resolve().parent
DB_PATH = APP_DIR / "crustacean_virus_core.db"
REPORTS_DIR = APP_DIR / "reports"
BACKUPS_DIR = APP_DIR / "backups"
CACHE_DIR = APP_DIR / "downloads" / "biosample_cache"


def stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def scalar(conn, sql: str, params=()) -> Any:
    cur = conn.execute(sql, params)
    row = cur.fetchone()
    return row[0] if row else None


def rows(conn, sql: str, params=()) -> list[dict]:
    cur = conn.execute(sql, params)
    return [dict(r) for r in cur.fetchall()]


def table_exists(conn, name: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone() is not None


def column_exists(conn, table: str, column: str) -> bool:
    cur = conn.execute(f"PRAGMA table_info({table})")
    return any(r[1] == column for r in cur.fetchall())


def backup_database(db_path: Path, backup_dir: Path, label: str) -> Path:
    import shutil
    import sqlite3 as _sqlite3
    backup_dir.mkdir(parents=True, exist_ok=True)
    ts = stamp()
    safe_label = label.replace(" ", "_").replace("/", "_").replace("\\", "_")
    backup_base = backup_dir / f"crustacean_virus_core_{safe_label}_{ts}"

    conn = _sqlite3.connect(str(db_path))
    try:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        conn.close()

    shutil.copy2(str(db_path), str(backup_base.with_suffix(".db")))
    for suffix in (".db-wal", ".db-shm"):
        src = Path(str(db_path) + suffix)
        if src.exists():
            dst = Path(str(backup_base.with_suffix("")) + suffix)
            shutil.copy2(str(src), str(dst))

    print(f"[backup] WAL-safe backup → {backup_base.with_suffix('.db').name}")
    return backup_base.with_suffix(".db")


def show_stats(conn) -> dict:
    """Show current sample/geography metadata coverage."""
    total_isolates = scalar(conn, "SELECT COUNT(*) FROM viral_isolates") or 0

    # Isolates with geography_quality_profiles
    with_geo = scalar(conn,
        "SELECT COUNT(DISTINCT isolate_id) FROM geography_quality_profiles WHERE isolate_id IS NOT NULL"
    ) or 0

    # Total biosample links
    total_biosample = scalar(conn, "SELECT COUNT(*) FROM biosample_links") or 0
    biosample_linked = scalar(conn,
        "SELECT COUNT(*) FROM biosample_links WHERE isolate_id IS NOT NULL") or 0
    biosample_unlinked = total_biosample - biosample_linked

    # Enrichable: has biosample link but no geography profile
    enrichable = scalar(conn, """
        SELECT COUNT(DISTINCT bl.isolate_id) FROM biosample_links bl
        WHERE bl.isolate_id IS NOT NULL
        AND NOT EXISTS (
            SELECT 1 FROM geography_quality_profiles gqp
            WHERE gqp.isolate_id = bl.isolate_id
        )
    """) or 0

    result = {
        "total_isolates": total_isolates,
        "with_geography_profile": with_geo,
        "geo_coverage_pct": round(with_geo / total_isolates * 100, 1) if total_isolates else 0,
        "total_biosample_links": total_biosample,
        "biosample_linked_to_isolate": biosample_linked,
        "biosample_unlinked": biosample_unlinked,
        "enrichable_isolates": enrichable,
    }

    print(f"\n{'='*50}")
    print("Sample / Geography Metadata Coverage")
    print(f"{'='*50}")
    print(f"  Total isolates:                  {total_isolates}")
    print(f"  With geography profile:          {with_geo} ({result['geo_coverage_pct']}%)")
    print(f"  Biosample links total:           {total_biosample}")
    print(f"  Biosample linked to isolate:      {biosample_linked}")
    print(f"  Biosample w/o isolate_id:         {biosample_unlinked}")
    print(f"  Enrichable (biosample, no geo):  {enrichable}")
    print()

    return result


def enrich_from_source_text(conn, dry_run: bool) -> dict:
    """Extract metadata from biosample_links.source_text.

    Creates entries in both sample_collections and geography_quality_profiles
    to link isolate metadata properly.
    """
    result = {"parsed": 0, "collections_created": 0, "geo_profiles_created": 0,
              "skipped_exists": 0, "skipped_no_data": 0}

    # Patterns
    org_pat = re.compile(r'organism=([^;]+)', re.IGNORECASE)
    sra_pat = re.compile(r'SRA=([^;]+)', re.IGNORECASE)
    title_pat = re.compile(r'title=([^;]+)', re.IGNORECASE)

    candidates = rows(conn, """
        SELECT DISTINCT bl.isolate_id, bl.biosample_accession, bl.bioproject_accession,
               bl.source_text
        FROM biosample_links bl
        WHERE bl.isolate_id IS NOT NULL
          AND bl.source_text IS NOT NULL AND bl.source_text != ''
          AND NOT EXISTS (
              SELECT 1 FROM geography_quality_profiles gqp
              WHERE gqp.isolate_id = bl.isolate_id
          )
    """)

    inserts_geo = []
    inserts_collection = []

    for row in candidates:
        result["parsed"] += 1
        source_text = row["source_text"]

        org_m = org_pat.search(source_text)
        title_m = title_pat.search(source_text)

        organism = org_m.group(1).strip() if org_m else ""
        source_desc = title_m.group(1).strip() if title_m else source_text[:500]

        if not organism and not source_desc:
            result["skipped_no_data"] += 1
            continue

        if not dry_run:
            # Check if this isolate already has a geo profile (safety double-check)
            exists = scalar(conn,
                "SELECT 1 FROM geography_quality_profiles WHERE isolate_id = ?",
                (row["isolate_id"],))
            if exists:
                result["skipped_exists"] += 1
                continue

            # Insert into sample_collections
            cur = conn.execute(
                """INSERT INTO sample_collections (source_type, note)
                VALUES (?, ?)""",
                ("biosample_import", source_desc[:500]))
            collection_id = cur.lastrowid
            result["collections_created"] += 1

            # Insert into geography_quality_profiles
            conn.execute(
                """INSERT INTO geography_quality_profiles
                (isolate_id, collection_id, host_organism, curation_status, created_at, notes)
                VALUES (?, ?, ?, ?, ?, ?)""",
                (row["isolate_id"], collection_id, organism[:200] if organism else None,
                 "auto_enriched", stamp(),
                 f"From biosample_links.source_text: {source_desc[:300]}"))
            result["geo_profiles_created"] += 1

        else:
            result["collections_created"] += 1
            result["geo_profiles_created"] += 1

    return result


def fetch_biosample_metadata(db_path: Path, dry_run: bool, ncbi_api_key: str = "",
                             batch_size: int = 50, sleep_sec: float = 1.0) -> dict:
    """Fetch BioSample XML from NCBI eutils for isolates missing geography data.

    Parses: organism, geo_loc_name (country), collection_date, lat_lon.
    Creates sample_collections + geography_quality_profiles entries.
    """
    import sqlite3
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    result = {"fetched": 0, "parsed": 0, "inserted_collections": 0,
              "inserted_geo_profiles": 0, "failed": 0, "errors": []}

    # Get unique biosample accessions to fetch
    biosample_rows = rows(conn, """
        SELECT DISTINCT bl.biosample_accession, bl.isolate_id
        FROM biosample_links bl
        WHERE bl.biosample_accession IS NOT NULL AND bl.biosample_accession != ''
          AND bl.isolate_id IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM geography_quality_profiles gqp
              WHERE gqp.isolate_id = bl.isolate_id
          )
        LIMIT 500
    """)

    if not biosample_rows:
        print("No biosample accessions to fetch.")
        conn.close()
        return result

    # Group by accession
    unique_accs = sorted(set(r["biosample_accession"] for r in biosample_rows))
    acc_to_isolates: dict[str, list] = {}
    for r in biosample_rows:
        acc = r["biosample_accession"]
        acc_to_isolates.setdefault(acc, []).append(r["isolate_id"])

    print(f"Found {len(unique_accs)} unique biosample accessions to fetch.")
    if dry_run:
        print(f"[dry-run] Would fetch {len(unique_accs)} records from NCBI BioSample.")
        conn.close()
        return result

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    all_parsed = []

    for i in range(0, len(unique_accs), batch_size):
        batch = unique_accs[i:i+batch_size]
        ids = ",".join(batch)

        url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
        params = f"db=biosample&id={ids}&rettype=xml&retmode=xml"
        if ncbi_api_key:
            params += f"&api_key={ncbi_api_key}"

        full_url = f"{url}?{params}"

        try:
            req = urllib.request.Request(full_url)
            # NCBI requires identification
            req.add_header("User-Agent", "AquaVir-KB/1.0 (Academic Research; mailto:placeholder@example.com)")
            with urllib.request.urlopen(req, timeout=120) as resp:
                xml_data = resp.read().decode("utf-8")

            cache_path = CACHE_DIR / f"biosample_batch_{i}_{stamp()}.xml"
            cache_path.write_text(xml_data, encoding="utf-8")

            parsed = _parse_biosample_xml_extended(xml_data, acc_to_isolates)
            all_parsed.extend(parsed)
            result["fetched"] += len(batch)
            result["parsed"] += len(parsed)

            print(f"  Batch {i//batch_size + 1}: {len(batch)} fetched, {len(parsed)} parsed")

            time.sleep(sleep_sec)

        except urllib.error.HTTPError as e:
            msg = f"HTTP {e.code} for batch starting at {batch[0]}"
            print(f"  [error] {msg}")
            result["errors"].append(msg)
            result["failed"] += len(batch)
            time.sleep(5)
        except Exception as e:
            msg = f"Error for batch {batch[0]}: {e}"
            print(f"  [error] {msg}")
            result["errors"].append(msg)
            result["failed"] += len(batch)
            time.sleep(2)

    # Insert into database
    if all_parsed:
        conn.execute("BEGIN IMMEDIATE")
        try:
            for d in all_parsed:
                # Insert sample_collections
                cur = conn.execute(
                    """INSERT INTO sample_collections
                    (country, collection_date, latitude, longitude, source_type, note)
                    VALUES (?, ?, ?, ?, ?, ?)""",
                    (d["country"], d["collection_date"], d["latitude"],
                     d["longitude"], "biosample_ncbi",
                     f"BioSample: {d['biosample_accession']}"))
                collection_id = cur.lastrowid
                result["inserted_collections"] += 1

                # Insert geography_quality_profiles
                conn.execute(
                    """INSERT INTO geography_quality_profiles
                    (isolate_id, collection_id, standardized_country, latitude, longitude,
                     location_precision, curation_status, created_at, notes)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (d["isolate_id"], collection_id, d["country"], d["latitude"],
                     d["longitude"], "biosample",
                     "auto_enriched", stamp(),
                     f"From NCBI BioSample {d['biosample_accession']}"))
                result["inserted_geo_profiles"] += 1
            conn.commit()
        except BaseException:
            conn.rollback()
            raise

    conn.close()
    return result


def _parse_biosample_xml_extended(xml_data: str, acc_to_isolates: dict) -> list[dict]:
    """Parse NCBI BioSample XML into metadata dicts.

    Returns list of dicts with keys: isolate_id, biosample_accession, country,
    collection_date, latitude, longitude.
    """
    results = []
    blocks = re.split(r'<BioSample[^>]*>', xml_data)

    for block in blocks:
        if not block.strip() or '</BioSample>' not in block:
            continue

        block = block.split('</BioSample>')[0]

        # Extract BioSample accession
        acc_m = re.search(r'<Id[^>]*db="BioSample"[^>]*>([^<]+)</Id>', block, re.IGNORECASE)
        if not acc_m:
            acc_m = re.search(r'accession="([^"]+)"', block)
        accession = acc_m.group(1) if acc_m else None

        if not accession or accession not in acc_to_isolates:
            continue

        # Extract organism
        org_m = re.search(r'<Organism[^>]*taxonomy_name="([^"]+)"', block)
        organism = org_m.group(1) if org_m else ""

        # Extract geo_loc_name
        geo_m = re.search(r'<Attribute[^>]*harmonized_name="geo_loc_name"[^>]*>([^<]+)</Attribute>', block)
        country_raw = geo_m.group(1) if geo_m else ""

        # Extract country (first part before colon, e.g., "China: Guangdong")
        country = country_raw.split(":")[0].strip() if country_raw else ""

        # Extract collection_date
        date_m = re.search(r'<Attribute[^>]*harmonized_name="collection_date"[^>]*>([^<]+)</Attribute>', block)
        collection_date = date_m.group(1) if date_m else ""

        # Extract lat_lon
        latlon_m = re.search(r'<Attribute[^>]*harmonized_name="lat_lon"[^>]*>([^<]+)</Attribute>', block)
        lat_lon_raw = latlon_m.group(1) if latlon_m else ""

        lat = None
        lon = None
        if lat_lon_raw:
            parts = lat_lon_raw.strip().split()
            if len(parts) >= 2:
                try:
                    lat = float(parts[0].replace("N", "").replace("S", "-").replace("E", "").replace("W", "-")
                                .rstrip("NSEW"))
                    lon = float(parts[1].replace("N", "").replace("S", "-").replace("E", "").replace("W", "-")
                                .rstrip("NSEW"))
                except ValueError:
                    pass

        isolate_ids = acc_to_isolates.get(accession, [])
        for iso_id in isolate_ids:
            results.append({
                "isolate_id": iso_id,
                "biosample_accession": accession,
                "country": country[:100],
                "collection_date": collection_date[:20],
                "latitude": lat,
                "longitude": lon,
            })

    return results


def main():
    parser = argparse.ArgumentParser(description="P1 Sample Metadata Enrichment")
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview changes only")
    parser.add_argument("--fetch-ncbi", action="store_true",
                        help="Fetch BioSample XML from NCBI eutils")
    parser.add_argument("--ncbi-api-key", type=str, default="",
                        help="NCBI API key for higher rate limits (3 req/s)")
    parser.add_argument("--db", type=str, default=str(DB_PATH),
                        help="Path to database file")
    args = parser.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"ERROR: Database not found: {db_path}")
        sys.exit(1)

    import sqlite3
    conn = sqlite3.connect(str(db_path), timeout=120)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 120000")

    try:
        stats = show_stats(conn)

        if args.fetch_ncbi:
            if not args.dry_run:
                backup_database(db_path, BACKUPS_DIR, "pre_biosample_fetch")
            result = fetch_biosample_metadata(db_path, args.dry_run, args.ncbi_api_key)
            print(f"\nBioSample Fetch Results:")
            print(f"  Fetched:                {result['fetched']}")
            print(f"  Parsed:                 {result['parsed']}")
            print(f"  Collections created:    {result['inserted_collections']}")
            print(f"  Geo profiles created:   {result['inserted_geo_profiles']}")
            print(f"  Failed:                 {result['failed']}")
            if result["errors"]:
                print(f"  Errors ({len(result['errors'])}):")
                for e in result["errors"][:5]:
                    print(f"    {e}")
        else:
            # Enrich from existing source_text
            with conn:
                result = enrich_from_source_text(conn, args.dry_run)

            label = "Would create" if args.dry_run else "Created"
            print(f"Source Text Enrichment Results:")
            print(f"  Parsed:                           {result['parsed']}")
            print(f"  {label} (collections):              {result['collections_created']}")
            print(f"  {label} (geo_profiles):             {result['geo_profiles_created']}")
            print(f"  Skipped (exists):                 {result['skipped_exists']}")
            print(f"  Skipped (no data):                {result['skipped_no_data']}")

            if not args.dry_run and result['geo_profiles_created'] > 0:
                print(f"\nTo fetch additional BioSample metadata from NCBI:")
                print(f"  python optimize_sample_metadata.py --fetch-ncbi --ncbi-api-key YOUR_KEY")

    finally:
        conn.close()


if __name__ == "__main__":
    main()
