#!/usr/bin/env python3
"""
Step 1: Mine PubMed for virulence and temperature data of crustacean viruses.

Strategy:
  1. For each target virus (top N by isolate count), search PubMed for
     abstracts containing temperature/virulence/mortality keywords.
  2. Download abstracts via NCBI E-utilities (cached to disk).
  3. Extract numeric values (temperatures, mortality rates) using regex.
  4. Export curated candidates for manual review.

Usage:
    python step1_mine_pubmed_for_virulence_temp.py

Output:
    external_data/pubmed_virulence_temp/<virus_name>/
        - search_results.json
        - abstracts.xml
        - extracted_candidates.csv
    external_data/mined_virulence_temp_summary.csv
"""
from __future__ import annotations

import csv
import json
import os
import re
import sqlite3
import time
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from datetime import datetime

# ── Configuration ─────────────────────────────────────────────────
DB_PATH = Path(r"F:\甲壳动物数据库\crustacean_virus_core.db")
OUT_DIR = Path(r"F:\甲壳动物数据库\external_data\pubmed_virulence_temp")
OUT_DIR.mkdir(parents=True, exist_ok=True)
SUMMARY_CSV = Path(r"F:\甲壳动物数据库\external_data\mined_virulence_temp_summary.csv")

NCBI_API_KEY = os.environ.get("NCBI_API_KEY", "")
# Rate limit: ~3 req/sec without key, ~10/sec with key
RATE_LIMIT = 0.35 if not NCBI_API_KEY else 0.12

# How many top viruses to process (exclude Unknown/Unclassified/Non-crustacean)
TOP_N = 40

# PubMed search templates
SEARCH_TEMPLATE_TEMP = (
    '{virus_name}[Title/Abstract] AND (temperature[Title/Abstract] '
    'OR thermal[Title/Abstract] OR heat[Title/Abstract] OR cold[Title/Abstract])'
)
SEARCH_TEMPLATE_VIRULENCE = (
    '{virus_name}[Title/Abstract] AND (virulence[Title/Abstract] '
    'OR pathogenicity[Title/Abstract] OR mortality[Title/Abstract] '
    'OR lethal[Title/Abstract] OR LD50[Title/Abstract])'
)

# Regex patterns for extraction
TEMP_PATTERNS = [
    re.compile(r"(\d+(?:\.\d+)?)\s*°?C\s*(?:to|-|–)\s*(\d+(?:\.\d+)?)\s*°?C", re.I),
    re.compile(r"(?:optimal|optimum|preferred)\s+temp(?:erature)?.*?[:\s]\s*(\d+(?:\.\d+)?)\s*°?C", re.I),
    re.compile(r"(\d+(?:\.\d+)?)\s*°?C\s*(?:was|is)?\s*(?:the\s+)?optimal", re.I),
    re.compile(r"(?:replication|growth)\s+(?:at|occurs?\s+at)\s+(\d+(?:\.\d+)?)\s*°?C", re.I),
    re.compile(r"(?:inactivated|inactivation)\s+.*?at\s+(\d+(?:\.\d+)?)\s*°?C", re.I),
    re.compile(r"(?:survived|survival)\s+.*?at\s+(\d+(?:\.\d+)?)\s*°?C", re.I),
]

MORTALITY_PATTERNS = [
    re.compile(r"mortality\s+rate.*?[:\s]\s*(\d+(?:\.\d+)?)\s*%", re.I),
    re.compile(r"(\d+(?:\.\d+)?)\s*%\s*mortality", re.I),
    re.compile(r"(?:caused|induced|resulted\s+in)\s+(\d+(?:\.\d+)?)\s*%\s*(?:mortality|death)", re.I),
    re.compile(r"cumulative\s+mortality.*?[:\s]\s*(\d+(?:\.\d+)?)", re.I),
    re.compile(r"LD50.*?[:\s]\s*([<>=]?\s*\d+(?:\.\d+)?(?:\s*×?\s*10\^?\d+)?)", re.I),
    re.compile(r"(?:lethal|fatal)\s+dose.*?[:\s]\s*([<>=]?\s*\d+)", re.I),
]

# ── PubMed API wrappers ───────────────────────────────────────────
def esearch(query: str, retmax: int = 200) -> list[str]:
    """Search PubMed and return list of PMIDs."""
    url = (
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
        f"?db=pubmed&term={urllib.request.quote(query)}"
        f"&retmax={retmax}&retmode=json"
    )
    if NCBI_API_KEY:
        url += f"&api_key={NCBI_API_KEY}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "crustacean-db-miner/1.0"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data.get("esearchresult", {}).get("idlist", [])
    except Exception as exc:
        print(f"    [ESEARCH ERROR] {exc}")
        return []


def efetch_abstracts(pmids: list[str]) -> str:
    """Fetch abstracts for a list of PMIDs."""
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
        req = urllib.request.Request(url, headers={"User-Agent": "crustacean-db-miner/1.0"})
        with urllib.request.urlopen(req, timeout=120) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except Exception as exc:
        print(f"    [EFETCH ERROR] {exc}")
        return ""


