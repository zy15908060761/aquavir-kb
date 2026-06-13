"""
Fetch literature metadata for isolates missing references.

Strategy:
  1. Query isolate_curated_profiles where discovery_reference_id is NULL
  2. Search Crossref by accession number (most papers mention accession in abstract)
  3. Fallback: search Crossref by canonical virus name
  4. Fallback: search PubMed E-utilities by accession
  5. Store hits in ref_literatures, link via isolate_reference_links
  6. Update isolate_curated_profiles discovery_reference_id where confident

Usage:
    python fetch_openex_literature.py                  # full run
    python fetch_openex_literature.py --limit 50       # first 50 only
    python fetch_openex_literature.py --dry-run        # preview only

Sources:
    - Crossref API (free, no API key needed for basic search)
    - PubMed E-utilities (free, NCBI API)
"""

from __future__ import annotations

import json
import re
import shutil
import sqlite3
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "crustacean_virus_core.db"
BACKUP_DIR = BASE_DIR / "backups"
DOWNLOADS_DIR = BASE_DIR / "downloads"

CROSSREF_BASE = "https://api.crossref.org/works"
PUBCHEM_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
REQUEST_DELAY = 0.5  # Polite delay for both APIs
MAX_RETRIES = 3

CONTACT_EMAIL = "curator@crustacean-virus-db.org"


@dataclass
class LitHit:
    doi: str | None
    title: str
    authors: str
    journal: str
    year: str
    pmid: str | None
    source: str  # 'crossref' or 'pubmed'
    relevance: float


# ── helpers ──────────────────────────────────────────────────────────


