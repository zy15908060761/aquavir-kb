"""
Build pairwise genome nucleotide identity matrix for virus species with multiple isolates.

Strategy (scalable):
  - Per species, select up to 5 representative isolates with diverse geography/year
  - Perform global pairwise alignment using Biopython PairwiseAligner
  - Store identity %, alignment length, mismatches, gaps

Inspired by IVCDB Section "Genomic nucleotide sequence identity".
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from itertools import combinations

from Bio import SeqIO
from Bio.Align import PairwiseAligner

DB_PATH = Path(r"F:\甲壳动物数据库\crustacean_virus_core.db")
SEQ_DIR = Path(r"F:\甲壳动物数据库\sequences")
MAX_PER_SPECIES = 5


def create_identity_table(conn: sqlite3.Connection) -> None:
    c = conn.cursor()
    c.executescript("""
    DROP TABLE IF EXISTS genome_pairwise_identity;
    CREATE TABLE genome_pairwise_identity (
        identity_id INTEGER PRIMARY KEY AUTOINCREMENT,
        accession_a VARCHAR(50) NOT NULL,
        accession_b VARCHAR(50) NOT NULL,
        virus_species VARCHAR(200),
        identity_percent REAL,
        alignment_length INTEGER,
        matches INTEGER,
        mismatches INTEGER,
        gaps INTEGER,
        score REAL,
        method TEXT DEFAULT 'biopython_global',
        UNIQUE(accession_a, accession_b)
    );
    CREATE INDEX idx_gpi_species ON genome_pairwise_identity(virus_species);
    CREATE INDEX idx_gpi_a ON genome_pairwise_identity(accession_a);
    CREATE INDEX idx_gpi_b ON genome_pairwise_identity(accession_b);
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


def compute_identity(seq_a: str, seq_b: str) -> dict | None:
    """Global alignment and identity metrics."""
    aligner = PairwiseAligner()
    aligner.mode = "global"
    aligner.match_score = 1
    aligner.mismatch_score = 0
    aligner.open_gap_score = -1
    aligner.extend_gap_score = -0.5

    try:
        alignments = aligner.align(seq_a, seq_b)
        if not alignments:
            return None
        alignment = alignments[0]
    except Exception:
        return None

    # Count matches, mismatches, gaps from formatted alignment
    formatted = alignment.format()
    lines = formatted.strip().splitlines()
    if len(lines) < 3:
        return None

    # Extract aligned sequences (Biopython format has seqA, match line, seqB)
    aln_seq_a = lines[0].split()[-1] if lines[0] else ""
    match_line = lines[1] if len(lines) > 1 else ""
    aln_seq_b = lines[2].split()[-1] if len(lines) > 2 else ""

    # If format is different, try to extract from alignment object
    if not aln_seq_a or not aln_seq_b:
        aln_seq_a = str(alignment[0])
        aln_seq_b = str(alignment[1])

    matches = 0
    mismatches = 0
    gaps = 0
    for ca, cb in zip(aln_seq_a, aln_seq_b):
        if ca == "-" or cb == "-":
            gaps += 1
        elif ca == cb:
            matches += 1
        else:
            mismatches += 1

    aln_len = len(aln_seq_a)
    identity = (matches / aln_len * 100.0) if aln_len > 0 else 0.0

    return {
        "identity_percent": round(identity, 2),
        "alignment_length": aln_len,
        "matches": matches,
        "mismatches": mismatches,
        "gaps": gaps,
        "score": alignment.score,
    }


def select_representatives(conn: sqlite3.Connection, species: str) -> list[dict]:
    """Select up to MAX_PER_SPECIES diverse isolates for a species."""
    c = conn.cursor()
    c.execute("""
        SELECT v.accession, v.genome_length,
               s.country, s.collection_year, s.continent
        FROM viral_isolates v
        JOIN virus_master vm ON v.master_id = vm.master_id
        LEFT JOIN infection_records ir ON v.isolate_id = ir.isolate_id
        LEFT JOIN sample_collections s ON ir.collection_id = s.collection_id
        WHERE vm.canonical_name = ?
          AND v.has_sequence = 1
          AND (v.genome_length IS NULL OR v.genome_length <= 500000)
        GROUP BY v.accession
        ORDER BY 
            CASE WHEN s.country IS NOT NULL AND s.country != '' THEN 0 ELSE 1 END,
            CASE WHEN s.collection_year IS NOT NULL AND s.collection_year != '' THEN 0 ELSE 1 END,
            v.accession
        LIMIT ?
    """, (species, MAX_PER_SPECIES))
    rows = c.fetchall()
    return [{"accession": r["accession"], "length": r["genome_length"],
             "country": r["country"], "year": r["collection_year"]} for r in rows]


