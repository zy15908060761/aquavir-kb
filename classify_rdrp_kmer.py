#!/usr/bin/env python3
"""
P4: RdRp-based virus family classification using k-mer similarity.
No BLAST, no external dependencies. Pure Python, runs in seconds.

Method:
1. For each known-family RdRp, build a set of k-mers (k=8)
2. For each unknown-family RdRp, find the known sequence with highest k-mer overlap
3. Assign family if similarity > threshold
"""
import sqlite3
from pathlib import Path
from collections import Counter
from datetime import datetime

DB_PATH = Path(r"F:\水生无脊椎动物数据库\crustacean_virus_core.db")
K = 8
MIN_SIMILARITY = 0.15  # minimum Jaccard similarity to assign family


def kmer_set(seq, k=K):
    """Extract k-mer set from protein sequence."""
    if len(seq) < k:
        return set()
    return {seq[i:i+k] for i in range(len(seq) - k + 1)}


def jaccard(set1, set2):
    """Jaccard similarity between two sets."""
    if not set1 or not set2:
        return 0.0
    intersection = len(set1 & set2)
    union = len(set1 | set2)
    return intersection / union if union > 0 else 0.0


def main():
    print("=" * 70)
    print("P4: RdRp K-MER FAMILY CLASSIFICATION")
    print("=" * 70)

    con = sqlite3.connect(str(DB_PATH), timeout=60)
    cur = con.cursor()

    # Load known-family RdRp sequences
    cur.execute("""SELECT vp.protein_id, vp.protein_accession, vp.translation,
                          vm.virus_family, vm.canonical_name
                   FROM viral_proteins vp
                   JOIN viral_isolates vi ON vp.isolate_id = vi.isolate_id
                   JOIN virus_master vm ON vi.master_id = vm.master_id
                   WHERE vp.is_rdrp = 1
                     AND vm.virus_family IS NOT NULL AND vm.virus_family != '' AND vm.virus_family != 'None'
                     AND vp.translation IS NOT NULL AND length(vp.translation) >= 50""")
    known = [(pid, acc, seq, fam, name) for pid, acc, seq, fam, name in cur.fetchall()]
    print(f"Known-family RdRp: {len(known)}")

    # Load unknown-family RdRp sequences
    cur.execute("""SELECT vp.protein_id, vp.protein_accession, vp.translation,
                          vm.master_id, vm.canonical_name, vm.host_phylum
                   FROM viral_proteins vp
                   JOIN viral_isolates vi ON vp.isolate_id = vi.isolate_id
                   JOIN virus_master vm ON vi.master_id = vm.master_id
                   WHERE vp.is_rdrp = 1
                     AND (vm.virus_family IS NULL OR vm.virus_family = '' OR vm.virus_family = 'None')
                     AND vp.translation IS NOT NULL AND length(vp.translation) >= 50
                     AND (vm.host_phylum NOT IN ('non_target (algae)','non_target (vertebrate)',
                          'non_target (fungus)','non_target (plant)','non_target','non_aquatic')
                          OR vm.host_phylum IS NULL)""")
    unknown = [(pid, acc, seq, master_id, name, phylum) for pid, acc, seq, master_id, name, phylum in cur.fetchall()]
    print(f"Unknown-family RdRp: {len(unknown)}")

    # Pre-compute k-mer sets for known sequences
    print("\nBuilding k-mer index...")
    known_kmers = {}
    for pid, acc, seq, fam, name in known:
        ks = kmer_set(seq)
        if ks:
            known_kmers[pid] = {"kmers": ks, "family": fam, "name": name, "accession": acc}

    # Classify each unknown
    print("Classifying...")
    results = []
    for pid, acc, seq, master_id, name, phylum in unknown:
        uk = kmer_set(seq)
        if not uk:
            results.append((master_id, name, None, 0.0, None, None, phylum))
            continue

        best_sim = 0.0
        best_fam = None
        best_known_name = None
        best_known_acc = None

        for kpid, kdata in known_kmers.items():
            sim = jaccard(uk, kdata["kmers"])
            if sim > best_sim:
                best_sim = sim
                best_fam = kdata["family"]
                best_known_name = kdata["name"]
                best_known_acc = kdata["accession"]

        results.append((master_id, name, best_fam, best_sim, best_known_name, best_known_acc, phylum))

    # Apply threshold and update DB
    assigned = 0
    low_conf = 0
    no_match = 0

    for master_id, name, fam, sim, best_known, best_acc, phylum in results:
        if fam and sim >= MIN_SIMILARITY:
            cur.execute("""UPDATE virus_master SET virus_family = ?, notes =
                COALESCE(notes || '; ','') || 'RdRp k-mer classified (sim=%.3f, match=%s)'
                WHERE master_id = ?""" % (sim, best_known or 'unknown'), (fam, master_id))
            assigned += 1
            print(f"  {name[:45]:<45} -> {fam:<25} (sim={sim:.3f}, match={best_known or '?'})")
        elif fam and sim >= 0.05:
            cur.execute("""UPDATE virus_master SET notes =
                COALESCE(notes || '; ','') || 'RdRp k-mer low confidence (sim=%.3f, candidate=%s)'
                WHERE master_id = ?""" % (sim, fam), (master_id,))
            low_conf += 1
            print(f"  {name[:45]:<45} -> ?{fam}? (LOW sim={sim:.3f})")
        else:
            no_match += 1

    con.commit()

    # Summary
    total_v = cur.execute("SELECT COUNT(*) FROM virus_master").fetchone()[0]
    with_family = cur.execute("""SELECT COUNT(*) FROM virus_master
        WHERE virus_family IS NOT NULL AND virus_family != '' AND virus_family != 'None'""").fetchone()[0]
    target_without = cur.execute("""SELECT COUNT(*) FROM virus_master
        WHERE (virus_family IS NULL OR virus_family = '' OR virus_family = 'None')
        AND host_phylum NOT IN ('non_target (algae)','non_target (vertebrate)','non_target (fungus)','non_target (plant)','non_target','non_aquatic')""").fetchone()[0]

    print(f"\n{'=' * 70}")
    print("COMPLETE")
    print(f"{'=' * 70}")
    print(f"  Assigned (sim >= {MIN_SIMILARITY}): {assigned}")
    print(f"  Low confidence (0.05 <= sim < {MIN_SIMILARITY}): {low_conf}")
    print(f"  No match (sim < 0.05): {no_match}")
    print(f"  Family coverage: {with_family}/{total_v} = {with_family/total_v*100:.1f}%")
    print(f"  Target viruses still without family: {target_without}")

    con.close()


if __name__ == "__main__":
    main()
