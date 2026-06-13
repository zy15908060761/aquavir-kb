"""Batch 2: import with corrected NCBI syntax (txid10239 + [All Fields])"""
import sqlite3, time, urllib.request, urllib.parse, xml.etree.ElementTree as ET, re

DB = 'F:/甲壳动物数据库/crustacean_virus_core.db'
RATE = 0.35

QUERIES = [
    ('Oyster_virus', 'oyster[All Fields] AND txid10239[Organism] NOT bacteria[Organism] AND 2010:2026[pdat]', 'Mollusca'),
    ('Mussel_virus', 'mussel[All Fields] AND txid10239[Organism] NOT bacteria[Organism] AND 2010:2026[pdat]', 'Mollusca'),
    ('Clam_virus', 'clam[All Fields] AND txid10239[Organism] NOT bacteria[Organism] AND 2010:2026[pdat]', 'Mollusca'),
    ('Abalone_virus', 'abalone[All Fields] AND txid10239[Organism] NOT bacteria[Organism] AND 2010:2026[pdat]', 'Mollusca'),
    ('Scallop_virus', 'scallop[All Fields] AND txid10239[Organism] NOT bacteria[Organism]', 'Mollusca'),
    ('Cephalopod_virus', '(squid[All Fields] OR octopus[All Fields] OR Sepia[All Fields]) AND txid10239[Organism] NOT bacteria[Organism]', 'Mollusca'),
    ('Coral_virus', 'coral[All Fields] AND txid10239[Organism] NOT bacteria[Organism] AND 2010:2026[pdat]', 'Cnidaria'),
    ('Cnidaria_virus', '(Cnidaria[All Fields] OR sea anemone[All Fields] OR jellyfish[All Fields]) AND txid10239[Organism] NOT bacteria[Organism] AND 2010:2026[pdat]', 'Cnidaria'),
    ('Echinoderm_virus', '(Echinodermata[All Fields] OR sea cucumber[All Fields] OR sea urchin[All Fields] OR starfish[All Fields]) AND txid10239[Organism] NOT bacteria[Organism]', 'Echinodermata'),
    ('Sea_cucumber', '(Apostichopus[All Fields] OR Holothuria[All Fields] OR sea cucumber[All Fields]) AND txid10239[Organism] NOT bacteria[Organism]', 'Echinodermata'),
    ('Sponge_virus', '(sponge[All Fields] OR Porifera[All Fields] OR Amphimedon[All Fields]) AND txid10239[Organism] NOT bacteria[Organism]', 'Porifera'),
    ('Marine_invert', 'marine invertebrate[All Fields] AND txid10239[Organism] NOT bacteria[Organism] NOT cellular[Organism] AND 2015:2026[pdat]', None),
    ('Parvoviridae_inv', '(Parvoviridae[All Fields] OR Densovirinae[All Fields]) AND (invertebrate[All Fields] OR shrimp[All Fields] OR crab[All Fields]) AND txid10239[Organism] NOT bacteria[Organism]', 'Arthropoda'),
    ('Mollusk_DNA_virus', '(oyster[All Fields] OR clam[All Fields] OR mussel[All Fields] OR abalone[All Fields]) AND (herpesvirus[All Fields] OR DNA virus[All Fields]) AND txid10239[Organism] NOT bacteria[Organism]', 'Mollusca'),
    ('Crust_DNA_virus', '(shrimp[All Fields] OR crab[All Fields] OR crayfish[All Fields] OR prawn[All Fields]) AND (Nimaviridae[All Fields] OR Nudiviridae[All Fields] OR Iridoviridae[All Fields]) AND txid10239[Organism] NOT bacteria[Organism] AND 2010:2026[pdat]', 'Arthropoda'),
]

SKIP = re.compile(r'uncultured|bacterium|bacteria|fungus|fungi|Homo sapien|Mus musculus|'
                  r'Escherichia coli|Saccharomyces|Arabidopsis|Danio rerio|Rattus |'
                  r'Bos taurus|Gallus gallus|Drosophila|Caenorhabditis|Xenopus|'
                  r'Oryza|Zea mays|phage\b|\w+ bacterium|\w+ bacteria', re.IGNORECASE)

def ncbi(endpoint, params, db='nucleotide'):
    params['db'] = db; params['retmode'] = 'xml'
    qs = urllib.parse.urlencode(params)
    url = f'https://eutils.ncbi.nlm.nih.gov/entrez/eutils/{endpoint}?{qs}'
    time.sleep(RATE)
    for _ in range(3):
        try:
            req = urllib.request.Request(url)
            req.add_header('User-Agent', 'AquaVir-KB/2.0')
            with urllib.request.urlopen(req, timeout=20) as r:
                return r.read().decode('utf-8')
        except: time.sleep(2)
    return None

