"""
Import preprint metadata from bioRxiv and medRxiv APIs directly.

bioRxiv (https://www.biorxiv.org/) and medRxiv are the primary preprint servers
for biology and medical sciences. Using their Content API, we can find the latest
crustacean virus research before it reaches PubMed.

This complements the Europe PMC preprint search with direct API access for
better coverage and structured metadata (version history, field categories).

bioRxiv Content API: https://api.biorxiv.org/details/biorxiv/10.1101/...
bioRxiv Search: https://api.biorxiv.org/details/biorxiv/<DOI>

Usage:
    python import_biorxiv.py                        # full run
    python import_biorxiv.py --dry-run              # preview only
    python import_biorxiv.py --search               # keyword search
    python import_biorxiv.py --date-range 2024-01-01/2025-12-31
    python import_biorxiv.py --stats                # coverage stats
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
CACHE_DIR = BASE_DIR / "external_data" / "biorxiv"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

BIORXIV_API = "https://api.biorxiv.org"
MEDRXIV_API = "https://api.medrxiv.org"

CRUSTACEAN_VIRUS_TERMS = [
    "shrimp virus", "crab virus", "crayfish virus", "lobster virus",
    "white spot syndrome virus", "WSSV", "iridovirus", "taura syndrome virus",
    "yellow head virus", "Penaeus vannamei virus", "crustacean virome",
    "Macrobrachium virus", "Cherax virus", "Procambarus virus",
    "infectious hypodermal", "hepatopancreatic parvovirus",
    "shrimp immunity virus", "viral shrimp disease",
]

RATE_LIMIT = 0.3


def create_tables(conn: sqlite3.Connection) -> None:
    """Create preprint tables (separate from EPMC preprints)."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS biorxiv_preprints (
            preprint_id INTEGER PRIMARY KEY AUTOINCREMENT,
            doi TEXT NOT NULL UNIQUE,
            title TEXT,
            authors TEXT,
            author_corresponding TEXT,
            author_corresponding_institution TEXT,
            abstract TEXT,
            date_posted TEXT,
            date_revised TEXT,
            server TEXT,
            category TEXT,
            collection TEXT,
            version INTEGER,
            published_doi TEXT,
            published_journal TEXT,
            match_status TEXT DEFAULT 'pending_review',
            local_virus_names TEXT,
            local_host_names TEXT,
            relevant INTEGER DEFAULT 1,
            raw_json TEXT,
            fetched_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE INDEX IF NOT EXISTS idx_biorxiv_doi ON biorxiv_preprints(doi);
        CREATE INDEX IF NOT EXISTS idx_biorxiv_date ON biorxiv_preprints(date_posted);
        CREATE INDEX IF NOT EXISTS idx_biorxiv_server ON biorxiv_preprints(server);
    """)
    conn.commit()


def fetch_preprint_by_doi(doi: str, server: str = "biorxiv") -> dict | None:
    """Fetch single preprint by DOI from bioRxiv/medRxiv API."""
    api_base = BIORXIV_API if server == "biorxiv" else MEDRXIV_API
    url = f"{api_base}/details/{server}/{doi}"
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "crustacean-virus-db-curation/1.0"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode())
            collection = data.get("collection", [])
            return collection[0] if collection else None
    except Exception:
        return None


def search_crossref_preprints(search_terms: list[str], max_results: int = 50) -> list[dict]:
    """Search for preprints via Crossref API (which indexes bioRxiv/medRxiv)."""
    all_results = []
    for term in search_terms:
        params = urllib.parse.urlencode({
            "query": term,
            "filter": "type:posted-content",
            "rows": min(max_results, 50),
            "sort": "relevance",
        })
        url = f"https://api.crossref.org/works?{params}"
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "crustacean-virus-db-curation/1.0"},
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = json.loads(resp.read().decode())
            items = data.get("message", {}).get("items", [])
            all_results.extend(items)
            print(f"  [search] '{term}' -> {len(items)} preprints via Crossref")
        except Exception as exc:
            print(f"  [warn] Crossref search failed for '{term}': {exc}")
        time.sleep(RATE_LIMIT)

    # Deduplicate by DOI
    seen = set()
    unique = []
    for item in all_results:
        doi = item.get("DOI", "")
        if doi not in seen:
            seen.add(doi)
            unique.append(item)
    return unique


def parse_crossref_preprint(item: dict) -> dict[str, Any]:
    """Parse a Crossref posted-content item into a preprint dict."""
    def scalar_text(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, list):
            return "; ".join(str(v) for v in value if v is not None)
        return str(value)

    title = ""
    titles = item.get("title", [])
    if titles:
        title = titles[0]

    authors = []
    author_list = item.get("author", [])
    for a in author_list:
        name = f"{a.get('given', '')} {a.get('family', '')}".strip()
        if name:
            authors.append(name)

    # Determine server
    publisher = item.get("publisher", "").lower()
    server = ""
    if "biorxiv" in publisher or "bioRxiv" in publisher:
        server = "biorxiv"
    elif "medrxiv" in publisher or "medRxiv" in publisher:
        server = "medrxiv"

    abstract = item.get("abstract", "")
    # Strip HTML/XML tags from abstract
    import re
    abstract = re.sub(r'<[^>]+>', '', abstract) if abstract else ""

    posted_date = ""
    date_parts = item.get("posted", {}).get("date-parts", [[]])
    if date_parts and date_parts[0]:
        parts = date_parts[0]
        try:
            y = parts[0] if len(parts) > 0 else 1
            m = str(parts[1]).zfill(2) if len(parts) > 1 and parts[1] else "01"
            d = str(parts[2]).zfill(2) if len(parts) > 2 and parts[2] else "01"
            posted_date = f"{y}-{m}-{d}"
        except (IndexError, TypeError):
            posted_date = str(parts[0]) if parts else ""

    return {
        "doi": item.get("DOI", ""),
        "title": title,
        "authors": "; ".join(authors[:20]),
        "author_corresponding": authors[0] if authors else "",
        "abstract": abstract[:5000] if abstract else "",
        "date_posted": posted_date,
        "server": server or "unknown",
        "category": scalar_text(item.get("group-title", "")),
        "collection": scalar_text(item.get("subtitle", "")),
        "version": 1,
        "published_doi": "",
        "published_journal": "",
    }


def search_and_import(
    conn: sqlite3.Connection,
    dry_run: bool = False,
    max_per_term: int = 50,
) -> int:
    """Search Crossref for preprints and import to database."""
    preprints = search_crossref_preprints(CRUSTACEAN_VIRUS_TERMS, max_per_term)
    print(f"[biorxiv] Total unique preprints found: {len(preprints)}")

    if dry_run:
        for pp in preprints[:30]:
            parsed = parse_crossref_preprint(pp)
            print(f"  [dry-run] {parsed['server']:10s} {parsed['date_posted']} {parsed['title'][:80]}")
        return 0

    local_viruses = _get_local_names(conn, "virus")
    local_hosts = _get_local_names(conn, "host")

    imported = 0
    for item in preprints:
        parsed = parse_crossref_preprint(item)
        doi = parsed["doi"]
        if not doi:
            continue

        # Check relevance: does the text mention local viruses?
        text = (parsed["title"] + " " + parsed["abstract"]).lower()
        matched_viruses = [v for v in local_viruses if v.lower() in text]
        matched_hosts = [h for h in local_hosts if h.lower() in text]

        # If no matches, still import but mark as lower relevance
        relevant = 1 if (matched_viruses or matched_hosts) else 0

        try:
            conn.execute(
                """
                INSERT OR IGNORE INTO biorxiv_preprints
                    (doi, title, authors, author_corresponding, abstract,
                     date_posted, server, category, collection, version,
                     match_status, local_virus_names, local_host_names, relevant, raw_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending_review', ?, ?, ?, ?)
                """,
                (
                    doi,
                    parsed["title"],
                    parsed["authors"],
                    parsed["author_corresponding"],
                    parsed["abstract"],
                    parsed["date_posted"],
                    parsed["server"],
                    parsed["category"],
                    parsed["collection"],
                    parsed["version"],
                    json.dumps(matched_viruses) if matched_viruses else None,
                    json.dumps(matched_hosts) if matched_hosts else None,
                    relevant,
                    json.dumps(item, ensure_ascii=False),
                ),
            )
            imported += 1
        except Exception as exc:
            print(f"  [warn] DB error for {doi}: {exc}")

    conn.commit()
    return imported


def _get_local_names(conn: sqlite3.Connection, name_type: str) -> list[str]:
    """Get local virus or host names."""
    if name_type == "virus":
        rows = conn.execute(
            "SELECT DISTINCT virus_name FROM viral_isolates WHERE virus_name IS NOT NULL AND virus_name != ''"
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT DISTINCT scientific_name FROM crustacean_hosts WHERE scientific_name IS NOT NULL AND scientific_name != ''"
        ).fetchall()
    return [r[0] for r in rows]


def register_source(conn: sqlite3.Connection) -> None:
    """Register bioRxiv/medRxiv in external_sources."""
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
            ("biorxiv", "bioRxiv", "preprint",
             "https://www.biorxiv.org/",
             "Preprints in biology, including crustacean virology and aquaculture health.",
             "api", 53),
            ("medrxiv", "medRxiv", "preprint",
             "https://www.medrxiv.org/",
             "Preprints in medical sciences with crustacean virus relevance.",
             "api", 54),
        ],
    )
    conn.commit()


def show_stats(conn: sqlite3.Connection) -> None:
    """Print bioRxiv integration stats."""
    print("\n=== bioRxiv / medRxiv Stats ===")
    row = conn.execute("SELECT COUNT(*) FROM biorxiv_preprints").fetchone()
    print(f"  Total preprints: {row[0]}")
    row = conn.execute("SELECT COUNT(*) FROM biorxiv_preprints WHERE relevant = 1").fetchone()
    print(f"  Relevant (virus/host matched): {row[0]}")
    row = conn.execute("SELECT server, COUNT(*) FROM biorxiv_preprints GROUP BY server").fetchall()
    print("  By server:")
    for r in row:
        print(f"    {r[0]:15s} {r[1]}")
    rows = conn.execute(
        "SELECT doi, title, date_posted FROM biorxiv_preprints WHERE relevant = 1 ORDER BY date_posted DESC LIMIT 10"
    ).fetchall()
    print("  Recent relevant preprints:")
    for r in rows:
        print(f"    [{r[2] or 'N/A'}] {r[0]:30s} {r[1][:70] if r[1] else 'N/A'}")


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="Import bioRxiv/medRxiv preprints")
    parser.add_argument("--dry-run", action="store_true", help="Preview only")
    parser.add_argument("--max-per-term", type=int, default=50, help="Max results per search term")
    parser.add_argument("--stats", action="store_true", help="Show stats only")
    args = parser.parse_args()

    conn = sqlite3.connect(str(DB_PATH))
    try:
        create_tables(conn)
        register_source(conn)

        if args.stats:
            show_stats(conn)
            return

        imported = search_and_import(conn, dry_run=args.dry_run, max_per_term=args.max_per_term)
        print(f"\n[done] bioRxiv/medRxiv import complete: {imported} preprints")
        show_stats(conn)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
