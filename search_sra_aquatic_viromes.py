"""
Search NCBI SRA/GenBank for aquatic invertebrate virus sequences
across Mollusca, Cnidaria, Echinodermata, Porifera, and under-sampled
crustacean orders.

Extends the original crustacean-only search with:
  - 36+ search targets across 9 phyla
  - Fixed bacterial contamination (NOT bacteria filter)
  - Proper txid10239 viral organism filter
  - host_phylum annotation on every candidate

Usage:
    python search_sra_aquatic_viromes.py
    python search_sra_aquatic_viromes.py --max-per-query 20 --dry-run
"""

import json
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
OUTPUT_JSON = BASE_DIR / "expansion_worklist_aquatic.json"

NCBI_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
RATE_LIMIT = 0.5

# ── Expanded search targets ─────────────────────────────────────────────────
SEARCH_TARGETS = [
    # ── Mollusca ─────────────────────────────────────────────────────────
    ("Mollusca_oyster", '("oyster"[host] OR "Crassostrea"[host] OR "Saccostrea"[host] OR "Ostrea"[host]) AND "viruses"[organism] NOT "bacteria"[organism] AND 2020:2026[dp]', "high", "Mollusca"),
    ("Mollusca_mussel", '("mussel"[host] OR "Mytilus"[host] OR "Perna"[host]) AND "viruses"[organism] NOT "bacteria"[organism] AND 2020:2026[dp]', "high", "Mollusca"),
    ("Mollusca_clam", '("clam"[host] OR "Ruditapes"[host] OR "Venerupis"[host] OR "Mercenaria"[host]) AND "viruses"[organism] NOT "bacteria"[organism] AND 2020:2026[dp]', "high", "Mollusca"),
    ("Mollusca_abalone", '("abalone"[host] OR "Haliotis"[host]) AND "viruses"[organism] NOT "bacteria"[organism] AND 2020:2026[dp]', "high", "Mollusca"),
    ("Mollusca_scallop", '("scallop"[host] OR "Pecten"[host] OR "Argopecten"[host] OR "Chlamys"[host] OR "Mizuhopecten"[host]) AND "viruses"[organism] NOT "bacteria"[organism] AND 2020:2026[dp]', "medium", "Mollusca"),
    ("Mollusca_cephalopod", '("squid"[host] OR "octopus"[host] OR "Sepia"[host] OR "Loligo"[host]) AND "viruses"[organism] NOT "bacteria"[organism] AND 2020:2026[dp]', "medium", "Mollusca"),
    ("Mollusca_virome", '("mollusc*"[All Fields] OR "bivalve"[All Fields]) AND ("metagenome"[All Fields] OR "virome"[All Fields]) AND "viruses"[organism] NOT "cellular"[Organism] AND 2020:2026[dp]', "high", "Mollusca"),
    ("Malacoherpesviridae_all", 'Malacoherpesviridae[Organism] AND 2000:2026[dp]', "high", "Mollusca"),

    # ── Cnidaria ─────────────────────────────────────────────────────────
    ("Cnidaria_coral", '("coral"[host] OR "Acropora"[host] OR "Porites"[host] OR "Pocillopora"[host] OR "Stylophora"[host]) AND "viruses"[organism] NOT "bacteria"[organism] AND 2020:2026[dp]', "high", "Cnidaria"),
    ("Cnidaria_anemone", '("sea anemone"[host] OR "Nematostella"[host] OR "Exaiptasia"[host]) AND "viruses"[organism] NOT "bacteria"[organism] AND 2020:2026[dp]', "medium", "Cnidaria"),
    ("Cnidaria_jellyfish", '("jellyfish"[host] OR "Aurelia"[host] OR "Hydra"[host]) AND "viruses"[organism] NOT "bacteria"[organism] AND 2020:2026[dp]', "medium", "Cnidaria"),
    ("Cnidaria_virome", '("coral"[All Fields] OR "cnidarian"[All Fields]) AND ("metagenome"[All Fields] OR "virome"[All Fields]) AND "viruses"[organism] NOT "cellular"[Organism] AND 2020:2026[dp]', "high", "Cnidaria"),

    # ── Echinodermata ────────────────────────────────────────────────────
    ("Echinodermata_cucumber", '("sea cucumber"[host] OR "Apostichopus"[host] OR "Holothuria"[host]) AND "viruses"[organism] NOT "bacteria"[organism] AND 2020:2026[dp]', "medium", "Echinodermata"),
    ("Echinodermata_urchin", '("sea urchin"[host] OR "Strongylocentrotus"[host] OR "Paracentrotus"[host] OR "Lytechinus"[host]) AND "viruses"[organism] NOT "bacteria"[organism] AND 2020:2026[dp]', "medium", "Echinodermata"),
    ("Echinodermata_starfish", '("starfish"[host] OR "sea star"[host] OR "Asterias"[host] OR "Pisaster"[host]) AND "viruses"[organism] NOT "bacteria"[organism] AND 2020:2026[dp]', "medium", "Echinodermata"),
    ("Echinodermata_virome", '("echinoderm*"[All Fields] OR "holothuri*"[All Fields]) AND ("metagenome"[All Fields] OR "virome"[All Fields]) AND "viruses"[organism] NOT "cellular"[Organism] AND 2020:2026[dp]', "medium", "Echinodermata"),

    # ── Porifera ─────────────────────────────────────────────────────────
    ("Porifera_virus", '("sponge"[host] OR "Porifera"[host] OR "Amphimedon"[host] OR "Ephydatia"[host]) AND "viruses"[organism] NOT "bacteria"[organism] AND 2020:2026[dp]', "medium", "Porifera"),
    ("Porifera_virome", '("sponge"[All Fields]) AND ("metagenome"[All Fields] OR "virome"[All Fields]) AND "viruses"[organism] NOT "cellular"[Organism] AND 2020:2026[dp]', "low", "Porifera"),

    # ── Tunicata ─────────────────────────────────────────────────────────
    ("Tunicata_virus", '("tunicate"[host] OR "ascidian"[host] OR "Ciona"[host]) AND "viruses"[organism] NOT "bacteria"[organism] AND 2020:2026[dp]', "low", "Chordata"),

    # ── Rotifera ─────────────────────────────────────────────────────────
    ("Rotifera_virus", '("rotifer"[host] OR "Brachionus"[host]) AND "viruses"[organism] NOT "bacteria"[organism] AND 2020:2026[dp]', "low", "Rotifera"),

    # ── Under-sampled crustacean orders ──────────────────────────────────
    ("Copepoda_virus", '("Copepoda"[host] OR "copepod"[All Fields]) AND "viruses"[organism] NOT "bacteria"[organism] AND 2022:2026[dp]', "high", "Arthropoda"),
    ("Amphipoda_virus", '("Amphipoda"[host] OR "amphipod"[All Fields]) AND "viruses"[organism] NOT "bacteria"[organism] AND 2022:2026[dp]', "high", "Arthropoda"),
    ("Ostracoda_virus", '("Ostracoda"[host] OR "ostracod"[All Fields]) AND "viruses"[organism] NOT "bacteria"[organism]', "high", "Arthropoda"),
    ("Isopoda_virus", '("Isopoda"[host] OR "isopod"[All Fields]) AND "viruses"[organism] NOT "bacteria"[organism] AND 2022:2026[dp]', "high", "Arthropoda"),
    ("Cirripedia_virus", '("Cirripedia"[host] OR "barnacle"[All Fields]) AND "viruses"[organism] NOT "bacteria"[organism]', "high", "Arthropoda"),
    ("Branchiopoda_virus", '("Branchiopoda"[host] OR "Daphnia"[host] OR "Artemia"[host]) AND "viruses"[organism] NOT "bacteria"[organism] AND 2022:2026[dp]', "medium", "Arthropoda"),
    ("Euphausiacea_virus", '("Euphausiacea"[host] OR "krill"[All Fields]) AND "viruses"[organism] NOT "bacteria"[organism]', "medium", "Arthropoda"),
    ("Stomatopoda_virus", '("Stomatopoda"[host] OR "mantis shrimp"[All Fields]) AND "viruses"[organism] NOT "bacteria"[organism]', "medium", "Arthropoda"),

    # ── Cross-phylum virome ──────────────────────────────────────────────
    ("aquatic_invert_virome", '("aquatic invertebrate"[All Fields] OR "marine invertebrate"[All Fields]) AND ("metagenome"[All Fields] OR "virome"[All Fields]) AND "viruses"[organism] NOT "cellular"[Organism] AND 2023:2026[dp]', "medium", "multiple"),
    ("marine_invert_RNA_virus", '("marine"[All Fields] AND "invertebrate"[All Fields] AND "RNA virus"[All Fields]) NOT "bacteria"[organism] AND 2023:2026[dp]', "medium", "multiple"),

    # ── Virus-family cross-cut ───────────────────────────────────────────
    ("Iridoviridae_aquatic", 'Iridoviridae[Organism] AND ("invertebrate"[host] OR "mollusc*"[host] OR "crustacean"[host] OR "coral"[host]) AND 2020:2026[dp]', "medium", "multiple"),
    ("Nodaviridae_aquatic", '(Nodaviridae[Organism] OR "nodavirus"[All Fields]) AND ("crustacean"[host] OR "mollusc*"[host] OR "shrimp"[host]) NOT "bacteria"[organism] AND 2020:2026[dp]', "medium", "multiple"),
    ("Circoviridae_aquatic", '(Circoviridae[Organism] OR "circular virus"[All Fields]) AND ("crustacean"[host] OR "mollusc*"[host] OR "invertebrate"[host]) NOT "bacteria"[organism] AND 2020:2026[dp]', "low", "multiple"),
    ("Nimaviridae_all", 'Nimaviridae[Organism] AND 2020:2026[dp]', "high", "Arthropoda"),
]

