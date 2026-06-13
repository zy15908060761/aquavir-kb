#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
整合所有新检索到的文献到数据库
合并来源：外部匹配、新PubMed检索、宽泛检索
"""

import csv
import json
from pathlib import Path
from collections import defaultdict

DB_DIR = Path(r"F:\甲壳动物数据库")
LIT_DIR = DB_DIR / "literature_curation_v2"
OUT_DIR = DB_DIR / "downloads" / "literature_integrated"
OUT_DIR.mkdir(parents=True, exist_ok=True)

def load_csv_dict(path, key_field="pmid"):
    """加载CSV为字典，按key_field去重"""
    if not path.exists():
        return {}
    result = {}
    with open(path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            k = row.get(key_field, "")
            if k:
                result[k] = row
    return result

def load_existing_priority():
    """加载已有优先文献"""
    return load_csv_dict(LIT_DIR / "pmid_results_final.csv", "pmid")

def load_external_matched():
    """加载外部匹配文献"""
    return load_csv_dict(DB_DIR / "downloads" / "literature_gap_analysis" / "external_matched_articles.csv", "pmid")

def load_new_search():
    """加载新PubMed检索文献"""
    return load_csv_dict(DB_DIR / "downloads" / "literature_new_search" / "new_articles.csv", "pmid")

def load_broad_search():
    """加载宽泛检索文献"""
    return load_csv_dict(DB_DIR / "downloads" / "literature_broad_search" / "broad_search_articles.csv", "pmid")

def merge_articles():
    existing = load_existing_priority()
    external = load_external_matched()
    new_search = load_new_search()
    broad_search = load_broad_search()
    
    print(f"已有优先文献: {len(existing)}")
    print(f"外部匹配文献: {len(external)}")
    print(f"新PubMed检索: {len(new_search)}")
    print(f"宽泛检索文献: {len(broad_search)}")
    
    # 合并所有新文献
    merged = {}
    
    # 1. 从已有文献开始
    for pmid, row in existing.items():
        merged[pmid] = {
            "pmid": pmid,
            "title": row.get("title", ""),
            "authors": row.get("authors", ""),
            "source": row.get("source", ""),
            "pubdate": row.get("pubdate", ""),
            "pubyear": row.get("pubyear", ""),
            "doi": row.get("doi", ""),
            "pmc_id": row.get("pmc_id", ""),
            "is_pmc_oa": row.get("is_pmc_oa", "NO"),
            "matched_viruses": row.get("matched_viruses", ""),
            "matched_fields": row.get("matched_fields", ""),
            "n_sources": row.get("n_sources", "1"),
            "download_status": row.get("download_status", "pending"),
            "fulltext_path": row.get("fulltext_path", ""),
            "extraction_status": row.get("extraction_status", "pending"),
            "notes": row.get("notes", ""),
            "data_source": "original_priority",
        }
    
    # 2. 添加外部匹配文献
    for pmid, row in external.items():
        if pmid in merged:
            # 合并病毒匹配信息
            existing_viruses = set(merged[pmid]["matched_viruses"].split("|")) if merged[pmid]["matched_viruses"] else set()
            new_viruses = set(row.get("matched_virus", "").split("|")) if row.get("matched_virus") else set()
            merged_viruses = existing_viruses | new_viruses
            merged[pmid]["matched_viruses"] = "|".join(sorted(v for v in merged_viruses if v))
            
            # 合并字段
            existing_fields = set(merged[pmid]["matched_fields"].split("|")) if merged[pmid]["matched_fields"] else set()
            new_fields = set(row.get("matched_fields", "").split("|")) if row.get("matched_fields") else set()
            merged_fields = existing_fields | new_fields
            merged[pmid]["matched_fields"] = "|".join(sorted(f for f in merged_fields if f))
            
            merged[pmid]["data_source"] += "|external_matched"
            # 更新DOI/PMCID如果之前为空
            if not merged[pmid]["doi"] and row.get("doi"):
                merged[pmid]["doi"] = row["doi"]
            if not merged[pmid]["pmc_id"] and row.get("pmcid"):
                merged[pmid]["pmc_id"] = row["pmcid"]
        else:
            merged[pmid] = {
                "pmid": pmid,
                "title": row.get("title", ""),
                "authors": row.get("authors", ""),
                "source": row.get("journal", ""),
                "pubdate": "",
                "pubyear": row.get("year", ""),
                "doi": row.get("doi", ""),
                "pmc_id": row.get("pmcid", ""),
                "is_pmc_oa": "YES" if row.get("pmcid") else "NO",
                "matched_viruses": row.get("matched_virus", ""),
                "matched_fields": row.get("matched_fields", ""),
                "n_sources": "1",
                "download_status": "pending",
                "fulltext_path": "",
                "extraction_status": "pending",
                "notes": "",
                "data_source": "external_matched",
            }
    
    # 3. 添加新PubMed检索文献
    for pmid, row in new_search.items():
        if pmid in merged:
            merged[pmid]["data_source"] += "|new_search"
            if not merged[pmid]["doi"] and row.get("doi"):
                merged[pmid]["doi"] = row["doi"]
            if not merged[pmid]["pmc_id"] and row.get("pmcid"):
                merged[pmid]["pmc_id"] = row["pmcid"]
        else:
            merged[pmid] = {
                "pmid": pmid,
                "title": row.get("title", ""),
                "authors": row.get("authors", ""),
                "source": row.get("journal", ""),
                "pubdate": "",
                "pubyear": row.get("year", ""),
                "doi": row.get("doi", ""),
                "pmc_id": row.get("pmcid", ""),
                "is_pmc_oa": "YES" if row.get("pmcid") else "NO",
                "matched_viruses": "",
                "matched_fields": "",
                "n_sources": "1",
                "download_status": "pending",
                "fulltext_path": "",
                "extraction_status": "pending",
                "notes": "",
                "data_source": "new_pubmed_search",
            }
    
    # 4. 添加宽泛检索文献
    for pmid, row in broad_search.items():
        if pmid in merged:
            merged[pmid]["data_source"] += "|broad_search"
            if not merged[pmid]["doi"] and row.get("doi"):
                merged[pmid]["doi"] = row["doi"]
            if not merged[pmid]["pmc_id"] and row.get("pmcid"):
                merged[pmid]["pmc_id"] = row["pmcid"]
        else:
            merged[pmid] = {
                "pmid": pmid,
                "title": row.get("title", ""),
                "authors": row.get("authors", ""),
                "source": row.get("journal", ""),
                "pubdate": "",
                "pubyear": row.get("year", ""),
                "doi": row.get("doi", ""),
                "pmc_id": row.get("pmcid", ""),
                "is_pmc_oa": "YES" if row.get("pmcid") else "NO",
                "matched_viruses": "",
                "matched_fields": "",
                "n_sources": "1",
                "download_status": "pending",
                "fulltext_path": "",
                "extraction_status": "pending",
                "notes": "",
                "data_source": "broad_search",
            }
    
    return merged

def generate_reports(merged):
    print(f"\n合并后总文献数: {len(merged)}")
    
    # 按来源统计
    source_counts = defaultdict(int)
    for row in merged.values():
        for src in row["data_source"].split("|"):
            source_counts[src] += 1
    print("\n来源分布:")
    for src, cnt in sorted(source_counts.items(), key=lambda x: -x[1]):
        print(f"  {src}: {cnt}")
    
    # 按病毒统计覆盖
    virus_coverage = defaultdict(lambda: {"total": 0, "thermal": 0, "virulence": 0, "genome": 0, "oa": 0, "pmc": 0})
    for row in merged.values():
        viruses = row["matched_viruses"].split("|")
        fields = row["matched_fields"].split("|")
        is_oa = row["is_pmc_oa"] == "YES" or row.get("pmc_id")
        for v in viruses:
            v = v.strip()
            if not v:
                continue
            virus_coverage[v]["total"] += 1
            for f in fields:
                f = f.strip()
                if f in ("thermal", "virulence", "genome"):
                    virus_coverage[v][f] += 1
            if is_oa:
                virus_coverage[v]["oa"] += 1
            if row.get("pmc_id"):
                virus_coverage[v]["pmc"] += 1
    
    print("\n病毒文献覆盖 (Top 20):")
    for v, info in sorted(virus_coverage.items(), key=lambda x: -x[1]["total"])[:20]:
        print(f"  {v}: {info['total']}篇 (thermal:{info['thermal']}, virulence:{info['virulence']}, genome:{info['genome']}, OA:{info['oa']}, PMC:{info['pmc']})")
    
    # 保存完整合并表
    csv_path = OUT_DIR / "literature_merged_master.csv"
    fieldnames = ["pmid", "title", "authors", "source", "pubyear", "doi", "pmc_id", 
                  "is_pmc_oa", "matched_viruses", "matched_fields", "data_source",
                  "download_status", "fulltext_path", "extraction_status", "notes"]
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in merged.values():
            writer.writerow({k: row.get(k, "") for k in fieldnames})
    print(f"\n合并主表已保存: {csv_path}")
    
    # 保存病毒覆盖报告
    report_path = OUT_DIR / "virus_coverage_report.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump({k: dict(v) for k, v in virus_coverage.items()}, f, ensure_ascii=False, indent=2)
    print(f"病毒覆盖报告已保存: {report_path}")
    
    # 生成未覆盖病毒清单
    priority_path = LIT_DIR / "priority_viruses.csv"
    priority_viruses = []
    with open(priority_path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            priority_viruses.append(row["canonical_name"])
    
    uncovered = [v for v in priority_viruses if v not in virus_coverage]
    print(f"\n仍未被任何文献覆盖的优先病毒: {len(uncovered)}个")
    for v in uncovered:
        print(f"  - {v}")
    
    if uncovered:
        with open(OUT_DIR / "still_uncovered_viruses.txt", "w", encoding="utf-8") as f:
            f.write("仍未被任何文献覆盖的优先病毒:\n")
            for v in uncovered:
                f.write(f"- {v}\n")
    
    # 生成待下载清单（有PMCID的）
    pmc_pending = [r for r in merged.values() if r.get("pmc_id") and r.get("download_status") == "pending"]
    print(f"\n待下载PMC文献数: {len(pmc_pending)}")
    
    # 生成待下载清单（有DOI的）
    doi_pending = [r for r in merged.values() if r.get("doi") and not r.get("pmc_id") and r.get("download_status") == "pending"]
    print(f"待下载DOI-only文献数: {len(doi_pending)}")

def main():
    print("=" * 60)
    print("整合所有新检索到的文献")
    print("=" * 60)
    
    merged = merge_articles()
    generate_reports(merged)
    
    print(f"\n{'='*60}")
    print("整合完成")
    print(f"{'='*60}")

if __name__ == "__main__":
    main()
