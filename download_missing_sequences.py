"""
Download missing FASTA sequences from NCBI for isolates without local sequence files.
Uses NCBI efetch API with rate limiting.
"""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path

import requests

DB_PATH = Path(r"F:\甲壳动物数据库\crustacean_virus_core.db")
SEQ_DIR = Path(r"F:\甲壳动物数据库\sequences")
EFETCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
BATCH_SIZE = 100
# NCBI policy: max 3 requests/sec without API key; be conservative
REQUEST_DELAY = 0.4


def fetch_fasta_batch(accessions: list[str]) -> dict[str, str] | None:
    """Fetch FASTA for a batch of accessions from NCBI."""
    ids = ",".join(accessions)
    try:
        resp = requests.get(
            EFETCH_URL,
            params={
                "db": "nuccore",
                "id": ids,
                "rettype": "fasta",
                "retmode": "text",
            },
            timeout=120,
        )
        resp.raise_for_status()
    except Exception as e:
        print(f"    [Error] efetch failed: {e}")
        return None

    # Parse multi-FASTA response
    sequences: dict[str, str] = {}
    current_acc = None
    current_lines: list[str] = []

    for line in resp.text.splitlines():
        line = line.strip()
        if line.startswith(">"):
            if current_acc and current_lines:
                sequences[current_acc] = "\n".join(current_lines)
            # Parse accession from header like >PQ724921.1 ...
            header = line[1:].split()[0]
            current_acc = header
            current_lines = []
        else:
            if current_acc is not None:
                current_lines.append(line)

    if current_acc and current_lines:
        sequences[current_acc] = "\n".join(current_lines)

    return sequences


def calc_gc(seq: str) -> float:
    seq_upper = seq.upper()
    gc = seq_upper.count("G") + seq_upper.count("C")
    total = len(seq_upper)
    return round(gc / total * 100, 2) if total > 0 else 0.0


def download_missing() -> None:
    print("=" * 60)
    print("Downloading Missing FASTA Sequences from NCBI")
    print("=" * 60)

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    c.execute(
        """
        SELECT isolate_id, accession, genome_length
        FROM viral_isolates
        WHERE has_sequence = 0
        ORDER BY isolate_id
        """
    )
    rows = c.fetchall()
    print(f"\n[1/3] Found {len(rows)} isolates without sequence files")

    if not rows:
        print("No missing sequences. Exiting.")
        conn.close()
        return

    total_batches = (len(rows) + BATCH_SIZE - 1) // BATCH_SIZE
    downloaded = 0
    failed_batches = 0
    updated_db = 0

    for batch_idx in range(total_batches):
        start = batch_idx * BATCH_SIZE
        end = start + BATCH_SIZE
        batch_rows = rows[start:end]
        batch_accs = [r["accession"] for r in batch_rows]

        print(f"\n  Batch {batch_idx + 1}/{total_batches} ({len(batch_accs)} accessions)...")
        sequences = fetch_fasta_batch(batch_accs)
        time.sleep(REQUEST_DELAY)

        if sequences is None:
            failed_batches += 1
            continue

        for row in batch_rows:
            acc = row["accession"]
            seq = sequences.get(acc)
            if not seq:
                # Try base accession (without version)
                base = acc.split(".")[0]
                for key, val in sequences.items():
                    if key.split(".")[0] == base:
                        seq = val
                        break

            if not seq:
                continue

            # Save FASTA file
            fasta_path = SEQ_DIR / f"{acc}.fasta"
            header = f">{acc}"
            fasta_path.write_text(f"{header}\n{seq}\n", encoding="utf-8")
            downloaded += 1

            # Update DB
            seq_clean = seq.replace("\n", "").replace(" ", "")
            gc = calc_gc(seq_clean)
            length = len(seq_clean)

            c.execute(
                """
                UPDATE viral_isolates
                SET has_sequence = 1,
                    genome_length = ?,
                    gc_content = ?
                WHERE isolate_id = ?
                """,
                (length, gc, row["isolate_id"]),
            )
            updated_db += 1

        if batch_idx % 5 == 4:
            conn.commit()
            print(f"    Progress: {downloaded} downloaded, {updated_db} DB updated")

    conn.commit()

    print(f"\n[2/3] Download summary:")
    print(f"    FASTA files downloaded: {downloaded}")
    print(f"    DB records updated: {updated_db}")
    print(f"    Failed batches: {failed_batches}")

    # Final verification
    print(f"\n[3/3] Final verification:")
    c.execute("SELECT COUNT(*) FROM viral_isolates")
    total = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM viral_isolates WHERE has_sequence = 1")
    has_seq = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM viral_isolates WHERE gc_content IS NOT NULL")
    has_gc = c.fetchone()[0]
    print(f"    Total: {total}")
    print(f"    With sequence: {has_seq}/{total} ({has_seq/total*100:.1f}%)")
    print(f"    With GC: {has_gc}/{total} ({has_gc/total*100:.1f}%)")

    conn.close()
    print("\n" + "=" * 60)
    print("Done! Missing sequence download complete.")
    print("=" * 60)


if __name__ == "__main__":
    download_missing()
