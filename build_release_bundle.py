from __future__ import annotations

import csv
import hashlib
import json
import argparse
import shutil
import sqlite3
import subprocess
import sys
from datetime import datetime
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "crustacean_virus_core.db"
REPORT_DIR = BASE_DIR / "reports"
RELEASE_ROOT = BASE_DIR / "releases"


def scalar(conn: sqlite3.Connection, sql: str) -> int | str | float | None:
    return conn.execute(sql).fetchone()[0]


def table_count(conn: sqlite3.Connection, table: str) -> int:
    try:
        return int(scalar(conn, f"SELECT COUNT(*) FROM {table}") or 0)
    except sqlite3.OperationalError:
        return 0


def pct(num: int, den: int) -> float:
    return round(num / den * 100, 2) if den else 0.0


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def run_release_gate(allow_curation_warnings: bool = False) -> None:
    cmd = [sys.executable, str(BASE_DIR / "release_gate.py")]
    if allow_curation_warnings:
        cmd.append("--allow-curation-warnings")
    result = subprocess.run(
        cmd,
        cwd=BASE_DIR,
        text=True,
        capture_output=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            "Strict release gate failed; refusing to build a public release bundle.\n"
            + result.stdout
            + result.stderr
        )


def export_schema(conn: sqlite3.Connection, out_file: Path) -> None:
    rows = conn.execute(
        """
        SELECT type, name, sql
        FROM sqlite_master
        WHERE sql IS NOT NULL
          AND name NOT LIKE 'sqlite_%'
        ORDER BY type, name
        """
    ).fetchall()
    with out_file.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(f"-- {row['type']}: {row['name']}\n")
            f.write(row["sql"].rstrip() + ";\n\n")


TARGET_MASTER_WITHOUT_ISOLATE_SQL = """
    SELECT COUNT(*)
    FROM virus_master vm
    LEFT JOIN viral_isolates vi ON vi.master_id = vm.master_id
    WHERE vi.isolate_id IS NULL
      AND vm.is_crustacean_virus = 1
      AND vm.entry_type NOT IN ('non_target', 'host_genome')
"""


