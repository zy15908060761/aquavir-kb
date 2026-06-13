#!/usr/bin/env python3
"""P2: Fix genome_type, virus_family, and non-target cleanup."""
import sqlite3

conn = sqlite3.connect('F:/水生无脊椎动物数据库/crustacean_virus_core.db')
conn.execute('PRAGMA journal_mode=WAL')

FAMILY_GENOME_TYPE = {
    'Nodaviridae': 'ssRNA(+)', 'Roniviridae': 'ssRNA(+)',
    'Sedoreoviridae': 'dsRNA', 'Reoviridae': 'dsRNA',
    'Totiviridae': 'dsRNA', 'Orthototiviridae': 'dsRNA',
    'Chuviridae': 'ssRNA(-)', 'Rhabdoviridae': 'ssRNA(-)',
    'Phenuiviridae': 'ssRNA(-)', 'Bunyaviridae': 'ssRNA(-)',
    'Peribunyaviridae': 'ssRNA(-)',
    'Astroviridae': 'ssRNA(+)', 'Picornaviridae': 'ssRNA(+)',
    'Dicistroviridae': 'ssRNA(+)', 'Iflaviridae': 'ssRNA(+)',
    'Marnaviridae': 'ssRNA(+)', 'Yanviridae': 'ssRNA(+)',
    'Flaviviridae': 'ssRNA(+)', 'Tombusviridae': 'ssRNA(+)',
    'Virgaviridae': 'ssRNA(+)', 'Potyviridae': 'ssRNA(+)',
    'Solemoviridae': 'ssRNA(+)', 'Solinviviridae': 'ssRNA(+)',
    'Yueviridae': 'ssRNA(+)', 'Weiviridae': 'ssRNA(+)',
    'Zhaoviridae': 'ssRNA(+)', 'Qinviridae': 'ssRNA(-)',
    'Phasmaviridae': 'ssRNA(-)', 'Lispiviridae': 'ssRNA(-)',
    'Narnaviridae': 'ssRNA(+)', 'Botourmiaviridae': 'ssRNA(+)',
    'Mitoviridae': 'ssRNA(+)', 'Hypoviridae': 'ssRNA(+)',
    'Parvoviridae': 'ssDNA', 'Bidnaviridae': 'ssDNA',
    'Circoviridae': 'ssDNA', 'Geminiviridae': 'ssDNA',
    'Nanoviridae': 'ssDNA', 'Smacoviridae': 'ssDNA',
    'Genomoviridae': 'ssDNA', 'Redondoviridae': 'ssDNA',
    'Baculoviridae': 'dsDNA', 'Nudiviridae': 'dsDNA',
    'Nimaviridae': 'dsDNA', 'Malacoherpesviridae': 'dsDNA',
    'Alloherpesviridae': 'dsDNA', 'Iridoviridae': 'dsDNA',
    'Poxviridae': 'dsDNA', 'Ascoviridae': 'dsDNA',
    'Adenoviridae': 'dsDNA', 'Polyomaviridae': 'dsDNA',
    'Papillomaviridae': 'dsDNA', 'Herpesviridae': 'dsDNA',
    'Mimiviridae': 'dsDNA', 'Phycodnaviridae': 'dsDNA',
    'Marseilleviridae': 'dsDNA', 'Pithoviridae': 'dsDNA',
    'Pandoraviridae': 'dsDNA', 'Polydnaviridae': 'dsDNA',
    'Hytrosaviridae': 'dsDNA', 'Glossinaviridae': 'dsDNA',
    'Bicaudaviridae': 'dsDNA', 'Clavaviridae': 'dsDNA',
    'Globuloviridae': 'dsDNA', 'Guttaviridae': 'dsDNA',
    'Ovaliviridae': 'dsDNA', 'Plasmaviridae': 'dsDNA',
    'Pleolipoviridae': 'dsDNA', 'Portogloboviridae': 'dsDNA',
    'Thaspiviridae': 'dsDNA', 'Tristromaviridae': 'dsDNA',
    'Retroviridae': 'ssRNA(RT)', 'Metaviridae': 'ssRNA(RT)',
    'Pseudoviridae': 'ssRNA(RT)', 'Belpaoviridae': 'ssRNA(RT)',
    'Caulimoviridae': 'dsDNA(RT)', 'Hepadnaviridae': 'dsDNA(RT)',
    'Togaviridae': 'ssRNA(+)', 'Coronaviridae': 'ssRNA(+)',
    'Arteriviridae': 'ssRNA(+)', 'Mesoniviridae': 'ssRNA(+)',
    'Caliciviridae': 'ssRNA(+)', 'Hepeviridae': 'ssRNA(+)',
    'Alphaflexiviridae': 'ssRNA(+)', 'Betaflexiviridae': 'ssRNA(+)',
    'Gammaflexiviridae': 'ssRNA(+)', 'Deltaflexiviridae': 'ssRNA(+)',
    'Tymoviridae': 'ssRNA(+)', 'Bromoviridae': 'ssRNA(+)',
    'Closteroviridae': 'ssRNA(+)', 'Luteoviridae': 'ssRNA(+)',
    'Secoviridae': 'ssRNA(+)', 'Partitiviridae': 'dsRNA',
    'Amalgaviridae': 'dsRNA', 'Chrysoviridae': 'dsRNA',
    'Endornaviridae': 'dsRNA', 'Megabirnaviridae': 'dsRNA',
    'Quadriviridae': 'dsRNA', 'Spinareoviridae': 'dsRNA',
    'Cystoviridae': 'dsRNA', 'Birnaviridae': 'dsRNA',
    'Picobirnaviridae': 'dsRNA', 'Anelloviridae': 'ssDNA',
    'Inoviridae': 'ssDNA', 'Microviridae': 'ssDNA',
    'Fusariviridae': 'ssRNA(+)', 'Hadakaviridae': 'ssRNA(+)',
    'Negevirus': 'ssRNA(+)', 'Unclassified': None,
}

