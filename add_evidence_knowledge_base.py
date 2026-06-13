"""
Create application-oriented evidence knowledge-base tables.

This is the P1 layer inspired by IVCDB:
- host range evidence
- pathogenicity evidence
- outbreak event summaries
- diagnostic methods
- control/management methods
- environmental and temperature evidence

The initial seed is conservative: it only uses existing curated virulence and
temperature profiles plus observed host-virus links from curated isolate profiles.
"""

from __future__ import annotations

import re
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "crustacean_virus_core.db"
BACKUP_DIR = BASE_DIR / "backups"


def backup_database() -> Path:
    BACKUP_DIR.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = BACKUP_DIR / f"crustacean_virus_core_before_evidence_kb_{stamp}.db"
    shutil.copy2(DB_PATH, backup_path)
    return backup_path


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        PRAGMA foreign_keys = ON;

        CREATE TABLE IF NOT EXISTS host_range_evidence (
            host_range_id INTEGER PRIMARY KEY AUTOINCREMENT,
            virus_master_id INTEGER NOT NULL,
            host_id INTEGER NOT NULL,
            evidence_category TEXT NOT NULL CHECK (
                evidence_category IN (
                    'observed_isolate',
                    'natural_infection',
                    'experimental_infection',
                    'database_annotation',
                    'literature_review',
                    'expert_curation'
                )
            ),
            isolate_count INTEGER DEFAULT 0,
            representative_isolate_id INTEGER,
            reference_id INTEGER,
            host_life_stage TEXT,
            tissue_or_sample TEXT,
            geography_summary TEXT,
            first_observed_year TEXT,
            last_observed_year TEXT,
            evidence_strength TEXT DEFAULT 'medium' CHECK (
                evidence_strength IN ('high', 'medium', 'low', 'unknown')
            ),
            curation_status TEXT DEFAULT 'auto_seeded' CHECK (
                curation_status IN ('auto_seeded', 'needs_review', 'manual_checked', 'rejected')
            ),
            notes TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (virus_master_id) REFERENCES virus_master(master_id),
            FOREIGN KEY (host_id) REFERENCES crustacean_hosts(host_id),
            FOREIGN KEY (representative_isolate_id) REFERENCES viral_isolates(isolate_id),
            FOREIGN KEY (reference_id) REFERENCES ref_literatures(reference_id),
            UNIQUE (virus_master_id, host_id, evidence_category)
        );

        CREATE TABLE IF NOT EXISTS pathogenicity_evidence (
            pathogenicity_id INTEGER PRIMARY KEY AUTOINCREMENT,
            virus_master_id INTEGER NOT NULL,
            host_id INTEGER,
            isolate_id INTEGER,
            reference_id INTEGER,
            virulence_level TEXT,
            virulence_label INTEGER,
            mortality_rate_min REAL,
            mortality_rate_max REAL,
            ld50_value TEXT,
            disease_symptoms TEXT,
            tissue_tropism TEXT,
            pathogenic_mechanism TEXT,
            host_age_susceptibility TEXT,
            observation_type TEXT CHECK (
                observation_type IS NULL OR observation_type IN ('field', 'lab', 'review', 'expert_curation', 'database_annotation')
            ),
            evidence_strength TEXT DEFAULT 'medium' CHECK (
                evidence_strength IN ('high', 'medium', 'low', 'unknown')
            ),
            source_text TEXT,
            curation_status TEXT DEFAULT 'needs_review' CHECK (
                curation_status IN ('auto_seeded', 'needs_review', 'manual_checked', 'rejected')
            ),
            notes TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (virus_master_id) REFERENCES virus_master(master_id),
            FOREIGN KEY (host_id) REFERENCES crustacean_hosts(host_id),
            FOREIGN KEY (isolate_id) REFERENCES viral_isolates(isolate_id),
            FOREIGN KEY (reference_id) REFERENCES ref_literatures(reference_id)
        );

        CREATE TABLE IF NOT EXISTS outbreak_events (
            outbreak_id INTEGER PRIMARY KEY AUTOINCREMENT,
            virus_master_id INTEGER NOT NULL,
            host_id INTEGER,
            country TEXT,
            province_state TEXT,
            start_year TEXT,
            end_year TEXT,
            event_summary TEXT NOT NULL,
            economic_impact TEXT,
            mortality_rate_min REAL,
            mortality_rate_max REAL,
            reference_id INTEGER,
            evidence_strength TEXT DEFAULT 'medium' CHECK (
                evidence_strength IN ('high', 'medium', 'low', 'unknown')
            ),
            curation_status TEXT DEFAULT 'needs_review' CHECK (
                curation_status IN ('auto_seeded', 'needs_review', 'manual_checked', 'rejected')
            ),
            notes TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (virus_master_id) REFERENCES virus_master(master_id),
            FOREIGN KEY (host_id) REFERENCES crustacean_hosts(host_id),
            FOREIGN KEY (reference_id) REFERENCES ref_literatures(reference_id)
        );

        CREATE TABLE IF NOT EXISTS diagnostic_methods (
            method_id INTEGER PRIMARY KEY AUTOINCREMENT,
            virus_master_id INTEGER,
            method_category TEXT NOT NULL CHECK (
                method_category IN ('PCR', 'qPCR', 'RT-PCR', 'LAMP', 'RPA', 'CRISPR', 'immunoassay', 'ISH', 'sequencing', 'other')
            ),
            method_name TEXT NOT NULL,
            target_gene_or_region TEXT,
            sample_type TEXT,
            field_deployable INTEGER CHECK (field_deployable IN (0, 1)),
            visual_readout INTEGER CHECK (visual_readout IN (0, 1)),
            detection_limit TEXT,
            validation_context TEXT,
            reference_id INTEGER,
            evidence_strength TEXT DEFAULT 'medium' CHECK (
                evidence_strength IN ('high', 'medium', 'low', 'unknown')
            ),
            curation_status TEXT DEFAULT 'needs_review' CHECK (
                curation_status IN ('auto_seeded', 'needs_review', 'manual_checked', 'rejected')
            ),
            notes TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (virus_master_id) REFERENCES virus_master(master_id),
            FOREIGN KEY (reference_id) REFERENCES ref_literatures(reference_id)
        );

        CREATE TABLE IF NOT EXISTS control_management_methods (
            control_id INTEGER PRIMARY KEY AUTOINCREMENT,
            virus_master_id INTEGER,
            host_id INTEGER,
            method_category TEXT NOT NULL CHECK (
                method_category IN ('vaccine', 'immunostimulant', 'thermal_management', 'biosecurity', 'selective_breeding', 'pond_management', 'disinfection', 'other')
            ),
            method_name TEXT NOT NULL,
            effect_summary TEXT,
            validation_context TEXT,
            reference_id INTEGER,
            evidence_strength TEXT DEFAULT 'medium' CHECK (
                evidence_strength IN ('high', 'medium', 'low', 'unknown')
            ),
            curation_status TEXT DEFAULT 'needs_review' CHECK (
                curation_status IN ('auto_seeded', 'needs_review', 'manual_checked', 'rejected')
            ),
            notes TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (virus_master_id) REFERENCES virus_master(master_id),
            FOREIGN KEY (host_id) REFERENCES crustacean_hosts(host_id),
            FOREIGN KEY (reference_id) REFERENCES ref_literatures(reference_id)
        );

        CREATE TABLE IF NOT EXISTS environmental_evidence (
            environmental_id INTEGER PRIMARY KEY AUTOINCREMENT,
            virus_master_id INTEGER NOT NULL,
            evidence_type TEXT NOT NULL CHECK (
                evidence_type IN ('optimal_temperature', 'survival_range', 'thermal_inactivation', 'cold_storage', 'climate_impact', 'salinity', 'ph', 'other')
            ),
            value_min REAL,
            value_max REAL,
            unit TEXT,
            value_text TEXT,
            context TEXT,
            reference_id INTEGER,
            evidence_strength TEXT DEFAULT 'medium' CHECK (
                evidence_strength IN ('high', 'medium', 'low', 'unknown')
            ),
            curation_status TEXT DEFAULT 'needs_review' CHECK (
                curation_status IN ('auto_seeded', 'needs_review', 'manual_checked', 'rejected')
            ),
            notes TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (virus_master_id) REFERENCES virus_master(master_id),
            FOREIGN KEY (reference_id) REFERENCES ref_literatures(reference_id)
        );

        CREATE INDEX IF NOT EXISTS idx_host_range_virus ON host_range_evidence(virus_master_id);
        CREATE INDEX IF NOT EXISTS idx_host_range_host ON host_range_evidence(host_id);
        CREATE INDEX IF NOT EXISTS idx_pathogenicity_virus ON pathogenicity_evidence(virus_master_id);
        CREATE INDEX IF NOT EXISTS idx_outbreak_virus ON outbreak_events(virus_master_id);
        CREATE INDEX IF NOT EXISTS idx_diagnostic_virus ON diagnostic_methods(virus_master_id);
        CREATE INDEX IF NOT EXISTS idx_control_virus ON control_management_methods(virus_master_id);
        CREATE INDEX IF NOT EXISTS idx_environment_virus ON environmental_evidence(virus_master_id);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_pathogenicity_unique
            ON pathogenicity_evidence(
                virus_master_id,
                COALESCE(host_id, -1),
                COALESCE(isolate_id, -1),
                COALESCE(reference_id, -1),
                COALESCE(source_text, '')
            );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_outbreak_unique
            ON outbreak_events(
                virus_master_id,
                COALESCE(country, ''),
                COALESCE(start_year, ''),
                event_summary
            );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_diagnostic_unique
            ON diagnostic_methods(
                COALESCE(virus_master_id, -1),
                method_category,
                method_name,
                COALESCE(reference_id, -1)
            );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_control_unique
            ON control_management_methods(
                COALESCE(virus_master_id, -1),
                COALESCE(host_id, -1),
                method_category,
                method_name,
                COALESCE(reference_id, -1)
            );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_environment_unique
            ON environmental_evidence(
                virus_master_id,
                evidence_type,
                COALESCE(value_min, -999999),
                COALESCE(value_max, -999999),
                COALESCE(value_text, '')
            );
        """
    )


def ensure_expression_unique_indexes(conn: sqlite3.Connection) -> None:
    """SQLite cannot add expression UNIQUE constraints in CREATE TABLE reliably across versions."""
    # Tables are created above with expression UNIQUE clauses in modern SQLite. This hook is kept
    # for compatibility if the schema is later migrated manually.
    return None


def confidence(value: str | None) -> str:
    if not value:
        return "unknown"
    lowered = value.lower()
    if lowered in {"high", "medium", "low", "unknown"}:
        return lowered
    return "unknown"


def master_for_virus_name(conn: sqlite3.Connection, virus_name: str) -> int | None:
    row = conn.execute(
        "SELECT master_id FROM virus_master WHERE LOWER(canonical_name) = LOWER(?)",
        (virus_name,),
    ).fetchone()
    if row:
        return row["master_id"]
    row = conn.execute(
        """
        SELECT master_id
        FROM virus_aliases
        WHERE LOWER(alias) = LOWER(?)
          AND match_status <> 'rejected'
        LIMIT 1
        """,
        (virus_name,),
    ).fetchone()
    return row["master_id"] if row else None


def insert_or_ignore(conn: sqlite3.Connection, sql: str, values: tuple) -> None:
    conn.execute(sql, values)


def seed_host_range(conn: sqlite3.Connection) -> int:
    before = conn.total_changes
    rows = conn.execute(
        """
        SELECT
            master_id,
            host_id,
            COUNT(*) AS isolate_count,
            MIN(isolate_id) AS representative_isolate_id,
            MIN(primary_reference_id) AS reference_id,
            MIN(collection_year) AS first_year,
            MAX(collection_year) AS last_year,
            GROUP_CONCAT(DISTINCT country) AS countries
        FROM isolate_curated_profiles
        WHERE master_id IS NOT NULL
          AND host_id IS NOT NULL
          AND host_is_target = 1
        GROUP BY master_id, host_id
        """
    ).fetchall()
    for row in rows:
        strength = "high" if row["reference_id"] and row["isolate_count"] >= 3 else "medium"
        conn.execute(
            """
            INSERT OR IGNORE INTO host_range_evidence
                (
                    virus_master_id, host_id, evidence_category, isolate_count,
                    representative_isolate_id, reference_id, geography_summary,
                    first_observed_year, last_observed_year, evidence_strength,
                    curation_status, notes
                )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row["master_id"],
                row["host_id"],
                "observed_isolate",
                row["isolate_count"],
                row["representative_isolate_id"],
                row["reference_id"],
                row["countries"],
                row["first_year"],
                row["last_year"],
                strength,
                "auto_seeded",
                "Seeded from curated isolate profiles; natural vs experimental infection not yet resolved.",
            ),
        )
    return conn.total_changes - before


