#!/usr/bin/env python3
"""Repeatable QA/QC hardening layer for AquaVir-KB.

This script does not invent biological facts. It records measurable quality
issues, duplicate/conflict groups, and entity-level quality scores so each
import or curation round can be audited and compared.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any


BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "crustacean_virus_core.db"
REPORTS_DIR = BASE_DIR / "reports"
DETAIL_LIMIT = 5000

TARGET_HOST_PHYLA = {
    "Arthropoda",
    "Mollusca",
    "Echinodermata",
    "Cnidaria",
    "Porifera",
    "Annelida",
    "Platyhelminthes",
    "Nematoda",
}

CLAIM_POLLUTION_SQL = """
(
    claim LIKE '%http%'
    OR claim LIKE '%www.%'
    OR claim LIKE '%doi.org%'
    OR claim LIKE '%Dryad, Table%'
    OR claim LIKE '%Table S%'
    OR claim LIKE '%Supplementary Table%'
    OR claim LIKE '%Full text%'
    OR LENGTH(claim) > 500
)
AND claim NOT LIKE 'Auto-extracted from abstract:%'
AND claim NOT LIKE 'Abstract mentions %'
"""


def stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path), timeout=120)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 120000")
    return conn


def table_exists(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (name,),
    ).fetchone() is not None


def create_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS qaqc_runs (
            run_id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_ts TEXT NOT NULL,
            db_path TEXT NOT NULL,
            script_name TEXT NOT NULL,
            notes TEXT
        );

        CREATE TABLE IF NOT EXISTS qaqc_summary (
            summary_id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id INTEGER NOT NULL,
            rule_group TEXT NOT NULL,
            rule_id TEXT NOT NULL,
            severity TEXT NOT NULL,
            table_name TEXT NOT NULL,
            issue_count INTEGER NOT NULL,
            affected_entity_count INTEGER NOT NULL,
            pass_rate REAL,
            recommendation TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (run_id) REFERENCES qaqc_runs(run_id)
        );

        CREATE TABLE IF NOT EXISTS qaqc_issues (
            issue_id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id INTEGER NOT NULL,
            rule_id TEXT NOT NULL,
            severity TEXT NOT NULL,
            table_name TEXT NOT NULL,
            primary_key TEXT,
            entity_type TEXT,
            entity_id INTEGER,
            field_name TEXT,
            observed_value TEXT,
            expected_rule TEXT,
            linked_virus_master_id INTEGER,
            linked_host_id INTEGER,
            linked_isolate_id INTEGER,
            linked_reference_id INTEGER,
            evidence_id INTEGER,
            action_hint TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (run_id) REFERENCES qaqc_runs(run_id)
        );

        CREATE TABLE IF NOT EXISTS qaqc_duplicates (
            duplicate_id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id INTEGER NOT NULL,
            duplicate_type TEXT NOT NULL,
            dedupe_key TEXT NOT NULL,
            table_name TEXT NOT NULL,
            record_ids TEXT NOT NULL,
            canonical_candidate_id INTEGER,
            conflict_fields TEXT,
            duplicate_count INTEGER NOT NULL,
            severity TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (run_id) REFERENCES qaqc_runs(run_id)
        );

        CREATE TABLE IF NOT EXISTS qaqc_conflicts (
            conflict_id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id INTEGER NOT NULL,
            conflict_type TEXT NOT NULL,
            entity_type TEXT NOT NULL,
            entity_id INTEGER,
            field_name TEXT NOT NULL,
            value_a TEXT,
            source_a TEXT,
            value_b TEXT,
            source_b TEXT,
            resolution_status TEXT NOT NULL DEFAULT 'open',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (run_id) REFERENCES qaqc_runs(run_id)
        );

        CREATE TABLE IF NOT EXISTS entity_quality_scores (
            score_id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id INTEGER NOT NULL,
            entity_type TEXT NOT NULL,
            entity_id INTEGER NOT NULL,
            virus_master_id INTEGER,
            host_id INTEGER,
            isolate_id INTEGER,
            reference_id INTEGER,
            completeness_score INTEGER NOT NULL,
            traceability_score INTEGER NOT NULL,
            consistency_score INTEGER NOT NULL,
            evidence_score INTEGER NOT NULL,
            artifact_penalty INTEGER NOT NULL,
            blocking_issue_count INTEGER NOT NULL,
            quality_grade TEXT NOT NULL,
            reasons TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (run_id) REFERENCES qaqc_runs(run_id)
        );

        CREATE INDEX IF NOT EXISTS idx_qaqc_issues_run_rule ON qaqc_issues(run_id, rule_id);
        CREATE INDEX IF NOT EXISTS idx_qaqc_issues_severity ON qaqc_issues(run_id, severity);
        CREATE INDEX IF NOT EXISTS idx_qaqc_scores_run_grade ON entity_quality_scores(run_id, entity_type, quality_grade);
        """
    )


def start_run(conn: sqlite3.Connection, db_path: Path) -> int:
    cur = conn.execute(
        """
        INSERT INTO qaqc_runs(run_ts, db_path, script_name, notes)
        VALUES (?, ?, ?, ?)
        """,
        (
            datetime.now().isoformat(timespec="seconds"),
            str(db_path),
            Path(__file__).name,
            "Offline QA/QC hardening: issues, duplicates, conflicts, and entity scores.",
        ),
    )
    return int(cur.lastrowid)


