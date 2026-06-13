"""
Standardized genome re-annotation pipeline for crustacean viruses.

Inspired by IVCDB methodology:
  (i) ORFs begin with ATG and end with TAA/TAG/TGA, contain >= 50 aa
  (ii) Both forward and reverse nested ORFs are excluded
  (iii) For overlapping co-directional ORFs, the longer ORF is retained;
        overlapping ORFs of equal length are both preserved.

Results stored in reannotated_orfs table.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from collections import defaultdict

from Bio import SeqIO
from Bio.Seq import Seq

DB_PATH = Path(r"F:\甲壳动物数据库\crustacean_virus_core.db")
SEQ_DIR = Path(r"F:\甲壳动物数据库\sequences")

STOP_CODONS = {"TAA", "TAG", "TGA"}
MIN_AA_LENGTH = 50


def find_orfs_in_frame(seq: str, frame: int, strand: int) -> list[dict]:
    """Find all ORFs starting with ATG in a single reading frame.

    Returns list of dicts with: start, end, strand, frame, aa_length, dna_seq, aa_seq
    Coordinates are 0-based, start inclusive, end exclusive.
    """
    orfs = []
    n = len(seq)
    i = frame
    while i + 2 < n:
        codon = seq[i:i+3]
        if codon == "ATG":
            # Look for stop codon
            j = i + 3
            while j + 2 < n:
                stop_codon = seq[j:j+3]
                if stop_codon in STOP_CODONS:
                    dna_seq = seq[i:j+3]
                    aa_len = len(dna_seq) // 3
                    if aa_len >= MIN_AA_LENGTH:
                        from Bio.Seq import Seq as SeqObj
                        aa_seq = str(SeqObj(dna_seq).translate(to_stop=True))
                        orfs.append({
                            "start": i,
                            "end": j + 3,
                            "strand": strand,
                            "frame": frame if strand == 1 else (2 - frame),
                            "aa_length": aa_len,
                            "dna_seq": dna_seq,
                            "aa_seq": aa_seq,
                        })
                    i = j + 3  # Continue searching after stop
                    break
                j += 3
            else:
                # No stop codon found; treat as incomplete ORF
                dna_seq = seq[i:]
                aa_len = len(dna_seq) // 3
                if aa_len >= MIN_AA_LENGTH:
                    from Bio.Seq import Seq as SeqObj
                    aa_seq = str(SeqObj(dna_seq).translate(to_stop=True))
                    orfs.append({
                        "start": i,
                        "end": n,
                        "strand": strand,
                        "frame": frame if strand == 1 else (2 - frame),
                        "aa_length": aa_len,
                        "dna_seq": dna_seq,
                        "aa_seq": aa_seq,
                        "incomplete": True,
                    })
                i = j
        else:
            i += 3
    return orfs


def find_all_orfs(seq: str) -> list[dict]:
    """Find ORFs in all 6 reading frames, then filter nested and overlapping."""
    seq = seq.upper().replace("U", "T")
    all_orfs = []

    # Forward strands (0, 1, 2)
    for frame in range(3):
        orfs = find_orfs_in_frame(seq, frame, 1)
        all_orfs.extend(orfs)

    # Reverse complement strands
    rev_seq = str(Seq(seq).reverse_complement())
    for frame in range(3):
        orfs = find_orfs_in_frame(rev_seq, frame, -1)
        # Convert coordinates back to original sequence
        n = len(seq)
        for o in orfs:
            orig_start = n - o["end"]
            orig_end = n - o["start"]
            o["start"] = orig_start
            o["end"] = orig_end
        all_orfs.extend(orfs)

    # Sort by start, then by length descending
    all_orfs.sort(key=lambda o: (o["start"], -o["aa_length"]))

    # Filter nested ORFs: if one ORF is completely contained within another,
    # remove the smaller one.
    filtered = []
    for o in all_orfs:
        is_nested = False
        for f in filtered:
            if o["strand"] == f["strand"] and o["start"] >= f["start"] and o["end"] <= f["end"]:
                # Nested ORF found
                is_nested = True
                break
            # Overlapping co-directional ORFs: if same strand and overlapping,
            # keep longer; if equal length, keep both
            if o["strand"] == f["strand"] and not (o["end"] <= f["start"] or o["start"] >= f["end"]):
                if o["aa_length"] < f["aa_length"]:
                    is_nested = True
                    break
                # If equal length, both are kept (do nothing)
        if not is_nested:
            filtered.append(o)

    # Renumber ORFs by genomic position
    filtered.sort(key=lambda o: (o["start"], o["strand"]))
    for idx, o in enumerate(filtered, 1):
        o["orf_id"] = idx
        o["locus_tag"] = f"ORF{idx:03d}{'F' if o['strand'] == 1 else 'R'}"

    return filtered


def create_reannotation_tables(conn: sqlite3.Connection) -> None:
    c = conn.cursor()
    c.executescript("""
    DROP TABLE IF EXISTS reannotated_orfs;
    DROP TABLE IF EXISTS reannotation_stats;

    CREATE TABLE reannotated_orfs (
        reanno_id INTEGER PRIMARY KEY AUTOINCREMENT,
        isolate_id INTEGER NOT NULL,
        orf_number INTEGER NOT NULL,
        locus_tag VARCHAR(20),
        start_pos INTEGER NOT NULL,
        end_pos INTEGER NOT NULL,
        strand INTEGER NOT NULL,
        frame INTEGER NOT NULL,
        aa_length INTEGER NOT NULL,
        dna_sequence TEXT,
        aa_sequence TEXT,
        is_incomplete INTEGER DEFAULT 0,
        note TEXT,
        FOREIGN KEY (isolate_id) REFERENCES viral_isolates(isolate_id)
    );

    CREATE TABLE reannotation_stats (
        isolate_id INTEGER PRIMARY KEY,
        original_orf_count INTEGER,
        reannotated_orf_count INTEGER,
        original_coverage_percent REAL,
        reannotated_coverage_percent REAL,
        avg_orf_length REAL,
        FOREIGN KEY (isolate_id) REFERENCES viral_isolates(isolate_id)
    );

    CREATE INDEX idx_reanno_isolate ON reannotated_orfs(isolate_id);
    CREATE INDEX idx_reanno_pos ON reannotated_orfs(start_pos, end_pos);
    """)
    conn.commit()
    print("[DB] Created reannotated_orfs and reannotation_stats tables")


def get_original_orf_count(conn: sqlite3.Connection, isolate_id: int) -> int:
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM viral_proteins WHERE isolate_id = ?", (isolate_id,))
    return c.fetchone()[0]


def reannotate_all() -> None:
    print("=" * 60)
    print("Standardized Genome Re-annotation Pipeline")
    print("=" * 60)

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    create_reannotation_tables(conn)

    # Get isolates with sequence files
    c.execute(
        """
        SELECT isolate_id, accession, genome_length
        FROM viral_isolates
        WHERE has_sequence = 1
        ORDER BY isolate_id
        """
    )
    isolates = c.fetchall()
    print(f"\n[1/4] Found {len(isolates)} isolates with sequence files")

    total_orfs = 0
    processed = 0
    skipped = 0

    for iso in isolates:
        iid = iso["isolate_id"]
        acc = iso["accession"]
        seq_file = SEQ_DIR / f"{acc}.fasta"
        if not seq_file.exists():
            base = acc.split(".")[0]
            seq_file = SEQ_DIR / f"{base}.fasta"
            if not seq_file.exists():
                skipped += 1
                continue

        try:
            rec = next(SeqIO.parse(str(seq_file), "fasta"))
            seq = str(rec.seq)
        except Exception:
            skipped += 1
            continue

        orfs = find_all_orfs(seq)
        original_count = get_original_orf_count(conn, iid)

        # Insert ORFs
        for o in orfs:
            c.execute(
                """
                INSERT INTO reannotated_orfs
                (isolate_id, orf_number, locus_tag, start_pos, end_pos,
                 strand, frame, aa_length, dna_sequence, aa_sequence,
                 is_incomplete, note)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    iid, o["orf_id"], o["locus_tag"], o["start"], o["end"],
                    o["strand"], o["frame"], o["aa_length"],
                    o.get("dna_seq", ""), o.get("aa_seq", ""),
                    1 if o.get("incomplete") else 0,
                    "incomplete_orf" if o.get("incomplete") else None,
                ),
            )

        # Calculate coverage
        covered = set()
        for o in orfs:
            for pos in range(o["start"], o["end"]):
                covered.add(pos)
        coverage = len(covered) / len(seq) * 100.0 if seq else 0
        avg_len = sum(o["aa_length"] for o in orfs) / len(orfs) if orfs else 0

        c.execute(
            """
            INSERT INTO reannotation_stats
            (isolate_id, original_orf_count, reannotated_orf_count,
             original_coverage_percent, reannotated_coverage_percent, avg_orf_length)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (iid, original_count, len(orfs), None, round(coverage, 1), round(avg_len, 1)),
        )

        total_orfs += len(orfs)
        processed += 1

        if processed % 100 == 0:
            conn.commit()
            print(f"    Processed {processed}/{len(isolates)} isolates, {total_orfs} ORFs found...")

    conn.commit()

    print(f"\n[2/4] Re-annotation complete:")
    print(f"    Isolates processed: {processed}")
    print(f"    Isolates skipped: {skipped}")
    print(f"    Total reannotated ORFs: {total_orfs}")
    print(f"    Avg ORFs per isolate: {total_orfs/processed:.1f}" if processed > 0 else "    N/A")

    # Comparison stats
    print(f"\n[3/4] Comparison with original GenBank annotations:")
    c.execute("""
        SELECT 
            SUM(rs.original_orf_count) as orig_total,
            SUM(rs.reannotated_orf_count) as reanno_total,
            ROUND(AVG(rs.reannotated_orf_count), 1) as avg_reanno,
            ROUND(AVG(rs.reannotated_coverage_percent), 1) as avg_cov
        FROM reannotation_stats rs
    """)
    r = c.fetchone()
    print(f"    Original ORFs (GenBank): {r['orig_total'] or 0}")
    print(f"    Reannotated ORFs: {r['reanno_total'] or 0}")
    print(f"    Avg reannotated ORFs per isolate: {r['avg_reanno'] or 0}")
    print(f"    Avg genome coverage: {r['avg_cov'] or 0}%")

    # Top isolates by ORF count increase
    print(f"\n[4/4] Top 10 isolates with largest ORF count increase:")
    c.execute("""
        SELECT vi.accession, vi.virus_name,
               rs.original_orf_count, rs.reannotated_orf_count,
               rs.reannotated_coverage_percent
        FROM reannotation_stats rs
        JOIN viral_isolates vi ON rs.isolate_id = vi.isolate_id
        WHERE rs.original_orf_count > 0
        ORDER BY (rs.reannotated_orf_count - rs.original_orf_count) DESC
        LIMIT 10
    """)
    for r in c.fetchall():
        diff = r["reannotated_orf_count"] - (r["original_orf_count"] or 0)
        print(f"    {r['accession']:15s} {r['virus_name'][:40]:40s}: "
              f"GenBank={r['original_orf_count'] or 0:3d} -> Reanno={r['reannotated_orf_count']:3d} "
              f"(+{diff:3d}) cov={r['reannotated_coverage_percent']:.1f}%")

    conn.close()
    print("\n" + "=" * 60)
    print("Done! Genome re-annotation complete.")
    print("=" * 60)


if __name__ == "__main__":
    reannotate_all()
