#!/usr/bin/env python3
"""
Fix final-scan residual issues.

Scope:
- Deduplicate virus_vmr_mappings by (master_id, vmr_id), retaining the best row.
- Add ICTV mapping/status for master_id=1304 Ostreid herpesvirus 1.
- Refresh analysis_target_isolates so target isolates without curated profiles can
  still be included via viral_isolates.master_id.
- Export backup inventory; do not delete backup files.
"""
from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from db_utils import DB_PATH, backup_database, db_connection, db_transaction


BASE_DIR = Path(__file__).resolve().parent
REPORTS_DIR = BASE_DIR / "reports"
BACKUPS_DIR = BASE_DIR / "backups"


TARGET_VIEW_SQL = """
CREATE VIEW analysis_target_isolates AS
    SELECT vi.*
    FROM viral_isolates vi
    LEFT JOIN isolate_curated_profiles icp ON vi.isolate_id = icp.isolate_id
    JOIN virus_master vm ON COALESCE(icp.master_id, vi.master_id) = vm.master_id
    WHERE vm.is_crustacean_virus = 1
      AND vm.entry_type NOT IN (
          'non_target',
          'ictv_non_target',
          'host_genome',
          'duplicate_ictv_vmr_placeholder',
          'duplicate_alias_placeholder'
      )
"""


STRICT_VIEW_SQL = """
CREATE VIEW analysis_strict_target_isolates AS
    SELECT *
    FROM analysis_target_isolates
    WHERE isolate_id IN (
        SELECT isolate_id
        FROM isolate_curated_profiles
        WHERE COALESCE(curation_status, 'auto_seeded') <> 'conflict_open'
    )
"""


def stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def scalar(conn, sql: str, params: tuple[Any, ...] = ()) -> int:
    return int(conn.execute(sql, params).fetchone()[0])


def vmr_duplicate_extra_count(conn) -> int:
    return scalar(
        conn,
        """
        WITH d AS (
          SELECT master_id, vmr_id, COUNT(*) n
          FROM virus_vmr_mappings
          GROUP BY master_id, vmr_id
          HAVING COUNT(*)>1
        )
        SELECT COALESCE(SUM(n-1),0) FROM d
        """,
    )


def irl_outside_ati_count(conn) -> int:
    return scalar(
        conn,
        """
        SELECT COUNT(*)
        FROM isolate_reference_links irl
        JOIN viral_isolates vi ON vi.isolate_id=irl.isolate_id
        WHERE irl.isolate_id NOT IN (SELECT isolate_id FROM analysis_target_isolates)
        """,
    )


def target_irl_outside_ati_count(conn) -> int:
    return scalar(
        conn,
        """
        SELECT COUNT(*)
        FROM isolate_reference_links irl
        JOIN viral_isolates vi ON vi.isolate_id=irl.isolate_id
        LEFT JOIN isolate_curated_profiles icp ON icp.isolate_id=vi.isolate_id
        JOIN virus_master vm ON vm.master_id=COALESCE(icp.master_id, vi.master_id)
        WHERE irl.isolate_id NOT IN (SELECT isolate_id FROM analysis_target_isolates)
          AND vm.is_crustacean_virus=1
          AND vm.entry_type NOT IN ('non_target','ictv_non_target','host_genome',
                                    'duplicate_ictv_vmr_placeholder','duplicate_alias_placeholder')
        """,
    )


def metrics(conn) -> dict[str, Any]:
    return {
        "vmr_duplicate_extra_rows": vmr_duplicate_extra_count(conn),
        "osHV1_ictv_mappings": scalar(conn, "SELECT COUNT(*) FROM virus_ictv_mappings WHERE master_id=1304"),
        "osHV1_ictv_status_rows": scalar(conn, "SELECT COUNT(*) FROM virus_ictv_status WHERE master_id=1304"),
        "analysis_target_isolates": scalar(conn, "SELECT COUNT(*) FROM analysis_target_isolates"),
        "analysis_strict_target_isolates": scalar(conn, "SELECT COUNT(*) FROM analysis_strict_target_isolates"),
        "irl_outside_ati": irl_outside_ati_count(conn),
        "target_irl_outside_ati": target_irl_outside_ati_count(conn),
    }


