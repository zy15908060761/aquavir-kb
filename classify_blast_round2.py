"""Round 2: Extract NEW proteins (added since first run) and BLAST classify."""
import sqlite3, subprocess, sys, time, tempfile, shutil
from pathlib import Path
from collections import defaultdict, Counter
from datetime import datetime

DB = Path(r"F:\水生无脊椎动物数据库\crustacean_virus_core.db")
BLAST_DIR = Path(r"F:\水生无脊椎动物数据库\blastdb")
BLAST_BIN = Path(r"F:\水生无脊椎动物数据库\tools\ncbi-blast-2.17.0+\bin\blastp.exe")
TMPDIR = Path(tempfile.mkdtemp(prefix='blast_r2_'))
QUERY_FA = TMPDIR / "round2_queries.faa"
OUT_TAB = TMPDIR / "round2_results.tsv"

REF_DB = r"C:\Users\DELL\AppData\Local\Temp\blast_j40rg949\local_ref"
EXCLUDED = ("non_target", "host_genome", "duplicate_alias_placeholder", "duplicate_ictv_vmr_placeholder")

def main():
    conn = sqlite3.connect(str(DB))
    c = conn.cursor()

    # Extract proteins from pending_review and unclassified (ALL, including new ones)
    c.execute(f"""
        SELECT DISTINCT vp.protein_id, vp.translation, vm.master_id, vm.canonical_name,
               vm.genome_type, vm.virus_family
        FROM viral_proteins vp
        JOIN viral_isolates vi ON vp.isolate_id = vi.isolate_id
        JOIN virus_master vm ON vi.master_id = vm.master_id
        JOIN virus_ictv_status vs ON vm.master_id = vs.master_id
        WHERE vs.ictv_status IN ('pending_review', 'unclassified_not_expected')
          AND vm.entry_type NOT IN {EXCLUDED}
          AND vp.translation IS NOT NULL AND length(vp.translation) > 20
    """)
    rows = c.fetchall()
    print(f"[{datetime.now():%H:%M:%S}] Query proteins: {len(rows)}")

    virus_proteins = defaultdict(list)
    n_seq = 0
    with open(QUERY_FA, 'w') as f:
        for pid, seq, mid, name, gtype, family in rows:
            seq_clean = seq.replace('\n', '').replace(' ', '')
            if len(seq_clean) < 20:
                continue
            f.write(f">qry|{pid}|{mid}|{name}|{gtype or ''}|{family or ''}\n")
            for j in range(0, len(seq_clean), 60):
                f.write(seq_clean[j:j+60] + '\n')
            virus_proteins[mid].append({'pid': pid, 'name': name, 'gtype': gtype, 'family': family})
            n_seq += 1
    print(f"  Written: {QUERY_FA} ({QUERY_FA.stat().st_size/1024:.1f} KB), {n_seq} sequences")

    # BLAST
    if not Path(REF_DB + ".phr").exists():
        print("ERROR: Reference BLAST DB not found, rebuilding...")
        conn.close()
        sys.exit(1)

    print(f"[{datetime.now():%H:%M:%S}] Running BLASTP (round 2)...")
    cmd = [
        str(BLAST_BIN), '-query', str(QUERY_FA), '-db', REF_DB,
        '-outfmt', '6 qseqid sseqid pident length qcovhsp',
        '-evalue', '1e-5', '-max_target_seqs', '10', '-num_threads', '4',
        '-out', str(OUT_TAB)
    ]
    subprocess.run(cmd, check=True, timeout=3600)
    print(f"  BLAST done. Results: {OUT_TAB.stat().st_size/1024:.0f} KB")

    # Parse and classify
    hit_families = defaultdict(list)
    with open(OUT_TAB) as f:
        for line in f:
            parts = line.strip().split('\t')
            if len(parts) < 5:
                continue
            qseqid, sseqid, pident, length, qcovhsp = parts[0], parts[1], float(parts[2]), int(parts[3]), float(parts[4])
            qparts = qseqid.split('|')
            sparts = sseqid.split('|')
            if len(qparts) >= 3 and len(sparts) >= 3:
                mid = qparts[2]
                ref_family = sparts[2]
                if not ref_family or ref_family == 'Unclassified' or ref_family == 'Dataset':
                    continue
                hit_families[mid].append({'pid': qparts[1], 'family': ref_family, 'pident': pident, 'qcov': qcovhsp})

    print(f"Parsed {len(hit_families)} viruses with BLAST hits")

    classified_high, classified_med, classified_low, failed = 0, 0, 0, 0
    updates_s, updates_m = [], []

    for mid, hits in hit_families.items():
        if not hits:
            continue
        best_by_protein = {}
        for h in hits:
            if h['pid'] not in best_by_protein or h['pident'] > best_by_protein[h['pid']]['pident']:
                best_by_protein[h['pid']] = h
        family_votes = Counter(h['family'] for h in best_by_protein.values())
        top_family, top_count = family_votes.most_common(1)[0]
        best = max(best_by_protein.values(), key=lambda h: h['pident'])

        if best['pident'] >= 70 and best['qcov'] >= 80:
            conf = 'high'; classified_high += 1
        elif best['pident'] >= 50:
            conf = 'medium'; classified_med += 1
        elif best['pident'] >= 30 and best['qcov'] >= 40:
            conf = 'low'; classified_low += 1
        else:
            failed += 1; continue

        updates_s.append((conf, mid))
        updates_m.append((mid, top_family, conf, best['pident'], best['qcov'], len(best_by_protein)))

    total = len(virus_proteins)
    classified = classified_high + classified_med + classified_low
    print(f"\n{'='*60}")
    print(f"Round 2 BLAST Results: {classified}/{total} viruses classified ({100*classified/max(total,1):.1f}%)")
    print(f"  High: {classified_high}, Medium: {classified_med}, Low: {classified_low}, Failed: {failed}")

    family_counts = Counter(f[1] for f in updates_m)
    print("\nTop families assigned:")
    for fam, cnt in family_counts.most_common(15):
        print(f"  {fam}: {cnt}")

    # Update DB
    if updates_s:
        c.executemany(
            "UPDATE virus_ictv_status SET ictv_status='mapped', best_confidence=?, updated_at=datetime('now') WHERE master_id=?",
            updates_s
        )
        print(f"  Updated {len(updates_s)} status rows → mapped")

    n_inserted = 0
    for mid, fam, conf, pident, qcov, nprot in updates_m:
        c.execute("SELECT ictv_id FROM ictv_taxonomy WHERE LOWER(family) = LOWER(?) LIMIT 1", (fam,))
        row = c.fetchone()
        if not row:
            c.execute("SELECT ictv_id FROM ictv_taxonomy WHERE LOWER(genus) = LOWER(?) LIMIT 1", (fam,))
            row = c.fetchone()
        if row:
            c.execute(
                "INSERT OR IGNORE INTO virus_ictv_mappings (master_id, ictv_id, match_status, confidence, match_type, matched_value, notes, created_at) VALUES (?, ?, 'auto_matched', ?, 'normalized_exact', ?, 'BLASTP_local_ref_r2', datetime('now'))",
                (mid, row[0], conf, fam)
            )
            n_inserted += 1

    conn.commit()

    # Final audit
    c.execute(f"""SELECT vs.ictv_status, COUNT(DISTINCT vs.master_id)
    FROM virus_ictv_status vs
    JOIN virus_master vm ON vs.master_id = vm.master_id
    WHERE vm.entry_type NOT IN {EXCLUDED}
    GROUP BY vs.ictv_status""")
    print("\nFinal ICTV Status:")
    total_v = 0
    for r in c.fetchall():
        print(f"  {r[0]}: {r[1]}")
        total_v += r[1]

    c.execute(f"""SELECT COUNT(DISTINCT vs.master_id)
    FROM virus_ictv_status vs
    JOIN virus_master vm ON vs.master_id = vm.master_id
    WHERE vs.ictv_status = 'mapped' AND vm.entry_type NOT IN {EXCLUDED}""")
    mapped = c.fetchone()[0]
    print(f"\nMapping rate: {mapped}/{total_v} = {100*mapped/total_v:.1f}%")
    print(f"Mapping rows inserted: {n_inserted}")

    conn.close()
    shutil.rmtree(TMPDIR, ignore_errors=True)
    print(f"Done in {time.time()-start_time:.0f}s")

start_time = time.time()
main()
