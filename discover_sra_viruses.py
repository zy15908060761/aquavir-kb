"""
discover_sra_viruses.py — Analyze SRA metagenome data for novel aquatic
invertebrate virus signals.

Phases:
  A. Survey the existing sra_runs table in the database
  B. Cross-reference sra_runs against virus_master
  C. Search NCBI SRA for new aquatic invertebrate virome projects (2024-2026)
  D. Generate a candidate novel-virus CSV and a discovery report

Usage:
    python discover_sra_viruses.py
    python discover_sra_viruses.py --dry-run        # skip NCBI queries
    python discover_sra_viruses.py --skip-ncbi       # skip NCBI queries
    python discover_sra_viruses.py --skip-db-write   # do not insert evidence
"""

import csv
import json
import sqlite3
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "crustacean_virus_core.db"
REPORT_DIR = BASE_DIR / "reports"
NCBI_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
NCBI_RATE = 0.35  # seconds between requests (NCBI guideline: ≤3/sec)

# ── Aquatic invertebrate phyla we care about ──────────────────────────────
AQUATIC_INVERT_PHYLA = [
    "Mollusca", "Arthropoda", "Cnidaria", "Porifera",
    "Echinodermata", "Annelida", "Nematoda", "Platyhelminthes",
    "Rotifera", "Tunicata", "Bryozoa", "Brachiopoda",
]

# ── SRA search queries for aquatic invertebrate viromes ──────────────────
SRA_QUERIES = [
    # Mollusca
    ("mollusk_virome", '("oyster virome" OR "mussel virome" OR "abalone virome" '
     'OR "clam virome" OR "scallop virome" OR "bivalve virome") '
     'AND ("virus" OR "viral" OR "metagenome")'),
    ("mollusk_raw", '("Crassostrea" OR "Mytilus" OR "Haliotis" OR "Ruditapes") '
     'AND ("RNA-seq" OR "total RNA" OR "metagenome")'),
    # Crustacea
    ("crustacean_virome", '("shrimp virome" OR "crab virome" OR "crayfish virome" '
     'OR "crustacean virome" OR "copepod virome")'),
    ("decapod_metagenome", '("Penaeus" OR "Litopenaeus" OR "Macrobrachium" OR '
     '"Eriocheir" OR "Procambarus") AND ("metagenome" OR "virome")'),
    # Cnidaria
    ("coral_virome", '("coral virome" OR "coral metagenome" OR "cnidarian virome" '
     'OR "Acropora virome" OR "Pocillopora virome")'),
    ("jellyfish_virome", '("jellyfish virome" OR "Aurelia virome" OR "Hydra virome")'),
    # Porifera
    ("sponge_virome", '("sponge virome" OR "sponge metagenome" OR "Porifera virome" '
     'OR "demosponge virome")'),
    # Echinodermata
    ("echinoderm_virome", '("sea cucumber virome" OR "sea urchin virome" '
     'OR "starfish virome" OR "holothurian virome" OR "echinoderm virome")'),
    # Annelida / Nemertea
    ("annelid_worm_virome", '("polychaete virome" OR "ragworm virome" '
     'OR "Nereis virome" OR "annelid metagenome")'),
    # Cross-phylum
    ("marine_invert_virome", '("aquatic invertebrate virome" OR "marine invertebrate '
     'virome" OR "invertebrate metagenome virome")'),
    ("invertebrate_viral_discovery", '("viral discovery" OR "novel virus" OR '
     '"virus hunting") AND ("invertebrate" OR "crustacean" OR "mollusk")'),
    ("aquatic_invert_RNAseq", '("RNA-seq" AND "invertebrate" AND "virus")'),
]

