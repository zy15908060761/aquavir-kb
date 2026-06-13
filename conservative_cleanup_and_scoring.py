#!/usr/bin/env python3
"""Conservative cleanup and evidence scoring for AquaVir-KB.

This script does not delete scientific source records except orphan child rows
that violate foreign keys and cannot be made valid because their FK columns are
NOT NULL. Those rows are copied into a quarantine table first.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

from db_utils import DB_PATH
from schema_version import SchemaTracker


APP_DIR = Path(__file__).resolve().parent
REPORTS_DIR = APP_DIR / "reports"
SCRIPT_NAME = Path(__file__).name

TARGET_PHYLA = {
    "Arthropoda",
    "Mollusca",
    "Echinodermata",
    "Cnidaria",
    "Porifera",
    "Annelida",
    "Platyhelminthes",
    "Nematoda",
}

CONFIRMED_HOST_METHODS = {"confirmed_infection", "experimental_infection"}
DISEASE_HOST_METHODS = {"disease_outbreak", "pathology_observation"}
WEAK_HOST_METHODS = {
    "metagenomic",
    "co_occurrence_metagenomic",
    "database_annotation",
    "ncbi_annotation",
    "name_inference",
    "phylum_inference",
    "environmental_sample",
}


def row_to_json(row: sqlite3.Row) -> str:
    return json.dumps(dict(row), ensure_ascii=False, sort_keys=True)


def table_columns(conn: sqlite3.Connection, table: str) -> dict[str, sqlite3.Row]:
    return {r["name"]: r for r in conn.execute(f"PRAGMA table_info({table})")}


def table_names(conn: sqlite3.Connection) -> list[str]:
    return [
        r["name"]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name"
        ).fetchall()
    ]


def primary_key_column(conn: sqlite3.Connection, table: str) -> str:
    for row in conn.execute(f"PRAGMA table_info({table})").fetchall():
        if int(row["pk"]) == 1:
            return row["name"]
    return "rowid"


def referencing_foreign_keys(conn: sqlite3.Connection, parent_table: str) -> list[tuple[str, sqlite3.Row]]:
    refs: list[tuple[str, sqlite3.Row]] = []
    for child_table in table_names(conn):
        for fk in conn.execute(f"PRAGMA foreign_key_list({child_table})").fetchall():
            if fk["table"] == parent_table:
                refs.append((child_table, fk))
    return refs


def create_tables(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS conservative_cleanup_runs (
            run_id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_at TEXT NOT NULL,
            script_name TEXT NOT NULL,
            notes TEXT
        );

        CREATE TABLE IF NOT EXISTS conservative_fk_quarantine (
            quarantine_id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id INTEGER NOT NULL,
            table_name TEXT NOT NULL,
            rowid_value INTEGER NOT NULL,
            parent_table TEXT NOT NULL,
            fk_id INTEGER,
            action TEXT NOT NULL,
            row_json TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS virus_scope_assessment (
            master_id INTEGER PRIMARY KEY,
            scope_class TEXT NOT NULL,
            scope_reason TEXT NOT NULL,
            evidence_tier TEXT NOT NULL,
            host_phylum TEXT,
            entry_type TEXT,
            discovery_context TEXT,
            has_isolate INTEGER NOT NULL DEFAULT 0,
            has_host_record INTEGER NOT NULL DEFAULT 0,
            has_reference INTEGER NOT NULL DEFAULT 0,
            has_protein INTEGER NOT NULL DEFAULT 0,
            has_country INTEGER NOT NULL DEFAULT 0,
            needs_manual_review INTEGER NOT NULL DEFAULT 0,
            run_id INTEGER NOT NULL,
            assessed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS host_association_assessment (
            record_id INTEGER PRIMARY KEY,
            isolate_id INTEGER,
            master_id INTEGER,
            host_id INTEGER,
            host_association_method TEXT,
            association_tier TEXT NOT NULL,
            association_reason TEXT NOT NULL,
            display_recommendation TEXT NOT NULL,
            run_id INTEGER NOT NULL,
            assessed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS pathogenicity_assessment (
            assessment_id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_table TEXT NOT NULL,
            source_id INTEGER NOT NULL,
            virus_master_id INTEGER,
            pathogenicity_tier TEXT NOT NULL,
            pathogenicity_reason TEXT NOT NULL,
            claim_recommendation TEXT NOT NULL,
            run_id INTEGER NOT NULL,
            assessed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(source_table, source_id)
        );
        """
    )


