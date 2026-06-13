#!/usr/bin/env python3
"""
Sync has_sequence flags with on-disk FASTA files (P1-5).

Part A (audit): Scan sequences/ directory, compare with has_sequence flags,
fix RDRP computational predictions, identify legitimately missing files.
Part B (download): Fetch missing FASTA from NCBI for real NCBI accessions.

Non-NCBI patterns (metagenomic contigs like k141_*, PDB-style like 8EUB_EC,
RDRP computational predictions) are skipped with explanation logged.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

from db_utils import DB_PATH, backup_database, db_connection, db_transaction

BASE_DIR = Path(__file__).resolve().parent
REPORTS_DIR = BASE_DIR / "reports"
SEQUENCES_DIR = BASE_DIR / "sequences"
EUTILS_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"

# Accession patterns
NCBI_GENBANK_RE = re.compile(r"^[A-Z]{1,2}\d{5,8}(\.\d+)?$")   # e.g. AF099142, AF099142.1
NCBI_REFSEQ_RE = re.compile(r"^N[CGW]_\d+(\.\d+)?$")              # NC_*, NG_*, NW_*
RDRP_RE = re.compile(r"^RDRP_", re.IGNORECASE)
METAGENOMIC_CONTIG_RE = re.compile(r"^k\d+_|^scaffold|^tig\d+|^ZHr\d+-k\d+")
PDB_RE = re.compile(r"^\d[A-Z0-9]{3}_")


def stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def is_ncbi_accession(acc: str) -> bool:
    """Return True if accession looks like a real NCBI record (not metagenomic/PDB/RDRP)."""
    acc = acc.strip()
    if not acc:
        return False
    if RDRP_RE.match(acc):
        return False
    if METAGENOMIC_CONTIG_RE.match(acc):
        return False
    if PDB_RE.match(acc):
        return False
    if NCBI_GENBANK_RE.match(acc):
        return True
    if NCBI_REFSEQ_RE.match(acc):
        return True
    return False


def base_accession(acc: str) -> str:
    """Strip version suffix from accession."""
    return acc.split(".")[0] if acc else ""


def scan_sequences_dir(seq_dir: Path) -> set[str]:
    """Scan sequences/ for FASTA files, return set of accessions (with and without version)."""
    accessions: set[str] = set()
    if not seq_dir.exists():
        return accessions
    for f in seq_dir.iterdir():
        if not f.is_file():
            continue
        name = f.name
        # Strip .fasta, .fa, .fna extensions
        for ext in (".fasta", ".fa", ".fna", ".seq"):
            if name.lower().endswith(ext):
                name = name[: -len(ext)]
                break
        accessions.add(name)
        accessions.add(base_accession(name))
    return accessions


def audit_isolates(conn, disk_accessions: set[str]) -> dict[str, Any]:
    """Audit has_sequence flags against on-disk files for target isolates."""
    rows = conn.execute(
        """
        SELECT vi.isolate_id, vi.accession, vi.has_sequence, vm.canonical_name
        FROM analysis_target_isolates vi
        JOIN virus_master vm ON vm.master_id = vi.master_id
        ORDER BY vi.has_sequence DESC, vm.canonical_name
        """
    ).fetchall()

    ok = 0
    flag1_no_file = []   # has_sequence=1 but file missing
    flag0_has_file = []  # has_sequence=0 but file exists
    rdpr_to_fix = []     # RDRP entries with has_sequence=1 (computational)
    non_ncbi_flagged = []  # non-NCBI accessions with has_sequence=1, no file
    downloadable = []    # real NCBI accessions, has_sequence=1, file missing

    for r in rows:
        acc = r["accession"] or ""
        has_seq = r["has_sequence"]
        on_disk = acc in disk_accessions or base_accession(acc) in disk_accessions

        if has_seq and on_disk:
            ok += 1
        elif has_seq and not on_disk:
            if RDRP_RE.match(acc):
                rdpr_to_fix.append(dict(r))
            elif is_ncbi_accession(acc):
                downloadable.append(dict(r))
            else:
                non_ncbi_flagged.append(dict(r))
        elif not has_seq and on_disk:
            flag0_has_file.append(dict(r))
        else:
            ok += 1  # no seq, no file — expected

    return {
        "ok": ok,
        "rdpr_to_fix": rdpr_to_fix,
        "downloadable": downloadable,
        "non_ncbi_flagged": non_ncbi_flagged,
        "flag0_has_file": flag0_has_file,
    }


def fetch_fasta_batch(accessions: list[str], timeout: int) -> str:
    """Fetch FASTA sequences from NCBI EFetch."""
    params = {
        "db": "nuccore",
        "id": ",".join(accessions),
        "rettype": "fasta",
        "retmode": "text",
        "tool": "aquavir_kb_curation",
    }
    url = EUTILS_URL + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(
        url, headers={"User-Agent": "aquavir-kb-curation/1.0 (local curation)"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def save_fasta_records(text: str, seq_dir: Path) -> int:
    """Split concatened FASTA into individual files. Returns count saved."""
    seq_dir.mkdir(exist_ok=True)
    count = 0
    current_header = None
    current_lines: list[str] = []
    for line in text.splitlines():
        if line.startswith(">"):
            if current_header:
                # Save previous
                acc = current_header.split()[0][1:]  # strip '>'
                fpath = seq_dir / f"{acc}.fasta"
                fpath.write_text("\n".join([current_header] + current_lines) + "\n", encoding="utf-8")
                count += 1
            current_header = line.strip()
            current_lines = []
        else:
            current_lines.append(line.strip())
    if current_header:
        acc = current_header.split()[0][1:]
        fpath = seq_dir / f"{acc}.fasta"
        fpath.write_text("\n".join([current_header] + current_lines) + "\n", encoding="utf-8")
        count += 1
    return count


def main() -> None:
    p = argparse.ArgumentParser(description="Sync FASTA files with has_sequence flags")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--sequences-dir", default=str(SEQUENCES_DIR))
    p.add_argument("--no-download", action="store_true", help="Skip NCBI download phase")
    p.add_argument("--batch-size", type=int, default=80)
    p.add_argument("--sleep", type=float, default=0.35)
    p.add_argument("--timeout", type=int, default=120)
    args = p.parse_args()

    ts = stamp()
    seq_dir = Path(args.sequences_dir)
    REPORTS_DIR.mkdir(exist_ok=True)
    summary: dict[str, Any] = {"timestamp": ts, "dry_run": args.dry_run}

    # Part A: Audit
    disk_accessions = scan_sequences_dir(seq_dir)
    summary["disk_files"] = len(disk_accessions)

    with db_connection(read_only=True) as conn:
        audit = audit_isolates(conn, disk_accessions)
        summary["audit"] = {
            "ok": audit["ok"],
            "rdpr_to_fix": len(audit["rdpr_to_fix"]),
            "downloadable_ncbi": len(audit["downloadable"]),
            "non_ncbi_flagged": len(audit["non_ncbi_flagged"]),
            "flag0_but_file_exists": len(audit["flag0_has_file"]),
        }
        for k in audit:
            if k != "ok":
                summary[f"sample_{k}"] = [
                    {"isolate_id": r["isolate_id"], "accession": r["accession"],
                     "canonical_name": r["canonical_name"]}
                    for r in audit[k][:10]
                ]

    if args.dry_run:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return

    backup_path = backup_database(label="before_sync_fasta")

    # Phase A: Fix flags
    with db_transaction() as conn:
        # Fix RDRP entries: set has_sequence=0 (computational predictions)
        if audit["rdpr_to_fix"]:
            rdpr_ids = [r["isolate_id"] for r in audit["rdpr_to_fix"]]
            for rdpr_id in rdpr_ids:
                conn.execute(
                    "UPDATE viral_isolates SET has_sequence=0 WHERE isolate_id=?",
                    (rdpr_id,),
                )
            summary["rdpr_fixed"] = len(rdpr_ids)
        else:
            summary["rdpr_fixed"] = 0

        # Fix flag0_has_file: set has_sequence=1 (file exists on disk)
        if audit["flag0_has_file"]:
            for item in audit["flag0_has_file"]:
                conn.execute(
                    "UPDATE viral_isolates SET has_sequence=1 WHERE isolate_id=?",
                    (item["isolate_id"],),
                )
            summary["flag0_fixed"] = len(audit["flag0_has_file"])
        else:
            summary["flag0_fixed"] = 0

        # Log non-NCBI flagged entries to notes
        if audit["non_ncbi_flagged"]:
            for item in audit["non_ncbi_flagged"]:
                conn.execute(
                    "UPDATE viral_isolates SET has_sequence=0 WHERE isolate_id=?",
                    (item["isolate_id"],),
                )
            summary["non_ncbi_cleared"] = len(audit["non_ncbi_flagged"])
        else:
            summary["non_ncbi_cleared"] = 0

    # Phase B: Download missing FASTA (online)
    if not args.no_download and audit["downloadable"]:
        download_accessions = [r["accession"] for r in audit["downloadable"]]
        # Deduplicate
        unique_accs = sorted(set(download_accessions))
        summary["unique_to_download"] = len(unique_accs)

        downloaded = 0
        download_errors = 0
        batches = [unique_accs[i:i + args.batch_size] for i in range(0, len(unique_accs), args.batch_size)]

        for i, batch in enumerate(batches):
            try:
                text = fetch_fasta_batch(batch, args.timeout)
                saved = save_fasta_records(text, seq_dir)
                downloaded += saved
                print(f"[download] batch {i+1}/{len(batches)}: {saved} files from {len(batch)} accessions")
            except Exception as exc:
                download_errors += 1
                print(f"[download] batch {i+1} FAILED: {exc}", file=sys.stderr)
            time.sleep(args.sleep)

        summary["fasta_downloaded"] = downloaded
        summary["download_errors"] = download_errors

        # Refresh disk_accessions and set has_sequence=1 for newly downloaded
        disk_accessions = scan_sequences_dir(seq_dir)
        with db_transaction() as conn:
            newly_present = 0
            for item in audit["downloadable"]:
                acc = item["accession"]
                if acc in disk_accessions or base_accession(acc) in disk_accessions:
                    conn.execute(
                        "UPDATE viral_isolates SET has_sequence=1 WHERE isolate_id=?",
                        (item["isolate_id"],),
                    )
                    newly_present += 1
            summary["newly_has_sequence_set"] = newly_present

    # ── Verification ──
    with db_connection(read_only=True) as conn:
        # Count isolates where has_sequence=1 and accession looks like NCBI but no file
        still_missing = conn.execute(
            """
            SELECT COUNT(*) FROM analysis_target_isolates
            WHERE has_sequence = 1
              AND accession NOT LIKE 'RDRP%'
            """
        ).fetchone()[0]
        total_has_seq = conn.execute(
            "SELECT COUNT(*) FROM analysis_target_isolates WHERE has_sequence = 1"
        ).fetchone()[0]
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]

    summary["has_sequence_total_after"] = total_has_seq
    summary["integrity_check"] = integrity
    summary["backup_path"] = str(backup_path)

    report_path = REPORTS_DIR / f"fasta_sync_{ts}.json"
    report_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
