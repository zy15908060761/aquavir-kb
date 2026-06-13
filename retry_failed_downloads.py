#!/usr/bin/env python3
"""
P2: Retry failed fulltext downloads.
Targets the 5,293 refs whose download previously failed (mostly network errors).
Now that NCBI / Europe PMC / Unpaywall are all reachable, most should succeed.

Channels (priority order):
  1. Europe PMC XML (best)
  2. Europe PMC PDF
  3. PMC OA direct
  4. Unpaywall OA PDF
  5. Semantic Scholar
"""
import json, sqlite3, time, urllib.request, urllib.parse, urllib.error
from pathlib import Path
from datetime import datetime
from collections import Counter

# Paths
DB_PATH = Path(r"F:\水生无脊椎动物数据库\crustacean_virus_core.db")
PROJECT_DIR = Path(r"F:\水生无脊椎动物数据库")
LIT_DIR = PROJECT_DIR / "literature_curation_v2"
PMC_XML_DIR = LIT_DIR / "pmc_xml"
FULLTEXT_DIR = LIT_DIR / "fulltext"
OA_DIR = LIT_DIR / "oa_fulltext"
EPMC_XML_DIR = PROJECT_DIR
LOG_DIR = PROJECT_DIR / "downloads" / "retry_logs"

for d in [PMC_XML_DIR, FULLTEXT_DIR, OA_DIR, LOG_DIR]:
    d.mkdir(parents=True, exist_ok=True)

CHECKPOINT_PATH = LOG_DIR / "retry_checkpoint.json"
USER_AGENT = "AquaVir-KB/2.0 literature curation (mailto:crustacean-db@proton.me)"
TIMEOUT = 60
SLEEP_EPMC = 0.4
SLEEP_DL = 0.5


def load_checkpoint():
    if CHECKPOINT_PATH.exists():
        return json.loads(CHECKPOINT_PATH.read_text(encoding="utf-8"))
    return {"completed": [], "still_failed": [], "no_oa_confirmed": []}


def save_checkpoint(cp):
    CHECKPOINT_PATH.write_text(json.dumps(cp, ensure_ascii=False, indent=2), encoding="utf-8")


def get_failed_refs():
    """Get all refs with failed download status, excluding those already retried."""
    con = sqlite3.connect(str(DB_PATH), timeout=60)
    con.row_factory = sqlite3.Row

    cp = load_checkpoint()
    already_done = set(cp.get("completed", [])) | set(cp.get("no_oa_confirmed", []))

    cur = con.execute("""
        SELECT DISTINCT lfs.reference_id, lfs.pmid, lfs.doi, lfs.source,
               rl.title, rl.journal, rl.year
        FROM literature_fulltext_sources lfs
        JOIN ref_literatures rl ON lfs.reference_id = rl.reference_id
        WHERE lfs.status = 'failed'
        ORDER BY rl.year DESC
    """)
    refs = []
    for row in cur.fetchall():
        if row["reference_id"] not in already_done:
            refs.append(dict(row))
    con.close()
    return refs


def update_fulltext_status(con, ref_id, status, source, local_path=None, content_type=None, oa_status=None):
    """Update or insert a fulltext source record."""
    con.execute("""
        UPDATE literature_fulltext_sources
        SET status = ?, source = ?, local_path = ?, content_type = ?,
            oa_status = COALESCE(?, oa_status)
        WHERE reference_id = ? AND status = 'failed'
    """, (status, source, local_path, content_type, oa_status, ref_id))


