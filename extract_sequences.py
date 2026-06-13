"""
Extract sequences from GenBank raw file to FASTA format,
and add sequence info to database.
"""

from Bio import SeqIO
from Bio.Seq import UndefinedSequenceError
from pathlib import Path
import sqlite3

GB_FILE = Path(r'F:\甲壳动物数据库\ncbi_metadata\crustacean_virus_raw.gb')
DB_PATH = Path(r'F:\甲壳动物数据库\crustacean_virus_core.db')
FASTA_DIR = Path(r'F:\甲壳动物数据库\sequences')
FASTA_ALL = Path(r'F:\甲壳动物数据库\sequences\all_sequences.fasta')

def extract_and_save():
    FASTA_DIR.mkdir(exist_ok=True)

    # Extract sequences
    print("Extracting sequences from GenBank file...")
    total = 0
    skipped = 0
    seq_stats = []

    with open(FASTA_ALL, 'w') as combined_handle:
        for rec in SeqIO.parse(str(GB_FILE), 'genbank'):
            acc = rec.id
            mol_type = rec.annotations.get('molecule_type', 'unknown')
            desc = rec.description

            try:
                seq = str(rec.seq)
            except UndefinedSequenceError:
                skipped += 1
                print(f"  Skipping undefined sequence: {acc}")
                continue

            if not seq or set(seq.upper()) <= {"N"}:
                skipped += 1
                print(f"  Skipping empty/ambiguous sequence: {acc}")
                continue

            # Write individual FASTA
            individual_file = FASTA_DIR / f"{acc}.fasta"
            with open(individual_file, 'w') as f:
                f.write(f">{acc} {desc}\n")
                # Wrap at 80 chars
                for i in range(0, len(seq), 80):
                    f.write(seq[i:i+80] + '\n')

            combined_handle.write(f">{acc} {desc}\n")
            for i in range(0, len(seq), 80):
                combined_handle.write(seq[i:i+80] + '\n')

            seq_stats.append((acc, len(seq), mol_type))
            total += 1
            if total % 500 == 0:
                print(f"  Processed {total} records...")

    print(f"\nExtracted {total} sequences.")
    print(f"Skipped {skipped} records with undefined or unusable sequence content.")
    print(f"Individual files: {FASTA_DIR}")
    print(f"Combined FASTA: {FASTA_ALL} ({FASTA_ALL.stat().st_size / 1024 / 1024:.1f} MB)")
    
    # Update database with sequence info
    print("\nUpdating database with sequence metadata...")
    conn = sqlite3.connect(str(DB_PATH))
    c = conn.cursor()
    
    # Add columns if not exist
    try:
        c.execute("ALTER TABLE viral_isolates ADD COLUMN sequence_length INTEGER")
    except sqlite3.OperationalError:
        pass
    try:
        c.execute("ALTER TABLE viral_isolates ADD COLUMN molecule_type VARCHAR(20)")
    except sqlite3.OperationalError:
        pass
    try:
        c.execute("ALTER TABLE viral_isolates ADD COLUMN has_sequence INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass
    
    # Update records
    updated = 0
    for acc, seq_len, mol_type in seq_stats:
        c.execute("""
            UPDATE viral_isolates 
            SET sequence_length = ?, molecule_type = ?, has_sequence = 1
            WHERE accession = ?
        """, (seq_len, mol_type, acc))
        if c.rowcount > 0:
            updated += 1
    
    conn.commit()
    conn.close()
    print(f"Updated {updated} records in database.")
    
    return total

if __name__ == "__main__":
    extract_and_save()
