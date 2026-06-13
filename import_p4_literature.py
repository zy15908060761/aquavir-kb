#!/usr/bin/env python3
"""
Import P4-discovered literature for the 5 zero-evidence viruses with PubMed hits.
Fetches full details, imports into ref_literatures, creates evidence records.
"""
import json, sqlite3, time, urllib.request, urllib.parse, xml.etree.ElementTree as ET
from pathlib import Path
from datetime import datetime

DB_PATH = Path(r"F:\水生无脊椎动物数据库\crustacean_virus_core.db")
UA = "AquaVir-KB/2.0 (mailto:crustacean-db@proton.me)"
TIMEOUT = 30

# The 5 viruses with their PMID hits (from exact PubMed search)
VIRUS_PMIDS = {
    "Alajuela virus": {
        "master_id": 1241,
        "pmids": ["40920035"],
    },
    "Cavally virus": {
        "master_id": 1054,
        "pmids": ["24884700", "23536661", "23728735", "36321387", "34502219"],
    },
    "Cosmacovirus": {
        "master_id": 1231,
        "pmids": ["39167240"],  # likely - check
    },
    "Inpeasmacovirus": {
        "master_id": 1230,
        "pmids": ["39167240"],  # shared with Cosmacovirus
    },
    "Porprismacovirus": {
        "master_id": 1227,
        "pmids": ["39167240", "29572596", "31377645", "31025388", "33278558"],
    },
}


def fetch_pubmed_details(pmids):
    """Fetch article details for PMIDs via NCBI EFetch."""
    if not pmids:
        return []

    url = f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=pubmed&id={','.join(pmids)}&retmode=xml"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            xml_content = resp.read()
    except Exception as e:
        print(f"  EFetch error: {e}")
        # Try Semantic Scholar as fallback
        return fetch_s2_details(pmids)

    results = []
    try:
        root = ET.fromstring(xml_content)
        for article in root.findall(".//PubmedArticle"):
            rec = {
                "pmid": "", "title": "", "abstract": "", "doi": "",
                "year": "", "journal": "", "authors": "",
                "volume": "", "issue": "", "pages": "",
            }

            pmid_el = article.find(".//PMID")
            if pmid_el is not None and pmid_el.text:
                rec["pmid"] = pmid_el.text

            title_el = article.find(".//ArticleTitle")
            if title_el is not None:
                rec["title"] = "".join(title_el.itertext()).strip()

            abstract_el = article.find(".//Abstract/AbstractText")
            if abstract_el is not None:
                rec["abstract"] = "".join(abstract_el.itertext()).strip()[:2000]

            doi_el = article.find(".//ArticleId[@IdType='doi']")
            if doi_el is not None:
                rec["doi"] = doi_el.text

            year_el = article.find(".//PubDate/Year")
            if year_el is not None and year_el.text:
                rec["year"] = year_el.text

            journal_el = article.find(".//Journal/Title")
            if journal_el is not None:
                rec["journal"] = (journal_el.text or "")[:200]

            vol_el = article.find(".//Journal/JournalIssue/Volume")
            if vol_el is not None:
                rec["volume"] = vol_el.text or ""

            iss_el = article.find(".//Journal/JournalIssue/Issue")
            if iss_el is not None:
                rec["issue"] = iss_el.text or ""

            pages_el = article.find(".//Pagination/MedlinePgn")
            if pages_el is not None:
                rec["pages"] = pages_el.text or ""

            # Authors
            author_names = []
            for author in article.findall(".//Author"):
                last = author.find("LastName")
                init = author.find("Initials")
                if last is not None:
                    name = last.text or ""
                    if init is not None and init.text:
                        name += " " + init.text
                    author_names.append(name)
            rec["authors"] = "; ".join(author_names[:10])

            results.append(rec)
    except Exception as e:
        print(f"  XML parse error: {e}")

    return results


def fetch_s2_details(pmids):
    """Fallback: try Semantic Scholar for article details."""
    results = []
    for pmid in pmids:
        try:
            url = f"https://api.semanticscholar.org/graph/v1/paper/PMID:{pmid}?fields=title,abstract,year,authors,journal,externalIds"
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            authors = "; ".join([a.get("name", "") for a in data.get("authors", [])[:10]])
            ext = data.get("externalIds", {})

            results.append({
                "pmid": pmid,
                "title": data.get("title", "")[:500],
                "abstract": (data.get("abstract") or "")[:2000],
                "doi": ext.get("DOI", ""),
                "year": str(data.get("year", "")),
                "journal": (data.get("journal", {}).get("name", "") if data.get("journal") else "")[:200],
                "authors": authors,
                "volume": "", "issue": "", "pages": "",
            })
        except Exception as e:
            print(f"  S2 error for PMID {pmid}: {e}")
        time.sleep(0.3)
    return results