# ── Mapping known host keywords → phylum ──────────────────────────────────
HOST_PHYLUM_KEYWORDS = {
    # Mollusca
    "oyster": "Mollusca", "Crassostrea": "Mollusca", "Saccostrea": "Mollusca",
    "Ostrea": "Mollusca", "mussel": "Mollusca", "Mytilus": "Mollusca",
    "Perna": "Mollusca", "clam": "Mollusca", "Ruditapes": "Mollusca",
    "Venerupis": "Mollusca", "Mercenaria": "Mollusca", "abalone": "Mollusca",
    "Haliotis": "Mollusca", "scallop": "Mollusca", "Pecten": "Mollusca",
    "Argopecten": "Mollusca", "Chlamys": "Mollusca", "Mizuhopecten": "Mollusca",
    "squid": "Mollusca", "octopus": "Mollusca", "Sepia": "Mollusca",
    "Loligo": "Mollusca", "bivalve": "Mollusca", "gastropod": "Mollusca",
    "cephalopod": "Mollusca", "mollusc": "Mollusca", "mollusk": "Mollusca",
    # Arthropoda
    "shrimp": "Arthropoda", "Penaeus": "Arthropoda", "Litopenaeus": "Arthropoda",
    "Macrobrachium": "Arthropoda", "crab": "Arthropoda", "Eriocheir": "Arthropoda",
    "Portunus": "Arthropoda", "Carcinus": "Arthropoda", "crayfish": "Arthropoda",
    "Procambarus": "Arthropoda", "Cherax": "Arthropoda", "lobster": "Arthropoda",
    "Homarus": "Arthropoda", "copepod": "Arthropoda", "Calanus": "Arthropoda",
    "krill": "Arthropoda", "Euphausia": "Arthropoda", "Daphnia": "Arthropoda",
    "Artemia": "Arthropoda", "barnacle": "Arthropoda", "amphipod": "Arthropoda",
    "isopod": "Arthropoda", "ostracod": "Arthropoda", "cirripedia": "Arthropoda",
    "decapod": "Arthropoda", "crustacean": "Arthropoda",
    # Cnidaria
    "coral": "Cnidaria", "Acropora": "Cnidaria", "Porites": "Cnidaria",
    "Pocillopora": "Cnidaria", "Stylophora": "Cnidaria", "anemone": "Cnidaria",
    "Nematostella": "Cnidaria", "Exaiptasia": "Cnidaria", "jellyfish": "Cnidaria",
    "Aurelia": "Cnidaria", "Hydra": "Cnidaria", "cnidarian": "Cnidaria",
    # Porifera
    "sponge": "Porifera", "Amphimedon": "Porifera", "Ephydatia": "Porifera",
    "demosponge": "Porifera", "porifera": "Porifera",
    # Echinodermata
    "sea cucumber": "Echinodermata", "Apostichopus": "Echinodermata",
    "Holothuria": "Echinodermata", "sea urchin": "Echinodermata",
    "Strongylocentrotus": "Echinodermata", "Paracentrotus": "Echinodermata",
    "starfish": "Echinodermata", "sea star": "Echinodermata",
    "Asterias": "Echinodermata", "echinoderm": "Echinodermata",
    # Annelida
    "polychaete": "Annelida", "ragworm": "Annelida", "Nereis": "Annelida",
    "earthworm": "Annelida", "annelid": "Annelida",
    # Nematoda
    "nematode": "Nematoda", "Caenorhabditis": "Nematoda",
    # Platyhelminthes
    "flatworm": "Platyhelminthes", "planarian": "Platyhelminthes",
    "Schmidtea": "Platyhelminthes",
    # Rotifera
    "rotifer": "Rotifera", "Brachionus": "Rotifera",
    # Tunicata
    "tunicate": "Tunicata", "ascidian": "Tunicata", "Ciona": "Tunicata",
}

# ── Common environmental / non-target filters ────────────────────────────
NON_TARGET_KEYWORDS = [
    "human", "Homo sapiens", "mouse", "Mus musculus", "zebrafish",
    "Danio rerio", "Escherichia", "bacteria", "soil", "wastewater",
    "sewage", "freshwater", "marine water", "sediment", "gut content",
    "stool", "fecal", "oral", "nasal", "blood", "serum", "plasma",
    "clinical", "patient", "lung", "liver", "kidney", "brain",
    "plant", "Arabidopsis", "rice", "wheat", "maize",
]


# ═══════════════════════════════════════════════════════════════════════════
#  Utility Functions
# ═══════════════════════════════════════════════════════════════════════════

