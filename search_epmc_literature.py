#!/usr/bin/env python3
"""Search Europe PMC for aquatic invertebrate virus literature across under-covered phyla."""
import urllib.request, urllib.parse, json, time, sqlite3

conn = sqlite3.connect('F:/水生无脊椎动物数据库/crustacean_virus_core.db')
BASE = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"

# Search queries for under-covered phyla
SEARCHES = {
    'Cnidaria_coral': '(coral AND (virome OR virus OR viral)) AND (PUB_YEAR:[2018 TO 2026])',
    'Cnidaria_jellyfish': '(jellyfish AND (virus OR virome OR viral)) AND (PUB_YEAR:[2018 TO 2026])',
    'Cnidaria_anemone': '("sea anemone" AND (virus OR virome OR viral)) AND (PUB_YEAR:[2018 TO 2026])',
    'Echinodermata_seacucumber': '("sea cucumber" AND (virus OR virome OR viral)) AND (PUB_YEAR:[2018 TO 2026])',
    'Echinodermata_starfish': '(starfish AND (virus OR virome OR viral)) AND (PUB_YEAR:[2018 TO 2026])',
    'Echinodermata_urchin': '("sea urchin" AND (virus OR virome OR viral)) AND (PUB_YEAR:[2018 TO 2026])',
    'Porifera': '(sponge AND (virome OR "virus diversity" OR "RNA virus")) AND (PUB_YEAR:[2018 TO 2026])',
    'Annelida': '((polychaete OR "marine leech" OR "aquatic annelid") AND (virus OR virome OR viral))',
    'Platyhelminthes': '(("marine flatworm" OR "aquatic planarian") AND (virus OR virome))',
    'Mollusca_oyster': '(oyster AND (virome OR "novel virus" OR "RNA virus" OR herpesvirus)) AND (PUB_YEAR:[2020 TO 2026])',
    'Mollusca_abalone': '(abalone AND (virus OR herpesvirus OR virome)) AND (PUB_YEAR:[2018 TO 2026])',
    'Mollusca_mussel': '(mussel AND (virome OR "novel virus" OR herpesvirus)) AND (PUB_YEAR:[2020 TO 2026])',
    'Mollusca_clam': '(clam AND (virome OR "novel virus" OR herpesvirus)) AND (PUB_YEAR:[2020 TO 2026])',
    'Mollusca_scallop': '(scallop AND (virome OR "novel virus" OR herpesvirus)) AND (PUB_YEAR:[2020 TO 2026])',
    'Aquaculture_general': '("aquatic invertebrate" AND (virus OR virome)) AND (PUB_YEAR:[2018 TO 2026])',
    'Marine_invert_virome': '("marine invertebrate" AND virome) AND (PUB_YEAR:[2018 TO 2026])',
}

# PMIDs already in DB
existing_pmids = set()
for row in conn.execute("SELECT pmid FROM ref_literatures WHERE pmid IS NOT NULL AND pmid != ''").fetchall():
    existing_pmids.add(row[0].strip())

new_candidates = {}
total_new = 0

for label, query in SEARCHES.items():
    params = {
        'query': query,
        'format': 'json',
        'pageSize': 100,
        'resultType': 'core',
    }
    url = BASE + '?' + urllib.parse.urlencode(params)
    print(f'Searching: {label}...', end=' ')
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'AquaVir-KB/1.0 (research db; mailto:admin@aquavir.org)'})
        resp = urllib.request.urlopen(req, timeout=30)
        data = json.loads(resp.read().decode())
        total_hits = data.get('hitCount', 0)
        results = data.get('resultList', {}).get('result', [])
        print(f'{total_hits} hits, got {len(results)}')

        new_for_label = []
        for r in results:
            pmid = r.get('pmid', '') or r.get('id', '')
            if pmid and pmid in existing_pmids:
                continue
            new_for_label.append({
                'pmid': r.get('pmid', '') or r.get('id', ''),
                'doi': r.get('doi', ''),
                'title': r.get('title', ''),
                'authors': r.get('authorString', ''),
                'journal': r.get('journalTitle', '') or r.get('journalCode', ''),
                'year': r.get('pubYear', ''),
                'abstract': r.get('abstractText', ''),
                'source': r.get('source', ''),
            })
            if pmid:
                existing_pmids.add(pmid)
        new_candidates[label] = new_for_label
        total_new += len(new_for_label)
    except Exception as e:
        print(f'ERROR: {e}')
    time.sleep(0.5)  # Be nice to API

print(f'\n===== TOTAL NEW CANDIDATES: {total_new} =====')

# Save for analysis
with open('F:/水生无脊椎动物数据库/epmc_search_results.json', 'w', encoding='utf-8') as f:
    json.dump(new_candidates, f, ensure_ascii=False, indent=2)

# Print summary
for label, results in sorted(new_candidates.items(), key=lambda x: -len(x[1])):
    if results:
        print(f'  {label}: {len(results)} new')
conn.close()
print('Done. Saved to epmc_search_results.json')