def seed_pathogenicity(conn: sqlite3.Connection) -> int:
    before = conn.total_changes
    rows = conn.execute("SELECT * FROM virulence_profiles").fetchall()
    for row in rows:
        master_id = master_for_virus_name(conn, row["virus_name"])
        if not master_id:
            continue
        conn.execute(
            """
            INSERT OR IGNORE INTO pathogenicity_evidence
                (
                    virus_master_id, virulence_level, virulence_label,
                    mortality_rate_min, mortality_rate_max, ld50_value,
                    disease_symptoms, pathogenic_mechanism, host_age_susceptibility,
                    observation_type, evidence_strength, source_text,
                    curation_status, notes
                )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                master_id,
                row["virulence_level"],
                row["virulence_label"],
                row["mortality_rate_min"],
                row["mortality_rate_max"],
                row["ld50_value"],
                None,
                row["pathogenic_mechanism"],
                row["host_age_susceptibility"],
                "expert_curation",
                confidence(row["confidence"]),
                row["data_source"],
                "needs_review",
                row["notes"],
            ),
        )
        if row["outbreak_record"]:
            seed_outbreak_from_text(
                conn,
                master_id,
                row["outbreak_record"],
                row["mortality_rate_min"],
                row["mortality_rate_max"],
                confidence(row["confidence"]),
                row["notes"],
            )
    return conn.total_changes - before


def seed_outbreak_from_text(
    conn: sqlite3.Connection,
    master_id: int,
    text: str,
    mortality_min: float | None,
    mortality_max: float | None,
    strength: str,
    notes: str | None,
) -> None:
    start_year = None
    m = re.search(r"(19|20)\d{2}", text)
    if m:
        start_year = m.group(0)
    country = None
    for candidate in ["China", "Thailand", "India", "Ecuador", "Mexico", "Vietnam", "Brazil", "Indonesia"]:
        if candidate.lower() in text.lower():
            country = candidate
            break
    conn.execute(
        """
        INSERT OR IGNORE INTO outbreak_events
            (
                virus_master_id, country, start_year, event_summary,
                mortality_rate_min, mortality_rate_max, evidence_strength,
                curation_status, notes
            )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            master_id,
            country,
            start_year,
            text,
            mortality_min,
            mortality_max,
            strength,
            "needs_review",
            notes,
        ),
    )


