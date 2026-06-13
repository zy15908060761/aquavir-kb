#!/usr/bin/env python3
"""
Multi-source literature mining for crustacean virus virulence & temperature data.

Sources:
  1. GenBank-linked PMIDs — papers that sequenced the virus (guaranteed relevant)
  2. Semantic Scholar API — free, covers more venues than PubMed
  3. PubMed via NCBI E-utilities — expanded flexible queries
  4. CNKI (中国知网) — Chinese aquaculture literature (manual export step)

Strategy:
  Phase 1: Extract all PMIDs from GenBank records → fetch abstracts → extract data
  Phase 2: For top 30 viruses, search PubMed + Semantic Scholar with expanded queries
  Phase 3: Generate structured review queue for manual curation

Output:
  external_data/multi_source_mining/
    genbank_seeds/  — candidates from GenBank-linked papers
    pubmed_expanded/ — candidates from expanded PubMed search
    s2_results/     — Semantic Scholar results
    master_review_queue.csv — unified review queue
"""

import csv
import json
import re
import os
import sys
import time
import sqlite3
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from datetime import datetime
from collections import defaultdict, Counter

# ── Config ──
DB_PATH = Path(r"F:\甲壳动物数据库\crustacean_virus_core.db")
OUT_DIR = Path(r"F:\甲壳动物数据库\external_data\multi_source_mining")
OUT_DIR.mkdir(parents=True, exist_ok=True)

NCBI_API_KEY = os.environ.get("NCBI_API_KEY", "")
RATE_LIMIT = 0.35 if not NCBI_API_KEY else 0.12

# ── Target virus list: prioritize those with NO experimental data ──
PRIORITY_VIRUSES = [
    # Already have data — still mine for more details
    "White spot syndrome virus",
    "Yellow head virus",
    "Taura syndrome virus",
    "Infectious hypodermal and hematopoietic necrosis virus",
    "Penaeid shrimp infectious myonecrosis virus",
    "Macrobrachium rosenbergii nodavirus",
    # High-priority: known pathogens, missing virulence data
    "Decapod iridescent virus",
    "Covert mortality nodavirus",
    "Hepatopancreatic parvovirus",
    "Mud crab virus",
    "Chinese mitten crab virus",
    "Laem-Singh virus",
    "Wenzhou shrimp virus",
    "Macrobrachium rosenbergii Golda virus",
    # Emerging / regional
    "Penaeus vannamei nodavirus",
    "Lymphoid organ parvo-like virus",
    "Shrimp hemocyte iridescent virus",
    "Chequa iflavirus",
    "Callinectes sapidus reovirus",
    "Eriocheir sinensis reovirus",
]

# ── PubMed helpers ──
def pubmed_search(query: str, retmax: int = 200) -> list[str]:
    url = (
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
        f"?db=pubmed&term={urllib.request.quote(query)}"
        f"&retmax={retmax}&retmode=json"
    )
    if NCBI_API_KEY:
        url += f"&api_key={NCBI_API_KEY}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "crustacean-db/2.0"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data.get("esearchresult", {}).get("idlist", [])
    except Exception as e:
        print(f"    [PubMed search error] {e}")
        return []


def pubmed_fetch_abstracts(pmids: list[str]) -> str:
    if not pmids:
        return ""
    ids = ",".join(pmids)
    url = (
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
        f"?db=pubmed&id={ids}&retmode=xml"
    )
    if NCBI_API_KEY:
        url += f"&api_key={NCBI_API_KEY}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "crustacean-db/2.0"})
        with urllib.request.urlopen(req, timeout=120) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        print(f"    [PubMed fetch error] {e}")
        return ""


