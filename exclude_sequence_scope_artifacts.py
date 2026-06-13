#!/usr/bin/env python3
"""
Exclude non-viral sequence artifacts that were normalized as virus isolates.

Rows where nucleotide_records.taxonomy_lineage is not Viruses are host cDNA/EST,
synthetic constructs, patents, or host-genome/endogenous fragments. They may be
useful as background evidence, but they are not viral isolate records and must
not be counted in target isolate statistics.
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


def stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def backup_database(db_path: Path, ts: str) -> Path:
    BACKUPS_DIR.mkdir(exist_ok=True)
    dst = BACKUPS_DIR / f"crustacean_virus_core_before_sequence_artifact_exclusion_{ts}.db"
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


def candidates(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    return rows(
        conn,
        """
        SELECT vi.isolate_id, vi.accession, vi.master_id, vm.canonical_name,
               vi.virus_name, nr.organism, nr.definition, nr.taxonomy_lineage,
               nr.molecule_type, icp.profile_id, icp.dataset_tier, icp.host_is_target
        FROM analysis_target_isolates vi
        JOIN virus_master vm ON vm.master_id = vi.master_id
        JOIN nucleotide_records nr ON nr.isolate_id = vi.isolate_id
        LEFT JOIN isolate_curated_profiles icp ON icp.isolate_id = vi.isolate_id
        WHERE nr.taxonomy_lineage IS NOT NULL
          AND nr.taxonomy_lineage NOT LIKE 'Viruses%'
        ORDER BY vm.canonical_name, vi.accession
        """,
    )


def rdrp_derived_candidates(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    return rows(
        conn,
        """
        SELECT vi.isolate_id, vi.accession, vi.master_id, vm.canonical_name,
               vi.virus_name, NULL AS organism,
               'Repository-derived RdRp/protein/structure identifier, not a nucleotide isolate accession.' AS definition,
               NULL AS taxonomy_lineage, vi.molecule_type,
               icp.profile_id, icp.dataset_tier, icp.host_is_target
        FROM analysis_target_isolates vi
        JOIN virus_master vm ON vm.master_id = vi.master_id
        LEFT JOIN isolate_curated_profiles icp ON icp.isolate_id = vi.isolate_id
        WHERE vi.accession LIKE 'RDRP\\_%' ESCAPE '\\'
        ORDER BY vm.canonical_name, vi.accession
        """,
    )


def artifact_reason(item: dict[str, Any]) -> str:
    definition = (item.get("definition") or "").lower()
    organism = item.get("organism") or "non-virus organism"
    if "synthetic construct" in organism.lower() or "artificial sequences" in organism.lower():
        return "synthetic/artificial construct"
    if definition.startswith("kr ") or "diagnostic" in definition or "patent" in definition:
        return "patent/diagnostic construct sequence"
    if " cdna " in f" {definition} " or "clone" in definition or "est" in definition:
        return "host cDNA/EST clone with viral-similarity annotation"
    if "endogenous" in definition or "retrotransposon" in definition:
        return "host genomic/endogenous viral element context"
    if str(item.get("accession") or "").startswith("RDRP_"):
        return "repository-derived RdRp/protein/structure identifier"
    return f"non-viral source organism: {organism}"


def mark_excluded(conn: sqlite3.Connection, item: dict[str, Any]) -> None:
    reason = artifact_reason(item)
    note = f"Excluded by quality audit: nucleotide taxonomy is non-viral ({reason}); not a viral isolate record."
    if item["profile_id"] is None:
        conn.execute(
            """
            INSERT INTO isolate_curated_profiles (
                isolate_id, accession, master_id, canonical_virus_name, raw_virus_name,
                host_is_target, metadata_source_priority, curation_status, confidence,
                dataset_tier, notes, updated_at
            ) VALUES (?, ?, ?, ?, ?, 0, 'manual_curated', 'manual_checked', 'high',
                      'sequence_scope_artifact', ?, CURRENT_TIMESTAMP)
            """,
            (
                item["isolate_id"],
                item["accession"],
                item["master_id"],
                item["canonical_name"],
                item["virus_name"],
                note,
            ),
        )
    else:
        old_note = rows(conn, "SELECT notes FROM isolate_curated_profiles WHERE profile_id=?", (item["profile_id"],))[0].get("notes") or ""
        new_note = old_note if note in old_note else f"{old_note}; {note}".strip("; ")
        conn.execute(
            """
            UPDATE isolate_curated_profiles
            SET host_is_target = 0,
                metadata_source_priority = 'manual_curated',
                curation_status = 'manual_checked',
                confidence = 'high',
                dataset_tier = 'sequence_scope_artifact',
                notes = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE profile_id = ?
            """,
            (new_note, item["profile_id"]),
        )


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

    before_target = conn.execute("SELECT COUNT(*) FROM analysis_target_isolates").fetchone()[0]
    items = candidates(conn) + rdrp_derived_candidates(conn)
    if not args.dry_run:
        with conn:
            for item in items:
                mark_excluded(conn, item)
    after_target = conn.execute("SELECT COUNT(*) FROM analysis_target_isolates").fetchone()[0]
    integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
    fk_count = len(conn.execute("PRAGMA foreign_key_check").fetchall())
    conn.close()

    csv_path = REPORTS_DIR / f"sequence_scope_artifacts_excluded_{ts}.csv"
    write_csv(csv_path, items)
    summary = {
        "timestamp": ts,
        "dry_run": args.dry_run,
        "backup_path": str(backup_path) if backup_path else None,
        "candidate_artifacts": len(items),
        "analysis_target_isolates_before": before_target,
        "analysis_target_isolates_after": after_target,
        "integrity_check": integrity,
        "foreign_key_violations": fk_count,
        "artifact_csv": str(csv_path),
    }
    summary_path = REPORTS_DIR / f"sequence_scope_artifact_exclusion_{ts}.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
