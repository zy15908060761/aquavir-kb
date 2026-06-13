#!/usr/bin/env python3
"""Extract evidence_records from newly imported references using title/abstract matching."""
import sqlite3, re, datetime

conn = sqlite3.connect('F:/水生无脊椎动物数据库/crustacean_virus_core.db')
ts = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')

# Get references that have NO evidence yet
new_refs = conn.execute("""
SELECT rl.reference_id, rl.title, rl.abstract, rl.pmid, rl.year
FROM ref_literatures rl
WHERE rl.reference_id NOT IN (
    SELECT DISTINCT reference_id FROM evidence_records WHERE reference_id IS NOT NULL
)
AND rl.title IS NOT NULL AND rl.title != ''
ORDER BY rl.reference_id DESC
""").fetchall()
print(f"References without evidence: {len(new_refs)}")

# Load virus and host lookup dictionaries
viruses = {}
for r in conn.execute("SELECT master_id, canonical_name, virus_family, host_phylum FROM virus_master").fetchall():
    name = r[1].lower()
    viruses[r[0]] = {
        'name': name,
        'family': (r[2] or '').lower(),
        'phylum': (r[3] or '').lower(),
        'tokens': set(name.split()),
    }

hosts = {}
for r in conn.execute("SELECT host_id, scientific_name, common_name_cn, phylum FROM crustacean_hosts").fetchall():
    name = (r[1] or '').lower()
    hosts[r[0]] = {
        'name': name,
        'cn': (r[2] or '').lower(),
        'phylum': (r[3] or '').lower(),
        'tokens': set(name.split()) if name else set(),
    }

# Evidence type keywords
EVIDENCE_TYPES = {
    'diagnosis': [r'PCR', r'RT-PCR', r'qPCR', r'RT-qPCR', r'detection', r'diagnostic', r'ELISA',
                  r'LAMP', r'RPA', r'RAA', r'ISH', r'in.situ.hybridization', r'immunohistochemistry',
                  r'microarray', r'biosensor', r'histopathology', r'TEM', r'electron microscopy'],
    'host_range': [r'host range', r'host specificity', r'susceptibility', r'experimental infection',
                   r'challenge', r'bioassay', r'cohabitation', r'transmission trial',
                   r'cross.species', r'new host', r'novel host', r'first report'],
    'pathogenicity': [r'virulence', r'pathogenic', r'pathogenicity', r'lesion', r'histopatholog',
                      r'tissue tropism', r'clinical sign', r'symptom', r'morbidity', r'disease'],
    'mortality': [r'mortality', r'survival rate', r'cumulative mortality', r'death', r'lethal'],
    'prevalence': [r'prevalence', r'infection rate', r'positive rate', r'carrier', r'epidemiology',
                   r'surveillance', r'survey', r'outbreak', r'screening'],
    'transmission': [r'transmission', r'horizontal transmission', r'vertical transmission',
                     r'waterborne', r'cohabitation', r'vector', r'carrier'],
    'temperature': [r'temperature', r'thermal', r'heat stress', r'cold stress', r'water temperature'],
    'genome': [r'genome', r'complete genome', r'genomic characterization', r'molecular characterization',
               r'sequence', r'phylogenetic', r'genetic diversity', r'genotype'],
}

def classify_evidence_type(text):
    """Classify evidence type from text content."""
    scores = {}
    for etype, patterns in EVIDENCE_TYPES.items():
        score = 0
        for pat in patterns:
            if re.search(pat, text, re.IGNORECASE):
                score += 1
        if score > 0:
            scores[etype] = score
    if not scores:
        return 'host_range'  # default
    return max(scores, key=scores.get)

def infer_evidence_strength(text):
    """Infer evidence strength from methods description."""
    tl = text.lower()
    if re.search(r'(experimental infection|Koch.s postulat|virus isolation|cultured|cell line|in vitro|in vivo.*challenge|fulfill.*Koch)', tl):
        return 'high'
    if re.search(r'(RT-PCR|qPCR|metagenomic|sequence|genome|phylogenetic|NGS|histopatholog|TEM|electron microscopy)', tl):
        return 'medium'
    return 'low'

