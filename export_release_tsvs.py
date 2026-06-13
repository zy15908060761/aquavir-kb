#!/usr/bin/env python3
"""Export core database tables as TSV files for release packages.

Addresses CRITICAL gap C-R1: the existing TSV files in downloads/
are stale and inconsistent with the live database. This script
exports fresh TSVs directly from the current database state.

Usage:
    python export_release_tsvs.py                    # Export to downloads/
    python export_release_tsvs.py --out-dir releases/rc_xxx/exports  # Custom dir
    python export_release_tsvs.py --table viral_isolates  # Single table
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path

from db_utils import get_db

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "crustacean_virus_core.db"
DEFAULT_OUT_DIR = BASE_DIR / "downloads" / "exports"

# Tables to export, in logical order for reviewers
EXPORT_TABLES = [
    # ── Core data tables ──
    "virus_master",
    "viral_isolates",
    "crustacean_hosts",
    "sample_collections",
    "ref_literatures",
    "infection_records",
    "analysis_reviewed_evidence_records",
    # ── Protein annotation ──
    "viral_proteins",
    "uniprot_annotations",
    "interpro_annotations",
    "interpro_go_terms",
    "kegg_annotations",
    "kegg_pathways",
    "uniprot_structures",
    # ── Prediction ──
    # ── External & enrichment ──
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
    # ── Metadata ──
    "data_provenance",
    "database_maintenance_log",
]

PUBLIC_EXPORTS = {
    "virus_master": {
        "curation_scope": "release_filtered_master_records",
        "allowed_statuses": "masters represented in analysis_strict_target_isolates",
        "sql": """
            SELECT DISTINCT vm.*
            FROM virus_master vm
            JOIN analysis_strict_target_isolates ati ON ati.master_id = vm.master_id
            ORDER BY vm.master_id
        """,
    },
    "viral_isolates": {
        "curation_scope": "release_filtered_strict_target_isolates",
        "allowed_statuses": "analysis_strict_target_isolates; curation columns included for transparency",
        "sql": """
            SELECT ati.*,
                   icp.curation_status,
                   icp.dataset_tier,
                   icp.confidence AS curation_confidence
            FROM analysis_strict_target_isolates ati
            LEFT JOIN isolate_curated_profiles icp ON icp.isolate_id = ati.isolate_id
            ORDER BY ati.accession
        """,
    },
    "crustacean_hosts": {
        "curation_scope": "hosts_linked_to_release_filtered_isolates",
        "allowed_statuses": "hosts linked through strict target infection records",
        "sql": """
            SELECT DISTINCT h.*
            FROM crustacean_hosts h
            JOIN infection_records ir ON ir.host_id = h.host_id
            JOIN analysis_strict_target_isolates ati ON ati.isolate_id = ir.isolate_id
            ORDER BY h.host_id
        """,
    },
    "sample_collections": {
        "curation_scope": "collections_linked_to_release_filtered_isolates",
        "allowed_statuses": "collections linked through strict target infection records",
        "sql": """
            SELECT DISTINCT sc.*
            FROM sample_collections sc
            JOIN infection_records ir ON ir.collection_id = sc.collection_id
            JOIN analysis_strict_target_isolates ati ON ati.isolate_id = ir.isolate_id
            ORDER BY sc.collection_id
        """,
    },
    "ref_literatures": {
        "curation_scope": "references_linked_to_release_filtered_isolates_or_reviewed_evidence",
        "allowed_statuses": "references used by strict target isolates or manual-reviewed evidence",
        "sql": """
            SELECT DISTINCT rl.*
            FROM ref_literatures rl
            WHERE rl.reference_id IN (
                SELECT reference_id FROM analysis_strict_target_isolates WHERE reference_id IS NOT NULL
                UNION
                SELECT reference_id FROM analysis_reviewed_evidence_records WHERE reference_id IS NOT NULL
            )
            ORDER BY rl.reference_id
        """,
    },
    "infection_records": {
        "curation_scope": "release_filtered_host_isolate_edges",
        "allowed_statuses": "edges linked to strict target isolates",
        "sql": """
            SELECT ir.*
            FROM infection_records ir
            JOIN analysis_strict_target_isolates ati ON ati.isolate_id = ir.isolate_id
            ORDER BY ir.record_id
        """,
    },
    "analysis_reviewed_evidence_records": {
        "curation_scope": "manual_checked_evidence_only",
        "allowed_statuses": "curation_status='manual_checked'",
        "sql": "SELECT * FROM analysis_reviewed_evidence_records ORDER BY evidence_id",
    },
    "viral_proteins": {
        "curation_scope": "source_derived_proteins_for_release_filtered_isolates",
        "allowed_statuses": "excludes rule_suggested_unreviewed functional assertions",
        "sql": """
            SELECT vp.*
            FROM viral_proteins vp
            JOIN analysis_strict_target_isolates ati ON ati.isolate_id = vp.isolate_id
            WHERE COALESCE(vp.functional_annotation_status, '') <> 'rule_suggested_unreviewed'
            ORDER BY vp.protein_id
        """,
    },
    "data_provenance": {
        "curation_scope": "release_provenance_trace",
        "allowed_statuses": "excludes confidence_level in inferred/predicted/unverified",
        "sql": """
            SELECT *
            FROM data_provenance
            WHERE COALESCE(confidence_level, '') NOT IN ('inferred', 'predicted', 'unverified')
            ORDER BY provenance_id
        """,
    },
}

for _table_name in [
    "uniprot_annotations",
    "interpro_annotations",
    "interpro_go_terms",
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
    "database_maintenance_log",
]:
    PUBLIC_EXPORTS[_table_name] = {
        "curation_scope": "source_index_or_annotation",
        "allowed_statuses": "public source-derived records; not manual-reviewed evidence",
        "sql": f"SELECT * FROM {_table_name}",
    }


def table_exists(conn, name: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (name,),
    ).fetchone() is not None


def relation_exists(conn, name: str) -> str | None:
    row = conn.execute(
        "SELECT type FROM sqlite_master WHERE type IN ('table', 'view') AND name=?",
        (name,),
    ).fetchone()
    return None if row is None else row[0]


def export_table_to_tsv(conn, table: str, out_dir: Path) -> dict:
    """Export one release-safe TSV. Returns {table, path, rows, bytes, sha256}."""
    spec = PUBLIC_EXPORTS.get(table)
    source_kind = relation_exists(conn, table)
    if spec is None and source_kind is None:
        return {"table": table, "status": "skipped", "reason": "table_or_view_not_found"}

    sql = spec["sql"] if spec else f"SELECT * FROM {table}"
    rows = conn.execute(sql).fetchall()
    filter_sql = " ".join(sql.split())
    if not rows:
        return {
            "table": table,
            "status": "empty",
            "rows": 0,
            "curation_scope": spec.get("curation_scope") if spec else "raw_table",
            "allowed_statuses": spec.get("allowed_statuses") if spec else "unfiltered",
            "row_filter_sql": filter_sql,
        }

    out_path = out_dir / f"{table}.tsv"
    with out_path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f, delimiter="\t")
        writer.writerow(rows[0].keys())
        for row in rows:
            writer.writerow([row[k] for k in row.keys()])

    file_size = out_path.stat().st_size
    sha = hashlib.sha256(out_path.read_bytes()).hexdigest()

    return {
        "table": table,
        "source_kind": source_kind,
        "path": str(out_path.relative_to(out_dir.parent)),
        "rows": len(rows),
        "bytes": file_size,
        "sha256": sha,
        "curation_scope": spec.get("curation_scope") if spec else "raw_table",
        "allowed_statuses": spec.get("allowed_statuses") if spec else "unfiltered",
        "row_filter_sql": filter_sql,
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Export database tables as TSV files for release."
    )
    parser.add_argument(
        "--out-dir", type=Path, default=DEFAULT_OUT_DIR,
        help="Output directory for TSV files",
    )
    parser.add_argument(
        "--table", type=str,
        help="Export a single table instead of all",
    )
    parser.add_argument(
        "--skip-empty", action="store_true",
        help="Skip empty tables",
    )
    args = parser.parse_args(argv)

    args.out_dir.mkdir(parents=True, exist_ok=True)

    conn = get_db(db_path=DB_PATH, wal_mode=True, timeout=60)
    manifest = {
        "exported_at": datetime.now().isoformat(timespec="seconds"),
        "database_path": str(DB_PATH),
        "database_size_bytes": DB_PATH.stat().st_size,
        "tables": [],
        "summary": {
            "total_tables_exported": 0,
            "total_rows": 0,
            "total_bytes": 0,
        },
    }

    try:
        tables_to_export = [args.table] if args.table else EXPORT_TABLES

        for table in tables_to_export:
            result = export_table_to_tsv(conn, table, args.out_dir)
            manifest["tables"].append(result)

            if result.get("status") == "skipped" and not args.skip_empty:
                print(f"  SKIP {table}: {result.get('reason', 'unknown')}")
            elif result.get("status") == "empty":
                print(f"  EMPTY {table}: 0 rows")
            else:
                print(f"  {table}: {result['rows']} rows → {result['path']}")
                manifest["summary"]["total_tables_exported"] += 1
                manifest["summary"]["total_rows"] += result["rows"]
                manifest["summary"]["total_bytes"] += result["bytes"]

    finally:
        conn.close()

    # Write manifest
    manifest_path = args.out_dir / "tsv_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"\nExported {manifest['summary']['total_tables_exported']} tables, "
          f"{manifest['summary']['total_rows']} total rows "
          f"({manifest['summary']['total_bytes'] / 1024 / 1024:.1f} MB)")
    print(f"Manifest: {manifest_path}")

    # Verify against database
    print("\n--- Verification against live database ---")
    conn2 = get_db(db_path=DB_PATH, wal_mode=True, timeout=60)
    try:
        ok = True
        for t in manifest["tables"]:
            if t.get("status") in ("skipped", "empty"):
                continue
            spec = PUBLIC_EXPORTS.get(t["table"])
            count_sql = (
                f"SELECT COUNT(*) FROM ({spec['sql']})"
                if spec
                else f"SELECT COUNT(*) FROM {t['table']}"
            )
            db_count = conn2.execute(count_sql).fetchone()[0]
            if db_count != t["rows"]:
                print(f"  MISMATCH {t['table']}: TSV has {t['rows']} rows, DB has {db_count}")
                ok = False
        if ok:
            print("  All TSV row counts match database. OK")
    finally:
        conn2.close()


if __name__ == "__main__":
    main()
