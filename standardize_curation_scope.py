#!/usr/bin/env python3
"""Apply conservative curation-standardization fixes.

This pass focuses on deterministic fixes:
- define controlled vocabulary tables used for audits
- quarantine non-target pathogenicity rows instead of deleting them
- mark technical/non-target hosts as excluded from target analyses
- synchronize isolate primary references from isolate_reference_links
- reject obvious diagnostic placeholder artifacts
- create ICTV status and analysis views
"""

from __future__ import annotations

import datetime as dt
import json
import shutil
import sqlite3
from pathlib import Path


APP_DIR = Path(__file__).resolve().parent
DB_PATH = APP_DIR / "crustacean_virus_core.db"
BACKUP_DIR = APP_DIR / "backups"


VOCAB = {
    "virus_entry_type": [
        ("complete_genome", "Target virus represented by complete/near-complete genome or accepted main entry."),
        ("unclassified_rna_virus", "Unclassified RNA virus entry retained for discovery/metavirome context."),
        ("non_target", "Non-crustacean/non-target viral context; excluded from target analyses."),
        ("host_genome", "Host genome or host-associated non-virus context; excluded from target analyses."),
    ],
    "host_type": [
        ("crustacean", "Species-level crustacean host."),
        ("not_species_level", "Crustacean or crustacean-like grouping above species level or common-name grouping."),
        ("non_crustacean", "Non-crustacean biological host/context."),
        ("technical_host", "Cloning/vector/cell-line host; not a biological virus host."),
        ("unknown", "Host cannot be resolved."),
    ],
    "curation_status": [
        ("needs_review", "Candidate or auto-derived record pending curator review."),
        ("auto_seeded", "Deterministically imported from source data but not manually checked."),
        ("auto_imported", "Imported by a scripted pipeline and suitable for candidate-level use."),
        ("manual_checked", "Curator-validated record."),
        ("rejected", "Known non-target, placeholder artifact, or incorrect candidate."),
        ("conflict_open", "Record has unresolved conflict."),
    ],
    "ictv_status": [
        ("mapped", "Mapped to ICTV taxonomy."),
        ("rejected", "Candidate mapping was rejected."),
        ("non_target", "Not part of the target crustacean-virus scope."),
        ("unclassified_not_expected", "Unclassified/discovery entry for which species-level ICTV mapping is not expected."),
        ("pending_review", "Target entry still needs ICTV review."),
    ],
}

TECHNICAL_HOST_PATTERNS = [
    "%e. coli%",
    "%e.coli%",
    "%dh5%",
    "%dh10b%",
    "%k12%",
    "%solr%",
    "%electromax%",
]


def stamp() -> str:
    return dt.datetime.now().strftime("%Y%m%d_%H%M%S")


def backup_database() -> Path:
    BACKUP_DIR.mkdir(exist_ok=True)
    backup = BACKUP_DIR / f"crustacean_virus_core_before_scope_standardization_{stamp()}.db"
    shutil.copy2(DB_PATH, backup)
    return backup


