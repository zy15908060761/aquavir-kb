#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
为未覆盖的优先病毒批量检索PubMed文献
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
OUT_DIR = DB_DIR / "downloads" / "literature_new_search"
OUT_DIR.mkdir(parents=True, exist_ok=True)

def fetch(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()

def esearch(term, retmax=10000, retstart=0):
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

def build_queries(virus_name):
    """为给定病毒构建PubMed检索查询"""
    queries = []
    # 基础查询
    queries.append(("basic", f'({virus_name}[Title/Abstract]) AND (virus[Title/Abstract] OR viral[Title/Abstract] OR virome[Title/Abstract])'))
    # 毒力相关
    queries.append(("virulence", f'({virus_name}[Title/Abstract]) AND (virulence[Title/Abstract] OR pathogenicity[Title/Abstract] OR lethal[Title/Abstract] OR mortality[Title/Abstract] OR disease[Title/Abstract])'))
    # 温度相关
    queries.append(("thermal", f'({virus_name}[Title/Abstract]) AND (temperature[Title/Abstract] OR thermal[Title/Abstract] OR heat[Title/Abstract] OR cold[Title/Abstract])'))
    # 基因组/分类
    queries.append(("genome", f'({virus_name}[Title/Abstract]) AND (genome[Title/Abstract] OR sequence[Title/Abstract] OR phylogeny[Title/Abstract] OR phylogenetic[Title/Abstract])'))
    return queries

def main():
    # 读取未覆盖病毒列表
    queries_path = DB_DIR / "downloads" / "literature_gap_analysis" / "uncovered_virus_search_queries.csv"
    viruses = []
    with open(queries_path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            viruses.append(row)
    
    print("=" * 60)
    print(f"为 {len(viruses)} 个未覆盖优先病毒检索PubMed文献")
    print(f"开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)
    
    all_articles = []
    all_pmids = set()
    search_stats = []
    
    for vidx, virus in enumerate(viruses, 1):
        vname = virus["virus"]
        priority = virus["priority"]
        print(f"\n[{vidx}/{len(viruses)}] 检索病毒: {vname} (优先级: {priority})")
        
        queries = build_queries(vname)
        virus_pmids = set()
        
        for qtype, query in queries:
            print(f"  -> 查询 [{qtype}]: {query[:90]}...", end=" ", flush=True)
            try:
                pmids, count = esearch(query, retmax=500)
                new_pmids = [p for p in pmids if p not in all_pmids]
                virus_pmids.update(pmids)
                all_pmids.update(pmids)
                print(f"找到 {len(pmids)} 条 (新增 {len(new_pmids)} 条), 总计匹配 {count}")
                search_stats.append({
                    "virus": vname,
                    "query_type": qtype,
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
                    "query_type": qtype,
                    "query": query,
                    "found": 0,
                    "new": 0,
                    "total_count": 0,
                    "error": str(e),
                })
                time.sleep(1.0)
        
        print(f"  -> 该病毒共找到 {len(virus_pmids)} 条文献")
    
    print(f"\n{'='*60}")
    print(f"检索完成，去重后共 {len(all_pmids)} 条唯一PMID")
    print(f"{'='*60}")
    
    # 保存查询统计
    stats_path = OUT_DIR / "search_stats.json"
    stats_path.write_text(json.dumps(search_stats, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"查询统计已保存: {stats_path}")
    
    # 获取文献详情
    pmid_list = sorted(all_pmids)
    print(f"\n开始获取 {len(pmid_list)} 条文献详情...")
    
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
        # JSON
        json_path = OUT_DIR / "new_articles.json"
        json_path.write_text(json.dumps(all_articles, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"JSON已保存: {json_path}")
        
        # CSV
        csv_path = OUT_DIR / "new_articles.csv"
        fieldnames = ["pmid", "title", "year", "journal", "authors", "doi", "pmcid", 
                      "keywords", "mesh_terms", "pubmed_url", "abstract"]
        with open(csv_path, "w", newline="", encoding="utf-8-sig") as fh:
            writer = csv.DictWriter(fh, fieldnames=fieldnames)
            writer.writeheader()
            for article in all_articles:
                writer.writerow({k: article.get(k, "") for k in fieldnames})
        print(f"CSV已保存: {csv_path}")
        
        # 按病毒分类保存PMID列表（用于后续匹配）
        # 这里简化处理，实际可以通过标题/摘要关键词匹配
    
    # 摘要统计
    year_counts = {}
    journal_counts = {}
    for a in all_articles:
        y = a.get("year", "NA") or "NA"
        year_counts[y] = year_counts.get(y, 0) + 1
        j = a.get("journal", "Unknown") or "Unknown"
        journal_counts[j] = journal_counts.get(j, 0) + 1
    
    print(f"\n{'='*60}")
    print("检索结果摘要")
    print(f"{'='*60}")
    print(f"总文献数: {len(all_articles)}")
    print(f"\n年份分布 (Top 10):")
    for y, c in sorted(year_counts.items(), key=lambda x: x[0], reverse=True)[:10]:
        print(f"  {y}: {c} 篇")
    print(f"\n期刊分布 (Top 10):")
    for j, c in sorted(journal_counts.items(), key=lambda x: x[1], reverse=True)[:10]:
        print(f"  {j}: {c} 篇")
    print(f"\n所有文件保存在: {OUT_DIR}")

if __name__ == "__main__":
    main()
