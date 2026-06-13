#!/usr/bin/env python3
"""Publication hardening fixes for the crustacean virus database.

This script fixes engineering-level issues without inventing biological
evidence. It adds explicit publication-use flags, controlled source fields,
FK indexes, compatibility views, and curator worklists for items that require
manual literature or taxonomy review.
"""

from __future__ import annotations

import csv
import json
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from db_utils import backup_database as wal_safe_backup


BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "crustacean_virus_core.db"
BACKUP_DIR = BASE_DIR / "backups"
REPORTS_DIR = BASE_DIR / "reports"


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn


def qident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def table_exists(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (name,),
    ).fetchone() is not None


def view_exists(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='view' AND name=?",
        (name,),
    ).fetchone() is not None


def column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    return any(row["name"] == column for row in conn.execute(f"PRAGMA table_info({qident(table)})"))


def add_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> bool:
    if column_exists(conn, table, column):
        return False
    conn.execute(f"ALTER TABLE {qident(table)} ADD COLUMN {qident(column)} {definition}")
    return True


def scalar(conn: sqlite3.Connection, sql: str, params: tuple[Any, ...] = ()) -> Any:
    row = conn.execute(sql, params).fetchone()
    return None if row is None else row[0]


def snapshot_metrics(conn: sqlite3.Connection) -> dict[str, Any]:
    metrics: dict[str, Any] = {}
    queries = {
        "protein_total": "SELECT COUNT(*) FROM viral_proteins",
        "protein_unknown": """
            SELECT COUNT(*) FROM viral_proteins
            WHERE COALESCE(functional_category, 'unknown') = 'unknown'
               OR TRIM(COALESCE(functional_category, '')) = ''
        """,
        "esmfold_total": "SELECT COUNT(*) FROM protein_structures",
        "esmfold_plddt_lt50": "SELECT COUNT(*) FROM protein_structures WHERE plddt_score < 50",
        "interpro_total": "SELECT COUNT(*) FROM interpro_annotations",
        "interpro_missing_positions": """
            SELECT COUNT(*) FROM interpro_annotations
            WHERE start_pos IS NULL OR end_pos IS NULL
        """,
        "virus_name_mismatch": """
            SELECT COUNT(*)
            FROM viral_isolates vi
            JOIN virus_master vm ON vm.master_id = vi.master_id
            WHERE TRIM(COALESCE(vi.virus_name, '')) <> ''
              AND TRIM(COALESCE(vm.canonical_name, '')) <> ''
              AND LOWER(TRIM(vi.virus_name)) <> LOWER(TRIM(vm.canonical_name))
        """,
        "references_missing_pmid_doi": """
            SELECT COUNT(*) FROM ref_literatures
            WHERE TRIM(COALESCE(pmid, '')) = ''
              AND TRIM(COALESCE(doi, '')) = ''
        """,
        "isolates_without_proteins": """
            SELECT COUNT(*) FROM viral_isolates vi
            WHERE NOT EXISTS (
                SELECT 1 FROM viral_proteins vp WHERE vp.isolate_id = vi.isolate_id
            )
        """,
        "isolates_without_infection": """
            SELECT COUNT(*) FROM viral_isolates vi
            WHERE NOT EXISTS (
                SELECT 1 FROM infection_records ir WHERE ir.isolate_id = vi.isolate_id
            )
        """,
        "infection_missing_host": "SELECT COUNT(*) FROM infection_records WHERE host_id IS NULL",
        "taxonomy_family_conflicts": """
            SELECT COUNT(*)
            FROM viral_isolates vi
            JOIN virus_master vm ON vm.master_id = vi.master_id
            WHERE TRIM(COALESCE(vi.taxon_family, '')) <> ''
              AND TRIM(COALESCE(vm.virus_family, '')) <> ''
              AND LOWER(TRIM(vi.taxon_family)) <> LOWER(TRIM(vm.virus_family))
        """,
        "reference_link_overlaps_infection": """
            SELECT COUNT(*)
            FROM isolate_reference_links l
            WHERE EXISTS (
                SELECT 1 FROM infection_records ir
                WHERE ir.isolate_id = l.isolate_id
                  AND ir.reference_id = l.reference_id
            )
        """,
        "site_name_nonempty": """
            SELECT COUNT(*) FROM sample_collections
            WHERE TRIM(COALESCE(site_name, '')) <> ''
        """,
        "iucn_assessment_year_nonempty": """
            SELECT COUNT(*) FROM crustacean_hosts
            WHERE TRIM(COALESCE(iucn_assessment_year, '')) <> ''
        """,
        "virus_master_missing_abbreviations": """
            SELECT COUNT(*) FROM virus_master
            WHERE TRIM(COALESCE(abbreviations, '')) = ''
        """,
        "core_orphan_master_entries": """
            SELECT COUNT(*)
            FROM virus_master vm
            LEFT JOIN viral_isolates vi ON vi.master_id = vm.master_id
            WHERE vi.isolate_id IS NULL
              AND COALESCE(vm.is_crustacean_virus, 1) = 1
              AND COALESCE(vm.entry_type, '') NOT IN (
                  'non_target', 'host_genome', 'catalog_only', 'reference_only'
              )
        """,
        "data_provenance_rows": "SELECT COUNT(*) FROM data_provenance",
        "virulence_profile_rows": "SELECT COUNT(*) FROM virulence_profiles",
        "temperature_profile_rows": "SELECT COUNT(*) FROM temperature_profiles",
    }
    for key, sql in queries.items():
        if key.startswith("interpro") and not table_exists(conn, "interpro_annotations"):
            metrics[key] = 0
        else:
            try:
                metrics[key] = scalar(conn, sql)
            except sqlite3.Error as exc:
                metrics[key] = f"ERROR: {exc}"

    metrics["predicted_virulence_profiles_present"] = table_exists(conn, "predicted_virulence_profiles") or view_exists(conn, "predicted_virulence_profiles")
    metrics["predicted_temperature_profiles_present"] = table_exists(conn, "predicted_temperature_profiles") or view_exists(conn, "predicted_temperature_profiles")
    metrics["missing_fk_indexes"] = len(find_missing_fk_indexes(conn))
    return metrics


def backup_database() -> Path:
    return wal_safe_backup(DB_PATH, BACKUP_DIR, label="publication_hardening")


def ensure_vocab(conn: sqlite3.Connection, category: str, term: str, description: str) -> None:
    if not table_exists(conn, "curation_vocab_terms"):
        return
    exists = conn.execute(
        """
        SELECT 1 FROM curation_vocab_terms
        WHERE category = ? AND term = ?
        """,
        (category, term),
    ).fetchone()
    if exists:
        return
    conn.execute(
        """
        INSERT INTO curation_vocab_terms (category, term, description, active)
        VALUES (?, ?, ?, 1)
        """,
        (category, term, description),
    )