def dashboard_metrics(conn: sqlite3.Connection) -> dict:
    target = int(scalar(conn, "SELECT COUNT(*) FROM analysis_target_isolates") or 0)
    target_filter = "isolate_id IN (SELECT isolate_id FROM analysis_target_isolates)"
    host = int(scalar(conn, f"SELECT COALESCE(SUM(has_host), 0) FROM analysis_isolate_completeness WHERE {target_filter}") or 0)
    country = int(scalar(conn, f"SELECT COALESCE(SUM(has_country), 0) FROM analysis_isolate_completeness WHERE {target_filter}") or 0)
    genome = int(scalar(conn, f"SELECT COALESCE(SUM(has_genome_type), 0) FROM analysis_isolate_completeness WHERE {target_filter}") or 0)
    ref = int(scalar(conn, f"SELECT COALESCE(SUM(has_reference), 0) FROM analysis_isolate_completeness WHERE {target_filter}") or 0)

    proteins = table_count(conn, "viral_proteins")
    bridge_rows = table_count(conn, "protein_annotation_bridge")
    protein_uniprot = int(scalar(conn, "SELECT COUNT(DISTINCT protein_id) FROM protein_annotation_bridge WHERE has_uniprot=1") or 0)
    protein_interpro = int(scalar(conn, "SELECT COUNT(DISTINCT protein_id) FROM protein_annotation_bridge WHERE has_interpro=1") or 0)
    protein_kegg = int(scalar(conn, "SELECT COUNT(DISTINCT protein_id) FROM protein_annotation_bridge WHERE has_kegg=1") or 0)
    protein_structure = int(scalar(conn, "SELECT COUNT(DISTINCT protein_id) FROM protein_annotation_bridge WHERE has_structure=1") or 0)

    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "database": {
            "path": str(DB_PATH),
            "size_bytes": DB_PATH.stat().st_size,
            "integrity_check": scalar(conn, "PRAGMA integrity_check"),
            "foreign_key_violations": len(conn.execute("PRAGMA foreign_key_check").fetchall()),
        },
        "core_counts": {
            "virus_master": table_count(conn, "virus_master"),
            "viral_isolates": table_count(conn, "viral_isolates"),
            "analysis_target_isolates": target,
            "crustacean_hosts": table_count(conn, "crustacean_hosts"),
            "ref_literatures": table_count(conn, "ref_literatures"),
            "viral_proteins": proteins,
        },
        "target_completeness": {
            "scope_note": "All numerators are restricted to analysis_target_isolates; values above 100% are invalid.",
            "has_host": {"count": host, "total": target, "pct": pct(host, target)},
            "has_country": {"count": country, "total": target, "pct": pct(country, target)},
            "has_genome_type": {"count": genome, "total": target, "pct": pct(genome, target)},
            "has_reference": {"count": ref, "total": target, "pct": pct(ref, target)},
        },
        "external_sources": {
            "geo_datasets": table_count(conn, "geo_datasets"),
            "sra_runs": table_count(conn, "sra_runs"),
            "gbif_occurrences": table_count(conn, "gbif_occurrences"),
            "obis_occurrences": table_count(conn, "obis_occurrences"),
            "biorxiv_preprints": table_count(conn, "biorxiv_preprints"),
            "pride_datasets": table_count(conn, "pride_datasets"),
            "ictv_taxonomy": table_count(conn, "ictv_taxonomy"),
            "ictv_vmr": table_count(conn, "ictv_vmr"),
            "viralzone_families": table_count(conn, "viralzone_families"),
        },
        "protein_annotation": {
            "bridge_rows": bridge_rows,
            "has_uniprot": {"count": protein_uniprot, "total": proteins, "pct": pct(protein_uniprot, proteins)},
            "has_interpro": {"count": protein_interpro, "total": proteins, "pct": pct(protein_interpro, proteins)},
            "has_kegg": {"count": protein_kegg, "total": proteins, "pct": pct(protein_kegg, proteins)},
            "has_structure": {"count": protein_structure, "total": proteins, "pct": pct(protein_structure, proteins)},
        },
        "manual_review_remaining": {
            "evidence_needs_review": int(scalar(conn, "SELECT COUNT(*) FROM evidence_records WHERE curation_status='needs_review'") or 0),
            "diagnostic_methods_need_review": int(scalar(conn, "SELECT COUNT(*) FROM diagnostic_methods WHERE curation_status='needs_review'") or 0),
            "ictv_pending_review": int(scalar(conn, "SELECT COUNT(*) FROM virus_ictv_status WHERE ictv_status='pending_review'") or 0),
            "target_master_without_isolate": int(scalar(conn, TARGET_MASTER_WITHOUT_ISOLATE_SQL) or 0),
        },
        "prediction_models": {
            "scope_note": (
                "Predicted profiles are family-level inferences and should NOT be "
                "used for primary scientific claims. 'curated' = curator-reviewed "
                "literature summary; 'requires_review' = not yet curator-verified; "
                "'predicted_family_inferred' = family-level inference only."
            ),
            "virulence_profiles": {
                "total": table_count(conn, "virulence_profiles"),
                "curated": int(scalar(
                    conn,
                    "SELECT COUNT(*) FROM virulence_profiles WHERE publication_use = 'curated_summary_requires_reference_check'",
                ) or 0),
                "requires_review": int(scalar(
                    conn,
                    "SELECT COUNT(*) FROM virulence_profiles WHERE publication_use = 'candidate_requires_reference_check'",
                ) or 0),
                "predicted_family_inferred": int(scalar(
                    conn,
                    "SELECT COUNT(*) FROM virulence_profiles WHERE publication_use = 'candidate_not_for_primary_claims'",
                ) or 0),
            },
            "temperature_profiles": {
                "total": table_count(conn, "temperature_profiles"),
                "curated": int(scalar(
                    conn,
                    "SELECT COUNT(*) FROM temperature_profiles WHERE publication_use = 'curated_summary_requires_reference_check'",
                ) or 0),
                "requires_review": int(scalar(
                    conn,
                    "SELECT COUNT(*) FROM temperature_profiles WHERE publication_use = 'candidate_requires_reference_check'",
                ) or 0),
                "predicted_family_inferred": int(scalar(
                    conn,
                    "SELECT COUNT(*) FROM temperature_profiles WHERE publication_use = 'candidate_not_for_primary_claims'",
                ) or 0),
            },
        },
        "model_performance": {
            "metrics_table_rows": table_count(conn, "model_performance_metrics"),
            "scope_note": (
                "Model accuracy, recall, F1, and cross-validation results are "
                "recorded in model_performance_metrics. Verify that metric values "
                "are populated (non-zero) before citing model quality."
            ),
        },
        "data_provenance": {
            "total_rows": table_count(conn, "data_provenance"),
            "tables_covered": int(scalar(
                conn,
                "SELECT COUNT(DISTINCT table_name) FROM data_provenance",
            ) or 0),
            "scope_note": "Provenance records trace each row to its source (NCBI, PubMed, API, etc.).",
        },
        "release_files": {
            "database_sha256": sha256_file(DB_PATH),
        },
    }


