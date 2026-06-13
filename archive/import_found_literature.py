"""Import literature found via Europe PMC searches and link to target viruses."""
import sqlite3

conn = sqlite3.connect('F:/甲壳动物数据库/crustacean_virus_core.db')
c = conn.cursor()

papers_to_import = [
    # DOV 2023 - primary source for 10 oyster viruses
    {'pmid': '36611217', 'doi': '10.1186/s40168-022-01431-8',
     'title': 'A remarkably diverse and well-organized virus community in a filter-feeding oyster',
     'authors': 'Jiang JZ, Fang YF, Wei HY, Zhu P, Liu M, Yuan WG, Yang LL, Guo YX, Jin T, Shi M, Yao T, Lu J, Ye LT, Shi SK, Wang M, Duan M, Zhang DC',
     'journal': 'Microbiome', 'year': '2023'},

    # Wenzhou crab / crustacean RNA virus diversity
    {'pmid': '39329483', 'doi': '10.1128/msystems.01016-24',
     'title': 'Enormous diversity of RNA viruses in economic crustaceans',
     'authors': 'Dong X, Meng F, Zhou C, Li J, Hu T, Wang Y, Wang G, Luo J, Li X, Liu S, Huang J, Shi W',
     'journal': 'mSystems', 'year': '2024'},

    # OsHV-1 host specialization
    {'pmid': '40712723', 'doi': '10.1016/j.meegid.2025.105803',
     'title': 'Phylogenomic evidence for host specialization and genetic divergence in OsHV-1 infecting Magallana gigas and Ostrea edulis',
     'authors': 'Pelletier C, et al.', 'journal': 'Infect Genet Evol', 'year': '2025'},

    # HaHV-1 immune priming
    {'pmid': '41605323', 'doi': '10.1016/j.jip.2026.108554',
     'title': 'Reducing the impact of HaHV-1 in Australian abalone: The role of age and immune priming',
     'authors': 'Agius JR, Ackerly D, Watson AC, Smith ML, Hulands L, McIntyre J, Beddoe T, Helbig KJ',
     'journal': 'J Invertebr Pathol', 'year': '2026'},

    # OsHV-1 transcriptomics
    {'pmid': '39555210', 'doi': '10.1093/ve/veae088',
     'title': 'Long-read transcriptomics of Ostreid herpesvirus 1 uncovers a conserved expression strategy for the capsid maturation module',
     'authors': 'Rosani U, Bortoletto E, Zhang X, Huang BW, Xin LS, Krupovic M, Bai CM',
     'journal': 'Virus Evol', 'year': '2024'},

    # Novel gastropod herpesvirus
    {'pmid': '38656275', 'doi': '10.1099/mgen.0.001237',
     'title': 'Whole-genome assembly of a novel invertebrate herpesvirus from the gastropod Babylonia areolata',
     'authors': 'Divilov K', 'journal': 'Microb Genom', 'year': '2024'},

    # HaHV-1 structural biology
    {'pmid': '41012706', 'doi': '10.3390/v17091279',
     'title': 'Structural Insights into the Nuclear Import of Haliotid Herpesvirus 1 Large Tegument Protein Homologue',
     'authors': 'Nath BK, Swarbrick CMD, Schwab RHM, Ariawan D, Tietz O, Forwood JK, Sarker S',
     'journal': 'Viruses', 'year': '2025'},

    # HaHV-1 hemocyte interaction
    {'pmid': '40001889', 'doi': '10.3390/biology14020121',
     'title': 'Mechanisms of HAHV-1 Interaction with Hemocytes in Haliotis diversicolor supertexta: An In Vitro Study',
     'authors': 'Wei ML, Li YN, Wang JL, Ma CP, Kang HG, Li PJ, Zhang X, Huang BW, Bai CM',
     'journal': 'Biology (Basel)', 'year': '2025'},
]

new_refs = 0
existing_refs = 0
ref_ids = {}

for p in papers_to_import:
    c.execute('SELECT reference_id FROM ref_literatures WHERE pmid=?', (p['pmid'],))
    existing = c.fetchone()
    if existing:
        ref_ids[p['pmid']] = existing[0]
        existing_refs += 1
    else:
        try:
            c.execute('''INSERT INTO ref_literatures (pmid, doi, title, authors, journal, year)
                VALUES (?, ?, ?, ?, ?, ?)''',
                (p['pmid'], p['doi'], p['title'], p['authors'], p['journal'], p['year']))
            ref_ids[p['pmid']] = c.lastrowid
            new_refs += 1
        except Exception as e:
            print(f'  Skip {p["pmid"]}: {e}')
            existing_refs += 1

conn.commit()
print(f'Imported {new_refs} new references, {existing_refs} already existed')

# Link DOV 2023 paper to the 10 DOV oyster viruses
dov_ref_id = ref_ids.get('36611217')
if dov_ref_id:
    print(f'Linking DOV 2023 paper (ref_id={dov_ref_id}) to DOV oyster viruses...')
    c.execute('''SELECT vm.master_id, vm.canonical_name FROM virus_master vm
        WHERE vm.discovery_context = 'dov_2023' AND vm.host_phylum = 'Mollusca'
        AND vm.master_id NOT IN (SELECT DISTINCT virus_master_id FROM evidence_records WHERE virus_master_id IS NOT NULL)''')
    dov_viruses = c.fetchall()

    ev_added = 0
    for mid, vname in dov_viruses:
        try:
            c.execute('''INSERT INTO evidence_records
                (evidence_type, virus_master_id, reference_id, evidence_strength,
                 curation_status, observation_type, claim, extraction_method, created_at)
                VALUES ('natural_infection', ?, ?, 'medium', 'auto_imported',
                 'field', 'Virus identified from oyster virome metagenomic sequencing (DOV 2023, Jiang et al. Microbiome)', 'literature_mining', datetime('now'))''',
                (mid, dov_ref_id))
            ev_added += 1
        except Exception as e:
            print(f'  Error for {vname}: {e}')

    conn.commit()
    print(f'  Created {ev_added} evidence records for DOV viruses')

