#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Audit quality of phylum-only matches."""

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

# Find phylum-only viruses with suspicious names
suspicious = []
for vid, entries in vl_map.items():
    ev_types = set()
    for e in entries:
        ev_types.update(e.get("evidence_type", "").split("|"))
    if ev_types != {"phylum"}:
        continue
    v = viruses[vid]
    name = v["canonical_name"].lower()
    phylum = v.get("host_phylum", "")
    red_flags = ["human", "hepatovirus", "salivirus", "aichivirus", "coxsackie", "mimivirus",
                 "mushroom", "baculovirus", "insect", "mosquito", "phasmavirus",
                 " influenza", "hiv", "immunodeficiency", "enterovirus", "parechovirus",
                 "cardiovirus", "kobuvirus", "rhinovirus", "rotavirus", "astrovirus"]
    flagged = [f for f in red_flags if f in name]
    if flagged:
        suspicious.append((v["canonical_name"], phylum, flagged))

print(f"Suspicious phylum-only viruses: {len(suspicious)}")
for name, phylum, flags in suspicious[:30]:
    print(f"  [{phylum}] {name}  -> flags: {flags}")

# Load phylum articles
phylum_articles = {}
for phylum_name in ["mollusca", "cnidaria", "echinodermata", "porifera"]:
    path = os.path.join(BASE_DIR, "downloads", "literature_all_viruses_search", "phylum_search", f"{phylum_name}_articles.json")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        for art in data.get("articles", []):
            phylum_articles[art.get("pmid", "")] = (art.get("title", "")[:80], phylum_name.capitalize())

# Show sample articles for a few phylum-only viruses
print("\n=== Sample phylum article assignments ===")
count = 0
for vid, entries in vl_map.items():
    ev_types = set()
    for e in entries:
        ev_types.update(e.get("evidence_type", "").split("|"))
    if ev_types == {"phylum"}:
        v = viruses[vid]
        print(f"\n{v['canonical_name']} [{v.get('host_phylum','')}]")
        for e in entries[:3]:
            pmid = e["pmid"]
            title, ph = phylum_articles.get(pmid, ("?", "?"))
            print(f"  PMID:{pmid} [{ph}] {title}")
        count += 1
        if count >= 10:
            break

# Summary of truly problematic
print(f"\n=== TRULY PROBLEMATIC (clearly wrong host) ===")
problem_hosts = {
    "Hepatovirus A": "human hepatitis A virus",
    "Salivirus A": "human salivirus",
    "aichivirus A1": "human Aichi virus",
    "Coxsackievirus A1": "human enterovirus",
    "Acanthamoeba polyphaga mimivirus": "amoeba virus (protist)",
    "Oyster mushroom spherical virus": "fungal virus",
    "Nilaparvata lugens bunyavirus 3": "brown planthopper (insect)",
    "Nilaparvata lugens bunyavirus 2": "brown planthopper (insect)",
    "Fushun phasmavirus 2": "insect virus",
}
for name, real_host in problem_hosts.items():
    found = False
    for vid, v in viruses.items():
        if v["canonical_name"] == name:
            entries = vl_map.get(vid, [])
            ev = set()
            for e in entries:
                ev.update(e.get("evidence_type", "").split("|"))
            print(f"  {name}")
            print(f"    DB says: {v.get('host_phylum', '?')}, Real host: {real_host}")
            print(f"    Evidence types: {ev}")
            found = True
            break
    if not found:
        print(f"  {name} NOT FOUND in DB")
