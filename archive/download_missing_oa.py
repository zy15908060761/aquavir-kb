#!/usr/bin/env python3
"""
Targeted download: 633 refs with known OA status but no successful download yet.
Channels: Europe PMC, Unpaywall PDF, Semantic Scholar.
Fully resumable with checkpoint.
"""

import json
import sqlite3
import time
import urllib.request
import urllib.parse
from pathlib import Path
from datetime import datetime
from collections import Counter

DB_PATH = Path(r"F:\甲壳动物数据库\crustacean_virus_core.db")
FULLTEXT_DIR = Path(r"F:\甲壳动物数据库\literature_curation_v2\fulltext")
OA_DIR = Path(r"F:\甲壳动物数据库\literature_curation_v2\oa_fulltext")
EPMC_XML_DIR = Path(r"F:\甲壳动物数据库")
REPORT_DIR = Path(r"F:\甲壳动物数据库\downloads\literature_download_report")
CHECKPOINT_DIR = REPORT_DIR

for d in [FULLTEXT_DIR, OA_DIR, REPORT_DIR]:
    d.mkdir(parents=True, exist_ok=True)

CHECKPOINT_PATH = CHECKPOINT_DIR / "oa_download_checkpoint.json"
USER_AGENT = "CrustaVirusDB/2.0 (mailto:crustacean-db@proton.me)"
UNPAYWALL_EMAIL = "crustacean.db.research@gmail.com"
SLEEP_UW = 1.5  # Unpaywall rate limit
SLEEP_S2 = 1.0  # Semantic Scholar rate limit
SLEEP_EPMC = 1.0
TIMEOUT = 90


def load_checkpoint():
    if CHECKPOINT_PATH.exists():
        return json.loads(CHECKPOINT_PATH.read_text(encoding="utf-8"))
    return {"downloaded": [], "failed": [], "skipped": []}


def save_checkpoint(cp):
    CHECKPOINT_PATH.write_text(json.dumps(cp, ensure_ascii=False, indent=2), encoding="utf-8")


def get_oa_refs_to_download():
    """Get refs with OA status but no download."""
    con = sqlite3.connect(DB_PATH, timeout=60)
    con.row_factory = sqlite3.Row

    # Get the best OA status + DOI info for each ref without a download
    cur = con.execute("""
        SELECT r.reference_id, r.doi, r.pmid, r.title, r.year, r.journal,
               MAX(CASE
                   WHEN lfs.oa_status IN ('oa_pdf', 'oa_fulltext') THEN 5
                   WHEN lfs.oa_status IN ('gold', 'oa') THEN 4
                   WHEN lfs.oa_status = 'green' THEN 3
                   WHEN lfs.oa_status = 'hybrid' THEN 2
                   WHEN lfs.oa_status = 'Y' THEN 1
                   ELSE 0
               END) as oa_priority
        FROM ref_literatures r
        JOIN literature_fulltext_sources lfs ON r.reference_id = lfs.reference_id
        WHERE r.doi IS NOT NULL AND r.doi != ''
          AND r.reference_id NOT IN (
              SELECT DISTINCT reference_id FROM literature_fulltext_sources WHERE status = 'downloaded'
          )
        GROUP BY r.reference_id
        HAVING oa_priority > 0
        ORDER BY oa_priority DESC, r.year DESC
    """)
    refs = [dict(row) for row in cur.fetchall()]

    # Also get one best LFS record per ref for existing OA info
    for ref in refs:
        cur.execute("""
            SELECT pmcid, source, oa_status, fulltext_url, pdf_url
            FROM literature_fulltext_sources
            WHERE reference_id = ?
            ORDER BY CASE oa_status
                WHEN 'oa_pdf' THEN 5 WHEN 'oa_fulltext' THEN 4
                WHEN 'gold' THEN 3 WHEN 'oa' THEN 3
                WHEN 'green' THEN 2 WHEN 'hybrid' THEN 2 WHEN 'Y' THEN 1
                ELSE 0 END DESC
            LIMIT 1
        """, (ref["reference_id"],))
        lfs = cur.fetchone()
        if lfs:
            ref["pmcid"] = lfs[0]
            ref["lfs_source"] = lfs[1]
            ref["oa_status"] = lfs[2]
            ref["fulltext_url"] = lfs[3]
            ref["pdf_url"] = lfs[4]

    con.close()
    return refs


