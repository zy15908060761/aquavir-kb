#!/usr/bin/env python3
"""Audit and conservatively refine promoted diagnostic methods.

This only touches records inserted by the literature promotion pilot
(`data_quality='literature_candidate'`). It does not change manually curated
diagnostic records.
"""

from __future__ import annotations

import argparse
import csv
import re
import sqlite3
from collections import defaultdict
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "crustacean_virus_core.db"
OUT_DIR = ROOT / "reports" / "literature_backfill_candidates"


STRONG_DIAGNOSTIC_RE = re.compile(
    r"\b("
    r"diagnos(?:is|tic)?|assay|method|primers?|probe|detection limit|"
    r"sensitivity|specificity|detect(?:ion|ed)?|screen(?:ing|ed)?|amplif(?:y|ied|ication)"
    r")\b",
    re.IGNORECASE,
)
WEAK_CONTEXT_RE = re.compile(
    r"\b("
    r"transcript(?:ion)? levels?|gene expression|tested positive|positive for|"
    r"in another laboratory infection|transcription was detected"
    r")\b",
    re.IGNORECASE,
)
SPECIFIC_METHODS = {
    "RT-PCR",
    "RT-qPCR",
    "qPCR",
    "real-time PCR",
    "nested PCR",
    "LAMP",
    "in situ hybridization",
    "ELISA",
    "western blot",
    "NGS",
}


def connect() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("pragma foreign_keys=on")
    return con


def load_promoted(con: sqlite3.Connection) -> list[sqlite3.Row]:
    return con.execute(
        """
        SELECT dm.*, vm.canonical_name, p.staging_id, lbc.evidence_text, lbc.signal,
               lbc.confidence AS staging_confidence, lbc.strict_score, rl.pmid, rl.title
        FROM diagnostic_methods dm
        JOIN literature_backfill_candidate_promotions p
          ON p.promoted_table='diagnostic_methods'
         AND p.promoted_record_id=dm.method_id
        JOIN literature_backfill_candidates lbc ON lbc.staging_id=p.staging_id
        LEFT JOIN virus_master vm ON vm.master_id=dm.virus_master_id
        LEFT JOIN ref_literatures rl ON rl.reference_id=dm.reference_id
        WHERE dm.data_quality='literature_candidate'
        ORDER BY dm.reference_id, dm.virus_master_id, dm.method_id
        """
    ).fetchall()


def normalize_method(row: sqlite3.Row) -> tuple[str, str, str] | None:
    method = row["method_name"]
    evidence = row["evidence_text"] or ""
    method_low = (method or "").casefold()
    ev_low = evidence.casefold()

    if method_low == "real-time pcr":
        if "reverse transcription" in ev_low or "rt-pcr" in ev_low or "rt qpcr" in ev_low or "rt-qpcr" in ev_low:
            return ("RT-qPCR", "molecular", "RT-qPCR")
        return ("qPCR", "molecular", "qPCR")
    if method_low == "qpcr":
        if "reverse transcription" in ev_low or "rt-pcr" in ev_low or "rt qpcr" in ev_low or "rt-qpcr" in ev_low:
            return ("RT-qPCR", "molecular", "RT-qPCR")
        return ("qPCR", "molecular", "qPCR")
    return None


