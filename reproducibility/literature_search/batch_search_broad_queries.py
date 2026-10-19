#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
为PubMed中无直接文献的优先病毒执行宽泛检索
使用宿主+病毒科/地理来源等组合查询
"""

import csv
import json
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from datetime import datetime

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) CrustaceanVirusDB/1.0"
ESEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
EFETCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"

DB_DIR = Path(r"F:\甲壳动物数据库")
OUT_DIR = DB_DIR / "downloads" / "literature_broad_search"
OUT_DIR.mkdir(parents=True, exist_ok=True)

def fetch(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()

def esearch(term, retmax=500, retstart=0):
    params = {
        "db": "pubmed",
        "retmode": "json",
        "retmax": str(retmax),
        "retstart": str(retstart),
        "sort": "date",
        "term": term,
    }
    url = f"{ESEARCH_URL}?{urllib.parse.urlencode(params)}"
    payload = fetch(url)
    data = json.loads(payload.decode("utf-8"))
    result = data.get("esearchresult", {})
    return result.get("idlist", []), int(result.get("count", 0))

def efetch_pmids(pmids):
    if not pmids:
        return []
    params = {
        "db": "pubmed",
        "retmode": "xml",
        "id": ",".join(pmids),
    }
    url = f"{EFETCH_URL}?{urllib.parse.urlencode(params)}"
    payload = fetch(url, timeout=60)
    root = ET.fromstring(payload)
    articles = []
    for article in root.findall("PubmedArticle"):
        articles.append(parse_pubmed_article(article))
    return articles

def first_text(elem, path):
    found = elem.find(path)
    return found.text.strip() if found is not None and found.text else ""

def parse_pubmed_article(article):
    medline = article.find("MedlineCitation")
    article_node = medline.find("Article") if medline is not None else None
    pubmed_data = article.find("PubmedData")
    pmid = first_text(medline, "PMID") if medline is not None else ""
    title = "".join(article_node.findtext("ArticleTitle", default="")) if article_node is not None else ""
    
    abstract_parts = []
    if article_node is not None:
        abstract = article_node.find("Abstract")
        if abstract is not None:
            for part in abstract.findall("AbstractText"):
                label = part.attrib.get("Label", "").strip()
                text = "".join(part.itertext()).strip()
                if text:
                    abstract_parts.append(f"{label}: {text}" if label else text)
    
    journal = ""
    year = ""
    authors = []
    if article_node is not None:
        journal = article_node.findtext("Journal/Title", default="").strip()
        year = (
            article_node.findtext("Journal/JournalIssue/PubDate/Year", default="").strip()
            or article_node.findtext("ArticleDate/Year", default="").strip()
            or article_node.findtext("Journal/JournalIssue/PubDate/MedlineDate", default="").strip()[:4]
        )
        author_list = article_node.find("AuthorList")
        if author_list is not None:
            for author in author_list.findall("Author"):
                lastname = author.findtext("LastName", default="").strip()
                initials = author.findtext("Initials", default="").strip()
                collective = author.findtext("CollectiveName", default="").strip()
                if collective:
                    authors.append(collective)
                elif lastname:
                    authors.append(f"{lastname} {initials}".strip())
    
    doi = ""
    pmcid = ""
    if pubmed_data is not None:
        for aid in pubmed_data.findall("ArticleIdList/ArticleId"):
            idtype = aid.attrib.get("IdType", "")
            value = (aid.text or "").strip()
            if idtype == "doi":
                doi = value
            elif idtype == "pmc":
                pmcid = value
    
    keywords = []
    keyword_list = medline.find("KeywordList") if medline is not None else None
    if keyword_list is not None:
        for kw in keyword_list.findall("Keyword"):
            text = (kw.text or "").strip()
            if text:
                keywords.append(text)
    
    mesh_terms = []
    mesh_list = medline.find("MeshHeadingList") if medline is not None else None
    if mesh_list is not None:
        for heading in mesh_list.findall("MeshHeading"):
            descriptor = heading.find("DescriptorName")
            if descriptor is not None and descriptor.text:
                mesh_terms.append(descriptor.text.strip())
    
    return {
        "pmid": pmid,
        "title": title,
        "abstract": "\n".join(abstract_parts),
        "journal": journal,
        "year": year,
        "authors": ", ".join(authors),
        "doi": doi,
        "pmcid": pmcid,
        "keywords": "; ".join(keywords),
        "mesh_terms": "; ".join(mesh_terms),
        "pubmed_url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
    }

# 宽泛检索策略：为无直接文献的病毒定义宿主+family/关键词组合
BROAD_QUERIES = [
    # Wenzhou 系列病毒
    {"virus": "Wenzhou shrimp virus", "queries": [
        '(Wenzhou[Title/Abstract] OR yuevirus[Title/Abstract] OR Yueviridae[Title/Abstract]) AND (shrimp[Title/Abstract] OR penaeus[Title/Abstract] OR crustacean[Title/Abstract])',
        '(Wenzhou[Title/Abstract]) AND (virus[Title/Abstract] OR virome[Title/Abstract] OR metagenome[Title/Abstract])',
    ]},
    {"virus": "Wenzhou crab virus", "queries": [
        '(Wenzhou[Title/Abstract] OR Charybdivirus[Title/Abstract] OR Natareviridae[Title/Abstract]) AND (crab[Title/Abstract] OR Eriocheir[Title/Abstract] OR Scylla[Title/Abstract])',
    ]},
    {"virus": "Wenzhou Shrimp Virus 1", "queries": [
        '(Wenzhou[Title/Abstract]) AND (shrimp[Title/Abstract] OR penaeid[Title/Abstract]) AND (virus[Title/Abstract] OR viral[Title/Abstract])',
    ]},
    {"virus": "Wenzhou Shrimp Virus 2", "queries": [
        '(Wenzhou[Title/Abstract]) AND (shrimp[Title/Abstract] OR penaeid[Title/Abstract]) AND (virus[Title/Abstract] OR viral[Title/Abstract])',
    ]},
    # Beihai 系列
    {"virus": "Beihai crab virus", "queries": [
        '(Beihai[Title/Abstract]) AND (crab[Title/Abstract] OR crustacean[Title/Abstract]) AND (virus[Title/Abstract] OR viral[Title/Abstract] OR circovirus[Title/Abstract])',
    ]},
    {"virus": "Beihai shrimp virus", "queries": [
        '(Beihai[Title/Abstract]) AND (shrimp[Title/Abstract] OR penaeid[Title/Abstract]) AND (virus[Title/Abstract] OR viral[Title/Abstract])',
    ]},
    # Scylla serrata reovirus
    {"virus": "Scylla serrata reovirus SZ-2007", "queries": [
        '(Scylla serrata[Title/Abstract] OR mud crab[Title/Abstract]) AND (reovirus[Title/Abstract] OR Reoviridae[Title/Abstract] OR Sedoreoviridae[Title/Abstract])',
        '(Scylla serrata[Title/Abstract]) AND (virus[Title/Abstract] OR viral[Title/Abstract] OR virome[Title/Abstract])',
    ]},
    # Laem-Singh virus
    {"virus": "Laem-Singh virus", "queries": [
        '(Laem-Singh[Title/Abstract] OR Laem Singh[Title/Abstract]) AND (shrimp[Title/Abstract] OR penaeus[Title/Abstract] OR crustacean[Title/Abstract])',
        '(LSV[Title/Abstract]) AND (shrimp[Title/Abstract] OR penaeus[Title/Abstract]) AND (virus[Title/Abstract])',
    ]},
    # Brine shrimp 系列
    {"virus": "Brine shrimp chuvirus 1", "queries": [
        '(brine shrimp[Title/Abstract] OR Artemia[Title/Abstract]) AND (chuvirus[Title/Abstract] OR Chuviridae[Title/Abstract] OR Boscovirus[Title/Abstract])',
        '(Artemia[Title/Abstract]) AND (virus[Title/Abstract] OR virome[Title/Abstract] OR viral[Title/Abstract])',
    ]},
    {"virus": "Brine shrimp chuvirus 2", "queries": [
        '(brine shrimp[Title/Abstract] OR Artemia[Title/Abstract]) AND (chuvirus[Title/Abstract] OR Chuviridae[Title/Abstract])',
    ]},
    {"virus": "Brine shrimp iflavirus 1", "queries": [
        '(brine shrimp[Title/Abstract] OR Artemia[Title/Abstract]) AND (iflavirus[Title/Abstract] OR Iflaviridae[Title/Abstract])',
    ]},
    {"virus": "Brine shrimp iflavirus 3", "queries": [
        '(brine shrimp[Title/Abstract] OR Artemia[Title/Abstract]) AND (iflavirus[Title/Abstract] OR Iflaviridae[Title/Abstract])',
    ]},
    # Qianjiang 系列
    {"virus": "Qianjiang marna-like virus 156", "queries": [
        '(Qianjiang[Title/Abstract]) AND (marna-like[Title/Abstract] OR Marnaviridae[Title/Abstract] OR marnavirus[Title/Abstract]) AND (shrimp[Title/Abstract] OR crab[Title/Abstract] OR crustacean[Title/Abstract])',
    ]},
    {"virus": "Qianjiang marna-like virus 185", "queries": [
        '(Qianjiang[Title/Abstract]) AND (marna-like[Title/Abstract] OR Marnaviridae[Title/Abstract]) AND (shrimp[Title/Abstract] OR crab[Title/Abstract] OR crustacean[Title/Abstract])',
    ]},
    {"virus": "Qianjiang marna-like virus 130", "queries": [
        '(Qianjiang[Title/Abstract]) AND (marna-like[Title/Abstract] OR Marnaviridae[Title/Abstract]) AND (shrimp[Title/Abstract] OR crab[Title/Abstract] OR crustacean[Title/Abstract])',
    ]},
    {"virus": "Qianjiang marna-like virus 147", "queries": [
        '(Qianjiang[Title/Abstract]) AND (marna-like[Title/Abstract] OR Marnaviridae[Title/Abstract]) AND (shrimp[Title/Abstract] OR crab[Title/Abstract] OR crustacean[Title/Abstract])',
    ]},
    {"virus": "Qianjiang marna-like virus 174", "queries": [
        '(Qianjiang[Title/Abstract]) AND (marna-like[Title/Abstract] OR Marnaviridae[Title/Abstract]) AND (shrimp[Title/Abstract] OR crab[Title/Abstract] OR crustacean[Title/Abstract])',
    ]},
    {"virus": "Qianjiang marna-like virus 187", "queries": [
        '(Qianjiang[Title/Abstract]) AND (marna-like[Title/Abstract] OR Marnaviridae[Title/Abstract]) AND (shrimp[Title/Abstract] OR crab[Title/Abstract] OR crustacean[Title/Abstract])',
    ]},
    {"virus": "Qianjiang marna-like virus 137", "queries": [
        '(Qianjiang[Title/Abstract]) AND (marna-like[Title/Abstract] OR Marnaviridae[Title/Abstract]) AND (shrimp[Title/Abstract] OR crab[Title/Abstract] OR crustacean[Title/Abstract])',
    ]},
    {"virus": "Qianjiang marna-like virus 222", "queries": [
        '(Qianjiang[Title/Abstract]) AND (marna-like[Title/Abstract] OR Marnaviridae[Title/Abstract]) AND (shrimp[Title/Abstract] OR crab[Title/Abstract] OR crustacean[Title/Abstract])',
    ]},
    {"virus": "Qianjiang picorna-like virus 109", "queries": [
        '(Qianjiang[Title/Abstract]) AND (picorna-like[Title/Abstract] OR Picornaviridae[Title/Abstract]) AND (shrimp[Title/Abstract] OR crab[Title/Abstract] OR crustacean[Title/Abstract])',
    ]},
    {"virus": "Qianjiang picorna-like virus 98", "queries": [
        '(Qianjiang[Title/Abstract]) AND (picorna-like[Title/Abstract] OR Picornaviridae[Title/Abstract]) AND (shrimp[Title/Abstract] OR crab[Title/Abstract] OR crustacean[Title/Abstract])',
    ]},
    # 其他
    {"virus": "Macrobrachium rosenbergii Golda virus", "queries": [
        '(Macrobrachium rosenbergii[Title/Abstract] OR giant freshwater prawn[Title/Abstract]) AND (Golda[Title/Abstract] OR golda virus[Title/Abstract]) AND (virus[Title/Abstract] OR viral[Title/Abstract])',
    ]},
    {"virus": "Macrobrachium rosenbergii virus 10", "queries": [
        '(Macrobrachium rosenbergii[Title/Abstract]) AND (virus 10[Title/Abstract] OR novel virus[Title/Abstract])',
    ]},
    {"virus": "Mud crab virus", "queries": [
        '(mud crab[Title/Abstract] OR Scylla[Title/Abstract] OR Portunus[Title/Abstract] OR Eriocheir[Title/Abstract]) AND (dicistrovirus[Title/Abstract] OR Dicistroviridae[Title/Abstract] OR Aparavirus[Title/Abstract])',
        '(mud crab[Title/Abstract] OR Scylla[Title/Abstract]) AND (virus[Title/Abstract] OR viral[Title/Abstract]) AND (novel[Title/Abstract] OR new[Title/Abstract])',
    ]},
    {"virus": "Chinese mitten crab virus", "queries": [
        '(Chinese mitten crab[Title/Abstract] OR Eriocheir sinensis[Title/Abstract]) AND (virus[Title/Abstract] OR viral[Title/Abstract] OR virome[Title/Abstract])',
    ]},
    {"virus": "Unclassified crustacean ssRNA virus", "queries": [
        '(crustacean[Title/Abstract] OR shrimp[Title/Abstract] OR crab[Title/Abstract]) AND (ssRNA virus[Title/Abstract] OR novel RNA virus[Title/Abstract])',
    ]},
    {"virus": "Unclassified Narnaviridae-like crustacean RNA virus", "queries": [
        '(crustacean[Title/Abstract] OR shrimp[Title/Abstract] OR crab[Title/Abstract]) AND (Narnaviridae[Title/Abstract] OR narnavirus[Title/Abstract])',
    ]},
    {"virus": "Covert mortality nodavirus", "queries": [
        '(covert mortality[Title/Abstract] OR CMNV[Title/Abstract]) AND (shrimp[Title/Abstract] OR penaeus[Title/Abstract] OR crustacean[Title/Abstract])',
        '(covert mortality nodavirus[Title/Abstract])',
    ]},
]

def main():
    print("=" * 60)
    print("宽泛检索：为PubMed中无直接文献的病毒补充检索")
    print(f"开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)
    
    all_pmids = set()
    search_stats = []
    
    for vidx, virus_group in enumerate(BROAD_QUERIES, 1):
        vname = virus_group["virus"]
        queries = virus_group["queries"]
        print(f"\n[{vidx}/{len(BROAD_QUERIES)}] 宽泛检索: {vname}")
        virus_pmids = set()
        
        for qidx, query in enumerate(queries, 1):
            print(f"  -> 查询 {qidx}/{len(queries)}: {query[:90]}...", end=" ", flush=True)
            try:
                pmids, count = esearch(query, retmax=500)
                new_pmids = [p for p in pmids if p not in all_pmids]
                virus_pmids.update(pmids)
                all_pmids.update(pmids)
                print(f"找到 {len(pmids)} 条 (新增 {len(new_pmids)} 条), 总计匹配 {count}")
                search_stats.append({
                    "virus": vname,
                    "query": query,
                    "found": len(pmids),
                    "new": len(new_pmids),
                    "total_count": count,
                })
                time.sleep(0.35)
            except Exception as e:
                print(f"失败: {e}")
                search_stats.append({
                    "virus": vname,
                    "query": query,
                    "found": 0,
                    "new": 0,
                    "total_count": 0,
                    "error": str(e),
                })
                time.sleep(1.0)
        
        print(f"  -> 该病毒共找到 {len(virus_pmids)} 条文献")
    
    print(f"\n{'='*60}")
    print(f"宽泛检索完成，去重后共 {len(all_pmids)} 条唯一PMID")
    print(f"{'='*60}")
    
    # 保存查询统计
    stats_path = OUT_DIR / "broad_search_stats.json"
    stats_path.write_text(json.dumps(search_stats, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"查询统计已保存: {stats_path}")
    
    # 获取文献详情
    pmid_list = sorted(all_pmids)
    if not pmid_list:
        print("未找到任何文献")
        return
    
    print(f"\n开始获取 {len(pmid_list)} 条文献详情...")
    all_articles = []
    batch_size = 200
    for i in range(0, len(pmid_list), batch_size):
        batch = pmid_list[i:i + batch_size]
        print(f"  批次 {i // batch_size + 1}/{(len(pmid_list) + batch_size - 1) // batch_size} ({len(batch)} 条)...", end=" ", flush=True)
        try:
            articles = efetch_pmids(batch)
            all_articles.extend(articles)
            print(f"成功获取 {len(articles)} 条")
            time.sleep(0.35)
        except Exception as e:
            print(f"失败: {e}")
            time.sleep(1.0)
    
    print(f"\n共获取 {len(all_articles)} 条文献详情")
    
    # 保存结果
    if all_articles:
        json_path = OUT_DIR / "broad_search_articles.json"
        json_path.write_text(json.dumps(all_articles, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"JSON已保存: {json_path}")
        
        csv_path = OUT_DIR / "broad_search_articles.csv"
        fieldnames = ["pmid", "title", "year", "journal", "authors", "doi", "pmcid", 
                      "keywords", "mesh_terms", "pubmed_url", "abstract"]
        with open(csv_path, "w", newline="", encoding="utf-8-sig") as fh:
            writer = csv.DictWriter(fh, fieldnames=fieldnames)
            writer.writeheader()
            for article in all_articles:
                writer.writerow({k: article.get(k, "") for k in fieldnames})
        print(f"CSV已保存: {csv_path}")
    
    print(f"\n所有文件保存在: {OUT_DIR}")

if __name__ == "__main__":
    main()
