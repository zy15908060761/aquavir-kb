"""
Resume ORF re-annotation for isolates not yet in reannotation_stats.
Optimized version with faster translation.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from Bio import SeqIO
from Bio.Seq import Seq

DB_PATH = Path(r"F:\甲壳动物数据库\crustacean_virus_core.db")
SEQ_DIR = Path(r"F:\甲壳动物数据库\sequences")

STOP_CODONS = {"TAA", "TAG", "TGA"}
MIN_AA_LENGTH = 50

# Simple codon table for fast translation (standard genetic code)
_CODON_TABLE = {
    'TTT':'F','TTC':'F','TTA':'L','TTG':'L','CTT':'L','CTC':'L','CTA':'L','CTG':'L',
    'ATT':'I','ATC':'I','ATA':'I','ATG':'M','GTT':'V','GTC':'V','GTA':'V','GTG':'V',
    'TCT':'S','TCC':'S','TCA':'S','TCG':'S','CCT':'P','CCC':'P','CCA':'P','CCG':'P',
    'ACT':'T','ACC':'T','ACA':'T','ACG':'T','GCT':'A','GCC':'A','GCA':'A','GCG':'A',
    'TAT':'Y','TAC':'Y','TAA':'*','TAG':'*','CAT':'H','CAC':'H','CAA':'Q','CAG':'Q',
    'AAT':'N','AAC':'N','AAA':'K','AAG':'K','GAT':'D','GAC':'D','GAA':'E','GAG':'E',
    'TGT':'C','TGC':'C','TGA':'*','TGG':'W','CGT':'R','CGC':'R','CGA':'R','CGG':'R',
    'AGT':'S','AGC':'S','AGA':'R','AGG':'R','GGT':'G','GGC':'G','GGA':'G','GGG':'G',
}


def fast_translate(dna: str) -> str:
    """Fast DNA-to-protein translation using lookup table."""
    aa = []
    for i in range(0, len(dna) - 2, 3):
        codon = dna[i:i+3]
        aa.append(_CODON_TABLE.get(codon, 'X'))
    return ''.join(aa)


def find_orfs_in_frame(seq: str, frame: int, strand: int) -> list[dict]:
    orfs = []
    n = len(seq)
    i = frame
    while i + 2 < n:
        if seq[i:i+3] == "ATG":
            j = i + 3
            found_stop = False
            while j + 2 < n:
                if seq[j:j+3] in STOP_CODONS:
                    dna_len = j + 3 - i
                    aa_len = dna_len // 3
                    if aa_len >= MIN_AA_LENGTH:
                        dna_seq = seq[i:j+3]
                        aa_seq = fast_translate(dna_seq)
                        orfs.append({
                            "start": i, "end": j + 3, "strand": strand,
                            "frame": frame if strand == 1 else (2 - frame),
                            "aa_length": aa_len,
                            "dna_seq": dna_seq,
                            "aa_seq": aa_seq,
                        })
                    i = j + 3
                    found_stop = True
                    break
                j += 3
            if not found_stop:
                dna_seq = seq[i:]
                aa_len = len(dna_seq) // 3
                if aa_len >= MIN_AA_LENGTH:
                    aa_seq = fast_translate(dna_seq)
                    orfs.append({
                        "start": i, "end": n, "strand": strand,
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
    seq = seq.upper().replace("U", "T")
    all_orfs = []

    for frame in range(3):
        all_orfs.extend(find_orfs_in_frame(seq, frame, 1))

    rev_seq = str(Seq(seq).reverse_complement())
    n = len(seq)
    for frame in range(3):
        orfs = find_orfs_in_frame(rev_seq, frame, -1)
        for o in orfs:
            o["start"] = n - o["end"]
            o["end"] = n - o["start"]
        all_orfs.extend(orfs)

    # Filter nested
    all_orfs.sort(key=lambda o: (o["start"], -o["aa_length"]))
    filtered = []
    for o in all_orfs:
        is_nested = False
        for f in filtered:
            if o["strand"] == f["strand"]:
                if o["start"] >= f["start"] and o["end"] <= f["end"]:
                    is_nested = True
                    break
                if not (o["end"] <= f["start"] or o["start"] >= f["end"]) and o["aa_length"] < f["aa_length"]:
                    is_nested = True
                    break
        if not is_nested:
            filtered.append(o)

    filtered.sort(key=lambda o: (o["start"], o["strand"]))
    for idx, o in enumerate(filtered, 1):
        o["orf_id"] = idx
        o["locus_tag"] = f"ORF{idx:03d}{'F' if o['strand'] == 1 else 'R'}"
    return filtered


def get_original_orf_count(conn, isolate_id: int) -> int:
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM viral_proteins WHERE isolate_id = ?", (isolate_id,))
    return c.fetchone()[0]


def main() -> None:
    print("=" * 60)
    print("Resuming ORF Re-annotation Pipeline")
    print("=" * 60)

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    # Find isolates not yet in reannotation_stats
    c.execute("""
        SELECT isolate_id, accession, genome_length
        FROM viral_isolates
        WHERE has_sequence = 1
          AND isolate_id NOT IN (SELECT isolate_id FROM reannotation_stats)
        ORDER BY isolate_id
    """)
    isolates = c.fetchall()
    print(f"\n[1/3] {len(isolates)} isolates remaining to process")

    if not isolates:
        print("Nothing to do. All isolates already processed.")
        conn.close()
        return

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

        for o in orfs:
            c.execute("""
                INSERT INTO reannotated_orfs
                (isolate_id, orf_number, locus_tag, start_pos, end_pos,
                 strand, frame, aa_length, dna_sequence, aa_sequence,
                 is_incomplete, note)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                iid, o["orf_id"], o["locus_tag"], o["start"], o["end"],
                o["strand"], o["frame"], o["aa_length"],
                o.get("dna_seq", ""), o.get("aa_seq", ""),
                1 if o.get("incomplete") else 0,
                "incomplete_orf" if o.get("incomplete") else None,
            ))

        covered = set()
        for o in orfs:
            covered.update(range(o["start"], o["end"]))
        coverage = len(covered) / len(seq) * 100.0 if seq else 0
        avg_len = sum(o["aa_length"] for o in orfs) / len(orfs) if orfs else 0

        c.execute("""
            INSERT INTO reannotation_stats
            (isolate_id, original_orf_count, reannotated_orf_count,
             original_coverage_percent, reannotated_coverage_percent, avg_orf_length)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (iid, original_count, len(orfs), None, round(coverage, 1), round(avg_len, 1)))

        total_orfs += len(orfs)
        processed += 1

        if processed % 200 == 0:
            conn.commit()
            print(f"    Processed {processed}/{len(isolates)}, {total_orfs} ORFs added...")

    conn.commit()
    print(f"\n[2/4] Resume complete: {processed} isolates, {total_orfs} ORFs, {skipped} skipped")

    # Final stats
    print("\n[3/4] Final comparison stats:")
    c.execute("""
        SELECT SUM(original_orf_count) as orig, SUM(reannotated_orf_count) as reanno,
               ROUND(AVG(reannotated_orf_count),1) as avg_orf,
               ROUND(AVG(reannotated_coverage_percent),1) as avg_cov
        FROM reannotation_stats
    """)
    r = c.fetchone()
    print(f"    Total GenBank ORFs: {r['orig'] or 0}")
    print(f"    Total reannotated ORFs: {r['reanno'] or 0}")
    print(f"    Avg ORFs per isolate: {r['avg_orf'] or 0}")
    print(f"    Avg genome coverage: {r['avg_cov'] or 0}%")

    print("\n[4/4] Top 10 by ORF count increase:")
    c.execute("""
        SELECT vi.accession, vi.virus_name, rs.original_orf_count, rs.reannotated_orf_count
        FROM reannotation_stats rs
        JOIN viral_isolates vi ON rs.isolate_id = vi.isolate_id
        WHERE rs.original_orf_count > 0
        ORDER BY (rs.reannotated_orf_count - rs.original_orf_count) DESC
        LIMIT 10
    """)
    for r in c.fetchall():
        diff = r["reannotated_orf_count"] - (r["original_orf_count"] or 0)
        print(f"    {r['accession']:15s} {r['virus_name'][:35]:35s}: {r['original_orf_count'] or 0:3d} -> {r['reannotated_orf_count']:3d} (+{diff})")

    conn.close()
    print("\n" + "=" * 60)
    print("Done! ORF re-annotation fully complete.")
    print("=" * 60)


if __name__ == "__main__":
    main()
