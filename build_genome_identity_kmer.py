"""
Fast pairwise genome identity estimation using k-mer Jaccard similarity.

For each species, selects up to 5 representative isolates and computes
shared k-mer proportion as a proxy for nucleotide identity.

Much faster than global alignment (O(N) per pair vs O(N^2) for alignment).
Suitable for same-species comparison where sequences are already similar.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from itertools import combinations

from Bio import SeqIO

DB_PATH = Path(r"F:\甲壳动物数据库\crustacean_virus_core.db")
SEQ_DIR = Path(r"F:\甲壳动物数据库\sequences")
MAX_PER_SPECIES = 5
KMER_SIZE = 11


def create_table(conn: sqlite3.Connection) -> None:
    c = conn.cursor()
    c.executescript("""
    DROP TABLE IF EXISTS genome_pairwise_identity;
    CREATE TABLE genome_pairwise_identity (
        identity_id INTEGER PRIMARY KEY AUTOINCREMENT,
        accession_a VARCHAR(50) NOT NULL,
        accession_b VARCHAR(50) NOT NULL,
        virus_species VARCHAR(200),
        identity_percent REAL,
        shared_kmers INTEGER,
        total_unique_kmers INTEGER,
        method TEXT DEFAULT 'kmer_jaccard_k11',
        UNIQUE(accession_a, accession_b)
    );
    CREATE INDEX idx_gpi_species ON genome_pairwise_identity(virus_species);
    """)
    conn.commit()
    print("[DB] Created genome_pairwise_identity table")


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


def get_kmers(seq: str, k: int = KMER_SIZE) -> set[str]:
    return {seq[i:i+k] for i in range(len(seq) - k + 1)}


def kmer_identity(seq_a: str, seq_b: str, k: int = KMER_SIZE) -> tuple[float, int, int]:
    """Return (estimated_identity%, shared_kmers, total_unique_kmers)."""
    kmers_a = get_kmers(seq_a, k)
    kmers_b = get_kmers(seq_b, k)
    shared = len(kmers_a & kmers_b)
    total = len(kmers_a | kmers_b)
    identity = (shared / total * 100.0) if total > 0 else 0.0
    return round(identity, 2), shared, total


def select_reps(conn: sqlite3.Connection, species: str) -> list[str]:
    c = conn.cursor()
    c.execute("""
        SELECT v.accession
        FROM viral_isolates v
        JOIN virus_master vm ON v.master_id = vm.master_id
        WHERE vm.canonical_name = ?
          AND v.has_sequence = 1
          AND (v.genome_length IS NULL OR v.genome_length <= 500000)
        GROUP BY v.accession
        ORDER BY v.accession
        LIMIT ?
    """, (species, MAX_PER_SPECIES))
    return [r[0] for r in c.fetchall()]


def main() -> None:
    print("=" * 60)
    print("Building Genome Identity Matrix (k-mer method)")
    print("=" * 60)

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    create_table(conn)

    c.execute("""
        SELECT vm.canonical_name, COUNT(*) as cnt
        FROM viral_isolates v
        JOIN virus_master vm ON v.master_id = vm.master_id
        WHERE vm.entry_type = 'complete_genome'
          AND v.has_sequence = 1
          AND (v.genome_length IS NULL OR v.genome_length <= 500000)
        GROUP BY vm.canonical_name
        HAVING COUNT(*) >= 2
        ORDER BY COUNT(*) DESC
    """)
    species_list = c.fetchall()
    print(f"\n[1/3] {len(species_list)} species with >=2 genomes")

    total_pairs = 0
    computed = 0
    skipped = 0

    for sp_row in species_list:
        species = sp_row["canonical_name"]
        reps = select_reps(conn, species)
        if len(reps) < 2:
            continue

        seqs = {}
        for acc in reps:
            seq = load_sequence(acc)
            if seq:
                seqs[acc] = seq

        if len(seqs) < 2:
            continue

        pairs = list(combinations(sorted(seqs.keys()), 2))
        total_pairs += len(pairs)

        for acc_a, acc_b in pairs:
            ident, shared, total = kmer_identity(seqs[acc_a], seqs[acc_b])
            c.execute("""
                INSERT INTO genome_pairwise_identity
                (accession_a, accession_b, virus_species, identity_percent,
                 shared_kmers, total_unique_kmers, method)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (acc_a, acc_b, species, ident, shared, total, f"kmer_jaccard_k{KMER_SIZE}"))
            computed += 1

        if computed % 200 == 0:
            conn.commit()
            print(f"    {computed}/{total_pairs} pairs computed...")

    conn.commit()

    print(f"\n[2/3] Computed {computed} pairs, skipped {skipped}")

    print("\n[3/3] Identity distribution:")
    c.execute("""
        SELECT CASE
            WHEN identity_percent >= 99 THEN '>=99%'
            WHEN identity_percent >= 95 THEN '95-99%'
            WHEN identity_percent >= 90 THEN '90-95%'
            WHEN identity_percent >= 80 THEN '80-90%'
            WHEN identity_percent >= 70 THEN '70-80%'
            WHEN identity_percent >= 50 THEN '50-70%'
            ELSE '<50%'
        END as bucket, COUNT(*) as cnt, ROUND(AVG(identity_percent),1) as avg
        FROM genome_pairwise_identity GROUP BY bucket ORDER BY MIN(identity_percent)
    """)
    for r in c.fetchall():
        print(f"    {r[0]:10s}: {r[1]:4d} pairs (avg {r[2]}%)")

    c.execute("""
        SELECT virus_species, COUNT(*) as pc, ROUND(AVG(identity_percent),1) as avg,
               ROUND(MIN(identity_percent),1) as mn, ROUND(MAX(identity_percent),1) as mx
        FROM genome_pairwise_identity GROUP BY virus_species HAVING COUNT(*) >= 2
        ORDER BY avg DESC LIMIT 15
    """)
    print("\n  Top species by avg within-species identity:")
    for r in c.fetchall():
        print(f"    {r[0][:35]:35s}: {r[1]:3d} pairs avg={r[2]:5.1f}% [{r[3]:.1f}%-{r[4]:.1f}%]")

    conn.close()
    print("\n" + "=" * 60)
    print("Done! Genome identity matrix (k-mer) built.")
    print("=" * 60)


if __name__ == "__main__":
    main()
