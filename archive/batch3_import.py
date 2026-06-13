"""Batch 3: targeted virus family and broad marine invertebrate searches"""
import sqlite3, time, urllib.request, urllib.parse, xml.etree.ElementTree as ET, re

DB = 'F:/甲壳动物数据库/crustacean_virus_core.db'
RATE = 0.35

QUERIES = [
    # Broad virus family searches for aquatic invertebrate hosts
    ('Bunyavirales_aquatic', 'Bunyavirales[Organism] AND (invertebrate[All Fields] OR shrimp[All Fields] OR crab[All Fields] OR mollusc[All Fields] OR coral[All Fields]) AND 2000:2026[pdat]', None),
    ('Mononegavirales_aquatic', 'Mononegavirales[Organism] AND (invertebrate[All Fields] OR shrimp[All Fields] OR crab[All Fields] OR mollusc[All Fields]) AND 2000:2026[pdat]', None),
    ('Reoviridae_aquatic', 'Reoviridae[Organism] AND (invertebrate[All Fields] OR shrimp[All Fields] OR crab[All Fields] OR crayfish[All Fields] OR mollusc[All Fields]) AND 2000:2026[pdat]', None),
    ('Narnaviridae_aquatic', 'Narnaviridae[Organism] AND (invertebrate[All Fields] OR shrimp[All Fields] OR crab[All Fields] OR mollusc[All Fields]) AND 2000:2026[pdat]', None),
    ('Dicistroviridae', 'Dicistroviridae[Organism] AND (invertebrate[All Fields] OR shrimp[All Fields] OR crab[All Fields] OR prawn[All Fields]) AND 2000:2026[pdat]', 'Arthropoda'),
    ('Iflaviridae', 'Iflaviridae[Organism] AND (invertebrate[All Fields] OR shrimp[All Fields] OR crab[All Fields]) AND 2000:2026[pdat]', 'Arthropoda'),
    ('Solemoviridae', 'Solemoviridae[Organism] AND (invertebrate[All Fields] OR shrimp[All Fields] OR crab[All Fields] OR mollusc[All Fields]) AND 2000:2026[pdat]', None),
    ('Marnaviridae', 'Marnaviridae[Organism] AND (invertebrate[All Fields] OR shrimp[All Fields] OR crab[All Fields] OR mollusc[All Fields] OR marine[All Fields]) AND 2000:2026[pdat]', None),
    ('Astroviridae_invert', 'Astroviridae[Organism] AND (invertebrate[All Fields] OR shrimp[All Fields] OR crab[All Fields]) AND 2000:2026[pdat]', None),
    ('Caliciviridae_invert', 'Caliciviridae[Organism] AND (invertebrate[All Fields] OR mollusc[All Fields] OR oyster[All Fields]) AND 2000:2026[pdat]', None),
    ('Polycipiviridae', 'Polycipiviridae[Organism] AND 2000:2026[pdat]', None),
    ('Luteoviridae_invert', 'Luteoviridae[Organism] AND (invertebrate[All Fields] OR shrimp[All Fields]) AND 2000:2026[pdat]', None),

    # Marine metagenome viromes
    ('Marine_virome_complete', '(marine metagenome[All Fields] OR marine virome[All Fields]) AND complete genome[title] AND txid10239[Organism] NOT bacteria[Organism] NOT cellular[Organism] AND 2015:2026[pdat]', None),
    ('Aquatic_invert_metagenome', '(aquatic invertebrate[All Fields] OR marine invertebrate[All Fields]) AND metagenome[All Fields] AND txid10239[Organism] NOT bacteria[Organism] AND 2015:2026[pdat]', None),

    # Crustacean-specific under-sampled groups
    ('Copepod_virus', '(copepod[All Fields] OR Copepoda[All Fields]) AND txid10239[Organism] NOT bacteria[Organism]', 'Arthropoda'),
    ('Amphipod_virus', '(amphipod[All Fields] OR Amphipoda[All Fields]) AND txid10239[Organism] NOT bacteria[Organism]', 'Arthropoda'),
    ('Isopod_virus', '(isopod[All Fields] OR Isopoda[All Fields]) AND txid10239[Organism] NOT bacteria[Organism]', 'Arthropoda'),
    ('Barnacle_virus', '(barnacle[All Fields] OR Cirripedia[All Fields]) AND txid10239[Organism] NOT bacteria[Organism]', 'Arthropoda'),
    ('Krill_virus', '(krill[All Fields] OR Euphausiacea[All Fields]) AND txid10239[Organism] NOT bacteria[Organism]', 'Arthropoda'),
    ('Daphnia_virus', '(Daphnia[All Fields] OR Branchiopoda[All Fields]) AND txid10239[Organism] NOT bacteria[Organism]', 'Arthropoda'),

    # Nudiviruses and other insect/crustacean DNA viruses
    ('Nudiviridae_all', 'Nudiviridae[Organism] AND 2000:2026[pdat]', 'Arthropoda'),
    ('Baculoviridae_aquatic', 'Baculoviridae[Organism] AND (shrimp[All Fields] OR crab[All Fields] OR crayfish[All Fields] OR prawn[All Fields]) AND 2000:2026[pdat]', 'Arthropoda'),
    ('Polydnaviridae', 'Polydnaviridae[Organism] AND 2000:2026[pdat]', None),
    ('Bidnaviridae', 'Bidnaviridae[Organism] AND 2000:2026[pdat]', None),

    # Additional mollusk-specific viruses from recent papers
    ('Bivalve_transcriptome_virus', '(bivalve[All Fields] OR oyster[All Fields] OR mussel[All Fields]) AND transcriptome[All Fields] AND txid10239[Organism] NOT bacteria[Organism] AND 2018:2026[pdat]', 'Mollusca'),
    ('Gastropod_virus', '(snail[All Fields] OR Gastropoda[All Fields]) AND txid10239[Organism] NOT bacteria[Organism] AND 2010:2026[pdat]', 'Mollusca'),
]

SKIP = re.compile(r'uncultured|bacterium|bacteria|fungus|fungi|Homo sapien|Mus musculus|'
                  r'Escherichia coli|Saccharomyces|Arabidopsis|Danio rerio|Rattus |'
                  r'Bos taurus|Gallus gallus|Drosophila|Caenorhabditis|Xenopus|'
                  r'Oryza|Zea mays|^phage |\wbacterium|\wbacteria', re.IGNORECASE)

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
    print(f'[{phylum or "any":20s}] {label:30s}', end=' ', flush=True)
    xml_s = ncbi('esearch.fcgi', {'term': term, 'retmax': '90', 'sort': 'relevance', 'usehistory': 'y'})
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
    if total_iso % 150 == 0: conn.commit()

conn.commit()
c.execute('SELECT COUNT(*) FROM virus_master'); final_sp = c.fetchone()[0]
c.execute('SELECT COUNT(*) FROM viral_isolates'); final_iso = c.fetchone()[0]
print(f'\nFINAL: {final_sp} species (+{final_sp-start_sp}), {final_iso} isolates (+{final_iso-start_iso})')
print(f'Total: 530 -> {final_sp} species, 3790 -> {final_iso} isolates')
conn.close()
