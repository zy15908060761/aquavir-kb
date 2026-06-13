"""
BULK IMPORT v2 — fetch GenBank XML for proper organism names.
NCBI API works. Fix: use efetch to get GBSeq_organism from full XML records.

Target: >300 new distinct virus species from aquatic invertebrates.
"""

import sqlite3
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
import re

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "crustacean_virus_core.db"
NCBI_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
RATE = 0.35

# Focused queries for maximum new SPECIES diversity
QUERIES = [
    # Mollusk herpesviruses - complete genomes
    ("Malaco_all", 'Malacoherpesviridae[Organism] AND complete genome[title]', "Mollusca"),
    ("OsHV1_all", '(Ostreid herpesvirus[Organism] OR OsHV-1[All]) AND 2000:2026[pdat]', "Mollusca"),
    ("Haliotid_all", '(Haliotid herpesvirus[Organism] OR HaHV-1[All] OR abalone herpesvirus[All])', "Mollusca"),

    # Mollusk picorna-like and other RNA viruses
    ("Oyster_picornavirus", '(oyster[All] AND picornavirus[All]) NOT bacteria[Organism] AND 2000:2026[pdat]', "Mollusca"),
    ("Bivalve_RNA_virus", '(bivalve[All] AND "RNA virus"[All]) NOT bacteria[Organism] AND 2015:2026[pdat]', "Mollusca"),
    ("Mollusk_nodavirus", '(mollusc*[All] AND nodavirus[All]) NOT bacteria[Organism]', "Mollusca"),
    ("Abalone_virus_all", '(abalone OR Haliotis) AND virus[Organism] NOT bacteria[Organism] AND 2000:2026[pdat]', "Mollusca"),
    ("Mussel_virus_all", '(mussel OR Mytilus) AND virus[Organism] NOT bacteria[Organism] AND 2000:2026[pdat]', "Mollusca"),
    ("Clam_virus_all", '(clam OR Ruditapes OR Mercenaria) AND virus[Organism] NOT bacteria[Organism] AND 2000:2026[pdat]', "Mollusca"),
    ("Scallop_virus_all", '(scallop OR Pecten OR Argopecten OR Chlamys) AND virus[Organism] NOT bacteria[Organism]', "Mollusca"),
    ("Oyster_virus_all", '(oyster OR Crassostrea OR Saccostrea OR Ostrea) AND virus[Organism] NOT bacteria[Organism] AND 2010:2026[pdat]', "Mollusca"),

    # Coral/Cnidaria
    ("Coral_virus_all", '(coral OR Acropora OR Porites OR Pocillopora) AND virus[Organism] NOT bacteria[Organism] AND 2010:2026[pdat]', "Cnidaria"),
    ("Cnidaria_virus_all", '(Cnidaria OR "sea anemone" OR Nematostella OR Exaiptasia OR Hydra) AND virus[Organism] NOT bacteria[Organism] AND 2010:2026[pdat]', "Cnidaria"),
    ("Coral_virome_all", 'coral virome AND virus[Organism] NOT bacteria[Organism] NOT cellular[Organism] AND 2015:2026[pdat]', "Cnidaria"),

    # Echinoderm
    ("Echinoderm_virus_all", '(Echinodermata OR "sea cucumber" OR Apostichopus OR Holothuria OR "sea urchin" OR Strongylocentrotus OR starfish OR Asterias) AND virus[Organism] NOT bacteria[Organism] AND 2000:2026[pdat]', "Echinodermata"),
    ("Sea_cucumber_all", '(Apostichopus OR Holothuria OR "sea cucumber") AND virus[Organism] NOT bacteria[Organism]', "Echinodermata"),
    ("Sea_urchin_virus_all", '("sea urchin" OR Strongylocentrotus OR Paracentrotus) AND virus[Organism] NOT bacteria[Organism]', "Echinodermata"),

    # Sponge
    ("Sponge_virus_all", '(Porifera OR sponge OR Amphimedon OR Xestospongia) AND virus[Organism] NOT bacteria[Organism] AND 2000:2026[pdat]', "Porifera"),

    # Marine invertebrate viromes (Shi et al. type)
    ("Marine_invert_virus_all", '("marine invertebrate" OR "aquatic invertebrate") AND virus[Organism] NOT bacteria[Organism] NOT cellular[Organism] AND 2015:2026[pdat]', None),
    ("Invert_virome_novel", '(invertebrate virome OR invertebrate RNA virus) AND "complete genome"[title] AND 2015:2026[pdat]', None),

    # Specific virus families known in aquatic inverts
    ("Nimaviridae_all", 'Nimaviridae[Organism] AND complete genome[title]', "Arthropoda"),
    ("Iridoviridae_invert", 'Iridoviridae[Organism] AND (invertebrate OR shrimp OR crab OR crayfish OR mollusc* OR coral) AND complete genome[title]', None),
    ("Nodaviridae_invert", 'Nodaviridae[Organism] AND (shrimp OR prawn OR crab OR mollusc*) AND complete genome[title]', None),
    ("Circoviridae_invert", 'Circoviridae[Organism] AND (invertebrate OR shrimp OR crab OR mollusc* OR coral) AND 2000:2026[pdat]', None),
    ("Parvoviridae_invert", '(Parvoviridae OR Densovirinae) AND (invertebrate OR shrimp OR crab OR crayfish) AND virus[Organism] NOT bacteria[Organism] AND 2000:2026[pdat]', "Arthropoda"),
    ("Totiviridae_invert", 'Totiviridae[Organism] AND (shrimp OR crab OR mollusc* OR invertebrate) AND 2000:2026[pdat]', None),
    ("Picornavirales_invert", 'Picornavirales[Organism] AND (invertebrate OR shrimp OR crab OR mollusc* OR coral) AND "complete genome"[title] AND 2010:2026[pdat]', None),
    ("Bunyavirales_invert", 'Bunyavirales[Organism] AND (invertebrate OR shrimp OR crab OR mollusc*) AND 2010:2026[pdat]', None),
]