def record_download(ref_id, doi, pmid, pmcid, source, status, oa_status, local_path, content_type, license_info, error_msg):
    """Insert download record into literature_fulltext_sources."""
    con = sqlite3.connect(DB_PATH, timeout=60)
    try:
        con.execute("""
            INSERT INTO literature_fulltext_sources
            (reference_id, pmid, doi, pmcid, source, status, oa_status, fulltext_url, local_path, content_type, license, error, checked_at, dedupe_key)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            ref_id, pmid, doi, pmcid, source, status, oa_status,
            local_path, local_path, content_type, license_info, error_msg,
            datetime.now().isoformat(), f"{ref_id}_{source}_{int(time.time())}"
        ))
        con.commit()
    except Exception:
        pass
    finally:
        con.close()


def download_via_unpaywall(doi, ref_id):
    """Check Unpaywall for OA PDF and download."""
    url = f"https://api.unpaywall.org/v2/{urllib.parse.quote(doi)}?email={UNPAYWALL_EMAIL}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
    except Exception as e:
        return False, "", "", f"unpaywall_api:{e}"

    best = data.get("best_oa_location")
    all_locations = [best] if best else []
    all_locations.extend(data.get("oa_locations", []))

    for loc in all_locations:
        if not loc:
            continue
        pdf_url = loc.get("url_for_pdf")
        if not pdf_url:
            continue
        lic = loc.get("license", "")
        src = "unpaywall"

        safe = f"DOI_{doi.replace('/', '_')[:60]}_{ref_id}"
        out_path = FULLTEXT_DIR / f"{safe}_unpaywall.pdf"

        ok, info = download_file(pdf_url, out_path)
        if ok:
            return True, str(out_path), lic, ""
        else:
            continue  # try next location

    return False, "", "", "unpaywall:no_pdf_url"


def download_via_semantic_scholar(doi, ref_id):
    """Check Semantic Scholar for OA PDF."""
    url = f"https://api.semanticscholar.org/graph/v1/paper/DOI:{urllib.parse.quote(doi)}?fields=openAccessPdf,title"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
    except Exception as e:
        # Try alternate lookup
        return False, "", "", f"s2_api:{e}"

    oa = data.get("openAccessPdf")
    if oa and oa.get("url"):
        safe = f"DOI_{doi.replace('/', '_')[:60]}_{ref_id}"
        out_path = FULLTEXT_DIR / f"{safe}_s2.pdf"
        ok, info = download_file(oa["url"], out_path)
        if ok:
            return True, str(out_path), "", ""
        else:
            return False, "", "", f"s2_download:{info}"
    return False, "", "", "s2:no_oa_pdf"


def download_via_europe_pmc(pmcid, doi, ref_id):
    """Try Europe PMC XML and PDF."""
    if not pmcid:
        return False, "", "", "epmc:no_pmcid"

    # Try XML first
    clean_doi = doi.replace("/", "_").replace(".", "_")[:80]
    xml_path = EPMC_XML_DIR / f"DOI_{clean_doi}_EPMC.xml"
    if not xml_path.exists():
        try:
            url = f"https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/fullTextXML"
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                data = resp.read()
            if len(data) > 200:
                xml_path.write_bytes(data)
        except Exception:
            pass

    if xml_path.exists():
        return True, str(xml_path), "", "epmc_xml"

    # Try PDF
    pdf_path = FULLTEXT_DIR / f"PMC{pmcid}_{ref_id}_epmc.pdf"
    if not pdf_path.exists():
        try:
            url = f"https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/fullTextPDF"
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                data = resp.read()
            if len(data) > 2048:
                pdf_path.write_bytes(data)
        except Exception:
            pass

    if pdf_path.exists():
        return True, str(pdf_path), "", "epmc_pdf"

    return False, "", "", "epmc:no_fulltext"


def download_file(url, out_path, timeout=TIMEOUT):
    """Download a file if it doesn't already exist."""
    if out_path.exists():
        return True, str(out_path)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read()
        if len(data) < 2048:
            return False, f"file_too_small:{len(data)}"
        out_path.write_bytes(data)
        return True, str(out_path)
    except Exception as e:
        return False, str(e)[:200]


def main():
    print("=" * 70)
    print("Targeted OA Download Pipeline")
    print("=" * 70)

    cp = load_checkpoint()
    refs = get_oa_refs_to_download()
    print(f"OA refs to download: {len(refs)}")

    # Filter already downloaded/failed from checkpoint
    remaining = [r for r in refs if str(r["reference_id"]) not in cp["downloaded"] + cp["failed"] + cp["skipped"]]
    print(f"After checkpoint filter: {len(remaining)} remaining")

    # Show priority breakdown
    from collections import Counter
    priorities = Counter(r["oa_priority"] for r in remaining)
    priority_names = {5: "oa_pdf/fulltext", 4: "gold/oa", 3: "green", 2: "hybrid", 1: "Y"}
    print("Priority breakdown:")
    for p, c in sorted(priorities.items(), reverse=True):
        print(f"  {priority_names.get(p, p)}: {c}")

    stats = Counter()
    total = len(remaining)

    for idx, ref in enumerate(remaining):
        ref_id = ref["reference_id"]
        rid_str = str(ref_id)
        doi = ref["doi"] or ""
        pmid = ref["pmid"] or ""
        pmcid = ref.get("pmcid", "")
        oa_status = ref.get("oa_status", "")

        if idx % 20 == 0:
            print(f"  [{idx + 1}/{total}] Success: {stats['success']}, Failed: {stats['failed']}, "
                  f"Skipped: {stats['skipped']}, EPMC: {stats['epmc_xml']}, UW: {stats['unpaywall']}, S2: {stats['s2']}")

        success = False
        source = ""
        local_path = ""
        content_type = ""
        license_info = ""

        # Channel 1: Europe PMC (if PMCID available)
        if pmcid:
            ok, path, lic, src = download_via_europe_pmc(pmcid, doi, ref_id)
            if ok:
                success, source, local_path, content_type = True, "europe_pmc", path, "application/xml" if path.endswith(".xml") else "application/pdf"
                license_info = lic
                stats["epmc_xml" if path.endswith(".xml") else "epmc_pdf"] += 1
            time.sleep(SLEEP_EPMC)

        # Channel 2: Unpaywall
        if not success and doi:
            ok, path, lic, err = download_via_unpaywall(doi, ref_id)
            if ok:
                success, source, local_path, content_type = True, "unpaywall", path, "application/pdf"
                license_info = lic
                stats["unpaywall"] += 1
            time.sleep(SLEEP_UW)

        # Channel 3: Semantic Scholar
        if not success and doi:
            ok, path, lic, err = download_via_semantic_scholar(doi, ref_id)
            if ok:
                success, source, local_path, content_type = True, "semantic_scholar", path, "application/pdf"
                license_info = lic
                stats["s2"] += 1
            time.sleep(SLEEP_S2)

        # Record result
        if success:
            stats["success"] += 1
            cp["downloaded"].append(rid_str)
            record_download(ref_id, doi, pmid, pmcid, source, "downloaded", oa_status, local_path, content_type, license_info, "")
            print(f"    [OK] ref {ref_id}: {source} — {(ref['title'] or '')[:60]}")
        else:
            stats["failed"] += 1
            cp["failed"].append(rid_str)
            record_download(ref_id, doi, pmid, pmcid, "multi_channel_retry", "failed", oa_status, "", "", "", "all_channels_failed")

        # Checkpoint every 10 refs
        if idx % 10 == 0:
            save_checkpoint(cp)

    save_checkpoint(cp)

    print(f"\n{'=' * 70}")
    print("DOWNLOAD COMPLETE")
    print(f"{'=' * 70}")
    print(f"  Success: {stats['success']}")
    print(f"  Failed: {stats['failed']}")
    print(f"  Skipped: {stats['skipped']}")
    print(f"  By channel: EPMC={stats.get('epmc_xml', 0) + stats.get('epmc_pdf', 0)}, "
          f"UW={stats.get('unpaywall', 0)}, S2={stats.get('s2', 0)}")
    print(f"  Checkpoint: {CHECKPOINT_PATH}")


if __name__ == "__main__":
    main()