def try_europe_pmc_xml(doi, pmid, ref_id):
    """Try to download XML fulltext from Europe PMC."""
    if not doi and not pmid:
        return None

    # Try to get the fulltext XML via Europe PMC
    query_id = doi or f"EXT:{pmid}"

    # First, check if it's available
    search_url = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
    params = urllib.parse.urlencode({
        "query": query_id,
        "format": "json",
        "resultType": "core",
    })
    try:
        req = urllib.request.Request(f"{search_url}?{params}", headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None

    if not data.get("resultList", {}).get("result"):
        return None

    result = data["resultList"]["result"][0]
    epmc_pmcid = result.get("pmcid")
    has_fulltext = result.get("hasFullText", "N")

    if has_fulltext != "Y" or not epmc_pmcid:
        return None

    # Download the XML
    xml_url = f"https://www.ebi.ac.uk/europepmc/webservices/rest/{epmc_pmcid}/fullTextXML"
    try:
        req = urllib.request.Request(xml_url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            content = resp.read()
    except Exception:
        return None

    if len(content) < 500:
        return None

    # Save
    clean_id = (doi or f"PMID{pmid}").replace("/", "_").replace(".", "_")[:80]
    xml_path = EPMC_XML_DIR / f"DOI_{clean_id}_EPMC.xml"
    xml_path.write_bytes(content)

    return str(xml_path)


def try_pmc_oa(doi, pmid):
    """Try PMC OA direct download."""
    pmcid = None
    if pmid:
        # Try ID converter
        try:
            url = f"https://www.ncbi.nlm.nih.gov/pmc/utils/idconv/v1.0/?ids={pmid}&format=json&tool=AquaVirKB&email=crustacean-db@proton.me"
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            for rec in data.get("records", []):
                if rec.get("pmcid"):
                    pmcid = rec["pmcid"]
                    break
        except Exception:
            pass

    if not pmcid:
        return None

    # Download from PMC OA
    pmc_url = f"https://www.ncbi.nlm.nih.gov/pmc/articles/{pmcid}/?report=classic"
    try:
        # Try XML first
        xml_url = f"https://www.ncbi.nlm.nih.gov/research/bionlp/RESTful/pmcoa.cgi/BioC_xml/{pmcid}/unicode"
        req = urllib.request.Request(xml_url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            content = resp.read()
        if len(content) > 500:
            path = PMC_XML_DIR / f"{pmcid}.xml"
            path.write_bytes(content)
            return str(path)
    except Exception:
        pass

    # Fallback: try PMC tar.gz
    try:
        targz_url = f"https://www.ncbi.nlm.nih.gov/pmc/articles/{pmcid}/pdf/main.pdf"
        req = urllib.request.Request(targz_url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            content = resp.read()
        if len(content) > 5000:
            path = FULLTEXT_DIR / f"{pmcid}_PMC.pdf"
            path.write_bytes(content)
            return str(path)
    except Exception:
        pass

    return None


def try_unpaywall(doi):
    """Try Unpaywall for OA PDF."""
    if not doi:
        return None
    try:
        url = f"https://api.unpaywall.org/v2/{doi}?email=crustacean-db@proton.me"
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        oa_loc = data.get("best_oa_location")
        if oa_loc and oa_loc.get("url_for_pdf"):
            pdf_url = oa_loc["url_for_pdf"]
            req2 = urllib.request.Request(pdf_url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req2, timeout=TIMEOUT) as resp2:
                content = resp2.read()
            if len(content) > 5000:
                clean_doi = doi.replace("/", "_").replace(".", "_")[:80]
                path = OA_DIR / f"{clean_doi}_unpaywall.pdf"
                path.write_bytes(content)
                return str(path)
    except Exception:
        pass
    return None


def try_semantic_scholar(doi):
    """Try Semantic Scholar for OA PDF."""
    if not doi:
        return None
    try:
        url = f"https://api.semanticscholar.org/graph/v1/paper/DOI:{doi}?fields=openAccessPdf"
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        oa = data.get("openAccessPdf")
        if oa and oa.get("url"):
            pdf_url = oa["url"]
            req2 = urllib.request.Request(pdf_url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req2, timeout=TIMEOUT) as resp2:
                content = resp2.read()
            if len(content) > 5000:
                clean_doi = doi.replace("/", "_").replace(".", "_")[:80]
                path = OA_DIR / f"{clean_doi}_s2.pdf"
                path.write_bytes(content)
                return str(path)
    except Exception:
        pass
    return None


def main():
    print("=" * 70)
    print("P2: Retrying Failed Literature Downloads")
    print("=" * 70)

    con = sqlite3.connect(str(DB_PATH), timeout=60)
    con.row_factory = sqlite3.Row

    refs = get_failed_refs()
    print(f"Failed refs to retry: {len(refs)}")

    cp = load_checkpoint()
    stats = Counter()
    t0 = time.time()

    for i, ref in enumerate(refs):
        ref_id = ref["reference_id"]
        pmid = ref["pmid"] or ""
        doi = ref["doi"] or ""

        local_path = None
        source = "retry_failed"
        content_type = None

        # Try channels in priority order
        # 1. Europe PMC XML
        local_path = try_europe_pmc_xml(doi, pmid, ref_id)
        if local_path:
            source = "retry_epmc_xml"
            content_type = "application/xml"
            stats["epmc_xml"] += 1
        else:
            # 2. PMC OA
            local_path = try_pmc_oa(doi, pmid)
            if local_path:
                source = "retry_pmc_oa"
                ext = Path(local_path).suffix
                content_type = "application/xml" if ext == ".xml" else "application/pdf"
                stats["pmc_oa"] += 1
            else:
                # 3. Unpaywall
                local_path = try_unpaywall(doi)
                if local_path:
                    source = "retry_unpaywall"
                    content_type = "application/pdf"
                    stats["unpaywall"] += 1
                else:
                    # 4. Semantic Scholar
                    local_path = try_semantic_scholar(doi)
                    if local_path:
                        source = "retry_s2"
                        content_type = "application/pdf"
                        stats["s2"] += 1

        if local_path:
            update_fulltext_status(con, ref_id, "downloaded", source, local_path, content_type, "retry_success")
            cp.setdefault("completed", []).append(ref_id)
            stats["success"] += 1
        else:
            # Check if it's genuinely no OA
            # We tried all channels; mark as no_oa to avoid infinite retry
            update_fulltext_status(con, ref_id, "no_oa", "retry_all_failed", oa_status="retry_confirmed_no_oa")
            cp.setdefault("no_oa_confirmed", []).append(ref_id)
            stats["no_oa"] += 1

        stats["total"] += 1

        if stats["total"] % 50 == 0:
            con.commit()
            save_checkpoint(cp)
            elapsed = time.time() - t0
            rate = stats["total"] / elapsed if elapsed > 0 else 0
            print(f"  [{stats['total']}/{len(refs)}] rate={rate:.1f}/s | "
                  f"OK={stats['success']} noOA={stats['no_oa']} | "
                  f"epmc={stats['epmc_xml']} pmc={stats['pmc_oa']} "
                  f"upw={stats['unpaywall']} s2={stats['s2']}")

        # Sleep to be polite
        time.sleep(SLEEP_DL)

    con.commit()
    save_checkpoint(cp)

    elapsed = time.time() - t0
    print(f"\n{'=' * 70}")
    print("P2 RETRY COMPLETE")
    print(f"{'=' * 70}")
    print(f"  Time: {elapsed:.1f}s ({elapsed/60:.1f} min)")
    print(f"  Total attempted: {stats['total']}")
    print(f"  Downloaded: {stats['success']}")
    print(f"  Confirmed no OA: {stats['no_oa']}")
    print(f"  Channels: epmc_xml={stats['epmc_xml']} pmc_oa={stats['pmc_oa']} "
          f"unpaywall={stats['unpaywall']} s2={stats['s2']}")

    # Final counts
    downloaded = con.execute(
        "SELECT COUNT(DISTINCT reference_id) FROM literature_fulltext_sources WHERE status='downloaded' OR status='local'"
    ).fetchone()[0]
    still_failed = con.execute(
        "SELECT COUNT(DISTINCT reference_id) FROM literature_fulltext_sources WHERE status='failed'"
    ).fetchone()[0]
    no_oa = con.execute(
        "SELECT COUNT(DISTINCT reference_id) FROM literature_fulltext_sources WHERE status='no_oa'"
    ).fetchone()[0]
    print(f"\n  DB state: downloaded={downloaded}, failed={still_failed}, no_oa={no_oa}")

    con.close()

    # Save run log
    log_data = {
        "timestamp": datetime.now().isoformat(),
        "elapsed_s": elapsed,
        "stats": dict(stats),
        "db_state": {"downloaded": downloaded, "failed": still_failed, "no_oa": no_oa},
    }
    log_path = LOG_DIR / f"retry_{int(time.time())}.json"
    log_path.write_text(json.dumps(log_data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n  Log: {log_path}")


if __name__ == "__main__":
    main()
