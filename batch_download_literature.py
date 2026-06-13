#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
批量下载甲壳动物病毒数据库文献全文
多渠道：PMC OA, Unpaywall, Semantic Scholar
"""

import csv
import json
import time
import urllib.request
import urllib.parse
from pathlib import Path
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

DB_DIR = Path(r"F:\甲壳动物数据库")
LIT_DIR = DB_DIR / "literature_curation_v2"
OUT_DIR = LIT_DIR / "oa_fulltext"
OUT_DIR.mkdir(parents=True, exist_ok=True)
REPORT_DIR = DB_DIR / "downloads" / "literature_download_report"
REPORT_DIR.mkdir(parents=True, exist_ok=True)

# 配置session
session = requests.Session()
retries = Retry(total=3, backoff_factor=1, status_forcelist=[500, 502, 503, 504])
session.mount("https://", HTTPAdapter(max_retries=retries))
session.headers.update({"User-Agent": "crustacean-db-curator/1.0 (academic research)"})

# Unpaywall 邮箱（必填）
UNPAYWALL_EMAIL = "crustacean.db.research@gmail.com"

def sanitize_filename(text, max_len=100):
    import re, unicodedata
    text = unicodedata.normalize("NFKC", text or "")
    text = re.sub(r'[<>:"/\\|?*]+', "_", text)
    text = re.sub(r"\s+", " ", text).strip().strip(".")
    return text[:max_len]

def check_pmc_oa(pmc_id):
    """检查PMC是否为OA并返回下载链接"""
    url = f"https://www.ncbi.nlm.nih.gov/pmc/utils/oa/oa.fcgi?id=PMC{pmc_id}&format=tgz"
    try:
        resp = session.get(url, timeout=30)
        resp.raise_for_status()
        text = resp.text
        if 'idIsNotOpenAccess' in text or '<error' in text:
            return None
        start = text.find('href="')
        if start == -1:
            return None
        start += len('href="')
        end = text.find('"', start)
        return text[start:end]
    except Exception as exc:
        return None

def download_file(url, out_path, timeout=120):
    """通用文件下载"""
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "crustacean-db-curator/1.0 (academic research)"
        })
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read()
            if len(data) < 1024:
                return False, f"too_small:{len(data)}"
            with open(out_path, "wb") as f:
                f.write(data)
            return True, len(data)
    except Exception as exc:
        return False, str(exc)

def check_unpaywall(doi):
    """通过Unpaywall查询OA状态"""
    if not doi:
        return None
    url = f"https://api.unpaywall.org/v2/{urllib.parse.quote(doi)}?email={UNPAYWALL_EMAIL}"
    try:
        resp = session.get(url, timeout=30)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        data = resp.json()
        best_oa = data.get("best_oa_location")
        if best_oa and best_oa.get("url_for_pdf"):
            return {
                "pdf_url": best_oa["url_for_pdf"],
                "license": best_oa.get("license", "unknown"),
                "source": "unpaywall"
            }
        # 也检查any location
        for loc in data.get("oa_locations", []):
            if loc.get("url_for_pdf"):
                return {
                    "pdf_url": loc["url_for_pdf"],
                    "license": loc.get("license", "unknown"),
                    "source": "unpaywall_alt"
                }
        return None
    except Exception as exc:
        return None

def check_semantic_scholar(doi):
    """通过Semantic Scholar查询PDF"""
    if not doi:
        return None
    url = f"https://api.semanticscholar.org/graph/v1/paper/DOI:{urllib.parse.quote(doi)}?fields=openAccessPdf"
    try:
        resp = session.get(url, timeout=30)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        data = resp.json()
        oa = data.get("openAccessPdf")
        if oa and oa.get("url"):
            return {
                "pdf_url": oa["url"],
                "source": "semantic_scholar"
            }
        return None
    except Exception as exc:
        return None

def try_pmc_pdf(pmc_id):
    """尝试直接下载PMC PDF"""
    url = f"https://www.ncbi.nlm.nih.gov/pmc/articles/PMC{pmc_id}/pdf/"
    try:
        resp = session.get(url, timeout=60)
        resp.raise_for_status()
        content_type = resp.headers.get("Content-Type", "")
        if "pdf" in content_type and len(resp.content) > 1024:
            return {"pdf_url": url, "source": "pmc_direct_pdf"}
        return None
    except Exception:
        return None

def process_literature(csv_path, source_name, limit=None):
    """处理文献CSV并尝试下载"""
    with open(csv_path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    
    if limit:
        rows = rows[:limit]
    
    print(f"[{source_name}] 总文献数: {len(rows)}")
    
    results = []
    for idx, row in enumerate(rows, 1):
        pmid = row.get("pmid", "")
        doi = row.get("doi", "")
        pmc_id = row.get("pmc_id", "")
        title = row.get("title", "")
        
        print(f"\n[{idx}/{len(rows)}] PMID:{pmid} DOI:{doi}")
        
        result = {
            "pmid": pmid, "doi": doi, "pmc_id": pmc_id, "title": title[:80],
            "source": source_name, "success": False, "path": "", "channel": "", "error": ""
        }
        
        safe_title = sanitize_filename(title)[:50]
        base_name = f"{pmid}_{safe_title}" if pmid else f"DOI_{sanitize_filename(doi)[:30]}"
        
        # 1. 优先尝试PMC OA tar.gz
        if pmc_id:
            print("  -> 检查PMC OA...")
            href = check_pmc_oa(pmc_id)
            if href:
                out_path = OUT_DIR / f"{base_name}_PMC{pmc_id}.tar.gz"
                if out_path.exists():
                    print(f"  -> 已存在: {out_path.name}")
                    result["success"] = True
                    result["path"] = str(out_path)
                    result["channel"] = "pmc_oa_tgz"
                else:
                    ok, info = download_file(href, out_path)
                    if ok:
                        print(f"  -> 下载成功 (PMC OA tar.gz): {info} bytes")
                        result["success"] = True
                        result["path"] = str(out_path)
                        result["channel"] = "pmc_oa_tgz"
                    else:
                        print(f"  -> 下载失败: {info}")
                        result["error"] = f"pmc_oa_tgz:{info}"
                if result["success"]:
                    results.append(result)
                    time.sleep(0.5)
                    continue
        
        # 2. 尝试PMC直接PDF
        if pmc_id and not result["success"]:
            print("  -> 尝试PMC直接PDF...")
            pdf_info = try_pmc_pdf(pmc_id)
            if pdf_info:
                out_path = OUT_DIR / f"{base_name}_PMC{pmc_id}.pdf"
                if out_path.exists():
                    print(f"  -> 已存在: {out_path.name}")
                    result["success"] = True
                    result["path"] = str(out_path)
                    result["channel"] = "pmc_direct_pdf"
                else:
                    ok, info = download_file(pdf_info["pdf_url"], out_path)
                    if ok:
                        print(f"  -> 下载成功 (PMC PDF): {info} bytes")
                        result["success"] = True
                        result["path"] = str(out_path)
                        result["channel"] = "pmc_direct_pdf"
                    else:
                        result["error"] += f";pmc_pdf:{info}"
                if result["success"]:
                    results.append(result)
                    time.sleep(0.5)
                    continue
        
        # 3. 尝试Unpaywall
        if doi and not result["success"]:
            print("  -> 查询Unpaywall...")
            up_info = check_unpaywall(doi)
            if up_info:
                out_path = OUT_DIR / f"{base_name}_unpaywall.pdf"
                if out_path.exists():
                    print(f"  -> 已存在: {out_path.name}")
                    result["success"] = True
                    result["path"] = str(out_path)
                    result["channel"] = "unpaywall"
                else:
                    ok, info = download_file(up_info["pdf_url"], out_path)
                    if ok:
                        print(f"  -> 下载成功 (Unpaywall): {info} bytes")
                        result["success"] = True
                        result["path"] = str(out_path)
                        result["channel"] = "unpaywall"
                    else:
                        result["error"] += f";unpaywall:{info}"
                if result["success"]:
                    results.append(result)
                    time.sleep(0.5)
                    continue
            else:
                print("  -> Unpaywall无OA链接")
        
        # 4. 尝试Semantic Scholar
        if doi and not result["success"]:
            print("  -> 查询Semantic Scholar...")
            s2_info = check_semantic_scholar(doi)
            if s2_info:
                out_path = OUT_DIR / f"{base_name}_s2.pdf"
                if out_path.exists():
                    print(f"  -> 已存在: {out_path.name}")
                    result["success"] = True
                    result["path"] = str(out_path)
                    result["channel"] = "semantic_scholar"
                else:
                    ok, info = download_file(s2_info["pdf_url"], out_path)
                    if ok:
                        print(f"  -> 下载成功 (S2): {info} bytes")
                        result["success"] = True
                        result["path"] = str(out_path)
                        result["channel"] = "semantic_scholar"
                    else:
                        result["error"] += f";s2:{info}"
                if result["success"]:
                    results.append(result)
                    time.sleep(0.5)
                    continue
            else:
                print("  -> Semantic Scholar无OA链接")
        
        if not result["success"]:
            print("  -> 所有渠道均失败")
            result["error"] = result["error"].strip(";")
        
        results.append(result)
        time.sleep(0.5)  # 速率限制
    
    return results

def main():
    all_results = []
    
    # 1. 处理 missing_fulltext.csv (最优先)
    missing_path = LIT_DIR / "missing_fulltext.csv"
    if missing_path.exists():
        print("\n" + "="*60)
        print("阶段1: 处理 missing_fulltext.csv (50篇关键缺失文献)")
        print("="*60)
        results = process_literature(missing_path, "missing_fulltext")
        all_results.extend(results)
        
        report_path = REPORT_DIR / "download_report_missing.json"
        report_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        success = sum(1 for r in results if r["success"])
        print(f"\nmissing_fulltext 下载完成: {success}/{len(results)} 成功")
    
    # 2. 处理 pmid_results_final.csv (优先文献)
    print("\n" + "="*60)
    print("阶段2: 处理 pmid_results_final.csv (406篇优先文献)")
    print("="*60)
    pmid_path = LIT_DIR / "pmid_results_final.csv"
    results = process_literature(pmid_path, "priority_pmid")
    all_results.extend(results)
    
    report_path = REPORT_DIR / "download_report_priority.json"
    report_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    success = sum(1 for r in results if r["success"])
    print(f"\nPriority PMID 下载完成: {success}/{len(results)} 成功")
    
    # 3. 保存总报告
    total_success = sum(1 for r in all_results if r["success"])
    print(f"\n{'='*60}")
    print("总下载报告")
    print(f"{'='*60}")
    print(f"总尝试: {len(all_results)}")
    print(f"成功下载: {total_success}")
    print(f"失败: {len(all_results) - total_success}")
    
    # 按渠道统计
    channels = {}
    for r in all_results:
        if r["success"]:
            ch = r["channel"]
            channels[ch] = channels.get(ch, 0) + 1
    print("\n成功渠道分布:")
    for ch, cnt in sorted(channels.items(), key=lambda x: -x[1]):
        print(f"  {ch}: {cnt}")
    
    summary = {
        "total_attempted": len(all_results),
        "total_success": total_success,
        "channel_distribution": channels,
        "results": all_results
    }
    summary_path = REPORT_DIR / "download_summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n完整报告已保存: {REPORT_DIR}")

if __name__ == "__main__":
    main()