# Background noise filters
SKIP_ORGANISM = re.compile(r'^(uncultured|unclassified|environmental|seawater|marine sediment|'
                           r'Homo sapiens|Mus musculus|Escherichia coli|Saccharomyces|'
                           r'Arabidopsis|Danio rerio|Rattus|Bos taurus|Gallus gallus|'
                           r'Drosophila|Caenorhabditis|Xenopus|Oryza|Zea mays|'
                           r'Bacteriophage|\w+ phage|\w+ bacterium|'
                           r'\w+ bacteria|Actinobacterium|Proteobacterium)', re.IGNORECASE)


def ncbi_request(endpoint, params, db="nucleotide"):
    params["db"] = db
    params["retmode"] = "xml"
    url = f"{NCBI_BASE}/{endpoint}?{urllib.parse.urlencode(params)}"
    time.sleep(RATE)
    for attempt in range(3):
        try:
            req = urllib.request.Request(url)
            req.add_header("User-Agent", "AquaVir-KB/2.0")
            with urllib.request.urlopen(req, timeout=20) as resp:
                return resp.read().decode("utf-8")
        except Exception as e:
            if attempt == 2:
                return None
            time.sleep(2)


def fetch_genbank_records(accessions, batch_size=15):
    """Fetch GenBank XML for accessions. Returns list of parsed virus records."""
    results = []
    for i in range(0, len(accessions), batch_size):
        batch = accessions[i:i+batch_size]
        xml_str = ncbi_request("efetch.fcgi", {
            "id": ",".join(batch),
            "rettype": "gb",
            "retmode": "xml",
        })
        if not xml_str:
            continue
        try:
            root = ET.fromstring(xml_str)
        except ET.ParseError:
            continue

        for seq in root.findall(".//GBSeq"):
            acc = (seq.findtext("GBSeq_primary-accession") or "").strip()
            if not acc:
                continue
            organism = (seq.findtext("GBSeq_organism") or "").strip()
            definition = (seq.findtext("GBSeq_definition") or "").strip()
            length = (seq.findtext("GBSeq_length") or "0").strip()
            mol_type = (seq.findtext("GBSeq_moltype") or "").strip()

            # Skip junk
            if not organism or SKIP_ORGANISM.match(organism):
                continue
            if 'virus' not in organism.lower() and 'phage' not in organism.lower():
                continue

            # Extract host/geo from features
            host = ""
            country = ""
            collection_date = ""
            features_elem = seq.find("GBSeq_feature-table")
            if features_elem is not None:
                for feat in features_elem.findall("GBFeature"):
                    for qual in feat.findall(".//GBQualifier"):
                        qname = (qual.findtext("GBQualifier_name") or "").lower()
                        qval = (qual.findtext("GBQualifier_value") or "").strip()
                        if qname == "host":
                            host = qval
                        elif qname == "country":
                            country = qval
                        elif qname == "collection_date":
                            collection_date = qval

            # Infer genome type
            genome_type = "DNA" if "dna" in mol_type.lower() else "RNA" if "rna" in mol_type.lower() else ""

            results.append({
                "accession": acc,
                "organism": organism,
                "definition": definition[:300],
                "length": int(length) if length.isdigit() else 0,
                "genome_type": genome_type,
                "host": host,
                "country": country,
                "collection_date": collection_date,
            })
    return results


