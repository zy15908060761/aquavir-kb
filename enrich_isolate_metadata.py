"""
Enrich isolate metadata from NCBI GenBank XML source feature qualifiers.

Strategy:
  1. Iterate over viral_isolates with real nucleotide accessions
     (exclude XM_, NW_, NC_, join(, RDRP_ pseudo-accessions)
  2. Fetch GenBank XML via NCBI efetch for each accession
  3. Parse /host, /isolation_source, /country, /collection_date, /lat_lon
     from the source feature qualifiers
  4. Store in sample_metadata table (one row per isolate_id)

Usage:
    python enrich_isolate_metadata.py                        # full run
    python enrich_isolate_metadata.py --dry-run              # preview only
    python enrich_isolate_metadata.py --rebuild-cache        # re-fetch all
    python enrich_isolate_metadata.py --limit 50             # process first N
    python enrich_isolate_metadata.py --stats                # coverage stats
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import time
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from typing import Any


BASE_DIR = Path(__file__).resolve().parent
DB_PATH = Path(os.environ.get("ENRICH_DB_PATH", "")) if os.environ.get("ENRICH_DB_PATH") else BASE_DIR / "crustacean_virus_core.db"
CACHE_DIR = BASE_DIR / "external_data" / "genbank_metadata"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

NCBI_API_KEY = ""  # optional: set your NCBI API key for higher rate limits
MIN_RATE_LIMIT_INTERVAL = 0.35  # ~3 req/sec without API key, 0.1 with key

# Accession patterns that are NOT real nucleotide accessions
SKIP_PREFIXES = ("XM_", "XR_", "XM_", "NW_", "NC_", "NT_", "NW_", "join(", "RDRP_", "COMPLETE_")


def is_real_accession(acc: str | None) -> bool:
    """Check if an accession is a real GenBank nucleotide accession."""
    if not acc or not acc.strip():
        return False
    acc = acc.strip().split(".")[0]  # strip version number
    if acc.startswith(SKIP_PREFIXES):
        return False
    # Must start with at least 2 uppercase letters followed by digits
    if not re.match(r"^[A-Z]{2}\d+", acc):
        return False
    return True


def normalize_accession(acc: str) -> str:
    """Strip version suffix for lookup."""
    return acc.strip().split(".")[0]


def cache_path(accession: str) -> Path:
    """Path to cached GenBank XML for an accession."""
    # Use first 3 chars as subdirectory to avoid too many files in one dir
    sub = accession[:3].lower()
    (CACHE_DIR / sub).mkdir(exist_ok=True)
    return CACHE_DIR / sub / f"{accession}.xml"


def fetch_genbank_xml(accession: str, rebuild: bool = False) -> str | None:
    """Fetch GenBank XML for an accession, using cache if available."""
    acc = normalize_accession(accession)
    cache_file = cache_path(acc)

    if cache_file.exists() and not rebuild:
        return cache_file.read_text(encoding="utf-8", errors="replace")

    url = (
        f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
        f"?db=nucleotide&id={acc}&retmode=xml"
    )
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "crustacean-virus-db-curation/1.0"},
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = resp.read().decode("utf-8", errors="replace")
        cache_file.write_text(data, encoding="utf-8")
        return data
    except Exception as exc:
        # Write empty placeholder so we don't retry on next run
        if not cache_file.exists():
            cache_file.write_text("", encoding="utf-8")
        return None


def parse_genbank_metadata(xml_str: str) -> dict[str, str | None]:
    """Parse GenBank XML for source feature qualifiers."""
    if not xml_str or not xml_str.strip():
        return {}

    try:
        root = ET.fromstring(xml_str)
    except ET.ParseError:
        return {}

    ns = {}  # no namespace in GenBank XML

    metadata: dict[str, str | None] = {
        "host": None,
        "collection_date": None,
        "isolation_source": None,
        "country": None,
        "geo_loc_name": None,
        "lat_lon": None,
        "isolate": None,
        "strain": None,
        "db_xref": None,
        "note": None,
        "mol_type": None,
        "organism": None,
    }

    # Find source feature qualifiers
    for gbseq in root.findall(".//GBSeq"):
        features = gbseq.find(".//GBSeq_feature-table")
        if features is None:
            continue

        for feature in features.findall("GBFeature"):
            key_elem = feature.find("GBFeature_key")
            if key_elem is None or key_elem.text != "source":
                continue

            quals = feature.find("GBFeature_quals")
            if quals is None:
                continue

            for qual in quals.findall("GBQualifier"):
                name_elem = qual.find("GBQualifier_name")
                val_elem = qual.find("GBQualifier_value")
                if name_elem is not None and val_elem is not None:
                    name = name_elem.text.strip() if name_elem.text else ""
                    value = val_elem.text.strip() if val_elem.text else ""
                    if name in metadata and value:
                        metadata[name] = value

    return {k: v for k, v in metadata.items() if v is not None}


def download_schema(conn: sqlite3.Connection) -> None:
    """Create sample_metadata table if it doesn't exist."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sample_metadata (
            isolate_id INTEGER PRIMARY KEY,
            accession TEXT NOT NULL,
            host_name TEXT,
            collection_date TEXT,
            isolation_source TEXT,
            geo_loc_name TEXT,
            lat_lon TEXT,
            isolate_name TEXT,
            strain TEXT,
            organism TEXT,
            mol_type TEXT,
            ncbi_taxid INTEGER,
            raw_notes TEXT,
            fetched_at TEXT,
            FOREIGN KEY (isolate_id) REFERENCES viral_isolates(isolate_id)
        )
    """)


def find_isolates(conn: sqlite3.Connection, limit: int | None = None) -> list[dict]:
    """Find isolates with real nucleotide accessions that need metadata enrichment."""
    query = """
        SELECT vi.isolate_id, vi.accession, vi.virus_name, vm.canonical_name
        FROM viral_isolates vi
        LEFT JOIN virus_master vm ON vi.master_id = vm.master_id
        WHERE vi.accession IS NOT NULL
          AND TRIM(vi.accession) <> ''
          AND vi.accession NOT LIKE 'XM_%%'
          AND vi.accession NOT LIKE 'XR_%%'
          AND vi.accession NOT LIKE 'NW_%%'
          AND vi.accession NOT LIKE 'NC_%%'
          AND vi.accession NOT LIKE 'NT_%%'
          AND vi.accession NOT LIKE 'join(%%'
          AND vi.accession NOT LIKE 'RDRP_%%'
          AND vi.accession NOT LIKE 'COMPLETE_%%'
    """
    # Exclude those already fetched
    query += """
          AND vi.isolate_id NOT IN (
              SELECT isolate_id FROM sample_metadata WHERE fetched_at IS NOT NULL
          )
    """
    query += " ORDER BY vi.isolate_id"
    if limit:
        query += f" LIMIT {limit}"

    rows = conn.execute(query).fetchall()
    return [dict(r) for r in rows]


def get_stats(conn: sqlite3.Connection) -> dict:
    """Get metadata enrichment coverage stats."""
    total = conn.execute(
        "SELECT COUNT(*) FROM viral_isolates WHERE accession IS NOT NULL AND TRIM(accession) <> ''"
    ).fetchone()[0]
    real = conn.execute(
        """SELECT COUNT(*) FROM viral_isolates
           WHERE accession IS NOT NULL AND TRIM(accession) <> ''
             AND accession NOT LIKE 'XM_%%' AND accession NOT LIKE 'NW_%%'
             AND accession NOT LIKE 'NC_%%' AND accession NOT LIKE 'NT_%%'
             AND accession NOT LIKE 'join(%%' AND accession NOT LIKE 'RDRP_%%'
             AND accession NOT LIKE 'COMPLETE_%%'"""
    ).fetchone()[0]
    enriched = conn.execute(
        "SELECT COUNT(*) FROM sample_metadata WHERE fetched_at IS NOT NULL"
    ).fetchone()[0]
    has_host = conn.execute(
        "SELECT COUNT(*) FROM sample_metadata WHERE host_name IS NOT NULL"
    ).fetchone()[0]
    has_date = conn.execute(
        "SELECT COUNT(*) FROM sample_metadata WHERE collection_date IS NOT NULL"
    ).fetchone()[0]
    has_source = conn.execute(
        "SELECT COUNT(*) FROM sample_metadata WHERE isolation_source IS NOT NULL"
    ).fetchone()[0]
    has_geo = conn.execute(
        "SELECT COUNT(*) FROM sample_metadata WHERE geo_loc_name IS NOT NULL"
    ).fetchone()[0]

    return {
        "total_isolates": total,
        "real_accessions": real,
        "enriched": enriched,
        "with_host": has_host,
        "with_collection_date": has_date,
        "with_isolation_source": has_source,
        "with_geo_location": has_geo,
        "remaining": real - enriched,
    }


def enrich(
    conn: sqlite3.Connection,
    dry_run: bool = False,
    rebuild_cache: bool = False,
    limit: int | None = None,
) -> dict:
    """Main enrichment logic."""
    stats = {
        "processed": 0,
        "fetched": 0,
        "cached": 0,
        "failed": 0,
        "with_host": 0,
        "with_collection_date": 0,
        "with_isolation_source": 0,
        "with_country": 0,
        "with_lat_lon": 0,
        "empty_xml": 0,
        "skipped_accession": 0,
    }

    isolates = find_isolates(conn, limit=limit)
    if not isolates:
        print("[info] No isolates pending enrichment.")
        return stats

    print(f"[isolates] {len(isolates)} pending metadata enrichment")
    stats["total_pending"] = len(isolates)

    COMMIT_INTERVAL = 200  # commit every N isolates
    last_commit = 0
    last_iso_id = None

    for i, iso in enumerate(isolates, 1):
        acc = iso["accession"].strip()
        if not is_real_accession(acc):
            stats["skipped_accession"] += 1
            continue

        try:
            stats["processed"] += 1
            isolate_id = iso["isolate_id"]
            last_iso_id = isolate_id
            cache_file = cache_path(normalize_accession(acc))

            if cache_file.exists() and not rebuild_cache:
                xml_str = cache_file.read_text(encoding="utf-8", errors="replace")
                if xml_str.strip():
                    stats["cached"] += 1
                else:
                    stats["empty_xml"] += 1
                    continue
            else:
                stats["fetched"] += 1
                xml_str = fetch_genbank_xml(acc, rebuild=True)
                if xml_str is None:
                    stats["failed"] += 1
                    if (i) % 10 == 0:
                        print(f"  [{i}/{len(isolates)}] failed: {acc}")
                    time.sleep(MIN_RATE_LIMIT_INTERVAL)
                    continue
                time.sleep(MIN_RATE_LIMIT_INTERVAL)

            meta = parse_genbank_metadata(xml_str)
            if not meta:
                stats["empty_xml"] += 1
                if (i) % 50 == 0:
                    print(f"  [{i}/{len(isolates)}] no metadata: {acc}")
                continue

            # Use geo_loc_name (preferred) or country as fallback
            geo_value = meta.get("geo_loc_name") or meta.get("country")

            if (i) % 50 == 0 or (meta.get("host") and stats["processed"] <= 5):
                hints = []
                if meta.get("host"):
                    hints.append(f"host={meta['host']}")
                if meta.get("collection_date"):
                    hints.append(f"date={meta['collection_date']}")
                if meta.get("isolation_source"):
                    hints.append(f"source={meta['isolation_source']}")
                if geo_value:
                    hints.append(f"geo={geo_value}")
                print(f"  [{i}/{len(isolates)}] {acc}: {', '.join(hints)}")

            # Count what we found
            if meta.get("host"):
                stats["with_host"] += 1
            if meta.get("collection_date"):
                stats["with_collection_date"] += 1
            if meta.get("isolation_source"):
                stats["with_isolation_source"] += 1
            if geo_value:
                stats["with_country"] += 1
            if meta.get("lat_lon"):
                stats["with_lat_lon"] += 1

            if not dry_run:
                # Extract NCBI TaxID from db_xref
                ncbi_taxid = None
                db_xref = meta.get("db_xref", "")
                if db_xref:
                    m = re.search(r"taxon:(\d+)", db_xref)
                    if m:
                        ncbi_taxid = int(m.group(1))

                conn.execute(
                    """
                    INSERT OR REPLACE INTO sample_metadata
                        (isolate_id, accession, host_name, collection_date,
                         isolation_source, geo_loc_name, lat_lon,
                         isolate_name, strain, organism, mol_type,
                         ncbi_taxid, raw_notes, fetched_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        isolate_id,
                        normalize_accession(acc),
                        meta.get("host"),
                        meta.get("collection_date"),
                        meta.get("isolation_source"),
                        geo_value,  # geo_loc_name or country
                        meta.get("lat_lon"),
                        meta.get("isolate"),
                        meta.get("strain"),
                        meta.get("organism"),
                        meta.get("mol_type"),
                        ncbi_taxid,
                        meta.get("note"),
                        datetime.now().isoformat(timespec="seconds"),
                    ),
                )

            # Periodic commit
            if not dry_run and (i - last_commit) >= COMMIT_INTERVAL:
                conn.commit()
                last_commit = i
                print(f"  [commit] checkpoint at {i}/{len(isolates)} (isolate_id={isolate_id})")

        except Exception as exc:
            print(f"  [error] at {acc} (isolate_id={iso['isolate_id']}): {exc}")
            # Continue with next accession rather than crashing
            stats.setdefault("errors", []).append(str(acc))
            continue

    # Final commit of remaining rows
    if not dry_run and last_commit < stats["processed"]:
        conn.commit()

    return stats