def start_run(conn: sqlite3.Connection) -> int:
    now = datetime.now().isoformat(timespec="seconds")
    cur = conn.execute(
        """
        INSERT INTO conservative_cleanup_runs (run_at, script_name, notes)
        VALUES (?, ?, ?)
        """,
        (
            now,
            SCRIPT_NAME,
            "Conservative scope/evidence scoring and FK cleanup. Original data preserved where possible.",
        ),
    )
    return int(cur.lastrowid)


def record_quarantine(
    conn: sqlite3.Connection,
    run_id: int,
    table: str,
    rowid_value: int,
    parent: str,
    fk_id: int,
    action: str,
    row_json: str | None,
) -> None:
    conn.execute(
        """
        INSERT INTO conservative_fk_quarantine
            (run_id, table_name, rowid_value, parent_table, fk_id, action, row_json)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (run_id, table, rowid_value, parent, fk_id, action, row_json),
    )


def detach_or_delete_children(
    conn: sqlite3.Connection,
    run_id: int,
    parent_table: str,
    parent_pk_col: str,
    parent_pk_value: object,
) -> None:
    """Clear or quarantine rows that would block deleting a parent row."""
    for child_table, fk in referencing_foreign_keys(conn, parent_table):
        child_col = fk["from"]
        parent_col = fk["to"]
        if parent_col != parent_pk_col:
            continue

        child_cols = table_columns(conn, child_table)
        child_rows = conn.execute(
            f"SELECT rowid AS _rowid_, * FROM {child_table} WHERE {child_col} = ?",
            (parent_pk_value,),
        ).fetchall()
        for child in child_rows:
            child_rowid = child["_rowid_"]
            child_json = row_to_json(child)
            if int(child_cols[child_col]["notnull"]) == 0:
                conn.execute(
                    f"UPDATE {child_table} SET {child_col} = NULL WHERE rowid = ?",
                    (child_rowid,),
                )
                record_quarantine(
                    conn,
                    run_id,
                    child_table,
                    child_rowid,
                    parent_table,
                    int(fk["id"]),
                    f"set child {child_col}=NULL before parent quarantine",
                    child_json,
                )
            else:
                child_pk_col = primary_key_column(conn, child_table)
                child_pk_value = child[child_pk_col] if child_pk_col != "rowid" else child_rowid
                detach_or_delete_children(conn, run_id, child_table, child_pk_col, child_pk_value)
                conn.execute(f"DELETE FROM {child_table} WHERE rowid = ?", (child_rowid,))
                record_quarantine(
                    conn,
                    run_id,
                    child_table,
                    child_rowid,
                    parent_table,
                    int(fk["id"]),
                    f"quarantined_deleted_child_before_parent_delete_nonnull_{child_col}",
                    child_json,
                )


def fix_foreign_keys(conn: sqlite3.Connection, run_id: int) -> dict[str, int]:
    """Detach nullable bad FKs; quarantine and delete non-null orphan child rows."""
    fixed: dict[str, int] = {}
    violations = conn.execute("PRAGMA foreign_key_check").fetchall()
    for violation in violations:
        table = violation["table"]
        rowid_value = violation["rowid"]
        parent = violation["parent"]
        fk_id = violation["fkid"]
        fk = conn.execute(f"PRAGMA foreign_key_list({table})").fetchall()[fk_id]
        child_col = fk["from"]
        cols = table_columns(conn, table)
        col_info = cols[child_col]
        row = conn.execute(f"SELECT rowid AS _rowid_, * FROM {table} WHERE rowid = ?", (rowid_value,)).fetchone()
        row_json = row_to_json(row) if row else None

        if int(col_info["notnull"]) == 0:
            conn.execute(f"UPDATE {table} SET {child_col} = NULL WHERE rowid = ?", (rowid_value,))
            if table == "infection_records" and "orphan_flag" in cols:
                conn.execute(
                    """
                    UPDATE infection_records
                    SET orphan_flag = COALESCE(orphan_flag || '; ', '') || ?
                    WHERE rowid = ?
                    """,
                    (f"detached_bad_{child_col}_fk_{run_id}", rowid_value),
                )
            action = f"set {child_col}=NULL"
        else:
            pk_col = primary_key_column(conn, table)
            pk_value = row[pk_col] if row and pk_col != "rowid" else rowid_value
            detach_or_delete_children(conn, run_id, table, pk_col, pk_value)
            conn.execute(f"DELETE FROM {table} WHERE rowid = ?", (rowid_value,))
            action = f"quarantined_deleted_orphan_child_nonnull_{child_col}"

        record_quarantine(conn, run_id, table, rowid_value, parent, fk_id, action, row_json)
        fixed[action] = fixed.get(action, 0) + 1
    return fixed


def classify_scope(row: sqlite3.Row, flags: dict[str, int]) -> tuple[str, str, int]:
    phylum = (row["host_phylum"] or "").strip()
    entry_type = (row["entry_type"] or "").strip().lower()
    discovery = (row["discovery_context"] or "").strip().lower()
    notes = (row["notes"] or "").strip().lower()

    if phylum not in TARGET_PHYLA:
        return "non_target_or_uncertain", f"host_phylum={phylum or 'missing'} is outside target aquatic invertebrate phyla", 1
    if entry_type in {"non_target", "host_genome"}:
        return "excluded_or_contaminant_candidate", f"entry_type={entry_type}", 1
    if "host genome" in notes or "artifact" in notes:
        return "excluded_or_contaminant_candidate", "notes indicate host-genome/artifact risk", 1
    if flags["has_host_record"] and flags["has_reference"]:
        if discovery in {"disease_outbreak", "experimental_infection", "isolated_and_cultured"}:
            return "core_target_high_confidence", "target phylum with direct disease/experimental/cultured context", 0
        return "core_target_supported", "target phylum with host record and reference", 0
    if flags["has_isolate"] and flags["has_reference"]:
        return "target_candidate_sequence_supported", "target phylum with isolate and reference but weak host linkage", 1
    return "target_candidate_needs_review", "target phylum but missing isolate/host/reference support", 1


def evidence_tier(row: sqlite3.Row, flags: dict[str, int]) -> str:
    discovery = (row["discovery_context"] or "").strip().lower()
    if discovery in {"experimental_infection", "disease_outbreak", "isolated_and_cultured"} and flags["has_host_record"] and flags["has_reference"]:
        return "strong"
    if flags["has_host_record"] and flags["has_reference"]:
        return "moderate"
    if flags["has_reference"] or flags["has_isolate"]:
        return "weak"
    return "trace_only"


def refresh_virus_scope_assessment(conn: sqlite3.Connection, run_id: int) -> dict[str, int]:
    conn.execute("DELETE FROM virus_scope_assessment")
    rows = conn.execute("SELECT * FROM virus_master").fetchall()
    counts: dict[str, int] = {}
    for row in rows:
        master_id = row["master_id"]
        flags = {
            "has_isolate": int(
                conn.execute(
                    "SELECT EXISTS(SELECT 1 FROM viral_isolates WHERE master_id = ?)",
                    (master_id,),
                ).fetchone()[0]
            ),
            "has_host_record": int(
                conn.execute(
                    """
                    SELECT EXISTS(
                        SELECT 1
                        FROM viral_isolates vi
                        JOIN infection_records ir ON vi.isolate_id = ir.isolate_id
                        WHERE vi.master_id = ? AND ir.host_id IS NOT NULL
                    )
                    """,
                    (master_id,),
                ).fetchone()[0]
            ),
            "has_reference": int(
                conn.execute(
                    """
                    SELECT EXISTS(SELECT 1 FROM viral_isolates WHERE master_id = ? AND reference_id IS NOT NULL)
                       OR EXISTS(SELECT 1 FROM evidence_records WHERE virus_master_id = ? AND reference_id IS NOT NULL)
                    """,
                    (master_id, master_id),
                ).fetchone()[0]
            ),
            "has_protein": int(
                conn.execute(
                    """
                    SELECT EXISTS(
                        SELECT 1
                        FROM viral_isolates vi
                        JOIN viral_proteins vp ON vi.isolate_id = vp.isolate_id
                        WHERE vi.master_id = ?
                    )
                    """,
                    (master_id,),
                ).fetchone()[0]
            ),
            "has_country": int(
                conn.execute(
                    """
                    SELECT EXISTS(
                        SELECT 1
                        FROM viral_isolates vi
                        JOIN infection_records ir ON vi.isolate_id = ir.isolate_id
                        JOIN sample_collections sc ON ir.collection_id = sc.collection_id
                        WHERE vi.master_id = ? AND sc.country IS NOT NULL AND trim(sc.country) <> ''
                    )
                    """,
                    (master_id,),
                ).fetchone()[0]
            ),
        }
        scope_class, scope_reason, needs_manual = classify_scope(row, flags)
        tier = evidence_tier(row, flags)
        conn.execute(
            """
            INSERT INTO virus_scope_assessment (
                master_id, scope_class, scope_reason, evidence_tier,
                host_phylum, entry_type, discovery_context,
                has_isolate, has_host_record, has_reference, has_protein,
                has_country, needs_manual_review, run_id
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                master_id,
                scope_class,
                scope_reason,
                tier,
                row["host_phylum"],
                row["entry_type"],
                row["discovery_context"],
                flags["has_isolate"],
                flags["has_host_record"],
                flags["has_reference"],
                flags["has_protein"],
                flags["has_country"],
                needs_manual,
                run_id,
            ),
        )
        counts[scope_class] = counts.get(scope_class, 0) + 1
    return counts