def export_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        if not rows:
            fh.write("status\nempty\n")
            return
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def dedupe_vmr_mappings(conn) -> list[dict[str, Any]]:
    rows = [
        dict(r)
        for r in conn.execute(
            """
            WITH ranked AS (
              SELECT *,
                     ROW_NUMBER() OVER (
                       PARTITION BY master_id, vmr_id
                       ORDER BY
                         CASE confidence WHEN 'high' THEN 0 WHEN 'medium' THEN 1 WHEN 'low' THEN 2 ELSE 3 END,
                         CASE match_status WHEN 'manual_checked' THEN 0 WHEN 'auto_matched' THEN 1 ELSE 2 END,
                         CASE match_type WHEN 'species_exact' THEN 0 WHEN 'normalized_exact' THEN 1
                                         WHEN 'virus_name_exact' THEN 2 ELSE 3 END,
                         mapping_id
                     ) AS rn
              FROM virus_vmr_mappings
            )
            SELECT * FROM ranked WHERE rn>1
            ORDER BY master_id, vmr_id, rn, mapping_id
            """
        ).fetchall()
    ]
    for row in rows:
        conn.execute("DELETE FROM virus_vmr_mappings WHERE mapping_id=?", (row["mapping_id"],))
    return rows


def add_oshv1_ictv_status(conn) -> dict[str, Any]:
    ictv = conn.execute(
        """
        SELECT ictv_id, family, genus, species, genome_composition
        FROM ictv_taxonomy
        WHERE ictv_id=49
        """
    ).fetchone()
    if not ictv:
        raise RuntimeError("ICTV taxonomy row ictv_id=49 not found")

    source = conn.execute("SELECT source_id FROM external_sources WHERE source_key LIKE '%ictv%' ORDER BY source_id LIMIT 1").fetchone()
    source_id = int(source["source_id"]) if source else None

    conn.execute(
        """
        INSERT INTO virus_ictv_mappings
            (master_id, ictv_id, match_type, matched_value, match_status, confidence, source_id, notes)
        SELECT 1304, 49, 'virus_name_exact', 'Ostreid herpesvirus 1', 'manual_checked',
               'high', ?, 'Final scan fix: OsHV-1 is ICTV species Ostreavirus ostreidmalaco1.'
        WHERE NOT EXISTS (
            SELECT 1 FROM virus_ictv_mappings WHERE master_id=1304 AND ictv_id=49
        )
        """,
        (source_id,),
    )
    conn.execute(
        """
        INSERT INTO virus_ictv_status (master_id, ictv_status, mapping_count, best_confidence, reason, updated_at)
        VALUES (1304, 'mapped', 1, 'high',
                'Final scan fix: Ostreid herpesvirus 1 manually mapped to ICTV MSL41 species Ostreavirus ostreidmalaco1 (ictv_id=49).',
                CURRENT_TIMESTAMP)
        ON CONFLICT(master_id) DO UPDATE SET
            ictv_status='mapped',
            mapping_count=(SELECT COUNT(*) FROM virus_ictv_mappings WHERE master_id=1304),
            best_confidence='high',
            reason=excluded.reason,
            updated_at=CURRENT_TIMESTAMP
        """
    )
    conn.execute(
        """
        INSERT INTO curation_logs
            (entity_type, entity_id, action, new_value, confidence, curator, notes)
        VALUES ('virus_master', 1304, 'add_ictv_status_mapping', ?, 'high',
                'fix_final_scan_residuals.py',
                'Added missing ICTV mapping/status for OsHV-1 after reactivation.')
        """,
        (
            json.dumps(
                {
                    "ictv_id": 49,
                    "family": ictv["family"],
                    "genus": ictv["genus"],
                    "species": ictv["species"],
                    "genome_type": ictv["genome_composition"],
                    "ictv_status": "mapped",
                },
                ensure_ascii=False,
            ),
        ),
    )
    return dict(ictv)


