#!/usr/bin/env python3
"""Evidence extraction v2 — fuzzy matching + family-level + improved NLP."""
import sqlite3, re, datetime

conn = sqlite3.connect('F:/水生无脊椎动物数据库/crustacean_virus_core.db')
ts = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')

# Get refs with 0 evidence
no_ev = conn.execute("""
SELECT rl.reference_id, rl.title, rl.abstract, rl.pmid, rl.doi, rl.year
FROM ref_literatures rl
WHERE rl.reference_id NOT IN (
    SELECT DISTINCT reference_id FROM evidence_records WHERE reference_id IS NOT NULL
)
AND rl.title IS NOT NULL AND rl.title != ''
ORDER BY rl.year DESC
""").fetchall()
print(f"References without evidence: {len(no_ev)}")

# Build richer lookup: virus names, family names, genus names
virus_lookup = {}
for r in conn.execute("""
SELECT master_id, canonical_name, virus_family, virus_genus, host_phylum
FROM virus_master
WHERE host_phylum NOT LIKE 'non_target%' AND host_phylum NOT LIKE 'non_aquatic%'
""").fetchall():
    mid, name, fam, genus, phy = r
    tokens_all = set()
    for s in [name, fam or '', genus or '']:
        for t in s.lower().split():
            if len(t) > 2:
                tokens_all.add(t)
    # Also add the full name as-is for substring matching
    virus_lookup[mid] = {
        'name': name.lower(),
        'family': (fam or '').lower(),
        'genus': (genus or '').lower(),
        'phylum': (phy or '').lower(),
        'tokens': tokens_all,
    }

host_lookup = {}
for r in conn.execute("""
SELECT host_id, scientific_name, common_name_cn, phylum, class, host_group
FROM crustacean_hosts
WHERE host_scope_status != 'excluded_non_target' OR host_scope_status IS NULL
""").fetchall():
    hid, name, cn, phy, cls, grp = r
    tokens_all = set()
    for s in [name or '', cn or '', phy or '', cls or '', grp or '']:
        for t in s.lower().split():
            if len(t) > 2:
                tokens_all.add(t)
    host_lookup[hid] = {
        'name': (name or '').lower(),
        'phylum': (phy or '').lower(),
        'class': (cls or '').lower(),
        'group': (grp or '').lower(),
        'tokens': tokens_all,
    }

# Better evidence type patterns
EVIDENCE_PATTERNS = {
    'genome': [r'complete genome', r'genome sequence', r'genomic characterization', r'molecular characterization',
               r'full.length genome', r'genome announcement', r'whole genome', r'genomic analysis',
               r'sequencing', r'genetic characterization', r'genome organization', r'genomic organization'],
    'diagnosis': [r'detection', r'diagnostic', r'PCR', r'RT.PCR', r'qPCR', r'RT.qPCR', r'LAMP',
                  r'RPA', r'RAA', r'ELISA', r'in situ hybridization', r'ISH', r'immunohistochemistry',
                  r'histopathology', r'electron microscopy', r'TEM', r'surveillance', r'screening'],
    'host_range': [r'host range', r'host specificity', r'susceptibility', r'experimental infection',
                   r'challenge experiment', r'bioassay', r'cross.species', r'new host', r'novel host',
                   r'first report', r'first detection', r'first isolation', r'first identification',
                   r'natural infection', r'coinfection', r'co.infection'],
    'pathogenicity': [r'virulence', r'pathogenic', r'pathogenicity', r'lesion', r'histopatholog',
                      r'tissue tropism', r'clinical sign', r'symptom', r'morbidity', r'disease',
                      r'patholog', r'necrosis', r'inflammation', r'atrophy', r'haemocyt',
                      r'white spot', r'inclusion body'],
    'mortality': [r'mortality', r'survival rate', r'cumulative mortality', r'death', r'lethal',
                  r'LC50', r'LD50', r'acute toxicity', r'mass mortali', r'die.off'],
    'prevalence': [r'prevalence', r'infection rate', r'positive rate', r'carrier', r'epidemiology',
                   r'survey', r'outbreak', r'screening', r'incidence', r'occurrence'],
    'transmission': [r'transmission', r'horizontal', r'vertical transmission', r'waterborne',
                     r'cohabitation', r'vector', r'carrier', r'oral infection', r'immersion',
                     r'injection', r'intramuscular', r'per os'],
    'temperature': [r'temperature', r'thermal', r'heat stress', r'cold stress', r'water temperature',
                    r'seasonal', r'summer', r'winter', r'environmental factor'],
}

def classify_evidence(text):
    scores = {}
    tl = text.lower()
    for etype, patterns in EVIDENCE_PATTERNS.items():
        s = sum(1 for p in patterns if re.search(p, tl))
        if s > 0:
            scores[etype] = s
    if not scores:
        return 'host_range'
    return max(scores, key=scores.get)

