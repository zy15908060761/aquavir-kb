#!/usr/bin/env python3
"""
Stable downloader: Python logic + curl engine (bypasses Python SSL issues).
Channels: Sci-Hub (primary) + Europe PMC + NCBI PMC + Unpaywall (fallbacks).

Usage:
  python download_stable_final.py           # full run (resumes automatically)
  python download_stable_final.py --test    # test connectivity only
  python download_stable_final.py --dry     # dry run (no actual download)
"""
import json, sqlite3, time, re, os, subprocess, hashlib, sys
from pathlib import Path
from collections import Counter

# === CONFIG ===
DB_PATH = Path(r"F:\水生无脊椎动物数据库\crustacean_virus_core.db")
PROJECT_DIR = Path(r"F:\水生无脊椎动物数据库")
OA_DIR = PROJECT_DIR / "literature_curation_v2" / "oa_fulltext"
PMC_XML_DIR = PROJECT_DIR / "literature_curation_v2" / "pmc_xml"
FULLTEXT_DIR = PROJECT_DIR / "literature_curation_v2" / "fulltext"
LOG_DIR = PROJECT_DIR / "downloads" / "stable_logs"

for d in [OA_DIR, PMC_XML_DIR, FULLTEXT_DIR, LOG_DIR]:
    d.mkdir(parents=True, exist_ok=True)

CHECKPOINT = LOG_DIR / "stable_checkpoint.json"
CURL = "curl"  # must be on PATH
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
TIMEOUT = 45
SLEEP_OK = 2.0
SLEEP_ERR = 10.0

SCI_HUB_MIRROR = "https://sci-hub.ru"


def load_cp():
    if CHECKPOINT.exists():
        return json.loads(CHECKPOINT.read_text(encoding="utf-8"))
    return {"done": {}, "unavailable": [], "errors": {}}


