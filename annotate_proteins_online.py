"""
Online protein annotation via NCBI E-utilities (www domain — confirmed working).
Uses elink to get: protein→conserved domains, protein→structures, protein→gene.

Strategy (all online, via www.ncbi.nlm.nih.gov):
  1. For each protein accession, use elink to find linked conserved domains (cdd)
  2. Fetch domain descriptions via esummary
  3. Use elink to find linked 3D structures
  4. Insert into interpro_annotations / protein_structures

Usage: python annotate_proteins_online.py [--max N] [--batch-size B]
"""

import sqlite3, time, urllib.request, urllib.parse, xml.etree.ElementTree as ET, ssl, sys

DB = 'F:/甲壳动物数据库/crustacean_virus_core.db'
NCBI = 'https://www.ncbi.nlm.nih.gov/entrez/eutils'
RATE = 0.4

# SSL context that tolerates network issues
ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

def ncbi(endpoint, params):
    params['retmode'] = 'xml'
    qs = urllib.parse.urlencode(params)
    url = f'{NCBI}/{endpoint}?{qs}'
    time.sleep(RATE)
    for attempt in range(5):
        try:
            req = urllib.request.Request(url)
            req.add_header('User-Agent', 'Mozilla/5.0 AquaVir-KB/2.0')
            with urllib.request.urlopen(req, timeout=20, context=ctx) as r:
                return r.read().decode('utf-8')
        except Exception as e:
            if attempt == 4: return None
            time.sleep(2 * (attempt + 1))
    return None

def get_linked_ids(protein_acc, target_db):
    """elink: protein → target_db. Returns list of linked IDs."""
    xml_s = ncbi('elink.fcgi', {
        'dbfrom': 'protein', 'db': target_db,
        'id': protein_acc, 'linkname': f'protein_{target_db}'
    })
    if not xml_s: return []
    try:
        root = ET.fromstring(xml_s)
        ids = [e.text for e in root.findall('.//Link/Id') if e.text]
        return ids
    except: return []

def get_domain_summary(domain_ids):
    """esummary for cdd domain IDs. Returns list of {id, title, accession}."""
    if not domain_ids: return []
    xml_s = ncbi('esummary.fcgi', {
        'db': 'cdd', 'id': ','.join(domain_ids[:50])
    })
    if not xml_s: return []
    results = []
    try:
        root = ET.fromstring(xml_s)
        for ds in root.findall('.//DocumentSummary'):
            uid = ds.get('uid', '')
            title = ds.findtext('Title', '') or ''
            acc = ds.findtext('Accession', '') or ''
            if uid:
                results.append({'id': uid, 'title': title[:200], 'accession': acc})
    except: pass
    return results

def get_structure_summary(struct_ids):
    """esummary for structure IDs."""
    if not struct_ids: return []
    xml_s = ncbi('esummary.fcgi', {
        'db': 'structure', 'id': ','.join(struct_ids[:30])
    })
    if not xml_s: return []
    results = []
    try:
        root = ET.fromstring(xml_s)
        for ds in root.findall('.//DocumentSummary'):
            uid = ds.get('uid', '')
            pdb_id = ds.findtext('PdbAcc', '') or ''
            title = ds.findtext('Title', '') or ''
            method = ds.findtext('ExpMethod', '') or ''
            if uid:
                results.append({'id': uid, 'pdb_id': pdb_id, 'title': title[:200], 'method': method})
    except: pass
    return results

def main():
    max_proteins = None
    for a in sys.argv:
        if a.startswith('--max='): max_proteins = int(a.split('=')[1])
    dry = '--dry-run' in sys.argv

    conn = sqlite3.connect(DB)
    c = conn.cursor()

    # Get proteins that DON'T have annotations yet
    c.execute('''SELECT vp.protein_id, vp.protein_accession, vp.aa_length, vm.virus_family,
                        vm.canonical_name
                 FROM viral_proteins vp
                 JOIN viral_isolates vi ON vp.isolate_id = vi.isolate_id
                 JOIN virus_master vm ON vi.master_id = vm.master_id
                 WHERE vp.protein_accession IS NOT NULL AND vp.protein_accession != ''
                 AND vp.protein_id NOT IN (
                     SELECT DISTINCT protein_id FROM interpro_annotations WHERE protein_id IS NOT NULL
                 )
                 ORDER BY vm.host_phylum IN ('Arthropoda','Mollusca','Cnidaria','Echinodermata','Porifera') DESC,
                          vp.aa_length DESC
                 LIMIT ?''', (max_proteins or 5000,))
    proteins = c.fetchall()
    print(f'Proteins to annotate: {len(proteins)}')

    new_domain_annos = 0
    new_structures = 0
    processed = 0
    skipped = 0

    for pid, pacc, length, family, vname in proteins:
        if not pacc or not pacc.strip():
            skipped += 1; continue

        if dry:
            processed += 1
            if processed % 100 == 0: print(f'  Dry: {processed}/{len(proteins)}')
            continue

        # Step 1: Find conserved domains for this protein
        domain_ids = get_linked_ids(pacc, 'cdd')
        if domain_ids:
            domains = get_domain_summary(domain_ids[:10])  # top 10 domains
            for d in domains:
                try:
                    c.execute('''INSERT OR IGNORE INTO interpro_annotations
                        (protein_id, interpro_id, interpro_name, source_database, fetched_at)
                        VALUES (?, ?, ?, 'NCBI_CDD', datetime('now'))''',
                        (pid, d['accession'], d['title']))
                    new_domain_annos += 1
                except sqlite3.IntegrityError: pass

        # Step 2: Find linked 3D structures
        struct_ids = get_linked_ids(pacc, 'structure')
        if struct_ids:
            structures = get_structure_summary(struct_ids[:5])
            for s in structures:
                if s['pdb_id']:
                    try:
                        c.execute('''INSERT OR IGNORE INTO protein_structures
                            (protein_id, source, entry_id, pdb_url, fetched_at)
                            VALUES (?, 'alphafold_ncbi', ?,
                            'https://www.ncbi.nlm.nih.gov/Structure/pdb/' || ?, datetime('now'))''',
                            (pid, s['pdb_id'], s['pdb_id']))
                        new_structures += 1
                    except sqlite3.IntegrityError: pass

        processed += 1
        if processed % 50 == 0:
            conn.commit()
            pct = processed/len(proteins)*100
            print(f'  [{processed}/{len(proteins)} {pct:.0f}%] +{new_domain_annos} domains, +{new_structures} structures')

    conn.commit()

    # Final stats
    c.execute('SELECT COUNT(DISTINCT protein_id) FROM interpro_annotations WHERE protein_id IS NOT NULL')
    proteins_with_domains = c.fetchone()[0]
    c.execute('SELECT COUNT(*) FROM protein_structures')
    total_structures = c.fetchone()[0]
    c.execute('SELECT COUNT(*) FROM viral_proteins')
    total_proteins = c.fetchone()[0]

    print(f'\n{"DRY RUN" if dry else "COMPLETE"}')
    print(f'New domain annotations: {new_domain_annos}')
    print(f'New structure links:    {new_structures}')
    print(f'Proteins with domains:  {proteins_with_domains}/{total_proteins}')
    print(f'Total structures:       {total_structures}')
    conn.close()

if __name__ == '__main__':
    main()
