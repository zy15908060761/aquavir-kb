#!/usr/bin/env python3
"""Rebuild BLAST databases for AquaVir-KB.

Exports:
  1. Protein FASTA  -> sequences/aa.fasta  (from viral_proteins.translation)
  2. Nucleotide FASTA -> sequences/nt.fasta (concatenated, header=accession)
  3. Syncs individual *.fasta for the download endpoint
Builds:
  makeblastdb -dbtype prot -in aa.fasta -out blastdb/aa
  makeblastdb -dbtype nucl -in nt.fasta -out blastdb/nt
Records:
  blastdb/VERSION (timestamp + counts)

Run on the host as the db owner:
  python3 /opt/aquavir-kb/rebuild_blast.py
"""
from __future__ import annotations

import sqlite3
import subprocess
import sys
import time
from pathlib import Path

DB_PATH = Path("/opt/aquavir-kb/deploy/data/crustacean_virus_core.db")
SEQUENCES_DIR = Path("/opt/aquavir-kb/deploy/data/sequences")
BLASTDB_DIR = Path("/opt/aquavir-kb/deploy/data/blastdb")
NT_SOURCE_DIR = Path("/opt/sequences")


def export_proteins() -> int:
    """Export viral_proteins.translation -> aa.fasta, header `>prot_<protein_id>`."""
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT vp.protein_id, vp.protein_accession, vp.protein_name,
               vp.translation, vi.accession AS isolate_acc,
               vm.canonical_name AS virus
        FROM viral_proteins vp
        LEFT JOIN viral_isolates vi ON vp.isolate_id = vi.isolate_id
        LEFT JOIN virus_master vm ON vi.master_id = vm.master_id
        WHERE vp.translation IS NOT NULL AND LENGTH(vp.translation) > 0
        """
    ).fetchall()
    conn.close()

    aa_path = SEQUENCES_DIR / "aa.fasta"
    count = 0
    with aa_path.open("w", encoding="utf-8", newline="\n") as f:
        for r in rows:
            seq = "".join(ch for ch in (r["translation"] or "").upper() if ch.isalpha() or ch == "*").replace("*", "")
            if len(seq) < 10:  # skip trivial fragments
                continue
            header = f">prot_{r['protein_id']} acc={r['protein_accession'] or '-'} isolate={r['isolate_acc'] or '-'} virus={r['virus'] or '-'}"
            f.write(header + "\n")
            for i in range(0, len(seq), 60):
                f.write(seq[i:i + 60] + "\n")
            count += 1
    return count


def _strip_ver(a: str) -> str:
    """Strip the accession version suffix (e.g. AB734057.1 -> AB734057)."""
    return a.rsplit(".", 1)[0] if "." in a else a


# Generated aggregates that live in SEQUENCES_DIR but must never be re-ingested.
_SKIP_FASTA = {"aa.fasta", "nt.fasta", "all_sequences.fasta"}


def _nt_source_files():
    """Every per-accession nucleotide FASTA we can see.

    Both the staging dir and the served sequences dir are scanned: imports have
    historically landed in only one of them, which silently dropped sequences
    from the BLAST index.
    """
    done = set()
    for src in (NT_SOURCE_DIR, SEQUENCES_DIR):
        for fa in sorted(src.glob("*.fasta")):
            if fa.name in _SKIP_FASTA or fa.name.startswith("unannotated_proteins"):
                continue
            if fa.name in done:
                continue
            done.add(fa.name)
            yield fa


def collect_nucleotides() -> int:
    """Concatenate nucleotide FASTA -> nt.fasta, keeping only accessions registered in
    nucleotide_records (excludes PDB/metagenomic non-nucleotide entries).
    Matching is version-insensitive (AB734057 == AB734057.1)."""
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    valid = set()
    for (a,) in conn.execute("SELECT accession FROM nucleotide_records"):
        valid.add(a)
        valid.add(_strip_ver(a))
    conn.close()

    nt_path = SEQUENCES_DIR / "nt.fasta"
    kept = 0
    skipped = 0
    seen = set()
    with nt_path.open("w", encoding="utf-8", newline="\n") as out:
        for fa in _nt_source_files():
            header = None
            seq_lines = []
            for line in fa.read_text(encoding="utf-8", errors="replace").splitlines():
                if line.startswith(">"):
                    if header is not None:
                        acc = header.split()[0]
                        key = _strip_ver(acc)
                        if key not in seen and (acc in valid or key in valid):
                            out.write(">" + acc + "\n" + "".join(seq_lines) + "\n")
                            kept += 1
                            seen.add(key)
                        else:
                            skipped += 1
                    header = line[1:].strip()
                    seq_lines = []
                elif line.strip():
                    seq_lines.append(line.strip())
            if header is not None:
                acc = header.split()[0]
                key = _strip_ver(acc)
                if key not in seen and (acc in valid or key in valid):
                    out.write(">" + acc + "\n" + "".join(seq_lines) + "\n")
                    kept += 1
                    seen.add(key)
                else:
                    skipped += 1
    print(f"  kept={kept} skipped={skipped}")
    return kept


def sync_individual_fasta() -> int:
    """Copy individual *.fasta into sequences/ for the download endpoint (skip existing)."""
    import shutil
    copied = 0
    for fa in NT_SOURCE_DIR.glob("*.fasta"):
        dst = SEQUENCES_DIR / fa.name
        if not dst.exists():
            shutil.copy2(fa, dst)
            copied += 1
    return copied


def build_db(fasta: Path, dbtype: str, out: Path, title: str) -> None:
    cmd = [
        "makeblastdb",
        "-in", str(fasta),
        "-dbtype", dbtype,
        "-out", str(out),
        "-title", title,
    ]
    print(f"[makeblastdb] {' '.join(cmd)}")
    subprocess.run(cmd, check=True)


def main() -> int:
    SEQUENCES_DIR.mkdir(parents=True, exist_ok=True)
    BLASTDB_DIR.mkdir(parents=True, exist_ok=True)

    print("=== exporting proteins ===")
    n_prot = export_proteins()
    print(f"  proteins: {n_prot}")

    print("=== collecting nucleotides ===")
    n_nt = collect_nucleotides()
    print(f"  nucleotides: {n_nt}")

    print("=== syncing individual fasta ===")
    n_sync = sync_individual_fasta()
    print(f"  newly synced: {n_sync}")

    print("=== building BLAST dbs ===")
    build_db(SEQUENCES_DIR / "aa.fasta", "prot", BLASTDB_DIR / "aa", "AquaVir-KB proteins")
    build_db(SEQUENCES_DIR / "nt.fasta", "nucl", BLASTDB_DIR / "nt", "AquaVir-KB nucleotides")

    version = f"built={time.strftime('%Y-%m-%d %H:%M:%S')} proteins={n_prot} nucleotides={n_nt}"
    (BLASTDB_DIR / "VERSION").write_text(version + "\n", encoding="utf-8")
    print(f"=== done: {version} ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