def log(msg: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] {msg}")


def ncbi_request(endpoint: str, params: dict, db: str = "sra") -> str | None:
    """Rate-limited NCBI E-utilities call, returns raw XML."""
    params["db"] = db
    params["retmode"] = "xml"
    qs = urllib.parse.urlencode(params)
    url = f"{NCBI_BASE}/{endpoint}?{qs}"
    time.sleep(NCBI_RATE)
    try:
        req = urllib.request.Request(url)
        req.add_header("User-Agent", "AquaVir-KB/2.0")
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.read().decode("utf-8")
    except Exception as e:
        log(f"  NCBI error ({url[:80]}...): {e}")
        return None


def classify_host_phylum(title: str, organism: str) -> str | None:
    """Try to determine host phylum from SRA run title / organism field."""
    text = f"{title} {organism}".lower()
    # Check explicit keyword matches
    for keyword, phylum in HOST_PHYLUM_KEYWORDS.items():
        if keyword.lower() in text:
            return phylum
    return None


def is_non_target(title: str, organism: str) -> bool:
    """Check if a run is from a clearly non-target source."""
    text = f"{title} {organism}".lower()
    nope_matches = sum(1 for kw in NON_TARGET_KEYWORDS if kw.lower() in text)
    return nope_matches >= 2


def guess_virus_family(title: str) -> str | None:
    """Guess virus family from run title keywords."""
    title_lower = title.lower()
    family_map = {
        "nimaviridae": "Nimaviridae",
        "whispovirus": "Nimaviridae",
        "wssv": "Nimaviridae",
        "iridoviridae": "Iridoviridae",
        "iridovirus": "Iridoviridae",
        "malacoherpesviridae": "Malacoherpesviridae",
        "malacoherpesvirus": "Malacoherpesviridae",
        "oshv": "Malacoherpesviridae",
        "nodaviridae": "Nodaviridae",
        "nodavirus": "Nodaviridae",
        "circoviridae": "Circoviridae",
        "circovirus": "Circoviridae",
        "parvoviridae": "Parvoviridae",
        "densovirus": "Parvoviridae",
        "dicistroviridae": "Dicistroviridae",
        "picornavirales": "Picornavirales",
        "iflaviridae": "Iflaviridae",
        "bunyaviridae": "Bunyaviridae",
        "rhabdoviridae": "Rhabdoviridae",
        "reoviridae": "Reoviridae",
        "totiviridae": "Totiviridae",
        "partitiviridae": "Partitiviridae",
        "coronaviridae": "Coronaviridae",
        "flaviviridae": "Flaviviridae",
        "togaviridae": "Togaviridae",
        "hepadnaviridae": "Hepadnaviridae",
        "picornavirus": "Picornaviridae",
        "caliciviridae": "Caliciviridae",
        "astroviridae": "Astroviridae",
        "herpesvirales": "Herpesvirales",
    }
    for kw, family in family_map.items():
        if kw in title_lower:
            return family
    return None


# ═══════════════════════════════════════════════════════════════════════════
#  Phase A — Survey sra_runs table
# ═══════════════════════════════════════════════════════════════════════════

