"""
Enrich literature coverage from Europe PMC.

Europe PMC (https://europepmc.org/) is a comprehensive biomedical literature
database covering PubMed + additional content including preprints, patents,
agricultural literature, and grey literature.

Compared to PubMed, Europe PMC provides:
  - Additional citation counts and metrics
  - Full-text search across open access articles
  - Grant/funder information
  - Preprint coverage (bioRxiv, medRxiv, Research Square, etc.)
  - ORCID author identifiers
  - Dataset links and data citations

Strategy:
  1. Search Europe PMC for crustacean virus literature not in PubMed
  2. Enrich existing ref_literatures with citation counts, grants, ORCIDs
  3. Search for preprints and add as supplementary literature
  4. Cross-reference with existing PMIDs to fill missing metadata

Usage:
    python enrich_europe_pmc.py                      # full run
    python enrich_europe_pmc.py --dry-run            # preview only
    python enrich_europe_pmc.py --enrich-existing     # enrich existing refs
    python enrich_europe_pmc.py --search-new          # search for new papers
    python enrich_europe_pmc.py --limit 100           # process first N
    python enrich_europe_pmc.py --stats               # coverage stats
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
CACHE_DIR = BASE_DIR / "external_data" / "europe_pmc"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

EPMC_BASE = "https://www.ebi.ac.uk/europepmc/webservices/rest"
RATE_LIMIT = 0.3

CRUSTACEAN_VIRUS_SEARCHES = [
    '(TITLE_ABS:"shrimp virus" OR TITLE_ABS:"crab virus" OR TITLE_ABS:"crayfish virus" OR TITLE_ABS:"lobster virus")',
    '(TITLE_ABS:"white spot syndrome" OR TITLE_ABS:"WSSV" OR TITLE_ABS:"yellow head virus")',
    '(TITLE_ABS:"iridovirus" AND TITLE_ABS:crustacean)',
    '(TITLE_ABS:"taura syndrome" OR TITLE_ABS:"infectious hypodermal" OR TITLE_ABS:"Penaeus" AND TITLE_ABS:virus)',
    '(TITLE_ABS:"crustacean" AND TITLE_ABS:"virome" OR TITLE_ABS:"viral metagenom")',
]


def create_tables(conn: sqlite3.Connection) -> None:
    """Create Europe PMC enrichment tables."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS epmc_literature (
            epmc_id INTEGER PRIMARY KEY AUTOINCREMENT,
            pmid TEXT,
            pmcid TEXT,
            doi TEXT,
            title TEXT,
            authors TEXT,
            author_orcids TEXT,
            journal TEXT,
            year TEXT,
            abstract TEXT,
            source TEXT,
            publication_type TEXT,
            citation_count INTEGER,
            relative_citation_ratio REAL,
            is_open_access INTEGER DEFAULT 0,
            has_full_text INTEGER DEFAULT 0,
            grants_json TEXT,
            data_links_json TEXT,
            mesh_terms TEXT,
            keywords TEXT,
            local_reference_id INTEGER,
            match_status TEXT DEFAULT 'new',
            raw_json TEXT,
            fetched_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (local_reference_id) REFERENCES ref_literatures(reference_id)
        );

        CREATE TABLE IF NOT EXISTS epmc_preprints (
            preprint_id INTEGER PRIMARY KEY AUTOINCREMENT,
            epmc_id INTEGER,
            title TEXT,
            authors TEXT,
            source TEXT,
            doi TEXT,
            posted_date TEXT,
            abstract TEXT,
            server TEXT,
            pmid TEXT,
            local_virus_names TEXT,
            raw_json TEXT,
            fetched_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (epmc_id) REFERENCES epmc_literature(epmc_id)
        );

        CREATE INDEX IF NOT EXISTS idx_epmc_pmid ON epmc_literature(pmid);
        CREATE INDEX IF NOT EXISTS idx_epmc_doi ON epmc_literature(doi);
        CREATE INDEX IF NOT EXISTS idx_epmc_ref ON epmc_literature(local_reference_id);
    """)
    conn.commit()


def _epmc_search(query: str, result_type: str = "core", page_size: int = 100, cursor_mark: str = "*") -> dict | None:
    """Search Europe PMC REST API."""
    params = urllib.parse.urlencode({
        "query": query,
        "resultType": result_type,
        "pageSize": page_size,
        "cursorMark": cursor_mark,
        "format": "json",
    })
    url = f"{EPMC_BASE}/search?{params}"
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "crustacean-virus-db-curation/1.0"},
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read().decode())
    except Exception as exc:
        print(f"  [warn] EPMC search failed: {exc}")
        return None


def _epmc_get_by_id(pmid: str) -> dict | None:
    """Get single article by PMID from Europe PMC."""
    params = urllib.parse.urlencode({
        "query": f"ext_id:{pmid}",
        "resultType": "core",
        "pageSize": 1,
        "format": "json",
    })
    url = f"{EPMC_BASE}/search?{params}"
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "crustacean-virus-db-curation/1.0"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode())
            results = data.get("resultList", {}).get("result", [])
            return results[0] if results else None
    except Exception as exc:
        print(f"  [warn] EPMC get {pmid} failed: {exc}")
        return None


def search_new_literature(conn: sqlite3.Connection, dry_run: bool = False) -> int:
    """Search Europe PMC for crustacean virus literature."""
    imported = 0
    existing_pmids = _get_existing_pmids(conn)
    existing_dois = _get_existing_dois(conn)

    for search_term in CRUSTACEAN_VIRUS_SEARCHES:
        print(f"  [search] {search_term[:80]}...")
        data = _epmc_search(search_term, page_size=100)

        if not data:
            continue

        results = data.get("resultList", {}).get("result", [])
        print(f"    Found {data.get('hitCount', len(results))} results")

        for article in results:
            pmid = article.get("pmid", "")
            doi = article.get("doi", "")

            # Skip if already in database
            if pmid in existing_pmids or (doi and doi in existing_dois):
                continue

            if dry_run:
                print(f"    [dry-run] {article.get('title', 'N/A')[:80]}")
                continue

            grants = []
            for g in article.get("grantsList", {}).get("grant", []):
                grants.append({
                    "agency": g.get("agency", ""),
                    "grantId": g.get("grantId", ""),
                })

            try:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO epmc_literature
                        (pmid, pmcid, doi, title, authors, author_orcids, journal, year,
                         abstract, source, publication_type, citation_count,
                         relative_citation_ratio, is_open_access, has_full_text,
                         grants_json, mesh_terms, keywords, match_status, raw_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'new', ?)
                    """,
                    (
                        pmid if pmid else None,
                        article.get("pmcid"),
                        doi if doi else None,
                        article.get("title", ""),
                        article.get("authorString", ""),
                        json.dumps(article.get("authorList", {}).get("author", [])),
                        article.get("journalTitle", ""),
                        article.get("pubYear", ""),
                        article.get("abstractText", ""),
                        article.get("source", ""),
                        article.get("pubTypeList", {}).get("pubType", ""),
                        article.get("citedByCount"),
                        article.get("relativeCitationRatio"),
                        1 if article.get("isOpenAccess") == "Y" else 0,
                        1 if article.get("hasFullText") == "Y" else 0,
                        json.dumps(grants),
                        json.dumps(article.get("meshHeadingList", {}).get("meshHeading", [])),
                        article.get("keywordList", {}).get("keyword", ""),
                        json.dumps(article, ensure_ascii=False),
                    ),
                )
                imported += 1
            except Exception:
                pass

        time.sleep(RATE_LIMIT)

    conn.commit()
    return imported


