"""
Create and seed curated isolate profile tables.

This implements the first IVCDB-inspired layer:
- one reviewable profile per viral isolate/accession
- explicit reference links by role
- conflict records where GenBank-derived metadata and curated/standard layers disagree
- media asset container for future EM/tissue/host images

The script is non-destructive and can be rerun.
"""

from __future__ import annotations

import shutil
import sqlite3
from datetime import datetime
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "crustacean_virus_core.db"
BACKUP_DIR = BASE_DIR / "backups"


COUNTRY_TO_CONTINENT = {
    "China": "Asia",
    "Thailand": "Asia",
    "Vietnam": "Asia",
    "India": "Asia",
    "Bangladesh": "Asia",
    "Iran": "Asia",
    "Philippines": "Asia",
    "Japan": "Asia",
    "Indonesia": "Asia",
    "Malaysia": "Asia",
    "Singapore": "Asia",
    "South Korea": "Asia",
    "Taiwan": "Asia",
    "Mexico": "North America",
    "United States": "North America",
    "Canada": "North America",
    "Panama": "North America",
    "Ecuador": "South America",
    "Brazil": "South America",
    "Peru": "South America",
    "Chile": "South America",
    "Australia": "Oceania",
    "Egypt": "Africa",
    "South Africa": "Africa",
    "France": "Europe",
    "Spain": "Europe",
    "Netherlands": "Europe",
    "United Kingdom": "Europe",
    "Italy": "Europe",
}


