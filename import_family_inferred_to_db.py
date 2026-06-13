#!/usr/bin/env python3
"""
Option A: Import family-level inferred virulence/temperature profiles into database.

Reads:
    external_data/family_inferred_virulence.csv
    external_data/family_inferred_temperature.csv

Inserts into:
    virulence_profiles, temperature_profiles  (primary tables)
    pathogenicity_evidence, environmental_evidence  (normalized evidence tables)

All entries are flagged with curation_status='auto_seeded' and notes containing
'FAMILY_INFERRED' for clear provenance tracking.
"""
from __future__ import annotations

import csv
import sqlite3
import shutil
from pathlib import Path
from datetime import datetime

DB_PATH = Path(r"F:\甲壳动物数据库\crustacean_virus_core.db")
BACKUP_DIR = Path(r"F:\甲壳动物数据库\backups")
VIR_CSV = Path(r"F:\甲壳动物数据库\external_data\family_inferred_virulence.csv")
TEMP_CSV = Path(r"F:\甲壳动物数据库\external_data\family_inferred_temperature.csv")


def backup_database() -> Path:
    BACKUP_DIR.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    bp = BACKUP_DIR / f"crustacean_virus_core_before_family_infer_{stamp}.db"
    shutil.copy2(DB_PATH, bp)
    return bp


