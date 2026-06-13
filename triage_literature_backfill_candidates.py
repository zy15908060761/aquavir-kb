#!/usr/bin/env python3
"""Triage literature backfill staging candidates.

This updates only the staging table curation_status/review_notes fields. It
does not write to production biological tables.
"""

from __future__ import annotations

import csv
import json
import re
import sqlite3
from collections import Counter
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "crustacean_virus_core.db"
OUT_DIR = ROOT / "reports" / "literature_backfill_candidates"


NOISE_RE = re.compile(
    r"("
    r"no associated publication|were not available|not available|unable to link|"
    r"could not be found|not found|not shown|"
    r"95% ci|confidence interval|coverage of the reference genome|"
    r"hot chains|cold chains|"
    r"amino acid sequence; animals;|mesh terms|publication type"
    r")",
    re.IGNORECASE,
)
BACKGROUND_RE = re.compile(
    r"\b(previously|reviewed|reported previously|has been reported|"
    r"references|according to|in earlier studies|other studies)\b",
    re.IGNORECASE,
)


def connect() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def parse_values(row: sqlite3.Row) -> dict:
    try:
        return json.loads(row["extracted_values_json"] or "{}")
    except json.JSONDecodeError:
        return {}


def triage_row(row: sqlite3.Row) -> tuple[str, str]:
    text = row["evidence_text"] or ""
    values = parse_values(row)
    signal = row["signal"]
    confidence = row["confidence"]
    source_type = row["source_type"]
    strict_score = int(row["strict_score"] or 0)
    has_ref = row["reference_id"] is not None

    if NOISE_RE.search(text):
        return "rejected", "auto_reject: noise or metadata-like sentence"
    if not row["virus_master_ids"]:
        return "rejected", "auto_reject: no target virus"

    if signal == "diagnostic_method":
        if "method" not in values:
            return "rejected", "auto_reject: diagnostic candidate without method"
        if not re.search(r"\b(detect|detection|diagnos|assay|primer|amplif|RT-PCR|PCR|qPCR|LAMP|ELISA|hybridization)\b", text, re.I):
            return "needs_review", "auto_hold: method term present but diagnostic context weak"
        if confidence == "high" and strict_score >= 6 and has_ref:
            return "approved", "auto_approve: high-confidence diagnostic method candidate"
        return "needs_review", "auto_hold: diagnostic candidate needs manual check"

    if signal == "pathogenicity":
        has_quant = any(k in values for k in ["mortality_rate_min", "mortality_rate_max", "ld50_value"])
        has_lab_or_field = values.get("observation_type") in {"lab", "field"}
        if not (has_quant or has_lab_or_field):
            return "needs_review", "auto_hold: pathogenicity without quantitative/observation value"
        if BACKGROUND_RE.search(text) and source_type == "db_abstract":
            return "needs_review", "auto_hold: possible background statement"
        if confidence == "high" and strict_score >= 7 and has_ref:
            return "approved", "auto_approve: high-confidence pathogenicity candidate"
        return "needs_review", "auto_hold: pathogenicity candidate needs manual check"

    if signal == "host_infection":
        if re.search(r"\b(natural infection|experimentally infected|infected with|susceptible to|host range|carrier|reservoir)\b", text, re.I):
            if confidence == "high" and has_ref:
                return "approved", "auto_approve: explicit host-infection relation"
            return "needs_review", "auto_hold: host relation candidate needs manual check"
        return "rejected", "auto_reject: weak host-infection wording"

    if signal == "outbreak_geography":
        if "country" not in values:
            return "rejected", "auto_reject: geography candidate without country"
        if re.search(r"\b(outbreak|epidemic|prevalence|farm|pond|hatcheries|survey)\b", text, re.I):
            if confidence == "high" and has_ref:
                return "approved", "auto_approve: explicit geography/outbreak candidate"
            return "needs_review", "auto_hold: geography candidate needs manual check"
        return "rejected", "auto_reject: country mention without event context"

    if signal == "temperature_environment":
        has_temp = any(k in values for k in ["temperature_min", "temperature_max"])
        if not has_temp:
            return "rejected", "auto_reject: temperature candidate without numeric temperature"
        if confidence == "high" and strict_score >= 6 and has_ref:
            return "approved", "auto_approve: high-confidence numeric temperature candidate"
        return "needs_review", "auto_hold: temperature candidate needs manual check"

    return "needs_review", "auto_hold: unhandled signal"


def export_csv(path: Path, rows: list[sqlite3.Row]) -> None:
    if not rows:
        return
    fields = list(rows[0].keys())
    with path.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow(dict(row))


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    con = connect()
    rows = con.execute(
        """
        SELECT *
        FROM literature_backfill_candidates
        WHERE curation_status='needs_review'
          AND (
              reviewer IS NULL
              OR reviewer=''
              OR reviewer='auto_triage_v1'
          )
        """
    ).fetchall()

    changes = Counter()
    notes = Counter()
    with con:
        for row in rows:
            new_status, note = triage_row(row)
            changes[(row["curation_status"], new_status)] += 1
            notes[note] += 1
            con.execute(
                """
                UPDATE literature_backfill_candidates
                SET curation_status=?,
                    reviewer='auto_triage_v1',
                    review_notes=?,
                    updated_at=CURRENT_TIMESTAMP
                WHERE staging_id=?
                """,
                (new_status, note, row["staging_id"]),
            )

    approved = con.execute(
        """
        SELECT staging_id, reference_id, pmid, signal, confidence, strict_score,
               virus_names, host_names, extracted_values_json, evidence_text,
               title, source_type, section, review_notes
        FROM literature_backfill_candidates
        WHERE curation_status='approved'
        ORDER BY signal, strict_score DESC, reference_id
        """
    ).fetchall()
    rejected = con.execute(
        """
        SELECT staging_id, reference_id, pmid, signal, confidence, strict_score,
               virus_names, host_names, extracted_values_json, evidence_text,
               title, source_type, section, review_notes
        FROM literature_backfill_candidates
        WHERE curation_status='rejected'
        ORDER BY signal, reference_id
        """
    ).fetchall()
    needs_review = con.execute(
        """
        SELECT staging_id, reference_id, pmid, signal, confidence, strict_score,
               virus_names, host_names, extracted_values_json, evidence_text,
               title, source_type, section, review_notes
        FROM literature_backfill_candidates
        WHERE curation_status='needs_review'
        ORDER BY confidence DESC, signal, strict_score DESC, reference_id
        LIMIT 1000
        """
    ).fetchall()

    export_csv(OUT_DIR / "auto_approved_candidates.csv", approved)
    export_csv(OUT_DIR / "auto_rejected_candidates.csv", rejected)
    export_csv(OUT_DIR / "manual_review_remaining_top1000.csv", needs_review)

    status_summary = [
        dict(r)
        for r in con.execute(
            """
            SELECT curation_status, signal, confidence, COUNT(*) AS n
            FROM literature_backfill_candidates
            GROUP BY curation_status, signal, confidence
            ORDER BY curation_status, n DESC
            """
        )
    ]
    summary = {
        "triaged_at": datetime.now().isoformat(timespec="seconds"),
        "rows_seen": len(rows),
        "transition_counts": {f"{a}->{b}": n for (a, b), n in changes.items()},
        "note_counts": dict(notes.most_common()),
        "approved": len(approved),
        "rejected": len(rejected),
        "needs_review": len(needs_review),
        "status_summary": status_summary,
    }
    (OUT_DIR / "auto_triage_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
