"""Apply conservative maintenance fixes for the crustacean virus database.

The script is intentionally repeatable:
- creates a SQLite backup before writing
- archives queue/host rows before cleanup
- rebuilds the FTS search table from canonical joined data
- runs ANALYZE/optimize and verifies integrity/foreign keys
"""

from __future__ import annotations

import datetime as dt
import json
import sqlite3
from pathlib import Path


APP_DIR = Path(__file__).resolve().parent
DB_PATH = APP_DIR / "crustacean_virus_core.db"
BACKUP_DIR = APP_DIR / "backups"


HOST_FK_COLUMNS = [
    ("control_management_methods", "host_id"),
    ("evidence_records", "host_id"),
    ("host_aliases", "host_id"),
    ("host_range_evidence", "host_id"),
    ("host_review_candidates", "host_id"),
    ("host_review_candidates", "suggested_host_id"),
    ("host_taxonomy_profiles", "host_id"),
    ("infection_records", "host_id"),
    ("isolate_curated_profiles", "host_id"),
    ("outbreak_events", "host_id"),
    ("pathogenicity_evidence", "host_id"),
]


def now_stamp() -> str:
    return dt.datetime.now().strftime("%Y%m%d_%H%M%S")


def backup_database() -> Path:
    BACKUP_DIR.mkdir(exist_ok=True)
    backup_path = BACKUP_DIR / f"crustacean_virus_core_before_priority_fixes_{now_stamp()}.db"
    with sqlite3.connect(DB_PATH) as src, sqlite3.connect(backup_path) as dst:
        src.backup(dst)
    return backup_path


def table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type IN ('table', 'view') AND name = ?",
            (table,),
        ).fetchone()
        is not None
    )


