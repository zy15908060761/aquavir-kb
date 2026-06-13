#!/usr/bin/env python3
"""
VPN-Enabled Fulltext Download Script.
Run this AFTER connecting to your university VPN.

Strategy (VPN IP = institutional access):
  1. Europe PMC XML — SSL may work over VPN (bypasses corporate firewall)
  2. Unpaywall — will detect institutional IP, resolve more OA URLs
  3. Publisher direct — DOI → dx.doi.org redirect → institutional access
     (Elsevier ScienceDirect, Springer Link, Wiley, Taylor & Francis)
  4. Semantic Scholar — fallback

Targets: 3,519 no_oa refs + remaining failed refs (~6,200 total)

Usage:
  1. Connect to university VPN
  2. python download_via_vpn.py
  3. Disconnect VPN when done
"""
import json, sqlite3, time, urllib.request, urllib.error, os, re
from pathlib import Path
from datetime import datetime
from collections import Counter

# === CONFIG ===
DB_PATH = Path(r"F:\水生无脊椎动物数据库\crustacean_virus_core.db")
PROJECT_DIR = Path(r"F:\水生无脊椎动物数据库")
LIT_DIR = PROJECT_DIR / "literature_curation_v2"
PMC_XML_DIR = LIT_DIR / "pmc_xml"
FULLTEXT_DIR = LIT_DIR / "fulltext"
OA_DIR = LIT_DIR / "oa_fulltext"
LOG_DIR = PROJECT_DIR / "downloads" / "vpn_logs"

for d in [PMC_XML_DIR, FULLTEXT_DIR, OA_DIR, LOG_DIR]:
    d.mkdir(parents=True, exist_ok=True)

CHECKPOINT = LOG_DIR / "vpn_checkpoint.json"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
TIMEOUT = 60
SLEEP = 0.5

# === VPN CONNECTIVITY TEST ===
def test_vpn_connectivity():
    """Quick test to verify VPN is working and institutional access is active."""
    print("Testing VPN connectivity...")

    tests = {
        "Europe PMC": "https://www.ebi.ac.uk/europepmc/webservices/rest/search?query=test&format=json&pageSize=1",
        "NCBI": "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?db=pubmed&term=test&retmax=1&retmode=json",
        "Unpaywall": "https://api.unpaywall.org/v2/10.1038/nature12373?email=test@test.com",
        "doi.org": "https://doi.org/10.1038/nature12373",
    }

    results = {}
    for name, url in tests.items():
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=15) as resp:
                results[name] = f"OK ({resp.getcode()})"
        except Exception as e:
            msg = str(e)[:100]
            results[name] = f"FAIL: {msg}"

    print()
    for name, status in results.items():
        print(f"  {name}: {status}")

    # Check if Europe PMC works now (was SSL-blocked before)
    if "OK" in results.get("Europe PMC", ""):
        print("\n  *** Europe PMC is reachable — SSL issue resolved via VPN!")
        return True

    if all("OK" in v for v in results.values()):
        print("\n  *** All channels open — VPN is working!")
        return True

    print("\n  WARNING: Some channels still blocked. Will use available ones.")
    return True  # proceed anyway


# === CHECKPOINT ===
def load_cp():
    if CHECKPOINT.exists():
        return json.loads(CHECKPOINT.read_text(encoding="utf-8"))
    return {"done": [], "no_oa_final": []}


def save_cp(cp):
    CHECKPOINT.write_text(json.dumps(cp, ensure_ascii=False, indent=2), encoding="utf-8")


