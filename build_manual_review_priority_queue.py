from __future__ import annotations

import csv
import json
import sqlite3
from datetime import datetime
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "crustacean_virus_core.db"
REPORT_DIR = BASE_DIR / "reports"


def priority_score(category: str, row: sqlite3.Row) -> tuple[int, str, str]:
    if category == "evidence":
        score = 40
        reasons = []
        if row["reference_id"]:
            score += 20
            reasons.append("has_reference")
        if row["virus_master_id"]:
            score += 15
            reasons.append("linked_virus_master")
        if row["evidence_strength"] == "high":
            score += 15
            reasons.append("high_strength")
        if row["host_id"] or row["isolate_id"]:
            score += 10
            reasons.append("host_or_isolate_linked")
    elif category == "diagnostic":
        score = 55
        reasons = []
        if row["reference_id"]:
            score += 20
            reasons.append("has_reference")
        if row["virus_master_id"]:
            score += 15
            reasons.append("linked_virus_master")
        if row["data_quality"] == "curated":
            score += 10
            reasons.append("curated_candidate")
        if row["method_category"] in {"PCR", "qPCR", "LAMP", "ISH"}:
            score += 5
            reasons.append("common_diagnostic")
    elif category == "ictv":
        score = 70
        reasons = ["taxonomy_release_blocker"]
        if (row["priority"] or "").upper() == "P0":
            score += 20
        elif (row["priority"] or "").upper() == "P1":
            score += 10
        if row["isolate_count"] and int(row["isolate_count"]) > 0:
            score += 10
            reasons.append("has_isolates")
    elif category == "auto_fill":
        score = 35
        reasons = ["auto_inference_needs_check"]
        if row["field_name"] in {"host_id", "country", "genome_type"}:
            score += 10
        if row["confidence"] == "medium":
            score += 10
            reasons.append("medium_confidence")
    else:
        score = 10
        reasons = []

    if score >= 80:
        bucket = "P0"
    elif score >= 60:
        bucket = "P1"
    else:
        bucket = "P2"
    return score, bucket, ";".join(reasons)


