#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Strict audit of 100% coverage claims."""

import csv
import os
from collections import Counter, defaultdict

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Load viruses
viruses = {}
with open(os.path.join(BASE_DIR, "downloads", "exports", "virus_master.tsv"), "r", encoding="utf-8-sig") as f:
    for row in csv.DictReader(f, delimiter="\t"):
        viruses[row["master_id"]] = row

# Load virus-literature map
vl_map = defaultdict(list)
map_path = os.path.join(BASE_DIR, "downloads", "literature_all_viruses_search", "virus_literature_map_enriched.tsv")
with open(map_path, "r", encoding="utf-8") as f:
    for row in csv.DictReader(f, delimiter="\t"):
        vl_map[row["master_id"]].append(row)

# Coverage check
covered = set(vl_map.keys())
all_vids = set(viruses.keys())
uncovered = all_vids - covered
print("=== Coverage Verification ===")
print(f"Total viruses: {len(viruses)}")
print(f"Viruses with map entries: {len(covered)}")
print(f"Missing: {len(uncovered)}")
if uncovered:
    for vid in list(uncovered)[:10]:
        print(f"  Missing: {viruses.get(vid, {}).get('canonical_name', vid)}")

# Evidence type breakdown by virus
ev_breakdown = Counter()
phylum_only_vids = []
direct_or_pubmed_vids = []
for vid, entries in vl_map.items():
    ev_types = set()
    for e in entries:
        ev_types.update(e.get("evidence_type", "").split("|"))
    ev_breakdown[tuple(sorted(ev_types))] += 1
    if ev_types == {"phylum"}:
        phylum_only_vids.append(vid)
    if "direct" in ev_types or "pubmed" in ev_types:
        direct_or_pubmed_vids.append(vid)

print("\n=== Evidence Type Distribution ===")
for ev_types, count in sorted(ev_breakdown.items(), key=lambda x: x[1], reverse=True):
    print(f"  {'+'.join(ev_types)} : {count} viruses")

# Audit phylum-only matches
print(f"\n=== Phylum-Only Match Audit (sample of 30 / {len(phylum_only_vids)} total) ===")
for vid in phylum_only_vids[:30]:
    v = viruses[vid]
    entries = vl_map[vid]
    phylum = v.get("host_phylum", "")
    print(f"  {v['canonical_name']} [{phylum}] => {len(entries)} articles")

# Audit direct+pubmed quality
print(f"\n=== Direct/PubMed Match Audit (top 20 by article count) ===")
vid_counts = [(vid, len(entries)) for vid, entries in vl_map.items() if vid in direct_or_pubmed_vids]
vid_counts.sort(key=lambda x: x[1], reverse=True)
for vid, cnt in vid_counts[:20]:
    v = viruses[vid]
    print(f"  {cnt:>4} articles  {v['canonical_name']}")

# Check for empty PMIDs or reference_ids
empty_issues = []
for vid, entries in vl_map.items():
    for e in entries:
        if not e.get("pmid") or not e.get("reference_id"):
            empty_issues.append((vid, e))
print(f"\n=== Data Quality ===")
print(f"Entries with empty PMID or reference_id: {len(empty_issues)}")

# Verify each virus has unique PMIDs (no duplicates within virus)
dup_issues = 0
for vid, entries in vl_map.items():
    pmids = [e["pmid"] for e in entries]
    if len(pmids) != len(set(pmids)):
        dup_issues += 1
print(f"Viruses with duplicate PMIDs: {dup_issues}")

# Verify reference_id continuity
all_ref_ids = sorted(int(e["reference_id"]) for entries in vl_map.values() for e in entries if e.get("reference_id").isdigit())
if all_ref_ids:
    print(f"Reference ID range: 1 - {max(all_ref_ids)}")
    print(f"Unique reference IDs: {len(set(all_ref_ids))}")

print("\n=== SUMMARY ===")
print(f"Direct/PubMed covered: {len(direct_or_pubmed_vids)} ({len(direct_or_pubmed_vids)/len(viruses)*100:.1f}%)")
print(f"Phylum-only covered: {len(phylum_only_vids)} ({len(phylum_only_vids)/len(viruses)*100:.1f}%)")
print(f"Other (indirect only): {len(viruses) - len(phylum_only_vids) - len(direct_or_pubmed_vids)}")
