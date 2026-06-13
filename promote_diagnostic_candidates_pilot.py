#!/usr/bin/env python3
"""Pilot promotion of approved diagnostic candidates into diagnostic_methods.

Safety constraints:
- only approved staging candidates
- only signal='diagnostic_method'
- only high confidence
- only one target virus_master_id
- requires extracted method
- max 100 inserts by default
- stores staging_id in notes and marks staging row as promoted
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "crustacean_virus_core.db"


METHOD_CATEGORY_MAP = {
    "qpcr": ("molecular", "qPCR"),
    "real-time pcr": ("molecular", "qPCR"),
    "rt-pcr": ("molecular", "RT-PCR"),
    "nested pcr": ("molecular", "nested PCR"),
    "pcr": ("molecular", "PCR"),
    "lamp": ("molecular", "LAMP"),
    "elisa": ("immunological", "ELISA"),
    "in situ hybridization": ("hybridization", "in situ hybridization"),
    "western blot": ("immunological", "western blot"),
    "ngs": ("sequencing", "NGS"),
    "metagenomic sequencing": ("sequencing", "metagenomic sequencing"),
}

STRONG_DIAGNOSTIC_RE = __import__("re").compile(
    r"\b("
    r"diagnos(?:is|tic)?|assay|method|primers?|probe|detection limit|"
    r"sensitivity|specificity|detect(?:ion|ed)?|screen(?:ing|ed)?|amplif(?:y|ied|ication)"
    r")\b",
    __import__("re").IGNORECASE,
)
WEAK_CONTEXT_RE = __import__("re").compile(
    r"\b("
    r"transcript(?:ion)? levels?|gene expression|tested positive|positive for|"
    r"in another laboratory infection|transcription was detected"
    r")\b",
    __import__("re").IGNORECASE,
)


def connect() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("pragma foreign_keys=on")
    return con


def ensure_promotion_bridge(con: sqlite3.Connection) -> None:
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS literature_backfill_candidate_promotions (
            promotion_id INTEGER PRIMARY KEY AUTOINCREMENT,
            staging_id INTEGER NOT NULL,
            promoted_table TEXT NOT NULL,
            promoted_record_id INTEGER NOT NULL,
            promoted_at TEXT DEFAULT CURRENT_TIMESTAMP,
            promotion_script TEXT,
            notes TEXT,
            FOREIGN KEY (staging_id) REFERENCES literature_backfill_candidates(staging_id),
            UNIQUE(staging_id, promoted_table, promoted_record_id)
        )
        """
    )
    con.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_lit_backfill_promotions_staging
        ON literature_backfill_candidate_promotions(staging_id)
        """
    )


def parse_values(row: sqlite3.Row) -> dict:
    try:
        return json.loads(row["extracted_values_json"] or "{}")
    except json.JSONDecodeError:
        return {}


def single_int(text: str | None) -> int | None:
    if not text:
        return None
    parts = [p.strip() for p in str(text).split("|") if p.strip()]
    if len(parts) != 1:
        return None
    try:
        return int(parts[0])
    except ValueError:
        return None


def split_methods(values: dict) -> list[str]:
    raw = values.get("method") or ""
    methods = []
    for part in raw.split("|"):
        method = part.strip()
        if method and method.casefold() not in {m.casefold() for m in methods}:
            methods.append(method)
    return prefer_specific_methods(methods)


def prefer_specific_methods(methods: list[str]) -> list[str]:
    """Keep the most specific method names from one evidence sentence."""
    keys = {m.casefold() for m in methods}
    result = list(methods)
    if "pcr" in keys and any(
        k in keys
        for k in {
            "rt-pcr",
            "qpcr",
            "real-time pcr",
            "nested pcr",
            "lamp",
            "rt-qpcr",
        }
    ):
        result = [m for m in result if m.casefold() != "pcr"]
    return result


def classify_method(method: str, evidence: str = "") -> tuple[str, str, str]:
    ev_low = evidence.casefold()
    key = method.casefold()
    if key in {"qpcr", "real-time pcr"}:
        if "rt-qpcr" in ev_low or "rt qpcr" in ev_low or "rt-qpcr" in key:
            return ("molecular", "RT-qPCR", "RT-qPCR")
        return ("molecular", "qPCR", "qPCR")
    category, subcategory = METHOD_CATEGORY_MAP.get(key, ("other", method))
    return category, subcategory, method


def candidate_rows(con: sqlite3.Connection, limit: int) -> list[sqlite3.Row]:
    return con.execute(
        """
        SELECT *
        FROM literature_backfill_candidates
        WHERE curation_status='approved'
          AND signal='diagnostic_method'
          AND confidence='high'
          AND reference_id IS NOT NULL
          AND virus_master_ids IS NOT NULL
          AND trim(virus_master_ids) != ''
        ORDER BY strict_score DESC, reference_id, staging_id
        LIMIT ?
        """,
        (limit * 4,),
    ).fetchall()


def already_exists(con: sqlite3.Connection, master_id: int, reference_id: int, method_category: str, method_name: str) -> bool:
    return (
        con.execute(
            """
            SELECT 1
            FROM diagnostic_methods
            WHERE virus_master_id=?
              AND reference_id=?
              AND method_category=?
              AND lower(method_name)=lower(?)
            LIMIT 1
            """,
            (master_id, reference_id, method_category, method_name),
        ).fetchone()
        is not None
    )


def promote(con: sqlite3.Connection, limit: int, dry_run: bool = False) -> dict:
    selected = []
    selected_keys = set()
    skipped = []
    inserted = []
    now = datetime.now().isoformat(timespec="seconds")

    for row in candidate_rows(con, limit):
        master_id = single_int(row["virus_master_ids"])
        if master_id is None:
            skipped.append({"staging_id": row["staging_id"], "reason": "not_single_virus"})
            continue
        evidence = row["evidence_text"] or ""
        if WEAK_CONTEXT_RE.search(evidence) and not STRONG_DIAGNOSTIC_RE.search(evidence):
            skipped.append({"staging_id": row["staging_id"], "reason": "weak_context"})
            continue
        values = parse_values(row)
        methods = split_methods(values)
        if not methods:
            skipped.append({"staging_id": row["staging_id"], "reason": "no_method"})
            continue
        target = values.get("target_gene_or_region") or None
        for method in methods:
            category, subcategory, normalized_method = classify_method(method, evidence)
            dedupe_key = (master_id, row["reference_id"], category, normalized_method.casefold())
            if dedupe_key in selected_keys:
                skipped.append({"staging_id": row["staging_id"], "reason": "duplicate_in_batch", "method": normalized_method})
                continue
            if already_exists(con, master_id, row["reference_id"], category, normalized_method):
                skipped.append({"staging_id": row["staging_id"], "reason": "duplicate", "method": normalized_method})
                continue
            selected_keys.add(dedupe_key)
            selected.append((row, normalized_method, category, subcategory, target))
            if len(selected) >= limit:
                break
        if len(selected) >= limit:
            break

    if dry_run:
        return {
            "dry_run": True,
            "would_insert": len(selected),
            "skipped": skipped[:50],
            "sample": [
                {
                    "staging_id": row["staging_id"],
                    "master_id": single_int(row["virus_master_ids"]),
                    "reference_id": row["reference_id"],
                    "method": method,
                    "category": category,
                    "target": target,
                }
                for row, method, category, subcategory, target in selected[:20]
            ],
        }

    with con:
        ensure_promotion_bridge(con)
        for row, method, category, subcategory, target in selected:
            notes = (
                f"Auto-promoted from literature_backfill_candidates staging_id={row['staging_id']} "
                f"at {now}. Evidence: {row['evidence_text'][:700]}"
            )
            cur = con.execute(
                """
                INSERT INTO diagnostic_methods (
                    virus_master_id, method_category, method_subcategory, method_name,
                    target_gene_or_region, reference_id, evidence_strength,
                    curation_status, notes, data_quality
                )
                VALUES (?, ?, ?, ?, ?, ?, 'low', 'auto_seeded', ?, 'literature_candidate')
                """,
                (
                    single_int(row["virus_master_ids"]),
                    category,
                    subcategory,
                    method,
                    target,
                    row["reference_id"],
                    notes,
                ),
            )
            method_id = cur.lastrowid
            con.execute(
                """
                INSERT OR IGNORE INTO literature_backfill_candidate_promotions (
                    staging_id, promoted_table, promoted_record_id, promotion_script, notes
                )
                VALUES (?, 'diagnostic_methods', ?, 'promote_diagnostic_candidates_pilot.py', ?)
                """,
                (row["staging_id"], method_id, f"Promoted diagnostic method: {method}"),
            )
            con.execute(
                """
                UPDATE literature_backfill_candidates
                SET curation_status='promoted',
                    promoted_table='diagnostic_methods',
                    promoted_record_id=NULL,
                    reviewer='promote_diagnostic_candidates_pilot.py',
                    review_notes='pilot_promoted_to_diagnostic_methods; see literature_backfill_candidate_promotions for one-to-many links',
                    updated_at=CURRENT_TIMESTAMP
                WHERE staging_id=?
                """,
                (row["staging_id"],),
            )
            inserted.append({"staging_id": row["staging_id"], "method_id": method_id, "method": method})

    return {
        "dry_run": False,
        "inserted": len(inserted),
        "inserted_rows": inserted[:50],
        "skipped": skipped[:50],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    con = connect()
    before = con.execute("SELECT COUNT(*) FROM diagnostic_methods").fetchone()[0]
    result = promote(con, args.limit, dry_run=args.dry_run)
    after = con.execute("SELECT COUNT(*) FROM diagnostic_methods").fetchone()[0]
    status = [
        dict(r)
        for r in con.execute(
            """
            SELECT curation_status, signal, COUNT(*) AS n
            FROM literature_backfill_candidates
            GROUP BY curation_status, signal
            ORDER BY curation_status, n DESC
            """
        )
    ]
    print(
        json.dumps(
            {
                "diagnostic_methods_before": before,
                "diagnostic_methods_after": after,
                "delta": after - before,
                "result": result,
                "staging_status": status,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
