"""
Build a lightweight phylogeny demo for the top 10 crustacean viruses.

The script selects one representative complete genome per virus and writes
both a Newick tree and a plain-text summary.
"""

import sqlite3
from pathlib import Path

import numpy as np
from Bio import SeqIO

DB_PATH = Path(r"F:\甲壳动物数据库\crustacean_virus_core.db")
SEQ_DIR = Path(r"F:\甲壳动物数据库\sequences")
OUT_DIR = Path(r"F:\甲壳动物数据库\downloads")
OUT_DIR.mkdir(exist_ok=True)

TOP_N = 10
MAX_COMPARE_BP = 5000


def quote_newick_label(label):
    return "'" + label.replace("'", "''") + "'"


def get_representative_sequences(limit=TOP_N):
    """Select one longest complete genome for each of the top N viruses."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        """
        WITH ranked AS (
            SELECT
                vm.canonical_name,
                v.accession,
                COALESCE(v.sequence_length, 0) AS sequence_length,
                COUNT(*) OVER (PARTITION BY vm.canonical_name) AS isolate_count
            FROM viral_isolates v
            JOIN virus_master vm ON v.master_id = vm.master_id
            WHERE v.completeness = 'complete_genome'
              AND vm.is_crustacean_virus = 1
              AND vm.entry_type NOT IN ('EST', 'patent', 'non_target')
        )
        SELECT canonical_name, accession, sequence_length, isolate_count
        FROM ranked
        ORDER BY isolate_count DESC, canonical_name ASC, sequence_length DESC
        """
    )
    rows = c.fetchall()
    conn.close()

    reps = {}
    for name, acc, length, isolate_count in rows:
        if name not in reps:
            reps[name] = {
                "accession": acc,
                "sequence_length": length,
                "isolate_count": isolate_count,
            }
        if len(reps) >= limit:
            break

    print(f"Selected {len(reps)} representative sequences:")
    for name, meta in reps.items():
        print(
            f"  {name}: {meta['accession']} "
            f"({meta['sequence_length']} bp, {meta['isolate_count']} isolates)"
        )

    return reps


def read_sequences(reps):
    """Load FASTA sequences for the selected representative accessions."""
    sequences = {}
    missing = []
    for name, meta in reps.items():
        acc = meta["accession"]
        fa_file = SEQ_DIR / f"{acc}.fasta"
        if not fa_file.exists():
            missing.append(acc)
            continue

        try:
            record = next(SeqIO.parse(str(fa_file), "fasta"))
        except StopIteration:
            missing.append(acc)
            continue

        seq_str = str(record.seq).upper()
        if not seq_str:
            missing.append(acc)
            continue

        sequences[name] = seq_str[:MAX_COMPARE_BP]

    if missing:
        print(f"Missing or unreadable FASTA for {len(missing)} accession(s):")
        for acc in missing:
            print(f"  {acc}")

    return sequences


def compute_distance_matrix(sequences):
    """Compute a simple pairwise mismatch-ratio distance matrix."""
    names = list(sequences.keys())
    seqs = [sequences[name] for name in names]
    n = len(names)
    matrix = np.zeros((n, n), dtype=float)

    print("\nComputing pairwise distances...")
    for i in range(n):
        for j in range(i + 1, n):
            s1, s2 = seqs[i], seqs[j]
            min_len = min(len(s1), len(s2))
            if min_len == 0:
                dist = 1.0
            else:
                matches = sum(
                    1
                    for a, b in zip(s1[:min_len], s2[:min_len])
                    if a == b and a in "ATGC"
                )
                dist = 1.0 - (matches / min_len)
            matrix[i, j] = matrix[j, i] = dist
            print(f"  {names[i][:20]} <-> {names[j][:20]}: {dist:.4f}")

    return names, matrix


def upgma_newick(names, matrix):
    """Build a Newick tree with a minimal pure-Python UPGMA implementation."""
    clusters = {
        i: {
            "members": [i],
            "size": 1,
            "height": 0.0,
            "newick": quote_newick_label(names[i]),
        }
        for i in range(len(names))
    }
    distances = {}
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            distances[(i, j)] = float(matrix[i, j])

    next_id = len(names)
    while len(clusters) > 1:
        a, b = min(distances, key=distances.get)
        if a not in clusters or b not in clusters:
            distances.pop((a, b), None)
            continue

        dist_ab = distances[(a, b)]
        new_height = dist_ab / 2.0
        cluster_a = clusters[a]
        cluster_b = clusters[b]
        branch_a = max(new_height - cluster_a["height"], 0.0)
        branch_b = max(new_height - cluster_b["height"], 0.0)

        merged = {
            "members": cluster_a["members"] + cluster_b["members"],
            "size": cluster_a["size"] + cluster_b["size"],
            "height": new_height,
            "newick": (
                f"({cluster_a['newick']}:{branch_a:.6f},"
                f"{cluster_b['newick']}:{branch_b:.6f})"
            ),
        }

        merged_distances = {}
        for other_id, other_cluster in list(clusters.items()):
            if other_id in (a, b):
                continue
            dist_a = cluster_distance(a, other_id, distances, matrix)
            dist_b = cluster_distance(b, other_id, distances, matrix)
            merged_distances[other_id] = (
                (cluster_a["size"] * dist_a) + (cluster_b["size"] * dist_b)
            ) / merged["size"]

        for key in list(distances):
            if a in key or b in key:
                distances.pop(key, None)

        for other_id, merged_dist in merged_distances.items():
            distances[tuple(sorted((next_id, other_id)))] = merged_dist

        del clusters[a]
        del clusters[b]
        clusters[next_id] = merged
        next_id += 1

    final_cluster = next(iter(clusters.values()))
    return final_cluster["newick"] + ";"


def cluster_distance(cluster_id, other_id, distances, matrix):
    """Retrieve the previous distance for a live cluster pair."""
    key = tuple(sorted((cluster_id, other_id)))
    if key in distances:
        return distances[key]
    return float(matrix[key[0], key[1]])


def save_newick(newick, names):
    """Save tree outputs."""
    out_file = OUT_DIR / "phylogeny_top10.nwk"
    with open(out_file, "w", encoding="utf-8") as f:
        f.write(newick)
    print(f"\nTree saved to: {out_file}")

    text_file = OUT_DIR / "phylogeny_top10.txt"
    with open(text_file, "w", encoding="utf-8") as f:
        f.write("Phylogenetic Tree (UPGMA, Top 10 viruses)\n")
        f.write("=" * 60 + "\n\n")
        f.write("Taxa:\n")
        for i, name in enumerate(names, start=1):
            f.write(f"  {i}. {name}\n")
        f.write(f"\nNewick:\n{newick}\n")
    print(f"Text summary saved to: {text_file}")

    return out_file


def main():
    reps = get_representative_sequences()
    sequences = read_sequences(reps)
    if len(sequences) < 3:
        raise RuntimeError("Need at least 3 readable representative sequences.")

    names, matrix = compute_distance_matrix(sequences)
    print("\nBuilding UPGMA tree...")
    newick = upgma_newick(names, matrix)
    save_newick(newick, names)
    print("\nPhylogeny framework built successfully.")
    return True


if __name__ == "__main__":
    main()
