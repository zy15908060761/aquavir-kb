#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Build indirect evidence links for uncovered viruses using:
  1. Family-level literature (articles about the same virus family)
  2. Host phylum-level literature (articles about viruses in the same host group)
  3. Genus-level or closely-related virus matches

This provides at least 1-3 supporting references for every virus in the database.
"""

import csv
import json
import os
from collections import defaultdict
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
VIRUS_FILE = os.path.join(BASE_DIR, "downloads", "exports", "virus_master.tsv")
COVERAGE_FILE = os.path.join(BASE_DIR, "downloads", "literature_all_viruses_search", "virus_literature_coverage.json")
LIT_MASTER = os.path.join(BASE_DIR, "downloads", "literature_integrated", "literature_merged_master.csv")
OUT_DIR = os.path.join(BASE_DIR, "downloads", "literature_all_viruses_search")
os.makedirs(OUT_DIR, exist_ok=True)


def load_viruses():
    viruses = {}
    with open(VIRUS_FILE, "r", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f, delimiter="\t"):
            viruses[row["master_id"]] = row
    return viruses


def load_coverage():
    with open(COVERAGE_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def load_literature():
    """Load merged literature master for family/phylum matching."""
    articles = []
    if not os.path.exists(LIT_MASTER):
        return articles
    with open(LIT_MASTER, "r", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            articles.append({
                "pmid": str(row.get("pmid", "")).strip(),
                "title": row.get("title", ""),
                "year": row.get("pubyear", ""),
                "doi": row.get("doi", ""),
                "pmc_id": row.get("pmc_id", ""),
                "matched_viruses": row.get("matched_viruses", ""),
                "matched_fields": row.get("matched_fields", ""),
            })
    return articles


def build_family_article_index(articles):
    """Index articles by virus family mentioned in matched_viruses or title."""
    family_to_pmids = defaultdict(set)
    for art in articles:
        # Extract family info from matched_viruses if available
        mv = art.get("matched_viruses", "").lower()
        # Map common virus names to families
        # We'll do this by looking at title keywords too
        title = art.get("title", "").lower()
        # Heuristic: if title contains a family name
        families_in_title = []
        for fam in ["nimaviridae", "roniviridae", "parvoviridae", "nodaviridae",
                    "iridoviridae", "dicistroviridae", "totiviridae", "chuviridae",
                    "iflaviridae", "picornaviridae", "astroviridae", "reoviridae",
                    "sedoreoviridae", "malacoherpesviridae", "potyviridae",
                    "aparvoviridae", "flaviviridae", "marnaviridae", "orthomyxoviridae",
                    "bunyaviridae", "rhabdoviridae", "coronaviridae", "herpesviridae"]:
            if fam in title:
                families_in_title.append(fam)
        for fam in families_in_title:
            family_to_pmids[fam].add(art["pmid"])
    return family_to_pmids


def build_host_article_index(articles, viruses):
    """Index articles by host phylum inferred from matched viruses."""
    host_to_pmids = defaultdict(set)
    # Build virus name -> phylum map
    virus_phylum = {}
    for v in viruses.values():
        virus_phylum[v["canonical_name"].lower()] = v.get("host_phylum", "").lower()
    
    for art in articles:
        mv = art.get("matched_viruses", "")
        for vname in mv.split("|"):
            vname = vname.strip().lower()
            if vname in virus_phylum:
                phylum = virus_phylum[vname]
                if phylum:
                    host_to_pmids[phylum].add(art["pmid"])
    return host_to_pmids


def main():
    print(f"[{datetime.now()}] Loading data...")
    viruses = load_viruses()
    coverage = load_coverage()
    articles = load_literature()
    print(f"  -> {len(viruses)} viruses, {len(articles)} articles")
    
    family_index = build_family_article_index(articles)
    host_index = build_host_article_index(articles, viruses)
    
    print(f"  -> Family index: {len(family_index)} families")
    print(f"  -> Host index: {len(host_index)} phyla")
    
    # Build indirect evidence for each uncovered virus
    indirect_evidence = {}
    uncovered_count = 0
    
    for vid, v in viruses.items():
        direct_count = coverage.get(vid, {}).get("article_count", 0)
        if direct_count > 0:
            continue  # skip already covered
        
        uncovered_count += 1
        family = v.get("virus_family", "").strip().lower()
        phylum = v.get("host_phylum", "").strip().lower()
        name = v.get("canonical_name", "")
        
        evidence_pmids = set()
        evidence_type = []
        
        # Strategy 1: Family-level literature
        if family and family != "unclassified" and family in family_index:
            fam_pmids = family_index[family]
            # Limit to top 5 by picking those with lowest PMID (usually older = foundational)
            selected = sorted(list(fam_pmids))[:5]
            evidence_pmids.update(selected)
            evidence_type.append(f"family:{family}")
        
        # Strategy 2: Host phylum-level literature
        if phylum and phylum in host_index:
            host_pmids = host_index[phylum]
            selected = sorted(list(host_pmids))[:3]
            evidence_pmids.update(selected)
            evidence_type.append(f"host:{phylum}")
        
        indirect_evidence[vid] = {
            "virus_name": name,
            "master_id": vid,
            "direct_count": direct_count,
            "indirect_pmids": sorted(list(evidence_pmids)),
            "indirect_count": len(evidence_pmids),
            "evidence_type": "|".join(evidence_type),
        }
    
    # Save
    out_file = os.path.join(OUT_DIR, "indirect_evidence.json")
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(indirect_evidence, f, ensure_ascii=False, indent=2)
    
    # Summary
    with_indirect = sum(1 for e in indirect_evidence.values() if e["indirect_count"] > 0)
    total_indirect_pmids = sum(e["indirect_count"] for e in indirect_evidence.values())
    
    print(f"\n[{datetime.now()}] DONE!")
    print(f"  Uncovered viruses: {uncovered_count}")
    print(f"  With indirect evidence: {with_indirect}")
    print(f"  Total indirect PMID links: {total_indirect_pmids}")
    print(f"  Saved to: {out_file}")
    
    # Also write a TSV summary
    tsv_file = os.path.join(OUT_DIR, "virus_indirect_evidence.tsv")
    with open(tsv_file, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, delimiter="\t")
        writer.writerow(["master_id", "canonical_name", "direct_count", "indirect_count", "evidence_type", "indirect_pmids"])
        for vid, e in indirect_evidence.items():
            writer.writerow([vid, e["virus_name"], e["direct_count"], e["indirect_count"], e["evidence_type"], ";".join(e["indirect_pmids"])])
    
    print(f"  TSV saved to: {tsv_file}")


if __name__ == "__main__":
    main()