def export_results(stats: dict) -> Path:
    """Write stats JSON to downloads dir."""
    out_dir = BASE_DIR / "downloads"
    out_dir.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = out_dir / f"metadata_enrich_{stamp}.json"
    data = {
        "script": "enrich_isolate_metadata.py",
        "stats": {k: v for k, v in sorted(stats.items()) if not k.startswith("_")},
        "completed_at": datetime.now().isoformat(timespec="seconds"),
    }
    out_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_path


def print_stats(stats: dict) -> None:
    """Pretty-print enrichment stats."""
    print(f"\n{'=' * 60}")
    print(f"Metadata Enrichment Results")
    print(f"{'=' * 60}")
    for key, value in sorted(stats.items()):
        print(f"  {key.replace('_', ' '):30s} {value}")


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Enrich isolate metadata from NCBI GenBank")
    parser.add_argument("--dry-run", action="store_true", help="Preview only")
    parser.add_argument("--rebuild-cache", action="store_true", help="Re-fetch all accessions")
    parser.add_argument("--limit", type=int, default=None, help="Process only first N isolates")
    parser.add_argument("--stats", action="store_true", help="Show coverage stats only")
    args = parser.parse_args()

    conn = sqlite3.connect(str(DB_PATH), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")

    try:
        download_schema(conn)

        if args.stats:
            s = get_stats(conn)
            print(f"\n{'=' * 60}")
            print(f"Metadata Enrichment Coverage Stats")
            print(f"{'=' * 60}")
            for k, v in sorted(s.items()):
                print(f"  {k.replace('_', ' '):30s} {v}")
            return

        if args.dry_run:
            print("[dry-run] Preview mode — no database writes")

        print(f"Starting metadata enrichment from NCBI GenBank...")
        print(f"  Dry run: {args.dry_run}")
        print(f"  Rebuild cache: {args.rebuild_cache}")
        print(f"  Limit: {args.limit or 'unlimited'}")

        stats = enrich(conn, dry_run=args.dry_run, rebuild_cache=args.rebuild_cache, limit=args.limit)

        if not args.dry_run and stats.get("processed", 0) > 0:
            export_path = export_results(stats)
            conn.commit()
            print(f"\n[export] Results written to {export_path}")

        print_stats(stats)

    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