# ── Abstract parsing ──────────────────────────────────────────────
def parse_abstracts(xml_text: str) -> list[dict]:
    """Parse PubMed XML and return list of article dicts."""
    if not xml_text:
        return []
    articles = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []

    for article in root.findall(".//PubmedArticle"):
        pmid_elem = article.find(".//PMID")
        pmid = pmid_elem.text if pmid_elem is not None else ""

        title_elem = article.find(".//ArticleTitle")
        title = title_elem.text if title_elem is not None else ""

        abstract_elems = article.findall(".//Abstract/AbstractText")
        abstract = " ".join(
            (e.text or "") for e in abstract_elems
        )

        year_elem = article.find(".//PubDate/Year")
        year = year_elem.text if year_elem is not None else ""

        articles.append({
            "pmid": pmid,
            "title": title,
            "abstract": abstract,
            "year": year,
        })
    return articles


# ── Extraction engines ────────────────────────────────────────────
def extract_temperatures(text: str) -> list[dict]:
    """Extract temperature-related values from text."""
    findings = []
    text_lower = text.lower()

    # Range patterns: e.g., "25°C to 30°C" or "25-30°C"
    for pat in TEMP_PATTERNS:
        for m in pat.finditer(text):
            vals = [float(v) for v in m.groups() if v]
            if not vals:
                continue
            # Determine context category by nearby keywords
            start = max(0, m.start() - 80)
            end = min(len(text), m.end() + 80)
            context = text_lower[start:end]

            category = "unknown"
            if any(k in context for k in ["optimal", "optimum", "preferred", "best"]):
                category = "optimal"
            elif any(k in context for k in ["inactivat", "kill", "destroy", "destroyed"]):
                category = "thermal_inactivation"
            elif any(k in context for k in ["surviv", "persist", "stable", "storage"]):
                category = "survival"
            elif any(k in context for k in ["replicat", "growth", "propagat", "multipl"]):
                category = "replication"
            elif any(k in context for k in ["range", "between", "from"]):
                category = "range"

            findings.append({
                "type": "temperature",
                "category": category,
                "values": vals,
                "match": m.group(0),
                "context": text[m.start():m.end()],
            })
    return findings


def extract_mortality(text: str) -> list[dict]:
    """Extract mortality / virulence values from text."""
    findings = []
    text_lower = text.lower()

    for pat in MORTALITY_PATTERNS:
        for m in pat.finditer(text):
            findings.append({
                "type": "mortality",
                "match": m.group(0),
                "value": m.group(1) if len(m.groups()) >= 1 else "",
            })

    # Also look for qualitative virulence descriptors
    virulence_keywords = {
        "highly virulent": "high", "high virulence": "high", "highly pathogenic": "high",
        "low virulence": "low", "low pathogenicity": "low", "avirulent": "low",
        "moderate virulence": "moderate", "moderate pathogenicity": "moderate",
        "non-pathogenic": "low", "nonpathogenic": "low",
    }
    for kw, level in virulence_keywords.items():
        if kw in text_lower:
            findings.append({
                "type": "virulence_qualitative",
                "match": kw,
                "value": level,
            })

    return findings


# ── Main pipeline ─────────────────────────────────────────────────
def get_target_viruses() -> list[dict]:
    """Fetch top N named viruses from database."""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("""
        SELECT vm.master_id, vm.canonical_name, vm.virus_family, COUNT(vi.isolate_id) as isolate_count
        FROM virus_master vm
        LEFT JOIN viral_isolates vi ON vm.master_id = vi.master_id
        WHERE vm.canonical_name IS NOT NULL
          AND vm.canonical_name != ''
          AND LOWER(vm.canonical_name) NOT LIKE '%unknown%'
          AND LOWER(vm.canonical_name) NOT LIKE '%unclassified%'
          AND LOWER(vm.canonical_name) NOT LIKE '%non-crustacean%'
        GROUP BY vm.master_id
        ORDER BY isolate_count DESC
        LIMIT ?
    """, (TOP_N,))
    viruses = [dict(row) for row in c.fetchall()]
    conn.close()
    return viruses


