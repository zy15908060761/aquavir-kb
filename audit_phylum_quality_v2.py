#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Audit quality of phylum-only matches - v2 with None handling."""

import csv
import json
import os
from collections import defaultdict

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

viruses = {}
with open(os.path.join(BASE_DIR, "downloads", "exports", "virus_master.tsv"), "r", encoding="utf-8-sig") as f:
    for row in csv.DictReader(f, delimiter="\t"):
        viruses[row["master_id"]] = row

vl_map = defaultdict(list)
with open(os.path.join(BASE_DIR, "downloads", "literature_all_viruses_search", "virus_literature_map_enriched.tsv"), "r", encoding="utf-8") as f:
    for row in csv.DictReader(f, delimiter="\t"):
        vl_map[row["master_id"]].append(row)

# Find phylum-only viruses
phylum_only = []
for vid, entries in vl_map.items():
    ev_types = set()
    for e in entries:
        ev_types.update(e.get("evidence_type", "").split("|"))
    if ev_types == {"phylum"}:
        phylum_only.append(vid)

print(f"Phylum-only viruses: {len(phylum_only)}")

# Group by phylum
by_phylum = defaultdict(list)
for vid in phylum_only:
    v = viruses[vid]
    by_phylum[v.get("host_phylum", "Unknown")].append(v["canonical_name"])

print("\n=== By Phylum ===")
for phylum, names in sorted(by_phylum.items(), key=lambda x: len(x[1]), reverse=True):
    print(f"  {phylum}: {len(names)} viruses")

# Known legitimate aquatic invertebrate viruses (should have phylum matches)
legit_mollusca = ["abalone herpesvirus", "haliotid herpesvirus", "oyster herpesvirus",
                   "norovirus oyster", "bivalve", "meretrix", "haliotis", "crassostrea",
                   "mytilus", "pinctada", "osHV"]
legit_cnidaria = ["coral", "jellyfish", "sea anemone", "nematostella", "hydra"]
legit_echinoderm = ["sea urchin", "starfish", "asteroid", "echinoderm"]
legit_porifera = ["sponge", "porifera"]

# Check Mollusca viruses for mismatches
mollusca_mismatch = []
for name in by_phylum.get("Mollusca", []):
    lower = name.lower()
    is_legit = any(k in lower for k in legit_mollusca)
    if not is_legit:
        mollusca_mismatch.append(name)

print(f"\n=== Mollusca Mismatches ({len(mollusca_mismatch)} / {len(by_phylum.get('Mollusca', []))}) ===")
for name in mollusca_mismatch[:20]:
    print(f"  {name}")

# Check what articles a few legit vs mismatch viruses got
phylum_articles = {}
for phylum_name in ["mollusca", "cnidaria", "echinodermata", "porifera"]:
    path = os.path.join(BASE_DIR, "downloads", "literature_all_viruses_search", "phylum_search", f"{phylum_name}_articles.json")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        for art in data.get("articles", []):
            pmid = art.get("pmid", "")
            title = (art.get("title") or "")[:80]
            phylum_articles[pmid] = (title, phylum_name.capitalize())

print("\n=== Sample legit Mollusca virus articles ===")
for vid in phylum_only:
    v = viruses[vid]
    if v.get("host_phylum") == "Mollusca" and "abalone" in v["canonical_name"].lower():
        print(f"\n{v['canonical_name']}")
        for e in vl_map[vid][:3]:
            pmid = e["pmid"]
            title, ph = phylum_articles.get(pmid, ("?", "?"))
            print(f"  PMID:{pmid} [{ph}] {title}")
        break

print("\n=== Sample mismatch Mollusca virus articles ===")
for name in mollusca_mismatch[:3]:
    for vid, v in viruses.items():
        if v["canonical_name"] == name:
            print(f"\n{v['canonical_name']}")
            for e in vl_map[vid][:3]:
                pmid = e["pmid"]
                title, ph = phylum_articles.get(pmid, ("?", "?"))
                print(f"  PMID:{pmid} [{ph}] {title}")
            break

# Overall assessment
print("\n" + "="*60)
print("VERDICT")
print("="*60)
print(f"Total phylum-only: {len(phylum_only)}")
print(f"Mollusca mismatches: {len(mollusca_mismatch)} ({len(mollusca_mismatch)/len(phylum_only)*100:.1f}% of phylum-only)")
print(f"Legitimate phylum matches: {len(phylum_only) - len(mollusca_mismatch)}")
print(f"\n100% coverage is TECHNICALLY TRUE (all 834 have >=1 article)")
print(f"But {len(mollusca_mismatch)} viruses are mis-classified in DB and got wrong-phylum articles.")
