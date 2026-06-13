#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Add confidence scores to each virus-literature link.

Confidence levels:
  HIGH   - direct name/abbr match OR PubMed esearch found exact name in title/abstract
  MEDIUM - indirect family match OR virus family name appears in article title
  LOW    - phylum-level broad match only (no specific virus/family mention)
  NONE   - no discernible link (should be flagged for review)
"""

import csv
import json
import os
import re
from collections import defaultdict
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
VIRUS_FILE = os.path.join(BASE_DIR, "downloads", "exports", "virus_master.tsv")
VIRUS_LIT_MAP = os.path.join(BASE_DIR, "downloads", "literature_all_viruses_search", "virus_literature_map_enriched.tsv")
REF_LIT = os.path.join(BASE_DIR, "downloads", "literature_all_viruses_search", "ref_literatures_enriched.tsv")
PUBMED_CHECKPOINT = os.path.join(BASE_DIR, "downloads", "literature_all_viruses_search", "search_checkpoint.json")

OUT_MAP = os.path.join(BASE_DIR, "downloads", "literature_all_viruses_search", "virus_literature_map_with_confidence.tsv")
OUT_REPORT = os.path.join(BASE_DIR, "downloads", "literature_all_viruses_search", "confidence_report.json")


def load_viruses():
    viruses = {}
    with open(VIRUS_FILE, "r", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f, delimiter="\t"):
            viruses[row["master_id"]] = row
    return viruses


def load_article_lookup():
    lookup = {}
    with open(REF_LIT, "r", encoding="utf-8") as f:
        for row in csv.DictReader(f, delimiter="\t"):
            lookup[row["pmid"]] = row.get("title", "") or ""
    return lookup


def load_pubmed_results():
    pubmed_pmids_by_virus = defaultdict(set)
    if not os.path.exists(PUBMED_CHECKPOINT):
        return pubmed_pmids_by_virus
    with open(PUBMED_CHECKPOINT, "r", encoding="utf-8") as f:
        cp = json.load(f)
    for vid, data in cp.get("results", {}).items():
        for pmid in data.get("all_pmids", []):
            pubmed_pmids_by_virus[vid].add(str(pmid))
    return pubmed_pmids_by_virus


def score_link(vid, pmid, ev_types, virus, article_title, pubmed_pmids):
    """
    Score a single virus-literature link.
    Returns: (confidence, reason)
    """
    title_lower = (article_title or "").lower()
    name = virus.get("canonical_name", "").strip()
    abbr = virus.get("abbreviations", "").strip()
    family = virus.get("virus_family", "").strip()
    
    # HIGH: direct evidence (name match in existing matched sources)
    if "direct" in ev_types:
        return "HIGH", "direct_name_match_in_source"
    
    # HIGH: PubMed found exact name/abbr in title/abstract
    if "pubmed" in ev_types and str(pmid) in pubmed_pmids.get(vid, set()):
        name_parts = name.lower().split()
        # If 2+ key words from name appear in title
        key_words = [p for p in name_parts if len(p) > 3 and p not in {"virus", "like"}]
        matches = sum(1 for w in key_words if w in title_lower)
        if matches >= 2 or name.lower() in title_lower:
            return "HIGH", "pubmed_name_in_title"
        # Abbreviation match
        if abbr:
            for a in abbr.split("/"):
                if len(a) > 2 and re.search(r'\b' + re.escape(a.lower()) + r'\b', title_lower):
                    return "HIGH", "pubmed_abbreviation_in_title"
        return "MEDIUM", "pubmed_found_but_title_unclear"
    
    # MEDIUM: family-level indirect evidence
    if "indirect" in ev_types:
        if family and family.lower() != "unclassified" and family.lower() in title_lower:
            return "MEDIUM", "family_name_in_title"
        return "MEDIUM", "indirect_family_or_host_match"
    
    # LOW/PHYLUM: phylum-level only
    if "phylum" in ev_types:
        # Check if family appears in title (upgrade to MEDIUM)
        if family and family.lower() != "unclassified" and family.lower() in title_lower:
            return "MEDIUM", "phylum_match_but_family_in_title"
        # Check if any part of virus name appears
        name_parts = [p for p in name.lower().split() if len(p) > 3 and p not in {"virus", "like", "unclassified"}]
        matches = sum(1 for w in name_parts if w in title_lower)
        if matches >= 2:
            return "MEDIUM", "phylum_match_but_name_words_in_title"
        # Special case: Abalone herpesvirus gets herpesvirus articles
        if "herpesvirus" in name.lower() and "herpes" in title_lower:
            return "MEDIUM", "phylum_match_herpesvirus_keyword"
        if "norovirus" in name.lower() and "norovirus" in title_lower:
            return "MEDIUM", "phylum_match_norovirus_keyword"
        return "LOW", "phylum_broad_match_only"
    
    return "NONE", "unknown_evidence_type"


def main():
    print(f"[{datetime.now()}] Loading data...")
    viruses = load_viruses()
    article_lookup = load_article_lookup()
    pubmed_pmids = load_pubmed_results()
    
    print(f"  Viruses: {len(viruses)}")
    print(f"  Articles: {len(article_lookup)}")
    print(f"  PubMed virus-PMID links: {sum(len(v) for v in pubmed_pmids.values())}")
    
    confidence_counts = defaultdict(int)
    virus_max_confidence = {}
    
    print(f"[{datetime.now()}] Scoring links...")
    scored_rows = []
    with open(VIRUS_LIT_MAP, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            vid = row["master_id"]
            pmid = row["pmid"]
            ev_types = row.get("evidence_type", "").split("|")
            virus = viruses.get(vid, {})
            title = article_lookup.get(pmid, "")
            
            confidence, reason = score_link(vid, pmid, ev_types, virus, title, pubmed_pmids)
            
            scored_rows.append({
                **row,
                "confidence": confidence,
                "confidence_reason": reason,
            })
            confidence_counts[confidence] += 1
            
            # Track max confidence per virus
            conf_order = {"HIGH": 3, "MEDIUM": 2, "LOW": 1, "NONE": 0}
            current_max = virus_max_confidence.get(vid, "NONE")
            if conf_order.get(confidence, 0) > conf_order.get(current_max, 0):
                virus_max_confidence[vid] = confidence
    
    # Write scored map
    print(f"[{datetime.now()}] Writing scored map...")
    with open(OUT_MAP, "w", encoding="utf-8", newline="") as f:
        if scored_rows:
            writer = csv.DictWriter(f, fieldnames=list(scored_rows[0].keys()), delimiter="\t")
            writer.writeheader()
            writer.writerows(scored_rows)
    
    # Report
    report = {
        "total_links": len(scored_rows),
        "confidence_distribution": dict(confidence_counts),
        "virus_coverage_by_confidence": {
            "HIGH": sum(1 for v in virus_max_confidence.values() if v == "HIGH"),
            "MEDIUM": sum(1 for v in virus_max_confidence.values() if v == "MEDIUM"),
            "LOW": sum(1 for v in virus_max_confidence.values() if v == "LOW"),
            "NONE": sum(1 for v in virus_max_confidence.values() if v == "NONE"),
        },
        "timestamp": datetime.now().isoformat(),
    }
    
    with open(OUT_REPORT, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    
    print(f"\n[{datetime.now()}] DONE!")
    print(f"  Total links scored: {len(scored_rows)}")
    for conf, cnt in sorted(confidence_counts.items(), key=lambda x: {"HIGH": 0, "MEDIUM": 1, "LOW": 2, "NONE": 3}.get(x[0], 4)):
        print(f"  {conf}: {cnt} links")
    print(f"\n  Virus coverage by max confidence:")
    for conf, cnt in report["virus_coverage_by_confidence"].items():
        print(f"    {conf}: {cnt} viruses")
    print(f"\n  Output: {OUT_MAP}")


if __name__ == "__main__":
    main()
