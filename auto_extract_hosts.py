"""
Auto-extract host associations from virus canonical names.
Parses 1246 virus names → matches aquatic invertebrate genera/species →
creates host entries + infection_records + updates host_phylum.

Strategy:
  1. Direct binomial match: "Genus_species virus" → exact host
  2. Genus-only match: "Genus virus" → host at genus level
  3. Common-name match: "oyster virus" → phylum-level host
  4. Fallback: from existing host_phylum or virus_family

Usage: python auto_extract_hosts.py [--dry-run]
"""

import sqlite3, re, sys
from pathlib import Path

DB = 'F:/甲壳动物数据库/crustacean_virus_core.db'

# ── Comprehensive aquatic invertebrate genus → taxonomy mapping ────────────
# Format: 'genus_lower': ('Phylum', 'Class', 'Order', 'Family', 'scope_status')
GENUS_MAP = {
    # === CRUSTACEA (Arthropoda) ===
    # Penaeid shrimps
    'penaeus': ('Arthropoda', 'Malacostraca', 'Decapoda', 'Penaeidae', 'target_crustacean'),
    'litopenaeus': ('Arthropoda', 'Malacostraca', 'Decapoda', 'Penaeidae', 'target_crustacean'),
    'marsupenaeus': ('Arthropoda', 'Malacostraca', 'Decapoda', 'Penaeidae', 'target_crustacean'),
    'fenneropenaeus': ('Arthropoda', 'Malacostraca', 'Decapoda', 'Penaeidae', 'target_crustacean'),
    'melicertus': ('Arthropoda', 'Malacostraca', 'Decapoda', 'Penaeidae', 'target_crustacean'),
    'metapenaeus': ('Arthropoda', 'Malacostraca', 'Decapoda', 'Penaeidae', 'target_crustacean'),
    'parapenaeus': ('Arthropoda', 'Malacostraca', 'Decapoda', 'Penaeidae', 'target_crustacean'),
    # Other shrimps/prawns
    'macrobrachium': ('Arthropoda', 'Malacostraca', 'Decapoda', 'Palaemonidae', 'target_crustacean'),
    'palaemon': ('Arthropoda', 'Malacostraca', 'Decapoda', 'Palaemonidae', 'target_crustacean'),
    'palaemonetes': ('Arthropoda', 'Malacostraca', 'Decapoda', 'Palaemonidae', 'target_crustacean'),
    'exopalaemon': ('Arthropoda', 'Malacostraca', 'Decapoda', 'Palaemonidae', 'target_crustacean'),
    'neocaridina': ('Arthropoda', 'Malacostraca', 'Decapoda', 'Atyidae', 'target_crustacean'),
    'caridina': ('Arthropoda', 'Malacostraca', 'Decapoda', 'Atyidae', 'target_crustacean'),
    'atyopsis': ('Arthropoda', 'Malacostraca', 'Decapoda', 'Atyidae', 'target_crustacean'),
    # Crabs
    'scylla': ('Arthropoda', 'Malacostraca', 'Decapoda', 'Portunidae', 'target_crustacean'),
    'portunus': ('Arthropoda', 'Malacostraca', 'Decapoda', 'Portunidae', 'target_crustacean'),
    'callinectes': ('Arthropoda', 'Malacostraca', 'Decapoda', 'Portunidae', 'target_crustacean'),
    'charybdis': ('Arthropoda', 'Malacostraca', 'Decapoda', 'Portunidae', 'target_crustacean'),
    'eriocheir': ('Arthropoda', 'Malacostraca', 'Decapoda', 'Varunidae', 'target_crustacean'),
    'cancer': ('Arthropoda', 'Malacostraca', 'Decapoda', 'Cancridae', 'target_crustacean'),
    'carcinus': ('Arthropoda', 'Malacostraca', 'Decapoda', 'Portunidae', 'target_crustacean'),
    'sesarma': ('Arthropoda', 'Malacostraca', 'Decapoda', 'Sesarmidae', 'target_crustacean'),
    'uca': ('Arthropoda', 'Malacostraca', 'Decapoda', 'Ocypodidae', 'target_crustacean'),
    'ocypode': ('Arthropoda', 'Malacostraca', 'Decapoda', 'Ocypodidae', 'target_crustacean'),
    # Crayfish/lobster
    'procambarus': ('Arthropoda', 'Malacostraca', 'Decapoda', 'Cambaridae', 'target_crustacean'),
    'cherax': ('Arthropoda', 'Malacostraca', 'Decapoda', 'Parastacidae', 'target_crustacean'),
    'pacifastacus': ('Arthropoda', 'Malacostraca', 'Decapoda', 'Astacidae', 'target_crustacean'),
    'astacus': ('Arthropoda', 'Malacostraca', 'Decapoda', 'Astacidae', 'target_crustacean'),
    'homarus': ('Arthropoda', 'Malacostraca', 'Decapoda', 'Nephropidae', 'target_crustacean'),
    'nephrops': ('Arthropoda', 'Malacostraca', 'Decapoda', 'Nephropidae', 'target_crustacean'),
    'panulirus': ('Arthropoda', 'Malacostraca', 'Decapoda', 'Palinuridae', 'target_crustacean'),
    # Small crustaceans
    'daphnia': ('Arthropoda', 'Branchiopoda', 'Cladocera', 'Daphniidae', 'target_crustacean'),
    'artemia': ('Arthropoda', 'Branchiopoda', 'Anostraca', 'Artemiidae', 'target_crustacean'),
    'triops': ('Arthropoda', 'Branchiopoda', 'Notostraca', 'Triopsidae', 'target_crustacean'),
    'gammarus': ('Arthropoda', 'Malacostraca', 'Amphipoda', 'Gammaridae', 'target_crustacean'),
    'hyalella': ('Arthropoda', 'Malacostraca', 'Amphipoda', 'Hyalellidae', 'target_crustacean'),
    'caprella': ('Arthropoda', 'Malacostraca', 'Amphipoda', 'Caprellidae', 'target_crustacean'),
    'ligia': ('Arthropoda', 'Malacostraca', 'Isopoda', 'Ligiidae', 'target_crustacean'),
    'armadillidium': ('Arthropoda', 'Malacostraca', 'Isopoda', 'Armadillidiidae', 'target_crustacean'),
    'balanus': ('Arthropoda', 'Maxillopoda', 'Sessilia', 'Balanidae', 'target_crustacean'),
    'megabalanus': ('Arthropoda', 'Maxillopoda', 'Sessilia', 'Balanidae', 'target_crustacean'),
    'euphausia': ('Arthropoda', 'Malacostraca', 'Euphausiacea', 'Euphausiidae', 'target_crustacean'),
    'calanus': ('Arthropoda', 'Hexanauplia', 'Calanoida', 'Calanidae', 'target_crustacean'),
    'tigriopus': ('Arthropoda', 'Hexanauplia', 'Harpacticoida', 'Harpacticidae', 'target_crustacean'),

    # === MOLLUSCA - Bivalvia ===
    'crassostrea': ('Mollusca', 'Bivalvia', 'Ostreoida', 'Ostreidae', 'target_mollusk'),
    'saccostrea': ('Mollusca', 'Bivalvia', 'Ostreoida', 'Ostreidae', 'target_mollusk'),
    'ostrea': ('Mollusca', 'Bivalvia', 'Ostreoida', 'Ostreidae', 'target_mollusk'),
    'mytilus': ('Mollusca', 'Bivalvia', 'Mytiloida', 'Mytilidae', 'target_mollusk'),
    'perna': ('Mollusca', 'Bivalvia', 'Mytiloida', 'Mytilidae', 'target_mollusk'),
    'modiolus': ('Mollusca', 'Bivalvia', 'Mytiloida', 'Mytilidae', 'target_mollusk'),
    'ruditapes': ('Mollusca', 'Bivalvia', 'Veneroida', 'Veneridae', 'target_mollusk'),
    'venerupis': ('Mollusca', 'Bivalvia', 'Veneroida', 'Veneridae', 'target_mollusk'),
    'mercenaria': ('Mollusca', 'Bivalvia', 'Veneroida', 'Veneridae', 'target_mollusk'),
    'meretrix': ('Mollusca', 'Bivalvia', 'Veneroida', 'Veneridae', 'target_mollusk'),
    'tapes': ('Mollusca', 'Bivalvia', 'Veneroida', 'Veneridae', 'target_mollusk'),
    'sinonovacula': ('Mollusca', 'Bivalvia', 'Adapedonta', 'Solenidae', 'target_mollusk'),
    'solen': ('Mollusca', 'Bivalvia', 'Adapedonta', 'Solenidae', 'target_mollusk'),
    'mya': ('Mollusca', 'Bivalvia', 'Myoida', 'Myidae', 'target_mollusk'),
    'pecten': ('Mollusca', 'Bivalvia', 'Pectinida', 'Pectinidae', 'target_mollusk'),
    'argopecten': ('Mollusca', 'Bivalvia', 'Pectinida', 'Pectinidae', 'target_mollusk'),
    'chlamys': ('Mollusca', 'Bivalvia', 'Pectinida', 'Pectinidae', 'target_mollusk'),
    'mizuhopecten': ('Mollusca', 'Bivalvia', 'Pectinida', 'Pectinidae', 'target_mollusk'),
    'patinopecten': ('Mollusca', 'Bivalvia', 'Pectinida', 'Pectinidae', 'target_mollusk'),
    'pinctada': ('Mollusca', 'Bivalvia', 'Pteriida', 'Pteriidae', 'target_mollusk'),
    'pteria': ('Mollusca', 'Bivalvia', 'Pteriida', 'Pteriidae', 'target_mollusk'),
    # === MOLLUSCA - Gastropoda ===
    'haliotis': ('Mollusca', 'Gastropoda', 'Lepetellida', 'Haliotidae', 'target_mollusk'),
    'lymnaea': ('Mollusca', 'Gastropoda', 'Hygrophila', 'Lymnaeidae', 'target_mollusk'),
    'biomphalaria': ('Mollusca', 'Gastropoda', 'Hygrophila', 'Planorbidae', 'target_mollusk'),
    'conus': ('Mollusca', 'Gastropoda', 'Neogastropoda', 'Conidae', 'target_mollusk'),
    'rapana': ('Mollusca', 'Gastropoda', 'Neogastropoda', 'Muricidae', 'target_mollusk'),
    'babylonia': ('Mollusca', 'Gastropoda', 'Neogastropoda', 'Babyloniidae', 'target_mollusk'),
    'pomacea': ('Mollusca', 'Gastropoda', 'Architaenioglossa', 'Ampullariidae', 'target_mollusk'),
    'bellamya': ('Mollusca', 'Gastropoda', 'Architaenioglossa', 'Viviparidae', 'target_mollusk'),
    'achatina': ('Mollusca', 'Gastropoda', 'Stylommatophora', 'Achatinidae', 'target_mollusk'),
    # === MOLLUSCA - Cephalopoda ===
    'octopus': ('Mollusca', 'Cephalopoda', 'Octopoda', 'Octopodidae', 'target_mollusk'),
    'sepia': ('Mollusca', 'Cephalopoda', 'Sepiida', 'Sepiidae', 'target_mollusk'),
    'loligo': ('Mollusca', 'Cephalopoda', 'Myopsida', 'Loliginidae', 'target_mollusk'),
    'doryteuthis': ('Mollusca', 'Cephalopoda', 'Myopsida', 'Loliginidae', 'target_mollusk'),

    # === CNIDARIA ===
    'acropora': ('Cnidaria', 'Anthozoa', 'Scleractinia', 'Acroporidae', 'target_other_aquatic_invert'),
    'porites': ('Cnidaria', 'Anthozoa', 'Scleractinia', 'Poritidae', 'target_other_aquatic_invert'),
    'pocillopora': ('Cnidaria', 'Anthozoa', 'Scleractinia', 'Pocilloporidae', 'target_other_aquatic_invert'),
    'stylophora': ('Cnidaria', 'Anthozoa', 'Scleractinia', 'Pocilloporidae', 'target_other_aquatic_invert'),
    'orbicella': ('Cnidaria', 'Anthozoa', 'Scleractinia', 'Merulinidae', 'target_other_aquatic_invert'),
    'montastraea': ('Cnidaria', 'Anthozoa', 'Scleractinia', 'Montastraeidae', 'target_other_aquatic_invert'),
    'nematostella': ('Cnidaria', 'Anthozoa', 'Actiniaria', 'Edwardsiidae', 'target_other_aquatic_invert'),
    'exaiptasia': ('Cnidaria', 'Anthozoa', 'Actiniaria', 'Aiptasiidae', 'target_other_aquatic_invert'),
    'hydra': ('Cnidaria', 'Hydrozoa', 'Anthoathecata', 'Hydridae', 'target_other_aquatic_invert'),

    # === ECHINODERMATA ===
    'apostichopus': ('Echinodermata', 'Holothuroidea', 'Synallactida', 'Stichopodidae', 'target_other_aquatic_invert'),
    'holothuria': ('Echinodermata', 'Holothuroidea', 'Holothuriida', 'Holothuriidae', 'target_other_aquatic_invert'),
    'strongylocentrotus': ('Echinodermata', 'Echinoidea', 'Camarodonta', 'Strongylocentrotidae', 'target_other_aquatic_invert'),
    'paracentrotus': ('Echinodermata', 'Echinoidea', 'Camarodonta', 'Parechinidae', 'target_other_aquatic_invert'),
    'lytechinus': ('Echinodermata', 'Echinoidea', 'Camarodonta', 'Toxopneustidae', 'target_other_aquatic_invert'),
    'asterias': ('Echinodermata', 'Asteroidea', 'Forcipulatida', 'Asteriidae', 'target_other_aquatic_invert'),
    'pisaster': ('Echinodermata', 'Asteroidea', 'Forcipulatida', 'Asteriidae', 'target_other_aquatic_invert'),
    'acanthaster': ('Echinodermata', 'Asteroidea', 'Valvatida', 'Acanthasteridae', 'target_other_aquatic_invert'),

    # === PORIFERA ===
    'amphimedon': ('Porifera', 'Demospongiae', 'Haplosclerida', 'Niphatidae', 'target_other_aquatic_invert'),
    'xestospongia': ('Porifera', 'Demospongiae', 'Haplosclerida', 'Petrosiidae', 'target_other_aquatic_invert'),
    'ephydatia': ('Porifera', 'Demospongiae', 'Spongillida', 'Spongillidae', 'target_other_aquatic_invert'),
    'tethya': ('Porifera', 'Demospongiae', 'Tethyida', 'Tethyidae', 'target_other_aquatic_invert'),
}

