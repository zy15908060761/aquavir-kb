"""
Search NCBI SRA/GenBank/PubMed for crustacean virus sequences from under-represented taxa.
Uses NCBI E-utilities with rate limiting.
"""
import json
import sqlite3
import time
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from pathlib import Path
from datetime import datetime

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "crustacean_virus_core.db"

NCBI_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
RATE_LIMIT = 0.5  # seconds between requests

# Orders to search with their search terms
SEARCH_TARGETS = [
    # (order_name, genbank_search_term, priority)
    ("Copepoda", '("Copepoda"[host] OR "copepod"[All Fields]) AND virus[organism] AND 2022:2026[dp]', "high"),
    ("Amphipoda", '("Amphipoda"[host] OR "amphipod"[All Fields]) AND virus[organism] AND 2022:2026[dp]', "high"),
    ("Ostracoda", '("Ostracoda"[host] OR "ostracod"[All Fields]) AND virus[organism]', "high"),
    ("Isopoda", '("Isopoda"[host] OR "isopod"[All Fields]) AND virus[organism] AND 2022:2026[dp]', "high"),
    ("Cirripedia", '("Cirripedia"[host] OR "barnacle"[All Fields]) AND virus[organism]', "high"),
    ("Branchiopoda", '("Branchiopoda"[host] OR "Daphnia"[host] OR "Artemia"[host]) AND virus[organism] AND 2022:2026[dp]', "medium"),
    ("Euphausiacea", '("Euphausiacea"[host] OR "krill"[All Fields]) AND virus[organism]', "medium"),
    ("Stomatopoda", '("Stomatopoda"[host] OR "mantis shrimp"[All Fields]) AND virus[organism]', "medium"),
    # Broader virome searches
    ("crustacean_virome", '(crustacean virome) OR (shrimp virome) OR (crab virome) OR (crayfish virome) OR (lobster virome) AND 2023:2026[dp]', "high"),
    # DNA virus searches
    ("crustacean_dna_virus", '(crustacean[host]) AND (Nimaviridae OR Malacoherpesviridae OR Iridoviridae OR Parvoviridae OR Circoviridae OR Nudiviridae) AND 2020:2026[dp]', "medium"),
]

# SRA search terms
SRA_SEARCHES = [
    ('crustacean virome', '("crustacean virome" OR "shrimp virome" OR "crab virome" OR "crayfish virome" OR "copepod virome" OR "amphipod virome" OR "krill virome")'),
    ('crustacean metagenome', '("crustacean"[All Fields] AND "metagenome"[All Fields]) AND ("virus"[All Fields] OR "viral"[All Fields])'),
]

def ncbi_request(endpoint, params, db="nucleotide"):
    """Make a rate-limited NCBI E-utilities request."""
    params["db"] = db
    params["retmode"] = "xml"
    query_string = urllib.parse.urlencode(params)
    url = f"{NCBI_BASE}/{endpoint}?{query_string}"
    time.sleep(RATE_LIMIT)
    try:
        req = urllib.request.Request(url)
        req.add_header("User-Agent", "CrustaVirusDB/1.0")
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.read().decode("utf-8")
    except Exception as e:
        print(f"  ERROR: {e}")
        return None


def search_nucleotide(term, max_results=50):
    """Search GenBank Nucleotide, return list of accession IDs."""
    xml_str = ncbi_request("esearch.fcgi", {
        "term": term,
        "retmax": str(max_results),
        "sort": "relevance",
        "usehistory": "y",
    })
    if not xml_str:
        return [], 0
    try:
        root = ET.fromstring(xml_str)
        ids = [e.text for e in root.findall(".//Id")]
        count = root.findtext(".//Count") or "0"
        return ids, int(count)
    except Exception as e:
        print(f"  Parse error: {e}")
        return [], 0


def fetch_summaries(ids, db="nucleotide"):
    """Fetch document summaries for a list of IDs."""
    if not ids:
        return []
    xml_str = ncbi_request("esummary.fcgi", {
        "id": ",".join(ids[:50]),
    }, db=db)
    if not xml_str:
        return []
    results = []
    try:
        root = ET.fromstring(xml_str)
        for docsum in root.findall(".//DocSum"):
            item = {"id": docsum.findtext("Id")}
            for child in docsum.findall("Item"):
                name = child.get("Name")
                if name in ("Title", "Organism", "Caption", "AccessionVersion",
                           "CreateDate", "UpdateDate", "TaxId", "SRA_Sample",
                           "BioProject", "BioSample"):
                    item[name] = child.text or ""
            results.append(item)
    except Exception as e:
        print(f"  Summary parse error: {e}")
    return results


