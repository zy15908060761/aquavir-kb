"""
补全：对768核心水生无脊椎病毒，从NCBI GenBank提取/host字段，
自动创建宿主条目和infection_records。
"""
import sqlite3, time, urllib.request, urllib.parse, xml.etree.ElementTree as ET, re, sys

DB = 'F:/甲壳动物数据库/crustacean_virus_core.db'
RATE = 0.3

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

def fetch_hosts_from_genbank(accessions):
    """Fetch GenBank XML for accessions, extract /host qualifier. Returns {acc: host_name}."""
    results = {}
    for i in range(0, len(accessions), 15):
        batch = accessions[i:i+15]
        xml_s = ncbi('efetch.fcgi', {'id': ','.join(batch), 'rettype': 'gb', 'retmode': 'xml'})
        if not xml_s: continue
        try: root = ET.fromstring(xml_s)
        except: continue
        for seq in root.findall('.//GBSeq'):
            acc = (seq.findtext('GBSeq_primary-accession') or '').strip()
            if not acc: continue
            host = ''
            country = ''
            feat_elem = seq.find('GBSeq_feature-table')
            if feat_elem is not None:
                for feat in feat_elem.findall('GBFeature'):
                    for qual in feat.findall('.//GBQualifier'):
                        qname = (qual.findtext('GBQualifier_name') or '').lower()
                        qval = (qual.findtext('GBQualifier_value') or '').strip()
                        if qname == 'host': host = qval
                        elif qname == 'country': country = qval
            if host:
                results[acc] = {'host': host, 'country': country}
    return results

