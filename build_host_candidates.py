#!/usr/bin/env python3
"""Build and import aquatic invertebrate host candidate list."""
import sqlite3, datetime

conn = sqlite3.connect('F:/水生无脊椎动物数据库/crustacean_virus_core.db')

targets = [
    # Mollusca - Bivalvia
    ('Crassostrea gigas', 'Pacific oyster (long muli)', 'Ostreida', 'Ostreidae', 'Mollusca', 'Bivalvia', 'oyster', 'marine', 'major'),
    ('Crassostrea virginica', 'Eastern oyster', 'Ostreida', 'Ostreidae', 'Mollusca', 'Bivalvia', 'oyster', 'marine', 'major'),
    ('Crassostrea angulata', 'Portuguese oyster', 'Ostreida', 'Ostreidae', 'Mollusca', 'Bivalvia', 'oyster', 'marine', 'minor'),
    ('Crassostrea hongkongensis', 'Hong Kong oyster', 'Ostreida', 'Ostreidae', 'Mollusca', 'Bivalvia', 'oyster', 'marine', 'minor'),
    ('Ostrea edulis', 'European flat oyster', 'Ostreida', 'Ostreidae', 'Mollusca', 'Bivalvia', 'oyster', 'marine', 'major'),
    ('Saccostrea glomerata', 'Sydney rock oyster', 'Ostreida', 'Ostreidae', 'Mollusca', 'Bivalvia', 'oyster', 'marine', 'minor'),
    ('Mytilus edulis', 'Blue mussel', 'Mytilida', 'Mytilidae', 'Mollusca', 'Bivalvia', 'mussel', 'marine', 'major'),
    ('Mytilus coruscus', 'Hard-shell mussel', 'Mytilida', 'Mytilidae', 'Mollusca', 'Bivalvia', 'mussel', 'marine', 'minor'),
    ('Perna viridis', 'Asian green mussel', 'Mytilida', 'Mytilidae', 'Mollusca', 'Bivalvia', 'mussel', 'marine', 'major'),
    ('Perna canaliculus', 'New Zealand green-lipped mussel', 'Mytilida', 'Mytilidae', 'Mollusca', 'Bivalvia', 'mussel', 'marine', 'major'),
    ('Ruditapes philippinarum', 'Manila clam', 'Venerida', 'Veneridae', 'Mollusca', 'Bivalvia', 'clam', 'marine', 'major'),
    ('Mercenaria mercenaria', 'Hard clam', 'Venerida', 'Veneridae', 'Mollusca', 'Bivalvia', 'clam', 'marine', 'major'),
    ('Sinonovacula constricta', 'Razor clam', 'Adapedonta', 'Solenidae', 'Mollusca', 'Bivalvia', 'clam', 'marine', 'major'),
    ('Patinopecten yessoensis', 'Yesso scallop', 'Pectinida', 'Pectinidae', 'Mollusca', 'Bivalvia', 'scallop', 'marine', 'major'),
    ('Chlamys farreri', 'Farrers scallop', 'Pectinida', 'Pectinidae', 'Mollusca', 'Bivalvia', 'scallop', 'marine', 'major'),
    ('Argopecten irradians', 'Bay scallop', 'Pectinida', 'Pectinidae', 'Mollusca', 'Bivalvia', 'scallop', 'marine', 'major'),
    ('Pinctada fucata', 'Akoya pearl oyster', 'Ostreida', 'Pteriidae', 'Mollusca', 'Bivalvia', 'pearl oyster', 'marine', 'major'),
    # Mollusca - Gastropoda
    ('Haliotis discus hannai', 'Disk abalone', 'Lepetellida', 'Haliotidae', 'Mollusca', 'Gastropoda', 'abalone', 'marine', 'major'),
    ('Haliotis rufescens', 'Red abalone', 'Lepetellida', 'Haliotidae', 'Mollusca', 'Gastropoda', 'abalone', 'marine', 'major'),
    ('Haliotis rubra', 'Blacklip abalone', 'Lepetellida', 'Haliotidae', 'Mollusca', 'Gastropoda', 'abalone', 'marine', 'major'),
    ('Haliotis midae', 'South African abalone', 'Lepetellida', 'Haliotidae', 'Mollusca', 'Gastropoda', 'abalone', 'marine', 'major'),
    ('Haliotis tuberculata', 'European abalone', 'Lepetellida', 'Haliotidae', 'Mollusca', 'Gastropoda', 'abalone', 'marine', 'major'),
    ('Pomacea canaliculata', 'Apple snail', 'Architaenioglossa', 'Ampullariidae', 'Mollusca', 'Gastropoda', 'snail', 'freshwater', 'minor'),
    ('Lymnaea stagnalis', 'Great pond snail', 'Lymnaeida', 'Lymnaeidae', 'Mollusca', 'Gastropoda', 'snail', 'freshwater', 'wild_only'),
    ('Biomphalaria glabrata', 'Blood fluke planorb', 'Planorbida', 'Planorbidae', 'Mollusca', 'Gastropoda', 'snail', 'freshwater', 'wild_only'),
    # Mollusca - Cephalopoda
    ('Octopus vulgaris', 'Common octopus', 'Octopoda', 'Octopodidae', 'Mollusca', 'Cephalopoda', 'octopus', 'marine', 'major'),
    ('Sepia officinalis', 'Common cuttlefish', 'Sepiida', 'Sepiidae', 'Mollusca', 'Cephalopoda', 'cuttlefish', 'marine', 'major'),
    # Echinodermata
    ('Apostichopus japonicus', 'Japanese sea cucumber', 'Synallactida', 'Stichopodidae', 'Echinodermata', 'Holothuroidea', 'sea cucumber', 'marine', 'major'),
    ('Holothuria scabra', 'Sandfish', 'Holothuriida', 'Holothuriidae', 'Echinodermata', 'Holothuroidea', 'sea cucumber', 'marine', 'minor'),
    ('Strongylocentrotus purpuratus', 'Purple sea urchin', 'Camarodonta', 'Strongylocentrotidae', 'Echinodermata', 'Echinoidea', 'sea urchin', 'marine', 'wild_only'),
    ('Strongylocentrotus intermedius', 'Intermediate sea urchin', 'Camarodonta', 'Strongylocentrotidae', 'Echinodermata', 'Echinoidea', 'sea urchin', 'marine', 'major'),
    ('Acanthaster planci', 'Crown-of-thorns starfish', 'Valvatida', 'Acanthasteridae', 'Echinodermata', 'Asteroidea', 'starfish', 'marine', 'wild_only'),
    ('Asterias rubens', 'Common starfish', 'Forcipulatida', 'Asteriidae', 'Echinodermata', 'Asteroidea', 'starfish', 'marine', 'wild_only'),
    # Cnidaria
    ('Acropora millepora', 'Staghorn coral', 'Scleractinia', 'Acroporidae', 'Cnidaria', 'Anthozoa', 'coral', 'marine', 'wild_only'),
    ('Acropora digitifera', 'Finger coral', 'Scleractinia', 'Acroporidae', 'Cnidaria', 'Anthozoa', 'coral', 'marine', 'wild_only'),
    ('Nematostella vectensis', 'Starlet sea anemone', 'Actiniaria', 'Edwardsiidae', 'Cnidaria', 'Anthozoa', 'sea anemone', 'marine', 'wild_only'),
    ('Exaiptasia pallida', 'Aiptasia anemone', 'Actiniaria', 'Aiptasiidae', 'Cnidaria', 'Anthozoa', 'sea anemone', 'marine', 'wild_only'),
    ('Hydra vulgaris', 'Common hydra', 'Hydroida', 'Hydridae', 'Cnidaria', 'Hydrozoa', 'hydra', 'freshwater', 'wild_only'),
    ('Aurelia aurita', 'Moon jellyfish', 'Semaeostomeae', 'Ulmaridae', 'Cnidaria', 'Scyphozoa', 'jellyfish', 'marine', 'wild_only'),
    # Porifera
    ('Amphimedon queenslandica', 'Great Barrier Reef sponge', 'Haplosclerida', 'Niphatidae', 'Porifera', 'Demospongiae', 'sponge', 'marine', 'wild_only'),
    ('Stylissa carteri', 'Carters sponge', 'Scopalinida', 'Scopalinidae', 'Porifera', 'Demospongiae', 'sponge', 'marine', 'wild_only'),
    ('Aplysina aerophoba', 'Golden sponge', 'Verongiida', 'Aplysinidae', 'Porifera', 'Demospongiae', 'sponge', 'marine', 'wild_only'),
    # Annelida
    ('Arenicola marina', 'Lugworm', 'Terebellida', 'Arenicolidae', 'Annelida', 'Polychaeta', 'polychaete', 'marine', 'wild_only'),
    ('Perinereis aibuhitensis', 'Sandworm', 'Phyllodocida', 'Nereididae', 'Annelida', 'Polychaeta', 'polychaete', 'marine', 'minor'),
    # Platyhelminthes (aquatic)
    ('Schmidtea mediterranea', 'Freshwater planarian', 'Tricladida', 'Dugesiidae', 'Platyhelminthes', 'Rhabditophora', 'flatworm', 'freshwater', 'wild_only'),
    # Nematoda
    ('Caenorhabditis elegans', 'C. elegans', 'Rhabditida', 'Rhabditidae', 'Nematoda', 'Chromadorea', 'nematode', 'terrestrial', 'wild_only'),
]

