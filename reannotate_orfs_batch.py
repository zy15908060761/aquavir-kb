"""
Batch-mode ORF re-annotation: processes N isolates per run and commits immediately.
Skips host_genome, non_target, and sequences >500kb.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from Bio import SeqIO
from Bio.Seq import Seq

DB_PATH = Path(r"F:\甲壳动物数据库\crustacean_virus_core.db")
SEQ_DIR = Path(r"F:\甲壳动物数据库\sequences")
BATCH_SIZE = 100
MAX_GENOME_LENGTH = 500_000

STOP_CODONS = {"TAA", "TAG", "TGA"}
MIN_AA_LENGTH = 50

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
    aa = []
    for i in range(0, len(dna) - 2, 3):
        aa.append(_CODON_TABLE.get(dna[i:i+3], 'X'))
    return ''.join(aa)


def find_orfs(seq: str) -> list[dict]:
    seq = seq.upper().replace("U", "T")
    all_orfs = []
    n = len(seq)

    # Forward
    for frame in range(3):
        i = frame
        while i + 2 < n:
            if seq[i:i+3] == "ATG":
                j = i + 3
                found = False
                while j + 2 < n:
                    if seq[j:j+3] in STOP_CODONS:
                        aa_len = (j + 3 - i) // 3
                        if aa_len >= MIN_AA_LENGTH:
                            dna = seq[i:j+3]
                            all_orfs.append({"s": i, "e": j+3, "st": 1, "fr": frame,
                                             "aa": aa_len, "dna": dna, "aa_seq": fast_translate(dna)})
                        i = j + 3
                        found = True
                        break
                    j += 3
                if not found:
                    dna = seq[i:]
                    aa_len = len(dna) // 3
                    if aa_len >= MIN_AA_LENGTH:
                        all_orfs.append({"s": i, "e": n, "st": 1, "fr": frame,
                                         "aa": aa_len, "dna": dna, "aa_seq": fast_translate(dna), "inc": True})
                    i = j
            else:
                i += 3

    # Reverse
    rev = str(Seq(seq).reverse_complement())
    for frame in range(3):
        i = frame
        while i + 2 < n:
            if rev[i:i+3] == "ATG":
                j = i + 3
                found = False
                while j + 2 < n:
                    if rev[j:j+3] in STOP_CODONS:
                        aa_len = (j + 3 - i) // 3
                        if aa_len >= MIN_AA_LENGTH:
                            dna = rev[i:j+3]
                            orig_s = n - (j + 3)
                            orig_e = n - i
                            all_orfs.append({"s": orig_s, "e": orig_e, "st": -1, "fr": 2-frame,
                                             "aa": aa_len, "dna": dna, "aa_seq": fast_translate(dna)})
                        i = j + 3
                        found = True
                        break
                    j += 3
                if not found:
                    dna = rev[i:]
                    aa_len = len(dna) // 3
                    if aa_len >= MIN_AA_LENGTH:
                        orig_s = 0
                        orig_e = n - i
                        all_orfs.append({"s": orig_s, "e": orig_e, "st": -1, "fr": 2-frame,
                                         "aa": aa_len, "dna": dna, "aa_seq": fast_translate(dna), "inc": True})
                    i = j
            else:
                i += 3

    # Filter nested
    all_orfs.sort(key=lambda o: (o["s"], -o["aa"]))
    filtered = []
    for o in all_orfs:
        nested = False
        for f in filtered:
            if o["st"] == f["st"]:
                if o["s"] >= f["s"] and o["e"] <= f["e"]:
                    nested = True
                    break
                if not (o["e"] <= f["s"] or o["s"] >= f["e"]) and o["aa"] < f["aa"]:
                    nested = True
                    break
        if not nested:
            filtered.append(o)

    filtered.sort(key=lambda o: (o["s"], o["st"]))
    for idx, o in enumerate(filtered, 1):
        o["id"] = idx
        o["tag"] = f"ORF{idx:03d}{'F' if o['st']==1 else 'R'}"
    return filtered


def main() -> None:
    conn = sqlite3.connect(str(DB_PATH), timeout=30)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    c.execute("""
        SELECT v.isolate_id, v.accession, v.genome_length
        FROM viral_isolates v
        JOIN virus_master vm ON v.master_id = vm.master_id
        WHERE v.has_sequence = 1
          AND v.isolate_id NOT IN (SELECT isolate_id FROM reannotation_stats)
          AND vm.entry_type NOT IN ('host_genome', 'non_target')
          AND (v.genome_length IS NULL OR v.genome_length <= ?)
        ORDER BY v.isolate_id LIMIT ?
    """, (MAX_GENOME_LENGTH, BATCH_SIZE))
    batch = c.fetchall()

    if not batch:
        print("All virus isolates already processed!")
        c.execute("SELECT COUNT(*) FROM reannotation_stats")
        print(f"Total processed: {c.fetchone()[0]}")
        c.execute("SELECT COUNT(*) FROM reannotated_orfs")
        print(f"Total ORFs: {c.fetchone()[0]}")
        conn.close()
        return

    print(f"Processing batch of {len(batch)} virus isolates...")
    total_orfs = 0

    for iso in batch:
        iid, acc = iso["isolate_id"], iso["accession"]
        sf = SEQ_DIR / f"{acc}.fasta"
        if not sf.exists():
            sf = SEQ_DIR / f"{acc.split('.')[0]}.fasta"
        if not sf.exists():
            continue

        try:
            rec = next(SeqIO.parse(str(sf), "fasta"))
            seq = str(rec.seq)
        except Exception:
            continue

        orfs = find_orfs(seq)
        c.execute("SELECT COUNT(*) FROM viral_proteins WHERE isolate_id = ?", (iid,))
        orig = c.fetchone()[0]

        for o in orfs:
            c.execute("""
                INSERT INTO reannotated_orfs
                (isolate_id, orf_number, locus_tag, start_pos, end_pos, strand, frame,
                 aa_length, dna_sequence, aa_sequence, is_incomplete, note)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            """, (iid, o["id"], o["tag"], o["s"], o["e"], o["st"], o["fr"],
                  o["aa"], o["dna"], o["aa_seq"], 1 if o.get("inc") else 0,
                  "incomplete" if o.get("inc") else None))

        covered = len({p for o in orfs for p in range(o["s"], o["e"])})
        cov = covered / len(seq) * 100 if seq else 0
        avg = sum(o["aa"] for o in orfs) / len(orfs) if orfs else 0

        c.execute("""
            INSERT INTO reannotation_stats
            (isolate_id, original_orf_count, reannotated_orf_count,
             reannotated_coverage_percent, avg_orf_length)
            VALUES (?,?,?,?,?)
        """, (iid, orig, len(orfs), round(cov, 1), round(avg, 1)))
        total_orfs += len(orfs)

    conn.commit()
    c.execute("SELECT COUNT(*) FROM reannotation_stats")
    total_proc = c.fetchone()[0]
    conn.close()
    print(f"Done! Added {total_orfs} ORFs. Total processed isolates: {total_proc}")


if __name__ == "__main__":
    main()
