#!/usr/bin/env python3
"""Search NCBI for recently published (2024-2026) aquatic invertebrate virus sequences."""
import urllib.request, urllib.parse, xml.etree.ElementTree as ET, json, time, sqlite3

conn = sqlite3.connect('F:/水生无脊椎动物数据库/crustacean_virus_core.db')
ESEARCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
EFETCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"

existing_acc = {r[0] for r in conn.execute("SELECT accession FROM viral_isolates WHERE accession IS NOT NULL").fetchall()}

# Broad searches, sorted by DATE (most recent first)
# Filter: viruses + aquatic invertebrate keywords + recent years
SEARCHES = [
    ('Mollusk_recent', '(oyster OR mussel OR abalone OR clam OR scallop OR Crassostrea OR Mytilus OR Haliotis OR Ruditapes) AND viruses[filter] AND ("2024/01/01"[PDAT] : "2026/12/31"[PDAT])', 300),
    ('Coral_recent', '(coral OR Acropora OR Porites OR "sea anemone" OR Nematostella OR Hydra OR jellyfish) AND viruses[filter] AND ("2024/01/01"[PDAT] : "2026/12/31"[PDAT])', 300),
    ('Echinoderm_recent', '("sea cucumber" OR starfish OR "sea urchin" OR Holothuria OR Strongylocentrotus OR Apostichopus) AND viruses[filter] AND ("2024/01/01"[PDAT] : "2026/12/31"[PDAT])', 200),
    ('Sponge_recent', '(sponge OR Porifera OR Amphimedon OR Stylissa) AND viruses[filter] AND ("2024/01/01"[PDAT] : "2026/12/31"[PDAT])', 200),
    ('Aquatic_invert_recent', '("marine invertebrate" OR "aquatic invertebrate" OR shellfish OR shrimp OR crab OR lobster OR prawn) AND viruses[filter] AND ("2025/01/01"[PDAT] : "2026/12/31"[PDAT])', 300),
]

all_new = {}

for label, query, max_results in SEARCHES:
    print(f'\n=== {label} ===')
    params = {'db': 'nucleotide', 'term': query, 'retmax': min(max_results, 200),
              'retmode': 'json', 'sort': 'pub+date', 'datetype': 'pdat'}
    url = ESEARCH + '?' + urllib.parse.urlencode(params)

    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'AquaVir-KB/1.0'})
        resp = urllib.request.urlopen(req, timeout=30)
        data = json.loads(resp.read().decode())
        id_list = data.get('esearchresult', {}).get('idlist', [])
        total = data.get('esearchresult', {}).get('count', '0')
        print(f'Total hits: {total}, got {len(id_list)} IDs')
    except Exception as e:
        print(f'ESearch error: {e}')
        continue

    time.sleep(0.5)
    if not id_list:
        continue

    # Fetch summaries
    new_for_label = []
    for i in range(0, len(id_list), 50):
        batch = id_list[i:i+50]
        params2 = {'db': 'nucleotide', 'id': ','.join(batch), 'retmode': 'xml', 'rettype': 'docsum'}
        url2 = EFETCH + '?' + urllib.parse.urlencode(params2)

        try:
            req2 = urllib.request.Request(url2, headers={'User-Agent': 'AquaVir-KB/1.0'})
            resp2 = urllib.request.urlopen(req2, timeout=30)
            root = ET.fromstring(resp2.read().decode())

            for doc in root.findall('.//Document'):
                acc = doc.findtext('AccessionVersion', '')
                title = doc.findtext('Title', '')
                org = doc.findtext('Organism', '')
                slen = doc.findtext('Slen', '')
                pdate = doc.findtext('PDAT', '')

                if acc and acc not in existing_acc:
                    new_for_label.append({
                        'accession': acc, 'title': title[:500], 'organism': org,
                        'length': slen, 'pub_date': pdate,
                    })
        except Exception as e:
            print(f'  EFetch err: {e}')
        time.sleep(0.5)

    all_new[label] = new_for_label
    print(f'New accessions: {len(new_for_label)}')

# Save
with open('F:/水生无脊椎动物数据库/ncbi_recent_results.json', 'w', encoding='utf-8') as f:
    json.dump(all_new, f, ensure_ascii=False, indent=2)

total = sum(len(v) for v in all_new.values())
print(f'\n===== TOTAL NEW: {total} =====')
for label, results in sorted(all_new.items(), key=lambda x: -len(x[1])):
    print(f'  {label}: {len(results)}')

# Quick import of the new accessions
imported = 0
def nid():
    return conn.execute("SELECT COALESCE(MAX(isolate_id),0) FROM viral_isolates").fetchone()[0] + 1

for label, results in all_new.items():
    for r in results:
        isoid = nid()
        acc = r['accession']
        if acc in existing_acc:
            continue
        try:
            conn.execute("""
            INSERT INTO viral_isolates (isolate_id, accession, virus_name, has_sequence,
                completeness, sequence_length, genome_type)
            VALUES (?, ?, ?, 1, 'unknown', ?, 'unknown')
            """, (isoid, acc, (r.get('organism') or r.get('title') or '')[:200],
                  int(r.get('length') or 0)))
            imported += 1
            existing_acc.add(acc)
        except:
            pass

conn.commit()
print(f'\nImported {imported} new viral_isolates')
print(f'Total viral_isolates: {conn.execute("SELECT COUNT(*) FROM viral_isolates").fetchone()[0]}')
conn.close()
