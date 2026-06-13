#!/usr/bin/env python3
"""
Refine the ICTV curation status layer with conservative, reproducible rules.

This script does not create species-level ICTV mappings. It only separates
obvious discovery/unclassified entries from records that still need taxonomic
review, and creates a priority queue for the remaining unresolved masters.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import shutil
import sqlite3
from collections import Counter
from datetime import datetime
from pathlib import Path


DB_PATH = Path("crustacean_virus_core.db")
REPORTS_DIR = Path("reports")
BACKUPS_DIR = Path("backups")

DISCOVERY_PREFIXES = (
    "qianjiang ",
    "beihai ",
    "wenzhou ",
    "changjiang ",
    "hubei ",
    "shahe ",
    "wenling ",
    "sanxia ",
)

LIKE_PATTERNS = (
    "-like virus",
    " like virus",
    "marna-like",
    "picorna-like",
    "astro-like",
    "sobemo-like",
    "solemo-like",
    "yanvirus-like",
    "zhaovirus-like",
    "botourmia-like",
    "noda-like",
    "toti-like",
    "reo-like",
    "bunya-like",
    "levi-like",
    "tobamo-like",
    "tombus-like",
    "dicistro-like",
    "alphatetra-like",
    "kita-like",
)

DISCOVERY_FAMILIES = {
    "Astroviridae",
    "Botourmiaviridae",
    "Chuviridae",
    "Dicistroviridae",
    "Marnaviridae",
    "Picornaviridae",
    "Sobemoviridae",
    "Totiviridae",
    "Weiviridae",
    "Yanviridae",
    "Zhaoviridae",
}

KNOWN_REVIEW_ABBREVIATIONS = {
    "CMNV",
    "DIV1",
    "IHHNV",
    "IMNV",
    "IPV",
    "LSNV",
    "MrNV",
    "TSV",
    "WSSV",
    "YHV",
}

HOST_ONLY_NAME_RE = re.compile(
    r"^(portunus trituberculatus|procambarus clarkii|eriocheir sinensis|macrobrachium rosenbergii|penaeus monodon)$",
    re.IGNORECASE,
)


def now_stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def backup_database(db_path: Path, stamp: str) -> Path:
    BACKUPS_DIR.mkdir(exist_ok=True)
    backup_path = BACKUPS_DIR / f"crustacean_virus_core_before_ictv_refine_{stamp}.db"
    shutil.copy2(db_path, backup_path)
    return backup_path


def pending_rows(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT
            vis.master_id,
            vis.ictv_status,
            vis.reason,
            vm.canonical_name,
            vm.abbreviations,
            vm.virus_family,
            vm.virus_genus,
            vm.entry_type,
            COUNT(vi.isolate_id) AS isolate_count
        FROM virus_ictv_status vis
        JOIN virus_master vm ON vis.master_id = vm.master_id
        LEFT JOIN viral_isolates vi ON vi.master_id = vm.master_id
        WHERE vis.ictv_status = 'pending_review'
        GROUP BY vis.master_id
        ORDER BY isolate_count DESC, vm.canonical_name
        """
    ).fetchall()


def classify_unclassified_not_expected(row: sqlite3.Row) -> str | None:
    name = (row["canonical_name"] or "").strip()
    name_l = name.lower()
    family = (row["virus_family"] or "").strip()
    entry_type = (row["entry_type"] or "").strip().lower()
    isolate_count = int(row["isolate_count"] or 0)
    abbr = (row["abbreviations"] or "").strip()

    if abbr in KNOWN_REVIEW_ABBREVIATIONS:
        return None

    if entry_type == "unclassified_rna_virus":
        return "Unclassified discovery entry; ICTV species mapping is not expected."

    if "unclassified" in name_l:
        return "Name is explicitly unclassified; ICTV species mapping is not expected."

    if " sp." in name_l or name_l.endswith(" sp"):
        return "Rank-level or placeholder 'sp.' discovery name; ICTV species mapping is not expected."

    if any(pattern in name_l for pattern in LIKE_PATTERNS):
        return "Contains '-like' discovery naming; retain family-level context without forcing ICTV species mapping."

    if (
        any(name_l.startswith(prefix) for prefix in DISCOVERY_PREFIXES)
        and family in DISCOVERY_FAMILIES
        and isolate_count <= 3
    ):
        return "Low-replicate geographic discovery-series entry; ICTV species mapping is not expected yet."

    if re.search(r"\bvirus\s+\d+[a-z]?$", name_l) and isolate_count <= 2 and family in DISCOVERY_FAMILIES:
        return "Numbered discovery-series entry with low replicate count; ICTV species mapping is not expected yet."

    return None


def priority_for_pending(row: sqlite3.Row) -> tuple[str, str]:
    name = (row["canonical_name"] or "").strip()
    family = (row["virus_family"] or "").strip()
    abbr = (row["abbreviations"] or "").strip()
    isolate_count = int(row["isolate_count"] or 0)
    name_l = name.lower()

    if HOST_ONLY_NAME_RE.match(name_l):
        return "critical", "Canonical virus name appears to be only a host species name; likely master-normalization error."

    if abbr in KNOWN_REVIEW_ABBREVIATIONS:
        return "critical", "Known crustacean disease-virus abbreviation remains unmapped or unresolved against ICTV."

    if isolate_count >= 20:
        return "critical", "High isolate count unresolved; this affects many records and should be manually reviewed first."

    if isolate_count >= 5:
        return "high", "Moderate/high isolate count unresolved; prioritize before low-frequency discovery entries."

    if family in {"Nodaviridae", "Reoviridae", "Parvoviridae"}:
        return "high", "Pathogen-relevant family remains unresolved; review before publication claims."

    if "unclassified" in family.lower():
        return "medium", "Family is unclassified; keep as unresolved until literature/ICTV status is checked."

    return "low", "Low-frequency unresolved entry; lower priority after core disease viruses and malformed names."


