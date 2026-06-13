#!/usr/bin/env python3
"""Build fulltext acquisition worklist for abstract-mention weak evidence."""

from __future__ import annotations

import csv
import json
import sqlite3
from datetime import datetime
from pathlib import Path

from db_utils import DB_PATH


BASE_DIR = Path(__file__).resolve().parent
REPORTS_DIR = BASE_DIR / "reports"


def stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH), timeout=120)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
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
        CREATE TABLE IF NOT EXISTS abstract_mention_fulltext_worklist (
            worklist_id INTEGER PRIMARY KEY AUTOINCREMENT,
            reference_id INTEGER NOT NULL UNIQUE,
            evidence_count INTEGER NOT NULL,
            high_risk_evidence_count INTEGER NOT NULL,
            host_range_count INTEGER NOT NULL,
            pmid TEXT,
            doi TEXT,
            title TEXT,
            year TEXT,
            existing_fulltext_status TEXT,
            priority TEXT NOT NULL,
            recommended_action TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'open',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(reference_id) REFERENCES ref_literatures(reference_id)
        )
        """
    )


def build(conn: sqlite3.Connection) -> int:
    rows = conn.execute(
        """
        WITH weak AS (
            SELECT er.*
            FROM evidence_records er
            WHERE er.claim LIKE 'Abstract mentions %'
               OR er.claim LIKE 'Auto-extracted from abstract:%'
        ),
        agg AS (
            SELECT reference_id,
                   COUNT(*) AS evidence_count,
                   SUM(CASE WHEN evidence_type IN ('pathogenicity','mortality','transmission','outbreak') THEN 1 ELSE 0 END) AS high_risk_evidence_count,
                   SUM(CASE WHEN evidence_type = 'host_range' THEN 1 ELSE 0 END) AS host_range_count
            FROM weak
            WHERE reference_id IS NOT NULL
              AND reference_id NOT IN (SELECT DISTINCT reference_id FROM literature_fulltext_sections)
            GROUP BY reference_id
        ),
        status AS (
            SELECT reference_id,
                   group_concat(DISTINCT status || ':' || source) AS existing_fulltext_status
            FROM literature_fulltext_sources
            GROUP BY reference_id
        )
        SELECT a.reference_id, a.evidence_count, a.high_risk_evidence_count,
               a.host_range_count, rl.pmid, rl.doi, rl.title, rl.year,
               COALESCE(s.existing_fulltext_status, '') AS existing_fulltext_status,
               CASE
                   WHEN a.high_risk_evidence_count > 0 THEN 'P0'
                   WHEN a.evidence_count >= 100 THEN 'P1'
                   WHEN a.evidence_count >= 20 THEN 'P2'
                   ELSE 'P3'
               END AS priority,
               CASE
                   WHEN a.high_risk_evidence_count > 0 THEN 'Fetch OA fulltext first; high-risk abstract-only disease evidence needs confirmation.'
                   WHEN a.evidence_count >= 100 THEN 'Fetch OA fulltext; single reference generated many weak host_range mentions.'
                   ELSE 'Fetch OA fulltext when batch capacity is available.'
               END AS recommended_action
        FROM agg a
        JOIN ref_literatures rl ON rl.reference_id = a.reference_id
        LEFT JOIN status s ON s.reference_id = a.reference_id
        ORDER BY CASE priority WHEN 'P0' THEN 0 WHEN 'P1' THEN 1 WHEN 'P2' THEN 2 ELSE 3 END,
                 a.evidence_count DESC
        """
    ).fetchall()
    inserted = 0
    for row in rows:
        cur = conn.execute(
            """
            INSERT INTO abstract_mention_fulltext_worklist(
                reference_id, evidence_count, high_risk_evidence_count,
                host_range_count, pmid, doi, title, year, existing_fulltext_status,
                priority, recommended_action, status, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'open', CURRENT_TIMESTAMP)
            ON CONFLICT(reference_id) DO UPDATE SET
                evidence_count=excluded.evidence_count,
                high_risk_evidence_count=excluded.high_risk_evidence_count,
                host_range_count=excluded.host_range_count,
                pmid=excluded.pmid,
                doi=excluded.doi,
                title=excluded.title,
                year=excluded.year,
                existing_fulltext_status=excluded.existing_fulltext_status,
                priority=excluded.priority,
                recommended_action=excluded.recommended_action,
                updated_at=CURRENT_TIMESTAMP
            """,
            (
                row["reference_id"],
                row["evidence_count"],
                row["high_risk_evidence_count"],
                row["host_range_count"],
                row["pmid"],
                row["doi"],
                row["title"],
                row["year"],
                row["existing_fulltext_status"],
                row["priority"],
                row["recommended_action"],
            ),
        )
        inserted += cur.rowcount
    return inserted


def export(conn: sqlite3.Connection) -> dict[str, str]:
    out_dir = REPORTS_DIR / f"abstract_mention_fulltext_worklist_{stamp()}"
    out_dir.mkdir(parents=True, exist_ok=True)
    artifacts = {
        "worklist_csv": str(out_dir / "worklist.csv"),
        "summary_json": str(out_dir / "summary.json"),
        "report_md": str(out_dir / "report.md"),
    }
    rows = conn.execute(
        """
        SELECT reference_id, priority, evidence_count, high_risk_evidence_count,
               host_range_count, pmid, doi, year, title, existing_fulltext_status,
               recommended_action
        FROM abstract_mention_fulltext_worklist
        WHERE status = 'open'
        ORDER BY CASE priority WHEN 'P0' THEN 0 WHEN 'P1' THEN 1 WHEN 'P2' THEN 2 ELSE 3 END,
                 evidence_count DESC
        """
    ).fetchall()
    write_csv(Path(artifacts["worklist_csv"]), rows)
    summary_rows = conn.execute(
        """
        SELECT priority, COUNT(*) AS refs, SUM(evidence_count) AS evidence_rows
        FROM abstract_mention_fulltext_worklist
        WHERE status = 'open'
        GROUP BY priority
        ORDER BY CASE priority WHEN 'P0' THEN 0 WHEN 'P1' THEN 1 WHEN 'P2' THEN 2 ELSE 3 END
        """
    ).fetchall()
    summary = {
        "open_references": len(rows),
        "summary": [dict(r) for r in summary_rows],
        "artifacts": artifacts,
    }
    Path(artifacts["summary_json"]).write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = ["# Abstract Mention Fulltext Worklist", "", f"- Open references: `{len(rows)}`", "", "## Summary", ""]
    for row in summary_rows:
        lines.append(f"- `{row['priority']}`: {row['refs']} refs covering {row['evidence_rows']} weak evidence rows")
    lines.extend(["", "## Artifacts", ""])
    for key, value in artifacts.items():
        lines.append(f"- {key}: `{value}`")
    Path(artifacts["report_md"]).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return artifacts


def main() -> None:
    conn = connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        ensure_schema(conn)
        inserted = build(conn)
        artifacts = export(conn)
        conn.commit()
        print(json.dumps({
            "inserted_or_updated": inserted,
            "integrity_check": conn.execute("PRAGMA integrity_check").fetchone()[0],
            "foreign_key_violations": len(conn.execute("PRAGMA foreign_key_check").fetchall()),
            "artifacts": artifacts,
        }, ensure_ascii=False, indent=2))
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
