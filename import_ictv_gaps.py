#!/usr/bin/env python3
"""Import ICTV-listed aquatic invertebrate viruses missing from AquaVir-KB. v3 - robust."""
import sqlite3, datetime

conn = sqlite3.connect('F:/水生无脊椎动物数据库/crustacean_virus_core.db')

imports = [
    ('Aquambidensovirus asteroid1', 'Parvoviridae', 'Aquambidensovirus', 'ssDNA(+/-)', 'Echinodermata', 'KM052275'),
    ('Aquambidensovirus asteroid2', 'Parvoviridae', 'Aquambidensovirus', 'ssDNA(+/-)', 'Echinodermata', 'MN190158'),
    ('Aquambidensovirus asteroid3', 'Parvoviridae', 'Aquambidensovirus', 'ssDNA(+/-)', 'Echinodermata', 'MT733014'),
    ('Aquambidensovirus asteroid4', 'Parvoviridae', 'Aquambidensovirus', 'ssDNA(+/-)', 'Echinodermata', 'MT733015'),
    ('Aquambidensovirus asteroid5', 'Parvoviridae', 'Aquambidensovirus', 'ssDNA(+/-)', 'Echinodermata', 'MT733016'),
    ('Aquambidensovirus asteroid6', 'Parvoviridae', 'Aquambidensovirus', 'ssDNA(+/-)', 'Echinodermata', 'MT733017'),
    ('Aquambidensovirus asteroid7', 'Parvoviridae', 'Aquambidensovirus', 'ssDNA(+/-)', 'Echinodermata', 'MT733018'),
    ('Aquambidensovirus asteroid8', 'Parvoviridae', 'Aquambidensovirus', 'ssDNA(+/-)', 'Echinodermata', 'MT733019'),
    ('Aquambidensovirus asteroid9', 'Parvoviridae', 'Aquambidensovirus', 'ssDNA(+/-)', 'Echinodermata', 'MT733023'),
    ('Aquambidensovirus asteroid10', 'Parvoviridae', 'Aquambidensovirus', 'ssDNA(+/-)', 'Echinodermata', 'MT733025'),
    ('Aquambidensovirus asteroid11', 'Parvoviridae', 'Aquambidensovirus', 'ssDNA(+/-)', 'Echinodermata', 'MT733027'),
    ('Aquambidensovirus asteroid12', 'Parvoviridae', 'Aquambidensovirus', 'ssDNA(+/-)', 'Echinodermata', 'MT733028'),
    ('Aquambidensovirus asteroid13', 'Parvoviridae', 'Aquambidensovirus', 'ssDNA(+/-)', 'Echinodermata', 'MT733034'),
    ('Aquambidensovirus asteroid14', 'Parvoviridae', 'Aquambidensovirus', 'ssDNA(+/-)', 'Echinodermata', 'MT733038'),
    ('Aquambidensovirus asteroid15', 'Parvoviridae', 'Aquambidensovirus', 'ssDNA(+/-)', 'Echinodermata', 'MT733039'),
    ('Aquambidensovirus asteroid16', 'Parvoviridae', 'Aquambidensovirus', 'ssDNA(+/-)', 'Echinodermata', 'MT733040'),
    ('Aquambidensovirus asteroid17', 'Parvoviridae', 'Aquambidensovirus', 'ssDNA(+/-)', 'Echinodermata', 'MT733041'),
    ('Aquambidensovirus asteroid18', 'Parvoviridae', 'Aquambidensovirus', 'ssDNA(+/-)', 'Echinodermata', 'MT733042'),
    ('Aquambidensovirus asteroid19', 'Parvoviridae', 'Aquambidensovirus', 'ssDNA(+/-)', 'Echinodermata', 'MT733043'),
    ('Aquambidensovirus asteroid20', 'Parvoviridae', 'Aquambidensovirus', 'ssDNA(+/-)', 'Echinodermata', 'MT733044'),
    ('Aquambidensovirus asteroid21', 'Parvoviridae', 'Aquambidensovirus', 'ssDNA(+/-)', 'Echinodermata', 'MT733049'),
    ('Aquambidensovirus asteroid22', 'Parvoviridae', 'Aquambidensovirus', 'ssDNA(+/-)', 'Echinodermata', 'MT733047'),
    ('Aquambidensovirus decapod1', 'Parvoviridae', 'Aquambidensovirus', 'ssDNA(+/-)', 'Arthropoda', 'KP410261'),
    ('Protohepanvirus decapod1', 'Parvoviridae', 'Protohepanvirus', 'ssDNA', 'Arthropoda', 'GU371276'),
    ('Protometallovirus decapod1', 'Parvoviridae', 'Protometallovirus', 'ssDNA', 'Arthropoda', 'MK028683'),
    ('Shripenbrevirus decapod1', 'Parvoviridae', 'Shripenbrevirus', 'ssDNA', 'Arthropoda', 'AF273215'),
    ('Decapodiridovirus litopenaeus1', 'Iridoviridae', 'Decapodiridovirus', 'dsDNA', 'Arthropoda', 'MF599468'),
    ('Whispovirus lacteolymphae', 'Nimaviridae', 'Whispovirus', 'dsDNA', 'Arthropoda', 'LC741431'),
    ('Cardoreovirus eriocheiris', 'Sedoreoviridae', 'Cardoreovirus', 'dsRNA', 'Arthropoda', 'AY542965'),
    ('Crabreovirus eriocheiris', 'Sedoreoviridae', 'Crabreovirus', 'dsRNA', 'Arthropoda', 'KP638402'),
    ('Hexartovirus artemiae', 'Artoviridae', 'Hexartovirus', 'ssRNA(-)', 'Arthropoda', 'OL472418'),
    ('Hexartovirus cirripedis', 'Artoviridae', 'Hexartovirus', 'ssRNA(-)', 'Arthropoda', 'KX884410'),
    ('Pediavirus cirripedis', 'Chuviridae', 'Pediavirus', 'ssRNA(-)', 'Arthropoda', 'KX884409'),
    ('Bivalveiridovirus cerastoderma1', 'Iridoviridae', 'Bivalveiridovirus', 'dsDNA', 'Mollusca', 'PQ846775'),
    ('Aurivirus haliotidmalaco1', 'Malacoherpesviridae', 'Aurivirus', 'dsDNA', 'Mollusca', 'JX453331'),
    ('Ostreavirus ostreidmalaco1', 'Malacoherpesviridae', 'Ostreavirus', 'dsDNA', 'Mollusca', 'AY509253'),
    ('Betaourmiavirus conchyli', 'Ourmiaviridae', 'Betaourmiavirus', 'ssRNA(+)', 'Mollusca', 'KX883515'),
    ('Gammaourmiavirus conchyli', 'Ourmiaviridae', 'Gammaourmiavirus', 'ssRNA(+)', 'Mollusca', 'KX883512'),
    ('Betaourmiavirus mollusci', 'Ourmiaviridae', 'Betaourmiavirus', 'ssRNA(+)', 'Mollusca', 'KX883578'),
    ('Alphaabyssovirus aplysiae', 'Abyssoviridae', 'Alphaabyssovirus', 'ssRNA(+)', 'Mollusca', 'GBBW01007738'),
    ('Mantiovirus clamco', 'Ouroboviridae', 'Mantiovirus', 'ssDNA(+/-)', 'Mollusca', 'KR528562'),
    ('Ronavirus rotiferae', 'Birnaviridae', 'Ronavirus', 'dsRNA', 'Rotifera', 'FM995220'),
]

