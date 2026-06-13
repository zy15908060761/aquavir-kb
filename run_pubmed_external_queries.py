"""
Run PubMed searches for external curation queries.

This script consumes the external_curation_queries table generated from P0/P1
gaps. It focuses on high-confidence PubMed search results:
- stores every PubMed hit in external_literature_hits
- inserts missing PubMed summaries into ref_literatures
- automatically applies only primary-reference hits where the GenBank title and
  PubMed title are highly similar and the query has a single hit

Accession-only matches are kept as candidates for review.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sqlite3
import time
import urllib.parse
import urllib.request
from urllib.error import URLError
from dataclasses import dataclass
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path

import pandas as pd

from fetch_pubmed_for_genbank_recovery import (
    extract_authors,
    extract_doi,
    extract_year,
    fetch_pubmed_summaries,
    insert_references,
)


BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "crustacean_virus_core.db"
BACKUP_DIR = BASE_DIR / "backups"
DOWNLOADS_DIR = BASE_DIR / "downloads"

NCBI_SEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
REQUEST_DELAY_SECONDS = 0.34


@dataclass(frozen=True)
class SearchResult:
    count: int
    pmids: tuple[str, ...]


def backup_database() -> Path:
    BACKUP_DIR.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = BACKUP_DIR / f"crustacean_virus_core_before_pubmed_external_queries_{stamp}.db"
    shutil.copy2(DB_PATH, backup_path)
    return backup_path


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        PRAGMA foreign_keys = ON;

        CREATE TABLE IF NOT EXISTS external_literature_hits (
            hit_id INTEGER PRIMARY KEY AUTOINCREMENT,
            query_id INTEGER NOT NULL,
            isolate_id INTEGER NOT NULL,
            accession TEXT NOT NULL,
            field_name TEXT NOT NULL,
            query_target TEXT NOT NULL,
            query_text TEXT NOT NULL,
            pmid TEXT NOT NULL,
            reference_id INTEGER,
            hit_rank INTEGER NOT NULL,
            hit_count INTEGER NOT NULL,
            title TEXT,
            journal TEXT,
            year TEXT,
            doi TEXT,
            match_basis TEXT NOT NULL CHECK (
                match_basis IN ('title_exact_or_high_similarity', 'accession_query', 'broad_query', 'manual_review')
            ),
            title_similarity REAL,
            confidence TEXT NOT NULL CHECK (confidence IN ('high', 'medium', 'low', 'unknown')),
            applied INTEGER NOT NULL DEFAULT 0 CHECK (applied IN (0, 1)),
            hit_status TEXT NOT NULL DEFAULT 'candidate' CHECK (
                hit_status IN ('candidate', 'applied', 'rejected')
            ),
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            notes TEXT,
            FOREIGN KEY (query_id) REFERENCES external_curation_queries(query_id),
            FOREIGN KEY (isolate_id) REFERENCES viral_isolates(isolate_id),
            FOREIGN KEY (reference_id) REFERENCES ref_literatures(reference_id)
        );

        CREATE UNIQUE INDEX IF NOT EXISTS idx_external_lit_hits_unique
            ON external_literature_hits(query_id, pmid);
        CREATE INDEX IF NOT EXISTS idx_external_lit_hits_pmid
            ON external_literature_hits(pmid);
        CREATE INDEX IF NOT EXISTS idx_external_lit_hits_accession
            ON external_literature_hits(accession);
        CREATE INDEX IF NOT EXISTS idx_external_lit_hits_status
            ON external_literature_hits(hit_status);
        """
    )


