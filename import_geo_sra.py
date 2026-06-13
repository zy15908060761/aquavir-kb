"""
Import GEO (Gene Expression Omnibus) and SRA (Sequence Read Archive) metadata
for crustacean virus transcriptomics studies.

Strategy:
  1. Search GEO DataSets for crustacean virus + host terms
  2. Search SRA for crustacean virus sequencing projects
  3. Match to local virus isolates by name/species
  4. Store transcriptomics metadata for cross-reference

Uses NCBI E-utilities (same API family as existing NCBI scripts).

Usage:
    python import_geo_sra.py                          # full run
    python import_geo_sra.py --dry-run                # preview only
    python import_geo_sra.py --limit 50               # process first N datasets
    python import_geo_sra.py --stats                  # coverage stats
"""

from __future__ import annotations

import json
import os
import sys
import re
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "crustacean_virus_core.db"
CACHE_DIR = BASE_DIR / "external_data" / "geo_sra"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

NCBI_EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
NCBI_EMAIL = "crustacean-virus-db@example.com"
RATE_LIMIT = 0.4  # seconds between NCBI requests (E-utilities limit: 3/sec)
NCBI_API_KEY = os.environ.get("NCBI_API_KEY", "").strip()
REQUEST_RETRIES = 3
ESUMMARY_BATCH_SIZE = 10

# Search terms for crustacean virus transcriptomics
SEARCH_TERMS = [
    '(shrimp virus OR crab virus OR crayfish virus OR lobster virus OR prawn virus) AND (transcriptom* OR RNA-seq OR expression)',
    '(iridovirus OR white spot syndrome OR WSSV OR yellow head virus OR taura syndrome) AND (transcriptom* OR RNA-seq)',
    '(nimavirus OR whispovirus OR crustacean iridovirus) AND (gene expression OR transcriptom*)',
    '(crustacean AND viral infection) AND (transcriptom* OR RNA-seq OR microarray)',
]


def _esearch(db: str, term: str, retmax: int = 200) -> list[str]:
    """Search NCBI database, return list of IDs."""
    params = {
        "db": db,
        "term": term,
        "retmax": retmax,
        "retmode": "json",
        "usehistory": "n",
        "email": NCBI_EMAIL,
    }
    if NCBI_API_KEY:
        params["api_key"] = NCBI_API_KEY
    url = f"{NCBI_EUTILS}/esearch.fcgi?{urllib.parse.urlencode(params)}"
    for attempt in range(1, REQUEST_RETRIES + 1):
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "crustacean-virus-db-curation/1.0"},
            )
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = json.loads(resp.read().decode())
            return data.get("esearchresult", {}).get("idlist", [])
        except Exception as exc:
            print(f"  [warn] ESearch failed for {db}/{term[:50]} attempt {attempt}/{REQUEST_RETRIES}: {exc}")
            time.sleep(RATE_LIMIT * attempt)
    return []


def _esummary(db: str, ids: list[str]) -> list[dict[str, Any]]:
    """Fetch summaries for given IDs."""
    if not ids:
        return []
    id_str = ",".join(ids)
    params = {
        "db": db,
        "id": id_str,
        "retmode": "json",
        "email": NCBI_EMAIL,
    }
    if NCBI_API_KEY:
        params["api_key"] = NCBI_API_KEY
    url = f"{NCBI_EUTILS}/esummary.fcgi?{urllib.parse.urlencode(params)}"
    for attempt in range(1, REQUEST_RETRIES + 1):
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "crustacean-virus-db-curation/1.0"},
            )
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = json.loads(resp.read().decode())
            result = data.get("result", {})
            result.pop("uids", None)
            return list(result.values())
        except Exception as exc:
            print(f"  [warn] ESummary failed attempt {attempt}/{REQUEST_RETRIES}: {exc}")
            time.sleep(RATE_LIMIT * attempt)
    return []