def save_cp(cp):
    tmp = CHECKPOINT.with_suffix(".tmp")
    tmp.write_text(json.dumps(cp, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(CHECKPOINT)


def curl_fetch(url, referer=None, timeout=TIMEOUT):
    """Fetch URL via curl. Returns (http_code, body_bytes) or (0, None)."""
    cmd = [CURL, "-sL", "--max-time", str(timeout), "-w", "%{http_code}", "-o", "-"]
    cmd += ["-H", f"User-Agent: {UA}"]
    if referer:
        cmd += ["-H", f"Referer: {referer}"]
    cmd.append(url)

    try:
        result = subprocess.run(cmd, capture_output=True, timeout=timeout + 10)
        stdout = result.stdout
        # Last 3 characters are the HTTP status code from -w
        if len(stdout) >= 3:
            http_code_str = stdout[-3:].decode("ascii", errors="ignore").strip()
            http_code = int(http_code_str) if http_code_str.isdigit() else 0
            body = stdout[:-3]
            return http_code, body
        return 0, None
    except Exception as e:
        return 0, None


def curl_download(url, output_path, referer=None, timeout=TIMEOUT):
    """Download a file via curl. Returns True on success."""
    cmd = [CURL, "-sL", "--max-time", str(timeout), "-o", str(output_path)]
    cmd += ["-H", f"User-Agent: {UA}"]
    if referer:
        cmd += ["-H", f"Referer: {referer}"]
    cmd.append(url)

    try:
        result = subprocess.run(cmd, capture_output=True, timeout=timeout + 30)
        if result.returncode == 0 and output_path.exists():
            return output_path.stat().st_size > 5000
        return False
    except Exception:
        return False


def test_connectivity():
    """Test all download channels."""
    print("Testing download channels via curl...\n")
    tests = [
        ("Sci-Hub", f"{SCI_HUB_MIRROR}/10.1038/nature12373"),
        ("Europe PMC", "https://www.ebi.ac.uk/europepmc/webservices/rest/search?query=shrimp+virus&format=json&pageSize=1"),
        ("NCBI", "https://www.ncbi.nlm.nih.gov/pmc/utils/idconv/v1.0/?ids=36656416&format=json"),
        ("Unpaywall", "https://api.unpaywall.org/v2/10.1038/nature12373?email=test@test.com"),
        ("SemanticScholar", "https://api.semanticscholar.org/graph/v1/paper/DOI:10.1038/nature12373?fields=title"),
    ]
    working = {}
    for name, url in tests:
        code, body = curl_fetch(url, timeout=20)
        status = "OK" if code in (200, 301, 302) else f"HTTP {code}"
        size = len(body) if body else 0
        print(f"  {name:<16} {status:<8} {size:>8,} bytes")
        if code in (200, 301, 302):
            working[name] = True

    print(f"\n  Working: {list(working.keys())}")
    return working


def get_target_refs():
    cp = load_cp()
    already = set(cp.get("done", {}).keys()) | set(cp.get("unavailable", []))
    con = sqlite3.connect(str(DB_PATH), timeout=60)
    con.row_factory = sqlite3.Row
    cur = con.execute("""
        SELECT DISTINCT lfs.reference_id, lfs.doi, lfs.pmid, lfs.status,
               rl.title, rl.journal, rl.year
        FROM literature_fulltext_sources lfs
        JOIN ref_literatures rl ON lfs.reference_id = rl.reference_id
        WHERE lfs.status IN ('no_oa', 'failed')
          AND lfs.doi IS NOT NULL AND lfs.doi != ''
        ORDER BY rl.year DESC
    """)
    refs = [dict(r) for r in cur.fetchall() if r["reference_id"] not in already]
    con.close()
    return refs


# === SCI-HUB ===
def scihub_get_pdf_url(doi):
    """Get PDF CDN URL from Sci-Hub. Returns URL string or None."""
    sci_url = f"{SCI_HUB_MIRROR}/{doi}"
    code, html = curl_fetch(sci_url)
    if not html:
        return None, f"curl_failed_{code}"

    html_str = html.decode("utf-8", errors="ignore")

    # Check for issues
    if "captcha" in html_str.lower():
        return None, "captcha"
    if "article not found" in html_str.lower():
        return None, "not_on_scihub"

    # Method 1: <meta name="citation_pdf_url"> — order-independent
    m = re.search(r'<meta\b[^>]*?\bcitation_pdf_url\b[^>]*?\bcontent\s*=\s*["\']([^"\']+)["\']', html_str, re.I)
    if m:
        pdf_url = m.group(1)
        if pdf_url.startswith("//"):
            pdf_url = "https:" + pdf_url
        elif pdf_url.startswith("/"):
            pdf_url = SCI_HUB_MIRROR + pdf_url
        return pdf_url, "meta_tag"

    # Method 2: <object data="...pdf...">
    m = re.search(r'<object[^>]*\bdata\s*=\s*["\']([^"\']+\.pdf[^"\']*)["\']', html_str, re.I)
    if m:
        pdf_url = m.group(1)
        if pdf_url.startswith("//"):
            pdf_url = "https:" + pdf_url
        elif pdf_url.startswith("/"):
            pdf_url = SCI_HUB_MIRROR + pdf_url
        return pdf_url, "object_tag"

    # Method 3: <a href="...pdf..." in download div
    m = re.search(r'class\s*=\s*["\']download["\'][^>]*>\s*<a\s[^>]*href\s*=\s*["\']([^"\']+\.pdf[^"\']*)["\']', html_str, re.I)
    if m:
        pdf_url = m.group(1)
        if pdf_url.startswith("//"):
            pdf_url = "https:" + pdf_url
        elif pdf_url.startswith("/"):
            pdf_url = SCI_HUB_MIRROR + pdf_url
        return pdf_url, "download_link"

    # Method 4: Any absolute PDF URL
    m = re.search(r'https?://[^"\'<>\s]+\.pdf[^"\'<>\s]*', html_str, re.I)
    if m:
        return m.group(0), "direct_pdf_link"

    return None, "no_pdf_url"


def scihub_download(doi, ref_id):
    """Download a paper via Sci-Hub. Returns (local_path, source) or (None, error)."""
    pdf_url, method = scihub_get_pdf_url(doi)
    if not pdf_url:
        return None, method

    clean = doi.replace("/", "_").replace(".", "_")[:80]
    h = hashlib.md5(pdf_url.encode()).hexdigest()[:6]
    path = OA_DIR / f"{clean}_{h}_scihub.pdf"

    if curl_download(pdf_url, path, referer=f"{SCI_HUB_MIRROR}/{doi}"):
        return str(path), f"scihub_{method}"
    return None, "pdf_download_failed"


# === EUROPE PMC ===
def epmc_download(doi, pmid):
    """Download via Europe PMC fulltext XML. Returns (path, source) or (None, error)."""
    query = f'DOI:"{doi}"' if doi else f'EXT:{pmid}'
    search_url = (
        "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
        f"?query={query}&format=json&resultType=core"
    )
    code, body = curl_fetch(search_url)
    if not body:
        return None, f"epmc_search_failed_{code}"

    try:
        data = json.loads(body.decode("utf-8"))
        results = data.get("resultList", {}).get("result", [])
        if not results:
            return None, "epmc_not_found"

        pmcid = results[0].get("pmcid")
        if not pmcid:
            return None, "epmc_no_pmcid"

        # Check hasFullText
        if results[0].get("hasFullText") != "Y":
            return None, "epmc_no_fulltext"

        xml_url = f"https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/fullTextXML"
        clean_id = (doi or f"PMID{pmid}").replace("/", "_").replace(".", "_")[:80]
        path = PROJECT_DIR / f"DOI_{clean_id}_EPMC.xml"

        if curl_download(xml_url, path):
            return str(path), "epmc_xml"
        return None, "epmc_xml_download_failed"
    except Exception as e:
        return None, f"epmc_parse_error"


# === NCBI PMC ===
def ncbi_pmc_download(pmid):
    """Download via NCBI PMC OA. Returns (path, source) or (None, error)."""
    # Step 1: PMID → PMCID
    conv_url = f"https://www.ncbi.nlm.nih.gov/pmc/utils/idconv/v1.0/?ids={pmid}&format=json&tool=AquaVirKB&email=crustacean-db@proton.me"
    code, body = curl_fetch(conv_url)
    if not body:
        return None, f"ncbi_conv_failed_{code}"

    try:
        data = json.loads(body.decode("utf-8"))
        pmcid = None
        for rec in data.get("records", []):
            if rec.get("pmcid"):
                pmcid = rec["pmcid"]
                break
        if not pmcid:
            return None, "ncbi_no_pmcid"

        # Step 2: Download XML
        xml_url = f"https://www.ncbi.nlm.nih.gov/research/bionlp/RESTful/pmcoa.cgi/BioC_xml/{pmcid}/unicode"
        path = PMC_XML_DIR / f"{pmcid}_PMC.xml"

        if curl_download(xml_url, path):
            return str(path), "ncbi_pmc_xml"

        # Fallback: PDF
        pdf_url = f"https://www.ncbi.nlm.nih.gov/pmc/articles/{pmcid}/pdf/main.pdf"
        pdf_path = FULLTEXT_DIR / f"{pmcid}_PMC.pdf"
        if curl_download(pdf_url, pdf_path):
            return str(pdf_path), "ncbi_pmc_pdf"

        return None, "ncbi_download_failed"
    except Exception as e:
        return None, f"ncbi_parse_error"


# === DB UPDATE ===
def mark_downloaded(con, ref_id, source, local_path):
    con.execute("""UPDATE literature_fulltext_sources
        SET status='downloaded', source=?, local_path=?, content_type=
            CASE WHEN ? LIKE '%.xml' OR ? LIKE '%_EPMC.xml' THEN 'application/xml'
                 ELSE 'application/pdf' END
        WHERE reference_id=? AND status IN ('no_oa','failed')""",
        (source, local_path, local_path, local_path, ref_id))


# === MAIN ===
def main():
    test_only = "--test" in sys.argv
    dry_run = "--dry" in sys.argv

    print("=" * 70)
    print("STABLE DOWNLOADER — curl engine + Python logic")
    print("=" * 70)

    # Test connectivity
    working = test_connectivity()
    if test_only:
        return

    if not working:
        print("\nNo channels available. Exiting.")
        return

    has_scihub = "Sci-Hub" in working
    has_epmc = "Europe PMC" in working
    has_ncbi = "NCBI" in working

    if has_scihub:
        print("\nSci-Hub: ENABLED (primary)")
    if has_epmc:
        print("Europe PMC: ENABLED (fallback)")
    if has_ncbi:
        print("NCBI PMC: ENABLED (fallback)")

    # Get targets
    con = sqlite3.connect(str(DB_PATH), timeout=60)
    con.row_factory = sqlite3.Row

    refs = get_target_refs()
    no_oa_n = sum(1 for r in refs if r["status"] == "no_oa")
    failed_n = sum(1 for r in refs if r["status"] == "failed")
    print(f"\nTargets: {len(refs):,} (no_oa={no_oa_n:,}  failed={failed_n:,})")

    cp = load_cp()
    prev_done = len(cp.get("done", {}))
    prev_unavail = len(cp.get("unavailable", []))
    if prev_done or prev_unavail:
        print(f"Resume: {prev_done} done, {prev_unavail} unavailable, {len(cp.get('errors',{}))} errors")

    stats = Counter()
    conseq_errors = 0
    t0 = time.time()
    print()

    for i, ref in enumerate(refs):
        ref_id = ref["reference_id"]
        doi = (ref["doi"] or "").strip()
        pmid = (ref["pmid"] or "").strip()

        if not doi:
            cp.setdefault("unavailable", []).append(ref_id)
            save_cp(cp)
            stats["no_doi"] += 1
            continue

        # Progress line
        elapsed = time.time() - t0
        rate = (stats["total"] + 1) / max(1, elapsed / 60)
        print(f"\r  [{stats['total']+1}/{len(refs)}] {doi[:50]:<50} "
              f"OK={stats['success']} no={stats['unavailable']} err={stats['error']} "
              f"| {rate:.0f}/min | {elapsed/60:.0f}m",
              end="", flush=True)

        if dry_run:
            stats["total"] += 1
            time.sleep(0.1)
            continue

        local_path = None
        source = None

        # Channel 1: Sci-Hub (primary — highest success rate)
        if has_scihub and not local_path:
            local_path, info = scihub_download(doi, ref_id)
            if local_path:
                source = info  # e.g., "scihub_meta_tag"
                stats[f"scihub_{info}"] += 1

        # Channel 2: Europe PMC XML (good for OA articles)
        if has_epmc and not local_path:
            local_path, info = epmc_download(doi, pmid)
            if local_path:
                source = "epmc_xml"
                stats["epmc"] += 1

        # Channel 3: NCBI PMC OA
        if has_ncbi and not local_path and pmid:
            local_path, info = ncbi_pmc_download(pmid)
            if local_path:
                source = info  # "ncbi_pmc_xml" or "ncbi_pmc_pdf"
                stats["ncbi"] += 1

        # Update DB + checkpoint
        if local_path:
            try:
                mark_downloaded(con, ref_id, source, local_path)
                con.commit()
            except Exception:
                time.sleep(2)
                try:
                    mark_downloaded(con, ref_id, source, local_path)
                    con.commit()
                except Exception:
                    pass

            cp.setdefault("done", {})[str(ref_id)] = {
                "doi": doi, "title": (ref["title"] or "")[:60], "source": source
            }
            save_cp(cp)
            stats["success"] += 1
            conseq_errors = 0
            time.sleep(SLEEP_OK)

        elif info in ("not_on_scihub", "epmc_not_found", "epmc_no_fulltext", "ncbi_no_pmcid"):
            # Definitely unavailable for this channel
            cp.setdefault("unavailable", []).append(ref_id)
            save_cp(cp)
            stats["unavailable"] += 1
            conseq_errors = 0
            time.sleep(SLEEP_OK)

        else:
            # Transient error — keep for retry
            stats["error"] += 1
            conseq_errors += 1
            cp.setdefault("errors", {})[str(ref_id)] = info
            if conseq_errors % 20 == 0:
                save_cp(cp)
            time.sleep(SLEEP_ERR if conseq_errors > 3 else SLEEP_OK * 2)

        stats["total"] += 1

        # Health check
        if conseq_errors > 20:
            print(f"\n  *** {conseq_errors} consecutive errors. Pausing 60s...")
            time.sleep(60)
            conseq_errors = 0

    # Done
    con.commit()
    save_cp(cp)
    con.close()

    total_time = time.time() - t0
    print(f"\n\n{'=' * 70}")
    print("COMPLETE")
    print(f"{'=' * 70}")
    print(f"  Duration: {total_time/60:.0f} min ({total_time/3600:.1f}h)")
    print(f"  Downloaded: {stats['success']:,}")
    print(f"  Unavailable: {stats['unavailable']:,}")
    print(f"  Errors: {stats['error']:,}")
    print(f"  Total + previous: {prev_done + stats['success']:,}")

    # Final DB state
    con = sqlite3.connect(str(DB_PATH), timeout=60)
    cur = con.cursor()
    print(f"\n  === Final Fulltext Status ===")
    for row in cur.execute("SELECT status, COUNT(DISTINCT reference_id) FROM literature_fulltext_sources GROUP BY status ORDER BY COUNT(*) DESC"):
        print(f"    {row[0]}: {row[1]:,}")
    con.close()


if __name__ == "__main__":
    main()
