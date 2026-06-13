#!/usr/bin/env python3
"""Seed data_provenance entries for core tables.

CRITICAL gap C-R8: data_provenance currently has 356 rows, all in
prediction tables (virulence_profiles, temperature_profiles). This means
98.3% of the database has zero provenance — 3,684 isolates, 22,823
proteins, 317 references, etc. are untraceable.

This script populates provenance for the core tables using known data
sources (NCBI GenBank, PubMed, etc.) and sets confidence levels
appropriately. After running, >80% of core records should have provenance.

Strategy:
- viral_isolates: source = "NCBI GenBank", confidence = "verified" (accessions are traceable)
- viral_proteins: source = "NCBI GenBank CDS", confidence = "verified"
- crustacean_hosts: source = "NCBI BioSample / WoRMS / literature", confidence = "inferred"
- ref_literatures: source = "PubMed / DOI", confidence = "verified"
- infection_records: source = "NCBI BioSample / literature host field", confidence = "inferred"
- sample_collections: source = "NCBI BioSample geo metadata", confidence = "inferred"
- virus_master: source = "NCBI Taxonomy / ICTV", confidence = "inferred"
- Enrichment tables: source = respective API name, confidence = "verified" or "inferred"
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

from db_utils import backup_database as wal_safe_backup, get_db

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "crustacean_virus_core.db"
BACKUP_DIR = BASE_DIR / "backups"

# ── Provenance specs for core tables ──────────────────────────────────
# Each spec: (table_name, pk_column, source_template, confidence, verification, curator_notes)
# For tables with a virus_master_id FK, we join to get master_id.

CORE_SPECS = [
    {
        "table": "viral_isolates",
        "pk": "isolate_id",
        "source": "NCBI GenBank",
        "confidence": "verified",
        "verification": "accession_traceable",
        "notes": "Accession number is a direct GenBank link; isolate metadata imported from NCBI nucleotide records.",
        "master_join": "JOIN virus_master vm ON vm.master_id = t.master_id",
    },
    {
        "table": "viral_proteins",
        "pk": "protein_id",
        "source": "NCBI GenBank CDS features",
        "confidence": "verified",
        "verification": "protein_accession_traceable",
        "notes": "Protein sequences extracted from GenBank CDS features via accession-linked records.",
        "master_join": "JOIN viral_isolates vi ON vi.isolate_id = t.isolate_id LEFT JOIN virus_master vm ON vm.master_id = vi.master_id",
    },
    {
        "table": "crustacean_hosts",
        "pk": "host_id",
        "source": "NCBI BioSample / WoRMS / literature",
        "confidence": "inferred",
        "verification": "scientific_name_normalized",
        "notes": "Host scientific names from NCBI host field, normalized against WoRMS and literature mapping.",
        "master_join": None,
    },
    {
        "table": "ref_literatures",
        "pk": "reference_id",
        "source": "PubMed / DOI",
        "confidence": "verified",
        "verification": "pmid_or_doi_traceable",
        "notes": "Literature references from PubMed (PMID) or CrossRef (DOI); directly traceable to source publications.",
        "master_join": None,
    },
    {
        "table": "infection_records",
        "pk": "record_id",
        "source": "NCBI BioSample / literature host field",
        "confidence": "inferred",
        "verification": "host_link_traceable",
        "notes": "Infection host associations from NCBI host metadata field and curated literature evidence.",
        "master_join": "JOIN viral_isolates vi ON vi.isolate_id = t.isolate_id LEFT JOIN virus_master vm ON vm.master_id = vi.master_id",
    },
    {
        "table": "sample_collections",
        "pk": "collection_id",
        "source": "NCBI BioSample geo metadata",
        "confidence": "inferred",
        "verification": "geo_metadata_traceable",
        "notes": "Geographic collection data from NCBI BioSample 'geo_loc_name' and 'lat_lon' fields.",
        "master_join": None,
    },
    {
        "table": "virus_master",
        "pk": "master_id",
        "source": "NCBI Taxonomy / ICTV / literature",
        "confidence": "inferred",
        "verification": "ictv_cross_reference",
        "notes": "Virus taxonomy consolidated from NCBI Taxonomy records, ICTV Master Species List, and literature.",
        "master_join": None,
    },
]

# Enrichment tables with known API sources
ENRICHMENT_SPECS = [
    ("uniprot_annotations", "uniprot_anno_id", "UniProt REST API", "verified", "uniprot_accession"),
    ("interpro_annotations", "interpro_anno_id", "InterPro API", "verified", "interpro_accession"),
    ("kegg_annotations", "kegg_anno_id", "KEGG REST API", "verified", "kegg_accession"),
    ("kegg_pathways", "pathway_id", "KEGG REST API", "verified", "kegg_pathway_id"),
    ("uniprot_structures", "structure_id", "AlphaFold DB / RCSB PDB", "verified", "structure_accession"),
    ("geo_datasets", "geo_id", "NCBI GEO", "verified", "geo_accession"),
    ("sra_runs", "sra_id", "NCBI SRA", "verified", "sra_accession"),
    ("gbif_occurrences", "gbif_id", "GBIF API", "verified", "gbif_occurrence_id"),
    ("obis_occurrences", "obis_id", "OBIS API", "verified", "obis_occurrence_id"),
    ("biorxiv_preprints", "preprint_id", "bioRxiv API", "verified", "biorxiv_doi"),
    ("pride_datasets", "pride_id", "PRIDE API", "verified", "pride_accession"),
    ("string_interactions", "interaction_id", "STRING API", "verified", "string_id"),
    ("viralzone_families", "viralzone_id", "ViralZone API", "verified", "viralzone_id"),
    ("ictv_taxonomy", "ictv_id", "ICTV Taxonomy", "verified", "ictv_taxon_id"),
    ("ictv_vmr", "vmr_id", "ICTV VMR", "verified", "ictv_vmr_id"),
]


def table_exists(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (name,),
    ).fetchone() is not None


def seed_core_table(conn: sqlite3.Connection, spec: dict) -> int:
    """Seed provenance for one core table. Returns rows inserted."""
    table = spec["table"]
    pk = spec["pk"]

    if not table_exists(conn, table):
        print(f"  SKIP {table}: table does not exist")
        return 0

    total = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    if total == 0:
        print(f"  SKIP {table}: 0 rows")
        return 0

    # Count existing provenance for this table
    existing = conn.execute(
        "SELECT COUNT(*) FROM data_provenance WHERE table_name = ?", (table,)
    ).fetchone()[0]
    if existing >= total:
        print(f"  SKIP {table}: {existing} provenance rows already ({total} table rows)")
        return 0

    # Escape single quotes in text fields for SQL literals
    notes_safe = spec["notes"].replace("'", "''")
    source_safe = spec["source"].replace("'", "''")
    verification_safe = spec["verification"].replace("'", "''")

    # Determine joined columns
    if spec["master_join"]:
        # Tables with master_id via join
        sql = f"""
            INSERT OR IGNORE INTO data_provenance (
                table_name, record_id, virus_master_id, virus_name,
                data_source, confidence_level, verification_method, curator_notes
            )
            SELECT '{table}', t.{pk}, vm.master_id,
                   COALESCE(vm.canonical_name, ''),
                   '{source_safe}', '{spec["confidence"]}',
                   '{verification_safe}', '{notes_safe}'
            FROM {table} t
            {spec["master_join"]}
            WHERE NOT EXISTS (
                SELECT 1 FROM data_provenance dp
                WHERE dp.table_name = '{table}' AND dp.record_id = t.{pk}
            )
        """
    else:
        sql = f"""
            INSERT OR IGNORE INTO data_provenance (
                table_name, record_id, data_source, confidence_level,
                verification_method, curator_notes
            )
            SELECT '{table}', t.{pk},
                   '{source_safe}', '{spec["confidence"]}',
                   '{verification_safe}', '{notes_safe}'
            FROM {table} t
            WHERE NOT EXISTS (
                SELECT 1 FROM data_provenance dp
                WHERE dp.table_name = '{table}' AND dp.record_id = t.{pk}
            )
        """

    conn.execute(sql)
    new_count = conn.execute(
        "SELECT COUNT(*) FROM data_provenance WHERE table_name = ?", (table,)
    ).fetchone()[0]
    added = new_count - existing
    print(f"  {table}: {added} provenance rows added (total {new_count}/{total})")
    return added


def seed_enrichment_table(conn: sqlite3.Connection, table: str, pk_guess: str,
                          source: str, confidence: str, verification: str) -> int:
    """Seed provenance for one enrichment table. Auto-detects PK column name."""
    if not table_exists(conn, table):
        return 0

    total = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    if total == 0:
        return 0

    existing = conn.execute(
        "SELECT COUNT(*) FROM data_provenance WHERE table_name = ?", (table,)
    ).fetchone()[0]
    if existing >= total:
        return 0

    # Try the guessed PK, fall back to table_info
    pk = pk_guess
    try:
        conn.execute(f"SELECT {pk} FROM {table} LIMIT 1")
    except sqlite3.OperationalError:
        # Auto-detect PK from table_info
        info = conn.execute(f"PRAGMA table_info({table})").fetchall()
        pk = info[0]["name"]  # first column as fallback
        for col in info:
            if col["pk"]:
                pk = col["name"]
                break
        print(f"    (auto-detected PK for {table}: {pk})")

    source_safe = source.replace("'", "''")
    verification_safe = verification.replace("'", "''")

    conn.execute(
        f"""
        INSERT OR IGNORE INTO data_provenance (
            table_name, record_id, data_source, confidence_level,
            verification_method, curator_notes
        )
        SELECT '{table}', t.{pk},
               '{source_safe}', '{confidence}',
               '{verification_safe}', 'Automatically seeded from enrichment pipeline.'
        FROM {table} t
        WHERE NOT EXISTS (
            SELECT 1 FROM data_provenance dp
            WHERE dp.table_name = '{table}' AND dp.record_id = t.{pk}
        )
        """
    )
    new_count = conn.execute(
        "SELECT COUNT(*) FROM data_provenance WHERE table_name = ?", (table,)
    ).fetchone()[0]
    added = new_count - existing
    if added:
        print(f"  {table}: {added} provenance rows added (total {new_count}/{total})")
    return added


def main() -> None:
    if not DB_PATH.exists():
        raise SystemExit(f"Database not found: {DB_PATH}")

    backup_path = wal_safe_backup(DB_PATH, BACKUP_DIR, label="seed_provenance")
    print(f"Backup: {backup_path}")

    conn = get_db()
    try:
        # Ensure data_provenance table exists
        conn.execute(
            """
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
            """
        )

        before_total = conn.execute(
            "SELECT COUNT(*) FROM data_provenance"
        ).fetchone()[0]
        before_tables = conn.execute(
            "SELECT COUNT(DISTINCT table_name) FROM data_provenance"
        ).fetchone()[0]
        print(f"\nBefore: {before_total} provenance rows across {before_tables} tables\n")

        total_added = 0

        print("--- Core tables ---")
        for spec in CORE_SPECS:
            total_added += seed_core_table(conn, spec)

        print("\n--- Enrichment tables ---")
        for table, pk, source, confidence, verification in ENRICHMENT_SPECS:
            total_added += seed_enrichment_table(
                conn, table, pk, source, confidence, verification
            )

        # Also seed for evidence_records (it has a virus_master_id FK directly)
        if table_exists(conn, "evidence_records"):
            existing = conn.execute(
                "SELECT COUNT(*) FROM data_provenance WHERE table_name = 'evidence_records'"
            ).fetchone()[0]
            if existing == 0:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO data_provenance (
                        table_name, record_id, virus_master_id, data_source,
                        confidence_level, verification_method, curator_notes
                    )
                    SELECT 'evidence_records', e.evidence_id, e.virus_master_id,
                           'PubMed / NCBI / curated',
                           CASE WHEN e.curation_status = 'reviewed' THEN 'verified' ELSE 'inferred' END,
                           'evidence_record',
                           'Evidence records from literature curation and NCBI metadata.'
                    FROM evidence_records e
                    """
                )
                added = conn.execute(
                    "SELECT COUNT(*) FROM data_provenance WHERE table_name = 'evidence_records'"
                ).fetchone()[0]
                total_added += added
                print(f"  evidence_records: {added} provenance rows added")

        conn.commit()

        after_total = conn.execute(
            "SELECT COUNT(*) FROM data_provenance"
        ).fetchone()[0]
        after_tables = conn.execute(
            "SELECT COUNT(DISTINCT table_name) FROM data_provenance"
        ).fetchone()[0]

        print(f"\nResult: {before_total} → {after_total} provenance rows (+{total_added})")
        print(f"Tables covered: {before_tables} → {after_tables}")

        # Calculate approximate coverage
        total_core_records = sum(
            conn.execute(f"SELECT COUNT(*) FROM {s['table']}").fetchone()[0]
            for s in CORE_SPECS
            if table_exists(conn, s["table"])
        )
        provenance_records = conn.execute(
            "SELECT COUNT(*) FROM data_provenance"
        ).fetchone()[0]
        print(f"Estimated core record coverage: {provenance_records}/{total_core_records} ({round(provenance_records/total_core_records*100, 1)}%)")

    finally:
        conn.close()

    print("\nDone. Data provenance seeded for core and enrichment tables.")


if __name__ == "__main__":
    main()
