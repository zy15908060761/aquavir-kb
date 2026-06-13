"""
Batch 2a: 死亡率/症状/检测方法回填到 infection_records
从 pathogenicity_evidence, virulence_profiles, diagnostic_methods 迁移数据
"""
import sqlite3
from pathlib import Path

DB = Path("F:/甲壳动物数据库/crustacean_virus_core.db")
conn = sqlite3.connect(str(DB))
conn.execute("PRAGMA foreign_keys = ON")
cur = conn.cursor()

print("=== MORTALITY RATE BACKFILL ===")

# Step 1: From pathogenicity_evidence (via virus_master -> viral_isolates -> infection_records)
cur.execute("""
    UPDATE infection_records SET mortality_rate = (
        SELECT CASE
            WHEN pe.mortality_rate_min IS NOT NULL AND pe.mortality_rate_max IS NOT NULL
            THEN CAST(pe.mortality_rate_min AS TEXT) || '-' || CAST(pe.mortality_rate_max AS TEXT) || '%'
            WHEN pe.mortality_rate_min IS NOT NULL
            THEN '~' || CAST(pe.mortality_rate_min AS TEXT) || '%'
            ELSE NULL
        END
        FROM pathogenicity_evidence pe
        WHERE pe.virus_master_id = (
            SELECT vi.master_id FROM viral_isolates vi
            WHERE vi.isolate_id = infection_records.isolate_id
        )
        AND pe.curation_status IN ('needs_review','manual_checked','auto_seeded')
        AND pe.mortality_rate_min IS NOT NULL
        LIMIT 1
    )
    WHERE mortality_rate IS NULL
""")
print(f"From pathogenicity_evidence (master-level): {cur.rowcount} rows")

# Step 2: From virulence_profiles (via virus_name matching)
cur.execute("""
    UPDATE infection_records SET mortality_rate = (
        SELECT CASE
            WHEN vp.mortality_rate_min IS NOT NULL AND vp.mortality_rate_max IS NOT NULL
            THEN CAST(vp.mortality_rate_min AS TEXT) || '-' || CAST(vp.mortality_rate_max AS TEXT) || '%'
            ELSE vp.ld50_value
        END
        FROM virulence_profiles vp
        JOIN viral_isolates vi ON (
            vp.virus_name = vi.virus_name
            OR vi.virus_name LIKE '%' || vp.virus_name || '%'
            OR vp.virus_name LIKE '%' || vi.virus_name || '%'
        )
        WHERE vi.isolate_id = infection_records.isolate_id
        LIMIT 1
    )
    WHERE mortality_rate IS NULL
""")
print(f"From virulence_profiles (name match): {cur.rowcount} rows")

# Step 3: From pathogenicity_evidence where isolate_id matches
cur.execute("""
    UPDATE infection_records SET mortality_rate = (
        SELECT CASE
            WHEN pe.mortality_rate_min IS NOT NULL AND pe.mortality_rate_max IS NOT NULL
            THEN CAST(pe.mortality_rate_min AS TEXT) || '-' || CAST(pe.mortality_rate_max AS TEXT) || '%'
            ELSE 'virulence:' || pe.virulence_level
        END
        FROM pathogenicity_evidence pe
        WHERE pe.isolate_id = infection_records.isolate_id
          AND pe.mortality_rate_min IS NOT NULL
        LIMIT 1
    )
    WHERE mortality_rate IS NULL
""")
print(f"From pathogenicity_evidence (isolate-level): {cur.rowcount} rows")

remaining = cur.execute("SELECT COUNT(*) FROM infection_records WHERE mortality_rate IS NULL").fetchone()[0]
total = cur.execute("SELECT COUNT(*) FROM infection_records").fetchone()[0]
print(f"Mortality rate still NULL: {remaining}/{total} ({100 - remaining*100//total if total else 0}% filled)")

print("\n=== DISEASE SYMPTOM BACKFILL ===")
initial_null = cur.execute("SELECT COUNT(*) FROM infection_records WHERE disease_symptom IS NULL").fetchone()[0]

# From pathogenicity_evidence
cur.execute("""
    UPDATE infection_records SET disease_symptom = (
        SELECT pe.disease_symptoms FROM pathogenicity_evidence pe
        WHERE pe.virus_master_id = (
            SELECT vi.master_id FROM viral_isolates vi
            WHERE vi.isolate_id = infection_records.isolate_id
        )
        AND pe.disease_symptoms IS NOT NULL
        AND TRIM(pe.disease_symptoms) <> ''
        AND pe.curation_status <> 'rejected'
        LIMIT 1
    )
    WHERE disease_symptom IS NULL
""")
print(f"From pathogenicity_evidence: {cur.rowcount} rows")

# From outbreak_events
cur.execute("""
    UPDATE infection_records SET disease_symptom = (
        SELECT oe.event_summary FROM outbreak_events oe
        WHERE oe.virus_master_id = (
            SELECT vi.master_id FROM viral_isolates vi
            WHERE vi.isolate_id = infection_records.isolate_id
        )
        AND oe.event_summary IS NOT NULL
        LIMIT 1
    )
    WHERE disease_symptom IS NULL
""")
print(f"From outbreak_events: {cur.rowcount} rows")

# From virulence_profiles pathogenic_mechanism
cur.execute("""
    UPDATE infection_records SET disease_symptom = (
        SELECT vp.pathogenic_mechanism FROM virulence_profiles vp
        JOIN viral_isolates vi ON vp.virus_name = vi.virus_name
        WHERE vi.isolate_id = infection_records.isolate_id
          AND vp.pathogenic_mechanism IS NOT NULL
        LIMIT 1
    )
    WHERE disease_symptom IS NULL
""")
print(f"From virulence_profiles (mechanism): {cur.rowcount} rows")

remaining_symptom = cur.execute("SELECT COUNT(*) FROM infection_records WHERE disease_symptom IS NULL").fetchone()[0]
print(f"Disease symptom filled: {initial_null - remaining_symptom}, still NULL: {remaining_symptom}")

print("\n=== DETECTION METHOD BACKFILL ===")
initial_null = cur.execute("SELECT COUNT(*) FROM infection_records WHERE detection_method IS NULL").fetchone()[0]

# From diagnostic_methods that are curated/manual_checked
cur.execute("""
    UPDATE infection_records SET detection_method = (
        SELECT dm.method_name FROM diagnostic_methods dm
        WHERE dm.virus_master_id = (
            SELECT vi.master_id FROM viral_isolates vi
            WHERE vi.isolate_id = infection_records.isolate_id
        )
        AND dm.curation_status IN ('manual_checked', 'auto_seeded')
        AND dm.data_quality IN ('curated', 'candidate_unreferenced')
        ORDER BY dm.data_quality DESC
        LIMIT 1
    )
    WHERE detection_method IS NULL
""")
print(f"From diagnostic_methods: {cur.rowcount} rows")

# From sample_metadata or genbank recovery
# Check if there are method hints in external_curation_queries
remaining_detection = cur.execute("SELECT COUNT(*) FROM infection_records WHERE detection_method IS NULL").fetchone()[0]
print(f"Detection method filled: {initial_null - remaining_detection}, still NULL: {remaining_detection}")

conn.commit()
conn.close()
print("\nSaved.")
