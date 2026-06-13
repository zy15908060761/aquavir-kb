#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
批量查询Unpaywall获取DOI文献的OA PDF链接
不下载文件，只收集链接，支持断点续传
"""

import csv
import json
import time
import urllib.parse
from pathlib import Path
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

DB_DIR = Path(r"F:\甲壳动物数据库")
REPORT_DIR = DB_DIR / "downloads" / "literature_download_report"
REPORT_DIR.mkdir(parents=True, exist_ok=True)

UNPAYWALL_EMAIL = "crustacean.db.research@gmail.com"

session = requests.Session()
retries = Retry(total=2, backoff_factor=0.5, status_forcelist=[500, 502, 503, 504])
session.mount("https://", HTTPAdapter(max_retries=retries))
session.headers.update({"User-Agent": "crustacean-db-curator/1.0 (academic research)"})

def load_candidates():
    path = DB_DIR / "downloads" / "literature_gap_analysis" / "high_value_download_candidates.csv"
    rows = []
    with open(path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get("doi") and not row.get("pmcid"):
                rows.append(row)
    return rows

def load_checkpoint():
    cp_path = REPORT_DIR / "unpaywall_query_checkpoint.json"
    if cp_path.exists():
        return json.loads(cp_path.read_text(encoding="utf-8"))
    return {"completed_dois": [], "oa_links": [], "failed_dois": []}

def save_checkpoint(cp):
    cp_path = REPORT_DIR / "unpaywall_query_checkpoint.json"
    cp_path.write_text(json.dumps(cp, ensure_ascii=False, indent=2), encoding="utf-8")

def query_unpaywall(doi):
    url = f"https://api.unpaywall.org/v2/{urllib.parse.quote(doi)}?email={UNPAYWALL_EMAIL}"
    try:
        resp = session.get(url, timeout=20)
        if resp.status_code == 404:
            return {"is_oa": False, "error": "doi_not_found"}
        resp.raise_for_status()
        data = resp.json()
        
        best_oa = data.get("best_oa_location")
        if best_oa and best_oa.get("url_for_pdf"):
            return {
                "is_oa": True,
                "pdf_url": best_oa["url_for_pdf"],
                "landing_url": best_oa.get("url"),
                "license": best_oa.get("license", "unknown"),
                "source": "unpaywall_best",
                "journal_is_oa": data.get("journal_is_oa", False),
            }
        
        # 检查any location
        for loc in data.get("oa_locations", [])[:3]:
            if loc.get("url_for_pdf"):
                return {
                    "is_oa": True,
                    "pdf_url": loc["url_for_pdf"],
                    "landing_url": loc.get("url"),
                    "license": loc.get("license", "unknown"),
                    "source": "unpaywall_alt",
                    "journal_is_oa": data.get("journal_is_oa", False),
                }
        
        return {"is_oa": False, "journal_is_oa": data.get("journal_is_oa", False)}
    except Exception as exc:
        return {"is_oa": False, "error": str(exc)}

def main():
    candidates = load_candidates()
    cp = load_checkpoint()
    completed = set(cp["completed_dois"])
    oa_links = cp["oa_links"]
    failed = cp["failed_dois"]
    
    todo = [r for r in candidates if r["doi"] not in completed]
    
    print("=" * 60)
    print(f"Unpaywall批量查询")
    print(f"总DOI-only候选: {len(candidates)}")
    print(f"已完成查询: {len(completed)}")
    print(f"待查询: {len(todo)}")
    print("=" * 60)
    
    oa_count = 0
    for idx, row in enumerate(todo, 1):
        doi = row["doi"]
        pmid = row["pmid"]
        title = row.get("title", "")[:60]
        virus = row.get("matched_virus", "unknown")
        
        print(f"\n[{idx}/{len(todo)}] DOI:{doi[:50]}... ({virus})")
        
        result = query_unpaywall(doi)
        completed.add(doi)
        
        if result.get("is_oa"):
            print(f"  -> OA找到! PDF: {result['pdf_url'][:80]}...")
            oa_links.append({
                "pmid": pmid,
                "doi": doi,
                "title": title,
                "virus": virus,
                "pdf_url": result["pdf_url"],
                "landing_url": result.get("landing_url", ""),
                "license": result.get("license", ""),
                "source": result["source"],
                "journal_is_oa": result.get("journal_is_oa", False),
            })
            oa_count += 1
        else:
            err = result.get("error", "not_oa")
            print(f"  -> 非OA ({err})")
            failed.append({"pmid": pmid, "doi": doi, "reason": err})
        
        # 每20条保存一次
        if idx % 20 == 0:
            cp["completed_dois"] = list(completed)
            cp["oa_links"] = oa_links
            cp["failed_dois"] = failed
            save_checkpoint(cp)
            print(f"  [检查点已保存] OA找到:{oa_count}/{idx}")
        
        time.sleep(0.2)  # Unpaywall速率限制较宽松
    
    # 最终保存
    cp["completed_dois"] = list(completed)
    cp["oa_links"] = oa_links
    cp["failed_dois"] = failed
    save_checkpoint(cp)
    
    print(f"\n{'='*60}")
    print("Unpaywall查询完成")
    print(f"{'='*60}")
    print(f"总查询: {len(todo)}")
    print(f"找到OA PDF: {oa_count}")
    print(f"非OA/失败: {len(todo) - oa_count}")
    
    # 保存OA链接CSV
    if oa_links:
        csv_path = REPORT_DIR / "unpaywall_oa_links.csv"
        fieldnames = ["pmid", "doi", "title", "virus", "pdf_url", "landing_url", "license", "source", "journal_is_oa"]
        with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for link in oa_links:
                writer.writerow({k: link.get(k, "") for k in fieldnames})
        print(f"OA链接CSV已保存: {csv_path} ({len(oa_links)}条)")

if __name__ == "__main__":
    main()
