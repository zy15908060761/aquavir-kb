#!/usr/bin/env python3
"""
One-shot migration script: SQLite (crustacean_virus_core.db) → PostgreSQL (AquaVir-KB).

Reads environment variables:
    SQLITE_PATH  — path to the SQLite database file
    PG_DSN       — PostgreSQL connection string (password via PG_PASSWORD or DB_PASSWORD)
    BATCH_SIZE   — rows per INSERT batch (default 5000)

Usage:
    python migrate_sqlite_to_pg.py
"""

import os
import sys
import time
from typing import Any, Optional

import psycopg2
import psycopg2.extras

# ── Configuration ───────────────────────────────────────────────────────────

SQLITE_PATH = os.environ.get(
    "SQLITE_PATH",
    r"F:\水生无脊椎动物数据库\crustacean_virus_core.db",
)

_PG_PASSWORD = os.environ.get("PG_PASSWORD") or os.environ.get("DB_PASSWORD") or "aquavir_secret"
PG_DSN = os.environ.get(
    "PG_DSN",
    f"postgresql://aquavir:{_PG_PASSWORD}@localhost:5432/aquavir_kb",
)

BATCH_SIZE = int(os.environ.get("BATCH_SIZE", "5000"))

# Path to the init_db.sql schema file (located next to this script in deploy/)
_SCHEMA_SRC = os.environ.get(
    "SCHEMA_SQL",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "deploy", "init_db.sql"),
)

# ── Table ordering (FK-safe, parents before children) ──────────────────────
# Extracted from deploy/init_db.sql by walking CREATE TABLE statements.
# Tables with no FK dependencies come first, then those that reference them.
#
# Phase 1 — no foreign keys (root tables)
PHASE_1 = [
    "schema_version",
    "ref_literatures",
    "crustacean_hosts",
    "virus_master",
    "external_sources",
    "curation_vocab_terms",
    "database_maintenance_log",
    "evidence_dedup_runs",
    "diagnostic_methods",
    "ictv_taxonomy",
    "ictv_vmr",
    "viralzone_families",
    "qaqc_runs",
    "optimize_quality_runs",
    "fulltext_evidence_rescue_runs",
    "literature_backfill_runs",
    "release_manifest",
    "schema_deprecated_columns",
    "bioRxiv_preprints",          # renamed on-disk to biorxiv_preprints
]