def phase_a_survey(conn: sqlite3.Connection) -> dict:
    """Survey the sra_runs table and return summary stats."""
    log("=" * 60)
    log("PHASE A: Survey existing sra_runs table")
    log("=" * 60)

    cur = conn.cursor()

    # Get schema
    cur.execute("PRAGMA table_info(sra_runs)")
    cols = [(r[1], r[2]) for r in cur.fetchall()]
    log(f"  sra_runs columns ({len(cols)}): {[c[0] for c in cols]}")

    # Row count
    cur.execute("SELECT COUNT(*) FROM sra_runs")
    total_runs = cur.fetchone()[0]
    log(f"  Total runs: {total_runs}")

    # Count runs with taxonomy classification
    taxonomy_cols = [c[0] for c in cols if "tax" in c[0].lower() or "phylum" in c[0].lower()]
    if taxonomy_cols:
        for tc in taxonomy_cols:
            cur.execute(f"SELECT COUNT(*) FROM sra_runs WHERE {tc} IS NOT NULL AND {tc} != ''")
            cnt = cur.fetchone()[0]
            log(f"  Runs with {tc}: {cnt}/{total_runs}")

    # Count by host_phylum if column exists
    phylum_counts = {}
    if "host_phylum" in [c[0] for c in cols]:
        cur.execute("SELECT host_phylum, COUNT(*) FROM sra_runs "
                    "WHERE host_phylum IS NOT NULL GROUP BY host_phylum ORDER BY 2 DESC")
        for row in cur.fetchall():
            phylum_counts[row[0]] = row[1]
            log(f"    {row[0]}: {row[1]}")
    else:
        log("  No host_phylum column, will infer from title/organism")

    # Count by associated virus
    virus_cols = ["virus_name", "virus_family", "associated_virus"]
    virus_col = None
    for vc in virus_cols:
        if vc in [c[0] for c in cols]:
            virus_col = vc
            cur.execute(f"SELECT COUNT(*) FROM sra_runs WHERE {vc} IS NOT NULL AND {vc} != ''")
            cnt = cur.fetchone()[0]
            log(f"  Runs with {vc}: {cnt}/{total_runs}")
            break

    # Count by year
    if "year" in [c[0] for c in cols]:
        cur.execute("SELECT year, COUNT(*) FROM sra_runs WHERE year IS NOT NULL "
                    "GROUP BY year ORDER BY year DESC LIMIT 10")
        log("  Runs by year:")
        for row in cur.fetchall():
            log(f"    {row[0]}: {row[1]}")

    # Count by platform if exists
    if "platform" in [c[0] for c in cols]:
        cur.execute("SELECT platform, COUNT(*) FROM sra_runs "
                    "WHERE platform IS NOT NULL GROUP BY platform")
        for row in cur.fetchall():
            log(f"    Platform {row[0]}: {row[1]}")

    # Sample 5 runs to see content
    cur.execute("SELECT * FROM sra_runs LIMIT 3")
    sample_cols = [desc[0] for desc in cur.description]
    log(f"  Sample columns: {sample_cols}")
    samples = []
    for row in cur.fetchall():
        samples.append(dict(zip(sample_cols, row)))
        log(f"    Run sample: {dict(zip(sample_cols, row))}")

    return {
        "columns": [c[0] for c in cols],
        "total_runs": total_runs,
        "phylum_counts": phylum_counts,
        "sample_data": samples,
    }


# ═══════════════════════════════════════════════════════════════════════════
#  Phase B — Cross-reference with virus_master
# ═══════════════════════════════════════════════════════════════════════════

