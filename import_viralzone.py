"""
Import ViralZone data from SIB (Swiss Institute of Bioinformatics).

ViralZone (https://viralzone.expasy.org/) provides curated molecular biology
factsheets for virus families, including genome organization, replication cycle,
host range, and virion structure.

Strategy:
  1. Fetch ViralZone virus family list via SIB API / uniprot API
  2. For each relevant family (especially Iridoviridae and crustacean-related),
     fetch the factsheet page and parse structured data
  3. Store in viralzone_families + viralzone_gene_tables
  4. Cross-link with local ICTV taxonomy via family name

Usage:
    python import_viralzone.py                        # full run
    python import_viralzone.py --dry-run              # preview only
    python import_viralzone.py --rebuild-cache        # re-download
    python import_viralzone.py --stats                # coverage stats
"""

from __future__ import annotations

import json
import re
import sqlite3
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "crustacean_virus_core.db"
CACHE_DIR = BASE_DIR / "external_data" / "viralzone"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

VIRALZONE_BASE = "https://viralzone.expasy.org"
VIRALZONE_FAMILY_PAGE = "https://viralzone.expasy.org"

# Direct ViralZone family page URLs (known IDs from ViralZone)
# Format: family_name -> ViralZone ID suffix
VIRALZONE_URL_MAP = {
    "Iridoviridae": "https://viralzone.expasy.org/29",
    "Nimaviridae": "https://viralzone.expasy.org/by_species/558",
    "Malacoherpesviridae": "https://viralzone.expasy.org/by_species/529",
    "Nudiviridae": "https://viralzone.expasy.org/by_species/540",
    "Baculoviridae": "https://viralzone.expasy.org/13",
    "Nodaviridae": "https://viralzone.expasy.org/49",
    "Totiviridae": "https://viralzone.expasy.org/43",
    "Reoviridae": "https://viralzone.expasy.org/67",
    "Dicistroviridae": "https://viralzone.expasy.org/43",
    "Roniviridae": "https://viralzone.expasy.org/81",
    "Parvoviridae": "https://viralzone.expasy.org/53",
    "Picornaviridae": "https://viralzone.expasy.org/33",
    "Rhabdoviridae": "https://viralzone.expasy.org/62",
    "Birnaviridae": "https://viralzone.expasy.org/68",
    "Orthomyxoviridae": "https://viralzone.expasy.org/45",
    "Bunyaviridae": "https://viralzone.expasy.org/14",
}

# Known crustacean-virus-relevant families (by ICTV / ViralZone naming)
CRUSTACEAN_VIRUS_FAMILIES = {
    "Iridoviridae",
    "Nimaviridae",        # Whispovirus (White Spot Syndrome Virus)
    "Malacoherpesviridae", # Ostreid herpesvirus
    "Nudiviridae",
    "Parvoviridae",        # some infect crustaceans
    "Totiviridae",
    "Dicistroviridae",
    "Roniviridae",
    "Bunyaviridae",        # some crustacean-associated
    "Reoviridae",
    "Picornaviridae",
    "Siphoviridae",        # bacteriophages affecting crustacean microbiota
    "Myoviridae",
    "Podoviridae",
    "Baculoviridae",       # some infect shrimp
    "Nodaviridae",
    "Birnaviridae",
    "Rhabdoviridae",
    "Orthomyxoviridae",
}

# Broader: also include any family mentioned in ICTV crustacean virus data
# We'll match at runtime from local database

RATE_LIMIT = 0.3  # seconds between requests


def _get_json(url: str, timeout: int = 60) -> dict | list | None:
    """Fetch JSON from URL with error handling."""
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
        print(f"  [warn] Failed to fetch {url}: {exc}")
        return None


def _get_text(url: str, timeout: int = 60) -> str | None:
    """Fetch text/HTML from URL."""
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "crustacean-virus-db-curation/1.0",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except Exception as exc:
        print(f"  [warn] Failed to fetch {url}: {exc}")
        return None


