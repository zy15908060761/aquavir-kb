from __future__ import annotations

import sqlite3
from pathlib import Path


DB_PATH = Path(__file__).resolve().parent / "crustacean_virus_core.db"


VIEW_SQL = """
DROP VIEW IF EXISTS analysis_isolate_completeness;

CREATE VIEW analysis_isolate_completeness AS
SELECT
    vi.isolate_id,
    vi.accession,
    vi.master_id,
    vm.canonical_name,
    vi.virus_name,
    COALESCE(icp.host_id, mh.host_id) AS host_id,
    COALESCE(NULLIF(icp.host_scientific_name, ''), mh.scientific_name, sm.host_name) AS host_scientific_name,
    COALESCE(NULLIF(sc.country, ''), NULLIF(icp.country, ''), NULLIF(substr(sm.geo_loc_name, 1, instr(sm.geo_loc_name || ':', ':') - 1), '')) AS country,
    COALESCE(sc.latitude, icp.latitude) AS latitude,
    COALESCE(sc.longitude, icp.longitude) AS longitude,
    COALESCE(NULLIF(sc.collection_year, ''), NULLIF(icp.collection_year, ''),
             CASE WHEN sm.collection_date GLOB '*[12][0-9][0-9][0-9]*'
                  THEN substr(sm.collection_date, instr(sm.collection_date, '20'), 4)
                  ELSE NULL END) AS collection_year,
    COALESCE(NULLIF(ir.isolation_source, ''), NULLIF(icp.sample_source, ''), NULLIF(sm.isolation_source, '')) AS isolation_source,
    vi.genome_type,
    vi.genome_length,
    vi.gc_content,
    CASE WHEN vi.reference_id IS NOT NULL OR EXISTS (
        SELECT 1 FROM isolate_reference_links irl WHERE irl.isolate_id = vi.isolate_id
    ) THEN 1 ELSE 0 END AS has_reference,
    CASE WHEN COALESCE(icp.host_id, mh.host_id) IS NOT NULL THEN 1 ELSE 0 END AS has_host,
    CASE WHEN COALESCE(NULLIF(sc.country, ''), NULLIF(icp.country, ''), NULLIF(substr(sm.geo_loc_name, 1, instr(sm.geo_loc_name || ':', ':') - 1), '')) IS NOT NULL THEN 1 ELSE 0 END AS has_country,
    CASE WHEN COALESCE(sc.latitude, icp.latitude) IS NOT NULL
           AND COALESCE(sc.longitude, icp.longitude) IS NOT NULL THEN 1 ELSE 0 END AS has_coordinates,
    CASE WHEN COALESCE(NULLIF(sc.collection_year, ''), NULLIF(icp.collection_year, ''), NULLIF(sm.collection_date, '')) IS NOT NULL THEN 1 ELSE 0 END AS has_collection_year,
    CASE WHEN COALESCE(NULLIF(ir.isolation_source, ''), NULLIF(icp.sample_source, ''), NULLIF(sm.isolation_source, '')) IS NOT NULL THEN 1 ELSE 0 END AS has_isolation_source,
    CASE WHEN vi.genome_type IS NOT NULL AND TRIM(vi.genome_type) <> '' THEN 1 ELSE 0 END AS has_genome_type
FROM viral_isolates vi
JOIN virus_master vm ON vm.master_id = vi.master_id
LEFT JOIN isolate_curated_profiles icp ON icp.isolate_id = vi.isolate_id
LEFT JOIN sample_metadata sm ON sm.isolate_id = vi.isolate_id
LEFT JOIN crustacean_hosts mh
  ON LOWER(mh.scientific_name) = LOWER(COALESCE(NULLIF(icp.host_scientific_name, ''), NULLIF(sm.host_name, '')))
LEFT JOIN infection_records ir ON ir.isolate_id = vi.isolate_id
LEFT JOIN sample_collections sc ON sc.collection_id = ir.collection_id;
"""


def main() -> None:
    conn = sqlite3.connect(DB_PATH, timeout=60)
    try:
        conn.execute("PRAGMA foreign_keys=ON")
        conn.executescript(VIEW_SQL)
        conn.commit()
        print("analysis_isolate_completeness refreshed")
        print("rows", conn.execute("SELECT COUNT(*) FROM analysis_isolate_completeness").fetchone()[0])
        print("integrity", conn.execute("PRAGMA integrity_check").fetchone()[0])
        print("fk", len(conn.execute("PRAGMA foreign_key_check").fetchall()))
    finally:
        conn.close()


if __name__ == "__main__":
    main()
