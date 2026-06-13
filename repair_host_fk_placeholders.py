from __future__ import annotations

import csv
import sqlite3
from datetime import datetime
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "crustacean_virus_core.db"
REPORTS_DIR = BASE_DIR / "reports"


def main() -> None:
    REPORTS_DIR.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    conn = sqlite3.connect(DB_PATH, timeout=60)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys=ON")
        checks = [
            ("host_biology_profiles", "host_id"),
            ("host_scope_overrides", "host_id"),
            ("host_aliases", "host_id"),
            ("host_taxonomy_profiles", "host_id"),
            ("isolate_curated_profiles", "host_id"),
            ("host_range_evidence", "host_id"),
        ]
        missing: set[int] = set()
        details = []
        for table, column in checks:
            sql = f"""
                SELECT DISTINCT {column} AS host_id
                FROM {table}
                WHERE {column} IS NOT NULL
                  AND {column} NOT IN (SELECT host_id FROM crustacean_hosts)
            """
            for row in conn.execute(sql):
                host_id = int(row["host_id"])
                missing.add(host_id)
                details.append({"table_name": table, "column_name": column, "missing_host_id": host_id})

        for host_id in sorted(missing):
            name = f"Unresolved host placeholder {host_id}"
            conn.execute(
                """
                INSERT OR IGNORE INTO crustacean_hosts
                    (host_id, scientific_name, common_name_cn, taxon_order, taxon_family,
                     host_group, habitat, aquaculture_status, iucn_status, host_type)
                VALUES (?, ?, NULL, NULL, NULL, 'needs_review', NULL, NULL, NULL, 'placeholder')
                """,
                (host_id, name),
            )
            conn.execute(
                """
                INSERT OR IGNORE INTO manual_review_priority_queue
                    (category, entity_id, priority, score, title, current_status,
                     suggested_action, review_reason, source_reference_id, related_master_id, related_isolate_id)
                VALUES ('host_fk_placeholder', ?, 'P0', 95, ?, 'needs_review',
                        'Resolve missing crustacean_hosts row or remap child-table host_id to an accepted host.',
                        'Placeholder inserted only to restore foreign-key integrity; not a curated host.',
                        NULL, NULL, NULL)
                """,
                (host_id, name),
            )

        conn.commit()
        fk_after = len(conn.execute("PRAGMA foreign_key_check").fetchall())

        csv_path = REPORTS_DIR / f"host_fk_placeholders_{stamp}.csv"
        with csv_path.open("w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=["table_name", "column_name", "missing_host_id"])
            writer.writeheader()
            writer.writerows(details)

        print({"inserted_placeholders": len(missing), "fk_after": fk_after, "report": str(csv_path)})
    finally:
        conn.close()


if __name__ == "__main__":
    main()