def enrich_existing_references(
    conn: sqlite3.Connection,
    dry_run: bool = False,
    limit: int | None = None,
) -> int:
    """Enrich existing ref_literatures with Europe PMC data."""
    limit_clause = f"LIMIT {limit}" if limit else ""
    rows = conn.execute(
        f"""
        SELECT r.reference_id, r.pmid, r.doi, r.title
        FROM ref_literatures r
        LEFT JOIN epmc_literature e ON r.reference_id = e.local_reference_id
        WHERE e.epmc_id IS NULL
          AND (r.pmid IS NOT NULL AND r.pmid != '')
        {limit_clause}
        """
    ).fetchall()

    print(f"[epmc] {len(rows)} references to enrich")

    enriched = 0
    for ref_id, pmid, doi, title in rows:
        if dry_run:
            print(f"  [dry-run] PMID={pmid}")
            continue

        article = _epmc_get_by_id(pmid)
        if not article:
            time.sleep(RATE_LIMIT)
            continue

        grants = []
        for g in article.get("grantsList", {}).get("grant", []):
            grants.append({
                "agency": g.get("agency", ""),
                "grantId": g.get("grantId", ""),
            })

        try:
            conn.execute(
                """
                INSERT OR REPLACE INTO epmc_literature
                    (pmid, pmcid, doi, title, authors, author_orcids, journal, year,
                     abstract, source, publication_type, citation_count,
                     relative_citation_ratio, is_open_access, has_full_text,
                     grants_json, mesh_terms, keywords, local_reference_id, match_status, raw_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'enriched', ?)
                """,
                (
                    pmid,
                    article.get("pmcid"),
                    doi,
                    article.get("title", ""),
                    article.get("authorString", ""),
                    json.dumps(article.get("authorList", {}).get("author", [])),
                    article.get("journalTitle", ""),
                    article.get("pubYear", ""),
                    article.get("abstractText", ""),
                    article.get("source", ""),
                    article.get("pubTypeList", {}).get("pubType", ""),
                    article.get("citedByCount"),
                    article.get("relativeCitationRatio"),
                    1 if article.get("isOpenAccess") == "Y" else 0,
                    1 if article.get("hasFullText") == "Y" else 0,
                    json.dumps(grants),
                    json.dumps(article.get("meshHeadingList", {}).get("meshHeading", [])),
                    article.get("keywordList", {}).get("keyword", ""),
                    ref_id,
                    json.dumps(article, ensure_ascii=False),
                ),
            )
            enriched += 1
        except Exception:
            pass

        time.sleep(RATE_LIMIT)

    conn.commit()
    return enriched


