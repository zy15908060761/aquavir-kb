#!/usr/bin/env python3
"""Batch PMCID discovery and Europe PMC fullTextXML fetch.

This accelerates the OA pipeline by using NCBI idconv in batches instead of
per-reference lookups. It only fetches openly available PMC XML.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import time
from pathlib import Path
from xml.etree import ElementTree as ET

import requests

from run_fulltext_oa_pipeline import (
    DB_PATH,
    PMC_XML_DIR,
    USER_AGENT,
    UNPAYWALL_EMAIL,
    TIMEOUT,
    connect,
    ensure_schema,
    record_source,
    parse_and_store_sections,
)


IDCONV_URL = "https://www.ncbi.nlm.nih.gov/pmc/utils/idconv/v1.0/"


def chunks(items: list, size: int):
    for i in range(0, len(items), size):
        yield items[i : i + size]


def remaining_pmids(con: sqlite3.Connection, limit: int = 0) -> list[sqlite3.Row]:
    sql = """
        SELECT reference_id, pmid, doi, title
        FROM ref_literatures
        WHERE pmid IS NOT NULL AND trim(pmid) != ''
          AND reference_id NOT IN (
              SELECT DISTINCT reference_id FROM literature_fulltext_sources
              WHERE status IN ('local','downloaded')
          )
        ORDER BY reference_id
    """
    if limit:
        sql += f" LIMIT {int(limit)}"
    return con.execute(sql).fetchall()


def idconv_batch(pmids: list[str]) -> dict[str, str]:
    params = {
        "ids": ",".join(pmids),
        "format": "json",
        "tool": "CrustaVirusDB",
        "email": UNPAYWALL_EMAIL,
    }
    r = requests.get(IDCONV_URL, params=params, headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT)
    r.raise_for_status()
    mapping = {}
    for rec in r.json().get("records", []):
        pmid = str(rec.get("pmid") or rec.get("requested-id") or "")
        pmcid = rec.get("pmcid")
        if pmid and pmcid:
            mapping[pmid] = pmcid
    return mapping


def fetch_xml(pmcid: str) -> tuple[bytes | None, str | None]:
    url = f"https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/fullTextXML"
    r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT)
    if r.status_code != 200:
        return None, f"http_{r.status_code}"
    data = r.content
    if len(data) < 1000 or b"<" not in data[:100]:
        return None, "not_xml"
    try:
        ET.fromstring(data)
    except Exception as exc:
        return None, f"xml_parse:{type(exc).__name__}"
    return data, None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--batch-size", type=int, default=150)
    parser.add_argument("--sleep", type=float, default=0.2)
    args = parser.parse_args()

    con = connect()
    con.execute("pragma busy_timeout=60000")
    ensure_schema(con)
    PMC_XML_DIR.mkdir(parents=True, exist_ok=True)
    refs = remaining_pmids(con, args.limit)
    by_pmid = {str(r["pmid"]): r for r in refs}
    stats = {"candidate_pmids": len(refs), "pmcids": 0, "downloaded_xml": 0, "failed_xml": 0, "sections": 0}
    for batch in chunks(list(by_pmid), args.batch_size):
        try:
            mapping = idconv_batch(batch)
        except Exception as exc:
            print(json.dumps({"batch_error": f"{type(exc).__name__}: {exc}", "batch_first": batch[:3]}, ensure_ascii=False))
            time.sleep(args.sleep)
            continue
        stats["pmcids"] += len(mapping)
        for pmid, pmcid in mapping.items():
            ref = by_pmid.get(pmid)
            if not ref:
                continue
            try:
                data, err = fetch_xml(pmcid)
                if data:
                    path = PMC_XML_DIR / f"{pmcid}_PMID{pmid}.xml"
                    path.write_bytes(data)
                    row = {
                        "reference_id": int(ref["reference_id"]),
                        "pmid": pmid,
                        "doi": ref["doi"],
                        "pmcid": pmcid,
                        "source": "batch_europe_pmc_xml",
                        "status": "downloaded",
                        "oa_status": "oa_fulltext",
                        "xml_url": f"https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/fullTextXML",
                        "local_path": str(path),
                        "content_type": "application/xml",
                    }
                    with con:
                        fulltext_id = record_source(con, row)
                    stats["sections"] += parse_and_store_sections(con, fulltext_id, int(ref["reference_id"]), path)
                    stats["downloaded_xml"] += 1
                else:
                    row = {
                        "reference_id": int(ref["reference_id"]),
                        "pmid": pmid,
                        "doi": ref["doi"],
                        "pmcid": pmcid,
                        "source": "batch_europe_pmc_xml",
                        "status": "failed",
                        "oa_status": "pmcid_no_xml",
                        "error": err,
                    }
                    with con:
                        record_source(con, row)
                    stats["failed_xml"] += 1
            except Exception as exc:
                stats["failed_xml"] += 1
                with con:
                    record_source(con, {
                        "reference_id": int(ref["reference_id"]),
                        "pmid": pmid,
                        "doi": ref["doi"],
                        "pmcid": pmcid,
                        "source": "batch_europe_pmc_xml",
                        "status": "failed",
                        "error": f"{type(exc).__name__}: {exc}",
                    })
            time.sleep(args.sleep)
        print(json.dumps(stats, ensure_ascii=False))
    print(json.dumps(stats, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