def parse_pubmed_xml(xml_text: str) -> list[dict]:
    if not xml_text:
        return []
    articles = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []
    for article in root.findall(".//PubmedArticle"):
        pmid = (article.find(".//PMID").text if article.find(".//PMID") is not None else "")
        title = (article.find(".//ArticleTitle").text if article.find(".//ArticleTitle") is not None else "")
        abstract_elems = article.findall(".//Abstract/AbstractText")
        abstract = " ".join((e.text or "") for e in abstract_elems)
        year_elem = article.find(".//PubDate/Year")
        year = year_elem.text if year_elem is not None else ""
        journal_elem = article.find(".//Journal/Title")
        journal = journal_elem.text if journal_elem is not None else ""
        articles.append({"pmid": pmid, "title": title, "abstract": abstract,
                         "year": year, "journal": journal})
    return articles


# ── Extraction engines ──
def extract_data_from_text(text: str, pmid="", year="", title="") -> list[dict]:
    """Extract temperature, mortality, and virulence from article text."""
    findings = []
    text_lower = text.lower()

    # ── Temperature extraction ──
    temp_rules = [
        # Range: "25°C to 30°C" or "25-30 °C"
        (re.compile(r"(\d+(?:\.\d+)?)\s*°?\s*C\s*(?:to|–|-)\s*(\d+(?:\.\d+)?)\s*°?\s*C", re.I),
         lambda m, ctx: "optimal" if any(k in ctx for k in ["optimal","optimum","preferred","best","ideal"])
         else ("thermal_inactivation" if any(k in ctx for k in ["inactivat","kill","destroy"])
         else ("survival" if any(k in ctx for k in ["surviv","persist","stable","storage"])
         else "range"))),
        # Single temp with context keyword
        (re.compile(r"(?:optimal|optimum|preferred)\s+temp(?:erature)?[:\s]*(\d+(?:\.\d+)?)\s*°?\s*C", re.I),
         lambda m, ctx: "optimal"),
        (re.compile(r"(?:inactivated|inactivation)\s+.*?(?:at|above)\s+(\d+(?:\.\d+)?)\s*°?\s*C", re.I),
         lambda m, ctx: "thermal_inactivation"),
        (re.compile(r"(\d+(?:\.\d+)?)\s*°?\s*C\s*(?:for\s+\d+\s*min.*?(?:inactivat|kill|complete))", re.I),
         lambda m, ctx: "thermal_inactivation"),
        (re.compile(r"(?:survive|survival|viable)\s+.*?(?:at|up\s+to)\s+(\d+(?:\.\d+)?)\s*°?\s*C", re.I),
         lambda m, ctx: "survival"),
        (re.compile(r"cold\s+(?:storage|temperature).*?(\d+(?:\.\d+)?)\s*°?\s*C", re.I),
         lambda m, ctx: "cold_storage"),
    ]

    for pat, categorizer in temp_rules:
        for m in pat.finditer(text):
            start = max(0, m.start() - 80)
            end = min(len(text), m.end() + 80)
            ctx = text_lower[start:end]
            category = categorizer(m, ctx)
            vals = [float(v) for v in m.groups() if v and v.replace('.','').isdigit()]
            if vals:
                findings.append({
                    "pmid": pmid, "year": year, "title": title[:120],
                    "category": f"temperature_{category}",
                    "value": str(vals[0]) if len(vals) == 1 else f"{min(vals)}-{max(vals)}",
                    "raw_match": m.group(0),
                    "context_window": text[max(0,m.start()-50):min(len(text),m.end()+50)],
                    "source": "pubmed",
                    "confidence": "needs_review",
                })

    # ── Mortality / virulence extraction ──
    vir_rules = [
        (re.compile(r"(?:cumulative\s+)?mortality\s+(?:rate\s+)?(?:of\s+)?(?:was\s+)?(?:up\s+to\s+)?(\d+(?:\.\d+)?)\s*%", re.I),
         "mortality_rate"),
        (re.compile(r"(\d+(?:\.\d+)?)\s*%\s*(?:cumulative\s+)?mortality", re.I),
         "mortality_rate"),
        (re.compile(r"LD50[:\s]*([<>=]?\s*\d+(?:\.\d+)?(?:\s*[×x]\s*10\^?\d+)?)", re.I),
         "LD50"),
        (re.compile(r"(?:highly|extremely)\s+(?:virulent|pathogenic)", re.I),
         "virulence_high"),
        (re.compile(r"moderate(?:ly)?\s+(?:virulent|pathogenic)", re.I),
         "virulence_moderate"),
        (re.compile(r"(?:low|non)[-\s](?:virulent|pathogenic)", re.I),
         "virulence_low"),
        (re.compile(r"(?:100|9\d|8\d)\s*%\s+(?:mortality|death|lethal)", re.I),
         "high_mortality_indicator"),
    ]

    for pat, category in vir_rules:
        for m in pat.finditer(text):
            val = m.group(1) if len(m.groups()) >= 1 else m.group(0)
            findings.append({
                "pmid": pmid, "year": year, "title": title[:120],
                "category": category,
                "value": val,
                "raw_match": m.group(0),
                "context_window": text[max(0,m.start()-50):min(len(text),m.end()+50)],
                "source": "pubmed",
                "confidence": "needs_review",
            })

    return findings


