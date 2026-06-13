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
QUARANTINE_DIR = BASE_DIR / "maintenance_archive" / "compliance_quarantine"


ARTIFACT_TEXT_SQL = """
LOWER(
    COALESCE(vi.virus_name, '') || ' ' ||
    COALESCE(vi.molecule_type, '') || ' ' ||
    COALESCE(vi.completeness, '') || ' ' ||
    COALESCE(nr.definition, '') || ' ' ||
    COALESCE(nr.organism, '') || ' ' ||
    COALESCE(nr.molecule_type, '') || ' ' ||
    COALESCE(nr.taxonomy_lineage, '') || ' ' ||
    COALESCE(sm.mol_type, '') || ' ' ||
    COALESCE(sm.raw_notes, '') || ' ' ||
    COALESCE(sm.organism, '')
)
"""


def stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=60)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def scalar(conn: sqlite3.Connection, sql: str, params: tuple[Any, ...] = ()) -> Any:
    row = conn.execute(sql, params).fetchone()
    return None if row is None else row[0]


def dict_rows(conn: sqlite3.Connection, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def backup_database(ts: str) -> Path:
    return wal_safe_backup(DB_PATH, BACKUP_DIR, f"before_submission_blocker_fixes_{ts}", quiet=True)


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def ensure_tables(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS sequence_curation_flags (
            flag_id INTEGER PRIMARY KEY AUTOINCREMENT,
            isolate_id INTEGER NOT NULL,
            accession TEXT,
            flag_type TEXT NOT NULL,
            severity TEXT NOT NULL,
            reason TEXT NOT NULL,
            previous_completeness TEXT,
            new_completeness TEXT,
            action_taken TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(isolate_id, flag_type, reason),
            FOREIGN KEY(isolate_id) REFERENCES viral_isolates(isolate_id)
        );

        CREATE TABLE IF NOT EXISTS compliance_quarantine_log (
            log_id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_path TEXT NOT NULL,
            quarantined_path TEXT,
            reason TEXT NOT NULL,
            action_taken TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(file_path, reason)
        );
        """
    )


def ensure_profile(conn: sqlite3.Connection, isolate_id: int, accession: str | None, master_id: int | None, virus_name: str | None) -> int:
    row = conn.execute(
        "SELECT profile_id FROM isolate_curated_profiles WHERE isolate_id = ?",
        (isolate_id,),
    ).fetchone()
    if row:
        return int(row["profile_id"])
    conn.execute(
        """
        INSERT INTO isolate_curated_profiles (
            isolate_id, accession, master_id, canonical_virus_name, raw_virus_name,
            host_is_target, metadata_source_priority, curation_status, confidence,
            dataset_tier, notes, updated_at
        ) VALUES (?, ?, ?, ?, ?, 0, 'manual_curated', 'manual_checked', 'high',
                  'sequence_scope_artifact', 'Created to quarantine a sequence-scope artifact.', CURRENT_TIMESTAMP)
        """,
        (isolate_id, accession, master_id, virus_name, virus_name),
    )
    return int(scalar(conn, "SELECT last_insert_rowid()"))


def flag_isolate(
    conn: sqlite3.Connection,
    row: dict[str, Any],
    flag_type: str,
    reason: str,
    action_taken: str,
    new_completeness: str | None = None,
) -> None:
    isolate_id = int(row["isolate_id"])
    profile_id = ensure_profile(conn, isolate_id, row.get("accession"), row.get("master_id"), row.get("virus_name") or row.get("canonical_name"))
    note = f"submission_blocker_fix:{flag_type}: {reason}"
    existing_note = scalar(conn, "SELECT notes FROM isolate_curated_profiles WHERE profile_id = ?", (profile_id,)) or ""
    next_note = existing_note if note in existing_note else f"{existing_note}; {note}".strip("; ")
    conn.execute(
        """
        UPDATE isolate_curated_profiles
        SET host_is_target = 0,
            metadata_source_priority = 'manual_curated',
            curation_status = 'manual_checked',
            confidence = 'high',
            dataset_tier = CASE
                WHEN ? = 'host_genome_artifact' THEN 'host_genome_artifact'
                ELSE 'sequence_scope_artifact'
            END,
            notes = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE profile_id = ?
        """,
        (flag_type, next_note, profile_id),
    )
    if new_completeness:
        conn.execute(
            """
            UPDATE viral_isolates
            SET completeness = ?,
                raw_completeness = COALESCE(raw_completeness, completeness),
                sequence_scope_status = CASE
                    WHEN ? = 'short_complete_genome' THEN 'short_fragment_not_complete_genome'
                    ELSE COALESCE(sequence_scope_status, ?)
                END,
                sequence_scope_note = CASE
                    WHEN ? = 'short_complete_genome'
                    THEN 'Record was labelled complete_genome but is shorter than 1000 bp; retained as fragment and excluded from target publication views.'
                    ELSE sequence_scope_note
                END
            WHERE isolate_id = ?
            """,
            (new_completeness, flag_type, flag_type, flag_type, isolate_id),
        )
    elif flag_type == "host_genome_artifact":
        conn.execute(
            """
            UPDATE viral_isolates
            SET raw_record_name = COALESCE(raw_record_name, virus_name),
                virus_name = CASE
                    WHEN LOWER(COALESCE(virus_name, '')) LIKE '%chromosome%'
                      OR LOWER(COALESCE(virus_name, '')) LIKE '%scaffold%'
                      OR LOWER(COALESCE(virus_name, '')) LIKE '%assembly%'
                      OR LOWER(COALESCE(virus_name, '')) LIKE '%shotgun%'
                    THEN 'Host genome artifact'
                    ELSE virus_name
                END,
                sequence_scope_status = 'host_genome_artifact',
                sequence_scope_note = 'Host chromosome/scaffold-scale record; retained for audit trail and excluded from target publication views.'
            WHERE isolate_id = ?
            """,
            (isolate_id,),
        )
    elif flag_type == "transcript_or_est_artifact":
        conn.execute(
            """
            UPDATE viral_isolates
            SET raw_record_name = COALESCE(raw_record_name, virus_name),
                sequence_scope_status = 'transcript_or_est_artifact',
                sequence_scope_note = 'Host transcript/cDNA/EST/diagnostic or patent fragment; retained for audit trail and excluded from target publication views.'
            WHERE isolate_id = ?
            """,
            (isolate_id,),
        )
    conn.execute(
        """
        INSERT INTO sequence_curation_flags (
            isolate_id, accession, flag_type, severity, reason,
            previous_completeness, new_completeness, action_taken
        ) VALUES (?, ?, ?, 'P0', ?, ?, ?, ?)
        ON CONFLICT(isolate_id, flag_type, reason) DO UPDATE SET
            previous_completeness = excluded.previous_completeness,
            new_completeness = excluded.new_completeness,
            action_taken = excluded.action_taken
        """,
        (
            isolate_id,
            row.get("accession"),
            flag_type,
            reason,
            row.get("completeness"),
            new_completeness,
            action_taken,
        ),
    )


def quarantine_sequence_artifacts(conn: sqlite3.Connection) -> dict[str, int]:
    host_genome_rows = dict_rows(
        conn,
        f"""
        SELECT vi.isolate_id, vi.accession, vi.master_id, vi.virus_name, vi.completeness,
               vi.genome_length, vi.sequence_length, nr.definition, nr.organism
        FROM viral_isolates vi
        LEFT JOIN nucleotide_records nr ON nr.isolate_id = vi.isolate_id
        LEFT JOIN sample_metadata sm ON sm.isolate_id = vi.isolate_id
        WHERE COALESCE(vi.sequence_length, vi.genome_length, 0) > 10000000
           OR {ARTIFACT_TEXT_SQL} LIKE '% chromosome %'
           OR {ARTIFACT_TEXT_SQL} LIKE '%unplaced genomic scaffold%'
           OR {ARTIFACT_TEXT_SQL} LIKE '%genomic scaffold%'
        """,
    )
    for row in host_genome_rows:
        flag_isolate(
            conn,
            row,
            "host_genome_artifact",
            "Host chromosome/scaffold-scale sequence, not a viral isolate genome.",
            "excluded_from_target_views",
            None,
        )

    transcript_rows = dict_rows(
        conn,
        f"""
        SELECT vi.isolate_id, vi.accession, vi.master_id, vi.virus_name, vi.completeness,
               vi.genome_length, vi.sequence_length, nr.definition, nr.organism
        FROM viral_isolates vi
        LEFT JOIN nucleotide_records nr ON nr.isolate_id = vi.isolate_id
        LEFT JOIN sample_metadata sm ON sm.isolate_id = vi.isolate_id
        WHERE {ARTIFACT_TEXT_SQL} LIKE '% mrna%'
           OR {ARTIFACT_TEXT_SQL} LIKE '% cdna%'
           OR {ARTIFACT_TEXT_SQL} LIKE '% est%'
           OR {ARTIFACT_TEXT_SQL} LIKE '%ribosomal%'
           OR {ARTIFACT_TEXT_SQL} LIKE '%clone %'
        """,
    )
    tiny_rows = dict_rows(
        conn,
        """
        SELECT vi.isolate_id, vi.accession, vi.master_id, vi.virus_name, vi.completeness,
               vi.genome_length, vi.sequence_length, NULL AS definition, NULL AS organism
        FROM viral_isolates vi
        LEFT JOIN isolate_curated_profiles icp ON icp.isolate_id = vi.isolate_id
        WHERE COALESCE(vi.sequence_length, vi.genome_length, 0) > 0
          AND COALESCE(vi.sequence_length, vi.genome_length, 0) < 100
          AND COALESCE(vi.sequence_scope_status, '') NOT IN (
              'short_fragment_not_complete_genome',
              'host_genome_artifact',
              'transcript_or_est_artifact'
          )
          AND COALESCE(icp.dataset_tier, '') NOT IN (
              'sequence_scope_artifact',
              'host_genome_artifact'
          )
        """,
    )
    transcript_seen = {row["isolate_id"] for row in transcript_rows}
    for row in tiny_rows:
        if row["isolate_id"] not in transcript_seen:
            transcript_rows.append(row)
    for row in transcript_rows:
        flag_isolate(
            conn,
            row,
            "transcript_or_est_artifact",
            "Host transcript/cDNA/EST/ribosomal/clone record or sub-100-nt diagnostic/patent fragment; not a viral isolate genome.",
            "excluded_from_target_views",
            None,
        )

    short_complete_rows = dict_rows(
        conn,
        """
        SELECT isolate_id, accession, master_id, virus_name, completeness,
               genome_length, sequence_length
        FROM viral_isolates
        WHERE completeness = 'complete_genome'
          AND COALESCE(sequence_length, genome_length, 0) > 0
          AND COALESCE(sequence_length, genome_length, 0) < 1000
        """,
    )
    for row in short_complete_rows:
        flag_isolate(
            conn,
            row,
            "short_complete_genome",
            "Record is labelled complete_genome but sequence length is under 1000 bp.",
            "downgraded_to_gene_fragment_and_excluded_from_target_views",
            "gene_fragment",
        )

    return {
        "host_genome_artifacts_flagged": len(host_genome_rows),
        "transcript_or_est_artifacts_flagged": len(transcript_rows),
        "tiny_sequence_artifacts_flagged": len(tiny_rows),
        "short_complete_genomes_downgraded": len(short_complete_rows),
    }


def mark_orphan_master_entries(conn: sqlite3.Connection) -> dict[str, int]:
    rows = dict_rows(
        conn,
        """
        SELECT vm.master_id, vm.canonical_name
        FROM virus_master vm
        LEFT JOIN viral_isolates vi ON vi.master_id = vm.master_id
        WHERE vi.isolate_id IS NULL
          AND vm.is_crustacean_virus = 1
          AND vm.entry_type NOT IN ('non_target', 'host_genome', 'catalog_only', 'reference_only')
        """,
    )
    for row in rows:
        conn.execute(
            """
            UPDATE virus_master
            SET entry_type = 'catalog_only',
                notes = TRIM(COALESCE(notes || ' ', '') ||
                    '[submission_blocker_fix] No linked isolate in the current release; retained as catalog-only context and excluded from target statistics.')
            WHERE master_id = ?
            """,
            (row["master_id"],),
        )
        conn.execute(
            """
            INSERT INTO virus_master_review_queue(master_id, canonical_name, issue_type, severity, reason, updated_at)
            VALUES (?, ?, 'catalog_only_no_local_isolate', 'P0',
                    'No linked isolate in the current release; excluded from target publication statistics.',
                    CURRENT_TIMESTAMP)
            ON CONFLICT(master_id) DO UPDATE SET
                canonical_name = excluded.canonical_name,
                issue_type = excluded.issue_type,
                severity = excluded.severity,
                reason = excluded.reason,
                updated_at = CURRENT_TIMESTAMP
            """,
            (row["master_id"], row["canonical_name"]),
        )
    return {"orphan_master_entries_marked_catalog_only": len(rows)}


def flag_diagnostic_title_pollution(conn: sqlite3.Connection) -> dict[str, int]:
    rows = dict_rows(
        conn,
        """
        SELECT method_id, method_name
        FROM diagnostic_methods
        WHERE curation_status <> 'rejected'
          AND (
              method_name LIKE 'Figure %:%'
              OR method_name LIKE 'Table %:%'
              OR LENGTH(method_name) > 120
          )
        """,
    )
    for row in rows:
        conn.execute(
            """
            UPDATE diagnostic_methods
            SET curation_status = 'rejected',
                data_quality = 'candidate_unreviewed',
                notes = trim(COALESCE(notes, '') || ' | submission_blocker_fix: method_name resembles a paper title/figure caption; not usable as curated method.')
            WHERE method_id = ?
            """,
            (row["method_id"],),
        )
        conn.execute(
            """
            INSERT INTO diagnostic_method_review_queue(method_id, issue_type, recommended_action)
            VALUES (?, 'method_name_title_or_caption_pollution', 'Extract actual assay name/target/LOD/validation from the source paper or reject.')
            ON CONFLICT(method_id) DO UPDATE SET
                issue_type = excluded.issue_type,
                recommended_action = excluded.recommended_action,
                status = 'open'
            """,
            (row["method_id"],),
        )
    return {"diagnostic_title_pollution_flagged": len(rows)}


def demote_unreferenced_manual_controls(conn: sqlite3.Connection) -> dict[str, int]:
    changed = conn.execute(
        """
        UPDATE control_management_methods
        SET curation_status = 'needs_review',
            notes = trim(COALESCE(notes, '') || ' | submission_blocker_fix: demoted from manual_checked because reference_id is missing.')
        WHERE curation_status = 'manual_checked'
          AND reference_id IS NULL
        """
    ).rowcount
    return {"manual_checked_controls_demoted_missing_reference": changed}


def demote_conflicting_ictv_mappings(conn: sqlite3.Connection) -> dict[str, int]:
    conflict_master_sql = """
        SELECT master_id
        FROM (
            SELECT vim.master_id
            FROM virus_ictv_mappings vim
            JOIN ictv_taxonomy it ON it.ictv_id = vim.ictv_id
            JOIN virus_master vm ON vm.master_id = vim.master_id
            WHERE vim.confidence = 'high'
              AND vim.match_status <> 'rejected'
            GROUP BY vim.master_id
            HAVING COUNT(DISTINCT vim.ictv_id) > 1
                OR COUNT(DISTINCT COALESCE(it.family, '')) > 1
                OR SUM(
                    CASE
                        WHEN NULLIF(TRIM(vm.virus_family), '') IS NOT NULL
                         AND NULLIF(TRIM(it.family), '') IS NOT NULL
                         AND LOWER(TRIM(vm.virus_family)) <> LOWER(TRIM(it.family))
                        THEN 1 ELSE 0
                    END
                ) > 0
        )
    """
    master_ids = [int(r["master_id"]) for r in conn.execute(conflict_master_sql).fetchall()]
    if not master_ids:
        return {
            "ictv_conflict_masters_demoted": 0,
            "ictv_conflict_mapping_rows_demoted": 0,
            "ictv_conflict_review_queue_rows": 0,
        }

    placeholders = ",".join("?" for _ in master_ids)
    mapping_rows_demoted = conn.execute(
        f"""
        UPDATE virus_ictv_mappings
        SET confidence = 'medium',
            notes = trim(COALESCE(notes, '') || ' | submission_blocker_fix: high-confidence ICTV mapping demoted because this master has multiple high-confidence taxa/families or family conflict; manual taxonomy review required.')
        WHERE master_id IN ({placeholders})
          AND confidence = 'high'
          AND match_status <> 'rejected'
        """,
        master_ids,
    ).rowcount
    conn.execute(
        f"""
        UPDATE virus_ictv_status
        SET ictv_status = 'pending_review',
            best_confidence = (
                SELECT MAX(confidence)
                FROM virus_ictv_mappings vim
                WHERE vim.master_id = virus_ictv_status.master_id
                  AND vim.match_status <> 'rejected'
            ),
            reason = trim(COALESCE(reason, '') || ' | submission_blocker_fix: conflicting ICTV mappings demoted; manual taxonomy review required.'),
            updated_at = CURRENT_TIMESTAMP
        WHERE master_id IN ({placeholders})
        """,
        master_ids,
    )
    queued = 0
    for row in dict_rows(
        conn,
        f"""
        SELECT vm.master_id, vm.canonical_name, vm.abbreviations, vm.virus_family, vm.virus_genus,
               COUNT(DISTINCT vi.isolate_id) AS isolate_count
        FROM virus_master vm
        LEFT JOIN viral_isolates vi ON vi.master_id = vm.master_id
        WHERE vm.master_id IN ({placeholders})
        GROUP BY vm.master_id
        """,
        tuple(master_ids),
    ):
        conn.execute(
            """
            INSERT INTO ictv_review_priority_queue (
                master_id, canonical_name, abbreviations, virus_family, virus_genus,
                isolate_count, priority, reason, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, 'P0',
                      'Conflicting high-confidence ICTV mappings were demoted; verify official family/taxon manually.',
                      CURRENT_TIMESTAMP)
            ON CONFLICT(master_id) DO UPDATE SET
                priority = 'P0',
                reason = excluded.reason,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                row["master_id"],
                row["canonical_name"],
                row["abbreviations"],
                row["virus_family"],
                row["virus_genus"],
                row["isolate_count"],
            ),
        )
        queued += 1
    return {
        "ictv_conflict_masters_demoted": len(master_ids),
        "ictv_conflict_mapping_rows_demoted": mapping_rows_demoted,
        "ictv_conflict_review_queue_rows": queued,
    }


