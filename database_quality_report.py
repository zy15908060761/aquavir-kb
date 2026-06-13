#!/usr/bin/env python3
"""
Generate a repeatable quality report for the crustacean virus database.

The report is intentionally strict: it separates database integrity, curation
coverage, evidence support, taxonomy status, and operational hygiene so the
remaining weaknesses are visible instead of hidden in aggregate counts.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any


DB_PATH = Path("crustacean_virus_core.db")
REPORTS_DIR = Path("reports")
SEQUENCES_DIR = Path("sequences")
SYNC_STATUS_PATH = Path("sync_runtime") / "sync_status.json"


def stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def rows(conn: sqlite3.Connection, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def value(conn: sqlite3.Connection, sql: str, params: tuple[Any, ...] = ()) -> Any:
    row = conn.execute(sql, params).fetchone()
    if row is None:
        return None
    return row[0]


def table_exists(conn: sqlite3.Connection, name: str) -> bool:
    return bool(value(conn, "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)))


def view_exists(conn: sqlite3.Connection, name: str) -> bool:
    return bool(value(conn, "SELECT 1 FROM sqlite_master WHERE type='view' AND name=?", (name,)))


def write_csv(path: Path, data: list[dict[str, Any]]) -> None:
    path.parent.mkdir(exist_ok=True)
    if not data:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(data[0].keys()))
        writer.writeheader()
        writer.writerows(data)


def sync_status() -> dict[str, Any]:
    if not SYNC_STATUS_PATH.exists():
        return {"present": False}
    try:
        data = json.loads(SYNC_STATUS_PATH.read_text(encoding="utf-8"))
    except Exception as exc:  # pragma: no cover - report should tolerate malformed ops files
        return {"present": True, "parse_error": str(exc)}
    pid = data.get("pid")
    running = False
    if isinstance(pid, int) and pid > 0:
        try:
            os.kill(pid, 0)
            running = True
        except OSError:
            running = False
    data["present"] = True
    data["pid_running"] = running
    return data


def issue(severity: str, category: str, metric: str, count: Any, recommendation: str) -> dict[str, Any]:
    return {
        "severity": severity,
        "category": category,
        "metric": metric,
        "count": count,
        "recommendation": recommendation,
    }


def generate(conn: sqlite3.Connection) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    report: dict[str, Any] = {}
    issues: list[dict[str, Any]] = []
    detail_exports: dict[str, list[dict[str, Any]]] = {}

    integrity = value(conn, "PRAGMA integrity_check")
    fk_rows = rows(conn, "PRAGMA foreign_key_check")
    report["integrity"] = {"integrity_check": integrity, "foreign_key_violations": len(fk_rows)}
    if integrity != "ok":
        issues.append(issue("critical", "integrity", "integrity_check", integrity, "Stop curation and repair SQLite integrity before any analysis."))
    if fk_rows:
        issues.append(issue("critical", "integrity", "foreign_key_violations", len(fk_rows), "Fix broken references before publishing or exporting the database."))
        detail_exports["foreign_key_violations"] = fk_rows

    report["table_counts"] = rows(
        conn,
        """
        SELECT name AS table_name,
               (SELECT COUNT(*) FROM sqlite_master sm2 WHERE sm2.name = sm.name) AS present
        FROM sqlite_master sm
        WHERE type='table'
        ORDER BY name
        """,
    )
    real_counts = []
    for item in report["table_counts"]:
        name = item["table_name"]
        if name.startswith("sqlite_"):
            continue
        real_counts.append({"table_name": name, "row_count": value(conn, f"SELECT COUNT(*) FROM {name}")})
    report["table_counts"] = real_counts

    total_isolates = value(conn, "SELECT COUNT(*) FROM viral_isolates") or 0
    target_isolates = value(conn, "SELECT COUNT(*) FROM analysis_target_isolates") if view_exists(conn, "analysis_target_isolates") else None
    if target_isolates is None:
        target_isolates = total_isolates
    non_target = total_isolates - int(target_isolates)
    report["scope"] = {
        "viral_isolates_total": total_isolates,
        "analysis_target_isolates": target_isolates,
        "excluded_or_non_target_isolates": non_target,
        "virus_master_total": value(conn, "SELECT COUNT(*) FROM virus_master"),
        "masters_without_isolates": value(conn, "SELECT COUNT(*) FROM virus_master vm LEFT JOIN viral_isolates vi ON vm.master_id=vi.master_id WHERE vi.isolate_id IS NULL"),
        "target_masters_without_isolates": value(
            conn,
            """
            SELECT COUNT(*)
            FROM virus_master vm
            LEFT JOIN viral_isolates vi ON vm.master_id=vi.master_id
            WHERE vi.isolate_id IS NULL
              AND vm.is_crustacean_virus = 1
              AND vm.entry_type NOT IN ('non_target', 'host_genome')
            """,
        ),
    }
    if report["scope"]["target_masters_without_isolates"]:
        issues.append(issue("high", "scope", "target_masters_without_isolates", report["scope"]["target_masters_without_isolates"], "Review whether these target master records are valid disease entities or orphan artifacts."))

    report["references"] = {
        "ref_literatures": value(conn, "SELECT COUNT(*) FROM ref_literatures"),
        "direct_isolate_references": value(conn, "SELECT COUNT(*) FROM viral_isolates WHERE reference_id IS NOT NULL"),
        "linked_isolate_references": value(conn, "SELECT COUNT(DISTINCT isolate_id) FROM isolate_reference_links") if table_exists(conn, "isolate_reference_links") else 0,
        "effective_isolate_references": value(
            conn,
            """
            SELECT COUNT(*)
            FROM viral_isolates vi
            WHERE vi.reference_id IS NOT NULL
               OR EXISTS (SELECT 1 FROM isolate_reference_links irl WHERE irl.isolate_id = vi.isolate_id)
            """,
        )
        if table_exists(conn, "isolate_reference_links")
        else value(conn, "SELECT COUNT(*) FROM viral_isolates WHERE reference_id IS NOT NULL"),
        "target_effective_isolate_references": value(
            conn,
            """
            SELECT COUNT(*)
            FROM analysis_target_isolates vi
            WHERE vi.reference_id IS NOT NULL
               OR EXISTS (SELECT 1 FROM isolate_reference_links irl WHERE irl.isolate_id = vi.isolate_id)
            """,
        )
        if table_exists(conn, "isolate_reference_links") and view_exists(conn, "analysis_target_isolates")
        else None,
        "references_without_title": value(conn, "SELECT COUNT(*) FROM ref_literatures WHERE title IS NULL OR TRIM(title)=''"),
        "references_without_year": value(conn, "SELECT COUNT(*) FROM ref_literatures WHERE year IS NULL OR TRIM(year)=''"),
        "references_without_identifier": value(
            conn,
            "SELECT COUNT(*) FROM ref_literatures WHERE (doi IS NULL OR TRIM(doi)='') AND (pmid IS NULL OR TRIM(pmid)='')",
        ),
    }
    reference_denominator = int(target_isolates) if report["references"]["target_effective_isolate_references"] is not None else total_isolates
    reference_covered = (
        report["references"]["target_effective_isolate_references"]
        if report["references"]["target_effective_isolate_references"] is not None
        else report["references"]["effective_isolate_references"]
    )
    missing_effective_refs = reference_denominator - int(reference_covered or 0)
    if missing_effective_refs:
        issues.append(issue("high", "evidence", "target_isolates_without_effective_reference", missing_effective_refs, "Do not treat these target isolates as literature-supported until a primary record or linked literature is attached."))

    report["diagnostics"] = {
        "status_counts": rows(
            conn,
            """
            SELECT data_quality, curation_status, COUNT(*) AS n
            FROM diagnostic_methods
            GROUP BY data_quality, curation_status
            ORDER BY n DESC
            """,
        ),
        "curated_without_reference": value(
            conn,
            "SELECT COUNT(*) FROM diagnostic_methods WHERE data_quality='curated' AND reference_id IS NULL",
        ),
        "placeholder_needs_review": value(
            conn,
            "SELECT COUNT(*) FROM diagnostic_methods WHERE data_quality='placeholder' AND curation_status='needs_review'",
        ),
    }
    if report["diagnostics"]["curated_without_reference"]:
        issues.append(issue("high", "diagnostics", "curated_without_reference", report["diagnostics"]["curated_without_reference"], "Curated diagnostic rows without references should be demoted or backed by primary method papers."))
    if report["diagnostics"]["placeholder_needs_review"]:
        issues.append(issue("medium", "diagnostics", "placeholder_needs_review", report["diagnostics"]["placeholder_needs_review"], "Keep these out of analysis views until manually verified or rejected."))

    report["ictv"] = {
        "status_counts": rows(conn, "SELECT ictv_status, COUNT(*) AS n FROM virus_ictv_status GROUP BY ictv_status ORDER BY n DESC"),
        "review_priority": rows(conn, "SELECT priority, COUNT(*) AS n FROM ictv_review_priority_queue GROUP BY priority ORDER BY CASE priority WHEN 'critical' THEN 0 WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END")
        if table_exists(conn, "ictv_review_priority_queue")
        else [],
    }
    pending_critical = value(conn, "SELECT COUNT(*) FROM ictv_review_priority_queue WHERE priority='critical'") if table_exists(conn, "ictv_review_priority_queue") else 0
    if pending_critical:
        issues.append(issue("critical", "taxonomy", "critical_ictv_review_items", pending_critical, "Resolve known disease viruses and high-impact unresolved master records before making taxonomy completeness claims."))

    report["geography"] = {
        "target_missing_country": value(
            conn,
            """
            SELECT COUNT(*)
            FROM analysis_target_isolates vi
            LEFT JOIN infection_records ir ON vi.isolate_id = ir.isolate_id
            LEFT JOIN sample_collections s ON ir.collection_id = s.collection_id
            LEFT JOIN isolate_curated_profiles icp ON vi.isolate_id = icp.isolate_id
            WHERE COALESCE(NULLIF(s.country,''), NULLIF(icp.country,'')) IS NULL
            """,
        )
        if view_exists(conn, "analysis_target_isolates")
        else None,
        "target_missing_coordinates": value(
            conn,
            """
            SELECT COUNT(*)
            FROM analysis_target_isolates vi
            LEFT JOIN infection_records ir ON vi.isolate_id = ir.isolate_id
            LEFT JOIN sample_collections s ON ir.collection_id = s.collection_id
            LEFT JOIN isolate_curated_profiles icp ON vi.isolate_id = icp.isolate_id
            WHERE COALESCE(s.latitude, icp.latitude) IS NULL
               OR COALESCE(s.longitude, icp.longitude) IS NULL
            """,
        )
        if view_exists(conn, "analysis_target_isolates")
        else None,
        "target_missing_continent": value(
            conn,
            """
            SELECT COUNT(*)
            FROM analysis_target_isolates vi
            LEFT JOIN infection_records ir ON vi.isolate_id = ir.isolate_id
            LEFT JOIN sample_collections s ON ir.collection_id = s.collection_id
            LEFT JOIN isolate_curated_profiles icp ON vi.isolate_id = icp.isolate_id
            WHERE COALESCE(NULLIF(s.continent,''), NULLIF(icp.continent,'')) IS NULL
            """,
        )
        if view_exists(conn, "analysis_target_isolates")
        else None,
        "invalid_coordinate_rows": value(
            conn,
            """
            SELECT COUNT(*)
            FROM sample_collections
            WHERE (latitude IS NOT NULL AND (latitude < -90 OR latitude > 90))
               OR (longitude IS NOT NULL AND (longitude < -180 OR longitude > 180))
            """,
        ),
    }
    if report["geography"]["target_missing_country"]:
        issues.append(issue("medium", "geography", "target_missing_country", report["geography"]["target_missing_country"], "Fill from GenBank/literature where possible; otherwise expose as unknown in map analysis."))
    if report["geography"]["target_missing_coordinates"]:
        issues.append(issue("medium", "geography", "target_missing_coordinates", report["geography"]["target_missing_coordinates"], "Coordinate-level maps must distinguish exact coordinates from country centroids or missing points."))

    fasta_count = len(list(SEQUENCES_DIR.glob("*.fasta"))) if SEQUENCES_DIR.exists() else 0
    report["sequences"] = {
        "isolate_has_sequence_flag": value(conn, "SELECT COUNT(*) FROM viral_isolates WHERE has_sequence=1"),
        "target_isolate_missing_sequence_length": value(conn, "SELECT COUNT(*) FROM analysis_target_isolates WHERE sequence_length IS NULL AND genome_length IS NULL")
        if view_exists(conn, "analysis_target_isolates")
        else value(conn, "SELECT COUNT(*) FROM viral_isolates WHERE sequence_length IS NULL AND genome_length IS NULL"),
        "fasta_files": fasta_count,
        "flagged_sequence_without_fasta": 0,
    }
    # The SQL above cannot see the file system; replace with a real accession/file check.
    if SEQUENCES_DIR.exists():
        fasta_stems = {p.stem for p in SEQUENCES_DIR.glob("*.fasta")}
        flagged = [dict(r) for r in conn.execute("SELECT isolate_id, accession FROM viral_isolates WHERE has_sequence=1")]
        missing_files = [r for r in flagged if r["accession"] not in fasta_stems]
        report["sequences"]["flagged_sequence_without_fasta"] = len(missing_files)
        detail_exports["flagged_sequence_without_fasta"] = missing_files[:500]
    if report["sequences"]["target_isolate_missing_sequence_length"]:
        issues.append(issue("medium", "sequence", "target_isolate_missing_sequence_length", report["sequences"]["target_isolate_missing_sequence_length"], "Genome-length dependent analyses should exclude these target rows or recover sequence metadata."))
    if report["sequences"]["flagged_sequence_without_fasta"]:
        issues.append(issue("medium", "sequence", "flagged_sequence_without_fasta", report["sequences"]["flagged_sequence_without_fasta"], "Synchronize sequence files with has_sequence flags before downstream ORF/phylogeny workflows."))

    report["evidence_records"] = {
        "status_counts": rows(
            conn,
            """
            SELECT evidence_type, curation_status, COUNT(*) AS n
            FROM evidence_records
            GROUP BY evidence_type, curation_status
            ORDER BY n DESC
            """,
        ),
        "needs_review": value(conn, "SELECT COUNT(*) FROM evidence_records WHERE curation_status='needs_review'"),
        "without_reference": value(conn, "SELECT COUNT(*) FROM evidence_records WHERE reference_id IS NULL"),
    }
    if report["evidence_records"]["needs_review"]:
        issues.append(issue("high", "evidence", "evidence_records_needs_review", report["evidence_records"]["needs_review"], "Do not use auto-extracted evidence as final claims until reviewed. Prioritize virulence, mortality, diagnosis, and host range."))

    report["conflicts"] = {
        "status_counts": rows(
            conn,
            """
            SELECT conflict_type, severity, status, COUNT(*) AS n
            FROM curation_conflicts
            GROUP BY conflict_type, severity, status
            ORDER BY status, n DESC
            """,
        )
        if table_exists(conn, "curation_conflicts")
        else [],
        "open_conflicts": value(conn, "SELECT COUNT(*) FROM curation_conflicts WHERE status='open'") if table_exists(conn, "curation_conflicts") else 0,
    }
    if report["conflicts"]["open_conflicts"]:
        issues.append(issue("high", "curation", "open_conflicts", report["conflicts"]["open_conflicts"], "Resolve or explicitly waive open curation conflicts; reviewers will treat unresolved taxonomy conflicts as unreliable curation."))

    archive_tables = [
        r["name"]
        for r in rows(
            conn,
            "SELECT name FROM sqlite_master WHERE type='table' AND (name LIKE '%archive%' OR name LIKE '\\_%' ESCAPE '\\') ORDER BY name",
        )
    ]
    report["operational_hygiene"] = {
        "archive_or_backup_tables": archive_tables,
        "root_underscore_python_scripts": sorted(str(p.name) for p in Path(".").glob("_*.py")),
        "sync_status": sync_status(),
    }
    if report["operational_hygiene"]["root_underscore_python_scripts"]:
        issues.append(issue("low", "maintenance", "root_underscore_python_scripts", len(report["operational_hygiene"]["root_underscore_python_scripts"]), "Archive one-off helper scripts so the project root contains reproducible maintenance entry points only."))
    sync = report["operational_hygiene"]["sync_status"]
    if sync.get("status") == "stale" or sync.get("overall_status") == "stale":
        issues.append(issue("medium", "operations", "sync_status_stale", 1, "Expose stale sync state in UI or restart the scheduled sync after reviewing failed steps."))

    if table_exists(conn, "ictv_review_priority_queue"):
        detail_exports["ictv_review_priority_queue"] = rows(
            conn,
            "SELECT * FROM ictv_review_priority_queue ORDER BY CASE priority WHEN 'critical' THEN 0 WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END, isolate_count DESC, canonical_name",
        )
    if table_exists(conn, "virus_master_review_queue"):
        detail_exports["virus_master_review_queue"] = rows(conn, "SELECT * FROM virus_master_review_queue ORDER BY severity, canonical_name")
    detail_exports["curated_diagnostics_without_reference"] = rows(
        conn,
        """
        SELECT method_id, virus_master_id, method_name, method_category, method_subcategory, curation_status
        FROM diagnostic_methods
        WHERE data_quality='curated' AND reference_id IS NULL
        ORDER BY virus_master_id, method_name
        """,
    )
    detail_exports["open_curation_conflicts"] = rows(
        conn,
        """
        SELECT conflict_id, entity_type, entity_id, field_name, value_a, source_a, value_b, source_b, conflict_type, severity, notes
        FROM curation_conflicts
        WHERE status='open'
        ORDER BY severity DESC, conflict_type, conflict_id
        """
    ) if table_exists(conn, "curation_conflicts") else []

    return report, issues, detail_exports


def markdown_report(report: dict[str, Any], issues: list[dict[str, Any]], artifact_paths: dict[str, str]) -> str:
    lines = [
        "# Crustacean Virus Database Quality Report",
        "",
        f"Generated: {datetime.now().isoformat(timespec='seconds')}",
        "",
        "## Executive Defects",
        "",
    ]
    if not issues:
        lines.append("No quality issues were detected by the automated checks.")
    else:
        for item in issues:
            lines.append(f"- **{item['severity']} / {item['category']}** `{item['metric']}` = {item['count']}: {item['recommendation']}")

    lines.extend(
        [
            "",
            "## Core Metrics",
            "",
            f"- Integrity check: `{report['integrity']['integrity_check']}`; foreign-key violations: `{report['integrity']['foreign_key_violations']}`",
            f"- Isolates: `{report['scope']['viral_isolates_total']}` total; `{report['scope']['analysis_target_isolates']}` analysis target; `{report['scope']['excluded_or_non_target_isolates']}` excluded/non-target",
            f"- References: `{report['references']['ref_literatures']}` literature rows; `{report['references']['effective_isolate_references']}` isolates with direct or linked reference",
            f"- ICTV: {json.dumps(report['ictv']['status_counts'], ensure_ascii=False)}",
            f"- Diagnostics: {json.dumps(report['diagnostics']['status_counts'], ensure_ascii=False)}",
            f"- Evidence records needing review: `{report['evidence_records']['needs_review']}`",
            f"- Open curation conflicts: `{report['conflicts']['open_conflicts']}`",
            "",
            "## Artifacts",
            "",
        ]
    )
    for label, path in artifact_paths.items():
        lines.append(f"- {label}: `{path}`")
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=str(DB_PATH))
    args = parser.parse_args()

    REPORTS_DIR.mkdir(exist_ok=True)
    ts = stamp()
    conn = connect(Path(args.db))
    report, issues, detail_exports = generate(conn)
    conn.close()

    json_path = REPORTS_DIR / f"database_quality_report_{ts}.json"
    issue_csv_path = REPORTS_DIR / f"database_quality_issues_{ts}.csv"
    md_path = REPORTS_DIR / f"database_quality_report_{ts}.md"

    detail_paths: dict[str, str] = {}
    for name, data in detail_exports.items():
        path = REPORTS_DIR / f"{name}_{ts}.csv"
        write_csv(path, data)
        detail_paths[name] = str(path)

    payload = {"timestamp": ts, "report": report, "issues": issues, "detail_exports": detail_paths}
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    write_csv(issue_csv_path, issues)
    artifact_paths = {"json": str(json_path), "issues_csv": str(issue_csv_path), **detail_paths}
    md_path.write_text(markdown_report(report, issues, artifact_paths), encoding="utf-8")

    print(
        json.dumps(
            {
                "json": str(json_path),
                "markdown": str(md_path),
                "issues_csv": str(issue_csv_path),
                "issue_count": len(issues),
                "critical_issues": sum(1 for i in issues if i["severity"] == "critical"),
                "high_issues": sum(1 for i in issues if i["severity"] == "high"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
