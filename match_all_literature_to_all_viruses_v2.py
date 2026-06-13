#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Match ALL existing literature sources against ALL 834 viruses.
Uses pre-existing matched_virus/matched_viruses columns where available.
Falls back to keyword matching for sources without pre-matched data.
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


def normalize(text):
    if not text or text != text:
        return ""
    return str(text).lower().strip()


def load_viruses():
    viruses = []
    with open(VIRUS_FILE, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            viruses.append(row)
    return viruses


def load_external_matched():
    """external_matched_articles.csv has pre-matched virus names."""
    path = os.path.join(BASE_DIR, "downloads", "literature_gap_analysis", "external_matched_articles.csv")
    articles = []
    if not os.path.exists(path):
        return articles
    with open(path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            matched = str(row.get("matched_virus", "")).strip()
            if matched:
                articles.append({
                    "pmid": str(row.get("pmid", "")).strip(),
                    "title": row.get("title", ""),
                    "matched_virus": matched,
                    "source": "external_matched",
                })
    return articles


def load_merged_master():
    """literature_merged_master.csv has matched_viruses (pipe-separated)."""
    path = os.path.join(BASE_DIR, "downloads", "literature_integrated", "literature_merged_master.csv")
    articles = []
    if not os.path.exists(path):
        return articles
    with open(path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            matched = str(row.get("matched_viruses", "")).strip()
            if matched:
                viruses = [v.strip() for v in matched.split("|") if v.strip()]
                for v in viruses:
                    articles.append({
                        "pmid": str(row.get("pmid", "")).strip(),
                        "title": row.get("title", ""),
                        "matched_virus": v,
                        "source": "merged_master",
                    })
    return articles


def load_other_sources():
    """Load broad_search, new_search, original priority sources."""
    sources = [
        (os.path.join(BASE_DIR, "downloads", "literature_broad_search", "broad_search_articles.csv"), "broad"),
        (os.path.join(BASE_DIR, "downloads", "literature_new_search", "new_articles.csv"), "new"),
        (os.path.join(BASE_DIR, "literature_curation_v2", "pmid_results_final.csv"), "original"),
    ]
    articles = []
    for path, label in sources:
        if not os.path.exists(path):
            continue
        with open(path, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                pmid = str(row.get("pmid", "")).strip()
                title = row.get("title", "")
                if pmid and title:
                    articles.append({
                        "pmid": pmid,
                        "title": title,
                        "matched_virus": None,  # needs fallback matching
                        "source": label,
                    })
    return articles


def build_name_index(viruses):
    """Build index: canonical_name -> master_id"""
    index = {}
    for v in viruses:
        name = v.get("canonical_name", "").strip()
        if name:
            index[name.lower()] = v.get("master_id", "")
    return index


def build_matching_patterns(viruses):
    """Build fuzzy matching patterns for fallback."""
    patterns = {}
    for v in viruses:
        vid = v.get("master_id", "")
        name = v.get("canonical_name", "").strip()
        abbr = v.get("abbreviations", "").strip()
        family = v.get("virus_family", "").strip()
        
        # Extract key tokens from name
        key_tokens = []
        if name:
            parts = name.lower().split()
            # Keep meaningful parts
            for p in parts:
                if len(p) > 3 and p not in {"virus", "like", "unclassified", "crustacean", "shrimp", "crab", "marine"}:
                    key_tokens.append(p)
        
        patterns[vid] = {
            "name": name.lower(),
            "abbr": abbr.upper().split("/") if abbr else [],
            "family": family.lower(),
            "key_tokens": key_tokens,
        }
    return patterns


def fallback_match(article, patterns):
    """Fallback keyword matching for articles without pre-matched virus."""
    text = normalize(article.get("title", ""))
    matched = []
    for vid, pat in patterns.items():
        # Full name match
        if pat["name"] and pat["name"] in text:
            matched.append(vid)
            continue
        # Abbreviation match
        for abbr in pat["abbr"]:
            if len(abbr) > 2 and re.search(r'\b' + re.escape(abbr) + r'\b', text, re.IGNORECASE):
                matched.append(vid)
                break
        else:
            # Key token match (at least 2 tokens)
            tokens_found = sum(1 for t in pat["key_tokens"] if t in text)
            if len(pat["key_tokens"]) >= 2 and tokens_found >= 2:
                matched.append(vid)
            elif len(pat["key_tokens"]) == 1 and tokens_found >= 1:
                matched.append(vid)
    return matched


def main():
    print(f"[{datetime.now()}] Loading viruses...")
    viruses = load_viruses()
    name_index = build_name_index(viruses)
    print(f"  -> {len(viruses)} viruses loaded")
    
    print(f"[{datetime.now()}] Loading literature with pre-matched viruses...")
    pre_matched = load_external_matched() + load_merged_master()
    print(f"  -> {len(pre_matched)} pre-matched article entries")
    
    print(f"[{datetime.now()}] Loading other literature sources...")
    other_articles = load_other_sources()
    print(f"  -> {len(other_articles)} other articles (need fallback matching)")
    
    # Deduplicate pre-matched by (pmid, virus)
    seen = set()
    virus_to_articles = defaultdict(set)
    
    for entry in pre_matched:
        key = (entry["pmid"], entry["matched_virus"].lower())
        if key in seen:
            continue
        seen.add(key)
        vid = name_index.get(entry["matched_virus"].lower())
        if vid:
            virus_to_articles[vid].add(entry["pmid"])
    
    # Fallback matching for other articles
    print(f"[{datetime.now()}] Running fallback matching...")
    patterns = build_matching_patterns(viruses)
    matched_other = 0
    for idx, article in enumerate(other_articles):
        matched = fallback_match(article, patterns)
        for vid in matched:
            virus_to_articles[vid].add(article["pmid"])
            matched_other += 1
        if (idx + 1) % 200 == 0:
            print(f"  Processed {idx+1}/{len(other_articles)}...")
    
    # Build coverage report
    coverage = {}
    covered_count = 0
    uncovered = []
    
    for v in viruses:
        vid = v.get("master_id", "")
        name = v.get("canonical_name", "")
        pmids = sorted(list(virus_to_articles.get(vid, set())))
        coverage[vid] = {
            "virus_name": name,
            "master_id": vid,
            "article_count": len(pmids),
            "pmids": pmids,
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
        "pre_matched_entries_used": len(seen),
        "fallback_matched_entries": matched_other,
        "timestamp": datetime.now().isoformat(),
    }
    summary_file = os.path.join(OUT_DIR, "coverage_summary.json")
    with open(summary_file, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    
    # TSV for easy review
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
    print(f"  Pre-matched entries: {len(seen)}")
    print(f"  Fallback matched: {matched_other}")
    print(f"  Results saved to: {OUT_DIR}")


if __name__ == "__main__":
    main()
