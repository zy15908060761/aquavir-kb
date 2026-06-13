#!/usr/bin/env python3
"""
Comprehensive fulltext download pipeline v2.
Resumable, multi-channel, prioritises XML over PDF.
Target: all 7,215 refs with DOIs.

Channels (in priority order):
  1. Europe PMC XML (best — structured fulltext, easy to extract)
  2. Europe PMC PDF
  3. PMC OA tar.gz / direct PDF
  4. Unpaywall OA PDF
  5. Semantic Scholar OA PDF
"""

import csv
import json
import sqlite3
import time
import urllib.request
import urllib.parse
from pathlib import Path
from datetime import datetime
from collections import Counter

DB_PATH = Path(r"F:\甲壳动物数据库\crustacean_virus_core.db")
LIT_DIR = Path(r"F:\甲壳动物数据库\literature_curation_v2")
PMC_XML_DIR = LIT_DIR / "pmc_xml"
FULLTEXT_DIR = LIT_DIR / "fulltext"
OA_DIR = LIT_DIR / "oa_fulltext"
EPMC_XML_DIR = Path(r"F:\甲壳动物数据库")
DOWNLOAD_LOG_DIR = Path(r"F:\甲壳动物数据库\downloads\fulltext_download_log")
CHECKPOINT_DIR = Path(r"F:\甲壳动物数据库\downloads\literature_download_report")

for d in [PMC_XML_DIR, FULLTEXT_DIR, OA_DIR, DOWNLOAD_LOG_DIR, CHECKPOINT_DIR]:
    d.mkdir(parents=True, exist_ok=True)

CHECKPOINT_PATH = CHECKPOINT_DIR / "comprehensive_download_checkpoint.json"
USER_AGENT = "CrustaVirusDB/2.0 literature curation (mailto:crustacean-db@proton.me)"
BATCH_SIZE_EPMC = 100
SLEEP_EPMC = 0.3
SLEEP_DOWNLOAD = 0.5
TIMEOUT = 60


def load_checkpoint():
    if CHECKPOINT_PATH.exists():
        return json.loads(CHECKPOINT_PATH.read_text(encoding="utf-8"))
    return {"completed_refs": [], "failed_refs": [], "epmc_checked_refs": {}}


def save_checkpoint(cp):
    CHECKPOINT_PATH.write_text(json.dumps(cp, ensure_ascii=False, indent=2), encoding="utf-8")


def get_refs_needing_download():
    """Get all refs with DOIs that don't have a successful download."""
    con = sqlite3.connect(DB_PATH, timeout=60)
    con.row_factory = sqlite3.Row
    cur = con.execute("""
        SELECT r.reference_id, r.doi, r.pmid, r.title, r.authors, r.journal, r.year
        FROM ref_literatures r
        WHERE r.doi IS NOT NULL AND r.doi != ''
          AND r.reference_id NOT IN (
              SELECT DISTINCT reference_id FROM literature_fulltext_sources WHERE status = 'downloaded'
          )
        ORDER BY r.year DESC, r.reference_id
    """)
    refs = [dict(row) for row in cur.fetchall()]
    con.close()
    return refs


def check_europe_pmc_batch(dois):
    """Batch query Europe PMC for OA status using the articles API."""
    results = {}
    # Europe PMC accepts POST with comma-separated DOIs
    url = "https://www.ebi.ac.uk/europepmc/webservices/rest/article/batch"
    payload = urllib.parse.urlencode({"query": " OR ".join(f'DOI:"{d}"' for d in dois), "format": "json", "pageSize": str(len(dois))})
    payload = payload.encode("utf-8")
    try:
        req = urllib.request.Request(
            f"https://www.ebi.ac.uk/europepmc/webservices/rest/search?query={' OR '.join(f'DOI:%22{d}%22' for d in dois)}&format=json&pageSize={len(dois)}",
            headers={"User-Agent": USER_AGENT}
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read())
        for item in data.get("resultList", {}).get("result", []):
            doi = item.get("doi", "").lower()
            if doi:
                results[doi] = {
                    "pmid": item.get("pmid", ""),
                    "pmcid": item.get("pmcid", ""),
                    "title": item.get("title", ""),
                    "isOpenAccess": item.get("isOpenAccess", "N"),
                    "source": item.get("source", ""),
                    "hasPDF": item.get("hasPDF", "N"),
                    "epmc_url": item.get("fullTextUrlList", {}).get("fullTextUrl", [{}])[0].get("url", "") if item.get("fullTextUrlList") else "",
                }
    except Exception as e:
        print(f"  Europe PMC batch error: {e}")
    return results


