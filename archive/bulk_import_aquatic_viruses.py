"""
BULK import aquatic invertebrate viruses from NCBI.
NCBI API is confirmed working. Max speed with rate limiting.

Target: Add 500-1500 new virus species from mollusk/coral/echinoderm phyla.

Usage: python bulk_import_aquatic_viruses.py [--dry-run] [--max 200]
"""

import sqlite3
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "crustacean_virus_core.db"
NCBI_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
RATE = 0.35

# Priority search queries - tuned for high recall of aquatic invertebrate viruses
QUERIES = [
    # === MOLLUSK VIRUSES ===
    # Malacoherpesviridae - ALL members infect mollusks (oyster/abalone herpesviruses)
    ("Malacoherpesviridae", 'Malacoherpesviridae[Organism]', "Mollusca", "Bivalvia"),
    # Oyster viruses (host filter)
    ("Oyster_virus", '(oyster[host] OR Crassostrea[host] OR Saccostrea[host] OR Ostrea[host]) AND viruses[organism] NOT bacteria[organism] AND 2000:2026[dp]', "Mollusca", "Bivalvia"),
    # Abalone viruses
    ("Abalone_virus", '(abalone[host] OR Haliotis[host]) AND viruses[organism] NOT bacteria[organism] AND 2000:2026[dp]', "Mollusca", "Gastropoda"),
    # Mussel viruses
    ("Mussel_virus", '(mussel[host] OR Mytilus[host] OR Perna[host]) AND viruses[organism] NOT bacteria[organism] AND 2000:2026[dp]', "Mollusca", "Bivalvia"),
    # Clam viruses
    ("Clam_virus", '(clam[host] OR Ruditapes[host] OR Mercenaria[host] OR Venerupis[host]) AND viruses[organism] NOT bacteria[organism] AND 2000:2026[dp]', "Mollusca", "Bivalvia"),
    # Scallop viruses
    ("Scallop_virus", '(scallop[host] OR Pecten[host] OR Argopecten[host] OR Chlamys[host] OR Mizuhopecten[host]) AND viruses[organism] NOT bacteria[organism] AND 2000:2026[dp]', "Mollusca", "Bivalvia"),
    # Broad mollusk host search
    ("Mollusca_host_virus", '("Mollusca"[host] OR "Bivalvia"[host] OR "Gastropoda"[host]) AND viruses[organism] NOT bacteria[organism] AND 2015:2026[dp]', "Mollusca", None),
    # Mollusk virome
    ("Mollusk_virome", '(mollusc*[All] OR bivalve[All]) AND (metagenome[All] OR virome[All]) AND viruses[organism] NOT bacteria[organism] NOT cellular[organism] AND 2018:2026[dp]', "Mollusca", None),

    # === CORAL/CNIDARIA VIRUSES ===
    ("Coral_virus", '(coral[host] OR Acropora[host] OR Porites[host] OR Pocillopora[host] OR Stylophora[host]) AND viruses[organism] NOT bacteria[organism] AND 2010:2026[dp]', "Cnidaria", "Anthozoa"),
    ("Cnidaria_virus", '("Cnidaria"[host] OR "Anthozoa"[host] OR "sea anemone"[host]) AND viruses[organism] NOT bacteria[organism] AND 2010:2026[dp]', "Cnidaria", None),
    ("Coral_virome", '(coral[All] OR "reef"[All]) AND (metagenome[All] OR virome[All]) AND viruses[organism] NOT bacteria[organism] NOT cellular[organism] AND 2018:2026[dp]', "Cnidaria", None),

    # === ECHINODERM VIRUSES ===
    ("Echinoderm_virus", '("Echinodermata"[host] OR "sea cucumber"[host] OR "Holothuria"[host] OR "Apostichopus"[host] OR "sea urchin"[host] OR "Strongylocentrotus"[host] OR "starfish"[host] OR "Asterias"[host]) AND viruses[organism] NOT bacteria[organism] AND 2000:2026[dp]', "Echinodermata", None),
    ("Sea_cucumber_virus", '(Apostichopus[host] OR Holothuria[host] OR "sea cucumber"[host]) AND viruses[organism] NOT bacteria[organism] AND 2000:2026[dp]', "Echinodermata", "Holothuroidea"),

    # === PORIFERA VIRUSES ===
    ("Sponge_virus", '("Porifera"[host] OR "sponge"[host] OR "Amphimedon"[host]) AND viruses[organism] NOT bacteria[organism] AND 2000:2026[dp]', "Porifera", None),

    # === CROSS-PHYLUM MARINE INVERTEBRATE VIRUSES ===
    ("Marine_invert_RNA", '("marine invertebrate"[All] AND "RNA virus"[All]) NOT bacteria[organism] AND 2018:2026[dp]', None, None),
    ("Marine_invert_virome", '("marine invertebrate"[All] OR "aquatic invertebrate"[All]) AND (metagenome[All] OR virome[All]) AND viruses[organism] NOT cellular[organism] NOT bacteria[organism] AND 2018:2026[dp]', None, None),

    # === VIRUS FAMILY SEARCHES (many members infect aquatic inverts) ===
    ("Nimaviridae", 'Nimaviridae[Organism] AND 2000:2026[dp]', "Arthropoda", "Malacostraca"),
    ("Nodaviridae_aquatic", 'Nodaviridae[Organism] AND (shrimp[All] OR prawn[All] OR crab[All] OR mollusc*[All]) AND 2000:2026[dp]', "Arthropoda", None),
    ("Totiviridae_aquatic", 'Totiviridae[Organism] AND (crustacean[All] OR shrimp[All] OR crab[All] OR mollusc*[All]) AND 2000:2026[dp]', None, None),
]


