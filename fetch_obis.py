"""
从 OBIS (Ocean Biodiversity Information System) API 抓取甲壳类宿主的海洋分布数据。

OBIS API: https://api.obis.org/v3/occurrence?taxon=...

写入 obis_occurrences 表。
"""

import sqlite3
import time
import json
import urllib.request
import urllib.parse
from datetime import datetime

DB_PATH = r'F:\甲壳动物数据库\crustacean_virus_core.db'
OBIS_OCCURRENCE_URL = 'https://api.obis.org/v3/occurrence'


def obis_request(url, params, retries=3):
    """发送 OBIS API 请求"""
    query_string = urllib.parse.urlencode(params)
    full_url = f'{url}?{query_string}'

    for attempt in range(retries):
        try:
            req = urllib.request.Request(full_url)
            req.add_header('User-Agent', 'CrustaVirusDB/1.0 (research database)')
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode('utf-8'))
        except urllib.error.HTTPError as e:
            if e.code == 429:
                wait = 2 ** attempt
                print(f'  Rate limited, waiting {wait}s...')
                time.sleep(wait)
                continue
            elif e.code == 404:
                return None
            elif e.code == 400:
                return None
            else:
                print(f'  HTTP {e.code}')
                return None
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(1)
                continue
            print(f'  Error: {e}')
            return None
    return None


def fetch_obis_occurrences(scientific_name, limit=100):
    """获取某个物种的 OBIS 分布记录"""
    results = []

    data = obis_request(OBIS_OCCURRENCE_URL, {
        'scientificname': scientific_name,
        'size': limit,
        'hascoordinate': 'true',
    })

    if not data or 'results' not in data:
        return results

    for r in data['results']:
        results.append({
            'scientific_name': r.get('scientificName', scientific_name),
            'aphia_id': r.get('aphiaID'),
            'decimal_latitude': r.get('decimalLatitude'),
            'decimal_longitude': r.get('decimalLongitude'),
            'depth_min': r.get('minimumDepthInMeters'),
            'depth_max': r.get('maximumDepthInMeters'),
            'temperature': r.get('temperature'),
            'salinity': r.get('salinity'),
            'country': r.get('country'),
            'locality': r.get('locality'),
            'year_collected': r.get('yearcollected'),
            'dataset_name': (r.get('datasetName') or r.get('dataset_name') or '')[:100],
            'record_count': 1,
        })

    return results


def main():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # Get hosts that should have OBIS data (marine crustaceans with infections)
    # Focus on shrimp/prawn species, exclude freshwater and non-crustacean
    c.execute("""
        SELECT h.host_id, h.scientific_name, h.habitat, COUNT(DISTINCT v.isolate_id) as cnt
        FROM crustacean_hosts h
        JOIN infection_records ir ON h.host_id = ir.host_id
        JOIN viral_isolates v ON ir.isolate_id = v.isolate_id
        WHERE h.host_id NOT IN (SELECT DISTINCT host_id FROM obis_occurrences)
          AND h.host_type != 'non_crustacean'
          AND h.scientific_name NOT LIKE '%E.coli%'
          AND h.scientific_name NOT LIKE '%E. coli%'
          AND h.scientific_name NOT LIKE '%GH K12%'
          AND h.scientific_name NOT LIKE '%spp.%'
          AND h.scientific_name NOT IN ('Crustacea', 'Penaeid shrimp', 'Brachyura',
              'Sesarmid crab', 'Mantis shrimp', 'Charybdis crab', 'hermit crab',
              'freshwater atyid shrimp', 'signal crayfish', 'Bellamya sp.')
          AND h.host_group IN ('penaeid shrimp', 'palaemonid shrimp', 'crab',
              'lobster', 'krill', 'mantis shrimp', 'barnacle', 'isopod', 'hermit crab')
        ORDER BY cnt DESC
        LIMIT 15
    """)
    targets = [dict(zip(['host_id','name','habitat','count'], row)) for row in c.fetchall()]
    print(f'Target hosts for OBIS: {len(targets)}')

    total_inserted = 0
    for i, t in enumerate(targets):
        host_id = t['host_id']
        name = t['name']
        count = t['count']

        print(f'\n[{i+1}/{len(targets)}] {name} ({count} isolates)')

        occurrences = fetch_obis_occurrences(name, limit=50)
        print(f'  Fetched {len(occurrences)} records')

        if not occurrences:
            continue

        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        inserted = 0
        for occ in occurrences:
            try:
                c.execute("""
                    INSERT INTO obis_occurrences
                        (host_id, scientific_name, aphia_id, decimal_latitude, decimal_longitude,
                         depth_min, depth_max, temperature, salinity, country, locality,
                         year_collected, dataset_name, record_count, fetched_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
                """, (
                    host_id, occ['scientific_name'], occ['aphia_id'],
                    occ['decimal_latitude'], occ['decimal_longitude'],
                    occ['depth_min'], occ['depth_max'],
                    occ['temperature'], occ['salinity'],
                    occ['country'], occ['locality'],
                    occ['year_collected'], occ['dataset_name'],
                    now,
                ))
                inserted += 1
            except Exception as e:
                pass

        conn.commit()
        total_inserted += inserted
        print(f'  Stored {inserted} records')
        time.sleep(0.5)

    # Summary
    c.execute('SELECT COUNT(DISTINCT host_id) FROM obis_occurrences')
    hosts_with_obis = c.fetchone()[0]
    c.execute('SELECT COUNT(*) FROM obis_occurrences')
    total_records = c.fetchone()[0]

    print(f'\n{"="*50}')
    print(f'OBIS fetch complete!')
    print(f'  Hosts processed: {len(targets)}')
    print(f'  Records inserted: {total_inserted}')
    print(f'  Total hosts with OBIS: {hosts_with_obis}')
    print(f'  Total OBIS records: {total_records}')

    # List hosts with OBIS now
    c.execute("""SELECT h.scientific_name, COUNT(*) as cnt
    FROM obis_occurrences o JOIN crustacean_hosts h ON o.host_id = h.host_id
    GROUP BY o.host_id ORDER BY cnt DESC""")
    print('\nHosts with OBIS data:')
    for row in c.fetchall():
        print(f'  {row[0]}: {row[1]} records')

    conn.close()


if __name__ == '__main__':
    main()