def download_viralzone_families(conn, rebuild: bool = False) -> Path:
    """Build ViralZone family list from local ICTV taxonomy + known families."""
    cache_file = CACHE_DIR / "viralzone_families.json"
    if cache_file.exists() and not rebuild:
        age = datetime.now() - datetime.fromtimestamp(cache_file.stat().st_mtime)
        if age.days < 30:
            print(f"[cache] using cached {cache_file}")
            return cache_file

    print("[download] building ViralZone family list from local data ...")

    # Get all families from local ICTV taxonomy
    families = []
    seen = set()

    rows = conn.execute(
        "SELECT DISTINCT family FROM ictv_taxonomy WHERE family IS NOT NULL AND family != ''"
    ).fetchall()
    for r in rows:
        fam = r[0]
        if fam not in seen:
            seen.add(fam)
            if fam in VIRALZONE_URL_MAP:
                families.append({"family_name": fam, "url": VIRALZONE_URL_MAP[fam]})
            else:
                families.append({"family_name": fam, "url": None})

    # Also add all from the map
    for fam, url in VIRALZONE_URL_MAP.items():
        if fam not in seen:
            seen.add(fam)
            families.append({"family_name": fam, "url": url})

    cache_file.write_text(json.dumps(families, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[cache] saved {len(families)} families to {cache_file}")
    return cache_file


def _scrape_family_list(conn, cache_file: Path) -> Path:
    """Build family list from local ICTV families + known families."""
    families = []
    seen = set()
    for fam in sorted(CRUSTACEAN_VIRUS_FAMILIES):
        seen.add(fam)
        families.append({
            "family_name": fam,
            "url": VIRALZONE_URL_MAP.get(fam, None),
        })
    # Also try to get from local DB
    try:
        rows = conn.execute("SELECT DISTINCT family FROM ictv_taxonomy WHERE family IS NOT NULL").fetchall()
        for r in rows:
            fam = r[0]
            if fam and fam not in seen:
                seen.add(fam)
                families.append({
                    "family_name": fam,
                    "url": VIRALZONE_URL_MAP.get(fam, None),
                })
    except Exception:
        pass
    cache_file.write_text(json.dumps(families, ensure_ascii=False, indent=2), encoding="utf-8")
    return cache_file


def parse_viralzone_factsheet(html: str, family_name: str) -> dict[str, Any]:
    """Parse a ViralZone family factsheet page for structured data."""
    result: dict[str, Any] = {
        "family_name": family_name,
        "virion": None,
        "genome": None,
        "genome_type": None,
        "genome_size_range": None,
        "replication": None,
        "host_range": None,
        "transmission": None,
        "taxonomy": None,
        "genera": [],
        "reference_strains": [],
        "gene_table": [],
        "raw_sections": {},
    }

    if not html:
        return result

    # Extract general info from definition list
    # ViralZone uses <dt>/<dd> pairs for structured data
    dt_pattern = re.compile(r'<dt[^>]*>(.*?)</dt>\s*<dd[^>]*>(.*?)</dd>', re.DOTALL | re.IGNORECASE)
    field_map = {
        "virion": "virion",
        "genome": "genome",
        "genome type": "genome_type",
        "replication": "replication",
        "host": "host_range",
        "transmission": "transmission",
        "taxonomy": "taxonomy",
    }

    for match in dt_pattern.finditer(html):
        key = match.group(1).strip().lower()
        value = re.sub(r'<[^>]+>', '', match.group(2)).strip()
        for field_key, result_key in field_map.items():
            if field_key in key:
                result[result_key] = value
                result["raw_sections"][key] = value
                break

    # Try to extract genome size from text
    size_match = re.search(r'(\d+[.,]?\d*)\s*[-–to]+\s*(\d+[.,]?\d*)\s*(kb|kbp|bp)', html, re.IGNORECASE)
    if size_match:
        result["genome_size_range"] = f"{size_match.group(1)}-{size_match.group(2)} {size_match.group(3)}"

    # Extract genera from content
    genus_pattern = re.findall(r'<a[^>]*href="[^"]*genus[^"]*"[^>]*>([^<]+)</a>', html, re.IGNORECASE)
    if genus_pattern:
        result["genera"] = list(set(g.strip() for g in genus_pattern if g.strip()))

    # Try to extract gene/ORF table
    # Look for table with gene names
    table_match = re.search(r'<table[^>]*>.*?</table>', html, re.DOTALL | re.IGNORECASE)
    if table_match:
        rows = re.findall(r'<tr[^>]*>(.*?)</tr>', table_match.group(), re.DOTALL | re.IGNORECASE)
        for row in rows:
            cells = re.findall(r'<t[hd][^>]*>(.*?)</t[hd]>', row, re.DOTALL | re.IGNORECASE)
            cells_clean = [re.sub(r'<[^>]+>', '', c).strip() for c in cells]
            if len(cells_clean) >= 2:
                result["gene_table"].append(cells_clean)

    return result


def create_tables(conn: sqlite3.Connection) -> None:
    """Create viralzone tables if not exists."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS viralzone_families (
            family_id INTEGER PRIMARY KEY AUTOINCREMENT,
            family_name TEXT NOT NULL UNIQUE,
            virion_description TEXT,
            genome_description TEXT,
            genome_type TEXT,
            genome_size_range TEXT,
            replication_cycle TEXT,
            host_range TEXT,
            transmission TEXT,
            taxonomy_lineage TEXT,
            genera_list TEXT,
            reference_strains TEXT,
            viralzone_url TEXT,
            raw_json TEXT,
            fetched_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS viralzone_gene_tables (
            gene_entry_id INTEGER PRIMARY KEY AUTOINCREMENT,
            family_id INTEGER NOT NULL,
            gene_name TEXT,
            protein_name TEXT,
            function_description TEXT,
            position TEXT,
            notes TEXT,
            FOREIGN KEY (family_id) REFERENCES viralzone_families(family_id)
        );

        CREATE INDEX IF NOT EXISTS idx_vz_family ON viralzone_families(family_name);
        CREATE INDEX IF NOT EXISTS idx_vz_gene_family ON viralzone_gene_tables(family_id);
    """)
    conn.commit()


def get_local_families(conn: sqlite3.Connection) -> set[str]:
    """Get all virus families from local ICTV taxonomy and virus_master."""
    families = set()
    # From ICTV taxonomy
    rows = conn.execute(
        "SELECT DISTINCT family FROM ictv_taxonomy WHERE family IS NOT NULL AND family != ''"
    ).fetchall()
    for r in rows:
        families.add(r[0])
    # From virus_master
    rows = conn.execute(
        "SELECT DISTINCT virus_family FROM virus_master WHERE virus_family IS NOT NULL AND virus_family != ''"
    ).fetchall()
    for r in rows:
        families.add(r[0])
    return families


def import_viralzone(
    conn: sqlite3.Connection,
    dry_run: bool = False,
    rebuild_cache: bool = False,
) -> int:
    """Main import logic. Returns number of families imported."""
    cache_file = download_viralzone_families(conn, rebuild=rebuild_cache)
    data = json.loads(cache_file.read_text(encoding="utf-8"))

    local_families = get_local_families(conn)
    # Expand: also include known crustacean-relevant families
    target_families = local_families | CRUSTACEAN_VIRUS_FAMILIES

    imported = 0
    records = data if isinstance(data, list) else []

    if not records:
        # Build from target families directly
        records = [{"family_name": f} for f in sorted(target_families)]

    for entry in records:
        family_name = entry.get("family_name", "")
        if not family_name:
            continue

        # Check if family is relevant
        if family_name not in target_families:
            continue

        family_url = entry.get("url")
        if not family_url:
            # No known URL, still store basic info if family is in target list
            if family_name in target_families and not dry_run:
                conn.execute(
                    """
                    INSERT INTO viralzone_families
                        (family_name, viralzone_url)
                    VALUES (?, ?)
                    ON CONFLICT(family_name) DO NOTHING
                    """,
                    (family_name, None),
                )
                imported += 1
            continue

        if dry_run:
            print(f"  [dry-run] would import: {family_name}")
            imported += 1
            continue

        print(f"  [fetching] {family_name} ...")
        html = _get_text(family_url)
        factsheet = parse_viralzone_factsheet(html or "", family_name)

        # Upsert into viralzone_families
        conn.execute(
            """
            INSERT INTO viralzone_families
                (family_name, virion_description, genome_description, genome_type,
                 genome_size_range, replication_cycle, host_range, transmission,
                 taxonomy_lineage, genera_list, reference_strains, viralzone_url, raw_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(family_name) DO UPDATE SET
                virion_description = excluded.virion_description,
                genome_description = excluded.genome_description,
                genome_type = excluded.genome_type,
                genome_size_range = excluded.genome_size_range,
                replication_cycle = excluded.replication_cycle,
                host_range = excluded.host_range,
                transmission = excluded.transmission,
                taxonomy_lineage = excluded.taxonomy_lineage,
                viralzone_url = excluded.viralzone_url,
                raw_json = excluded.raw_json,
                fetched_at = CURRENT_TIMESTAMP
            """,
            (
                family_name,
                factsheet.get("virion"),
                factsheet.get("genome"),
                factsheet.get("genome_type"),
                factsheet.get("genome_size_range"),
                factsheet.get("replication"),
                factsheet.get("host_range"),
                factsheet.get("transmission"),
                factsheet.get("taxonomy"),
                json.dumps(factsheet.get("genera", [])),
                json.dumps(factsheet.get("reference_strains", [])),
                family_url,
                json.dumps(factsheet, ensure_ascii=False),
            ),
        )

        # Get family_id for gene table
        row = conn.execute(
            "SELECT family_id FROM viralzone_families WHERE family_name = ?",
            (family_name,),
        ).fetchone()
        if row and factsheet.get("gene_table"):
            family_id = row[0]
            # Clear old gene entries
            conn.execute(
                "DELETE FROM viralzone_gene_tables WHERE family_id = ?",
                (family_id,),
            )
            for gene_row in factsheet["gene_table"]:
                conn.execute(
                    """
                    INSERT INTO viralzone_gene_tables
                        (family_id, gene_name, protein_name, function_description, position)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        family_id,
                        gene_row[0] if len(gene_row) > 0 else None,
                        gene_row[1] if len(gene_row) > 1 else None,
                        gene_row[2] if len(gene_row) > 2 else None,
                        gene_row[3] if len(gene_row) > 3 else None,
                    ),
                )

        imported += 1
        time.sleep(RATE_LIMIT)

    conn.commit()
    return imported


def register_source(conn: sqlite3.Connection) -> None:
    """Register ViralZone in external_sources."""
    conn.execute(
        """
        INSERT INTO external_sources
            (source_key, name, category, base_url, description, update_policy, priority)
        VALUES ('viralzone', 'ViralZone', 'virus_knowledge',
                'https://viralzone.expasy.org/',
                'Curated virus family factsheets with genome organization, replication, and host data.',
                'manual_or_api', 35)
        ON CONFLICT(source_key) DO UPDATE SET
            name = excluded.name,
            category = excluded.category,
            base_url = excluded.base_url,
            description = excluded.description,
            priority = excluded.priority,
            updated_at = CURRENT_TIMESTAMP
        """
    )
    conn.commit()


def show_stats(conn: sqlite3.Connection) -> None:
    """Print coverage statistics."""
    print("\n=== ViralZone Integration Stats ===")
    row = conn.execute("SELECT COUNT(*) FROM viralzone_families").fetchone()
    print(f"  Families imported: {row[0]}")
    row = conn.execute("SELECT COUNT(*) FROM viralzone_gene_tables").fetchone()
    print(f"  Gene table entries: {row[0]}")
    row = conn.execute(
        "SELECT family_name, genome_type, host_range FROM viralzone_families LIMIT 10"
    ).fetchall()
    print("  Sample families:")
    for r in row:
        print(f"    {r[0]:30s} genome: {r[1] or 'N/A':20s} host: {r[2] or 'N/A'}")


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="Import ViralZone data")
    parser.add_argument("--dry-run", action="store_true", help="Preview only")
    parser.add_argument("--rebuild-cache", action="store_true", help="Re-download cache")
    parser.add_argument("--stats", action="store_true", help="Show stats only")
    args = parser.parse_args()

    conn = sqlite3.connect(str(DB_PATH))
    try:
        create_tables(conn)
        register_source(conn)

        if args.stats:
            show_stats(conn)
            return

        imported = import_viralzone(
            conn,
            dry_run=args.dry_run,
            rebuild_cache=args.rebuild_cache,
        )
        print(f"\n[done] Imported {imported} ViralZone family factsheets")
        show_stats(conn)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
