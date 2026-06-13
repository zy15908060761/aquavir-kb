#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
将外部检索的大量文献与优先病毒进行匹配
挖掘已有文献库中的相关文献
"""

import csv
import re
import json
from pathlib import Path
from collections import defaultdict

DB_DIR = Path(r"F:\甲壳动物数据库")
EXT_DIR = Path(r"F:\水生无脊椎动物病毒文献检索")
OUT_DIR = DB_DIR / "downloads" / "literature_gap_analysis"
OUT_DIR.mkdir(parents=True, exist_ok=True)

def load_priority_viruses():
    path = DB_DIR / "literature_curation_v2" / "priority_viruses.csv"
    viruses = []
    with open(path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            viruses.append({
                "rank": row["rank"],
                "name": row["canonical_name"],
                "priority": row["priority"],
                "abbr": row.get("virus_abbr", ""),
                "family": row.get("virus_family", ""),
            })
    return viruses

def load_external_articles():
    path = EXT_DIR / "articles_final.csv"
    articles = []
    with open(path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            articles.append(row)
    return articles

def load_existing_pmids():
    path = DB_DIR / "literature_curation_v2" / "pmid_results_final.csv"
    pmids = set()
    with open(path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            pmids.add(row.get("pmid", ""))
    return pmids

def build_match_patterns(virus):
    """为病毒构建标题/摘要匹配模式"""
    name = virus["name"]
    patterns = [re.escape(name)]
    
    # 添加缩写匹配（如果有）
    abbr = virus["abbr"]
    if abbr and len(abbr) >= 3:
        patterns.append(re.escape(abbr))
    
    # 为一些常见病毒添加别名
    aliases = {
        "White spot syndrome virus": ["WSSV", "white spot syndrome"],
        "Taura syndrome virus": ["TSV", "Taura syndrome"],
        "Yellow head virus": ["YHV", "yellow head"],
        "Infectious hypodermal and hematopoietic necrosis virus": ["IHHNV"],
        "Infectious myonecrosis virus": ["IMNV"],
        "Macrobrachium rosenbergii nodavirus": ["MrNV"],
        "Decapod iridescent virus": ["DIV1", "decapod iridescent"],
        "Covert mortality nodavirus": ["CMNV"],
        "Hepatopancreatic parvovirus": ["HPV"],
        "Wenzhou shrimp virus": ["WzSV"],
        "Wenzhou crab virus": ["WzCV"],
        "Beihai crab virus": ["BhCV"],
        "Beihai shrimp virus": ["BhSV"],
        "Laem-Singh virus": ["LSV"],
        "Crab associated circular virus": ["CVCV"],
        "Scylla serrata reovirus SZ-2007": ["SsRV"],
        "Chinese mitten crab virus": ["CmcV"],
        "Brine shrimp chuvirus 1": ["BSCV1"],
        "Brine shrimp chuvirus 2": ["BSCV2"],
        "Brine shrimp iflavirus 1": ["BSIfV1"],
        "Brine shrimp iflavirus 3": ["BSIfV3"],
        "Macrobrachium rosenbergii Golda virus": ["MrGV"],
        "Macrobrachium rosenbergii virus 10": ["MrV10"],
        "Mud crab virus": ["MCV"],
    }
    
    if name in aliases:
        for alias in aliases[name]:
            if alias.lower() not in name.lower():
                patterns.append(re.escape(alias))
    
    # 添加family/genus级别匹配（对于unclassified病毒）
    family = virus["family"]
    if family and "unclassified" not in name.lower():
        # 如果病毒名已经包含family，不额外添加
        if family.lower() not in name.lower():
            patterns.append(re.escape(family))
    
    return [re.compile(r'\b' + p + r'\b', re.IGNORECASE) for p in patterns]

def classify_fields(title, abstract):
    text = (title + " " + abstract).lower()
    fields = []
    if any(k in text for k in ["temperature", "thermal", "heat", "cold stress", "°C"]):
        fields.append("thermal")
    if any(k in text for k in ["virulence", "pathogenicity", "lethal", "mortality", "ld50", "disease", "infection", "pathogen"]):
        fields.append("virulence")
    if any(k in text for k in ["genome", "sequence", "phylogen", " RdRp ", "capsid", "structural protein"]):
        fields.append("genome")
    return "|".join(fields) if fields else ""

def main():
    viruses = load_priority_viruses()
    articles = load_external_articles()
    existing_pmids = load_existing_pmids()
    
    print(f"优先病毒数: {len(viruses)}")
    print(f"外部文献数: {len(articles)}")
    print(f"已有PMID数: {len(existing_pmids)}")
    
    # 为每个病毒预编译匹配模式
    virus_patterns = {}
    for v in viruses:
        virus_patterns[v["name"]] = build_match_patterns(v)
    
    matches = defaultdict(list)
    matched_pmids = set()
    
    for idx, article in enumerate(articles):
        pmid = article.get("pmid", "")
        title = article.get("title", "")
        abstract = article.get("abstract", "")
        text = title + " " + abstract
        
        # 跳过已有文献
        if pmid in existing_pmids:
            continue
        
        for v in viruses:
            patterns = virus_patterns[v["name"]]
            if any(p.search(text) for p in patterns):
                fields = classify_fields(title, abstract)
                matches[v["name"]].append({
                    "pmid": pmid,
                    "title": title,
                    "year": article.get("year", ""),
                    "journal": article.get("journal", ""),
                    "authors": article.get("authors", ""),
                    "doi": article.get("doi", ""),
                    "pmcid": article.get("pmcid", ""),
                    "matched_fields": fields,
                    "pubmed_url": article.get("pubmed_url", ""),
                })
                matched_pmids.add(pmid)
        
        if (idx + 1) % 1000 == 0:
            print(f"  已处理 {idx + 1}/{len(articles)} 条文献...")
    
    print(f"\n匹配完成，共找到 {len(matched_pmids)} 条新关联文献")
    
    # 保存按病毒分类的匹配结果
    all_matches = []
    summary = {}
    for v in viruses:
        vname = v["name"]
        v_matches = matches.get(vname, [])
        summary[vname] = {
            "priority": v["priority"],
            "total_new_matches": len(v_matches),
            "has_doi": sum(1 for m in v_matches if m["doi"]),
            "has_pmcid": sum(1 for m in v_matches if m["pmcid"]),
            "thermal": sum(1 for m in v_matches if "thermal" in m["matched_fields"]),
            "virulence": sum(1 for m in v_matches if "virulence" in m["matched_fields"]),
        }
        for m in v_matches:
            m["matched_virus"] = vname
            all_matches.append(m)
    
    # 保存汇总
    summary_path = OUT_DIR / "external_match_summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"匹配汇总已保存: {summary_path}")
    
    # 保存所有匹配文献CSV
    if all_matches:
        csv_path = OUT_DIR / "external_matched_articles.csv"
        fieldnames = ["pmid", "title", "year", "journal", "authors", "doi", "pmcid", 
                      "matched_virus", "matched_fields", "pubmed_url"]
        with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for m in all_matches:
                writer.writerow({k: m.get(k, "") for k in fieldnames})
        print(f"匹配文献CSV已保存: {csv_path} ({len(all_matches)} 条)")
    
    # 打印汇总
    print("\n" + "="*60)
    print("各病毒新匹配文献数量 (Top 20)")
    print("="*60)
    for vname, info in sorted(summary.items(), key=lambda x: -x[1]["total_new_matches"])[:20]:
        if info["total_new_matches"] > 0:
            print(f"  {vname}: {info['total_new_matches']}篇 (DOI:{info['has_doi']}, PMC:{info['has_pmcid']}, thermal:{info['thermal']}, virulence:{info['virulence']})")
    
    # 生成高价值下载列表（有DOI或PMCID的）
    high_value = [m for m in all_matches if (m["doi"] or m["pmcid"])]
    print(f"\n高价值可下载文献数: {len(high_value)}")
    
    if high_value:
        hv_path = OUT_DIR / "high_value_download_candidates.csv"
        fieldnames = ["pmid", "title", "year", "journal", "authors", "doi", "pmcid", 
                      "matched_virus", "matched_fields", "pubmed_url"]
        with open(hv_path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            # 去重
            seen_pmids = set()
            for m in high_value:
                if m["pmid"] not in seen_pmids:
                    seen_pmids.add(m["pmid"])
                    writer.writerow({k: m.get(k, "") for k in fieldnames})
        print(f"高价值下载候选已保存: {hv_path}")

if __name__ == "__main__":
    main()