def ensure_tables(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS ictv_review_priority_queue (
            master_id INTEGER PRIMARY KEY,
            canonical_name TEXT NOT NULL,
            abbreviations TEXT,
            virus_family TEXT,
            virus_genus TEXT,
            isolate_count INTEGER DEFAULT 0,
            priority TEXT NOT NULL,
            reason TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (master_id) REFERENCES virus_master(master_id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS virus_master_review_queue (
            master_id INTEGER PRIMARY KEY,
            canonical_name TEXT NOT NULL,
            issue_type TEXT NOT NULL,
            severity TEXT NOT NULL,
            reason TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (master_id) REFERENCES virus_master(master_id)
        )
        """
    )


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=str(DB_PATH))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    db_path = Path(args.db)
    stamp = now_stamp()
    REPORTS_DIR.mkdir(exist_ok=True)

    backup_path = None if args.dry_run else backup_database(db_path, stamp)
    conn = connect(db_path)

    before = Counter(
        dict(conn.execute("SELECT ictv_status, COUNT(*) FROM virus_ictv_status GROUP BY ictv_status").fetchall())
    )

    rows = pending_rows(conn)
    auto_updates: list[dict] = []
    pending_queue: list[dict] = []
    malformed_queue: list[dict] = []

    for row in rows:
        reason = classify_unclassified_not_expected(row)
        item = dict(row)
        if reason:
            item["new_status"] = "unclassified_not_expected"
            item["classification_reason"] = reason
            auto_updates.append(item)
            continue

        priority, priority_reason = priority_for_pending(row)
        item["priority"] = priority
        item["priority_reason"] = priority_reason
        pending_queue.append(item)
        if priority == "critical" and "host species name" in priority_reason:
            malformed_queue.append(
                {
                    "master_id": row["master_id"],
                    "canonical_name": row["canonical_name"],
                    "issue_type": "malformed_master_name",
                    "severity": "critical",
                    "reason": priority_reason,
                }
            )

    if not args.dry_run:
        ensure_tables(conn)
        with conn:
            for item in auto_updates:
                conn.execute(
                    """
                    UPDATE virus_ictv_status
                    SET ictv_status = 'unclassified_not_expected',
                        mapping_count = 0,
                        best_confidence = NULL,
                        reason = ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE master_id = ? AND ictv_status = 'pending_review'
                    """,
                    (item["classification_reason"], item["master_id"]),
                )
            conn.execute("DELETE FROM ictv_review_priority_queue")
            for item in pending_queue:
                conn.execute(
                    """
                    INSERT INTO ictv_review_priority_queue (
                        master_id, canonical_name, abbreviations, virus_family, virus_genus,
                        isolate_count, priority, reason, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    """,
                    (
                        item["master_id"],
                        item["canonical_name"],
                        item["abbreviations"],
                        item["virus_family"],
                        item["virus_genus"],
                        item["isolate_count"],
                        item["priority"],
                        item["priority_reason"],
                    ),
                )
            for item in malformed_queue:
                conn.execute(
                    """
                    INSERT INTO virus_master_review_queue (
                        master_id, canonical_name, issue_type, severity, reason, updated_at
                    ) VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(master_id) DO UPDATE SET
                        canonical_name = excluded.canonical_name,
                        issue_type = excluded.issue_type,
                        severity = excluded.severity,
                        reason = excluded.reason,
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    (
                        item["master_id"],
                        item["canonical_name"],
                        item["issue_type"],
                        item["severity"],
                        item["reason"],
                    ),
                )

    after = Counter(
        dict(conn.execute("SELECT ictv_status, COUNT(*) FROM virus_ictv_status GROUP BY ictv_status").fetchall())
    )
    integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
    fk_count = len(conn.execute("PRAGMA foreign_key_check").fetchall())
    conn.close()

    auto_csv = REPORTS_DIR / f"ictv_auto_reclassified_{stamp}.csv"
    queue_csv = REPORTS_DIR / f"ictv_review_priority_queue_{stamp}.csv"
    write_csv(auto_csv, auto_updates)
    write_csv(queue_csv, pending_queue)

    summary = {
        "timestamp": stamp,
        "dry_run": args.dry_run,
        "backup_path": str(backup_path) if backup_path else None,
        "before_status": dict(before),
        "after_status": dict(after),
        "auto_reclassified": len(auto_updates),
        "remaining_pending": len(pending_queue),
        "malformed_master_names_queued": len(malformed_queue),
        "auto_reclassified_csv": str(auto_csv),
        "review_queue_csv": str(queue_csv),
        "integrity_check": integrity,
        "foreign_key_violations": fk_count,
    }
    summary_path = REPORTS_DIR / f"ictv_status_refinement_{stamp}.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