ts = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')

def next_id(table, col):
    """Get next available ID for a table."""
    r = conn.execute(f"SELECT COALESCE(MAX({col}), 0) FROM {table}").fetchone()[0]
    return r + 1

# STEP 0: Clean orphans from previous failed runs
for sp, _, _, _, _, _ in imports:
    rows = conn.execute("SELECT master_id FROM virus_master WHERE canonical_name=?", (sp,)).fetchall()
    for (mid,) in rows:
        has_map = conn.execute("SELECT COUNT(*) FROM virus_ictv_mappings WHERE master_id=?", (mid,)).fetchone()[0]
        has_ev = conn.execute("SELECT COUNT(*) FROM evidence_records WHERE virus_master_id=?", (mid,)).fetchone()[0]
        has_isol = conn.execute("SELECT COUNT(*) FROM viral_isolates WHERE master_id=?", (mid,)).fetchone()[0]
        if has_map == 0 and has_ev == 0 and has_isol == 0:
            conn.execute("DELETE FROM virus_master WHERE master_id=?", (mid,))
            print(f'Cleaned orphan: {mid} ({sp})')

# STEP 1: Dedup
existing = {r[0] for r in conn.execute("SELECT LOWER(canonical_name) FROM virus_master").fetchall()}
prepared = []
for sp, fam, gen, gm, ph, acc in imports:
    if sp.lower() in existing:
        print(f'SKIP: {sp}')
        continue
    vmr = conn.execute("SELECT vmr_id FROM ictv_vmr WHERE species=? LIMIT 1", (sp,)).fetchone()
    if vmr:
        prepared.append((sp, fam, gen, gm, ph, acc, vmr[0]))
    else:
        print(f'NO_VMR: {sp}')

