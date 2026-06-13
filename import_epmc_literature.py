#!/usr/bin/env python3
"""Import EPMC literature search results into ref_literatures."""
import json, sqlite3, datetime

conn = sqlite3.connect('F:/水生无脊椎动物数据库/crustacean_virus_core.db')

with open('F:/水生无脊椎动物数据库/epmc_search_results.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

ts = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')

# Existing PMID and DOI check
existing_pmids = {r[0] for r in conn.execute("SELECT pmid FROM ref_literatures WHERE pmid IS NOT NULL AND pmid != ''").fetchall()}
existing_dois = {r[0] for r in conn.execute("SELECT doi FROM ref_literatures WHERE doi IS NOT NULL AND doi != ''").fetchall()}

def next_id():
    return conn.execute("SELECT COALESCE(MAX(reference_id), 0) FROM ref_literatures").fetchone()[0] + 1

imported = 0
skipped_dup = 0
for label, results in data.items():
    for r in results:
        pmid = (r.get('pmid') or '').strip()
        doi = (r.get('doi') or '').strip()

        # Dedup
        if pmid and pmid in existing_pmids:
            skipped_dup += 1
            continue
        if doi and doi in existing_dois:
            skipped_dup += 1
            continue

        rid = next_id()
        try:
            conn.execute("""
            INSERT INTO ref_literatures (reference_id, pmid, title, authors, journal, year, doi, abstract)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (rid, pmid or None,
                  r.get('title', '')[:2000],
                  r.get('authors', '')[:2000],
                  r.get('journal', '')[:500],
                  str(r.get('year', ''))[:10],
                  doi or None,
                  r.get('abstract', '')[:10000]))
            imported += 1
            if pmid: existing_pmids.add(pmid)
            if doi: existing_dois.add(doi)
        except Exception as e:
            print(f'ERROR (ref {rid}): {e}')
            continue

        if imported % 100 == 0:
            conn.commit()
            print(f'  Imported {imported}...')

conn.commit()

# Summary by source label
from collections import Counter
label_cnt = Counter()
for label, results in data.items():
    label_cnt[label] = len(results)

print(f'\n===== IMPORT COMPLETE ====')
print(f'Imported: {imported} new ref_literatures')
print(f'Skipped (dup): {skipped_dup}')
print(f'Total ref_literatures now: {conn.execute("SELECT COUNT(*) FROM ref_literatures").fetchone()[0]}')
print()
print('By search query:')
for label, cnt in label_cnt.most_common():
    print(f'  {label}: {cnt} candidates')

conn.close()
