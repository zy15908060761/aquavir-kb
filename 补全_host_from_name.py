"""
补全第二波：从病毒名推断宿主（钱江/北海/沙河系列 + 已知属名）
对GenBank缺失/host字段的病毒，从canonical_name直接提取宿主信息。
"""
import sqlite3, re, sys

DB = 'F:/甲壳动物数据库/crustacean_virus_core.db'

# Known aquatic invertebrate genera → taxonomy
GENUS_TAX = {
    'penaeus':'Arthropoda','litopenaeus':'Arthropoda','marsupenaeus':'Arthropoda',
    'macrobrachium':'Arthropoda','palaemon':'Arthropoda','homarus':'Arthropoda',
    'procambarus':'Arthropoda','cherax':'Arthropoda','pacifastacus':'Arthropoda',
    'callinectes':'Arthropoda','scylla':'Arthropoda','portunus':'Arthropoda',
    'charybdis':'Arthropoda','eriocheir':'Arthropoda','carcinus':'Arthropoda',
    'cancer':'Arthropoda','daphnia':'Arthropoda','artemia':'Arthropoda',
    'gammarus':'Arthropoda','euphausia':'Arthropoda','balanus':'Arthropoda',
    'megabalanus':'Arthropoda','tigriopus':'Arthropoda','calanus':'Arthropoda',
    'hyalella':'Arthropoda','ligia':'Arthropoda','uca':'Arthropoda',
    'crassostrea':'Mollusca','saccostrea':'Mollusca','ostrea':'Mollusca',
    'mytilus':'Mollusca','perna':'Mollusca','ruditapes':'Mollusca',
    'mercenaria':'Mollusca','meretrix':'Mollusca','venerupis':'Mollusca',
    'pecten':'Mollusca','argopecten':'Mollusca','chlamys':'Mollusca',
    'mizuhopecten':'Mollusca','patinopecten':'Mollusca','pinctada':'Mollusca',
    'haliotis':'Mollusca','lymnaea':'Mollusca','biomphalaria':'Mollusca',
    'conus':'Mollusca','rapana':'Mollusca','pomacea':'Mollusca','bellamya':'Mollusca',
    'octopus':'Mollusca','sepia':'Mollusca','loligo':'Mollusca',
    'acropora':'Cnidaria','porites':'Cnidaria','pocillopora':'Cnidaria',
    'stylophora':'Cnidaria','orbicella':'Cnidaria','nematostella':'Cnidaria',
    'exaiptasia':'Cnidaria','hydra':'Cnidaria',
    'apostichopus':'Echinodermata','holothuria':'Echinodermata',
    'strongylocentrotus':'Echinodermata','paracentrotus':'Echinodermata',
    'asterias':'Echinodermata','pisaster':'Echinodermata','acanthaster':'Echinodermata',
    'amphimedon':'Porifera','xestospongia':'Porifera',
}

COMMON_HOST = {
    'shrimp':'Arthropoda','prawn':'Arthropoda','crab':'Arthropoda',
    'crayfish':'Arthropoda','lobster':'Arthropoda','copepod':'Arthropoda',
    'amphipod':'Arthropoda','isopod':'Arthropoda','barnacle':'Arthropoda',
    'krill':'Arthropoda','daphnia':'Arthropoda','brine':'Arthropoda',
    'crustacean':'Arthropoda','decapod':'Arthropoda',
    'oyster':'Mollusca','mussel':'Mollusca','clam':'Mollusca',
    'scallop':'Mollusca','abalone':'Mollusca','snail':'Mollusca',
    'bivalve':'Mollusca','gastropod':'Mollusca','mollusc':'Mollusca',
    'squid':'Mollusca','octopus':'Mollusca','cephalopod':'Mollusca',
    'coral':'Cnidaria','anemone':'Cnidaria','jellyfish':'Cnidaria',
    'sea cucumber':'Echinodermata','sea urchin':'Echinodermata',
    'starfish':'Echinodermata','sponge':'Porifera',
}

CAP_WORD = re.compile(r'\b([A-Z][a-z]{2,})\b')