def download_europe_pmc_xml(pmcid, doi):
    """Download Europe PMC fulltext XML."""
    clean_doi = doi.replace("/", "_").replace(".", "_")[:80]
    out_path = EPMC_XML_DIR / f"DOI_{clean_doi}_EPMC.xml"
    if out_path.exists():
        return True, str(out_path), "epmc_xml"

    url = f"https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/fullTextXML"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            data = resp.read()
        if len(data) < 200:
            return False, "", f"xml_too_small:{len(data)}"
        out_path.write_bytes(data)
        return True, str(out_path), "epmc_xml"
    except Exception as e:
        return False, "", str(e)[:200]


def download_europe_pmc_pdf(pmcid, doi, ref_id):
    """Download Europe PMC PDF."""
    safe_title = f"PMC{pmcid}_{ref_id}"
    out_path = FULLTEXT_DIR / f"{safe_title}.pdf"
    if out_path.exists():
        return True, str(out_path), "epmc_pdf"

    url = f"https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/fullTextPDF"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            data = resp.read()
        if len(data) < 2048:
            return False, "", f"pdf_too_small:{len(data)}"
        out_path.write_bytes(data)
        return True, str(out_path), "epmc_pdf"
    except Exception as e:
        return False, "", str(e)[:200]


def check_and_download_pmc_oa(pmcid, doi, ref_id):
    """Check PMC OA and download tar.gz if available (contains NXML)."""
    pmc_num = pmcid.replace("PMC", "")
    out_path = OA_DIR / f"PMC{pmc_num}_{ref_id}.tar.gz"
    if out_path.exists():
        return True, str(out_path), "pmc_oa_tgz"

    url = f"https://www.ncbi.nlm.nih.gov/pmc/utils/oa/oa.fcgi?id=PMC{pmc_num}&format=tgz"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=30) as resp:
            text = resp.read().decode("utf-8", errors="ignore")
        if "idIsNotOpenAccess" in text or "<error" in text:
            return False, "", "pmc_not_oa"
        # Find download URL
        href_idx = text.find('href="')
        if href_idx == -1:
            return False, "", "pmc_no_href"
        href_idx += 6
        href_end = text.find('"', href_idx)
        download_url = text[href_idx:href_end]

        # Download the actual file
        req2 = urllib.request.Request(download_url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req2, timeout=120) as resp2:
            tgz_data = resp2.read()
        if len(tgz_data) < 1024:
            return False, "", f"tgz_too_small:{len(tgz_data)}"
        out_path.write_bytes(tgz_data)
        return True, str(out_path), "pmc_oa_tgz"
    except Exception as e:
        return False, "", str(e)[:200]


def check_unpaywall(doi):
    """Query Unpaywall for OA PDF URLs."""
    email = "crustacean.db.research@gmail.com"
    url = f"https://api.unpaywall.org/v2/{urllib.parse.quote(doi)}?email={email}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read())
    except Exception:
        return None

    best = data.get("best_oa_location")
    if best and best.get("url_for_pdf"):
        return {"pdf_url": best["url_for_pdf"], "license": best.get("license", ""), "source": "unpaywall"}
    for loc in data.get("oa_locations", []):
        if loc.get("url_for_pdf"):
            return {"pdf_url": loc["url_for_pdf"], "license": loc.get("license", ""), "source": "unpaywall_alt"}
    return None


def download_pdf(url, out_path):
    """Download a PDF file."""
    if out_path.exists():
        return True, str(out_path)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = resp.read()
        if len(data) < 2048:
            return False, f"pdf_too_small:{len(data)}"
        out_path.write_bytes(data)
        return True, str(out_path)
    except Exception as e:
        return False, str(e)[:200]