def phase_b_crossref(conn: sqlite3.Connection, survey: dict) -> dict:
    """Cross-reference sra_runs against virus_master and evidence tables."""
    log("=" * 60)
    log("PHASE B: Cross-reference with virus_master")
    log("=" * 60)

    cur = conn.cursor()

    # Check virus_master
    cur.execute("PRAGMA table_info(virus_master)")
    vm_cols = [r[1] for r in cur.fetchall()]
    log(f"  virus_master columns: {vm_cols}")

    cur.execute("SELECT COUNT(*) FROM virus_master")
    vm_count = cur.fetchone()[0]
    log(f"  Total virus_master entries: {vm_count}")

    # Get all virus names for matching
    cur.execute("SELECT virus_name FROM virus_master ORDER BY virus_name")
    known_viruses = [r[0] for r in cur.fetchall()]
    log(f"  Known virus names: {len(known_viruses)}")

    # Extract key virus name parts for matching
    virus_name_tokens = set()
    for vn in known_viruses:
        parts = vn.lower().replace("_", " ").replace("-", " ").split()
        for p in parts:
            if len(p) > 3:
                virus_name_tokens.add(p)
    # Add common virus abbreviations
    abbrevs = {"wssv", "ihhnv", "tsv", "yhv", "imnv", "mrnv", "pstv",
               "oshv", "hav", "avnv", "cmnv", "mdnv", "hv", "bv"}
    virus_name_tokens.update(abbrevs)

    # Query sra_runs - try to match by known virus names in title
    cur.execute("SELECT rowid, * FROM sra_runs LIMIT 0")
    sra_cols = [desc[0] for desc in cur.description]

    # Get all runs
    # If there are too many, sample
    cur.execute("SELECT COUNT(*) FROM sra_runs")
    n_runs = cur.fetchone()[0]

    if n_runs > 100000:
        # Too many, just survey
        log(f"  sra_runs has {n_runs} rows — sampling a subset for crossref")
        cur.execute(f"SELECT * FROM sra_runs ORDER BY rowid LIMIT 20000")
    else:
        cur.execute("SELECT * FROM sra_runs")

    rows = cur.fetchall()
    log(f"  Processing {len(rows)} sra_runs for virus matches...")

    matched_count = 0
    unmatched_count = 0
    matches_by_virus = defaultdict(list)
    matched_phyla = Counter()
    unmatched_by_phylum = defaultdict(list)
    candidate_novel = []

    for row in rows:
        run = dict(zip(sra_cols, row))
        title = str(run.get("title", run.get("run_title", run.get("sra_title", ""))))
        organism = str(run.get("organism", run.get("scientific_name", "")))
        run_acc = str(run.get("run_accession", run.get("accession", "")))
        full_text = f"{title} {organism}".lower()

        # Determine host phylum
        host_phylum = run.get("host_phylum", None)
        if not host_phylum:
            host_phylum = classify_host_phylum(title, organism)

        # Check if this run mentions a known virus
        matched_virus = None
        for vn in known_viruses:
            vn_lower = vn.lower().replace("_", " ")
            if vn_lower in full_text:
                matched_virus = vn
                break

        # Also check abbreviation-only matches
        if not matched_virus:
            for abbr in abbrevs:
                # Check as whole word
                if f" {abbr} " in f" {full_text} ":
                    # Try to identify the full virus name
                    for vn in known_viruses:
                        if abbr in vn.lower().replace("_", "").replace("-", ""):
                            matched_virus = vn
                            break
                    if matched_virus:
                        break

        if matched_virus:
            matched_count += 1
            matches_by_virus[matched_virus].append(run_acc)
            if host_phylum:
                matched_phyla[host_phylum] += 1
        else:
            unmatched_count += 1
            if host_phylum:
                unmatched_by_phylum[host_phylum].append({
                    "run_accession": run_acc,
                    "title": title[:200],
                    "organism": organism,
                })
                # Flag as potential novel virus source
                if not is_non_target(title, organism):
                    candidate_novel.append({
                        "run_accession": run_acc,
                        "title": title[:200],
                        "organism": organism,
                        "host_phylum": host_phylum or "unknown",
                    })

    log(f"\n  CrossRef results:")
    log(f"    Runs matching known viruses: {matched_count}")
    log(f"    Runs without matching virus: {unmatched_count}")
    log(f"    Candidate novel virus runs: {len(candidate_novel)}")
    if matched_phyla:
        log(f"    Matched by phylum: {dict(matched_phyla)}")

    # Top matched viruses
    top_matches = sorted(matches_by_virus.items(), key=lambda x: -len(x[1]))[:20]
    log(f"\n  Top 20 matched viruses:")
    for vn, runs in top_matches:
        log(f"    {vn}: {len(runs)} runs")

    return {
        "matched_count": matched_count,
        "unmatched_count": unmatched_count,
        "candidate_novel_count": len(candidate_novel),
        "candidate_novel_runs": candidate_novel,
        "matches_by_virus": {k: v for k, v in matches_by_virus.items()},
        "top_matches": [(vn, len(runs)) for vn, runs in top_matches],
    }


# ═══════════════════════════════════════════════════════════════════════════
#  Phase C — Search NCBI SRA for new virome projects
# ═══════════════════════════════════════════════════════════════════════════