# Phase 2 — depend on Phase 1 tables
PHASE_2 = [
    "virus_aliases",                # virus_master
    "virus_ictv_mappings",          # virus_master, ictv_taxonomy
    "virus_ictv_status",            # virus_master
    "virus_master_review_queue",    # virus_master
    "virus_name_scope_review",      # virus_master
    "virus_scope_assessment",       # virus_master
    "virus_vmr_mappings",           # virus_master, ictv_vmr, ictv_taxonomy, external_sources
    "viral_isolates",               # virus_master
    "viral_proteins",               # viral_isolates
    "viral_proteins_nr",            # viral_isolates
    "nucleotide_records",           # viral_isolates
    "host_aliases",                 # crustacean_hosts
    "infection_records",            # virus_master, crustacean_hosts, viral_isolates, ref_literatures
    "core_genes",                   # virus_master
    "data_provenance",              # virus_master
    "environmental_evidence",       # virus_master, ref_literatures
    "host_range_evidence",          # virus_master, crustacean_hosts, viral_isolates, ref_literatures
    "control_management_methods",   # virus_master, crustacean_hosts, ref_literatures
    "outbreak_events",              # virus_master, crustacean_hosts, ref_literatures
    "pathogenicity_assessment",     # virus_master, crustacean_hosts, ref_literatures
    "pathogenicity_evidence",       # virus_master, viral_isolates, ref_literatures
    "temperature_profiles",         # virus_master, crustacean_hosts, ref_literatures
    "virulence_profiles",           # virus_master, crustacean_hosts, ref_literatures
    "host_biology_profiles",        # crustacean_hosts
    "host_ecological_traits",       # crustacean_hosts
    "host_genome_artifacts",        # viral_isolates
    "host_taxonomy_profiles",       # crustacean_hosts
    "sample_collections",           # viral_isolates, ref_literatures
    "sample_metadata",              # viral_isolates, sample_collections
    "sra_runs",                     # viral_isolates
    "curation_logs",                # external_sources
    "epmc_literature",              # ref_literatures
    "evidence_records",             # virus_master, crustacean_hosts, viral_isolates, ref_literatures, external_sources
    "external_xrefs",               # external_sources
    "host_association_assessment",  # virus_master, crustacean_hosts
    "host_review_candidates",       # crustacean_hosts
    "host_scope_overrides",         # crustacean_hosts
    "ictv_review_priority_queue",   # virus_master, crustacean_hosts, ref_literatures
    "literature_evidence_candidates",  # virus_master, crustacean_hosts, ref_literatures
    "manual_ictv_bridges",          # virus_master, ictv_taxonomy, ictv_vmr
    "abstract_mention_fulltext_worklist",  # ref_literatures
    "accession_duplicate_review_queue",    # viral_isolates
    "biosample_links",              # viral_isolates
    "curation_conflicts",           # viral_isolates
    "curation_priority_queue",      # curation_conflicts, viral_isolates
    "diagnostic_method_review_queue",  # diagnostic_methods
    "entity_quality_scores",        # qaqc_runs
    "fulltext_evidence_rescue_candidates",  # ref_literatures
    "fulltext_evidence_rescue_review_queue",  # fulltext_evidence_rescue_candidates
    "fulltext_evidence_rescue_targets",
    "geo_datasets",
    "geo_virus_links",
    "genbank_recovery_candidates",
    "genome_pairwise_identity",
    "genome_synteny_blocks",
    "interpro_annotations",
    "interpro_go_terms",
    "isolate_curated_profiles",
    "isolate_reference_links",      # viral_isolates, ref_literatures
    "kegg_annotations",
    "kegg_pathways",
    "kegg_protein_pathways",        # viral_proteins
    "literature_backfill_candidates",
    "literature_fulltext_quality",
    "literature_fulltext_sections",
    "literature_fulltext_sources",
    "manual_review_priority_queue",
    "nr_protein_clusters",
    "obis_occurrences",
    "optimize_quality_quarantine",
    "phi_base_hits",                # viral_proteins
    "pride_datasets",
    "pride_virus_links",
    "protein_annotation_bridge",    # viral_proteins, external_sources
    "protein_domains",              # viral_proteins
    "protein_function_suggestions", # viral_proteins
    "protein_structures",           # viral_proteins
    "qaqc_conflicts",
    "qaqc_duplicates",
    "qaqc_issues",
    "qaqc_summary",
    "quality_hardening_log",
    "rdrp_classification",          # viral_proteins
    "rdrp_classification_v2",       # viral_proteins
    "reannotated_orfs",             # viral_isolates
    "reannotation_stats",           # viral_isolates
    "ref_citation_metadata",
    "sequence_curation_flags",      # viral_isolates
    "string_interactions",          # viral_proteins
    "submission_manual_intervention_tasks",
    "submission_protein_annotation_coverage",
    "submission_target_geography_precision",
    "uniprot_annotations",          # viral_proteins
    "uniprot_protein_links",        # viral_proteins
    "uniprot_structures",           # viral_proteins
    "viralzone_gene_tables",
    "virus_evidence_quality_score",
    "evidence_dedup_quarantine",    # evidence_dedup_runs
    "evidence_duplicate_suppression_log",  # evidence_records
    "evidence_isolate_links",       # evidence_records, viral_isolates
    "evidence_review_priority_queue",  # evidence_records, virus_master
    "weak_evidence_isolation_log",  # evidence_records
    "epmc_preprints",              # epmc_literature
    "fulltext_evidence_rescue_candidates_legacy_20260528_104551",
    "gbif_occurrences",
    "gbif_species_summary",         # crustacean_hosts
    "geography_quality_profiles",
    "conservative_cleanup_runs",
    "conservative_fk_quarantine",
    "preprint_evidence_links",      # may not exist — handled gracefully
]

# Collapse into one ordered list (deduplicated, preserving order)
def _dedup_ordered(seq):
    seen = set()
    return [x for x in seq if not (x in seen or seen.add(x))]

TABLE_ORDER = _dedup_ordered(PHASE_1 + PHASE_2)

# Tables that should NOT be migrated (SQLite internal or FTS virtual tables)
SKIP_TABLES = {
    "sqlite_sequence",
    "sqlite_stat1",
    "virus_search_fts",
    "virus_search_fts_config",
    "virus_search_fts_data",
    "virus_search_fts_docsize",
    "virus_search_fts_idx",
}