def ensure_publication_columns(conn: sqlite3.Connection) -> dict[str, int]:
    added = 0
    for column, definition in {
        "functional_annotation_status": "TEXT DEFAULT 'unannotated'",
        "functional_category_source": "TEXT",
    }.items():
        added += int(add_column(conn, "viral_proteins", column, definition))

    for column, definition in {
        "plddt_raw": "REAL",
        "plddt_scale": "TEXT",
        "plddt_normalized_100": "REAL",
        "confidence_tier": "TEXT",
        "publication_use": "TEXT",
        "quality_notes": "TEXT",
    }.items():
        added += int(add_column(conn, "protein_structures", column, definition))

    if table_exists(conn, "interpro_annotations"):
        for column, definition in {
            "position_status": "TEXT",
            "publication_use": "TEXT",
        }.items():
            added += int(add_column(conn, "interpro_annotations", column, definition))

    for table in ("virulence_profiles", "temperature_profiles"):
        for column, definition in {
            "data_origin": "TEXT",
            "data_source_type": "TEXT",
            "publication_use": "TEXT",
        }.items():
            added += int(add_column(conn, table, column, definition))

    if table_exists(conn, "virulence_profiles"):
        for column, definition in {
            "mortality_rate_min_raw": "REAL",
            "mortality_rate_max_raw": "REAL",
            "mortality_rate_unit": "TEXT",
            "mortality_normalization_note": "TEXT",
        }.items():
            added += int(add_column(conn, "virulence_profiles", column, definition))

    if table_exists(conn, "viral_isolates"):
        for column, definition in {
            "raw_completeness": "TEXT",
            "sequence_scope_status": "TEXT",
            "sequence_scope_note": "TEXT",
        }.items():
            added += int(add_column(conn, "viral_isolates", column, definition))

    return {"columns_added": added}