def ensure_table(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS manual_review_priority_queue (
            review_id INTEGER PRIMARY KEY AUTOINCREMENT,
            category TEXT NOT NULL,
            entity_id INTEGER NOT NULL,
            priority TEXT NOT NULL,
            score INTEGER NOT NULL,
            title TEXT,
            current_status TEXT,
            suggested_action TEXT,
            review_reason TEXT,
            source_reference_id INTEGER,
            related_master_id INTEGER,
            related_isolate_id INTEGER,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(category, entity_id)
        );
        CREATE INDEX IF NOT EXISTS idx_manual_review_priority
            ON manual_review_priority_queue(priority, score DESC, category);
        """
    )
    conn.execute("DELETE FROM manual_review_priority_queue")


def add_row(conn: sqlite3.Connection, item: dict) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO manual_review_priority_queue
            (category, entity_id, priority, score, title, current_status,
             suggested_action, review_reason, source_reference_id,
             related_master_id, related_isolate_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            item["category"],
            item["entity_id"],
            item["priority"],
            item["score"],
            item.get("title", ""),
            item.get("current_status", ""),
            item.get("suggested_action", ""),
            item.get("review_reason", ""),
            item.get("source_reference_id"),
            item.get("related_master_id"),
            item.get("related_isolate_id"),
        ),
    )


def build_queue(conn: sqlite3.Connection) -> dict[str, int]:
    ensure_table(conn)

    for r in conn.execute(
        """
        SELECT e.*, vm.canonical_name
        FROM evidence_records e
        LEFT JOIN virus_master vm ON vm.master_id = e.virus_master_id
        WHERE e.curation_status='needs_review'
        """
    ):
        score, bucket, reasons = priority_score("evidence", r)
        add_row(
            conn,
            {
                "category": "evidence",
                "entity_id": r["evidence_id"],
                "priority": bucket,
                "score": score,
                "title": f"{r['evidence_type']} | {r['canonical_name'] or 'unlinked'} | {str(r['claim'])[:120]}",
                "current_status": r["curation_status"],
                "suggested_action": "核对原文；确认 claim/value/context 是否支持；通过后改 manual_checked，否则 rejected/demoted。",
                "review_reason": reasons,
                "source_reference_id": r["reference_id"],
                "related_master_id": r["virus_master_id"],
                "related_isolate_id": r["isolate_id"],
            },
        )

    for r in conn.execute(
        """
        SELECT d.*, vm.canonical_name
        FROM diagnostic_methods d
        LEFT JOIN virus_master vm ON vm.master_id = d.virus_master_id
        WHERE d.curation_status='needs_review' AND d.data_quality <> 'placeholder'
        """
    ):
        score, bucket, reasons = priority_score("diagnostic", r)
        add_row(
            conn,
            {
                "category": "diagnostic",
                "entity_id": r["method_id"],
                "priority": bucket,
                "score": score,
                "title": f"{r['method_category']} | {r['canonical_name'] or 'unlinked'} | {r['method_name']}",
                "current_status": f"{r['data_quality']}/{r['curation_status']}",
                "suggested_action": "核对方法论文、靶基因/区域、样本类型和检测限；确认后改 curated/manual_checked。",
                "review_reason": reasons,
                "source_reference_id": r["reference_id"],
                "related_master_id": r["virus_master_id"],
                "related_isolate_id": None,
            },
        )

    for r in conn.execute(
        """
        SELECT q.*
        FROM ictv_review_priority_queue q
        """
    ):
        score, bucket, reasons = priority_score("ictv", r)
        add_row(
            conn,
            {
                "category": "ictv",
                "entity_id": r["master_id"],
                "priority": bucket,
                "score": score,
                "title": f"{r['canonical_name']} | {r['virus_family'] or ''} | {r['virus_genus'] or ''}",
                "current_status": r["priority"],
                "suggested_action": "核对 ICTV MSL/VMR 候选；确认 accepted species 或保持 pending 并写明原因。",
                "review_reason": f"{reasons}; {r['reason']}",
                "source_reference_id": None,
                "related_master_id": r["master_id"],
                "related_isolate_id": None,
            },
        )

    for r in conn.execute(
        """
        SELECT *
        FROM auto_completeness_fills
        WHERE needs_manual_review=1
        """
    ):
        score, bucket, reasons = priority_score("auto_fill", r)
        add_row(
            conn,
            {
                "category": "auto_fill",
                "entity_id": r["fill_id"],
                "priority": bucket,
                "score": score,
                "title": f"{r['entity_type']}:{r['entity_id']} {r['field_name']} -> {r['new_value']}",
                "current_status": f"{r['method']}/{r['confidence']}",
                "suggested_action": "核对 source_table/source_id；若推断错误，回改字段并保留日志。",
                "review_reason": reasons,
                "source_reference_id": None,
                "related_master_id": None,
                "related_isolate_id": r["entity_id"] if r["entity_type"] in {"viral_isolate", "isolate_curated_profile"} else None,
            },
        )

    conn.commit()
    return dict(
        conn.execute(
            """
            SELECT category || ':' || priority AS k, COUNT(*) AS n
            FROM manual_review_priority_queue
            GROUP BY category, priority
            """
        ).fetchall()
    )


def export(conn: sqlite3.Connection, summary: dict[str, int]) -> Path:
    REPORT_DIR.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path = REPORT_DIR / f"manual_review_priority_queue_{stamp}.csv"
    rows = conn.execute(
        """
        SELECT priority, score, category, entity_id, title, current_status,
               suggested_action, review_reason, source_reference_id,
               related_master_id, related_isolate_id
        FROM manual_review_priority_queue
        ORDER BY CASE priority WHEN 'P0' THEN 0 WHEN 'P1' THEN 1 ELSE 2 END,
                 score DESC, category, entity_id
        """
    ).fetchall()
    with csv_path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(rows[0].keys() if rows else ["priority"])
        for row in rows:
            writer.writerow([row[k] for k in row.keys()])

    json_path = REPORT_DIR / f"manual_review_priority_queue_{stamp}.json"
    json_path.write_text(
        json.dumps(
            {"generated_at": datetime.now().isoformat(timespec="seconds"), "summary": summary, "csv": str(csv_path)},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return csv_path


def main() -> None:
    conn = sqlite3.connect(DB_PATH, timeout=60)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys=ON")
        summary = build_queue(conn)
        path = export(conn, summary)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        print(f"[csv] {path}")
        print("integrity", conn.execute("PRAGMA integrity_check").fetchone()[0])
        print("fk", len(conn.execute("PRAGMA foreign_key_check").fetchall()))
    finally:
        conn.close()


if __name__ == "__main__":
    main()
