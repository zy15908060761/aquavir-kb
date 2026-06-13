"""
Build an external curation query queue for unresolved high-priority gaps.

The local GenBank and PubMed-ID recovery pass leaves many old/high-value
records without host, geography, or primary references. This script creates a
reviewable query layer so the next curation pass can target PubMed, Crossref,
ICTV/VMR, Google Scholar, and original articles systematically.
"""

from __future__ import annotations

import re
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

import pandas as pd
from Bio import SeqIO


BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "crustacean_virus_core.db"
GB_PATH = BASE_DIR / "ncbi_metadata" / "crustacean_virus_raw.gb"
BACKUP_DIR = BASE_DIR / "backups"
DOWNLOADS_DIR = BASE_DIR / "downloads"

TARGET_BANDS = ("P0", "P1")
GENERIC_TITLES = {"", "Direct Submission"}


def backup_database() -> Path:
    BACKUP_DIR.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = BACKUP_DIR / f"crustacean_virus_core_before_external_queries_{stamp}.db"
    shutil.copy2(DB_PATH, backup_path)
    return backup_path


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        PRAGMA foreign_keys = ON;

        CREATE TABLE IF NOT EXISTS external_curation_queries (
            query_id INTEGER PRIMARY KEY AUTOINCREMENT,
            isolate_id INTEGER NOT NULL,
            accession TEXT NOT NULL,
            priority_band TEXT NOT NULL,
            priority_score INTEGER NOT NULL,
            canonical_virus_name TEXT,
            field_name TEXT NOT NULL,
            query_target TEXT NOT NULL CHECK (
                query_target IN ('pubmed', 'crossref', 'scholar', 'genbank', 'literature_manual')
            ),
            query_text TEXT NOT NULL,
            genbank_title TEXT,
            genbank_journal TEXT,
            genbank_authors TEXT,
            query_status TEXT NOT NULL DEFAULT 'open' CHECK (
                query_status IN ('open', 'searched_no_hit', 'candidate_found', 'resolved', 'ignored')
            ),
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            notes TEXT,
            FOREIGN KEY (isolate_id) REFERENCES viral_isolates(isolate_id)
        );

        CREATE UNIQUE INDEX IF NOT EXISTS idx_external_curation_queries_unique
            ON external_curation_queries(isolate_id, field_name, query_target, query_text);
        CREATE INDEX IF NOT EXISTS idx_external_curation_queries_band
            ON external_curation_queries(priority_band);
        CREATE INDEX IF NOT EXISTS idx_external_curation_queries_field
            ON external_curation_queries(field_name);
        CREATE INDEX IF NOT EXISTS idx_external_curation_queries_status
            ON external_curation_queries(query_status);
        """
    )


def accession_base(accession: str | None) -> str:
    return (accession or "").strip().split(".", 1)[0]


def clean_text(value: str | None) -> str:
    return re.sub(r"\s+", " ", (value or "").strip())


def quote(value: str) -> str:
    text = clean_text(value)
    return f'"{text}"' if text else ""


def parse_genbank_references() -> dict[str, list[dict[str, str]]]:
    refs: dict[str, list[dict[str, str]]] = {}
    for record in SeqIO.parse(str(GB_PATH), "genbank"):
        accession = clean_text(record.id)
        record_refs = []
        for ref in record.annotations.get("references", []) or []:
            title = clean_text(getattr(ref, "title", ""))
            journal = clean_text(getattr(ref, "journal", ""))
            authors = clean_text(getattr(ref, "authors", ""))
            pmid = clean_text(getattr(ref, "pubmed_id", ""))
            if title in GENERIC_TITLES and not pmid:
                continue
            record_refs.append(
                {
                    "title": title,
                    "journal": journal,
                    "authors": authors,
                    "pmid": pmid,
                }
            )
        refs[accession] = record_refs
        refs.setdefault(accession_base(accession), record_refs)
    return refs


def first_non_pubmed_reference(refs: list[dict[str, str]]) -> dict[str, str]:
    for ref in refs:
        if ref.get("title") and not ref.get("pmid"):
            return ref
    return refs[0] if refs else {"title": "", "journal": "", "authors": "", "pmid": ""}


def build_queries(row: sqlite3.Row, ref: dict[str, str]) -> list[tuple[str, str, str]]:
    accession = clean_text(row["accession"])
    base = accession_base(accession)
    virus = clean_text(row["canonical_virus_name"])
    title = clean_text(ref.get("title"))
    field_name = row["field_name"]

    queries: list[tuple[str, str, str]] = []
    if field_name == "primary_reference_id":
        if title:
            queries.append(("pubmed", f"{quote(title)}", "Search exact GenBank reference title in PubMed."))
            queries.append(("crossref", title, "Search exact GenBank reference title in Crossref/DOI."))
        queries.append(("pubmed", f"{quote(accession)} OR {quote(base)}", "Search accession in PubMed."))
        if virus:
            queries.append(("scholar", f"{quote(accession)} {quote(virus)}", "Search accession and canonical virus name in scholarly indexes."))
    elif field_name == "host_id":
        if virus:
            queries.append(("pubmed", f"{quote(accession)} OR ({quote(virus)} AND host)", "Recover host from accession-specific or virus host-range papers."))
            queries.append(("literature_manual", f"{virus} {accession} host isolate", "Manual host curation query."))
        else:
            queries.append(("literature_manual", f"{accession} host isolate", "Manual host curation query."))
    elif field_name in {"country", "location"}:
        if virus:
            queries.append(("pubmed", f"{quote(accession)} OR ({quote(virus)} AND isolate AND geography)", "Recover geography from accession or isolate paper."))
            queries.append(("literature_manual", f"{virus} {accession} country isolate", "Manual geography curation query."))
        else:
            queries.append(("literature_manual", f"{accession} country isolate", "Manual geography curation query."))
    else:
        if virus:
            queries.append(("literature_manual", f"{virus} {accession} {field_name}", "Manual curation query."))

    deduped = []
    seen = set()
    for target, query, note in queries:
        key = (target, query)
        if query and key not in seen:
            seen.add(key)
            deduped.append((target, query, note))
    return deduped


def seed_queries(conn: sqlite3.Connection, gb_refs: dict[str, list[dict[str, str]]]) -> int:
    before = conn.total_changes
    placeholders = ", ".join("?" for _ in TARGET_BANDS)
    rows = conn.execute(
        f"""
        SELECT q.isolate_id, q.accession, q.priority_band, q.priority_score,
               q.canonical_virus_name, q.field_name
        FROM curation_priority_queue q
        WHERE q.priority_band IN ({placeholders})
          AND q.queue_status = 'open'
          AND q.field_name IN ('primary_reference_id', 'host_id', 'country', 'location')
        ORDER BY q.priority_score DESC, q.queue_id
        """,
        TARGET_BANDS,
    ).fetchall()

    for row in rows:
        refs = gb_refs.get(clean_text(row["accession"])) or gb_refs.get(accession_base(row["accession"])) or []
        ref = first_non_pubmed_reference(refs)
        for target, query, note in build_queries(row, ref):
            conn.execute(
                """
                INSERT INTO external_curation_queries
                    (
                        isolate_id, accession, priority_band, priority_score,
                        canonical_virus_name, field_name, query_target,
                        query_text, genbank_title, genbank_journal,
                        genbank_authors, notes
                    )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(isolate_id, field_name, query_target, query_text)
                DO UPDATE SET
                    priority_band = excluded.priority_band,
                    priority_score = excluded.priority_score,
                    canonical_virus_name = excluded.canonical_virus_name,
                    genbank_title = excluded.genbank_title,
                    genbank_journal = excluded.genbank_journal,
                    genbank_authors = excluded.genbank_authors,
                    notes = excluded.notes,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    row["isolate_id"],
                    row["accession"],
                    row["priority_band"],
                    row["priority_score"],
                    row["canonical_virus_name"],
                    row["field_name"],
                    target,
                    query,
                    ref.get("title", ""),
                    ref.get("journal", ""),
                    ref.get("authors", ""),
                    note,
                ),
            )
    return conn.total_changes - before