# Fix 1: genome_type from family
updated = 0
for family, gtype in FAMILY_GENOME_TYPE.items():
    if gtype is None:
        continue
    cur = conn.execute("""
        UPDATE virus_master SET genome_type = ?
        WHERE (genome_type IS NULL OR genome_type = '')
        AND virus_family = ?
    """, (gtype, family))
    updated += cur.rowcount
conn.commit()
print(f'Genome types fixed (from family): {updated}')

# Fix 2: genome_type from molecule_type in isolates
updated2 = conn.execute("""
    UPDATE virus_master SET genome_type = (
        SELECT CASE
            WHEN LOWER(vi.molecule_type) IN ('rna', 'ss-rna') THEN 'ssRNA'
            WHEN LOWER(vi.molecule_type) IN ('ds-rna', 'dsrna') THEN 'dsRNA'
            WHEN LOWER(vi.molecule_type) IN ('dna', 'genomic dna') THEN 'dsDNA'
            WHEN LOWER(vi.molecule_type) IN ('ss-dna', 'ssdna') THEN 'ssDNA'
            WHEN LOWER(vi.molecule_type) = 'mrna' THEN 'mRNA'
            ELSE vi.molecule_type
        END
        FROM viral_isolates vi
        WHERE vi.master_id = virus_master.master_id
        AND vi.molecule_type IS NOT NULL AND vi.molecule_type != ''
        LIMIT 1
    )
    WHERE (genome_type IS NULL OR genome_type = '')
    AND EXISTS (
        SELECT 1 FROM viral_isolates vi
        WHERE vi.master_id = virus_master.master_id
        AND vi.molecule_type IS NOT NULL AND vi.molecule_type != ''
    )
""")
conn.commit()
print(f'Genome types fixed (from molecule_type): {updated2.rowcount}')

# Fix 3: missing family from isolate taxon_family
updated3 = conn.execute("""
    UPDATE virus_master SET virus_family = (
        SELECT vi.taxon_family
        FROM viral_isolates vi
        WHERE vi.master_id = virus_master.master_id
        AND vi.taxon_family IS NOT NULL AND vi.taxon_family != ''
        LIMIT 1
    )
    WHERE (virus_family IS NULL OR virus_family = '')
    AND entry_type != 'non_target'
    AND EXISTS (
        SELECT 1 FROM viral_isolates vi
        WHERE vi.master_id = virus_master.master_id
        AND vi.taxon_family IS NOT NULL AND vi.taxon_family != ''
    )
""")
conn.commit()
print(f'Family fixed (from isolate taxon): {updated3.rowcount}')

# Fix 4: Mark non-target entries
updated4 = conn.execute("""
    UPDATE virus_master SET
        entry_type = 'non_target',
        public_visibility = 'hidden'
    WHERE host_phylum IN (
        'non_target (algae)', 'non_target (vertebrate)',
        'non_target (fungus)', 'non_target (plant)',
        'non_aquatic', 'non_target'
    )
    AND entry_type NOT IN ('non_target', 'ictv_vmr')
""")
conn.commit()
print(f'Non-target entries marked: {updated4.rowcount}')

# Final stats
conn.row_factory = sqlite3.Row
r = conn.execute(
    "SELECT COUNT(*) as n FROM virus_master WHERE (genome_type IS NULL OR genome_type = '')"
).fetchone()
print(f'\nRemaining missing genome_type: {r["n"]}')

r = conn.execute("""
    SELECT COUNT(*) as n FROM virus_master
    WHERE (virus_family IS NULL OR virus_family = '')
    AND entry_type != 'non_target'
""").fetchone()
print(f'Remaining missing family: {r["n"]}')

r = conn.execute("SELECT COUNT(*) as n FROM virus_master WHERE entry_type = 'non_target'").fetchone()
print(f'Total non_target entries: {r["n"]}')

# Active entries
active = conn.execute(
    "SELECT COUNT(*) as n FROM virus_master WHERE entry_type != 'non_target'"
).fetchone()
print(f'Total active entries: {active["n"]}')

conn.close()
print('\nDone.')