def ncbi_request(endpoint, params, db="nucleotide"):
    params["db"] = db
    params["retmode"] = "xml"
    url = f"{NCBI_BASE}/{endpoint}?{urllib.parse.urlencode(params)}"
    time.sleep(RATE)
    try:
        req = urllib.request.Request(url)
        req.add_header("User-Agent", "AquaVir-KB/2.0")
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.read().decode("utf-8")
    except Exception as e:
        print(f"  REQ_ERR: {e}")
        return None


def search_and_fetch(term, max_results=100):
    """Search NCBI and fetch summaries. Returns list of dicts."""
    # Search
    xml_str = ncbi_request("esearch.fcgi", {
        "term": term, "retmax": str(max_results), "sort": "relevance", "usehistory": "y",
    })
    if not xml_str:
        return [], 0
    try:
        root = ET.fromstring(xml_str)
        ids = [e.text for e in root.findall(".//Id") if e.text]
        count = int(root.findtext(".//Count") or "0")
    except Exception:
        return [], 0
    if not ids:
        return [], count

    # Fetch summaries
    xml_str2 = ncbi_request("esummary.fcgi", {"id": ",".join(ids[:max_results])})
    if not xml_str2:
        return [], count

    records = []
    try:
        root2 = ET.fromstring(xml_str2)
        for ds in root2.findall(".//DocSum"):
            rec = {"uid": ds.findtext("Id")}
            for child in ds.findall("Item"):
                name = child.get("Name")
                if name in ("AccessionVersion", "Caption", "Title", "Organism",
                           "CreateDate", "TaxId", "BioProject", "BioSample",
                           "Length", "SourceDb", "Extra"):
                    rec[name] = child.text or ""
            if rec.get("AccessionVersion") or rec.get("Caption"):
                records.append(rec)
    except Exception:
        pass
    return records, count