def infer_host_assoc_method(text):
    tl = text.lower()
    if re.search(r'(experimental infection|Koch.s postulat|virus isolation|cell culture|cultured.*virus)', tl):
        return 'confirmed_infection'
    if re.search(r'(histopatholog|TEM|electron microscopy|tissue.*section|paraffin.*embed)', tl):
        return 'pathology_observation'
    if re.search(r'(outbreak|mass mortality|epidemic|epizootic|die.off)', tl):
        return 'disease_outbreak'
    if re.search(r'(metagenomic|metatranscriptom|virome|NGS|high.throughput|RNA.seq|shotgun)', tl):
        return 'co_occurrence_metagenomic'
    return 'co_occurrence_metagenomic'

def nid(table, col):
    return conn.execute(f'SELECT COALESCE(MAX({col}),0) FROM {table}').fetchone()[0] + 1

# Main extraction loop
evidence_created = 0
infection_created = 0

for ref_id, title, abstract, pmid, year in new_refs:
    text = f"{title or ''} {abstract or ''}"
    tl = text.lower()
    if len(text) < 50:
        continue

    # Match viruses by name tokens
    matched_viruses = []
    for mid, vinfo in viruses.items():
        tokens = vinfo['tokens']
        if len(tokens) >= 2:
            # Require ALL tokens for compound names
            if all(t in tl for t in tokens):
                matched_viruses.append(mid)
        elif len(tokens) == 1:
            tok = list(tokens)[0]
            if len(tok) > 5 and tok in tl:
                matched_viruses.append(mid)

    # Match hosts by name
    matched_hosts = []
    for hid, hinfo in hosts.items():
        hname = hinfo['name']
        if hname and len(hname) > 5 and hname in tl:
            matched_hosts.append(hid)

    # Create records for matched pairs
    for mid in matched_viruses[:3]:  # max 3 viruses per ref to avoid noise
        for hid in matched_hosts[:3]:  # max 3 hosts
            etype = classify_evidence_type(text)
            strength = infer_evidence_strength(text)
            eid = nid('evidence_records', 'evidence_id')

            try:
                conn.execute("""
                INSERT INTO evidence_records (evidence_id, evidence_type, virus_master_id, host_id,
                    reference_id, claim, evidence_strength, source_pmid,
                    extraction_method, curation_status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?,
                    'auto_epmc_title_abstract_match', 'auto_imported')
                """, (eid, etype, mid, hid, ref_id, (title or '')[:500], strength, pmid))
                evidence_created += 1
            except:
                pass

        # Create infection records for host-virus pairs
        if matched_hosts and len(matched_viruses) > 0:
            for mid in matched_viruses[:2]:
                for hid in matched_hosts[:2]:
                    method = infer_host_assoc_method(text)
                    irec_id = nid('infection_records', 'record_id')
                    try:
                        conn.execute("""
                        INSERT INTO infection_records (record_id, isolate_id, host_id,
                            detection_method, reference_id, host_association_method)
                        VALUES (?, NULL, ?, 'literature_mining', ?, ?)
                        """, (irec_id, hid, ref_id, method))
                        infection_created += 1
                    except:
                        pass

    if evidence_created % 500 == 0 and evidence_created > 0:
        conn.commit()
        print(f"  Evidence: {evidence_created}, Infections: {infection_created}...")

conn.commit()
total_ev = conn.execute("SELECT COUNT(*) FROM evidence_records").fetchone()[0]
total_inf = conn.execute("SELECT COUNT(*) FROM infection_records").fetchone()[0]
print(f"\nCreated: {evidence_created} evidence_records, {infection_created} infection_records")
print(f"Total evidence: {total_ev}")
print(f"Total infections: {total_inf}")
conn.close()