def refresh_ati_views(conn) -> None:
    conn.execute("DROP VIEW IF EXISTS analysis_strict_target_isolates")
    conn.execute("DROP VIEW IF EXISTS analysis_target_isolates")
    conn.execute(TARGET_VIEW_SQL)
    conn.execute(STRICT_VIEW_SQL)


def backup_inventory(ts: str) -> dict[str, Any]:
    files = sorted(BACKUPS_DIR.glob("*"), key=lambda p: p.stat().st_mtime if p.is_file() else 0)
    rows = []
    for p in files:
        if not p.is_file():
            continue
        st = p.stat()
        rows.append(
            {
                "name": p.name,
                "bytes": st.st_size,
                "mb": round(st.st_size / 1024 / 1024, 2),
                "mtime": datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds"),
            }
        )
    path = REPORTS_DIR / f"backup_inventory_{ts}.csv"
    export_rows(path, rows)
    return {
        "file_count": len(rows),
        "total_bytes": sum(r["bytes"] for r in rows),
        "total_gb": round(sum(r["bytes"] for r in rows) / 1024 / 1024 / 1024, 2),
        "inventory_csv": str(path),
        "recommendation": "Do not delete automatically. Keep key pre-R1/final backups locally and move intermediate 2026-06-01 repair backups to external storage before release.",
    }


def main() -> int:
    ts = stamp()
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    with db_connection(DB_PATH, read_only=True) as conn:
        before = metrics(conn)

    backup = backup_database(DB_PATH, label="before_final_scan_residuals")
    with db_transaction(DB_PATH) as conn:
        deleted_vmr_rows = dedupe_vmr_mappings(conn)
        oshv_ictv = add_oshv1_ictv_status(conn)
        refresh_ati_views(conn)
        conn.execute(
            """
            INSERT INTO database_maintenance_log (action, details_json)
            VALUES ('final_scan_residual_fixes', ?)
            """,
            (
                json.dumps(
                    {
                        "vmr_duplicate_rows_removed": len(deleted_vmr_rows),
                        "oshv1_ictv": oshv_ictv,
                        "ati_view": "uses isolate_curated_profiles when present, otherwise viral_isolates.master_id",
                    },
                    ensure_ascii=False,
                ),
            ),
        )

    deleted_path = REPORTS_DIR / f"final_scan_vmr_deduplicated_rows_{ts}.csv"
    export_rows(deleted_path, deleted_vmr_rows)

    with db_connection(DB_PATH, read_only=True) as conn:
        after = metrics(conn)
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        fk = len(conn.execute("PRAGMA foreign_key_check").fetchall())
        ati_host_phyla = [
            dict(r)
            for r in conn.execute(
                """
                SELECT vm.host_phylum, COUNT(*) AS isolate_count
                FROM analysis_target_isolates ati
                LEFT JOIN isolate_curated_profiles icp ON icp.isolate_id=ati.isolate_id
                JOIN virus_master vm ON vm.master_id=COALESCE(icp.master_id, ati.master_id)
                GROUP BY vm.host_phylum
                ORDER BY isolate_count DESC, vm.host_phylum
                """
            ).fetchall()
        ]

    summary = {
        "timestamp": ts,
        "backup": str(backup),
        "before": before,
        "after": after,
        "delta": {k: after[k] - before[k] for k in before if isinstance(before[k], int)},
        "vmr_deduplicated_rows_csv": str(deleted_path),
        "backup_inventory": backup_inventory(ts),
        "ati_host_phylum_distribution_after": ati_host_phyla,
        "foreign_key_violations": fk,
        "integrity_check": integrity,
    }
    out = REPORTS_DIR / f"final_scan_residuals_{ts}.json"
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
