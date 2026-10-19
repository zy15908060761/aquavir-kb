#!/usr/bin/env python3
"""
Targeted PubMed search for P0 crustacean virus virulence/thermal evidence.
Outputs: search_matrix.csv (input plan) + pmid_results.csv (retrieved PMIDs with metadata)
"""

import csv
import json
import time
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from pathlib import Path

USER_AGENT = "crustacean-db-curator/1.0 (mailto:your_email@institution.edu)"
RATE_LIMIT = 0.35  # seconds between requests (no API key)

OUT_DIR = Path(r"F:\甲壳动物数据库\literature_curation_v2")
OUT_DIR.mkdir(parents=True, exist_ok=True)

# P0 viruses with high likelihood of experimental data
# Format: (canonical_name, abbreviations, family, priority_override_note)
TARGET_VIRUSES = [
    ("White spot syndrome virus", "WSSV", "Nimaviridae", ""),
    ("Taura syndrome virus", "TSV", "Aparvoviridae", ""),
    ("Infectious hypodermal and hematopoietic necrosis virus", "IHHNV", "Parvoviridae", ""),
    ("Yellow head virus", "YHV", "Roniviridae", ""),
    ("Macrobrachium rosenbergii nodavirus", "MrNV", "Nodaviridae", ""),
    ("Infectious myonecrosis virus", "IMNV", "Totiviridae", ""),
    ("Scylla serrata reovirus SZ-2007", "", "Sedoreoviridae", ""),
    ("Covert mortality nodavirus", "CMNV", "Nodaviridae", "P1 but economically critical"),
    ("Decapod iridescent virus", "DIV1", "Iridoviridae", "P1 but economically critical"),
    ("Laem-Singh virus", "", "", "P0; mostly detection literature, low expectation"),
    ("Crab associated circular virus", "", "Circoviridae", "P0; mostly metagenomic, low expectation"),
    ("Wenzhou shrimp virus", "", "", "P0; metagenomic discovery, low expectation"),
    ("Beihai crab virus", "", "", "P0; metagenomic discovery, low expectation"),
    ("Beihai shrimp virus", "", "", "P0; metagenomic discovery, low expectation"),
    ("Macrobrachium rosenbergii Golda virus", "", "", "P0; metagenomic discovery, low expectation"),
]

SEARCH_CONFIGS = [
    {
        "field": "virulence",
        "template": '{name}[Title/Abstract] AND (shrimp[Title/Abstract] OR crustacean[Title/Abstract] OR prawn[Title/Abstract] OR crab[Title/Abstract] OR crayfish[Title/Abstract] OR Macrobrachium[Title/Abstract] OR Penaeus[Title/Abstract] OR Scylla[Title/Abstract]) AND (mortality[Title/Abstract] OR pathogenicity[Title/Abstract] OR virulence[Title/Abstract] OR LD50[Title/Abstract] OR "cumulative mortality"[Title/Abstract] OR "lethal dose"[Title/Abstract])',
    },
    {
        "field": "thermal",
        "template": '{name}[Title/Abstract] AND (shrimp[Title/Abstract] OR crustacean[Title/Abstract] OR prawn[Title/Abstract] OR crab[Title/Abstract] OR crayfish[Title/Abstract] OR Macrobrachium[Title/Abstract] OR Penaeus[Title/Abstract] OR Scylla[Title/Abstract]) AND (temperature[Title/Abstract] OR thermal[Title/Abstract] OR "heat inactivation"[Title/Abstract] OR "cold storage"[Title/Abstract] OR "optimal temperature"[Title/Abstract] OR "thermal stability"[Title/Abstract] OR "thermal inactivation"[Title/Abstract])',
    },
]


def esearch(query, retmax=200):
    url = (
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
        f"?db=pubmed&term={urllib.parse.quote(query)}"
        f"&retmax={retmax}&retmode=json"
    )
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data.get("esearchresult", {}).get("idlist", [])
    except Exception as exc:
        print(f"    [ESEARCH ERROR] {exc}")
        return []


def esummary(pmids):
    if not pmids:
        return []
    ids = ",".join(pmids)
    url = (
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"
        f"?db=pubmed&id={ids}&retmode=json"
    )
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data.get("result", {})
    except Exception as exc:
        print(f"    [ESUMMARY ERROR] {exc}")
        return {}


def check_pmc_oa(pmids):
    """Batch check PMC OA status via E-utilities elink (pmc -> pubmed)."""
    if not pmids:
        return {}
    # Use ELink to find PMC IDs for PMIDs
    ids = ",".join(pmids)
    url = (
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/elink.fcgi"
        f"?dbfrom=pubmed&db=pmc&linkname=pubmed_pmc&id={ids}&retmode=json"
    )
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        pmid_to_pmc = {}
        for linkset in data.get("linksets", []):
            pmid = linkset.get("ids", [{}])[0].get("value", "")
            for link in linkset.get("linksetdbs", []):
                if link.get("dbto") == "pmc":
                    pmc_ids = link.get("links", [])
                    if pmc_ids:
                        pmid_to_pmc[pmid] = str(pmc_ids[0])
        return pmid_to_pmc
    except Exception as exc:
        print(f"    [ELINK ERROR] {exc}")
        return {}


