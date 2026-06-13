#!/usr/bin/env python3
"""One-shot sync: Drop existing PG tables → Recreate schema → Migrate from SQLite.

Usage:
    python sync_full.py

Environment:
    PG_DSN       — PostgreSQL connection string
    SQLITE_PATH  — path to the local SQLite database
    DB_PASSWORD  — fallback password if PG_DSN doesn't contain one
"""

import os, sys, time
from pathlib import Path

# ── Configuration ───────────────────────────────────────────────────────────
BASE = Path(__file__).resolve().parent
SQLITE_PATH = os.environ.get("SQLITE_PATH", str(BASE / "crustacean_virus_core.db"))
_PG_PASSWORD = os.environ.get("PG_PASSWORD") or os.environ.get("DB_PASSWORD") or ""
PG_DSN = os.environ.get("PG_DSN", f"postgresql://aquavir:{_PG_PASSWORD}@localhost:5432/aquavir_kb")
SCHEMA_SQL = os.environ.get("SCHEMA_SQL", str(BASE / "deploy" / "init_db.sql"))

import psycopg2

def now_stamp():
    return time.strftime("%Y%m%d_%H%M%S")

def drop_all_tables(pg_conn):
    """Drop all public tables, views, materialized views, sequences (cascade)."""
    cur = pg_conn.cursor()
    # Disable triggers temporarily to avoid FK issues
    cur.execute("SET session_replication_role = 'replica';")
    
    # Drop views first (they may depend on tables)
    cur.execute("""
        SELECT 'DROP VIEW IF EXISTS "' || table_name || '" CASCADE;'
        FROM information_schema.views
        WHERE table_schema = 'public'
    """)
    for row in cur.fetchall():
        try:
            cur.execute(row[0])
        except Exception as e:
            print(f"  [warn] Drop view failed: {e}")
    
    # Drop tables (cascade handles FK dependencies)
    cur.execute("""
        SELECT 'DROP TABLE IF EXISTS "' || tablename || '" CASCADE;'
        FROM pg_tables
        WHERE schemaname = 'public'
    """)
    for row in cur.fetchall():
        try:
            cur.execute(row[0])
        except Exception as e:
            print(f"  [warn] Drop table failed: {e}")
    
    # Drop sequences
    cur.execute("""
        SELECT 'DROP SEQUENCE IF EXISTS "' || sequence_name || '" CASCADE;'
        FROM information_schema.sequences
        WHERE sequence_schema = 'public'
    """)
    for row in cur.fetchall():
        try:
            cur.execute(row[0])
        except Exception as e:
            print(f"  [warn] Drop sequence failed: {e}")
    
    # Re-enable triggers
    cur.execute("SET session_replication_role = 'origin';")
    pg_conn.commit()
    print("  All tables/views/sequences dropped.")

def main():
    ts = now_stamp()
    start = time.time()
    
    # Step 1: Connect to PostgreSQL
    print(f"[{ts}] Connecting to PostgreSQL …")
    pg = psycopg2.connect(PG_DSN)
    pg.autocommit = False
    print(f"  DSN: {PG_DSN.replace(_PG_PASSWORD, '****') if _PG_PASSWORD else PG_DSN}")
    
    # Step 2: BACKUP current database (pg_dump via shell)
    backup_file = f"/opt/backups/aquavir_before_full_sync_{ts}.dump"
    print(f"[{ts}] Creating backup → {backup_file} …")
    os.makedirs("/opt/backups", exist_ok=True)
    dump_cmd = f'pg_dump -U aquavir -Fc aquavir_kb > {backup_file}'
    print(f"  Running: {dump_cmd}")
    # We'll run pg_dump via shell - the user needs to be inside docker
    # The actual pg_dump will be run by the parent shell script
    print(f"  NOTE: pg_dump will be executed by the wrapper shell script.")
    
    # Step 3: Drop all existing objects
    print(f"[{ts}] Dropping all existing database objects …")
    drop_all_tables(pg)
    
    # Step 4: Recreate schema from init_db.sql
    print(f"[{ts}] Recreating schema from {SCHEMA_SQL} …")
    if not os.path.isfile(SCHEMA_SQL):
        print(f"[FATAL] Schema file not found: {SCHEMA_SQL}")
        sys.exit(1)
    
    with open(SCHEMA_SQL, "r", encoding="utf-8") as f:
        schema = f.read()
    
    statements = []
    current = []
    for line in schema.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("--"):
            continue
        current.append(line)
        if stripped.endswith(";"):
            statements.append("\n".join(current))
            current = []
    if current:
        statements.append("\n".join(current))
    
    with pg.cursor() as cur:
        for idx, stmt in enumerate(statements):
            try:
                cur.execute(stmt)
            except Exception as e:
                print(f"  [warn] Stmt {idx+1} skipped: {str(e).strip()[:120]}")
                pg.rollback()
    pg.commit()
    print(f"  Schema recreated ({len(statements)} statements).")
    
    # Step 5: Verify empty tables
    with pg.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='public'")
        table_count = cur.fetchone()[0]
    print(f"  Tables in PG: {table_count}")
    
    # Step 6: Run the actual migration
    print(f"[{ts}] Running migrate_sqlite_to_pg.py …")
    import subprocess
    env = os.environ.copy()
    env["SQLITE_PATH"] = str(SQLITE_PATH)
    env["PG_DSN"] = PG_DSN
    env["SCHEMA_SQL"] = str(SCHEMA_SQL)
    
    result = subprocess.run(
        [sys.executable, str(BASE / "migrate_sqlite_to_pg.py")],
        env=env, cwd=str(BASE)
    )
    
    elapsed = time.time() - start
    print(f"[{now_stamp()}] [DONE] Sync completed in {elapsed/60:.1f} minutes.")
    print(f"    Exit code: {result.returncode}")
    pg.close()
    return result.returncode

if __name__ == "__main__":
    sys.exit(main())
