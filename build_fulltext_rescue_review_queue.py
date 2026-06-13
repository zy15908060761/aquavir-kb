#!/usr/bin/env python3
"""Build a deduplicated review queue for fulltext rescue candidates."""

from __future__ import annotations

import csv
import json
import sqlite3
import argparse
from datetime import datetime
from pathlib import Path
from typing import Any

from db_utils import DB_PATH


BASE_DIR = Path(__file__).resolve().parent
REPORTS_DIR = BASE_DIR / "reports"


def stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH), timeout=120)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 120000")
    return conn


def write_csv(path: Path, rows: list[sqlite3.Row]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows([dict(r) for r in rows])


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS fulltext_evidence_rescue_review_queue (
            review_id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_run_id INTEGER NOT NULL,
            source_evidence_type TEXT NOT NULL,
            reference_id INTEGER NOT NULL,
            sentence_hash TEXT NOT NULL,
            representative_candidate_id INTEGER NOT NULL,
            source_evidence_ids TEXT NOT NULL,
            source_evidence_count INTEGER NOT NULL,
            max_confidence_score INTEGER NOT NULL,
            confidence_label TEXT NOT NULL,
            priority TEXT NOT NULL,
            section_type TEXT,
            section_title TEXT,
            virus_master_ids TEXT,
            host_ids TEXT,
            matched_terms TEXT,
            sentence TEXT NOT NULL,
            review_status TEXT NOT NULL DEFAULT 'open',
            recommended_action TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(source_run_id, source_evidence_type, reference_id, sentence_hash)
        )
        """
    )


def latest_rescue_run(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT MAX(run_id) FROM fulltext_evidence_rescue_runs").fetchone()
    if row is None or row[0] is None:
        raise SystemExit("No fulltext_evidence_rescue_runs found.")
    return int(row[0])


def build_queue(conn: sqlite3.Connection, source_run_id: int, include_host_range: bool = False) -> int:
    allowed_types = "('pathogenicity', 'mortality', 'diagnosis', 'outbreak', 'transmission', 'host_range')" if include_host_range else "('pathogenicity', 'mortality', 'diagnosis', 'outbreak', 'transmission')"
    rows = conn.execute(
        f"""
        WITH ranked AS (
            SELECT c.*,
                   ROW_NUMBER() OVER (
                       PARTITION BY c.source_evidence_type, c.reference_id, c.sentence_hash
                       ORDER BY c.confidence_score DESC, c.candidate_id
                   ) AS rn
            FROM fulltext_evidence_rescue_candidates c
            WHERE c.run_id = ?
              AND c.confidence_label IN ('high', 'medium')
              AND c.source_evidence_type IN {allowed_types}
        ),
        grouped AS (
            SELECT c.source_evidence_type, c.reference_id, c.sentence_hash,
                   MIN(CASE WHEN r.rn = 1 THEN r.candidate_id END) AS representative_candidate_id,
                   group_concat(DISTINCT c.source_evidence_id) AS source_evidence_ids,
                   COUNT(DISTINCT c.source_evidence_id) AS source_evidence_count,
                   MAX(c.confidence_score) AS max_confidence_score,
                   group_concat(DISTINCT c.virus_master_id) AS virus_master_ids,
                   group_concat(DISTINCT c.host_id) AS host_ids,
                   group_concat(DISTINCT c.matched_terms) AS matched_terms
            FROM fulltext_evidence_rescue_candidates c
            JOIN ranked r ON r.candidate_id = c.candidate_id
            WHERE c.run_id = ?
              AND c.confidence_label IN ('high', 'medium')
              AND c.source_evidence_type IN {allowed_types}
            GROUP BY c.source_evidence_type, c.reference_id, c.sentence_hash
        )
        SELECT g.*, rc.section_type, rc.section_title, rc.sentence,
               CASE
                   WHEN g.max_confidence_score >= 75 THEN 'high'
                   WHEN g.max_confidence_score >= 50 THEN 'medium'
                   ELSE 'low'
               END AS confidence_label,
               CASE
                   WHEN g.source_evidence_type IN ('pathogenicity','mortality','outbreak') AND g.max_confidence_score >= 75 THEN 'P0'
                   WHEN g.source_evidence_type = 'diagnosis' AND g.max_confidence_score >= 75 THEN 'P1'
                   WHEN g.source_evidence_type = 'host_range' AND g.max_confidence_score >= 75 THEN 'P1'
                   ELSE 'P2'
               END AS priority,
               CASE
                   WHEN g.max_confidence_score >= 75 THEN 'Review for promotion to structured evidence; source sentence is high confidence.'
                   ELSE 'Review as medium-confidence replacement candidate for polluted claim.'
               END AS recommended_action
        FROM grouped g
        JOIN fulltext_evidence_rescue_candidates rc
          ON rc.candidate_id = g.representative_candidate_id
        ORDER BY
          CASE priority WHEN 'P0' THEN 0 WHEN 'P1' THEN 1 ELSE 2 END,
          g.max_confidence_score DESC,
          g.source_evidence_count DESC,
          g.source_evidence_type,
          g.reference_id
        """,
        (source_run_id, source_run_id),
    ).fetchall()

    inserted = 0
    for row in rows:
        cur = conn.execute(
            """
            INSERT OR IGNORE INTO fulltext_evidence_rescue_review_queue(
                source_run_id, source_evidence_type, reference_id, sentence_hash,
                representative_candidate_id, source_evidence_ids, source_evidence_count,
                max_confidence_score, confidence_label, priority, section_type,
                section_title, virus_master_ids, host_ids, matched_terms, sentence,
                review_status, recommended_action
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'open', ?)
            """,
            (
                source_run_id,
                row["source_evidence_type"],
                row["reference_id"],
                row["sentence_hash"],
                row["representative_candidate_id"],
                row["source_evidence_ids"],
                row["source_evidence_count"],
                row["max_confidence_score"],
                row["confidence_label"],
                row["priority"],
                row["section_type"],
                row["section_title"],
                row["virus_master_ids"],
                row["host_ids"],
                row["matched_terms"],
                row["sentence"],
                row["recommended_action"],
            ),
        )
        inserted += cur.rowcount
    return inserted


def export(conn: sqlite3.Connection, source_run_id: int, inserted: int) -> dict[str, str]:
    out_dir = REPORTS_DIR / f"fulltext_rescue_review_queue_{source_run_id}_{stamp()}"
    out_dir.mkdir(parents=True, exist_ok=True)
    artifacts = {
        "review_queue_csv": str(out_dir / "review_queue.csv"),
        "summary_json": str(out_dir / "summary.json"),
        "report_md": str(out_dir / "report.md"),
    }
    queue = conn.execute(
        """
        SELECT review_id, priority, source_evidence_type, confidence_label,
               max_confidence_score, source_evidence_count, reference_id,
               representative_candidate_id, virus_master_ids, host_ids,
               section_type, section_title, matched_terms, sentence,
               source_evidence_ids, recommended_action
        FROM fulltext_evidence_rescue_review_queue
        WHERE source_run_id = ?
        ORDER BY CASE priority WHEN 'P0' THEN 0 WHEN 'P1' THEN 1 ELSE 2 END,
                 max_confidence_score DESC, source_evidence_count DESC
        """,
        (source_run_id,),
    ).fetchall()
    write_csv(Path(artifacts["review_queue_csv"]), queue)
    summary_rows = conn.execute(
        """
        SELECT priority, source_evidence_type, confidence_label,
               COUNT(*) AS review_items,
               SUM(source_evidence_count) AS covered_source_evidence
        FROM fulltext_evidence_rescue_review_queue
        WHERE source_run_id = ?
        GROUP BY priority, source_evidence_type, confidence_label
        ORDER BY CASE priority WHEN 'P0' THEN 0 WHEN 'P1' THEN 1 ELSE 2 END,
                 source_evidence_type, confidence_label
        """,
        (source_run_id,),
    ).fetchall()
    summary = {
        "source_run_id": source_run_id,
        "inserted": inserted,
        "review_queue_total": len(queue),
        "summary": [dict(r) for r in summary_rows],
        "artifacts": artifacts,
    }
    Path(artifacts["summary_json"]).write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [
        "# Fulltext Rescue Review Queue",
        "",
        f"- Source rescue run: `{source_run_id}`",
        f"- Review items: `{len(queue)}`",
        f"- Newly inserted: `{inserted}`",
        "",
        "## Summary",
        "",
    ]
    for row in summary_rows:
        lines.append(
            f"- `{row['priority']}` `{row['source_evidence_type']}` / `{row['confidence_label']}`: "
            f"{row['review_items']} review items covering {row['covered_source_evidence']} source evidence rows"
        )
    lines.extend(["", "## Artifacts", ""])
    for key, value in artifacts.items():
        lines.append(f"- {key}: `{value}`")
    Path(artifacts["report_md"]).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return artifacts


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-run", type=int, default=None)
    parser.add_argument("--include-host-range", action="store_true")
    args = parser.parse_args()

    conn = connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        ensure_schema(conn)
        run_id = args.source_run or latest_rescue_run(conn)
        inserted = build_queue(conn, run_id, include_host_range=args.include_host_range)
        artifacts = export(conn, run_id, inserted)
        conn.commit()
        result = {
            "source_run_id": run_id,
            "inserted": inserted,
            "integrity_check": conn.execute("PRAGMA integrity_check").fetchone()[0],
            "foreign_key_violations": len(conn.execute("PRAGMA foreign_key_check").fetchall()),
            "artifacts": artifacts,
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
