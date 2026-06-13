"""
Phase 4: Literature evidence backfill with improved matching.
Debug version - run on small batch first.
"""
import json, sqlite3, time, urllib.request, urllib.parse, sys
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "crustacean_virus_core.db"
EPMC_SEARCH = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"

def main():
    conn = sqlite3.connect(str(DB_PATH))
    c = conn.cursor()

    # Get refs with DOI or PMID
    c.execute("""SELECT reference_id, title, pmid, doi FROM ref_literatures
        WHERE (doi IS NOT NULL AND doi != '') OR (pmid IS NOT NULL AND pmid != '')
        ORDER BY reference_id LIMIT 20""")
    refs = [dict(zip(["reference_id", "title", "pmid", "doi"], row)) for row in c.fetchall()]

    # Get virus names for matching (crustacean only)
    c.execute("SELECT master_id, canonical_name FROM virus_master WHERE is_crustacean_virus = 1 OR is_crustacean_virus IS NULL")
    viruses = {row[0]: row[1] for row in c.fetchall() if row[1]}

    # Evidence keywords
    EVIDENCE_TERMS = {
        "mortality": ["mortality", "mortalities", "death", "die", "lethal", "survival rate"],
        "pathogenicity": ["pathogenic", "virulen", "disease", "infection", "infectious"],
        "outbreak": ["outbreak", "epidemic", "mass mortality", "pond", "farm outbreak"],
        "transmission": ["transmission", "vector", "carrier", "horizontal", "vertical transmission"],
        "temperature": ["temperature", "thermal", "heat", "cold", "water temperature", "°C"],
        "diagnostic": ["detection", "PCR", "diagnostic", "diagnosis", "assay", "RT-PCR", "qPCR"],
        "host_range": ["host range", "susceptible", "resistant", "experimental infection"],
    }

    log = []
    new_evidence = 0

    for i, ref in enumerate(refs):
        query = ref["doi"] or ref["pmid"]
        if not query:
            continue

        # Query Europe PMC
        epmc_query = f"DOI:{query}" if query.startswith("10.") else f"EXT_ID:{query}"
        url = f"{EPMC_SEARCH}?query={urllib.parse.quote(epmc_query)}&format=json&resultType=core&pageSize=1"
        time.sleep(0.3)

        abstract = ""
        pmcid = ""
        try:
            req = urllib.request.Request(url)
            req.add_header("User-Agent", "CrustaVirusDB/1.0")
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode())
            results = data.get("resultList", {}).get("result", [])
            if results:
                abstract = results[0].get("abstractText", "") or ""
                pmcid = results[0].get("pmcid", "")
        except Exception as e:
            log.append(f"API error for ref {ref['reference_id']}: {e}")
            continue

        if not abstract:
            log.append(f"No abstract for ref {ref['reference_id']}: {ref.get('title','')[:80]}")
            continue

        abstract_lower = abstract.lower()
        matched_viruses = []

        # Match virus names
        for master_id, vname in viruses.items():
            vname_lower = vname.lower()
            if len(vname_lower) > 4 and vname_lower in abstract_lower:
                matched_viruses.append((master_id, vname))
            # Also try partial match for multi-word names
            elif " " in vname_lower:
                # Try first 2 words (e.g., "white spot" from "white spot syndrome virus")
                parts = vname_lower.split()
                short_name = " ".join(parts[:2])
                if len(short_name) > 5 and short_name in abstract_lower:
                    matched_viruses.append((master_id, vname))

        if not matched_viruses:
            log.append(f"No virus match in ref {ref['reference_id']}: {ref.get('title','')[:80]}")
            continue

        # Check for evidence types
        evidence_found = set()
        for etype, keywords in EVIDENCE_TERMS.items():
            for kw in keywords:
                if kw in abstract_lower:
                    evidence_found.add(etype)
                    break

        if not evidence_found:
            log.append(f"No evidence keywords in ref {ref['reference_id']} (matched viruses: {[v[1] for v in matched_viruses]})")
            continue

        # Create evidence records
        for master_id, vname in matched_viruses:
            for etype in evidence_found:
                try:
                    c.execute("""INSERT INTO evidence_records
                        (reference_id, virus_master_id, evidence_type, claim, extraction_method,
                         curation_status, evidence_strength, source_doi, created_at)
                        VALUES (?, ?, ?, ?, 'auto_extracted_epmc_abstract',
                         'needs_review', 'medium', ?, CURRENT_TIMESTAMP)""",
                        (ref["reference_id"], master_id, etype,
                         f"Auto-extracted from abstract: {etype} evidence for {vname}",
                         ref.get("doi")))
                    new_evidence += 1
                except Exception as e:
                    log.append(f"Insert error: {e}")

        log.append(f"OK: ref {ref['reference_id']} - {len(matched_viruses)} viruses, {len(evidence_found)} evidence types = {len(matched_viruses)*len(evidence_found)} records")

    conn.commit()

    # Print log
    for entry in log:
        print(entry)

    print(f"\nTotal: {new_evidence} new evidence records from {len(refs)} refs")

    # Check final count
    c.execute("SELECT COUNT(*) FROM evidence_records")
    total = c.fetchone()[0]
    print(f"Total evidence_records in DB: {total}")

    conn.close()

if __name__ == "__main__":
    main()
