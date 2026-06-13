#!/usr/bin/env python3
"""
Resolve the highest-priority ICTV review queue items using local MSL41 evidence.

Only exact MSL41-supported mappings are inserted. Known disease/discovery
entities absent from MSL41 are not forced into species mappings; they are marked
as unclassified_not_expected with an explicit reason.
"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any


DB_PATH = Path("crustacean_virus_core.db")
REPORTS_DIR = Path("reports")
BACKUPS_DIR = Path("backups")


MSL_MAPPINGS = {
    6: {
        "ictv_species": "Macronovirus macrobrachii",
        "matched_value": "Macrobrachium rosenbergii nodavirus; MrNV",
        "reason": "MSL41 contains Macronovirus macrobrachii; this is the accepted ICTV species for Macrobrachium rosenbergii nodavirus/MrNV.",
    },
    125: {
        "ictv_species": "Crabreovirus scylla",
        "matched_value": "Scylla serrata reovirus SZ-2007",
        "reason": "MSL41 contains Crabreovirus scylla for Scylla-associated crab reovirus.",
    },
}

UNCLASSIFIED_DECISIONS = {
    7: "Covert mortality nodavirus/CMNV is a disease-associated crustacean virus but has no exact MSL41 species entry; keep as unclassified disease entity instead of forcing a false ICTV mapping.",
    9: "Laem-Singh virus/LSNV has no exact MSL41 species entry; keep as unclassified disease entity instead of forcing a false ICTV mapping.",
    11: "Beihai shrimp virus has no exact MSL41 species entry; Beihai-like ICTV names are not exact matches to this database entry, so retain as unclassified discovery/disease context.",
    63: "Macrobrachium rosenbergii Golda virus has no exact MSL41 species entry; retain as unclassified disease/discovery entity instead of forcing a false ICTV mapping.",
}


def stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def backup_database(db_path: Path, ts: str) -> Path:
    BACKUPS_DIR.mkdir(exist_ok=True)
    dst = BACKUPS_DIR / f"crustacean_virus_core_before_critical_ictv_resolution_{ts}.db"
    shutil.copy2(db_path, dst)
    return dst


def rows(conn: sqlite3.Connection, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def write_csv(path: Path, data: list[dict[str, Any]]) -> None:
    path.parent.mkdir(exist_ok=True)
    if not data:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(data[0].keys()))
        writer.writeheader()
        writer.writerows(data)


def resolve_mappings(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    resolved: list[dict[str, Any]] = []
    for master_id, decision in MSL_MAPPINGS.items():
        ictv = conn.execute(
            "SELECT ictv_id, species, genus, family, msl_version FROM ictv_taxonomy WHERE species=?",
            (decision["ictv_species"],),
        ).fetchone()
        if not ictv:
            raise RuntimeError(f"Missing ICTV species in local MSL table: {decision['ictv_species']}")
        vm = conn.execute("SELECT * FROM virus_master WHERE master_id=?", (master_id,)).fetchone()
        conn.execute(
            """
            INSERT INTO virus_ictv_mappings(master_id, ictv_id, match_type, matched_value, match_status, confidence, notes)
            VALUES (?, ?, 'normalized_exact', ?, 'manual_checked', 'high', ?)
            ON CONFLICT(master_id, ictv_id, match_type, matched_value) DO UPDATE SET
                match_status='manual_checked',
                confidence='high',
                notes=excluded.notes
            """,
            (master_id, ictv["ictv_id"], decision["matched_value"], decision["reason"]),
        )
        conn.execute(
            """
            UPDATE virus_ictv_status
            SET ictv_status='mapped',
                mapping_count=(SELECT COUNT(*) FROM virus_ictv_mappings WHERE master_id=? AND match_status!='rejected'),
                best_confidence='high',
                reason=?,
                updated_at=CURRENT_TIMESTAMP
            WHERE master_id=?
            """,
            (master_id, decision["reason"], master_id),
        )
        old_note = vm["notes"] or ""
        note = f"ICTV MSL41 normalization: family/genus updated from {vm['virus_family'] or 'unknown'}/{vm['virus_genus'] or 'unknown'} to {ictv['family']}/{ictv['genus']}."
        new_note = old_note if note in old_note else f"{old_note}; {note}".strip("; ")
        conn.execute(
            """
            UPDATE virus_master
            SET virus_family=?, virus_genus=?, notes=?
            WHERE master_id=?
            """,
            (ictv["family"], ictv["genus"], new_note, master_id),
        )
        conn.execute("DELETE FROM ictv_review_priority_queue WHERE master_id=?", (master_id,))
        resolved.append(
            {
                "master_id": master_id,
                "canonical_name": vm["canonical_name"],
                "action": "mapped",
                "ictv_species": ictv["species"],
                "ictv_genus": ictv["genus"],
                "ictv_family": ictv["family"],
                "reason": decision["reason"],
            }
        )
    return resolved


def resolve_unclassified(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    resolved: list[dict[str, Any]] = []
    for master_id, reason in UNCLASSIFIED_DECISIONS.items():
        vm = conn.execute("SELECT * FROM virus_master WHERE master_id=?", (master_id,)).fetchone()
        conn.execute(
            """
            UPDATE virus_ictv_status
            SET ictv_status='unclassified_not_expected',
                mapping_count=0,
                best_confidence=NULL,
                reason=?,
                updated_at=CURRENT_TIMESTAMP
            WHERE master_id=?
            """,
            (reason, master_id),
        )
        conn.execute("DELETE FROM ictv_review_priority_queue WHERE master_id=?", (master_id,))
        resolved.append(
            {
                "master_id": master_id,
                "canonical_name": vm["canonical_name"],
                "action": "unclassified_not_expected",
                "ictv_species": "",
                "ictv_genus": "",
                "ictv_family": vm["virus_family"],
                "reason": reason,
            }
        )
    return resolved


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=str(DB_PATH))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    ts = stamp()
    db_path = Path(args.db)
    REPORTS_DIR.mkdir(exist_ok=True)
    backup_path = None if args.dry_run else backup_database(db_path, ts)
    conn = connect(db_path)

    before = rows(conn, "SELECT * FROM ictv_review_priority_queue WHERE priority='critical' ORDER BY isolate_count DESC")
    if args.dry_run:
        resolved = []
        for item in before:
            if item["master_id"] in MSL_MAPPINGS:
                resolved.append({**item, "planned_action": "mapped", "target": MSL_MAPPINGS[item["master_id"]]["ictv_species"]})
            elif item["master_id"] in UNCLASSIFIED_DECISIONS:
                resolved.append({**item, "planned_action": "unclassified_not_expected", "target": ""})
    else:
        with conn:
            resolved = resolve_mappings(conn) + resolve_unclassified(conn)

    after = rows(conn, "SELECT * FROM ictv_review_priority_queue WHERE priority='critical' ORDER BY isolate_count DESC")
    integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
    fk_count = len(conn.execute("PRAGMA foreign_key_check").fetchall())
    conn.close()

    csv_path = REPORTS_DIR / f"critical_ictv_resolution_{ts}.csv"
    write_csv(csv_path, resolved)
    summary = {
        "timestamp": ts,
        "dry_run": args.dry_run,
        "backup_path": str(backup_path) if backup_path else None,
        "critical_before": len(before),
        "resolved_or_planned": len(resolved),
        "critical_after": len(after),
        "integrity_check": integrity,
        "foreign_key_violations": fk_count,
        "artifact_csv": str(csv_path),
    }
    summary_path = REPORTS_DIR / f"critical_ictv_resolution_{ts}.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