def load_csv(path: Path) -> list[dict]:
    if not path.exists():
        print(f"[warn] {path} not found, skipping")
        return []
    with open(path, "r", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def build_name_to_master_id(conn: sqlite3.Connection) -> dict[str, int]:
    c = conn.cursor()
    mapping: dict[str, int] = {}
    c.execute("SELECT master_id, canonical_name FROM virus_master")
    for row in c.fetchall():
        if row[1]:
            mapping[row[1].lower().strip()] = row[0]
    c.execute("SELECT alias, master_id FROM virus_aliases WHERE master_id IS NOT NULL")
    for row in c.fetchall():
        if row[0]:
            key = row[0].lower().strip()
            mapping.setdefault(key, row[1])
    return mapping


def import_virulence(conn: sqlite3.Connection, records: list[dict], name_map: dict[str, int]) -> dict:
    c = conn.cursor()
    stats = {"total": len(records), "inserted_vir": 0, "inserted_path": 0, "skipped": 0}

    for rec in records:
        name = rec.get("virus_name", "").strip()
        master_id = name_map.get(name.lower())
        if not master_id:
            stats["skipped"] += 1
            continue

        # Skip if already exists
        c.execute("SELECT 1 FROM virulence_profiles WHERE LOWER(virus_name) = LOWER(?)", (name,))
        if c.fetchone():
            continue

        # Insert into virulence_profiles
        c.execute("""
            INSERT INTO virulence_profiles
                (virus_name, virulence_level, virulence_label, mortality_rate_min,
                 mortality_rate_max, ld50_value, pathogenic_mechanism, outbreak_record,
                 host_age_susceptibility, data_source, confidence, curation_date, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            name,
            rec.get("virulence_level", "Moderate"),
            int(rec.get("virulence_label", 1)) if rec.get("virulence_label") else 1,
            float(rec.get("mortality_rate_min", 0)) if rec.get("mortality_rate_min") else None,
            float(rec.get("mortality_rate_max", 50)) if rec.get("mortality_rate_max") else None,
            rec.get("ld50_value", ""),
            rec.get("pathogenic_mechanism", ""),
            rec.get("outbreak_record", ""),
            rec.get("host_age_susceptibility", ""),
            rec.get("data_source", ""),
            rec.get("confidence", "medium"),
            rec.get("curation_date", datetime.now().strftime("%Y-%m-%d")),
            rec.get("notes", "") + " [FAMILY_INFERRED]",
        ))
        stats["inserted_vir"] += 1

        # Also insert into pathogenicity_evidence for normalization
        c.execute("""
            INSERT OR IGNORE INTO pathogenicity_evidence
                (virus_master_id, virulence_level, virulence_label, mortality_rate_min,
                 mortality_rate_max, ld50_value, pathogenic_mechanism, host_age_susceptibility,
                 observation_type, evidence_strength, source_text, curation_status, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            master_id,
            rec.get("virulence_level", "Moderate"),
            int(rec.get("virulence_label", 1)) if rec.get("virulence_label") else 1,
            float(rec.get("mortality_rate_min", 0)) if rec.get("mortality_rate_min") else None,
            float(rec.get("mortality_rate_max", 50)) if rec.get("mortality_rate_max") else None,
            rec.get("ld50_value", ""),
            rec.get("pathogenic_mechanism", ""),
            rec.get("host_age_susceptibility", ""),
            "expert_curation",
            rec.get("confidence", "medium"),
            rec.get("data_source", ""),
            "auto_seeded",
            "FAMILY_INFERRED: " + rec.get("notes", ""),
        ))
        stats["inserted_path"] += 1

    return stats


def import_temperature(conn: sqlite3.Connection, records: list[dict], name_map: dict[str, int]) -> dict:
    c = conn.cursor()
    stats = {"total": len(records), "inserted_temp": 0, "inserted_env": 0, "skipped": 0}

    for rec in records:
        name = rec.get("virus_name", "").strip()
        master_id = name_map.get(name.lower())
        if not master_id:
            stats["skipped"] += 1
            continue

        # Skip if already exists
        c.execute("SELECT 1 FROM temperature_profiles WHERE LOWER(virus_name) = LOWER(?)", (name,))
        if c.fetchone():
            continue

        # Insert into temperature_profiles
        c.execute("""
            INSERT INTO temperature_profiles
                (virus_name, optimal_temp_min, optimal_temp_max, temp_range_min,
                 temp_range_max, thermal_inactivation_temp, thermal_inactivation_time,
                 cold_storage_temp, cold_storage_viability, temp_sensitivity_notes,
                 climate_change_impact, data_source, confidence, curation_date, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            name,
            float(rec.get("optimal_temp_min", 20)) if rec.get("optimal_temp_min") else None,
            float(rec.get("optimal_temp_max", 30)) if rec.get("optimal_temp_max") else None,
            float(rec.get("temp_range_min", 4)) if rec.get("temp_range_min") else None,
            float(rec.get("temp_range_max", 35)) if rec.get("temp_range_max") else None,
            float(rec.get("thermal_inactivation_temp", 50)) if rec.get("thermal_inactivation_temp") else None,
            float(rec.get("thermal_inactivation_time", 30)) if rec.get("thermal_inactivation_time") else None,
            float(rec.get("cold_storage_temp", 4)) if rec.get("cold_storage_temp") else None,
            rec.get("cold_storage_viability", ""),
            rec.get("temp_sensitivity_notes", ""),
            rec.get("climate_change_impact", ""),
            rec.get("data_source", ""),
            rec.get("confidence", "medium"),
            rec.get("curation_date", datetime.now().strftime("%Y-%m-%d")),
            rec.get("notes", "") + " [FAMILY_INFERRED]",
        ))
        stats["inserted_temp"] += 1

        # Also insert into environmental_evidence for normalization
        evidence_entries = [
            ("optimal_temperature", rec.get("optimal_temp_min"), rec.get("optimal_temp_max"), "degree_celsius", None, rec.get("temp_sensitivity_notes", "")),
            ("survival_range", rec.get("temp_range_min"), rec.get("temp_range_max"), "degree_celsius", None, rec.get("temp_sensitivity_notes", "")),
            ("thermal_inactivation", rec.get("thermal_inactivation_temp"), rec.get("thermal_inactivation_time"), "degree_celsius/minute", None, rec.get("notes", "")),
            ("cold_storage", rec.get("cold_storage_temp"), None, "degree_celsius", rec.get("cold_storage_viability", ""), rec.get("notes", "")),
        ]

        for ev_type, val_min, val_max, unit, val_text, context in evidence_entries:
            vm = float(val_min) if val_min else None
            vx = float(val_max) if val_max else None
            if vm is None and vx is None and not val_text:
                continue
            c.execute("""
                INSERT OR IGNORE INTO environmental_evidence
                    (virus_master_id, evidence_type, value_min, value_max, unit, value_text, context, evidence_strength, curation_status, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                master_id, ev_type, vm, vx, unit, val_text, context,
                rec.get("confidence", "medium"), "auto_seeded",
                "FAMILY_INFERRED: " + rec.get("notes", ""),
            ))
            stats["inserted_env"] += 1

    return stats


def main():
    print("=" * 60)
    print("Option A: Import family-level inferred profiles")
    print("=" * 60)

    vir_records = load_csv(VIR_CSV)
    temp_records = load_csv(TEMP_CSV)
    print(f"Loaded {len(vir_records)} virulence + {len(temp_records)} temperature records")

    bp = backup_database()
    print(f"[backup] {bp}")

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 30000")

    name_map = build_name_to_master_id(conn)
    print(f"[map] {len(name_map)} virus name mappings")

    try:
        vstats = import_virulence(conn, vir_records, name_map)
        tstats = import_temperature(conn, temp_records, name_map)

        conn.commit()

        print(f"\n[done] Virulence: inserted {vstats['inserted_vir']} profiles, {vstats['inserted_path']} pathogenicity_evidence rows")
        print(f"[done] Temperature: inserted {tstats['inserted_temp']} profiles, {tstats['inserted_env']} environmental_evidence rows")
        print(f"[done] Skipped (no master_id match): {vstats['skipped']} + {tstats['skipped']}")

    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    print("\nNext: run import_virushostdb.py (Option B) or enhance_genbank_coordinates.py (Option C)")


if __name__ == "__main__":
    main()
