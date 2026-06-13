from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

from db_utils import get_db as _db_get_db

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "crustacean_virus_core.db"
DOWNLOADS_DIR = BASE_DIR / "downloads"


STEPS = [
    ("analysis_views", [sys.executable, "maintain_analysis_views.py"]),
    ("protein_bridge", [sys.executable, "build_protein_annotation_bridge.py"]),
    ("manual_review_queue", [sys.executable, "build_manual_review_priority_queue.py"]),
    ("auto_optimization", [sys.executable, "auto_optimize_completeness.py"]),
    ("quality_report", [sys.executable, "database_quality_report.py"]),
    ("release_gate", [sys.executable, "release_gate.py", "--allow-curation-warnings"]),
    ("manual_review_word", [sys.executable, "build_manual_review_word.py"]),
    ("release_bundle", [sys.executable, "build_release_bundle.py"]),
]


def scalar(conn: sqlite3.Connection, sql: str):
    return conn.execute(sql).fetchone()[0]


def pct(num: int, den: int) -> float:
    return round(num / den * 100, 2) if den else 0.0


def table_count(conn: sqlite3.Connection, table: str) -> int:
    try:
        return int(scalar(conn, f"SELECT COUNT(*) FROM {table}") or 0)
    except sqlite3.Error:
        return 0


def build_frontend_metrics() -> dict:
    conn = _db_get_db(wal_mode=True, timeout=60)
    try:
        # Use analysis_target_isolates (not strict) for public-facing numbers
        target_total = int(scalar(conn, "SELECT COUNT(*) FROM analysis_target_isolates") or 0)
        strict_total = int(scalar(conn, "SELECT COUNT(*) FROM analysis_strict_target_isolates") or 0)

        # Helper to count distinct hosts within a given isolate set
        def host_count_in_isolates(subquery_sql: str) -> int:
            try:
                return int(scalar(conn, f"""
                    SELECT COUNT(DISTINCT ir.host_id)
                    FROM infection_records ir
                    WHERE ir.isolate_id IN ({subquery_sql})
                      AND ir.host_id IS NOT NULL
                """) or 0)
            except sqlite3.Error:
                return 0

        # Helper to count distinct species within a given isolate set
        def species_count_in_isolates(subquery_sql: str) -> int:
            try:
                return int(scalar(conn, f"""
                    SELECT COUNT(DISTINCT vm.canonical_name)
                    FROM ({subquery_sql}) v
                    JOIN virus_master vm ON v.master_id = vm.master_id
                    WHERE vm.is_crustacean_virus = 1
                """) or 0)
            except sqlite3.Error:
                return 0

        target_hosts = host_count_in_isolates("SELECT isolate_id FROM analysis_target_isolates")
        strict_hosts = host_count_in_isolates("SELECT isolate_id FROM analysis_strict_target_isolates")
        target_species = species_count_in_isolates("SELECT * FROM analysis_target_isolates")
        strict_species = species_count_in_isolates("SELECT * FROM analysis_strict_target_isolates")

        total_isolates = table_count(conn, "viral_isolates")
        total_hosts = table_count(conn, "crustacean_hosts")
        total_species = table_count(conn, "virus_master")

        metrics = {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "database": {
                "integrity_check": scalar(conn, "PRAGMA integrity_check"),
                "foreign_key_violations": len(conn.execute("PRAGMA foreign_key_check").fetchall()),
            },
            "summary": {
                # Raw table counts (full database)
                "total_isolates": total_isolates,
                "total_hosts": total_hosts,
                "total_species": total_species,
                # Backward-compatible aliases (point to full DB)
                "viral_isolates": total_isolates,
                "crustacean_hosts": total_hosts,
                "virus_master": total_species,
                # analysis_target_isolates (publication-ready, excludes conflict_open)
                "target_isolates": target_total,
                "target_hosts": target_hosts,
                "target_species": target_species,
                # analysis_strict_target_isolates (strict publication subset)
                "strict_target_isolates": strict_total,
                "strict_target_hosts": strict_hosts,
                "strict_target_species": strict_species,
                # Scope explanation
                "scope_note": (
                    "total_* = raw table counts (full database); "
                    "target_* = analysis_target_isolates (publication set, conflict_open excluded); "
                    "strict_target_* = analysis_strict_target_isolates (also excludes unpublished candidates)"
                ),
                "viral_proteins": table_count(conn, "viral_proteins"),
            },
            "target_completeness": {},
            "protein_annotation_bridge": {},
            "enrichment_counts": {},
            "prediction_models": {},
            "data_provenance": {},
        }
        for key, field in [
            ("host", "has_host"),
            ("country", "has_country"),
            ("coordinates", "has_coordinates"),
            ("collection_year", "has_collection_year"),
            ("isolation_source", "has_isolation_source"),
            ("genome_type", "has_genome_type"),
            ("reference", "has_reference"),
        ]:
            count = int(
                scalar(
                    conn,
                    f"""
                    SELECT COALESCE(SUM({field}), 0)
                    FROM analysis_isolate_completeness
                    WHERE isolate_id IN (SELECT isolate_id FROM analysis_target_isolates)
                    """,
                )
                or 0
            )
            metrics["target_completeness"][key] = {
                "count": count,
                "total": target_total,
                "pct": pct(count, target_total),
            }

        protein_total = table_count(conn, "viral_proteins")
        for key, field in [
            ("uniprot", "has_uniprot"),
            ("interpro", "has_interpro"),
            ("go", "has_interpro_go"),
            ("kegg", "has_kegg"),
            ("structure", "has_structure"),
        ]:
            count = int(
                scalar(conn, f"SELECT COUNT(DISTINCT protein_id) FROM protein_annotation_bridge WHERE {field}=1")
                or 0
            )
            metrics["protein_annotation_bridge"][key] = {
                "count": count,
                "total": protein_total,
                "pct": pct(count, protein_total),
            }

        for table in [
            "uniprot_annotations",
            "interpro_annotations",
            "kegg_annotations",
            "kegg_pathways",
            "uniprot_structures",
            "geo_datasets",
            "sra_runs",
            "gbif_occurrences",
            "obis_occurrences",
            "biorxiv_preprints",
            "pride_datasets",
            "string_interactions",
            "viralzone_families",
            "ictv_taxonomy",
            "ictv_vmr",
        ]:
            metrics["enrichment_counts"][table] = table_count(conn, table)

        # Curated/predicted/requires_review breakdown for virulence/temperature profiles
        metrics["prediction_models"] = {
            "scope_note": (
                "Predicted profiles are family-level inferences and should NOT "
                "be used for primary scientific claims. 'curated' = curator-reviewed "
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
            "model_performance_metrics_rows": table_count(conn, "model_performance_metrics"),
        }

        metrics["data_provenance"] = {
            "total_rows": table_count(conn, "data_provenance"),
            "tables_covered": int(scalar(
                conn,
                "SELECT COUNT(DISTINCT table_name) FROM data_provenance",
            ) or 0),
        }

        return metrics
    finally:
        conn.close()


def write_frontend_metrics() -> Path:
    DOWNLOADS_DIR.mkdir(exist_ok=True)
    metrics = build_frontend_metrics()
    out = DOWNLOADS_DIR / "frontend_dashboard_metrics.json"
    out.write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def run_step(name: str, cmd: list[str], continue_on_error: bool = False) -> dict:
    started = time.time()
    proc = subprocess.run(
        cmd,
        cwd=BASE_DIR,
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
    )
    result = {
        "name": name,
        "cmd": cmd,
        "returncode": proc.returncode,
        "seconds": round(time.time() - started, 2),
        "stdout_tail": proc.stdout[-4000:],
        "stderr_tail": proc.stderr[-4000:],
    }
    if proc.returncode != 0 and not continue_on_error:
        raise RuntimeError(f"{name} failed with code {proc.returncode}\n{proc.stderr[-2000:]}")
    return result


def smoke_test(port: int = 8899) -> dict:
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "backend:app", "--host", "127.0.0.1", "--port", str(port)],
        cwd=BASE_DIR,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        time.sleep(4)
        checks = {}
        for path in ["/api/stats", "/api/stats/proteins", "/api/stats/completeness_release", "/stats"]:
            url = f"http://127.0.0.1:{port}{path}"
            with urllib.request.urlopen(url, timeout=20) as resp:
                body = resp.read(1000)
                checks[path] = {"status": resp.status, "bytes_sample": len(body)}
        return checks
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