def backup_database() -> Path:
    BACKUP_DIR.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = BACKUP_DIR / f"crustacean_virus_core_before_isolate_profiles_{stamp}.db"
    shutil.copy2(DB_PATH, backup_path)
    return backup_path


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        PRAGMA foreign_keys = ON;

        CREATE TABLE IF NOT EXISTS isolate_curated_profiles (
            profile_id INTEGER PRIMARY KEY AUTOINCREMENT,
            isolate_id INTEGER NOT NULL UNIQUE,
            accession TEXT NOT NULL UNIQUE,
            master_id INTEGER,
            canonical_virus_name TEXT,
            raw_virus_name TEXT,
            isolate_designation TEXT,
            ictv_species TEXT,
            ictv_id TEXT,
            virus_family TEXT,
            virus_genus TEXT,
            genome_type TEXT,
            completeness TEXT,
            sequence_length INTEGER,
            genome_length INTEGER,
            gc_content REAL,
            host_id INTEGER,
            host_scientific_name TEXT,
            host_common_name_cn TEXT,
            host_taxid TEXT,
            host_is_target INTEGER CHECK (host_is_target IN (0, 1)),
            sample_source TEXT,
            collection_id INTEGER,
            specific_site TEXT,
            city TEXT,
            province_state TEXT,
            country TEXT,
            continent TEXT,
            latitude REAL,
            longitude REAL,
            elevation_m REAL,
            collection_year TEXT,
            collection_date TEXT,
            location_precision TEXT CHECK (
                location_precision IS NULL OR location_precision IN (
                    'exact_coordinates',
                    'site',
                    'city',
                    'province_state',
                    'country',
                    'unknown'
                )
            ),
            coordinates_source TEXT,
            primary_reference_id INTEGER,
            genome_reference_id INTEGER,
            discovery_reference_id INTEGER,
            metadata_source_priority TEXT DEFAULT 'genbank_until_literature_checked' CHECK (
                metadata_source_priority IN (
                    'original_reference',
                    'genbank_until_literature_checked',
                    'manual_curated',
                    'mixed_with_conflicts'
                )
            ),
            curation_status TEXT DEFAULT 'needs_review' CHECK (
                curation_status IN ('needs_review', 'auto_seeded', 'manual_checked', 'conflict_open')
            ),
            confidence TEXT DEFAULT 'medium' CHECK (
                confidence IN ('high', 'medium', 'low', 'unknown')
            ),
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            notes TEXT,
            FOREIGN KEY (isolate_id) REFERENCES viral_isolates(isolate_id),
            FOREIGN KEY (master_id) REFERENCES virus_master(master_id),
            FOREIGN KEY (host_id) REFERENCES crustacean_hosts(host_id),
            FOREIGN KEY (collection_id) REFERENCES sample_collections(collection_id),
            FOREIGN KEY (primary_reference_id) REFERENCES ref_literatures(reference_id),
            FOREIGN KEY (genome_reference_id) REFERENCES ref_literatures(reference_id),
            FOREIGN KEY (discovery_reference_id) REFERENCES ref_literatures(reference_id)
        );

        CREATE TABLE IF NOT EXISTS isolate_reference_links (
            link_id INTEGER PRIMARY KEY AUTOINCREMENT,
            isolate_id INTEGER NOT NULL,
            reference_id INTEGER NOT NULL,
            link_type TEXT NOT NULL CHECK (
                link_type IN (
                    'genbank_reference',
                    'infection_record_reference',
                    'genome_sequencing',
                    'initial_discovery',
                    'collection_or_isolation',
                    'curation_evidence',
                    'other'
                )
            ),
            source_table TEXT,
            source_field TEXT,
            priority INTEGER DEFAULT 100,
            evidence_status TEXT DEFAULT 'auto_seeded' CHECK (
                evidence_status IN ('auto_seeded', 'manual_checked', 'rejected')
            ),
            notes TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (isolate_id) REFERENCES viral_isolates(isolate_id),
            FOREIGN KEY (reference_id) REFERENCES ref_literatures(reference_id),
            UNIQUE (isolate_id, reference_id, link_type)
        );

        CREATE TABLE IF NOT EXISTS curation_conflicts (
            conflict_id INTEGER PRIMARY KEY AUTOINCREMENT,
            entity_type TEXT NOT NULL CHECK (
                entity_type IN ('isolate', 'virus', 'host', 'collection', 'reference')
            ),
            entity_id INTEGER NOT NULL,
            isolate_id INTEGER,
            field_name TEXT NOT NULL,
            value_a TEXT,
            source_a TEXT,
            value_b TEXT,
            source_b TEXT,
            conflict_type TEXT NOT NULL CHECK (
                conflict_type IN (
                    'missing_in_profile',
                    'value_mismatch',
                    'taxonomy_mismatch',
                    'reference_mismatch',
                    'non_target_or_noise',
                    'ambiguous_mapping'
                )
            ),
            severity TEXT DEFAULT 'medium' CHECK (
                severity IN ('high', 'medium', 'low')
            ),
            status TEXT DEFAULT 'open' CHECK (
                status IN ('open', 'resolved', 'accepted_a', 'accepted_b', 'ignored')
            ),
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            resolved_at TEXT,
            notes TEXT,
            FOREIGN KEY (isolate_id) REFERENCES viral_isolates(isolate_id)
        );

        CREATE TABLE IF NOT EXISTS isolate_media_assets (
            asset_id INTEGER PRIMARY KEY AUTOINCREMENT,
            isolate_id INTEGER NOT NULL,
            asset_type TEXT NOT NULL CHECK (
                asset_type IN ('host_photo', 'tissue_section', 'electron_micrograph', 'gross_sign', 'pond_site', 'other')
            ),
            title TEXT,
            file_path TEXT,
            source_url TEXT,
            reference_id INTEGER,
            license TEXT,
            caption TEXT,
            curation_status TEXT DEFAULT 'needs_review' CHECK (
                curation_status IN ('needs_review', 'manual_checked', 'rejected')
            ),
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (isolate_id) REFERENCES viral_isolates(isolate_id),
            FOREIGN KEY (reference_id) REFERENCES ref_literatures(reference_id)
        );

        CREATE INDEX IF NOT EXISTS idx_icp_master ON isolate_curated_profiles(master_id);
        CREATE INDEX IF NOT EXISTS idx_icp_host ON isolate_curated_profiles(host_id);
        CREATE INDEX IF NOT EXISTS idx_icp_country ON isolate_curated_profiles(country);
        CREATE INDEX IF NOT EXISTS idx_icp_year ON isolate_curated_profiles(collection_year);
        CREATE INDEX IF NOT EXISTS idx_icp_status ON isolate_curated_profiles(curation_status);
        CREATE INDEX IF NOT EXISTS idx_irl_isolate ON isolate_reference_links(isolate_id);
        CREATE INDEX IF NOT EXISTS idx_irl_reference ON isolate_reference_links(reference_id);
        CREATE INDEX IF NOT EXISTS idx_conflicts_isolate ON curation_conflicts(isolate_id);
        CREATE INDEX IF NOT EXISTS idx_conflicts_status ON curation_conflicts(status);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_conflicts_unique_open_seed
            ON curation_conflicts(
                entity_type,
                entity_id,
                COALESCE(isolate_id, -1),
                field_name,
                conflict_type,
                COALESCE(value_a, ''),
                COALESCE(value_b, '')
            );
        CREATE INDEX IF NOT EXISTS idx_media_isolate ON isolate_media_assets(isolate_id);
        """
    )


def location_precision(row: sqlite3.Row) -> str:
    if row["latitude"] is not None and row["longitude"] is not None:
        return "exact_coordinates"
    if row["specific_site"]:
        return "site"
    if row["city"]:
        return "city"
    if row["province_state"]:
        return "province_state"
    if row["country"]:
        return "country"
    return "unknown"


def first_reference_id(row: sqlite3.Row) -> int | None:
    return row["viral_reference_id"] or row["infection_reference_id"]


def seed_profiles(conn: sqlite3.Connection) -> int:
    before = conn.total_changes
    rows = conn.execute(
        """
        SELECT
            v.isolate_id,
            v.accession,
            v.master_id,
            v.virus_name AS raw_virus_name,
            v.genome_length,
            v.gc_content,
            v.genome_type AS isolate_genome_type,
            v.sequence_length,
            v.completeness,
            v.reference_id AS viral_reference_id,
            v.taxon_family AS isolate_taxon_family,
            v.taxon_genus AS isolate_taxon_genus,
            vm.canonical_name,
            vm.virus_family AS master_family,
            vm.virus_genus AS master_genus,
            vm.genome_type AS master_genome_type,
            ir.reference_id AS infection_reference_id,
            ir.host_id,
            ir.collection_id,
            ir.isolation_source,
            ir.detection_method,
            h.scientific_name AS host_scientific_name,
            h.common_name_cn AS host_common_name_cn,
            h.host_group,
            htp.ncbi_taxid AS host_taxid,
            htp.is_target_host AS host_is_target,
            s.site_name AS specific_site,
            s.city,
            s.province AS province_state,
            s.country,
            s.latitude,
            s.longitude,
            s.collection_year,
            s.collection_date,
            s.source_type AS collection_source_type,
            s.note AS collection_note,
            (
                SELECT it.species
                FROM virus_ictv_mappings vim
                JOIN ictv_taxonomy it ON vim.ictv_id = it.ictv_id
                WHERE vim.master_id = v.master_id
                  AND vim.match_status <> 'rejected'
                ORDER BY
                  CASE vim.match_status WHEN 'manual_checked' THEN 0 ELSE 1 END,
                  CASE vim.match_type WHEN 'species_exact' THEN 0 ELSE 1 END
                LIMIT 1
            ) AS ictv_species,
            (
                SELECT it.official_ictv_id
                FROM virus_ictv_mappings vim
                JOIN ictv_taxonomy it ON vim.ictv_id = it.ictv_id
                WHERE vim.master_id = v.master_id
                  AND vim.match_status <> 'rejected'
                ORDER BY
                  CASE vim.match_status WHEN 'manual_checked' THEN 0 ELSE 1 END,
                  CASE vim.match_type WHEN 'species_exact' THEN 0 ELSE 1 END
                LIMIT 1
            ) AS ictv_id
        FROM viral_isolates v
        LEFT JOIN virus_master vm ON v.master_id = vm.master_id
        LEFT JOIN infection_records ir ON v.isolate_id = ir.isolate_id
        LEFT JOIN crustacean_hosts h ON ir.host_id = h.host_id
        LEFT JOIN host_taxonomy_profiles htp ON h.host_id = htp.host_id
        LEFT JOIN sample_collections s ON ir.collection_id = s.collection_id
        """
    ).fetchall()

    for row in rows:
        continent = COUNTRY_TO_CONTINENT.get(row["country"])
        precision = location_precision(row)
        primary_ref = first_reference_id(row)
        has_conflict = row["host_is_target"] == 0 or precision == "unknown" or primary_ref is None
        source_priority = "genbank_until_literature_checked"
        curation_status = "conflict_open" if has_conflict else "auto_seeded"
        confidence = "medium"
        notes = "Seeded from current normalized core tables. Original-reference verification pending."
        conn.execute(
            """
            INSERT INTO isolate_curated_profiles
                (
                    isolate_id, accession, master_id, canonical_virus_name, raw_virus_name,
                    isolate_designation, ictv_species, ictv_id, virus_family, virus_genus,
                    genome_type, completeness, sequence_length, genome_length, gc_content,
                    host_id, host_scientific_name, host_common_name_cn, host_taxid,
                    host_is_target, sample_source, collection_id, specific_site, city,
                    province_state, country, continent, latitude, longitude, collection_year,
                    collection_date, location_precision, coordinates_source,
                    primary_reference_id, genome_reference_id, discovery_reference_id,
                    metadata_source_priority, curation_status, confidence, notes
                )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(isolate_id) DO UPDATE SET
                accession = excluded.accession,
                master_id = excluded.master_id,
                canonical_virus_name = excluded.canonical_virus_name,
                raw_virus_name = excluded.raw_virus_name,
                ictv_species = excluded.ictv_species,
                ictv_id = excluded.ictv_id,
                virus_family = excluded.virus_family,
                virus_genus = excluded.virus_genus,
                genome_type = excluded.genome_type,
                completeness = excluded.completeness,
                sequence_length = excluded.sequence_length,
                genome_length = excluded.genome_length,
                gc_content = excluded.gc_content,
                host_id = excluded.host_id,
                host_scientific_name = excluded.host_scientific_name,
                host_common_name_cn = excluded.host_common_name_cn,
                host_taxid = excluded.host_taxid,
                host_is_target = excluded.host_is_target,
                sample_source = excluded.sample_source,
                collection_id = excluded.collection_id,
                specific_site = excluded.specific_site,
                city = excluded.city,
                province_state = excluded.province_state,
                country = excluded.country,
                continent = excluded.continent,
                latitude = excluded.latitude,
                longitude = excluded.longitude,
                collection_year = excluded.collection_year,
                collection_date = excluded.collection_date,
                location_precision = excluded.location_precision,
                coordinates_source = excluded.coordinates_source,
                primary_reference_id = excluded.primary_reference_id,
                genome_reference_id = excluded.genome_reference_id,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                row["isolate_id"],
                row["accession"],
                row["master_id"],
                row["canonical_name"],
                row["raw_virus_name"],
                row["accession"],
                row["ictv_species"],
                row["ictv_id"],
                row["master_family"] or row["isolate_taxon_family"],
                row["master_genus"] or row["isolate_taxon_genus"],
                row["master_genome_type"] or row["isolate_genome_type"],
                row["completeness"],
                row["sequence_length"],
                row["genome_length"],
                row["gc_content"],
                row["host_id"],
                row["host_scientific_name"],
                row["host_common_name_cn"],
                row["host_taxid"],
                row["host_is_target"],
                row["isolation_source"] or row["collection_note"],
                row["collection_id"],
                row["specific_site"],
                row["city"],
                row["province_state"],
                row["country"],
                continent,
                row["latitude"],
                row["longitude"],
                row["collection_year"],
                row["collection_date"],
                precision,
                row["collection_source_type"],
                primary_ref,
                row["viral_reference_id"],
                None,
                source_priority,
                curation_status,
                confidence,
                notes,
            ),
        )
    return conn.total_changes - before


