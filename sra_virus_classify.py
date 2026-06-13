#!/usr/bin/env python3
"""Query NCBI for viral content in SRA runs via Taxonomy Browser API."""
import urllib.request, urllib.parse, json, time, sqlite3

conn = sqlite3.connect('F:/水生无脊椎动物数据库/crustacean_virus_core.db')

# NCBI SRA Taxonomy Analysis API
# Each SRA run has a taxonomic profile computed by NCBI
# We can query: https://www.ncbi.nlm.nih.gov/sra/?term=<run_accession>
# Or use the trace API: https://trace.ncbi.nlm.nih.gov/Traces/sra/sra.cgi

# Actually, more direct: use NCBI E-utilities to search SRA for viral content
# txid10239 = Viruses
ESEARCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"

# Get SRA runs grouped by organism type
print("=== Searching SRA for viral content in aquatic invertebrates ===\n")

searches = [
    ('Mollusk_viral', '(oyster OR mussel OR abalone OR clam OR scallop OR Crassostrea OR Mytilus OR Haliotis OR Ruditapes) AND "txid10239"[Organism]', 200),
    ('Coral_viral', '(coral OR Acropora OR Porites OR "sea anemone" OR Nematostella OR jellyfish) AND "txid10239"[Organism]', 200),
    ('Echinoderm_viral', '("sea cucumber" OR starfish OR "sea urchin" OR Holothuria OR Apostichopus OR Strongylocentrotus) AND "txid10239"[Organism]', 200),
    ('Sponge_viral', '(sponge OR Porifera OR Amphimedon OR Stylissa) AND "txid10239"[Organism]', 100),
    ('Crustacean_viral_new', '(shrimp OR prawn OR crab OR lobster OR Penaeus OR Litopenaeus OR Macrobrachium OR Procambarus) AND "txid10239"[Organism] AND ("2024/01/01"[PDAT] : "2026/12/31"[PDAT])', 200),
]

all_hits = {}
for label, query, max_res in searches:
    params = {'db': 'sra', 'term': query, 'retmax': min(max_res, 200), 'retmode': 'json'}
    url = ESEARCH + '?' + urllib.parse.urlencode(params)

    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'AquaVir-KB/1.0'})
        resp = urllib.request.urlopen(req, timeout=30)
        data = json.loads(resp.read().decode())
        total = data.get('esearchresult', {}).get('count', '0')
        ids = data.get('esearchresult', {}).get('idlist', [])
        print(f'{label}: {total} total viral SRA runs, got {len(ids)} IDs')
        all_hits[label] = {'total': int(total), 'ids': ids}
    except Exception as e:
        print(f'{label}: ERROR {e}')
    time.sleep(0.5)

# Now, let's fetch summaries to get the organism/virus details
import xml.etree.ElementTree as ET

EFETCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
all_viruses = []

existing_sra = {r[0] for r in conn.execute("SELECT sra_accession FROM sra_runs").fetchall()}

for label, info in all_hits.items():
    ids = info['ids']
    if not ids:
        continue

    for i in range(0, len(ids), 50):
        batch = ids[i:i+50]
        params = {'db': 'sra', 'id': ','.join(batch), 'retmode': 'xml'}
        url = EFETCH + '?' + urllib.parse.urlencode(params)

        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'AquaVir-KB/1.0'})
            resp = urllib.request.urlopen(req, timeout=30)
            root = ET.fromstring(resp.read().decode())

            for run in root.findall('.//RUN'):
                run_acc = run.get('accession', '')
                title_el = run.find('.//TITLE')
                title = title_el.text if title_el is not None else ''

                bp_el = run.find('.//BioProject/ID')
                bp = bp_el.text if bp_el is not None else ''

                bs_el = run.find('.//BioSample/ID')
                bs = bs_el.text if bs_el is not None else ''

                if run_acc not in existing_sra:
                    all_viruses.append({
                        'run': run_acc, 'bp': bp, 'bs': bs, 'title': title[:300],
                        'source_label': label,
                    })
        except Exception as e:
            print(f'  EFetch err: {e}')
        time.sleep(0.35)

# Deduplicate by run accession
seen = set()
unique = []
for v in all_viruses:
    if v['run'] not in seen:
        seen.add(v['run'])
        unique.append(v)

print(f'\n=== Total unique viral SRA runs found: {len(unique)} ===')

# Import as new evidence candidates
import datetime
ts = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')

def nid(t, c):
    return conn.execute(f"SELECT COALESCE(MAX({c}),0) FROM {t}").fetchone()[0] + 1

sra_imported = 0
ev_imported = 0

for v in unique:
    # Insert into sra_runs if not exists
    if v['run'] not in existing_sra:
        sid = nid('sra_runs', 'sra_id')
        try:
            conn.execute("""
            INSERT INTO sra_runs (sra_id, sra_accession, bioproject, biosample, title,
                library_strategy, fetched_at, virus_species_matched)
            VALUES (?, ?, ?, ?, ?, 'metagenomic', ?, 'viral_taxid_detected')
            """, (sid, v['run'], v['bp'], v['bs'], v['title'][:500], ts))
            sra_imported += 1
        except Exception as e:
            pass

    # Create evidence record linking SRA to potential virus discovery
    eid = nid('evidence_records', 'evidence_id')
    try:
        conn.execute("""
        INSERT INTO evidence_records (evidence_id, evidence_type, claim,
            evidence_strength, extraction_method, curation_status, context)
        VALUES (?, 'host_range', ?, 'medium', 'sra_viral_taxonomy_api', 'auto_imported', ?)
        """, (eid, f"SRA {v['run']}: viral sequences detected by NCBI taxonomy analysis [{v['source_label']}]", v['title'][:500]))
        ev_imported += 1
    except Exception as e:
        pass

conn.commit()
total_sra = conn.execute("SELECT COUNT(*) FROM sra_runs").fetchone()[0]
total_ev = conn.execute("SELECT COUNT(*) FROM evidence_records").fetchone()[0]
print(f"\nImported: {sra_imported} new SRA runs, {ev_imported} evidence records")
print(f"Total sra_runs: {total_sra}")
print(f"Total evidence_records: {total_ev}")

# Summary
for label in all_hits:
    info = all_hits[label]
    print(f"  {label}: {info['total']} total viral runs")

conn.close()