# ── Genus lookup for host taxonomy ────────────────────────────────────────
GENUS_TAXONOMY = {
    'penaeus': ('Arthropoda','Malacostraca','Decapoda','Penaeidae','target_crustacean'),
    'litopenaeus': ('Arthropoda','Malacostraca','Decapoda','Penaeidae','target_crustacean'),
    'marsupenaeus': ('Arthropoda','Malacostraca','Decapoda','Penaeidae','target_crustacean'),
    'fenneropenaeus': ('Arthropoda','Malacostraca','Decapoda','Penaeidae','target_crustacean'),
    'metapenaeus': ('Arthropoda','Malacostraca','Decapoda','Penaeidae','target_crustacean'),
    'macrobrachium': ('Arthropoda','Malacostraca','Decapoda','Palaemonidae','target_crustacean'),
    'palaemon': ('Arthropoda','Malacostraca','Decapoda','Palaemonidae','target_crustacean'),
    'homarus': ('Arthropoda','Malacostraca','Decapoda','Nephropidae','target_crustacean'),
    'procambarus': ('Arthropoda','Malacostraca','Decapoda','Cambaridae','target_crustacean'),
    'cherax': ('Arthropoda','Malacostraca','Decapoda','Parastacidae','target_crustacean'),
    'pacifastacus': ('Arthropoda','Malacostraca','Decapoda','Astacidae','target_crustacean'),
    'callinectes': ('Arthropoda','Malacostraca','Decapoda','Portunidae','target_crustacean'),
    'scylla': ('Arthropoda','Malacostraca','Decapoda','Portunidae','target_crustacean'),
    'portunus': ('Arthropoda','Malacostraca','Decapoda','Portunidae','target_crustacean'),
    'charybdis': ('Arthropoda','Malacostraca','Decapoda','Portunidae','target_crustacean'),
    'eriocheir': ('Arthropoda','Malacostraca','Decapoda','Varunidae','target_crustacean'),
    'carcinus': ('Arthropoda','Malacostraca','Decapoda','Portunidae','target_crustacean'),
    'cancer': ('Arthropoda','Malacostraca','Decapoda','Cancridae','target_crustacean'),
    'daphnia': ('Arthropoda','Branchiopoda','Cladocera','Daphniidae','target_crustacean'),
    'artemia': ('Arthropoda','Branchiopoda','Anostraca','Artemiidae','target_crustacean'),
    'gammarus': ('Arthropoda','Malacostraca','Amphipoda','Gammaridae','target_crustacean'),
    'euphausia': ('Arthropoda','Malacostraca','Euphausiacea','Euphausiidae','target_crustacean'),
    'balanus': ('Arthropoda','Maxillopoda','Sessilia','Balanidae','target_crustacean'),
    'crassostrea': ('Mollusca','Bivalvia','Ostreoida','Ostreidae','target_mollusk'),
    'saccostrea': ('Mollusca','Bivalvia','Ostreoida','Ostreidae','target_mollusk'),
    'ostrea': ('Mollusca','Bivalvia','Ostreoida','Ostreidae','target_mollusk'),
    'mytilus': ('Mollusca','Bivalvia','Mytiloida','Mytilidae','target_mollusk'),
    'perna': ('Mollusca','Bivalvia','Mytiloida','Mytilidae','target_mollusk'),
    'ruditapes': ('Mollusca','Bivalvia','Veneroida','Veneridae','target_mollusk'),
    'mercenaria': ('Mollusca','Bivalvia','Veneroida','Veneridae','target_mollusk'),
    'meretrix': ('Mollusca','Bivalvia','Veneroida','Veneridae','target_mollusk'),
    'pecten': ('Mollusca','Bivalvia','Pectinida','Pectinidae','target_mollusk'),
    'argopecten': ('Mollusca','Bivalvia','Pectinida','Pectinidae','target_mollusk'),
    'chlamys': ('Mollusca','Bivalvia','Pectinida','Pectinidae','target_mollusk'),
    'mizuhopecten': ('Mollusca','Bivalvia','Pectinida','Pectinidae','target_mollusk'),
    'haliotis': ('Mollusca','Gastropoda','Lepetellida','Haliotidae','target_mollusk'),
    'octopus': ('Mollusca','Cephalopoda','Octopoda','Octopodidae','target_mollusk'),
    'sepia': ('Mollusca','Cephalopoda','Sepiida','Sepiidae','target_mollusk'),
    'acropora': ('Cnidaria','Anthozoa','Scleractinia','Acroporidae','target_other_aquatic_invert'),
    'porites': ('Cnidaria','Anthozoa','Scleractinia','Poritidae','target_other_aquatic_invert'),
    'pocillopora': ('Cnidaria','Anthozoa','Scleractinia','Pocilloporidae','target_other_aquatic_invert'),
    'apostichopus': ('Echinodermata','Holothuroidea','Synallactida','Stichopodidae','target_other_aquatic_invert'),
    'holothuria': ('Echinodermata','Holothuroidea','Holothuriida','Holothuriidae','target_other_aquatic_invert'),
    'strongylocentrotus': ('Echinodermata','Echinoidea','Camarodonta','Strongylocentrotidae','target_other_aquatic_invert'),
    'asterias': ('Echinodermata','Asteroidea','Forcipulatida','Asteriidae','target_other_aquatic_invert'),
    'amphimedon': ('Porifera','Demospongiae','Haplosclerida','Niphatidae','target_other_aquatic_invert'),
}

def resolve_host_taxonomy(host_name):
    """Try to match a host name to known taxonomy."""
    if not host_name: return None
    words = host_name.lower().replace(',',' ').replace('(',' ').replace(')',' ').split()
    # Try first word as genus
    for w in words:
        w = re.sub(r'[^a-z]', '', w)
        if w in GENUS_TAXONOMY:
            return GENUS_TAXONOMY[w]
    return None

conn = sqlite3.connect(DB)
c = conn.cursor()

# Get core viruses without infection records
c.execute('''SELECT vm.master_id, vm.canonical_name, vm.host_phylum, vi.accession
             FROM virus_master vm
             JOIN viral_isolates vi ON vm.master_id = vi.master_id
             WHERE vm.host_phylum IN ('Arthropoda','Mollusca','Cnidaria','Echinodermata','Porifera')
             AND vm.master_id NOT IN (
                 SELECT DISTINCT vi2.master_id FROM viral_isolates vi2
                 JOIN infection_records ir ON vi2.isolate_id = ir.isolate_id
             )
             GROUP BY vm.master_id
             LIMIT 500''')
need_hosts = c.fetchall()
print(f'Core viruses needing host linkage: {len(need_hosts)}')

# Get accessions to query
acc_to_master = {}
for mid, name, phylum, acc in need_hosts:
    if acc and acc not in acc_to_master:
        acc_to_master[acc] = (mid, name, phylum)

accessions = list(acc_to_master.keys())
print(f'Fetching GenBank host data for {len(accessions)} accessions...')