def seed_reference_links(conn: sqlite3.Connection) -> int:
    before = conn.total_changes
    rows = conn.execute(
        """
        SELECT v.isolate_id, v.reference_id AS viral_reference_id, ir.reference_id AS infection_reference_id
        FROM viral_isolates v
        LEFT JOIN infection_records ir ON v.isolate_id = ir.isolate_id
        """
    ).fetchall()
    for row in rows:
        if row["viral_reference_id"]:
            conn.execute(
                """
                INSERT OR IGNORE INTO isolate_reference_links
                    (isolate_id, reference_id, link_type, source_table, source_field, priority, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row["isolate_id"],
                    row["viral_reference_id"],
                    "genbank_reference",
                    "viral_isolates",
                    "reference_id",
                    50,
                    "Seeded from viral_isolates.reference_id.",
                ),
            )
        if row["infection_reference_id"]:
            conn.execute(
                """
                INSERT OR IGNORE INTO isolate_reference_links
                    (isolate_id, reference_id, link_type, source_table, source_field, priority, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row["isolate_id"],
                    row["infection_reference_id"],
                    "infection_record_reference",
                    "infection_records",
                    "reference_id",
                    60,
                    "Seeded from infection_records.reference_id.",
                ),
            )
    return conn.total_changes - before


def conflict_insert(
    conn: sqlite3.Connection,
    entity_type: str,
    entity_id: int,
    isolate_id: int | None,
    field_name: str,
    value_a,
    source_a: str,
    value_b,
    source_b: str,
    conflict_type: str,
    severity: str,
    notes: str,
) -> None:
    conn.execute(
        """
        INSERT OR IGNORE INTO curation_conflicts
            (
                entity_type, entity_id, isolate_id, field_name,
                value_a, source_a, value_b, source_b,
                conflict_type, severity, notes
            )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            entity_type,
            entity_id,
            isolate_id,
            field_name,
            None if value_a is None else str(value_a),
            source_a,
            None if value_b is None else str(value_b),
            source_b,
            conflict_type,
            severity,
            notes,
        ),
    )


def seed_conflicts(conn: sqlite3.Connection) -> int:
    before = conn.total_changes
    rows = conn.execute(
        """
        SELECT
            p.*,
            v.taxon_family AS isolate_taxon_family,
            v.taxon_genus AS isolate_taxon_genus,
            v.reference_id AS viral_reference_id,
            ir.reference_id AS infection_reference_id,
            vm.entry_type,
            vm.is_crustacean_virus
        FROM isolate_curated_profiles p
        JOIN viral_isolates v ON p.isolate_id = v.isolate_id
        LEFT JOIN infection_records ir ON p.isolate_id = ir.isolate_id
        LEFT JOIN virus_master vm ON p.master_id = vm.master_id
        """
    ).fetchall()
    for row in rows:
        isolate_id = row["isolate_id"]
        if row["host_id"] is None:
            conflict_insert(conn, "isolate", isolate_id, isolate_id, "host_id", None, "profile", None, "infection_records", "missing_in_profile", "high", "Host is missing.")
        if row["country"] is None:
            conflict_insert(conn, "collection", row["collection_id"] or isolate_id, isolate_id, "country", None, "profile", None, "sample_collections", "missing_in_profile", "medium", "Country is missing.")
        if row["location_precision"] == "unknown":
            conflict_insert(conn, "collection", row["collection_id"] or isolate_id, isolate_id, "location", None, "profile", None, "sample_collections", "missing_in_profile", "medium", "No usable location level.")
        if row["primary_reference_id"] is None:
            conflict_insert(conn, "reference", isolate_id, isolate_id, "primary_reference_id", None, "profile", None, "ref_literatures", "missing_in_profile", "high", "No linked literature reference.")
        if row["viral_reference_id"] and row["infection_reference_id"] and row["viral_reference_id"] != row["infection_reference_id"]:
            conflict_insert(
                conn,
                "reference",
                isolate_id,
                isolate_id,
                "reference_id",
                row["viral_reference_id"],
                "viral_isolates.reference_id",
                row["infection_reference_id"],
                "infection_records.reference_id",
                "reference_mismatch",
                "medium",
                "Different references are linked at isolate and infection-record levels.",
            )
        if row["host_is_target"] == 0:
            conflict_insert(
                conn,
                "host",
                row["host_id"] or isolate_id,
                isolate_id,
                "host_is_target",
                0,
                "host_taxonomy_profiles",
                row["host_scientific_name"],
                "crustacean_hosts",
                "non_target_or_noise",
                "high",
                "Host profile is marked as non-target/non-crustacean.",
            )
        if row["entry_type"] in {"non_target", "EST", "patent"} or row["is_crustacean_virus"] == 0:
            conflict_insert(
                conn,
                "virus",
                row["master_id"] or isolate_id,
                isolate_id,
                "entry_type",
                row["entry_type"],
                "virus_master",
                row["canonical_virus_name"],
                "virus_master.canonical_name",
                "non_target_or_noise",
                "medium",
                "Virus master entry is marked as non-target/noise-like for curated disease isolate profile.",
            )
        if row["virus_family"] and row["isolate_taxon_family"] and row["virus_family"] != row["isolate_taxon_family"]:
            conflict_insert(
                conn,
                "virus",
                row["master_id"] or isolate_id,
                isolate_id,
                "virus_family",
                row["virus_family"],
                "curated/ICTV layer",
                row["isolate_taxon_family"],
                "viral_isolates.taxon_family",
                "taxonomy_mismatch",
                "low",
                "Family differs between curated master layer and isolate metadata.",
            )
        if row["virus_genus"] and row["isolate_taxon_genus"] and row["virus_genus"] != row["isolate_taxon_genus"]:
            conflict_insert(
                conn,
                "virus",
                row["master_id"] or isolate_id,
                isolate_id,
                "virus_genus",
                row["virus_genus"],
                "curated/ICTV layer",
                row["isolate_taxon_genus"],
                "viral_isolates.taxon_genus",
                "taxonomy_mismatch",
                "low",
                "Genus differs between curated master layer and isolate metadata.",
            )
    conn.execute(
        """
        UPDATE isolate_curated_profiles
        SET curation_status = 'conflict_open',
            metadata_source_priority = 'mixed_with_conflicts',
            updated_at = CURRENT_TIMESTAMP
        WHERE isolate_id IN (
            SELECT DISTINCT isolate_id
            FROM curation_conflicts
            WHERE isolate_id IS NOT NULL
              AND status = 'open'
        )
        """
    )
    return conn.total_changes - before


def log_run(conn: sqlite3.Connection, profile_changes: int, reference_changes: int, conflict_changes: int) -> None:
    source_id_row = conn.execute("SELECT source_id FROM external_sources WHERE source_key = 'local_curation'").fetchone()
    source_id = source_id_row["source_id"] if source_id_row else None
    conn.execute(
        """
        INSERT INTO curation_logs
            (entity_type, action, source_id, new_value, confidence, curator, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "isolate_curated_profiles",
            "add_isolate_curated_profiles",
            source_id,
            f"profile_changes={profile_changes}; reference_changes={reference_changes}; conflict_changes={conflict_changes}",
            "high",
            "add_isolate_curated_profiles.py",
            "Seeded IVCDB-style isolate profile, reference link, media container, and conflict tables.",
        ),
    )


def main() -> None:
    backup_path = backup_database()
    print(f"[backup] {backup_path}")
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        ensure_schema(conn)
        profile_changes = seed_profiles(conn)
        reference_changes = seed_reference_links(conn)
        conflict_changes = seed_conflicts(conn)
        log_run(conn, profile_changes, reference_changes, conflict_changes)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    print(f"[done] profile_changes={profile_changes}")
    print(f"[done] reference_changes={reference_changes}")
    print(f"[done] conflict_changes={conflict_changes}")


if __name__ == "__main__":
    main()