def phase_c_search_ncbi(skip_ncbi: bool = False) -> dict:
    """Search NCBI SRA for new aquatic invertebrate virome projects."""
    log("=" * 60)
    log("PHASE C: Search NCBI SRA for new virome projects (2024-2026)")
    log("=" * 60)

    if skip_ncbi:
        log("  Skipping NCBI queries (--skip-ncbi or --dry-run)")
        return {"sra_projects": [], "sra_runs": [], "by_phylum": {}}

    all_projects = []
    all_runs = []
    phylum_run_counts = defaultdict(int)
    phylum_project_counts = defaultdict(int)
    seen_bioprojects = set()
    total_estimated = 0

    for label, query in SRA_QUERIES:
        log(f"\n  SRA search: {label}")
        # Add date filter for recent results
        full_query = f"({query}) AND 2024:2026[dp]"

        xml_str = ncbi_request("esearch.fcgi", {
            "term": full_query,
            "retmax": "100",
            "sort": "relevance",
        })
        if not xml_str:
            log(f"    No response from NCBI")
            continue

        try:
            root = ET.fromstring(xml_str)
            id_list = [e.text for e in root.findall(".//Id") if e.text]
            count = int(root.findtext(".//Count") or "0")
        except Exception as e:
            log(f"    Parse error: {e}")
            continue

        total_estimated += count
        log(f"    Total results: {count}, Fetching summaries for {len(id_list)}")

        if not id_list:
            continue

        # Fetch summaries in batches of 50
        seen_runs = set()
        batch_projects = []
        batch_runs = []

        for i in range(0, len(id_list), 50):
            batch = id_list[i:i + 50]
            xml_s = ncbi_request("esummary.fcgi", {"id": ",".join(batch)})
            if not xml_s:
                continue

            try:
                root_s = ET.fromstring(xml_s)
            except Exception:
                continue

            for docsum in root_s.findall(".//DocSum"):
                run_info = {"id": docsum.findtext("Id")}
                for child in docsum.findall("Item"):
                    name = child.get("Name")
                    if name in ("Title", "Organism", "TaxId", "BioProject",
                                "BioSample", "Run", "SRA_Sample", "Sample",
                                "LoadDate", "ReleaseDate", "MBases", "MBytes",
                                "LibraryLayout", "LibrarySource", "LibraryStrategy",
                                "Platform", "CenterName"):
                        run_info[name] = child.text or ""
                    # Sub-items for Run
                    if name == "Run" and child.find("Item") is not None:
                        for sub in child.findall("Item"):
                            run_info[f"Run_{sub.get('Name', '')}"] = sub.text or ""

                run_title = run_info.get("Title", "")
                run_organism = run_info.get("Organism", "")
                run_acc = run_info.get("Run_Run", run_info.get("id", ""))

                # Skip non-target
                if is_non_target(run_title, run_organism):
                    continue

                if run_acc in seen_runs:
                    continue
                seen_runs.add(run_acc)

                bio_project = run_info.get("BioProject", "")

                host_phylum = classify_host_phylum(
                    run_title, run_organism
                )
                if not host_phylum:
                    # Try running query-specific phylum
                    for ph in AQUATIC_INVERT_PHYLA:
                        if ph.lower() in label.lower():
                            host_phylum = ph
                            break

                virus_family = guess_virus_family(run_title)

                run_entry = {
                    "run_accession": run_acc,
                    "title": run_title[:300],
                    "organism": run_organism,
                    "tax_id": run_info.get("TaxId", ""),
                    "bioproject": bio_project,
                    "biosample": run_info.get("BioSample", ""),
                    "platform": run_info.get("Platform", ""),
                    "library_source": run_info.get("LibrarySource", ""),
                    "library_strategy": run_info.get("LibraryStrategy", ""),
                    "library_layout": run_info.get("LibraryLayout", ""),
                    "mbases": run_info.get("MBases", ""),
                    "release_date": run_info.get("ReleaseDate", ""),
                    "search_term": label,
                    "host_phylum": host_phylum or "unknown",
                    "virus_family": virus_family or "",
                }
                batch_runs.append(run_entry)
                phylum_run_counts[host_phylum or "unclassified"] += 1

                if bio_project and bio_project not in seen_bioprojects:
                    seen_bioprojects.add(bio_project)
                    proj_entry = {
                        "bioproject": bio_project,
                        "title": run_title[:300],
                        "organism": run_organism,
                        "search_term": label,
                        "host_phylum": host_phylum or "unknown",
                        "estimated_runs": count,
                    }
                    batch_projects.append(proj_entry)
                    phylum_project_counts[host_phylum or "unclassified"] += 1

        all_runs.extend(batch_runs)
        all_projects.extend(batch_projects)
        log(f"    Runs found: {len(batch_runs)}, New BioProjects: {len(batch_projects)}")

    log(f"\n  === SRA Search Summary ===")
    log(f"  Total runs found: {len(all_runs)}")
    log(f"  Total BioProjects: {len(all_projects)}")
    log(f"  Runs by phylum:")
    for ph, cnt in sorted(phylum_run_counts.items(), key=lambda x: -x[1]):
        log(f"    {ph}: {cnt}")
    log(f"  Total estimated results across all queries: {total_estimated}")

    return {
        "sra_projects": all_projects,
        "sra_runs": all_runs,
        "by_phylum": dict(phylum_run_counts),
        "projects_by_phylum": dict(phylum_project_counts),
        "total_estimated": total_estimated,
    }


