#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Integrate phylum-level search results into the existing literature coverage.
Matches phylum articles to uncovered viruses by host phylum.
"""

import csv
import json
import os
from collections import defaultdict
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
VIRUS_FILE = os.path.join(BASE_DIR, "downloads", "exports", "virus_master.tsv")
PHYLUM_DIR = os.path.join(BASE_DIR, "downloads", "literature_all_viruses_search", "phylum_search")
DIRECT_COVERAGE = os.path.join(BASE_DIR, "downloads", "literature_all_viruses_search", "virus_literature_coverage.json")
INDIRECT_EVIDENCE = os.path.join(BASE_DIR, "downloads", "literature_all_viruses_search", "indirect_evidence.json")
PUBMED_CHECKPOINT = os.path.join(BASE_DIR, "downloads", "literature_all_viruses_search", "search_checkpoint.json")
LIT_MASTER = os.path.join(BASE_DIR, "downloads", "literature_integrated", "literature_merged_master.csv")

OUT_DIR = os.path.join(BASE_DIR, "downloads", "literature_all_viruses_search")


def load_viruses():
    viruses = {}
    with open(VIRUS_FILE, "r", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f, delimiter="\t"):
            viruses[row["master_id"]] = row
    return viruses


def load_phylum_articles():
    combined_file = os.path.join(PHYLUM_DIR, "phylum_search_results.json")
    if not os.path.exists(combined_file):
        # Try individual files
        all_results = {}
        for phylum in ["mollusca", "cnidaria", "echinodermata", "porifera"]:
            fpath = os.path.join(PHYLUM_DIR, f"{phylum}_articles.json")
            if os.path.exists(fpath):
                with open(fpath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                all_results[phylum.capitalize()] = data
        return all_results
    with open(combined_file, "r", encoding="utf-8") as f:
        return json.load(f)


def load_existing_coverage():
    direct = {}
    if os.path.exists(DIRECT_COVERAGE):
        with open(DIRECT_COVERAGE, "r", encoding="utf-8") as f:
            direct = json.load(f)
    indirect = {}
    if os.path.exists(INDIRECT_EVIDENCE):
        with open(INDIRECT_EVIDENCE, "r", encoding="utf-8") as f:
            indirect = json.load(f)
    pubmed = {}
    if os.path.exists(PUBMED_CHECKPOINT):
        with open(PUBMED_CHECKPOINT, "r", encoding="utf-8") as f:
            cp = json.load(f)
        for vid, data in cp.get("results", {}).items():
            if data.get("all_pmids"):
                pubmed[vid] = data.get("all_pmids", [])
    return direct, indirect, pubmed


def load_lit_master():
    lookup = {}
    if not os.path.exists(LIT_MASTER):
        return lookup
    with open(LIT_MASTER, "r", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            pmid = str(row.get("pmid", "")).strip()
            if pmid:
                lookup[pmid] = {
                    "pmid": pmid,
                    "title": row.get("title", ""),
                    "authors": row.get("authors", ""),
                    "source": row.get("source", ""),
                    "year": row.get("pubyear", ""),
                    "doi": row.get("doi", ""),
                    "pmc_id": row.get("pmc_id", ""),
                }
    return lookup


def build_phylum_article_lookup(phylum_data):
    """Build PMID -> {phylum, article} lookup from phylum search results."""
    lookup = {}
    for phylum, data in phylum_data.items():
        for art in data.get("articles", []):
            pmid = art.get("pmid", "")
            if pmid:
                lookup[pmid] = {
                    "pmid": pmid,
                    "title": art.get("title", ""),
                    "year": art.get("year", ""),
                    "doi": art.get("doi", ""),
                    "pmc_id": art.get("pmc_id", ""),
                    "phylum": phylum,
                }
    return lookup


def main():
    print(f"[{datetime.now()}] Loading data...")
    viruses = load_viruses()
    phylum_data = load_phylum_articles()
    direct, indirect, pubmed = load_existing_coverage()
    lit_lookup = load_lit_master()
    phylum_art_lookup = build_phylum_article_lookup(phylum_data)
    
    print(f"  Viruses: {len(viruses)}")
    print(f"  Phylum articles: {len(phylum_art_lookup)} unique PMIDs")
    
    # Determine which viruses are still uncovered
    covered_vids = set()
    for vid, data in direct.items():
        if data.get("article_count", 0) > 0:
            covered_vids.add(vid)
    for vid, data in indirect.items():
        if data.get("indirect_count", 0) > 0:
            covered_vids.add(vid)
    for vid in pubmed:
        covered_vids.add(vid)
    
    uncovered = [vid for vid in viruses if vid not in covered_vids]
    print(f"  Currently uncovered: {len(uncovered)}")
    
    # Match uncovered viruses to phylum articles by host phylum
    new_coverage = defaultdict(list)
    for vid in uncovered:
        v = viruses[vid]
        v_phylum = v.get("host_phylum", "").strip()
        if not v_phylum:
            continue
        # Find articles from same phylum
        matched_pmids = []
        for pmid, art in phylum_art_lookup.items():
            if art["phylum"] == v_phylum:
                matched_pmids.append(pmid)
        # Limit to top 10 per virus to avoid over-linking
        if matched_pmids:
            new_coverage[vid] = matched_pmids[:10]
    
    print(f"  Viruses matched to phylum articles: {len(new_coverage)}")
    
    # Now rebuild the full integration with phylum evidence included
    # 1. Collect all PMIDs and their evidence types
    virus_to_pmids = defaultdict(set)
    pmid_to_viruses = defaultdict(set)
    pmid_evidence_type = defaultdict(set)
    
    # Direct
    for vid, data in direct.items():
        for pmid in data.get("pmids", []):
            virus_to_pmids[vid].add(pmid)
            pmid_to_viruses[pmid].add(vid)
            pmid_evidence_type[pmid].add("direct")
    
    # Indirect
    for vid, data in indirect.items():
        for pmid in data.get("indirect_pmids", []):
            virus_to_pmids[vid].add(pmid)
            pmid_to_viruses[pmid].add(vid)
            pmid_evidence_type[pmid].add("indirect")
    
    # PubMed
    for vid, pmids in pubmed.items():
        for pmid in pmids:
            virus_to_pmids[vid].add(pmid)
            pmid_to_viruses[pmid].add(vid)
            pmid_evidence_type[pmid].add("pubmed")
    
    # Phylum new
    for vid, pmids in new_coverage.items():
        for pmid in pmids:
            virus_to_pmids[vid].add(pmid)
            pmid_to_viruses[pmid].add(vid)
            pmid_evidence_type[pmid].add("phylum")
    
    # Build unique article list
    all_pmids = sorted(pmid_to_viruses.keys())
    
    # Merge phylum article metadata with lit_lookup
    full_lookup = dict(lit_lookup)
    for pmid, art in phylum_art_lookup.items():
        if pmid not in full_lookup:
            full_lookup[pmid] = {
                "pmid": pmid,
                "title": art["title"],
                "authors": "",
                "source": "PubMed",
                "year": art["year"],
                "doi": art["doi"],
                "pmc_id": art["pmc_id"],
            }
    
    # Write ref_literatures TSV
    REF_LIT_OUT = os.path.join(OUT_DIR, "ref_literatures_enriched.tsv")
    with open(REF_LIT_OUT, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, delimiter="\t")
        writer.writerow(["reference_id", "pmid", "title", "authors", "journal_source", "pubyear", "doi", "pmc_id", "evidence_types"])
        for idx, pmid in enumerate(all_pmids, 1):
            meta = full_lookup.get(pmid, {})
            ev_types = "|".join(sorted(pmid_evidence_type[pmid]))
            writer.writerow([
                idx, meta.get("pmid", ""), meta.get("title", ""), meta.get("authors", ""),
                meta.get("source", ""), meta.get("year", ""), meta.get("doi", ""),
                meta.get("pmc_id", ""), ev_types,
            ])
    
    pmid_to_refid = {pmid: idx for idx, pmid in enumerate(all_pmids, 1)}
    
    # Write virus-literature map
    VIRUS_LIT_MAP_OUT = os.path.join(OUT_DIR, "virus_literature_map_enriched.tsv")
    with open(VIRUS_LIT_MAP_OUT, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, delimiter="\t")
        writer.writerow(["master_id", "canonical_name", "reference_id", "pmid", "evidence_type"])
        for vid in sorted(viruses.keys(), key=int):
            vname = viruses[vid]["canonical_name"]
            pmids = sorted(virus_to_pmids.get(vid, set()))
            for pmid in pmids:
                ref_id = pmid_to_refid.get(pmid, "")
                ev_type = "|".join(sorted(pmid_evidence_type[pmid]))
                writer.writerow([vid, vname, ref_id, pmid, ev_type])
    
    # Coverage report
    covered = sum(1 for vid in viruses if virus_to_pmids.get(vid))
    direct_only = sum(1 for vid in viruses if vid in direct and vid not in indirect and vid not in pubmed and vid not in new_coverage)
    phylum_only = sum(1 for vid in viruses if vid in new_coverage and vid not in direct and vid not in indirect and vid not in pubmed)
    
    report = {
        "total_viruses": len(viruses),
        "covered_viruses": covered,
        "coverage_pct": round(covered / len(viruses) * 100, 2) if viruses else 0,
        "direct_only": direct_only,
        "phylum_only": len(new_coverage),
        "total_unique_articles": len(all_pmids),
        "timestamp": datetime.now().isoformat(),
    }
    
    COVERAGE_REPORT_OUT = os.path.join(OUT_DIR, "final_coverage_report.json")
    with open(COVERAGE_REPORT_OUT, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    
    # Save phylum match details
    phylum_match_file = os.path.join(OUT_DIR, "phylum_matches.json")
    with open(phylum_match_file, "w", encoding="utf-8") as f:
        json.dump({vid: {"virus_name": viruses[vid]["canonical_name"], "pmids": pmids} for vid, pmids in new_coverage.items()}, f, ensure_ascii=False, indent=2)
    
    print(f"\n[{datetime.now()}] INTEGRATION COMPLETE!")
    print(f"  Covered viruses: {covered}/{len(viruses)} ({report['coverage_pct']}%)")
    print(f"  Phylum-only viruses: {len(new_coverage)}")
    print(f"  Total unique articles: {len(all_pmids)}")
    print(f"  Output: {OUT_DIR}")


if __name__ == "__main__":
    main()
