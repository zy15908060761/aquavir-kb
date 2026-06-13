"""Batch 4: HIGH VOLUME import. 100 records per query, comprehensive family coverage."""
import sqlite3, time, urllib.request, urllib.parse, xml.etree.ElementTree as ET, re

DB = 'F:/甲壳动物数据库/crustacean_virus_core.db'
RATE = 0.3

QUERIES = [
    ('Nimaviridae', 'Nimaviridae[Organism]', 'Arthropoda'),
    ('Nudiviridae', 'Nudiviridae[Organism] AND 2000:2026[pdat]', 'Arthropoda'),
    ('Iridoviridae', 'Iridoviridae[Organism] AND (invertebrate OR crustacean OR mollusc OR insect OR shrimp) AND 2000:2026[pdat]', None),
    ('Baculoviridae', 'Baculoviridae[Organism] AND (invertebrate OR shrimp OR crab OR insect) AND 2000:2026[pdat]', 'Arthropoda'),
    ('Polydnaviridae', 'Polydnaviridae[Organism] AND 2000:2026[pdat]', None),
    ('Hytrosaviridae', 'Hytrosaviridae[Organism] AND 2000:2026[pdat]', None),
    ('Mesoniviridae', 'Mesoniviridae[Organism] AND 2000:2026[pdat]', None),
    ('Roniviridae', 'Roniviridae[Organism] AND 2000:2026[pdat]', 'Arthropoda'),
    ('Sarthroviridae', 'Sarthroviridae[Organism] AND 2000:2026[pdat]', 'Arthropoda'),
    ('Dicistroviridae', 'Dicistroviridae[Organism] AND 2000:2026[pdat]', 'Arthropoda'),
    ('Iflaviridae', 'Iflaviridae[Organism] AND 2000:2026[pdat]', 'Arthropoda'),
    ('Nodaviridae', 'Nodaviridae[Organism] AND 2000:2026[pdat]', None),
    ('Solemoviridae', 'Solemoviridae[Organism] AND 2000:2026[pdat]', None),
    ('Totiviridae', 'Totiviridae[Organism] AND (invertebrate OR crustacean OR mollusc OR shrimp) AND 2000:2026[pdat]', None),
    ('Partitiviridae', 'Partitiviridae[Organism] AND 2000:2026[pdat]', None),
    ('Botourmiaviridae', 'Botourmiaviridae[Organism] AND 2000:2026[pdat]', None),
    ('Mitoviridae', 'Mitoviridae[Organism] AND 2000:2026[pdat]', None),
    ('Astroviridae', 'Astroviridae[Organism] AND 2000:2026[pdat]', None),
    ('Caliciviridae', 'Caliciviridae[Organism] AND 2000:2026[pdat]', None),
    ('Hepeviridae', 'Hepeviridae[Organism] AND 2000:2026[pdat]', None),
    ('Reoviridae', 'Reoviridae[Organism] AND (invertebrate OR crustacean OR shrimp OR crab) AND 2000:2026[pdat]', None),
    ('Chuviridae', 'Chuviridae[Organism] AND 2000:2026[pdat]', None),
    ('Yanviridae', 'Yanviridae[Organism] AND 2000:2026[pdat]', None),
    ('Weiviridae', 'Weiviridae[Organism] AND 2000:2026[pdat]', None),
    ('Zhaoviridae', 'Zhaoviridae[Organism] AND 2000:2026[pdat]', None),
    ('Qinviridae', 'Qinviridae[Organism] AND 2000:2026[pdat]', None),
    ('Rhabdoviridae', 'Rhabdoviridae[Organism] AND 2000:2026[pdat]', None),
    ('Circoviridae', 'Circoviridae[Organism] AND 2000:2026[pdat]', None),
    ('Parvoviridae', 'Parvoviridae[Organism] AND 2000:2026[pdat]', None),
    ('Genomoviridae', 'Genomoviridae[Organism] AND 2000:2026[pdat]', None),
    ('Smacoviridae', 'Smacoviridae[Organism] AND 2000:2026[pdat]', None),
    ('Bidnaviridae', 'Bidnaviridae[Organism] AND 2000:2026[pdat]', None),
    ('Bunyavirales_aq', 'Bunyavirales[Organism] AND (invertebrate OR crustacean OR shrimp OR crab OR marine) AND 2000:2026[pdat]', None),
    ('Mononegavirales_aq', 'Mononegavirales[Organism] AND (invertebrate OR crustacean OR shrimp OR marine) AND 2000:2026[pdat]', None),
    ('Picornaviridae_aq', 'Picornaviridae[Organism] AND (invertebrate OR marine OR mollusc OR crustacean) AND 2000:2026[pdat]', None),
    ('Coronaviridae_aq', 'Coronaviridae[Organism] AND (invertebrate OR crustacean OR marine) AND 2000:2026[pdat]', None),
    ('Oyster_complete', 'oyster AND complete genome[title] AND txid10239[Organism] NOT bacteria[Organism] AND 2000:2026[pdat]', 'Mollusca'),
    ('Mussel_complete', 'mussel AND complete genome[title] AND txid10239[Organism] NOT bacteria[Organism] AND 2000:2026[pdat]', 'Mollusca'),
    ('Abalone_complete', 'abalone AND complete genome[title] AND txid10239[Organism] NOT bacteria[Organism] AND 2000:2026[pdat]', 'Mollusca'),
    ('Clam_complete', 'clam AND complete genome[title] AND txid10239[Organism] NOT bacteria[Organism] AND 2000:2026[pdat]', 'Mollusca'),
    ('Scallop_complete', 'scallop AND complete genome[title] AND txid10239[Organism] NOT bacteria[Organism]', 'Mollusca'),
    ('Shrimp_complete', 'shrimp AND complete genome[title] AND txid10239[Organism] NOT bacteria[Organism] AND 2015:2026[pdat]', 'Arthropoda'),
    ('Crab_complete', 'crab AND complete genome[title] AND txid10239[Organism] NOT bacteria[Organism] AND 2015:2026[pdat]', 'Arthropoda'),
    ('Crayfish_complete', 'crayfish AND complete genome[title] AND txid10239[Organism] NOT bacteria[Organism] AND 2015:2026[pdat]', 'Arthropoda'),
    ('Coral_complete', 'coral AND complete genome[title] AND txid10239[Organism] NOT bacteria[Organism] AND 2000:2026[pdat]', 'Cnidaria'),
    ('Sponge_complete', 'sponge AND complete genome[title] AND txid10239[Organism] NOT bacteria[Organism] AND 2000:2026[pdat]', 'Porifera'),
    ('Sea_cucumber_complete', 'sea cucumber AND complete genome[title] AND txid10239[Organism] NOT bacteria[Organism] AND 2000:2026[pdat]', 'Echinodermata'),
]

