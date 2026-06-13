#!/usr/bin/env python3
"""Recover the 29 missed refs + sample test the 2,023 failed refs."""
import json, sqlite3, subprocess, re, hashlib
from pathlib import Path

DB_PATH = Path(r"F:\水生无脊椎动物数据库\crustacean_virus_core.db")
OA_DIR = Path(r"F:\水生无脊椎动物数据库\literature_curation_v2\oa_fulltext")
OA_DIR.mkdir(parents=True, exist_ok=True)

# 29 missed ref IDs from the gap analysis
MISSED_IDS = [577,1425,1561,1958,2009,2091,2275,2480,3018,3108,3115,3662,4251,
              4581,4583,5010,5181,5770,6188,6297,6307,6318,6324,6330,6475,6591,6627,6706,6726]

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"
SCI_HUB = "https://sci-hub.ru"


def curl_fetch(url, timeout=30):
    cmd = ["curl", "-sL", "--max-time", str(timeout), "-w", "%{http_code}", "-o", "-",
           "-H", f"User-Agent: {UA}", url]
    result = subprocess.run(cmd, capture_output=True, timeout=timeout+10)
    raw = result.stdout
    if len(raw) >= 3:
        code = int(raw[-3:].decode().strip())
        body = raw[:-3]
        return code, body
    return 0, None


def scihub_get_pdf(doi):
    """Get PDF content from Sci-Hub for a DOI."""
    url = f"{SCI_HUB}/{doi}"
    code, body = curl_fetch(url)
    if not body:
        return None

    html = body.decode("utf-8", errors="ignore")
    m = re.search(r'<meta\b[^>]*?\bcitation_pdf_url\b[^>]*?\bcontent\s*=\s*["\']([^"\']+)["\']', html, re.I)
    if not m:
        m = re.search(r'https?://[^"\'<>\s]+\.pdf[^"\'<>\s]*', html, re.I)
    if not m:
        return None

    pdf_url = m.group(0) if m.re.pattern.startswith("https?") else m.group(1)
    if pdf_url.startswith("//"):
        pdf_url = "https:" + pdf_url
    elif pdf_url.startswith("/"):
        pdf_url = SCI_HUB + pdf_url

    code2, pdf_content = curl_fetch(pdf_url, timeout=60)
    if pdf_content and len(pdf_content) > 5000 and pdf_content[:4] == b"%PDF":
        return pdf_content
    return None


def ncbi_try_pmc(pmid):
    """Try NCBI PMID→PMCID→download."""
    url = f"https://www.ncbi.nlm.nih.gov/pmc/utils/idconv/v1.0/?ids={pmid}&format=json&tool=AquaVirKB&email=crustacean-db@proton.me"
    code, body = curl_fetch(url)
    if not body:
        return None
    try:
        data = json.loads(body)
        pmcid = None
        for rec in data.get("records", []):
            if rec.get("pmcid"):
                pmcid = rec["pmcid"]
                break
        if not pmcid:
            return None

        xml_url = f"https://www.ncbi.nlm.nih.gov/research/bionlp/RESTful/pmcoa.cgi/BioC_xml/{pmcid}/unicode"
        code2, xml = curl_fetch(xml_url, timeout=60)
        if xml and len(xml) > 500:
            return xml, "xml"
        pdf_url = f"https://www.ncbi.nlm.nih.gov/pmc/articles/{pmcid}/pdf/main.pdf"
        code3, pdf = curl_fetch(pdf_url, timeout=60)
        if pdf and len(pdf) > 5000:
            return pdf, "pdf"
    except:
        pass
    return None


def main():
    con = sqlite3.connect(str(DB_PATH), timeout=60)
    cur = con.cursor()

    print("=== Recovering 29 missed refs ===\n")

    recovered = 0
    skipped = 0
    still_failed = 0

    for rid in MISSED_IDS:
        row = cur.execute("""SELECT rl.reference_id, rl.doi, rl.pmid, rl.title, rl.journal, lfs.status
            FROM ref_literatures rl JOIN literature_fulltext_sources lfs ON rl.reference_id=lfs.reference_id
            WHERE rl.reference_id=?""", (rid,)).fetchone()
        if not row:
            print(f"  ID={rid}: NOT FOUND")
            continue

        ref_id, doi, pmid, title, journal, status = row

        # Skip if already downloaded
        if status == "downloaded":
            print(f"  ID={rid}: already downloaded, skip")
            skipped += 1
            continue

        print(f"  ID={rid}: {(doi or 'no DOI')[:55]}...", end=" ", flush=True)

        local_path = None
        source = None

        # Try NCBI PMC first (for PMID refs)
        if pmid:
            result = ncbi_try_pmc(str(pmid))
            if result:
                content, ext = result
                h = hashlib.md5(content[:1024]).hexdigest()[:6]
                clean = (doi or f"PMID{pmid}").replace("/", "_").replace(".", "_")[:80]
                path = OA_DIR / f"{clean}_{h}_ncbi.{ext}"
                path.write_bytes(content)
                local_path = str(path)
                source = "recover_ncbi"

        # Try Sci-Hub
        if not local_path and doi:
            pdf = scihub_get_pdf(doi)
            if pdf:
                h = hashlib.md5(pdf[:1024]).hexdigest()[:6]
                clean = doi.replace("/", "_").replace(".", "_")[:80]
                path = OA_DIR / f"{clean}_{h}_scihub.pdf"
                path.write_bytes(pdf)
                local_path = str(path)
                source = "recover_scihub"

        if local_path:
            cur.execute("""UPDATE literature_fulltext_sources
                SET status='downloaded', source=?, local_path=?
                WHERE reference_id=? AND status IN ('no_oa','failed')""",
                (source, local_path, ref_id))
            con.commit()
            print(f"OK ({source})")
            recovered += 1
        else:
            print("FAIL")
            still_failed += 1

    print(f"\n=== 29 Missed: {recovered} recovered, {skipped} already done, {still_failed} still failed ===")

    # Summary
    print(f"\n=== Updated DB State ===")
    for row in cur.execute("SELECT status, COUNT(DISTINCT reference_id) FROM literature_fulltext_sources GROUP BY status ORDER BY COUNT(*) DESC"):
        print(f"  {row[0]}: {row[1]}")

    con.close()


if __name__ == "__main__":
    main()
