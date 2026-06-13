#!/usr/bin/env python3
"""
批量获取110篇GenBank关联论文的PubMed完整元数据
包括：MeSH术语、摘要全文、引用信息、化学物质

策略：用NCBI E-utilities的efetch批量获取，然后用Semantic Scholar补充
"""

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
from collections import defaultdict, Counter

DB_PATH = Path(r"F:\甲壳动物数据库\crustacean_virus_core.db")
OUT_DIR = Path(r"F:\甲壳动物数据库\external_data\multi_source_mining")
OUT_DIR.mkdir(parents=True, exist_ok=True)

NCBI_API_KEY = os.environ.get("NCBI_API_KEY", "")
RATE_LIMIT = 0.35 if not NCBI_API_KEY else 0.12


def get_all_pmids():
    """获取所有GenBank关联的PMID及其病毒映射"""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    c.execute("""
        SELECT rl.pmid, rl.doi, rl.title, rl.journal, rl.year, rl.authors,
               GROUP_CONCAT(DISTINCT vm.canonical_name) as viruses
        FROM ref_literatures rl
        JOIN isolate_reference_links irl ON rl.reference_id = irl.reference_id
        JOIN viral_isolates vi ON irl.isolate_id = vi.isolate_id
        JOIN virus_master vm ON vi.master_id = vm.master_id
        WHERE rl.pmid IS NOT NULL AND rl.pmid != ''
        GROUP BY rl.pmid
        ORDER BY COUNT(DISTINCT vm.canonical_name) DESC
    """)
    refs = [dict(row) for row in c.fetchall()]
    conn.close()
    return refs


def pubmed_efetch_details(pmids: list[str]) -> str:
    """用efetch获取完整PubMed记录（包含MeSH, Chemicals, 引用等）"""
    if not pmids:
        return ""
    ids = ",".join(pmids)
    # 使用pubmed db获取完整记录
    url = (
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
        f"?db=pubmed&id={ids}&retmode=xml&rettype=medline"
    )
    if NCBI_API_KEY:
        url += f"&api_key={NCBI_API_KEY}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "crustacean-db/3.0"})
        with urllib.request.urlopen(req, timeout=120) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        print(f"    [efetch error] {e}")
        return ""


def parse_pubmed_full(xml_text: str) -> list[dict]:
    """解析包含MeSH的完整PubMed记录"""
    if not xml_text:
        return []
    articles = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []

    for article in root.findall(".//PubmedArticle"):
        medline = article.find(".//MedlineCitation")
        if medline is None:
            continue

        pmid = (medline.find("./PMID").text if medline.find("./PMID") is not None else "")

        # Article info
        art = medline.find("./Article")
        title = (art.find("./ArticleTitle").text if art is not None and art.find("./ArticleTitle") is not None else "")
        abstract_elems = art.findall(".//Abstract/AbstractText") if art is not None else []
        abstract = " ".join((e.text or "") for e in abstract_elems)

        # Journal
        journal_elem = art.find("./Journal/Title") if art is not None else None
        journal = journal_elem.text if journal_elem is not None else ""
        year_elem = art.find("./Journal/JournalIssue/PubDate/Year") if art is not None else None
        year = year_elem.text if year_elem is not None else ""

        # Authors
        authors = []
        for author in art.findall("./AuthorList/Author") if art is not None else []:
            last = author.find("./LastName")
            fore = author.find("./ForeName")
            if last is not None:
                authors.append(f"{last.text} {fore.text if fore is not None else ''}")

        # MeSH terms
        mesh_terms = []
        for mesh in medline.findall("./MeshHeadingList/MeshHeading"):
            desc = mesh.find("./DescriptorName")
            if desc is not None:
                qualifiers = [q.text for q in mesh.findall("./QualifierName") if q is not None]
                mesh_terms.append({
                    "descriptor": desc.text,
                    "qualifiers": qualifiers,
                    "is_major": desc.get("MajorTopicYN", "N") == "Y",
                })

        # Chemicals
        chemicals = []
        for chem in medline.findall("./ChemicalList/Chemical"):
            name = chem.find("./NameOfSubstance")
            reg_num = chem.find("./RegistryNumber")
            chemicals.append({
                "name": name.text if name is not None else "",
                "registry_number": reg_num.text if reg_num is not None else "",
            })

        # Publication types
        pub_types = [pt.text for pt in medline.findall("./Article/PublicationTypeList/PublicationType")]

        # Language
        lang_elems = art.findall("./Language") if art is not None else []
        languages = [l.text for l in lang_elems]

        articles.append({
            "pmid": pmid,
            "title": title,
            "abstract": abstract,
            "journal": journal,
            "year": year,
            "authors": "; ".join(authors[:5]),
            "mesh_terms": mesh_terms,
            "chemicals": chemicals,
            "publication_types": pub_types,
            "languages": languages,
        })

    return articles