def add_summary(
    conn: sqlite3.Connection,
    run_id: int,
    rule_group: str,
    rule_id: str,
    severity: str,
    table_name: str,
    issue_count: int,
    affected_entity_count: int,
    recommendation: str,
    denominator: int | None = None,
) -> None:
    pass_rate = None
    if denominator and denominator > 0:
        pass_rate = round((denominator - issue_count) / denominator * 100, 3)
    conn.execute(
        """
        INSERT INTO qaqc_summary(
            run_id, rule_group, rule_id, severity, table_name, issue_count,
            affected_entity_count, pass_rate, recommendation
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            run_id,
            rule_group,
            rule_id,
            severity,
            table_name,
            int(issue_count),
            int(affected_entity_count),
            pass_rate,
            recommendation,
        ),
    )


def add_issue(
    conn: sqlite3.Connection,
    run_id: int,
    rule_id: str,
    severity: str,
    table_name: str,
    primary_key: Any,
    entity_type: str,
    entity_id: Any,
    field_name: str,
    observed_value: Any,
    expected_rule: str,
    action_hint: str,
    *,
    virus_master_id: Any = None,
    host_id: Any = None,
    isolate_id: Any = None,
    reference_id: Any = None,
    evidence_id: Any = None,
) -> None:
    conn.execute(
        """
        INSERT INTO qaqc_issues(
            run_id, rule_id, severity, table_name, primary_key, entity_type,
            entity_id, field_name, observed_value, expected_rule,
            linked_virus_master_id, linked_host_id, linked_isolate_id,
            linked_reference_id, evidence_id, action_hint
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            run_id,
            rule_id,
            severity,
            table_name,
            None if primary_key is None else str(primary_key),
            entity_type,
            entity_id,
            field_name,
            None if observed_value is None else str(observed_value),
            expected_rule,
            virus_master_id,
            host_id,
            isolate_id,
            reference_id,
            evidence_id,
            action_hint,
        ),
    )


def scalar(conn: sqlite3.Connection, sql: str, params: tuple[Any, ...] = ()) -> int:
    row = conn.execute(sql, params).fetchone()
    return int(row[0] or 0)


