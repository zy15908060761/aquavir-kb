"""
Build BLAST reference DB from locally-mapped virus proteins, then classify
unmapped DNA viruses by BLAST top-hit taxonomy. No NCBI download needed.
"""
import sqlite3, subprocess, sys, os, time
from pathlib import Path
from collections import defaultdict, Counter
from datetime import datetime

DB_PATH = Path(r"F:\水生无脊椎动物数据库\crustacean_virus_core.db")
BLAST_DIR = Path(r"F:\水生无脊椎动物数据库\blastdb")
BLAST_BIN = Path(r"F:\水生无脊椎动物数据库\tools\ncbi-blast-2.17.0+\bin\blastp.exe")
MAKEBLASTDB = Path(r"F:\水生无脊椎动物数据库\tools\ncbi-blast-2.17.0+\bin\makeblastdb.exe")
REF_FA = BLAST_DIR / "local_ref_proteins.faa"
QUERY_FA = BLAST_DIR / "target_query_proteins.faa"
OUT_TAB = BLAST_DIR / "blast_results.tsv"

EXCLUDED = ("non_target", "host_genome", "duplicate_alias_placeholder", "duplicate_ictv_vmr_placeholder")

def main():
    BLAST_DIR.mkdir(exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    c = conn.cursor()

    # Step 1: Extract reference proteins from mapped viruses
    print(f"[{datetime.now():%H:%M:%S}] Extracting reference proteins from mapped viruses...")
    c.execute(f"""
        SELECT DISTINCT vp.protein_id, vp.translation, vm.virus_family, vm.virus_genus,
               vm.canonical_name, vi.accession
        FROM viral_proteins vp
        JOIN viral_isolates vi ON vp.isolate_id = vi.isolate_id
        JOIN virus_master vm ON vi.master_id = vm.master_id
        JOIN virus_ictv_status vs ON vm.master_id = vs.master_id
        WHERE vs.ictv_status = 'mapped'
          AND vm.entry_type NOT IN {EXCLUDED}
          AND vp.translation IS NOT NULL AND length(vp.translation) > 20
    """)
    ref_rows = c.fetchall()
    print(f"  Reference proteins: {len(ref_rows)} (from mapped viruses)")

    n_ref = 0
    with open(REF_FA, 'w') as f:
        for pid, seq, family, genus, name, acc in ref_rows:
            family = family or 'Unclassified'
            genus = genus or ''
            f.write(f">ref|{pid}|{family}|{genus}|{name}|{acc}\n")
            # Write sequence in 60-char lines
            seq_clean = seq.replace('\n', '').replace(' ', '')
            for j in range(0, len(seq_clean), 60):
                f.write(seq_clean[j:j+60] + '\n')
            n_ref += 1
    print(f"  Written: {REF_FA} ({REF_FA.stat().st_size / 1024 / 1024:.1f} MB)")

    # Build BLAST DB (use temp dir to avoid permission issues on Windows)
    import tempfile
    tmpdir = Path(tempfile.mkdtemp(prefix='blast_'))
    print(f"  Using temp directory: {tmpdir}")

    if MAKEBLASTDB.exists():
        print(f"[{datetime.now():%H:%M:%S}] Building BLAST database...")
        subprocess.run([
            str(MAKEBLASTDB), '-in', str(REF_FA), '-dbtype', 'prot',
            '-title', 'AquaVir_Local_Ref', '-out', str(tmpdir / 'local_ref')
        ], check=True)
        print("  BLAST database built.")
    else:
        print("ERROR: makeblastdb not found"); sys.exit(1)

    # Step 2: Extract query proteins from pending/unclassified viruses
    print(f"[{datetime.now():%H:%M:%S}] Extracting query proteins...")
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
    qrows = c.fetchall()
    print(f"  Query proteins: {len(qrows)}")

    virus_proteins = defaultdict(list)
    with open(QUERY_FA, 'w') as f:
        for pid, seq, mid, name, gtype, family in qrows:
            f.write(f">qry|{pid}|{mid}|{name}|{gtype or ''}|{family or ''}\n")
            seq_clean = seq.replace('\n', '').replace(' ', '')
            for j in range(0, len(seq_clean), 60):
                f.write(seq_clean[j:j+60] + '\n')
            virus_proteins[mid].append({'pid': pid, 'name': name, 'gtype': gtype, 'family': family})
    n_virus = len(virus_proteins)
    print(f"  Viruses with proteins: {n_virus}")
    print(f"  Written: {QUERY_FA} ({QUERY_FA.stat().st_size / 1024 / 1024:.1f} MB)")

    # Step 3: Run BLAST
    print(f"[{datetime.now():%H:%M:%S}] Running BLASTP...")
    cmd = [
        str(BLAST_BIN), '-query', str(QUERY_FA), '-db', str(tmpdir / 'local_ref'),
        '-outfmt', '6 qseqid sseqid pident length qcovhsp evalue',
        '-evalue', '1e-5', '-max_target_seqs', '10', '-num_threads', '4',
        '-out', str(OUT_TAB)
    ]
    subprocess.run(cmd, check=True, timeout=3600)
    print(f"  BLAST complete. Output: {OUT_TAB.stat().st_size / 1024:.1f} KB")

    # Step 4: Parse BLAST results and classify
    print(f"[{datetime.now():%H:%M:%S}] Classifying viruses...")
    hit_families = defaultdict(list)  # virus_master_id -> [(protein_id, family, pident, qcov)]

    with open(OUT_TAB) as f:
        for line in f:
            parts = line.strip().split('\t')
            if len(parts) < 6:
                continue
            qseqid, sseqid, pident, length, qcovhsp, evalue = parts[0], parts[1], float(parts[2]), int(parts[3]), float(parts[4]), float(parts[5])
            # qseqid format: qry|protein_id|master_id|name|genome_type|family
            qparts = qseqid.split('|')
            if len(qparts) >= 3:
                mid = qparts[2]
                # sseqid format: ref|protein_id|family|genus|name|accession
                sparts = sseqid.split('|')
                ref_family = sparts[2] if len(sparts) >= 3 else 'Unknown'
                hit_families[mid].append({
                    'pid': qparts[1], 'family': ref_family,
                    'pident': pident, 'qcov': qcovhsp, 'evalue': evalue
                })

    classified_high, classified_med, classified_low, failed = 0, 0, 0, 0
    updates_status, updates_mappings = [], []

    for mid, hits in hit_families.items():
        if not hits:
            continue
        # Best hit per protein
        best_by_protein = {}
        for h in hits:
            if h['pid'] not in best_by_protein or h['pident'] > best_by_protein[h['pid']]['pident']:
                best_by_protein[h['pid']] = h

        # Majority vote across proteins
        family_votes = Counter(h['family'] for h in best_by_protein.values())
        top_family, top_count = family_votes.most_common(1)[0]
        consensus = top_count / len(best_by_protein)

        # Confidence from best hit
        best = max(best_by_protein.values(), key=lambda h: h['pident'])
        if best['pident'] >= 70 and best['qcov'] >= 80:
            conf = 'high'
            classified_high += 1
        elif best['pident'] >= 50:
            conf = 'medium'
            classified_med += 1
        elif best['pident'] >= 30 and best['qcov'] >= 40:
            conf = 'low'
            classified_low += 1
        else:
            failed += 1
            continue

        # Get virus info
        vinfo = virus_proteins.get(mid, [{}])[0]
        updates_status.append((conf, mid))
        updates_mappings.append((mid, top_family, conf, best['pident'], best['qcov'], consensus, len(best_by_protein)))

    total = len(virus_proteins)
    classified = classified_high + classified_med + classified_low

    print(f"\n{'='*60}")
    print("BLAST Classification Results")
    print(f"{'='*60}")
    print(f"Reference: {n_ref} proteins from mapped viruses")
    print(f"Query: {n_virus} viruses ({len(qrows)} proteins)")
    print(f"\nClassified: {classified}/{total} ({100*classified/total:.1f}%)")
    print(f"  High confidence: {classified_high}")
    print(f"  Medium confidence: {classified_med}")
    print(f"  Low confidence: {classified_low}")
    print(f"  Failed: {failed}")

    # Top families assigned
    family_counts = Counter()
    for _, fam, _, _, _, _, _ in updates_mappings:
        family_counts[fam] += 1
    print("\nTop families assigned:")
    for fam, cnt in family_counts.most_common(15):
        print(f"  {fam}: {cnt}")

    # Step 5: Update database
    print(f"\n[{datetime.now():%H:%M:%S}] Updating database...")
    c.executemany("UPDATE virus_ictv_status SET ictv_status='mapped', best_confidence=?, updated_at=datetime('now') WHERE master_id=?", updates_status)

    for mid, fam, conf, pident, qcov, consensus, nprot in updates_mappings:
        # Find ICTV taxonomy ID for the family
        c.execute("SELECT ictv_id FROM ictv_taxonomy WHERE LOWER(family) = LOWER(?) LIMIT 1", (fam,))
        ictv_row = c.fetchone()
        ictv_id = ictv_row[0] if ictv_row else None
        if ictv_id:
            c.execute("""
                INSERT OR IGNORE INTO virus_ictv_mappings
                (master_id, ictv_id, match_status, confidence, matched_family, match_method, created_at)
                VALUES (?, ?, 'auto_matched', ?, ?, 'BLASTP_local_ref', datetime('now'))
            """, (mid, ictv_id, conf, fam))

    conn.commit()
    conn.close()

    print(f"  Updated {len(updates_status)} virus_ictv_status rows")
    print(f"  Inserted {len(updates_mappings)} virus_ictv_mappings rows")
    print(f"\nDone in {time.time() - start_time:.0f}s")

    # Clean up temp directory
    import shutil
    shutil.rmtree(tmpdir, ignore_errors=True)

start_time = time.time()
main()