def main() -> None:
    print("=" * 60)
    print("Building Genome Pairwise Identity Matrix")
    print("=" * 60)

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    create_identity_table(conn)

    # Find species with >= 2 complete genomes
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
    print(f"\n[1/4] Found {len(species_list)} species with >=2 complete genomes")

    total_pairs = 0
    computed = 0
    skipped = 0

    for sp_row in species_list:
        species = sp_row["canonical_name"]
        reps = select_representatives(conn, species)
        if len(reps) < 2:
            continue

        # Load sequences
        seqs = {}
        for r in reps:
            seq = load_sequence(r["accession"])
            if seq:
                seqs[r["accession"]] = seq

        if len(seqs) < 2:
            continue

        pairs = list(combinations(sorted(seqs.keys()), 2))
        total_pairs += len(pairs)

        for acc_a, acc_b in pairs:
            # Check if already computed
            c.execute("""
                SELECT 1 FROM genome_pairwise_identity
                WHERE (accession_a = ? AND accession_b = ?)
                   OR (accession_a = ? AND accession_b = ?)
            """, (acc_a, acc_b, acc_b, acc_a))
            if c.fetchone():
                continue

            result = compute_identity(seqs[acc_a], seqs[acc_b])
            if not result:
                skipped += 1
                continue

            c.execute("""
                INSERT INTO genome_pairwise_identity
                (accession_a, accession_b, virus_species, identity_percent,
                 alignment_length, matches, mismatches, gaps, score)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                acc_a, acc_b, species,
                result["identity_percent"], result["alignment_length"],
                result["matches"], result["mismatches"], result["gaps"],
                result["score"],
            ))
            computed += 1

        if computed % 50 == 0:
            conn.commit()
            print(f"    Computed {computed}/{total_pairs} pairs...")

    conn.commit()

    print(f"\n[2/4] Computation complete:")
    print(f"    Species processed: {len(species_list)}")
    print(f"    Total pairs: {total_pairs}")
    print(f"    Computed successfully: {computed}")
    print(f"    Skipped/failed: {skipped}")

    # Stats
    print(f"\n[3/4] Identity distribution:")
    c.execute("""
        SELECT 
            CASE 
                WHEN identity_percent >= 99 THEN '>=99%'
                WHEN identity_percent >= 95 THEN '95-99%'
                WHEN identity_percent >= 90 THEN '90-95%'
                WHEN identity_percent >= 80 THEN '80-90%'
                WHEN identity_percent >= 70 THEN '70-80%'
                WHEN identity_percent >= 50 THEN '50-70%'
                ELSE '<50%'
            END as bucket,
            COUNT(*) as cnt,
            ROUND(AVG(identity_percent), 1) as avg_id
        FROM genome_pairwise_identity
        GROUP BY bucket
        ORDER BY MIN(identity_percent)
    """)
    for r in c.fetchall():
        print(f"    {r[0]:10s}: {r[1]:4d} pairs (avg {r[2]}%)")

    print(f"\n[4/4] Top species by average within-species identity:")
    c.execute("""
        SELECT virus_species, COUNT(*) as pair_count,
               ROUND(AVG(identity_percent), 1) as avg_id,
               ROUND(MIN(identity_percent), 1) as min_id,
               ROUND(MAX(identity_percent), 1) as max_id
        FROM genome_pairwise_identity
        GROUP BY virus_species
        HAVING COUNT(*) >= 2
        ORDER BY avg_id DESC
        LIMIT 15
    """)
    for r in c.fetchall():
        print(f"    {r[0][:35]:35s}: {r[1]:3d} pairs  avg={r[2]:5.1f}%  range=[{r[3]:.1f}%-{r[4]:.1f}%]")

    conn.close()
    print("\n" + "=" * 60)
    print("Done! Genome identity matrix built.")
    print("=" * 60)


if __name__ == "__main__":
    main()