def infer_strength(text):
    tl = text.lower()
    if re.search(r'(experimental infection|Koch.s postulat|virus isolation|cultured|cell line|in vitro|in vivo.*challenge|fulfill.*Koch)', tl):
        return 'high'
    if re.search(r'(RT.PCR|qPCR|metagenomic|sequenc|genome|phylogenetic|NGS|histopatholog|TEM|electron microscopy)', tl):
        return 'medium'
    return 'low'

def nid(t, c):
    return conn.execute(f"SELECT COALESCE(MAX({c}),0) FROM {t}").fetchone()[0] + 1

# Main loop — improved matching
evidence_created = 0

for ref_id, title, abstract, pmid, doi, year in no_ev:
    text = f"{title or ''} {abstract or ''}"
    tl = text.lower()
    if len(text) < 60:
        continue

    # Score each virus by token overlap (fuzzy)
    virus_scores = []
    for mid, vinfo in virus_lookup.items():
        score = 0
        # Full name match (highest weight)
        if vinfo['name'] in tl:
            score += 10
        elif len(vinfo['name']) > 8:
            # Partial name match (first/last parts)
            parts = vinfo['name'].split()
            if len(parts) >= 2:
                if all(p in tl for p in parts[:2]):
                    score += 5
                elif parts[0] in tl and len(parts[0]) > 5:
                    score += 3
        # Family name match
        if vinfo['family'] and vinfo['family'] in tl:
            score += 4
        # Token overlap
        token_overlap = sum(1 for t in vinfo['tokens'] if t in tl)
        score += token_overlap * 2
        if score >= 3:
            virus_scores.append((mid, score))

    # Score each host
    host_scores = []
    for hid, hinfo in host_lookup.items():
        score = 0
        if hinfo['name'] and hinfo['name'] in tl:
            score += 10
        elif hinfo['group'] and hinfo['group'] in tl:
            score += 5
        # Token overlap
        token_overlap = sum(1 for t in hinfo['tokens'] if t in tl)
        score += token_overlap * 2
        if score >= 3:
            host_scores.append((hid, score))

    # Take top matches
    top_viruses = sorted(virus_scores, key=lambda x: -x[1])[:5]
    top_hosts = sorted(host_scores, key=lambda x: -x[1])[:5]

    if not top_viruses and not top_hosts:
        continue

    etype = classify_evidence(text)
    strength = infer_strength(text)

    # Create records for best pairs
    for mid, vscore in top_viruses[:3]:
        for hid, hscore in top_hosts[:2]:
            eid = nid('evidence_records', 'evidence_id')
            try:
                conn.execute("""
                INSERT INTO evidence_records (evidence_id, evidence_type, virus_master_id, host_id,
                    reference_id, claim, evidence_strength, source_pmid, source_doi,
                    extraction_method, curation_status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'evidence_v2_fuzzy_match', 'auto_imported')
                """, (eid, etype, mid, hid, ref_id, (title or '')[:500], strength, pmid, doi))
                evidence_created += 1
            except:
                pass

        # If virus matched but no host, still create a virus-only evidence record
        if not top_hosts and vscore >= 6:
            eid = nid('evidence_records', 'evidence_id')
            try:
                conn.execute("""
                INSERT INTO evidence_records (evidence_id, evidence_type, virus_master_id,
                    reference_id, claim, evidence_strength, source_pmid, source_doi,
                    extraction_method, curation_status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'evidence_v2_fuzzy_match', 'auto_imported')
                """, (eid, etype, mid, ref_id, (title or '')[:500], strength, pmid, doi))
                evidence_created += 1
            except:
                pass

    if evidence_created % 1000 == 0 and evidence_created > 0:
        conn.commit()
        print(f"  {evidence_created} evidence records created...")

conn.commit()
total_ev = conn.execute("SELECT COUNT(*) FROM evidence_records").fetchone()[0]
print(f"\nCreated: {evidence_created} evidence records")
print(f"Total evidence_records: {total_ev}")

# Stats
refs_with_ev = conn.execute("""
SELECT COUNT(DISTINCT reference_id) FROM evidence_records WHERE reference_id IS NOT NULL
""").fetchone()[0]
print(f"References with evidence: {refs_with_ev} / {conn.execute('SELECT COUNT(*) FROM ref_literatures').fetchone()[0]}")

ev_types = conn.execute("""
SELECT evidence_type, COUNT(*) FROM evidence_records
WHERE extraction_method = 'evidence_v2_fuzzy_match'
GROUP BY evidence_type ORDER BY COUNT(*) DESC
""").fetchall()
if ev_types:
    print("\nNew evidence by type:")
    for r in ev_types:
        print(f"  {r[0]:<20} {r[1]:,}")

conn.close()
