"""
Schema migration tracker for the crustacean virus database.

Tracks which build/migration scripts have been applied to the database
to prevent duplicate application and ensure correct ordering.

Usage
-----
    from schema_version import SchemaTracker

    tracker = SchemaTracker()
    tracker.ensure_table()              # create the tracking table if missing
    tracker.is_applied("my_script")     # False (first time)
    tracker.record("my_script")         # mark as applied
    tracker.is_applied("my_script")     # True
    tracker.pending(["a", "b", "c"])    # returns those not yet applied
"""
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    from db_utils import get_db, DB_PATH
except ImportError:
    # Allow standalone use before db_utils is in place
    import sqlite3
    DB_PATH = Path(__file__).resolve().parent / "crustacean_virus_core.db"
    def get_db(**kwargs):
        conn = sqlite3.connect(str(DB_PATH), timeout=60)
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA busy_timeout = 15000")
        conn.row_factory = sqlite3.Row
        return conn

SCHEMA_TABLE = "schema_version"


class SchemaTracker:
    """Track applied schema/migration scripts in the database."""

    def __init__(self, db_path=None):
        self.db_path = db_path or DB_PATH

    # ── table management ───────────────────────────────────────

    def ensure_table(self, conn=None):
        """Create the schema_version table if it does not exist."""
        close = conn is None
        if conn is None:
            conn = get_db(db_path=self.db_path)
        try:
            conn.execute(f"""
                CREATE TABLE IF NOT EXISTS {SCHEMA_TABLE} (
                    version_id    INTEGER PRIMARY KEY AUTOINCREMENT,
                    script_name   TEXT NOT NULL UNIQUE,
                    applied_at    TEXT NOT NULL DEFAULT (datetime('now')),
                    checksum      TEXT,
                    exit_code     INTEGER DEFAULT 0,
                    notes         TEXT
                )
            """)
            conn.commit()
        finally:
            if close:
                conn.close()

    def drop_table(self, conn=None):
        """Drop the tracking table (use with extreme caution)."""
        close = conn is None
        if conn is None:
            conn = get_db(db_path=self.db_path)
        try:
            conn.execute(f"DROP TABLE IF EXISTS {SCHEMA_TABLE}")
            conn.commit()
        finally:
            if close:
                conn.close()

    # ── query ──────────────────────────────────────────────────

    def is_applied(self, script_name: str) -> bool:
        """Return True if *script_name* has already been recorded."""
        conn = get_db(db_path=self.db_path)
        try:
            row = conn.execute(
                f"SELECT 1 FROM {SCHEMA_TABLE} WHERE script_name = ?",
                (script_name,),
            ).fetchone()
            return row is not None
        finally:
            conn.close()

    def applied_scripts(self) -> list[str]:
        """Return sorted list of all applied script names."""
        conn = get_db(db_path=self.db_path)
        try:
            rows = conn.execute(
                f"SELECT script_name FROM {SCHEMA_TABLE} ORDER BY version_id"
            ).fetchall()
            return [r["script_name"] for r in rows]
        finally:
            conn.close()

    def pending(self, ordered_scripts: list[str]) -> list[str]:
        """Return scripts from *ordered_scripts* that have not been applied."""
        applied = set(self.applied_scripts())
        return [s for s in ordered_scripts if s not in applied]

    # ── record ─────────────────────────────────────────────────

    def record(
        self,
        script_name: str,
        checksum: str = "",
        exit_code: int = 0,
        notes: str = "",
    ):
        """Record *script_name* as successfully applied."""
        conn = get_db(db_path=self.db_path)
        try:
            conn.execute(
                f"""
                INSERT OR IGNORE INTO {SCHEMA_TABLE}
                    (script_name, checksum, exit_code, notes)
                VALUES (?, ?, ?, ?)
                """,
                (script_name, checksum, exit_code, notes),
            )
            conn.commit()
        finally:
            conn.close()

    def remove(self, script_name: str):
        """Remove a single script from the tracking table (for re-runs)."""
        conn = get_db(db_path=self.db_path)
        try:
            conn.execute(
                f"DELETE FROM {SCHEMA_TABLE} WHERE script_name = ?",
                (script_name,),
            )
            conn.commit()
        finally:
            conn.close()

    # ── summary ────────────────────────────────────────────────

    def summary(self) -> str:
        """Return a human-readable summary of applied migrations."""
        applied = self.applied_scripts()
        if not applied:
            return "[schema] No migrations recorded yet."
        lines = [f"[schema] {len(applied)} migration(s) applied:"]
        for i, name in enumerate(applied, 1):
            lines.append(f"  {i:3d}. {name}")
        return "\n".join(lines)


# ── convenience CLI ────────────────────────────────────────────────

def main():
    """Quick CLI to inspect schema version state."""
    tracker = SchemaTracker()
    tracker.ensure_table()
    args = set(a.lower() for a in sys.argv[1:])

    conn = get_db(db_path=tracker.db_path)
    try:
        cur = conn.execute(f"SELECT * FROM {SCHEMA_TABLE} ORDER BY version_id")
        rows = cur.fetchall()
    finally:
        conn.close()

    if not rows:
        print("[schema] No migrations recorded yet.")
        return

    print(f"[schema] {len(rows)} migration(s) applied:\n")
    print(f"  {'ID':>4s}  {'Script':45s}  {'Applied At':20s}  {'Exit':>5s}  Notes")
    print(f"  {'-'*4}  {'-'*45}  {'-'*20}  {'-'*5}  {'-'*20}")
    for r in rows:
        script = r["script_name"][:45]
        applied = r["applied_at"][:19] if r["applied_at"] else ""
        exit_code = r["exit_code"]
        notes = (r["notes"] or "")[:20]
        print(f"  {r['version_id']:>4d}  {script:45s}  {applied:20s}  {exit_code:>5d}  {notes}")
    print()


if __name__ == "__main__":
    main()
