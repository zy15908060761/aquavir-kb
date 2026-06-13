#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
批量下载PMC OA文献（高优先级）
支持断点续传和进度保存
"""

import csv
import json
import time
import urllib.request
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

session = requests.Session()
retries = Retry(total=2, backoff_factor=0.5, status_forcelist=[500, 502, 503, 504])
session.mount("https://", HTTPAdapter(max_retries=retries))
session.headers.update({"User-Agent": "crustacean-db-curator/1.0 (academic research)"})

def load_candidates():
    """加载高价值下载候选"""
    path = DB_DIR / "downloads" / "literature_gap_analysis" / "high_value_download_candidates.csv"
    rows = []
    with open(path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get("pmcid"):
                rows.append(row)
    return rows

def load_checkpoint():
    """加载断点续传状态"""
    cp_path = REPORT_DIR / "pmc_download_checkpoint.json"
    if cp_path.exists():
        return json.loads(cp_path.read_text(encoding="utf-8"))
    return {"completed_pmids": [], "failed_records": []}

def save_checkpoint(cp):
    cp_path = REPORT_DIR / "pmc_download_checkpoint.json"
    cp_path.write_text(json.dumps(cp, ensure_ascii=False, indent=2), encoding="utf-8")

def check_pmc_oa(pmc_id):
    url = f"https://www.ncbi.nlm.nih.gov/pmc/utils/oa/oa.fcgi?id={pmc_id}&format=tgz"
    try:
        resp = session.get(url, timeout=20)
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
    except Exception:
        return None

def download_pmc_pdf(pmc_id, out_path):
    """直接下载PMC PDF"""
    url = f"https://www.ncbi.nlm.nih.gov/pmc/articles/{pmc_id}/pdf/"
    try:
        resp = session.get(url, timeout=60)
        resp.raise_for_status()
        content_type = resp.headers.get("Content-Type", "")
        if "pdf" in content_type and len(resp.content) > 1024:
            with open(out_path, "wb") as f:
                f.write(resp.content)
            return True, len(resp.content)
        return False, "not_pdf_or_too_small"
    except Exception as exc:
        return False, str(exc)

def download_ftp(url, out_path):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "crustacean-db-curator/1.0"})
        with urllib.request.urlopen(req, timeout=90) as resp:
            data = resp.read()
            if len(data) < 1024:
                return False, "too_small"
            with open(out_path, "wb") as f:
                f.write(data)
            return True, len(data)
    except Exception as exc:
        return False, str(exc)

def sanitize_filename(text, max_len=80):
    import re, unicodedata
    text = unicodedata.normalize("NFKC", text or "")
    text = re.sub(r'[<>:"/\\|?*]+', "_", text)
    text = re.sub(r"\s+", " ", text).strip().strip(".")
    return text[:max_len]

def main():
    candidates = load_candidates()
    cp = load_checkpoint()
    completed = set(cp["completed_pmids"])
    failed = cp["failed_records"]
    
    # 过滤已完成的
    todo = [r for r in candidates if r["pmid"] not in completed]
    
    print("=" * 60)
    print(f"PMC OA批量下载")
    print(f"总PMC候选: {len(candidates)}")
    print(f"已完成: {len(completed)}")
    print(f"待下载: {len(todo)}")
    print("=" * 60)
    
    results = []
    for idx, row in enumerate(todo, 1):
        pmid = row["pmid"]
        pmc_id = row["pmcid"]
        title = row.get("title", "")
        virus = row.get("matched_virus", "unknown").replace("|", "_")
        
        print(f"\n[{idx}/{len(todo)}] PMID:{pmid} PMC:{pmc_id} ({virus})")
        
        safe_title = sanitize_filename(title)[:40]
        base_name = f"{pmid}_{safe_title}"
        
        result = {"pmid": pmid, "pmc_id": pmc_id, "title": title[:60], 
                  "virus": virus, "success": False, "path": "", "channel": "", "error": ""}
        
        # 1. 尝试PMC直接PDF
        out_pdf = OUT_DIR / f"{base_name}_PMC{pmc_id}.pdf"
        if out_pdf.exists():
            print(f"  -> PDF已存在")
            result["success"] = True
            result["path"] = str(out_pdf)
            result["channel"] = "pmc_direct_pdf"
        else:
            print("  -> 尝试PMC直接PDF...")
            ok, info = download_pmc_pdf(pmc_id, out_pdf)
            if ok:
                print(f"  -> PDF下载成功: {info} bytes")
                result["success"] = True
                result["path"] = str(out_pdf)
                result["channel"] = "pmc_direct_pdf"
            else:
                print(f"  -> PDF失败: {info}")
                result["error"] = f"pdf:{info}"
        
        # 2. 如果PDF失败，尝试OA tar.gz
        if not result["success"]:
            print("  -> 尝试PMC OA tar.gz...")
            href = check_pmc_oa(pmc_id)
            if href:
                out_tgz = OUT_DIR / f"{base_name}_PMC{pmc_id}.tar.gz"
                if out_tgz.exists():
                    print(f"  -> tar.gz已存在")
                    result["success"] = True
                    result["path"] = str(out_tgz)
                    result["channel"] = "pmc_oa_tgz"
                else:
                    ok, info = download_ftp(href, out_tgz)
                    if ok:
                        print(f"  -> tar.gz下载成功: {info} bytes")
                        result["success"] = True
                        result["path"] = str(out_tgz)
                        result["channel"] = "pmc_oa_tgz"
                    else:
                        print(f"  -> tar.gz失败: {info}")
                        result["error"] += f";tgz:{info}"
            else:
                print("  -> 非PMC OA")
                result["error"] += ";not_oa"
        
        if result["success"]:
            completed.add(pmid)
        else:
            failed.append({"pmid": pmid, "pmc_id": pmc_id, "error": result["error"]})
        
        results.append(result)
        
        # 每10条保存一次断点
        if idx % 10 == 0:
            cp["completed_pmids"] = list(completed)
            cp["failed_records"] = failed
            save_checkpoint(cp)
            print(f"  [检查点已保存] 完成:{len(completed)}/{len(candidates)}")
        
        time.sleep(0.3)
    
    # 最终保存
    cp["completed_pmids"] = list(completed)
    cp["failed_records"] = failed
    save_checkpoint(cp)
    
    success_count = sum(1 for r in results if r["success"])
    print(f"\n{'='*60}")
    print("PMC下载完成")
    print(f"{'='*60}")
    print(f"本次尝试: {len(results)}")
    print(f"成功: {success_count}")
    print(f"失败: {len(results) - success_count}")
    print(f"累计完成: {len(completed)}/{len(candidates)}")
    
    # 保存报告
    report_path = REPORT_DIR / "pmc_download_report.json"
    report_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"报告已保存: {report_path}")

if __name__ == "__main__":
    main()
