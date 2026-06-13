#!/usr/bin/env python3
"""
P4: Search PubMed for the 26 zero-evidence target viruses.
Uses NCBI Entrez API to find publications mentioning each virus.
"""
import json, sqlite3, time, urllib.request, urllib.parse, xml.etree.ElementTree as ET
from pathlib import Path
from datetime import datetime
from collections import defaultdict

DB_PATH = Path(r"F:\水生无脊椎动物数据库\crustacean_virus_core.db")
LOG_DIR = Path(r"F:\水生无脊椎动物数据库\downloads\p4_search_logs")
LOG_DIR.mkdir(parents=True, exist_ok=True)

UA = "AquaVir-KB/2.0 (mailto:crustacean-db@proton.me)"
TIMEOUT = 30
SLEEP = 0.4  # NCBI rate limit: 3/sec without API key


def get_zero_evidence_viruses():
    con = sqlite3.connect(str(DB_PATH), timeout=60)
    cur = con.cursor()
    rows = cur.execute("""SELECT v.master_id, v.canonical_name, v.host_phylum, v.virus_family, v.genome_type
        FROM virus_master v
        WHERE v.master_id NOT IN (SELECT DISTINCT virus_master_id FROM evidence_records WHERE virus_master_id IS NOT NULL)
        AND (v.host_phylum NOT IN ('non_target (algae)','non_target (vertebrate)','non_target (fungus)','non_target (plant)','non_target','non_aquatic') OR v.host_phylum IS NULL)
        ORDER BY v.canonical_name""").fetchall()
    con.close()
    return rows


def search_pubmed(query, max_results=20):
    """Search PubMed via E-utilities, return list of PMIDs."""
    base_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"

    # Step 1: Search
    search_params = urllib.parse.urlencode({
        "db": "pubmed",
        "term": query,
        "retmax": str(max_results),
        "retmode": "json",
        "sort": "relevance",
    })
    search_url = f"{base_url}/esearch.fcgi?{search_params}"

    try:
        req = urllib.request.Request(search_url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data.get("esearchresult", {}).get("idlist", [])
    except Exception as e:
        print(f"    Search error: {e}")
        return []


def fetch_pubmed_details(pmids):
    """Fetch title, abstract, DOI, year for a list of PMIDs."""
    if not pmids:
        return []

    base_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
    fetch_params = urllib.parse.urlencode({
        "db": "pubmed",
        "id": ",".join(pmids),
        "retmode": "xml",
    })
    fetch_url = f"{base_url}/efetch.fcgi?{fetch_params}"

    try:
        req = urllib.request.Request(fetch_url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            xml_content = resp.read()
    except Exception as e:
        print(f"    Fetch error: {e}")
        return []

    results = []
    try:
        root = ET.fromstring(xml_content)
        for article in root.findall(".//PubmedArticle"):
            rec = {"pmid": "", "title": "", "abstract": "", "doi": "", "year": "", "journal": ""}

            pmid_el = article.find(".//PMID")
            if pmid_el is not None and pmid_el.text:
                rec["pmid"] = pmid_el.text

            title_el = article.find(".//ArticleTitle")
            if title_el is not None:
                rec["title"] = "".join(title_el.itertext()).strip()

            abstract_el = article.find(".//AbstractText")
            if abstract_el is not None:
                rec["abstract"] = "".join(abstract_el.itertext()).strip()[:500]

            doi_el = article.find(".//ArticleId[@IdType='doi']")
            if doi_el is not None:
                rec["doi"] = doi_el.text

            year_el = article.find(".//PubDate/Year")
            if year_el is not None and year_el.text:
                rec["year"] = year_el.text

            journal_el = article.find(".//Journal/Title")
            if journal_el is not None:
                rec["journal"] = journal_el.text or ""

            results.append(rec)
    except Exception as e:
        print(f"    XML parse error: {e}")

    return results


def main():
    print("=" * 70)
    print("P4: PubMed Search for 26 Zero-Evidence Viruses")
    print("=" * 70)

    viruses = get_zero_evidence_viruses()
    print(f"Viruses to search: {len(viruses)}")

    all_results = {}  # virus_name -> {pmids, details}
    total_pmids_found = 0

    for i, (master_id, name, phylum, family, gtype) in enumerate(viruses):
        print(f"\n[{i+1}/{len(viruses)}] {name}")

        # Build search query
        # Use exact name first, then broader
        clean_name = name.replace("'", "").replace('"', '')
        query = f'"{clean_name}"[Title/Abstract]'

        pmids = search_pubmed(query, max_results=10)

        if not pmids:
            # Try without quotes, broader search
            query2 = f'{clean_name}[All Fields]'
            pmids = search_pubmed(query2, max_results=10)
            if pmids:
                print(f"  Broad search found {len(pmids)} results")

        if not pmids:
            print(f"  No PubMed results")
            all_results[name] = {"pmids": [], "articles": []}
            continue

        print(f"  Found {len(pmids)} PMIDs, fetching details...")
        articles = fetch_pubmed_details(pmids)

        all_results[name] = {
            "master_id": master_id,
            "phylum": phylum,
            "family": family,
            "pmids": pmids,
            "articles": articles,
        }
        total_pmids_found += len(pmids)

        # Show top results
        for art in articles[:3]:
            print(f"    [{art['pmid']}] {art['title'][:100]}... ({art['year']})")

        time.sleep(SLEEP)

    # Summary
    print(f"\n{'=' * 70}")
    print("SEARCH COMPLETE")
    print(f"{'=' * 70}")

    viruses_with_hits = sum(1 for v in all_results.values() if v["pmids"])
    print(f"Viruses with PubMed hits: {viruses_with_hits}/{len(viruses)}")
    print(f"Total PMIDs found: {total_pmids_found}")

    # Per-virus breakdown
    print("\n=== Per-Virus Results ===")
    for vname, data in sorted(all_results.items()):
        n = len(data["pmids"])
        status = f"{n} hits" if n > 0 else "NO RESULTS"
        print(f"  {vname}: {status}")
        if data.get("articles"):
            for art in data["articles"][:2]:
                print(f"    -> [{art['pmid']}] {art.get('doi','no DOI')} | {art['title'][:80]}")

    # Save results
    output = {
        "timestamp": datetime.now().isoformat(),
        "viruses_searched": len(viruses),
        "viruses_with_hits": viruses_with_hits,
        "total_pmids": total_pmids_found,
        "results": {},
    }
    for vname, data in all_results.items():
        output["results"][vname] = {
            "master_id": data["master_id"],
            "pmids": data["pmids"],
            "articles": data["articles"],
        }

    log_path = LOG_DIR / f"p4_search_{int(time.time())}.json"
    log_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nResults saved: {log_path}")

    # Also save a simple text report
    report_path = LOG_DIR / "p4_zero_evidence_report.txt"
    lines = [f"P4 Zero-Evidence Virus PubMed Search Report", f"Date: {datetime.now().isoformat()}", "",
             f"Total viruses: {len(viruses)}", f"With PubMed hits: {viruses_with_hits}",
             f"Without hits: {len(viruses) - viruses_with_hits}", ""]
    for vname, data in sorted(all_results.items()):
        n = len(data["pmids"])
        lines.append(f"{'[HIT]' if n > 0 else '[MISS]'} {vname} (ID={data['master_id']}, phylum={data['phylum']})")
        for art in data.get("articles", [])[:3]:
            lines.append(f"  PMID:{art['pmid']} | {art.get('year','?')} | {art['title'][:100]}")
    report_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"Report saved: {report_path}")


if __name__ == "__main__":
    main()
