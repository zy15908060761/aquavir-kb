#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
激进全文下载脚本 — 多渠道并行下载所有可获取的OA文献全文
1. PMC OA tar.gz (最可靠)
2. Europe PMC XML + PDF
3. Unpaywall OA PDF
4. 针对高优先级文献 (P0/P1病毒) 尝试所有渠道
"""

import csv
import hashlib
import json
import os
import re
import sqlite3
import sys
import tarfile
import time
import urllib.request
import urllib.error
from pathlib import Path
from xml.etree import ElementTree as ET
from collections import defaultdict

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

DB_PATH = Path(r"F:\甲壳动物数据库\crustacean_virus_core.db")
CURATION_DIR = Path(r"F:\甲壳动物数据库\literature_curation_v2")
OA_DIR = CURATION_DIR / "oa_fulltext"
PDF_DIR = CURATION_DIR / "fulltext"
XML_DIR = CURATION_DIR / "pmc_xml"
LOG_DIR = Path(r"F:\甲壳动物数据库\downloads\fulltext_download_log")
for d in [OA_DIR, PDF_DIR, XML_DIR, LOG_DIR]:
    d.mkdir(parents=True, exist_ok=True)

USER_AGENT = "CrustaVirusDB/1.0 (academic research; mailto:crustacean-db@proton.me)"
UNPAYWALL_EMAIL = "crustacean-db@proton.me"

session = requests.Session()
retries = Retry(total=2, backoff_factor=2, status_forcelist=[429, 500, 502, 503, 504])
session.mount("https://", HTTPAdapter(max_retries=retries))
session.headers.update({"User-Agent": USER_AGENT})


def db_connect():
    con = sqlite3.connect(str(DB_PATH), timeout=60)
    con.row_factory = sqlite3.Row
    return con


def sanitize_filename(text, max_len=80):
    text = re.sub(r'[<>:"/\\|?*]+', '_', text or '')
    text = re.sub(r'\s+', ' ', text).strip().strip('.')
    return text[:max_len]


def dedupe_key(ref_id, source):
    return f"{ref_id}_{source}"


# ================================================================
# 渠道1: PMC OA tar.gz (通过 PMCID)
# ================================================================
def try_pmc_oa(pmcid, ref_id, con):
    """通过PMCID下载PMC OA全文包"""
    if not pmcid:
        return None

    url = f"https://www.ncbi.nlm.nih.gov/pmc/utils/oa/oa.fcgi?id={pmcid}&format=tgz"
    try:
        resp = session.get(url, timeout=30)
        resp.raise_for_status()
        text = resp.text
        if 'idIsNotOpenAccess' in text or '<error' in text:
            return None
        # 找下载链接
        start = text.find('href="')
        if start < 0:
            return None
        start += len('href="')
        end = text.find('"', start)
        download_url = text[start:end]

        # 下载tgz包
        dl_resp = session.get(download_url, timeout=120)
        dl_resp.raise_for_status()

        # 保存
        out_path = OA_DIR / f"PMC{pmcid}.tar.gz"
        with open(out_path, 'wb') as f:
            f.write(dl_resp.content)

        # 解压并提取PDF和XML
        extracted = []
        try:
            with tarfile.open(out_path, 'r:gz') as tar:
                for member in tar.getmembers():
                    if member.name.lower().endswith('.pdf'):
                        pdf_name = f"PMC{pmcid}.pdf"
                        tar.extract(member, PDF_DIR)
                        # 重命名
                        src = PDF_DIR / member.name
                        dst = PDF_DIR / pdf_name
                        if src.exists() and not dst.exists():
                            src.rename(dst)
                        extracted.append(str(dst))
                    elif member.name.lower().endswith('.nxml') or member.name.lower().endswith('.xml'):
                        xml_name = f"PMC{pmcid}.nxml"
                        tar.extract(member, XML_DIR)
                        src = XML_DIR / member.name
                        dst = XML_DIR / xml_name
                        if src.exists() and not dst.exists():
                            src.rename(dst)
                        extracted.append(str(dst))
        except Exception:
            pass

        return {
            "local_path": str(out_path),
            "extracted": extracted,
            "content_type": "tgz",
        }
    except Exception as e:
        return None


# ================================================================
# 渠道2: Europe PMC (XML + PDF)
# ================================================================
def try_europe_pmc(pmid, doi, ref_id, con):
    """通过Europe PMC API获取全文"""
    results = {}

    if not pmid and not doi:
        return results

    # 2a: XML全文
    try:
        if pmid:
            eurl = f"https://www.ebi.ac.uk/europepmc/webservices/rest/{pmid}/fullTextXML"
        else:
            eurl = f"https://www.ebi.ac.uk/europepmc/webservices/rest/search/query={doi}&resultType=core&format=json"

        resp = session.get(eurl, timeout=30)
        if resp.status_code == 200 and len(resp.content) > 1000:
            xml_path = XML_DIR / f"PMID{pmid}_EPMC.xml" if pmid else f"DOI_{sanitize_filename(doi)}_EPMC.xml"
            with open(xml_path, 'wb') as f:
                f.write(resp.content)
            results["xml_path"] = str(xml_path)
    except Exception:
        pass

    # 2b: PDF (Europe PMC有时有OA PDF链接)
    try:
        if pmid:
            pdf_url = f"https://www.ebi.ac.uk/europepmc/webservices/rest/{pmid}/fullTextPDF"
            resp = session.head(pdf_url, timeout=15)
            if resp.status_code == 200:
                dl = session.get(pdf_url, timeout=60)
                if dl.status_code == 200 and len(dl.content) > 50000:
                    pdf_path = PDF_DIR / f"PMID{pmid}_EPMC.pdf"
                    with open(pdf_path, 'wb') as f:
                        f.write(dl.content)
                    results["pdf_path"] = str(pdf_path)
    except Exception:
        pass

    return results


# ================================================================
# 渠道3: Unpaywall (通过DOI)
# ================================================================
def try_unpaywall(doi, ref_id, con):
    """通过Unpaywall API查询OA PDF"""
    if not doi:
        return None

    try:
        url = f"https://api.unpaywall.org/v2/{doi}?email={UNPAYWALL_EMAIL}"
        resp = session.get(url, timeout=30)
        if resp.status_code != 200:
            return None

        data = resp.json()
        best_oa = data.get("best_oa_location") or {}
        oa_url = best_oa.get("url_for_pdf") or best_oa.get("url")

        if not oa_url:
            return None

        # 尝试下载PDF
        dl = session.get(oa_url, timeout=60, allow_redirects=True)
        if dl.status_code == 200 and len(dl.content) > 50000:
            # 检查是否是PDF
            content_type = dl.headers.get('Content-Type', '')
            if 'pdf' in content_type.lower() or oa_url.endswith('.pdf'):
                pdf_name = f"PMID_{ref_id}_{sanitize_filename(doi)}_unpaywall.pdf"
                pdf_path = PDF_DIR / pdf_name
                with open(pdf_path, 'wb') as f:
                    f.write(dl.content)
                return {"pdf_path": str(pdf_path), "oa_url": oa_url}

        return {"oa_url": oa_url}  # 有链接但下载失败
    except Exception:
        return None


# ================================================================
# 渠道4: PMC 直接PDF
# ================================================================
def try_pmc_direct_pdf(pmcid, ref_id, con):
    """直接通过PMC的PDF链接下载"""
    if not pmcid:
        return None
    try:
        pdf_url = f"https://www.ncbi.nlm.nih.gov/pmc/articles/{pmcid}/pdf/"
        resp = session.get(pdf_url, timeout=60, allow_redirects=True)
        if resp.status_code == 200 and len(resp.content) > 50000:
            content_type = resp.headers.get('Content-Type', '')
            if 'pdf' in content_type.lower():
                pdf_path = PDF_DIR / f"{pmcid}.pdf"
                with open(pdf_path, 'wb') as f:
                    f.write(resp.content)
                return str(pdf_path)
        return None
    except Exception:
        return None


# ================================================================
# 主下载循环
# ================================================================
def download_all():
    con = db_connect()
    cur = con.cursor()

    # 获取所有需要下载的参考文献 (有PMCID或DOI的)
    refs = cur.execute("""
        SELECT rl.reference_id, rl.pmid, rl.doi, rl.title,
               lfs.pmcid,
               lfs.status as current_status,
               lfs.local_path
        FROM ref_literatures rl
        LEFT JOIN literature_fulltext_sources lfs
            ON rl.reference_id = lfs.reference_id
        WHERE (rl.pmid IS NOT NULL OR rl.doi IS NOT NULL)
        ORDER BY
            CASE WHEN lfs.status = 'downloaded' THEN 1 ELSE 0 END,
            CASE WHEN lfs.status = 'failed' THEN 1 ELSE 0 END,
            rl.reference_id
    """).fetchall()

    print(f"待处理参考文献: {len(refs)}")

    stats = {
        "total": len(refs),
        "already_downloaded": 0,
        "newly_downloaded": 0,
        "no_oa": 0,
        "failed": 0,
        "skipped": 0,
        "by_source": defaultdict(int),
    }

    batch_size = 0
    start_time = time.time()

    for i, ref in enumerate(refs):
        ref_id = ref["reference_id"]
        pmid = ref["pmid"]
        doi = ref["doi"]
        pmcid = ref["pmcid"]
        status = ref["current_status"]
        title = (ref["title"] or "")[:100]

        # 跳过已下载的
        if status == "downloaded" and ref["local_path"]:
            stats["already_downloaded"] += 1
            continue

        # 跳过确认无OA的
        if status == "no_oa":
            stats["no_oa"] += 1
            continue

        downloaded = False
        results = {}

        # 按优先级尝试各渠道
        # 1. PMC OA (如果有PMCID)
        if pmcid:
            result = try_pmc_oa(pmcid, ref_id, con)
            if result:
                results["pmc_oa"] = result
                downloaded = True
                stats["by_source"]["pmc_oa"] += 1

        # 2. PMC直接PDF
        if not downloaded and pmcid:
            pdf_path = try_pmc_direct_pdf(pmcid, ref_id, con)
            if pdf_path:
                results["pmc_direct"] = pdf_path
                downloaded = True
                stats["by_source"]["pmc_direct"] += 1

        # 3. Europe PMC
        if not downloaded:
            epmc_results = try_europe_pmc(pmid, doi, ref_id, con)
            if epmc_results:
                results["europe_pmc"] = epmc_results
                if "pdf_path" in epmc_results or "xml_path" in epmc_results:
                    downloaded = True
                    stats["by_source"]["europe_pmc"] += 1

        # 4. Unpaywall
        if not downloaded and doi:
            result = try_unpaywall(doi, ref_id, con)
            if result and "pdf_path" in result:
                results["unpaywall"] = result
                downloaded = True
                stats["by_source"]["unpaywall"] += 1

        # 更新数据库状态
        if downloaded:
            local_path = ""
            if results:
                for source, r in results.items():
                    if isinstance(r, dict):
                        local_path = r.get("local_path", "") or "".join(
                            r.get("extracted", [])[:1])
                    elif isinstance(r, str):
                        local_path = r
                    if local_path:
                        break

            dkey = dedupe_key(ref_id, "multi_channel")
            try:
                cur.execute("""
                    INSERT OR REPLACE INTO literature_fulltext_sources
                    (reference_id, pmid, doi, pmcid, source, status, oa_status,
                     local_path, content_type, dedupe_key, raw_json)
                    VALUES (?, ?, ?, ?, 'multi_channel', 'downloaded', 'oa',
                            ?, 'pdf/xml', ?, ?)
                """, (ref_id, pmid, doi, pmcid, local_path, dkey,
                      json.dumps({k: str(v)[:500] for k, v in results.items()})))
                con.commit()
            except Exception:
                pass

            stats["newly_downloaded"] += 1
        else:
            # 标记为失败
            if status != "failed":
                try:
                    cur.execute("""
                        INSERT OR IGNORE INTO literature_fulltext_sources
                        (reference_id, pmid, doi, pmcid, source, status,
                         oa_status, dedupe_key)
                        VALUES (?, ?, ?, ?, 'multi_channel', 'failed', 'checked', ?)
                    """, (ref_id, pmid, doi, pmcid, dedupe_key(ref_id, "multi_channel")))
                    con.commit()
                except Exception:
                    pass
            stats["failed"] += 1

        batch_size += 1
        if batch_size % 50 == 0:
            elapsed = time.time() - start_time
            rate = batch_size / elapsed if elapsed > 0 else 0
            print(f"  [{batch_size}/{len(refs)}] "
                  f"已下载: {stats['newly_downloaded']}, "
                  f"失败: {stats['failed']}, "
                  f"速率: {rate:.1f}/s",
                  end='\r')

    con.close()

    # 最终统计
    print(f"\n\n{'=' * 60}")
    print("全文下载完成")
    print(f"{'=' * 60}")
    print(f"总文献: {stats['total']}")
    print(f"已有本地文件: {stats['already_downloaded']}")
    print(f"新增下载: {stats['newly_downloaded']}")
    print(f"确认无OA: {stats['no_oa']}")
    print(f"下载失败: {stats['failed']}")
    print(f"\n按渠道分布:")
    for source, cnt in sorted(stats['by_source'].items(), key=lambda x: -x[1]):
        print(f"  {source}: {cnt}")

    # 保存日志
    log_path = LOG_DIR / f"download_log_{int(time.time())}.json"
    log_path.write_text(json.dumps(stats, indent=2, ensure_ascii=False), encoding="utf-8")

    return stats


if __name__ == "__main__":
    download_all()