def search_sra(term, max_results=30):
    """Search SRA database."""
    ids, count = search_nucleotide(term.replace('"nucleotide"', '"sra"'))
    # Re-search with correct db
    xml_str = ncbi_request("esearch.fcgi", {
        "term": term,
        "retmax": str(max_results),
        "sort": "relevance",
    }, db="sra")
    if not xml_str:
        return [], 0
    try:
        root = ET.fromstring(xml_str)
        ids = [e.text for e in root.findall(".//Id")]
        count = int(root.findtext(".//Count") or "0")
        return ids, count
    except:
        return [], 0


def main():
    # Load existing accessions
    conn = sqlite3.connect(str(DB_PATH))
    c = conn.cursor()
    c.execute("SELECT DISTINCT accession FROM viral_isolates")
    existing = {row[0] for row in c.fetchall()}
    c.execute("SELECT DISTINCT genome_accession FROM viral_isolates WHERE genome_accession IS NOT NULL")
    existing.update(row[0] for row in c.fetchall())
    conn.close()
    print(f"Existing accessions loaded: {len(existing)}")

    worklist = {
        "generated_at": datetime.now().isoformat(),
        "new_virus_candidates": [],
        "new_host_taxa": [],
        "sra_projects": [],
        "summary": {},
    }
    total_candidates = 0
    new_orders_found = set()

    # 1. Search GenBank Nucleotide for each target
    print("\n=== Searching GenBank Nucleotide ===")
    for order_name, term, priority in SEARCH_TARGETS:
        print(f"\nSearching: {order_name} ({priority})")
        ids, count = search_nucleotide(term)
        print(f"  Found {count} results, fetching top {len(ids)} summaries...")

        if ids:
            summaries = fetch_summaries(ids[:30])
            for s in summaries:
                acc = s.get("AccessionVersion", s.get("Caption", ""))
                if acc in existing:
                    continue
                organism = s.get("Organism", "")
                title = s.get("Title", "")
                worklist["new_virus_candidates"].append({
                    "accession": acc,
                    "virus_name": organism,
                    "host_order": order_name,
                    "title": title[:200],
                    "priority": priority,
                    "source": "genbank",
                    "create_date": s.get("CreateDate", ""),
                    "taxid": s.get("TaxId", ""),
                })
                total_candidates += 1
                new_orders_found.add(order_name)
        print(f"  New candidates added: {len([c for c in worklist['new_virus_candidates'] if c['host_order'] == order_name])}")

    # 2. Search SRA for virome projects
    print("\n=== Searching SRA ===")
    for label, term in SRA_SEARCHES:
        print(f"\nSRA search: {label}")
        ids, count = search_sra(term)
        print(f"  Found {count} projects")
        if ids:
            summaries = fetch_summaries(ids[:20], db="sra")
            for s in summaries:
                worklist["sra_projects"].append({
                    "sra_id": s.get("id", ""),
                    "title": s.get("Title", ""),
                    "organism": s.get("Organism", ""),
                    "bioproject": s.get("BioProject", ""),
                    "search_term": label,
                })

    # 3. Summary
    worklist["summary"] = {
        "total_new_candidates": total_candidates,
        "new_orders_found": list(new_orders_found),
        "sra_projects_found": len(worklist["sra_projects"]),
        "search_targets_queried": len(SEARCH_TARGETS),
    }

    # Write output
    out_path = BASE_DIR / "expansion_worklist.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(worklist, f, indent=2, ensure_ascii=False)

    print("\n" + "=" * 60)
    print("SEARCH RESULTS SUMMARY")
    print("=" * 60)
    print(f"Total new virus candidates:    {total_candidates}")
    print(f"New host orders found:          {new_orders_found}")
    print(f"SRA projects identified:        {len(worklist['sra_projects'])}")
    print(f"\nWorklist written to: {out_path}")

    # Show top 10 candidates
    print("\nTop 10 new candidates:")
    for i, cand in enumerate(worklist["new_virus_candidates"][:10]):
        print(f"  {i+1}. {cand['accession']} - {cand['virus_name'][:80]} [{cand['host_order']}] ({cand['priority']})")


if __name__ == "__main__":
    main()