def count(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> int:
    return int(conn.execute(sql, params).fetchone()[0])


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS curation_vocab_terms (
            vocab_id INTEGER PRIMARY KEY AUTOINCREMENT,
            category TEXT NOT NULL,
            term TEXT NOT NULL,
            description TEXT,
            active INTEGER DEFAULT 1 CHECK (active IN (0, 1)),
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(category, term)
        );

        CREATE TABLE IF NOT EXISTS curation_standardization_log (
            log_id INTEGER PRIMARY KEY AUTOINCREMENT,
            action TEXT NOT NULL,
            details_json TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS host_scope_overrides (
            host_id INTEGER PRIMARY KEY,
            scope_status TEXT NOT NULL CHECK (
                scope_status IN ('target', 'non_target', 'technical_host', 'not_species_level', 'unknown')
            ),
            exclude_from_target_stats INTEGER NOT NULL DEFAULT 0 CHECK (exclude_from_target_stats IN (0, 1)),
            reason TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(host_id) REFERENCES crustacean_hosts(host_id)
        );

        CREATE TABLE IF NOT EXISTS virus_ictv_status (
            master_id INTEGER PRIMARY KEY,
            ictv_status TEXT NOT NULL CHECK (
                ictv_status IN ('mapped', 'rejected', 'non_target', 'unclassified_not_expected', 'pending_review')
            ),
            mapping_count INTEGER DEFAULT 0,
            best_confidence TEXT,
            reason TEXT,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(master_id) REFERENCES virus_master(master_id)
        );

        CREATE TABLE IF NOT EXISTS diagnostic_method_review_queue (
            review_id INTEGER PRIMARY KEY AUTOINCREMENT,
            method_id INTEGER NOT NULL UNIQUE,
            issue_type TEXT NOT NULL,
            recommended_action TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            status TEXT DEFAULT 'open' CHECK (status IN ('open', 'resolved', 'ignored')),
            FOREIGN KEY(method_id) REFERENCES diagnostic_methods(method_id)
        );
        """
    )
    for category, rows in VOCAB.items():
        for term, desc in rows:
            conn.execute(
                """
                INSERT INTO curation_vocab_terms(category, term, description)
                VALUES (?, ?, ?)
                ON CONFLICT(category, term) DO UPDATE SET
                    description = excluded.description,
                    active = 1
                """,
                (category, term, desc),
            )


def log_action(conn: sqlite3.Connection, action: str, details: dict) -> None:
    conn.execute(
        "INSERT INTO curation_standardization_log(action, details_json) VALUES (?, ?)",
        (action, json.dumps(details, ensure_ascii=False, sort_keys=True)),
    )


def mark_technical_hosts(conn: sqlite3.Connection) -> dict:
    technical_where = " OR ".join(["lower(scientific_name) LIKE ?" for _ in TECHNICAL_HOST_PATTERNS])
    params = tuple(p.lower() for p in TECHNICAL_HOST_PATTERNS)
    technical_ids = [
        int(row["host_id"])
        for row in conn.execute(
            f"SELECT host_id FROM crustacean_hosts WHERE {technical_where}", params
        )
    ]
    for host_id in technical_ids:
        conn.execute(
            """
            UPDATE crustacean_hosts
            SET host_type = 'technical_host',
                common_name_cn = COALESCE(common_name_cn, '技术宿主/克隆宿主')
            WHERE host_id = ?
            """,
            (host_id,),
        )
        conn.execute(
            """
            INSERT INTO host_scope_overrides(host_id, scope_status, exclude_from_target_stats, reason)
            VALUES (?, 'technical_host', 1, 'Detected E. coli / cloning strain technical host context')
            ON CONFLICT(host_id) DO UPDATE SET
                scope_status = excluded.scope_status,
                exclude_from_target_stats = excluded.exclude_from_target_stats,
                reason = excluded.reason,
                updated_at = CURRENT_TIMESTAMP
            """,
            (host_id,),
        )

    non_target_ids = [
        int(row["host_id"])
        for row in conn.execute(
            """
            SELECT host_id
            FROM crustacean_hosts
            WHERE host_type IN ('non_crustacean', 'technical_host')
            """
        )
    ]
    for host_id in non_target_ids:
        conn.execute(
            """
            INSERT INTO host_scope_overrides(host_id, scope_status, exclude_from_target_stats, reason)
            SELECT host_id,
                   CASE WHEN host_type = 'technical_host' THEN 'technical_host' ELSE 'non_target' END,
                   1,
                   'Host type excludes this row from target crustacean-host analyses'
            FROM crustacean_hosts
            WHERE host_id = ?
            ON CONFLICT(host_id) DO UPDATE SET
                scope_status = excluded.scope_status,
                exclude_from_target_stats = excluded.exclude_from_target_stats,
                reason = excluded.reason,
                updated_at = CURRENT_TIMESTAMP
            """,
            (host_id,),
        )

    updated_profiles = conn.execute(
        """
        UPDATE isolate_curated_profiles
        SET host_is_target = 0,
            notes = trim(COALESCE(notes, '') || ' | host_scope_standardized: non-target or technical host'),
            updated_at = CURRENT_TIMESTAMP
        WHERE host_id IN (SELECT host_id FROM host_scope_overrides WHERE exclude_from_target_stats = 1)
          AND COALESCE(host_is_target, 1) != 0
        """
    ).rowcount
    return {
        "technical_hosts_marked": len(technical_ids),
        "non_target_host_overrides": len(non_target_ids),
        "isolate_profiles_host_is_target_zeroed": updated_profiles,
    }


def quarantine_non_target_pathogenicity(conn: sqlite3.Connection) -> dict:
    rows = conn.execute(
        """
        SELECT pe.pathogenicity_id, vm.canonical_name
        FROM pathogenicity_evidence pe
        JOIN virus_master vm ON vm.master_id = pe.virus_master_id
        WHERE (vm.is_crustacean_virus = 0 OR vm.entry_type IN ('non_target', 'host_genome'))
          AND pe.curation_status != 'rejected'
        """
    ).fetchall()
    changed = 0
    for row in rows:
        conn.execute(
            """
            UPDATE pathogenicity_evidence
            SET curation_status = 'rejected',
                notes = trim(COALESCE(notes, '') || ' | scope_standardization: non-target virus excluded from crustacean pathogenicity evidence'),
                updated_at = CURRENT_TIMESTAMP
            WHERE pathogenicity_id = ?
            """,
            (row["pathogenicity_id"],),
        )
        changed += 1
    return {"non_target_pathogenicity_rejected": changed}


def sync_isolate_primary_references(conn: sqlite3.Connection) -> dict:
    priority = {
        "infection_record_reference": 10,
        "genome_sequencing": 20,
        "genbank_reference": 30,
        "initial_discovery": 40,
        "collection_or_isolation": 50,
        "curation_evidence": 60,
        "other": 90,
    }
    rows = conn.execute(
        """
        SELECT v.isolate_id, l.reference_id, l.link_type
        FROM viral_isolates v
        JOIN isolate_reference_links l ON l.isolate_id = v.isolate_id
        WHERE v.reference_id IS NULL
        ORDER BY v.isolate_id, l.priority, l.reference_id
        """
    ).fetchall()
    best: dict[int, tuple[int, int]] = {}
    for row in rows:
        isolate_id = int(row["isolate_id"])
        score = priority.get(row["link_type"], 100)
        ref_id = int(row["reference_id"])
        if isolate_id not in best or (score, ref_id) < best[isolate_id]:
            best[isolate_id] = (score, ref_id)
    for isolate_id, (_, ref_id) in best.items():
        conn.execute(
            "UPDATE viral_isolates SET reference_id = ? WHERE isolate_id = ? AND reference_id IS NULL",
            (ref_id, isolate_id),
        )
    conn.execute(
        """
        UPDATE isolate_curated_profiles
        SET primary_reference_id = (
                SELECT v.reference_id FROM viral_isolates v
                WHERE v.isolate_id = isolate_curated_profiles.isolate_id
            ),
            updated_at = CURRENT_TIMESTAMP
        WHERE primary_reference_id IS NULL
          AND EXISTS (
              SELECT 1 FROM viral_isolates v
              WHERE v.isolate_id = isolate_curated_profiles.isolate_id
                AND v.reference_id IS NOT NULL
          )
        """
    )
    return {"viral_isolates_reference_id_filled": len(best)}


def reject_bad_diagnostic_placeholders(conn: sqlite3.Connection) -> dict:
    bad = conn.execute(
        """
        SELECT method_id,
               CASE
                 WHEN virus_master_id IS NULL THEN 'missing_virus_master_id'
                 WHEN method_name = method_category OR method_name = method_subcategory THEN 'method_name_is_category_placeholder'
                 ELSE 'placeholder_needs_review'
               END AS issue_type
        FROM diagnostic_methods
        WHERE data_quality = 'placeholder'
          AND (
              virus_master_id IS NULL
              OR method_name = method_category
              OR method_name = method_subcategory
          )
        """
    ).fetchall()
    for row in bad:
        action = (
            "delete_or_replace_with_specific_method_after_manual_review"
            if row["issue_type"] == "method_name_is_category_placeholder"
            else "link_to_virus_master_or_reject"
        )
        conn.execute(
            """
            INSERT INTO diagnostic_method_review_queue(method_id, issue_type, recommended_action)
            VALUES (?, ?, ?)
            ON CONFLICT(method_id) DO UPDATE SET
                issue_type = excluded.issue_type,
                recommended_action = excluded.recommended_action,
                status = 'open'
            """,
            (row["method_id"], row["issue_type"], action),
        )
    rejected = conn.execute(
        """
        UPDATE diagnostic_methods
        SET curation_status = 'rejected',
            notes = trim(COALESCE(notes, '') || ' | scope_standardization: placeholder artifact excluded from curated diagnostics')
        WHERE method_id IN (SELECT method_id FROM diagnostic_method_review_queue WHERE status = 'open')
          AND data_quality = 'placeholder'
          AND curation_status != 'rejected'
        """
    ).rowcount
    return {"diagnostic_placeholder_review_rows": len(bad), "diagnostic_placeholders_rejected": rejected}


def rebuild_ictv_status(conn: sqlite3.Connection) -> dict:
    conn.execute("DELETE FROM virus_ictv_status")
    rows = conn.execute(
        """
        SELECT vm.master_id, vm.canonical_name, vm.entry_type, vm.is_crustacean_virus,
               SUM(CASE WHEN vim.match_status IN ('auto_matched', 'manual_checked') THEN 1 ELSE 0 END) AS accepted_mappings,
               SUM(CASE WHEN vim.match_status = 'rejected' THEN 1 ELSE 0 END) AS rejected_mappings,
               MAX(vim.confidence) AS best_confidence
        FROM virus_master vm
        LEFT JOIN virus_ictv_mappings vim ON vim.master_id = vm.master_id
        GROUP BY vm.master_id
        """
    ).fetchall()
    counts: dict[str, int] = {}
    for row in rows:
        accepted = int(row["accepted_mappings"] or 0)
        rejected = int(row["rejected_mappings"] or 0)
        if row["is_crustacean_virus"] == 0 or row["entry_type"] in ("non_target", "host_genome"):
            status = "non_target"
            reason = "Non-target or host-genome entry."
        elif accepted:
            status = "mapped"
            reason = "Has accepted ICTV mapping."
        elif rejected:
            status = "rejected"
            reason = "Only rejected ICTV mappings found."
        elif row["entry_type"] == "unclassified_rna_virus" or str(row["canonical_name"]).lower().startswith("unclassified"):
            status = "unclassified_not_expected"
            reason = "Unclassified discovery entry; ICTV species mapping is not expected yet."
        else:
            status = "pending_review"
            reason = "Target virus without accepted ICTV mapping."
        counts[status] = counts.get(status, 0) + 1
        conn.execute(
            """
            INSERT INTO virus_ictv_status(master_id, ictv_status, mapping_count, best_confidence, reason)
            VALUES (?, ?, ?, ?, ?)
            """,
            (row["master_id"], status, accepted + rejected, row["best_confidence"], reason),
        )
    return {f"ictv_status_{k}": v for k, v in counts.items()}


def create_analysis_views(conn: sqlite3.Connection) -> None:
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
          AND COALESCE(hso.exclude_from_target_stats, 0) = 0;

        DROP VIEW IF EXISTS analysis_curated_diagnostic_methods;
        CREATE VIEW analysis_curated_diagnostic_methods AS
        SELECT *
        FROM diagnostic_methods
        WHERE data_quality = 'curated'
          AND curation_status = 'manual_checked'
          AND virus_master_id IS NOT NULL;

        DROP VIEW IF EXISTS analysis_reviewed_evidence_records;
        CREATE VIEW analysis_reviewed_evidence_records AS
        SELECT *
        FROM evidence_records
        WHERE curation_status IN ('manual_checked', 'auto_imported')
          AND reference_id IS NOT NULL;
        """
    )


def main() -> None:
    if not DB_PATH.exists():
        raise FileNotFoundError(DB_PATH)
    backup = backup_database()
    details = {"backup": str(backup)}
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        with conn:
            ensure_schema(conn)
            details.update(mark_technical_hosts(conn))
            details.update(quarantine_non_target_pathogenicity(conn))
            details.update(sync_isolate_primary_references(conn))
            details.update(reject_bad_diagnostic_placeholders(conn))
            details.update(rebuild_ictv_status(conn))
            create_analysis_views(conn)
            integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
            fk_rows = [tuple(row) for row in conn.execute("PRAGMA foreign_key_check").fetchall()]
            details["integrity_check"] = integrity
            details["foreign_key_violations"] = len(fk_rows)
            details["analysis_target_isolates"] = count(conn, "SELECT COUNT(*) FROM analysis_target_isolates")
            log_action(conn, "standardize_curation_scope", details)
            if integrity != "ok" or fk_rows:
                raise RuntimeError({"integrity_check": integrity, "foreign_key_check": fk_rows[:20]})
    print(json.dumps(details, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