def search_preprints(conn: sqlite3.Connection, dry_run: bool = False) -> int:
    """Search for crustacean virus preprints on bioRxiv/medRxiv via Europe PMC."""
    imported = 0
    search_terms = [
        '(TITLE_ABS:"shrimp virus" OR TITLE_ABS:"crab virus" OR TITLE_ABS:"crayfish virus") AND (SRC:PPR OR SRC:MED)',
        '(TITLE_ABS:"white spot syndrome" OR TITLE_ABS:"WSSV") AND (SRC:PPR OR SRC:MED)',
        '(TITLE_ABS:"iridovirus" AND TITLE_ABS:crustacean) AND (SRC:PPR OR SRC:MED)',
    ]

    for term in search_terms:
        print(f"  [preprint search] {term[:80]}...")
        data = _epmc_search(term, page_size=100)

        if not data:
            continue

        results = data.get("resultList", {}).get("result", [])
        print(f"    Found {data.get('hitCount', len(results))} results")

        for article in results:
            if dry_run:
                print(f"    [dry-run] {article.get('title', 'N/A')[:80]}")
                continue

            # Match to local viruses
            text = (article.get("title", "") + " " + article.get("abstractText", ""))
            matched = _match_local_viruses(conn, text)

            try:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO epmc_preprints
                        (title, authors, source, doi, posted_date, abstract, server, pmid, local_virus_names, raw_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        article.get("title", ""),
                        article.get("authorString", ""),
                        article.get("source", ""),
                        article.get("doi", ""),
                        article.get("firstPublicationDate", ""),
                        article.get("abstractText", ""),
                        article.get("bookOrReportDetails", {}).get("publisher", "")
                        if article.get("bookOrReportDetails") else None,
                        article.get("pmid"),
                        json.dumps(matched) if matched else None,
                        json.dumps(article, ensure_ascii=False),
                    ),
                )
                imported += 1
            except Exception:
                pass

        time.sleep(RATE_LIMIT)

    conn.commit()
    return imported