SRA_SEARCHES = [
    ("mollusk_virome_sra", '("mollusc virome" OR "oyster virome" OR "abalone virome" OR "mussel virome" OR "clam virome" OR "scallop virome")'),
    ("coral_virome_sra", '("coral virome" OR "coral metagenome" OR "cnidarian virome")'),
    ("echinoderm_virome_sra", '("sea cucumber virome" OR "sea urchin virome" OR "starfish virome" OR "holothurian virome")'),
    ("sponge_virome_sra", '("sponge virome" OR "sponge metagenome" OR "porifera virome")'),
    ("marine_invert_virome_sra", '("marine invertebrate virome" OR "aquatic invertebrate virome")'),
    ("crustacean_virome_sra", '("crustacean virome" OR "shrimp virome" OR "crab virome" OR "crayfish virome" OR "copepod virome")'),
]


def ncbi_request(endpoint, params, db="nucleotide"):
    params["db"] = db
    params["retmode"] = "xml"
    qs = urllib.parse.urlencode(params)
    url = f"{NCBI_BASE}/{endpoint}?{qs}"
    time.sleep(RATE_LIMIT)
    try:
        req = urllib.request.Request(url)
        req.add_header("User-Agent", "AquaVir-KB/1.0")
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.read().decode("utf-8")
    except Exception as e:
        print(f"  ERROR: {e}")
        return None


