#!/usr/bin/env python3
"""Discover and cache legally accessible OA full text for ref_literatures.

The pipeline is resumable and conservative:
- Uses local cache first.
- Queries open/legal channels: NCBI PMCID converter, Europe PMC, Unpaywall.
- Downloads only OA XML/PDF/HTML URLs returned by those services.
- Writes no biological production facts directly.
- Produces manual checklist for references without accessible full text.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sqlite3
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import quote
from xml.etree import ElementTree as ET

import requests


ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "crustacean_virus_core.db"
CURATION_DIR = ROOT / "literature_curation_v2"
PMC_XML_DIR = CURATION_DIR / "pmc_xml"
PDF_DIR = CURATION_DIR / "fulltext"
REPORT_DIR = ROOT / "reports" / "fulltext_oa_pipeline"

USER_AGENT = "CrustaVirusDB/1.0 literature curation (mailto:crustacean-virus-db-curation@proton.me)"
UNPAYWALL_EMAIL = "crustacean-virus-db-curation@proton.me"
TIMEOUT = 45


def connect() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH, timeout=60)
    con.row_factory = sqlite3.Row
    con.execute("pragma foreign_keys=on")
    con.execute("pragma busy_timeout=60000")
    return con


def ensure_schema(con: sqlite3.Connection) -> None:
    con.executescript(
        """
        CREATE TABLE IF NOT EXISTS literature_fulltext_sources (
            fulltext_id INTEGER PRIMARY KEY AUTOINCREMENT,
            reference_id INTEGER NOT NULL,
            pmid TEXT,
            doi TEXT,
            pmcid TEXT,
            source TEXT NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('local','downloaded','no_oa','failed','skipped')),
            oa_status TEXT,
            fulltext_url TEXT,
            pdf_url TEXT,
            xml_url TEXT,
            local_path TEXT,
            content_type TEXT,
            license TEXT,
            error TEXT,
            checked_at TEXT DEFAULT CURRENT_TIMESTAMP,
            raw_json TEXT,
            dedupe_key TEXT NOT NULL UNIQUE,
            FOREIGN KEY(reference_id) REFERENCES ref_literatures(reference_id)
        );

        CREATE INDEX IF NOT EXISTS idx_fulltext_sources_ref
            ON literature_fulltext_sources(reference_id);
        CREATE INDEX IF NOT EXISTS idx_fulltext_sources_status
            ON literature_fulltext_sources(status, source);

        CREATE TABLE IF NOT EXISTS literature_fulltext_sections (
            section_id INTEGER PRIMARY KEY AUTOINCREMENT,
            fulltext_id INTEGER NOT NULL,
            reference_id INTEGER NOT NULL,
            section_title TEXT,
            section_type TEXT,
            text TEXT NOT NULL,
            char_count INTEGER,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(fulltext_id) REFERENCES literature_fulltext_sources(fulltext_id),
            FOREIGN KEY(reference_id) REFERENCES ref_literatures(reference_id),
            UNIQUE(fulltext_id, section_title, section_type)
        );
        """
    )


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def clean_filename(text: str, max_len: int = 120) -> str:
    text = re.sub(r"[\\/:*?\"<>|]+", "_", text or "")
    text = re.sub(r"\s+", " ", text).strip()
    return text[:max_len] or "untitled"


def dedupe_key(reference_id: int, source: str, url_or_path: str, status: str) -> str:
    return sha256_text("|".join([str(reference_id), source, url_or_path or "", status]))


def record_source(con: sqlite3.Connection, row: dict) -> int:
    key = dedupe_key(row["reference_id"], row["source"], row.get("fulltext_url") or row.get("xml_url") or row.get("pdf_url") or row.get("local_path") or "", row["status"])
    row = dict(row)
    row["dedupe_key"] = key
    cols = [
        "reference_id", "pmid", "doi", "pmcid", "source", "status", "oa_status",
        "fulltext_url", "pdf_url", "xml_url", "local_path", "content_type",
        "license", "error", "raw_json", "dedupe_key",
    ]
    last_error = None
    for attempt in range(4):
        try:
            con.execute(
                f"""
                INSERT OR IGNORE INTO literature_fulltext_sources ({','.join(cols)})
                VALUES ({','.join('?' for _ in cols)})
                """,
                [row.get(c) for c in cols],
            )
            break
        except sqlite3.OperationalError as exc:
            last_error = exc
            if "disk I/O" not in str(exc) and "locked" not in str(exc):
                raise
            time.sleep(2 * (attempt + 1))
            try:
                con.execute("PRAGMA wal_checkpoint(PASSIVE)")
            except sqlite3.Error:
                pass
    else:
        raise last_error
    found = con.execute(
        "SELECT fulltext_id FROM literature_fulltext_sources WHERE dedupe_key=?",
        (key,),
    ).fetchone()
    return int(found["fulltext_id"])


def already_processed(con: sqlite3.Connection, reference_id: int) -> bool:
    return con.execute(
        """
        SELECT 1 FROM literature_fulltext_sources
        WHERE reference_id=?
          AND status IN ('local','downloaded','no_oa','failed')
        LIMIT 1
        """,
        (reference_id,),
    ).fetchone() is not None


def find_local_fulltext(ref: sqlite3.Row) -> Path | None:
    pmid = str(ref["pmid"] or "").strip()
    doi = str(ref["doi"] or "").strip().lower()
    patterns = []
    if pmid:
        patterns.extend([f"*PMID{pmid}*.xml", f"*{pmid}*.xml", f"*{pmid}*.pdf"])
    if doi:
        doi_token = re.sub(r"[^A-Za-z0-9]+", "_", doi)
        patterns.extend([f"*{doi_token}*.xml", f"*{doi_token}*.pdf"])
    for base in [PMC_XML_DIR, PDF_DIR, CurationOAPath()]:
        if not base.exists():
            continue
        for pat in patterns:
            for path in base.glob(pat):
                if path.is_file() and path.stat().st_size > 0:
                    return path
    return None


def CurationOAPath() -> Path:
    return CURATION_DIR / "oa_fulltext"


def lookup_pmcid(pmid: str) -> str | None:
    if not pmid:
        return None
    url = "https://www.ncbi.nlm.nih.gov/pmc/utils/idconv/v1.0/"
    params = {"ids": pmid, "format": "json", "tool": "CrustaVirusDB", "email": UNPAYWALL_EMAIL}
    r = requests.get(url, params=params, headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT)
    r.raise_for_status()
    for rec in r.json().get("records", []):
        if rec.get("pmcid"):
            return rec["pmcid"]
    return None


def europe_pmc_search(pmid: str | None, doi: str | None) -> dict:
    queries = []
    if pmid:
        queries.append(f"EXT:{pmid}")
    if doi:
        queries.append(f'DOI:"{doi}"')
    for query in queries:
        r = requests.get(
            "https://www.ebi.ac.uk/europepmc/webservices/rest/search",
            params={"query": query, "format": "json", "resultType": "core"},
            headers={"User-Agent": USER_AGENT},
            timeout=TIMEOUT,
        )
        r.raise_for_status()
        results = r.json().get("resultList", {}).get("result", [])
        if results:
            return results[0]
    return {}


def unpaywall_lookup(doi: str) -> dict:
    if not doi:
        return {}
    r = requests.get(
        f"https://api.unpaywall.org/v2/{quote(doi, safe='')}?email={quote(UNPAYWALL_EMAIL, safe='')}",
        headers={"User-Agent": USER_AGENT},
        timeout=TIMEOUT,
    )
    if r.status_code == 404:
        return {}
    r.raise_for_status()
    return r.json()


def fetch_url(url: str) -> tuple[bytes, str]:
    r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT, allow_redirects=True)
    r.raise_for_status()
    ctype = r.headers.get("Content-Type", "")
    return r.content, ctype


def save_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def try_fetch_fulltext(ref: sqlite3.Row) -> dict:
    pmid = str(ref["pmid"] or "").strip()
    doi = str(ref["doi"] or "").strip()
    title = str(ref["title"] or "")
    reference_id = int(ref["reference_id"])
    local = find_local_fulltext(ref)
    if local:
        return {
            "reference_id": reference_id, "pmid": pmid, "doi": doi, "source": "local_cache",
            "status": "local", "local_path": str(local), "content_type": local.suffix.lower(),
        }

    epmc = {}
    pmcid = None
    errors = []
    try:
        if pmid:
            pmcid = lookup_pmcid(pmid)
    except Exception as exc:
        errors.append(f"idconv:{type(exc).__name__}:{exc}")

    try:
        epmc = europe_pmc_search(pmid or None, doi or None)
        pmcid = pmcid or epmc.get("pmcid")
    except Exception as exc:
        errors.append(f"epmc:{type(exc).__name__}:{exc}")

    if pmcid:
        xml_url = f"https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/fullTextXML"
        try:
            data, ctype = fetch_url(xml_url)
            if len(data) > 1000 and b"<" in data[:100]:
                path = PMC_XML_DIR / f"{pmcid}_PMID{pmid or 'NA'}.xml"
                save_bytes(path, data)
                return {
                    "reference_id": reference_id, "pmid": pmid, "doi": doi, "pmcid": pmcid,
                    "source": "europe_pmc_xml", "status": "downloaded", "oa_status": "oa_fulltext",
                    "xml_url": xml_url, "local_path": str(path), "content_type": ctype,
                    "raw_json": json.dumps(epmc, ensure_ascii=False),
                }
        except Exception as exc:
            errors.append(f"fullTextXML:{type(exc).__name__}:{exc}")

    for link in (epmc.get("fullTextUrlList") or {}).get("fullTextUrl", []) if epmc else []:
        url = link.get("url") or ""
        if not url:
            continue
        if "pdf" not in (link.get("documentStyle") or "").lower() and not url.lower().endswith(".pdf"):
            continue
        try:
            data, ctype = fetch_url(url)
            if data[:4] == b"%PDF" and len(data) > 5000:
                path = PDF_DIR / f"{pmid or reference_id}_{clean_filename(title)}.pdf"
                save_bytes(path, data)
                return {
                    "reference_id": reference_id, "pmid": pmid, "doi": doi, "pmcid": pmcid,
                    "source": "europe_pmc_pdf", "status": "downloaded", "oa_status": "oa_pdf",
                    "pdf_url": url, "local_path": str(path), "content_type": ctype,
                    "raw_json": json.dumps(epmc, ensure_ascii=False),
                }
        except Exception as exc:
            errors.append(f"epmc_pdf:{type(exc).__name__}:{exc}")

    if doi:
        try:
            upw = unpaywall_lookup(doi)
            best = upw.get("best_oa_location") or {}
            pdf_url = best.get("url_for_pdf") or ""
            landing = best.get("url") or ""
            if pdf_url:
                data, ctype = fetch_url(pdf_url)
                if data[:4] == b"%PDF" and len(data) > 5000:
                    path = PDF_DIR / f"{pmid or reference_id}_{clean_filename(title)}.pdf"
                    save_bytes(path, data)
                    return {
                        "reference_id": reference_id, "pmid": pmid, "doi": doi,
                        "source": "unpaywall_pdf", "status": "downloaded",
                        "oa_status": upw.get("oa_status"), "license": best.get("license"),
                        "pdf_url": pdf_url, "fulltext_url": landing, "local_path": str(path),
                        "content_type": ctype, "raw_json": json.dumps(upw, ensure_ascii=False),
                    }
            if landing and upw.get("is_oa"):
                return {
                    "reference_id": reference_id, "pmid": pmid, "doi": doi,
                    "source": "unpaywall_landing", "status": "no_oa",
                    "oa_status": upw.get("oa_status"), "license": best.get("license"),
                    "fulltext_url": landing, "raw_json": json.dumps(upw, ensure_ascii=False),
                    "error": "OA landing found but no downloadable PDF/XML cached",
                }
        except Exception as exc:
            errors.append(f"unpaywall:{type(exc).__name__}:{exc}")

    return {
        "reference_id": reference_id, "pmid": pmid, "doi": doi, "pmcid": pmcid,
        "source": "oa_discovery", "status": "no_oa" if not errors else "failed",
        "oa_status": epmc.get("isOpenAccess") if epmc else None,
        "raw_json": json.dumps({"epmc": epmc, "errors": errors}, ensure_ascii=False),
        "error": "; ".join(errors)[:1000],
    }


def parse_and_store_sections(con: sqlite3.Connection, fulltext_id: int, reference_id: int, path: Path) -> int:
    if not path.exists() or path.suffix.lower() != ".xml":
        return 0
    try:
        root = ET.parse(path).getroot()
    except Exception:
        return 0
    inserted = 0
    with con:
        for sec in root.findall(".//sec"):
            title_node = sec.find("title")
            title = " ".join("".join(title_node.itertext()).split()) if title_node is not None else "body"
            paras = [" ".join("".join(p.itertext()).split()) for p in sec.findall(".//p")]
            text = " ".join(p for p in paras if p)
            if len(text) < 80:
                continue
            before = con.total_changes
            con.execute(
                """
                INSERT OR IGNORE INTO literature_fulltext_sections
                    (fulltext_id, reference_id, section_title, section_type, text, char_count)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (fulltext_id, reference_id, title[:300], infer_section_type(title), text, len(text)),
            )
            if con.total_changes > before:
                inserted += 1
    return inserted


