from __future__ import annotations

import csv
import json
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "crustacean_virus_core.db"
BACKUP_DIR = BASE_DIR / "backups"
ARCHIVE_DIR = BASE_DIR / "maintenance_archive" / "orphan_fk_cleanup"


def quote_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def table_columns(conn: sqlite3.Connection, table: str) -> list[str]:
    return [row[1] for row in conn.execute(f"PRAGMA table_info({quote_ident(table)})").fetchall()]


def main() -> None:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    BACKUP_DIR.mkdir(exist_ok=True)
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    backup = BACKUP_DIR / f"crustacean_virus_core_before_orphan_fk_cleanup_{ts}.db"
    shutil.copy2(DB_PATH, backup)

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    violations = [dict(r) for r in conn.execute("PRAGMA foreign_key_check").fetchall()]
    if not violations:
        print(json.dumps({"timestamp": ts, "backup": str(backup), "violations": 0}, ensure_ascii=False, indent=2))
        conn.close()
        return

    summary = {
        "timestamp": ts,
        "backup": str(backup),
        "initial_violations": len(violations),
        "tables": {},
    }
    archived: set[tuple[str, int]] = set()
    for iteration in range(1, 20):
        current = [dict(r) for r in conn.execute("PRAGMA foreign_key_check").fetchall()]
        if not current:
            break
        progress = 0
        by_table: dict[str, set[int]] = {}
        for item in current:
            rowid = item.get("rowid")
            table = item.get("table")
            if table and rowid is not None:
                by_table.setdefault(table, set()).add(int(rowid))
        for table, rowids in sorted(by_table.items()):
            cols = table_columns(conn, table)
            archive_path = ARCHIVE_DIR / f"{table}_orphan_rows_{ts}.csv"
            rows = []
            for rowid in sorted(rowids):
                row = conn.execute(f"SELECT rowid AS _rowid_, * FROM {quote_ident(table)} WHERE rowid = ?", (rowid,)).fetchone()
                if row and (table, rowid) not in archived:
                    rows.append(dict(row))
                    archived.add((table, rowid))
            if rows:
                fieldnames = ["_rowid_"] + cols
                file_exists = archive_path.exists()
                with archive_path.open("a", newline="", encoding="utf-8-sig") as f:
                    writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
                    if not file_exists:
                        writer.writeheader()
                    writer.writerows(rows)
            deleted = 0
            for rowid in sorted(rowids):
                try:
                    with conn:
                        deleted += conn.execute(f"DELETE FROM {quote_ident(table)} WHERE rowid = ?", (rowid,)).rowcount
                except sqlite3.IntegrityError:
                    continue
            if deleted:
                progress += deleted
                item = summary["tables"].setdefault(
                    table,
                    {
                        "violating_rowids": 0,
                        "archived_rows": 0,
                        "deleted_rows": 0,
                        "archive_path": str(archive_path.relative_to(BASE_DIR)),
                    },
                )
                item["violating_rowids"] += len(rowids)
                item["archived_rows"] += len(rows)
                item["deleted_rows"] += deleted
        if progress == 0:
            summary["stopped_iteration"] = iteration
            break

    remaining = [dict(r) for r in conn.execute("PRAGMA foreign_key_check").fetchall()]
    summary["remaining_violations"] = len(remaining)
    report_path = ARCHIVE_DIR / f"orphan_fk_cleanup_{ts}.json"
    report_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    conn.close()
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