# Check existing
existing = {r[0].lower() for r in conn.execute('SELECT LOWER(scientific_name) FROM crustacean_hosts').fetchall()}

missing = [(name, cn, order_, family, phylum, class_, group, habitat, aqua_status)
           for name, cn, order_, family, phylum, class_, group, habitat, aqua_status in targets
           if name.lower() not in existing]

print(f'Already in DB: {len(targets) - len(missing)} / {len(targets)}')
print(f'To add: {len(missing)}')

# Import
ts = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
def nid():
    return conn.execute('SELECT COALESCE(MAX(host_id), 0) FROM crustacean_hosts').fetchone()[0] + 1

imported = 0
for name, cn, order_, family, phylum, class_, group, habitat, aqua_status in missing:
    hid = nid()
    try:
        conn.execute("""
        INSERT INTO crustacean_hosts (host_id, scientific_name, common_name_cn, taxon_order, taxon_family,
            phylum, class, host_group, habitat, aquaculture_status, host_scope_status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'target_mollusk')
        """, (hid, name, cn, order_, family, phylum, class_, group, habitat, aqua_status))

        # Also add host_taxonomy_profiles placeholder
        tpid = conn.execute('SELECT COALESCE(MAX(profile_id), 0) FROM host_taxonomy_profiles').fetchone()[0] + 1
        conn.execute("""
        INSERT INTO host_taxonomy_profiles (profile_id, host_id, accepted_name, lineage_phylum,
            lineage_class, lineage_order, lineage_family, is_target_host, confidence)
        VALUES (?, ?, ?, ?, ?, ?, ?, 1, 'medium')
        """, (tpid, hid, name, phylum, class_, order_, family))

        imported += 1
    except Exception as e:
        print(f'ERROR [{name}]: {e}')

conn.commit()
print(f'Imported: {imported} new hosts')
print(f'Total hosts: {conn.execute("SELECT COUNT(*) FROM crustacean_hosts").fetchone()[0]}')

# Summary by phylum
for r in conn.execute('SELECT phylum, COUNT(*) FROM crustacean_hosts GROUP BY phylum ORDER BY COUNT(*) DESC').fetchall():
    print(f'  {r[0]:<30} {r[1]}')
conn.close()