def normalize_title(value: str | None) -> str:
    text = (value or "").lower()
    text = re.sub(r"\[[^\]]+\]", " ", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def title_similarity(a: str | None, b: str | None) -> float:
    left = normalize_title(a)
    right = normalize_title(b)
    if not left or not right:
        return 0.0
    if left == right:
        return 1.0
    return SequenceMatcher(None, left, right).ratio()


def query_kind(query_text: str, genbank_title: str | None) -> str:
    text = query_text or ""
    if genbank_title and normalize_title(genbank_title) and normalize_title(genbank_title) in normalize_title(text):
        return "title"
    if " OR " in text and re.search(r'"[A-Z]{1,3}_?\d+[A-Z]?(?:\.\d+)?"', text):
        return "accession"
    return "broad"


def fetch_pubmed_search(query_text: str, retmax: int = 5) -> SearchResult:
    query = urllib.parse.urlencode(
        {
            "db": "pubmed",
            "term": query_text,
            "retmode": "json",
            "retmax": str(retmax),
            "tool": "crustacean_virus_db_curation",
            "email": "curator@example.com",
        }
    )
    request = urllib.request.Request(
        f"{NCBI_SEARCH_URL}?{query}",
        headers={"User-Agent": "crustacean-virus-db-curation/1.0"},
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        payload = json.loads(response.read().decode("utf-8"))
    result = payload.get("esearchresult", {})
    count = int(result.get("count", 0) or 0)
    pmids = tuple(str(pmid) for pmid in result.get("idlist", []) if str(pmid).strip())
    return SearchResult(count=count, pmids=pmids)


def fetch_pubmed_search_retry(query_text: str, retmax: int = 5, attempts: int = 3) -> SearchResult:
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            return fetch_pubmed_search(query_text, retmax=retmax)
        except (TimeoutError, URLError, OSError) as exc:
            last_error = exc
            time.sleep(REQUEST_DELAY_SECONDS * attempt * 2)
    raise RuntimeError(f"PubMed search failed after {attempts} attempts: {last_error}")


def fetch_pubmed_summaries_retry(pmids: list[str], attempts: int = 3) -> dict[str, dict]:
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            return fetch_pubmed_summaries(pmids)
        except (TimeoutError, URLError, OSError) as exc:
            last_error = exc
            time.sleep(REQUEST_DELAY_SECONDS * attempt * 2)
    raise RuntimeError(f"PubMed summary fetch failed after {attempts} attempts: {last_error}")


def get_queries(conn: sqlite3.Connection, limit: int) -> list[sqlite3.Row]:
    rows = conn.execute(
        """
        SELECT q.*
        FROM external_curation_queries q
        LEFT JOIN (
            SELECT query_id, COUNT(*) AS hit_rows
            FROM external_literature_hits
            GROUP BY query_id
        ) h ON h.query_id = q.query_id
        WHERE q.priority_band = 'P0'
          AND q.query_target = 'pubmed'
          AND q.query_status = 'open'
          AND q.field_name = 'primary_reference_id'
          AND h.hit_rows IS NULL
        ORDER BY
          CASE
            WHEN q.genbank_title IS NOT NULL AND TRIM(q.genbank_title) <> '' AND q.query_text NOT LIKE '% OR %'
            THEN 0 ELSE 1
          END,
          q.priority_score DESC,
          q.query_id
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return rows


def reference_id_for_pmid(conn: sqlite3.Connection, pmid: str) -> int | None:
    row = conn.execute("SELECT reference_id FROM ref_literatures WHERE pmid = ?", (pmid,)).fetchone()
    return row["reference_id"] if row else None


def upsert_hit(
    conn: sqlite3.Connection,
    query: sqlite3.Row,
    pmid: str,
    reference_id: int | None,
    rank: int,
    hit_count: int,
    summary: dict,
    match_basis: str,
    similarity: float,
    confidence: str,
    applied: int = 0,
    status: str = "candidate",
    notes: str = "",
) -> None:
    conn.execute(
        """
        INSERT INTO external_literature_hits
            (
                query_id, isolate_id, accession, field_name, query_target,
                query_text, pmid, reference_id, hit_rank, hit_count,
                title, journal, year, doi, match_basis, title_similarity,
                confidence, applied, hit_status, notes
            )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(query_id, pmid) DO UPDATE SET
            reference_id = excluded.reference_id,
            hit_rank = excluded.hit_rank,
            hit_count = excluded.hit_count,
            title = excluded.title,
            journal = excluded.journal,
            year = excluded.year,
            doi = excluded.doi,
            match_basis = excluded.match_basis,
            title_similarity = excluded.title_similarity,
            confidence = excluded.confidence,
            applied = excluded.applied,
            hit_status = excluded.hit_status,
            notes = excluded.notes,
            updated_at = CURRENT_TIMESTAMP
        """,
        (
            query["query_id"],
            query["isolate_id"],
            query["accession"],
            query["field_name"],
            query["query_target"],
            query["query_text"],
            pmid,
            reference_id,
            rank,
            hit_count,
            str(summary.get("title", "")).strip().rstrip("."),
            str(summary.get("fulljournalname") or summary.get("source") or "").strip(),
            extract_year(summary),
            extract_doi(summary),
            match_basis,
            similarity,
            confidence,
            applied,
            status,
            notes,
        ),
    )


def add_reference_link(conn: sqlite3.Connection, isolate_id: int, reference_id: int) -> None:
    conn.execute(
        """
        INSERT OR IGNORE INTO isolate_reference_links
            (
                isolate_id, reference_id, link_type, source_table,
                source_field, priority, evidence_status, notes
            )
        VALUES (?, ?, 'curation_evidence', 'external_literature_hits',
                'primary_reference_id', 25, 'auto_seeded',
                'Recovered from PubMed external query with high title similarity.')
        """,
        (isolate_id, reference_id),
    )


def mark_conflict_resolved(conn: sqlite3.Connection, isolate_id: int, pmid: str) -> None:
    note = f"Recovered by PubMed exact-title query; PMID {pmid}."
    conn.execute(
        """
        UPDATE curation_conflicts
        SET status = 'resolved',
            resolved_at = CURRENT_TIMESTAMP,
            notes = COALESCE(notes || ' | ', '') || ?
        WHERE isolate_id = ?
          AND field_name = 'primary_reference_id'
          AND status = 'open'
        """,
        (note, isolate_id),
    )
    conn.execute(
        """
        UPDATE curation_priority_queue
        SET queue_status = 'resolved',
            updated_at = CURRENT_TIMESTAMP,
            notes = COALESCE(notes || ' | ', '') || ?
        WHERE isolate_id = ?
          AND field_name = 'primary_reference_id'
          AND queue_status = 'open'
        """,
        (note, isolate_id),
    )


def apply_reference(conn: sqlite3.Connection, query: sqlite3.Row, reference_id: int, pmid: str) -> None:
    conn.execute(
        """
        UPDATE isolate_curated_profiles
        SET primary_reference_id = ?,
            metadata_source_priority = 'mixed_with_conflicts',
            curation_status = 'auto_seeded',
            confidence = 'high',
            notes = COALESCE(notes || ' | ', '') || ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE isolate_id = ?
          AND primary_reference_id IS NULL
        """,
        (
            reference_id,
            f"Primary reference recovered by PubMed title query; PMID {pmid}.",
            query["isolate_id"],
        ),
    )
    add_reference_link(conn, query["isolate_id"], reference_id)
    mark_conflict_resolved(conn, query["isolate_id"], pmid)


def mark_query_status(conn: sqlite3.Connection, query_id: int, status: str, note: str) -> None:
    conn.execute(
        """
        UPDATE external_curation_queries
        SET query_status = ?,
            notes = COALESCE(notes || ' | ', '') || ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE query_id = ?
        """,
        (status, note, query_id),
    )


def run_queries(conn: sqlite3.Connection, limit: int) -> dict[str, int]:
    stats = {
        "queries_run": 0,
        "queries_no_hit": 0,
        "queries_with_hits": 0,
        "pmids_fetched": 0,
        "references_inserted": 0,
        "hits_stored": 0,
        "references_applied": 0,
        "candidate_only": 0,
        "query_errors": 0,
    }

    queries = get_queries(conn, limit)
    for index, query in enumerate(queries, start=1):
        try:
            search = fetch_pubmed_search_retry(query["query_text"], retmax=5)
        except RuntimeError as exc:
            stats["query_errors"] += 1
            print(f"[warn] query_id={query['query_id']} search_failed={exc}")
            time.sleep(REQUEST_DELAY_SECONDS)
            continue
        stats["queries_run"] += 1
        if search.count == 0:
            mark_query_status(conn, query["query_id"], "searched_no_hit", "PubMed returned no hits.")
            stats["queries_no_hit"] += 1
            time.sleep(REQUEST_DELAY_SECONDS)
            continue

        stats["queries_with_hits"] += 1
        try:
            summaries = fetch_pubmed_summaries_retry(list(search.pmids))
        except RuntimeError as exc:
            stats["query_errors"] += 1
            print(f"[warn] query_id={query['query_id']} summary_failed={exc}")
            time.sleep(REQUEST_DELAY_SECONDS)
            continue
        stats["pmids_fetched"] += len(summaries)
        stats["references_inserted"] += insert_references(conn, summaries)

        kind = query_kind(query["query_text"], query["genbank_title"])
        applied_this_query = False
        for rank, pmid in enumerate(search.pmids, start=1):
            summary = summaries.get(pmid, {})
            reference_id = reference_id_for_pmid(conn, pmid)
            similarity = title_similarity(query["genbank_title"], summary.get("title", ""))
            if kind == "title":
                match_basis = "title_exact_or_high_similarity"
                high_confidence = search.count == 1 and similarity >= 0.92
            elif kind == "accession":
                match_basis = "accession_query"
                high_confidence = False
            else:
                match_basis = "broad_query"
                high_confidence = False

            confidence = "high" if high_confidence else "medium" if search.count <= 3 else "low"
            if high_confidence and reference_id and not applied_this_query:
                apply_reference(conn, query, reference_id, pmid)
                upsert_hit(
                    conn,
                    query,
                    pmid,
                    reference_id,
                    rank,
                    search.count,
                    summary,
                    match_basis,
                    similarity,
                    confidence,
                    applied=1,
                    status="applied",
                    notes="Auto-applied: single PubMed hit and high title similarity.",
                )
                mark_query_status(conn, query["query_id"], "resolved", f"Applied PMID {pmid}.")
                stats["references_applied"] += 1
                stats["hits_stored"] += 1
                applied_this_query = True
            else:
                upsert_hit(
                    conn,
                    query,
                    pmid,
                    reference_id,
                    rank,
                    search.count,
                    summary,
                    match_basis,
                    similarity,
                    confidence,
                    notes="Candidate only; manual review required before applying.",
                )
                stats["hits_stored"] += 1

        if not applied_this_query:
            mark_query_status(conn, query["query_id"], "candidate_found", f"PubMed returned {search.count} hit(s); manual review required.")
            stats["candidate_only"] += 1
        time.sleep(REQUEST_DELAY_SECONDS)
        if index % 50 == 0:
            print(f"[progress] queries={index}/{len(queries)} applied={stats['references_applied']} candidates={stats['candidate_only']}")

    return stats


def export_hits(conn: sqlite3.Connection) -> Path:
    DOWNLOADS_DIR.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = DOWNLOADS_DIR / f"pubmed_external_query_hits_{stamp}.xlsx"
    summary = pd.read_sql_query(
        """
        SELECT match_basis, confidence, hit_status, applied, COUNT(*) AS n
        FROM external_literature_hits
        GROUP BY match_basis, confidence, hit_status, applied
        ORDER BY match_basis, confidence, hit_status
        """,
        conn,
    )
    hits = pd.read_sql_query(
        """
        SELECT h.hit_id, h.query_id, h.isolate_id, h.accession, h.field_name,
               h.query_text, h.pmid, h.reference_id, h.hit_rank, h.hit_count,
               h.title, h.journal, h.year, h.doi, h.match_basis,
               h.title_similarity, h.confidence, h.hit_status, h.applied,
               h.notes
        FROM external_literature_hits h
        ORDER BY h.applied DESC, h.confidence, h.hit_count, h.accession, h.hit_rank
        """,
        conn,
    )
    with pd.ExcelWriter(out_path, engine="openpyxl") as writer:
        summary.to_excel(writer, index=False, sheet_name="summary")
        hits.to_excel(writer, index=False, sheet_name="hits")
    return out_path


def log_run(conn: sqlite3.Connection, stats: dict[str, int], export_path: Path) -> None:
    source = conn.execute("SELECT source_id FROM external_sources WHERE source_key='pubmed'").fetchone()
    payload = "; ".join(f"{key}={value}" for key, value in sorted(stats.items()))
    conn.execute(
        """
        INSERT INTO curation_logs
            (entity_type, action, source_id, new_value, confidence, curator, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "external_pubmed_query",
            "run_pubmed_external_queries",
            source["source_id"] if source else None,
            payload,
            "high",
            "run_pubmed_external_queries.py",
            f"Ran PubMed searches for unresolved P0 external curation queries; export={export_path}",
        ),
    )


def validate(conn: sqlite3.Connection) -> None:
    quick_check = conn.execute("PRAGMA quick_check").fetchone()[0]
    if quick_check != "ok":
        raise RuntimeError(f"SQLite quick_check failed: {quick_check}")
    fk_errors = conn.execute("PRAGMA foreign_key_check").fetchall()
    if fk_errors:
        raise RuntimeError(f"Foreign key check failed: {fk_errors[:5]}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=500, help="Maximum PubMed queries to run this pass.")
    args = parser.parse_args()

    backup_path = backup_database()
    print(f"[backup] {backup_path}")

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        ensure_schema(conn)
        stats = run_queries(conn, args.limit)
        export_path = export_hits(conn)
        log_run(conn, stats, export_path)
        validate(conn)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    for key, value in sorted(stats.items()):
        print(f"[done] {key}={value}")
    print(f"[done] export={export_path}")


if __name__ == "__main__":
    main()