# Fetch in batches
new_hosts = 0
new_infections = 0
c.execute('SELECT LOWER(scientific_name), host_id FROM crustacean_hosts')
existing_host_names = {r[0]: r[1] for r in c.fetchall()}

for batch_start in range(0, len(accessions), 50):
    batch = accessions[batch_start:batch_start+50]
    print(f'  Batch {batch_start//50 + 1}/{len(accessions)//50 + 1} ({len(batch)} accs)...', end=' ', flush=True)
    host_data = fetch_hosts_from_genbank(batch)
    print(f'{len(host_data)} hosts found')

    for acc, info in host_data.items():
        if acc not in acc_to_master: continue
        mid, name, phylum = acc_to_master[acc]
        host_name = info['host']
        if not host_name: continue

        # Try to resolve taxonomy
        tax = resolve_host_taxonomy(host_name)
        if not tax:
            # Try to match existing host by substring
            host_lower = host_name.lower().strip()
            matched = None
            for ename, eid in existing_host_names.items():
                if host_lower in ename or ename in host_lower:
                    matched = eid; break
            if matched:
                # Create infection record with existing host
                try:
                    c.execute('INSERT INTO infection_records (isolate_id, host_id, host_association_method, detection_method) SELECT isolate_id, ?, \'ncbi_annotation\', \'sequence_analysis\' FROM viral_isolates WHERE accession = ? LIMIT 1', (matched, acc))
                    new_infections += 1
                except: pass
            continue

        phy, cls, order, fam, scope = tax

        # Clean host name - take first 2-3 words as binomial
        words = host_name.strip().split()
        if len(words) >= 2:
            clean_name = f'{words[0]} {words[1]}'
        else:
            clean_name = words[0]

        # Create or get host
        host_key = clean_name.lower()
        if host_key in existing_host_names:
            host_id = existing_host_names[host_key]
        else:
            try:
                c.execute('''INSERT INTO crustacean_hosts
                    (scientific_name, taxon_order, taxon_family, phylum, class, host_scope_status)
                    VALUES (?, ?, ?, ?, ?, ?)''',
                    (clean_name, order, fam, phy, cls, scope))
                host_id = c.lastrowid
                existing_host_names[host_key] = host_id
                new_hosts += 1
            except sqlite3.IntegrityError:
                c.execute('SELECT host_id FROM crustacean_hosts WHERE LOWER(scientific_name) = ?', (host_key,))
                ex = c.fetchone()
                if ex: host_id = ex[0]; existing_host_names[host_key] = host_id
                else: continue

        # Create infection record
        try:
            c.execute('INSERT INTO infection_records (isolate_id, host_id, host_association_method, detection_method) SELECT isolate_id, ?, \'ncbi_annotation\', \'sequence_analysis\' FROM viral_isolates WHERE accession = ? LIMIT 1', (host_id, acc))
            new_infections += 1
        except: pass

    if new_infections % 50 == 0:
        conn.commit()

conn.commit()

# Final stats
c.execute('SELECT COUNT(*) FROM infection_records'); total_inf = c.fetchone()[0]
c.execute('''SELECT COUNT(DISTINCT vm.master_id) FROM virus_master vm
             JOIN viral_isolates vi ON vm.master_id = vi.master_id
             JOIN infection_records ir ON vi.isolate_id = ir.isolate_id
             WHERE vm.host_phylum IN ('Arthropoda','Mollusca','Cnidaria','Echinodermata','Porifera')''')
core_linked = c.fetchone()[0]
c.execute('SELECT COUNT(*) FROM virus_master WHERE host_phylum IN (\'Arthropoda\',\'Mollusca\',\'Cnidaria\',\'Echinodermata\',\'Porifera\')')
core_total = c.fetchone()[0]
c.execute('SELECT COUNT(*) FROM crustacean_hosts'); host_total = c.fetchone()[0]

print(f'\nCOMPLETION RESULTS')
print('=' * 50)
print(f'New host species created:       {new_hosts}')
print(f'New infection records:          {new_infections}')
print(f'Total infection records:        {total_inf}')
print(f'Core species with host linkage: {core_linked} / {core_total} ({core_linked/core_total*100:.1f}%)')
print(f'Total host species:             {host_total}')

conn.close()
