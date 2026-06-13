"""
从 GBIF API 抓取甲壳类宿主的全球分布数据。

GBIF API:
  - Species match: GET https://api.gbif.org/v1/species/match?name=...
  - Occurrence search: GET https://api.gbif.org/v1/occurrence/search?taxonKey=...&limit=100

写入 gbif_occurrences 表。
"""

import sqlite3
import time
import json
import urllib.request
import urllib.parse
import sys
from datetime import datetime

DB_PATH = r'F:\甲壳动物数据库\crustacean_virus_core.db'

# 需要排除的非目标宿主（细菌、非物种级别、重复条目）
SKIP_HOST_IDS = {
    112,  # E. coli K12
    69,   # Crustacea (too broad)
    31,   # Penaeid shrimp (too broad)
    58,   # Sesarmid crab (too broad)
    61,   # Mantis shrimp (too broad)
    59,   # Charybdis crab (too broad)
    51,   # hermit crab (too broad)
    2,    # Penaeus spp. (too broad)
    98,   # Macrobrachium sp. (too broad)
    18,   # Penaeus monodon (duplicate of ID=3)
    33,   # Penaeus indicus (duplicate of ID=44 Fenneropenaeus indicus)
}

GBIF_SPECIES_URL = 'https://api.gbif.org/v1/species/match'
GBIF_OCCURRENCE_URL = 'https://api.gbif.org/v1/occurrence/search'


def gbif_request(url, params, retries=3):
    """发送 GBIF API 请求，带重试和速率限制"""
    query_string = urllib.parse.urlencode(params)
    full_url = f'{url}?{query_string}'

    for attempt in range(retries):
        try:
            req = urllib.request.Request(full_url)
            req.add_header('User-Agent', 'CrustaVirusDB/1.0')
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode('utf-8'))
        except urllib.error.HTTPError as e:
            if e.code == 429:  # Rate limited
                wait = 2 ** attempt
                print(f'  Rate limited, waiting {wait}s...')
                time.sleep(wait)
                continue
            elif e.code == 404:
                return None
            else:
                print(f'  HTTP {e.code} for {full_url[:100]}')
                return None
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(1)
                continue
            print(f'  Error: {e}')
            return None
    return None


def match_species(name):
    """通过 GBIF Species API 查找物种的 taxonKey"""
    result = gbif_request(GBIF_SPECIES_URL, {
        'name': name,
        'strict': 'false',
        'kingdom': 'Animalia'
    })
    if result and result.get('usageKey'):
        return {
            'taxon_key': result['usageKey'],
            'canonical_name': result.get('canonicalName', name),
            'rank': result.get('rank', ''),
            'match_type': result.get('matchType', ''),
            'confidence': result.get('confidence', 0),
        }
    return None


def fetch_occurrences(taxon_key, limit=100):
    """获取某个 taxon 的分布记录"""
    results = []
    offset = 0

    while offset < limit:
        data = gbif_request(GBIF_OCCURRENCE_URL, {
            'taxonKey': taxon_key,
            'limit': min(100, limit - offset),
            'offset': offset,
            'hasCoordinate': 'true',
        })
        if not data or 'results' not in data:
            break

        for r in data['results']:
            results.append({
                'country': r.get('country'),
                'continent': r.get('continent'),
                'decimal_latitude': r.get('decimalLatitude'),
                'decimal_longitude': r.get('decimalLongitude'),
                'locality': r.get('locality'),
                'year': r.get('year'),
                'basis_of_record': r.get('basisOfRecord'),
                'dataset_name': (r.get('datasetName') or '')[:100],
            })

        if data.get('endOfRecords', True):
            break
        offset += len(data['results'])
        time.sleep(0.3)  # Rate limit

    return results


def main():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # 获取需要 GBIF 数据的宿主列表（按感染记录数排序，排除已存在的和非目标的）
    c.execute("""
        SELECT h.host_id, h.scientific_name, COUNT(DISTINCT v.isolate_id) as cnt
        FROM crustacean_hosts h
        JOIN infection_records ir ON h.host_id = ir.host_id
        JOIN viral_isolates v ON ir.isolate_id = v.isolate_id
        WHERE h.host_id NOT IN (SELECT DISTINCT host_id FROM gbif_occurrences)
          AND h.host_type != 'non_crustacean'
          AND h.host_id NOT IN ({})
        GROUP BY h.host_id
        ORDER BY cnt DESC
        LIMIT 15
    """.format(','.join(str(x) for x in SKIP_HOST_IDS)))
    targets = [dict(zip(['host_id', 'name', 'count'], row)) for row in c.fetchall()]

    print(f'Target hosts: {len(targets)}')
    total_inserted = 0
    skipped = 0
    failed = 0

    for i, t in enumerate(targets):
        host_id = t['host_id']
        name = t['name']
        count = t['count']

        print(f'\n[{i+1}/{len(targets)}] {name} (ID={host_id}, {count} isolates)')

        # Step 1: Match species
        match = match_species(name)
        if not match or not match['taxon_key']:
            # Try without subspecies/author info
            clean_name = name.split('(')[0].strip()
            if clean_name != name:
                match = match_species(clean_name)

        if not match or not match['taxon_key']:
            print(f'  No GBIF match found')
            failed += 1
            continue

        print(f'  GBIF match: {match["canonical_name"]} (key={match["taxon_key"]}, confidence={match["confidence"]})')

        # Skip low confidence matches
        if match['confidence'] < 80:
            print(f'  Low confidence ({match["confidence"]}), skipping')
            skipped += 1
            continue

        # Step 2: Fetch occurrences
        occurrences = fetch_occurrences(match['taxon_key'], limit=100)
        print(f'  Fetched {len(occurrences)} occurrence records')

        if not occurrences:
            failed += 1
            continue

        # Step 3: Store in database
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        inserted = 0
        for occ in occurrences:
            try:
                c.execute("""
                    INSERT INTO gbif_occurrences
                        (host_id, scientific_name, gbif_taxon_key, country, continent,
                         decimal_latitude, decimal_longitude, locality, year,
                         basis_of_record, dataset_name, occurrence_count, fetched_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
                """, (
                    host_id,
                    match['canonical_name'],
                    match['taxon_key'],
                    occ['country'],
                    occ['continent'],
                    occ['decimal_latitude'],
                    occ['decimal_longitude'],
                    occ['locality'],
                    occ['year'],
                    occ['basis_of_record'],
                    occ['dataset_name'],
                    now,
                ))
                inserted += 1
            except Exception as e:
                pass  # Skip duplicates or invalid records

        conn.commit()
        total_inserted += inserted
        print(f'  Stored {inserted} records')

        # Rate limiting between species
        time.sleep(0.5)

    conn.commit()

    # Summary
    c.execute('SELECT COUNT(DISTINCT host_id) FROM gbif_occurrences')
    hosts_with_gbif = c.fetchone()[0]
    c.execute('SELECT COUNT(*) FROM gbif_occurrences')
    total_records = c.fetchone()[0]

    print(f'\n{"="*50}')
    print(f'GBIF fetch complete!')
    print(f'  Hosts processed: {len(targets)}')
    print(f'  Records inserted: {total_inserted}')
    print(f'  Skipped (low confidence): {skipped}')
    print(f'  Failed: {failed}')
    print(f'  Total hosts with GBIF data now: {hosts_with_gbif}')
    print(f'  Total GBIF records: {total_records}')

    conn.close()


if __name__ == '__main__':
    main()