def create_tables(conn: sqlite3.Connection) -> None:
    """Create GEO/SRA metadata tables."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS geo_datasets (
            geo_id INTEGER PRIMARY KEY AUTOINCREMENT,
            gse_accession TEXT NOT NULL UNIQUE,
            title TEXT,
            summary TEXT,
            organism TEXT,
            experiment_type TEXT,
            platform TEXT,
            sample_count INTEGER,
            pubmed_ids TEXT,
            submission_date TEXT,
            gds_type TEXT,
            virus_species_matched TEXT,
            host_species_matched TEXT,
            raw_json TEXT,
            fetched_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS sra_runs (
            sra_id INTEGER PRIMARY KEY AUTOINCREMENT,
            sra_accession TEXT NOT NULL UNIQUE,
            bioproject TEXT,
            biosample TEXT,
            title TEXT,
            organism TEXT,
            library_strategy TEXT,
            library_source TEXT,
            library_layout TEXT,
            platform TEXT,
            total_bases TEXT,
            total_spots TEXT,
            run_date TEXT,
            geo_linked TEXT,
            virus_species_matched TEXT,
            raw_json TEXT,
            fetched_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS geo_virus_links (
            link_id INTEGER PRIMARY KEY AUTOINCREMENT,
            geo_dataset_id INTEGER,
            sra_run_id INTEGER,
            local_isolate_id INTEGER,
            virus_name TEXT,
            match_type TEXT DEFAULT 'name_fuzzy',
            match_confidence TEXT DEFAULT 'medium',
            notes TEXT,
            FOREIGN KEY (geo_dataset_id) REFERENCES geo_datasets(geo_id),
            FOREIGN KEY (sra_run_id) REFERENCES sra_runs(sra_id),
            FOREIGN KEY (local_isolate_id) REFERENCES viral_isolates(isolate_id)
        );

        CREATE INDEX IF NOT EXISTS idx_geo_gse ON geo_datasets(gse_accession);
        CREATE INDEX IF NOT EXISTS idx_sra_acc ON sra_runs(sra_accession);
        CREATE INDEX IF NOT EXISTS idx_geo_virus_name ON geo_virus_links(virus_name);
    """)
    conn.commit()


def search_and_import_geo(
    conn: sqlite3.Connection,
    dry_run: bool = False,
    limit: int | None = None,
) -> int:
    """Search GEO and import dataset metadata."""
    all_gse_ids: set[str] = set()
    for term in SEARCH_TERMS:
        ids = _esearch("gds", term, retmax=100)
        print(f"  [search] '{term[:60]}...' -> {len(ids)} datasets")
        all_gse_ids.update(ids)
        time.sleep(RATE_LIMIT)

    if limit:
        all_gse_ids = set(list(all_gse_ids)[:limit])

    print(f"[geo] Total unique datasets: {len(all_gse_ids)}")

    if dry_run:
        for gid in list(all_gse_ids)[:20]:
            print(f"  [dry-run] GSE ID: {gid}")
        return 0

    # Fetch summaries in batches of 50
    id_list = list(all_gse_ids)
    imported = 0
    local_viruses = _get_local_virus_names(conn)

    for i in range(0, len(id_list), ESUMMARY_BATCH_SIZE):
        batch = id_list[i:i + ESUMMARY_BATCH_SIZE]
        summaries = _esummary("gds", batch)

        for s in summaries:
            gse = s.get("accession", "")
            if not gse:
                continue
            title = s.get("title", "")
            summary = s.get("summary", "")
            organism = s.get("taxon", "")

            # Match to local viruses
            matched = _match_virus_names(title + " " + summary, local_viruses)

            try:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO geo_datasets
                        (gse_accession, title, summary, organism, experiment_type,
                         platform, sample_count, pubmed_ids, submission_date, gds_type,
                         virus_species_matched, raw_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        gse,
                        title,
                        summary[:5000] if summary else "",
                        organism,
                        s.get("gdsType", ""),
                        s.get("gpl", ""),
                        int(s.get("n_samples", 0)) if s.get("n_samples") else None,
                        json.dumps(s.get("pmids", [])),
                        s.get("PDAT", ""),
                        s.get("gdsType", ""),
                        json.dumps(matched) if matched else None,
                        json.dumps(s, ensure_ascii=False),
                    ),
                )
                imported += 1

                # Create virus links
                if matched:
                    row = conn.execute(
                        "SELECT geo_id FROM geo_datasets WHERE gse_accession = ?",
                        (gse,),
                    ).fetchone()
                    if row:
                        for vname in matched:
                            _link_geo_to_local(conn, row[0], vname, "name_fuzzy")

            except Exception as exc:
                print(f"  [warn] DB insert error for {gse}: {exc}")

        time.sleep(RATE_LIMIT)

    conn.commit()
    return imported


