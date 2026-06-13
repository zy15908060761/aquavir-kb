#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Match ALL existing literature sources against ALL 834 viruses.
Produces comprehensive coverage report and identifies gaps.
"""

import csv
import json
import os
import re
from collections import defaultdict
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
VIRUS_FILE = os.path.join(BASE_DIR, "downloads", "exports", "virus_master.tsv")
OUT_DIR = os.path.join(BASE_DIR, "downloads", "literature_all_viruses_search")
os.makedirs(OUT_DIR, exist_ok=True)

# Literature sources
LIT_SOURCES = [
    (os.path.join(BASE_DIR, "downloads", "literature_gap_analysis", "external_matched_articles.csv"), "external"),
    (os.path.join(BASE_DIR, "downloads", "literature_broad_search", "broad_search_articles.csv"), "broad"),
    (os.path.join(BASE_DIR, "downloads", "literature_new_search", "new_articles.csv"), "new"),
    (os.path.join(BASE_DIR, "literature_curation_v2", "pmid_results_final.csv"), "original"),
    (os.path.join(BASE_DIR, "downloads", "literature_integrated", "literature_merged_master.csv"), "merged"),
]


def normalize(text):
    if not text or text != text:  # handle NaN
        return ""
    return str(text).lower().strip()


def load_viruses():
    viruses = []
    with open(VIRUS_FILE, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            viruses.append(row)
    return viruses


def load_all_articles():
    all_articles = {}
    for path, source_label in LIT_SOURCES:
        if not os.path.exists(path):
            print(f"Warning: {path} not found, skipping.")
            continue
        with open(path, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                pmid = str(row.get("pmid", row.get("PMID", ""))).strip()
                if not pmid:
                    continue
                if pmid not in all_articles:
                    all_articles[pmid] = {
                        "pmid": pmid,
                        "title": row.get("title", row.get("Title", "")),
                        "source": source_label,
                        "sources": [source_label],
                        "year": row.get("year", row.get("pubyear", row.get("Year", ""))),
                        "doi": row.get("doi", row.get("DOI", "")),
                        "pmc_id": row.get("pmc_id", row.get("pmcid", row.get("PMCID", ""))),
                    }
                else:
                    if source_label not in all_articles[pmid]["sources"]:
                        all_articles[pmid]["sources"].append(source_label)
    return list(all_articles.values())


def build_virus_patterns(viruses):
    patterns = {}
    for v in viruses:
        vid = v.get("master_id", "")
        name = normalize(v.get("canonical_name", ""))
        abbr = normalize(v.get("abbreviations", ""))
        family = normalize(v.get("virus_family", ""))
        genus = normalize(v.get("virus_genus", ""))
        
        tokens = set()
        if name:
            tokens.add(name)
            # Also add key words from name
            tokens.update(name.split())
        if abbr and abbr != name and len(abbr) > 2:
            tokens.add(abbr)
        if family:
            tokens.add(family)
        if genus:
            tokens.add(genus)
        
        # Remove common noise words
        noise = {"virus", "like", "unclassified", "crustacean", "shrimp", "crab", "ssrna", "dsrna", "rna", "dna"}
        tokens = {t for t in tokens if t and len(t) > 2 and t not in noise}
        
        patterns[vid] = {
            "name": name,
            "abbr": abbr,
            "family": family,
            "tokens": tokens,
        }
    return patterns


def match_article_to_viruses(article, virus_patterns):
    text = normalize(article.get("title", ""))
    matched = []
    for vid, pat in virus_patterns.items():
        # Direct name match
        if pat["name"] and pat["name"] in text:
            matched.append(vid)
            continue
        # Abbreviation match (must be whole word-like)
        if pat["abbr"] and len(pat["abbr"]) > 2:
            if re.search(r'\b' + re.escape(pat["abbr"]) + r'\b', text):
                matched.append(vid)
                continue
        # Family match (only if family is specific and not too generic)
        if pat["family"] and len(pat["family"]) > 5 and pat["family"] in text:
            matched.append(vid)
            continue
    return matched


def main():
    print(f"[{datetime.now()}] Loading viruses...")
    viruses = load_viruses()
    print(f"  -> {len(viruses)} viruses loaded")
    
    print(f"[{datetime.now()}] Loading literature sources...")
    articles = load_all_articles()
    print(f"  -> {len(articles)} unique articles loaded")
    
    print(f"[{datetime.now()}] Building matching patterns...")
    virus_patterns = build_virus_patterns(viruses)
    
    print(f"[{datetime.now()}] Matching articles to viruses...")
    virus_to_articles = defaultdict(list)
    article_to_viruses = defaultdict(list)
    
    for idx, article in enumerate(articles):
        matched = match_article_to_viruses(article, virus_patterns)
        if matched:
            for vid in matched:
                virus_to_articles[vid].append(article["pmid"])
            article_to_viruses[article["pmid"]] = matched
        if (idx + 1) % 500 == 0:
            print(f"  Processed {idx+1}/{len(articles)} articles...")
    
    # Build coverage report
    coverage = {}
    covered_count = 0
    uncovered = []
    
    for v in viruses:
        vid = v.get("master_id", "")
        name = v.get("canonical_name", "")
        pmids = virus_to_articles.get(vid, [])
        coverage[vid] = {
            "virus_name": name,
            "master_id": vid,
            "article_count": len(pmids),
            "pmids": sorted(list(set(pmids))),
        }
        if pmids:
            covered_count += 1
        else:
            uncovered.append(name)
    
    # Save results
    coverage_file = os.path.join(OUT_DIR, "virus_literature_coverage.json")
    with open(coverage_file, "w", encoding="utf-8") as f:
        json.dump(coverage, f, ensure_ascii=False, indent=2)
    
    summary = {
        "total_viruses": len(viruses),
        "covered_viruses": covered_count,
        "uncovered_viruses": len(uncovered),
        "uncovered_list": uncovered,
        "total_unique_articles": len(articles),
        "articles_with_matches": len(article_to_viruses),
        "timestamp": datetime.now().isoformat(),
    }
    summary_file = os.path.join(OUT_DIR, "coverage_summary.json")
    with open(summary_file, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    
    # Also save TSV for easy review
    tsv_file = os.path.join(OUT_DIR, "virus_coverage.tsv")
    with open(tsv_file, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, delimiter="\t")
        writer.writerow(["master_id", "canonical_name", "article_count", "pmids"])
        for v in viruses:
            vid = v.get("master_id", "")
            name = v.get("canonical_name", "")
            pmids = coverage.get(vid, {}).get("pmids", [])
            writer.writerow([vid, name, len(pmids), ";".join(pmids)])
    
    print(f"\n[{datetime.now()}] DONE!")
    print(f"  Covered: {covered_count}/{len(viruses)}")
    print(f"  Uncovered: {len(uncovered)}")
    print(f"  Articles with matches: {len(article_to_viruses)}/{len(articles)}")
    print(f"  Results saved to: {OUT_DIR}")


if __name__ == "__main__":
    main()
