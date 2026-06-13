#!/usr/bin/env python3
"""第3批下载: PMCID PMC OA → PMID转换 → Unpaywall"""
import sqlite3, requests, tarfile, time, re, os, json
from pathlib import Path

con = sqlite3.connect(r'F:\甲壳动物数据库\crustacean_virus_core.db')
OA_DIR = Path(r'F:\甲壳动物数据库\literature_curation_v2\oa_fulltext')
PDF_DIR = Path(r'F:\甲壳动物数据库\literature_curation_v2\fulltext')
XML_DIR = Path(r'F:\甲壳动物数据库\literature_curation_v2\pmc_xml')
for d in [OA_DIR, PDF_DIR, XML_DIR]:
    d.mkdir(parents=True, exist_ok=True)

session = requests.Session()
session.headers.update({'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) CrustaVirusDB/1.0'})
session.timeout = 120

total_success = 0
total_not_oa = 0
total_fail = 0

# ====== 第一轮: PMCID → PMC OA ======
print('=== Round 1: PMCID -> PMC OA ===')
rows = con.execute("""
    SELECT lfs.reference_id, lfs.pmcid, lfs.pmid, rl.title
    FROM literature_fulltext_sources lfs
    JOIN ref_literatures rl ON lfs.reference_id = rl.reference_id
    WHERE lfs.pmcid IS NOT NULL AND lfs.pmcid != ''
    AND lfs.status != 'downloaded' AND lfs.status != 'no_oa'
    ORDER BY lfs.status = 'failed' DESC
    LIMIT 500
""").fetchall()
print(f'Count: {len(rows)}')

for i, (ref_id, pmcid, pmid, title) in enumerate(rows):
    pmcid_c = pmcid.replace('PMC', '')
    if not pmcid_c:
        continue
    try:
        oa_url = f'https://www.ncbi.nlm.nih.gov/pmc/utils/oa/oa.fcgi?id=PMC{pmcid_c}&format=tgz'
        resp = session.get(oa_url, timeout=60)
        text = resp.text
        if 'idIsNotOpenAccess' in text or '<error' in text:
            con.execute("UPDATE literature_fulltext_sources SET status='no_oa' WHERE reference_id=?", (ref_id,))
            total_not_oa += 1
            continue
        start = text.find('href="')
        if start < 0:
            total_fail += 1
            continue
        start += 6
        end = text.find('"', start)
        dl_url = text[start:end]
        dl = session.get(dl_url, timeout=180)
        if dl.status_code == 200 and len(dl.content) > 1000:
            out_path = OA_DIR / f'PMC{pmcid_c}.tar.gz'
            with open(out_path, 'wb') as f:
                f.write(dl.content)
            # extract
            try:
                with tarfile.open(out_path, 'r:gz') as tar:
                    for member in tar.getmembers():
                        fn = member.name.lower()
                        if fn.endswith('.pdf'):
                            tar.extract(member, PDF_DIR)
                        elif fn.endswith('.nxml'):
                            tar.extract(member, XML_DIR)
            except Exception:
                pass
            con.execute("UPDATE literature_fulltext_sources SET status='downloaded', local_path=? WHERE reference_id=?", (str(out_path), ref_id))
            total_success += 1
        else:
            total_fail += 1
    except Exception as e:
        total_fail += 1

    if (i + 1) % 50 == 0:
        con.commit()
        print(f'  [{i+1}/{len(rows)}] ok:{total_success} no_oa:{total_not_oa} fail:{total_fail}')

con.commit()
print(f'R1 done: ok={total_success} no_oa={total_not_oa} fail={total_fail}')

# ====== 第二轮: PMID -> PMCID -> OA ======
print('\n=== Round 2: PMID -> PMCID -> OA ===')
rows2 = con.execute("""
    SELECT lfs.reference_id, lfs.pmid, lfs.doi, rl.title
    FROM literature_fulltext_sources lfs
    JOIN ref_literatures rl ON lfs.reference_id = rl.reference_id
    WHERE lfs.pmid IS NOT NULL AND lfs.pmid != ''
    AND (lfs.pmcid IS NULL OR lfs.pmcid = '')
    AND lfs.status = 'failed'
    LIMIT 300
""").fetchall()
print(f'Count: {len(rows2)}')

