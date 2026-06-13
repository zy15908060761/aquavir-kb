"""
PostgreSQL connection pool and SQLite-compatible query adapter for AquaVir-KB.

Provides a seamless dual-backend layer so that backend.py (4000+ lines of
sqLite3 code) can target PostgreSQL with minimal changes -- typically just
replacing ``from db_utils import get_db_connection`` with ``from db_pg
import get_query_connection`` and letting the environment variable
``DATABASE_URL`` decide the backend.

Usage
-----
    from db_pg import get_query_connection

    with get_query_connection() as conn:
        rows = conn.execute("SELECT * FROM viral_isolates LIMIT ?", [5]).fetchall()

When ``DATABASE_URL`` is set the connection is drawn from a PostgreSQL
connection pool; when it is unset (or empty) the call is forwarded straight
to ``db_utils.db_connection(...)``.

Environment
-----------
DATABASE_URL : str, optional
    PostgreSQL connection string, e.g.:
    ``postgresql://user:password@host:5432/aquavir_db``
    When empty or absent the adapter falls through to SQLite.
"""

import logging
import os
from collections.abc import Generator
from contextlib import contextmanager
from typing import Any, Optional, Union

LOG = logging.getLogger("aquavir.db")

# --- Backend detection -------------------------------------------------------

_DATABASE_URL: Optional[str] = os.environ.get("DATABASE_URL", "").strip()
_IS_PG: bool = bool(_DATABASE_URL)


# --- PostgreSQL connection pool (lazy init) ----------------------------------

_pool = None  # psycopg2.pool.ThreadedConnectionPool, created on first use


def _init_pool() -> None:
    """Lazily initialise the global PostgreSQL connection pool."""
    global _pool
    if _pool is not None:
        return

    try:
        import psycopg2
        from psycopg2 import pool as pg_pool
        from psycopg2.extras import RealDictCursor
    except ImportError as exc:
        raise RuntimeError(
            "DATABASE_URL is set but psycopg2 is not installed. "
            "Run: pip install psycopg2-binary"
        ) from exc

    LOG.info(
        "Creating PostgreSQL connection pool (min=4, max=40) for %s ...",
        _mask_url(_DATABASE_URL),
    )
    _pool = pg_pool.ThreadedConnectionPool(
        minconn=4,
        maxconn=40,
        dsn=_DATABASE_URL,
        cursor_factory=RealDictCursor,
    )
    LOG.info("PostgreSQL connection pool created.")


def _mask_url(url: Optional[str]) -> str:
    """Return a safe-to-log version of the database URL (hide credentials)."""
    if not url:
        return "<empty>"
    try:
        from urllib.parse import urlparse, urlunparse

        parsed = urlparse(url)
        if parsed.password:
            # Replace password with ****
            netloc = f"{parsed.username}:****@{parsed.hostname}"
            if parsed.port:
                netloc = f"{netloc}:{parsed.port}"
            return urlunparse(parsed._replace(netloc=netloc))
    except Exception:
        pass
    return url


@contextmanager
def get_pg_connection(
    read_only: bool = False,
) -> Generator[Any, None, None]:
    """Context manager that yields a PostgreSQL connection from the pool.

    Parameters
    ----------
    read_only : bool
        If True the connection is put into read-only transaction mode
        (``default_transaction_read_only = on``) as a safety guard.

    Yields
    ------
    psycopg2.extensions.connection
        A connection with ``RealDictCursor`` as the default cursor factory,
        meaning rows behave like ``sqlite3.Row`` (dict-like access).

    The connection is automatically returned to the pool when the context
    exits.
    """
    if _pool is None:
        _init_pool()

    conn = _pool.getconn()
    try:
        # Every connection operates in UTC.
        with conn.cursor() as cur:
            cur.execute("SET timezone = 'UTC'")
            if read_only:
                cur.execute("SET default_transaction_read_only = on")
        yield conn
    finally:
        # Roll back any unfinished transaction before returning to the pool
        # so the next user gets a clean connection.
        try:
            conn.rollback()
        except Exception:
            pass
        _pool.putconn(conn)


# --- SQLite compatibility shims ----------------------------------------------


def _convert_placeholders(sql: str) -> str:
    """Replace SQLite ``?`` placeholders with psycopg2 ``%s`` placeholders.

    This is a *simple* positional replacement -- no named-parameter
    conversion.  It assumes the caller provides positional parameters.
    """
    return sql.replace("?", "%s")


