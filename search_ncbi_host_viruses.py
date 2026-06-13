#!/usr/bin/env python3
"""Search NCBI Nucleotide for aquatic invertebrate virus sequences by host keywords."""
import urllib.request, urllib.parse, xml.etree.ElementTree as ET, json, time, sqlite3

conn = sqlite3.connect('F:/水生无脊椎动物数据库/crustacean_virus_core.db')
ESEARCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
EFETCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"

existing_acc = {r[0] for r in conn.execute("SELECT accession FROM viral_isolates WHERE accession IS NOT NULL").fetchall()}

# Keyword searches — host names likely to appear in GenBank records
SEARCHES = [
    ('Mollusk_oyster', '("Crassostrea" OR "oyster" OR "Ostrea" OR "Saccostrea") AND viruses[filter] AND 2018:2026[PDAT]', 500),
    ('Mollusk_mussel', '("Mytilus" OR "mussel" OR "Perna" OR "Modiolus") AND viruses[filter] AND 2018:2026[PDAT]', 300),
    ('Mollusk_abalone', '("Haliotis" OR "abalone") AND viruses[filter] AND 2018:2026[PDAT]', 300),
    ('Mollusk_clam', '("Ruditapes" OR "Mercenaria" OR "Venerupis" OR "clam" OR "Sinonovacula") AND viruses[filter] AND 2018:2026[PDAT]', 300),
    ('Mollusk_scallop', '("Pecten" OR "Chlamys" OR "Argopecten" OR "Mizuhopecten" OR "scallop") AND viruses[filter] AND 2018:2026[PDAT]', 300),
    ('Coral_virome', '("Acropora" OR "Porites" OR "coral" OR "Montipora" OR "Pocillopora") AND viruses[filter] AND 2018:2026[PDAT]', 300),
    ('Cnidaria_other', '("Nematostella" OR "Hydra" OR "jellyfish" OR "Aurelia" OR "sea anemone" OR "Exaiptasia") AND viruses[filter] AND 2018:2026[PDAT]', 200),
    ('Echinodermata', '("Strongylocentrotus" OR "Holothuria" OR "Apostichopus" OR "starfish" OR "sea cucumber" OR "sea urchin" OR "Asterias") AND viruses[filter] AND 2018:2026[PDAT]', 300),
    ('Porifera', '("Porifera" OR "sponge" OR "Amphimedon" OR "Stylissa" OR "Aplysina" OR "Petrosia" OR "Xestospongia") AND viruses[filter] AND 2018:2026[PDAT]', 200),
    ('Annelida_worm', '("polychaete" OR "leeche" OR "Hirudo" OR "Nereis" OR "Arenicola" OR "marine worm") AND viruses[filter] AND 2018:2026[PDAT]', 100),
]

all_new = {}
for label, query, max_results in SEARCHES:
    print(f'\n=== {label} ===')
    params = {'db': 'nucleotide', 'term': query, 'retmax': min(max_results, 200), 'retmode': 'json', 'sort': 'relevance'}
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

    time.sleep(0.35)

    if not id_list:
        continue

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

                if acc and acc not in existing_acc:
                    new_for_label.append({'accession': acc, 'title': title[:500], 'organism': org, 'length': slen})
        except Exception as e:
            print(f'  EFetch err: {e}')
        time.sleep(0.35)

    all_new[label] = new_for_label
    print(f'New accessions: {len(new_for_label)}')

# Save
with open('F:/水生无脊椎动物数据库/ncbi_host_search_results.json', 'w', encoding='utf-8') as f:
    json.dump(all_new, f, ensure_ascii=False, indent=2)

total = sum(len(v) for v in all_new.values())
print(f'\n===== TOTAL NEW: {total} =====')
for label, results in sorted(all_new.items(), key=lambda x: -len(x[1])):
    print(f'  {label}: {len(results)}')
conn.close()
