#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
分析甲壳动物病毒数据库的文献缺口
"""

import csv
import json
from pathlib import Path
from collections import defaultdict

DB_DIR = Path(r"F:\甲壳动物数据库")
LIT_DIR = DB_DIR / "literature_curation_v2"
OUT_DIR = DB_DIR / "downloads" / "literature_gap_analysis"
OUT_DIR.mkdir(parents=True, exist_ok=True)

def load_priority_viruses():
    path = LIT_DIR / "priority_viruses.csv"
    viruses = []
    with open(path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            viruses.append(row)
    return viruses

def load_pmid_results():
    path = LIT_DIR / "pmid_results_final.csv"
    rows = []
    with open(path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    return rows

def analyze():
    viruses = load_priority_viruses()
    pmids = load_pmid_results()
    
    # 1. 统计病毒profile缺口
    missing_vir = [v for v in viruses if v.get("has_vir_profile", "").lower() != "true"]
    missing_temp = [v for v in viruses if v.get("has_temp_profile", "").lower() != "true"]
    missing_both = [v for v in viruses if v.get("has_vir_profile", "").lower() != "true" and v.get("has_temp_profile", "").lower() != "true"]
    
    print("=" * 60)
    print("优先病毒文献缺口分析")
    print("=" * 60)
    print(f"总优先病毒数: {len(viruses)}")
    print(f"缺少 vir_profile: {len(missing_vir)}")
    print(f"缺少 temp_profile: {len(missing_temp)}")
    print(f"两者都缺: {len(missing_both)}")
    
    print("\n--- 缺少 vir_profile 的病毒 (Top 20) ---")
    for v in missing_vir[:20]:
        print(f"  {v['rank']:>3}. {v['canonical_name']} (优先级: {v['priority']}, 分离株: {v['n_isolates']})")
    
    print("\n--- 缺少 temp_profile 的病毒 (Top 20) ---")
    for v in missing_temp[:20]:
        print(f"  {v['rank']:>3}. {v['canonical_name']} (优先级: {v['priority']}, 分离株: {v['n_isolates']})")
    
    # 2. 已有PMID覆盖分析
    virus_coverage = defaultdict(lambda: {"thermal": 0, "virulence": 0, "total": 0, "oa": 0, "pmc": 0})
    for row in pmids:
        vnames = row.get("matched_viruses", "")
        fields = row.get("matched_fields", "")
        is_oa = row.get("is_pmc_oa", "") == "YES"
        pmc_id = row.get("pmc_id", "")
        for vname in vnames.split("|"):
            vname = vname.strip()
            if not vname:
                continue
            virus_coverage[vname]["total"] += 1
            if "thermal" in fields:
                virus_coverage[vname]["thermal"] += 1
            if "virulence" in fields:
                virus_coverage[vname]["virulence"] += 1
            if is_oa:
                virus_coverage[vname]["oa"] += 1
            if pmc_id:
                virus_coverage[vname]["pmc"] += 1
    
    print("\n--- 已有PMID文献覆盖的病毒 ---")
    for vname in sorted(virus_coverage.keys()):
        cov = virus_coverage[vname]
        print(f"  {vname}: 总{cov['total']}篇, thermal={cov['thermal']}, virulence={cov['virulence']}, OA={cov['oa']}, PMC={cov['pmc']}")
    
    # 3. 未覆盖的优先病毒
    covered_names = set(virus_coverage.keys())
    uncovered = [v for v in viruses if v["canonical_name"] not in covered_names]
    print(f"\n--- 完全没有PMID文献覆盖的优先病毒 ({len(uncovered)}个) ---")
    for v in uncovered:
        print(f"  {v['rank']:>3}. {v['canonical_name']} (优先级: {v['priority']})")
    
    # 4. 可下载的OA文献统计
    oa_to_download = [r for r in pmids if r.get("is_pmc_oa") == "YES" and r.get("pmc_id")]
    print(f"\n--- 可下载OA文献 ---")
    print(f"  PMC OA标识的文献总数: {len(oa_to_download)}")
    
    # 检查已下载
    oa_dir = LIT_DIR / "oa_fulltext"
    downloaded = list(oa_dir.glob("*")) if oa_dir.exists() else []
    downloaded_pmids = set()
    for d in downloaded:
        # 文件名格式: {pmid}_PMC{pmc_id}_{virus}.pdf 或 .tar.gz
        parts = d.stem.split("_")
        if parts:
            downloaded_pmids.add(parts[0])
    print(f"  已下载文件数: {len(downloaded)}")
    print(f"  已覆盖PMID数: {len(downloaded_pmids)}")
    print(f"  待下载PMC OA文献数: {len(oa_to_download) - len(downloaded_pmids)}")
    
    # 5. missing_fulltext 分析
    missing_path = LIT_DIR / "missing_fulltext.csv"
    if missing_path.exists():
        with open(missing_path, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            missing_rows = list(reader)
        print(f"\n--- missing_fulltext.csv 中需要手动获取的文献: {len(missing_rows)}篇 ---")
        virus_missing = defaultdict(int)
        for row in missing_rows:
            for v in row.get("matched_viruses", "").split("|"):
                virus_missing[v.strip()] += 1
        for v, c in sorted(virus_missing.items(), key=lambda x: -x[1]):
            print(f"  {v}: {c}篇")
    
    # 保存缺口报告
    report = {
        "total_priority_viruses": len(viruses),
        "missing_vir_profile": len(missing_vir),
        "missing_temp_profile": len(missing_temp),
        "missing_both": len(missing_both),
        "covered_viruses": len(covered_names),
        "uncovered_viruses": [
            {"rank": v["rank"], "name": v["canonical_name"], "priority": v["priority"], "n_isolates": v["n_isolates"]}
            for v in uncovered
        ],
        "missing_vir_profile_list": [
            {"rank": v["rank"], "name": v["canonical_name"], "priority": v["priority"]}
            for v in missing_vir
        ],
        "missing_temp_profile_list": [
            {"rank": v["rank"], "name": v["canonical_name"], "priority": v["priority"]}
            for v in missing_temp
        ],
        "oa_total": len(oa_to_download),
        "oa_downloaded": len(downloaded_pmids),
        "oa_pending": len(oa_to_download) - len(downloaded_pmids),
        "pmid_total": len(pmids),
        "virus_coverage": {k: dict(v) for k, v in virus_coverage.items()},
    }
    
    report_path = OUT_DIR / "gap_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n缺口报告已保存: {report_path}")
    
    # 生成待下载OA清单
    pending_oa = []
    for r in oa_to_download:
        pmid = r["pmid"]
        if pmid not in downloaded_pmids:
            pending_oa.append(r)
    
    if pending_oa:
        oa_csv = OUT_DIR / "pending_oa_downloads.csv"
        with open(oa_csv, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=["pmid", "pmc_id", "title", "doi", "matched_viruses", "matched_fields"])
            writer.writeheader()
            for r in pending_oa:
                writer.writerow({
                    "pmid": r["pmid"],
                    "pmc_id": r["pmc_id"],
                    "title": r.get("title", ""),
                    "doi": r.get("doi", ""),
                    "matched_viruses": r.get("matched_viruses", ""),
                    "matched_fields": r.get("matched_fields", ""),
                })
        print(f"待下载OA清单已保存: {oa_csv} ({len(pending_oa)}条)")
    
    # 生成未覆盖病毒的检索查询
    search_queries = []
    for v in uncovered:
        name = v["canonical_name"]
        # 构造简单PubMed查询
        search_queries.append({
            "virus": name,
            "priority": v["priority"],
            "query": f'({name}[Title/Abstract]) AND (virus[Title/Abstract] OR viral[Title/Abstract])',
            "query_virulence": f'({name}[Title/Abstract]) AND (virulence[Title/Abstract] OR pathogenicity[Title/Abstract] OR lethal[Title/Abstract] OR mortality[Title/Abstract])',
            "query_thermal": f'({name}[Title/Abstract]) AND (temperature[Title/Abstract] OR thermal[Title/Abstract] OR heat[Title/Abstract])',
        })
    
    if search_queries:
        query_csv = OUT_DIR / "uncovered_virus_search_queries.csv"
        with open(query_csv, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=["virus", "priority", "query", "query_virulence", "query_thermal"])
            writer.writeheader()
            for q in search_queries:
                writer.writerow(q)
        print(f"未覆盖病毒检索查询已保存: {query_csv} ({len(search_queries)}条)")

if __name__ == "__main__":
    analyze()