r2_found = 0
r2_ok = 0
for i, (ref_id, pmid, doi, title) in enumerate(rows2):
    try:
        eurl = f'https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=pubmed&id={pmid}&retmode=xml'
        resp = session.get(eurl, timeout=30)
        m = re.search(r'pub-id-type="pmc">PMC(\d+)<', resp.text)
        if m:
            new_pmc = m.group(1)
            r2_found += 1
            con.execute("UPDATE literature_fulltext_sources SET pmcid=? WHERE reference_id=?", (f'PMC{new_pmc}', ref_id))
            # try download
            try:
                oa_url = f'https://www.ncbi.nlm.nih.gov/pmc/utils/oa/oa.fcgi?id=PMC{new_pmc}&format=tgz'
                resp2 = session.get(oa_url, timeout=60)
                if 'idIsNotOpenAccess' not in resp2.text:
                    s = resp2.text.find('href="')
                    if s >= 0:
                        dl_url = resp2.text[s+6:resp2.text.find('"', s+6)]
                        dl = session.get(dl_url, timeout=180)
                        if dl.status_code == 200 and len(dl.content) > 1000:
                            out_path = OA_DIR / f'PMC{new_pmc}.tar.gz'
                            with open(out_path, 'wb') as f:
                                f.write(dl.content)
                            try:
                                with tarfile.open(out_path, 'r:gz') as tar:
                                    for member in tar.getmembers():
                                        fn = member.name.lower()
                                        if fn.endswith('.pdf'):
                                            tar.extract(member, PDF_DIR)
                                        elif fn.endswith('.nxml'):
                                            tar.extract(member, XML_DIR)
                            except Exception:
                                pass
                            con.execute("UPDATE literature_fulltext_sources SET status='downloaded', local_path=? WHERE reference_id=?", (str(out_path), ref_id))
                            r2_ok += 1
            except Exception:
                pass
    except Exception:
        pass

    if (i + 1) % 50 == 0:
        con.commit()
        print(f'  [{i+1}/{len(rows2)}] found_pmcid:{r2_found} downloaded:{r2_ok}')

con.commit()
print(f'R2 done: found_pmcid={r2_found} downloaded={r2_ok}')

# ====== 第三轮: Unpaywall DOI ======
print('\n=== Round 3: DOI -> Unpaywall ===')
rows3 = con.execute("""
    SELECT lfs.reference_id, lfs.doi, lfs.pmid
    FROM literature_fulltext_sources lfs
    WHERE lfs.doi IS NOT NULL AND lfs.doi != ''
    AND lfs.status = 'failed'
    LIMIT 200
""").fetchall()
print(f'Count: {len(rows3)}')

r3_ok = 0
for i, (ref_id, doi, pmid) in enumerate(rows3):
    try:
        resp = session.get(f'https://api.unpaywall.org/v2/{doi}?email=crustacean-db@proton.me', timeout=30)
        if resp.status_code == 200:
            data = resp.json()
            best = data.get('best_oa_location') or {}
            pdf_url = best.get('url_for_pdf') or best.get('url')
            if pdf_url:
                try:
                    dl = session.get(pdf_url, timeout=90, allow_redirects=True)
                    if dl.status_code == 200 and len(dl.content) > 50000:
                        safe_doi = re.sub(r'[<>:"/\\|?*]+', '_', doi)[:60]
                        pdf_path = PDF_DIR / f'DOI_{safe_doi}_unpaywall.pdf'
                        with open(pdf_path, 'wb') as f:
                            f.write(dl.content)
                        con.execute("UPDATE literature_fulltext_sources SET status='downloaded', local_path=? WHERE reference_id=?", (str(pdf_path), ref_id))
                        r3_ok += 1
                except Exception:
                    pass
    except Exception:
        pass
    if (i + 1) % 50 == 0:
        con.commit()
        print(f'  [{i+1}/{len(rows3)}] downloaded:{r3_ok}')

con.commit()
print(f'R3 done: downloaded={r3_ok}')

# Final
total_new = total_success + r2_ok + r3_ok
total_dl = con.execute("SELECT COUNT(DISTINCT reference_id) FROM literature_fulltext_sources WHERE status='downloaded'").fetchone()[0]
print(f'\n=== Summary ===')
print(f'R1 PMC OA: {total_success}')
print(f'R2 PMID->PMCID->OA: {r2_ok}')
print(f'R3 Unpaywall: {r3_ok}')
print(f'Total new downloads: {total_new}')
print(f'Already downloaded: {total_dl}')
con.close()