def refresh_ictv_status_derived_fields(conn: sqlite3.Connection) -> dict[str, int]:
    rows = dict_rows(
        conn,
        """
        SELECT s.master_id,
               COUNT(m.mapping_id) AS mapping_count,
               CASE
                   WHEN SUM(CASE WHEN m.confidence = 'high' THEN 1 ELSE 0 END) > 0 THEN 'high'
                   WHEN SUM(CASE WHEN m.confidence = 'medium' THEN 1 ELSE 0 END) > 0 THEN 'medium'
                   WHEN SUM(CASE WHEN m.confidence = 'low' THEN 1 ELSE 0 END) > 0 THEN 'low'
                   ELSE NULL
               END AS best_confidence
        FROM virus_ictv_status s
        LEFT JOIN virus_ictv_mappings m
          ON m.master_id = s.master_id
         AND m.match_status <> 'rejected'
        GROUP BY s.master_id
        """
    )
    changed = 0
    for row in rows:
        changed += conn.execute(
            """
            UPDATE virus_ictv_status
            SET mapping_count = ?,
                best_confidence = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE master_id = ?
              AND (
                  COALESCE(mapping_count, -1) <> ?
                  OR COALESCE(best_confidence, '') <> COALESCE(?, '')
              )
            """,
            (
                row["mapping_count"],
                row["best_confidence"],
                row["master_id"],
                row["mapping_count"],
                row["best_confidence"],
            ),
        ).rowcount
    return {"ictv_status_derived_fields_refreshed": changed}