def classify_rows(rows: list[sqlite3.Row]) -> list[dict]:
    by_context: dict[tuple, list[sqlite3.Row]] = defaultdict(list)
    for row in rows:
        key = (row["reference_id"], row["virus_master_id"], row["staging_id"])
        by_context[key].append(row)

    actions = []
    for key, group in by_context.items():
        methods = {r["method_name"] for r in group}
        has_specific = bool(methods & SPECIFIC_METHODS)
        for row in group:
            evidence = row["evidence_text"] or ""
            action = "keep"
            reason = "specific_or_acceptable_method"
            if row["method_name"] == "PCR" and has_specific:
                action = "downgrade"
                reason = "redundant_generic_pcr_with_specific_method_same_evidence"
            elif WEAK_CONTEXT_RE.search(evidence) and not STRONG_DIAGNOSTIC_RE.search(evidence):
                action = "downgrade"
                reason = "weak_experimental_detection_context"
            elif len(evidence.strip()) < 60:
                action = "downgrade"
                reason = "short_or_incomplete_evidence"

            norm = normalize_method(row)
            if norm:
                action = "normalize" if action == "keep" else action + "+normalize"
                reason += "; normalize_method_name"

            actions.append(
                {
                    "method_id": row["method_id"],
                    "staging_id": row["staging_id"],
                    "reference_id": row["reference_id"],
                    "pmid": row["pmid"],
                    "virus_master_id": row["virus_master_id"],
                    "canonical_name": row["canonical_name"],
                    "method_name": row["method_name"],
                    "method_category": row["method_category"],
                    "method_subcategory": row["method_subcategory"],
                    "target_gene_or_region": row["target_gene_or_region"],
                    "action": action,
                    "reason": reason,
                    "normalized_method_name": norm[0] if norm else "",
                    "normalized_category": norm[1] if norm else "",
                    "normalized_subcategory": norm[2] if norm else "",
                    "evidence_text": evidence,
                    "title": row["title"],
                }
            )
    return actions


def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    with path.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def apply_actions(con: sqlite3.Connection, actions: list[dict]) -> dict:
    changed = {"downgraded": 0, "normalized": 0}
    now = datetime.now().isoformat(timespec="seconds")
    with con:
        for item in actions:
            action = item["action"]
            method_id = item["method_id"]
            if "normalize" in action and item["normalized_method_name"]:
                # Avoid violating the unique diagnostic index.
                exists = con.execute(
                    """
                    SELECT 1
                    FROM diagnostic_methods
                    WHERE method_id != ?
                      AND virus_master_id=?
                      AND reference_id=?
                      AND method_category=?
                      AND lower(method_name)=lower(?)
                    LIMIT 1
                    """,
                    (
                        method_id,
                        item["virus_master_id"],
                        item["reference_id"],
                        item["normalized_category"],
                        item["normalized_method_name"],
                    ),
                ).fetchone()
                if not exists:
                    con.execute(
                        """
                        UPDATE diagnostic_methods
                        SET method_name=?,
                            method_category=?,
                            method_subcategory=?,
                            notes=coalesce(notes,'') || ?
                        WHERE method_id=?
                        """,
                        (
                            item["normalized_method_name"],
                            item["normalized_category"],
                            item["normalized_subcategory"],
                            f" [Refined {now}: normalized method name from literature pilot.]",
                            method_id,
                        ),
                    )
                    changed["normalized"] += 1

            if "downgrade" in action:
                con.execute(
                    """
                    UPDATE diagnostic_methods
                    SET curation_status='needs_review',
                        evidence_strength='low',
                        data_quality='literature_candidate_needs_review',
                        notes=coalesce(notes,'') || ?
                    WHERE method_id=?
                    """,
                    (
                        f" [Refined {now}: downgraded because {item['reason']}.]",
                        method_id,
                    ),
                )
                changed["downgraded"] += 1
    return changed


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    con = connect()
    rows = load_promoted(con)
    actions = classify_rows(rows)
    write_csv(OUT_DIR / "diagnostic_pilot_refinement_actions.csv", actions)

    summary = {
        "promoted_literature_diagnostics": len(rows),
        "keep": sum(1 for a in actions if a["action"] == "keep"),
        "downgrade": sum(1 for a in actions if "downgrade" in a["action"]),
        "normalize": sum(1 for a in actions if "normalize" in a["action"]),
        "applied": False,
        "changes": {},
    }
    if args.apply:
        summary["changes"] = apply_actions(con, actions)
        summary["applied"] = True

    (OUT_DIR / "diagnostic_pilot_refinement_summary.json").write_text(
        __import__("json").dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(__import__("json").dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