def backup_database() -> Path:
    BACKUP_DIR.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = BACKUP_DIR / f"crustacean_virus_core_before_literature_{stamp}.db"
    shutil.copy2(DB_PATH, backup_path)
    return backup_path


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        PRAGMA foreign_keys = ON;
        CREATE TABLE IF NOT EXISTS literature_search_log (
            log_id INTEGER PRIMARY KEY AUTOINCREMENT,
            search_source TEXT NOT NULL,
            search_query TEXT NOT NULL,
            hit_count INTEGER DEFAULT 0,
            top_doi TEXT,
            searched_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        """
    )


def source_id(conn: sqlite3.Connection, key: str) -> int | None:
    row = conn.execute(
        "SELECT source_id FROM external_sources WHERE source_key = ?", (key,)
    ).fetchone()
    return row["source_id"] if row else None


def extract_year(date_str: str | None) -> str:
    if not date_str:
        return ""
    return date_str[:4] if len(date_str) >= 4 and date_str[:4].isdigit() else ""


def normalize_text(value: str | None) -> str:
    text = (value or "").lower().strip()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


# ── Crossref API ─────────────────────────────────────────────────────


def _crossref_headers() -> dict[str, str]:
    return {"User-Agent": f"crustacean-virus-db-curation/1.0 (mailto:{CONTACT_EMAIL})"}


def crossref_search(query: str, rows: int = 5) -> list[LitHit]:
    """Search Crossref Works API."""
    params = {
        "query": query,
        "rows": str(rows),
        "sort": "relevance",
        "order": "desc",
        "mailto": CONTACT_EMAIL,
    }
    full_url = f"{CROSSREF_BASE}?{urllib.parse.urlencode(params)}"
    for attempt in range(MAX_RETRIES):
        try:
            req = urllib.request.Request(full_url, headers=_crossref_headers())
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception as exc:
            if attempt < MAX_RETRIES - 1:
                time.sleep(2 * (attempt + 1))
                continue
            print(f"    [warn] Crossref search failed: {exc}")
            return []

    hits: list[LitHit] = []
    items = (data or {}).get("message", {}).get("items", [])
    for item in items:
        doi = (item.get("DOI") or "").strip() or None
        title_list = item.get("title", []) or []
        title = str(title_list[0]).rstrip(".") if title_list else ""
        authors_list = item.get("author", []) or []
        authors = "; ".join(
            f"{a.get('given', '')} {a.get('family', '')}".strip()
            for a in authors_list if a.get('family')
        )
        journal_info = item.get("container-title", []) or []
        journal = str(journal_info[0]) if journal_info else ""
        date_parts = item.get("published-print", {}).get("date-parts", [[]])[0] or \
                     item.get("published-online", {}).get("date-parts", [[]])[0] or []
        year = str(date_parts[0]) if date_parts else extract_year(
            item.get("deposited", {}).get("date-time", "")
        )

        hits.append(LitHit(
            doi=doi,
            title=title,
            authors=authors,
            journal=journal,
            year=year,
            pmid=None,
            source="crossref",
            relevance=float(item.get("score", 0) or 0),
        ))
    return hits


# ── PubMed E-utilities (fallback) ────────────────────────────────────


def pubmed_search(query: str, retmax: int = 5) -> list[LitHit]:
    """Search PubMed via E-utilities esearch + esummary."""
    search_params = urllib.parse.urlencode({
        "db": "pubmed",
        "term": query,
        "retmax": str(retmax),
        "retmode": "json",
        "tool": "crustacean_virus_db",
        "email": CONTACT_EMAIL,
    })
    search_url = f"{PUBCHEM_BASE}/esearch.fcgi?{search_params}"
    for attempt in range(MAX_RETRIES):
        try:
            req = urllib.request.Request(
                search_url,
                headers={"User-Agent": "crustacean-virus-db-curation/1.0"},
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                search_data = json.loads(resp.read().decode("utf-8"))
        except Exception as exc:
            if attempt < MAX_RETRIES - 1:
                time.sleep(2 * (attempt + 1))
                continue
            return []

    id_list = (search_data or {}).get("esearchresult", {}).get("idlist", [])
    if not id_list:
        return []

    # Fetch summaries
    summary_params = urllib.parse.urlencode({
        "db": "pubmed",
        "id": ",".join(id_list),
        "retmode": "json",
        "tool": "crustacean_virus_db",
        "email": CONTACT_EMAIL,
    })
    summary_url = f"{PUBCHEM_BASE}/esummary.fcgi?{summary_params}"
    for attempt in range(MAX_RETRIES):
        try:
            req = urllib.request.Request(
                summary_url,
                headers={"User-Agent": "crustacean-virus-db-curation/1.0"},
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                summary_data = json.loads(resp.read().decode("utf-8"))
            break
        except Exception as exc:
            if attempt < MAX_RETRIES - 1:
                time.sleep(2 * (attempt + 1))
                continue
            return []

    result_map = (summary_data or {}).get("result", {})
    hits: list[LitHit] = []
    for pmid in id_list:
        item = result_map.get(pmid) or {}
        title = str(item.get("title", "")).strip().rstrip(".")
        journal = str(item.get("fulljournalname") or item.get("source") or "").strip()
        year = extract_year(item.get("pubdate", ""))
        doi = ""
        for aid in item.get("articleids", []) or []:
            if str(aid.get("idtype", "")).lower() == "doi":
                doi = str(aid.get("value", "")).strip()
        authors_list = item.get("authors", []) or []
        authors = "; ".join(
            str(a.get("name", "")).strip() for a in authors_list if a.get("name")
        )
        hits.append(LitHit(
            doi=doi or None,
            title=title,
            authors=authors,
            journal=journal,
            year=year,
            pmid=pmid,
            source="pubmed",
            relevance=1.0,
        ))
    return hits


# ── matching ─────────────────────────────────────────────────────────


def filter_relevant(
    hits: list[LitHit], accession: str, virus_name: str,
    accession_search: bool = False
) -> list[LitHit]:
    """Filter hits to only those that genuinely match this isolate."""
    title_norm_base = normalize_text(accession)
    virus_norm = normalize_text(virus_name)

    scored: list[tuple[float, LitHit]] = []
    for h in hits:
        title_norm = normalize_text(h.title)
        journal_norm = normalize_text(h.journal)

        # Reject generic reference/compendium/review/database entries
        # Check both title and journal for these markers
        combined_text = f"{title_norm} {journal_norm}"
        if any(kw in combined_text for kw in ["compendium", "profile", "overview", "fact sheet",
                                               "data sheet", "cabi", "invasive species",
                                               "peer review"]):
            continue

        # PubMed accession search already verified accession is in record metadata
        if accession_search and h.source == "pubmed":
            scored.append((0.9, h))
            continue

        # Accession appears in title — strongest signal
        if title_norm_base and title_norm_base in title_norm:
            scored.append((1.0, h))
            continue

        # Virus name in title — good signal
        if virus_norm and virus_norm in title_norm:
            # Demote very generic titles (1–2 short words that could match many viruses)
            word_count = len(title_norm.split())
            if word_count <= 4:
                continue
            # Prefer PubMed (peer-reviewed) over Crossref (can include book chapters, etc.)
            score = 0.85 if h.source == "pubmed" else 0.80
            scored.append((score, h))
            continue

    scored.sort(key=lambda x: -x[0])
    return [h for _, h in scored if _ >= 0.8]


# ── database operations ──────────────────────────────────────────────


def pending_profiles(conn: sqlite3.Connection, limit: int | None) -> list[sqlite3.Row]:
    query = """
        SELECT p.isolate_id, p.accession, p.canonical_virus_name,
               p.primary_reference_id, p.discovery_reference_id
        FROM isolate_curated_profiles p
        WHERE p.discovery_reference_id IS NULL
           OR p.primary_reference_id IS NULL
        ORDER BY
          CASE WHEN p.primary_reference_id IS NULL THEN 0 ELSE 1 END,
          p.isolate_id
    """
    if limit:
        query += f" LIMIT {limit}"
    return conn.execute(query).fetchall()


def insert_reference(conn: sqlite3.Connection, hit: LitHit) -> int | None:
    """Insert into ref_literatures if DOI/title not already present."""
    if hit.doi:
        existing = conn.execute(
            "SELECT reference_id FROM ref_literatures WHERE doi = ?", (hit.doi,)
        ).fetchone()
        if existing:
            return existing["reference_id"]
    existing = conn.execute(
        "SELECT reference_id FROM ref_literatures WHERE title = ? AND year = ?",
        (hit.title, hit.year),
    ).fetchone()
    if existing:
        return existing["reference_id"]

    conn.execute(
        """
        INSERT INTO ref_literatures
            (pmid, title, authors, journal, year, doi, abstract, keywords)
        VALUES (?, ?, ?, ?, ?, ?, NULL, NULL)
        """,
        (hit.pmid, hit.title, hit.authors, hit.journal, hit.year, hit.doi),
    )
    return conn.execute("SELECT last_insert_rowid()").fetchone()[0]


def add_reference_link(
    conn: sqlite3.Connection, isolate_id: int, reference_id: int,
    link_type: str = "initial_discovery", notes: str = "",
) -> None:
    conn.execute(
        """
        INSERT OR IGNORE INTO isolate_reference_links
            (isolate_id, reference_id, link_type, source_table, source_field,
             priority, evidence_status, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (isolate_id, reference_id, link_type, "lit_search",
         "discovery_reference_id", 20, "auto_seeded",
         notes or "Recovered from literature API search."),
    )


def update_profile_reference(
    conn: sqlite3.Connection, isolate_id: int, reference_id: int, field: str
) -> None:
    if field == "discovery_reference_id":
        conn.execute(
            """
            UPDATE isolate_curated_profiles
            SET discovery_reference_id = ?,
                metadata_source_priority = 'mixed_with_conflicts',
                curation_status = 'auto_seeded',
                updated_at = CURRENT_TIMESTAMP,
                notes = COALESCE(notes || ' | ', '') || ?
            WHERE isolate_id = ? AND discovery_reference_id IS NULL
            """,
            (reference_id, "Discovery reference recovered via literature search.", isolate_id),
        )
    elif field == "primary_reference_id":
        conn.execute(
            """
            UPDATE isolate_curated_profiles
            SET primary_reference_id = ?,
                metadata_source_priority = 'mixed_with_conflicts',
                curation_status = 'auto_seeded',
                updated_at = CURRENT_TIMESTAMP,
                notes = COALESCE(notes || ' | ', '') || ?
            WHERE isolate_id = ? AND primary_reference_id IS NULL
            """,
            (reference_id, "Primary reference recovered via literature search.", isolate_id),
        )


def log_search(conn: sqlite3.Connection, source: str, query: str, hit_count: int, top_doi: str | None) -> None:
    conn.execute(
        """INSERT INTO literature_search_log (search_source, search_query, hit_count, top_doi)
         VALUES (?, ?, ?, ?)""",
        (source, query, hit_count, top_doi),
    )


def mark_review_candidate(conn: sqlite3.Connection, isolate_id: int, field: str, notes: str) -> None:
    conn.execute(
        """
        INSERT OR IGNORE INTO curation_conflicts
            (entity_type, entity_id, isolate_id, field_name,
             value_a, source_a, value_b, source_b,
             conflict_type, severity, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ("reference", isolate_id, isolate_id, field,
         None, "profile", None, "lit_search",
         "missing_in_profile", "medium", notes),
    )


# ── main logic ───────────────────────────────────────────────────────


def run_literature_fetch(conn: sqlite3.Connection, limit: int | None, dry_run: bool) -> dict:
    stats = {
        "profiles_checked": 0,
        "crossref_searched": 0,
        "pubmed_searched": 0,
        "refs_inserted": 0,
        "discovery_links_added": 0,
        "primary_links_added": 0,
        "no_hit": 0,
        "cache_hit": 0,
    }

    # Cache: virus_name -> (reference_id, best_hit) for previously resolved viruses.
    # This avoids redundant API calls when hundreds of isolates share the same virus.
    # A value of None means "already searched, no hit found".
    virus_cache: dict[str, tuple[int, LitHit] | None] = {}

    profiles = pending_profiles(conn, limit)
    stats["profiles_checked"] = len(profiles)

    for idx, profile in enumerate(profiles, start=1):
        isolate_id = profile["isolate_id"]
        accession = profile["accession"]
        virus_name = profile["canonical_virus_name"] or ""

        # Skip if both refs already filled
        if profile["discovery_reference_id"] is not None and profile["primary_reference_id"] is not None:
            continue

        # ── Check virus cache ──
        if virus_name and virus_name not in ("Unknown/Unclassified", "") and virus_name in virus_cache:
            cached = virus_cache[virus_name]
            if cached is None:
                # Previously searched this virus and found no hits
                stats["no_hit"] += 1
                if idx % 500 == 0:
                    print(f"  [progress] {idx}/{len(profiles)} cache={stats['cache_hit']} searched={stats['crossref_searched']+stats['pubmed_searched']} refs={stats['refs_inserted']} no_hit={stats['no_hit']}")
                continue
            cached_ref_id, best = cached
            if not dry_run:
                if profile["discovery_reference_id"] is None:
                    update_profile_reference(conn, isolate_id, cached_ref_id, "discovery_reference_id")
                    add_reference_link(
                        conn, isolate_id, cached_ref_id, "initial_discovery",
                        f"Matched via cache ({best.source}): {accession} -> {best.doi or best.title[:80]}",
                    )
                    stats["discovery_links_added"] += 1
                if profile["primary_reference_id"] is None:
                    update_profile_reference(conn, isolate_id, cached_ref_id, "primary_reference_id")
                    add_reference_link(
                        conn, isolate_id, cached_ref_id, "genbank_reference",
                        f"Also set as primary (cache): {best.doi or best.title[:80]}",
                    )
                    stats["primary_links_added"] += 1
                stats["cache_hit"] += 1
            if idx % 500 == 0:
                print(f"  [progress] {idx}/{len(profiles)} cache={stats['cache_hit']} searched={stats['crossref_searched']+stats['pubmed_searched']} refs={stats['refs_inserted']} no_hit={stats['no_hit']}")
            continue

        # ── Phase 1: PubMed by accession ──
        time.sleep(REQUEST_DELAY)
        pubmed_acc_hits = pubmed_search(accession, retmax=5)
        stats["pubmed_searched"] += 1
        log_search(conn, "pubmed", accession, len(pubmed_acc_hits),
                   pubmed_acc_hits[0].doi if pubmed_acc_hits else None)

        # ── Phase 2: Crossref by virus name ──
        crossref_hits: list[LitHit] = []
        if virus_name and virus_name not in ("Unknown/Unclassified", ""):
            time.sleep(REQUEST_DELAY)
            crossref_hits = crossref_search(f"{virus_name} crustacean", rows=5)
            stats["crossref_searched"] += 1
            log_search(conn, "crossref", f"virus_name:{virus_name}", len(crossref_hits),
                       crossref_hits[0].doi if crossref_hits else None)

        # ── Phase 3: PubMed by virus name (always try) ──
        pubmed_virus_hits: list[LitHit] = []
        if virus_name and virus_name not in ("Unknown/Unclassified", ""):
            time.sleep(REQUEST_DELAY)
            pubmed_virus_hits = pubmed_search(virus_name, retmax=5)
            stats["pubmed_searched"] += 1
            log_search(conn, "pubmed", f"virus_name:{virus_name}", len(pubmed_virus_hits),
                       pubmed_virus_hits[0].doi if pubmed_virus_hits else None)

        # Combine all hits
        all_hits = list(pubmed_acc_hits) + crossref_hits + pubmed_virus_hits

        relevant = filter_relevant(
            all_hits, accession, virus_name,
            accession_search=bool(pubmed_acc_hits),
        )

        if not relevant:
            stats["no_hit"] += 1
            # Mark virus in cache as no_hit so we don't re-search
            if virus_name and virus_name not in ("Unknown/Unclassified", ""):
                virus_cache[virus_name] = None  # type: ignore[assignment]
            if not dry_run and stats["no_hit"] <= 10:
                mark_review_candidate(
                    conn, isolate_id, "discovery_reference_id",
                    f"No literature hit for accession={accession} virus={virus_name}",
                )
            if idx % 500 == 0:
                print(f"  [progress] {idx}/{len(profiles)} cache={stats['cache_hit']} searched={stats['crossref_searched']+stats['pubmed_searched']} refs={stats['refs_inserted']} no_hit={stats['no_hit']}")
            continue

        best = relevant[0]

        if dry_run:
            print(f"  [{idx}/{len(profiles)}] iso={isolate_id} {accession:20s} virus={virus_name[:35]:35s} -> {best.source:8s} {best.title[:65]:65s} doi={best.doi or ''}")
            # Still cache in dry-run so output is concise
            if virus_name and virus_name not in ("Unknown/Unclassified", ""):
                virus_cache[virus_name] = (-1, best)  # dummy ref_id
            continue

        # Insert reference
        ref_id = insert_reference(conn, best)
        if ref_id is None:
            continue

        stats["refs_inserted"] += 1

        # Cache the result
        if virus_name and virus_name not in ("Unknown/Unclassified", ""):
            virus_cache[virus_name] = (ref_id, best)

        if profile["discovery_reference_id"] is None:
            update_profile_reference(conn, isolate_id, ref_id, "discovery_reference_id")
            add_reference_link(
                conn, isolate_id, ref_id, "initial_discovery",
                f"Matched via {best.source}: {accession} -> {best.doi or best.title[:80]}",
            )
            stats["discovery_links_added"] += 1

        if profile["primary_reference_id"] is None:
            update_profile_reference(conn, isolate_id, ref_id, "primary_reference_id")
            add_reference_link(
                conn, isolate_id, ref_id, "genbank_reference",
                f"Also set as primary from {best.source}: {best.doi or best.title[:80]}",
            )
            stats["primary_links_added"] += 1

        if idx % 500 == 0:
            print(f"  [progress] {idx}/{len(profiles)} cache={stats['cache_hit']} searched={stats['crossref_searched']+stats['pubmed_searched']} refs={stats['refs_inserted']} no_hit={stats['no_hit']}")

    return stats


def export_results(conn: sqlite3.Connection, stats: dict) -> Path:
    DOWNLOADS_DIR.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = DOWNLOADS_DIR / f"literature_results_{stamp}.json"
    data = {"stats": stats, "completed_at": datetime.now().isoformat(timespec="seconds")}
    out_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_path


def log_run(conn: sqlite3.Connection, stats: dict) -> None:
    src_id = source_id(conn, "crossref")
    payload = "; ".join(f"{k}={v}" for k, v in sorted(stats.items()))
    conn.execute(
        """INSERT INTO curation_logs
           (entity_type, action, source_id, new_value, confidence, curator, notes)
         VALUES (?, ?, ?, ?, ?, ?, ?)""",
        ("reference", "fetch_literature", src_id, payload,
         "high", "fetch_openex_literature.py",
         "Crossref+PubMed literature search for isolates missing references."),
    )


def validate(conn: sqlite3.Connection) -> None:
    quick_check = conn.execute("PRAGMA quick_check").fetchone()[0]
    if quick_check != "ok":
        raise RuntimeError(f"SQLite quick_check failed: {quick_check}")
    fk_errors = conn.execute("PRAGMA foreign_key_check").fetchall()
    if fk_errors:
        raise RuntimeError(f"Foreign key check failed: {fk_errors[:5]}")


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.dry_run:
        print("[dry-run] Preview mode — no database changes will be made")

    backup_path = backup_database() if not args.dry_run else None
    if backup_path:
        print(f"[backup] {backup_path}")

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        ensure_schema(conn)
        stats = run_literature_fetch(conn, args.limit, args.dry_run)
        if not args.dry_run:
            export_path = export_results(conn, stats)
            log_run(conn, stats)
            validate(conn)
            conn.commit()
            print(f"[done] export={export_path}")
        else:
            print("[dry-run] skipped writes")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    for key, value in sorted(stats.items()):
        print(f"[done] {key}={value}")


if __name__ == "__main__":
    main()
