#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""重试失败的全文下载 — 增强版
策略:
1. 有 PMCID → PMC OA tar.gz (NCBI 美国服务器, 中国可访问)
2. 有 PMID → NCBI E-utilities efetch → 尝试找 PMCID, 然后走 PMC OA
3. 有 DOI  → Unpaywall API + Semantic Scholar API
4. 更长超时 + 更多重试 + HTTP降级
"""

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
from datetime import datetime

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

DB_PATH = Path(r"F:\甲壳动物数据库\crustacean_virus_core.db")
PDF_DIR = Path(r"F:\甲壳动物数据库\literature_curation_v2\fulltext")
XML_DIR = Path(r"F:\甲壳动物数据库\literature_curation_v2\pmc_xml")
OA_DIR = Path(r"F:\甲壳动物数据库\literature_curation_v2\oa_fulltext")
for d in [PDF_DIR, XML_DIR, OA_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# 增强的session: 5次重试, 更长退避
session = requests.Session()
retries = Retry(total=5, backoff_factor=3, status_forcelist=[429, 500, 502, 503, 504])
session.mount("https://", HTTPAdapter(max_retries=retries, pool_connections=10, pool_maxsize=20))
session.headers.update({
    "User-Agent": "CrustaVirusDB/1.0 (academic research; mailto:crustacean-db@proton.me)",
    "Accept": "application/pdf, application/xml, text/xml, */*",
})
session.timeout = 90  # 全局超时90秒


def sanitize(text, max_len=80):
    return re.sub(r'[<>:"/\\|?*]+', '_', text or '')[:max_len].strip()


# ===========================================================
# 渠道1: NCBI PMC OA (美国服务器 — 中国网络通常可达)
# ===========================================================
def download_pmc_oa(pmcid, pmid=""):
    """通过PMCID从NCBI下载OA全文包"""
    if not pmcid:
        return None
    pmcid = pmcid.replace("PMC", "")

    # Step 1: 查询OA状态
    oa_url = f"https://www.ncbi.nlm.nih.gov/pmc/utils/oa/oa.fcgi?id=PMC{pmcid}&format=tgz"
    for attempt in range(3):
        try:
            resp = session.get(oa_url, timeout=60)
            resp.raise_for_status()
            text = resp.text
            if 'idIsNotOpenAccess' in text or '<error' in text:
                return {"status": "not_oa", "reason": text[:200]}

            start = text.find('href="')
            if start < 0:
                return {"status": "no_link"}
            start += len('href="')
            end = text.find('"', start)
            download_url = text[start:end]

            # Step 2: 下载 tgz
            dl = session.get(download_url, timeout=180)
            dl.raise_for_status()

            out_path = OA_DIR / f"PMC{pmcid}.tar.gz"
            with open(out_path, 'wb') as f:
                f.write(dl.content)

            # Step 3: 解压提取 PDF/XML
            extracted = []
            try:
                with tarfile.open(out_path, 'r:gz') as tar:
                    for member in tar.getmembers():
                        name = member.name.lower()
                        if name.endswith('.pdf'):
                            tar.extract(member, PDF_DIR)
                            extracted.append('pdf')
                        elif name.endswith('.nxml') or (name.endswith('.xml') and 'article' in name):
                            tar.extract(member, XML_DIR)
                            extracted.append('xml')
            except Exception:
                pass

            return {
                "status": "downloaded",
                "local_path": str(out_path),
                "bytes": len(dl.content),
                "extracted": extracted,
            }
        except Exception as e:
            if attempt < 2:
                time.sleep(5 * (attempt + 1))
            else:
                return {"status": "failed", "reason": str(e)[:200]}
    return None


# ===========================================================
# 渠道2: NCBI E-utilities — 通过 PMID 找 PMCID
# ===========================================================
def pmid_to_pmcid(pmid):
    """通过NCBI E-utilities将PMID转换为PMCID"""
    if not pmid:
        return None
    url = f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=pubmed&id={pmid}&retmode=xml"
    for attempt in range(3):
        try:
            resp = session.get(url, timeout=60)
            resp.raise_for_status()
            text = resp.text
            # 查找 PMC ID
            m = re.search(r'<article-id\s+pub-id-type="pmc">PMC(\d+)</article-id>', text)
            if not m:
                m = re.search(r'pmc[:\s]+PMC(\d+)', text, re.IGNORECASE)
            if m:
                return m.group(1)
            return None
        except Exception:
            if attempt < 2:
                time.sleep(3)
    return None


# ===========================================================
# 渠道3: 多种方式重试 Unpaywall
# ===========================================================
def try_unpaywall_v2(doi):
    """增强版Unpaywall — 多次重试"""
    if not doi:
        return None
    url = f"https://api.unpaywall.org/v2/{doi}?email=crustacean-db@proton.me"
    for attempt in range(3):
        try:
            resp = session.get(url, timeout=60)
            if resp.status_code != 200:
                if attempt < 2:
                    time.sleep(10)
                continue
            data = resp.json()
            best = data.get("best_oa_location") or {}
            pdf_url = best.get("url_for_pdf") or best.get("url")
            if pdf_url:
                # 尝试下载PDF
                for dl_attempt in range(2):
                    try:
                        dl = session.get(pdf_url, timeout=120, allow_redirects=True)
                        if dl.status_code == 200 and len(dl.content) > 50000:
                            pdf_name = f"DOI_{sanitize(doi)}_unpaywall.pdf"
                            pdf_path = PDF_DIR / pdf_name
                            with open(pdf_path, 'wb') as f:
                                f.write(dl.content)
                            return {"status": "downloaded", "local_path": str(pdf_path), "bytes": len(dl.content)}
                    except Exception:
                        if dl_attempt < 1:
                            time.sleep(5)
            return {"status": "no_pdf", "oa_url": pdf_url}
        except Exception as e:
            if attempt < 2:
                time.sleep(10 * (attempt + 1))
    return None


# ===========================================================
# 渠道4: Semantic Scholar API
# ===========================================================
def try_semantic_scholar(doi, pmid):
    """通过Semantic Scholar API查OA PDF"""
    identifier = doi or (f"PMID:{pmid}" if pmid else None)
    if not identifier:
        return None

    url = f"https://api.semanticscholar.org/graph/v1/paper/{identifier}?fields=openAccessPdf,externalIds"
    for attempt in range(2):
        try:
            resp = session.get(url, timeout=45)
            if resp.status_code != 200:
                continue
            data = resp.json()
            oa = data.get("openAccessPdf") or {}
            pdf_url = oa.get("url")
            if pdf_url:
                dl = session.get(pdf_url, timeout=120)
                if dl.status_code == 200 and len(dl.content) > 50000:
                    pdf_path = PDF_DIR / f"DOI_{sanitize(doi)}_s2.pdf" if doi else PDF_DIR / f"PMID{pmid}_s2.pdf"
                    with open(pdf_path, 'wb') as f:
                        f.write(dl.content)
                    return {"status": "downloaded", "local_path": str(pdf_path), "bytes": len(dl.content)}
            # 也检查externalIds中的PMCID
            ext = data.get("externalIds") or {}
            pmcid = ext.get("PMCID")
            if pmcid:
                return {"status": "found_pmcid", "pmcid": pmcid}
            return None
        except Exception:
            if attempt < 1:
                time.sleep(5)
    return None


# ===========================================================
# 主重试逻辑
# ===========================================================
def retry_failed():
    con = sqlite3.connect(str(DB_PATH))
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    # 获取所有失败的引用
    failed = cur.execute("""
        SELECT lfs.fulltext_id, lfs.reference_id, lfs.pmid, lfs.doi, lfs.pmcid,
               lfs.source, rl.title
        FROM literature_fulltext_sources lfs
        JOIN ref_literatures rl ON lfs.reference_id = rl.reference_id
        WHERE lfs.status = 'failed'
        ORDER BY
            CASE WHEN lfs.pmcid IS NOT NULL AND lfs.pmcid != '' THEN 0 ELSE 1 END,
            lfs.reference_id
    """).fetchall()

    print(f"重试失败文献: {len(failed)} 篇")
    print(f"  其中有 PMCID: {sum(1 for f in failed if f['pmcid'])}")
    print(f"  其中有 DOI: {sum(1 for f in failed if f['doi'])}")
    print(f"  其中有 PMID: {sum(1 for f in failed if f['pmid'])}")
    print()

    stats = {"retried": 0, "success": 0, "still_failed": 0, "no_oa": 0, "by_method": {}}

    for i, ref in enumerate(failed):
        ref_id = ref["reference_id"]
        pmid = ref["pmid"]
        doi = ref["doi"]
        pmcid = ref["pmcid"]
        title = (ref["title"] or "")[:80]

        result = None
        method = ""

        # 优先级: PMC OA > Semantic Scholar > Unpaywall > PMID→PMCID转换

        # 1. 已知 PMCID → 直接下PMC OA
        if pmcid:
            method = "pmc_oa_direct"
            result = download_pmc_oa(pmcid, pmid)

        # 2. 没有 PMCID 但有 PMID → 尝试通过NCBI找到PMCID
        if not result and pmid and not pmcid:
            method = "pmid_to_pmcid"
            found_pmcid = pmid_to_pmcid(pmid)
            if found_pmcid:
                method = "pmc_oa_via_pmid"
                result = download_pmc_oa(found_pmcid, pmid)
                if result and result.get("status") == "downloaded":
                    # 更新pmcid
                    cur.execute("""
                        UPDATE literature_fulltext_sources SET pmcid = ? WHERE reference_id = ?
                    """, (f"PMC{found_pmcid}", ref_id))

        # 3. Semantic Scholar
        if not result:
            method = "semantic_scholar"
            result = try_semantic_scholar(doi, pmid)
            if result and result.get("status") == "found_pmcid":
                new_pmcid = result["pmcid"]
                method = "pmc_oa_via_s2"
                result = download_pmc_oa(new_pmcid, pmid)
                if result and result.get("status") == "downloaded":
                    cur.execute("""
                        UPDATE literature_fulltext_sources SET pmcid = ? WHERE reference_id = ?
                    """, (f"PMC{new_pmcid}", ref_id))

        # 4. Unpaywall (最后尝试, 因为欧洲服务器)
        if not result and doi:
            method = "unpaywall_v2"
            result = try_unpaywall_v2(doi)

        # 更新数据库
        if result and result.get("status") == "downloaded":
            local_path = result.get("local_path", "")
            cur.execute("""
                UPDATE literature_fulltext_sources
                SET status = 'downloaded', source = ?, local_path = ?,
                    content_type = 'pdf/xml', raw_json = ?
                WHERE reference_id = ? AND fulltext_id = ?
            """, (method, local_path, json.dumps(result)[:1000], ref_id, ref["fulltext_id"]))
            stats["success"] += 1
            stats["by_method"][method] = stats["by_method"].get(method, 0) + 1
        elif result and result.get("status") == "not_oa":
            cur.execute("""
                UPDATE literature_fulltext_sources
                SET status = 'no_oa', source = ?, raw_json = ?
                WHERE reference_id = ? AND fulltext_id = ?
            """, (method, json.dumps(result)[:500], ref_id, ref["fulltext_id"]))
            stats["no_oa"] += 1
        else:
            stats["still_failed"] += 1

        stats["retried"] += 1
        if stats["retried"] % 50 == 0:
            con.commit()
            print(f"  [{stats['retried']}/{len(failed)}] "
                  f"成功: {stats['success']}, 确认无OA: {stats['no_oa']}, "
                  f"仍失败: {stats['still_failed']}", end='\r')

    con.commit()
    print(f"\n\n{'=' * 55}")
    print(f"重试完成")
    print(f"{'=' * 55}")
    print(f"重试总数: {stats['retried']}")
    print(f"新下载成功: {stats['success']}")
    print(f"确认无OA(付费墙): {stats['no_oa']}")
    print(f"仍失败: {stats['still_failed']}")
    print(f"\n按方法分布:")
    for m, c in sorted(stats['by_method'].items(), key=lambda x: -x[1]):
        print(f"  {m}: {c}")

    # 下载成功的文献中有多少是病毒文献
    new_dl = cur.execute("""
        SELECT COUNT(DISTINCT lfs.reference_id)
        FROM literature_fulltext_sources lfs
        JOIN evidence_records er ON lfs.reference_id = er.reference_id
        WHERE lfs.status = 'downloaded'
    """).fetchone()[0]
    print(f"\n已下载且有病毒证据的文献: {new_dl}")

    con.close()
    return stats


if __name__ == "__main__":
    retry_failed()
