#!/usr/bin/env python3
"""
Refresh scope/data-dictionary views after post-audit tier clarification.

Fixes:
- analysis_target_isolates now follows the master target flag
  (virus_master.is_crustacean_virus=1) instead of a hard-coded host phylum list.
- analysis_strict_target_isolates remains the conflict-free subset of the target view.
- v_data_dictionary is rebuilt as a dynamic schema view over sqlite_schema and
  pragma_table_info(), so newly added tables/views appear automatically.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from db_utils import DB_PATH, backup_database, db_connection, db_transaction


BASE_DIR = Path(__file__).resolve().parent
REPORTS_DIR = BASE_DIR / "reports"


TARGET_VIEW_SQL = """
CREATE VIEW analysis_target_isolates AS
    SELECT vi.*
    FROM viral_isolates vi
    JOIN isolate_curated_profiles icp ON vi.isolate_id = icp.isolate_id
    JOIN virus_master vm ON icp.master_id = vm.master_id
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


DATA_DICTIONARY_VIEW_SQL = """
CREATE VIEW v_data_dictionary AS
    SELECT
        m.name AS table_name,
        p.cid,
        p.name AS column_name,
        p.type AS data_type,
        CASE WHEN p."notnull" THEN 1 ELSE 0 END AS not_null,
        COALESCE(p.dflt_value, '') AS default_value,
        CASE WHEN p.pk THEN 1 ELSE 0 END AS is_primary_key
    FROM sqlite_schema AS m
    JOIN pragma_table_info(m.name) AS p
    WHERE m.type IN ('table', 'view')
      AND m.name NOT LIKE 'sqlite_%'
    ORDER BY m.name, p.cid
"""


def stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def scalar(conn, sql: str, params: tuple[Any, ...] = ()) -> int:
    return int(conn.execute(sql, params).fetchone()[0])


def metrics(conn) -> dict[str, Any]:
    return {
        "analysis_target_isolates": scalar(conn, "SELECT COUNT(*) FROM analysis_target_isolates"),
        "analysis_strict_target_isolates": scalar(conn, "SELECT COUNT(*) FROM analysis_strict_target_isolates"),
        "data_dictionary_rows": scalar(conn, "SELECT COUNT(*) FROM v_data_dictionary"),
        "schema_tables": scalar(
            conn,
            "SELECT COUNT(*) FROM sqlite_schema WHERE type='table' AND name NOT LIKE 'sqlite_%'",
        ),
        "schema_views": scalar(
            conn,
            "SELECT COUNT(*) FROM sqlite_schema WHERE type='view' AND name NOT LIKE 'sqlite_%'",
        ),
    }


def added_by_new_scope(conn) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT vm.host_phylum, vm.entry_type, icp.curation_status, COUNT(*) AS isolate_count
        FROM viral_isolates vi
        JOIN isolate_curated_profiles icp ON vi.isolate_id = icp.isolate_id
        JOIN virus_master vm ON icp.master_id = vm.master_id
        WHERE vm.is_crustacean_virus=1
          AND vm.entry_type NOT IN ('non_target','ictv_non_target','host_genome',
                                    'duplicate_ictv_vmr_placeholder','duplicate_alias_placeholder')
          AND vm.host_phylum NOT IN ('Arthropoda','Mollusca','Cnidaria','Echinodermata','Porifera')
        GROUP BY vm.host_phylum, vm.entry_type, icp.curation_status
        ORDER BY isolate_count DESC, vm.host_phylum, vm.entry_type
        """
    ).fetchall()
    return [dict(r) for r in rows]


def recreate_views(db_path: str | Path = DB_PATH) -> dict[str, Any]:
    ts = stamp()
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    with db_connection(db_path, read_only=True) as conn:
        before = metrics(conn)
        new_scope_distribution = added_by_new_scope(conn)

    backup = backup_database(db_path, label="before_fifth_round_scope_views")
    with db_transaction(db_path) as conn:
        conn.execute("DROP VIEW IF EXISTS analysis_strict_target_isolates")
        conn.execute("DROP VIEW IF EXISTS analysis_target_isolates")
        conn.execute(TARGET_VIEW_SQL)
        conn.execute(STRICT_VIEW_SQL)
        conn.execute("DROP VIEW IF EXISTS v_data_dictionary")
        conn.execute(DATA_DICTIONARY_VIEW_SQL)
        conn.execute(
            """
            INSERT INTO database_maintenance_log (action, details_json)
            VALUES ('fifth_round_scope_view_refresh', ?)
            """,
            (
                json.dumps(
                    {
                        "analysis_target_isolates": "uses virus_master.is_crustacean_virus=1 instead of hard-coded host phyla",
                        "v_data_dictionary": "dynamic sqlite_schema/pragma_table_info view",
                    },
                    ensure_ascii=False,
                ),
            ),
        )

    with db_connection(db_path, read_only=True) as conn:
        after = metrics(conn)
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        fk_violations = len(conn.execute("PRAGMA foreign_key_check").fetchall())
        host_phylum_distribution = [
            dict(r)
            for r in conn.execute(
                """
                SELECT vm.host_phylum, COUNT(*) AS isolate_count
                FROM analysis_target_isolates ati
                JOIN isolate_curated_profiles icp ON ati.isolate_id=icp.isolate_id
                JOIN virus_master vm ON icp.master_id=vm.master_id
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
        "new_scope_distribution_outside_old_five_phyla": new_scope_distribution,
        "target_host_phylum_distribution_after": host_phylum_distribution,
        "foreign_key_violations": fk_violations,
        "integrity_check": integrity,
    }
    out = REPORTS_DIR / f"fifth_round_scope_views_{ts}.json"
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return summary


def main() -> int:
    recreate_views()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
