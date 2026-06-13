#!/usr/bin/env python3
"""Release gate for the crustacean virus database.

The default gate is intentionally strict enough for NAR pre-submission work:
unresolved manual curation worklists are blocking failures, not cosmetic
warnings. Use --allow-curation-warnings only for local source-code or UI checks
where the goal is to confirm that candidate records are not leaking into public
reviewed surfaces.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any


DB_PATH = Path("crustacean_virus_core.db")
REPORTS_DIR = Path("reports")
BASE_DIR = Path(__file__).resolve().parent


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


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def value(conn: sqlite3.Connection, sql: str, params: tuple[Any, ...] = ()) -> Any:
    row = conn.execute(sql, params).fetchone()
    return None if row is None else row[0]


def rows(conn: sqlite3.Connection, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def exists(conn: sqlite3.Connection, kind: str, name: str) -> bool:
    return bool(value(conn, "SELECT 1 FROM sqlite_master WHERE type=? AND name=?", (kind, name)))


def pct(numerator: int | None, denominator: int | None) -> float | None:
    if denominator in (None, 0) or numerator is None:
        return None
    return float(numerator) / float(denominator)


def count_scihub_artifacts() -> int:
    return sum(
        1
        for path in BASE_DIR.rglob("*")
        if path.is_file()
        and ("scihub" in path.name.lower() or "sci-hub" in path.name.lower())
    )


def count_forbidden_release_text() -> int:
    forbidden_patterns = [
        "ML推断",
        "ML预测",
        "ML 预测",
        "RandomForest",
        "chart-ml",
        "ml-virulence",
        "ml-temperature",
        "dq-ml-count",
        "准确率92",
        "92.6",
        "178种文献校验",
        "LOFO",
        "ROC曲线",
        "致病性等级预测",
        "温度耐受性预测",
    ]
    checked_paths = [
        BASE_DIR / "templates",
        BASE_DIR / "backend.py",
        BASE_DIR / "build_downloads.py",
        BASE_DIR / "generate_article_outline.py",
        BASE_DIR / "reports" / "CSVDB_article_enhanced_architecture_20260507.md",
    ]
    count = 0
    for root in checked_paths:
        paths = root.rglob("*") if root.is_dir() else [root]
        for path in paths:
            if not path.is_file():
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            if any(pattern in text for pattern in forbidden_patterns):
                count += 1
    return count


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def public_download_failures() -> list[dict[str, Any]]:
    failures: list[dict[str, Any]] = []
    public_dir = BASE_DIR / "public_downloads"
    manifest = public_dir / "SHA256SUMS.csv"
    if not public_dir.exists():
        return [{"metric": "public_downloads_dir", "value": "missing", "required": "present"}]
    if not manifest.exists():
        return [{"metric": "public_download_checksums", "value": "missing", "required": "SHA256SUMS.csv"}]

    allowed_root_files = {
        "all_sequences.fasta",
        "complete_genomes.fasta",
        "crustacean_virus_metadata_standardized.xlsx",
        "host_virus_network.csv",
        "reviewed_evidence_records.xlsx",
        "SHA256SUMS.csv",
        "README.md",
        "LICENSE.txt",
        "CITATION.cff",
        "DATA_USE_AGREEMENT.md",
    }
    allowed_phylogeny_suffixes = {".png", ".svg", ".contree", ".tree", ".nwk", ".newick"}
    forbidden_suffixes = {".log", ".iqtree", ".mldist", ".splits", ".ckp", ".gz", ".model"}
    manifest_rows: dict[str, dict[str, str]] = {}
    try:
        with manifest.open(newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                manifest_rows[row["path"]] = row
    except Exception as exc:
        failures.append({"metric": "public_download_checksum_manifest_readable", "value": type(exc).__name__, "required": "ok"})
        return failures

    unlisted = []
    disallowed = []
    checksum_mismatches = []
    unsafe_text_files = []
    for path in sorted(p for p in public_dir.rglob("*") if p.is_file()):
        rel = path.relative_to(public_dir).as_posix()
        if rel == "SHA256SUMS.csv":
            continue
        is_allowed = (
            ("/" not in rel and path.name in allowed_root_files)
            or (
                rel.startswith("phylogeny/")
                and path.suffix.lower() in allowed_phylogeny_suffixes
                and not any(part in {"logs", "intermediate", "tmp"} for part in path.parts)
            )
        )
        if path.suffix.lower() in forbidden_suffixes or not is_allowed:
            disallowed.append(rel)
        row = manifest_rows.get(rel)
        if row is None:
            unlisted.append(rel)
        else:
            size_ok = str(path.stat().st_size) == str(row.get("bytes", ""))
            hash_ok = sha256_file(path) == row.get("sha256")
            if not size_ok or not hash_ok:
                checksum_mismatches.append(rel)
        if path.suffix.lower() in {".txt", ".md", ".json", ".log", ".iqtree", ".csv"}:
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                text = ""
            if "F:\\" in text or "C:\\" in text or "failed composition" in text.lower():
                unsafe_text_files.append(rel)

    missing_files = sorted(rel for rel in manifest_rows if not (public_dir / rel).exists())
    if unlisted:
        failures.append({"metric": "public_download_files_missing_from_checksums", "value": unlisted[:20], "required": []})
    if missing_files:
        failures.append({"metric": "public_download_manifest_points_to_missing_files", "value": missing_files[:20], "required": []})
    if checksum_mismatches:
        failures.append({"metric": "public_download_checksum_mismatches", "value": checksum_mismatches[:20], "required": []})
    if disallowed:
        failures.append({"metric": "public_download_disallowed_files", "value": disallowed[:30], "required": []})
    if unsafe_text_files:
        failures.append({"metric": "public_download_unsafe_text", "value": unsafe_text_files[:20], "required": []})
    return failures


def release_tsv_policy_failures() -> list[dict[str, Any]]:
    failures: list[dict[str, Any]] = []
    try:
        from export_release_tsvs import EXPORT_TABLES, PUBLIC_EXPORTS
    except Exception as exc:
        return [{"metric": "release_tsv_policy_importable", "value": type(exc).__name__, "required": "ok"}]

    missing = [table for table in EXPORT_TABLES if table not in PUBLIC_EXPORTS]
    if missing:
        failures.append({"metric": "release_tsv_tables_without_public_policy", "value": missing, "required": []})

    raw_sensitive = {"viral_isolates", "infection_records", "data_provenance", "viral_proteins"}
    unsafe = []
    for table in raw_sensitive.intersection(PUBLIC_EXPORTS):
        spec = PUBLIC_EXPORTS[table]
        sql = " ".join(str(spec.get("sql", "")).lower().split())
        scope = str(spec.get("curation_scope", "")).lower()
        if table == "data_provenance" and "inferred" not in sql:
            unsafe.append(table)
        elif table != "data_provenance" and "analysis_strict_target_isolates" not in sql and "manual_checked" not in sql:
            unsafe.append(table)
        if not scope:
            unsafe.append(f"{table}:missing_scope")
    if unsafe:
        failures.append({"metric": "release_tsv_sensitive_tables_unfiltered", "value": unsafe, "required": []})
    return failures


def required_root_file_failures() -> list[dict[str, Any]]:
    required = [
        "README.md",
        "requirements.txt",
        "environment.yml",
        "LICENSE.txt",
        "CITATION.cff",
        "DATA_USE_AGREEMENT.md",
    ]
    failures = []
    for name in required:
        path = BASE_DIR / name
        if not path.exists() or path.stat().st_size == 0:
            failures.append({"metric": f"required_root_file.{name}", "value": "missing_or_empty", "required": "present"})
    return failures


def api_static_smoke_checks(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Static API checks that do not require a running public server."""
    failures: list[dict[str, Any]] = []

    backend_path = BASE_DIR / "backend.py"
    try:
        spec = importlib.util.spec_from_file_location("release_gate_backend", backend_path)
        if spec is None or spec.loader is None:
            failures.append({"metric": "api_backend_importable", "value": False, "required": True})
            return failures
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        routes = {getattr(route, "path", None) for route in module.app.routes}
        required_routes = {"/", "/search", "/api/health", "/api/stats", "/api/search", "/api/download/{filename}"}
        missing_routes = sorted(route for route in required_routes if route not in routes)
        if missing_routes:
            failures.append({"metric": "api_required_routes_missing", "value": missing_routes, "required": []})

        try:
            stats = module.get_stats()
            for key in ["viral_isolates", "virus_species", "crustacean_hosts", "viral_proteins"]:
                if key not in stats:
                    failures.append({"metric": f"api_stats_missing_{key}", "value": None, "required": "present"})
        except Exception as exc:
            failures.append({"metric": "api_stats_callable", "value": type(exc).__name__, "required": "ok"})

        for endpoint, func_name, forbidden_keys in [
            (
                "/api/virulence",
                "get_virulence_profiles",
                {"publication_use", "data_origin", "data_source_type"},
            ),
            (
                "/api/temperature",
                "get_temperature_profiles",
                {"publication_use", "data_origin", "data_source_type"},
            ),
        ]:
            try:
                api_rows = getattr(module, func_name)()
                if not isinstance(api_rows, list):
                    failures.append({"metric": f"{endpoint}.return_type", "value": type(api_rows).__name__, "required": "list"})
                    continue
                leaked_keys = sorted(
                    key
                    for row in api_rows
                    if isinstance(row, dict)
                    for key in forbidden_keys.intersection(row.keys())
                )
                if leaked_keys:
                    failures.append({"metric": f"{endpoint}.candidate_fields_exposed", "value": leaked_keys, "required": []})
            except Exception as exc:
                failures.append({"metric": f"{endpoint}.callable", "value": type(exc).__name__, "required": "ok"})
    except Exception as exc:
        failures.append({"metric": "api_backend_importable", "value": type(exc).__name__, "required": "ok"})

    required_public_files = [
        BASE_DIR / "public_downloads" / "crustacean_virus_metadata_standardized.xlsx",
        BASE_DIR / "public_downloads" / "all_sequences.fasta",
        BASE_DIR / "public_downloads" / "complete_genomes.fasta",
        BASE_DIR / "public_assets" / "world.json",
        BASE_DIR / "public_assets" / "china.json",
    ]
    missing_files = [str(path.relative_to(BASE_DIR)) for path in required_public_files if not path.exists()]
    if missing_files:
        failures.append({"metric": "api_public_assets_missing", "value": missing_files, "required": []})

    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate DB before release/export.")
    parser.add_argument(
        "--allow-curation-warnings",
        action="store_true",
        help=(
            "Downgrade unresolved curation worklists to warnings for local "
            "source-code/UI checks. Do not use this for NAR readiness."
        ),
    )
    parser.add_argument("--min-target-host", type=float, default=0.70)
    parser.add_argument("--min-target-country", type=float, default=0.60)
    parser.add_argument("--min-target-reference", type=float, default=0.95)
    parser.add_argument("--min-protein-uniprot", type=float, default=0.45)
    args = parser.parse_args()

    REPORTS_DIR.mkdir(exist_ok=True)
    generated_at = datetime.now().strftime("%Y%m%d_%H%M%S")
    failures: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    metrics: dict[str, Any] = {}

    with connect() as conn:
        integrity = value(conn, "PRAGMA integrity_check")
        fk_violations = len(rows(conn, "PRAGMA foreign_key_check"))
        metrics["integrity_check"] = integrity
        metrics["foreign_key_violations"] = fk_violations
        if integrity != "ok":
            failures.append({"metric": "integrity_check", "value": integrity, "required": "ok"})
        if fk_violations:
            failures.append({"metric": "foreign_key_violations", "value": fk_violations, "required": 0})

        required_views = [
            "analysis_target_isolates",
            "analysis_strict_target_isolates",
            "analysis_isolate_completeness",
            "analysis_protein_annotation_completeness",
            "analysis_reviewed_evidence_records",
            "analysis_curated_diagnostic_methods",
        ]
        for view in required_views:
            present = exists(conn, "view", view)
            metrics[f"view.{view}"] = present
            if not present:
                failures.append({"metric": f"view.{view}", "value": present, "required": True})

        if exists(conn, "view", "analysis_strict_target_isolates") and exists(conn, "view", "analysis_isolate_completeness"):
            denominator = value(conn, "SELECT COUNT(*) FROM analysis_strict_target_isolates")
            checks = [
                ("target_has_host", "SELECT SUM(has_host) FROM analysis_isolate_completeness WHERE isolate_id IN (SELECT isolate_id FROM analysis_strict_target_isolates)", args.min_target_host),
                ("target_has_country", "SELECT SUM(has_country) FROM analysis_isolate_completeness WHERE isolate_id IN (SELECT isolate_id FROM analysis_strict_target_isolates)", args.min_target_country),
                ("target_has_reference", "SELECT SUM(has_reference) FROM analysis_isolate_completeness WHERE isolate_id IN (SELECT isolate_id FROM analysis_strict_target_isolates)", args.min_target_reference),
            ]
            for metric, sql, threshold in checks:
                numerator = value(conn, sql) or 0
                ratio = pct(int(numerator), int(denominator))
                metrics[metric] = {"numerator": numerator, "denominator": denominator, "pct": ratio}
                if int(numerator) > int(denominator):
                    failures.append({"metric": f"{metric}_numerator_exceeds_denominator", "value": numerator, "required_max": denominator})
                if ratio is None or ratio < threshold:
                    failures.append({"metric": metric, "value": ratio, "required_min": threshold})

        if exists(conn, "view", "analysis_protein_annotation_completeness"):
            denominator = value(conn, "SELECT COUNT(*) FROM analysis_protein_annotation_completeness")
            numerator = value(conn, "SELECT SUM(has_uniprot_link) FROM analysis_protein_annotation_completeness") or 0
            ratio = pct(int(numerator), int(denominator))
            metrics["protein_has_uniprot_link"] = {"numerator": numerator, "denominator": denominator, "pct": ratio}
            if ratio is None or ratio < args.min_protein_uniprot:
                failures.append({"metric": "protein_has_uniprot_link", "value": ratio, "required_min": args.min_protein_uniprot})

        manual_worklist_checks = {
            "evidence_needs_review": "SELECT COUNT(*) FROM evidence_records WHERE curation_status='needs_review'",
            "diagnostic_methods_need_review": "SELECT COUNT(*) FROM diagnostic_methods WHERE curation_status='needs_review' AND data_quality <> 'placeholder'",
            "ictv_pending_review": "SELECT COUNT(*) FROM virus_ictv_status WHERE ictv_status='pending_review'",
            "target_master_without_isolate": """
                SELECT COUNT(*)
                FROM virus_master vm
                LEFT JOIN viral_isolates vi ON vi.master_id = vm.master_id
                WHERE vi.isolate_id IS NULL
                  AND vm.is_crustacean_virus = 1
                  AND vm.entry_type NOT IN ('non_target', 'host_genome', 'catalog_only', 'reference_only')
            """,
            "host_range_evidence_unreviewed": "SELECT COUNT(*) FROM host_range_evidence WHERE curation_status <> 'manual_checked'",
            "pathogenicity_evidence_unreviewed": "SELECT COUNT(*) FROM pathogenicity_evidence WHERE curation_status <> 'manual_checked'",
            "environmental_evidence_unreviewed": "SELECT COUNT(*) FROM environmental_evidence WHERE curation_status <> 'manual_checked'",
            "outbreak_events_unreviewed": "SELECT COUNT(*) FROM outbreak_events WHERE curation_status <> 'manual_checked'",
            "candidate_profile_records_not_for_public_claims": """
                SELECT COUNT(*)
                FROM (
                    SELECT publication_use
                    FROM virulence_profiles
                    UNION ALL
                    SELECT publication_use
                    FROM temperature_profiles
                )
                WHERE COALESCE(publication_use, '') NOT IN (
                    'curated_for_primary_claims',
                    'reviewed_supporting_evidence'
                )
            """,
        }
        for metric, sql in manual_worklist_checks.items():
            count = value(conn, sql) or 0
            metrics[metric] = count
            item = {"metric": metric, "value": count, "required": 0}
            if count:
                if args.allow_curation_warnings:
                    warnings.append(item)
                else:
                    failures.append(item)

        blocker_checks = {
            "target_mrna_cdna_est_artifacts": f"""
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
            "target_host_genome_artifacts": f"""
                SELECT COUNT(*)
                FROM analysis_target_isolates vi
                LEFT JOIN nucleotide_records nr ON nr.isolate_id = vi.isolate_id
                LEFT JOIN sample_metadata sm ON sm.isolate_id = vi.isolate_id
                WHERE COALESCE(vi.sequence_length, vi.genome_length, 0) > 10000000
                   OR {ARTIFACT_TEXT_SQL} LIKE '% chromosome %'
                   OR {ARTIFACT_TEXT_SQL} LIKE '%genomic scaffold%'
            """,
            "target_short_complete_genomes": """
                SELECT COUNT(*)
                FROM analysis_target_isolates
                WHERE completeness = 'complete_genome'
                  AND COALESCE(sequence_length, genome_length, 0) > 0
                  AND COALESCE(sequence_length, genome_length, 0) < 1000
            """,
            "all_short_complete_genomes_unflagged": """
                SELECT COUNT(*)
                FROM viral_isolates
                WHERE completeness = 'complete_genome'
                  AND COALESCE(sequence_length, genome_length, 0) > 0
                  AND COALESCE(sequence_length, genome_length, 0) < 1000
                  AND COALESCE(sequence_scope_status, '') <> 'short_fragment_not_complete_genome'
            """,
            "virulence_mortality_fraction_invalid": """
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
            "non_target_hosts_not_excluded": """
                SELECT COUNT(*)
                FROM crustacean_hosts h
                LEFT JOIN host_scope_overrides hso ON hso.host_id = h.host_id
                WHERE h.host_scope_status NOT IN ('target_crustacean', 'target_mollusk', 'target_other_aquatic_invert')
                  AND h.host_scope_status NOT LIKE 'excluded_%'
                  AND COALESCE(hso.exclude_from_target_stats, 0) <> 1
            """,
            "manual_checked_controls_missing_reference": """
                SELECT COUNT(*)
                FROM control_management_methods
                WHERE curation_status='manual_checked'
                  AND reference_id IS NULL
            """,
            "diagnostic_title_pollution_open": """
                SELECT COUNT(*)
                FROM diagnostic_methods
                WHERE curation_status <> 'rejected'
                  AND (
                      method_name LIKE 'Figure %:%'
                      OR method_name LIKE 'Table %:%'
                      OR LENGTH(method_name) > 120
                  )
            """,
            "ictv_multiple_high_confidence_taxa": """
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
            "ictv_multiple_high_confidence_families": """
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
            "ictv_family_conflict_with_master": """
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
            "raw_evidence_records_in_release_manifest": """
                SELECT COUNT(*)
                FROM release_manifest
                WHERE LOWER(table_name) = 'evidence_records'
                  AND LOWER(COALESCE(export_path, '')) NOT LIKE '%reviewed%'
                  AND LOWER(COALESCE(export_path, '')) NOT LIKE 'maintenance_archive/deprecated_release_exports/%'
            """,
            "esmfold_low_confidence_primary_claims": """
                SELECT COUNT(*)
                FROM protein_structures
                WHERE prediction_method = 'esmfold'
                  AND COALESCE(publication_use, 'do_not_use_for_primary_claims') = 'supporting_structure_annotation'
                  AND COALESCE(plddt_normalized_100,
                      CASE
                          WHEN plddt_score IS NULL THEN NULL
                          WHEN plddt_score <= 1.0 THEN plddt_score * 100.0
                          ELSE plddt_score
                      END
                  ) < 70
            """,
            "interpro_domain_visualization_without_coordinates": """
                SELECT COUNT(*)
                FROM interpro_annotations
                WHERE (start_pos IS NULL OR end_pos IS NULL)
                  AND COALESCE(publication_use, 'domain_presence_only_no_visualization') = 'domain_presence_and_position'
            """,
            "reviewed_evidence_view_contains_non_manual": """
                SELECT COUNT(*)
                FROM analysis_reviewed_evidence_records
                WHERE curation_status <> 'manual_checked'
            """,
            "reviewed_evidence_view_missing_reference": """
                SELECT COUNT(*)
                FROM analysis_reviewed_evidence_records er
                LEFT JOIN ref_literatures rl ON rl.reference_id = er.reference_id
                WHERE NULLIF(TRIM(COALESCE(er.source_pmid, '')), '') IS NULL
                  AND NULLIF(TRIM(COALESCE(er.source_doi, '')), '') IS NULL
                  AND NULLIF(TRIM(COALESCE(rl.pmid, '')), '') IS NULL
                  AND NULLIF(TRIM(COALESCE(rl.doi, '')), '') IS NULL
            """,
            "primary_profile_records_without_manual_evidence": """
                SELECT COUNT(*)
                FROM (
                    SELECT publication_use, virus_name, 'virulence' AS evidence_group
                    FROM virulence_profiles
                    UNION ALL
                    SELECT publication_use, virus_name, 'temperature' AS evidence_group
                    FROM temperature_profiles
                ) p
                WHERE COALESCE(p.publication_use, '') IN (
                    'curated_for_primary_claims',
                    'reviewed_supporting_evidence'
                )
                  AND NOT EXISTS (
                      SELECT 1
                      FROM analysis_reviewed_evidence_records er
                      LEFT JOIN virus_master vm ON vm.master_id = er.virus_master_id
                      LEFT JOIN viral_isolates vi ON vi.isolate_id = er.isolate_id
                      WHERE LOWER(COALESCE(vm.canonical_name, vi.virus_name, '')) = LOWER(COALESCE(p.virus_name, ''))
                        AND (
                            (p.evidence_group = 'virulence' AND er.evidence_type IN ('virulence','pathogenicity','mortality'))
                         OR (p.evidence_group = 'temperature' AND er.evidence_type IN ('temperature','thermal_stability','thermal_inactivation','temperature_range'))
                        )
                  )
            """,
        }
        for metric, sql in blocker_checks.items():
            count = value(conn, sql) or 0
            metrics[metric] = count
            if count:
                failures.append({"metric": metric, "value": count, "required": 0})

        scihub_count = count_scihub_artifacts()
        metrics["scihub_artifacts_remaining"] = scihub_count
        if scihub_count:
            failures.append({"metric": "scihub_artifacts_remaining", "value": scihub_count, "required": 0})

        forbidden_text_count = count_forbidden_release_text()
        metrics["forbidden_release_text_files"] = forbidden_text_count
        if forbidden_text_count:
            failures.append({"metric": "forbidden_release_text_files", "value": forbidden_text_count, "required": 0})

        tsv_policy_failures = release_tsv_policy_failures()
        metrics["release_tsv_policy_failures"] = len(tsv_policy_failures)
        failures.extend(tsv_policy_failures)

        api_failures = api_static_smoke_checks(conn)
        metrics["api_static_smoke_failures"] = len(api_failures)
        failures.extend(api_failures)

        download_failures = public_download_failures()
        metrics["public_download_failures"] = len(download_failures)
        failures.extend(download_failures)

        root_file_failures = required_root_file_failures()
        metrics["required_root_file_failures"] = len(root_file_failures)
        failures.extend(root_file_failures)

        warning_checks = {
            "strict_target_host_taxonomy_unverified": """
                SELECT COUNT(*)
                FROM analysis_strict_target_isolates ati
                JOIN isolate_curated_profiles icp ON icp.isolate_id = ati.isolate_id
                LEFT JOIN host_taxonomy_profiles htp ON htp.host_id = icp.host_id
                WHERE icp.host_id IS NOT NULL
                  AND (htp.host_id IS NULL OR (htp.is_crustacean IS NULL AND htp.is_target_host IS NULL))
            """,
            "ictv_status_mapping_count_inconsistent": """
                SELECT COUNT(*)
                FROM virus_ictv_status s
                WHERE COALESCE(s.mapping_count, -1) <> (
                    SELECT COUNT(*)
                    FROM virus_ictv_mappings m
                    WHERE m.master_id = s.master_id
                      AND m.match_status <> 'rejected'
                )
            """,
            "protein_function_rule_suggestions_unreviewed": """
                SELECT COUNT(*)
                FROM protein_function_suggestions
                WHERE needs_manual_review = 1
                  AND COALESCE(curator_decision, '') = ''
            """,
            "interpro_annotations_missing_span": """
                SELECT COUNT(*)
                FROM interpro_annotations
                WHERE start_pos IS NULL OR end_pos IS NULL
            """,
        }
        for metric, sql in warning_checks.items():
            count = value(conn, sql) or 0
            metrics[metric] = count
            if count:
                warnings.append({"metric": metric, "value": count, "required": 0})

        report = {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "strict_curation": not args.allow_curation_warnings,
            "allow_curation_warnings": args.allow_curation_warnings,
            "passed": not failures,
            "failures": failures,
            "warnings": warnings,
            "metrics": metrics,
        }
        out_json = REPORTS_DIR / f"release_gate_{generated_at}.json"
        out_md = REPORTS_DIR / f"release_gate_{generated_at}.md"
        out_json.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        lines = [
            "# Release Gate",
            "",
            f"Generated: {report['generated_at']}",
            f"Passed: `{report['passed']}`",
            f"Strict curation: `{not args.allow_curation_warnings}`",
            f"Allow curation warnings: `{args.allow_curation_warnings}`",
            "",
            "## Failures",
        ]
        if failures:
            for item in failures:
                lines.append(f"- {item}")
        else:
            lines.append("- None")
        lines += ["", "## Warnings"]
        if warnings:
            for item in warnings:
                lines.append(f"- {item}")
        else:
            lines.append("- None")
        lines += ["", "## Artifacts", f"- `{out_json}`"]
        out_md.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