def main() -> None:
    parser = argparse.ArgumentParser(description="Refresh frontend-facing data after database updates.")
    parser.add_argument("--skip-smoke", action="store_true", help="Skip local FastAPI smoke test")
    parser.add_argument("--continue-on-error", action="store_true", help="Continue even if a refresh step fails")
    parser.add_argument("--port", type=int, default=8899, help="Temporary smoke-test port")
    args = parser.parse_args()

    run_ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    report = {
        "run_ts": run_ts,
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "steps": [],
        "frontend_metrics": None,
        "smoke_test": None,
    }

    for name, cmd in STEPS:
        print(f"[sync] {name} ...")
        result = run_step(name, cmd, continue_on_error=args.continue_on_error)
        report["steps"].append(result)
        print(f"[sync] {name} done code={result['returncode']} seconds={result['seconds']}")

    metrics_path = write_frontend_metrics()
    report["frontend_metrics"] = str(metrics_path)
    print(f"[sync] frontend metrics: {metrics_path}")

    if not args.skip_smoke:
        print("[sync] smoke test ...")
        report["smoke_test"] = smoke_test(args.port)
        print(json.dumps(report["smoke_test"], ensure_ascii=False, indent=2))

    report["completed_at"] = datetime.now().isoformat(timespec="seconds")
    out = BASE_DIR / "reports" / f"frontend_sync_{run_ts}.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[sync] report: {out}")


if __name__ == "__main__":
    main()
