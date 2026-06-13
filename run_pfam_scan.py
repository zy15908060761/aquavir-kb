"""
Pfam-A domain annotation via pyhmmer (local, low CPU).
Scans all 22,823 viral proteins against Pfam-A HMM database.
Inserts results into interpro_annotations table.

Usage: python run_pfam_scan.py [--max 100] [--evalue 0.001]
"""

import sqlite3, sys, time, os
from pathlib import Path

BASE = Path(__file__).resolve().parent
DB = BASE / 'crustacean_virus_core.db'
PFAM_HMM = Path('F:/pfam_data/Pfam-A.hmm')

def main():
    max_proteins = None
    e_value = 0.001
    for a in sys.argv:
        if a.startswith('--max='): max_proteins = int(a.split('=')[1])
        if a.startswith('--evalue='): e_value = float(a.split('=')[1])

    if not PFAM_HMM.exists():
        print(f'ERROR: {PFAM_HMM} not found. Run annotate_pfam_local.py --download-only first.')
        return

    import pyhmmer.plan7, pyhmmer.easel

    conn = sqlite3.connect(str(DB))
    c = conn.cursor()

    # Get proteins without Pfam annotations
    sql = '''SELECT vp.protein_id, vp.protein_accession, vp.translation
             FROM viral_proteins vp
             WHERE vp.translation IS NOT NULL AND length(vp.translation) > 20
             AND vp.protein_id NOT IN (
                 SELECT DISTINCT protein_id FROM interpro_annotations
                 WHERE protein_id IS NOT NULL AND source_database = 'Pfam'
             )
             ORDER BY vp.protein_id
             LIMIT ?'''
    limit_val = max_proteins if max_proteins else 100000
    c.execute(sql, (limit_val,))
    proteins = c.fetchall()
    print(f'Proteins to scan: {len(proteins)}')

    alphabet = pyhmmer.easel.Alphabet.amino()
    new_annos = 0
    batch_size = 200  # Process in small batches to keep memory low
    t0 = time.time()

    for batch_start in range(0, len(proteins), batch_size):
        batch = proteins[batch_start:batch_start + batch_size]

        # Prepare sequences
        queries = []
        for pid, pacc, seq in batch:
            try:
                name = (pacc or str(pid)).encode('ascii', errors='replace')
                ts = pyhmmer.easel.TextSequence(sequence=seq.encode('ascii', errors='replace'), name=name)
                digi = ts.digitize(alphabet)
                queries.append((pid, digi))
            except Exception:
                continue

        if not queries:
            continue

        # Scan against Pfam
        pipeline = pyhmmer.plan7.Pipeline(alphabet, E=e_value, bit_cutoffs='gathering')

        try:
            with pyhmmer.plan7.HMMFile(str(PFAM_HMM)) as hmm_file:
                hits_iter = pipeline.search_hmm(hmm_file, [q[1] for q in queries])
        except Exception as e:
            print(f'  Search error: {e}')
            continue

        # Parse results
        for query_idx, top_hits in enumerate(hits_iter):
            pid = queries[query_idx][0]
            if not top_hits.hits:
                continue

            for hit in top_hits.hits[:5]:  # Top 5 domains per protein
                try:
                    hmm_name = hit.name.decode('ascii', errors='replace')

                    # Only store significant hits
                    if not hit.included:
                        continue

                    c.execute('''INSERT OR IGNORE INTO interpro_annotations
                        (protein_id, interpro_id, interpro_name, source_database, score, fetched_at)
                        VALUES (?, ?, ?, 'Pfam', ?, datetime('now'))''',
                        (pid, hmm_name, hmm_name, hit.score))
                    new_annos += 1
                except Exception:
                    continue

        elapsed = time.time() - t0
        pct = min(100, (batch_start + batch_size) / len(proteins) * 100)
        rate = (batch_start + batch_size) / elapsed if elapsed > 0 else 0
        eta = (len(proteins) - batch_start - batch_size) / rate if rate > 0 else 0
        print(f'  [{min(batch_start + batch_size, len(proteins))}/{len(proteins)} {pct:.1f}%] +{new_annos} hits | {elapsed/60:.1f}min elapsed | ETA {eta/60:.0f}min')

        if new_annos % 500 == 0:
            conn.commit()

    conn.commit()

    # Stats
    elapsed = time.time() - t0
    c.execute('SELECT COUNT(DISTINCT protein_id) FROM interpro_annotations WHERE source_database = \"Pfam\"')
    pfam_proteins = c.fetchone()[0]
    c.execute('SELECT COUNT(*) FROM interpro_annotations WHERE source_database = \"Pfam\"')
    pfam_total = c.fetchone()[0]
    c.execute('SELECT COUNT(*) FROM viral_proteins')
    total_proteins = c.fetchone()[0]

    print(f'\nCOMPLETE ({elapsed/60:.0f} min)')
    print(f'Pfam-annotated proteins: {pfam_proteins}/{total_proteins} ({pfam_proteins/total_proteins*100:.1f}%)')
    print(f'Total Pfam domain hits:  {pfam_total}')
    conn.close()

if __name__ == '__main__':
    main()
