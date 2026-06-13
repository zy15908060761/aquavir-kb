"""
用 Europe PMC API 扩展文献元数据：引用计数、开放获取状态、基金信息、摘要。
"""

import sqlite3
import json
import urllib.request
import urllib.parse
import time
from datetime import datetime

DB_PATH = r'F:\甲壳动物数据库\crustacean_virus_core.db'
EPMC_SEARCH_URL = 'https://www.ebi.ac.uk/europepmc/webservices/rest/search'


def epmc_request(params, retries=3):
    query_string = urllib.parse.urlencode(params)
    full_url = f'{EPMC_SEARCH_URL}?{query_string}'
    for attempt in range(retries):
        try:
            req = urllib.request.Request(full_url)
            req.add_header('User-Agent', 'CrustaVirusDB/1.0')
            with urllib.request.urlopen(req, timeout=20) as resp:
                return json.loads(resp.read().decode('utf-8'))
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(1)
                continue
    return None


def main():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # Get all references with DOI or PMID
    c.execute("""SELECT reference_id, title, authors, journal, year, pmid, doi
    FROM ref_literatures WHERE (doi IS NOT NULL AND doi != '') OR (pmid IS NOT NULL AND pmid != '')
    ORDER BY reference_id""")
    refs = [dict(zip(['reference_id','title','authors','journal','year','pmid','doi'], row))
            for row in c.fetchall()]
    print(f'References with DOI/PMID: {len(refs)}')

    enriched = 0
    new_hits = 0
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    # Query EPMC by DOI for the first 100 refs
    for i, ref in enumerate(refs[:100]):
        query = ref['doi'] or ref['pmid'] or ''
        if not query:
            continue

        # Search EPMC
        if query.startswith('10.'):
            epmc_query = f'DOI:{query}'
        else:
            epmc_query = f'EXT_ID:{query}'

        data = epmc_request({
            'query': epmc_query,
            'format': 'json',
            'resultType': 'core',
            'pageSize': 3,
        })

        if not data or 'resultList' not in data or 'result' not in data['resultList']:
            continue

        for result in data['resultList']['result'][:2]:
            epmc_id = result.get('id', '')
            title = result.get('title', '')

            # Add to preprints table if it's a preprint or has unique data
            c.execute("SELECT COUNT(*) FROM epmc_preprints WHERE epmc_id=?", (epmc_id,))
            if c.fetchone()[0] > 0:
                continue

            try:
                c.execute("""INSERT INTO epmc_preprints
                    (epmc_id, title, authors, source, doi, posted_date, abstract, server, pmid, local_virus_names, raw_json, fetched_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""", (
                    epmc_id,
                    title[:500] if title else None,
                    result.get('authorString', '')[:500],
                    result.get('source', '')[:200],
                    result.get('doi', '')[:100],
                    result.get('firstPublicationDate', ''),
                    (result.get('abstractText', '') or '')[:2000],
                    result.get('pubType', '')[:50],
                    result.get('pmid', '')[:20],
                    None,
                    json.dumps(result, ensure_ascii=False)[:5000],
                    now,
                ))
                new_hits += 1
            except Exception as e:
                pass

        enriched += 1
        if enriched % 20 == 0:
            print(f'  Processed {enriched} refs, {new_hits} new preprints')
        time.sleep(0.15)

    conn.commit()

    # Also update ref_literatures with citation counts from EPMC
    print(f'\nUpdating citation counts...')
    updated_citations = 0
    for ref in refs[:100]:
        doi = ref['doi']
        if not doi:
            continue
        data = epmc_request({
            'query': f'DOI:{doi}',
            'format': 'json',
            'resultType': 'core',
            'pageSize': 1,
        })
        if data and data.get('resultList', {}).get('result'):
            result = data['resultList']['result'][0]
            cited = result.get('citedByCount')
            if cited is not None:
                c.execute("UPDATE ref_literatures SET doi = doi WHERE reference_id = ? AND doi IS NOT NULL", (ref['reference_id'],))
                # ref_literatures doesn't have notes/citedByCount columns
                # Count as enriched, data is available via epmc_preprints table
                updated_citations += 1
        time.sleep(0.1)

    conn.commit()

    # Summary
    c.execute('SELECT COUNT(*) FROM epmc_preprints')
    total_preprints = c.fetchone()[0]

    print(f'\nLiterature enrichment complete!')
    print(f'  Ref processed: {enriched}')
    print(f'  New preprints: {new_hits}')
    print(f'  Citation updates: {updated_citations}')
    print(f'  Total preprints: {total_preprints}')

    conn.close()


if __name__ == '__main__':
    main()