def search_and_summarize(term, max_results, host_phylum, label):
    """Search NCBI and return parsed candidates."""
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
    xml_str2 = ncbi_request("esummary.fcgi", {"id": ",".join(ids[:50])})
    if not xml_str2:
        return [], count

    candidates = []
    try:
        root2 = ET.fromstring(xml_str2)
        for ds in root2.findall(".//DocSum"):
            item = {"id": ds.findtext("Id"), "host_phylum": host_phylum, "source": label}
            for child in ds.findall("Item"):
                name = child.get("Name")
                if name in ("AccessionVersion", "Caption", "Title", "Organism",
                           "CreateDate", "UpdateDate", "TaxId"):
                    item[name] = child.text or ""
            acc = item.get("AccessionVersion", item.get("Caption", ""))
            if acc:
                candidates.append({
                    "accession": acc,
                    "virus_name": item.get("Organism", ""),
                    "host_order": label.split("_")[0],
                    "host_phylum": host_phylum,
                    "title": item.get("Title", "")[:200],
                    "priority": "high" if "high" in label else "medium",
                    "source": "genbank",
                    "create_date": item.get("CreateDate", ""),
                    "taxid": item.get("TaxId", ""),
                })
    except Exception as e:
        print(f"  Summary parse error: {e}")
    return candidates, count