def association_tier(method: str | None, has_ref: bool, host_scope: str | None) -> tuple[str, str, str]:
    method_norm = (method or "").strip()
    host_scope_norm = (host_scope or "").strip()
    if host_scope_norm.startswith("excluded"):
        return "excluded_host", f"host_scope_status={host_scope_norm}", "hide_from_core_claims"
    if method_norm in CONFIRMED_HOST_METHODS and has_ref:
        return "confirmed_infection", "confirmed method with reference", "show_as_confirmed"
    if method_norm in DISEASE_HOST_METHODS and has_ref:
        return "disease_associated", "disease/outbreak method with reference", "show_as_disease_associated"
    if method_norm in CONFIRMED_HOST_METHODS | DISEASE_HOST_METHODS:
        return "needs_reference", "strong method label but missing reference", "manual_review"
    if method_norm in WEAK_HOST_METHODS:
        return "candidate_or_context", f"weak association method={method_norm}", "show_as_candidate_only"
    return "needs_review", f"unrecognized or missing method={method_norm or 'missing'}", "manual_review"


def refresh_host_association_assessment(conn: sqlite3.Connection, run_id: int) -> dict[str, int]:
    conn.execute("DELETE FROM host_association_assessment")
    rows = conn.execute(
        """
        SELECT ir.record_id, ir.isolate_id, vi.master_id, ir.host_id,
               ir.host_association_method, ir.reference_id, ch.host_scope_status
        FROM infection_records ir
        LEFT JOIN viral_isolates vi ON ir.isolate_id = vi.isolate_id
        LEFT JOIN crustacean_hosts ch ON ir.host_id = ch.host_id
        """
    ).fetchall()
    counts: dict[str, int] = {}
    for row in rows:
        tier, reason, display = association_tier(
            row["host_association_method"],
            row["reference_id"] is not None,
            row["host_scope_status"],
        )
        conn.execute(
            """
            INSERT INTO host_association_assessment (
                record_id, isolate_id, master_id, host_id, host_association_method,
                association_tier, association_reason, display_recommendation, run_id
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row["record_id"],
                row["isolate_id"],
                row["master_id"],
                row["host_id"],
                row["host_association_method"],
                tier,
                reason,
                display,
                run_id,
            ),
        )
        counts[tier] = counts.get(tier, 0) + 1
    return counts


def classify_pathogenicity(row: sqlite3.Row, source_table: str) -> tuple[str, str, str]:
    has_ref = row["reference_id"] is not None
    has_host = row["host_id"] is not None
    has_isolate = "isolate_id" in row.keys() and row["isolate_id"] is not None
    has_mortality = row["mortality_rate_min"] is not None or row["mortality_rate_max"] is not None
    evidence_strength = (row["evidence_strength"] or "").strip().lower()
    curation = (row["curation_status"] or "").strip().lower()
    observation = (row["observation_type"] or "").strip().lower() if "observation_type" in row.keys() else ""
    symptoms = (row["disease_symptoms"] or "").strip() if "disease_symptoms" in row.keys() and row["disease_symptoms"] else ""

    if curation == "manual_checked" and has_ref and has_host and (has_isolate or source_table == "outbreak_events") and (has_mortality or symptoms or source_table == "outbreak_events"):
        return "strong_pathogenicity", "manual checked with host, reference, and mortality/symptom/outbreak evidence", "can_claim_pathogenicity"
    if has_ref and has_host and evidence_strength in {"high", "medium"} and (has_mortality or symptoms or observation in {"pathology", "experimental_infection"}):
        return "probable_pathogenicity", "referenced host-linked disease evidence but not fully manual checked", "claim_as_probable_or_disease_associated"
    if has_ref and evidence_strength in {"high", "medium"}:
        return "disease_association", "referenced disease evidence but missing host/isolate or detailed phenotype link", "candidate_claim_only"
    if evidence_strength == "low" or not has_ref:
        return "weak_or_inferred", "missing reference or low evidence strength", "do_not_claim_pathogenicity"
    return "needs_review", "insufficient structured fields for pathogenicity claim", "manual_review"


def refresh_pathogenicity_assessment(conn: sqlite3.Connection, run_id: int) -> dict[str, int]:
    conn.execute("DELETE FROM pathogenicity_assessment")
    counts: dict[str, int] = {}
    sources = [
        ("pathogenicity_evidence", "pathogenicity_id", "virus_master_id"),
        ("outbreak_events", "outbreak_id", "virus_master_id"),
    ]
    for table, pk, virus_col in sources:
        for row in conn.execute(f"SELECT * FROM {table}").fetchall():
            tier, reason, recommendation = classify_pathogenicity(row, table)
            conn.execute(
                """
                INSERT OR REPLACE INTO pathogenicity_assessment (
                    source_table, source_id, virus_master_id, pathogenicity_tier,
                    pathogenicity_reason, claim_recommendation, run_id
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (table, row[pk], row[virus_col], tier, reason, recommendation, run_id),
            )
            counts[tier] = counts.get(tier, 0) + 1
    return counts


def create_views(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE VIEW IF NOT EXISTS v_core_target_viruses AS
        SELECT vm.*, vsa.scope_class, vsa.evidence_tier, vsa.scope_reason,
               vsa.has_isolate, vsa.has_host_record, vsa.has_reference,
               vsa.has_protein, vsa.has_country
        FROM virus_master vm
        JOIN virus_scope_assessment vsa ON vm.master_id = vsa.master_id
        WHERE vsa.scope_class IN ('core_target_high_confidence', 'core_target_supported');

        CREATE VIEW IF NOT EXISTS v_non_target_or_uncertain_viruses AS
        SELECT vm.*, vsa.scope_class, vsa.evidence_tier, vsa.scope_reason
        FROM virus_master vm
        JOIN virus_scope_assessment vsa ON vm.master_id = vsa.master_id
        WHERE vsa.scope_class NOT IN ('core_target_high_confidence', 'core_target_supported');

        CREATE VIEW IF NOT EXISTS v_host_association_for_display AS
        SELECT ir.*, haa.association_tier, haa.association_reason, haa.display_recommendation
        FROM infection_records ir
        JOIN host_association_assessment haa ON ir.record_id = haa.record_id;

        CREATE VIEW IF NOT EXISTS v_pathogenicity_claim_safety AS
        SELECT pa.*, vm.canonical_name
        FROM pathogenicity_assessment pa
        LEFT JOIN virus_master vm ON pa.virus_master_id = vm.master_id;
        """
    )


def report_counts(conn: sqlite3.Connection, run_id: int, fk_actions: dict[str, int]) -> dict[str, object]:
    def grouped(sql: str) -> list[dict[str, object]]:
        return [dict(r) for r in conn.execute(sql).fetchall()]

    return {
        "run_id": run_id,
        "run_at": conn.execute(
            "SELECT run_at FROM conservative_cleanup_runs WHERE run_id = ?",
            (run_id,),
        ).fetchone()[0],
        "fk_actions": fk_actions,
        "foreign_key_violations_after": len(conn.execute("PRAGMA foreign_key_check").fetchall()),
        "integrity_check": conn.execute("PRAGMA integrity_check").fetchone()[0],
        "virus_scope": grouped(
            """
            SELECT scope_class, evidence_tier, COUNT(*) AS n
            FROM virus_scope_assessment
            GROUP BY scope_class, evidence_tier
            ORDER BY n DESC
            """
        ),
        "host_association": grouped(
            """
            SELECT association_tier, display_recommendation, COUNT(*) AS n
            FROM host_association_assessment
            GROUP BY association_tier, display_recommendation
            ORDER BY n DESC
            """
        ),
        "pathogenicity": grouped(
            """
            SELECT pathogenicity_tier, claim_recommendation, COUNT(*) AS n
            FROM pathogenicity_assessment
            GROUP BY pathogenicity_tier, claim_recommendation
            ORDER BY n DESC
            """
        ),
        "remaining_manual_review": {
            "virus_scope_needs_manual": conn.execute(
                "SELECT COUNT(*) FROM virus_scope_assessment WHERE needs_manual_review = 1"
            ).fetchone()[0],
            "host_association_manual_review": conn.execute(
                """
                SELECT COUNT(*) FROM host_association_assessment
                WHERE display_recommendation = 'manual_review'
                """
            ).fetchone()[0],
            "pathogenicity_manual_or_no_claim": conn.execute(
                """
                SELECT COUNT(*) FROM pathogenicity_assessment
                WHERE claim_recommendation IN ('manual_review', 'do_not_claim_pathogenicity')
                """
            ).fetchone()[0],
            "evidence_needs_review": conn.execute(
                "SELECT COUNT(*) FROM evidence_records WHERE curation_status = 'needs_review'"
            ).fetchone()[0],
            "curation_conflicts": conn.execute("SELECT COUNT(*) FROM curation_conflicts").fetchone()[0],
            "ictv_review_queue": conn.execute("SELECT COUNT(*) FROM ictv_review_priority_queue").fetchone()[0],
        },
    }


def write_report(report: dict[str, object]) -> Path:
    REPORTS_DIR.mkdir(exist_ok=True)
    path = REPORTS_DIR / f"conservative_cleanup_{report['run_id']}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def main() -> None:
    tracker = SchemaTracker(DB_PATH)
    tracker.ensure_table()
    conn = sqlite3.connect(str(DB_PATH), timeout=120)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 120000")
    try:
        conn.execute("BEGIN IMMEDIATE")
        create_tables(conn)
        run_id = start_run(conn)
        fk_actions = fix_foreign_keys(conn, run_id)
        refresh_virus_scope_assessment(conn, run_id)
        refresh_host_association_assessment(conn, run_id)
        refresh_pathogenicity_assessment(conn, run_id)
        create_views(conn)
        schema_cols = table_columns(conn, "schema_version")
        if "checksum" in schema_cols:
            conn.execute(
                """
                INSERT OR IGNORE INTO schema_version
                    (script_name, checksum, exit_code, notes)
                VALUES (?, ?, ?, ?)
                """,
                (SCRIPT_NAME, "", 0, f"run_id={run_id}; conservative cleanup/scoring"),
            )
        elif "description" in schema_cols:
            conn.execute(
                """
                INSERT OR IGNORE INTO schema_version
                    (script_name, description)
                VALUES (?, ?)
                """,
                (SCRIPT_NAME, f"run_id={run_id}; conservative cleanup/scoring"),
            )
        report = report_counts(conn, run_id, fk_actions)
        report_path = write_report(report)
        conn.commit()
        print(json.dumps(report, ensure_ascii=False, indent=2))
        print(f"REPORT_PATH={report_path}")
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
