"""
Database connection utilities for the Crustacean Virus Database project.

Provides a standardized connection factory with proper PRAGMA settings
(foreign_keys, WAL mode, busy_timeout) so that every script gets consistent,
safe defaults instead of copy-pasted or missing PRAGMA lines.
"""

import shutil
import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Optional, Union

# Default database path -- overridable per call
DB_PATH = Path(__file__).resolve().parent / "crustacean_virus_core.db"
DEFAULT_DB_PATH = DB_PATH


# ── Shortcut aliases for common use ────────────────────────────────

def get_db(db_path=None, foreign_keys=True, wal_mode=True, timeout=60):
    """Standardized DB connection. ALWAYS enables FK by default.

    Parameters
    ----------
    db_path : str or Path, optional
        Path to the SQLite database file. Defaults to crustacean_virus_core.db
        in the project root.
    foreign_keys : bool
        Enable PRAGMA foreign_keys = ON (default True).
    wal_mode : bool
        Enable WAL journal mode (default True).
    timeout : int
        Connection timeout in seconds (default 60).

    Returns
    -------
    sqlite3.Connection
    """
    conn = sqlite3.connect(str(db_path or DB_PATH), timeout=timeout)
    if foreign_keys:
        conn.execute("PRAGMA foreign_keys = ON")
    if wal_mode:
        conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 15000")
    conn.row_factory = sqlite3.Row
    return conn


def get_db_cursor(conn=None):
    """Get a cursor, optionally from an existing connection.

    Parameters
    ----------
    conn : sqlite3.Connection, optional
        Existing connection. If None, opens a new default connection.

    Returns
    -------
    sqlite3.Cursor
    """
    if conn is not None:
        return conn.cursor()
    return get_db().cursor()


def get_db_connection(
    db_path: Optional[Union[str, Path]] = None,
    *,
    foreign_keys: bool = True,
    wal_mode: bool = True,
    row_factory: bool = True,
    read_only: bool = False,
    busy_timeout: int = 15000,
) -> sqlite3.Connection:
    """Create a database connection with safe, standard PRAGMA settings.

    Parameters
    ----------
    db_path : str or Path, optional
        Path to the SQLite database file.  Defaults to ``DEFAULT_DB_PATH``
        (``crustacean_virus_core.db`` in the same directory as this module).
    foreign_keys : bool
        Enable ``PRAGMA foreign_keys = ON``.
    wal_mode : bool
        Enable ``PRAGMA journal_mode = WAL``.
    row_factory : bool
        Set ``conn.row_factory = sqlite3.Row`` for dict-like access.
    read_only : bool
        If True, also sets ``PRAGMA query_only = ON`` for safety.
    busy_timeout : int
        Milliseconds to wait before raising ``sqlite3.OperationalError``
        on a locked database.

    Returns
    -------
    sqlite3.Connection
    """
    resolved = Path(db_path) if db_path else DEFAULT_DB_PATH
    conn = sqlite3.connect(str(resolved), timeout=busy_timeout // 1000)

    if row_factory:
        conn.row_factory = sqlite3.Row

    # --- PRAGMA block (order matters) ---
    if wal_mode:
        conn.execute("PRAGMA journal_mode = WAL")
    if foreign_keys:
        conn.execute("PRAGMA foreign_keys = ON")
    conn.execute(f"PRAGMA busy_timeout = {busy_timeout}")
    if read_only:
        conn.execute("PRAGMA query_only = ON")

    return conn


@contextmanager
def db_connection(
    db_path: Optional[Union[str, Path]] = None,
    *,
    foreign_keys: bool = True,
    wal_mode: bool = True,
    row_factory: bool = True,
    read_only: bool = False,
    busy_timeout: int = 15000,
) -> Generator[sqlite3.Connection, None, None]:
    """Context manager that yields a connection and closes it on exit.

    Usage::

        with db_connection() as conn:
            cur = conn.execute("SELECT COUNT(*) FROM viral_isolates")
            print(cur.fetchone()[0])
    """
    conn = get_db_connection(
        db_path,
        foreign_keys=foreign_keys,
        wal_mode=wal_mode,
        row_factory=row_factory,
        read_only=read_only,
        busy_timeout=busy_timeout,
    )
    try:
        yield conn
    finally:
        conn.close()


@contextmanager
def db_transaction(
    db_path: Optional[Union[str, Path]] = None,
    *,
    foreign_keys: bool = True,
    wal_mode: bool = True,
    busy_timeout: int = 15000,
) -> Generator[sqlite3.Connection, None, None]:
    """Context manager that wraps work in an explicit transaction
    (commit on success, rollback on exception).

    Usage::

        with db_transaction() as conn:
            conn.execute("UPDATE viral_isolates SET ... WHERE ...")
    """
    conn = get_db_connection(
        db_path,
        foreign_keys=foreign_keys,
        wal_mode=wal_mode,
        row_factory=True,
        busy_timeout=busy_timeout,
    )
    try:
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def backup_database(
    db_path: Optional[Union[str, Path]] = None,
    backup_dir: Optional[Union[str, Path]] = None,
    label: str = "backup",
    *,
    quiet: bool = False,
) -> Path:
    """WAL-safe database backup.

    Checkpoints the WAL to flush pending writes into the main database file,
    then copies the ``.db``, ``.db-wal``, and ``.db-shm`` files so the backup
    is consistent and restorable even under WAL journal mode.

    Parameters
    ----------
    db_path : str or Path, optional
        Path to the SQLite database file. Defaults to ``DEFAULT_DB_PATH``.
    backup_dir : str or Path, optional
        Directory to write the backup into. Defaults to a ``backups/``
        subdirectory next to the database file.
    label : str
        Human-readable label that appears in the backup filename.
    quiet : bool
        If True, suppress the log message.

    Returns
    -------
    Path
        Path to the backup ``.db`` file (the ``.db-wal`` and ``.db-shm``
        siblings, if they existed, are copied beside it).
    """
    resolved_db = Path(db_path) if db_path else DEFAULT_DB_PATH
    if backup_dir is None:
        backup_dir = resolved_db.parent / "backups"
    backup_dir = Path(backup_dir)
    backup_dir.mkdir(parents=True, exist_ok=True)

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_label = label.replace(" ", "_").replace("/", "_").replace("\\", "_")
    backup_base = backup_dir / f"crustacean_virus_core_{safe_label}_{stamp}"

    # Checkpoint WAL so all committed writes land in the .db file
    conn = sqlite3.connect(str(resolved_db))
    try:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        conn.close()

    # Copy main database
    shutil.copy2(str(resolved_db), str(backup_base.with_suffix(".db")))

    # Copy WAL and SHM if they exist
    for suffix in (".db-wal", ".db-shm"):
        src = Path(str(resolved_db) + suffix)
        if src.exists():
            dst = Path(str(backup_base.with_suffix("")) + suffix)
            shutil.copy2(str(src), str(dst))

    if not quiet:
        print(f"[backup] WAL-safe backup → {backup_base.with_suffix('.db').name}")

    return backup_base.with_suffix(".db")
