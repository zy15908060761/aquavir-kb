#!/usr/bin/env python3
"""第4批: PMC直接PDF(HTTP) + Unpaywall扩大"""
import sqlite3, requests, time, re
from pathlib import Path

con = sqlite3.connect(r'F:\甲壳动物数据库\crustacean_virus_core.db')
PDF_DIR = Path(r'F:\甲壳动物数据库\literature_curation_v2\fulltext')
PDF_DIR.mkdir(parents=True, exist_ok=True)

session = requests.Session()
session.headers.update({'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) CrustaVirusDB/1.0'})
session.timeout = 120

total = 0
r1 = 0  # PMC direct PDF
r2 = 0  # Unpaywall

# ====== R1: PMC直接PDF (HTTP, 不是FTP) ======
print('=== R1: PMC direct PDF (HTTP) ===')
rows = con.execute("""
    SELECT lfs.reference_id, lfs.pmcid, lfs.pmid
    FROM literature_fulltext_sources lfs
    WHERE lfs.pmcid IS NOT NULL AND lfs.pmcid != ''
    AND lfs.status = 'failed'
    LIMIT 200
""").fetchall()
print(f'Count: {len(rows)}')

for i, (ref_id, pmcid, pmid) in enumerate(rows):
    pmcid_c = pmcid.replace('PMC', '')
    try:
        # 直接HTTP下载PMC PDF
        pdf_url = f'https://www.ncbi.nlm.nih.gov/pmc/articles/PMC{pmcid_c}/pdf/'
        dl = session.get(pdf_url, timeout=90, allow_redirects=True)
        ct = dl.headers.get('Content-Type', '')
        if dl.status_code == 200 and len(dl.content) > 50000 and 'pdf' in ct.lower():
            pdf_path = PDF_DIR / f'{pmcid}.pdf'
            with open(pdf_path, 'wb') as f:
                f.write(dl.content)
            con.execute("UPDATE literature_fulltext_sources SET status='downloaded', local_path=? WHERE reference_id=?",
                        (str(pdf_path), ref_id))
            r1 += 1
        else:
            # 标记为真正的no_OA
            con.execute("UPDATE literature_fulltext_sources SET status='no_oa' WHERE reference_id=?",
                        (ref_id,))
    except Exception:
        pass
    if (i + 1) % 50 == 0:
        con.commit()
        print(f'  [{i+1}/{len(rows)}] ok:{r1}')
con.commit()
print(f'R1: PMC direct PDF = {r1}')

# ====== R2: Unpaywall 扩大范围 ======
print('\n=== R2: Unpaywall expanded ===')
rows2 = con.execute("""
    SELECT lfs.reference_id, lfs.doi, lfs.pmid
    FROM literature_fulltext_sources lfs
    WHERE lfs.doi IS NOT NULL AND lfs.doi != ''
    AND lfs.status = 'failed'
    ORDER BY lfs.reference_id
""").fetchall()
print(f'Count: {len(rows2)}')

for i, (ref_id, doi, pmid) in enumerate(rows2):
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
                        con.execute("UPDATE literature_fulltext_sources SET status='downloaded', local_path=? WHERE reference_id=?",
                                    (str(pdf_path), ref_id))
                        r2 += 1
                except Exception:
                    pass
    except Exception:
        pass
    if (i + 1) % 100 == 0:
        con.commit()
        print(f'  [{i+1}/{len(rows2)}] downloaded:{r2}')
con.commit()
print(f'R2: Unpaywall = {r2}')

# Final
total = r1 + r2
total_dl = con.execute("SELECT COUNT(DISTINCT reference_id) FROM literature_fulltext_sources WHERE status='downloaded'").fetchone()[0]
total_all = con.execute("SELECT COUNT(DISTINCT reference_id) FROM literature_fulltext_sources").fetchone()[0]
print(f'\n=== Summary ===')
print(f'R1 PMC PDF: {r1}')
print(f'R2 Unpaywall: {r2}')
print(f'Total new: {total}')
print(f'Overall downloaded: {total_dl}/{total_all}')
con.close()
