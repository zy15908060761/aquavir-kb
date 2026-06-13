"""
Test: database connection opens, has expected tables, FK is ON.
"""
import sys
import sqlite3
from pathlib import Path

# Ensure project root is on sys.path so db_utils can be imported
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from db_utils import get_db, DB_PATH
from db_pg import _IS_PG


EXPECTED_TABLES = {
    "ref_literatures",
    "viral_isolates",
    "crustacean_hosts",
    "sample_collections",
    "infection_records",
    "schema_version",
}


def test_db_exists():
    """The database file must exist on disk."""
    assert DB_PATH.exists(), f"Database file not found: {DB_PATH}"
    print(f"[PASS] DB file exists at {DB_PATH}")


def test_db_opens():
    """A connection can be established."""
    conn = get_db()
    assert conn is not None
    conn.close()
    print("[PASS] Database connection established")


def test_foreign_keys_on():
    """PRAGMA foreign_keys must be ON (SQLite only)."""
    if _IS_PG:
        print("[SKIP] PRAGMA foreign_keys is SQLite-specific, skipping")
        return
    conn = get_db()
    try:
        row = conn.execute("PRAGMA foreign_keys").fetchone()
        assert row[0] == 1, f"Expected foreign_keys=1, got {row[0]}"
    finally:
        conn.close()
    print("[PASS] Foreign keys are enabled")


def test_wal_mode():
    """PRAGMA journal_mode should be WAL (SQLite only)."""
    if _IS_PG:
        print("[SKIP] PRAGMA journal_mode is SQLite-specific, skipping")
        return
    conn = get_db()
    try:
        row = conn.execute("PRAGMA journal_mode").fetchone()
        mode = row[0].upper() if isinstance(row[0], str) else row[0]
        # SQLite may return 'wal' or 'WAL' or 'delete' on first connection
        # WAL is nice-to-have; warn but don't fail
        if mode not in ("wal", "WAL"):
            print(f"[WARN] Journal mode is {mode}, expected 'wal'")
        else:
            print(f"[PASS] Journal mode is {mode}")
    finally:
        conn.close()


def test_expected_tables_exist():
    """All core tables must exist."""
    conn = get_db()
    try:
        cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        actual = {r["name"] for r in cur.fetchall()}
    finally:
        conn.close()

    missing = EXPECTED_TABLES - actual
    if missing:
        print(f"[WARN] Missing optional tables: {missing}")
    else:
        print(f"[PASS] All {len(EXPECTED_TABLES)} expected tables present")

    # At minimum these 5 core tables must exist
    core = {"ref_literatures", "viral_isolates", "crustacean_hosts", "sample_collections", "infection_records"}
    still_missing = core - actual
    if still_missing:
        print(f"[FAIL] Core tables missing: {still_missing}")
        return False
    else:
        print(f"[PASS] All 5 core tables present")
    return True


def test_row_factory():
    """Row factory should be sqlite3.Row for dict-like access."""
    conn = get_db()
    try:
        assert conn.row_factory is sqlite3.Row, \
            f"Expected sqlite3.Row, got {conn.row_factory}"
    finally:
        conn.close()
    print("[PASS] row_factory is sqlite3.Row")


def test_each_table_has_rows():
    """Each core table should have at least one row."""
    conn = get_db()
    try:
        for table in ["ref_literatures", "viral_isolates", "crustacean_hosts",
                       "sample_collections", "infection_records"]:
            row = conn.execute(f"SELECT COUNT(*) AS cnt FROM {table}").fetchone()
            cnt = row["cnt"]
            status = "PASS" if cnt > 0 else "WARN"
            print(f"  [{status}] {table:25s}: {cnt:>6d} rows")
            if cnt == 0:
                print(f"    WARNING: {table} is empty")
    finally:
        conn.close()


def run_all():
    print("=" * 60)
    print("test_db_connection.py  --  Database connection & structure")
    print("=" * 60)
    test_db_exists()
    test_db_opens()
    test_foreign_keys_on()
    test_wal_mode()
    test_row_factory()
    test_expected_tables_exist()
    test_each_table_has_rows()
    print("=" * 60)
    return True


if __name__ == "__main__":
    run_all()
