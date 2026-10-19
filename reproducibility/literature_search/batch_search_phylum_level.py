#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Phylum-level broad PubMed search for uncovered Mollusca, Cnidaria,
Echinodermata, and Porifera viruses.
Uses conservative rate limits to avoid conflicting with main PubMed search.
"""

import csv
import json
import time
import urllib.request
import urllib.parse
import ssl
import os
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(BASE_DIR, "downloads", "literature_all_viruses_search", "phylum_search")
os.makedirs(OUT_DIR, exist_ok=True)

NCBI_ESearch = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
NCBI_EFetch = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
EMAIL = "research@example.com"
TOOL = "aquatic_virus_db_phylum"

ssl_context = ssl.create_default_context()
ssl_context.check_hostname = False
ssl_context.verify_mode = ssl.CERT_NONE

# Phylum search queries
PHYLA_QUERIES = {
    "Mollusca": [
        '(abalone[Title/Abstract] OR oyster[Title/Abstract] OR mussel[Title/Abstract] OR clam[Title/Abstract] OR scallop[Title/Abstract] OR mollus*[Title/Abstract] OR haliotis[Title/Abstract] OR crassostrea[Title/Abstract] OR mytilus[Title/Abstract] OR pinctada[Title/Abstract]) AND (virus[Title/Abstract] OR herpesvirus[Title/Abstract] OR pathogen[Title/Abstract])',
        'Malacoherpesviridae[Title/Abstract]',
        'osHV[Title/Abstract] OR \u201cohv[Title/Abstract] OR \u2018ohv[Title/Abstract]',
    ],
    "Cnidaria": [
        '(coral[Title/Abstract] OR cnidaria[Title/Abstract] OR jellyfish[Title/Abstract] OR sea anemone[Title/Abstract] OR nematostella[Title/Abstract] OR hydra[Title/Abstract]) AND virus[Title/Abstract]',
        '(coral[Title/Abstract] OR reef[Title/Abstract]) AND (virome[Title/Abstract] OR viral[Title/Abstract])',
    ],
    "Echinodermata": [
        '(sea urchin[Title/Abstract] OR starfish[Title/Abstract] OR echinoderm[Title/Abstract] OR asteroid[Title/Abstract]) AND virus[Title/Abstract]',
    ],
    "Porifera": [
        '(sponge[Title/Abstract] OR porifera[Title/Abstract] OR poriferan[Title/Abstract]) AND virus[Title/Abstract]',
        '(marine sponge[Title/Abstract]) AND (virome[Title/Abstract] OR viral[Title/Abstract])',
    ],
}


def esearch(query, retmax=500):
    url = f"{NCBI_ESearch}?db=pubmed&term={urllib.parse.quote(query)}&retmode=json&retmax={retmax}&email={EMAIL}&tool={TOOL}"
    max_retries = 3
    for attempt in range(max_retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": TOOL})
            with urllib.request.urlopen(req, timeout=30, context=ssl_context) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            return data.get("esearchresult", {}).get("idlist", [])
        except Exception as e:
            wait = 2 ** attempt
            print(f"    [Retry {attempt+1}/{max_retries}] {e} (sleep {wait}s)")
            time.sleep(wait)
    return []


def efetch_metadata(pmids):
    if not pmids:
        return []
    pmid_str = ",".join(pmids)
    url = f"{NCBI_EFetch}?db=pubmed&id={pmid_str}&retmode=xml&email={EMAIL}&tool={TOOL}"
    max_retries = 3
    for attempt in range(max_retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": TOOL})
            with urllib.request.urlopen(req, timeout=60, context=ssl_context) as resp:
                xml_data = resp.read().decode("utf-8")
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
                articles.append({"pmid": pmid, "title": title, "year": year, "doi": doi, "pmc_id": pmc_id})
            return articles
        except Exception as e:
            wait = 2 ** attempt
            print(f"    [EFetch Retry {attempt+1}/{max_retries}] {e} (sleep {wait}s)")
            time.sleep(wait)
    return []


def main():
    print(f"[{datetime.now()}] Starting phylum-level broad search...")
    all_results = {}
    
    for phylum, queries in PHYLA_QUERIES.items():
        print(f"\n[{datetime.now()}] Phylum: {phylum}")
        phylum_pmids = set()
        
        for qtext in queries:
            print(f"  Query: {qtext[:100]}...")
            pmids = esearch(qtext)
            time.sleep(1.0)  # Conservative rate limit
            phylum_pmids.update(pmids)
            if pmids:
                print(f"    -> Found {len(pmids)} PMIDs")
        
        print(f"  Total unique PMIDs for {phylum}: {len(phylum_pmids)}")
        
        # Fetch metadata in batches
        articles = []
        pmid_list = sorted(list(phylum_pmids))
        for i in range(0, len(pmid_list), 200):
            batch = pmid_list[i:i+200]
            batch_articles = efetch_metadata(batch)
            articles.extend(batch_articles)
            time.sleep(1.0)
        
        all_results[phylum] = {
            "phylum": phylum,
            "pmids": pmid_list,
            "article_count": len(articles),
            "articles": articles,
        }
        
        # Save intermediate
        out_file = os.path.join(OUT_DIR, f"{phylum.lower()}_articles.json")
        with open(out_file, "w", encoding="utf-8") as f:
            json.dump(all_results[phylum], f, ensure_ascii=False, indent=2)
        print(f"  Saved to {out_file}")
    
    # Save combined
    combined_file = os.path.join(OUT_DIR, "phylum_search_results.json")
    with open(combined_file, "w", encoding="utf-8") as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)
    
    # Also write CSV
    csv_file = os.path.join(OUT_DIR, "phylum_articles_combined.csv")
    with open(csv_file, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["pmid", "title", "year", "doi", "pmc_id", "phylum"])
        for phylum, data in all_results.items():
            for art in data.get("articles", []):
                writer.writerow([art["pmid"], art["title"], art["year"], art["doi"], art["pmc_id"], phylum])
    
    total_articles = sum(d["article_count"] for d in all_results.values())
    print(f"\n[{datetime.now()}] DONE!")
    print(f"  Total articles found: {total_articles}")
    for phylum, data in all_results.items():
        print(f"  {phylum}: {data['article_count']} articles")


if __name__ == "__main__":
    main()
