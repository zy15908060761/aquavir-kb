"""
Fetch PubMed metadata for GenBank recovery candidates.

This fills ref_literatures for explicit PMID values found in GenBank records
but missing from the local reference table. It does not guess references from
titles or free text. After this script runs, rerun recover_p0_from_genbank_raw.py
to apply newly available references to isolate_curated_profiles.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
import time
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "crustacean_virus_core.db"
BACKUP_DIR = BASE_DIR / "backups"
DOWNLOADS_DIR = BASE_DIR / "downloads"

NCBI_SUMMARY_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"


def backup_database() -> Path:
    BACKUP_DIR.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = BACKUP_DIR / f"crustacean_virus_core_before_pubmed_recovery_{stamp}.db"
    shutil.copy2(DB_PATH, backup_path)
    return backup_path


def pending_pmids(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        """
        SELECT DISTINCT candidate_value AS pmid
        FROM genbank_recovery_candidates
        WHERE field_name = 'primary_reference_id'
          AND match_status = 'no_local_reference'
          AND candidate_value IS NOT NULL
          AND TRIM(candidate_value) <> ''
          AND candidate_value NOT IN (
              SELECT pmid
              FROM ref_literatures
              WHERE pmid IS NOT NULL AND TRIM(pmid) <> ''
          )
        ORDER BY candidate_value
        """
    ).fetchall()
    return [str(row["pmid"]).strip() for row in rows]


def fetch_pubmed_summaries(pmids: list[str]) -> dict[str, dict]:
    if not pmids:
        return {}

    query = urllib.parse.urlencode(
        {
            "db": "pubmed",
            "id": ",".join(pmids),
            "retmode": "json",
            "tool": "crustacean_virus_db_curation",
            "email": "curator@example.com",
        }
    )
    url = f"{NCBI_SUMMARY_URL}?{query}"
    request = urllib.request.Request(url, headers={"User-Agent": "crustacean-virus-db-curation/1.0"})
    with urllib.request.urlopen(request, timeout=60) as response:
        payload = json.loads(response.read().decode("utf-8"))

    result = payload.get("result", {})
    summaries: dict[str, dict] = {}
    for pmid in result.get("uids", []):
        item = result.get(pmid) or {}
        if item:
            summaries[pmid] = item
    return summaries


def extract_doi(item: dict) -> str:
    for article_id in item.get("articleids", []) or []:
        if str(article_id.get("idtype", "")).lower() == "doi":
            return str(article_id.get("value", "")).strip()
    return ""


def extract_authors(item: dict) -> str:
    names = []
    for author in item.get("authors", []) or []:
        name = str(author.get("name", "")).strip()
        if name:
            names.append(name)
    return "; ".join(names)


def extract_year(item: dict) -> str:
    pubdate = str(item.get("pubdate", "")).strip()
    for token in pubdate.replace("-", " ").split():
        if len(token) == 4 and token.isdigit():
            return token
    return ""


def insert_references(conn: sqlite3.Connection, summaries: dict[str, dict]) -> int:
    inserted = 0
    for pmid, item in summaries.items():
        title = str(item.get("title", "")).strip().rstrip(".")
        journal = str(item.get("fulljournalname") or item.get("source") or "").strip()
        authors = extract_authors(item)
        year = extract_year(item)
        doi = extract_doi(item)
        conn.execute(
            """
            INSERT OR IGNORE INTO ref_literatures
                (pmid, title, authors, journal, year, doi, abstract, keywords)
            VALUES (?, ?, ?, ?, ?, ?, NULL, NULL)
            """,
            (pmid, title, authors, journal, year, doi),
        )
        inserted += conn.execute("SELECT changes()").fetchone()[0]
    return inserted


def write_manifest(pmids: list[str], summaries: dict[str, dict]) -> Path:
    DOWNLOADS_DIR.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = DOWNLOADS_DIR / f"pubmed_recovery_manifest_{stamp}.json"
    data = {
        "requested_pmids": pmids,
        "fetched_pmids": sorted(summaries),
        "missing_pmids": sorted(set(pmids) - set(summaries)),
        "fetched_at": datetime.now().isoformat(timespec="seconds"),
    }
    out_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_path


def log_run(conn: sqlite3.Connection, pmids: list[str], fetched: int, inserted: int, manifest_path: Path) -> None:
    source = conn.execute("SELECT source_id FROM external_sources WHERE source_key='pubmed'").fetchone()
    conn.execute(
        """
        INSERT INTO curation_logs
            (entity_type, action, source_id, new_value, confidence, curator, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "reference",
            "fetch_pubmed_for_genbank_recovery",
            source["source_id"] if source else None,
            f"requested_pmids={len(pmids)}; fetched={fetched}; inserted={inserted}",
            "high",
            "fetch_pubmed_for_genbank_recovery.py",
            f"Fetched PubMed summaries for explicit GenBank PMID recovery candidates; manifest={manifest_path}",
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

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        pmids = pending_pmids(conn)
        print(f"[pending] pmids={len(pmids)} {','.join(pmids)}")
        summaries = fetch_pubmed_summaries(pmids)
        time.sleep(0.34)
        inserted = insert_references(conn, summaries)
        manifest_path = write_manifest(pmids, summaries)
        log_run(conn, pmids, len(summaries), inserted, manifest_path)
        validate(conn)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    print(f"[done] fetched={len(summaries)}")
    print(f"[done] inserted={inserted}")
    print(f"[done] manifest={manifest_path}")


if __name__ == "__main__":
    main()