def extract_from_mesh(articles: list[dict]) -> dict:
    """从MeSH术语推断论文是否包含毒力/温度数据"""
    virulence_mesh = {
        "Virulence", "Virulence Factors", "Pathogenicity", "Host-Pathogen Interactions",
        "Disease Resistance", "Disease Susceptibility", "Mortality", "Lethal Dose 50",
    }
    temperature_mesh = {
        "Temperature", "Hot Temperature", "Cold Temperature", "Heat-Shock Response",
        "Thermal Inactivation", "Water Temperature", "Climate Change",
    }

    relevant = {"virulence": [], "temperature": [], "both": [], "other": []}

    for art in articles:
        mesh_descriptors = {m["descriptor"] for m in art.get("mesh_terms", [])}
        has_vir = bool(mesh_descriptors & virulence_mesh)
        has_temp = bool(mesh_descriptors & temperature_mesh)

        if has_vir and has_temp:
            relevant["both"].append(art)
        elif has_vir:
            relevant["virulence"].append(art)
        elif has_temp:
            relevant["temperature"].append(art)
        else:
            relevant["other"].append(art)

    return relevant


def semantic_scholar_batch_search(virus_names: list[str]):
    """
    用Semantic Scholar API搜索文献（免费，无需API key）
    https://api.semanticscholar.org/
    """
    print("\n" + "=" * 60)
    print("Semantic Scholar search")
    print("=" * 60)

    s2_dir = OUT_DIR / "semantic_scholar"
    s2_dir.mkdir(exist_ok=True)

    all_papers = []

    for virus_name in virus_names:
        safe_name = re.sub(r"[^\w\s-]", "", virus_name).strip().replace(" ", "_")[:60]
        cache_file = s2_dir / f"{safe_name}.json"

        if cache_file.exists():
            with open(cache_file, "r", encoding="utf-8") as f:
                papers = json.load(f)
            print(f"  [{virus_name}]: {len(papers)} cached")
        else:
            # Search S2
            query = urllib.request.quote(f"{virus_name} virulence mortality temperature")
            url = f"https://api.semanticscholar.org/graph/v1/paper/search?query={query}&limit=30&fields=title,year,authors,journal,abstract,externalIds,publicationTypes,citationCount"

            try:
                req = urllib.request.Request(url, headers={"User-Agent": "crustacean-db/3.0"})
                with urllib.request.urlopen(req, timeout=60) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                papers = data.get("data", [])
                with open(cache_file, "w", encoding="utf-8") as f:
                    json.dump(papers, f, indent=2, ensure_ascii=False)
                print(f"  [{virus_name}]: {len(papers)} papers found")
                time.sleep(1.0)  # Respect rate limit
            except Exception as e:
                print(f"  [{virus_name}]: error - {e}")
                papers = []

        for p in papers:
            p["target_virus"] = virus_name
        all_papers.extend(papers)

    # Summary
    by_virus = Counter(p["target_virus"] for p in all_papers)
    print(f"\n  Semantic Scholar total: {len(all_papers)} papers")
    print(f"  Top viruses by paper count:")
    for v, cnt in by_virus.most_common(20):
        print(f"    {cnt:>4} | {v}")

    # Save
    csv_path = s2_dir / "s2_search_results.csv"
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        fieldnames = ["target_virus", "title", "year", "citationCount", "journal",
                      "abstract", "externalIds", "publicationTypes"]
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for p in all_papers:
            # Flatten externalIds
            ext = p.get("externalIds") or {}
            journal_info = p.get("journal") or {}
            row = {
                "target_virus": p.get("target_virus", ""),
                "title": p.get("title", ""),
                "year": p.get("year", ""),
                "citationCount": p.get("citationCount", 0),
                "journal": journal_info.get("name", "") if isinstance(journal_info, dict) else str(journal_info),
                "abstract": p.get("abstract", ""),
                "externalIds": json.dumps(ext),
                "publicationTypes": json.dumps(p.get("publicationTypes", [])),
            }
            writer.writerow(row)

    print(f"  Results saved: {csv_path}")
    return all_papers