# ═══════════════════════════════════════════════════════════════════════════
#  Phase D — Generate reports
# ═══════════════════════════════════════════════════════════════════════════

def phase_d_report(survey: dict, crossref: dict, ncbi_results: dict) -> str:
    """Generate the discovery report and CSV outputs."""
    log("=" * 60)
    log("PHASE D: Generate reports")
    log("=" * 60)

    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    # ── Candidate novel virus CSV ────────────────────────────────────────
    csv_path = REPORT_DIR / "novel_virus_candidates.csv"
    candidate_runs = crossref.get("candidate_novel_runs", [])
    ncbi_runs = ncbi_results.get("sra_runs", [])

    # Combine: database candidates + NCBI fresh finds
    all_candidates = []
    seen_accs = set()

    for c in candidate_runs:
        acc = c.get("run_accession", "")
        if acc and acc not in seen_accs:
            seen_accs.add(acc)
            all_candidates.append({
                "run_accession": acc,
                "host_phylum": c.get("host_phylum", "unknown"),
                "organism": c.get("organism", ""),
                "title": c.get("title", ""),
                "source": "sra_runs_table",
                "match_type": "unmatched_in_db",
                "priority": "medium",
            })

    for r in ncbi_runs:
        acc = r.get("run_accession", "")
        if acc and acc not in seen_accs:
            seen_accs.add(acc)
            host_ph = r.get("host_phylum", "unknown")
            # NCBI runs without virus_family = higher priority for novel virus
            priority = "high" if not r.get("virus_family") else "medium"
            all_candidates.append({
                "run_accession": acc,
                "host_phylum": host_ph,
                "organism": r.get("organism", ""),
                "title": r.get("title", ""),
                "source": "ncbi_sra_search",
                "match_type": r.get("virus_family", "novel_virus_unknown") if r.get("virus_family") else "novel_virus_unknown",
                "priority": priority,
            })

    # De-duplicate by keeping first occurrence
    seen = set()
    deduped = []
    for c in all_candidates:
        acc = c["run_accession"]
        if acc not in seen:
            seen.add(acc)
            deduped.append(c)

    all_candidates = deduped

    # Write CSV
    with open(str(csv_path), "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "run_accession", "host_phylum", "organism", "title",
            "source", "match_type", "priority"
        ])
        writer.writeheader()
        writer.writerows(all_candidates)

    log(f"  Novel virus candidates CSV: {csv_path}")
    log(f"    Total candidates: {len(all_candidates)}")

    # ── Bioproject CSV ───────────────────────────────────────────────────
    bp_csv_path = REPORT_DIR / "sra_bioprojects.csv"
    projects = ncbi_results.get("sra_projects", [])
    with open(str(bp_csv_path), "w", newline="", encoding="utf-8") as f:
        if projects:
            writer = csv.DictWriter(f, fieldnames=projects[0].keys())
            writer.writeheader()
            writer.writerows(projects)
    log(f"  BioProjects CSV: {bp_csv_path} ({len(projects)} projects)")

    # ── SRA runs CSV ─────────────────────────────────────────────────────
    runs_csv_path = REPORT_DIR / "sra_virome_runs.csv"
    with open(str(runs_csv_path), "w", newline="", encoding="utf-8") as f:
        if ncbi_runs:
            writer = csv.DictWriter(f, fieldnames=ncbi_runs[0].keys())
            writer.writeheader()
            writer.writerows(ncbi_runs)
    log(f"  SRA runs CSV: {runs_csv_path} ({len(ncbi_runs)} runs)")

    # ── JSON report ──────────────────────────────────────────────────────
    report = {
        "generated_at": datetime.now().isoformat(),
        "database_path": str(DB_PATH),
        "phase_a_database_survey": {
            "total_sra_runs": survey.get("total_runs", 0),
            "columns": survey.get("columns", []),
            "phylum_counts": survey.get("phylum_counts", {}),
        },
        "phase_b_crossref": {
            "runs_matching_known_viruses": crossref.get("matched_count", 0),
            "runs_without_virus_match": crossref.get("unmatched_count", 0),
            "candidate_novel_runs_in_db": crossref.get("candidate_novel_count", 0),
            "top_matched_viruses": dict(crossref.get("top_matches", [])[:20]),
        },
        "phase_c_ncbi_sra_search": {
            "total_runs_discovered": len(ncbi_runs),
            "total_bioprojects": len(projects),
            "runs_by_phylum": ncbi_results.get("by_phylum", {}),
            "projects_by_phylum": ncbi_results.get("projects_by_phylum", {}),
            "total_estimated_results": ncbi_results.get("total_estimated", 0),
        },
        "phase_d_outputs": {
            "novel_virus_candidates_csv": str(csv_path),
            "sra_bioprojects_csv": str(bp_csv_path),
            "sra_virome_runs_csv": str(runs_csv_path),
            "total_novel_candidates": len(all_candidates),
        },
        "summary_stats": {
            "total_candidates_identified": len(all_candidates),
            "high_priority_novel": sum(1 for c in all_candidates if c["priority"] == "high"),
            "medium_priority": sum(1 for c in all_candidates if c["priority"] == "medium"),
            "phyla_covered": len(set(c["host_phylum"] for c in all_candidates if c["host_phylum"] != "unknown")),
            "candidates_by_phylum": dict(
                Counter(c["host_phylum"] for c in all_candidates if c["host_phylum"] != "unknown")
            ),
            "sra_from_db_total": survey.get("total_runs", 0),
            "ncbi_newly_discovered": len(ncbi_runs),
            "bioprojects_found": len(projects),
        },
    }

    report_path = REPORT_DIR / "sra_virus_discovery_report.json"
    with open(str(report_path), "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    log(f"  Report JSON: {report_path}")

    return str(report_path)


# ═══════════════════════════════════════════════════════════════════════════
#  Main
# ═══════════════════════════════════════════════════════════════════════════

def main():
    skip_ncbi = "--dry-run" in sys.argv or "--skip-ncbi" in sys.argv
    skip_db_write = "--skip-db-write" in sys.argv

    log("Starting SRA virus discovery for aquatic invertebrates")
    log(f"  DB: {DB_PATH}")
    log(f"  Skip NCBI: {skip_ncbi}")
    log(f"  Skip DB write: {skip_db_write}")

    # ── Connect to database ─────────────────────────────────────────────
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row

    # ── Phase A: Survey ─────────────────────────────────────────────────
    survey = phase_a_survey(conn)

    # ── Phase B: Cross-reference ────────────────────────────────────────
    crossref = phase_b_crossref(conn, survey)

    # ── Phase C: Search NCBI SRA ────────────────────────────────────────
    ncbi_results = phase_c_search_ncbi(skip_ncbi)

    # ── Phase D: Reports ────────────────────────────────────────────────
    report_path = phase_d_report(survey, crossref, ncbi_results)

    conn.close()
    log(f"\n{'=' * 60}")
    log("DISCOVERY COMPLETE")
    log(f"  Report: {report_path}")
    log(f"  Close this report and read it for next steps.")
    log(f"{'=' * 60}")


if __name__ == "__main__":
    main()