def latest_files(pattern: str, limit: int = 1) -> list[Path]:
    files = sorted(REPORT_DIR.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    return files[:limit]


def export_key_tables(conn: sqlite3.Connection, out_dir: Path) -> None:
    exports = {
        "dashboard_counts.csv": """
            SELECT 'virus_master' AS metric, COUNT(*) AS value FROM virus_master
            UNION ALL SELECT 'viral_isolates', COUNT(*) FROM viral_isolates
            UNION ALL SELECT 'target_isolates', COUNT(*) FROM analysis_target_isolates
            UNION ALL SELECT 'crustacean_hosts', COUNT(*) FROM crustacean_hosts
            UNION ALL SELECT 'viral_proteins', COUNT(*) FROM viral_proteins
            UNION ALL SELECT 'protein_annotation_bridge', COUNT(*) FROM protein_annotation_bridge
        """,
        "target_isolate_completeness_sample.csv": """
            SELECT isolate_id, accession, virus_name, host_id, host_scientific_name,
                   country, collection_year, genome_type, has_reference
            FROM analysis_isolate_completeness
            ORDER BY isolate_id
            LIMIT 5000
        """,
        "protein_annotation_bridge_sample.csv": """
            SELECT protein_id, isolate_id, protein_accession, uniprot_id,
                   annotation_sources, has_uniprot, has_interpro, has_kegg, has_structure,
                   match_method
            FROM protein_annotation_bridge
            ORDER BY protein_id, uniprot_id
            LIMIT 50000
        """,
    }

    for name, sql in exports.items():
        rows = conn.execute(sql).fetchall()
        path = out_dir / name
        with path.open("w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(rows[0].keys() if rows else ["metric", "value"])
            for row in rows:
                writer.writerow([row[k] for k in row.keys()])


def write_readme(out_dir: Path, metrics: dict, copied_reports: list[str], release_status: str) -> None:
    readme = out_dir / "README.md"
    tc = metrics["target_completeness"]
    pa = metrics["protein_annotation"]
    readme.write_text(
        f"""# Crustacean Virus Database Release

Generated at: {metrics['generated_at']}

Release status: {release_status}

## Integrity

- SQLite integrity_check: {metrics['database']['integrity_check']}
- Foreign key violations: {metrics['database']['foreign_key_violations']}

## Core Coverage

- Target isolates: {metrics['core_counts']['analysis_target_isolates']}
- Host coverage: {tc['has_host']['count']}/{tc['has_host']['total']} ({tc['has_host']['pct']}%)
- Country coverage: {tc['has_country']['count']}/{tc['has_country']['total']} ({tc['has_country']['pct']}%)
- Genome type coverage: {tc['has_genome_type']['count']}/{tc['has_genome_type']['total']} ({tc['has_genome_type']['pct']}%)
- Reference coverage: {tc['has_reference']['count']}/{tc['has_reference']['total']} ({tc['has_reference']['pct']}%)

## Protein Annotation

- Proteins: {metrics['core_counts']['viral_proteins']}
- UniProt: {pa['has_uniprot']['count']} ({pa['has_uniprot']['pct']}%)
- InterPro: {pa['has_interpro']['count']} ({pa['has_interpro']['pct']}%)
- KEGG: {pa['has_kegg']['count']} ({pa['has_kegg']['pct']}%)
- Structure: {pa['has_structure']['count']} ({pa['has_structure']['pct']}%)

## Manual Review Remaining

- Evidence records: {metrics['manual_review_remaining']['evidence_needs_review']}
- Diagnostic methods: {metrics['manual_review_remaining']['diagnostic_methods_need_review']}
- ICTV pending: {metrics['manual_review_remaining']['ictv_pending_review']}
- Target master without isolate: {metrics['manual_review_remaining']['target_master_without_isolate']}

## Included Reports

{chr(10).join(f'- {name}' for name in copied_reports)}
""",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a CrustaVirus DB release bundle.")
    parser.add_argument(
        "--internal-rc",
        action="store_true",
        help="Build an internal release-candidate bundle while unresolved manual curation warnings remain.",
    )
    args = parser.parse_args()

    run_release_gate(allow_curation_warnings=args.internal_rc)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    prefix = "release_candidate" if args.internal_rc else "release"
    out_dir = RELEASE_ROOT / f"{prefix}_{stamp}"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "reports").mkdir(exist_ok=True)
    (out_dir / "exports").mkdir(exist_ok=True)

    conn = sqlite3.connect(DB_PATH, timeout=60)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys=ON")
        metrics = dashboard_metrics(conn)
        shutil.copy2(DB_PATH, out_dir / "crustacean_virus_core.db")
        export_schema(conn, out_dir / "schema.sql")
        (out_dir / "dashboard_metrics.json").write_text(
            json.dumps(metrics, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        export_key_tables(conn, out_dir / "exports")

        # Export full TSV set (from current DB — always consistent)
        from export_release_tsvs import export_table_to_tsv, EXPORT_TABLES
        tsv_dir = out_dir / "exports" / "tsv"
        tsv_dir.mkdir(parents=True, exist_ok=True)
        print("Exporting TSVs for release bundle...")
        for table in EXPORT_TABLES:
            result = export_table_to_tsv(conn, table, tsv_dir)
            if result.get("status") not in ("skipped", "empty"):
                print(f"  {result['table']}: {result['rows']} rows")
    finally:
        conn.close()

    copied = []
    for pattern in [
        "database_quality_report_*.md",
        "database_quality_report_*.json",
        "release_gate_*.md",
        "manual_review_workbook_*.docx",
        "traceable_completeness_fills_*.json",
        "protein_annotation_bridge_*.json",
    ]:
        for src in latest_files(pattern, limit=1):
            dst = out_dir / "reports" / src.name
            shutil.copy2(src, dst)
            copied.append(f"reports/{src.name}")

    manifest_rows = []
    for path in sorted(p for p in out_dir.rglob("*") if p.is_file()):
        manifest_rows.append({
            "path": str(path.relative_to(out_dir)).replace("\\", "/"),
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        })
    with (out_dir / "SHA256SUMS.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["path", "bytes", "sha256"])
        writer.writeheader()
        writer.writerows(manifest_rows)

    release_status = (
        "internal release candidate; unresolved manual curation warnings remain"
        if args.internal_rc
        else "strict public release"
    )
    write_readme(out_dir, metrics, copied, release_status)
    print(out_dir)


if __name__ == "__main__":
    main()