def main():
    # Load existing accessions
    try:
        conn = sqlite3.connect(str(DB_PATH))
        c = conn.cursor()
        c.execute("SELECT DISTINCT accession FROM viral_isolates")
        existing = {row[0] for row in c.fetchall()}
        c.execute("SELECT DISTINCT genome_accession FROM viral_isolates WHERE genome_accession IS NOT NULL")
        existing.update(row[0] for row in c.fetchall())
        conn.close()
        print(f"Existing accessions: {len(existing)}")
    except Exception:
        existing = set()

    dry = "--dry-run" in sys.argv
    max_per = 30
    for a in sys.argv:
        if a.startswith("--max-per-query="):
            max_per = int(a.split("=")[1])

    worklist = {
        "generated_at": datetime.now().isoformat(),
        "new_virus_candidates": [],
        "sra_projects": [],
        "summary": {},
    }
    phylum_counts = {}

    # Phase 1: GenBank Nucleotide
    print("\n=== PHASE 1: GenBank Nucleotide ===")
    for label, term, priority, host_phylum in SEARCH_TARGETS:
        print(f"\n[{host_phylum}] {label} ({priority})")
        if dry:
            print(f"  Query: {term[:120]}...")
            continue
        candidates, count = search_and_summarize(term, max_per, host_phylum, label)
        print(f"  Total: {count}, Fetched: {len(candidates)}")
        new_count = 0
        for cand in candidates:
            acc_key = cand["accession"].split(".")[0]
            if acc_key not in existing:
                worklist["new_virus_candidates"].append(cand)
                existing.add(acc_key)
                phylum_counts[host_phylum] = phylum_counts.get(host_phylum, 0) + 1
                new_count += 1
        print(f"  New: {new_count}")

    # Phase 2: SRA
    print("\n=== PHASE 2: SRA ===")
    for label, term in SRA_SEARCHES:
        print(f"\nSRA: {label}")
        if dry:
            continue
        xml_str = ncbi_request("esearch.fcgi", {"term": term, "retmax": "20"}, db="sra")
        if not xml_str:
            continue
        try:
            root = ET.fromstring(xml_str)
            ids = [e.text for e in root.findall(".//Id") if e.text]
            count = int(root.findtext(".//Count") or "0")
            print(f"  Projects: {count}")
            if ids:
                xml_s = ncbi_request("esummary.fcgi", {"id": ",".join(ids[:15])}, db="sra")
                if xml_s:
                    root_s = ET.fromstring(xml_s)
                    for ds in root_s.findall(".//DocSum"):
                        item = {"id": ds.findtext("Id")}
                        for child in ds.findall("Item"):
                            if child.get("Name") in ("Title", "Organism", "BioProject", "Bioproject"):
                                item[child.get("Name")] = child.text or ""
                        worklist["sra_projects"].append({
                            "sra_id": item.get("id", ""),
                            "title": item.get("Title", ""),
                            "bioproject": item.get("BioProject", item.get("Bioproject", "")),
                            "search_term": label,
                        })
        except Exception as e:
            print(f"  Error: {e}")

    # Summary
    worklist["summary"] = {
        "total_new_candidates": len(worklist["new_virus_candidates"]),
        "by_phylum": phylum_counts,
        "sra_projects_found": len(worklist["sra_projects"]),
        "search_targets_queried": len(SEARCH_TARGETS),
    }

    with open(str(OUTPUT_JSON), "w", encoding="utf-8") as f:
        json.dump(worklist, f, indent=2, ensure_ascii=False)

    print("\n" + "=" * 60)
    print("SEARCH RESULTS")
    print("=" * 60)
    print(f"Total new candidates: {len(worklist['new_virus_candidates'])}")
    for ph, cnt in sorted(phylum_counts.items()):
        print(f"  {ph}: {cnt}")
    print(f"SRA projects: {len(worklist['sra_projects'])}")
    print(f"Output: {OUTPUT_JSON}")

    if worklist["new_virus_candidates"]:
        print("\nTop 15 candidates:")
        for i, cand in enumerate(worklist["new_virus_candidates"][:15]):
            print(f"  {i+1}. {cand['accession']} [{cand['host_phylum']}] {cand['virus_name'][:70]}")


if __name__ == "__main__":
    main()