def main():
    print("=" * 70)
    print("Targeted PubMed Search: P0 Virus Virulence & Thermal Evidence")
    print("=" * 70)

    # Write search matrix
    matrix_path = OUT_DIR / "search_matrix.csv"
    with open(matrix_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["virus_name", "abbreviation", "family", "field", "pubmed_query", "pmid_count", "note"])
        for name, abbr, fam, note in TARGET_VIRUSES:
            for cfg in SEARCH_CONFIGS:
                q = cfg["template"].format(name=name)
                writer.writerow([name, abbr, fam, cfg["field"], q, "", note])
    print(f"[1] Search matrix written: {matrix_path}")

    # Execute searches
    all_pmids = set()
    virus_field_pmids = {}  # (name, field) -> [pmids]

    for name, abbr, fam, note in TARGET_VIRUSES:
        print(f"\nSearching: {name}")
        for cfg in SEARCH_CONFIGS:
            field = cfg["field"]
            q = cfg["template"].format(name=name)
            pmids = esearch(q, retmax=200)
            virus_field_pmids[(name, field)] = pmids
            all_pmids.update(pmids)
            print(f"  {field}: {len(pmids)} PMIDs")
            time.sleep(RATE_LIMIT)

    print(f"\n[2] Total unique PMIDs retrieved: {len(all_pmids)}")

    # Fetch metadata in batches of 200
    pmid_list = sorted(all_pmids)
    summary_data = {}
    for i in range(0, len(pmid_list), 200):
        batch = pmid_list[i:i+200]
        result = esummary(batch)
        for pmid in batch:
            if pmid in result and pmid != "uids":
                summary_data[pmid] = result[pmid]
        time.sleep(RATE_LIMIT)

    # Check PMC OA status in batches
    pmc_map = {}
    for i in range(0, len(pmid_list), 200):
        batch = pmid_list[i:i+200]
        partial = check_pmc_oa(batch)
        pmc_map.update(partial)
        time.sleep(RATE_LIMIT)

    # Build per-PMID virus-field mapping for deduplication tracking
    pmid_to_sources = {}
    for (name, field), pmids in virus_field_pmids.items():
        for pmid in pmids:
            pmid_to_sources.setdefault(pmid, []).append(f"{name}:{field}")

    # Write results
    results_path = OUT_DIR / "pmid_results.csv"
    with open(results_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow([
            "pmid", "title", "authors", "source", "pubdate", "pubyear",
            "doi", "pmc_id", "is_pmc_oa",
            "matched_viruses", "matched_fields", "n_sources",
            "download_status", "fulltext_path", "extraction_status", "notes"
        ])
        for pmid in pmid_list:
            info = summary_data.get(pmid, {})
            title = info.get("title", "")
            authors = "; ".join([a.get("name", "") for a in info.get("authors", [])[:5]])
            source = info.get("source", "")
            pubdate = info.get("pubdate", "")
            pubyear = pubdate[:4] if pubdate else ""
            doi = ""
            for articleid in info.get("articleids", []):
                if articleid.get("idtype") == "doi":
                    doi = articleid.get("value", "")
            pmc_id = pmc_map.get(pmid, "")
            is_oa = "YES" if pmc_id else "NO"
            sources = pmid_to_sources.get(pmid, [])
            matched_viruses = "|".join(sorted(set(s.split(":")[0] for s in sources)))
            matched_fields = "|".join(sorted(set(s.split(":")[1] for s in sources)))
            writer.writerow([
                pmid, title, authors, source, pubdate, pubyear, doi,
                pmc_id, is_oa, matched_viruses, matched_fields, len(sources),
                "pending", "", "pending", ""
            ])

    print(f"[3] PMID results written: {results_path}")

    # Summary stats
    print("\n[4] Summary:")
    for name, abbr, fam, note in TARGET_VIRUSES:
        v_pmids = set(virus_field_pmids.get((name, "virulence"), []))
        t_pmids = set(virus_field_pmids.get((name, "thermal"), []))
        union = v_pmids | t_pmids
        oa_count = sum(1 for p in union if p in pmc_map)
        print(f"  {name:55s} | virulence={len(v_pmids):3d} | thermal={len(t_pmids):3d} | OA={oa_count:3d}")

    print("\nDone. Next step: open pmid_results.csv and sort by is_pmc_oa=YES + pubyear descending.")
    print("Download OA papers first, then tackle non-OA via institutional access.")


if __name__ == "__main__":
    main()
