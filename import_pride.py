"""
Import PRIDE / ProteomeXchange proteomics datasets for crustacean virus proteins.

PRIDE (PRoteomics IDEntifications, https://www.ebi.ac.uk/pride/) is the world's
largest mass spectrometry proteomics data repository. ProteomeXchange provides
a common framework for proteomics data submission and discovery.

Strategy:
  1. Query PRIDE API for crustacean virus proteomics datasets
  2. Query ProteomeXchange for additional datasets
  3. Match datasets to local viruses by name/species
  4. Store dataset metadata and links

Usage:
    python import_pride.py                          # full run
    python import_pride.py --dry-run                # preview only
    python import_pride.py --limit 20               # process first N
    python import_pride.py --stats                  # coverage stats
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
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from typing import Any

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "crustacean_virus_core.db"
CACHE_DIR = BASE_DIR / "external_data" / "pride"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

PRIDE_API = "https://www.ebi.ac.uk/pride/ws/archive/v2"
PX_API = "http://proteomecentral.proteomexchange.org/cgi/GetDataset"
RATE_LIMIT = 0.4

SEARCH_TERMS = [
    "shrimp virus",
    "crab virus",
    "crayfish virus",
    "lobster virus",
    "white spot syndrome virus",
    "WSSV",
    "iridovirus crustacean",
    "taura syndrome virus",
    "yellow head virus",
    "penaeus virus",
    "crustacean virome",
]


def create_tables(conn: sqlite3.Connection) -> None:
    """Create proteomics dataset tables."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS pride_datasets (
            pride_id INTEGER PRIMARY KEY AUTOINCREMENT,
            pride_accession TEXT NOT NULL UNIQUE,
            px_accession TEXT,
            title TEXT,
            description TEXT,
            organism TEXT,
            instrument TEXT,
            modification TEXT,
            num_proteins INTEGER,
            num_peptides INTEGER,
            num_psms INTEGER,
            publication_pmid TEXT,
            publication_doi TEXT,
            submission_date TEXT,
            data_protocol TEXT,
            sample_protocol TEXT,
            virus_species_matched TEXT,
            host_species_matched TEXT,
            source_repository TEXT DEFAULT 'PRIDE',
            raw_json TEXT,
            fetched_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS pride_virus_links (
            link_id INTEGER PRIMARY KEY AUTOINCREMENT,
            pride_dataset_id INTEGER,
            local_protein_id INTEGER,
            local_isolate_id INTEGER,
            virus_name TEXT,
            protein_description TEXT,
            match_type TEXT DEFAULT 'organism_match',
            match_confidence TEXT DEFAULT 'medium',
            FOREIGN KEY (pride_dataset_id) REFERENCES pride_datasets(pride_id),
            FOREIGN KEY (local_protein_id) REFERENCES viral_proteins(protein_id),
            FOREIGN KEY (local_isolate_id) REFERENCES viral_isolates(isolate_id)
        );

        CREATE INDEX IF NOT EXISTS idx_pride_acc ON pride_datasets(pride_accession);
        CREATE INDEX IF NOT EXISTS idx_pride_pmid ON pride_datasets(publication_pmid);
    """)
    conn.commit()


def _pride_search(query: str, page_size: int = 100) -> dict | None:
    """Search PRIDE API for datasets."""
    params = urllib.parse.urlencode({
        "query": query,
        "pageSize": page_size,
        "page": 0,
        "show proteinCount": "true",
        "show peptideCount": "true",
    })
    url = f"{PRIDE_API}/search/projects?{params}"
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "crustacean-virus-db-curation/1.0",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode())
    except Exception as exc:
        print(f"  [warn] PRIDE search failed for '{query}': {exc}")
        return None


def _pride_get(accession: str) -> dict | None:
    """Get detailed PRIDE dataset info."""
    url = f"{PRIDE_API}/projects/{accession}"
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "crustacean-virus-db-curation/1.0",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode())
    except Exception as exc:
        print(f"  [warn] PRIDE get {accession} failed: {exc}")
        return None


def search_and_import(
    conn: sqlite3.Connection,
    dry_run: bool = False,
    limit: int | None = None,
) -> int:
    """Search PRIDE for crustacean virus datasets and import."""
    all_accessions: set[str] = set()

    for term in SEARCH_TERMS:
        data = _pride_search(term)
        if not data:
            continue
        results = []
        if isinstance(data, dict):
            results = data.get("_embedded", {}).get("projects", [])
        elif isinstance(data, list):
            results = data
        print(f"  [search] '{term}' -> {len(results)} datasets")
        for r in results:
            if isinstance(r, dict):
                all_accessions.add(r.get("accession", ""))
        time.sleep(RATE_LIMIT)

    if limit:
        all_accessions = set(list(all_accessions)[:limit])

    print(f"[pride] Total unique datasets: {len(all_accessions)}")

    if dry_run:
        for acc in list(all_accessions)[:30]:
            print(f"  [dry-run] {acc}")
        return 0

    local_viruses = _get_local_virus_names(conn)
    imported = 0

    for acc in sorted(all_accessions):
        if not acc:
            continue

        detail = _pride_get(acc)
        if not detail:
            time.sleep(RATE_LIMIT)
            continue

        title = detail.get("title", "")
        description = detail.get("description", "")
        combined_text = (title + " " + description).lower()

        # Match to local viruses
        virus_matched = []
        for vname in local_viruses:
            if vname.lower() in combined_text:
                virus_matched.append(vname)

        try:
            conn.execute(
                """
                INSERT OR IGNORE INTO pride_datasets
                    (pride_accession, px_accession, title, description, organism,
                     instrument, modification, num_proteins, num_peptides, num_psms,
                     publication_pmid, publication_doi, submission_date,
                     data_protocol, sample_protocol, virus_species_matched,
                     source_repository, raw_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'PRIDE', ?)
                """,
                (
                    acc,
                    detail.get("proteomeXchangeAccession", ""),
                    title,
                    description[:5000] if description else "",
                    json.dumps(detail.get("organisms", [])),
                    json.dumps(detail.get("instruments", [])),
                    json.dumps(detail.get("ptmNames", [])),
                    detail.get("identifiedProteinCount"),
                    detail.get("identifiedPeptideCount"),
                    detail.get("identifiedPSMCount"),
                    detail.get("pubmedId", ""),
                    json.dumps(detail.get("references", [])),
                    detail.get("submissionDate", ""),
                    detail.get("dataProcessingProtocol", ""),
                    detail.get("sampleProcessingProtocol", ""),
                    json.dumps(virus_matched) if virus_matched else None,
                    json.dumps(detail, ensure_ascii=False),
                ),
            )
            imported += 1

            # Create virus links
            if virus_matched:
                row = conn.execute(
                    "SELECT pride_id FROM pride_datasets WHERE pride_accession = ?",
                    (acc,),
                ).fetchone()
                if row:
                    for vname in virus_matched[:5]:
                        isolate_row = conn.execute(
                            "SELECT isolate_id FROM viral_isolates WHERE LOWER(virus_name) = LOWER(?) LIMIT 1",
                            (vname,),
                        ).fetchone()
                        if isolate_row:
                            conn.execute(
                                """
                                INSERT OR IGNORE INTO pride_virus_links
                                    (pride_dataset_id, local_isolate_id, virus_name, match_type)
                                VALUES (?, ?, ?, 'organism_match')
                                """,
                                (row[0], isolate_row[0], vname),
                            )
            conn.commit()
        except Exception as exc:
            print(f"  [warn] DB insert error for {acc}: {exc}")

        time.sleep(RATE_LIMIT)

    return imported


def _get_local_virus_names(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT DISTINCT virus_name FROM viral_isolates WHERE virus_name IS NOT NULL AND virus_name != ''"
    ).fetchall()
    return [r[0] for r in rows]


def register_source(conn: sqlite3.Connection) -> None:
    """Register PRIDE in external_sources."""
    conn.execute(
        """
        INSERT INTO external_sources
            (source_key, name, category, base_url, description, update_policy, priority)
        VALUES ('pride', 'PRIDE / ProteomeXchange', 'proteomics',
                'https://www.ebi.ac.uk/pride/',
                'Mass spectrometry proteomics datasets for crustacean virus-host interactions.',
                'api', 87)
        ON CONFLICT(source_key) DO UPDATE SET
            name = excluded.name,
            description = excluded.description,
            priority = excluded.priority,
            updated_at = CURRENT_TIMESTAMP
        """
    )
    conn.commit()


def show_stats(conn: sqlite3.Connection) -> None:
    """Print PRIDE integration stats."""
    print("\n=== PRIDE / ProteomeXchange Stats ===")
    row = conn.execute("SELECT COUNT(*) FROM pride_datasets").fetchone()
    print(f"  Total datasets: {row[0]}")
    row = conn.execute("SELECT COUNT(*) FROM pride_datasets WHERE virus_species_matched IS NOT NULL").fetchone()
    print(f"  Virus-matched datasets: {row[0]}")
    row = conn.execute("SELECT COUNT(*) FROM pride_virus_links").fetchone()
    print(f"  Virus links: {row[0]}")

    rows = conn.execute(
        "SELECT pride_accession, title, num_proteins FROM pride_datasets LIMIT 10"
    ).fetchall()
    print("  Sample datasets:")
    for r in rows:
        print(f"    {r[0]:15s} proteins={r[2] or 0:5d} {r[1][:70] if r[1] else 'N/A'}")


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="Import PRIDE/ProteomeXchange proteomics data")
    parser.add_argument("--dry-run", action="store_true", help="Preview only")
    parser.add_argument("--limit", type=int, default=None, help="Limit datasets")
    parser.add_argument("--stats", action="store_true", help="Show stats only")
    args = parser.parse_args()

    conn = sqlite3.connect(str(DB_PATH))
    try:
        create_tables(conn)
        register_source(conn)

        if args.stats:
            show_stats(conn)
            return

        imported = search_and_import(conn, dry_run=args.dry_run, limit=args.limit)
        print(f"\n[done] PRIDE import complete: {imported} datasets")
        show_stats(conn)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
