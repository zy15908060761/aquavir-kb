"""
auto_fetch_fulltext.py — 自动获取文献全文

多通道并行尝试获取 PDF 全文，按优先级依次尝试:
  1. PubMed Central (PMC) — 如果有 PMCID，直接下载 PDF
  2. Unpaywall API — 查找合法的 OA 版本 (预印本/机构仓储/作者上传)
  3. Europe PMC API — 欧洲生物医学文献 OA 查询
  4. Semantic Scholar API — 补充 OA 状态查询
  5. 标记为"需人工下载" — 输出 missing_fulltext.csv

不需要任何账号。所有渠道都是免费且合法的。
Unpaywall 有速率限制 (1000/day)，脚本已内置 1s 延迟。

输入:  literature_curation_v2/pmid_results_final.csv
输出:  literature_curation_v2/fulltext/  (PDF 文件)
       literature_curation_v2/fetch_status.csv  (获取状态)
       literature_curation_v2/missing_fulltext.csv  (需人工下载清单)
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
import hashlib
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

import requests
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ── Paths ────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent
CURATION_DIR = BASE_DIR / "literature_curation_v2"
INPUT_CSV = CURATION_DIR / "pmid_results_final.csv"
OUTPUT_DIR = CURATION_DIR / "fulltext"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
STATUS_CSV = CURATION_DIR / "fetch_status.csv"
MISSING_CSV = CURATION_DIR / "missing_fulltext.csv"

# ── Config ───────────────────────────────────────────────────────
USER_AGENT = "CrustaVirusDB/1.0 (mailto:crustacean-db@example.com)"
UNPAYWALL_EMAIL = os.environ.get("UNPAYWALL_EMAIL", "crustacean-virus-db-curation@proton.me")
REQUEST_TIMEOUT = 60
RATE_LIMIT = 1.2  # 请求间隔 (秒)
CHUNK_SIZE = 65536

# ── Source priority labels ───────────────────────────────────────
SOURCE_PMC = "pmc"
SOURCE_UNPAYWALL = "unpaywall"
SOURCE_EUROPE_PMC = "europe_pmc"
SOURCE_SEMANTIC_SCHOLAR = "semantic_scholar"
SOURCE_MANUAL = "manual_required"


def fetch_pmc_pdf(pmcid: str, pmid: str, timeout: int = REQUEST_TIMEOUT) -> tuple[str | None, str]:
    """
    从 PubMed Central 下载 PDF。
    PMC 的 PDF URL 格式: https://www.ncbi.nlm.nih.gov/pmc/articles/PMC{pmcid}/pdf/
    返回: (pdf_bytes_or_None, source_label)
    """
    if not pmcid or not pmcid.strip():
        return None, ""

    pmcid = pmcid.strip()
    # PMC PDF endpoint
    pdf_url = f"https://www.ncbi.nlm.nih.gov/pmc/articles/PMC{pmcid}/pdf/main.pdf"

    try:
        resp = requests.get(pdf_url, headers={"User-Agent": USER_AGENT}, timeout=timeout)
        if resp.status_code == 200 and len(resp.content) > 5000:
            # Verify it's a PDF
            if resp.content[:4] == b"%PDF":
                return resp.content, SOURCE_PMC
        # Try alternative PMC URL format
        alt_url = f"https://www.ncbi.nlm.nih.gov/pmc/articles/PMC{pmcid}/pdf/"
        resp2 = requests.get(alt_url, headers={"User-Agent": USER_AGENT}, timeout=timeout, allow_redirects=True)
        if resp2.status_code == 200 and len(resp2.content) > 5000 and resp2.content[:4] == b"%PDF":
            return resp2.content, SOURCE_PMC
    except Exception:
        pass

    return None, ""


def lookup_pmcid_from_pmid(pmid: str, timeout: int = REQUEST_TIMEOUT) -> str | None:
    """通过 PubMed E-utilities 查询 PMCID (适用于之前没有 PMCID 的记录)"""
    url = "https://www.ncbi.nlm.nih.gov/pmc/utils/idconv/v1.0/"
    params = {"ids": pmid, "format": "json", "tool": "CrustaVirusDB", "email": UNPAYWALL_EMAIL}

    try:
        resp = requests.get(url, params=params, headers={"User-Agent": USER_AGENT}, timeout=timeout)
        data = resp.json()
        records = data.get("records", [])
        for r in records:
            pmcid = r.get("pmcid")
            if pmcid:
                return pmcid
    except Exception:
        pass
    return None


def fetch_unpaywall(doi: str, email: str = "", timeout: int = REQUEST_TIMEOUT) -> tuple[str | None, str, dict]:
    """
    通过 Unpaywall API 查找 OA 版本。需要提供有效邮箱。
    返回: (pdf_url_or_None, source_label, metadata_dict)
    """
    if not doi or not doi.strip():
        return None, "", {}
    if not email:
        return None, "", {"error": "no email provided"}

    doi = doi.strip()
    url = f"https://api.unpaywall.org/v2/{quote(doi, safe='')}?email={quote(email, safe='')}"

    try:
        resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=timeout)
        if resp.status_code != 200:
            return None, "", {}

        data = resp.json()
        best_loc = data.get("best_oa_location") or {}
        oa_status = data.get("oa_status", "closed")
        pdf_url = best_loc.get("url_for_pdf") or best_loc.get("url") or ""

        meta = {
            "oa_status": oa_status,
            "journal": data.get("journal_name", ""),
            "published_date": data.get("published_date", ""),
            "oa_repository": best_loc.get("host_type", ""),
        }

        if pdf_url:
            return pdf_url, SOURCE_UNPAYWALL, meta
        return None, "", meta

    except Exception:
        return None, "", {}


def fetch_europe_pmc(pmid: str, doi: str = "", timeout: int = REQUEST_TIMEOUT) -> tuple[str | None, str]:
    """
    通过 Europe PMC API 查找全文 PDF。
    Europe PMC 覆盖比 NCBI PMC 更广，有时能找到 PMC 没有的 OA PDF。
    """
    # Try by PMID first
    for query_id in [f"EXT:{pmid}", f"DOI:{doi}"] if doi else [f"EXT:{pmid}"]:
        try:
            url = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
            params = {
                "query": query_id,
                "format": "json",
                "resultType": "core",
            }
            resp = requests.get(url, params=params, headers={"User-Agent": USER_AGENT}, timeout=timeout)
            data = resp.json()
            results = data.get("resultList", {}).get("result", [])
            if results:
                r = results[0]
                # Check if full text is available
                has_pdf = r.get("hasPDF", "N")
                pmcid = r.get("pmcid", "")
                if has_pdf == "Y" and pmcid:
                    pdf_bytes, src = fetch_pmc_pdf(pmcid, pmid, timeout)
                    if pdf_bytes:
                        return pdf_bytes, SOURCE_EUROPE_PMC
                # Europe PMC also has direct PDF links sometimes
                ft_links = r.get("fullTextUrlList", {}).get("fullTextUrl", [])
                if isinstance(ft_links, list):
                    for link in ft_links:
                        pdf_url = link.get("url", "")
                        if pdf_url.endswith(".pdf"):
                            try:
                                pdf_resp = requests.get(
                                    pdf_url, headers={"User-Agent": USER_AGENT},
                                    timeout=timeout
                                )
                                if pdf_resp.status_code == 200 and len(pdf_resp.content) > 5000:
                                    return pdf_resp.content, SOURCE_EUROPE_PMC
                            except Exception:
                                continue
        except Exception:
            continue
    return None, ""


def fetch_semantic_scholar(doi: str, timeout: int = REQUEST_TIMEOUT) -> dict[str, Any]:
    """
    通过 Semantic Scholar API 查询论文 OA 状态和 PDF 链接。
    不直接下载 PDF，但可以提供额外的 OA URL 信息。
    """
    if not doi or not doi.strip():
        return {}

    doi = doi.strip()
    url = f"https://api.semanticscholar.org/graph/v1/paper/DOI:{quote(doi, safe='')}"
    params = {"fields": "title,openAccessPdf,isOpenAccess,externalIds"}

    try:
        resp = requests.get(url, params=params, headers={"User-Agent": USER_AGENT}, timeout=timeout)
        if resp.status_code != 200:
            return {}
        data = resp.json()
        result = {"is_open_access": data.get("isOpenAccess", False)}
        oa_pdf = data.get("openAccessPdf")
        if oa_pdf and oa_pdf.get("url"):
            result["oa_pdf_url"] = oa_pdf["url"]
        return result
    except Exception:
        return {}


def download_pdf_from_url(pdf_url: str, timeout: int = REQUEST_TIMEOUT) -> bytes | None:
    """下载 PDF 文件内容"""
    try:
        resp = requests.get(
            pdf_url,
            headers={"User-Agent": USER_AGENT, "Accept": "application/pdf"},
            timeout=timeout,
            stream=True,
        )
        resp.raise_for_status()

        content = b""
        for chunk in resp.iter_content(chunk_size=CHUNK_SIZE):
            content += chunk
            if len(content) > 100 * 1024 * 1024:  # 100 MB max
                break

        if len(content) > 5000 and content[:4] == b"%PDF":
            return content
    except Exception:
        pass
    return None


def make_safe_filename(pmid: str, title: str, source: str, doi: str = "") -> str:
    """生成安全的文件名"""
    # Use PMID + source as the base
    safe = f"PMID{pmid}_{source}"
    # Remove any path-unsafe chars
    safe = "".join(c for c in safe if c.isalnum() or c in "_-.")
    return safe[:200] + ".pdf"


def dedup_rows(rows: list[dict]) -> list[dict]:
    """按 PMID 去重，保留信息最完整的那一条"""
    seen: dict[str, dict] = {}
    for r in rows:
        pmid = r.get("pmid", "").strip()
        if not pmid:
            continue
        if pmid not in seen:
            seen[pmid] = r
        else:
            # 保留 DOI 非空的那个
            if r.get("doi", "").strip() and not seen[pmid].get("doi", "").strip():
                seen[pmid] = r
    return list(seen.values())


def run_fetch(
    csv_path: Path,
    unpaywall_email: str = "",
    limit: int | None = None,
    resume: bool = True,
    missing_only: bool = False,
) -> dict[str, int]:
    """
    主流程: 遍历 PMID 列表，多渠道尝试获取全文。
    """
    # 读取输入
    with open(csv_path, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        all_rows = list(reader)

    rows = dedup_rows(all_rows)
    print(f"Total PMIDs: {len(all_rows)} (unique: {len(rows)})")

    # 读取已有的下载状态 (支持断点续传)
    completed_pmids: set[str] = set()
    if resume and STATUS_CSV.exists():
        with open(STATUS_CSV, encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                if r.get("status") == "success":
                    completed_pmids.add(r.get("pmid", "").strip())

    if completed_pmids:
        print(f"Already fetched: {len(completed_pmids)} (resume mode)")

    # 统计
    stats: dict[str, int] = {
        "total": 0, "success": 0, "failed": 0,
        SOURCE_PMC: 0, SOURCE_UNPAYWALL: 0, SOURCE_EUROPE_PMC: 0,
        SOURCE_SEMANTIC_SCHOLAR: 0, SOURCE_MANUAL: 0,
    }

    status_rows: list[dict] = []
    missing_rows: list[dict] = []

    for i, row in enumerate(rows):
        pmid = row.get("pmid", "").strip()
        if not pmid:
            continue

        if limit and stats["total"] >= limit:
            break

        stats["total"] += 1

        # 跳过已完成的
        if pmid in completed_pmids:
            stats["success"] += 1
            continue

        doi = row.get("doi", "").strip()
        pmcid = row.get("pmc_id", "").strip()
        title = row.get("title", "").strip()[:100]
        virus = row.get("matched_viruses", "").strip()

        title_safe = title.encode('ascii', errors='replace').decode('ascii')[:80]
        print(f"\n[{stats['total']}/{len(rows)}] PMID:{pmid} {title_safe}...")

        pdf_content: bytes | None = None
        pdf_source: str = ""
        fetch_meta: dict[str, str] = {}

        # missing_only 模式：跳过所有下载，直接标记为 manual
        if missing_only:
            stats["failed"] += 1
            stats[SOURCE_MANUAL] += 1
            missing_rows.append({
                "pmid": pmid, "doi": doi, "title": title,
                "matched_viruses": virus, "matched_fields": row.get("matched_fields", ""),
                "pubyear": row.get("pubyear", ""), "source": row.get("source", ""),
                "authors": row.get("authors", ""),
            })
            continue

        # ── Channel 1: PMC (已有 PMCID) ──
        if pmcid and not pdf_content:
            pdf_content, _ = fetch_pmc_pdf(pmcid, pmid)
            if pdf_content:
                pdf_source = SOURCE_PMC
                print(f"  [OK] PMC (已有 PMCID:{pmcid})")

        # ── Channel 2: PMC (通过 PMID 查找 PMCID) ──
        if not pdf_content:
            new_pmcid = lookup_pmcid_from_pmid(pmid)
            if new_pmcid:
                pdf_content, _ = fetch_pmc_pdf(new_pmcid, pmid)
                if pdf_content:
                    pdf_source = SOURCE_PMC
                    fetch_meta["pmcid_found"] = new_pmcid
                    print(f"  [OK] PMC (查找到 PMCID:{new_pmcid})")

        # ── Channel 3: Unpaywall ──
        if not pdf_content and doi and unpaywall_email:
            pdf_url, label, meta = fetch_unpaywall(doi, email=unpaywall_email)
            oa_status = meta.get("oa_status", "closed")
            fetch_meta.update({f"uw_{k}": str(v) for k, v in meta.items()})
            if pdf_url:
                print(f"  Unpaywall: {oa_status} [{meta.get('oa_repository', '?')}]")
                pdf_content = download_pdf_from_url(pdf_url)
                if pdf_content:
                    pdf_source = SOURCE_UNPAYWALL
                    print(f"  [OK] Unpaywall PDF downloaded")
                else:
                    print(f"  Unpaywall URL failed, trying alternate channels...")
            elif oa_status != "closed":
                print(f"  Unpaywall: {oa_status} (no direct PDF URL, try publisher page)")
            time.sleep(RATE_LIMIT)

        # ── Channel 4: Europe PMC ──
        if not pdf_content:
            pdf_content, _ = fetch_europe_pmc(pmid, doi)
            if pdf_content:
                pdf_source = SOURCE_EUROPE_PMC
                print(f"  [OK] Europe PMC")

        # ── Channel 5: Semantic Scholar (仅查 OA URL) ──
        if not pdf_content and doi:
            s2 = fetch_semantic_scholar(doi)
            if s2:
                fetch_meta["s2_oa"] = str(s2.get("is_open_access", ""))
                oa_pdf_url = s2.get("oa_pdf_url", "")
                if oa_pdf_url and not pdf_content:
                    print(f"  Semantic Scholar: OA PDF URL found, downloading...")
                    pdf_content = download_pdf_from_url(oa_pdf_url)
                    if pdf_content:
                        pdf_source = SOURCE_SEMANTIC_SCHOLAR
                        print(f"  [OK] Semantic Scholar")
            time.sleep(RATE_LIMIT / 2)

        # ── 保存 ──
        status_row = {
            "pmid": pmid,
            "doi": doi,
            "title": title,
            "matched_viruses": virus,
            "source": pdf_source or SOURCE_MANUAL,
            "status": "success" if pdf_content else "failed",
            "file_path": "",
            "error": "",
            **fetch_meta,
        }

        if pdf_content:
            filename = make_safe_filename(pmid, title, pdf_source)
            filepath = OUTPUT_DIR / filename
            filepath.write_bytes(pdf_content)
            file_size_kb = len(pdf_content) // 1024
            status_row["file_path"] = str(filepath)
            print(f"  Saved: {filename} ({file_size_kb} KB)")
            stats["success"] += 1
            stats[pdf_source] = stats.get(pdf_source, 0) + 1
        else:
            status_row["error"] = "All channels exhausted"
            print(f"  [FAIL] 需人工下载")
            stats["failed"] += 1
            stats[SOURCE_MANUAL] += 1
            missing_rows.append(status_row)

        status_rows.append(status_row)

        # 每 20 条刷新一次状态文件
        if stats["total"] % 20 == 0:
            _write_status(status_rows, missing_rows)
            print(f"\n  [progress] {stats['success']}/{stats['total']} fetched, "
                  f"{stats['failed']} remaining")

        # 速率限制
        time.sleep(RATE_LIMIT / 3)

    # 最终写入
    _write_status(status_rows, missing_rows)

    # 如果还有需要人工下载的，输出详细清单
    if missing_rows:
        _write_missing_csv(missing_rows)
        _print_missing_summary(missing_rows)

    return stats


def _print_missing_summary(missing_rows: list[dict]) -> None:
    """打印待下载清单摘要：按期刊和病毒分组"""
    # 按期刊分组
    from collections import Counter
    journals = Counter(r.get("source", "Unknown") for r in missing_rows)
    viruses = Counter()
    for r in missing_rows:
        for v in (r.get("matched_viruses", "") or "").split("|"):
            if v.strip():
                viruses[v.strip()] += 1

    print("\n" + "=" * 60)
    print("MISSING FULLTEXT — 需人工下载")
    print("=" * 60)
    print(f"  总计: {len(missing_rows)} 篇")
    print(f"\n  按期刊分布 (Top 15):")
    for j, c in journals.most_common(15):
        print(f"    {c:4d}  {j[:55]}")
    print(f"\n  按病毒分布:")
    for v, c in viruses.most_common(15):
        print(f"    {c:4d}  {v}")
    print(f"\n  建议操作:")
    print(f"    1. 有机构订阅：按期刊名批量下载")
    print(f"    2. 无订阅：通过馆际互借或机构开放获取平台逐篇获取")
    print(f"    3. 优先获取 virulent+mortality 标记的文献")
    print(f"  清单文件: {MISSING_CSV}")
    print("=" * 60)


def _write_status(status_rows: list[dict], missing_rows: list[dict]) -> None:
    """刷新状态 CSV"""
    fields = ["pmid", "doi", "title", "matched_viruses", "source", "status", "file_path", "error"]
    # Collect extra meta fields
    extra = set()
    for r in status_rows:
        for k in r:
            if k not in fields:
                extra.add(k)
    all_fields = fields + sorted(extra)

    with open(STATUS_CSV, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=all_fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(status_rows)


def _write_missing_csv(missing_rows: list[dict]) -> None:
    """输出需人工下载的清单"""
    with open(MISSING_CSV, "w", newline="", encoding="utf-8-sig") as f:
        fields = ["pmid", "doi", "title", "matched_viruses", "matched_fields", "pubyear", "source", "authors"]
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(missing_rows)
    print(f"\n  Missing PDF list: {MISSING_CSV} ({len(missing_rows)} entries)")


def print_stats(stats: dict[str, int]) -> None:
    print("\n" + "=" * 60)
    print("FETCH SUMMARY")
    print("=" * 60)
    total = stats["total"]
    success = stats["success"]
    failed = stats["failed"]
    pct = success / total * 100 if total > 0 else 0
    print(f"  Total:   {total}")
    print(f"  Success: {success} ({pct:.1f}%)")
    print(f"  Failed:  {failed} ({100-pct:.1f}%)")
    print(f"\n  By source:")
    for src, label in [
        (SOURCE_PMC, "PubMed Central"),
        (SOURCE_UNPAYWALL, "Unpaywall"),
        (SOURCE_EUROPE_PMC, "Europe PMC"),
        (SOURCE_SEMANTIC_SCHOLAR, "Semantic Scholar"),
        (SOURCE_MANUAL, "需要人工下载"),
    ]:
        cnt = stats.get(src, 0)
        if cnt > 0:
            print(f"    {label:25s} {cnt:4d}")
    print(f"\n  PDF directory: {OUTPUT_DIR}")
    print(f"  Status file:   {STATUS_CSV}")
    if stats.get(SOURCE_MANUAL, 0) > 0:
        print(f"  Missing list:  {MISSING_CSV}")
    print("=" * 60)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="自动获取文献全文 (PMC + Unpaywall + Europe PMC + Semantic Scholar)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python auto_fetch_fulltext.py --limit 10       # 测试: 只处理前 10 篇
  python auto_fetch_fulltext.py                  # 全部 406 篇
  python auto_fetch_fulltext.py --no-resume      # 强制重新下载
        """,
    )
    parser.add_argument("--limit", type=int, default=None, help="最多处理 N 篇")
    parser.add_argument("--no-resume", action="store_true", help="不跳过已下载的")
    parser.add_argument("--email", type=str, default=None, help="Unpaywall API 邮箱 (不提供则跳过 Unpaywall)")
    parser.add_argument("--input", type=str, default=None, help="输入 CSV 路径 (默认 pmid_results_final.csv)")
    parser.add_argument("--missing-only", action="store_true", help="仅生成待下载清单，不尝试下载")
    args = parser.parse_args()

    input_path = Path(args.input) if args.input else INPUT_CSV
    if not input_path.exists():
        print(f"ERROR: Input file not found: {input_path}")
        sys.exit(1)

    print("=" * 60)
    print("AUTO FETCH FULLTEXT")
    print("=" * 60)
    print(f"  Input:      {input_path}")
    print(f"  Output:     {OUTPUT_DIR}")
    print(f"  Channels:   PMC → Europe PMC → Semantic Scholar", end="")
    if args.email:
        print(f" → Unpaywall ({args.email})")
    else:
        print(f"\n              (Unpaywall disabled — 提供 --email 启用)")
    if args.missing_only:
        print(f"  Mode:       missing-only (仅生成清单)")
    print(f"  Resume:     {'no' if args.no_resume else 'yes'}")
    if args.limit:
        print(f"  Limit:      {args.limit}")

    stats = run_fetch(
        csv_path=input_path,
        unpaywall_email=args.email or "",
        limit=args.limit,
        resume=not args.no_resume,
        missing_only=args.missing_only,
    )

    print_stats(stats)


if __name__ == "__main__":
    main()