def search_and_import_sra(
    conn: sqlite3.Connection,
    dry_run: bool = False,
    limit: int | None = None,
) -> int:
    """Search SRA and import run metadata."""
    all_sra_ids: set[str] = set()
    for term in SEARCH_TERMS:
        ids = _esearch("sra", term, retmax=100)
        print(f"  [search] '{term[:60]}...' -> {len(ids)} SRA entries")
        all_sra_ids.update(ids)
        time.sleep(RATE_LIMIT)

    if limit:
        all_sra_ids = set(list(all_sra_ids)[:limit])

    print(f"[sra] Total unique SRA entries: {len(all_sra_ids)}")

    if dry_run:
        for sid in list(all_sra_ids)[:20]:
            print(f"  [dry-run] SRA ID: {sid}")
        return 0

    id_list = list(all_sra_ids)
    imported = 0
    local_viruses = _get_local_virus_names(conn)

    for i in range(0, len(id_list), ESUMMARY_BATCH_SIZE):
        batch = id_list[i:i + ESUMMARY_BATCH_SIZE]
        summaries = _esummary("sra", batch)

        for s in summaries:
            expxml = s.get("expxml", "") or s.get("ExpXml", "")
            runs_xml = s.get("runs", "") or s.get("Runs", "")
            parsed = _parse_sra_xml(expxml, runs_xml)
            acc = parsed.get("sra_accession") or s.get("accession", "") or s.get("Run", "")
            if not acc:
                continue
            title = parsed.get("title") or s.get("title", "")
            organism = parsed.get("organism") or s.get("ScientificName", "") or s.get("organism", "")

            matched = _match_virus_names(title + " " + organism, local_viruses)

            try:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO sra_runs
                        (sra_accession, bioproject, biosample, title, organism,
                         library_strategy, library_source, library_layout, platform,
                         total_bases, total_spots, run_date, geo_linked,
                         virus_species_matched, raw_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        acc,
                        parsed.get("bioproject") or s.get("Bioproject", ""),
                        parsed.get("biosample") or s.get("Biosample", ""),
                        title,
                        organism,
                        parsed.get("library_strategy") or s.get("LibraryStrategy", ""),
                        parsed.get("library_source") or s.get("LibrarySource", ""),
                        parsed.get("library_layout") or s.get("LibraryLayout", ""),
                        parsed.get("platform") or s.get("Platform", ""),
                        parsed.get("total_bases") or (str(s.get("bases", "")) if s.get("bases") else None),
                        parsed.get("total_spots") or (str(s.get("spots", "")) if s.get("spots") else None),
                        s.get("createdate", "") or s.get("CreateDate", "") or s.get("run_date", ""),
                        _extract_geo_from_sra(expxml),
                        json.dumps(matched) if matched else None,
                        json.dumps(s, ensure_ascii=False),
                    ),
                )
                imported += 1
            except Exception as exc:
                print(f"  [warn] DB insert error for {acc}: {exc}")

        time.sleep(RATE_LIMIT)

    conn.commit()
    return imported


def _parse_sra_xml(expxml: str, runs_xml: str) -> dict[str, str]:
    """Parse key fields from SRA esummary XML strings."""
    out: dict[str, str] = {}
    if expxml:
        try:
            root = ET.fromstring(f"<Root>{expxml}</Root>")
            summary = root.find("Summary")
            if summary is not None:
                title = summary.findtext("Title")
                if title:
                    out["title"] = title
                platform = summary.find("Platform")
                if platform is not None:
                    out["platform"] = platform.text or platform.attrib.get("instrument_model", "")
            study = root.find("Study")
            if study is not None:
                out["bioproject"] = study.attrib.get("acc", "")
            sample = root.find("Sample")
            if sample is not None:
                out["biosample"] = sample.attrib.get("acc", "")
            organism = root.find("Organism")
            if organism is not None:
                out["organism"] = organism.attrib.get("ScientificName", "")
            lib = root.find(".//Library_descriptor")
            if lib is not None:
                out["library_strategy"] = lib.findtext("LIBRARY_STRATEGY") or ""
                out["library_source"] = lib.findtext("LIBRARY_SOURCE") or ""
                layout = lib.find("LIBRARY_LAYOUT")
                if layout is not None and list(layout):
                    out["library_layout"] = list(layout)[0].tag
        except ET.ParseError:
            pass
    if runs_xml:
        try:
            root = ET.fromstring(f"<Root>{runs_xml}</Root>")
            run = root.find("Run")
            if run is not None:
                out["sra_accession"] = run.attrib.get("acc", "")
                out["total_spots"] = run.attrib.get("total_spots", "")
                out["total_bases"] = run.attrib.get("total_bases", "")
        except ET.ParseError:
            pass
    return out


