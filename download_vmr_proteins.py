"""
Download VMR reference proteins from NCBI and build BLAST database.
Rate-limited batch download of ~19,130 VMR accessions.
"""
import sqlite3, time, sys, os
from pathlib import Path
from datetime import datetime

import requests

DB = Path(r"F:\水生无脊椎动物数据库\crustacean_virus_core.db")
OUT = Path(r"F:\水生无脊椎动物数据库\blastdb\vmr_reference_proteins.faa")
BLAST_DIR = Path(r"F:\水生无脊椎动物数据库\blastdb")
BLAST_BIN = Path(r"F:\水生无脊椎动物数据库\tools\ncbi-blast-2.17.0+\bin\makeblastdb.exe")
BATCH_SIZE = 100
RATE = 0.35  # seconds between requests (3/sec without API key)
RETRIES = 3

def main():
    BLAST_DIR.mkdir(exist_ok=True)
    conn = sqlite3.connect(str(DB))
    c = conn.cursor()

    # Get all VMR accessions with taxonomy
    c.execute("""
        SELECT DISTINCT vmr.genbank_accession, vmr.species, vmr.family, vmr.genus
        FROM ictv_vmr vmr
        WHERE vmr.genbank_accession IS NOT NULL AND vmr.genbank_accession != ''
    """)
    rows = c.fetchall()
    accessions = [r[0].split('.')[0] for r in rows]  # Remove version suffix
    tax_lookup = {r[0].split('.')[0]: (r[1], r[2], r[3]) for r in rows}
    conn.close()

    total = len(accessions)
    print(f"[{datetime.now().strftime('%H:%M:%S')}] VMR accessions to download: {total}")
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Batches: {(total + BATCH_SIZE - 1) // BATCH_SIZE}")

    # Check if already partially downloaded
    existing = set()
    if OUT.exists():
        with open(OUT) as f:
            for line in f:
                if line.startswith('>'):
                    acc = line.split('|')[1] if '|' in line else line[1:].split()[0]
                    existing.add(acc)
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Already downloaded: {len(existing)}")

    to_download = [a for a in accessions if a not in existing]
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Remaining to download: {len(to_download)}")

    success, failed, skipped = 0, 0, 0
    start = time.time()
    total_proteins = 0

    with open(OUT, 'a') as f:
        for i in range(0, len(to_download), BATCH_SIZE):
            batch = to_download[i:i + BATCH_SIZE]
            batch_num = i // BATCH_SIZE + 1
            total_batches = (len(to_download) + BATCH_SIZE - 1) // BATCH_SIZE

            for attempt in range(RETRIES):
                try:
                    ids = ','.join(batch)
                    url = 'https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi'
                    params = {'db': 'protein', 'id': ids, 'rettype': 'fasta', 'retmode': 'text'}
                    resp = requests.get(url, params=params, timeout=60)
                    if resp.status_code == 200 and resp.text.strip():
                        # Parse sequences and rewrite headers with taxonomy
                        seqs = resp.text.strip().split('\n>')
                        for seq in seqs:
                            if not seq.startswith('>'):
                                seq = '>' + seq
                            lines = seq.split('\n')
                            header = lines[0]
                            # Extract accession from NCBI header: >gi|xxx|ref|ACC.1| ...
                            parts = header.split('|')
                            acc = ''
                            for j, p in enumerate(parts):
                                if p in ('ref', 'gb', 'emb', 'dbj') and j + 1 < len(parts):
                                    acc = parts[j + 1].split('.')[0]
                                    break
                            if not acc:
                                acc = header[1:].split()[0].split('.')[0]

                            if acc in tax_lookup:
                                species, family, genus = tax_lookup[acc]
                                new_header = f">gb|{acc}|{species or ''}|{family or ''}|{genus or ''}"
                            else:
                                new_header = f">gb|{acc}|unknown||"
                            f.write(new_header + '\n')
                            f.write('\n'.join(lines[1:]) + '\n')
                            total_proteins += 1
                        success += len(batch)
                        f.flush()
                        break
                    elif resp.status_code == 429:
                        wait = 5 * (attempt + 1)
                        print(f"  Rate limited, waiting {wait}s...")
                        time.sleep(wait)
                    else:
                        if attempt == RETRIES - 1:
                            failed += len(batch)
                            print(f"  Batch {batch_num}: HTTP {resp.status_code}, skipping after {RETRIES} retries")
                        time.sleep(1)
                except Exception as e:
                    if attempt == RETRIES - 1:
                        failed += len(batch)
                        print(f"  Batch {batch_num}: {e}, skipping")
                    time.sleep(1)

            time.sleep(RATE)

            if batch_num % 10 == 0 or batch_num <= 3:
                elapsed = (time.time() - start) / 60
                pct = (success / len(to_download)) * 100
                print(f"[{datetime.now().strftime('%H:%M:%S')}] Batch {batch_num}/{total_batches}: {total_proteins} proteins, {pct:.0f}% done, {elapsed:.1f} min")

    elapsed = (time.time() - start) / 60
    print(f"\n{'='*60}")
    print(f"VMR Protein Download Complete")
    print(f"{'='*60}")
    print(f"Total accessions: {total}")
    print(f"  Already had: {len(existing)}")
    print(f"  Downloaded: {success}")
    print(f"  Failed: {failed}")
    print(f"Proteins written: {total_proteins}")
    print(f"Output: {OUT} ({OUT.stat().st_size / 1024 / 1024:.1f} MB)")
    print(f"Time: {elapsed:.1f} min")

    # Build BLAST DB
    if BLAST_BIN.exists():
        print(f"\nBuilding BLAST database...")
        cmd = f'"{BLAST_BIN}" -in "{OUT}" -dbtype prot -title "ICTV_VMR_Reference" -out "{BLAST_DIR / "vmr_ref"}"'
        print(f"  Running: {cmd}")
        os.system(cmd)
        print("BLAST database built successfully.")
    else:
        print(f"WARNING: makeblastdb not found at {BLAST_BIN}")
        print("FASTA file saved, but BLAST database was not built.")

if __name__ == '__main__':
    main()