print(f'\nPrepared: {len(prepared)}')

# STEP 2: Insert each one atomically
virus_ok = 0; isol_ok = 0
for sp, fam, gen, gm, ph, acc, vmr_id in prepared:
    try:
        mid = next_id('virus_master', 'master_id')
        mapid = next_id('virus_ictv_mappings', 'mapping_id')
        provid = next_id('data_provenance', 'provenance_id')
        logid = next_id('curation_logs', 'log_id')

        conn.execute("""
        INSERT INTO virus_master (master_id, canonical_name, virus_family, virus_genus,
            genome_type, host_phylum, entry_type, discovery_context, is_crustacean_virus)
        VALUES (?, ?, ?, ?, ?, ?, 'complete_genome', 'metagenomic_environmental', 1)
        """, (mid, sp, fam, gen, gm, ph))

        conn.execute("""
        INSERT INTO virus_ictv_mappings (mapping_id, master_id, ictv_id, match_type, matched_value,
            match_status, confidence, source_id, created_at)
        VALUES (?, ?, ?, 'species_exact', ?, 'auto_matched', 'high', 3, ?)
        """, (mapid, mid, vmr_id, sp, ts))

        conn.execute("""
        INSERT INTO data_provenance (provenance_id, table_name, record_id, virus_master_id,
            virus_name, data_source, confidence_level)
        VALUES (?, 'virus_master', ?, ?, ?, 'ICTV VMR', 'verified')
        """, (provid, mid, mid, sp))

        conn.execute("""
        INSERT INTO curation_logs (log_id, entity_type, entity_id, action, new_value,
            confidence, curator, created_at)
        VALUES (?, 'virus', ?, 'insert', ?, 'high', 'ictv_gap_import', ?)
        """, (logid, mid, f"ICTV gap fill: {sp} (family={fam})", ts))

        virus_ok += 1

        # Isolate
        acc_clean = acc.strip()
        if acc_clean and len(acc_clean) >= 6 and ';' not in acc_clean and 'Seg' not in acc_clean:
            if not conn.execute("SELECT COUNT(*) FROM viral_isolates WHERE accession=?", (acc_clean,)).fetchone()[0]:
                isoid = next_id('viral_isolates', 'isolate_id')
                conn.execute("""
                INSERT INTO viral_isolates (isolate_id, accession, virus_name, taxon_family,
                    taxon_genus, genome_type, has_sequence, master_id, completeness)
                VALUES (?, ?, ?, ?, ?, ?, 1, ?, 'complete')
                """, (isoid, acc_clean, sp, fam, gen, gm, mid))
                isol_ok += 1

        conn.commit()

    except Exception as e:
        print(f'ERROR [{sp}]: {e}')
        conn.rollback()
        continue

# Summary
print(f"\n===== IMPORT COMPLETE =====")
print(f"virus_master: +{virus_ok}, viral_isolates: +{isol_ok}")
from collections import Counter
for p, c in Counter(p[4] for p in prepared).most_common():
    print(f"  {p}: {c}")
conn.close()