def seed_environment(conn: sqlite3.Connection) -> int:
    before = conn.total_changes
    rows = conn.execute("SELECT * FROM temperature_profiles").fetchall()
    for row in rows:
        master_id = master_for_virus_name(conn, row["virus_name"])
        if not master_id:
            continue
        strength = confidence(row["confidence"])
        entries = [
            ("optimal_temperature", row["optimal_temp_min"], row["optimal_temp_max"], "degree_celsius", None, row["temp_sensitivity_notes"]),
            ("survival_range", row["temp_range_min"], row["temp_range_max"], "degree_celsius", None, row["temp_sensitivity_notes"]),
            ("thermal_inactivation", row["thermal_inactivation_temp"], row["thermal_inactivation_time"], "degree_celsius/minute", None, row["notes"]),
            ("cold_storage", row["cold_storage_temp"], None, "degree_celsius", row["cold_storage_viability"], row["notes"]),
            ("climate_impact", None, None, None, row["climate_change_impact"], row["notes"]),
        ]
        for evidence_type, value_min, value_max, unit, value_text, context in entries:
            if value_min is None and value_max is None and not value_text:
                continue
            conn.execute(
                """
                INSERT OR IGNORE INTO environmental_evidence
                    (
                        virus_master_id, evidence_type, value_min, value_max,
                        unit, value_text, context, evidence_strength,
                        curation_status, notes
                    )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    master_id,
                    evidence_type,
                    value_min,
                    value_max,
                    unit,
                    value_text,
                    context,
                    strength,
                    "needs_review",
                    row["data_source"],
                ),
            )
    return conn.total_changes - before


def seed_diagnostics_from_references(conn: sqlite3.Connection) -> int:
    before = conn.total_changes
    patterns = [
        ("qPCR", re.compile(r"\bquantitative polymerase chain reaction\b|\bqPCR\b", re.I)),
        ("PCR", re.compile(r"\bpolymerase chain reaction\b|\bPCR\b", re.I)),
        ("LAMP", re.compile(r"\bLAMP\b|loop-mediated", re.I)),
        ("RPA", re.compile(r"\bRPA\b|recombinase polymerase", re.I)),
        ("CRISPR", re.compile(r"CRISPR|Cas12|Cas13", re.I)),
        ("immunoassay", re.compile(r"immunoassay|antibody|ELISA", re.I)),
        ("ISH", re.compile(r"in situ hybridization|\\bISH\\b", re.I)),
        ("sequencing", re.compile(r"genome sequence|sequencing", re.I)),
    ]
    rows = conn.execute("SELECT reference_id, title, abstract FROM ref_literatures").fetchall()
    for ref in rows:
        text = " ".join(x for x in [ref["title"], ref["abstract"]] if x)
        if not text:
            continue
        virus_master_id = infer_virus_from_text(conn, text)
        for category, pattern in patterns:
            if not pattern.search(text):
                continue
            field = 1 if category in {"LAMP", "RPA", "CRISPR", "immunoassay"} else 0
            visual = 1 if re.search(r"visual|colorimetric|lateral flow|strip", text, re.I) else 0
            conn.execute(
                """
                INSERT OR IGNORE INTO diagnostic_methods
                    (
                        virus_master_id, method_category, method_name,
                        field_deployable, visual_readout, validation_context,
                        reference_id, evidence_strength, curation_status, notes
                    )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    virus_master_id,
                    category,
                    category,
                    field,
                    visual,
                    ref["title"],
                    ref["reference_id"],
                    "medium",
                    "needs_review",
                    "Auto-detected from reference title/abstract keyword; needs manual curation.",
                ),
            )
    return conn.total_changes - before


