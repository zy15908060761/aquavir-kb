#!/usr/bin/env python3
"""Automatic, auditable completeness optimizations for the crustacean virus DB.

This script intentionally avoids expert curation decisions. It performs only:
- safe schema additions (indexes, analysis views, worklist tables)
- conservative derived-field fills
- obvious host-scope overrides from already curated host_type values
- CSV/Markdown reports for remaining manual review
"""

from __future__ import annotations

import csv
import json
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any


DB_PATH = Path("crustacean_virus_core.db")
REPORTS_DIR = Path("reports")


def stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def rows(conn: sqlite3.Connection, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def value(conn: sqlite3.Connection, sql: str, params: tuple[Any, ...] = ()) -> Any:
    row = conn.execute(sql, params).fetchone()
    return None if row is None else row[0]


def table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return bool(value(conn, "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)))


def view_exists(conn: sqlite3.Connection, view: str) -> bool:
    return bool(value(conn, "SELECT 1 FROM sqlite_master WHERE type='view' AND name=?", (view,)))


def table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    if not table_exists(conn, table):
        return set()
    return {r["name"] for r in conn.execute(f'PRAGMA table_info("{table}")')}


def write_csv(path: Path, data: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not data:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(data[0].keys()))
        writer.writeheader()
        writer.writerows(data)


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def exec_if_columns(conn: sqlite3.Connection, sql: str, table: str, required_cols: list[str]) -> bool:
    cols = table_columns(conn, table)
    if not all(c in cols for c in required_cols):
        return False
    conn.execute(sql)
    return True


def extract_year(text: Any) -> str | None:
    if text is None:
        return None
    match = re.search(r"(19|20)\d{2}", str(text))
    return match.group(0) if match else None


def register_year_function(conn: sqlite3.Connection) -> None:
    conn.create_function("auto_extract_year", 1, extract_year)


def create_indexes(conn: sqlite3.Connection) -> list[str]:
    index_specs = [
        ("sample_metadata", ["isolate_id"], "idx_auto_sample_metadata_isolate"),
        ("sample_metadata", ["accession"], "idx_auto_sample_metadata_accession"),
        ("sample_metadata", ["geo_loc_name"], "idx_auto_sample_metadata_geo_loc"),
        ("sample_metadata", ["collection_date"], "idx_auto_sample_metadata_collection_date"),
        ("reannotation_stats", ["isolate_id"], "idx_auto_reannotation_stats_isolate"),
        ("biosample_links", ["isolate_id"], "idx_auto_biosample_links_isolate"),
        ("biosample_links", ["biosample_acc"], "idx_auto_biosample_links_biosample"),
        ("protein_domains", ["protein_id"], "idx_auto_protein_domains_protein"),
        ("protein_domains", ["reanno_id"], "idx_auto_protein_domains_reanno"),
        ("protein_domains", ["cluster_id"], "idx_auto_protein_domains_cluster"),
        ("protein_structures", ["protein_id"], "idx_auto_protein_structures_protein"),
        ("protein_structures", ["reanno_id"], "idx_auto_protein_structures_reanno"),
        ("kegg_protein_pathways", ["protein_id"], "idx_auto_kegg_protein_pathways_protein"),
        ("pathogenicity_evidence", ["reference_id"], "idx_auto_pathogenicity_reference"),
        ("pathogenicity_evidence", ["isolate_id"], "idx_auto_pathogenicity_isolate"),
        ("pathogenicity_evidence", ["host_id"], "idx_auto_pathogenicity_host"),
        ("diagnostic_methods", ["reference_id"], "idx_auto_diagnostic_reference"),
        ("control_management_methods", ["reference_id"], "idx_auto_control_reference"),
        ("outbreak_events", ["reference_id"], "idx_auto_outbreak_reference"),
        ("outbreak_events", ["host_id"], "idx_auto_outbreak_host"),
        ("isolate_curated_profiles", ["host_scientific_name"], "idx_auto_icp_host_name"),
        ("isolate_curated_profiles", ["accession"], "idx_auto_icp_accession"),
        ("viral_proteins", ["protein_accession"], "idx_auto_viral_proteins_accession"),
        ("viral_proteins", ["is_rdrp"], "idx_auto_viral_proteins_is_rdrp"),
    ]
    created: list[str] = []
    for table, cols, idx_name in index_specs:
        if not table_exists(conn, table):
            continue
        table_cols = table_columns(conn, table)
        if not all(c in table_cols for c in cols):
            continue
        col_expr = ", ".join(f'"{c}"' for c in cols)
        conn.execute(f'CREATE INDEX IF NOT EXISTS "{idx_name}" ON "{table}" ({col_expr})')
        created.append(idx_name)
    return created


def create_worklist_tables(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS auto_completeness_worklist (
            worklist_id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_ts TEXT NOT NULL,
            priority TEXT NOT NULL,
            entity_type TEXT NOT NULL,
            entity_id TEXT,
            accession TEXT,
            virus_master_id INTEGER,
            virus_name TEXT,
            issue_type TEXT NOT NULL,
            suggested_source TEXT,
            suggested_action TEXT,
            current_value TEXT,
            status TEXT NOT NULL DEFAULT 'open',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS auto_host_scope_worklist (
            worklist_id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_ts TEXT NOT NULL,
            host_id INTEGER,
            scientific_name TEXT,
            host_type TEXT,
            host_group TEXT,
            taxon_order TEXT,
            issue_type TEXT NOT NULL,
            suggested_scope_status TEXT,
            suggested_exclude_from_target_stats INTEGER,
            evidence TEXT,
            status TEXT NOT NULL DEFAULT 'open',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(host_id) REFERENCES crustacean_hosts(host_id)
        );

        CREATE TABLE IF NOT EXISTS auto_annotation_gap_worklist (
            worklist_id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_ts TEXT NOT NULL,
            priority TEXT NOT NULL,
            protein_id INTEGER,
            isolate_id INTEGER,
            accession TEXT,
            protein_accession TEXT,
            protein_name TEXT,
            gap_type TEXT NOT NULL,
            suggested_action TEXT,
            status TEXT NOT NULL DEFAULT 'open',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS auto_quality_metrics (
            metric_id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_ts TEXT NOT NULL,
            category TEXT NOT NULL,
            metric TEXT NOT NULL,
            numerator INTEGER,
            denominator INTEGER,
            pct REAL,
            notes TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        """
    )


def safe_backfills(conn: sqlite3.Connection) -> dict[str, int]:
    register_year_function(conn)
    changes: dict[str, int] = {}

    before = conn.total_changes
    conn.execute(
        """
        UPDATE sample_collections
        SET collection_year = auto_extract_year(collection_date)
        WHERE (collection_year IS NULL OR TRIM(collection_year) = '')
          AND auto_extract_year(collection_date) IS NOT NULL
        """
    )
    changes["sample_collections.collection_year_from_date"] = conn.total_changes - before

    before = conn.total_changes
    conn.execute(
        """
        UPDATE isolate_curated_profiles
        SET collection_year = auto_extract_year(collection_date),
            updated_at = CURRENT_TIMESTAMP
        WHERE (collection_year IS NULL OR TRIM(collection_year) = '')
          AND auto_extract_year(collection_date) IS NOT NULL
        """
    )
    changes["isolate_curated_profiles.collection_year_from_date"] = conn.total_changes - before

    before = conn.total_changes
    conn.execute(
        """
        UPDATE sample_collections
        SET coordinate_precision = CASE
            WHEN latitude IS NULL OR longitude IS NULL THEN 'unknown'
            WHEN coordinate_precision IS NULL OR TRIM(coordinate_precision) = '' THEN 'country'
            ELSE coordinate_precision
        END
        WHERE coordinate_precision IS NULL
           OR TRIM(coordinate_precision) = ''
           OR latitude IS NULL
           OR longitude IS NULL
        """
    )
    changes["sample_collections.coordinate_precision_normalized"] = conn.total_changes - before

    before = conn.total_changes
    conn.execute(
        """
        INSERT OR IGNORE INTO host_scope_overrides(host_id, scope_status, exclude_from_target_stats, reason)
        SELECT host_id,
               CASE
                   WHEN host_type = 'technical_host' THEN 'technical_host'
                   WHEN host_type = 'non_crustacean' THEN 'non_target'
                   WHEN host_type = 'not_species_level' THEN 'not_species_level'
                   WHEN host_type = 'crustacean' THEN 'target'
                   ELSE 'unknown'
               END AS scope_status,
               CASE WHEN host_type IN ('technical_host', 'non_crustacean') THEN 1 ELSE 0 END AS exclude_from_target_stats,
               'auto_optimize_completeness: derived from curated crustacean_hosts.host_type'
        FROM crustacean_hosts
        WHERE host_type IN ('technical_host', 'non_crustacean', 'not_species_level', 'crustacean')
        """
    )
    changes["host_scope_overrides_from_host_type"] = conn.total_changes - before

    before = conn.total_changes
    conn.execute(
        """
        WITH unique_uniprot_map AS (
            SELECT uniprot_id, MIN(protein_id) AS protein_id
            FROM uniprot_protein_links
            WHERE protein_id IS NOT NULL
            GROUP BY uniprot_id
            HAVING COUNT(DISTINCT protein_id) = 1
        )
        UPDATE interpro_annotations
        SET protein_id = (
            SELECT unique_uniprot_map.protein_id
            FROM unique_uniprot_map
            WHERE unique_uniprot_map.uniprot_id = interpro_annotations.uniprot_id
        )
        WHERE protein_id IS NULL
          AND uniprot_id IN (SELECT uniprot_id FROM unique_uniprot_map)
        """
    )
    changes["interpro_annotations.protein_id_from_unique_uniprot"] = conn.total_changes - before

    return changes


def create_analysis_views(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE VIEW IF NOT EXISTS analysis_strict_target_isolates AS
        SELECT v.*
        FROM viral_isolates v
        JOIN virus_master vm ON vm.master_id = v.master_id
        LEFT JOIN isolate_curated_profiles icp ON icp.isolate_id = v.isolate_id
        LEFT JOIN host_scope_overrides hso ON hso.host_id = icp.host_id
        WHERE vm.is_crustacean_virus = 1
          AND vm.entry_type NOT IN ('non_target', 'host_genome')
          AND COALESCE(icp.host_is_target, 1) = 1
          AND COALESCE(hso.exclude_from_target_stats, 0) = 0
          AND COALESCE(hso.scope_status, 'target') NOT IN ('technical_host', 'non_target');

        DROP VIEW IF EXISTS analysis_isolate_completeness;

        CREATE VIEW analysis_isolate_completeness AS
        SELECT
            vi.isolate_id,
            vi.accession,
            vi.master_id,
            vm.canonical_name,
            vi.virus_name,
            COALESCE(icp.host_id, mh.host_id) AS host_id,
            COALESCE(NULLIF(icp.host_scientific_name, ''), mh.scientific_name, sm.host_name) AS host_scientific_name,
            COALESCE(NULLIF(sc.country, ''), NULLIF(icp.country, ''), NULLIF(substr(sm.geo_loc_name, 1, instr(sm.geo_loc_name || ':', ':') - 1), '')) AS country,
            COALESCE(sc.latitude, icp.latitude) AS latitude,
            COALESCE(sc.longitude, icp.longitude) AS longitude,
            COALESCE(NULLIF(sc.collection_year, ''), NULLIF(icp.collection_year, ''), NULLIF(sm.collection_date, '')) AS collection_year,
            COALESCE(NULLIF(ir.isolation_source, ''), NULLIF(icp.sample_source, ''), NULLIF(sm.isolation_source, '')) AS isolation_source,
            vi.genome_type,
            vi.genome_length,
            vi.gc_content,
            CASE WHEN vi.reference_id IS NOT NULL OR EXISTS (
                SELECT 1 FROM isolate_reference_links irl WHERE irl.isolate_id = vi.isolate_id
            ) THEN 1 ELSE 0 END AS has_reference,
            CASE WHEN COALESCE(icp.host_id, mh.host_id) IS NOT NULL THEN 1 ELSE 0 END AS has_host,
            CASE WHEN COALESCE(NULLIF(sc.country, ''), NULLIF(icp.country, ''), NULLIF(substr(sm.geo_loc_name, 1, instr(sm.geo_loc_name || ':', ':') - 1), '')) IS NOT NULL THEN 1 ELSE 0 END AS has_country,
            CASE WHEN COALESCE(sc.latitude, icp.latitude) IS NOT NULL
                   AND COALESCE(sc.longitude, icp.longitude) IS NOT NULL THEN 1 ELSE 0 END AS has_coordinates,
            CASE WHEN COALESCE(NULLIF(sc.collection_year, ''), NULLIF(icp.collection_year, ''), NULLIF(sm.collection_date, '')) IS NOT NULL THEN 1 ELSE 0 END AS has_collection_year,
            CASE WHEN COALESCE(NULLIF(ir.isolation_source, ''), NULLIF(icp.sample_source, ''), NULLIF(sm.isolation_source, '')) IS NOT NULL THEN 1 ELSE 0 END AS has_isolation_source,
            CASE WHEN vi.genome_type IS NOT NULL AND TRIM(vi.genome_type) <> '' THEN 1 ELSE 0 END AS has_genome_type
        FROM viral_isolates vi
        JOIN virus_master vm ON vm.master_id = vi.master_id
        LEFT JOIN isolate_curated_profiles icp ON icp.isolate_id = vi.isolate_id
        LEFT JOIN sample_metadata sm ON sm.isolate_id = vi.isolate_id
        LEFT JOIN crustacean_hosts mh
          ON LOWER(mh.scientific_name) = LOWER(COALESCE(NULLIF(icp.host_scientific_name, ''), NULLIF(sm.host_name, '')))
        LEFT JOIN infection_records ir ON ir.isolate_id = vi.isolate_id
        LEFT JOIN sample_collections sc ON sc.collection_id = ir.collection_id;

        CREATE VIEW IF NOT EXISTS analysis_protein_annotation_completeness AS
        SELECT
            vp.protein_id,
            vp.isolate_id,
            vi.accession,
            vp.protein_accession,
            vp.protein_name,
            vp.aa_length,
            CASE WHEN upl.link_id IS NOT NULL THEN 1 ELSE 0 END AS has_uniprot_link,
            CASE WHEN pd.domain_id IS NOT NULL THEN 1 ELSE 0 END AS has_domain,
            CASE WHEN ig.id IS NOT NULL THEN 1 ELSE 0 END AS has_go_term,
            CASE WHEN kpp.link_id IS NOT NULL THEN 1 ELSE 0 END AS has_kegg_pathway,
            CASE WHEN ps.structure_id IS NOT NULL THEN 1 ELSE 0 END AS has_structure
        FROM viral_proteins vp
        JOIN viral_isolates vi ON vi.isolate_id = vp.isolate_id
        LEFT JOIN uniprot_protein_links upl ON upl.protein_id = vp.protein_id
        LEFT JOIN protein_domains pd ON pd.protein_id = vp.protein_id
        LEFT JOIN interpro_go_terms ig ON ig.protein_id = vp.protein_id
        LEFT JOIN kegg_protein_pathways kpp ON kpp.protein_id = vp.protein_id
        LEFT JOIN protein_structures ps ON ps.protein_id = vp.protein_id
        GROUP BY vp.protein_id;
        """
    )


def refresh_worklists(conn: sqlite3.Connection, run_ts: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for table in [
        "auto_completeness_worklist",
        "auto_host_scope_worklist",
        "auto_annotation_gap_worklist",
        "auto_quality_metrics",
    ]:
        conn.execute(f"DELETE FROM {table}")

    def insert_count(name: str, sql: str, params: tuple[Any, ...] = ()) -> None:
        before = conn.total_changes
        conn.execute(sql, params)
        counts[name] = conn.total_changes - before

    gap_specs = [
        ("P1", "isolate", "missing_host", "GenBank BioSample/source + primary literature", "Resolve host_id and host_scientific_name"),
        ("P1", "isolate", "missing_country", "GenBank source geo_loc_name + literature", "Fill standardized country or keep explicit unknown"),
        ("P1", "isolate", "missing_coordinates", "GenBank lat_lon, GBIF/OBIS, or country/province centroid", "Fill coordinates_source and location_precision before map use"),
        ("P1", "isolate", "missing_isolation_source", "GenBank isolation_source + source feature + literature", "Fill tissue/sample/isolation source"),
        ("P2", "isolate", "missing_collection_year", "GenBank collection_date + literature", "Recover collection year/date"),
        ("P2", "isolate", "missing_genome_type", "ICTV/NCBI taxonomy + GenBank molecule type", "Standardize genome type"),
        ("P1", "isolate", "missing_effective_reference", "GenBank reference + PubMed/Europe PMC", "Attach primary reference or linked literature"),
    ]
    predicates = {
        "missing_host": "has_host = 0",
        "missing_country": "has_country = 0",
        "missing_coordinates": "has_coordinates = 0",
        "missing_isolation_source": "has_isolation_source = 0",
        "missing_collection_year": "has_collection_year = 0",
        "missing_genome_type": "has_genome_type = 0",
        "missing_effective_reference": "has_reference = 0",
    }
    for priority, entity_type, issue, source, action in gap_specs:
        insert_count(
            f"worklist_{issue}",
            f"""
            INSERT INTO auto_completeness_worklist(
                run_ts, priority, entity_type, entity_id, accession, virus_master_id,
                virus_name, issue_type, suggested_source, suggested_action, current_value
            )
            SELECT ?, ?, ?, isolate_id, accession, master_id, canonical_name,
                   ?, ?, ?, NULL
            FROM analysis_isolate_completeness
            WHERE isolate_id IN (SELECT isolate_id FROM analysis_strict_target_isolates)
              AND {predicates[issue]}
            """,
            (run_ts, priority, entity_type, issue, source, action),
        )

    insert_count(
        "host_scope_worklist",
        """
        INSERT INTO auto_host_scope_worklist(
            run_ts, host_id, scientific_name, host_type, host_group, taxon_order,
            issue_type, suggested_scope_status, suggested_exclude_from_target_stats, evidence
        )
        SELECT ?, ch.host_id, ch.scientific_name, ch.host_type, ch.host_group, ch.taxon_order,
               CASE
                   WHEN ch.host_type IN ('technical_host', 'non_crustacean') THEN 'exclude_from_target_stats'
                   WHEN ch.host_type = 'not_species_level' THEN 'not_species_level_review'
                   WHEN ch.taxon_order IS NULL OR ch.taxon_family IS NULL THEN 'missing_taxonomy'
                   ELSE 'scope_confirmed'
               END,
               COALESCE(hso.scope_status,
                   CASE
                       WHEN ch.host_type = 'technical_host' THEN 'technical_host'
                       WHEN ch.host_type = 'non_crustacean' THEN 'non_target'
                       WHEN ch.host_type = 'not_species_level' THEN 'not_species_level'
                       WHEN ch.host_type = 'crustacean' THEN 'target'
                       ELSE 'unknown'
                   END
               ),
               COALESCE(hso.exclude_from_target_stats,
                   CASE WHEN ch.host_type IN ('technical_host', 'non_crustacean') THEN 1 ELSE 0 END
               ),
               'Derived from crustacean_hosts.host_type/taxonomy; review not_species_level and missing taxonomy rows.'
        FROM crustacean_hosts ch
        LEFT JOIN host_scope_overrides hso ON hso.host_id = ch.host_id
        WHERE ch.host_type IN ('technical_host', 'non_crustacean', 'not_species_level')
           OR ch.taxon_order IS NULL
           OR ch.taxon_family IS NULL
        """,
        (run_ts,),
    )

    insert_count(
        "protein_annotation_gap_uniprot",
        """
        INSERT INTO auto_annotation_gap_worklist(
            run_ts, priority, protein_id, isolate_id, accession, protein_accession,
            protein_name, gap_type, suggested_action
        )
        SELECT ?, 'P2', protein_id, isolate_id, accession, protein_accession,
               protein_name, 'missing_uniprot_link',
               'Map NCBI protein accession to UniProt or mark no-match with source/version.'
        FROM analysis_protein_annotation_completeness
        WHERE has_uniprot_link = 0
        """,
        (run_ts,),
    )
    insert_count(
        "protein_annotation_gap_domain",
        """
        INSERT INTO auto_annotation_gap_worklist(
            run_ts, priority, protein_id, isolate_id, accession, protein_accession,
            protein_name, gap_type, suggested_action
        )
        SELECT ?, 'P1', protein_id, isolate_id, accession, protein_accession,
               protein_name, 'missing_domain_or_interpro',
               'Run InterProScan/Pfam/CDD or link existing reannotation/cluster domain result to protein_id.'
        FROM analysis_protein_annotation_completeness
        WHERE has_domain = 0
        """,
        (run_ts,),
    )
    insert_count(
        "protein_annotation_gap_go",
        """
        INSERT INTO auto_annotation_gap_worklist(
            run_ts, priority, protein_id, isolate_id, accession, protein_accession,
            protein_name, gap_type, suggested_action
        )
        SELECT ?, 'P2', protein_id, isolate_id, accession, protein_accession,
               protein_name, 'missing_go_term',
               'Backfill GO via InterPro/UniProt and record evidence_source.'
        FROM analysis_protein_annotation_completeness
        WHERE has_go_term = 0
        """,
        (run_ts,),
    )

    evidence_sql = """
        INSERT INTO auto_completeness_worklist(
            run_ts, priority, entity_type, entity_id, accession, virus_master_id,
            virus_name, issue_type, suggested_source, suggested_action, current_value
        )
        SELECT ?, 'P0', 'evidence_record', evidence_id, NULL, virus_master_id,
               evidence_type, 'evidence_needs_manual_review',
               'Primary literature and source_text',
               'Verify support level; only then promote to manual_checked or reject.',
               COALESCE(curation_status, '') || '/' || COALESCE(evidence_strength, '')
        FROM evidence_records
        WHERE curation_status = 'needs_review'
    """
    insert_count("evidence_needs_review", evidence_sql, (run_ts,))

    diag_sql = """
        INSERT INTO auto_completeness_worklist(
            run_ts, priority, entity_type, entity_id, accession, virus_master_id,
            virus_name, issue_type, suggested_source, suggested_action, current_value
        )
        SELECT ?, 'P0', 'diagnostic_method', method_id, NULL, virus_master_id,
               method_name, 'diagnostic_method_needs_review',
               'Diagnostic method paper or WOAH/manual protocol',
               'Verify target gene, method context, detection limit, and evidence strength.',
               COALESCE(curation_status, '') || '/' || COALESCE(data_quality, '')
        FROM diagnostic_methods
        WHERE curation_status = 'needs_review'
          AND data_quality <> 'placeholder'
    """
    insert_count("diagnostic_needs_review", diag_sql, (run_ts,))

    ictv_sql = """
        INSERT INTO auto_completeness_worklist(
            run_ts, priority, entity_type, entity_id, accession, virus_master_id,
            virus_name, issue_type, suggested_source, suggested_action, current_value
        )
        SELECT ?, 'P0', 'virus_master', vm.master_id, NULL, vm.master_id,
               vm.canonical_name, 'ictv_pending_review',
               'ICTV MSL/VMR + GenBank taxonomy',
               'Resolve mapped/rejected/unclassified_not_expected and document confidence.',
               vis.ictv_status
        FROM virus_master vm
        JOIN virus_ictv_status vis ON vis.master_id = vm.master_id
        WHERE vis.ictv_status = 'pending_review'
    """
    insert_count("ictv_pending_review", ictv_sql, (run_ts,))

    orphan_sql = """
        INSERT INTO auto_completeness_worklist(
            run_ts, priority, entity_type, entity_id, accession, virus_master_id,
            virus_name, issue_type, suggested_source, suggested_action, current_value
        )
        SELECT ?, 'P0', 'virus_master', vm.master_id, NULL, vm.master_id,
               vm.canonical_name, 'target_master_without_isolate',
               'Virus master table + sequence import logs',
               'Attach isolate, merge with existing master, or demote entry_type.',
               vm.entry_type
        FROM virus_master vm
        LEFT JOIN viral_isolates vi ON vi.master_id = vm.master_id
        WHERE vi.isolate_id IS NULL
          AND vm.is_crustacean_virus = 1
          AND vm.entry_type NOT IN ('non_target', 'host_genome')
    """
    insert_count("target_master_without_isolate", orphan_sql, (run_ts,))

    return counts


def refresh_quality_metrics(conn: sqlite3.Connection, run_ts: str) -> list[dict[str, Any]]:
    metrics = [
        ("scope", "strict_target_isolates", "SELECT COUNT(*) FROM analysis_strict_target_isolates", None),
        ("scope", "virus_master_total", "SELECT COUNT(*) FROM virus_master", None),
        ("scope", "target_master_without_isolate", """
            SELECT COUNT(*)
            FROM virus_master vm
            LEFT JOIN viral_isolates vi ON vi.master_id = vm.master_id
            WHERE vi.isolate_id IS NULL
              AND vm.is_crustacean_virus = 1
              AND vm.entry_type NOT IN ('non_target', 'host_genome')
        """, "SELECT COUNT(*) FROM virus_master WHERE is_crustacean_virus = 1 AND entry_type NOT IN ('non_target', 'host_genome')"),
        ("target_isolate", "has_host", "SELECT SUM(has_host) FROM analysis_isolate_completeness WHERE isolate_id IN (SELECT isolate_id FROM analysis_strict_target_isolates)", "SELECT COUNT(*) FROM analysis_strict_target_isolates"),
        ("target_isolate", "has_country", "SELECT SUM(has_country) FROM analysis_isolate_completeness WHERE isolate_id IN (SELECT isolate_id FROM analysis_strict_target_isolates)", "SELECT COUNT(*) FROM analysis_strict_target_isolates"),
        ("target_isolate", "has_coordinates", "SELECT SUM(has_coordinates) FROM analysis_isolate_completeness WHERE isolate_id IN (SELECT isolate_id FROM analysis_strict_target_isolates)", "SELECT COUNT(*) FROM analysis_strict_target_isolates"),
        ("target_isolate", "has_collection_year", "SELECT SUM(has_collection_year) FROM analysis_isolate_completeness WHERE isolate_id IN (SELECT isolate_id FROM analysis_strict_target_isolates)", "SELECT COUNT(*) FROM analysis_strict_target_isolates"),
        ("target_isolate", "has_isolation_source", "SELECT SUM(has_isolation_source) FROM analysis_isolate_completeness WHERE isolate_id IN (SELECT isolate_id FROM analysis_strict_target_isolates)", "SELECT COUNT(*) FROM analysis_strict_target_isolates"),
        ("target_isolate", "has_genome_type", "SELECT SUM(has_genome_type) FROM analysis_isolate_completeness WHERE isolate_id IN (SELECT isolate_id FROM analysis_strict_target_isolates)", "SELECT COUNT(*) FROM analysis_strict_target_isolates"),
        ("target_isolate", "has_reference", "SELECT SUM(has_reference) FROM analysis_isolate_completeness WHERE isolate_id IN (SELECT isolate_id FROM analysis_strict_target_isolates)", "SELECT COUNT(*) FROM analysis_strict_target_isolates"),
        ("protein", "has_uniprot_link", "SELECT SUM(has_uniprot_link) FROM analysis_protein_annotation_completeness", "SELECT COUNT(*) FROM analysis_protein_annotation_completeness"),
        ("protein", "has_domain", "SELECT SUM(has_domain) FROM analysis_protein_annotation_completeness", "SELECT COUNT(*) FROM analysis_protein_annotation_completeness"),
        ("protein", "has_go_term", "SELECT SUM(has_go_term) FROM analysis_protein_annotation_completeness", "SELECT COUNT(*) FROM analysis_protein_annotation_completeness"),
        ("protein", "has_kegg_pathway", "SELECT SUM(has_kegg_pathway) FROM analysis_protein_annotation_completeness", "SELECT COUNT(*) FROM analysis_protein_annotation_completeness"),
        ("protein", "has_structure", "SELECT SUM(has_structure) FROM analysis_protein_annotation_completeness", "SELECT COUNT(*) FROM analysis_protein_annotation_completeness"),
        ("curation", "evidence_needs_review", "SELECT COUNT(*) FROM evidence_records WHERE curation_status = 'needs_review'", "SELECT COUNT(*) FROM evidence_records"),
        ("curation", "diagnostics_manual_checked_curated", "SELECT COUNT(*) FROM diagnostic_methods WHERE curation_status='manual_checked' AND data_quality='curated'", "SELECT COUNT(*) FROM diagnostic_methods WHERE data_quality <> 'placeholder'"),
        ("taxonomy", "ictv_pending_review", "SELECT COUNT(*) FROM virus_ictv_status WHERE ictv_status = 'pending_review'", "SELECT COUNT(*) FROM virus_ictv_status"),
    ]
    out: list[dict[str, Any]] = []
    for category, metric, numerator_sql, denominator_sql in metrics:
        numerator = value(conn, numerator_sql)
        denominator = value(conn, denominator_sql) if denominator_sql else None
        if numerator is None:
            numerator = 0
        pct = None
        if denominator:
            pct = float(numerator) / float(denominator)
        row = {
            "run_ts": run_ts,
            "category": category,
            "metric": metric,
            "numerator": int(numerator),
            "denominator": int(denominator) if denominator is not None else None,
            "pct": pct,
            "notes": None,
        }
        out.append(row)
        conn.execute(
            """
            INSERT INTO auto_quality_metrics(run_ts, category, metric, numerator, denominator, pct, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row["run_ts"],
                row["category"],
                row["metric"],
                row["numerator"],
                row["denominator"],
                row["pct"],
                row["notes"],
            ),
        )
    return out


def export_data_dictionary(conn: sqlite3.Connection, out_dir: Path) -> tuple[Path, Path]:
    tables = rows(
        conn,
        """
        SELECT name AS table_name, type, sql
        FROM sqlite_master
        WHERE type IN ('table', 'view')
          AND name NOT LIKE 'sqlite_%'
        ORDER BY type, name
        """,
    )
    table_rows: list[dict[str, Any]] = []
    field_rows: list[dict[str, Any]] = []
    for item in tables:
        name = item["table_name"]
        obj_type = item["type"]
        try:
            row_count = value(conn, f'SELECT COUNT(*) FROM "{name}"')
        except sqlite3.DatabaseError:
            row_count = None
        pk_cols = []
        fks = []
        if obj_type == "table":
            pk_cols = [r["name"] for r in conn.execute(f'PRAGMA table_info("{name}")') if r["pk"]]
            fks = [dict(r) for r in conn.execute(f'PRAGMA foreign_key_list("{name}")')]
        table_rows.append(
            {
                "object_name": name,
                "object_type": obj_type,
                "row_count": row_count,
                "primary_key": ";".join(pk_cols),
                "foreign_key_count": len(fks),
            }
        )
        if obj_type == "table":
            n = row_count or 0
            for col in conn.execute(f'PRAGMA table_info("{name}")'):
                col_name = col["name"]
                missing = None
                missing_pct = None
                if n:
                    try:
                        missing = value(
                            conn,
                            f'SELECT COUNT(*) FROM "{name}" WHERE "{col_name}" IS NULL OR TRIM(CAST("{col_name}" AS TEXT)) = ""',
                        )
                        missing_pct = float(missing) / float(n)
                    except sqlite3.DatabaseError:
                        missing = None
                fk_targets = [
                    f'{fk["table"]}.{fk["to"]}'
                    for fk in fks
                    if fk["from"] == col_name
                ]
                field_rows.append(
                    {
                        "table_name": name,
                        "column_name": col_name,
                        "declared_type": col["type"],
                        "not_null": col["notnull"],
                        "primary_key_position": col["pk"],
                        "default_value": col["dflt_value"],
                        "foreign_key_target": ";".join(fk_targets),
                        "missing_count": missing,
                        "missing_pct": missing_pct,
                    }
                )
    tables_path = out_dir / "data_dictionary_tables.csv"
    fields_path = out_dir / "data_dictionary_fields.csv"
    write_csv(tables_path, table_rows)
    write_csv(fields_path, field_rows)
    return tables_path, fields_path


def export_reports(conn: sqlite3.Connection, run_ts: str, summary: dict[str, Any]) -> dict[str, str]:
    out_dir = REPORTS_DIR / f"auto_optimization_{run_ts}"
    out_dir.mkdir(parents=True, exist_ok=True)

    exports = {
        "completeness_worklist": rows(conn, "SELECT * FROM auto_completeness_worklist ORDER BY priority, issue_type, virus_name LIMIT 200000"),
        "host_scope_worklist": rows(conn, "SELECT * FROM auto_host_scope_worklist ORDER BY issue_type, scientific_name"),
        "annotation_gap_worklist": rows(conn, "SELECT * FROM auto_annotation_gap_worklist ORDER BY priority, gap_type, accession LIMIT 200000"),
        "quality_metrics": rows(conn, "SELECT * FROM auto_quality_metrics WHERE run_ts=? ORDER BY category, metric", (run_ts,)),
        "host_scope_overrides": rows(conn, "SELECT hso.*, ch.scientific_name, ch.host_type FROM host_scope_overrides hso JOIN crustacean_hosts ch ON ch.host_id=hso.host_id ORDER BY hso.scope_status, ch.scientific_name"),
    }
    paths: dict[str, str] = {}
    for name, data in exports.items():
        path = out_dir / f"{name}.csv"
        write_csv(path, data)
        paths[name] = str(path)

    tables_path, fields_path = export_data_dictionary(conn, out_dir)
    paths["data_dictionary_tables"] = str(tables_path)
    paths["data_dictionary_fields"] = str(fields_path)

    summary_path = out_dir / "auto_optimization_summary.json"
    write_json(summary_path, summary)
    paths["summary_json"] = str(summary_path)

    md_lines = [
        "# Automatic Completeness Optimization Report",
        "",
        f"Generated: {datetime.now().isoformat(timespec='seconds')}",
        f"Run timestamp: `{run_ts}`",
        "",
        "## Safety",
        f"- Integrity check: `{summary['post_integrity']['integrity_check']}`",
        f"- Foreign-key violations: `{summary['post_integrity']['foreign_key_violations']}`",
        "",
        "## Changes",
    ]
    for key, val in summary["changes"].items():
        md_lines.append(f"- {key}: {val}")
    md_lines += ["", "## Created Indexes"]
    for idx in summary["created_indexes"]:
        md_lines.append(f"- `{idx}`")
    md_lines += ["", "## Worklist Counts"]
    for key, val in summary["worklist_counts"].items():
        md_lines.append(f"- {key}: {val}")
    md_lines += ["", "## Quality Metrics"]
    for m in exports["quality_metrics"]:
        pct = "" if m["pct"] is None else f" ({m['pct']:.1%})"
        denom = "" if m["denominator"] is None else f"/{m['denominator']}"
        md_lines.append(f"- {m['category']}.{m['metric']}: {m['numerator']}{denom}{pct}")
    md_lines += ["", "## Exported Files"]
    for key, path in paths.items():
        md_lines.append(f"- {key}: `{path}`")
    md_path = out_dir / "auto_optimization_report.md"
    md_path.write_text("\n".join(md_lines) + "\n", encoding="utf-8")
    paths["report_md"] = str(md_path)
    return paths


def log_maintenance(conn: sqlite3.Connection, summary: dict[str, Any]) -> None:
    conn.execute(
        """
        INSERT INTO database_maintenance_log(action, details_json)
        VALUES (?, ?)
        """,
        ("auto_optimize_completeness", json.dumps(summary, ensure_ascii=False, sort_keys=True)),
    )
    conn.execute(
        """
        INSERT INTO release_manifest(release_name, table_name, row_count, export_path, notes)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            f"auto_optimization_{summary['run_ts']}",
            "auto_quality_metrics",
            value(conn, "SELECT COUNT(*) FROM auto_quality_metrics WHERE run_ts=?", (summary["run_ts"],)),
            summary.get("report_dir"),
            "Automatic completeness optimization and worklist export.",
        ),
    )


def main() -> None:
    REPORTS_DIR.mkdir(exist_ok=True)
    run_ts = stamp()
    with connect() as conn:
        pre_integrity = {
            "integrity_check": value(conn, "PRAGMA integrity_check"),
            "foreign_key_violations": len(rows(conn, "PRAGMA foreign_key_check")),
        }
        if pre_integrity["integrity_check"] != "ok" or pre_integrity["foreign_key_violations"]:
            raise RuntimeError(f"Refusing to optimize inconsistent database: {pre_integrity}")

        create_worklist_tables(conn)
        created_indexes = create_indexes(conn)
        changes = safe_backfills(conn)
        create_analysis_views(conn)
        worklist_counts = refresh_worklists(conn, run_ts)
        metrics = refresh_quality_metrics(conn, run_ts)

        post_integrity = {
            "integrity_check": value(conn, "PRAGMA integrity_check"),
            "foreign_key_violations": len(rows(conn, "PRAGMA foreign_key_check")),
        }
        summary = {
            "run_ts": run_ts,
            "pre_integrity": pre_integrity,
            "post_integrity": post_integrity,
            "created_indexes": created_indexes,
            "changes": changes,
            "worklist_counts": worklist_counts,
            "quality_metrics": metrics,
        }
        paths = export_reports(conn, run_ts, summary)
        summary["report_dir"] = str(Path(paths["report_md"]).parent)
        log_maintenance(conn, summary)
        conn.commit()

    print(json.dumps({"run_ts": run_ts, "reports": paths, "summary": summary}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