def pg_query(conn: Any, sql_text: str, params: Optional[Any] = None) -> list:
    """Execute a SELECT and return results as a list of RealDictRow.

    Parameters
    ----------
    conn : psycopg2 connection
        An active connection from ``get_pg_connection``.
    sql_text : str
        SQL with ``?`` placeholders (will be converted to ``%s``).
    params : list, tuple, or None
        Bound parameters for the query.

    Returns
    -------
    list[psycopg2.extras.RealDictRow]
        Each row supports both ``row["column"]`` and ``row[0]`` access
        (compatible with ``sqlite3.Row``).
    """
    sql = _convert_placeholders(sql_text)
    if params is not None and not isinstance(params, (list, tuple)):
        params = [params]
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchall()


def pg_execute(
    conn: Any,
    sql_text: str,
    params: Optional[Any] = None,
) -> None:
    """Execute an INSERT, UPDATE, or DELETE and commit.

    Parameters
    ----------
    conn : psycopg2 connection
        An active connection from ``get_pg_connection``.
    sql_text : str
        SQL with ``?`` placeholders (will be converted to ``%s``).
    params : list, tuple, or None
        Bound parameters for the statement.
    """
    sql = _convert_placeholders(sql_text)
    if params is not None and not isinstance(params, (list, tuple)):
        params = [params]
    with conn.cursor() as cur:
        cur.execute(sql, params)
    conn.commit()


# --- Unified connection helper (the one function backend.py should use) ------


def get_query_connection():
    """Return a context manager that yields a DB connection.

    Behaviour
    ---------
    * If ``DATABASE_URL`` is set (PostgreSQL mode) returns
      ``get_pg_connection(read_only=True)``.
    * Otherwise (SQLite mode) delegates to
      ``db_utils.get_db_connection(read_only=True)`` wrapped so that
      it **also** works with ``with ... as conn:``.

    This is the **single** function that ``backend.py`` should import and
    call everywhere it currently uses ``get_db()`` or
    ``get_db_connection()``.

    Returns
    -------
    contextmanager
        A context manager that yields a PEP-249 connection whose rows
        support dict-like access (``row["column"]``).
    """
    if _IS_PG:
        return get_pg_connection(read_only=True)

    # SQLite fallback -- return a context manager so callers can write:
    #   with get_query_connection() as conn:
    from db_utils import get_db_connection as _sqlite_get_db_connection

    @contextmanager
    def _sqlite_cm():
        conn = _sqlite_get_db_connection(read_only=True, busy_timeout=5000)
        try:
            yield conn
        finally:
            conn.close()

    return _sqlite_cm()


# --- Health check -------------------------------------------------------------


# --- Raw connection (for _get_db() pattern in backend.py) ------------------


def get_raw_db_connection(read_only: bool = True):
    """Return a DB connection with a ``.close()`` that does the right thing.

    For the ``conn = _get_db()`` / ``conn.close()`` pattern used in
    backend.py's enrichment and download endpoints (roughly 20 call sites).
    In PostgreSQL mode the connection is pulled from the pool and
    ``.close()`` returns it to the pool.  In SQLite mode it is a regular
    sqlite3 connection.
    """
    if _IS_PG:
        if _pool is None:
            _init_pool()
        conn = _pool.getconn()
        # Apply per-connection settings
        try:
            with conn.cursor() as cur:
                cur.execute("SET timezone = 'UTC'")
                if read_only:
                    cur.execute("SET default_transaction_read_only = on")
        except Exception:
            _pool.putconn(conn)
            raise

        # Wrap .close() so it returns to pool instead of closing
        _original_close = conn.close
        def _return_to_pool():
            try:
                conn.rollback()
            except Exception:
                pass
            _original_close()  # psycopg2's close returns to pool
        conn.close = _return_to_pool
        return conn

    # SQLite mode
    from db_utils import get_db_connection as _sqlite_get_db_connection
    return _sqlite_get_db_connection(read_only=read_only, busy_timeout=5000)


def check_db_connection() -> dict:
    """Quick connectivity check for the active backend.

    Returns
    -------
    dict
        ``{"backend": "postgresql"|"sqlite", "healthy": True|False}``
    """
    if _IS_PG:
        try:
            if _pool is None:
                _init_pool()
            conn = _pool.getconn()
            try:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1 AS ok")
                    cur.fetchone()
                return {"backend": "postgresql", "healthy": True}
            finally:
                _pool.putconn(conn)
        except Exception as exc:
            LOG.warning("PostgreSQL health check failed: %s", exc)
            return {"backend": "postgresql", "healthy": False}
    else:
        try:
            from db_utils import get_db_connection as _sqlite_get_db_connection

            conn = _sqlite_get_db_connection(read_only=True, busy_timeout=2000)
            conn.execute("SELECT 1")
            conn.close()
            return {"backend": "sqlite", "healthy": True}
        except Exception as exc:
            LOG.warning("SQLite health check failed: %s", exc)
            return {"backend": "sqlite", "healthy": False}
