"""Rebuild reference BLAST DB from mapped virus proteins, then salvage-classify remaining."""
import sqlite3, subprocess, sys, time, tempfile, shutil
from pathlib import Path
from collections import defaultdict, Counter
from datetime import datetime

DB = Path(r"F:\水生无脊椎动物数据库\crustacean_virus_core.db")
BLAST_DIR = Path(r"F:\水生无脊椎动物数据库\blastdb")
BLAST_BIN = Path(r"F:\水生无脊椎动物数据库\tools\ncbi-blast-2.17.0+\bin\blastp.exe")
MAKEBLASTDB = Path(r"F:\水生无脊椎动物数据库\tools\ncbi-blast-2.17.0+\bin\makeblastdb.exe")
EXCLUDED = ("non_target", "host_genome", "duplicate_alias_placeholder", "duplicate_ictv_vmr_placeholder")

# Persistent temp in project dir
TMPDIR = BLAST_DIR / "_ref_db"
TMPDIR.mkdir(exist_ok=True)
REF_FA = TMPDIR / "ref_proteins.faa"
REF_DB = TMPDIR / "ref_db"
QUERY_FA = TMPDIR / "salvage_queries.faa"
OUT_TAB = TMPDIR / "salvage_results.tsv"

def main():
    conn = sqlite3.connect(str(DB))
    c = conn.cursor()

    # Step 1: Rebuild reference
    print(f"[{datetime.now():%H:%M:%S}] Building reference FASTA...")
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
    rows = c.fetchall()
    print(f"  {len(rows)} reference proteins")

    n = 0
    with open(REF_FA, 'w') as f:
        for pid, seq, family, genus, name, acc in rows:
            family = family or 'Unclassified'
            genus = genus or ''
            seq_clean = seq.replace('\n', '').replace(' ', '')
            if len(seq_clean) < 20: continue
            f.write(f">ref|{pid}|{family}|{genus}|{name}|{acc}\n")
            for j in range(0, len(seq_clean), 60): f.write(seq_clean[j:j+60] + '\n')
            n += 1
    print(f"  Written {n} ref proteins ({REF_FA.stat().st_size/1024/1024:.1f} MB)")

    # Build DB
    subprocess.run([str(MAKEBLASTDB), '-in', str(REF_FA), '-dbtype', 'prot', '-title', 'AquaVir_Ref', '-out', str(REF_DB)], check=True)
    print("  BLAST DB built")

    # Step 2: Extract query proteins (pending + unclassified)
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
    print(f"\n[{datetime.now():%H:%M:%S}] Query proteins: {len(rows)}")

    virus_proteins = defaultdict(list)
    with open(QUERY_FA, 'w') as f:
        for pid, seq, mid, name, gtype, family in rows:
            seq_clean = seq.replace('\n', '').replace(' ', '')
            if len(seq_clean) < 20: continue
            f.write(f">qry|{pid}|{mid}|{name}|{gtype or ''}|{family or ''}\n")
            for j in range(0, len(seq_clean), 60): f.write(seq_clean[j:j+60] + '\n')
            virus_proteins[mid].append({})

    # Step 3: BLAST with looser threshold
    print(f"[{datetime.now():%H:%M:%S}] Running BLAST...")
    subprocess.run([
        str(BLAST_BIN), '-query', str(QUERY_FA), '-db', str(REF_DB),
        '-outfmt', '6 qseqid sseqid pident length qcovhsp',
        '-evalue', '1e-3', '-max_target_seqs', '10', '-num_threads', '4',
        '-out', str(OUT_TAB)
    ], check=True, timeout=3600)
    print(f"  Results: {OUT_TAB.stat().st_size/1024:.0f} KB")

    # Step 4: Classify with salvage thresholds
    hit_families = defaultdict(list)
    with open(OUT_TAB) as f:
        for line in f:
            parts = line.strip().split('\t')
            if len(parts) < 5: continue
            qseqid, sseqid, pident, length, qcovhsp = parts[0], parts[1], float(parts[2]), int(parts[3]), float(parts[4])
            qparts = qseqid.split('|'); sparts = sseqid.split('|')
            if len(qparts) >= 3 and len(sparts) >= 3:
                mid = qparts[2]
                ref_family = sparts[2]
                if not ref_family or ref_family in ('Unclassified', 'Dataset'): continue
                hit_families[mid].append({'pid': qparts[1], 'family': ref_family, 'pident': pident, 'qcov': qcovhsp})

    print(f"Parsed {len(hit_families)} viruses with BLAST hits (e-value < 1e-3)")

    # SALVAGE: pident >= 25%, qcov >= 25%
    updates_s, updates_m = [], []
    for mid, hits in hit_families.items():
        best_by_protein = {}
        for h in hits:
            if h['pid'] not in best_by_protein or h['pident'] > best_by_protein[h['pid']]['pident']:
                best_by_protein[h['pid']] = h
        family_votes = Counter(h['family'] for h in best_by_protein.values())
        top_family, top_count = family_votes.most_common(1)[0]
        best = max(best_by_protein.values(), key=lambda h: h['pident'])
        if best['pident'] >= 25 and best['qcov'] >= 25:
            conf = 'high' if best['pident'] >= 70 and best['qcov'] >= 80 else \
                   'medium' if best['pident'] >= 50 else 'low'
            updates_s.append((conf, mid))
            updates_m.append((mid, top_family, conf, best['pident'], best['qcov'], len(best_by_protein)))

    n_v = len(virus_proteins)
    print(f"Salvage classified: {len(updates_s)}/{n_v} ({100*len(updates_s)/max(n_v,1):.1f}%)")

    # Update
    if updates_s:
        c.executemany("UPDATE virus_ictv_status SET ictv_status='mapped', best_confidence=?, updated_at=datetime('now') WHERE master_id=?", updates_s)

    n_inserted = 0
    for mid, fam, conf, pident, qcov, nprot in updates_m:
        c.execute("SELECT ictv_id FROM ictv_taxonomy WHERE LOWER(family) = LOWER(?) LIMIT 1", (fam,))
        row = c.fetchone()
        if not row:
            c.execute("SELECT ictv_id FROM ictv_taxonomy WHERE LOWER(genus) = LOWER(?) LIMIT 1", (fam,))
            row = c.fetchone()
        if row:
            c.execute(
                "INSERT OR IGNORE INTO virus_ictv_mappings (master_id, ictv_id, match_status, confidence, match_type, matched_value, notes, created_at) VALUES (?, ?, 'auto_matched', ?, 'normalized_exact', ?, 'BLASTP_salvage_r3', datetime('now'))",
                (mid, row[0], conf, fam)
            ); n_inserted += 1

    conn.commit()

    c.execute(f"""SELECT vs.ictv_status, COUNT(DISTINCT vs.master_id)
    FROM virus_ictv_status vs JOIN virus_master vm ON vs.master_id = vm.master_id
    WHERE vm.entry_type NOT IN {EXCLUDED}
    GROUP BY vs.ictv_status""")
    total_v = 0
    print(f"\n{'='*60}")
    for r in c.fetchall():
        print(f"  {r[0]}: {r[1]}"); total_v += r[1]
    c.execute(f"""SELECT COUNT(DISTINCT vs.master_id)
    FROM virus_ictv_status vs JOIN virus_master vm ON vs.master_id = vm.master_id
    WHERE vs.ictv_status = 'mapped' AND vm.entry_type NOT IN {EXCLUDED}""")
    mapped = c.fetchone()[0]
    print(f"\nFINAL: {mapped}/{total_v} = {100*mapped/total_v:.1f}%  (inserted {n_inserted} mappings)")
    conn.close()
    print(f"Done in {time.time()-start_time:.0f}s")

start_time = time.time()
main()