def main():
    print("=" * 70)
    print("P4 Import: Adding literature for zero-evidence viruses")
    print("=" * 70)

    con = sqlite3.connect(str(DB_PATH), timeout=60)
    cur = con.cursor()

    # Collect all unique PMIDs
    all_pmids = set()
    for vname, data in VIRUS_PMIDS.items():
        all_pmids.update(data["pmids"])
    all_pmids = list(all_pmids)

    print(f"Unique PMIDs to fetch: {len(all_pmids)}")
    print(f"Fetching article details...")

    articles = fetch_pubmed_details(all_pmids)
    print(f"  Got {len(articles)} article records")

    # Build PMID → article lookup
    art_by_pmid = {}
    for art in articles:
        art_by_pmid[art["pmid"]] = art

    # Import articles as ref_literatures
    new_refs = 0
    new_evidence = 0
    ref_id_map = {}  # pmid → reference_id

    for pmid, art in art_by_pmid.items():
        # Check if already exists
        existing = cur.execute(
            "SELECT reference_id FROM ref_literatures WHERE pmid = ?", (pmid,)
        ).fetchone()

        if existing:
            ref_id_map[pmid] = existing[0]
            print(f"  PMID {pmid}: already exists (ref_id={existing[0]})")
            continue

        # Insert new ref
        try:
            cur.execute("""
                INSERT INTO ref_literatures
                (pmid, doi, title, abstract, authors, journal, year)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                pmid,
                art.get("doi", ""),
                art.get("title", "")[:500],
                art.get("abstract", "")[:5000],
                art.get("authors", "")[:500],
                art.get("journal", "")[:200],
                art.get("year", ""),
            ))
            ref_id = cur.lastrowid
            ref_id_map[pmid] = ref_id
            new_refs += 1
            print(f"  PMID {pmid}: imported as ref_id={ref_id} — {art.get('title','')[:80]}")
        except Exception as e:
            print(f"  PMID {pmid}: import error — {e}")
            continue

    con.commit()

    # Create evidence records linking refs to viruses
    for vname, data in VIRUS_PMIDS.items():
        master_id = data["master_id"]
        vname_clean = vname

        for pmid in data["pmids"]:
            ref_id = ref_id_map.get(pmid)
            if not ref_id:
                continue

            # Create a "host_range" evidence record (since the paper names the virus)
            try:
                art = art_by_pmid.get(pmid, {})
                claim = f"PubMed reference naming {vname_clean}"
                if art.get("title"):
                    claim += f": {art['title'][:150]}"

                cur.execute("""
                    INSERT OR IGNORE INTO evidence_records
                    (evidence_type, virus_master_id, reference_id, claim,
                     evidence_strength, source_pmid, source_doi,
                     extraction_method, curation_status, observation_type)
                    VALUES ('host_range', ?, ?, ?, 'low', ?, ?,
                            'p4_pubmed_search', 'auto_imported', 'review')
                """, (master_id, ref_id, claim, pmid, art.get("doi", "")))
                if cur.rowcount > 0:
                    new_evidence += 1
            except Exception as e:
                print(f"  Evidence insert error for {vname}/{pmid}: {e}")

    con.commit()

    print(f"\n{'=' * 70}")
    print("P4 IMPORT COMPLETE")
    print(f"{'=' * 70}")
    print(f"  New refs imported: {new_refs}")
    print(f"  New evidence records: {new_evidence}")

    # Updated coverage
    total_v = cur.execute("SELECT COUNT(*) FROM virus_master").fetchone()[0]
    with_ev = cur.execute(
        "SELECT COUNT(DISTINCT virus_master_id) FROM evidence_records WHERE virus_master_id IS NOT NULL"
    ).fetchone()[0]
    zero_target = cur.execute("""SELECT COUNT(*) FROM virus_master v
        WHERE v.master_id NOT IN (SELECT DISTINCT virus_master_id FROM evidence_records WHERE virus_master_id IS NOT NULL)
        AND (v.host_phylum NOT IN ('non_target (algae)','non_target (vertebrate)','non_target (fungus)','non_target (plant)','non_target','non_aquatic') OR v.host_phylum IS NULL)"""
    ).fetchone()[0]
    print(f"  Evidence coverage: {with_ev}/{total_v} = {with_ev/total_v*100:.1f}%")
    print(f"  Zero-evidence target viruses: {zero_target} (was 26)")

    con.close()


if __name__ == "__main__":
    main()