def export_queries(conn: sqlite3.Connection) -> Path:
    DOWNLOADS_DIR.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = DOWNLOADS_DIR / f"external_curation_queries_{stamp}.xlsx"
    summary = pd.read_sql_query(
        """
        SELECT priority_band, field_name, query_target, query_status, COUNT(*) AS n
        FROM external_curation_queries
        GROUP BY priority_band, field_name, query_target, query_status
        ORDER BY priority_band, field_name, query_target
        """,
        conn,
    )
    queries = pd.read_sql_query(
        """
        SELECT query_id, isolate_id, accession, priority_band, priority_score,
               canonical_virus_name, field_name, query_target, query_text,
               genbank_title, genbank_journal, genbank_authors, query_status, notes
        FROM external_curation_queries
        WHERE priority_band IN ('P0', 'P1')
          AND query_status = 'open'
        ORDER BY priority_band, priority_score DESC, field_name, accession, query_target
        """,
        conn,
    )
    with pd.ExcelWriter(out_path, engine="openpyxl") as writer:
        summary.to_excel(writer, index=False, sheet_name="summary")
        queries.to_excel(writer, index=False, sheet_name="queries")
    return out_path


def log_run(conn: sqlite3.Connection, changes: int, export_path: Path) -> None:
    source = conn.execute("SELECT source_id FROM external_sources WHERE source_key='local_curation'").fetchone()
    conn.execute(
        """
        INSERT INTO curation_logs
            (entity_type, action, source_id, new_value, confidence, curator, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "external_query",
            "build_external_curation_queries",
            source["source_id"] if source else None,
            f"query_changes={changes}",
            "high",
            "build_external_curation_queries.py",
            f"Generated query queue for unresolved P0/P1 curation issues; export={export_path}",
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
    backup_path = backup_database()
    print(f"[backup] {backup_path}")
    gb_refs = parse_genbank_references()
    print(f"[genbank] reference_records={len(gb_refs)}")

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        ensure_schema(conn)
        changes = seed_queries(conn, gb_refs)
        export_path = export_queries(conn)
        log_run(conn, changes, export_path)
        validate(conn)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    print(f"[done] query_changes={changes}")
    print(f"[done] export={export_path}")


if __name__ == "__main__":
    main()
