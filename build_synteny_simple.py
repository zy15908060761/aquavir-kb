"""
Simplified genome collinearity (synteny) analysis using k-mer anchors.

Since MUMmer is not available on Windows, this script implements a lightweight
k-mer-based approach to find conserved blocks between genome pairs.

For production use, replace with MUMmer (nucmer -l 10) when available:
  nucmer -l 10 genomeA.fasta genomeB.fasta
  mummerplot --png out.delta

Method:
  1. Extract k-mers (k=15) from both genomes
  2. Find matching k-mer positions (anchors)
  3. Chain anchors into collinear blocks (same strand)
  4. Filter blocks by minimum length (≥100 bp)
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from collections import defaultdict

from Bio import SeqIO

DB_PATH = Path(r"F:\甲壳动物数据库\crustacean_virus_core.db")
SEQ_DIR = Path(r"F:\甲壳动物数据库\sequences")
KMER_SIZE = 15
MIN_BLOCK_LEN = 100
MAX_PAIRS = 50  # Limit to avoid excessive computation


def create_synteny_table(conn: sqlite3.Connection) -> None:
    c = conn.cursor()
    c.executescript("""
    DROP TABLE IF EXISTS genome_synteny_blocks;
    CREATE TABLE genome_synteny_blocks (
        block_id INTEGER PRIMARY KEY AUTOINCREMENT,
        accession_a VARCHAR(50) NOT NULL,
        accession_b VARCHAR(50) NOT NULL,
        virus_species VARCHAR(200),
        start_a INTEGER,
        end_a INTEGER,
        start_b INTEGER,
        end_b INTEGER,
        strand INTEGER DEFAULT 1,
        block_length INTEGER,
        anchor_kmers INTEGER,
        method TEXT DEFAULT 'kmer_anchor_k15',
        UNIQUE(accession_a, accession_b, start_a, start_b)
    );
    CREATE INDEX idx_synteny_species ON genome_synteny_blocks(virus_species);
    """)
    conn.commit()
    print("[DB] Created genome_synteny_blocks table")


def load_sequence(accession: str) -> str | None:
    sf = SEQ_DIR / f"{accession}.fasta"
    if not sf.exists():
        sf = SEQ_DIR / f"{accession.split('.')[0]}.fasta"
    if not sf.exists():
        return None
    try:
        rec = next(SeqIO.parse(str(sf), "fasta"))
        return str(rec.seq).upper()
    except Exception:
        return None


def find_kmer_positions(seq: str, k: int = KMER_SIZE) -> dict[str, list[int]]:
    """Return dict: kmer -> list of start positions."""
    pos = defaultdict(list)
    for i in range(len(seq) - k + 1):
        pos[seq[i:i+k]].append(i)
    return pos


def find_synteny_blocks(seq_a: str, seq_b: str) -> list[dict]:
    """Find collinear k-mer anchor blocks between two sequences."""
    pos_a = find_kmer_positions(seq_a)
    pos_b = find_kmer_positions(seq_b)

    # Find shared kmers and their positions
    anchors = []
    for kmer, pa_list in pos_a.items():
        if kmer not in pos_b:
            continue
        pb_list = pos_b[kmer]
        for pa in pa_list:
            for pb in pb_list:
                anchors.append((pa, pb))

    if not anchors:
        return []

    # Sort by position in A
    anchors.sort(key=lambda x: x[0])

    # Chain anchors: find longest increasing subsequence in B (forward strand)
    # Simplified: greedy chaining with gap tolerance
    blocks = []
    current = [anchors[0]]
    max_gap = 500  # bp

    for i in range(1, len(anchors)):
        prev = current[-1]
        curr = anchors[i]
        if (curr[0] - prev[0] < max_gap) and (curr[1] - prev[1] < max_gap) and (curr[1] > prev[1]):
            current.append(curr)
        else:
            if len(current) >= 3:
                block_len = current[-1][0] - current[0][0] + KMER_SIZE
                if block_len >= MIN_BLOCK_LEN:
                    blocks.append({
                        "start_a": current[0][0],
                        "end_a": current[-1][0] + KMER_SIZE,
                        "start_b": current[0][1],
                        "end_b": current[-1][1] + KMER_SIZE,
                        "strand": 1,
                        "length": block_len,
                        "anchors": len(current),
                    })
            current = [curr]

    # Final block
    if len(current) >= 3:
        block_len = current[-1][0] - current[0][0] + KMER_SIZE
        if block_len >= MIN_BLOCK_LEN:
            blocks.append({
                "start_a": current[0][0],
                "end_a": current[-1][0] + KMER_SIZE,
                "start_b": current[0][1],
                "end_b": current[-1][1] + KMER_SIZE,
                "strand": 1,
                "length": block_len,
                "anchors": len(current),
            })

    return blocks


def main() -> None:
    print("=" * 60)
    print("Simplified Genome Collinearity Analysis (k-mer anchors)")
    print("=" * 60)

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    create_synteny_table(conn)

    # Select top species with multiple genomes, up to MAX_PAIRS pairs
    c.execute("""
        SELECT vm.canonical_name
        FROM viral_isolates v
        JOIN virus_master vm ON v.master_id = vm.master_id
        WHERE vm.entry_type = 'complete_genome'
          AND v.has_sequence = 1
          AND (v.genome_length IS NULL OR v.genome_length <= 200000)
        GROUP BY vm.canonical_name
        HAVING COUNT(*) >= 2
        ORDER BY COUNT(*) DESC
    """)
    species_list = [r[0] for r in c.fetchall()]
    print(f"\n[1/3] Found {len(species_list)} species eligible for synteny analysis")

    total_pairs = 0
    processed_pairs = 0
    total_blocks = 0

    for species in species_list:
        c.execute("""
            SELECT v.accession
            FROM viral_isolates v
            JOIN virus_master vm ON v.master_id = vm.master_id
            WHERE vm.canonical_name = ?
              AND v.has_sequence = 1
              AND (v.genome_length IS NULL OR v.genome_length <= 200000)
            ORDER BY v.accession
            LIMIT 3
        """, (species,))
        reps = [r[0] for r in c.fetchall()]
        if len(reps) < 2:
            continue

        acc_a, acc_b = reps[0], reps[1]
        total_pairs += 1
        if total_pairs > MAX_PAIRS:
            break

        seq_a = load_sequence(acc_a)
        seq_b = load_sequence(acc_b)
        if not seq_a or not seq_b:
            continue

        blocks = find_synteny_blocks(seq_a, seq_b)
        for b in blocks:
            c.execute("""
                INSERT OR IGNORE INTO genome_synteny_blocks
                (accession_a, accession_b, virus_species, start_a, end_a,
                 start_b, end_b, strand, block_length, anchor_kmers)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (acc_a, acc_b, species, b["start_a"], b["end_a"],
                  b["start_b"], b["end_b"], b["strand"], b["length"], b["anchors"]))
        total_blocks += len(blocks)
        processed_pairs += 1

        if processed_pairs % 10 == 0:
            conn.commit()
            print(f"    Processed {processed_pairs}/{total_pairs} pairs, {total_blocks} blocks...")

    conn.commit()

    print(f"\n[2/3] Processed {processed_pairs} pairs, found {total_blocks} synteny blocks")

    c.execute("""
        SELECT virus_species, COUNT(*) as bc, ROUND(AVG(block_length),0) as avg_len,
               ROUND(MAX(block_length),0) as max_len
        FROM genome_synteny_blocks
        GROUP BY virus_species
        ORDER BY bc DESC
        LIMIT 10
    """)
    print("\n[3/3] Top species by synteny block count:")
    for r in c.fetchall():
        print(f"    {r[0][:35]:35s}: {r[1]:3d} blocks  avg_len={r[2]:>6,.0f} bp  max={r[3]:>6,.0f} bp")

    conn.close()
    print("\n" + "=" * 60)
    print("Done! Synteny analysis complete.")
    print("\nNote: For production-quality collinearity, install MUMmer and run:")
    print("  nucmer -l 10 genomeA.fasta genomeB.fasta")
    print("  mummerplot --png out.delta")
    print("=" * 60)


if __name__ == "__main__":
    main()