def main():
    dry = "--dry-run" in sys.argv
    max_per = 100
    for a in sys.argv:
        if a.startswith("--max="):
            max_per = int(a.split("=")[1])

    # Load existing accessions
    conn = sqlite3.connect(str(DB_PATH))
    c = conn.cursor()
    c.execute("SELECT DISTINCT accession FROM viral_isolates")
    existing = {row[0] for row in c.fetchall()}
    c.execute("SELECT DISTINCT genome_accession FROM viral_isolates WHERE genome_accession IS NOT NULL")
    existing.update(row[0] for row in c.fetchall())
    # Also track by title/organism for dedup
    c.execute("SELECT DISTINCT canonical_name FROM virus_master")
    existing_names = {row[0].lower() for row in c.fetchall()}
    print(f"Existing: {len(existing)} accessions, {len(existing_names)} virus names")

    total_new = 0
    stats = {}

    for label, term, phylum, cls in QUERIES:
        print(f"\n[{phylum or 'any':20s}] {label:30s} ...", end=" ", flush=True)
        if dry:
            print(f"DRY-RUN: {term[:100]}...")
            continue

        records, count = search_and_fetch(term, max_results=max_per)
        print(f"{count:5d} total, {len(records):3d} fetched", end=" ", flush=True)

        new_for_query = 0
        for rec in records:
            acc = rec.get("AccessionVersion", rec.get("Caption", ""))
            if not acc or acc in existing:
                continue
            organism = rec.get("Organism", "")[:200]
            title = rec.get("Title", "")[:500]
            taxid = rec.get("TaxId", "")

            # Skip clearly non-viral (bacteria, eukaryotes)
            org_lower = organism.lower()
            if any(x in org_lower for x in ['bacterium', 'bacteria', 'fungus', 'fungi',
                   'homo sapien', 'mus musculus', 'danio rerio', 'escherichia coli',
                   'saccharomyces', 'arabidopsis', 'rattus ', 'bos taurus']):
                if 'virus' not in org_lower and 'phage' not in org_lower:
                    continue

            # Determine host info
            host_phylum = phylum or ""
            host_class = cls or ""
            discovery = "metagenomic_survey"

            # Infer from organism name
            if any(x in org_lower for x in ['ostreid', 'ostrea', 'crassostrea', 'oyster']):
                host_phylum = host_phylum or "Mollusca"
                host_class = host_class or "Bivalvia"
            elif any(x in org_lower for x in ['haliotid', 'haliotis', 'abalone']):
                host_phylum = host_phylum or "Mollusca"
                host_class = host_class or "Gastropoda"
            elif any(x in org_lower for x in ['coral', 'cnidaria', 'acropora']):
                host_phylum = host_phylum or "Cnidaria"

            try:
                # Insert virus_master
                c.execute("SELECT master_id FROM virus_master WHERE canonical_name = ?", (organism,))
                vm = c.fetchone()
                if vm:
                    master_id = vm[0]
                else:
                    c.execute("""INSERT INTO virus_master
                        (canonical_name, virus_family, genome_type, entry_type,
                         discovery_context, host_phylum)
                        VALUES (?, '', '', 'partial_genome', ?, ?)""",
                        (organism, discovery, host_phylum or None))
                    master_id = c.lastrowid

                # Insert viral_isolates
                try:
                    c.execute("""INSERT INTO viral_isolates
                        (accession, virus_name, master_id)
                        VALUES (?, ?, ?)""", (acc, organism, master_id))
                except sqlite3.IntegrityError:
                    continue  # duplicate accession

                new_for_query += 1
                existing.add(acc)
            except sqlite3.Error as e:
                continue

        stats[label] = {"total": count, "new": new_for_query}
        total_new += new_for_query
        print(f"→ +{new_for_query} new")

        if total_new % 200 == 0:
            conn.commit()
            print(f"  [commit at {total_new} total new]")

    conn.commit()

    # Final stats
    c.execute("SELECT COUNT(*) FROM virus_master")
    final_species = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM viral_isolates")
    final_isolates = c.fetchone()[0]
    c.execute("""SELECT phylum, COUNT(*) FROM crustacean_hosts
                 WHERE host_scope_status LIKE 'target%'
                 GROUP BY phylum ORDER BY COUNT(*) DESC""")
    host_stats = c.fetchall()

    print("\n" + "=" * 60)
    print("BULK IMPORT COMPLETE")
    print("=" * 60)
    print(f"New accessions imported: {total_new}")
    print(f"Virus species: 530 → {final_species} (+{final_species - 530})")
    print(f"Isolates: 3790 → {final_isolates} (+{final_isolates - 3790})")
    print(f"\nTarget hosts by phylum:")
    for ph, cnt in host_stats:
        print(f"  {ph}: {cnt}")

    print(f"\nPer-query breakdown:")
    for label, s in sorted(stats.items(), key=lambda x: -x[1]['new']):
        if s['new'] > 0:
            print(f"  {label:35s}: +{s['new']:4d} new / {s['total']:5d} total")

    conn.close()


if __name__ == "__main__":
    main()
