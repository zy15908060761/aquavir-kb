#!/usr/bin/env python3
"""Mine GenBank accessions from virome paper abstracts and search for novel virus sequences."""
import sqlite3, re, json

conn = sqlite3.connect('F:/水生无脊椎动物数据库/crustacean_virus_core.db')

# Find virome/metagenomic papers in our references
virome_refs = conn.execute("""
SELECT reference_id, title, abstract, pmid, year
FROM ref_literatures
WHERE (title LIKE '%virome%' OR title LIKE '%metatranscriptom%' OR title LIKE '%metagenom%'
   OR title LIKE '%viral diversity%' OR title LIKE '%virus discovery%'
   OR title LIKE '%RNA virome%' OR title LIKE '%novel virus%'
   OR abstract LIKE '%virome%' OR abstract LIKE '%metatranscriptom%')
  AND year >= '2018'
ORDER BY year DESC
""").fetchall()

print(f"Virome/metagenomic papers in DB: {len(virome_refs)}")

# Extract GenBank/RefSeq accessions from text
gb_pattern = re.compile(r'\b([A-Z]{1,2}\d{5,6}|[A-Z]{4}\d{8,9}|NC_\d{6,7}|NW_\d{7,8}|NT_\d{7,8}|AC_\d{6,7})\b')
sra_pattern = re.compile(r'\b([SED]RR\d{6,9}|PRJNA\d{5,8}|SAMN\d{7,9})\b')

# Existing accessions in viral_isolates
existing_accs = {r[0] for r in conn.execute("SELECT accession FROM viral_isolates WHERE accession IS NOT NULL").fetchall()}
existing_sra = {r[0] for r in conn.execute("SELECT sra_accession FROM sra_runs").fetchall()}
existing_bp = {r[0] for r in conn.execute("SELECT bioproject FROM sra_runs WHERE bioproject IS NOT NULL").fetchall()}

new_gb = set()
new_sra = set()
linked_bp = set()

for ref_id, title, abstract, pmid, year in virome_refs:
    text = f"{title or ''} {abstract or ''}"

    # Extract GenBank accessions
    gb_matches = gb_pattern.findall(text)
    for acc in gb_matches:
        if acc not in existing_accs:
            new_gb.add(acc)

    # Extract SRA/BioProject accessions
    sra_matches = sra_pattern.findall(text)
    for acc in sra_matches:
        if acc.startswith('PRJNA') and acc not in existing_bp:
            linked_bp.add(acc)
        elif acc not in existing_sra and acc not in existing_bp:
            new_sra.add(acc)

print(f"\nNovel GenBank accessions found in virome papers: {len(new_gb)}")
print(f"Novel SRA/BioProject accessions found: {len(new_sra)}")
print(f"BioProjects to add: {len(linked_bp)}")

# Validate accessions via NCBI E-utilities (batch check existence)
validated = []
print("\nValidating GenBank accessions via NCBI...")
import urllib.request, urllib.parse, xml.etree.ElementTree as ET, time

gb_list = list(new_gb)
batch_size = 50
for i in range(0, min(len(gb_list), 500), batch_size):  # Check up to 500
    batch = gb_list[i:i+batch_size]
    joined = ','.join(batch)
    try:
        params = {'db': 'nucleotide', 'id': joined, 'retmode': 'xml', 'rettype': 'docsum'}
        url = 'https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi?' + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, headers={'User-Agent': 'AquaVir-KB/1.0'})
        resp = urllib.request.urlopen(req, timeout=30)
        root = ET.fromstring(resp.read().decode())

        for doc in root.findall('.//Document'):
            acc = doc.findtext('AccessionVersion', '')
            org = doc.findtext('Organism', '')
            title_el = doc.findtext('Title', '')
            slen = doc.findtext('Slen', '')

            if acc and 'virus' in (org or '').lower():
                validated.append({
                    'accession': acc,
                    'organism': org,
                    'title': (title_el or '')[:300],
                    'length': slen,
                })
        time.sleep(0.35)
    except Exception as e:
        print(f"  Validation error: {e}")

print(f"Validated virus accessions: {len(validated)}")

# Import validated virus accessions as new viral_isolates
imported = 0
def nid(t, c):
    return conn.execute(f"SELECT COALESCE(MAX({c}),0) FROM {t}").fetchone()[0] + 1

for v in validated:
    if v['accession'] in existing_accs:
        continue
    isoid = nid('viral_isolates', 'isolate_id')
    try:
        conn.execute("""
        INSERT INTO viral_isolates (isolate_id, accession, virus_name, genome_type,
            has_sequence, completeness, sequence_length)
        VALUES (?, ?, ?, 'unknown', 1, 'unknown', ?)
        """, (isoid, v['accession'], v['organism'][:200], v.get('length') or 0))
        imported += 1
        existing_accs.add(v['accession'])
    except Exception as e:
        pass

conn.commit()
print(f"Imported new viral_isolates: {imported}")
print(f"Total viral_isolates now: {conn.execute('SELECT COUNT(*) FROM viral_isolates').fetchone()[0]}")

# Save results for later use
results = {
    'virome_papers': len(virome_refs),
    'new_genbank': list(new_gb)[:100],
    'new_sra': list(new_sra)[:100],
    'new_bioprojects': list(linked_bp)[:100],
    'validated_virus': validated,
}
with open('F:/水生无脊椎动物数据库/virome_mining_results.json', 'w', encoding='utf-8') as f:
    json.dump(results, f, ensure_ascii=False, indent=2)

print(f"Results saved to virome_mining_results.json")
conn.close()
