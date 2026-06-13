"""
Add the external database integration and evidence layer.

This migration is intentionally non-destructive:
- existing NCBI-derived core tables are kept unchanged
- new tables store aliases, external IDs, evidence claims, and curation logs
- the script backs up the SQLite database before applying changes
"""

from __future__ import annotations

import re
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "crustacean_virus_core.db"
BACKUP_DIR = BASE_DIR / "backups"


SOURCES = [
    (
        "local_curation",
        "Local Curation",
        "curation",
        None,
        "Locally curated records, manual review notes, and seeded profile evidence.",
        "manual",
        0,
    ),
    (
        "ncbi_nucleotide",
        "NCBI Nucleotide",
        "sequence",
        "https://www.ncbi.nlm.nih.gov/nuccore/",
        "Primary sequence accessions and GenBank metadata.",
        "sync",
        10,
    ),
    (
        "ncbi_taxonomy",
        "NCBI Taxonomy",
        "taxonomy",
        "https://www.ncbi.nlm.nih.gov/taxonomy/",
        "Taxonomic identifiers for viruses and hosts.",
        "manual_or_api",
        20,
    ),
    (
        "ictv",
        "ICTV",
        "virus_taxonomy",
        "https://ictv.global/",
        "Official virus taxonomy, species names, and higher ranks.",
        "manual_or_release_file",
        30,
    ),
    (
        "worms",
        "WoRMS",
        "host_taxonomy",
        "https://www.marinespecies.org/",
        "Marine species taxonomy and AphiaID mappings for crustacean hosts.",
        "api_or_manual",
        40,
    ),
    (
        "pubmed",
        "PubMed",
        "literature",
        "https://pubmed.ncbi.nlm.nih.gov/",
        "Biomedical literature metadata and evidence source tracking.",
        "api",
        50,
    ),
    (
        "crossref",
        "Crossref",
        "literature",
        "https://www.crossref.org/",
        "DOI metadata and publication cross references.",
        "api",
        60,
    ),
    (
        "uniprot",
        "UniProt",
        "protein",
        "https://www.uniprot.org/",
        "Protein names, accessions, and functional annotations.",
        "api_or_mapping_file",
        70,
    ),
    (
        "pfam",
        "Pfam",
        "protein_domain",
        "https://www.ebi.ac.uk/interpro/entry/pfam/",
        "Protein family and domain annotations.",
        "api_or_interpro",
        80,
    ),
    (
        "interpro",
        "InterPro",
        "protein_domain",
        "https://www.ebi.ac.uk/interpro/",
        "Integrated protein family, domain, and site annotations.",
        "api",
        90,
    ),
    (
        "gbif",
        "GBIF",
        "biodiversity",
        "https://www.gbif.org/",
        "Species occurrence and distribution references.",
        "api",
        100,
    ),
    (
        "fao",
        "FAO",
        "aquaculture",
        "https://www.fao.org/",
        "Aquaculture context, host importance, and production background.",
        "manual_or_dataset",
        110,
    ),
]


def backup_database() -> Path:
    if not DB_PATH.exists():
        raise FileNotFoundError(f"Database not found: {DB_PATH}")
    BACKUP_DIR.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = BACKUP_DIR / f"crustacean_virus_core_before_external_layer_{stamp}.db"
    shutil.copy2(DB_PATH, backup_path)
    return backup_path