def _get_local_virus_names(conn: sqlite3.Connection) -> dict[str, int]:
    """Get virus names and IDs from local database for matching."""
    names = {}
    rows = conn.execute(
        "SELECT isolate_id, virus_name FROM viral_isolates WHERE virus_name IS NOT NULL"
    ).fetchall()
    for r in rows:
        names[r[1].lower()] = r[0]

    # Also add virus_master canonical names
    rows = conn.execute(
        "SELECT master_id, canonical_name FROM virus_master WHERE canonical_name IS NOT NULL"
    ).fetchall()
    for r in rows:
        names[r[1].lower()] = r[0]

    return names


def _match_virus_names(text: str, local_viruses: dict[str, int]) -> list[str]:
    """Match virus names from text against local database."""
    text_lower = text.lower()
    matched = []
    for vname in local_viruses:
        if len(vname) >= 8 and vname in text_lower:
            matched.append(vname)
    return matched[:10]


def _link_geo_to_local(
    conn: sqlite3.Connection,
    geo_id: int,
    virus_name: str,
    match_type: str,
) -> None:
    """Create link between GEO dataset and local virus isolate."""
    # Find local isolate
    row = conn.execute(
        "SELECT isolate_id FROM viral_isolates WHERE LOWER(virus_name) = LOWER(?) LIMIT 1",
        (virus_name,),
    ).fetchone()
    if row:
        conn.execute(
            """
            INSERT OR IGNORE INTO geo_virus_links
                (geo_dataset_id, local_isolate_id, virus_name, match_type, notes)
            VALUES (?, ?, ?, ?, 'auto-matched by name')
            """,
            (geo_id, row[0], virus_name, match_type),
        )


def _extract_geo_from_sra(expxml: str) -> str | None:
    """Extract linked GEO accession from SRA ExpXml."""
    if not expxml:
        return None
    # Try simple regex for GEO accession in XML
    match = re.search(r'GSE\d+', expxml)
    return match.group(0) if match else None


def register_source(conn: sqlite3.Connection) -> None:
    """Register GEO/SRA in external_sources."""
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
            ("geo", "GEO", "transcriptomics",
             "https://www.ncbi.nlm.nih.gov/geo/",
             "Gene Expression Omnibus - transcriptomics datasets for crustacean virus infections.",
             "api", 85),
            ("sra", "SRA", "transcriptomics",
             "https://www.ncbi.nlm.nih.gov/sra/",
             "Sequence Read Archive - raw sequencing data for crustacean virus studies.",
             "api", 86),
        ],
    )
    conn.commit()


def show_stats(conn: sqlite3.Connection) -> None:
    """Print GEO/SRA integration stats."""
    print("\n=== GEO / SRA Integration Stats ===")
    row = conn.execute("SELECT COUNT(*) FROM geo_datasets").fetchone()
    print(f"  GEO datasets: {row[0]}")
    row = conn.execute("SELECT COUNT(*) FROM sra_runs").fetchone()
    print(f"  SRA runs: {row[0]}")
    row = conn.execute("SELECT COUNT(*) FROM geo_virus_links").fetchone()
    print(f"  Virus links: {row[0]}")

    rows = conn.execute(
        "SELECT gse_accession, title FROM geo_datasets WHERE virus_species_matched IS NOT NULL LIMIT 10"
    ).fetchall()
    print("  Matched datasets:")
    for r in rows:
        print(f"    {r[0]:15s} {r[1][:80] if r[1] else 'N/A'}")


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="Import GEO/SRA transcriptomics metadata")
    parser.add_argument("--dry-run", action="store_true", help="Preview only")
    parser.add_argument("--limit", type=int, default=None, help="Limit datasets per source")
    parser.add_argument("--skip-sra", action="store_true", help="Skip SRA import")
    parser.add_argument("--skip-geo", action="store_true", help="Skip GEO import")
    parser.add_argument("--stats", action="store_true", help="Show stats only")
    args = parser.parse_args()

    conn = sqlite3.connect(str(DB_PATH))
    try:
        create_tables(conn)
        register_source(conn)

        if args.stats:
            show_stats(conn)
            return

        geo_count = 0
        sra_count = 0

        if not args.skip_geo:
            print("\n--- GEO Datasets ---")
            geo_count = search_and_import_geo(conn, dry_run=args.dry_run, limit=args.limit)
            print(f"[geo] Imported {geo_count} datasets")

        if not args.skip_sra:
            print("\n--- SRA Runs ---")
            sra_count = search_and_import_sra(conn, dry_run=args.dry_run, limit=args.limit)
            print(f"[sra] Imported {sra_count} runs")

        print(f"\n[done] GEO/SRA import complete: {geo_count} datasets + {sra_count} runs")
        show_stats(conn)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