def write_csv(path: Path, rows: list[sqlite3.Row] | list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    first = rows[0]
    fieldnames = list(first.keys()) if isinstance(first, sqlite3.Row) else list(first)
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(dict(row))


def record_duplicate_groups(
    conn: sqlite3.Connection,
    run_id: int,
    duplicate_type: str,
    table_name: str,
    key_sql: str,
    severity: str,
    recommendation: str,
) -> int:
    groups = conn.execute(key_sql).fetchall()
    for row in groups:
        ids = str(row["record_ids"])
        canonical = int(ids.split(",")[0]) if ids else None
        conn.execute(
            """
            INSERT INTO qaqc_duplicates(
                run_id, duplicate_type, dedupe_key, table_name, record_ids,
                canonical_candidate_id, conflict_fields, duplicate_count, severity
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                duplicate_type,
                row["dedupe_key"],
                table_name,
                ids,
                canonical,
                row["conflict_fields"] if "conflict_fields" in row.keys() else None,
                row["n"],
                severity,
            ),
        )
    add_summary(
        conn,
        run_id,
        "duplicates",
        duplicate_type,
        severity,
        table_name,
        len(groups),
        sum(int(r["n"]) for r in groups),
        recommendation,
    )
    return len(groups)


def run_duplicate_rules(conn: sqlite3.Connection, run_id: int) -> None:
    record_duplicate_groups(
        conn,
        run_id,
        "duplicate_isolate_accession",
        "viral_isolates",
        """
        SELECT lower(trim(accession)) AS dedupe_key,
               group_concat(isolate_id) AS record_ids,
               group_concat(DISTINCT COALESCE(master_id, 'NULL')) AS conflict_fields,
               COUNT(*) AS n
        FROM viral_isolates
        WHERE accession IS NOT NULL AND trim(accession) <> ''
        GROUP BY lower(trim(accession))
        HAVING COUNT(*) > 1
        ORDER BY n DESC, dedupe_key
        """,
        "P0",
        "Merge duplicate accessions or split true segmented records with explicit segment identifiers.",
    )
    record_duplicate_groups(
        conn,
        run_id,
        "duplicate_reference_doi",
        "ref_literatures",
        """
        SELECT lower(trim(doi)) AS dedupe_key,
               group_concat(reference_id) AS record_ids,
               group_concat(DISTINCT COALESCE(title, '')) AS conflict_fields,
               COUNT(*) AS n
        FROM ref_literatures
        WHERE doi IS NOT NULL AND trim(doi) <> ''
        GROUP BY lower(trim(doi))
        HAVING COUNT(*) > 1
        ORDER BY n DESC, dedupe_key
        """,
        "P1",
        "Consolidate duplicated DOI rows and preserve alias/reference links.",
    )
    record_duplicate_groups(
        conn,
        run_id,
        "duplicate_reference_title_year",
        "ref_literatures",
        """
        SELECT lower(trim(title)) || '|' || trim(year) AS dedupe_key,
               group_concat(reference_id) AS record_ids,
               group_concat(DISTINCT COALESCE(doi, '')) AS conflict_fields,
               COUNT(*) AS n
        FROM ref_literatures
        WHERE title IS NOT NULL AND trim(title) <> ''
          AND year IS NOT NULL AND trim(year) <> ''
        GROUP BY lower(trim(title)), trim(year)
        HAVING COUNT(*) > 1
        ORDER BY n DESC
        """,
        "P1",
        "Review same-title same-year references and merge exact duplicates.",
    )
    record_duplicate_groups(
        conn,
        run_id,
        "duplicate_evidence_record",
        "evidence_records",
        """
        SELECT COALESCE(evidence_type, '') || '|' ||
               COALESCE(virus_master_id, '') || '|' ||
               COALESCE(host_id, '') || '|' ||
               COALESCE(isolate_id, '') || '|' ||
               COALESCE(reference_id, '') || '|' ||
               lower(trim(COALESCE(claim, ''))) || '|' ||
               lower(trim(COALESCE(value_text, ''))) || '|' ||
               COALESCE(unit, '') AS dedupe_key,
               group_concat(evidence_id) AS record_ids,
               group_concat(DISTINCT COALESCE(curation_status, '')) AS conflict_fields,
               COUNT(*) AS n
        FROM evidence_records
        GROUP BY dedupe_key
        HAVING COUNT(*) > 1
        ORDER BY n DESC
        """,
        "P1",
        "Collapse exact evidence duplicates or mark one canonical row per evidence claim.",
    )
    record_duplicate_groups(
        conn,
        run_id,
        "duplicate_ictv_mapping",
        "virus_ictv_mappings",
        """
        SELECT master_id || '|' || ictv_id AS dedupe_key,
               group_concat(mapping_id) AS record_ids,
               group_concat(DISTINCT COALESCE(match_status, '')) AS conflict_fields,
               COUNT(*) AS n
        FROM virus_ictv_mappings
        WHERE master_id IS NOT NULL AND ictv_id IS NOT NULL
        GROUP BY master_id, ictv_id
        HAVING COUNT(*) > 1
        ORDER BY n DESC
        """,
        "P2",
        "Keep one canonical ICTV mapping per local master and ICTV row.",
    )


def run_issue_rules(conn: sqlite3.Connection, run_id: int) -> None:
    # Evidence rows with neither entity links nor source links are not usable.
    total_evidence = scalar(conn, "SELECT COUNT(*) FROM evidence_records")
    no_links_count = scalar(
        conn,
        """
        SELECT COUNT(*)
        FROM evidence_records
        WHERE virus_master_id IS NULL AND host_id IS NULL AND isolate_id IS NULL
          AND reference_id IS NULL AND source_id IS NULL
          AND COALESCE(curation_status, '') <> 'rejected'
        """,
    )
    for row in conn.execute(
        """
        SELECT evidence_id, evidence_type, claim, value_text
        FROM evidence_records
        WHERE virus_master_id IS NULL AND host_id IS NULL AND isolate_id IS NULL
          AND reference_id IS NULL AND source_id IS NULL
          AND COALESCE(curation_status, '') <> 'rejected'
        ORDER BY evidence_id
        LIMIT ?
        """,
        (DETAIL_LIMIT,),
    ):
        add_issue(
            conn,
            run_id,
            "evidence_without_entity_or_source",
            "P0",
            "evidence_records",
            row["evidence_id"],
            "evidence",
            row["evidence_id"],
            "virus_master_id,host_id,isolate_id,reference_id,source_id",
            row["evidence_type"],
            "At least one entity link and one source/reference link should be present.",
            "Quarantine from analysis views until linked or rejected.",
            evidence_id=row["evidence_id"],
        )
    add_summary(
        conn,
        run_id,
        "traceability",
        "evidence_without_entity_or_source",
        "P0",
        "evidence_records",
        no_links_count,
        no_links_count,
        "Exclude unlinked evidence rows from claims until linked to a virus/host/isolate and source.",
        total_evidence,
    )

    # Candidate evidence claims that look like URLs, supplementary table snippets,
    # or pasted full text. Broad source phrases such as "Abstract mentions" are
    # tracked separately as weak evidence, not as text pollution.
    pollution_count = scalar(
        conn,
        f"SELECT COUNT(*) FROM evidence_records WHERE claim IS NOT NULL AND {CLAIM_POLLUTION_SQL}",
    )
    for row in conn.execute(
        f"""
        SELECT evidence_id, virus_master_id, host_id, isolate_id, reference_id, claim
        FROM evidence_records
        WHERE claim IS NOT NULL AND {CLAIM_POLLUTION_SQL}
        ORDER BY evidence_id
        LIMIT ?
        """,
        (DETAIL_LIMIT,),
    ):
        observed = (row["claim"] or "")[:250]
        add_issue(
            conn,
            run_id,
            "evidence_claim_text_pollution",
            "P1",
            "evidence_records",
            row["evidence_id"],
            "evidence",
            row["evidence_id"],
            "claim",
            observed,
            "Claim should be a concise single assertion, not a reference list, URL, table, or pasted abstract.",
            "Re-extract a concise claim or demote to literature_candidate_needs_review.",
            virus_master_id=row["virus_master_id"],
            host_id=row["host_id"],
            isolate_id=row["isolate_id"],
            reference_id=row["reference_id"],
            evidence_id=row["evidence_id"],
        )
    add_summary(
        conn,
        run_id,
        "evidence",
        "evidence_claim_text_pollution",
        "P1",
        "evidence_records",
        pollution_count,
        pollution_count,
        "Prioritize polluted claims before using evidence_records for narrative claims.",
        total_evidence,
    )

    weak_abstract_count = scalar(
        conn,
        """
        SELECT COUNT(*)
        FROM evidence_records
        WHERE claim LIKE 'Abstract mentions %'
           OR claim LIKE 'Auto-extracted from abstract:%'
        """,
    )
    add_summary(
        conn,
        run_id,
        "evidence",
        "abstract_mention_weak_evidence",
        "P2",
        "evidence_records",
        weak_abstract_count,
        weak_abstract_count,
        "Treat abstract-mention evidence as weak/candidate evidence unless manually converted to a specific claim.",
        total_evidence,
    )

    # Host scope conflicts.
    host_total = scalar(conn, "SELECT COUNT(*) FROM crustacean_hosts")
    mollusk_conflict = scalar(
        conn,
        """
        SELECT COUNT(*)
        FROM crustacean_hosts
        WHERE host_scope_status = 'target_mollusk'
          AND COALESCE(phylum, '') <> 'Mollusca'
        """,
    )
    for row in conn.execute(
        """
        SELECT host_id, scientific_name, phylum, class, host_scope_status
        FROM crustacean_hosts
        WHERE host_scope_status = 'target_mollusk'
          AND COALESCE(phylum, '') <> 'Mollusca'
        ORDER BY host_id
        LIMIT ?
        """,
        (DETAIL_LIMIT,),
    ):
        add_issue(
            conn,
            run_id,
            "host_scope_phylum_conflict",
            "P0",
            "crustacean_hosts",
            row["host_id"],
            "host",
            row["host_id"],
            "host_scope_status,phylum",
            f"{row['host_scope_status']}|{row['phylum']}",
            "target_mollusk requires phylum=Mollusca.",
            "Correct host_scope_status or host taxonomy before public release.",
            host_id=row["host_id"],
        )
    add_summary(
        conn,
        run_id,
        "taxonomy",
        "host_scope_phylum_conflict",
        "P0",
        "crustacean_hosts",
        mollusk_conflict,
        mollusk_conflict,
        "Fix public target-host classification conflicts.",
        host_total,
    )

    excluded_public = scalar(
        conn,
        """
        SELECT COUNT(*)
        FROM crustacean_hosts
        WHERE COALESCE(host_scope_status, '') LIKE 'excluded%'
          AND COALESCE(public_visibility, 'public') = 'public'
        """,
    )
    for row in conn.execute(
        """
        SELECT host_id, scientific_name, phylum, host_scope_status, public_visibility
        FROM crustacean_hosts
        WHERE COALESCE(host_scope_status, '') LIKE 'excluded%'
          AND COALESCE(public_visibility, 'public') = 'public'
        ORDER BY host_id
        LIMIT ?
        """,
        (DETAIL_LIMIT,),
    ):
        add_issue(
            conn,
            run_id,
            "excluded_host_public_visibility",
            "P0",
            "crustacean_hosts",
            row["host_id"],
            "host",
            row["host_id"],
            "public_visibility",
            row["public_visibility"],
            "Excluded hosts should not be public target hosts.",
            "Set public_visibility to hidden/restricted or correct scope.",
            host_id=row["host_id"],
        )
    add_summary(
        conn,
        run_id,
        "scope",
        "excluded_host_public_visibility",
        "P0",
        "crustacean_hosts",
        excluded_public,
        excluded_public,
        "Hide excluded hosts from public target-host views unless manually justified.",
        host_total,
    )

    alias_conflicts = conn.execute(
        """
        SELECT lower(trim(alias)) AS alias_key,
               group_concat(DISTINCT host_id) AS host_ids,
               COUNT(DISTINCT host_id) AS n
        FROM host_aliases
        WHERE alias IS NOT NULL AND trim(alias) <> ''
        GROUP BY lower(trim(alias))
        HAVING COUNT(DISTINCT host_id) > 1
        ORDER BY n DESC, alias_key
        """
    ).fetchall()
    for row in alias_conflicts:
        conn.execute(
            """
            INSERT INTO qaqc_conflicts(
                run_id, conflict_type, entity_type, entity_id, field_name,
                value_a, source_a, value_b, source_b, resolution_status
            )
            VALUES (?, 'host_alias_multi_mapping', 'host_alias', NULL, 'alias',
                    ?, 'host_aliases.alias', ?, 'host_aliases.host_id', 'open')
            """,
            (run_id, row["alias_key"], row["host_ids"]),
        )
    add_summary(
        conn,
        run_id,
        "taxonomy",
        "host_alias_multi_mapping",
        "P1",
        "host_aliases",
        len(alias_conflicts),
        sum(int(r["n"]) for r in alias_conflicts),
        "Mark ambiguous aliases or resolve them to a single preferred host.",
    )

    # Fulltext status conflicts.
    if table_exists(conn, "literature_fulltext_sources"):
        total_fulltext = scalar(conn, "SELECT COUNT(*) FROM literature_fulltext_sources")
        downloaded_no_path = scalar(
            conn,
            """
            SELECT COUNT(*)
            FROM literature_fulltext_sources
            WHERE status = 'downloaded'
              AND COALESCE(local_path, '') = ''
              AND COALESCE(pdf_url, '') = ''
              AND COALESCE(xml_url, '') = ''
              AND COALESCE(fulltext_url, '') = ''
            """,
        )
        for row in conn.execute(
            """
            SELECT fulltext_id, reference_id, pmid, doi, status, oa_status
            FROM literature_fulltext_sources
            WHERE status = 'downloaded'
              AND COALESCE(local_path, '') = ''
              AND COALESCE(pdf_url, '') = ''
              AND COALESCE(xml_url, '') = ''
              AND COALESCE(fulltext_url, '') = ''
            ORDER BY fulltext_id
            LIMIT ?
            """,
            (DETAIL_LIMIT,),
        ):
            add_issue(
                conn,
                run_id,
                "downloaded_fulltext_without_locator",
                "P1",
                "literature_fulltext_sources",
                row["fulltext_id"],
                "fulltext",
                row["fulltext_id"],
                "local_path,pdf_url,xml_url,fulltext_url",
                f"status={row['status']}; oa_status={row['oa_status']}",
                "Downloaded full text must have a local path or retrievable URL.",
                "Re-audit fulltext asset or mark status as missing/failed.",
                reference_id=row["reference_id"],
            )
        add_summary(
            conn,
            run_id,
            "fulltext",
            "downloaded_fulltext_without_locator",
            "P1",
            "literature_fulltext_sources",
            downloaded_no_path,
            downloaded_no_path,
            "Fix downloaded fulltext records without a retrievable asset locator.",
            total_fulltext,
        )

    if table_exists(conn, "literature_fulltext_sections"):
        total_sections = scalar(conn, "SELECT COUNT(*) FROM literature_fulltext_sections")
        char_mismatch = scalar(
            conn,
            """
            SELECT COUNT(*)
            FROM literature_fulltext_sections
            WHERE text IS NOT NULL
              AND char_count IS NOT NULL
              AND ABS(char_count - LENGTH(text)) > 20
            """,
        )
        add_summary(
            conn,
            run_id,
            "fulltext",
            "fulltext_section_char_count_mismatch",
            "P2",
            "literature_fulltext_sections",
            char_mismatch,
            char_mismatch,
            "Refresh fulltext section char_count values or re-extract malformed sections.",
            total_sections,
        )

    # Numeric consistency.
    if table_exists(conn, "pathogenicity_evidence"):
        path_total = scalar(conn, "SELECT COUNT(*) FROM pathogenicity_evidence")
        mortality_conflict = scalar(
            conn,
            """
            SELECT COUNT(*)
            FROM pathogenicity_evidence
            WHERE mortality_rate_min IS NOT NULL
              AND mortality_rate_max IS NOT NULL
              AND mortality_rate_min > mortality_rate_max
            """,
        )
        for row in conn.execute(
            """
            SELECT pathogenicity_id, virus_master_id, host_id, isolate_id, reference_id,
                   mortality_rate_min, mortality_rate_max
            FROM pathogenicity_evidence
            WHERE mortality_rate_min IS NOT NULL
              AND mortality_rate_max IS NOT NULL
              AND mortality_rate_min > mortality_rate_max
            LIMIT ?
            """,
            (DETAIL_LIMIT,),
        ):
            add_issue(
                conn,
                run_id,
                "mortality_min_greater_than_max",
                "P0",
                "pathogenicity_evidence",
                row["pathogenicity_id"],
                "pathogenicity",
                row["pathogenicity_id"],
                "mortality_rate_min,mortality_rate_max",
                f"{row['mortality_rate_min']}|{row['mortality_rate_max']}",
                "mortality_rate_min must be <= mortality_rate_max.",
                "Swap values only after checking the source text; otherwise mark needs_review.",
                virus_master_id=row["virus_master_id"],
                host_id=row["host_id"],
                isolate_id=row["isolate_id"],
                reference_id=row["reference_id"],
            )
        add_summary(
            conn,
            run_id,
            "numeric",
            "mortality_min_greater_than_max",
            "P0",
            "pathogenicity_evidence",
            mortality_conflict,
            mortality_conflict,
            "Correct impossible mortality ranges after source verification.",
            path_total,
        )


def run_coverage_rules(conn: sqlite3.Connection, run_id: int) -> None:
    isolate_total = scalar(conn, "SELECT COUNT(*) FROM viral_isolates")
    missing_ref = scalar(
        conn,
        """
        SELECT COUNT(*)
        FROM viral_isolates vi
        WHERE vi.reference_id IS NULL
          AND NOT EXISTS (
              SELECT 1 FROM isolate_reference_links irl
              WHERE irl.isolate_id = vi.isolate_id
          )
        """,
    )
    add_summary(
        conn,
        run_id,
        "coverage",
        "isolate_without_effective_reference",
        "P2",
        "viral_isolates",
        missing_ref,
        missing_ref,
        "Attach a primary reference or linked literature before treating isolates as literature supported.",
        isolate_total,
    )

    missing_taxon_family = scalar(
        conn,
        "SELECT COUNT(*) FROM viral_isolates WHERE taxon_family IS NULL OR trim(taxon_family) = ''",
    )
    add_summary(
        conn,
        run_id,
        "coverage",
        "isolate_missing_taxon_family",
        "P2",
        "viral_isolates",
        missing_taxon_family,
        missing_taxon_family,
        "Backfill isolate family from virus_master, ICTV, VMR, or NCBI with source labels.",
        isolate_total,
    )

    if table_exists(conn, "sample_collections"):
        sample_total = scalar(conn, "SELECT COUNT(*) FROM sample_collections")
        date_non_iso = scalar(
            conn,
            """
            SELECT COUNT(*)
            FROM sample_collections
            WHERE collection_date IS NOT NULL
              AND trim(collection_date) <> ''
              AND collection_date NOT GLOB '[0-9][0-9][0-9][0-9]'
              AND collection_date NOT GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]'
              AND collection_date NOT GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'
            """,
        )
        add_summary(
            conn,
            run_id,
            "temporal",
            "sample_collection_date_non_iso",
            "P2",
            "sample_collections",
            date_non_iso,
            date_non_iso,
            "Normalize sampling dates to YYYY, YYYY-MM, or YYYY-MM-DD and retain precision.",
            sample_total,
        )

    protein_total = scalar(conn, "SELECT COUNT(*) FROM viral_proteins")
    unknown_function = scalar(
        conn,
        """
        SELECT COUNT(*)
        FROM viral_proteins
        WHERE functional_category IS NULL
           OR trim(functional_category) = ''
           OR lower(functional_category) IN ('unknown', 'hypothetical', 'unannotated')
        """,
    )
    add_summary(
        conn,
        run_id,
        "coverage",
        "protein_missing_functional_category",
        "P3",
        "viral_proteins",
        unknown_function,
        unknown_function,
        "Prioritize RdRP, structural, and replication proteins for second-pass annotation.",
        protein_total,
    )


def grade_from_scores(
    completeness: int,
    traceability: int,
    consistency: int,
    evidence: int,
    penalty: int,
    blocking: int,
) -> str:
    total = completeness + traceability + consistency + evidence - penalty
    if blocking > 0 or penalty >= 40:
        return "D"
    if total >= 85 and traceability >= 20 and consistency >= 25:
        return "A"
    if total >= 65 and traceability >= 10:
        return "B"
    if total >= 40:
        return "C"
    return "D"


def score_viruses(conn: sqlite3.Connection, run_id: int) -> None:
    rows = conn.execute(
        """
        SELECT vm.master_id, vm.canonical_name, vm.virus_family, vm.virus_genus,
               vm.genome_type, vm.host_phylum, vm.entry_type, vm.public_visibility,
               COALESCE(vsa.scope_class, '') AS scope_class,
               COALESCE(vsa.evidence_tier, '') AS evidence_tier,
               (SELECT COUNT(*) FROM viral_isolates vi WHERE vi.master_id = vm.master_id) AS isolate_count,
               (SELECT COUNT(*) FROM evidence_records er WHERE er.virus_master_id = vm.master_id) AS evidence_count,
               (SELECT COUNT(*) FROM virus_ictv_mappings vim WHERE vim.master_id = vm.master_id) AS ictv_mapping_count
        FROM virus_master vm
        LEFT JOIN virus_scope_assessment vsa ON vsa.master_id = vm.master_id
        ORDER BY vm.master_id
        """
    ).fetchall()
    for row in rows:
        reasons: list[str] = []
        completeness = 0
        completeness += 10 if row["canonical_name"] else 0
        completeness += 8 if row["virus_family"] else 0
        completeness += 6 if row["virus_genus"] else 0
        completeness += 6 if row["genome_type"] else 0
        completeness += 10 if row["host_phylum"] in TARGET_HOST_PHYLA else 0
        completeness += 10 if int(row["isolate_count"]) > 0 else 0

        traceability = 0
        traceability += 10 if int(row["evidence_count"]) > 0 else 0
        traceability += 10 if int(row["ictv_mapping_count"]) > 0 else 0
        traceability += 10 if row["evidence_tier"] in {"strong", "moderate"} else 0

        consistency = 30
        blocking = 0
        penalty = 0
        if row["entry_type"] in {"non_target", "host_genome"}:
            penalty += 35
            reasons.append(f"entry_type={row['entry_type']}")
        if row["scope_class"] in {"excluded_or_contaminant_candidate", "non_target_or_uncertain"}:
            penalty += 20
            reasons.append(f"scope_class={row['scope_class']}")
        if int(row["isolate_count"]) == 0:
            blocking += 1
            reasons.append("no_isolates")

        evidence = 20 if row["evidence_tier"] == "strong" else 15 if row["evidence_tier"] == "moderate" else 5
        grade = grade_from_scores(completeness, traceability, consistency, evidence, penalty, blocking)
        conn.execute(
            """
            INSERT INTO entity_quality_scores(
                run_id, entity_type, entity_id, virus_master_id, completeness_score,
                traceability_score, consistency_score, evidence_score,
                artifact_penalty, blocking_issue_count, quality_grade, reasons
            )
            VALUES (?, 'virus_master', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                row["master_id"],
                row["master_id"],
                completeness,
                traceability,
                consistency,
                evidence,
                penalty,
                blocking,
                grade,
                "; ".join(reasons),
            ),
        )


