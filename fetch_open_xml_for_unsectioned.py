#!/usr/bin/env python3
"""Fetch open PMC/Europe PMC XML for references that still have no parsed sections."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import time
from datetime import datetime
from pathlib import Path
from xml.etree import ElementTree as ET

import requests

from optimize_fulltext_assets import parse_unsectioned


ROOT = Path.cwd()
DB_PATH = ROOT / "crustacean_virus_core.db"
PMC_XML_DIR = ROOT / "literature_curation_v2" / "pmc_xml"
LOG_DIR = ROOT / "downloads" / "fulltext_optimization"
USER_AGENT = "AquaVir-KB/1.0 literature curation (mailto:crustacean-virus-db-curation@proton.me)"
EMAIL = "crustacean-virus-db-curation@proton.me"
TIMEOUT = 45


def dedupe_key(reference_id: int, source: str, url_or_path: str, status: str) -> str:
    text = "|".join([str(reference_id), source, url_or_path or "", status])
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def record_source(con: sqlite3.Connection, row: dict) -> int:
    row = dict(row)
    row["dedupe_key"] = dedupe_key(
        int(row["reference_id"]),
        row["source"],
        row.get("xml_url") or row.get("local_path") or "",
        row["status"],
    )
    cols = [
        "reference_id", "pmid", "doi", "pmcid", "source", "status", "oa_status",
        "fulltext_url", "pdf_url", "xml_url", "local_path", "content_type",
        "license", "error", "raw_json", "dedupe_key",
    ]
    con.execute(
        f"""
        INSERT OR IGNORE INTO literature_fulltext_sources ({','.join(cols)})
        VALUES ({','.join('?' for _ in cols)})
        """,
        [row.get(c) for c in cols],
    )
    found = con.execute(
        "SELECT fulltext_id FROM literature_fulltext_sources WHERE dedupe_key=?",
        (row["dedupe_key"],),
    ).fetchone()
    return int(found[0])


def idconv_batch(pmids: list[str]) -> dict[str, str]:
    if not pmids:
        return {}
    response = requests.get(
        "https://www.ncbi.nlm.nih.gov/pmc/utils/idconv/v1.0/",
        params={"ids": ",".join(pmids), "format": "json", "tool": "AquaVir-KB", "email": EMAIL},
        headers={"User-Agent": USER_AGENT},
        timeout=TIMEOUT,
    )
    response.raise_for_status()
    mapping = {}
    for rec in response.json().get("records", []):
        pmid = str(rec.get("pmid") or rec.get("requested-id") or "")
        pmcid = rec.get("pmcid")
        if pmid and pmcid:
            mapping[pmid] = pmcid
    return mapping


def fetch_fulltext_xml(pmcid: str) -> tuple[bytes | None, str | None, str]:
    urls = [
        f"https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/fullTextXML",
        f"https://www.ncbi.nlm.nih.gov/research/bionlp/RESTful/pmcoa.cgi/BioC_XML/PMCIDs/{pmcid}/unicode",
    ]
    errors = []
    for url in urls:
        try:
            response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT)
            if response.status_code != 200:
                errors.append(f"{url}:http_{response.status_code}")
                continue
            data = response.content
            if len(data) < 1000:
                errors.append(f"{url}:too_small")
                continue
            head = data[:200].lower()
            if b"[error]" in head or b"no result can be found" in data[:1000].lower():
                errors.append(f"{url}:no_result")
                continue
            try:
                ET.fromstring(data)
            except Exception as exc:
                errors.append(f"{url}:xml_{type(exc).__name__}")
                continue
            return data, None, url
        except Exception as exc:
            errors.append(f"{url}:{type(exc).__name__}:{exc}")
    return None, "; ".join(errors), urls[0]


def chunks(items: list, size: int):
    for idx in range(0, len(items), size):
        yield items[idx:idx + size]


def candidate_refs(con: sqlite3.Connection, limit: int) -> list[sqlite3.Row]:
    sql = """
        SELECT DISTINCT rl.reference_id, rl.pmid, rl.doi, lfs.pmcid, rl.title, rl.year
        FROM literature_fulltext_sources lfs
        JOIN ref_literatures rl ON rl.reference_id = lfs.reference_id
        WHERE lfs.status IN ('downloaded','local')
          AND rl.pmid IS NOT NULL AND trim(rl.pmid) <> ''
          AND lfs.reference_id NOT IN (
              SELECT DISTINCT reference_id FROM literature_fulltext_sections
              WHERE reference_id IS NOT NULL
          )
        ORDER BY rl.year DESC, rl.reference_id
    """
    if limit:
        sql += f" LIMIT {int(limit)}"
    return con.execute(sql).fetchall()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=120)
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument("--sleep", type=float, default=0.25)
    parser.add_argument("--known-pmcid-only", action="store_true")
    args = parser.parse_args()

    PMC_XML_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    con = sqlite3.connect(str(DB_PATH), timeout=120)
    con.row_factory = sqlite3.Row
    refs = candidate_refs(con, args.limit)
    by_pmid = {str(r["pmid"]): r for r in refs if r["pmid"]}
    existing_pmcid = {
        str(r["pmid"]): str(r["pmcid"])
        for r in refs if r["pmid"] and r["pmcid"]
    }
    stats = {
        "candidates": len(refs),
        "pmcids_known": len(existing_pmcid),
        "pmcids_discovered": 0,
        "downloaded_xml": 0,
        "failed_xml": 0,
        "parse_runs": 0,
    }

    mapping = dict(existing_pmcid)
    if not args.known_pmcid_only:
        missing_pmids = [pmid for pmid in by_pmid if pmid not in mapping]
        for batch in chunks(missing_pmids, args.batch_size):
            try:
                discovered = idconv_batch(batch)
                stats["pmcids_discovered"] += len(discovered)
                mapping.update(discovered)
            except Exception as exc:
                print(json.dumps({"idconv_error": f"{type(exc).__name__}: {exc}", "batch": batch[:5]}, ensure_ascii=False))
            time.sleep(args.sleep)

    for pmid, pmcid in mapping.items():
        ref = by_pmid.get(pmid)
        if not ref:
            continue
        reference_id = int(ref["reference_id"])
        path = PMC_XML_DIR / f"{pmcid}_PMID{pmid}_openxml.xml"
        url = f"https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/fullTextXML"
        if not path.exists():
            data, err, url = fetch_fulltext_xml(pmcid)
            if not data:
                with con:
                    record_source(con, {
                        "reference_id": reference_id,
                        "pmid": pmid,
                        "doi": ref["doi"],
                        "pmcid": pmcid,
                        "source": "open_xml_unsectioned",
                        "status": "failed",
                        "oa_status": "pmcid_no_xml",
                        "xml_url": url,
                        "error": err,
                    })
                stats["failed_xml"] += 1
                time.sleep(args.sleep)
                continue
            path.write_bytes(data)

        with con:
            record_source(con, {
                "reference_id": reference_id,
                "pmid": pmid,
                "doi": ref["doi"],
                "pmcid": pmcid,
                "source": "open_xml_unsectioned",
                "status": "downloaded",
                "oa_status": "oa_fulltext",
                "xml_url": url,
                "local_path": str(path),
                "content_type": "application/xml",
            })
        stats["downloaded_xml"] += 1
        time.sleep(args.sleep)

    parse_stats = parse_unsectioned(con, ROOT, dry_run=False, limit=0, max_pdf_chars=80000)
    stats["parse_runs"] = parse_stats
    con.close()

    report = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "stats": stats,
    }
    out = LOG_DIR / f"fetch_open_xml_for_unsectioned_{int(time.time())}.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"Log: {out}")


if __name__ == "__main__":
    main()