def main(dry_run=False):
    conn = sqlite3.connect(DB)
    c = conn.cursor()

    # Get core viruses without infection records
    c.execute('''SELECT vm.master_id, vm.canonical_name, vm.host_phylum, vi.accession, vi.isolate_id
                 FROM virus_master vm
                 JOIN viral_isolates vi ON vm.master_id = vi.master_id
                 WHERE vm.host_phylum IN ('Arthropoda','Mollusca','Cnidaria','Echinodermata','Porifera')
                 AND vm.master_id NOT IN (
                     SELECT DISTINCT vi2.master_id FROM viral_isolates vi2
                     JOIN infection_records ir ON vi2.isolate_id = ir.isolate_id
                 )
                 GROUP BY vm.master_id''')
    need_hosts = c.fetchall()
    print(f'Core viruses needing host: {len(need_hosts)}')

    c.execute('SELECT LOWER(scientific_name), host_id FROM crustacean_hosts')
    existing_hosts = {r[0]: r[1] for r in c.fetchall()}

    new_hosts = 0
    new_infections = 0

    for mid, name, phylum, acc, iso_id in need_hosts:
        if not name: continue
        name_lower = name.lower()

        # Strategy 1: Find capitalized genus word matching known genera
        cap_words = CAP_WORD.findall(name)
        matched_phylum = None
        matched_genus = None
        for w in cap_words:
            wl = w.lower()
            if wl in GENUS_TAX:
                matched_genus = w
                matched_phylum = GENUS_TAX[wl]
                break

        # Strategy 2: Common name match
        if not matched_genus:
            for common, phy in COMMON_HOST.items():
                if common in name_lower:
                    matched_phylum = phy
                    break

        if not matched_phylum:
            continue

        # Create host entry from genus name
        host_id = None
        if matched_genus:
            genus_lower = matched_genus.lower()
            if genus_lower in existing_hosts:
                host_id = existing_hosts[genus_lower]
            elif not dry_run:
                # Create genus-level host
                try:
                    c.execute('''INSERT INTO crustacean_hosts
                        (scientific_name, phylum, class, host_scope_status)
                        VALUES (?, ?, '',
                         CASE WHEN ? IN (''Arthropoda'') THEN ''target_crustacean''
                              WHEN ? IN (''Mollusca'') THEN ''target_mollusk''
                              ELSE ''target_other_aquatic_invert'' END)''',
                        (matched_genus, matched_phylum, matched_phylum, matched_phylum))
                    host_id = c.lastrowid
                    existing_hosts[genus_lower] = host_id
                    new_hosts += 1
                except sqlite3.IntegrityError:
                    c.execute('SELECT host_id FROM crustacean_hosts WHERE LOWER(scientific_name) = ?',
                             (genus_lower,))
                    ex = c.fetchone()
                    if ex: host_id = ex[0]; existing_hosts[genus_lower] = host_id

        # Create infection record
        if host_id and not dry_run:
            try:
                c.execute('''INSERT INTO infection_records
                    (isolate_id, host_id, host_association_method, detection_method)
                    VALUES (?, ?, 'name_inference', 'metagenomic_survey')''',
                    (iso_id, host_id))
                new_infections += 1
            except sqlite3.IntegrityError:
                pass

    if not dry_run:
        conn.commit()

    # Stats
    c.execute('SELECT COUNT(*) FROM infection_records'); total_inf = c.fetchone()[0]
    c.execute('''SELECT COUNT(DISTINCT vm.master_id) FROM virus_master vm
                 JOIN viral_isolates vi ON vm.master_id = vi.master_id
                 JOIN infection_records ir ON vi.isolate_id = ir.isolate_id
                 WHERE vm.host_phylum IN ('Arthropoda','Mollusca','Cnidaria','Echinodermata','Porifera')''')
    core_linked = c.fetchone()[0]
    c.execute('''SELECT COUNT(*) FROM virus_master
                 WHERE host_phylum IN ('Arthropoda','Mollusca','Cnidaria','Echinodermata','Porifera')''')
    core_total = c.fetchone()[0]

    print(f'\n{"DRY RUN" if dry_run else "RESULTS"}')
    print(f'New host entries (genus-level):  {new_hosts}')
    print(f'New infection records:          {new_infections}')
    print(f'Total infection records:        {total_inf}')
    print(f'Core species with host linkage: {core_linked}/{core_total} ({core_linked/core_total*100:.1f}%)')

    conn.close()

if __name__ == '__main__':
    dry = '--dry-run' in sys.argv
    main(dry_run=dry)