def fetch_gb(ids):
    results = []
    for i in range(0, len(ids), 10):
        xml_s = ncbi('efetch.fcgi', {'id': ','.join(ids[i:i+10]), 'rettype': 'gb', 'retmode': 'xml'})
        if not xml_s: continue
        try: root = ET.fromstring(xml_s)
        except: continue
        for seq in root.findall('.//GBSeq'):
            acc = (seq.findtext('GBSeq_primary-accession') or '').strip()
            org = (seq.findtext('GBSeq_organism') or '').strip()
            if not acc or not org or SKIP.search(org): continue
            if 'virus' not in org.lower(): continue
            mol = (seq.findtext('GBSeq_moltype') or '').strip()
            length_s = (seq.findtext('GBSeq_length') or '0').strip()
            results.append({'acc': acc, 'org': org, 'mol': mol,
                           'len': int(length_s) if length_s.isdigit() else 0})
    return results

conn = sqlite3.connect(DB)
c = conn.cursor()
c.execute('SELECT DISTINCT accession FROM viral_isolates')
existing_acc = {r[0] for r in c.fetchall()}
c.execute('SELECT DISTINCT LOWER(canonical_name) FROM virus_master')
existing_names = {r[0] for r in c.fetchall()}
start_sp = c.execute('SELECT COUNT(*) FROM virus_master').fetchone()[0]
start_iso = len(existing_acc)
print(f'Start: {start_sp} species, {start_iso} isolates')

total_iso, total_sp = 0, 0
for label, term, phylum in QUERIES:
    print(f'[{phylum or "any":20s}] {label:25s}', end=' ', flush=True)
    xml_s = ncbi('esearch.fcgi', {'term': term, 'retmax': '80', 'sort': 'relevance', 'usehistory': 'y'})
    if not xml_s: print('FAIL'); continue
    try:
        root = ET.fromstring(xml_s)
        ids = [e.text for e in root.findall('.//Id') if e.text]
        cnt = int(root.findtext('.//Count') or '0')
    except: print('PARSE_FAIL'); continue
    new_ids = [i for i in ids if i not in existing_acc][:30]
    if not new_ids: print(f'{cnt:5d} total, 0 new'); continue
    print(f'{cnt:5d} total, {len(new_ids):2d} new...', end=' ', flush=True)
    recs = fetch_gb(new_ids)
    iso, sp = 0, 0
    for rec in recs:
        if rec['acc'] in existing_acc: continue
        c.execute("SELECT master_id FROM virus_master WHERE canonical_name = ?", (rec['org'],))
        vm = c.fetchone()
        if vm:
            mid = vm[0]
        elif rec['org'].lower() in existing_names:
            c.execute("SELECT master_id FROM virus_master WHERE LOWER(canonical_name) = ?", (rec['org'].lower(),))
            vm = c.fetchone()
            mid = vm[0] if vm else None
        else:
            try:
                gt = 'DNA' if 'dna' in rec['mol'].lower() else 'RNA' if 'rna' in rec['mol'].lower() else ''
                c.execute("INSERT INTO virus_master (canonical_name, genome_type, entry_type, discovery_context, host_phylum) VALUES (?,?,?,?,?)",
                         (rec['org'], gt, 'partial_genome', 'metagenomic_survey', phylum))
                mid = c.lastrowid
                existing_names.add(rec['org'].lower())
                sp += 1
            except sqlite3.IntegrityError:
                c.execute("SELECT master_id FROM virus_master WHERE canonical_name = ?", (rec['org'],))
                vm = c.fetchone()
                mid = vm[0] if vm else None
        if not mid: continue
        try:
            gt = 'DNA' if 'dna' in rec['mol'].lower() else 'RNA' if 'rna' in rec['mol'].lower() else None
            c.execute("INSERT INTO viral_isolates (accession, virus_name, master_id, genome_length, genome_type) VALUES (?,?,?,?,?)",
                     (rec['acc'], rec['org'], mid, rec['len'], gt))
            existing_acc.add(rec['acc']); iso += 1
        except sqlite3.IntegrityError: continue
    total_iso += iso; total_sp += sp
    print(f'+{iso} iso +{sp} sp')
    if total_iso % 200 == 0: conn.commit()

conn.commit()
c.execute('SELECT COUNT(*) FROM virus_master'); final_sp = c.fetchone()[0]
c.execute('SELECT COUNT(*) FROM viral_isolates'); final_iso = c.fetchone()[0]
print(f'\nFINAL: {final_sp} species (+{final_sp-start_sp}), {final_iso} isolates (+{final_iso-start_iso})')
print(f'Total growth: {start_sp} -> {final_sp} species, {start_iso} -> {final_iso} isolates')
conn.close()