# Tables that exist in SQLite but may not be in init_db.sql (historic artifacts)
# — we still try to migrate them if they exist on both sides.
EXTRA_TABLES = []


# ── Helpers ─────────────────────────────────────────────────────────────────

def now_stamp() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def pg_value(v: Any) -> Any:
    """Convert a SQLite Python value to a PostgreSQL-safe Python value."""
    if isinstance(v, bytes):
        return psycopg2.Binary(v)
    # SQLite bools come as int 0/1 — keep as int
    return v


def get_table_list(sqlite_conn) -> list[str]:
    """Return non-system table names present in the SQLite database."""
    cur = sqlite_conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    )
    return [row[0] for row in cur.fetchall() if row[0] not in SKIP_TABLES]


def get_columns(pg_conn, table: str) -> list[str]:
    """Return column names for a table in PostgreSQL (quoting needed)."""
    with pg_conn.cursor() as cur:
        cur.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = %s
            ORDER BY ordinal_position
            """,
            (table,),
        )
        return [row[0] for row in cur.fetchall()]


def get_serial_columns(pg_conn) -> set[str]:
    """Return set of table names that have a SERIAL/BIGSERIAL primary key."""
    serial_tables: set[str] = set()
    with pg_conn.cursor() as cur:
        cur.execute(
            """
            SELECT tc.table_name
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
              ON tc.constraint_name = kcu.constraint_name
              AND tc.table_schema = kcu.table_schema
            JOIN information_schema.columns c
              ON c.table_schema = tc.table_schema
              AND c.table_name = tc.table_name
              AND c.column_name = kcu.column_name
            WHERE tc.constraint_type = 'PRIMARY KEY'
              AND tc.table_schema = 'public'
              AND (c.column_default LIKE %s OR c.column_default LIKE %s)
            """,
            ("nextval%", "nextval%"),
        )
        for row in cur:
            serial_tables.add(row[0])
    return serial_tables


def reset_serial_sequences(pg_conn, tables: list[str]):
    """Reset SERIAL sequences to MAX(id)+1 for each table."""
    print("[reset] Resetting auto-increment sequences …")
    with pg_conn.cursor() as cur:
        for table in tables:
            qtable = psycopg2.sql.Identifier(table)
            try:
                cur.execute(
                    psycopg2.sql.SQL(
                        "SELECT setval(pg_get_serial_sequence(%s, 'id'), "
                        "COALESCE((SELECT MAX(id) FROM {}), 0))"
                    ).format(qtable),
                    (table,),
                )
                pg_conn.commit()
            except Exception as exc:
                pg_conn.rollback()
                print(f"  [warn] Could not reset sequence for {table}: {exc}")
    print(f"  [reset] Done — {len(tables)} sequences updated.")


# ── Core migration function ─────────────────────────────────────────────────

def migrate_table(
    sqlite_conn,
    pg_conn,
    table_name: str,
    batch_size: int = 5000,
    *,
    columns: Optional[list[str]] = None,
) -> int:
    """Migrate one table from SQLite → PostgreSQL.

    Returns the number of rows migrated.
    """
    # Quote table name for SQLite (some are quoted in init_db, some are not)
    qtable = f'"{table_name}"' if " " in table_name or "-" in table_name else table_name

    # Count rows in SQLite
    try:
        (total,) = sqlite_conn.execute(f"SELECT COUNT(*) FROM {qtable}").fetchone()
    except Exception as exc:
        print(f"  [FAIL] {table_name}: cannot count rows — {exc}")
        return 0

    if total == 0:
        # Still create the empty table; nothing to migrate
        return 0

    # Resolve column list
    if columns is None:
        columns = get_columns(pg_conn, table_name)

    if not columns:
        print(f"  [SKIP] {table_name}: no columns found in PostgreSQL")
        return 0

    col_list = ", ".join(f'"{c}"' for c in columns)
    col_placeholders = ", ".join("%s" for _ in columns)

    # Check resume: does PG already have data?
    with pg_conn.cursor() as cur:
        try:
            cur.execute(
                psycopg2.sql.SQL("SELECT COUNT(*) FROM {}").format(
                    psycopg2.sql.Identifier(table_name)
                )
            )
            pg_count = cur.fetchone()[0]
        except Exception:
            pg_count = 0

    if pg_count > 0:
        if pg_count >= total:
            print(f"  [SKIP] {table_name}: already has {pg_count} rows (≥{total} in SQLite)")
            return 0
        else:
            print(f"  [RESUME] {table_name}: PG has {pg_count}/{total}, continuing …")

    # Batch migrate
    migrated = 0
    offset = pg_count  # resume from where PG left off

    while offset < total:
        sqlite_conn.execute("SELECT 1")  # keep connection alive
        try:
            rows = sqlite_conn.execute(
                f"SELECT * FROM {qtable} LIMIT {batch_size} OFFSET {offset}"
            ).fetchall()
        except Exception as exc:
            print(f"  [FAIL] {table_name}: SELECT error at offset {offset} — {exc}")
            break

        if not rows:
            break

        # Convert rows to list of tuples with type coercion
        values = []
        for row in rows:
            values.append(tuple(pg_value(v) for v in row))

        # Batch insert
        try:
            with pg_conn.cursor() as cur:
                psycopg2.extras.execute_values(
                    cur,
                    f"INSERT INTO {psycopg2.sql.Identifier(table_name).as_string(pg_conn)} "
                    f"({col_list}) VALUES %s "
                    f"ON CONFLICT DO NOTHING",
                    values,
                    template=f"({col_placeholders})",
                )
            pg_conn.commit()
        except Exception as exc:
            pg_conn.rollback()
            # Try row-by-row fallback for this batch
            print(f"  [warn] {table_name}: batch INSERT failed at offset {offset}, "
                  f"falling back row-by-row …")
            fallback_ok = 0
            for row_tuple in values:
                try:
                    with pg_conn.cursor() as cur:
                        cur.execute(
                            f"INSERT INTO {psycopg2.sql.Identifier(table_name).as_string(pg_conn)} "
                            f"({col_list}) VALUES ({col_placeholders}) "
                            f"ON CONFLICT DO NOTHING",
                            row_tuple,
                        )
                    pg_conn.commit()
                    fallback_ok += 1
                except Exception:
                    pg_conn.rollback()
            migrated += fallback_ok
            offset += len(rows)
            print(f"  {table_name}: {migrated}/{total}  (batch failed, "
                  f"{fallback_ok}/{len(rows)} inserted row-by-row)")
            continue

        migrated += len(values)
        offset += len(values)
        print(f"  {table_name}: {migrated}/{total}")

    return migrated


# ── Main flow ───────────────────────────────────────────────────────────────

def main():
    import sqlite3

    start_wall = time.time()

    # ── [1/4] Connect to SQLite ───────────────────────────────────────────
    print(f"[{now_stamp()}] [1/4] Connecting to SQLite …")
    print(f"         Path: {SQLITE_PATH}")
    if not os.path.isfile(SQLITE_PATH):
        print(f"[FATAL] SQLite database not found: {SQLITE_PATH}")
        sys.exit(1)

    sqlite_conn = sqlite3.connect(SQLITE_PATH, timeout=60)
    sqlite_conn.execute("PRAGMA journal_mode = WAL")
    sqlite_conn.execute("PRAGMA busy_timeout = 15000")
    sqlite_conn.row_factory = sqlite3.Row
    print(f"         Connected ({os.path.getsize(SQLITE_PATH) / 1e6:.0f} MB)")

    sqlite_tables = set(get_table_list(sqlite_conn))
    print(f"         Tables in SQLite: {len(sqlite_tables)}")

    # ── [2/4] Connect to PostgreSQL ───────────────────────────────────────
    print(f"[{now_stamp()}] [2/4] Connecting to PostgreSQL …")
    try:
        pg_conn = psycopg2.connect(PG_DSN)
        pg_conn.autocommit = False
        print(f"         DSN: {PG_DSN.replace(_PG_PASSWORD, '****')}")
    except Exception as exc:
        print(f"[FATAL] Cannot connect to PostgreSQL: {exc}")
        sqlite_conn.close()
        sys.exit(1)

    # ── [3/4] Create schema from init_db.sql ───────────────────────────────
    print(f"[{now_stamp()}] [3/4] Creating schema from init_db.sql …")
    print(f"         Schema file: {_SCHEMA_SRC}")
    if not os.path.isfile(_SCHEMA_SRC):
        print(f"[FATAL] Schema file not found: {_SCHEMA_SRC}")
        sqlite_conn.close()
        pg_conn.close()
        sys.exit(1)

    try:
        with open(_SCHEMA_SRC, "r", encoding="utf-8") as f:
            schema_sql = f.read()
    except Exception as exc:
        print(f"[FATAL] Cannot read schema file: {exc}")
        sqlite_conn.close()
        pg_conn.close()
        sys.exit(1)

    with pg_conn.cursor() as cur:
        try:
            # Execute each non-empty, non-comment statement
            # The schema file uses standard ';'-delimited SQL
            statements = []
            current = []
            for line in schema_sql.splitlines():
                stripped = line.strip()
                if not stripped or stripped.startswith("--"):
                    continue
                current.append(line)
                if stripped.endswith(";"):
                    statements.append("\n".join(current))
                    current = []
            if current:
                statements.append("\n".join(current))

            for stmt in statements:
                try:
                    cur.execute(stmt)
                except Exception as stmt_exc:
                    # Some statements may already exist (indexes, etc.) — warn but continue
                    msg = str(stmt_exc).strip()
                    first_80 = stmt.strip()[:80].replace("\n", " ")
                    print(f"  [warn] Statement skipped: {first_80}…")
                    print(f"         Reason: {msg}")
                    pg_conn.rollback()
            pg_conn.commit()
        except Exception as exc:
            pg_conn.rollback()
            print(f"[FATAL] Schema creation failed: {exc}")
            sqlite_conn.close()
            pg_conn.close()
            sys.exit(1)

    print(f"         Schema applied successfully.")

    # Determine which tables to migrate (intersection of SQLite + PG schema)
    pg_available = set(get_columns(pg_conn, t)[0] for t in [])
    # Actually get all PG tables
    with pg_conn.cursor() as cur:
        cur.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_type = 'BASE TABLE'"
        )
        pg_tables_set = {row[0] for row in cur.fetchall()}

    # Use TABLE_ORDER, filtered to tables that exist in BOTH SQLite and PG
    migrate_list = [t for t in TABLE_ORDER if t in sqlite_tables and t in pg_tables_set]
    # Also include any tables in SQLite+PG that weren't in our hardcoded list
    extra = sorted(sqlite_tables & pg_tables_set - set(TABLE_ORDER) - SKIP_TABLES)
    # Remove sqlite_* or fts tables
    extra = [t for t in extra if not t.startswith("sqlite_") and "fts" not in t.lower()]
    if extra:
        print(f"  [info] Extra tables found (not in hardcoded order): {extra}")
        migrate_list.extend(extra)

    total_tables = len(migrate_list)
    print(f"         Tables to migrate: {total_tables}")

    # Pre-resolve column lists for common tables (cached)
    _col_cache: dict[str, list[str]] = {}

    # ── [4/4] Migrate data ─────────────────────────────────────────────────
    print(f"[{now_stamp()}] [4/4] Migrating data …")

    total_rows = 0
    migrated_count = 0
    for idx, table in enumerate(migrate_list, start=1):
        print(f"  [{idx}/{total_tables}] {table} …")
        try:
            # Fetch columns from PG
            if table not in _col_cache:
                _col_cache[table] = get_columns(pg_conn, table)
            cols = _col_cache[table]

            n = migrate_table(
                sqlite_conn, pg_conn, table,
                batch_size=BATCH_SIZE,
                columns=cols,
            )
            total_rows += n
            if n > 0:
                migrated_count += 1
        except Exception as exc:
            print(f"  [ERROR] {table}: migration failed — {exc}")
            continue

    # ── Sequence reset ─────────────────────────────────────────────────────
    serial_tables_set = get_serial_columns(pg_conn)
    serial_in_migrated = [t for t in migrate_list if t in serial_tables_set]
    reset_serial_sequences(pg_conn, serial_in_migrated)

    # ── Done ───────────────────────────────────────────────────────────────
    elapsed = time.time() - start_wall
    minutes = elapsed / 60
    print(f"[{now_stamp()}] [Done] Migrated {migrated_count} tables, "
          f"{total_rows} total rows in {minutes:.1f} minutes.")

    sqlite_conn.close()
    pg_conn.close()


if __name__ == "__main__":
    main()