def score_isolates(conn: sqlite3.Connection, run_id: int) -> None:
    rows = conn.execute(
        """
        SELECT vi.isolate_id, vi.master_id, vi.accession, vi.reference_id,
               vi.sequence_length, vi.genome_length, vi.taxon_family,
               vi.taxon_genus, vi.taxon_species, vi.has_sequence,
               vi.sequence_scope_status, vi.completeness,
               EXISTS (
                   SELECT 1 FROM isolate_reference_links irl
                   WHERE irl.isolate_id = vi.isolate_id
               ) AS has_linked_reference,
               EXISTS (
                   SELECT 1 FROM infection_records ir
                   WHERE ir.isolate_id = vi.isolate_id
               ) AS has_host_record
        FROM viral_isolates vi
        ORDER BY vi.isolate_id
        """
    ).fetchall()
    for row in rows:
        reasons: list[str] = []
        completeness = 0
        completeness += 10 if row["accession"] else 0
        completeness += 8 if row["master_id"] else 0
        completeness += 6 if row["taxon_family"] else 0
        completeness += 4 if row["taxon_genus"] else 0
        completeness += 4 if row["taxon_species"] else 0
        completeness += 8 if row["sequence_length"] or row["genome_length"] else 0
        completeness += 10 if row["has_host_record"] else 0

        traceability = 25 if row["reference_id"] or row["has_linked_reference"] else 0
        consistency = 30
        evidence = 15 if row["has_host_record"] else 5
        penalty = 0
        blocking = 0

        if row["sequence_scope_status"] in {
            "host_genome_artifact",
            "transcript_or_est_artifact",
            "short_fragment_not_complete_genome",
        }:
            penalty += 35
            reasons.append(f"sequence_scope_status={row['sequence_scope_status']}")
        if not (row["reference_id"] or row["has_linked_reference"]):
            reasons.append("missing_effective_reference")
        if not row["accession"]:
            blocking += 1
            reasons.append("missing_accession")

        grade = grade_from_scores(completeness, traceability, consistency, evidence, penalty, blocking)
        conn.execute(
            """
            INSERT INTO entity_quality_scores(
                run_id, entity_type, entity_id, virus_master_id, isolate_id,
                reference_id, completeness_score, traceability_score,
                consistency_score, evidence_score, artifact_penalty,
                blocking_issue_count, quality_grade, reasons
            )
            VALUES (?, 'viral_isolate', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                row["isolate_id"],
                row["master_id"],
                row["isolate_id"],
                row["reference_id"],
                completeness,
                traceability,
                consistency,
                evidence,
                penalty,
                blocking,
                grade,
                "; ".join(reasons),
            ),
        )


def score_hosts(conn: sqlite3.Connection, run_id: int) -> None:
    rows = conn.execute(
        """
        SELECT host_id, scientific_name, phylum, class, taxon_order, taxon_family,
               host_scope_status, public_visibility
        FROM crustacean_hosts
        ORDER BY host_id
        """
    ).fetchall()
    for row in rows:
        reasons: list[str] = []
        completeness = 0
        completeness += 15 if row["scientific_name"] else 0
        completeness += 10 if row["phylum"] else 0
        completeness += 8 if row["class"] else 0
        completeness += 6 if row["taxon_order"] else 0
        completeness += 6 if row["taxon_family"] else 0
        completeness += 5 if row["host_scope_status"] else 0
        traceability = 15
        consistency = 30
        evidence = 15
        penalty = 0
        blocking = 0

        if row["host_scope_status"] == "target_mollusk" and row["phylum"] != "Mollusca":
            penalty += 45
            blocking += 1
            reasons.append("target_mollusk_phylum_conflict")
        if (row["host_scope_status"] or "").startswith("excluded") and (row["public_visibility"] or "public") == "public":
            penalty += 35
            blocking += 1
            reasons.append("excluded_host_public")
        if row["phylum"] and row["phylum"] not in TARGET_HOST_PHYLA:
            penalty += 15
            reasons.append(f"non_target_phylum={row['phylum']}")

        grade = grade_from_scores(completeness, traceability, consistency, evidence, penalty, blocking)
        conn.execute(
            """
            INSERT INTO entity_quality_scores(
                run_id, entity_type, entity_id, host_id, completeness_score,
                traceability_score, consistency_score, evidence_score,
                artifact_penalty, blocking_issue_count, quality_grade, reasons
            )
            VALUES (?, 'host', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                row["host_id"],
                row["host_id"],
                completeness,
                traceability,
                consistency,
                evidence,
                penalty,
                blocking,
                grade,
                "; ".join(reasons),
            ),
        )


