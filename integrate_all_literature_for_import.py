#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Integrate ALL literature evidence (direct + indirect + PubMed new) into
a single import-ready TSV for ref_literatures and virus-literature links.

Can be run incrementally: re-reads PubMed checkpoint if available.
"""

import csv
import json
import os
from collections import defaultdict
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
VIRUS_FILE = os.path.join(BASE_DIR, "downloads", "exports", "virus_master.tsv")
DIRECT_COVERAGE = os.path.join(BASE_DIR, "downloads", "literature_all_viruses_search", "virus_literature_coverage.json")
INDIRECT_EVIDENCE = os.path.join(BASE_DIR, "downloads", "literature_all_viruses_search", "indirect_evidence.json")
PUBMED_CHECKPOINT = os.path.join(BASE_DIR, "downloads", "literature_all_viruses_search", "search_checkpoint.json")
LIT_MASTER = os.path.join(BASE_DIR, "downloads", "literature_integrated", "literature_merged_master.csv")
OUT_DIR = os.path.join(BASE_DIR, "downloads", "literature_all_viruses_search")
os.makedirs(OUT_DIR, exist_ok=True)

# Output files
REF_LIT_OUT = os.path.join(OUT_DIR, "ref_literatures_enriched.tsv")
VIRUS_LIT_MAP_OUT = os.path.join(OUT_DIR, "virus_literature_map_enriched.tsv")
COVERAGE_REPORT_OUT = os.path.join(OUT_DIR, "final_coverage_report.json")


def load_viruses():
    viruses = {}
    with open(VIRUS_FILE, "r", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f, delimiter="\t"):
            viruses[row["master_id"]] = row
    return viruses


def load_direct_coverage():
    if not os.path.exists(DIRECT_COVERAGE):
        return {}
    with open(DIRECT_COVERAGE, "r", encoding="utf-8") as f:
        return json.load(f)


def load_indirect_evidence():
    if not os.path.exists(INDIRECT_EVIDENCE):
        return {}
    with open(INDIRECT_EVIDENCE, "r", encoding="utf-8") as f:
        return json.load(f)


def load_pubmed_results():
    """Load new PubMed search results from checkpoint."""
    if not os.path.exists(PUBMED_CHECKPOINT):
        return {}
    with open(PUBMED_CHECKPOINT, "r", encoding="utf-8") as f:
        cp = json.load(f)
    results = {}
    for vid, data in cp.get("results", {}).items():
        pmids = data.get("all_pmids", [])
        if pmids:
            results[vid] = {
                "pmids": pmids,
                "articles": data.get("articles", []),
            }
    return results


def load_literature_master():
    """Load literature master as PMID -> metadata lookup."""
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


def build_article_metadata(pmid, lit_lookup, pubmed_articles):
    """Get metadata for a PMID from lit_master or PubMed results."""
    if pmid in lit_lookup:
        return lit_lookup[pmid]
    # Search in PubMed articles
    for vid_data in pubmed_articles.values():
        for art in vid_data.get("articles", []):
            if art.get("pmid") == pmid:
                return {
                    "pmid": pmid,
                    "title": art.get("title", ""),
                    "authors": "",
                    "source": "PubMed",
                    "year": art.get("year", ""),
                    "doi": art.get("doi", ""),
                    "pmc_id": art.get("pmc_id", ""),
                }
    return {
        "pmid": pmid,
        "title": "",
        "authors": "",
        "source": "",
        "year": "",
        "doi": "",
        "pmc_id": "",
    }


def main():
    print(f"[{datetime.now()}] Loading data sources...")
    viruses = load_viruses()
    direct = load_direct_coverage()
    indirect = load_indirect_evidence()
    pubmed = load_pubmed_results()
    lit_lookup = load_literature_master()
    
    print(f"  Viruses: {len(viruses)}")
    print(f"  Direct coverage: {len([v for v in direct.values() if v.get('article_count', 0) > 0])} viruses")
    print(f"  Indirect evidence: {len([v for v in indirect.values() if v.get('indirect_count', 0) > 0])} viruses")
    print(f"  PubMed new results: {len(pubmed)} viruses")
    
    # Collect all unique PMIDs and their links to viruses
    virus_to_pmids = defaultdict(set)
    pmid_to_viruses = defaultdict(set)
    pmid_evidence_type = defaultdict(set)  # 'direct', 'indirect', 'pubmed'
    
    # 1. Direct coverage
    for vid, data in direct.items():
        for pmid in data.get("pmids", []):
            virus_to_pmids[vid].add(pmid)
            pmid_to_viruses[pmid].add(vid)
            pmid_evidence_type[pmid].add("direct")
    
    # 2. Indirect evidence
    for vid, data in indirect.items():
        for pmid in data.get("indirect_pmids", []):
            virus_to_pmids[vid].add(pmid)
            pmid_to_viruses[pmid].add(vid)
            pmid_evidence_type[pmid].add("indirect")
    
    # 3. PubMed new results
    for vid, data in pubmed.items():
        for pmid in data.get("pmids", []):
            virus_to_pmids[vid].add(pmid)
            pmid_to_viruses[pmid].add(vid)
            pmid_evidence_type[pmid].add("pubmed")
    
    # Build unique article list
    all_pmids = sorted(pmid_to_viruses.keys())
    print(f"  Total unique PMID links: {len(all_pmids)}")
    
    # Write ref_literatures TSV
    print(f"[{datetime.now()}] Writing ref_literatures_enriched.tsv...")
    with open(REF_LIT_OUT, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, delimiter="\t")
        writer.writerow(["reference_id", "pmid", "title", "authors", "journal_source", "pubyear", "doi", "pmc_id", "evidence_types"])
        for idx, pmid in enumerate(all_pmids, 1):
            meta = build_article_metadata(pmid, lit_lookup, pubmed)
            ev_types = "|".join(sorted(pmid_evidence_type[pmid]))
            writer.writerow([
                idx,
                meta["pmid"],
                meta["title"],
                meta["authors"],
                meta["source"],
                meta["year"],
                meta["doi"],
                meta["pmc_id"],
                ev_types,
            ])
    
    # Build PMID -> reference_id map
    pmid_to_refid = {pmid: idx for idx, pmid in enumerate(all_pmids, 1)}
    
    # Write virus-literature map TSV
    print(f"[{datetime.now()}] Writing virus_literature_map_enriched.tsv...")
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
    direct_only = sum(1 for vid in viruses if vid in direct and direct[vid].get("article_count", 0) > 0 and vid not in indirect)
    indirect_only = sum(1 for vid in viruses if vid in indirect and indirect[vid].get("indirect_count", 0) > 0 and vid not in direct)
    both = sum(1 for vid in viruses if vid in direct and direct[vid].get("article_count", 0) > 0 and vid in indirect and indirect[vid].get("indirect_count", 0) > 0)
    
    report = {
        "total_viruses": len(viruses),
        "covered_viruses": covered,
        "coverage_pct": round(covered / len(viruses) * 100, 2) if viruses else 0,
        "direct_only": direct_only,
        "indirect_only": indirect_only,
        "both_direct_indirect": both,
        "pubmed_enhanced": len(pubmed),
        "total_unique_articles": len(all_pmids),
        "ref_literatures_file": REF_LIT_OUT,
        "virus_literature_map_file": VIRUS_LIT_MAP_OUT,
        "timestamp": datetime.now().isoformat(),
    }
    
    with open(COVERAGE_REPORT_OUT, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    
    print(f"\n[{datetime.now()}] INTEGRATION COMPLETE!")
    print(f"  Covered viruses: {covered}/{len(viruses)} ({report['coverage_pct']}%)")
    print(f"  Direct only: {direct_only}")
    print(f"  Indirect only: {indirect_only}")
    print(f"  Both: {both}")
    print(f"  PubMed-enhanced viruses: {len(pubmed)}")
    print(f"  Total unique articles: {len(all_pmids)}")
    print(f"  Output files:")
    print(f"    - {REF_LIT_OUT}")
    print(f"    - {VIRUS_LIT_MAP_OUT}")
    print(f"    - {COVERAGE_REPORT_OUT}")


if __name__ == "__main__":
    main()