# ── Common name → phylum mapping ──────────────────────────────────────────
COMMON_NAME_MAP = {
    'shrimp': ('Arthropoda', 'target_crustacean'),
    'prawn': ('Arthropoda', 'target_crustacean'),
    'crab': ('Arthropoda', 'target_crustacean'),
    'crayfish': ('Arthropoda', 'target_crustacean'),
    'lobster': ('Arthropoda', 'target_crustacean'),
    'copepod': ('Arthropoda', 'target_crustacean'),
    'amphipod': ('Arthropoda', 'target_crustacean'),
    'isopod': ('Arthropoda', 'target_crustacean'),
    'barnacle': ('Arthropoda', 'target_crustacean'),
    'krill': ('Arthropoda', 'target_crustacean'),
    'daphnia': ('Arthropoda', 'target_crustacean'),
    'artemia': ('Arthropoda', 'target_crustacean'),
    'crustacean': ('Arthropoda', 'target_crustacean'),
    'decapod': ('Arthropoda', 'target_crustacean'),
    'oyster': ('Mollusca', 'target_mollusk'),
    'mussel': ('Mollusca', 'target_mollusk'),
    'clam': ('Mollusca', 'target_mollusk'),
    'scallop': ('Mollusca', 'target_mollusk'),
    'abalone': ('Mollusca', 'target_mollusk'),
    'snail': ('Mollusca', 'target_mollusk'),
    'bivalv': ('Mollusca', 'target_mollusk'),
    'gastropod': ('Mollusca', 'target_mollusk'),
    'mollusc': ('Mollusca', 'target_mollusk'),
    'squid': ('Mollusca', 'target_mollusk'),
    'octopus': ('Mollusca', 'target_mollusk'),
    'coral': ('Cnidaria', 'target_other_aquatic_invert'),
    'anemone': ('Cnidaria', 'target_other_aquatic_invert'),
    'jellyfish': ('Cnidaria', 'target_other_aquatic_invert'),
    'cnidaria': ('Cnidaria', 'target_other_aquatic_invert'),
    'sea cucumber': ('Echinodermata', 'target_other_aquatic_invert'),
    'sea urchin': ('Echinodermata', 'target_other_aquatic_invert'),
    'starfish': ('Echinodermata', 'target_other_aquatic_invert'),
    'echinoderm': ('Echinodermata', 'target_other_aquatic_invert'),
    'sponge': ('Porifera', 'target_other_aquatic_invert'),
    'polychaete': ('Annelida', 'target_other_aquatic_invert'),
    'ascidian': ('Chordata', 'target_other_aquatic_invert'),
    'tunicate': ('Chordata', 'target_other_aquatic_invert'),
}

