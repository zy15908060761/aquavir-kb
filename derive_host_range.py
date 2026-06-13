"""
从现有的 infection_records + sample_collections 数据中自动推导病毒-宿主互作证据。

推导内容：
  - 每种病毒×宿主的自然/实验感染区分
  - 首次/末次检出年份
  - 主要采样组织
  - 地理分布摘要
  - 证据强度评级
"""

import sqlite3
from datetime import datetime

DB_PATH = r'F:\甲壳动物数据库\crustacean_virus_core.db'


def main():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # Clear old auto-derived data
    c.execute("DELETE FROM host_range_evidence WHERE curation_status = 'auto_seeded'")
    print(f'Cleared {c.rowcount} old auto_derived records')

    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    inserted = 0

    # For each virus_master × host combination, derive evidence from infection_records
    c.execute("""
        SELECT
            vm.master_id,
            vm.canonical_name as virus_name,
            h.host_id,
            h.scientific_name as host_name,
            COUNT(DISTINCT v.isolate_id) as isolate_count,
            COUNT(DISTINCT s.country) as country_count,
            GROUP_CONCAT(DISTINCT s.country) as countries,
            MIN(s.collection_year) as first_year,
            MAX(s.collection_year) as last_year,
            COUNT(DISTINCT l.reference_id) as ref_count,
            GROUP_CONCAT(DISTINCT ir.isolation_source) as isolation_sources,
            COUNT(DISTINCT CASE WHEN ir.detection_method IS NOT NULL THEN ir.record_id END) as with_method
        FROM virus_master vm
        JOIN viral_isolates v ON vm.master_id = v.master_id
        JOIN infection_records ir ON v.isolate_id = ir.isolate_id
        JOIN crustacean_hosts h ON ir.host_id = h.host_id
        LEFT JOIN sample_collections s ON ir.collection_id = s.collection_id
        LEFT JOIN ref_literatures l ON v.reference_id = l.reference_id
        WHERE vm.is_crustacean_virus = 1
          AND vm.entry_type NOT IN ('EST', 'patent', 'non_target')
          AND h.scientific_name NOT LIKE '%E.coli%'
          AND h.scientific_name NOT LIKE '%E. coli%'
        GROUP BY vm.master_id, h.host_id
        ORDER BY isolate_count DESC
    """)

    rows = c.fetchall()
    print(f'Virus-host pairs to analyze: {len(rows)}')

    for row in rows:
        master_id, virus_name, host_id, host_name, iso_count, country_count, countries, \
            first_year, last_year, ref_count, isolation_sources, with_method = row

        # Determine evidence category
        if iso_count >= 10 and ref_count >= 3:
            evidence_category = 'natural_infection'
            evidence_strength = 'high'
        elif iso_count >= 3 and ref_count >= 1:
            evidence_category = 'literature_review'
            evidence_strength = 'medium'
        elif iso_count >= 1:
            evidence_category = 'database_annotation'
            evidence_strength = 'low'
        else:
            continue

        # Geography summary
        geo_summary = None
        if countries and country_count and country_count > 0:
            country_list = [c.strip() for c in (countries or '').split(',') if c.strip()]
            if len(country_list) <= 5:
                geo_summary = ', '.join(country_list)
            else:
                geo_summary = f'{country_count} countries including {", ".join(country_list[:3])}...'

        # Tissue/sample info
        tissue_info = None
        if isolation_sources:
            sources = [s.strip() for s in isolation_sources.split(',') if s.strip() and s.strip() != 'None']
            if sources:
                tissue_info = ', '.join(list(set(sources))[:3])

        # Insert
        c.execute("""
            INSERT OR IGNORE INTO host_range_evidence
                (virus_master_id, host_id, evidence_category, isolate_count,
                 host_life_stage, tissue_or_sample, geography_summary,
                 first_observed_year, last_observed_year, evidence_strength,
                 curation_status, notes, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'auto_derived', ?, ?)
        """, (
            master_id, host_id, evidence_category, iso_count,
            None, tissue_info, geo_summary,
            str(first_year) if first_year else None,
            str(last_year) if last_year else None,
            evidence_strength,
            f'Auto-derived from {iso_count} isolates across {ref_count} refs in {country_count} countries',
            now,
        ))
        inserted += 1

    conn.commit()

    # Summary
    c.execute("SELECT evidence_strength, COUNT(*) FROM host_range_evidence WHERE curation_status='auto_derived' GROUP BY evidence_strength")
    print(f'\nInserted {inserted} host range evidence records:')
    for strength, cnt in c.fetchall():
        print(f'  {strength}: {cnt}')

    # Show a few examples
    c.execute("""SELECT vm.canonical_name, h.scientific_name, hre.evidence_category, hre.isolate_count, hre.evidence_strength
    FROM host_range_evidence hre
    JOIN virus_master vm ON hre.virus_master_id = vm.master_id
    JOIN crustacean_hosts h ON hre.host_id = h.host_id
    WHERE hre.curation_status = 'auto_seeded' AND hre.evidence_strength = 'high'
    LIMIT 5""")
    print('\nSample high-confidence evidence:')
    for row in c.fetchall():
        print(f'  {row[0]} → {row[1]}: {row[2]} ({row[3]} isolates)')

    conn.close()


if __name__ == '__main__':
    main()