# ═══════════════════════════════════════
# Phase 1: GenBank-linked PMIDs
# ═══════════════════════════════════════
def phase1_genbank_seeds():
    """Extract PMIDs from GenBank records and fetch the most relevant papers first."""
    print("=" * 60)
    print("Phase 1: Mining GenBank-linked PMIDs")
    print("=" * 60)

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    # Get all PMIDs from infection_records that have references
    c.execute("""
        SELECT DISTINCT rl.pmid, vm.canonical_name as virus_name
        FROM ref_literatures rl
        JOIN isolate_reference_links irl ON rl.reference_id = irl.reference_id
        JOIN viral_isolates vi ON irl.isolate_id = vi.isolate_id
        JOIN virus_master vm ON vi.master_id = vm.master_id
        WHERE rl.pmid IS NOT NULL AND rl.pmid != ''
    """)
    pmid_virus_map = defaultdict(set)
    for row in c.fetchall():
        pmid_virus_map[row["pmid"]].add(row["virus_name"])

    conn.close()

    all_pmids = list(pmid_virus_map.keys())
    print(f"  Unique PMIDs from GenBank records: {len(all_pmids)}")
    print(f"  Associated viruses: {len(set().union(*pmid_virus_map.values()))}")

    # Fetch abstracts in batches
    seed_dir = OUT_DIR / "genbank_seeds"
    seed_dir.mkdir(exist_ok=True)

    all_candidates = []
    xml_path = seed_dir / "all_abstracts.xml"

    if xml_path.exists():
        print(f"  Using cached abstracts: {xml_path}")
        xml_text = xml_path.read_text(encoding="utf-8", errors="replace")
    else:
        print(f"  Fetching {len(all_pmids)} abstracts in batches of 100...")
        xml_parts = []
        for i in range(0, len(all_pmids), 100):
            batch = all_pmids[i:i+100]
            xml_parts.append(pubmed_fetch_abstracts(batch))
            time.sleep(RATE_LIMIT)
            if (i // 100) % 10 == 0:
                print(f"    {min(i+100, len(all_pmids))}/{len(all_pmids)}")
        xml_text = "\n".join(xml_parts)
        xml_path.write_text(xml_text, encoding="utf-8", errors="replace")

    articles = parse_pubmed_xml(xml_text)
    print(f"  Parsed {len(articles)} articles")

    for art in articles:
        viruses = pmid_virus_map.get(art["pmid"], set())
        if not viruses:
            continue
        full_text = f"{art['title']} {art['abstract']}"
        candidates = extract_data_from_text(full_text, art["pmid"], art["year"], art["title"])
        for c in candidates:
            c["virus_names"] = "; ".join(viruses)
        all_candidates.extend(candidates)

    # Save
    csv_path = seed_dir / "genbank_seed_candidates.csv"
    if all_candidates:
        fieldnames = list(all_candidates[0].keys())
        with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(all_candidates)
    print(f"  Extracted {len(all_candidates)} findings → {csv_path}")

    return all_candidates


# ═══════════════════════════════════════
# Phase 2: Expanded PubMed search
# ═══════════════════════════════════════
def phase2_pubmed_expanded():
    """Search PubMed with more flexible queries for priority viruses."""
    print("\n" + "=" * 60)
    print("Phase 2: Expanded PubMed search for priority viruses")
    print("=" * 60)

    pubmed_dir = OUT_DIR / "pubmed_expanded"
    pubmed_dir.mkdir(exist_ok=True)

    # More flexible search templates
    queries = {
        "temp_direct": '(("{name}") AND (temperature OR "thermal inactivation" OR "optimal temperature" OR "heat treatment"))',
        "vir_direct": '(("{name}") AND (virulence OR pathogenicity OR mortality OR "lethal dose" OR LD50))',
        "host_disease": '(("{name}") AND (infection OR disease OR outbreak OR epizootic))',
        "review": '(("{name}") AND (review[ptyp] AND (pathogenesis OR virulence OR temperature OR epidemiology)))',
    }

    all_candidates = []
    found_count = 0

    for virus_name in PRIORITY_VIRUSES:
        safe_name = re.sub(r"[^\w\s-]", "", virus_name).strip().replace(" ", "_")[:60]
        virus_dir = pubmed_dir / safe_name
        virus_dir.mkdir(exist_ok=True)

        # Check cache
        cache_file = virus_dir / "search_cache.json"
        if cache_file.exists():
            with open(cache_file, "r", encoding="utf-8") as f:
                cache = json.load(f)
        else:
            cache = {}

        virus_pmids = set()
        for qtype, template in queries.items():
            query = template.format(name=virus_name)
            cache_key = f"{safe_name}_{qtype}"

            if cache_key in cache:
                pmids = cache[cache_key]
            else:
                pmids = pubmed_search(query, retmax=50)
                cache[cache_key] = pmids
                time.sleep(RATE_LIMIT)

            virus_pmids.update(pmids)

        # Save cache
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(cache, f, indent=2)

        virus_pmids = list(virus_pmids)
        if not virus_pmids:
            continue

        print(f"\n  [{virus_name}]: {len(virus_pmids)} PMIDs")

        # Fetch abstracts
        abstracts_file = virus_dir / "abstracts.xml"
        if abstracts_file.exists():
            xml_text = abstracts_file.read_text(encoding="utf-8", errors="replace")
        else:
            xml_parts = []
            for i in range(0, len(virus_pmids), 100):
                batch = virus_pmids[i:i+100]
                xml_parts.append(pubmed_fetch_abstracts(batch))
                time.sleep(RATE_LIMIT)
            xml_text = "\n".join(xml_parts)
            abstracts_file.write_text(xml_text, encoding="utf-8", errors="replace")

        articles = parse_pubmed_xml(xml_text)

        # Extract data
        virus_candidates = []
        for art in articles:
            full_text = f"{art['title']} {art['abstract']}"
            candidates = extract_data_from_text(full_text, art["pmid"], art["year"], art["title"])
            for c in candidates:
                c["target_virus"] = virus_name
            virus_candidates.extend(candidates)

        if virus_candidates:
            found_count += 1
            csv_file = virus_dir / "candidates.csv"
            with open(csv_file, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.DictWriter(f, fieldnames=list(virus_candidates[0].keys()))
                writer.writeheader()
                writer.writerows(virus_candidates)
            print(f"    Found {len(virus_candidates)} candidate findings")
            all_candidates.extend(virus_candidates)

    print(f"\n  Viruses with findings: {found_count}/{len(PRIORITY_VIRUSES)}")
    print(f"  Total candidates: {len(all_candidates)}")

    return all_candidates


# ═══════════════════════════════════════
# Phase 3: Master review queue
# ═══════════════════════════════════════
def phase3_build_review_queue(seed_candidates, pubmed_candidates):
    """Merge all findings, deduplicate, rank by potential quality."""
    print("\n" + "=" * 60)
    print("Phase 3: Building master review queue")
    print("=" * 60)

    # Merge and normalize
    all_findings = []
    seen = set()

    for c in seed_candidates + pubmed_candidates:
        # Create dedup key
        key = f"{c.get('pmid','')}|{c.get('category','')}|{c.get('value','')}|{c.get('raw_match','')[:50]}"
        if key not in seen:
            seen.add(key)
            all_findings.append(c)

    # Rank: temperature + mortality findings together are most valuable
    # Group by PMID
    by_pmid = defaultdict(list)
    for f in all_findings:
        by_pmid[f.get("pmid", "")].append(f)

    # Score each PMID by variety of findings
    pmid_scores = {}
    for pmid, findings in by_pmid.items():
        categories = set(f["category"] for f in findings)
        score = len(findings) * (1 + len(categories))  # more categories → higher score
        pmid_scores[pmid] = score

    # Sort by score
    all_findings_sorted = sorted(all_findings, key=lambda f: pmid_scores.get(f.get("pmid",""), 0), reverse=True)

    # Save master queue
    master_csv = OUT_DIR / "master_review_queue.csv"
    if all_findings_sorted:
        fieldnames = list(all_findings_sorted[0].keys())
        with open(master_csv, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(all_findings_sorted)

    # Summary stats
    by_category = Counter(f["category"] for f in all_findings_sorted)
    print(f"  Total unique findings: {len(all_findings_sorted)}")
    print(f"  By category:")
    for cat, cnt in by_category.most_common():
        print(f"    {cat:30s}: {cnt:>5}")

    # Per-virus statistics (index by target_virus or virus_names)
    by_virus = defaultdict(int)
    for f in all_findings_sorted:
        targets = f.get("target_virus") or f.get("virus_names") or ""
        for v in targets.split("; "):
            if v:
                by_virus[v] += 1
    print(f"\n  Top viruses by findings:")
    for v, cnt in sorted(by_virus.items(), key=lambda x: -x[1])[:20]:
        has_exp = v.lower() in {
            "white spot syndrome virus", "yellow head virus", "taura syndrome virus",
            "infectious hypodermal and hematopoietic necrosis virus",
            "penaeid shrimp infectious myonecrosis virus",
            "macrobrachium rosenbergii nodavirus"
        }
        star = " [HAS EXP DATA]" if has_exp else " [PRIORITY]"
        print(f"    {cnt:>4} | {v[:50]}{star}")

    print(f"\n  Master queue saved: {master_csv}")
    return all_findings_sorted


# ═══════════════════════════════════════
# Phase 4: Structured import suggestions
# ═══════════════════════════════════════
def phase4_import_suggestions(all_findings):
    """
    Analyze findings and suggest structured imports for virulence_profiles
    and temperature_profiles tables.
    """
    print("\n" + "=" * 60)
    print("Phase 4: Import suggestions for database")
    print("=" * 60)

    # Group by target virus
    by_virus = defaultdict(lambda: {"temperature": [], "mortality": [], "virulence": []})

    for f in all_findings:
        targets = (f.get("target_virus") or f.get("virus_names") or "").split("; ")
        for v in targets:
            if not v:
                continue
            cat = f.get("category", "")
            if "temperature" in cat:
                by_virus[v]["temperature"].append(f)
            elif "mortality" in cat or "LD50" in cat or "virulence" in cat:
                by_virus[v]["mortality"].append(f)

    # Check which new viruses now have some data
    existing_data = {
        "white spot syndrome virus", "yellow head virus", "taura syndrome virus",
        "infectious hypodermal and hematopoietic necrosis virus",
        "penaeid shrimp infectious myonecrosis virus",
        "macrobrachium rosenbergii nodavirus",
    }

    print("\n  Viruses with NEW potential data (not in current experimental set):")
    newly_covered = []
    for v, data in sorted(by_virus.items(), key=lambda x: -(len(x[1]["temperature"]) + len(x[1]["mortality"]))):
        v_lower = v.lower().strip()
        if v_lower not in existing_data and (data["temperature"] or data["mortality"]):
            n_temp = len(data["temperature"])
            n_vir = len(data["mortality"])
            print(f"    {n_temp:>3} temp + {n_vir:>3} vir | {v[:60]}")
            newly_covered.append((v, n_temp, n_vir))

    print(f"\n  Potential new viruses with data: {len(newly_covered)}")
    print(f"  (After manual review, these could become new experimental labels)")

    # Suggest import format
    suggestions_csv = OUT_DIR / "import_suggestions.csv"
    with open(suggestions_csv, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "virus_name", "data_type", "suggested_value", "evidence_pmids",
            "confidence", "needs_review", "source_description"
        ])
        writer.writeheader()

        for v, data in sorted(by_virus.items()):
            # Temperature suggestions
            if data["temperature"]:
                temps = []
                pmids = set()
                for f in data["temperature"]:
                    try:
                        temps.append(float(f["value"]))
                    except ValueError:
                        pass
                    if f.get("pmid"):
                        pmids.add(f["pmid"])
                if temps:
                    writer.writerow({
                        "virus_name": v,
                        "data_type": "optimal_temp_range",
                        "suggested_value": f"{min(temps):.0f}-{max(temps):.0f} C",
                        "evidence_pmids": ";".join(list(pmids)[:5]),
                        "confidence": "medium" if len(temps) >= 3 else "low",
                        "needs_review": "YES",
                        "source_description": f"Extracted from {len(temps)} temperature mentions in {len(pmids)} papers",
                    })

            # Mortality suggestions
            if data["mortality"]:
                mortality_rates = []
                pmids = set()
                for f in data["mortality"]:
                    val_str = f["value"]
                    try:
                        mortality_rates.append(float(val_str.replace("%","").strip()))
                    except ValueError:
                        pass
                    if f.get("pmid"):
                        pmids.add(f["pmid"])
                if mortality_rates:
                    writer.writerow({
                        "virus_name": v,
                        "data_type": "mortality_rate",
                        "suggested_value": f"{min(mortality_rates):.0f}-{max(mortality_rates):.0f}%",
                        "evidence_pmids": ";".join(list(pmids)[:5]),
                        "confidence": "medium" if len(mortality_rates) >= 3 else "low",
                        "needs_review": "YES",
                        "source_description": f"Extracted from {len(mortality_rates)} mortality mentions in {len(pmids)} papers",
                    })

    print(f"  Import suggestions saved: {suggestions_csv}")


# ═══════════════════════════════════════
# MAIN
# ═══════════════════════════════════════
def main():
    print("=" * 60)
    print("Multi-Source Literature Mining")
    print(f"Output: {OUT_DIR}")
    print(f"Target viruses: {len(PRIORITY_VIRUSES)}")
    print("=" * 60)

    start = time.time()

    # Phase 1: GenBank seeds (most efficient — guaranteed relevant)
    seed_candidates = phase1_genbank_seeds()

    # Phase 2: Expanded PubMed search
    pubmed_candidates = phase2_pubmed_expanded()

    # Phase 3: Review queue
    all_findings = phase3_build_review_queue(seed_candidates, pubmed_candidates)

    # Phase 4: Import suggestions
    phase4_import_suggestions(all_findings)

    elapsed = time.time() - start
    print(f"\n{'='*60}")
    print(f"Done in {elapsed:.0f}s. Next steps:")
    print(f"  1. Review: {OUT_DIR / 'master_review_queue.csv'}")
    print(f"  2. Review import suggestions: {OUT_DIR / 'import_suggestions.csv'}")
    print(f"  3. For high-confidence findings, manually verify against full-text papers")
    print(f"  4. Import verified findings into virulence_profiles / temperature_profiles")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
