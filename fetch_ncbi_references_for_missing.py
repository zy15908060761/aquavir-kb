#!/usr/bin/env python3
"""
Fetch missing GenBank references for target isolates from NCBI E-utilities.

This is the online complement to recover_genbank_references.py. It only targets
analysis-scope isolates still lacking references after local flatfile recovery.
"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import sqlite3
import time
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

from recover_genbank_references import (
    base_accession,
    choose_reference,
    find_or_create_reference,
    parse_record,
)


DB_PATH = Path("crustacean_virus_core.db")
REPORTS_DIR = Path("reports")
BACKUPS_DIR = Path("backups")
FETCH_DIR = Path("external_data") / "ncbi_reference_recovery"
EUTILS_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"


def stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def backup_database(db_path: Path, ts: str) -> Path:
    BACKUPS_DIR.mkdir(exist_ok=True)
    dst = BACKUPS_DIR / f"crustacean_virus_core_before_ncbi_reference_fetch_{ts}.db"
    shutil.copy2(db_path, dst)
    return dst


def rows(conn: sqlite3.Connection, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def write_csv(path: Path, data: list[dict[str, Any]]) -> None:
    path.parent.mkdir(exist_ok=True)
    if not data:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(data[0].keys()))
        writer.writeheader()
        writer.writerows(data)


def candidate_isolates(conn: sqlite3.Connection, limit: int | None = None) -> list[dict[str, Any]]:
    sql = """
        SELECT vi.isolate_id, vi.accession, vi.master_id, vm.canonical_name
        FROM analysis_target_isolates vi
        JOIN virus_master vm ON vm.master_id = vi.master_id
        WHERE vi.reference_id IS NULL
          AND vi.accession NOT LIKE 'RDRP\\_%' ESCAPE '\\'
          AND NOT EXISTS (
              SELECT 1 FROM isolate_reference_links irl
              WHERE irl.isolate_id = vi.isolate_id
          )
        ORDER BY vm.canonical_name, vi.accession
    """
    if limit:
        sql += f" LIMIT {int(limit)}"
    return rows(conn, sql)


def split_batches(items: list[str], batch_size: int) -> list[list[str]]:
    return [items[i : i + batch_size] for i in range(0, len(items), batch_size)]


def fetch_batch(accessions: list[str], timeout: int) -> str:
    params = {
        "db": "nuccore",
        "id": ",".join(accessions),
        "rettype": "gb",
        "retmode": "text",
        "tool": "crustacean_virus_db_curation",
    }
    url = EUTILS_URL + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "crustacean-virus-db-curation/1.0 (local curation; contact unavailable)"
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def parse_fetched_records(text: str) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    chunks = text.split("\n//")
    for chunk in chunks:
        chunk = chunk.strip()
        if not chunk:
            continue
        parsed = parse_record(chunk)
        if not parsed:
            continue
        for key in {parsed.get("accession"), parsed.get("version"), base_accession(parsed.get("accession")), base_accession(parsed.get("version"))}:
            if key:
                index[key] = parsed
    return index


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=str(DB_PATH))
    parser.add_argument("--batch-size", type=int, default=80)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument("--sleep", type=float, default=0.4)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    ts = stamp()
    db_path = Path(args.db)
    REPORTS_DIR.mkdir(exist_ok=True)
    FETCH_DIR.mkdir(parents=True, exist_ok=True)
    backup_path = None if args.dry_run else backup_database(db_path, ts)

    conn = connect(db_path)
    candidates = candidate_isolates(conn, args.limit)
    if args.dry_run:
        summary = {
            "timestamp": ts,
            "dry_run": True,
            "candidate_count": len(candidates),
            "first_accessions": [c["accession"] for c in candidates[:20]],
        }
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        conn.close()
        return

    unique_accessions = sorted({c["accession"] for c in candidates})
    fetched_texts: list[str] = []
    fetch_errors: list[dict[str, Any]] = []
    for batch in split_batches(unique_accessions, args.batch_size):
        try:
            fetched_texts.append(fetch_batch(batch, args.timeout))
        except Exception as exc:
            fetch_errors.append({"batch_first": batch[0], "batch_size": len(batch), "error": str(exc)})
        time.sleep(args.sleep)

    fetched_text = "\n//\n".join(fetched_texts)
    fetched_path = FETCH_DIR / f"missing_reference_efetch_{ts}.gb"
    fetched_path.write_text(fetched_text, encoding="utf-8")
    index = parse_fetched_records(fetched_text)

    linked: list[dict[str, Any]] = []
    unmatched: list[dict[str, Any]] = []
    with conn:
        for item in candidates:
            parsed = index.get(item["accession"]) or index.get(base_accession(item["accession"]))
            ref = choose_reference(parsed["references"]) if parsed else None
            if not parsed or not ref:
                unmatched.append(item)
                continue
            reference_id = find_or_create_reference(conn, ref, parsed.get("definition") or "")
            exists = conn.execute(
                """
                SELECT 1 FROM isolate_reference_links
                WHERE isolate_id=? AND reference_id=? AND link_type='genbank_reference'
                """,
                (item["isolate_id"], reference_id),
            ).fetchone()
            if not exists:
                conn.execute(
                    """
                    INSERT INTO isolate_reference_links(
                        isolate_id, reference_id, link_type, source_table, source_field,
                        priority, evidence_status, notes
                    ) VALUES (?, ?, 'genbank_reference', 'ncbi_efetch',
                              'REFERENCE', ?, 'auto_seeded', ?)
                    """,
                    (
                        item["isolate_id"],
                        reference_id,
                        20 if ref["ref_class"] != "direct_submission" else 60,
                        f"Fetched from NCBI EFetch; reference_class={ref['ref_class']}; fetched_at={ts}",
                    ),
                )
            conn.execute(
                """
                UPDATE viral_isolates
                SET reference_id = COALESCE(reference_id, ?)
                WHERE isolate_id = ?
                """,
                (reference_id, item["isolate_id"]),
            )
            linked.append(
                {
                    **item,
                    "reference_id_recovered": reference_id,
                    "title": ref["title"],
                    "ref_class": ref["ref_class"],
                    "pmid": ref.get("pmid", ""),
                }
            )

    after_missing = conn.execute(
        """
        SELECT COUNT(*)
        FROM analysis_target_isolates vi
        WHERE vi.reference_id IS NULL
          AND NOT EXISTS (SELECT 1 FROM isolate_reference_links irl WHERE irl.isolate_id=vi.isolate_id)
        """
    ).fetchone()[0]
    integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
    fk_count = len(conn.execute("PRAGMA foreign_key_check").fetchall())
    conn.close()

    linked_csv = REPORTS_DIR / f"ncbi_reference_fetched_linked_{ts}.csv"
    unmatched_csv = REPORTS_DIR / f"ncbi_reference_fetched_unmatched_{ts}.csv"
    errors_csv = REPORTS_DIR / f"ncbi_reference_fetch_errors_{ts}.csv"
    write_csv(linked_csv, linked)
    write_csv(unmatched_csv, unmatched)
    write_csv(errors_csv, fetch_errors)
    summary = {
        "timestamp": ts,
        "dry_run": False,
        "backup_path": str(backup_path) if backup_path else None,
        "candidate_count": len(candidates),
        "unique_accessions_requested": len(unique_accessions),
        "fetched_records_indexed": len(index),
        "linked": len(linked),
        "unmatched": len(unmatched),
        "fetch_errors": len(fetch_errors),
        "target_missing_refs_after": after_missing,
        "integrity_check": integrity,
        "foreign_key_violations": fk_count,
        "artifacts": {
            "fetched_genbank": str(fetched_path),
            "linked_csv": str(linked_csv),
            "unmatched_csv": str(unmatched_csv),
            "errors_csv": str(errors_csv),
        },
    }
    summary_path = REPORTS_DIR / f"ncbi_reference_fetch_{ts}.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