SKIP = re.compile(
    r'uncultured|bacterium|bacteria|fungus|fungi|Homo sapien|Mus musculus|'
    r'Escherichia coli|Saccharomyces|Arabidopsis|Danio rerio|Rattus |'
    r'Bos taurus|Gallus gallus|Drosophila|Caenorhabditis|Xenopus|'
    r'Oryza|Zea mays|phage |bacterium|bacteria|human|HIV|SARS|'
    r'influenza|hepatitis|measles|rabies|ebola|immunodeficiency|mastadeno|'
    r'bovine|avian|canine|feline|porcine|murine|duck|chicken|turkey|mallard|teal',
    re.IGNORECASE
)

def ncbi(endpoint, params, db='nucleotide'):
    params['db'] = db; params['retmode'] = 'xml'
    qs = urllib.parse.urlencode(params)
    url = f'https://eutils.ncbi.nlm.nih.gov/entrez/eutils/{endpoint}?{qs}'
    time.sleep(RATE)
    for attempt in range(3):
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
            if not acc or not org: continue
            if SKIP.search(org): continue
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
    print(f'[{phylum or "any":20s}] {label:30s}', end=' ', flush=True)
    xml_s = ncbi('esearch.fcgi', {'term': term, 'retmax': '100', 'sort': 'relevance', 'usehistory': 'y'})
    if not xml_s: print('FAIL'); continue
    try:
        root = ET.fromstring(xml_s)
        ids = [e.text for e in root.findall('.//Id') if e.text]
        cnt = int(root.findtext('.//Count') or '0')
    except: print('PARSE_FAIL'); continue
    new_ids = [i for i in ids if i not in existing_acc][:50]
    if not new_ids: print(f'{cnt:5d} total, 0 new'); continue
    print(f'{cnt:5d} total, {len(new_ids):2d} new...', end=' ', flush=True)
    recs = fetch_gb(new_ids)
    iso, sp = 0, 0
    for rec in recs:
        if rec['acc'] in existing_acc: continue
        c.execute('SELECT master_id FROM virus_master WHERE canonical_name = ?', (rec['org'],))
        vm = c.fetchone()
        if vm:
            mid = vm[0]
        else:
            org_lower = rec['org'].lower()
            if org_lower in existing_names:
                c.execute('SELECT master_id FROM virus_master WHERE LOWER(canonical_name) = ?', (org_lower,))
                vm = c.fetchone(); mid = vm[0] if vm else None
            else:
                try:
                    gt = 'DNA' if 'dna' in rec['mol'].lower() else 'RNA'
                    c.execute('INSERT INTO virus_master (canonical_name,genome_type,entry_type,discovery_context,host_phylum) VALUES (?,?,?,?,?)',
                             (rec['org'], gt, 'partial_genome', 'metagenomic_survey', phylum))
                    mid = c.lastrowid; existing_names.add(org_lower); sp += 1
                except: continue
        if not mid: continue
        try:
            gt = 'DNA' if 'dna' in rec['mol'].lower() else 'RNA'
            c.execute('INSERT INTO viral_isolates (accession,virus_name,master_id,genome_length,genome_type) VALUES (?,?,?,?,?)',
                     (rec['acc'], rec['org'], mid, rec['len'], gt))
            existing_acc.add(rec['acc']); iso += 1
        except: continue
    total_iso += iso; total_sp += sp
    if sp > 0: print(f'+{iso}i +{sp}s')
    else: print(f'+{iso}i')
    if total_sp % 100 == 0: conn.commit(); print(f'  [commit +{total_sp}sp]')

conn.commit()
c.execute('SELECT COUNT(*) FROM virus_master'); final_sp = c.fetchone()[0]
c.execute('SELECT COUNT(*) FROM viral_isolates'); final_iso = c.fetchone()[0]
print(f'\nFINAL: {final_sp} species (+{final_sp-start_sp}), {final_iso} isolates (+{final_iso-start_iso})')
conn.close()
