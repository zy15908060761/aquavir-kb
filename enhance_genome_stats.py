"""
Calculate missing GC content and other genome statistics from FASTA sequences.
Updates viral_isolates table with computed values.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

DB_PATH = Path(r"F:\甲壳动物数据库\crustacean_virus_core.db")
SEQ_DIR = Path(r"F:\甲壳动物数据库\sequences")


def parse_fasta(path: Path) -> str:
    """Return concatenated sequence string from FASTA file."""
    lines = path.read_text(encoding="utf-8").splitlines()
    seq_parts = []
    for line in lines:
        line = line.strip()
        if not line or line.startswith(">"):
            continue
        seq_parts.append(line)
    return "".join(seq_parts)


def calc_gc_and_stats(seq: str) -> dict | None:
    """Calculate GC%, AT%, length, N count from raw sequence string."""
    if not seq:
        return None
    seq_upper = seq.upper()
    total = len(seq_upper)
    gc = seq_upper.count("G") + seq_upper.count("C")
    at = seq_upper.count("A") + seq_upper.count("T") + seq_upper.count("U")
    n_count = seq_upper.count("N")
    other = total - gc - at - n_count

    gc_content = (gc / total * 100.0) if total > 0 else None
    at_content = (at / total * 100.0) if total > 0 else None
    n_percent = (n_count / total * 100.0) if total > 0 else None

    return {
        "length": total,
        "gc_content": round(gc_content, 2) if gc_content is not None else None,
        "at_content": round(at_content, 2) if at_content is not None else None,
        "n_count": n_count,
        "n_percent": round(n_percent, 2) if n_percent is not None else None,
        "other_bases": other,
    }


def enhance_genome_stats() -> None:
    print("=" * 60)
    print("Enhancing Genome Statistics (GC content from FASTA)")
    print("=" * 60)

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    # Find isolates missing gc_content or genome_length
    c.execute(
        """
        SELECT isolate_id, accession, genome_length, gc_content
        FROM viral_isolates
        WHERE (gc_content IS NULL OR genome_length IS NULL)
        ORDER BY isolate_id
        """
    )
    rows = c.fetchall()
    print(f"\n[1/3] Found {len(rows)} isolates missing genome stats")

    updated = 0
    skipped_no_file = 0
    skipped_empty_seq = 0
    length_mismatch = 0

    for row in rows:
        acc = row["accession"]
        seq_file = SEQ_DIR / f"{acc}.fasta"
        if not seq_file.exists():
            # Try without version suffix
            base = acc.split(".")[0]
            seq_file = SEQ_DIR / f"{base}.fasta"
            if not seq_file.exists():
                skipped_no_file += 1
                continue

        seq = parse_fasta(seq_file)
        if not seq:
            skipped_empty_seq += 1
            continue

        stats = calc_gc_and_stats(seq)
        if not stats:
            skipped_empty_seq += 1
            continue

        # Warn if declared length differs from actual
        declared_len = row["genome_length"]
        actual_len = stats["length"]
        if declared_len and declared_len != actual_len:
            length_mismatch += 1

        c.execute(
            """
            UPDATE viral_isolates
            SET genome_length = ?,
                gc_content = ?
            WHERE isolate_id = ?
            """,
            (actual_len, stats["gc_content"], row["isolate_id"]),
        )
        updated += 1

    conn.commit()

    print(f"    Updated: {updated}")
    print(f"    No FASTA file: {skipped_no_file}")
    print(f"    Empty sequence: {skipped_empty_seq}")
    print(f"    Length mismatches (minor): {length_mismatch}")

    # Verification
    print("\n[2/3] Verification statistics:")
    c.execute("SELECT COUNT(*) FROM viral_isolates")
    total = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM viral_isolates WHERE genome_length IS NOT NULL")
    has_len = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM viral_isolates WHERE gc_content IS NOT NULL")
    has_gc = c.fetchone()[0]
    print(f"    Total isolates: {total}")
    print(f"    With genome_length: {has_len}/{total} ({has_len/total*100:.1f}%)")
    print(f"    With gc_content: {has_gc}/{total} ({has_gc/total*100:.1f}%)")

    # Distribution of GC content by family
    print("\n[3/3] GC content distribution by virus family (top 10):")
    c.execute(
        """
        SELECT taxon_family,
               COUNT(*) as cnt,
               ROUND(AVG(gc_content), 1) as avg_gc,
               ROUND(MIN(gc_content), 1) as min_gc,
               ROUND(MAX(gc_content), 1) as max_gc
        FROM viral_isolates
        WHERE gc_content IS NOT NULL AND taxon_family IS NOT NULL AND taxon_family != ''
        GROUP BY taxon_family
        ORDER BY cnt DESC
        LIMIT 10
        """
    )
    for r in c.fetchall():
        print(f"    {r[0] or 'Unknown':35s}: n={r[1]:4d}  avg={r[2]:5.1f}%  range=[{r[3]:.1f}%-{r[4]:.1f}%]")

    conn.close()
    print("\n" + "=" * 60)
    print("Done! Genome statistics enhancement complete.")
    print("=" * 60)


if __name__ == "__main__":
    enhance_genome_stats()