def quarantine_raw_release_manifest_exports(conn: sqlite3.Connection) -> dict[str, int]:
    changed = conn.execute(
        """
        UPDATE release_manifest
        SET notes = trim(COALESCE(notes, '') || ' | submission_blocker_fix: raw evidence_records export is deprecated and must not be included in public release artifacts.'),
            export_path = 'maintenance_archive/deprecated_release_exports/' || COALESCE(export_path, 'evidence_records.tsv')
        WHERE LOWER(table_name) = 'evidence_records'
          AND LOWER(COALESCE(export_path, '')) NOT LIKE '%reviewed%'
          AND LOWER(COALESCE(export_path, '')) NOT LIKE 'maintenance_archive/deprecated_release_exports/%'
        """
    ).rowcount
    return {"raw_evidence_release_manifest_entries_deprecated": changed}


def rebuild_analysis_views(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        DROP VIEW IF EXISTS analysis_target_isolates;
        CREATE VIEW analysis_target_isolates AS
        SELECT v.*
        FROM viral_isolates v
        JOIN virus_master vm ON vm.master_id = v.master_id
        LEFT JOIN isolate_curated_profiles icp ON icp.isolate_id = v.isolate_id
        LEFT JOIN host_scope_overrides hso ON hso.host_id = icp.host_id
        WHERE vm.is_crustacean_virus = 1
          AND vm.entry_type NOT IN ('non_target', 'host_genome')
          AND COALESCE(icp.host_is_target, 1) = 1
          AND COALESCE(hso.exclude_from_target_stats, 0) = 0
          AND COALESCE(icp.dataset_tier, '') NOT IN ('sequence_scope_artifact', 'host_genome_artifact')
          AND v.accession NOT LIKE 'RDRP\\_%' ESCAPE '\\';

        DROP VIEW IF EXISTS analysis_strict_target_isolates;
        CREATE VIEW analysis_strict_target_isolates AS
        SELECT v.*
        FROM analysis_target_isolates v
        LEFT JOIN isolate_curated_profiles icp ON icp.isolate_id = v.isolate_id
        WHERE COALESCE(icp.curation_status, 'auto_seeded') <> 'conflict_open'
          AND COALESCE(icp.dataset_tier, '') <> 'unverified';

        DROP VIEW IF EXISTS analysis_reviewed_evidence_records;
        CREATE VIEW analysis_reviewed_evidence_records AS
        SELECT *
        FROM evidence_records
        WHERE curation_status = 'manual_checked'
          AND reference_id IS NOT NULL;

        DROP VIEW IF EXISTS analysis_curated_diagnostic_methods;
        CREATE VIEW analysis_curated_diagnostic_methods AS
        SELECT *
        FROM diagnostic_methods
        WHERE data_quality = 'curated'
          AND curation_status = 'manual_checked'
          AND virus_master_id IS NOT NULL
          AND reference_id IS NOT NULL
          AND target_gene_or_region IS NOT NULL AND TRIM(target_gene_or_region) <> ''
          AND detection_limit IS NOT NULL AND TRIM(detection_limit) <> ''
          AND validation_context IS NOT NULL AND TRIM(validation_context) <> '';
        """
    )


def audit_blockers(conn: sqlite3.Connection) -> dict[str, Any]:
    metrics = {
        "target_mrna_cdna_est_artifacts": scalar(
            conn,
            f"""
            SELECT COUNT(*)
            FROM analysis_target_isolates vi
            LEFT JOIN nucleotide_records nr ON nr.isolate_id = vi.isolate_id
            LEFT JOIN sample_metadata sm ON sm.isolate_id = vi.isolate_id
            WHERE {ARTIFACT_TEXT_SQL} LIKE '% mrna%'
               OR {ARTIFACT_TEXT_SQL} LIKE '% cdna%'
               OR {ARTIFACT_TEXT_SQL} LIKE '% est%'
               OR {ARTIFACT_TEXT_SQL} LIKE '%ribosomal%'
               OR {ARTIFACT_TEXT_SQL} LIKE '%clone %'
            """,
        ),
        "target_host_genome_artifacts": scalar(
            conn,
            f"""
            SELECT COUNT(*)
            FROM analysis_target_isolates vi
            LEFT JOIN nucleotide_records nr ON nr.isolate_id = vi.isolate_id
            LEFT JOIN sample_metadata sm ON sm.isolate_id = vi.isolate_id
            WHERE COALESCE(vi.sequence_length, vi.genome_length, 0) > 10000000
               OR {ARTIFACT_TEXT_SQL} LIKE '% chromosome %'
               OR {ARTIFACT_TEXT_SQL} LIKE '%genomic scaffold%'
            """,
        ),
        "target_short_complete_genomes": scalar(
            conn,
            """
            SELECT COUNT(*)
            FROM analysis_target_isolates
            WHERE completeness = 'complete_genome'
              AND COALESCE(sequence_length, genome_length, 0) > 0
              AND COALESCE(sequence_length, genome_length, 0) < 1000
            """,
        ),
        "manual_checked_controls_missing_reference": scalar(
            conn,
            "SELECT COUNT(*) FROM control_management_methods WHERE curation_status='manual_checked' AND reference_id IS NULL",
        ),
            "diagnostic_title_pollution_open": scalar(
            conn,
            """
            SELECT COUNT(*)
            FROM diagnostic_methods
            WHERE curation_status <> 'rejected'
              AND (method_name LIKE 'Figure %:%' OR method_name LIKE 'Table %:%' OR LENGTH(method_name) > 120)
            """,
        ),
        "analysis_target_isolates": scalar(conn, "SELECT COUNT(*) FROM analysis_target_isolates"),
        "analysis_strict_target_isolates": scalar(conn, "SELECT COUNT(*) FROM analysis_strict_target_isolates"),
        "sequence_curation_flags": scalar(conn, "SELECT COUNT(*) FROM sequence_curation_flags"),
        "ictv_multiple_high_confidence_taxa": scalar(
            conn,
            """
            SELECT COUNT(*)
            FROM (
                SELECT master_id
                FROM virus_ictv_mappings
                WHERE confidence = 'high'
                  AND match_status <> 'rejected'
                GROUP BY master_id
                HAVING COUNT(DISTINCT ictv_id) > 1
            )
            """,
        ),
        "ictv_multiple_high_confidence_families": scalar(
            conn,
            """
            SELECT COUNT(*)
            FROM (
                SELECT vim.master_id
                FROM virus_ictv_mappings vim
                JOIN ictv_taxonomy it ON it.ictv_id = vim.ictv_id
                WHERE vim.confidence = 'high'
                  AND vim.match_status <> 'rejected'
                GROUP BY vim.master_id
                HAVING COUNT(DISTINCT COALESCE(it.family, '')) > 1
            )
            """,
        ),
        "ictv_family_conflict_with_master": scalar(
            conn,
            """
            SELECT COUNT(*)
            FROM (
                SELECT DISTINCT vim.master_id
                FROM virus_ictv_mappings vim
                JOIN ictv_taxonomy it ON it.ictv_id = vim.ictv_id
                JOIN virus_master vm ON vm.master_id = vim.master_id
                WHERE vim.confidence = 'high'
                  AND vim.match_status <> 'rejected'
                  AND NULLIF(TRIM(vm.virus_family), '') IS NOT NULL
                  AND NULLIF(TRIM(it.family), '') IS NOT NULL
                  AND LOWER(TRIM(vm.virus_family)) <> LOWER(TRIM(it.family))
            )
            """,
        ),
    }
    return metrics


def main() -> None:
    if not DB_PATH.exists():
        raise FileNotFoundError(DB_PATH)
    ts = stamp()
    REPORTS_DIR.mkdir(exist_ok=True)
    backup = backup_database(ts)
    with connect() as conn:
        before = {
            "analysis_target_isolates": scalar(conn, "SELECT COUNT(*) FROM analysis_target_isolates"),
            "analysis_strict_target_isolates": scalar(conn, "SELECT COUNT(*) FROM analysis_strict_target_isolates"),
        }
        with conn:
            ensure_tables(conn)
            sequence_counts = quarantine_sequence_artifacts(conn)
            orphan_counts = mark_orphan_master_entries(conn)
            diagnostic_counts = flag_diagnostic_title_pollution(conn)
            control_counts = demote_unreferenced_manual_controls(conn)
            ictv_counts = demote_conflicting_ictv_mappings(conn)
            ictv_refresh_counts = refresh_ictv_status_derived_fields(conn)
            release_manifest_counts = quarantine_raw_release_manifest_exports(conn)
            rebuild_analysis_views(conn)
            metrics = audit_blockers(conn)
            integrity = scalar(conn, "PRAGMA integrity_check")
            fk_violations = len(dict_rows(conn, "PRAGMA foreign_key_check"))
            if integrity != "ok" or fk_violations:
                raise RuntimeError({"integrity_check": integrity, "foreign_key_violations": fk_violations})
        flag_rows = dict_rows(
            conn,
            """
            SELECT scf.*, vi.virus_name, vi.genome_length, vi.sequence_length
            FROM sequence_curation_flags scf
            JOIN viral_isolates vi ON vi.isolate_id = scf.isolate_id
            ORDER BY scf.flag_type, vi.accession
            """,
        )
    flags_csv = REPORTS_DIR / f"submission_blocker_sequence_flags_{ts}.csv"
    write_csv(flags_csv, flag_rows)
    report = {
        "timestamp": ts,
        "backup": str(backup),
        "before": before,
        "actions": {**sequence_counts, **orphan_counts, **diagnostic_counts, **control_counts, **ictv_counts, **ictv_refresh_counts, **release_manifest_counts},
        "post_fix_blocker_metrics": metrics,
        "integrity_check": "ok",
        "foreign_key_violations": 0,
        "sequence_flags_csv": str(flags_csv),
    }
    report_path = REPORTS_DIR / f"submission_blocker_fixes_{ts}.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