# ═══════════════════════════════════════
def main():
    print("=" * 60)
    print("Batch PMID Enrichment + Semantic Scholar Search")
    print("=" * 60)

    # Step 1: Get all PMIDs
    refs = get_all_pmids()
    all_pmids = [r["pmid"] for r in refs]
    print(f"Total PMIDs: {len(all_pmids)}")

    # Step 2: Fetch full PubMed records (cached)
    cache_path = OUT_DIR / "pubmed_full_records.xml"
    if cache_path.exists():
        print(f"Using cached PubMed records: {cache_path}")
        xml_text = cache_path.read_text(encoding="utf-8", errors="replace")
    else:
        print("Fetching full PubMed records in batches...")
        xml_parts = []
        for i in range(0, len(all_pmids), 100):
            batch = all_pmids[i:i+100]
            xml = pubmed_efetch_details(batch)
            if xml:
                xml_parts.append(xml)
            time.sleep(RATE_LIMIT)
            if (i // 100) % 5 == 0:
                print(f"  {min(i+100, len(all_pmids))}/{len(all_pmids)}")
        xml_text = "\n".join(xml_parts)
        cache_path.write_text(xml_text, encoding="utf-8", errors="replace")

    articles = parse_pubmed_full(xml_text)
    print(f"Parsed {len(articles)} full PubMed articles")

    # Step 3: MeSH classification
    mesh_classes = extract_from_mesh(articles)
    print(f"\nMeSH classification:")
    print(f"  Virulence-related MeSH:  {len(mesh_classes['virulence'])} papers")
    print(f"  Temperature-related MeSH: {len(mesh_classes['temperature'])} papers")
    print(f"  BOTH virulence + temperature: {len(mesh_classes['both'])} papers")
    print(f"  Neither: {len(mesh_classes['other'])} papers")

    # Save MeSH-classified articles
    for category, arts in mesh_classes.items():
        if not arts:
            continue
        csv_path = OUT_DIR / f"pubmed_mesh_{category}.csv"
        with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
            fieldnames = ["pmid", "title", "year", "journal", "authors",
                         "mesh_descriptors", "publication_types", "abstract"]
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for art in arts:
                mesh_str = "; ".join(f"{m['descriptor']}{'*' if m['is_major'] else ''}"
                                    for m in art.get("mesh_terms", []))
                writer.writerow({
                    "pmid": art["pmid"],
                    "title": art["title"],
                    "year": art["year"],
                    "journal": art["journal"],
                    "authors": art.get("authors", ""),
                    "mesh_descriptors": mesh_str,
                    "publication_types": "; ".join(art.get("publication_types", [])),
                    "abstract": art.get("abstract", "")[:500],
                })
        print(f"  {category}: {len(arts)} papers → {csv_path}")

    # Step 4: Semantic Scholar search for priority viruses
    priority_viruses = [
        "White spot syndrome virus", "Yellow head virus", "Taura syndrome virus",
        "Infectious hypodermal and hematopoietic necrosis virus",
        "Infectious myonecrosis virus", "Macrobrachium rosenbergii nodavirus",
        "Decapod iridescent virus", "Covert mortality nodavirus",
        "Hepatopancreatic parvovirus", "Mud crab virus",
        "Chinese mitten crab virus", "Laem-Singh virus",
        "Wenzhou shrimp virus", "Penaeus vannamei nodavirus",
        "Shrimp hemocyte iridescent virus",
        "Callinectes sapidus reovirus", "Eriocheir sinensis reovirus",
    ]
    s2_papers = semantic_scholar_batch_search(priority_viruses)

    # Step 5: Generate full-text access URLs
    print(f"\n{'='*60}")
    print("Full-text access URLs (publisher/PubMed only)")
    print(f"{'='*60}")
    doi_list = [r for r in refs if r.get("doi")]
    access_csv = OUT_DIR / "legal_fulltext_access_urls.csv"
    with open(access_csv, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=["pmid", "doi", "year", "viruses", "title", "doi_url", "pubmed_url"])
        writer.writeheader()
        for r in doi_list:
            writer.writerow({
                "pmid": r["pmid"],
                "doi": r["doi"],
                "year": r.get("year", ""),
                "viruses": r.get("viruses", ""),
                "title": (r.get("title") or "")[:120],
                "doi_url": f"https://doi.org/{r['doi']}",
                "pubmed_url": f"https://pubmed.ncbi.nlm.nih.gov/{r['pmid']}/",
            })
    print(f"  {len(doi_list)} DOI access URLs saved: {access_csv}")

    # Summary
    print(f"\n{'='*60}")
    print("SUMMARY: Data available for manual curation")
    print(f"{'='*60}")
    print(f"""
Output files:
  1. {OUT_DIR / 'pubmed_mesh_both.csv'}
     → Papers with BOTH virulence and temperature MeSH terms (highest priority for review)

  2. {OUT_DIR / 'pubmed_mesh_virulence.csv'}
     → Papers with virulence-related MeSH terms

  3. {OUT_DIR / 'pubmed_mesh_temperature.csv'}
     → Papers with temperature-related MeSH terms

  4. {OUT_DIR / 'semantic_scholar' / 's2_search_results.csv'}
     → Semantic Scholar search results for 17 priority viruses

  5. {OUT_DIR / 'legal_fulltext_access_urls.csv'}
     DOI/PubMed links for legal full-text lookup

  6. {OUT_DIR / 'master_review_queue.csv'}
     → Combined review queue from the earlier mining round

Next steps:
  1. Review pubmed_mesh_both.csv first — these papers are most likely to contain useful data
  2. Use institutional subscriptions, publisher pages, PubMed Central, or author manuscripts for full-text access
  3. For each paper that contains experimental virulence/temperature data:
     - Extract: virus name, mortality rate, LD50, optimal temp, thermal inactivation temp
     - Record: PMID, page/section where data was found, experimental conditions
     - Import into virulence_profiles / temperature_profiles tables
  4. Use Semantic Scholar results (s2_search_results.csv) for additional recent papers
""")

    print("Done.")


if __name__ == "__main__":
    main()