def main():
    conn = sqlite3.connect(str(DB_PATH))
    c = conn.cursor()
    c.execute("SELECT DISTINCT accession FROM viral_isolates")
    existing_acc = {row[0] for row in c.fetchall()}
    c.execute("SELECT DISTINCT canonical_name FROM virus_master")
    existing_names = {row[0].lower() for row in c.fetchall()}
    print(f"Existing: {len(existing_acc)} accessions, {len(existing_names)} virus names")

    total_isolates = 0
    total_species = 0
    stats = {}

    for label, term, host_phylum in QUERIES:
        print(f"\n[{host_phylum or 'any':20s}] {label:30s} ...", end=" ", flush=True)

        # Search NCBI
        xml_str = ncbi_request("esearch.fcgi", {
            "term": term, "retmax": "80", "sort": "relevance", "usehistory": "y",
        })
        if not xml_str:
            print("SEARCH_FAIL")
            continue
        try:
            root = ET.fromstring(xml_str)
            ncbi_ids = [e.text for e in root.findall(".//Id") if e.text]
            count = int(root.findtext(".//Count") or "0")
        except Exception:
            print("PARSE_FAIL")
            continue

        # Filter to truly new accessions
        new_ids = [i for i in ncbi_ids if i not in existing_acc][:40]
        if not new_ids:
            print(f"{count:5d} total, 0 new")
            stats[label] = {"new_isolates": 0, "new_species": 0}
            continue

        print(f"{count:5d} total, {len(new_ids):3d} new ids...", end=" ", flush=True)

        # Fetch full GenBank records
        records = fetch_genbank_records(new_ids)
        new_iso = 0
        new_sp = 0

        for rec in records:
            acc = rec["accession"]
            organism = rec["organism"]

            # Dedup by accession
            if acc in existing_acc:
                continue

            # Normalize organism name
            org_key = organism.lower().strip()

            # Try to match existing virus_master
            c.execute("SELECT master_id FROM virus_master WHERE canonical_name = ?", (organism,))
            vm = c.fetchone()
            if vm:
                master_id = vm[0]
            elif org_key in existing_names:
                # Find the matching name
                c.execute("SELECT master_id FROM virus_master WHERE LOWER(canonical_name) = ?", (org_key,))
                vm = c.fetchone()
                master_id = vm[0] if vm else None
            else:
                # NEW VIRUS SPECIES!
                try:
                    c.execute("""INSERT INTO virus_master
                        (canonical_name, genome_type, entry_type,
                         discovery_context, host_phylum)
                        VALUES (?, ?, 'partial_genome',
                         'metagenomic_survey', ?)""",
                        (organism, rec["genome_type"] or "", host_phylum))
                    master_id = c.lastrowid
                    existing_names.add(org_key)
                    new_sp += 1
                except sqlite3.IntegrityError:
                    # Race condition or duplicate name
                    c.execute("SELECT master_id FROM virus_master WHERE canonical_name = ?", (organism,))
                    vm = c.fetchone()
                    master_id = vm[0] if vm else None

            if master_id is None:
                continue

            # Insert isolate
            try:
                c.execute("""INSERT INTO viral_isolates
                    (accession, virus_name, master_id, genome_length,
                     genome_type)
                    VALUES (?, ?, ?, ?, ?)""",
                    (acc, organism, master_id, rec["length"],
                     rec["genome_type"] or None))
                existing_acc.add(acc)
                new_iso += 1
            except sqlite3.IntegrityError:
                continue

        stats[label] = {"new_isolates": new_iso, "new_species": new_sp}
        total_isolates += new_iso
        total_species += new_sp
        print(f"+{new_iso} isolates, +{new_sp} species")

        if total_isolates % 200 == 0:
            conn.commit()

    conn.commit()

    # Final count
    c.execute("SELECT COUNT(*) FROM virus_master")
    final_sp = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM viral_isolates")
    final_iso = c.fetchone()[0]

    # Host phyla stats
    c.execute("""SELECT phylum, host_scope_status, COUNT(*)
                 FROM crustacean_hosts
                 WHERE host_scope_status LIKE 'target%'
                 GROUP BY phylum, host_scope_status ORDER BY COUNT(*) DESC""")
    host_stats = c.fetchall()

    print("\n" + "=" * 60)
    print(f"IMPORT COMPLETE — {total_isolates} isolates, {total_species} species")
    print("=" * 60)
    print(f"Virus species: 531 → {final_sp} (+{final_sp - 531})")
    print(f"Isolates:      4682 → {final_iso} (+{final_iso - 4682})")
    print(f"\nTarget hosts by phylum:")
    for ph, scope, cnt in host_stats:
        print(f"  {ph}: [{scope}] {cnt}")

    print(f"\nQuery results:")
    for label, s in sorted(stats.items(), key=lambda x: -x[1]['new_isolates']):
        if s['new_isolates'] > 0:
            print(f"  {label:30s}: +{s['new_isolates']:3d} isolates, +{s['new_species']:3d} species")
    conn.close()


if __name__ == "__main__":
    main()
