#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Batch PubMed search for ALL 834 viruses in the database.
Uses checkpoint/resume to handle interruptions.
Strategies per virus:
  1. canonical_name[Title/Abstract]
  2. abbreviation[Title/Abstract] (if available)
  3. virus_family + host_phylum[Title/Abstract] (fallback)
"""

import csv
import json
import time
import urllib.request
import urllib.error
import ssl
import os
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
VIRUS_FILE = os.path.join(BASE_DIR, "downloads", "exports", "virus_master.tsv")
OUT_DIR = os.path.join(BASE_DIR, "downloads", "literature_all_viruses_search")
CHECKPOINT_FILE = os.path.join(OUT_DIR, "search_checkpoint.json")
RESULTS_FILE = os.path.join(OUT_DIR, "all_virus_pmids.json")
SUMMARY_FILE = os.path.join(OUT_DIR, "search_summary.json")

os.makedirs(OUT_DIR, exist_ok=True)

NCBI_ESearch = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
NCBI_EFetch = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
EMAIL = "research@example.com"
TOOL = "aquatic_virus_db"

# SSL context that ignores verification (to handle UNEXPECTED_EOF errors)
ssl_context = ssl.create_default_context()
ssl_context.check_hostname = False
ssl_context.verify_mode = ssl.CERT_NONE


def load_viruses():
    viruses = []
    with open(VIRUS_FILE, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            viruses.append(row)
    return viruses


def esearch(query, retmax=500):
    """Run PubMed esearch and return list of PMIDs."""
    url = (
        f"{NCBI_ESearch}?db=pubmed&term={urllib.parse.quote(query)}"
        f"&retmode=json&retmax={retmax}&email={EMAIL}&tool={TOOL}"
    )
    max_retries = 3
    for attempt in range(max_retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": TOOL})
            with urllib.request.urlopen(req, timeout=30, context=ssl_context) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            pmids = data.get("esearchresult", {}).get("idlist", [])
            return pmids
        except Exception as e:
            wait = 2 ** attempt
            print(f"  [Retry {attempt+1}/{max_retries}] {e} (sleep {wait}s)")
            time.sleep(wait)
    return []


def efetch_metadata(pmids):
    """Fetch metadata for a list of PMIDs (batch)."""
    if not pmids:
        return []
    pmid_str = ",".join(pmids)
    url = (
        f"{NCBI_EFetch}?db=pubmed&id={pmid_str}"
        f"&retmode=xml&email={EMAIL}&tool={TOOL}"
    )
    max_retries = 3
    for attempt in range(max_retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": TOOL})
            with urllib.request.urlopen(req, timeout=60, context=ssl_context) as resp:
                xml_data = resp.read().decode("utf-8")
            # Basic XML parsing to extract title, year, DOI
            import xml.etree.ElementTree as ET
            root = ET.fromstring(xml_data)
            articles = []
            for article in root.findall(".//PubmedArticle"):
                pmid_el = article.find(".//PMID")
                pmid = pmid_el.text if pmid_el is not None else ""
                title_el = article.find(".//ArticleTitle")
                title = title_el.text if title_el is not None else ""
                year_el = article.find(".//PubDate/Year")
                year = year_el.text if year_el is not None else ""
                doi_el = article.find(".//ArticleId[@IdType='doi']")
                doi = doi_el.text if doi_el is not None else ""
                pmc_el = article.find(".//ArticleId[@IdType='pmc']")
                pmc_id = pmc_el.text if pmc_el is not None else ""
                articles.append({
                    "pmid": pmid,
                    "title": title,
                    "year": year,
                    "doi": doi,
                    "pmc_id": pmc_id,
                })
            return articles
        except Exception as e:
            wait = 2 ** attempt
            print(f"  [EFetch Retry {attempt+1}/{max_retries}] {e} (sleep {wait}s)")
            time.sleep(wait)
    return []


def load_checkpoint():
    if os.path.exists(CHECKPOINT_FILE):
        with open(CHECKPOINT_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"completed": [], "results": {}}


def save_checkpoint(cp):
    with open(CHECKPOINT_FILE, "w", encoding="utf-8") as f:
        json.dump(cp, f, ensure_ascii=False, indent=2)


def build_queries(virus):
    queries = []
    name = virus.get("canonical_name", "").strip()
    abbr = virus.get("abbreviations", "").strip()
    family = virus.get("virus_family", "").strip()
    host = virus.get("host_phylum", "").strip().lower()
    
    if name:
        queries.append((f'{name}[Title/Abstract]', "name"))
    if abbr and abbr != name and len(abbr) > 2:
        # Avoid very short abbreviations
        queries.append((f'{abbr}[Title/Abstract]', "abbr"))
    if family and host:
        queries.append((f'{family}[Title/Abstract] AND {host}[Title/Abstract]', "family_host"))
    return queries


def main():
    viruses = load_viruses()
    total = len(viruses)
    print(f"[{datetime.now()}] Loaded {total} viruses. Starting batch search...")
    
    cp = load_checkpoint()
    completed = set(cp.get("completed", []))
    results = cp.get("results", {})
    
    for idx, virus in enumerate(viruses):
        vid = virus.get("master_id", str(idx))
        if vid in completed:
            print(f"[{idx+1}/{total}] SKIP (already done): {virus.get('canonical_name')}")
            continue
        
        name = virus.get("canonical_name", "")
        print(f"[{idx+1}/{total}] Searching: {name}")
        
        virus_results = {
            "virus_name": name,
            "master_id": vid,
            "queries": {},
            "all_pmids": [],
            "articles": []
        }
        
        queries = build_queries(virus)
        all_pmids = set()
        
        for qtext, qtype in queries:
            print(f"  Query [{qtype}]: {qtext[:80]}...")
            pmids = esearch(qtext)
            time.sleep(0.35)  # rate limit
            virus_results["queries"][qtype] = {
                "query": qtext,
                "pmids": pmids,
                "count": len(pmids)
            }
            all_pmids.update(pmids)
            if pmids:
                print(f"    -> Found {len(pmids)} PMIDs")
        
        virus_results["all_pmids"] = sorted(list(all_pmids))
        
        # Batch fetch metadata (max 200 at a time to avoid URL too long)
        pmid_list = virus_results["all_pmids"]
        articles = []
        for i in range(0, len(pmid_list), 200):
            batch = pmid_list[i:i+200]
            batch_articles = efetch_metadata(batch)
            articles.extend(batch_articles)
            time.sleep(0.35)
        
        virus_results["articles"] = articles
        virus_results["article_count"] = len(articles)
        results[vid] = virus_results
        
        completed.add(vid)
        cp["completed"] = sorted(list(completed))
        cp["results"] = results
        
        if (idx + 1) % 10 == 0:
            save_checkpoint(cp)
            print(f"  [Checkpoint saved] {len(completed)}/{total} done")
        
        time.sleep(0.35)
    
    save_checkpoint(cp)
    
    # Write final JSON
    with open(RESULTS_FILE, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    
    # Summary
    summary = {
        "total_viruses": total,
        "searched": len(completed),
        "viruses_with_pmids": sum(1 for v in results.values() if v.get("all_pmids")),
        "total_unique_pmids": len(set(pmid for v in results.values() for pmid in v.get("all_pmids", []))),
        "timestamp": datetime.now().isoformat()
    }
    with open(SUMMARY_FILE, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    
    print(f"\n[{datetime.now()}] DONE!")
    print(f"Summary: {summary}")


if __name__ == "__main__":
    main()