# === TARGET REFS ===
def get_target_refs():
    """Get no_oa + failed refs that haven't been processed yet."""
    con = sqlite3.connect(str(DB_PATH), timeout=60)
    con.row_factory = sqlite3.Row
    cp = load_cp()
    already = set(cp.get("done", [])) | set(cp.get("no_oa_final", []))

    cur = con.execute("""
        SELECT DISTINCT lfs.reference_id, lfs.pmid, lfs.doi, lfs.status,
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


# === DOWNLOAD CHANNELS ===
def try_europe_pmc(doi, pmid):
    """Europe PMC XML/PDF — retry now that VPN may fix SSL."""
    clean_id = (doi or f"PMID{pmid}").replace("/", "_").replace(".", "_")[:80]

    # Search for the article
    query = f'DOI:"{doi}"' if doi else f'EXT:{pmid}'
    search_url = (
        "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
        f"?query={urllib.request.quote(query)}&format=json&resultType=core"
    )
    try:
        req = urllib.request.Request(search_url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        results = data.get("resultList", {}).get("result", [])
        if not results:
            return None

        r = results[0]
        pmcid = r.get("pmcid")
        if not pmcid:
            return None

        # Download XML fulltext
        xml_url = f"https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/fullTextXML"
        req2 = urllib.request.Request(xml_url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req2, timeout=TIMEOUT) as resp2:
            content = resp2.read()
        if len(content) > 1000:
            path = PROJECT_DIR / f"DOI_{clean_id}_EPMC.xml"
            path.write_bytes(content)
            return str(path)
    except Exception:
        pass
    return None


def try_unpaywall(doi):
    """Unpaywall — institutional IP may reveal more OA copies."""
    if not doi:
        return None
    try:
        url = f"https://api.unpaywall.org/v2/{doi}?email=crustacean-db@proton.me"
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        best = data.get("best_oa_location")
        if not best:
            # Try all locations
            for loc in data.get("oa_locations", []):
                if loc.get("url_for_pdf"):
                    best = loc
                    break

        if best and best.get("url_for_pdf"):
            pdf_url = best["url_for_pdf"]
            req2 = urllib.request.Request(pdf_url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req2, timeout=TIMEOUT) as resp2:
                content = resp2.read()
            if len(content) > 5000:
                clean = doi.replace("/", "_").replace(".", "_")[:80]
                path = OA_DIR / f"{clean}_unpaywall.pdf"
                path.write_bytes(content)
                return str(path)
    except Exception:
        pass
    return None


def try_doi_direct(doi):
    """Resolve DOI → catch institutional redirect to publisher PDF."""
    if not doi:
        return None
    try:
        # Step 1: Resolve DOI to get publisher URL
        doi_url = f"https://doi.org/{doi}"
        req = urllib.request.Request(doi_url, headers={"User-Agent": UA}, method="HEAD")
        # Don't follow redirect — we want to see where it goes
        from urllib.request import HTTPRedirectHandler

        class NoRedirect(HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                return None

        opener = urllib.request.build_opener(NoRedirect)
        try:
            with opener.open(req, timeout=TIMEOUT) as resp:
                pass
        except urllib.error.HTTPError as e:
            if e.code in (301, 302, 303, 307, 308):
                publisher_url = e.headers.get("Location", "")
            else:
                return None
        except Exception:
            return None

        if not publisher_url:
            return None

        # Step 2: If it's a known publisher, try to construct PDF URL
        # Many publishers serve PDF at <article_url>/pdf or <article_url>.pdf
        clean = doi.replace("/", "_").replace(".", "_")[:80]

        # Elsevier ScienceDirect
        if "sciencedirect.com" in publisher_url or "elsevier" in publisher_url:
            # Try ScienceDirect PDF endpoint
            pii_match = re.search(r'/pii/([^/?]+)', publisher_url)
            if pii_match:
                pii = pii_match.group(1)
                pdf_urls = [
                    f"https://www.sciencedirect.com/science/article/pii/{pii}/pdfft?md5=0&pid=1-s2.0-{pii}-main.pdf",
                    f"https://www.sciencedirect.com/science/article/pii/{pii}/pdf",
                ]
                for pdf_url in pdf_urls:
                    try:
                        req2 = urllib.request.Request(pdf_url, headers={"User-Agent": UA})
                        with urllib.request.urlopen(req2, timeout=TIMEOUT) as resp2:
                            content = resp2.read()
                        if len(content) > 5000:
                            path = OA_DIR / f"{clean}_elsevier.pdf"
                            path.write_bytes(content)
                            return str(path)
                    except Exception:
                        continue

        # Springer
        if "springer.com" in publisher_url or "link.springer.com" in publisher_url:
            pdf_url = publisher_url.replace("/article/", "/content/pdf/") + ".pdf"
            if not pdf_url.endswith(".pdf"):
                pdf_url = publisher_url.rstrip("/") + ".pdf"
            try:
                req2 = urllib.request.Request(pdf_url, headers={"User-Agent": UA})
                with urllib.request.urlopen(req2, timeout=TIMEOUT) as resp2:
                    content = resp2.read()
                if len(content) > 5000:
                    path = OA_DIR / f"{clean}_springer.pdf"
                    path.write_bytes(content)
                    return str(path)
            except Exception:
                pass

        # Wiley
        if "wiley.com" in publisher_url:
            pdf_url = publisher_url + "?download=true"
            try:
                req2 = urllib.request.Request(pdf_url, headers={"User-Agent": UA})
                with urllib.request.urlopen(req2, timeout=TIMEOUT) as resp2:
                    content = resp2.read()
                if len(content) > 5000:
                    path = OA_DIR / f"{clean}_wiley.pdf"
                    path.write_bytes(content)
                    return str(path)
            except Exception:
                pass

        # Generic: try adding /pdf or .pdf to the URL
        generic_urls = [
            publisher_url.rstrip("/") + "/pdf",
            publisher_url.rstrip("/") + ".pdf",
            publisher_url.replace("/full", "/pdf") if "/full" in publisher_url else None,
        ]
        for pdf_url in [u for u in generic_urls if u]:
            try:
                req2 = urllib.request.Request(pdf_url, headers={"User-Agent": UA})
                with urllib.request.urlopen(req2, timeout=TIMEOUT) as resp2:
                    content = resp2.read()
                if len(content) > 5000 and b"<!DOCTYPE" not in content[:100]:
                    path = OA_DIR / f"{clean}_publisher.pdf"
                    path.write_bytes(content)
                    return str(path)
            except Exception:
                continue

    except Exception:
        pass
    return None


def try_semantic_scholar(doi):
    """Semantic Scholar — last resort."""
    if not doi:
        return None
    try:
        url = f"https://api.semanticscholar.org/graph/v1/paper/DOI:{doi}?fields=openAccessPdf"
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        oa = data.get("openAccessPdf")
        if oa and oa.get("url"):
            req2 = urllib.request.Request(oa["url"], headers={"User-Agent": UA})
            with urllib.request.urlopen(req2, timeout=TIMEOUT) as resp2:
                content = resp2.read()
            if len(content) > 5000:
                clean = doi.replace("/", "_").replace(".", "_")[:80]
                path = OA_DIR / f"{clean}_s2.pdf"
                path.write_bytes(content)
                return str(path)
    except Exception:
        pass
    return None


def update_db(con, ref_id, new_status, source, local_path=None, content_type=None):
    con.execute("""UPDATE literature_fulltext_sources
        SET status=?, source=?, local_path=?, content_type=?
        WHERE reference_id=? AND status IN ('no_oa','failed')""",
        (new_status, source, local_path, content_type, ref_id))


# === MAIN ===
def main():
    print("=" * 70)
    print("VPN-ENABLED FULLTEXT DOWNLOAD")
    print("=" * 70)
    print()

    # Test connectivity
    if not test_vpn_connectivity():
        print("\nVPN doesn't seem to be connected or working.")
        print("Please connect to your university VPN first, then re-run.")
        return

    print()
    print("-" * 70)

    con = sqlite3.connect(str(DB_PATH), timeout=60)
    con.row_factory = sqlite3.Row

    refs = get_target_refs()
    print(f"\nTarget refs (no_oa + failed): {len(refs)}")
    print(f"  no_oa: {sum(1 for r in refs if r['status'] == 'no_oa')}")
    print(f"  failed: {sum(1 for r in refs if r['status'] == 'failed')}")

    cp = load_cp()
    stats = Counter()
    t0 = time.time()

    print("\nDownloading... (press Ctrl+C to stop, can resume)\n")

    for i, ref in enumerate(refs):
        ref_id = ref["reference_id"]
        pmid = ref["pmid"] or ""
        doi = ref["doi"] or ""

        local_path = None
        source = "vpn"
        content_type = None

        # Channel 1: Europe PMC (now reachable via VPN)
        if not local_path:
            local_path = try_europe_pmc(doi, pmid)
            if local_path:
                source = "vpn_epmc"
                content_type = "application/xml"
                stats["epmc"] += 1

        # Channel 2: Unpaywall (institutional IP)
        if not local_path:
            local_path = try_unpaywall(doi)
            if local_path:
                source = "vpn_unpaywall"
                content_type = "application/pdf"
                stats["unpaywall"] += 1

        # Channel 3: DOI direct → publisher (institutional access)
        if not local_path:
            local_path = try_doi_direct(doi)
            if local_path:
                source = "vpn_publisher"
                content_type = "application/pdf"
                stats["publisher"] += 1

        # Channel 4: Semantic Scholar
        if not local_path:
            local_path = try_semantic_scholar(doi)
            if local_path:
                source = "vpn_s2"
                content_type = "application/pdf"
                stats["s2"] += 1

        if local_path:
            update_db(con, ref_id, "downloaded", source, local_path, content_type)
            cp.setdefault("done", []).append(ref_id)
            stats["success"] += 1
        else:
            cp.setdefault("no_oa_final", []).append(ref_id)
            stats["no_oa"] += 1

        stats["total"] += 1

        if stats["total"] % 100 == 0:
            con.commit()
            save_cp(cp)
            elapsed = time.time() - t0
            rate = stats["total"] / elapsed if elapsed > 0 else 0
            print(f"  [{stats['total']}/{len(refs)}] {rate:.1f}/s | "
                  f"OK={stats['success']} ({stats['success']/max(1,stats['total'])*100:.0f}%) | "
                  f"EPMC={stats['epmc']} UPW={stats['unpaywall']} "
                  f"PUB={stats['publisher']} S2={stats['s2']}")

        time.sleep(SLEEP)

    con.commit()
    save_cp(cp)
    con.close()

    elapsed = time.time() - t0
    print(f"\n{'=' * 70}")
    print("VPN DOWNLOAD COMPLETE")
    print(f"{'=' * 70}")
    print(f"  Time: {elapsed/60:.1f} min")
    print(f"  Total: {stats['total']}")
    print(f"  Downloaded: {stats['success']} ({stats['success']/max(1,stats['total'])*100:.1f}%)")
    print(f"  Still unavailable: {stats['no_oa']}")
    print(f"  Channels: EPMC={stats['epmc']} Unpaywall={stats['unpaywall']} "
          f"Publisher={stats['publisher']} S2={stats['s2']}")
    print(f"\n  Files in: {OA_DIR}")
    print(f"  Disconnect VPN when ready.")


if __name__ == "__main__":
    main()
