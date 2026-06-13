#!/usr/bin/env python3
"""
Backfill missing references for 574 analysis_target_isolates using NCBI EFetch.

Fetches GenBank flatfile records for isolates without references, extracts
REFERENCE blocks, creates ref_literatures entries, and links via
isolate_reference_links. Reuses parse_record/choose_reference/find_or_create_reference
from recover_genbank_references.py.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

from db_utils import DB_PATH, backup_database, db_connection, db_transaction
from recover_genbank_references import (
    base_accession,
    choose_reference,
    find_or_create_reference,
    parse_record,
)

BASE_DIR = Path(__file__).resolve().parent
REPORTS_DIR = BASE_DIR / "reports"
FETCH_DIR = BASE_DIR / "external_data" / "ncbi_reference_recovery"
EUTILS_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"


def stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def candidate_isolates(conn) -> list[dict[str, Any]]:
    """Return all analysis_target_isolates missing references."""
    return [
        dict(r)
        for r in conn.execute(
            """
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
        ).fetchall()
    ]


def split_batches(items: list[str], batch_size: int) -> list[list[str]]:
    return [items[i : i + batch_size] for i in range(0, len(items), batch_size)]


def fetch_batch(accessions: list[str], timeout: int) -> str:
    """Fetch GenBank flatfile for a batch of accessions via NCBI EFetch."""
    params = {
        "db": "nuccore",
        "id": ",".join(accessions),
        "rettype": "gb",
        "retmode": "text",
        "tool": "aquavir_kb_curation",
    }
    url = EUTILS_URL + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "aquavir-kb-curation/1.0 (local curation)"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def parse_fetched_records(text: str) -> dict[str, dict[str, Any]]:
    """Parse concatenated GenBank flatfile text into accession-keyed index."""
    index: dict[str, dict[str, Any]] = {}
    chunks = text.split("\n//")
    for chunk in chunks:
        chunk = chunk.strip()
        if not chunk:
            continue
        parsed = parse_record(chunk)
        if not parsed:
            continue
        for key in (
            parsed.get("accession"),
            parsed.get("version"),
            base_accession(parsed.get("accession")),
            base_accession(parsed.get("version")),
        ):
            if key:
                index[key] = parsed
    return index


def write_csv(path: Path, data: list[dict[str, Any]]) -> None:
    path.parent.mkdir(exist_ok=True)
    if not data:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(data[0].keys()))
        writer.writeheader()
        writer.writerows(data)


def main() -> None:
    p = argparse.ArgumentParser(description="Backfill missing isolate references from NCBI")
    p.add_argument("--dry-run", action="store_true", help="Preview without writing")
    p.add_argument("--batch-size", type=int, default=50, help="Accessions per NCBI request")
    p.add_argument("--sleep", type=float, default=0.35, help="Seconds between NCBI requests")
    p.add_argument("--timeout", type=int, default=60, help="NCBI request timeout seconds")
    p.add_argument("--limit", type=int, default=None, help="Limit candidates for testing")
    args = p.parse_args()

    ts = stamp()
    REPORTS_DIR.mkdir(exist_ok=True)
    FETCH_DIR.mkdir(parents=True, exist_ok=True)

    with db_connection(read_only=True) as conn:
        candidates = candidate_isolates(conn)
        if args.limit:
            candidates = candidates[: args.limit]
        before_count = len(candidates)

    if args.dry_run:
        summary = {
            "timestamp": ts,
            "dry_run": True,
            "candidate_count": before_count,
            "sample_accessions": [c["accession"] for c in candidates[:20]],
        }
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return

    # Backup before writing
    backup_path = backup_database(label="before_backfill_isolate_references")

    # Fetch all unique accessions
    unique_accessions = sorted({c["accession"] for c in candidates})
    print(f"[info] {len(candidates)} candidates, {len(unique_accessions)} unique accessions")

    fetched_texts: list[str] = []
    fetch_errors: list[dict[str, Any]] = []
    for i, batch in enumerate(split_batches(unique_accessions, args.batch_size)):
        try:
            text = fetch_batch(batch, args.timeout)
            fetched_texts.append(text)
            print(f"[fetch] batch {i+1}/{len(split_batches(unique_accessions, args.batch_size))}: "
                  f"{len(batch)} accessions OK")
        except Exception as exc:
            fetch_errors.append(
                {"batch_index": i, "batch_first": batch[0], "batch_size": len(batch), "error": str(exc)}
            )
            print(f"[fetch] batch {i+1} FAILED: {exc}", file=sys.stderr)
        time.sleep(args.sleep)

    # Save raw fetch
    fetched_text = "\n//\n".join(fetched_texts)
    fetched_path = FETCH_DIR / f"isolate_reference_efetch_{ts}.gb"
    fetched_path.write_text(fetched_text, encoding="utf-8")
    index = parse_fetched_records(fetched_text)
    print(f"[info] parsed {len(index)} records from fetch")

    # Link references
    linked: list[dict[str, Any]] = []
    unmatched: list[dict[str, Any]] = []
    refs_created = 0
    refs_found = 0

    with db_transaction() as conn:
        for item in candidates:
            acc = item["accession"]
            parsed = index.get(acc) or index.get(base_accession(acc))
            ref = choose_reference(parsed["references"]) if parsed else None
            if not parsed or not ref:
                unmatched.append(item)
                continue

            # Check if reference already exists (by PMID or title+year)
            pmid = ref.get("pmid") or None
            existing_ref_id = None
            if pmid:
                row = conn.execute(
                    "SELECT reference_id FROM ref_literatures WHERE pmid=?", (pmid,)
                ).fetchone()
                if row:
                    existing_ref_id = int(row[0])

            if existing_ref_id is None:
                reference_id = find_or_create_reference(
                    conn, ref, parsed.get("definition") or ""
                )
                refs_created += 1
            else:
                reference_id = existing_ref_id
                refs_found += 1

            # Create isolate_reference_links if not exists
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
                        f"Fetched from NCBI EFetch; reference_class={ref['ref_class']}; ts={ts}",
                    ),
                )

            # Update viral_isolates.reference_id
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
                    "isolate_id": item["isolate_id"],
                    "accession": acc,
                    "canonical_name": item["canonical_name"],
                    "reference_id": reference_id,
                    "title": ref["title"][:120],
                    "ref_class": ref["ref_class"],
                    "pmid": ref.get("pmid", ""),
                }
            )

    # Post-run verification
    with db_connection(read_only=True) as conn:
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

    # Write reports
    linked_csv = REPORTS_DIR / f"isolate_reference_backfill_linked_{ts}.csv"
    unmatched_csv = REPORTS_DIR / f"isolate_reference_backfill_unmatched_{ts}.csv"
    errors_csv = REPORTS_DIR / f"isolate_reference_backfill_errors_{ts}.csv"
    write_csv(linked_csv, linked)
    write_csv(unmatched_csv, unmatched)
    write_csv(errors_csv, fetch_errors)

    summary = {
        "timestamp": ts,
        "dry_run": False,
        "backup_path": str(backup_path),
        "candidates_before": before_count,
        "unique_accessions_fetched": len(unique_accessions),
        "records_indexed_from_fetch": len(index),
        "linked": len(linked),
        "references_created": refs_created,
        "references_found_existing": refs_found,
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
    summary_path = REPORTS_DIR / f"isolate_reference_backfill_{ts}.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