def count(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> int:
    return int(conn.execute(sql, params).fetchone()[0])


def log_action(conn: sqlite3.Connection, action: str, details: dict) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS database_maintenance_log (
            log_id INTEGER PRIMARY KEY AUTOINCREMENT,
            action TEXT NOT NULL,
            details_json TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.execute(
        "INSERT INTO database_maintenance_log(action, details_json) VALUES (?, ?)",
        (action, json.dumps(details, ensure_ascii=False, sort_keys=True)),
    )


def archive_and_delete_orphan_queue(conn: sqlite3.Connection) -> int:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS curation_priority_queue_orphan_archive AS
        SELECT q.*, NULL AS archived_at, NULL AS archive_reason
        FROM curation_priority_queue q
        WHERE 0
        """
    )
    orphan_count = count(
        conn,
        """
        SELECT COUNT(*)
        FROM curation_priority_queue q
        WHERE NOT EXISTS (
            SELECT 1 FROM curation_conflicts c
            WHERE c.conflict_id = q.conflict_id
        )
        """,
    )
    if orphan_count == 0:
        return 0

    conn.execute(
        """
        INSERT INTO curation_priority_queue_orphan_archive
        SELECT q.*, CURRENT_TIMESTAMP, 'missing curation_conflicts row'
        FROM curation_priority_queue q
        WHERE NOT EXISTS (
            SELECT 1 FROM curation_conflicts c
            WHERE c.conflict_id = q.conflict_id
        )
        """
    )
    conn.execute(
        """
        DELETE FROM curation_priority_queue
        WHERE NOT EXISTS (
            SELECT 1 FROM curation_conflicts c
            WHERE c.conflict_id = curation_priority_queue.conflict_id
        )
        """
    )
    log_action(conn, "delete_orphan_curation_priority_queue", {"rows": orphan_count})
    return orphan_count


def create_host_merge_archives(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS crustacean_host_merge_archive AS
        SELECT h.*, NULL AS target_host_id, NULL AS merge_reason, NULL AS merged_at
        FROM crustacean_hosts h
        WHERE 0
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS host_reference_merge_conflict_archive (
            archive_id INTEGER PRIMARY KEY AUTOINCREMENT,
            table_name TEXT NOT NULL,
            row_json TEXT NOT NULL,
            source_host_id INTEGER NOT NULL,
            target_host_id INTEGER NOT NULL,
            merged_at TEXT DEFAULT CURRENT_TIMESTAMP,
            reason TEXT NOT NULL
        )
        """
    )


def archive_conflicting_rows(
    conn: sqlite3.Connection,
    table: str,
    column: str,
    source_host_id: int,
    target_host_id: int,
) -> int:
    rows = [
        dict(row)
        for row in conn.execute(
            f'SELECT * FROM "{table}" WHERE "{column}" = ?',
            (source_host_id,),
        )
    ]
    for row in rows:
        conn.execute(
            """
            INSERT INTO host_reference_merge_conflict_archive
                (table_name, row_json, source_host_id, target_host_id, reason)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                table,
                json.dumps(row, ensure_ascii=False, sort_keys=True),
                source_host_id,
                target_host_id,
                f"unique conflict while merging {column}",
            ),
        )
    return len(rows)


def update_host_reference(
    conn: sqlite3.Connection,
    table: str,
    column: str,
    source_host_id: int,
    target_host_id: int,
) -> tuple[int, int]:
    before = count(
        conn,
        f'SELECT COUNT(*) FROM "{table}" WHERE "{column}" = ?',
        (source_host_id,),
    )
    if before == 0:
        return 0, 0

    conn.execute("SAVEPOINT host_ref_update")
    try:
        conn.execute(
            f'UPDATE "{table}" SET "{column}" = ? WHERE "{column}" = ?',
            (target_host_id, source_host_id),
        )
        conn.execute("RELEASE host_ref_update")
        return before, 0
    except sqlite3.IntegrityError:
        conn.execute("ROLLBACK TO host_ref_update")
        conn.execute("RELEASE host_ref_update")

    conn.execute(
        f'UPDATE OR IGNORE "{table}" SET "{column}" = ? WHERE "{column}" = ?',
        (target_host_id, source_host_id),
    )
    archived = archive_conflicting_rows(conn, table, column, source_host_id, target_host_id)
    conn.execute(f'DELETE FROM "{table}" WHERE "{column}" = ?', (source_host_id,))
    return before, archived


def merge_duplicate_hosts(conn: sqlite3.Connection) -> dict:
    create_host_merge_archives(conn)
    groups = conn.execute(
        """
        SELECT lower(trim(scientific_name)) AS normalized_name,
               group_concat(host_id) AS host_ids,
               COUNT(*) AS c
        FROM crustacean_hosts
        GROUP BY normalized_name
        HAVING c > 1
        ORDER BY normalized_name
        """
    ).fetchall()

    merged_hosts = 0
    updated_refs = 0
    archived_conflicts = 0
    merge_details = []

    for group in groups:
        host_ids = [int(x) for x in group["host_ids"].split(",")]
        hosts = [
            dict(row)
            for row in conn.execute(
                f"SELECT * FROM crustacean_hosts WHERE host_id IN ({','.join('?' for _ in host_ids)})",
                host_ids,
            )
        ]
        hosts.sort(key=lambda h: (h.get("host_type") != "crustacean", h["host_id"]))
        target = hosts[0]
        for source in hosts[1:]:
            source_id = int(source["host_id"])
            target_id = int(target["host_id"])
            conn.execute(
                """
                INSERT INTO crustacean_host_merge_archive
                SELECT h.*, ?, 'case-insensitive duplicate scientific_name', CURRENT_TIMESTAMP
                FROM crustacean_hosts h
                WHERE h.host_id = ?
                """,
                (target_id, source_id),
            )
            conn.execute(
                """
                INSERT OR IGNORE INTO host_aliases
                    (host_id, alias, alias_type, match_status, confidence, is_preferred, notes)
                VALUES (?, ?, 'synonym', 'manual_checked', 'high', 0, ?)
                """,
                (
                    target_id,
                    source["scientific_name"],
                    f"Merged duplicate host_id {source_id} into {target_id}",
                ),
            )

            for table, column in HOST_FK_COLUMNS:
                changed, archived = update_host_reference(conn, table, column, source_id, target_id)
                updated_refs += changed
                archived_conflicts += archived

            conn.execute("DELETE FROM crustacean_hosts WHERE host_id = ?", (source_id,))
            merged_hosts += 1
            merge_details.append(
                {
                    "source_host_id": source_id,
                    "source_name": source["scientific_name"],
                    "target_host_id": target_id,
                    "target_name": target["scientific_name"],
                }
            )

    if merged_hosts:
        conn.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_ch_scientific_name_nocase_unique
            ON crustacean_hosts(scientific_name COLLATE NOCASE)
            """
        )
        log_action(
            conn,
            "merge_duplicate_hosts",
            {
                "merged_hosts": merged_hosts,
                "updated_references": updated_refs,
                "archived_conflicting_child_rows": archived_conflicts,
                "details": merge_details,
            },
        )
    return {
        "merged_hosts": merged_hosts,
        "updated_references": updated_refs,
        "archived_conflicting_child_rows": archived_conflicts,
    }


def fix_malformed_accessions(conn: sqlite3.Connection) -> int:
    replacements = {
        "join(PP054173": "PP054173",
        "join(ON382579": "ON382579",
    }
    changed = 0
    for old, new in replacements.items():
        exists = count(conn, "SELECT COUNT(*) FROM viral_isolates WHERE accession = ?", (old,))
        collision = count(conn, "SELECT COUNT(*) FROM viral_isolates WHERE accession = ?", (new,))
        if exists and not collision:
            conn.execute(
                """
                UPDATE viral_isolates
                SET accession = ?,
                    keywords = trim(COALESCE(keywords, '') || ' accession_corrected_from:' || ?)
                WHERE accession = ?
                """,
                (new, old, old),
            )
            changed += exists
    if changed:
        log_action(conn, "fix_malformed_accessions", {"rows": changed, "mapping": replacements})
    return changed


def rebuild_fts(conn: sqlite3.Connection) -> int:
    conn.execute("DROP TABLE IF EXISTS virus_search_fts")
    conn.execute(
        """
        CREATE VIRTUAL TABLE virus_search_fts USING fts5(
            accession,
            virus_name,
            canonical_name,
            abbreviations,
            chinese_name,
            taxon_family,
            taxon_genus,
            host_name,
            host_cn,
            country,
            tokenize = 'unicode61'
        )
        """
    )
    conn.execute(
        """
        INSERT INTO virus_search_fts(
            rowid, accession, virus_name, canonical_name, abbreviations,
            chinese_name, taxon_family, taxon_genus, host_name, host_cn, country
        )
        SELECT
            v.isolate_id,
            COALESCE(v.accession, ''),
            COALESCE(v.virus_name, ''),
            COALESCE(vm.canonical_name, ''),
            COALESCE(vm.abbreviations, ''),
            COALESCE(vm.chinese_name, ''),
            COALESCE(v.taxon_family, ''),
            COALESCE(v.taxon_genus, ''),
            COALESCE(h.scientific_name, ''),
            COALESCE(h.common_name_cn, ''),
            COALESCE(s.country, '')
        FROM viral_isolates v
        LEFT JOIN virus_master vm ON v.master_id = vm.master_id
        LEFT JOIN infection_records ir ON v.isolate_id = ir.isolate_id
        LEFT JOIN crustacean_hosts h ON ir.host_id = h.host_id
        LEFT JOIN sample_collections s ON ir.collection_id = s.collection_id
        """
    )
    rows = count(conn, "SELECT COUNT(*) FROM virus_search_fts")
    log_action(conn, "rebuild_virus_search_fts", {"rows": rows})
    return rows


def optimize_sqlite(conn: sqlite3.Connection) -> None:
    conn.execute("ANALYZE")
    conn.execute("PRAGMA optimize")
    log_action(conn, "analyze_and_optimize", {})


def verify(conn: sqlite3.Connection) -> dict:
    integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
    fk_rows = [tuple(row) for row in conn.execute("PRAGMA foreign_key_check").fetchall()]
    if integrity != "ok" or fk_rows:
        raise RuntimeError({"integrity": integrity, "foreign_key_check": fk_rows[:20]})
    return {"integrity": integrity, "foreign_key_check_rows": len(fk_rows)}


def main() -> None:
    if not DB_PATH.exists():
        raise FileNotFoundError(DB_PATH)

    backup_path = backup_database()
    summary = {"backup": str(backup_path)}

    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 10000")
        with conn:
            summary["orphan_queue_deleted"] = archive_and_delete_orphan_queue(conn)
            summary["host_merge"] = merge_duplicate_hosts(conn)
            summary["malformed_accessions_fixed"] = fix_malformed_accessions(conn)
            summary["fts_rows"] = rebuild_fts(conn)
            optimize_sqlite(conn)
            summary["verification"] = verify(conn)

    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
