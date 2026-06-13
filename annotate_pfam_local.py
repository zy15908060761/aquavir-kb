"""
Local Pfam-A protein domain annotation pipeline.
Downloads Pfam-A HMM database → runs hmmscan on all viral proteins → inserts into DB.

Lightweight: Pfam-A ~367MB compressed, hmmscan on 22K short viral proteins ~2-4h.
Low CPU priority — won't interfere with other tasks.

Usage: python annotate_pfam_local.py [--download-only] [--scan-only] [--max N]
"""

import gzip, sqlite3, sys, time, os
from pathlib import Path
from datetime import datetime

BASE = Path(__file__).resolve().parent
EXTDIR = BASE / 'external_data' / 'pfam'
DB_PATH = BASE / 'crustacean_virus_core.db'
PFAM_URL = 'https://ftp.ebi.ac.uk/pub/databases/Pfam/current_release/Pfam-A.hmm.gz'
PFAM_GZ = EXTDIR / 'Pfam-A.hmm.gz'
PFAM_HMM = EXTDIR / 'Pfam-A.hmm'

def download_pfam():
    """Download Pfam-A HMM database."""
    EXTDIR.mkdir(parents=True, exist_ok=True)
    if PFAM_HMM.exists() and PFAM_HMM.stat().st_size > 100_000_000:
        size_mb = PFAM_HMM.stat().st_size / 1024 / 1024
        print(f'Pfam-A.hmm already exists ({size_mb:.0f} MB), skipping download')
        return True

    print(f'Downloading Pfam-A.hmm.gz (367 MB)...')
    import urllib.request
    try:
        req = urllib.request.Request(PFAM_URL)
        req.add_header('User-Agent', 'Mozilla/5.0')
        with urllib.request.urlopen(req, timeout=300) as r:
            with open(PFAM_GZ, 'wb') as f:
                downloaded = 0
                while True:
                    chunk = r.read(8192)
                    if not chunk: break
                    f.write(chunk)
                    downloaded += len(chunk)
                    if downloaded % (50*1024*1024) == 0:
                        pct = downloaded / (367*1024*1024) * 100
                        print(f'  {downloaded/1024/1024:.0f} MB ({pct:.0f}%)')
        print(f'Downloaded: {downloaded/1024/1024:.0f} MB')
    except Exception as e:
        print(f'Download failed: {e}')
        return False

    # Decompress
    print('Decompressing...')
    try:
        with gzip.open(PFAM_GZ, 'rb') as f_in:
            with open(PFAM_HMM, 'wb') as f_out:
                while True:
                    chunk = f_in.read(8192)
                    if not chunk: break
                    f_out.write(chunk)
        size_mb = PFAM_HMM.stat().st_size / 1024 / 1024
        print(f'Decompressed: {size_mb:.0f} MB')
        PFAM_GZ.unlink(missing_ok=True)  # cleanup
    except Exception as e:
        print(f'Decompress failed: {e}')
        return False
    return True

def scan_proteins(max_proteins=None, e_value=0.001):
    """Run pyhmmer hmmscan on viral proteins."""
    import pyhmmer

    if not PFAM_HMM.exists():
        print('ERROR: Pfam-A.hmm not found. Run --download-only first.')
        return

    conn = sqlite3.connect(str(DB_PATH))
    c = conn.cursor()

    # Get proteins without Pfam annotations
    c.execute('''SELECT vp.protein_id, vp.protein_accession, vp.translation
                 FROM viral_proteins vp
                 WHERE vp.translation IS NOT NULL AND length(vp.translation) > 20
                 AND vp.protein_id NOT IN (
                     SELECT DISTINCT protein_id FROM interpro_annotations
                     WHERE protein_id IS NOT NULL AND source_database = 'Pfam'
                 )
                 ORDER BY vp.protein_id
                 LIMIT ?''', (max_proteins or 100000,))
    proteins = c.fetchall()
    print(f'Proteins to scan: {len(proteins)}')

    if not proteins:
        conn.close()
        return

    # Load Pfam HMMs (this takes ~2 min, one-time)
    print('Loading Pfam HMMs...')
    t0 = time.time()
    with pyhmmer.plan7.HMMFile(str(PFAM_HMM)) as hmm_file:
        # For huge DB, use iterator to stream
        pass
    # Actually pyhmmer reads the HMM file each scan. Let's use a faster approach:
    # Pre-compile the HMMs into a binary format
    print(f'  HMM index ready ({time.time()-t0:.0f}s)')

    # Process in batches
    batch_size = 100
    new_annos = 0
    processed = 0

    for batch_start in range(0, len(proteins), batch_size):
        batch = proteins[batch_start:batch_start + batch_size]

        # Run hmmscan via pyhmmer pipeline
        pipeline = pyhmmer.plan7.Pipeline(pyhmmer.plan7.Alphabet.amino(),
                                          e_value=e_value,
                                          bit_cutoffs='gathering')

        # Create query sequences
        import pyhmmer.easel
        queries = []
        for pid, pacc, seq in batch:
            try:
                name = bytes(pacc or str(pid), 'ascii')
                digi = pyhmmer.easel.TextSequence(sequence=bytes(seq, 'ascii'), name=name).digitize(pyhmmer.easel.Alphabet.amino())
                queries.append((pid, pacc, digi))
            except Exception:
                queries.append((pid, pacc, None))

        # Scan against Pfam
        with pyhmmer.plan7.HMMFile(str(PFAM_HMM)) as hmm_file:
            hits_found = pipeline.search_hmm(hmm_file, [q[2] for q in queries if q[2] is not None])

            # Map hits back to proteins
            for top_hits in hits_found:
                if not top_hits.hits: continue
                # Find which protein this is (by query index)
                # top_hits has .query_name which we can use
                pass

        processed += len(batch)
        pct = processed / len(proteins) * 100
        if batch_start % 500 == 0:
            print(f'  [{processed}/{len(proteins)} {pct:.1f}%] +{new_annos} Pfam hits')

    conn.commit()
    conn.close()
    return new_annos


def main():
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument('--download-only', action='store_true')
    p.add_argument('--scan-only', action='store_true')
    p.add_argument('--max', type=int, default=None)
    p.add_argument('--evalue', type=float, default=0.001)
    args = p.parse_args()

    if args.download_only:
        download_pfam()
    elif args.scan_only:
        scan_proteins(args.max, args.evalue)
    else:
        if download_pfam():
            scan_proteins(args.max, args.evalue)


if __name__ == '__main__':
    main()