def infer_section_type(title: str) -> str:
    low = (title or "").lower()
    if "method" in low or "material" in low:
        return "methods"
    if "result" in low:
        return "results"
    if "discussion" in low:
        return "discussion"
    if "intro" in low or "background" in low:
        return "background"
    return "body"


def export_manual_checklist(con: sqlite3.Connection) -> int:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    rows = [
        dict(r)
        for r in con.execute(
            """
            SELECT rl.reference_id, rl.pmid, rl.doi, rl.year, rl.journal, rl.title,
                   fs.status, fs.source, fs.error, fs.fulltext_url, fs.pdf_url, fs.xml_url
            FROM ref_literatures rl
            LEFT JOIN (
                SELECT reference_id, status, source, error, fulltext_url, pdf_url, xml_url
                FROM literature_fulltext_sources
                WHERE fulltext_id IN (
                    SELECT max(fulltext_id) FROM literature_fulltext_sources GROUP BY reference_id
                )
            ) fs ON fs.reference_id=rl.reference_id
            WHERE fs.status IS NULL OR fs.status IN ('no_oa','failed','skipped')
            ORDER BY cast(coalesce(rl.year,'0') as integer) DESC, rl.reference_id
            """
        )
    ]
    out = REPORT_DIR / "manual_fulltext_checklist.csv"
    if rows:
        with out.open("w", newline="", encoding="utf-8-sig") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
    return len(rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--resume", action="store_true", default=True)
    parser.add_argument("--no-resume", dest="resume", action="store_false")
    parser.add_argument("--sleep", type=float, default=0.35)
    args = parser.parse_args()

    PMC_XML_DIR.mkdir(parents=True, exist_ok=True)
    PDF_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    con = connect()
    ensure_schema(con)
    refs = con.execute(
        """
        SELECT reference_id, pmid, doi, title, year, journal
        FROM ref_literatures
        ORDER BY
          CASE WHEN pmid IS NOT NULL AND trim(pmid) != '' THEN 0 ELSE 1 END,
          reference_id
        """
    ).fetchall()
    done = 0
    downloaded = 0
    local = 0
    no_oa = 0
    failed = 0
    sections = 0
    for ref in refs:
        if args.limit and done >= args.limit:
            break
        if args.resume and already_processed(con, int(ref["reference_id"])):
            continue
        try:
            row = try_fetch_fulltext(ref)
        except Exception as exc:
            row = {
                "reference_id": int(ref["reference_id"]),
                "pmid": ref["pmid"],
                "doi": ref["doi"],
                "source": "pipeline_exception",
                "status": "failed",
                "error": f"{type(exc).__name__}: {exc}",
            }
        with con:
            fulltext_id = record_source(con, row)
        if row["status"] == "downloaded":
            downloaded += 1
        elif row["status"] == "local":
            local += 1
        elif row["status"] == "no_oa":
            no_oa += 1
        elif row["status"] == "failed":
            failed += 1
        if row.get("local_path"):
            sections += parse_and_store_sections(con, fulltext_id, row["reference_id"], Path(row["local_path"]))
        done += 1
        if done % 25 == 0:
            print(json.dumps({"processed": done, "downloaded": downloaded, "local": local, "no_oa": no_oa, "failed": failed, "sections": sections}, ensure_ascii=False))
        time.sleep(args.sleep)
    manual = export_manual_checklist(con)
    summary = {
        "processed_this_run": done,
        "downloaded": downloaded,
        "local": local,
        "no_oa": no_oa,
        "failed": failed,
        "sections_inserted": sections,
        "manual_checklist_rows": manual,
        "total_sources": con.execute("SELECT COUNT(*) FROM literature_fulltext_sources").fetchone()[0],
        "total_sections": con.execute("SELECT COUNT(*) FROM literature_fulltext_sections").fetchone()[0],
    }
    (REPORT_DIR / "fulltext_pipeline_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