def refresh_scores(conn: sqlite3.Connection, run_id: int) -> None:
    score_viruses(conn, run_id)
    score_isolates(conn, run_id)
    score_hosts(conn, run_id)


def export_reports(conn: sqlite3.Connection, run_id: int) -> dict[str, str]:
    out_dir = REPORTS_DIR / f"qaqc_hardening_{run_id}_{stamp()}"
    out_dir.mkdir(parents=True, exist_ok=True)

    artifacts = {
        "summary_csv": str(out_dir / "qaqc_summary.csv"),
        "issues_csv": str(out_dir / "qaqc_issues_sample.csv"),
        "duplicates_csv": str(out_dir / "qaqc_duplicates.csv"),
        "conflicts_csv": str(out_dir / "qaqc_conflicts.csv"),
        "entity_scores_csv": str(out_dir / "entity_quality_scores_summary.csv"),
        "report_md": str(out_dir / "qaqc_report.md"),
        "report_json": str(out_dir / "qaqc_report.json"),
    }

    summary = conn.execute(
        """
        SELECT rule_group, rule_id, severity, table_name, issue_count,
               affected_entity_count, pass_rate, recommendation
        FROM qaqc_summary
        WHERE run_id = ?
        ORDER BY CASE severity
            WHEN 'P0' THEN 0 WHEN 'P1' THEN 1 WHEN 'P2' THEN 2 WHEN 'P3' THEN 3 ELSE 4 END,
            issue_count DESC, rule_id
        """,
        (run_id,),
    ).fetchall()
    write_csv(Path(artifacts["summary_csv"]), summary)

    issues = conn.execute(
        """
        SELECT rule_id, severity, table_name, primary_key, entity_type, entity_id,
               field_name, observed_value, expected_rule, action_hint
        FROM qaqc_issues
        WHERE run_id = ?
        ORDER BY CASE severity
            WHEN 'P0' THEN 0 WHEN 'P1' THEN 1 WHEN 'P2' THEN 2 WHEN 'P3' THEN 3 ELSE 4 END,
            rule_id, CAST(primary_key AS INTEGER)
        LIMIT 20000
        """,
        (run_id,),
    ).fetchall()
    write_csv(Path(artifacts["issues_csv"]), issues)

    duplicates = conn.execute(
        """
        SELECT duplicate_type, severity, table_name, dedupe_key, record_ids,
               canonical_candidate_id, conflict_fields, duplicate_count
        FROM qaqc_duplicates
        WHERE run_id = ?
        ORDER BY CASE severity
            WHEN 'P0' THEN 0 WHEN 'P1' THEN 1 WHEN 'P2' THEN 2 WHEN 'P3' THEN 3 ELSE 4 END,
            duplicate_count DESC
        """,
        (run_id,),
    ).fetchall()
    write_csv(Path(artifacts["duplicates_csv"]), duplicates)

    conflicts = conn.execute(
        """
        SELECT conflict_type, entity_type, entity_id, field_name, value_a,
               source_a, value_b, source_b, resolution_status
        FROM qaqc_conflicts
        WHERE run_id = ?
        ORDER BY conflict_type, value_a
        """,
        (run_id,),
    ).fetchall()
    write_csv(Path(artifacts["conflicts_csv"]), conflicts)

    score_summary = conn.execute(
        """
        SELECT entity_type, quality_grade, COUNT(*) AS n,
               ROUND(AVG(completeness_score), 2) AS avg_completeness,
               ROUND(AVG(traceability_score), 2) AS avg_traceability,
               ROUND(AVG(consistency_score), 2) AS avg_consistency,
               ROUND(AVG(evidence_score), 2) AS avg_evidence,
               ROUND(AVG(artifact_penalty), 2) AS avg_penalty
        FROM entity_quality_scores
        WHERE run_id = ?
        GROUP BY entity_type, quality_grade
        ORDER BY entity_type, quality_grade
        """,
        (run_id,),
    ).fetchall()
    write_csv(Path(artifacts["entity_scores_csv"]), score_summary)

    severity_counts = {
        row["severity"]: row["n"]
        for row in conn.execute(
            """
            SELECT severity, SUM(issue_count) AS n
            FROM qaqc_summary
            WHERE run_id = ?
            GROUP BY severity
            """,
            (run_id,),
        )
    }
    report = {
        "run_id": run_id,
        "run_ts": conn.execute("SELECT run_ts FROM qaqc_runs WHERE run_id=?", (run_id,)).fetchone()[0],
        "severity_counts": severity_counts,
        "summary_rows": [dict(r) for r in summary],
        "entity_quality_distribution": [dict(r) for r in score_summary],
        "artifacts": artifacts,
    }
    Path(artifacts["report_json"]).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        f"# QA/QC Hardening Report",
        "",
        f"- Run ID: `{run_id}`",
        f"- Generated: `{report['run_ts']}`",
        f"- P0 issues: `{severity_counts.get('P0', 0)}`",
        f"- P1 issues: `{severity_counts.get('P1', 0)}`",
        f"- P2 issues: `{severity_counts.get('P2', 0)}`",
        f"- P3 issues: `{severity_counts.get('P3', 0)}`",
        "",
        "## Highest Priority Rules",
        "",
    ]
    for row in summary[:15]:
        lines.append(
            f"- **{row['severity']}** `{row['rule_id']}` on `{row['table_name']}`: "
            f"{row['issue_count']} issues. {row['recommendation']}"
        )
    lines.extend(["", "## Entity Quality Distribution", ""])
    for row in score_summary:
        lines.append(f"- `{row['entity_type']}` grade `{row['quality_grade']}`: {row['n']}")
    lines.extend(["", "## Artifacts", ""])
    for key, value in artifacts.items():
        lines.append(f"- {key}: `{value}`")
    Path(artifacts["report_md"]).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return artifacts


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=str(DB_PATH))
    args = parser.parse_args()

    db_path = Path(args.db)
    conn = connect(db_path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        create_schema(conn)
        run_id = start_run(conn, db_path)
        run_duplicate_rules(conn, run_id)
        run_issue_rules(conn, run_id)
        run_coverage_rules(conn, run_id)
        refresh_scores(conn, run_id)
        artifacts = export_reports(conn, run_id)
        conn.commit()
        result = {
            "run_id": run_id,
            "integrity_check": conn.execute("PRAGMA integrity_check").fetchone()[0],
            "foreign_key_violations": len(conn.execute("PRAGMA foreign_key_check").fetchall()),
            "artifacts": artifacts,
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