def record_in_db(ref_id, doi, pmid, pmcid, source, status, oa_status, local_path, content_type, license_info, error_msg):
    """Record download result in literature_fulltext_sources."""
    con = sqlite3.connect(DB_PATH, timeout=60)
    try:
        con.execute("""
            INSERT INTO literature_fulltext_sources
            (reference_id, pmid, doi, pmcid, source, status, oa_status, local_path, content_type, license, error, checked_at, dedupe_key)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            ref_id, pmid, doi, pmcid, source, status, oa_status,
            local_path, content_type, license_info, error_msg,
            datetime.now().isoformat(), f"{ref_id}_{source}"
        ))
        con.commit()
    except sqlite3.IntegrityError:
        pass  # dedupe_key collision — already recorded
    finally:
        con.close()


def main():
    print("=" * 70)
    print("Comprehensive Fulltext Download Pipeline v2")
    print("=" * 70)

    cp = load_checkpoint()
    refs = get_refs_needing_download()
    print(f"\nRefs needing download: {len(refs)} (total DOI refs: ~7,215)")

    # Filter out already completed
    remaining = [r for r in refs if str(r["reference_id"]) not in cp["completed_refs"]]
    print(f"After checkpoint filter: {len(remaining)} remaining")

    # Phase 1: Europe PMC batch OA check
    print(f"\n--- Phase 1: Europe PMC OA check ---")
    epmc_results = {}
    e_newly_checked = 0

    dois_to_check = [r["doi"] for r in remaining if r["doi"] and str(r["reference_id"]) not in cp["epmc_checked_refs"]]
    print(f"DOIs to check with Europe PMC: {len(dois_to_check)}")

    for i in range(0, len(dois_to_check), BATCH_SIZE_EPMC):
        batch = dois_to_check[i:i + BATCH_SIZE_EPMC]
        batch_results = check_europe_pmc_batch(batch)
        epmc_results.update(batch_results)
        e_newly_checked += len(batch_results)
        if i % 500 == 0 and i > 0:
            print(f"  Checked {i}/{len(dois_to_check)}...")
        time.sleep(SLEEP_EPMC)

    # Save EPMC check results to checkpoint
    for doi, info in epmc_results.items():
        cp["epmc_checked_refs"][doi] = info
    save_checkpoint(cp)
    print(f"  Europe PMC results: {len(epmc_results)} records retrieved")

    # Phase 2: Download from Europe PMC (XML preferred)
    print(f"\n--- Phase 2: Download ---")
    stats = Counter()
    total = len(remaining)

    for idx, ref in enumerate(remaining):
        ref_id = ref["reference_id"]
        doi = ref["doi"] or ""
        pmid = ref.get("pmid", "")
        title = ref["title"] or ""

        if idx % 50 == 0:
            print(f"\n  [{idx + 1}/{total}] Processing... (downloaded: {stats['success']}, failed: {stats['failed']})")

        epmc = epmc_results.get(doi.lower(), {}) or cp["epmc_checked_refs"].get(doi.lower(), {})
        pmcid = epmc.get("pmcid", "")
        is_oa = epmc.get("isOpenAccess", "N") in ("Y", "true", "True", True)

        success = False
        source = ""
        local_path = ""
        content_type = ""
        license_info = ""
        error_msg = ""
        oa_status = is_oa and "oa" or "unknown"

        # --- Channel 1: Europe PMC XML ---
        if pmcid and not success:
            ok, path, src = download_europe_pmc_xml(pmcid, doi)
            if ok:
                success, source, local_path, content_type = True, src, path, "application/xml"
                record_in_db(ref_id, doi, pmid, pmcid, source, "downloaded", oa_status, local_path, content_type, "", "")
            else:
                error_msg += f"epmc_xml:{src};"

        # --- Channel 2: Europe PMC PDF ---
        if pmcid and not success:
            ok, path, src = download_europe_pmc_pdf(pmcid, doi, ref_id)
            if ok:
                success, source, local_path, content_type = True, src, path, "application/pdf"
                record_in_db(ref_id, doi, pmid, pmcid, source, "downloaded", oa_status, local_path, content_type, "", "")
            else:
                error_msg += f"epmc_pdf:{src};"

        # --- Channel 3: PMC OA tar.gz ---
        if pmcid and not success:
            ok, path, src = check_and_download_pmc_oa(pmcid, doi, ref_id)
            if ok:
                success, source, local_path, content_type = True, src, path, "application/gzip"
                record_in_db(ref_id, doi, pmid, pmcid, source, "downloaded", oa_status, local_path, content_type, "", "")
            else:
                error_msg += f"pmc_oa:{src};"

        # --- Channel 4: Unpaywall PDF ---
        if not success and doi:
            up = check_unpaywall(doi)
            if up:
                safe = f"DOI_{doi.replace('/', '_')[:60]}_{ref_id}"
                out_path = FULLTEXT_DIR / f"{safe}_unpaywall.pdf"
                ok, info = download_pdf(up["pdf_url"], out_path)
                if ok:
                    success, source, local_path, content_type = True, "unpaywall", str(out_path), "application/pdf"
                    license_info = up.get("license", "")
                    record_in_db(ref_id, doi, pmid, pmcid, source, "downloaded", oa_status, local_path, content_type, license_info, "")
                else:
                    error_msg += f"unpaywall:{info};"
                time.sleep(SLEEP_DOWNLOAD)
            else:
                error_msg += "unpaywall:no_oa;"

        # Update stats
        if success:
            stats["success"] += 1
            cp["completed_refs"].append(str(ref_id))
        else:
            stats["failed"] += 1
            cp["failed_refs"].append(str(ref_id))
            record_in_db(ref_id, doi, pmid, pmcid, "multi_channel", "failed", oa_status, "", "", "", error_msg)

        # Save checkpoint every 20 refs
        if idx % 20 == 0:
            save_checkpoint(cp)

        time.sleep(SLEEP_DOWNLOAD)

    save_checkpoint(cp)

    print(f"\n{'=' * 70}")
    print("DOWNLOAD COMPLETE")
    print(f"{'=' * 70}")
    print(f"  Success: {stats['success']}")
    print(f"  Failed: {stats['failed']}")
    print(f"  Already completed (from checkpoint): {len(cp['completed_refs']) - stats['success']}")
    print(f"  Checkpoint: {CHECKPOINT_PATH}")


if __name__ == "__main__":
    main()