def create_tables(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        PRAGMA foreign_keys = ON;

        CREATE TABLE IF NOT EXISTS external_sources (
            source_id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_key TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            category TEXT NOT NULL,
            base_url TEXT,
            description TEXT,
            update_policy TEXT,
            priority INTEGER DEFAULT 100,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS external_xrefs (
            xref_id INTEGER PRIMARY KEY AUTOINCREMENT,
            entity_type TEXT NOT NULL CHECK (
                entity_type IN (
                    'virus_master',
                    'viral_isolate',
                    'host',
                    'reference',
                    'protein',
                    'evidence'
                )
            ),
            entity_id INTEGER NOT NULL,
            source_id INTEGER NOT NULL,
            external_id TEXT NOT NULL,
            external_url TEXT,
            match_status TEXT NOT NULL DEFAULT 'unverified' CHECK (
                match_status IN ('exact', 'fuzzy', 'inferred', 'manual_checked', 'unverified', 'rejected')
            ),
            confidence TEXT DEFAULT 'medium' CHECK (
                confidence IN ('high', 'medium', 'low', 'unknown')
            ),
            matched_by TEXT DEFAULT 'script',
            matched_at TEXT DEFAULT CURRENT_TIMESTAMP,
            notes TEXT,
            FOREIGN KEY (source_id) REFERENCES external_sources(source_id),
            UNIQUE (entity_type, entity_id, source_id, external_id)
        );

        CREATE TABLE IF NOT EXISTS virus_aliases (
            alias_id INTEGER PRIMARY KEY AUTOINCREMENT,
            master_id INTEGER NOT NULL,
            alias TEXT NOT NULL,
            alias_type TEXT NOT NULL DEFAULT 'synonym' CHECK (
                alias_type IN ('canonical', 'abbreviation', 'synonym', 'historical_name', 'raw_name', 'manual_alias')
            ),
            source_id INTEGER,
            external_id TEXT,
            match_status TEXT NOT NULL DEFAULT 'unverified' CHECK (
                match_status IN ('exact', 'fuzzy', 'inferred', 'manual_checked', 'unverified', 'rejected')
            ),
            confidence TEXT DEFAULT 'medium' CHECK (
                confidence IN ('high', 'medium', 'low', 'unknown')
            ),
            is_preferred INTEGER DEFAULT 0 CHECK (is_preferred IN (0, 1)),
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            notes TEXT,
            FOREIGN KEY (master_id) REFERENCES virus_master(master_id),
            FOREIGN KEY (source_id) REFERENCES external_sources(source_id),
            UNIQUE (master_id, alias)
        );

        CREATE TABLE IF NOT EXISTS host_aliases (
            alias_id INTEGER PRIMARY KEY AUTOINCREMENT,
            host_id INTEGER NOT NULL,
            alias TEXT NOT NULL,
            alias_type TEXT NOT NULL DEFAULT 'synonym' CHECK (
                alias_type IN ('scientific_name', 'common_name_cn', 'synonym', 'historical_name', 'raw_name', 'manual_alias')
            ),
            source_id INTEGER,
            external_id TEXT,
            match_status TEXT NOT NULL DEFAULT 'unverified' CHECK (
                match_status IN ('exact', 'fuzzy', 'inferred', 'manual_checked', 'unverified', 'rejected')
            ),
            confidence TEXT DEFAULT 'medium' CHECK (
                confidence IN ('high', 'medium', 'low', 'unknown')
            ),
            is_preferred INTEGER DEFAULT 0 CHECK (is_preferred IN (0, 1)),
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            notes TEXT,
            FOREIGN KEY (host_id) REFERENCES crustacean_hosts(host_id),
            FOREIGN KEY (source_id) REFERENCES external_sources(source_id),
            UNIQUE (host_id, alias)
        );

        CREATE TABLE IF NOT EXISTS evidence_records (
            evidence_id INTEGER PRIMARY KEY AUTOINCREMENT,
            evidence_type TEXT NOT NULL CHECK (
                evidence_type IN (
                    'host_range',
                    'natural_infection',
                    'experimental_infection',
                    'outbreak',
                    'mortality',
                    'symptom',
                    'temperature',
                    'diagnosis',
                    'transmission',
                    'virulence',
                    'pathogenicity',
                    'other'
                )
            ),
            virus_master_id INTEGER,
            host_id INTEGER,
            isolate_id INTEGER,
            reference_id INTEGER,
            source_id INTEGER,
            claim TEXT NOT NULL,
            value_text TEXT,
            value_numeric_min REAL,
            value_numeric_max REAL,
            unit TEXT,
            context TEXT,
            observation_type TEXT CHECK (
                observation_type IS NULL OR observation_type IN (
                    'field',
                    'lab',
                    'database_annotation',
                    'review',
                    'expert_curation',
                    'unknown'
                )
            ),
            evidence_strength TEXT DEFAULT 'medium' CHECK (
                evidence_strength IN ('high', 'medium', 'low', 'unknown')
            ),
            source_pmid TEXT,
            source_doi TEXT,
            extraction_method TEXT DEFAULT 'manual_or_seeded',
            curation_status TEXT DEFAULT 'needs_review' CHECK (
                curation_status IN ('needs_review', 'auto_imported', 'manual_checked', 'rejected')
            ),
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            notes TEXT,
            FOREIGN KEY (virus_master_id) REFERENCES virus_master(master_id),
            FOREIGN KEY (host_id) REFERENCES crustacean_hosts(host_id),
            FOREIGN KEY (isolate_id) REFERENCES viral_isolates(isolate_id),
            FOREIGN KEY (reference_id) REFERENCES ref_literatures(reference_id),
            FOREIGN KEY (source_id) REFERENCES external_sources(source_id)
        );

        CREATE TABLE IF NOT EXISTS curation_logs (
            log_id INTEGER PRIMARY KEY AUTOINCREMENT,
            entity_type TEXT NOT NULL,
            entity_id INTEGER,
            action TEXT NOT NULL,
            source_id INTEGER,
            old_value TEXT,
            new_value TEXT,
            confidence TEXT DEFAULT 'unknown' CHECK (
                confidence IN ('high', 'medium', 'low', 'unknown')
            ),
            curator TEXT DEFAULT 'script',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            notes TEXT,
            FOREIGN KEY (source_id) REFERENCES external_sources(source_id)
        );

        CREATE INDEX IF NOT EXISTS idx_xrefs_entity
            ON external_xrefs(entity_type, entity_id);
        CREATE INDEX IF NOT EXISTS idx_xrefs_source_external
            ON external_xrefs(source_id, external_id);
        CREATE INDEX IF NOT EXISTS idx_virus_aliases_alias
            ON virus_aliases(alias);
        CREATE INDEX IF NOT EXISTS idx_virus_aliases_master
            ON virus_aliases(master_id);
        CREATE INDEX IF NOT EXISTS idx_host_aliases_alias
            ON host_aliases(alias);
        CREATE INDEX IF NOT EXISTS idx_host_aliases_host
            ON host_aliases(host_id);
        CREATE INDEX IF NOT EXISTS idx_evidence_virus
            ON evidence_records(virus_master_id);
        CREATE INDEX IF NOT EXISTS idx_evidence_host
            ON evidence_records(host_id);
        CREATE INDEX IF NOT EXISTS idx_evidence_reference
            ON evidence_records(reference_id);
        CREATE INDEX IF NOT EXISTS idx_evidence_type
            ON evidence_records(evidence_type);
        """
    )


def seed_sources(conn: sqlite3.Connection) -> dict[str, int]:
    conn.executemany(
        """
        INSERT INTO external_sources
            (source_key, name, category, base_url, description, update_policy, priority)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(source_key) DO UPDATE SET
            name = excluded.name,
            category = excluded.category,
            base_url = excluded.base_url,
            description = excluded.description,
            update_policy = excluded.update_policy,
            priority = excluded.priority,
            updated_at = CURRENT_TIMESTAMP
        """,
        SOURCES,
    )
    rows = conn.execute("SELECT source_key, source_id FROM external_sources").fetchall()
    return {row["source_key"]: row["source_id"] for row in rows}


def split_aliases(value: str | None) -> list[str]:
    if not value:
        return []
    parts = re.split(r"[;,/|]+", value)
    return [part.strip() for part in parts if part and part.strip()]


def seed_virus_aliases(conn: sqlite3.Connection, source_ids: dict[str, int]) -> int:
    before = conn.total_changes
    ncbi_source = source_ids["ncbi_nucleotide"]
    rows = conn.execute(
        """
        SELECT master_id, canonical_name, abbreviations
        FROM virus_master
        WHERE canonical_name IS NOT NULL AND TRIM(canonical_name) <> ''
        """
    ).fetchall()
    inserts = []
    for row in rows:
        inserts.append(
            (
                row["master_id"],
                row["canonical_name"],
                "canonical",
                ncbi_source,
                "exact",
                "high",
                1,
                "Seeded from virus_master.canonical_name",
            )
        )
        for alias in split_aliases(row["abbreviations"]):
            inserts.append(
                (
                    row["master_id"],
                    alias,
                    "abbreviation",
                    ncbi_source,
                    "inferred",
                    "medium",
                    0,
                    "Seeded from virus_master.abbreviations",
                )
            )

    conn.executemany(
        """
        INSERT OR IGNORE INTO virus_aliases
            (master_id, alias, alias_type, source_id, match_status, confidence, is_preferred, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        inserts,
    )
    return conn.total_changes - before


def seed_host_aliases(conn: sqlite3.Connection, source_ids: dict[str, int]) -> int:
    before = conn.total_changes
    ncbi_source = source_ids["ncbi_nucleotide"]
    rows = conn.execute(
        """
        SELECT host_id, scientific_name, common_name_cn
        FROM crustacean_hosts
        WHERE scientific_name IS NOT NULL AND TRIM(scientific_name) <> ''
        """
    ).fetchall()
    inserts = []
    for row in rows:
        inserts.append(
            (
                row["host_id"],
                row["scientific_name"],
                "scientific_name",
                ncbi_source,
                "exact",
                "high",
                1,
                "Seeded from crustacean_hosts.scientific_name",
            )
        )
        if row["common_name_cn"]:
            inserts.append(
                (
                    row["host_id"],
                    row["common_name_cn"],
                    "common_name_cn",
                    ncbi_source,
                    "exact",
                    "medium",
                    0,
                    "Seeded from crustacean_hosts.common_name_cn",
                )
            )

    conn.executemany(
        """
        INSERT OR IGNORE INTO host_aliases
            (host_id, alias, alias_type, source_id, match_status, confidence, is_preferred, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        inserts,
    )
    return conn.total_changes - before


def seed_reference_xrefs(conn: sqlite3.Connection, source_ids: dict[str, int]) -> int:
    before = conn.total_changes
    pubmed_source = source_ids["pubmed"]
    crossref_source = source_ids["crossref"]
    rows = conn.execute(
        """
        SELECT reference_id, pmid, doi
        FROM ref_literatures
        WHERE (pmid IS NOT NULL AND TRIM(pmid) <> '')
           OR (doi IS NOT NULL AND TRIM(doi) <> '')
        """
    ).fetchall()
    inserts = []
    for row in rows:
        if row["pmid"]:
            inserts.append(
                (
                    "reference",
                    row["reference_id"],
                    pubmed_source,
                    row["pmid"].strip(),
                    f"https://pubmed.ncbi.nlm.nih.gov/{row['pmid'].strip()}/",
                    "exact",
                    "high",
                    "Seeded from ref_literatures.pmid",
                )
            )
        if row["doi"]:
            doi = row["doi"].strip()
            inserts.append(
                (
                    "reference",
                    row["reference_id"],
                    crossref_source,
                    doi,
                    f"https://doi.org/{doi}",
                    "exact",
                    "high",
                    "Seeded from ref_literatures.doi",
                )
            )

    conn.executemany(
        """
        INSERT OR IGNORE INTO external_xrefs
            (entity_type, entity_id, source_id, external_id, external_url, match_status, confidence, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        inserts,
    )
    return conn.total_changes - before


def seed_isolate_xrefs(conn: sqlite3.Connection, source_ids: dict[str, int]) -> int:
    before = conn.total_changes
    ncbi_source = source_ids["ncbi_nucleotide"]
    rows = conn.execute(
        """
        SELECT isolate_id, accession
        FROM viral_isolates
        WHERE accession IS NOT NULL AND TRIM(accession) <> ''
        """
    ).fetchall()
    inserts = [
        (
            "viral_isolate",
            row["isolate_id"],
            ncbi_source,
            row["accession"].strip(),
            f"https://www.ncbi.nlm.nih.gov/nuccore/{row['accession'].strip()}",
            "exact",
            "high",
            "Seeded from viral_isolates.accession",
        )
        for row in rows
    ]
    conn.executemany(
        """
        INSERT OR IGNORE INTO external_xrefs
            (entity_type, entity_id, source_id, external_id, external_url, match_status, confidence, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        inserts,
    )
    return conn.total_changes - before


def seed_existing_profile_evidence(conn: sqlite3.Connection, source_ids: dict[str, int]) -> int:
    """Convert existing curated profile rows into reviewable evidence records."""
    before = conn.total_changes
    profile_source = source_ids["local_curation"]

    virulence_rows = conn.execute(
        """
        SELECT p.*, vm.master_id
        FROM virulence_profiles p
        LEFT JOIN virus_master vm ON LOWER(p.virus_name) = LOWER(vm.canonical_name)
        """
    ).fetchall()
    temp_rows = conn.execute(
        """
        SELECT p.*, vm.master_id
        FROM temperature_profiles p
        LEFT JOIN virus_master vm ON LOWER(p.virus_name) = LOWER(vm.canonical_name)
        """
    ).fetchall()

    inserts = []
    for row in virulence_rows:
        claim = f"{row['virus_name']} virulence profile: {row['virulence_level'] or 'unknown'}"
        inserts.append(
            (
                "virulence",
                row["master_id"],
                None,
                None,
                profile_source,
                claim,
                row["virulence_level"],
                row["mortality_rate_min"],
                row["mortality_rate_max"],
                "percent_mortality",
                row["pathogenic_mechanism"],
                "expert_curation",
                (row["confidence"] or "medium").lower(),
                "seeded_from_virulence_profiles",
                "needs_review",
                row["notes"],
            )
        )

    for row in temp_rows:
        claim = f"{row['virus_name']} temperature profile"
        inserts.append(
            (
                "temperature",
                row["master_id"],
                None,
                None,
                profile_source,
                claim,
                row["temp_sensitivity_notes"],
                row["optimal_temp_min"],
                row["optimal_temp_max"],
                "degree_celsius",
                row["climate_change_impact"],
                "expert_curation",
                (row["confidence"] or "medium").lower(),
                "seeded_from_temperature_profiles",
                "needs_review",
                row["notes"],
            )
        )

    cleaned = []
    for item in inserts:
        values = list(item)
        if values[12] not in {"high", "medium", "low", "unknown"}:
            values[12] = "unknown"
        cleaned.append(tuple(values))

    conn.executemany(
        """
        INSERT INTO evidence_records
            (
                evidence_type, virus_master_id, host_id, reference_id, source_id,
                claim, value_text, value_numeric_min, value_numeric_max, unit,
                context, observation_type, evidence_strength, extraction_method,
                curation_status, notes
            )
        SELECT ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
        WHERE NOT EXISTS (
            SELECT 1
            FROM evidence_records
            WHERE evidence_type = ?
              AND claim = ?
              AND extraction_method = ?
        )
        """,
        [item + (item[0], item[5], item[13]) for item in cleaned],
    )
    return conn.total_changes - before


def repair_seeded_profile_evidence_source(conn: sqlite3.Connection, source_ids: dict[str, int]) -> int:
    before = conn.total_changes
    conn.execute(
        """
        UPDATE evidence_records
        SET source_id = ?,
            updated_at = CURRENT_TIMESTAMP,
            notes = COALESCE(notes, '') || CASE
                WHEN notes IS NULL OR notes = '' THEN ''
                ELSE '; '
            END || 'Source corrected to Local Curation.'
        WHERE extraction_method IN (
            'seeded_from_virulence_profiles',
            'seeded_from_temperature_profiles'
        )
          AND (source_id IS NULL OR source_id <> ?)
        """,
        (source_ids["local_curation"], source_ids["local_curation"]),
    )
    return conn.total_changes - before


def log_migration(conn: sqlite3.Connection, source_ids: dict[str, int]) -> None:
    conn.execute(
        """
        INSERT INTO curation_logs
            (entity_type, action, source_id, new_value, confidence, curator, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "database",
            "add_external_integration_layer",
            source_ids["local_curation"],
            "external_sources, external_xrefs, virus_aliases, host_aliases, evidence_records, curation_logs",
            "high",
            "add_external_integration_layer.py",
            "Non-destructive schema migration for standardization and evidence tracking.",
        ),
    )


def main() -> None:
    backup_path = backup_database()
    print(f"[backup] {backup_path}")

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        create_tables(conn)
        source_ids = seed_sources(conn)
        counts = {
            "virus_aliases": seed_virus_aliases(conn, source_ids),
            "host_aliases": seed_host_aliases(conn, source_ids),
            "reference_xrefs": seed_reference_xrefs(conn, source_ids),
            "isolate_xrefs": seed_isolate_xrefs(conn, source_ids),
            "profile_evidence": seed_existing_profile_evidence(conn, source_ids),
            "profile_evidence_source_repairs": repair_seeded_profile_evidence_source(conn, source_ids),
        }
        log_migration(conn, source_ids)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    print("[done] External integration layer added.")
    for name, count in counts.items():
        print(f"[seed] {name}: {count}")


if __name__ == "__main__":
    main()
