from __future__ import annotations

import csv
import hashlib
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any


BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "crustacean_virus_core.db"
REPORTS_DIR = BASE_DIR / "reports"


ARTIFACT_TEXT_SQL = """
LOWER(
    COALESCE(ati.virus_name, '') || ' ' ||
    COALESCE(ati.molecule_type, '') || ' ' ||
    COALESCE(ati.completeness, '') || ' ' ||
    COALESCE(nr.definition, '') || ' ' ||
    COALESCE(nr.organism, '') || ' ' ||
    COALESCE(nr.molecule_type, '') || ' ' ||
    COALESCE(nr.taxonomy_lineage, '') || ' ' ||
    COALESCE(sm.mol_type, '') || ' ' ||
    COALESCE(sm.raw_notes, '') || ' ' ||
    COALESCE(sm.organism, '')
)
"""


def scalar(conn: sqlite3.Connection, sql: str, params: tuple[Any, ...] = ()) -> Any:
    row = conn.execute(sql, params).fetchone()
    return None if row is None else row[0]


def rows(conn: sqlite3.Connection, sql: str, params: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
    return conn.execute(sql, params).fetchall()


def table_exists(conn: sqlite3.Connection, name: str) -> bool:
    return bool(scalar(conn, "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)))


def view_exists(conn: sqlite3.Connection, name: str) -> bool:
    return bool(scalar(conn, "SELECT 1 FROM sqlite_master WHERE type='view' AND name=?", (name,)))


def pct(n: int, d: int) -> float:
    return round((n / d) * 100, 2) if d else 0.0


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def write_csv(path: Path, header: list[str], data: list[dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=header, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(data)


def refresh_review_views(conn: sqlite3.Connection) -> None:
    for obj in [
        "submission_excluded_isolates_with_reasons",
        "submission_target_geography_precision",
        "submission_protein_annotation_coverage",
        "submission_manual_intervention_tasks",
        "submission_p0_release_blockers",
    ]:
        while True:
            existing = conn.execute(
                "SELECT type FROM sqlite_master WHERE name=? AND type IN ('table', 'view')",
                (obj,),
            ).fetchone()
            if not existing:
                break
            if existing[0] == "view":
                conn.execute(f"DROP VIEW {obj}")
            elif existing[0] == "table":
                conn.execute(f"DROP TABLE {obj}")
            else:
                raise RuntimeError(f"Unsupported sqlite object type for {obj}: {existing[0]}")
    conn.commit()
    conn.executescript(
        """
        CREATE VIEW submission_excluded_isolates_with_reasons AS
        SELECT
            vi.isolate_id,
            vi.accession,
            vi.virus_name,
            vi.master_id,
            vm.canonical_name,
            vm.entry_type,
            vm.is_crustacean_virus,
            icp.host_id,
            icp.host_scientific_name,
            icp.host_is_target,
            hso.scope_status,
            hso.exclude_from_target_stats,
            CASE
                WHEN vm.is_crustacean_virus <> 1 THEN 'virus_master_not_marked_crustacean'
                WHEN vm.entry_type IN ('non_target', 'host_genome') THEN 'virus_master_entry_type_excluded'
                WHEN COALESCE(icp.host_is_target, 1) <> 1 THEN 'curated_host_not_target'
                WHEN COALESCE(hso.exclude_from_target_stats, 0) <> 0 THEN 'host_scope_override_excluded'
                WHEN COALESCE(hso.scope_status, 'target') IN ('technical_host', 'non_target') THEN 'strict_scope_status_excluded'
                ELSE 'not_excluded_by_current_target_rule'
            END AS exclusion_reason,
            CASE
                WHEN vi.isolate_id IN (SELECT isolate_id FROM analysis_target_isolates) THEN 1 ELSE 0
            END AS in_analysis_target,
            CASE
                WHEN vi.isolate_id IN (SELECT isolate_id FROM analysis_strict_target_isolates) THEN 1 ELSE 0
            END AS in_strict_target
        FROM viral_isolates vi
        JOIN virus_master vm ON vm.master_id = vi.master_id
        LEFT JOIN isolate_curated_profiles icp ON icp.isolate_id = vi.isolate_id
        LEFT JOIN host_scope_overrides hso ON hso.host_id = icp.host_id
        WHERE vi.isolate_id NOT IN (SELECT isolate_id FROM analysis_strict_target_isolates);

        CREATE TABLE submission_target_geography_precision AS
        SELECT
            aic.isolate_id,
            aic.accession,
            aic.virus_name,
            aic.master_id,
            aic.canonical_name,
            aic.host_scientific_name,
            aic.country,
            aic.latitude,
            aic.longitude,
            COALESCE(NULLIF(sc.coordinate_precision, ''), NULLIF(gqp.location_precision, ''), NULLIF(icp.location_precision, ''), 'unknown') AS raw_precision,
            CASE
                WHEN aic.latitude IS NULL OR aic.longitude IS NULL THEN 'unknown'
                WHEN lower(COALESCE(sc.coordinate_precision, gqp.location_precision, icp.location_precision, '')) IN ('reported_lat_lon','exact','precise','site') THEN 'exact'
                WHEN lower(COALESCE(sc.coordinate_precision, gqp.location_precision, icp.location_precision, '')) LIKE '%province%' THEN 'province'
                WHEN lower(COALESCE(sc.coordinate_precision, gqp.location_precision, icp.location_precision, '')) LIKE '%city%' THEN 'city'
                WHEN lower(COALESCE(sc.coordinate_precision, gqp.location_precision, icp.location_precision, '')) LIKE '%country%' THEN 'country'
                WHEN lower(COALESCE(sc.coordinate_precision, gqp.location_precision, icp.location_precision, '')) LIKE '%inferred%' THEN 'inferred'
                ELSE 'unknown'
            END AS map_precision_class,
            CASE
                WHEN aic.latitude IS NOT NULL AND aic.longitude IS NOT NULL
                 AND lower(COALESCE(sc.coordinate_precision, gqp.location_precision, icp.location_precision, '')) IN ('reported_lat_lon','exact','precise','site')
                THEN 1 ELSE 0
            END AS default_map_eligible
        FROM analysis_isolate_completeness aic
        JOIN analysis_target_isolates ati ON ati.isolate_id = aic.isolate_id
        LEFT JOIN infection_records ir ON ir.isolate_id = aic.isolate_id
        LEFT JOIN sample_collections sc ON sc.collection_id = ir.collection_id
        LEFT JOIN geography_quality_profiles gqp ON gqp.isolate_id = aic.isolate_id
        LEFT JOIN isolate_curated_profiles icp ON icp.isolate_id = aic.isolate_id;

        CREATE TABLE submission_protein_annotation_coverage AS
        SELECT
            vp.protein_id,
            vp.isolate_id,
            vp.protein_accession,
            vp.protein_name,
            vp.functional_category,
            MAX(COALESCE(pab.has_uniprot, 0)) AS has_uniprot,
            MAX(COALESCE(pab.has_interpro, 0)) AS has_interpro,
            MAX(COALESCE(pab.has_interpro_go, 0)) AS has_go,
            MAX(COALESCE(pab.has_kegg, 0)) AS has_kegg,
            MAX(COALESCE(pab.has_structure, 0)) AS has_bridge_structure,
            CASE WHEN EXISTS (
                SELECT 1 FROM protein_structures ps
                WHERE ps.protein_id = vp.protein_id
            ) THEN 1 ELSE 0 END AS has_protein_structures_row,
            CASE WHEN EXISTS (
                SELECT 1 FROM uniprot_structures us
                WHERE us.protein_id = vp.protein_id
                   OR us.uniprot_id IN (
                        SELECT uniprot_id FROM protein_annotation_bridge pab2
                        WHERE pab2.protein_id = vp.protein_id AND pab2.uniprot_id IS NOT NULL
                   )
            ) THEN 1 ELSE 0 END AS has_uniprot_structures_row,
            CASE
                WHEN MAX(COALESCE(pab.has_structure, 0)) = 1
                 AND MAX(CASE WHEN ps.protein_id IS NOT NULL THEN 1 ELSE 0 END) = 0
                THEN 'bridge_structure_without_local_protein_structures'
                WHEN MAX(COALESCE(pab.has_structure, 0)) = 0
                 AND MAX(CASE WHEN ps.protein_id IS NOT NULL THEN 1 ELSE 0 END) = 1
                THEN 'local_protein_structures_not_reflected_in_bridge'
                ELSE 'consistent_or_not_applicable'
            END AS structure_consistency_status
        FROM viral_proteins vp
        LEFT JOIN protein_annotation_bridge pab ON pab.protein_id = vp.protein_id
        LEFT JOIN protein_structures ps ON ps.protein_id = vp.protein_id
        GROUP BY vp.protein_id;

        CREATE TABLE submission_manual_intervention_tasks AS
        SELECT 'evidence_needs_review' AS task_type, evidence_id AS entity_id,
               evidence_type AS subtype, evidence_strength AS priority_hint,
               claim AS summary, reference_id, virus_master_id, isolate_id
        FROM evidence_records
        WHERE curation_status = 'needs_review'
        UNION ALL
        SELECT 'diagnostic_needs_review', method_id, method_category, evidence_strength,
               COALESCE(method_name, '') || ' | target=' || COALESCE(target_gene_or_region, '') || ' | lod=' || COALESCE(detection_limit, ''),
               reference_id, virus_master_id, NULL
        FROM diagnostic_methods
        WHERE curation_status = 'needs_review' AND data_quality <> 'placeholder'
        UNION ALL
        SELECT 'diagnostic_missing_required_fields', method_id, method_category, evidence_strength,
               COALESCE(method_name, '') || ' | missing target_gene_or_region/detection_limit/validation_context',
               reference_id, virus_master_id, NULL
        FROM diagnostic_methods
        WHERE data_quality = 'curated'
          AND (
              target_gene_or_region IS NULL OR trim(target_gene_or_region) = ''
              OR detection_limit IS NULL OR trim(detection_limit) = ''
              OR validation_context IS NULL OR trim(validation_context) = ''
          )
        UNION ALL
        SELECT 'control_missing_reference', control_id, method_category, evidence_strength,
               COALESCE(method_name, '') || ' | missing primary reference',
               reference_id, virus_master_id, NULL
        FROM control_management_methods
        WHERE reference_id IS NULL
        UNION ALL
        SELECT 'ictv_pending_review', master_id, priority, NULL,
               canonical_name || ' | ' || COALESCE(reason, ''),
               NULL, master_id, NULL
        FROM ictv_review_priority_queue;

        CREATE INDEX IF NOT EXISTS idx_submission_geo_precision_class ON submission_target_geography_precision(map_precision_class, isolate_id);
        CREATE INDEX IF NOT EXISTS idx_submission_protein_structure_status ON submission_protein_annotation_coverage(structure_consistency_status, protein_id);
        CREATE INDEX IF NOT EXISTS idx_submission_manual_tasks_type ON submission_manual_intervention_tasks(task_type, entity_id);
        """
    )
    conn.executescript(
        f"""
        CREATE TABLE submission_p0_release_blockers AS
        SELECT 'mrna_cdna_est_artifact_in_target' AS blocker_type,
               ati.isolate_id AS entity_id,
               ati.accession || ' | ' || COALESCE(ati.virus_name, '') AS summary
        FROM analysis_strict_target_isolates ati
        LEFT JOIN nucleotide_records nr ON nr.isolate_id = ati.isolate_id
        LEFT JOIN sample_metadata sm ON sm.isolate_id = ati.isolate_id
        WHERE {ARTIFACT_TEXT_SQL} LIKE '% mrna%'
           OR {ARTIFACT_TEXT_SQL} LIKE '% cdna%'
           OR {ARTIFACT_TEXT_SQL} LIKE '% est%'
           OR {ARTIFACT_TEXT_SQL} LIKE '%ribosomal%'
           OR {ARTIFACT_TEXT_SQL} LIKE '%clone %'
        UNION ALL
        SELECT 'host_genome_artifact_in_target', ati.isolate_id,
               ati.accession || ' | ' || COALESCE(ati.virus_name, '')
        FROM analysis_strict_target_isolates ati
        LEFT JOIN nucleotide_records nr ON nr.isolate_id = ati.isolate_id
        LEFT JOIN sample_metadata sm ON sm.isolate_id = ati.isolate_id
        WHERE COALESCE(ati.sequence_length, ati.genome_length, 0) > 10000000
           OR {ARTIFACT_TEXT_SQL} LIKE '% chromosome %'
           OR {ARTIFACT_TEXT_SQL} LIKE '%genomic scaffold%'
        UNION ALL
        SELECT 'short_complete_genome', isolate_id,
               accession || ' | len=' || COALESCE(sequence_length, genome_length, '')
        FROM analysis_strict_target_isolates
        WHERE completeness = 'complete_genome'
          AND COALESCE(sequence_length, genome_length, 0) > 0
          AND COALESCE(sequence_length, genome_length, 0) < 1000
        UNION ALL
        SELECT 'manual_checked_control_missing_reference', control_id,
               COALESCE(method_name, '')
        FROM control_management_methods
        WHERE curation_status='manual_checked'
          AND reference_id IS NULL
        UNION ALL
        SELECT 'diagnostic_title_pollution_open', method_id,
               COALESCE(method_name, '')
        FROM diagnostic_methods
        WHERE curation_status <> 'rejected'
          AND (
              method_name LIKE 'Figure %:%'
              OR method_name LIKE 'Table %:%'
              OR LENGTH(method_name) > 120
          )
        UNION ALL
        SELECT 'ictv_multiple_high_confidence_taxa', master_id,
               'distinct high-confidence ictv_id=' || COUNT(DISTINCT ictv_id)
        FROM virus_ictv_mappings
        WHERE confidence = 'high'
          AND match_status <> 'rejected'
        GROUP BY master_id
        HAVING COUNT(DISTINCT ictv_id) > 1
        UNION ALL
        SELECT 'ictv_multiple_high_confidence_families', vim.master_id,
               'distinct high-confidence ICTV families=' || COUNT(DISTINCT COALESCE(it.family, ''))
        FROM virus_ictv_mappings vim
        JOIN ictv_taxonomy it ON it.ictv_id = vim.ictv_id
        WHERE vim.confidence = 'high'
          AND vim.match_status <> 'rejected'
        GROUP BY vim.master_id
        HAVING COUNT(DISTINCT COALESCE(it.family, '')) > 1
        UNION ALL
        SELECT DISTINCT 'ictv_family_conflict_with_master', vim.master_id,
               COALESCE(vm.canonical_name, '') || ' | master_family=' || COALESCE(vm.virus_family, '') || ' | ictv_family=' || COALESCE(it.family, '')
        FROM virus_ictv_mappings vim
        JOIN ictv_taxonomy it ON it.ictv_id = vim.ictv_id
        JOIN virus_master vm ON vm.master_id = vim.master_id
        WHERE vim.confidence = 'high'
          AND vim.match_status <> 'rejected'
          AND NULLIF(TRIM(vm.virus_family), '') IS NOT NULL
          AND NULLIF(TRIM(it.family), '') IS NOT NULL
          AND LOWER(TRIM(vm.virus_family)) <> LOWER(TRIM(it.family));

        CREATE INDEX IF NOT EXISTS idx_submission_p0_blockers_type ON submission_p0_release_blockers(blocker_type, entity_id);
        """
    )
    conn.commit()


def export_data_dictionary(conn: sqlite3.Connection, out_dir: Path) -> None:
    tables = rows(
        conn,
        """
        SELECT name, type, sql
        FROM sqlite_master
        WHERE type IN ('table','view') AND name NOT LIKE 'sqlite_%'
        ORDER BY type, name
        """,
    )
    data = []
    for item in tables:
        name = item["name"]
        if name.startswith("virus_search_fts"):
            continue
        try:
            count = int(scalar(conn, f'SELECT COUNT(*) FROM "{name}"') or 0)
        except sqlite3.Error:
            count = None
        for col in rows(conn, f'PRAGMA table_info("{name}")'):
            data.append(
                {
                    "object_type": item["type"],
                    "table_or_view": name,
                    "column_name": col["name"],
                    "sqlite_type": col["type"],
                    "not_null": col["notnull"],
                    "default_value": col["dflt_value"],
                    "primary_key_position": col["pk"],
                    "row_count": count,
                }
            )
    write_csv(
        out_dir / "submission_data_dictionary.csv",
        ["object_type", "table_or_view", "column_name", "sqlite_type", "not_null", "default_value", "primary_key_position", "row_count"],
        data,
    )

    fks = []
    for item in tables:
        if item["type"] != "table":
            continue
        if item["name"].startswith("virus_search_fts"):
            continue
        for fk in rows(conn, f'PRAGMA foreign_key_list("{item["name"]}")'):
            fks.append(
                {
                    "table": item["name"],
                    "from_column": fk["from"],
                    "to_table": fk["table"],
                    "to_column": fk["to"],
                    "on_update": fk["on_update"],
                    "on_delete": fk["on_delete"],
                }
            )
    write_csv(out_dir / "submission_foreign_keys.csv", ["table", "from_column", "to_table", "to_column", "on_update", "on_delete"], fks)

    with (out_dir / "submission_er_diagram.mmd").open("w", encoding="utf-8") as f:
        f.write("erDiagram\n")
        for fk in fks:
            f.write(f'  {fk["to_table"]} ||--o{{ {fk["table"]} : "{fk["from_column"]}"\n')


def export_peer_database_comparison(out_dir: Path) -> None:
    data = [
        {
            "resource": "CSVDB",
            "scope": "Crustacean-associated viruses",
            "isolate_level": "yes",
            "host_evidence": "planned; must separate reviewed vs inferred",
            "geography": "yes; must split exact/province/country/inferred/unknown",
            "experimental_phenotypes": "only if manual_checked",
            "diagnostics_control": "currently indexed candidates; not validated knowledgebase",
            "protein_annotation": "partial UniProt/InterPro/GO/KEGG/structure coverage",
            "download_api_versioning": "must be completed before submission",
            "manual_curation": "must report counts and queue",
        },
        {
            "resource": "IVCDB",
            "scope": "Iridoviruses",
            "isolate_level": "yes",
            "host_evidence": "host range for iridoviruses",
            "geography": "yes",
            "experimental_phenotypes": "vaccine/detection disease-management modules",
            "diagnostics_control": "yes for its domain",
            "protein_annotation": "nonredundant proteins/core genes/phylogeny/synteny",
            "download_api_versioning": "database paper resource",
            "manual_curation": "domain-specific curation",
        },
        {
            "resource": "VirusHostDB",
            "scope": "Virus-host relationships",
            "isolate_level": "limited",
            "host_evidence": "yes",
            "geography": "no",
            "experimental_phenotypes": "limited",
            "diagnostics_control": "no",
            "protein_annotation": "external links",
            "download_api_versioning": "yes",
            "manual_curation": "source-integrated",
        },
        {
            "resource": "ViralZone",
            "scope": "Virus family knowledge",
            "isolate_level": "no",
            "host_evidence": "general",
            "geography": "no",
            "experimental_phenotypes": "family factsheets",
            "diagnostics_control": "no",
            "protein_annotation": "virus-family knowledge",
            "download_api_versioning": "web resource",
            "manual_curation": "curated knowledge pages",
        },
        {
            "resource": "CrustyBase",
            "scope": "Crustacean transcriptomes",
            "isolate_level": "no",
            "host_evidence": "host species resource",
            "geography": "not virus isolate geography",
            "experimental_phenotypes": "host transcriptomic context",
            "diagnostics_control": "no",
            "protein_annotation": "host transcript/protein-oriented",
            "download_api_versioning": "database resource",
            "manual_curation": "domain resource",
        },
        {
            "resource": "FVD",
            "scope": "Fish viruses",
            "isolate_level": "sequence/host/geography-centered",
            "host_evidence": "fish host",
            "geography": "yes",
            "experimental_phenotypes": "limited",
            "diagnostics_control": "limited",
            "protein_annotation": "not CSVDB-style",
            "download_api_versioning": "published database",
            "manual_curation": "domain resource",
        },
    ]
    write_csv(
        out_dir / "submission_peer_database_comparison.csv",
        [
            "resource",
            "scope",
            "isolate_level",
            "host_evidence",
            "geography",
            "experimental_phenotypes",
            "diagnostics_control",
            "protein_annotation",
            "download_api_versioning",
            "manual_curation",
        ],
        data,
    )


def build_summary(conn: sqlite3.Connection) -> dict[str, Any]:
    target = int(scalar(conn, "SELECT COUNT(*) FROM analysis_target_isolates") or 0)
    strict = int(scalar(conn, "SELECT COUNT(*) FROM analysis_strict_target_isolates") or 0)
    total = int(scalar(conn, "SELECT COUNT(*) FROM viral_isolates") or 0)
    geo = {r["map_precision_class"]: r["n"] for r in rows(conn, "SELECT map_precision_class, COUNT(*) AS n FROM submission_target_geography_precision GROUP BY map_precision_class")}
    default_map = int(scalar(conn, "SELECT COUNT(*) FROM submission_target_geography_precision WHERE default_map_eligible=1") or 0)

    protein_total = int(scalar(conn, "SELECT COUNT(*) FROM viral_proteins") or 0)
    protein = {}
    for field in ["has_uniprot", "has_interpro", "has_go", "has_kegg", "has_bridge_structure", "has_protein_structures_row", "has_uniprot_structures_row"]:
        n = int(scalar(conn, f"SELECT COUNT(*) FROM submission_protein_annotation_coverage WHERE {field}=1") or 0)
        protein[field] = {"count": n, "total": protein_total, "pct": pct(n, protein_total)}
    protein["structure_conflicts"] = dict(
        (r["structure_consistency_status"], r["n"])
        for r in rows(conn, "SELECT structure_consistency_status, COUNT(*) AS n FROM submission_protein_annotation_coverage GROUP BY structure_consistency_status")
    )

    tasks = dict((r["task_type"], r["n"]) for r in rows(conn, "SELECT task_type, COUNT(*) AS n FROM submission_manual_intervention_tasks GROUP BY task_type"))
    p0_release_blockers = dict((r["blocker_type"], r["n"]) for r in rows(conn, "SELECT blocker_type, COUNT(*) AS n FROM submission_p0_release_blockers GROUP BY blocker_type"))
    excluded_reasons = dict((r["exclusion_reason"], r["n"]) for r in rows(conn, "SELECT exclusion_reason, COUNT(*) AS n FROM submission_excluded_isolates_with_reasons GROUP BY exclusion_reason"))
    dashboard_violations = []
    for metric, field in [("host", "has_host"), ("country", "has_country"), ("coordinates", "has_coordinates"), ("genome_type", "has_genome_type"), ("reference", "has_reference")]:
        n = int(scalar(conn, f"SELECT COALESCE(SUM({field}),0) FROM analysis_isolate_completeness WHERE isolate_id IN (SELECT isolate_id FROM analysis_target_isolates)") or 0)
        dashboard_violations.append({"metric": metric, "count": n, "total": target, "pct": pct(n, target), "valid": n <= target})

    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "database_sha256": file_sha256(DB_PATH),
        "scope": {"viral_isolates_total": total, "analysis_target_isolates": target, "analysis_strict_target_isolates": strict, "excluded_from_strict_target": total - strict},
        "dashboard_denominator_checks": dashboard_violations,
        "geography_precision": geo,
        "default_map_eligible_exact_points": {"count": default_map, "total": target, "pct": pct(default_map, target)},
        "protein_annotation_coverage": protein,
        "manual_intervention_tasks": tasks,
        "p0_release_blockers": p0_release_blockers,
        "excluded_reason_counts": excluded_reasons,
        "claim_policy": {
            "map_default": "Only default_map_eligible exact/reported/site-level coordinates may be shown as precise points.",
            "evidence": "needs_review, auto_imported, inferred, and rejected records must not support main manuscript claims.",
            "diagnostics": "Only curated/manual_checked rows with primary reference and required method fields may support diagnostic knowledgebase claims.",
            "removed_prediction_workflow": "Virulence/temperature prediction tables and release claims have been removed; manuscript claims must use reviewed evidence only.",
        },
    }


def export_review_artifacts(conn: sqlite3.Connection, out_dir: Path, summary: dict[str, Any]) -> None:
    exports = {
        "submission_excluded_isolates_with_reasons.csv": (
            "SELECT * FROM submission_excluded_isolates_with_reasons WHERE exclusion_reason <> 'not_excluded_by_current_target_rule' ORDER BY exclusion_reason, isolate_id LIMIT 20000",
            ["isolate_id", "accession", "virus_name", "master_id", "canonical_name", "entry_type", "is_crustacean_virus", "host_id", "host_scientific_name", "host_is_target", "scope_status", "exclude_from_target_stats", "exclusion_reason", "in_analysis_target", "in_strict_target"],
        ),
        "submission_target_geography_precision.csv": (
            "SELECT * FROM submission_target_geography_precision WHERE map_precision_class <> 'exact' ORDER BY map_precision_class, isolate_id LIMIT 20000",
            ["isolate_id", "accession", "virus_name", "master_id", "canonical_name", "host_scientific_name", "country", "latitude", "longitude", "raw_precision", "map_precision_class", "default_map_eligible"],
        ),
        "submission_protein_annotation_coverage_conflicts.csv": (
            "SELECT * FROM submission_protein_annotation_coverage WHERE structure_consistency_status <> 'consistent_or_not_applicable' ORDER BY structure_consistency_status, protein_id LIMIT 50000",
            ["protein_id", "isolate_id", "protein_accession", "protein_name", "functional_category", "has_uniprot", "has_interpro", "has_go", "has_kegg", "has_bridge_structure", "has_protein_structures_row", "has_uniprot_structures_row", "structure_consistency_status"],
        ),
        "submission_manual_intervention_tasks.csv": (
            "SELECT * FROM submission_manual_intervention_tasks ORDER BY task_type, entity_id LIMIT 50000",
            ["task_type", "entity_id", "subtype", "priority_hint", "summary", "reference_id", "virus_master_id", "isolate_id"],
        ),
        "submission_p0_release_blockers.csv": (
            "SELECT * FROM submission_p0_release_blockers ORDER BY blocker_type, entity_id LIMIT 50000",
            ["blocker_type", "entity_id", "summary"],
        ),
    }
    for filename, (sql, header) in exports.items():
        write_csv(out_dir / filename, header, [dict(r) for r in rows(conn, sql)])

    (out_dir / "submission_hardening_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [
        "# Submission Hardening Report",
        "",
        f"Generated: {summary['generated_at']}",
        f"Database SHA256: `{summary['database_sha256']}`",
        "",
        "## Scope",
        f"- Viral isolates total: `{summary['scope']['viral_isolates_total']}`",
        f"- Analysis target isolates: `{summary['scope']['analysis_target_isolates']}`",
        f"- Strict target isolates: `{summary['scope']['analysis_strict_target_isolates']}`",
        f"- Excluded from strict target: `{summary['scope']['excluded_from_strict_target']}`",
        "",
        "## Dashboard Denominator Checks",
    ]
    for item in summary["dashboard_denominator_checks"]:
        lines.append(f"- {item['metric']}: {item['count']}/{item['total']} ({item['pct']}%), valid={item['valid']}")
    lines += ["", "## Geography Precision"]
    for k, v in sorted(summary["geography_precision"].items()):
        lines.append(f"- {k}: {v}")
    ep = summary["default_map_eligible_exact_points"]
    lines.append(f"- Default precise map points: {ep['count']}/{ep['total']} ({ep['pct']}%)")
    lines += ["", "## Protein Annotation Coverage"]
    for k, v in summary["protein_annotation_coverage"].items():
        if isinstance(v, dict) and "count" in v:
            lines.append(f"- {k}: {v['count']}/{v['total']} ({v['pct']}%)")
        else:
            lines.append(f"- {k}: {v}")
    lines += ["", "## Manual Intervention Remaining"]
    for k, v in sorted(summary["manual_intervention_tasks"].items()):
        lines.append(f"- {k}: {v}")
    lines += ["", "## P0 Release Blockers"]
    if summary["p0_release_blockers"]:
        for k, v in sorted(summary["p0_release_blockers"].items()):
            lines.append(f"- {k}: {v}")
    else:
        lines.append("- None")
    lines += ["", "## Generated CSV Artifacts"]
    for path in sorted(out_dir.glob("submission_*.csv")):
        lines.append(f"- `{path.name}`")
    (out_dir / "submission_hardening_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    REPORTS_DIR.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = REPORTS_DIR / f"submission_hardening_{stamp}"
    out_dir.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(DB_PATH, timeout=60)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys=ON")
        required = ["analysis_target_isolates", "analysis_strict_target_isolates", "analysis_isolate_completeness"]
        missing = [name for name in required if not view_exists(conn, name)]
        if missing:
            raise RuntimeError(f"Missing required analysis views: {missing}")
        refresh_review_views(conn)
        summary = build_summary(conn)
        export_data_dictionary(conn, out_dir)
        export_peer_database_comparison(out_dir)
        export_review_artifacts(conn, out_dir, summary)
    finally:
        conn.close()

    print(out_dir)


if __name__ == "__main__":
    main()