def _get_existing_pmids(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("SELECT pmid FROM ref_literatures WHERE pmid IS NOT NULL AND pmid != ''").fetchall()
    return {r[0].strip() for r in rows}


def _get_existing_dois(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("SELECT doi FROM ref_literatures WHERE doi IS NOT NULL AND doi != ''").fetchall()
    return {r[0].strip() for r in rows}


def _match_local_viruses(conn: sqlite3.Connection, text: str) -> list[str]:
    """Match virus names from text against local database."""
    text_lower = text.lower()
    rows = conn.execute(
        "SELECT DISTINCT virus_name FROM viral_isolates WHERE virus_name IS NOT NULL"
    ).fetchall()
    matched = []
    for r in rows:
        if not r[0]:
            continue
        vname = r[0].lower()
        if vname in text_lower:
            matched.append(vname)
        elif sum(1 for w in vname.split() if len(w) > 4 and w in text_lower) >= 2:
            matched.append(vname)
    return matched[:10]


def register_source(conn: sqlite3.Connection) -> None:
    """Register Europe PMC in external_sources."""
    conn.execute(
        """
        INSERT INTO external_sources
            (source_key, name, category, base_url, description, update_policy, priority)
        VALUES ('europe_pmc', 'Europe PMC', 'literature_index',
                'https://europepmc.org/',
                'Comprehensive biomedical literature including PubMed, preprints, grants, and citation metrics.',
                'api', 56)
        ON CONFLICT(source_key) DO UPDATE SET
            name = excluded.name,
            description = excluded.description,
            priority = excluded.priority,
            updated_at = CURRENT_TIMESTAMP
        """
    )
    conn.commit()


def show_stats(conn: sqlite3.Connection) -> None:
    """Print Europe PMC enrichment stats."""
    print("\n=== Europe PMC Integration Stats ===")
    row = conn.execute("SELECT COUNT(*) FROM epmc_literature").fetchone()
    print(f"  Literature records: {row[0]}")
    row = conn.execute("SELECT COUNT(*) FROM epmc_literature WHERE match_status = 'enriched'").fetchone()
    print(f"  Enriched from existing: {row[0]}")
    row = conn.execute("SELECT COUNT(*) FROM epmc_literature WHERE match_status = 'new'").fetchone()
    print(f"  New discoveries: {row[0]}")
    row = conn.execute("SELECT COUNT(*) FROM epmc_preprints").fetchone()
    print(f"  Preprints found: {row[0]}")

    rows = conn.execute(
        "SELECT title, citation_count FROM epmc_literature "
        "WHERE citation_count IS NOT NULL ORDER BY citation_count DESC LIMIT 10"
    ).fetchall()
    print("  Top cited papers:")
    for r in rows:
        print(f"    [{r[1]:4d}] {r[0][:80] if r[0] else 'N/A'}")


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="Enrich from Europe PMC")
    parser.add_argument("--dry-run", action="store_true", help="Preview only")
    parser.add_argument("--enrich-existing", action="store_true", help="Enrich existing ref_literatures")
    parser.add_argument("--search-new", action="store_true", help="Search for new literature")
    parser.add_argument("--search-preprints", action="store_true", help="Search for preprints")
    parser.add_argument("--all", action="store_true", help="Run all EPMC operations")
    parser.add_argument("--limit", type=int, default=None, help="Limit to N references")
    parser.add_argument("--stats", action="store_true", help="Show stats only")
    args = parser.parse_args()

    # Default: run all if no specific flag
    if not any([args.enrich_existing, args.search_new, args.search_preprints, args.stats]):
        args.all = True

    conn = sqlite3.connect(str(DB_PATH))
    try:
        create_tables(conn)
        register_source(conn)

        if args.stats:
            show_stats(conn)
            return

        total = 0

        if args.all or args.enrich_existing:
            print("\n--- Enrich Existing References ---")
            n = enrich_existing_references(conn, dry_run=args.dry_run, limit=args.limit)
            print(f"  Enriched: {n}")
            total += n

        if args.all or args.search_new:
            print("\n--- Search New Literature ---")
            n = search_new_literature(conn, dry_run=args.dry_run)
            print(f"  New: {n}")
            total += n

        if args.all or args.search_preprints:
            print("\n--- Search Preprints ---")
            n = search_preprints(conn, dry_run=args.dry_run)
            print(f"  Preprints: {n}")
            total += n

        print(f"\n[done] Europe PMC enrichment complete: {total} total records")
        show_stats(conn)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