def process_virus(virus: dict) -> list[dict]:
    """Search PubMed, download abstracts, extract candidates for one virus."""
    name = virus["canonical_name"]
    safe_name = re.sub(r"[^\w\s-]", "", name).strip().replace(" ", "_")
    virus_dir = OUT_DIR / safe_name[:60]
    virus_dir.mkdir(exist_ok=True)

    print(f"\n[{name}] ({virus['isolate_count']} isolates)")

    # Check cache
    results_file = virus_dir / "search_results.json"
    if results_file.exists():
        with open(results_file, "r", encoding="utf-8") as f:
            cached = json.load(f)
        print(f"  Using cached results ({len(cached.get('temp_pmids', []))} temp + {len(cached.get('vir_pmids', []))} virulence)")
        temp_pmids = cached.get("temp_pmids", [])
        vir_pmids = cached.get("vir_pmids", [])
    else:
        # Search temperature literature
        print("  Searching PubMed for temperature...")
        q_temp = SEARCH_TEMPLATE_TEMP.format(virus_name=name)
        temp_pmids = esearch(q_temp)
        time.sleep(RATE_LIMIT)

        # Search virulence literature
        print("  Searching PubMed for virulence...")
        q_vir = SEARCH_TEMPLATE_VIRULENCE.format(virus_name=name)
        vir_pmids = esearch(q_vir)
        time.sleep(RATE_LIMIT)

        with open(results_file, "w", encoding="utf-8") as f:
            json.dump({"temp_pmids": temp_pmids, "vir_pmids": vir_pmids, "timestamp": datetime.now().isoformat()}, f, indent=2)
        print(f"  Found {len(temp_pmids)} temp + {len(vir_pmids)} virulence articles")

    # Fetch abstracts (deduplicate PMIDs)
    all_pmids = list(dict.fromkeys(temp_pmids + vir_pmids))
    if not all_pmids:
        return []

    abstracts_file = virus_dir / "abstracts.xml"
    if abstracts_file.exists():
        xml_text = abstracts_file.read_text(encoding="utf-8")
    else:
        print(f"  Fetching {len(all_pmids)} abstracts...")
        # Fetch in batches of 100 to avoid URL too long
        xml_parts = []
        for i in range(0, len(all_pmids), 100):
            batch = all_pmids[i:i+100]
            xml_parts.append(efetch_abstracts(batch))
            time.sleep(RATE_LIMIT)
        xml_text = "\n".join(xml_parts)
        abstracts_file.write_text(xml_text, encoding="utf-8")

    articles = parse_abstracts(xml_text)
    print(f"  Parsed {len(articles)} articles")

    # Extract candidates
    candidates = []
    for art in articles:
        full_text = f"{art['title']} {art['abstract']}"
        temp_findings = extract_temperatures(full_text)
        vir_findings = extract_mortality(full_text)

        for f in temp_findings:
            candidates.append({
                "virus_name": name,
                "virus_family": virus.get("virus_family", ""),
                "pmid": art["pmid"],
                "year": art["year"],
                "finding_type": f"temp_{f['category']}",
                "value": ";".join(str(v) for v in f["values"]),
                "match_text": f["match"],
                "evidence": "pubmed_mined",
                "confidence": "low",  # default; needs human review
            })

        for f in vir_findings:
            candidates.append({
                "virus_name": name,
                "virus_family": virus.get("virus_family", ""),
                "pmid": art["pmid"],
                "year": art["year"],
                "finding_type": f"vir_{f['type']}",
                "value": f["value"],
                "match_text": f["match"],
                "evidence": "pubmed_mined",
                "confidence": "low",
            })

    # Save per-virus CSV
    csv_file = virus_dir / "extracted_candidates.csv"
    with open(csv_file, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "virus_name", "virus_family", "pmid", "year",
            "finding_type", "value", "match_text", "evidence", "confidence"
        ])
        writer.writeheader()
        writer.writerows(candidates)

    print(f"  Extracted {len(candidates)} candidate findings -> {csv_file}")
    return candidates


def aggregate_summary(all_candidates: list[dict]) -> None:
    """Aggregate all candidates into a summary CSV for manual review."""
    with open(SUMMARY_CSV, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "virus_name", "virus_family", "pmid", "year",
            "finding_type", "value", "match_text", "evidence", "confidence"
        ])
        writer.writeheader()
        writer.writerows(all_candidates)
    print(f"\n{'='*60}")
    print(f"Summary saved: {SUMMARY_CSV}")
    print(f"Total candidate findings: {len(all_candidates)}")

    # Quick stats
    by_virus = {}
    by_type = {}
    for c in all_candidates:
        by_virus[c["virus_name"]] = by_virus.get(c["virus_name"], 0) + 1
        by_type[c["finding_type"]] = by_type.get(c["finding_type"], 0) + 1

    print("\nTop viruses by candidate count:")
    for v, cnt in sorted(by_virus.items(), key=lambda x: -x[1])[:10]:
        print(f"  {cnt:>4} | {v}")

    print("\nFinding types:")
    for t, cnt in sorted(by_type.items(), key=lambda x: -x[1]):
        print(f"  {cnt:>4} | {t}")


def main():
    print("=" * 60)
    print("Step 1: Mining PubMed for virulence & temperature data")
    print("=" * 60)
    print(f"Database: {DB_PATH}")
    print(f"Target: top {TOP_N} named viruses")
    print(f"Rate limit: {RATE_LIMIT}s between requests")
    if NCBI_API_KEY:
        print("NCBI API key: detected")
    else:
        print("NCBI API key: NOT SET (set env NCBI_API_KEY for faster mining)")

    viruses = get_target_viruses()
    print(f"\nWill process {len(viruses)} viruses")

    all_candidates = []
    for i, v in enumerate(viruses, 1):
        print(f"\n[{i}/{len(viruses)}] ", end="")
        candidates = process_virus(v)
        all_candidates.extend(candidates)

    aggregate_summary(all_candidates)
    print("\nDone! Next: review the summary CSV and curate high-confidence entries.")
    print("Then run step2_extract_virus_features.py")


if __name__ == "__main__":
    main()