def infer_virus_from_text(conn: sqlite3.Connection, text: str) -> int | None:
    lowered = text.lower()
    rows = conn.execute("SELECT master_id, canonical_name, abbreviations FROM virus_master").fetchall()
    for row in rows:
        if row["canonical_name"] and row["canonical_name"].lower() in lowered:
            return row["master_id"]
        if row["abbreviations"]:
            for abbr in re.split(r"[;,/|]+", row["abbreviations"]):
                abbr = abbr.strip()
                if abbr and re.search(rf"\b{re.escape(abbr.lower())}\b", lowered):
                    return row["master_id"]
    return None


def seed_control_from_temperature(conn: sqlite3.Connection) -> int:
    before = conn.total_changes
    rows = conn.execute("SELECT * FROM temperature_profiles").fetchall()
    for row in rows:
        master_id = master_for_virus_name(conn, row["virus_name"])
        if not master_id:
            continue
        summary_parts = []
        if row["thermal_inactivation_temp"]:
            summary_parts.append(f"Thermal inactivation around {row['thermal_inactivation_temp']} C for {row['thermal_inactivation_time']} min")
        if row["cold_storage_viability"]:
            summary_parts.append(f"Cold storage: {row['cold_storage_viability']}")
        if not summary_parts:
            continue
        conn.execute(
            """
            INSERT OR IGNORE INTO control_management_methods
                (
                    virus_master_id, method_category, method_name, effect_summary,
                    validation_context, evidence_strength, curation_status, notes
                )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                master_id,
                "thermal_management",
                "Temperature-based management",
                "; ".join(summary_parts),
                row["temp_sensitivity_notes"],
                confidence(row["confidence"]),
                "needs_review",
                row["data_source"],
            ),
        )
    return conn.total_changes - before


def sync_evidence_records(conn: sqlite3.Connection) -> int:
    before = conn.total_changes
    rows = []
    rows += [
        ("host_range", r["virus_master_id"], r["host_id"], r["representative_isolate_id"], r["reference_id"], f"Observed host association: virus_master_id={r['virus_master_id']} host_id={r['host_id']}", str(r["isolate_count"]), None, None, "isolate_count", r["geography_summary"], "database_annotation", r["evidence_strength"], "seeded_from_host_range_evidence", evidence_record_status(r["curation_status"]), r["notes"])
        for r in conn.execute("SELECT * FROM host_range_evidence")
    ]
    rows += [
        ("virulence", r["virus_master_id"], r["host_id"], r["isolate_id"], r["reference_id"], f"Pathogenicity evidence: {r['virulence_level'] or 'unknown'}", r["ld50_value"], r["mortality_rate_min"], r["mortality_rate_max"], "percent_mortality", r["pathogenic_mechanism"], r["observation_type"], r["evidence_strength"], "seeded_from_pathogenicity_evidence", evidence_record_status(r["curation_status"]), r["notes"])
        for r in conn.execute("SELECT * FROM pathogenicity_evidence")
    ]
    for item in rows:
        conn.execute(
            """
            INSERT INTO evidence_records
                (
                    evidence_type, virus_master_id, host_id, isolate_id, reference_id,
                    claim, value_text, value_numeric_min, value_numeric_max, unit,
                    context, observation_type, evidence_strength, extraction_method,
                    curation_status, notes
                )
            SELECT ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            WHERE NOT EXISTS (
                SELECT 1 FROM evidence_records
                WHERE evidence_type = ?
                  AND COALESCE(virus_master_id, -1) = COALESCE(?, -1)
                  AND claim = ?
                  AND extraction_method = ?
            )
            """,
            item + (item[0], item[1], item[5], item[13]),
        )
    return conn.total_changes - before


def evidence_record_status(status: str | None) -> str:
    if status == "manual_checked":
        return "manual_checked"
    if status in {"rejected"}:
        return "rejected"
    if status == "auto_seeded":
        return "auto_imported"
    return "needs_review"


def log_run(conn: sqlite3.Connection, counts: dict[str, int]) -> None:
    source_row = conn.execute("SELECT source_id FROM external_sources WHERE source_key='local_curation'").fetchone()
    source_id = source_row["source_id"] if source_row else None
    conn.execute(
        """
        INSERT INTO curation_logs
            (entity_type, action, source_id, new_value, confidence, curator, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "evidence_knowledge_base",
            "add_evidence_knowledge_base",
            source_id,
            "; ".join(f"{k}={v}" for k, v in counts.items()),
            "high",
            "add_evidence_knowledge_base.py",
            "Created and seeded P1 evidence knowledge-base tables.",
        ),
    )


def main() -> None:
    backup_path = backup_database()
    print(f"[backup] {backup_path}")
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        ensure_schema(conn)
        counts = {
            "host_range": seed_host_range(conn),
            "pathogenicity": seed_pathogenicity(conn),
            "environment": seed_environment(conn),
            "diagnostics": seed_diagnostics_from_references(conn),
            "control": seed_control_from_temperature(conn),
        }
        counts["evidence_records_sync"] = sync_evidence_records(conn)
        log_run(conn, counts)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    for key, value in counts.items():
        print(f"[done] {key}={value}")


if __name__ == "__main__":
    main()
