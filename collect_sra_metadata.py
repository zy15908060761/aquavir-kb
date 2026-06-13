#!/usr/bin/env python3
"""Collect SRA metadata for aquatic invertebrate metagenomic/metatranscriptomic runs."""
import urllib.request, urllib.parse, xml.etree.ElementTree as ET, json, time, sqlite3

conn = sqlite3.connect('F:/水生无脊椎动物数据库/crustacean_virus_core.db')
ESEARCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
EFETCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"

existing_runs = {r[0] for r in conn.execute("SELECT sra_accession FROM sra_runs").fetchall()}

# Broad searches for SRA runs from aquatic invertebrates
# Strategy: RNA-Seq, metagenomic, metatranscriptomic, WGS, OTHER
SEARCHES = [
    # Mollusca
    ('Mollusk_oyster', '("Crassostrea"[Organism] OR "Ostrea"[Organism] OR "Saccostrea"[Organism] OR "oyster"[All Fields]) AND ("RNA-Seq"[Strategy] OR "metagenomic"[Strategy] OR "metatranscriptomic"[Strategy]) AND "viruses"[Filter]', 300),
    ('Mollusk_mussel', '("Mytilus"[Organism] OR "Perna"[Organism] OR "mussel"[All Fields]) AND ("RNA-Seq"[Strategy] OR "metagenomic"[Strategy] OR "metatranscriptomic"[Strategy])', 200),
    ('Mollusk_abalone', '("Haliotis"[Organism] OR "abalone"[All Fields]) AND ("RNA-Seq"[Strategy] OR "metagenomic"[Strategy] OR "metatranscriptomic"[Strategy])', 200),
    ('Mollusk_clam', '("Ruditapes"[Organism] OR "Mercenaria"[Organism] OR "Sinonovacula"[Organism] OR "clam"[All Fields]) AND ("RNA-Seq"[Strategy] OR "metagenomic"[Strategy])', 200),
    ('Mollusk_scallop', '("Patinopecten"[Organism] OR "Chlamys"[Organism] OR "Argopecten"[Organism] OR "scallop"[All Fields]) AND ("RNA-Seq"[Strategy] OR "metagenomic"[Strategy])', 200),
    # Cnidaria
    ('Coral', '("Acropora"[Organism] OR "Porites"[Organism] OR "Montipora"[Organism] OR "coral"[All Fields]) AND ("RNA-Seq"[Strategy] OR "metagenomic"[Strategy] OR "metatranscriptomic"[Strategy])', 200),
    ('Cnidaria_other', '("Nematostella"[Organism] OR "Hydra"[Organism] OR "Exaiptasia"[Organism] OR "jellyfish"[All Fields] OR "Aurelia"[Organism]) AND ("RNA-Seq"[Strategy] OR "metagenomic"[Strategy])', 200),
    # Echinodermata
    ('Sea_cucumber', '("Apostichopus"[Organism] OR "Holothuria"[Organism] OR "sea cucumber"[All Fields]) AND ("RNA-Seq"[Strategy] OR "metagenomic"[Strategy])', 200),
    ('Sea_urchin', '("Strongylocentrotus"[Organism] OR "Lytechinus"[Organism] OR "sea urchin"[All Fields]) AND ("RNA-Seq"[Strategy] OR "metagenomic"[Strategy])', 200),
    ('Starfish', '("Asterias"[Organism] OR "Acanthaster"[Organism] OR "starfish"[All Fields]) AND ("RNA-Seq"[Strategy] OR "metagenomic"[Strategy])', 200),
    # Porifera
    ('Sponge', '("Amphimedon"[Organism] OR "Stylissa"[Organism] OR "Aplysina"[Organism] OR "Petrosia"[Organism] OR "marine sponge"[All Fields]) AND ("RNA-Seq"[Strategy] OR "metagenomic"[Strategy])', 200),
]

all_new = {}

for label, query, max_runs in SEARCHES:
    print(f'\n=== {label} ===')
    # Step 1: ESearch SRA
    params = {'db': 'sra', 'term': query, 'retmax': min(max_runs, 200), 'retmode': 'json', 'sort': 'relevance'}
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

    # Step 2: EFetch to get run details
    new_for_label = []
    for i in range(0, len(id_list), 30):
        batch = id_list[i:i+30]
        params2 = {'db': 'sra', 'id': ','.join(batch), 'retmode': 'xml'}
        url2 = EFETCH + '?' + urllib.parse.urlencode(params2)

        try:
            req2 = urllib.request.Request(url2, headers={'User-Agent': 'AquaVir-KB/1.0'})
            resp2 = urllib.request.urlopen(req2, timeout=30)
            root = ET.fromstring(resp2.read().decode())

            for run in root.findall('.//RUN'):
                run_acc = run.get('accession', '')
                if run_acc in existing_runs or run_acc in all_new:
                    continue

                # Extract metadata
                title_el = run.find('.//TITLE')
                title = title_el.text if title_el is not None else ''

                # Get BioProject
                bp_el = run.find('.//BioProject/ID')
                bp = bp_el.text if bp_el is not None else ''

                # Get BioSample
                bs_el = run.find('.//BioSample/ID')
                bs = bs_el.text if bs_el is not None else ''

                # Library info
                lib = run.find('.//LIBRARY_STRATEGY')
                lib_strategy = lib.text if lib is not None else ''
                lib_src = run.find('.//LIBRARY_SOURCE')
                lib_source = lib_src.text if lib_src is not None else ''
                lib_layout_el = run.find('.//LIBRARY_LAYOUT')
                lib_layout = 'PAIRED' if lib_layout_el is not None and lib_layout_el.find('PAIRED') is not None else 'SINGLE'
                plat_el = run.find('.//PLATFORM')
                platform = ''
                if plat_el is not None:
                    for child in plat_el:
                        platform = child.tag
                        break

                # Bases
                bases_el = run.find('.//Bases')
                bases = bases_el.get('count', '') if bases_el is not None else ''

                new_for_label.append({
                    'run': run_acc, 'bp': bp, 'bs': bs, 'title': title,
                    'lib_strategy': lib_strategy, 'lib_source': lib_source,
                    'lib_layout': lib_layout, 'platform': platform, 'bases': bases,
                })

        except Exception as e:
            print(f'  EFetch err: {e}')

        time.sleep(0.35)

    all_new[label] = new_for_label
    print(f'New SRA runs: {len(new_for_label)}')

# Save
with open('F:/水生无脊椎动物数据库/sra_metadata_new.json', 'w', encoding='utf-8') as f:
    json.dump(all_new, f, ensure_ascii=False, indent=2)

total = sum(len(v) for v in all_new.values())
print(f'\n===== TOTAL NEW SRA RUNS: {total} =====')
for label, results in sorted(all_new.items(), key=lambda x: -len(x[1])):
    print(f'  {label}: {len(results)}')
conn.close()