# ── Pattern: extract capitalized genus-looking words from virus name ─────
CAPITALIZED_WORD = re.compile(r'\b([A-Z][a-z]{2,})\b')

def main(dry_run=False):
    conn = sqlite3.connect(DB)
    c = conn.cursor()

    # Load existing hosts
    c.execute('SELECT LOWER(scientific_name), host_id FROM crustacean_hosts')
    existing_hosts = {r[0]: r[1] for r in c.fetchall()}
    print(f'Existing hosts: {len(existing_hosts)}')

    # Get all virus species
    c.execute('''SELECT master_id, canonical_name, host_phylum, virus_family
                 FROM virus_master ORDER BY canonical_name''')
    viruses = c.fetchall()
    print(f'Viruses to process: {len(viruses)}')

    new_hosts = 0
    new_infections = 0
    updated_phylum = 0
    matched_species = 0
    matched_genus = 0
    matched_common = 0
    matched_family = 0

    for mid, name, current_phylum, family in viruses:
        if not name:
            continue
        name_lower = name.lower().strip()

        host_id = None
        match_type = None
        inferred_phylum = None
        host_scientific_name = None

        # ── Strategy 1: Find ANY capitalized words that match known genera ──
        cap_words = CAPITALIZED_WORD.findall(name)
        matched_genus_name = None
        matched_taxonomy = None
        for word in cap_words:
            word_lower = word.lower()
            if word_lower in GENUS_MAP:
                matched_genus_name = word
                matched_taxonomy = GENUS_MAP[word_lower]
                break
            # Also check if it matches a host already in the DB
            if word_lower in existing_hosts:
                host_id = existing_hosts[word_lower]
                inferred_phylum = None  # will get from host record
                match_type = 'existing_host_name'
                break

        if matched_genus_name and not match_type:
            phy, cls, order, family_name, scope = matched_taxonomy
            inferred_phylum = phy
            host_scientific_name = matched_genus_name
            match_type = 'genus_match'

        # ── Strategy 2: Common name substring match ──────────────────────
        if not match_type:
            for common, (phy, scope) in COMMON_NAME_MAP.items():
                if common in name_lower:
                    inferred_phylum = phy
                    match_type = 'common_name'
                    break

        # ── Strategy 3: From existing host_phylum ────────────────────────
        if not match_type and current_phylum and current_phylum not in ('unset', ''):
            inferred_phylum = current_phylum
            match_type = 'from_existing_phylum'

        # ── Strategy 4: From virus family ─────────────────────────────────
        if not match_type and family:
            family_phylum_map = {
                'Malacoherpesviridae': ('Mollusca', 'target_mollusk'),
                'Nimaviridae': ('Arthropoda', 'target_crustacean'),
                'Nudiviridae': ('Arthropoda', 'target_crustacean'),
                'Roniviridae': ('Arthropoda', 'target_crustacean'),
                'Sarthroviridae': ('Arthropoda', 'target_crustacean'),
                'Dicistroviridae': ('Arthropoda', 'target_crustacean'),
                'Iflaviridae': ('Arthropoda', 'target_crustacean'),
            }
            if family in family_phylum_map:
                inferred_phylum, scope = family_phylum_map[family]
                match_type = 'from_family'
                matched_family += 1

        # ── Apply results ──────────────────────────────────────────────
        if match_type and not dry_run:
            # Create genus-level host entry if needed
            if match_type in ('genus_match', 'existing_host_name') and host_scientific_name:
                name_key = host_scientific_name.lower()
                if name_key not in existing_hosts and matched_taxonomy:
                    try:
                        phy, cls, order, fam, scope = matched_taxonomy
                        c.execute('''INSERT INTO crustacean_hosts
                            (scientific_name, taxon_order, taxon_family, phylum, class, host_scope_status)
                            VALUES (?, ?, ?, ?, ?, ?)''',
                            (host_scientific_name, order, fam, phy, cls, scope))
                        host_id = c.lastrowid
                        existing_hosts[name_key] = host_id
                        new_hosts += 1
                    except sqlite3.IntegrityError:
                        c.execute('SELECT host_id FROM crustacean_hosts WHERE LOWER(scientific_name) = ?',
                                 (name_key,))
                        ex = c.fetchone()
                        if ex:
                            host_id = ex[0]
                            existing_hosts[name_key] = host_id

            # Update virus_master host_phylum if unset
            needs_phylum = not current_phylum or current_phylum == 'unset' or current_phylum == ''
            if needs_phylum and inferred_phylum:
                c.execute('UPDATE virus_master SET host_phylum = ? WHERE master_id = ?',
                         (inferred_phylum, mid))
                updated_phylum += 1

            # Create infection_record if we have a host_id
            if host_id:
                c.execute('''SELECT COUNT(*) FROM infection_records ir
                             JOIN viral_isolates vi ON ir.isolate_id = vi.isolate_id
                             WHERE vi.master_id = ? AND ir.host_id = ?''', (mid, host_id))
                if c.fetchone()[0] == 0:
                    c.execute('SELECT isolate_id FROM viral_isolates WHERE master_id = ? LIMIT 1', (mid,))
                    iso = c.fetchone()
                    if iso:
                        try:
                            c.execute('''INSERT INTO infection_records
                                (isolate_id, host_id, host_association_method, detection_method)
                                VALUES (?, ?, 'name_inference', 'sequence_analysis')''',
                                (iso[0], host_id))
                            new_infections += 1
                        except sqlite3.IntegrityError:
                            pass

        # Count match types
        if match_type == 'genus_match': matched_genus += 1
        elif match_type == 'existing_host_name': matched_species += 1
        elif match_type == 'common_name': matched_common += 1

    if not dry_run:
        conn.commit()

    # ── Report ────────────────────────────────────────────────────────────
    c.execute('SELECT COUNT(*) FROM infection_records')
    total_inf = c.fetchone()[0]
    c.execute('SELECT COUNT(DISTINCT vm.master_id) FROM virus_master vm '
              'JOIN viral_isolates vi ON vm.master_id = vi.master_id '
              'JOIN infection_records ir ON vi.isolate_id = ir.isolate_id')
    species_linked = c.fetchone()[0]
    c.execute('SELECT COUNT(*) FROM crustacean_hosts')
    total_hosts = c.fetchone()[0]
    c.execute('SELECT COUNT(*) FROM virus_master WHERE host_phylum IS NULL OR host_phylum = ""')
    still_unset = c.fetchone()[0]

    print(f'\n{"DRY RUN" if dry_run else "RESULTS"}')
    print('=' * 50)
    print(f'Species matched (existing host):     {matched_species}')
    print(f'Species matched (genus level):       {matched_genus}')
    print(f'Species matched (common name):       {matched_common}')
    print(f'New host entries created:            {new_hosts}')
    print(f'New infection records:               {new_infections}')
    print(f'Updated host_phylum (was unset):     {updated_phylum}')
    print(f'')
    print(f'Total hosts (all):                   {total_hosts}')
    print(f'Total infection records:             {total_inf}')
    print(f'Species with host linkage:           {species_linked} / {len(viruses)}')
    print(f'Still unset host_phylum:             {still_unset}')

    # Show host scope distribution
    c.execute('''SELECT host_scope_status, COUNT(*) FROM crustacean_hosts
                 GROUP BY host_scope_status ORDER BY COUNT(*) DESC''')
    print(f'\nHost scope distribution:')
    for r in c.fetchall():
        print(f'  {r[0]}: {r[1]}')

    conn.close()


if __name__ == '__main__':
    dry = '--dry-run' in sys.argv
    main(dry_run=dry)
