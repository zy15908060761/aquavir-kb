#!/usr/bin/env python3
"""Import strict literature backfill candidates into staging tables.

This does not promote data into production biological tables. It creates a
reviewable staging layer with provenance and evidence text.
"""

from __future__ import annotations

import csv
import hashlib
import json
import sqlite3
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "crustacean_virus_core.db"
STRICT_CSV = ROOT / "reports" / "literature_backfill_candidates" / "candidate_evidence_strict.csv"


def connect() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("pragma foreign_keys=on")
    return con


def create_schema(con: sqlite3.Connection) -> None:
    con.executescript(
        """
        CREATE TABLE IF NOT EXISTS literature_backfill_runs (
            run_id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_ts TEXT NOT NULL,
            source_file TEXT NOT NULL,
            source_file_sha256 TEXT NOT NULL,
            candidate_count INTEGER NOT NULL,
            strict_policy TEXT NOT NULL,
            notes TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS literature_backfill_candidates (
            staging_id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id INTEGER NOT NULL,
            source_candidate_id INTEGER,
            reference_id INTEGER,
            pmid TEXT,
            doi TEXT,
            title TEXT,
            source_type TEXT NOT NULL,
            source_path TEXT,
            section TEXT,
            signal TEXT NOT NULL,
            target_tables TEXT,
            matched_terms TEXT,
            virus_master_ids TEXT,
            virus_names TEXT,
            host_ids TEXT,
            host_names TEXT,
            extracted_values_json TEXT,
            confidence TEXT NOT NULL CHECK (confidence IN ('high','medium','low','unknown')),
            strict_score INTEGER DEFAULT 0,
            strict_reason TEXT,
            evidence_text TEXT NOT NULL,
            dedupe_key TEXT,
            curation_status TEXT NOT NULL DEFAULT 'needs_review'
                CHECK (curation_status IN ('needs_review','approved','rejected','promoted','superseded')),
            reviewer TEXT,
            review_notes TEXT,
            promoted_table TEXT,
            promoted_record_id INTEGER,
            evidence_hash TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (run_id) REFERENCES literature_backfill_runs(run_id),
            FOREIGN KEY (reference_id) REFERENCES ref_literatures(reference_id),
            UNIQUE(reference_id, signal, virus_master_ids, host_ids, evidence_hash)
        );

        CREATE INDEX IF NOT EXISTS idx_lit_backfill_status
            ON literature_backfill_candidates(curation_status, confidence, signal);
        CREATE INDEX IF NOT EXISTS idx_lit_backfill_ref
            ON literature_backfill_candidates(reference_id);
        CREATE INDEX IF NOT EXISTS idx_lit_backfill_signal
            ON literature_backfill_candidates(signal);
        CREATE INDEX IF NOT EXISTS idx_lit_backfill_run
            ON literature_backfill_candidates(run_id);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_lit_backfill_dedupe_key
            ON literature_backfill_candidates(dedupe_key);
        """
    )

    existing_cols = {row["name"] for row in con.execute("PRAGMA table_info(literature_backfill_candidates)")}
    if "dedupe_key" not in existing_cols:
        con.execute("ALTER TABLE literature_backfill_candidates ADD COLUMN dedupe_key TEXT")
        con.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_lit_backfill_dedupe_key
            ON literature_backfill_candidates(dedupe_key)
            """
        )


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def evidence_hash(row: dict) -> str:
    payload = "|".join(
        [
            row.get("reference_id") or "",
            row.get("pmid") or "",
            row.get("signal") or "",
            row.get("virus_master_ids") or "",
            row.get("host_ids") or "",
            " ".join((row.get("evidence_text") or "").split()).lower(),
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def dedupe_key(row: dict, ev_hash: str) -> str:
    identity = (
        row.get("reference_id")
        or row.get("pmid")
        or row.get("doi")
        or row.get("source_path")
        or ""
    )
    payload = "|".join(
        [
            str(identity),
            row.get("signal") or "",
            row.get("virus_master_ids") or "",
            row.get("host_ids") or "",
            ev_hash,
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def import_rows(con: sqlite3.Connection) -> dict:
    if not STRICT_CSV.exists():
        raise FileNotFoundError(f"Missing strict candidate CSV: {STRICT_CSV}")

    with STRICT_CSV.open("r", encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))

    source_hash = file_sha256(STRICT_CSV)
    run_ts = datetime.now().isoformat(timespec="seconds")
    strict_policy = {
        "source": "candidate_evidence_strict.csv",
        "rule": "strict_candidate == 1 from extract_literature_backfill_candidates.py",
        "production_tables_changed": False,
    }
    cur = con.execute(
        """
        INSERT INTO literature_backfill_runs
            (run_ts, source_file, source_file_sha256, candidate_count, strict_policy, notes)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            run_ts,
            str(STRICT_CSV),
            source_hash,
            len(rows),
            json.dumps(strict_policy, ensure_ascii=False, sort_keys=True),
            "Imported strict literature backfill candidates for manual review.",
        ),
    )
    run_id = cur.lastrowid

    inserted = 0
    skipped = 0
    for row in rows:
        ref_id = row.get("reference_id") or None
        try:
            ref_id_int = int(ref_id) if ref_id else None
        except ValueError:
            ref_id_int = None
        params = {
            "run_id": run_id,
            "source_candidate_id": int(row["candidate_id"]) if row.get("candidate_id") else None,
            "reference_id": ref_id_int,
            "pmid": row.get("pmid") or None,
            "doi": row.get("doi") or None,
            "title": row.get("title") or None,
            "source_type": row.get("source_type") or "unknown",
            "source_path": row.get("source_path") or None,
            "section": row.get("section") or None,
            "signal": row.get("signal") or "unknown",
            "target_tables": row.get("target_tables") or None,
            "matched_terms": row.get("matched_terms") or None,
            "virus_master_ids": row.get("virus_master_ids") or None,
            "virus_names": row.get("virus_names") or None,
            "host_ids": row.get("host_ids") or None,
            "host_names": row.get("host_names") or None,
            "extracted_values_json": row.get("extracted_values_json") or "{}",
            "confidence": row.get("confidence") or "unknown",
            "strict_score": int(float(row.get("strict_score") or 0)),
            "strict_reason": row.get("strict_reason") or None,
            "evidence_text": row.get("evidence_text") or "",
            "evidence_hash": evidence_hash(row),
        }
        params["dedupe_key"] = dedupe_key(row, params["evidence_hash"])
        before = con.total_changes
        con.execute(
            """
            INSERT OR IGNORE INTO literature_backfill_candidates (
                run_id, source_candidate_id, reference_id, pmid, doi, title,
                source_type, source_path, section, signal, target_tables, matched_terms,
                virus_master_ids, virus_names, host_ids, host_names, extracted_values_json,
                confidence, strict_score, strict_reason, evidence_text, evidence_hash, dedupe_key
            )
            VALUES (
                :run_id, :source_candidate_id, :reference_id, :pmid, :doi, :title,
                :source_type, :source_path, :section, :signal, :target_tables, :matched_terms,
                :virus_master_ids, :virus_names, :host_ids, :host_names, :extracted_values_json,
                :confidence, :strict_score, :strict_reason, :evidence_text, :evidence_hash, :dedupe_key
            )
            """,
            params,
        )
        if con.total_changes > before:
            inserted += 1
        else:
            skipped += 1

    return {
        "run_id": run_id,
        "source_rows": len(rows),
        "inserted": inserted,
        "skipped_duplicates": skipped,
        "source_sha256": source_hash,
    }


def summarize(con: sqlite3.Connection) -> dict:
    def rows(sql: str) -> list[dict]:
        return [dict(r) for r in con.execute(sql)]

    return {
        "total_staging_candidates": con.execute("SELECT COUNT(*) FROM literature_backfill_candidates").fetchone()[0],
        "by_status": rows(
            """
            SELECT curation_status, COUNT(*) AS n
            FROM literature_backfill_candidates
            GROUP BY curation_status
            ORDER BY n DESC
            """
        ),
        "by_signal_confidence": rows(
            """
            SELECT signal, confidence, COUNT(*) AS n
            FROM literature_backfill_candidates
            GROUP BY signal, confidence
            ORDER BY n DESC
            """
        ),
        "by_source": rows(
            """
            SELECT source_type, COUNT(*) AS n
            FROM literature_backfill_candidates
            GROUP BY source_type
            ORDER BY n DESC
            """
        ),
    }


def main() -> None:
    con = connect()
    with con:
        create_schema(con)
        import_result = import_rows(con)
    summary = summarize(con)
    result = {"import": import_result, "summary": summary}
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
