#!/usr/bin/env python3
"""
Recover isolate references from the local GenBank flatfile.

The parser is intentionally conservative. It links each accession to the first
non-direct reference where available; otherwise it links the direct GenBank
submission as sequence metadata. It deduplicates ref_literatures and records the
source in isolate_reference_links.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any


DB_PATH = Path("crustacean_virus_core.db")
GENBANK_PATH = Path("ncbi_metadata") / "crustacean_virus_raw.gb"
REPORTS_DIR = Path("reports")
BACKUPS_DIR = Path("backups")


def stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def backup_database(db_path: Path, ts: str) -> Path:
    BACKUPS_DIR.mkdir(exist_ok=True)
    dst = BACKUPS_DIR / f"crustacean_virus_core_before_genbank_reference_recovery_{ts}.db"
    shutil.copy2(db_path, dst)
    return dst


def normalize_accession(acc: str | None) -> str:
    if not acc:
        return ""
    return acc.strip().split()[0]


def base_accession(acc: str | None) -> str:
    acc = normalize_accession(acc)
    return acc.split(".")[0] if acc else ""


def clean_text(text: str | None) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def extract_year(journal: str) -> str | None:
    match = re.search(r"\((\d{4})\)", journal or "")
    if match:
        return match.group(1)
    match = re.search(r"\b(19|20)\d{2}\b", journal or "")
    return match.group(0) if match else None


def parse_reference_block(lines: list[str]) -> dict[str, str]:
    current: str | None = None
    fields: dict[str, list[str]] = {}
    for line in lines:
        if len(line) >= 12 and line[:2].strip() == "" and line[2:12].strip():
            key = line[2:12].strip()
            value = line[12:].strip()
            current = key
            fields.setdefault(key, []).append(value)
        elif current:
            fields.setdefault(current, []).append(line[12:].strip() if len(line) > 12 else line.strip())
    return {k.lower(): clean_text(" ".join(v)) for k, v in fields.items()}


def parse_record(record: str) -> dict[str, Any] | None:
    lines = record.splitlines()
    accession = None
    version = None
    definition_lines: list[str] = []
    in_definition = False
    ref_blocks: list[list[str]] = []
    current_ref: list[str] | None = None
    in_refs = False

    for line in lines:
        if line.startswith("DEFINITION"):
            in_definition = True
            definition_lines.append(line[12:].strip())
            continue
        if in_definition:
            if line.startswith("ACCESSION"):
                in_definition = False
            elif line.startswith("            "):
                definition_lines.append(line.strip())
                continue
            else:
                in_definition = False
        if line.startswith("ACCESSION"):
            accession = normalize_accession(line[12:])
        elif line.startswith("VERSION"):
            version = normalize_accession(line[12:])
        elif line.startswith("REFERENCE"):
            in_refs = True
            if current_ref:
                ref_blocks.append(current_ref)
            current_ref = [line]
        elif in_refs:
            if line.startswith("FEATURES") or line.startswith("ORIGIN"):
                if current_ref:
                    ref_blocks.append(current_ref)
                    current_ref = None
                in_refs = False
            elif current_ref is not None:
                current_ref.append(line)
    if current_ref:
        ref_blocks.append(current_ref)
    if not accession and not version:
        return None
    refs = []
    for block in ref_blocks:
        parsed = parse_reference_block(block)
        title = parsed.get("title", "")
        journal = parsed.get("journal", "")
        if not title and not journal:
            continue
        ref_class = "direct_submission" if title.lower() == "direct submission" else "published_or_unpublished"
        if title.lower() != "direct submission" and journal.lower() == "unpublished":
            ref_class = "unpublished_study"
        refs.append(
            {
                "title": title,
                "authors": parsed.get("authors", ""),
                "journal": journal,
                "pmid": parsed.get("pubmed", ""),
                "year": extract_year(journal) or "",
                "ref_class": ref_class,
            }
        )
    return {
        "accession": accession,
        "version": version,
        "definition": clean_text(" ".join(definition_lines)),
        "references": refs,
    }


def iter_genbank_records(path: Path):
    buf: list[str] = []
    with path.open("r", encoding="utf-8", errors="replace") as f:
        for line in f:
            if line.rstrip("\n") == "//":
                if buf:
                    yield "\n".join(buf)
                    buf = []
            else:
                buf.append(line.rstrip("\n"))
    if buf:
        yield "\n".join(buf)


def parse_genbank(path: Path) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for record in iter_genbank_records(path):
        parsed = parse_record(record)
        if not parsed:
            continue
        keys = {parsed.get("accession"), parsed.get("version"), base_accession(parsed.get("accession")), base_accession(parsed.get("version"))}
        for key in keys:
            if key:
                index[key] = parsed
    return index


def choose_reference(refs: list[dict[str, str]]) -> dict[str, str] | None:
    if not refs:
        return None
    for ref in refs:
        if ref["ref_class"] != "direct_submission":
            return ref
    return refs[0]


def find_or_create_reference(conn: sqlite3.Connection, ref: dict[str, str], definition: str) -> int:
    pmid = ref.get("pmid") or None
    title = clean_text(ref.get("title"))
    journal = clean_text(ref.get("journal"))
    year = ref.get("year") or None
    if pmid:
        row = conn.execute("SELECT reference_id FROM ref_literatures WHERE pmid=?", (pmid,)).fetchone()
        if row:
            return int(row[0])
    if title:
        row = conn.execute(
            """
            SELECT reference_id FROM ref_literatures
            WHERE lower(title)=lower(?) AND COALESCE(year,'')=COALESCE(?, '')
            LIMIT 1
            """,
            (title, year or ""),
        ).fetchone()
        if row:
            return int(row[0])
    keywords = f"source:genbank_raw; evidence_scope:sequence_metadata; reference_class:{ref.get('ref_class')}; definition:{definition[:180]}"
    conn.execute(
        """
        INSERT INTO ref_literatures(pmid, title, authors, journal, year, doi, abstract, keywords)
        VALUES (?, ?, ?, ?, ?, '', '', ?)
        """,
        (pmid, title, clean_text(ref.get("authors")), journal, year, keywords),
    )
    return int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])


def candidate_isolates(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    return [
        dict(r)
        for r in conn.execute(
            """
            SELECT vi.isolate_id, vi.accession, vi.master_id, vm.canonical_name, vi.reference_id
            FROM analysis_target_isolates vi
            JOIN virus_master vm ON vm.master_id = vi.master_id
            WHERE vi.reference_id IS NULL
              AND NOT EXISTS (
                  SELECT 1 FROM isolate_reference_links irl
                  WHERE irl.isolate_id = vi.isolate_id
              )
            ORDER BY vm.canonical_name, vi.accession
            """
        ).fetchall()
    ]


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
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=str(DB_PATH))
    parser.add_argument("--genbank", default=str(GENBANK_PATH))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    ts = stamp()
    db_path = Path(args.db)
    gb_path = Path(args.genbank)
    REPORTS_DIR.mkdir(exist_ok=True)
    backup_path = None if args.dry_run else backup_database(db_path, ts)

    index = parse_genbank(gb_path)
    conn = connect(db_path)
    candidates = candidate_isolates(conn)
    before_missing = len(candidates)
    linked: list[dict[str, Any]] = []
    unmatched: list[dict[str, Any]] = []

    if args.dry_run:
        for item in candidates:
            parsed = index.get(item["accession"]) or index.get(base_accession(item["accession"]))
            ref = choose_reference(parsed["references"]) if parsed else None
            if parsed and ref:
                linked.append({**item, "title": ref["title"], "ref_class": ref["ref_class"], "pmid": ref.get("pmid", "")})
            else:
                unmatched.append(item)
    else:
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
                        ) VALUES (?, ?, 'genbank_reference', 'genbank_flatfile',
                                  'REFERENCE', ?, 'auto_seeded', ?)
                        """,
                        (
                            item["isolate_id"],
                            reference_id,
                            20 if ref["ref_class"] != "direct_submission" else 60,
                            f"Recovered from {gb_path.name}; reference_class={ref['ref_class']}",
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
                linked.append({**item, "reference_id_recovered": reference_id, "title": ref["title"], "ref_class": ref["ref_class"], "pmid": ref.get("pmid", "")})

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

    linked_csv = REPORTS_DIR / f"genbank_reference_recovered_{ts}.csv"
    unmatched_csv = REPORTS_DIR / f"genbank_reference_unmatched_{ts}.csv"
    write_csv(linked_csv, linked)
    write_csv(unmatched_csv, unmatched)
    summary = {
        "timestamp": ts,
        "dry_run": args.dry_run,
        "backup_path": str(backup_path) if backup_path else None,
        "genbank_records_indexed": len(index),
        "candidate_target_isolates_missing_refs_before": before_missing,
        "linked_or_recoverable": len(linked),
        "unmatched": len(unmatched),
        "target_missing_refs_after": after_missing,
        "integrity_check": integrity,
        "foreign_key_violations": fk_count,
        "artifacts": {"linked_csv": str(linked_csv), "unmatched_csv": str(unmatched_csv)},
    }
    summary_path = REPORTS_DIR / f"genbank_reference_recovery_{ts}.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