def classify_protein_functions(conn: sqlite3.Connection) -> dict[str, int]:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS protein_function_suggestions (
            suggestion_id INTEGER PRIMARY KEY AUTOINCREMENT,
            protein_id INTEGER NOT NULL,
            suggested_category TEXT NOT NULL,
            suggestion_source TEXT NOT NULL,
            rule_id TEXT NOT NULL,
            evidence_text TEXT,
            confidence_level TEXT NOT NULL DEFAULT 'medium',
            needs_manual_review INTEGER NOT NULL DEFAULT 1,
            curator_decision TEXT,
            curator_notes TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(protein_id, suggested_category, rule_id)
        )
        """
    )

    before = scalar(
        conn,
        """
        SELECT COUNT(*) FROM viral_proteins
        WHERE COALESCE(functional_category, 'unknown') = 'unknown'
           OR TRIM(COALESCE(functional_category, '')) = ''
        """,
    )

    conn.execute(
        """
        UPDATE viral_proteins
        SET functional_annotation_status = CASE
                WHEN functional_category IS NULL
                  OR TRIM(functional_category) = ''
                  OR functional_category = 'unknown'
                THEN 'unannotated'
                ELSE COALESCE(functional_annotation_status, 'classified')
            END,
            functional_category_source = CASE
                WHEN functional_category IS NULL
                  OR TRIM(functional_category) = ''
                  OR functional_category = 'unknown'
                THEN COALESCE(functional_category_source, 'none')
                ELSE COALESCE(functional_category_source, 'legacy_or_imported')
            END
        """
    )

    text_expr = "LOWER(COALESCE(protein_name, '') || ' ' || COALESCE(gene_symbol, '') || ' ' || COALESCE(note, ''))"
    rules = [
        (
            "structural",
            [
                "%major capsid%",
                "%minor capsid%",
                "%capsid protein%",
                "%coat protein%",
                "%nucleocapsid%",
                "%envelope protein%",
                "%virion protein%",
            ],
        ),
        (
            "replication",
            [
                "%rna-dependent rna polymerase%",
                "%rna directed rna polymerase%",
                "%rna-directed rna polymerase%",
                "%dna polymerase%",
                "%polymerase%",
                "%replicase%",
                "%helicase%",
                "%rdrp%",
            ],
        ),
        (
            "metabolism",
            [
                "%thymidine kinase%",
                "%thymidylate synthase%",
                "%ribonucleotide reductase%",
                "%methyltransferase%",
            ],
        ),
    ]
    changed_total = 0
    for category, patterns in rules:
        where = " OR ".join([f"{text_expr} LIKE ?" for _ in patterns])
        rows = conn.execute(
            f"""
            SELECT protein_id,
                   TRIM(COALESCE(protein_name, '') || ' ' ||
                        COALESCE(gene_symbol, '') || ' ' ||
                        COALESCE(note, '')) AS evidence_text
            FROM viral_proteins
            WHERE (functional_category IS NULL
                OR TRIM(functional_category) = ''
                OR functional_category = 'unknown')
              AND ({where})
            """,
            tuple(patterns),
        ).fetchall()
        for row in rows:
            cur = conn.execute(
                """
                INSERT OR IGNORE INTO protein_function_suggestions (
                    protein_id, suggested_category, suggestion_source,
                    rule_id, evidence_text, confidence_level, needs_manual_review
                )
                VALUES (?, ?, 'publication_hardening_name_rule', ?, ?, 'medium', 1)
                """,
                (row["protein_id"], category, f"name_rule:{category}", row["evidence_text"]),
            )
            changed_total += cur.rowcount if cur.rowcount is not None else 0

    conn.execute(
        """
        UPDATE viral_proteins
        SET functional_annotation_status = 'rule_suggested_unreviewed',
            functional_category_source = 'suggestion_only_not_applied'
        WHERE (functional_category IS NULL
            OR TRIM(functional_category) = ''
            OR functional_category = 'unknown')
          AND EXISTS (
              SELECT 1 FROM protein_function_suggestions pfs
              WHERE pfs.protein_id = viral_proteins.protein_id
          )
        """
    )

    after = scalar(
        conn,
        """
        SELECT COUNT(*) FROM viral_proteins
        WHERE COALESCE(functional_category, 'unknown') = 'unknown'
            OR TRIM(COALESCE(functional_category, '')) = ''
        """,
    )
    return {"unknown_before": before, "function_suggestions_inserted": changed_total, "unknown_after": after}


def flag_structure_and_domain_quality(conn: sqlite3.Connection) -> dict[str, int]:
    conn.execute(
        """
        UPDATE protein_structures
        SET plddt_raw = COALESCE(plddt_raw, plddt_score),
            plddt_scale = CASE
                WHEN plddt_score IS NULL THEN 'unknown'
                WHEN plddt_score <= 1.0 THEN '0-1'
                ELSE '0-100'
            END,
            plddt_normalized_100 = CASE
                WHEN plddt_score IS NULL THEN NULL
                WHEN plddt_score <= 1.0 THEN plddt_score * 100.0
                ELSE plddt_score
            END
        """
    )
    conn.execute(
        """
        UPDATE protein_structures
        SET confidence_tier = CASE
                WHEN plddt_normalized_100 IS NULL THEN 'unscored'
                WHEN plddt_normalized_100 >= 90 THEN 'very_high'
                WHEN plddt_normalized_100 >= 70 THEN 'high'
                WHEN plddt_normalized_100 >= 50 THEN 'medium'
                ELSE 'low'
            END,
            publication_use = CASE
                WHEN plddt_normalized_100 >= 70 THEN 'supporting_structure_annotation'
                WHEN plddt_normalized_100 >= 50 THEN 'exploratory_visualization_only'
                ELSE 'do_not_use_for_primary_claims'
            END,
            quality_notes = CASE
                WHEN plddt_normalized_100 < 50 THEN 'Low pLDDT; retain only as exploratory model, not evidence for structural claims.'
                WHEN plddt_normalized_100 < 70 THEN 'Moderate pLDDT; use cautiously.'
                ELSE COALESCE(quality_notes, 'Prediction quality acceptable for supporting annotation.')
            END
        """
    )

    interpro_flagged = 0
    if table_exists(conn, "interpro_annotations"):
        # NOTE: Most rows have NULL start_pos/end_pos because the upstream
        # InterPro API did not return domain coordinates for these entries.
        # The label 'coordinates_not_available_from_source' accurately
        # reflects that this is an upstream data limitation, not a pipeline
        # defect.  Rows with actual positions are marked 'positioned'.
        cur = conn.execute(
            """
            UPDATE interpro_annotations
            SET position_status = CASE
                    WHEN start_pos IS NOT NULL AND end_pos IS NOT NULL THEN 'positioned'
                    ELSE 'coordinates_not_available_from_source'
                END,
                publication_use = CASE
                    WHEN start_pos IS NOT NULL AND end_pos IS NOT NULL THEN 'domain_presence_and_position'
                    ELSE 'domain_presence_only_no_visualization'
                END
            """
        )
        interpro_flagged = cur.rowcount if cur.rowcount is not None else 0

    return {
        "esmfold_low_confidence": scalar(conn, "SELECT COUNT(*) FROM protein_structures WHERE plddt_normalized_100 < 50"),
        "interpro_rows_flagged": interpro_flagged,
    }


def normalize_profile_sources(conn: sqlite3.Connection) -> dict[str, int]:
    changed = 0
    for table in ("virulence_profiles", "temperature_profiles"):
        cur = conn.execute(
            f"""
            UPDATE {qident(table)}
            SET data_origin = CASE
                    WHEN UPPER(COALESCE(notes, '')) LIKE '%FAMILY_INFERRED%' THEN 'family_inferred'
                    WHEN LOWER(COALESCE(data_source, '')) LIKE '%expert curation%' THEN 'expert_literature_summary'
                    ELSE 'literature_summary_candidate'
                END,
                data_source_type = CASE
                    WHEN UPPER(COALESCE(notes, '')) LIKE '%FAMILY_INFERRED%' THEN 'family_inferred'
                    WHEN LOWER(COALESCE(data_source, '')) LIKE '%expert curation%' THEN 'expert_literature_summary'
                    ELSE 'free_text_literature_summary'
                END,
                publication_use = CASE
                    WHEN UPPER(COALESCE(notes, '')) LIKE '%FAMILY_INFERRED%' THEN 'candidate_not_for_primary_claims'
                    WHEN confidence = 'high' THEN 'curated_summary_requires_reference_check'
                    ELSE 'candidate_requires_reference_check'
                END
            """
        )
        changed += cur.rowcount if cur.rowcount is not None else 0

    return {"profile_rows_normalized": changed}


def normalize_virulence_mortality_rates(conn: sqlite3.Connection) -> dict[str, int]:
    if not table_exists(conn, "virulence_profiles"):
        return {"virulence_mortality_rows_normalized": 0, "virulence_mortality_invalid_rows": 0}

    cur = conn.execute(
        """
        UPDATE virulence_profiles
        SET mortality_rate_min_raw = COALESCE(mortality_rate_min_raw, mortality_rate_min),
            mortality_rate_max_raw = COALESCE(mortality_rate_max_raw, mortality_rate_max),
            mortality_rate_unit = COALESCE(mortality_rate_unit, 'percent'),
            mortality_rate_min = mortality_rate_min / 100.0,
            mortality_rate_max = mortality_rate_max / 100.0,
            mortality_normalization_note = 'Converted from 0-100 percent scale to 0-1 fraction by publication_hardening.',
            publication_use = CASE
                WHEN publication_use IS NULL OR publication_use = ''
                THEN 'candidate_requires_reference_check'
                ELSE publication_use
            END
        WHERE mortality_rate_min IS NOT NULL
          AND mortality_rate_max IS NOT NULL
          AND mortality_rate_min BETWEEN 0 AND 100
          AND mortality_rate_max BETWEEN 0 AND 100
          AND mortality_rate_min <= mortality_rate_max
          AND (mortality_rate_min > 1 OR mortality_rate_max > 1)
        """
    )
    invalid = scalar(
        conn,
        """
        SELECT COUNT(*)
        FROM virulence_profiles
        WHERE mortality_rate_min IS NOT NULL
          AND mortality_rate_max IS NOT NULL
          AND (
              mortality_rate_min < 0
           OR mortality_rate_max > 1
           OR mortality_rate_min > mortality_rate_max
          )
        """,
    )
    return {
        "virulence_mortality_rows_normalized": cur.rowcount if cur.rowcount is not None else 0,
        "virulence_mortality_invalid_rows": invalid,
    }


def backfill_infection_hosts_from_curated_profiles(conn: sqlite3.Connection) -> dict[str, int]:
    cur = conn.execute(
        """
        UPDATE infection_records
        SET host_id = (
            SELECT icp.host_id
            FROM isolate_curated_profiles icp
            WHERE icp.isolate_id = infection_records.isolate_id
              AND icp.host_id IS NOT NULL
        )
        WHERE host_id IS NULL
          AND EXISTS (
              SELECT 1
              FROM isolate_curated_profiles icp
              WHERE icp.isolate_id = infection_records.isolate_id
                AND icp.host_id IS NOT NULL
          )
        """
    )
    return {"infection_host_ids_backfilled_from_curated_profiles": cur.rowcount if cur.rowcount is not None else 0}


def sanitize_host_genome_artifact_names(conn: sqlite3.Connection) -> dict[str, int]:
    added = int(add_column(conn, "viral_isolates", "raw_record_name", "TEXT"))
    # First pass: sanitize records already flagged as host_genome in virus_master
    cur1 = conn.execute(
        """
        UPDATE viral_isolates
        SET raw_record_name = COALESCE(raw_record_name, virus_name),
            virus_name = 'Host genome artifact'
        WHERE isolate_id IN (
            SELECT vi.isolate_id
            FROM viral_isolates vi
            JOIN virus_master vm ON vm.master_id = vi.master_id
            WHERE vm.entry_type = 'host_genome'
              AND (
                  LOWER(COALESCE(vi.virus_name, '')) LIKE '%chromosome%'
               OR LOWER(COALESCE(vi.virus_name, '')) LIKE '%scaffold%'
               OR LOWER(COALESCE(vi.virus_name, '')) LIKE '%assembly%'
               OR LOWER(COALESCE(vi.virus_name, '')) LIKE '%shotgun%'
              )
        )
        """
    )
    # Second pass: catch any remaining host-genome artifacts regardless of entry_type
    # (safety net for records that were not previously flagged)
    cur2 = conn.execute(
        """
        UPDATE viral_isolates
        SET raw_record_name = COALESCE(raw_record_name, virus_name),
            virus_name = 'Host genome artifact',
            sequence_scope_status = COALESCE(sequence_scope_status, 'host_genome_artifact')
        WHERE (
            LOWER(COALESCE(virus_name, '')) LIKE '%chromosome%'
         OR LOWER(COALESCE(virus_name, '')) LIKE '%scaffold%'
         OR LOWER(COALESCE(virus_name, '')) LIKE '%assembly%'
         OR LOWER(COALESCE(virus_name, '')) LIKE '%shotgun%'
        )
          AND COALESCE(virus_name, '') <> 'Host genome artifact'
        """
    )
    return {
        "raw_record_name_column_added": added,
        "host_genome_artifact_names_sanitized": (cur1.rowcount if cur1.rowcount is not None else 0) + (cur2.rowcount if cur2.rowcount is not None else 0),
    }


def quarantine_sequence_scope_artifacts(conn: sqlite3.Connection) -> dict[str, int]:
    cur_short = conn.execute(
        """
        UPDATE viral_isolates
        SET raw_completeness = COALESCE(raw_completeness, completeness),
            completeness = 'gene_fragment',
            sequence_scope_status = 'short_fragment_not_complete_genome',
            sequence_scope_note = 'Record was marked complete_genome but is shorter than 1000 bp; retained as fragment pending accession-level review.'
        WHERE completeness = 'complete_genome'
          AND COALESCE(sequence_length, genome_length, 0) < 1000
        """
    )
    cur_long = conn.execute(
        """
        UPDATE viral_isolates
        SET sequence_scope_status = 'host_genome_artifact',
            sequence_scope_note = 'Genome length exceeds viral scope threshold or record is already marked as host genome artifact; excluded from target publication views.'
        WHERE COALESCE(genome_length, sequence_length, 0) > 10000000
           OR LOWER(COALESCE(virus_name, '')) = 'host genome artifact'
        """
    )
    return {
        "short_complete_records_reclassified_gene_fragment": cur_short.rowcount if cur_short.rowcount is not None else 0,
        "host_genome_artifact_records_flagged": cur_long.rowcount if cur_long.rowcount is not None else 0,
    }


def isolate_non_target_hosts(conn: sqlite3.Connection) -> dict[str, int]:
    inserted = 0
    rows = conn.execute(
        """
        SELECT host_id
        FROM crustacean_hosts
        WHERE LOWER(COALESCE(host_group, '')) = 'non-crustacean'
        """
    ).fetchall()
    for row in rows:
        cur = conn.execute(
            """
            INSERT INTO host_scope_overrides (
                host_id, scope_status, exclude_from_target_stats, reason
            )
            VALUES (?, 'non_target', 1,
                    'host_group is non-crustacean; retained as extended/ecological/lab context only until curator review.')
            ON CONFLICT(host_id) DO UPDATE SET
                scope_status = excluded.scope_status,
                exclude_from_target_stats = 1,
                reason = excluded.reason,
                updated_at = CURRENT_TIMESTAMP
            """,
            (row["host_id"],),
        )
        inserted += cur.rowcount if cur.rowcount is not None else 0
    linked_records = scalar(
        conn,
        """
        SELECT COUNT(*)
        FROM infection_records ir
        JOIN crustacean_hosts h ON h.host_id = ir.host_id
        WHERE LOWER(COALESCE(h.host_group, '')) = 'non-crustacean'
        """,
    )
    return {
        "non_crustacean_hosts_excluded_from_target_stats": len(rows),
        "non_crustacean_host_override_rows_touched": inserted,
        "infection_records_linked_to_non_crustacean_hosts": linked_records,
    }


def create_scope_quarantine_tables(conn: sqlite3.Connection) -> dict[str, int]:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS host_genome_artifacts AS
        SELECT *
        FROM viral_isolates
        WHERE 0
        """
    )
    conn.execute("DELETE FROM host_genome_artifacts")
    conn.execute(
        """
        INSERT INTO host_genome_artifacts
        SELECT *
        FROM viral_isolates
        WHERE COALESCE(genome_length, sequence_length, 0) > 10000000
           OR LOWER(COALESCE(virus_name, '')) = 'host genome artifact'
           OR sequence_scope_status = 'host_genome_artifact'
        """
    )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS virus_name_scope_review (
            review_id INTEGER PRIMARY KEY AUTOINCREMENT,
            isolate_id INTEGER NOT NULL UNIQUE,
            accession TEXT,
            reported_virus_name TEXT,
            linked_master_id INTEGER,
            linked_canonical_name TEXT,
            master_entry_type TEXT,
            master_is_crustacean_virus INTEGER,
            review_reason TEXT NOT NULL,
            suggested_action TEXT NOT NULL,
            curator_decision TEXT,
            curator_notes TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.execute("DELETE FROM virus_name_scope_review")
    conn.execute(
        """
        INSERT INTO virus_name_scope_review (
            isolate_id, accession, reported_virus_name, linked_master_id,
            linked_canonical_name, master_entry_type, master_is_crustacean_virus,
            review_reason, suggested_action
        )
        SELECT vi.isolate_id,
               vi.accession,
               vi.virus_name,
               vi.master_id,
               vm.canonical_name,
               vm.entry_type,
               vm.is_crustacean_virus,
               CASE
                   WHEN COALESCE(vm.is_crustacean_virus, 1) = 0
                     OR COALESCE(vm.entry_type, '') IN ('non_target', 'host_genome')
                   THEN 'non_target_or_artifact_master'
                   WHEN vm_by_name.master_id IS NULL
                   THEN 'reported_name_not_in_master_canonical_or_abbreviation'
                   ELSE 'reported_name_differs_from_linked_canonical'
               END,
               'manual_review_required: classify as supported alias, add alias/master mapping, non-target virus, host artifact, or experimental/environmental context'
        FROM viral_isolates vi
        JOIN virus_master vm ON vm.master_id = vi.master_id
        LEFT JOIN virus_master vm_by_name
          ON LOWER(TRIM(vm_by_name.canonical_name)) = LOWER(TRIM(vi.virus_name))
          OR LOWER(TRIM(COALESCE(vm_by_name.abbreviations, ''))) = LOWER(TRIM(vi.virus_name))
        WHERE TRIM(COALESCE(vi.virus_name, '')) <> ''
          AND (
              vm_by_name.master_id IS NULL
              OR COALESCE(vm.is_crustacean_virus, 1) = 0
              OR COALESCE(vm.entry_type, '') IN ('non_target', 'host_genome')
          )
        """
    )

    conn.executescript(
        """
        DROP VIEW IF EXISTS analysis_clean_viral_isolates;
        CREATE VIEW analysis_clean_viral_isolates AS
        SELECT *
        FROM viral_isolates
        WHERE NOT (
            COALESCE(genome_length, sequence_length, 0) > 10000000
            OR LOWER(COALESCE(virus_name, '')) = 'host genome artifact'
            OR COALESCE(sequence_scope_status, '') = 'host_genome_artifact'
        );
        """
    )
    return {
        "host_genome_artifact_quarantine_rows": scalar(conn, "SELECT COUNT(*) FROM host_genome_artifacts"),
        "virus_name_scope_review_rows": scalar(conn, "SELECT COUNT(*) FROM virus_name_scope_review"),
    }


def seed_profile_provenance(conn: sqlite3.Connection) -> dict[str, int]:
    inserted = 0
    specs = [
        ("virulence_profiles", "profile_id"),
        ("temperature_profiles", "profile_id"),
    ]
    for table, pk in specs:
        rows = conn.execute(
            f"""
            SELECT p.{qident(pk)} AS record_id,
                   p.virus_name,
                   p.data_origin,
                   p.data_source_type,
                   p.confidence,
                   p.data_source,
                   vm.master_id
            FROM {qident(table)} p
            LEFT JOIN virus_master vm
              ON LOWER(TRIM(vm.canonical_name)) = LOWER(TRIM(p.virus_name))
            WHERE NOT EXISTS (
                SELECT 1 FROM data_provenance dp
                WHERE dp.table_name = ?
                  AND dp.record_id = p.{qident(pk)}
            )
            """,
            (table,),
        ).fetchall()
        for row in rows:
            conn.execute(
                """
                INSERT INTO data_provenance (
                    table_name, record_id, virus_master_id, virus_name,
                    data_source, confidence_level, verification_method, curator_notes
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    table,
                    row["record_id"],
                    row["master_id"],
                    row["virus_name"],
                    row["data_source_type"] or "unclassified_source",
                    "inferred" if row["data_origin"] == "family_inferred"
                    else "unverified",
                    "publication_hardening_controlled_source",
                    f"Original data_source: {row['data_source'] or ''}".strip(),
                ),
            )
            inserted += 1
    return {"provenance_rows_inserted": inserted}


def create_views(conn: sqlite3.Connection) -> None:
    view_sql = {
        "v_viral_isolate_name_reconciled": """
            CREATE VIEW v_viral_isolate_name_reconciled AS
            SELECT vi.isolate_id,
                   vi.accession,
                   vi.virus_name AS isolate_reported_virus_name,
                   vm.canonical_name AS canonical_virus_name,
                   CASE
                       WHEN TRIM(COALESCE(vi.virus_name, '')) = ''
                            OR TRIM(COALESCE(vm.canonical_name, '')) = ''
                       THEN 'missing_name'
                       WHEN LOWER(TRIM(vi.virus_name)) = LOWER(TRIM(vm.canonical_name))
                       THEN 'match'
                       ELSE 'alias_or_conflict_requires_review'
                   END AS name_reconciliation_status,
                   vm.master_id
            FROM viral_isolates vi
            LEFT JOIN virus_master vm ON vm.master_id = vi.master_id
        """,
        "v_viral_isolate_taxonomy_reconciled": """
            CREATE VIEW v_viral_isolate_taxonomy_reconciled AS
            SELECT vi.isolate_id,
                   vi.accession,
                   vi.taxon_family AS isolate_raw_family,
                   vm.virus_family AS canonical_family,
                   vi.taxon_genus AS isolate_raw_genus,
                   vm.virus_genus AS canonical_genus,
                   CASE
                       WHEN TRIM(COALESCE(vi.taxon_family, '')) = ''
                            OR TRIM(COALESCE(vm.virus_family, '')) = ''
                       THEN 'missing_family'
                       WHEN LOWER(TRIM(vi.taxon_family)) = LOWER(TRIM(vm.virus_family))
                       THEN 'match'
                       ELSE 'conflict_requires_taxonomy_review'
                   END AS family_reconciliation_status,
                   vm.master_id
            FROM viral_isolates vi
            LEFT JOIN virus_master vm ON vm.master_id = vi.master_id
        """,
        "v_isolate_reference_unique": """
            CREATE VIEW v_isolate_reference_unique AS
            SELECT l.isolate_id,
                   l.reference_id,
                   MIN(l.link_id) AS representative_link_id,
                   GROUP_CONCAT(DISTINCT l.link_type) AS link_types,
                   CASE
                       WHEN EXISTS (
                           SELECT 1 FROM infection_records ir
                           WHERE ir.isolate_id = l.isolate_id
                             AND ir.reference_id = l.reference_id
                       )
                       THEN 1 ELSE 0
                   END AS also_in_infection_records,
                   MIN(l.priority) AS best_priority
            FROM isolate_reference_links l
            GROUP BY l.isolate_id, l.reference_id
        """,
        "v_references_missing_identifiers": """
            CREATE VIEW v_references_missing_identifiers AS
            SELECT reference_id, title, authors, journal, year, pmid, doi
            FROM ref_literatures
            WHERE TRIM(COALESCE(pmid, '')) = ''
              AND TRIM(COALESCE(doi, '')) = ''
        """,
        "v_isolates_without_proteins": """
            CREATE VIEW v_isolates_without_proteins AS
            SELECT vi.isolate_id, vi.accession, vm.canonical_name, vi.virus_name,
                   vi.completeness, vi.sequence_length, vi.genome_length
            FROM viral_isolates vi
            LEFT JOIN virus_master vm ON vm.master_id = vi.master_id
            WHERE NOT EXISTS (
                SELECT 1 FROM viral_proteins vp WHERE vp.isolate_id = vi.isolate_id
            )
        """,
        "v_isolates_without_infection_records": """
            CREATE VIEW v_isolates_without_infection_records AS
            SELECT vi.isolate_id, vi.accession, vm.canonical_name, vi.virus_name,
                   vi.reference_id, vi.completeness
            FROM viral_isolates vi
            LEFT JOIN virus_master vm ON vm.master_id = vi.master_id
            WHERE NOT EXISTS (
                SELECT 1 FROM infection_records ir WHERE ir.isolate_id = vi.isolate_id
            )
        """,
        "v_infection_records_missing_host": """
            CREATE VIEW v_infection_records_missing_host AS
            SELECT ir.*, vi.accession, vm.canonical_name
            FROM infection_records ir
            LEFT JOIN viral_isolates vi ON vi.isolate_id = ir.isolate_id
            LEFT JOIN virus_master vm ON vm.master_id = vi.master_id
            WHERE ir.host_id IS NULL
        """,
        "v_low_confidence_structures": """
            CREATE VIEW v_low_confidence_structures AS
            SELECT ps.*, vp.protein_accession, vp.protein_name, vi.accession AS isolate_accession,
                   vm.canonical_name
            FROM protein_structures ps
            LEFT JOIN viral_proteins vp ON vp.protein_id = ps.protein_id
            LEFT JOIN viral_isolates vi ON vi.isolate_id = vp.isolate_id
            LEFT JOIN virus_master vm ON vm.master_id = vi.master_id
            WHERE COALESCE(ps.plddt_normalized_100,
                           CASE WHEN ps.plddt_score <= 1.0 THEN ps.plddt_score * 100.0 ELSE ps.plddt_score END) < 50
               OR ps.publication_use = 'do_not_use_for_primary_claims'
        """,
        "v_interpro_missing_positions": """
            CREATE VIEW v_interpro_missing_positions AS
            SELECT *
            FROM interpro_annotations
            WHERE start_pos IS NULL OR end_pos IS NULL
        """,
        "v_interpro_annotations_positioned": """
            CREATE VIEW v_interpro_annotations_positioned AS
            SELECT *
            FROM interpro_annotations
            WHERE start_pos IS NOT NULL AND end_pos IS NOT NULL
        """,
        "predicted_virulence_profiles": """
            CREATE VIEW predicted_virulence_profiles AS
            SELECT profile_id,
                   virus_name,
                   virulence_level,
                   virulence_label,
                   mortality_rate_min,
                   mortality_rate_max,
                   ld50_value,
                   pathogenic_mechanism,
                   outbreak_record,
                   host_age_susceptibility,
                   data_source,
                   data_origin,
                   data_source_type,
                   confidence,
                   publication_use,
                   curation_date,
                   notes
            FROM virulence_profiles
        """,
        "predicted_temperature_profiles": """
            CREATE VIEW predicted_temperature_profiles AS
            SELECT profile_id,
                   virus_name,
                   optimal_temp_min,
                   optimal_temp_max,
                   temp_range_min,
                   temp_range_max,
                   thermal_inactivation_temp,
                   thermal_inactivation_time,
                   cold_storage_temp,
                   cold_storage_viability,
                   temp_sensitivity_notes,
                   climate_change_impact,
                   data_source,
                   data_origin,
                   data_source_type,
                   confidence,
                   publication_use,
                   curation_date,
                   notes
            FROM temperature_profiles
        """,
        "v_publication_profile_status": """
            CREATE VIEW v_publication_profile_status AS
            SELECT 'virulence_profiles' AS table_name,
                   profile_id AS record_id,
                   virus_name,
                   data_origin,
                   data_source_type,
                   confidence,
                   publication_use
            FROM virulence_profiles
            UNION ALL
            SELECT 'temperature_profiles' AS table_name,
                   profile_id AS record_id,
                   virus_name,
                   data_origin,
                   data_source_type,
                   confidence,
                   publication_use
            FROM temperature_profiles
        """,
    }

    for view, sql in view_sql.items():
        conn.execute(f"DROP VIEW IF EXISTS {qident(view)}")
        conn.execute(sql)


def find_missing_fk_indexes(conn: sqlite3.Connection) -> list[dict[str, str]]:
    missing: list[dict[str, str]] = []
    tables = [row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
    for table in tables:
        fks = conn.execute(f"PRAGMA foreign_key_list({qident(table)})").fetchall()
        if not fks:
            continue
        indexed_first_cols: set[str] = set()
        for idx in conn.execute(f"PRAGMA index_list({qident(table)})").fetchall():
            for info in conn.execute(f"PRAGMA index_info({qident(idx['name'])})").fetchall():
                if info["seqno"] == 0:
                    indexed_first_cols.add(info["name"])
        for fk in fks:
            if fk["from"] not in indexed_first_cols:
                missing.append(
                    {
                        "table": table,
                        "column": fk["from"],
                        "ref_table": fk["table"],
                        "ref_column": fk["to"],
                    }
                )
    return missing


def create_missing_fk_indexes(conn: sqlite3.Connection) -> dict[str, int]:
    missing = find_missing_fk_indexes(conn)
    for item in missing:
        index_name = f"idx_pub_fk_{item['table']}_{item['column']}"
        conn.execute(
            f"""
            CREATE INDEX IF NOT EXISTS {qident(index_name)}
            ON {qident(item['table'])}({qident(item['column'])})
            """
        )
    return {"fk_indexes_created": len(missing)}


def harden_reference_links(conn: sqlite3.Connection) -> dict[str, Any]:
    conn.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_irl_unique_isolate_reference_type
        ON isolate_reference_links(isolate_id, reference_id, link_type)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_irl_isolate_reference
        ON isolate_reference_links(isolate_id, reference_id)
        """
    )
    overlaps = scalar(
        conn,
        """
        SELECT COUNT(*)
        FROM isolate_reference_links l
        WHERE EXISTS (
            SELECT 1 FROM infection_records ir
            WHERE ir.isolate_id = l.isolate_id
              AND ir.reference_id = l.reference_id
        )
        """,
    )
    return {"reference_link_overlap_rows_documented_by_view": overlaps}


def refresh_analysis_target_views(conn: sqlite3.Connection) -> dict[str, int]:
    artifact_text = """
    LOWER(
        COALESCE(v.virus_name, '') || ' ' ||
        COALESCE(v.molecule_type, '') || ' ' ||
        COALESCE(v.completeness, '') || ' ' ||
        COALESCE(nr.definition, '') || ' ' ||
        COALESCE(nr.organism, '') || ' ' ||
        COALESCE(nr.molecule_type, '') || ' ' ||
        COALESCE(nr.taxonomy_lineage, '') || ' ' ||
        COALESCE(sm.mol_type, '') || ' ' ||
        COALESCE(sm.raw_notes, '') || ' ' ||
        COALESCE(sm.organism, '')
    )
    """
    conn.executescript(
        f"""
        DROP VIEW IF EXISTS analysis_target_isolates;
        DROP VIEW IF EXISTS analysis_strict_target_isolates;

        CREATE VIEW analysis_target_isolates AS
        SELECT v.*
        FROM viral_isolates v
        JOIN virus_master vm ON vm.master_id = v.master_id
        LEFT JOIN isolate_curated_profiles icp ON icp.isolate_id = v.isolate_id
        LEFT JOIN host_scope_overrides hso ON hso.host_id = icp.host_id
        LEFT JOIN nucleotide_records nr ON nr.isolate_id = v.isolate_id
        LEFT JOIN sample_metadata sm ON sm.isolate_id = v.isolate_id
        WHERE vm.is_crustacean_virus = 1
          AND vm.entry_type NOT IN ('non_target', 'host_genome', 'catalog_only', 'reference_only')
          AND COALESCE(icp.host_is_target, 1) = 1
          AND COALESCE(hso.exclude_from_target_stats, 0) = 0
        AND COALESCE(icp.dataset_tier, '') NOT IN (
              'sequence_scope_artifact', 'host_genome_artifact'
          )
          AND COALESCE(v.sequence_scope_status, '') NOT IN (
              'short_fragment_not_complete_genome', 'host_genome_artifact'
          )
          AND v.accession NOT LIKE 'RDRP\\_%' ESCAPE '\\'
          AND NOT (
              COALESCE(v.genome_length, v.sequence_length, 0) > 10000000
              OR LOWER(COALESCE(v.virus_name, '')) = 'host genome artifact'
          )
          AND {artifact_text} NOT LIKE '% mrna%'
          AND {artifact_text} NOT LIKE '% cdna%'
          AND {artifact_text} NOT LIKE '% est%'
          AND NOT (
              v.completeness = 'complete_genome'
              AND COALESCE(v.sequence_length, v.genome_length, 0) < 1000
          );

        CREATE VIEW analysis_strict_target_isolates AS
        SELECT v.*
        FROM analysis_target_isolates v
        LEFT JOIN isolate_curated_profiles icp ON icp.isolate_id = v.isolate_id
        WHERE COALESCE(icp.curation_status, 'auto_seeded') <> 'conflict_open'
          AND COALESCE(icp.dataset_tier, '') <> 'unverified';
        """
    )
    return {
        "analysis_target_isolates_rows": scalar(conn, "SELECT COUNT(*) FROM analysis_target_isolates"),
        "analysis_strict_target_isolates_rows": scalar(conn, "SELECT COUNT(*) FROM analysis_strict_target_isolates"),
    }


def mark_orphan_master_entries(conn: sqlite3.Connection) -> dict[str, int]:
    ensure_vocab(
        conn,
        "virus_entry_type",
        "catalog_only",
        "Virus catalog entry retained for nomenclature/context but not backed by a local isolate record.",
    )
    cur = conn.execute(
        """
        UPDATE virus_master
        SET entry_type = 'catalog_only',
            notes = TRIM(COALESCE(notes || ' ', '') ||
                '[publication_hardening] No linked isolate in this database; retained as catalog-only context.')
        WHERE master_id IN (
            SELECT vm.master_id
            FROM virus_master vm
            LEFT JOIN viral_isolates vi ON vi.master_id = vm.master_id
            WHERE vi.isolate_id IS NULL
              AND COALESCE(vm.is_crustacean_virus, 1) = 1
              AND COALESCE(vm.entry_type, '') NOT IN (
                  'non_target', 'host_genome', 'catalog_only', 'reference_only'
              )
        )
        """
    )
    return {"orphan_master_entries_marked_catalog_only": cur.rowcount if cur.rowcount is not None else 0}


def record_deprecated_columns(conn: sqlite3.Connection) -> dict[str, int]:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_deprecated_columns (
            deprecated_id INTEGER PRIMARY KEY AUTOINCREMENT,
            table_name TEXT NOT NULL,
            column_name TEXT NOT NULL,
            reason TEXT NOT NULL,
            recommended_action TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(table_name, column_name)
        )
        """
    )
    rows = [
        (
            "sample_collections",
            "site_name",
            "Column is 100% NULL in the current release database.",
            "Do not expose in public downloads; retain only for backward-compatible imports until a major schema rebuild.",
        ),
        (
            "crustacean_hosts",
            "iucn_assessment_year",
            "Column is 100% NULL in the current release database.",
            "Do not expose in public downloads; populate from IUCN source before using or remove during a major schema rebuild.",
        ),
        (
            "virus_master",
            "abbreviations",
            "Optional synonym field is sparse; NULL is not a data-quality failure by itself.",
            "Use virus_aliases for searchable synonyms; curate abbreviations only where literature-supported.",
        ),
    ]
    inserted = 0
    for row in rows:
        cur = conn.execute(
            """
            INSERT OR IGNORE INTO schema_deprecated_columns (
                table_name, column_name, reason, recommended_action
            )
            VALUES (?, ?, ?, ?)
            """,
            row,
        )
        inserted += cur.rowcount if cur.rowcount is not None else 0
    return {"deprecated_column_records_inserted": inserted}


def ensure_controlled_vocab(conn: sqlite3.Connection) -> None:
    terms = [
        ("profile_data_origin", "expert_literature_summary", "Curator-authored summary from literature; verify underlying references before primary claims."),
        ("profile_data_origin", "literature_summary_candidate", "Candidate literature summary that requires reference verification."),
        ("profile_data_origin", "family_inferred", "Family-level inference; not isolate-specific evidence."),
        ("publication_use", "do_not_use_for_primary_claims", "Retain for transparency only; exclude from primary scientific claims."),
        ("publication_use", "candidate_requires_reference_check", "Candidate data requiring curator verification."),
        ("publication_use", "curated_summary_requires_reference_check", "Curated summary, but reference chain must be checked before submission claims."),
        ("publication_use", "domain_presence_only_no_visualization", "Domain presence without coordinates; unsuitable for positional visualizations."),
        ("host_scope_status", "non_target", "Non-crustacean host/sample retained outside target publication statistics until curator review."),
        ("sequence_scope_status", "short_fragment_not_complete_genome", "Short sequence previously marked complete genome; retained as fragment pending curator review."),
        ("sequence_scope_status", "host_genome_artifact", "Host genome-scale record excluded from viral target views."),
    ]
    for category, term, desc in terms:
        ensure_vocab(conn, category, term, desc)


def fetch_rows(conn: sqlite3.Connection, sql: str) -> list[dict[str, Any]]:
    return [dict(row) for row in conn.execute(sql).fetchall()]


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8-sig", newline="") as fout:
        writer = csv.DictWriter(fout, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def export_manual_worklists(conn: sqlite3.Connection, out_dir: Path) -> dict[str, int]:
    exports: dict[str, tuple[str, str]] = {
        "01_protein_function_unknown_review.csv": """
            SELECT vp.protein_id, vi.accession, vm.canonical_name,
                   vp.protein_accession, vp.protein_name, vp.gene_symbol,
                   vp.aa_length, vp.functional_category,
                   vp.functional_annotation_status, vp.functional_category_source,
                   pfs.suggested_category, pfs.suggestion_source, pfs.rule_id,
                   pfs.evidence_text, pfs.confidence_level,
                   COALESCE(pfs.needs_manual_review, 1) AS needs_manual_review,
                   pfs.curator_decision, pfs.curator_notes
            FROM viral_proteins vp
            LEFT JOIN viral_isolates vi ON vi.isolate_id = vp.isolate_id
            LEFT JOIN virus_master vm ON vm.master_id = vi.master_id
            LEFT JOIN protein_function_suggestions pfs ON pfs.protein_id = vp.protein_id
            WHERE COALESCE(vp.functional_category, 'unknown') = 'unknown'
               OR TRIM(COALESCE(vp.functional_category, '')) = ''
               OR pfs.suggestion_id IS NOT NULL
            ORDER BY
                CASE WHEN pfs.suggestion_id IS NOT NULL THEN 0 ELSE 1 END,
                vm.canonical_name, vi.accession, vp.protein_id
        """,
        "02_low_confidence_structures_do_not_claim.csv": """
            SELECT structure_id, cluster_id, protein_id, reanno_id, prediction_method,
                   model_version, plddt_raw, plddt_scale, plddt_normalized_100,
                   confidence_tier, publication_use, quality_notes,
                   sequence_length, prediction_date, api_source,
                   protein_accession, protein_name, isolate_accession, canonical_name
            FROM v_low_confidence_structures
            ORDER BY plddt_normalized_100 ASC, structure_id
        """,
        "03_interpro_missing_domain_positions.csv": """
            SELECT interpro_anno_id, protein_id, uniprot_id, interpro_id,
                   interpro_name, interpro_type, source_database,
                   start_pos, end_pos, position_status, publication_use
            FROM interpro_annotations
            WHERE start_pos IS NULL OR end_pos IS NULL
            ORDER BY protein_id, interpro_id
        """,
        "04_virus_name_alias_or_conflict_review.csv": """
            SELECT * FROM v_viral_isolate_name_reconciled
            WHERE name_reconciliation_status = 'alias_or_conflict_requires_review'
            ORDER BY canonical_virus_name, accession
        """,
        "05_taxonomy_family_conflict_review.csv": """
            SELECT * FROM v_viral_isolate_taxonomy_reconciled
            WHERE family_reconciliation_status = 'conflict_requires_taxonomy_review'
            ORDER BY canonical_family, isolate_raw_family, accession
        """,
        "06_references_missing_pmid_doi.csv": """
            SELECT * FROM v_references_missing_identifiers
            ORDER BY year DESC, reference_id
        """,
        "07_isolates_without_proteins.csv": """
            SELECT * FROM v_isolates_without_proteins
            ORDER BY canonical_name, accession
        """,
        "08_isolates_without_infection_records.csv": """
            SELECT * FROM v_isolates_without_infection_records
            ORDER BY canonical_name, accession
        """,
        "09_infection_records_missing_host.csv": """
            SELECT * FROM v_infection_records_missing_host
            ORDER BY canonical_name, accession, record_id
        """,
        "10_profile_source_review.csv": """
            SELECT * FROM v_publication_profile_status
            WHERE publication_use <> 'curated_summary_requires_reference_check'
               OR confidence <> 'high'
            ORDER BY data_origin, confidence, virus_name
        """,
        "11_schema_deprecated_or_sparse_columns.csv": """
            SELECT * FROM schema_deprecated_columns
            ORDER BY table_name, column_name
        """,
        "12_short_complete_genome_fragments_reclassified.csv": """
            SELECT isolate_id, accession, virus_name, raw_completeness,
                   completeness, sequence_length, genome_length,
                   sequence_scope_status, sequence_scope_note
            FROM viral_isolates
            WHERE sequence_scope_status = 'short_fragment_not_complete_genome'
               OR (
                   raw_completeness = 'complete_genome'
                   AND COALESCE(sequence_length, genome_length, 0) < 1000
               )
            ORDER BY accession
        """,
        "13_host_genome_artifacts_quarantine.csv": """
            SELECT isolate_id, accession, virus_name, raw_record_name,
                   completeness, sequence_length, genome_length,
                   sequence_scope_status, sequence_scope_note
            FROM host_genome_artifacts
            ORDER BY genome_length DESC, accession
        """,
        "14_non_crustacean_hosts_review.csv": """
            SELECT h.host_id, h.scientific_name, h.common_name_cn,
                   h.taxon_order, h.taxon_family, h.host_group,
                   hso.scope_status, hso.exclude_from_target_stats, hso.reason,
                   COUNT(ir.record_id) AS linked_infection_records
            FROM crustacean_hosts h
            LEFT JOIN host_scope_overrides hso ON hso.host_id = h.host_id
            LEFT JOIN infection_records ir ON ir.host_id = h.host_id
            WHERE LOWER(COALESCE(h.host_group, '')) = 'non-crustacean'
            GROUP BY h.host_id
            ORDER BY linked_infection_records DESC, h.scientific_name
        """,
        "15_virus_name_scope_pollution_review.csv": """
            SELECT *
            FROM virus_name_scope_review
            ORDER BY review_reason, linked_canonical_name, accession
        """,
        "16_virulence_mortality_normalization_review.csv": """
            SELECT profile_id, virus_name, virulence_level, virulence_label,
                   mortality_rate_min_raw, mortality_rate_max_raw,
                   mortality_rate_unit, mortality_rate_min, mortality_rate_max,
                   mortality_normalization_note, data_source, confidence,
                   data_origin, data_source_type, publication_use
            FROM virulence_profiles
            WHERE mortality_rate_min_raw IS NOT NULL
               OR mortality_rate_max_raw IS NOT NULL
               OR mortality_rate_min < 0
               OR mortality_rate_max > 1
               OR mortality_rate_min > mortality_rate_max
            ORDER BY virus_name, profile_id
        """,
    }

    counts: dict[str, int] = {}
    for filename, sql in exports.items():
        rows = fetch_rows(conn, sql)
        write_csv(out_dir / filename, rows)
        counts[filename] = len(rows)
    return counts


def record_maintenance_log(conn: sqlite3.Connection, details: dict[str, Any]) -> None:
    if not table_exists(conn, "database_maintenance_log"):
        return
    conn.execute(
        """
        INSERT INTO database_maintenance_log (action, details_json)
        VALUES (?, ?)
        """,
        ("publication_hardening", json.dumps(details, ensure_ascii=False, sort_keys=True)),
    )


def main() -> int:
    if not DB_PATH.exists():
        raise SystemExit(f"Database not found: {DB_PATH}")

    REPORTS_DIR.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = REPORTS_DIR / f"publication_hardening_{stamp}"

    backup = backup_database()
    actions: dict[str, Any] = {"backup": str(backup)}

    with connect() as conn:
        before = snapshot_metrics(conn)
        ensure_controlled_vocab(conn)
        actions.update(ensure_publication_columns(conn))
        actions.update(classify_protein_functions(conn))
        actions.update(flag_structure_and_domain_quality(conn))
        actions.update(normalize_profile_sources(conn))
        actions.update(normalize_virulence_mortality_rates(conn))
        actions.update(backfill_infection_hosts_from_curated_profiles(conn))
        actions.update(sanitize_host_genome_artifact_names(conn))
        actions.update(quarantine_sequence_scope_artifacts(conn))
        actions.update(isolate_non_target_hosts(conn))
        actions.update(create_scope_quarantine_tables(conn))
        actions.update(seed_profile_provenance(conn))
        actions.update(create_missing_fk_indexes(conn))
        actions.update(harden_reference_links(conn))
        actions.update(mark_orphan_master_entries(conn))
        actions.update(refresh_analysis_target_views(conn))
        actions.update(record_deprecated_columns(conn))
        create_views(conn)
        after = snapshot_metrics(conn)
        worklist_counts = export_manual_worklists(conn, out_dir)
        actions["manual_worklist_dir"] = str(out_dir)
        actions["manual_worklist_counts"] = worklist_counts
        actions["metrics_before"] = before
        actions["metrics_after"] = after
        record_maintenance_log(conn, actions)
        conn.commit()

    (out_dir / "publication_hardening_summary.json").write_text(
        json.dumps(actions, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print(json.dumps(actions, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