# Link Wenzhou crab virus paper
wz_ref_id = ref_ids.get('39329483')
if wz_ref_id:
    print(f'Linking Wenzhou crab paper (ref_id={wz_ref_id})...')
    c.execute('''SELECT vm.master_id, vm.canonical_name FROM virus_master vm
        WHERE vm.canonical_name LIKE '%Wenzhou%Crab%'
        AND vm.master_id NOT IN (SELECT DISTINCT virus_master_id FROM evidence_records WHERE virus_master_id IS NOT NULL)''')
    wz_viruses = c.fetchall()

    ev_added = 0
    for mid, vname in wz_viruses:
        try:
            c.execute('''INSERT INTO evidence_records
                (evidence_type, virus_master_id, reference_id, evidence_strength,
                 curation_status, observation_type, claim, extraction_method, created_at)
                VALUES ('natural_infection', ?, ?, 'medium', 'auto_imported',
                 'field', 'Virus identified from crustacean RNA virome (Dong et al. 2024 mSystems)', 'literature_mining', datetime('now'))''',
                (mid, wz_ref_id))
            ev_added += 1
        except Exception as e:
            print(f'  Error for {vname}: {e}')

    conn.commit()
    print(f'  Created {ev_added} evidence records for Wenzhou crab viruses')

# Link OsHV-1 papers to Malaco herpesviruses and any mollusk virus with "herpes" in name
oshv_refs = [ref_ids.get(p) for p in ['40712723', '39555210'] if ref_ids.get(p)]
if oshv_refs:
    c.execute('''SELECT vm.master_id, vm.canonical_name FROM virus_master vm
        WHERE (vm.canonical_name LIKE '%Malaco%herpes%' OR vm.canonical_name LIKE '%OsHV%'
               OR vm.canonical_name LIKE '%ostreid%' OR vm.canonical_name LIKE '%herpesvirus%')
        AND vm.host_phylum = 'Mollusca' ''')
    malaco_viruses = c.fetchall()

    ev_added = 0
    for mid, vname in malaco_viruses:
        for rid in oshv_refs:
            c.execute('SELECT COUNT(*) FROM evidence_records WHERE virus_master_id=? AND reference_id=?', (mid, rid))
            if c.fetchone()[0] == 0:
                try:
                    c.execute('''INSERT INTO evidence_records
                        (evidence_type, virus_master_id, reference_id, evidence_strength,
                         curation_status, observation_type, claim, extraction_method, created_at)
                        VALUES ('natural_infection', ?, ?, 'high', 'auto_imported',
                         'review', 'Herpesvirus infection documented in mollusk host', 'literature_mining', datetime('now'))''',
                        (mid, rid))
                    ev_added += 1
                except:
                    pass

    conn.commit()
    print(f'Linked OsHV-1 papers to {len(malaco_viruses)} Malaco herpesviruses ({ev_added} new evidence records)')

# Also link HaHV-1 papers to abalone herpesviruses
hahv_refs = [ref_ids.get(p) for p in ['41605323', '41012706', '40001889'] if ref_ids.get(p)]
if hahv_refs:
    c.execute('''SELECT vm.master_id, vm.canonical_name FROM virus_master vm
        WHERE (vm.canonical_name LIKE '%Haliotid%' OR vm.canonical_name LIKE '%abalone%'
               OR vm.canonical_name LIKE '%HaHV%')
        AND vm.host_phylum = 'Mollusca' ''')
    hahv_viruses = c.fetchall()

    ev_added = 0
    for mid, vname in hahv_viruses:
        for rid in hahv_refs:
            c.execute('SELECT COUNT(*) FROM evidence_records WHERE virus_master_id=? AND reference_id=?', (mid, rid))
            if c.fetchone()[0] == 0:
                try:
                    c.execute('''INSERT INTO evidence_records
                        (evidence_type, virus_master_id, reference_id, evidence_strength,
                         curation_status, observation_type, claim, extraction_method, created_at)
                        VALUES ('natural_infection', ?, ?, 'high', 'auto_imported',
                         'review', 'HaHV-1 infection documented in abalone host', 'literature_mining', datetime('now'))''',
                        (mid, rid))
                    ev_added += 1
                except:
                    pass

    conn.commit()
    print(f'Linked HaHV-1 papers to {len(hahv_viruses)} abalone herpesviruses ({ev_added} new evidence records)')

# Final stats
c.execute('SELECT COUNT(*) FROM evidence_records')
total_ev = c.fetchone()[0]
c.execute('SELECT COUNT(DISTINCT vm.master_id) FROM virus_master vm JOIN evidence_records er ON vm.master_id = er.virus_master_id')
with_ev = c.fetchone()[0]
c.execute('SELECT COUNT(*) FROM virus_master')
total_vm = c.fetchone()[0]
c.execute('SELECT COUNT(*) FROM ref_literatures')
total_refs = c.fetchone()[0]

print(f'\n=== UPDATED STATS ===')
print(f'References: {total_refs}')
print(f'Evidence records: {total_ev}')
print(f'Viruses with evidence: {with_ev}/{total_vm} ({100*with_ev/total_vm:.1f}%)')
print(f'New papers imported: {new_refs}')

conn.close()
