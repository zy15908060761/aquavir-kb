#!/usr/bin/env python3
"""
Module 1: Batch InterProScan annotation for non-redundant protein clusters.

Replaces the existing rule-based domain annotation with database-validated
domain annotations from Pfam, CDD, Gene3D, SUPERFAMILY, SMART, etc.

Workflow:
  1. Export representative sequences from nr_protein_clusters to FASTA
  2. Run InterProScan locally (preferred) or via EBI REST API (fallback)
  3. Parse TSV output and import into protein_domains + new protein_go table
  4. Generate annotation quality report

Prerequisites:
  - InterProScan v5.75+ installed locally (recommended for 16k+ sequences)
    OR EBI REST API access (slower, no installation)
  - Java 11+ (for local InterProScan)
  - ~30-50 GB disk space (for InterProScan data files)

Usage:
    # Check prerequisites and export FASTA only
    python run_interproscan_annotation.py --export-only

    # Run with local InterProScan
    python run_interproscan_annotation.py --interproscan-path /path/to/interproscan.sh

    # Run with EBI REST API (slower, for small batches)
    python run_interproscan_annotation.py --use-ebi-api --limit 100

    # Dry-run (preview what would be annotated)
    python run_interproscan_annotation.py --dry-run
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from datetime import datetime
from typing import Any

# ── Configuration ─────────────────────────────────────────────────
DB_PATH = Path(r"F:\甲壳动物数据库\crustacean_virus_core.db")
WORK_DIR = Path(r"F:\甲壳动物数据库\external_data\interproscan")
WORK_DIR.mkdir(parents=True, exist_ok=True)

FASTA_PATH = WORK_DIR / "nr_protein_representatives.fasta"
INTERPRO_TSV = WORK_DIR / "interproscan_results.tsv"
REPORT_JSON = WORK_DIR / "annotation_report.json"

# Batch size for local InterProScan (to avoid memory issues)
LOCAL_BATCH_SIZE = 1000

# EBI REST API settings
EBI_BASE_URL = "https://www.ebi.ac.uk/Tools/services/rest/iprscan5"
EBI_POLL_INTERVAL = 10  # seconds


# ── Step 1: Export NR representatives to FASTA ────────────────────
def export_representatives(conn: sqlite3.Connection, limit: int | None = None) -> int:
    """Export representative sequences from nr_protein_clusters to FASTA."""
    c = conn.cursor()

    query = """
        SELECT cluster_id, representative_aa_seq, cluster_size, source_count
        FROM nr_protein_clusters
        WHERE representative_aa_seq IS NOT NULL
          AND LENGTH(representative_aa_seq) > 0
          AND cluster_size >= 1
    """
    if limit:
        query += f" LIMIT {limit}"

    rows = c.execute(query).fetchall()
    if not rows:
        print("[warn] No NR protein clusters found with sequences")
        return 0

    with open(FASTA_PATH, "w", encoding="utf-8") as f:
        for row in rows:
            cluster_id, seq, size, src_count = row
            # Clean sequence: uppercase, remove non-AA characters
            seq_clean = re.sub(r"[^A-Z]", "", seq.upper())
            if len(seq_clean) < 10:
                continue
            header = f">cluster_{cluster_id} size={size} sources={src_count}"
            f.write(f"{header}\n")
            # Write 60 chars per line
            for i in range(0, len(seq_clean), 60):
                f.write(seq_clean[i:i + 60] + "\n")

    print(f"[export] {len(rows)} representative sequences -> {FASTA_PATH}")
    print(f"         Total FASTA size: {FASTA_PATH.stat().st_size / 1024 / 1024:.1f} MB")
    return len(rows)


# ── Step 2a: Local InterProScan runner ────────────────────────────
def find_interproscan(interproscan_path: str | None = None) -> Path | None:
    """Locate InterProScan executable."""
    if interproscan_path:
        p = Path(interproscan_path)
        if p.exists():
            return p
        print(f"[warn] Specified path not found: {p}")

    # Common locations
    candidates = [
        r"F:\tools\interproscan\interproscan.sh",
        r"C:\tools\interproscan\interproscan.sh",
        r"F:\InterProScan\interproscan.sh",
        shutil.which("interproscan.sh"),
    ]
    for cand in candidates:
        if cand and Path(cand).exists():
            return Path(cand)
    return None


def run_interproscan_local(ipr_path: Path, input_fasta: Path, output_tsv: Path) -> bool:
    """Run InterProScan locally with TSV output."""
    print(f"[interproscan] Using: {ipr_path}")
    print(f"[interproscan] Input:  {input_fasta}")
    print(f"[interproscan] Output: {output_tsv}")

    # Use WSL or direct bash if on Windows
    cmd = [
        str(ipr_path),
        "-i", str(input_fasta),
        "-f", "TSV",
        "-o", str(output_tsv),
        "-cpu", "4",
        "-goterms",
        "-pa",
    ]

    print(f"[interproscan] Command: {' '.join(cmd)}")
    print("[interproscan] This may take 30 minutes to several hours depending on sequence count...")

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=86400,  # 24 hours max
        )
        if result.returncode != 0:
            print(f"[error] InterProScan failed with code {result.returncode}")
            print(f"[stderr] {result.stderr[:2000]}")
            return False

        if not output_tsv.exists():
            print("[error] InterProScan completed but output file not found")
            return False

        print(f"[interproscan] Done. Output: {output_tsv} ({output_tsv.stat().st_size / 1024:.1f} KB)")
        return True

    except subprocess.TimeoutExpired:
        print("[error] InterProScan timed out after 24 hours")
        return False
    except FileNotFoundError:
        print("[error] Cannot execute InterProScan. On Windows, you may need WSL or Cygwin.")
        return False


# ── Step 2b: EBI REST API runner ──────────────────────────────────
def submit_ebi_job(fasta_sequence: str, email: str = "user@example.com") -> str | None:
    """Submit a single sequence to EBI InterProScan REST API. Returns job ID."""
    url = f"{EBI_BASE_URL}/run"
    data = urllib.parse.urlencode({
        "email": email,
        "title": "crustacean_db_annotation",
        "sequence": fasta_sequence,
    }).encode("utf-8")

    try:
        req = urllib.request.Request(url, data=data, method="POST")
        with urllib.request.urlopen(req, timeout=60) as resp:
            job_id = resp.read().decode("utf-8").strip()
        return job_id
    except Exception as exc:
        print(f"[ebi error] {exc}")
        return None


def poll_ebi_job(job_id: str) -> str | None:
    """Poll EBI job status until complete. Returns result text."""
    status_url = f"{EBI_BASE_URL}/status/{job_id}"
    result_url = f"{EBI_BASE_URL}/result/{job_id}/tsv"

    for attempt in range(360):  # max 1 hour
        try:
            with urllib.request.urlopen(status_url, timeout=30) as resp:
                status = resp.read().decode("utf-8").strip()
        except Exception as exc:
            print(f"  [poll error] {exc}")
            time.sleep(EBI_POLL_INTERVAL)
            continue

        if status == "FINISHED":
            try:
                with urllib.request.urlopen(result_url, timeout=60) as resp:
                    return resp.read().decode("utf-8")
            except Exception as exc:
                print(f"  [result error] {exc}")
                return None
        elif status in ("ERROR", "FAILURE"):
            print(f"  [ebi] Job {job_id} failed with status: {status}")
            return None

        if attempt % 6 == 0:
            print(f"  [ebi] Job {job_id} status: {status} (waiting {attempt * EBI_POLL_INTERVAL}s)")
        time.sleep(EBI_POLL_INTERVAL)

    print(f"  [ebi] Job {job_id} timed out after 1 hour")
    return None


def run_interproscan_ebi(limit: int = 50) -> bool:
    """Run via EBI REST API (slow, for testing small batches only)."""
    print(f"[ebi] Using EBI REST API (limit={limit} sequences)")
    print("[ebi] WARNING: This is very slow (~2-5 min per sequence). Only use for testing.")

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    rows = c.execute(f"""
        SELECT cluster_id, representative_aa_seq
        FROM nr_protein_clusters
        WHERE representative_aa_seq IS NOT NULL
        LIMIT {limit}
    """).fetchall()
    conn.close()

    all_results = []
    for i, row in enumerate(rows, 1):
        cid, seq = row
        print(f"\n[ebi {i}/{len(rows)}] Submitting cluster_{cid}...")
        job_id = submit_ebi_job(seq)
        if not job_id:
            continue
        print(f"  Job ID: {job_id}")
        result = poll_ebi_job(job_id)
        if result:
            all_results.append(result)
            print(f"  Got {len(result.splitlines())} annotation lines")

    if all_results:
        INTERPRO_TSV.write_text("\n".join(all_results), encoding="utf-8")
        print(f"\n[ebi] Combined results saved: {INTERPRO_TSV}")
        return True
    return False


# ── Step 3: Parse TSV output ──────────────────────────────────────
def parse_interpro_tsv(tsv_path: Path) -> list[dict]:
    """Parse InterProScan TSV output."""
    if not tsv_path.exists():
        return []

    # TSV columns:
    # 0: Protein Accession
    # 1: Sequence MD5
    # 2: Sequence Length
    # 3: Analysis (Pfam, Gene3D, SMART, etc.)
    # 4: Signature Accession
    # 5: Signature Description
    # 6: Start
    # 7: Stop
    # 8: Score
    # 9: Status (T: true, ?: unknown)
    # 10: Date
    # 11: InterPro Accession
    # 12: InterPro Description
    # 13: GO Terms (optional)
    # 14: Pathways (optional)

    results = []
    with open(tsv_path, "r", encoding="utf-8") as f:
        reader = csv.reader(f, delimiter="\t")
        for row in reader:
            if len(row) < 12:
                continue
            protein_acc = row[0]  # e.g., "cluster_1234"
            analysis = row[3]     # e.g., "Pfam"
            sig_acc = row[4]      # e.g., "PF00069"
            sig_desc = row[5]     # e.g., "Protein kinase domain"
            start = row[6]
            end = row[7]
            interpro_id = row[11] if len(row) > 11 else ""
            interpro_desc = row[12] if len(row) > 12 else ""
            go_terms = row[13] if len(row) > 13 else ""
            pathways = row[14] if len(row) > 14 else ""

            # Extract cluster_id from protein accession
            m = re.search(r"cluster_(\d+)", protein_acc)
            if not m:
                continue
            cluster_id = int(m.group(1))

            results.append({
                "cluster_id": cluster_id,
                "domain_source": analysis,
                "domain_name": sig_acc,
                "domain_description": sig_desc,
                "start_pos": int(start) if start.isdigit() else None,
                "end_pos": int(end) if end.isdigit() else None,
                "interpro_id": interpro_id,
                "interpro_description": interpro_desc,
                "go_terms": go_terms,
                "pathways": pathways,
            })

    print(f"[parse] Parsed {len(results)} annotation lines from {tsv_path}")
    return results


# ── Step 4: Import into database ──────────────────────────────────
def import_annotations(conn: sqlite3.Connection, annotations: list[dict]) -> dict:
    """Import InterProScan results into protein_domains and protein_go tables."""
    c = conn.cursor()

    # Create protein_go table if not exists
    c.executescript("""
        CREATE TABLE IF NOT EXISTS protein_go_terms (
            go_id INTEGER PRIMARY KEY AUTOINCREMENT,
            cluster_id INTEGER,
            protein_id INTEGER,
            go_term TEXT,
            go_category TEXT,
            evidence_code TEXT DEFAULT 'IEA',
            source TEXT DEFAULT 'InterProScan',
            FOREIGN KEY (cluster_id) REFERENCES nr_protein_clusters(cluster_id)
        );
        CREATE INDEX IF NOT EXISTS idx_go_cluster ON protein_go_terms(cluster_id);
        CREATE INDEX IF NOT EXISTS idx_go_term ON protein_go_terms(go_term);
    """)

    stats = {"domains_inserted": 0, "go_inserted": 0, "skipped": 0}

    for ann in annotations:
        cluster_id = ann["cluster_id"]

        # Insert domain annotation
        try:
            c.execute("""
                INSERT OR IGNORE INTO protein_domains
                    (cluster_id, domain_source, domain_name, domain_description,
                     start_pos, end_pos, confidence_score, interpro_id,
                     domain_model, pfam_id, cdd_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                cluster_id,
                f"interproscan_{ann['domain_source']}",
                ann["domain_name"],
                ann["domain_description"],
                ann["start_pos"],
                ann["end_pos"],
                0.8,  # InterProScan results are high-confidence
                ann["interpro_id"] if ann["interpro_id"] else None,
                ann["domain_source"],  # domain_model
                ann["domain_name"] if ann["domain_source"] == "Pfam" else None,
                ann["domain_name"] if ann["domain_source"] == "CDD" else None,
            ))
            if c.rowcount > 0:
                stats["domains_inserted"] += 1
        except sqlite3.IntegrityError:
            stats["skipped"] += 1

        # Parse and insert GO terms
        if ann.get("go_terms"):
            for go_term in ann["go_terms"].split("|"):
                go_term = go_term.strip()
                if not go_term:
                    continue
                # GO term format: "GO:0005524" or "GO:0005524~ATP binding"
                go_id = go_term.split("~")[0].strip()
                go_desc = go_term.split("~")[1].strip() if "~" in go_term else ""

                c.execute("""
                    INSERT OR IGNORE INTO protein_go_terms
                        (cluster_id, go_term, go_category, source)
                    VALUES (?, ?, ?, ?)
                """, (
                    cluster_id, go_id, go_desc, "InterProScan",
                ))
                if c.rowcount > 0:
                    stats["go_inserted"] += 1

    return stats


def generate_report(conn: sqlite3.Connection, stats: dict) -> dict:
    """Generate annotation quality report."""
    c = conn.cursor()

    # Domain source breakdown
    c.execute("""
        SELECT domain_source, COUNT(*) as cnt
        FROM protein_domains
        WHERE domain_source LIKE 'interproscan_%'
        GROUP BY domain_source
        ORDER BY cnt DESC
    """)
    source_breakdown = {row[0]: row[1] for row in c.fetchall()}

    # GO term breakdown
    c.execute("SELECT COUNT(DISTINCT go_term) FROM protein_go_terms")
    unique_go = c.fetchone()[0]

    c.execute("SELECT COUNT(DISTINCT cluster_id) FROM protein_go_terms")
    clusters_with_go = c.fetchone()[0]

    report = {
        "timestamp": datetime.now().isoformat(),
        "method": "InterProScan",
        "domains_inserted": stats["domains_inserted"],
        "go_terms_inserted": stats["go_inserted"],
        "unique_go_terms": unique_go,
        "clusters_with_go": clusters_with_go,
        "source_breakdown": source_breakdown,
    }

    with open(REPORT_JSON, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    return report


# ── Main ──────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="InterProScan annotation pipeline")
    parser.add_argument("--export-only", action="store_true", help="Only export FASTA, skip annotation")
    parser.add_argument("--interproscan-path", type=str, default=None, help="Path to interproscan.sh")
    parser.add_argument("--use-ebi-api", action="store_true", help="Use EBI REST API instead of local")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of sequences (for testing)")
    parser.add_argument("--dry-run", action="store_true", help="Preview only, no database writes")
    parser.add_argument("--parse-only", type=str, default=None, help="Parse existing TSV file and import")
    args = parser.parse_args()

    print("=" * 60)
    print("Module 1: InterProScan Protein Domain Annotation")
    print("=" * 60)

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")

    # Step 1: Export
    n_exported = export_representatives(conn, limit=args.limit)
    if not n_exported:
        print("[error] No sequences to annotate")
        conn.close()
        return

    if args.export_only:
        print(f"\n[done] FASTA exported to {FASTA_PATH}")
        print("Next: run InterProScan manually or provide --interproscan-path")
        conn.close()
        return

    # Step 2: Run InterProScan
    if args.parse_only:
        tsv_path = Path(args.parse_only)
        if not tsv_path.exists():
            print(f"[error] TSV file not found: {tsv_path}")
            conn.close()
            return
    elif args.use_ebi_api:
        limit = args.limit or 50
        success = run_interproscan_ebi(limit=limit)
        if not success:
            conn.close()
            return
        tsv_path = INTERPRO_TSV
    else:
        ipr_path = find_interproscan(args.interproscan_path)
        if not ipr_path:
            print("\n[error] InterProScan not found!")
            print("\nTo install InterProScan locally:")
            print("  1. Download from https://www.ebi.ac.uk/interpro/download/")
            print("  2. Extract to F:\\tools\\interproscan\\")
            print("  3. Run: python run_interproscan_annotation.py --interproscan-path F:\\tools\\interproscan\\interproscan.sh")
            print("\nAlternatively, use EBI API (slow but no installation):")
            print("  python run_interproscan_annotation.py --use-ebi-api --limit 50")
            conn.close()
            return

        if args.dry_run:
            print("\n[dry-run] Would run:")
            print(f"  {ipr_path} -i {FASTA_PATH} -f TSV -o {INTERPRO_TSV}")
            conn.close()
            return

        success = run_interproscan_local(ipr_path, FASTA_PATH, INTERPRO_TSV)
        if not success:
            conn.close()
            return
        tsv_path = INTERPRO_TSV

    # Step 3: Parse
    annotations = parse_interpro_tsv(tsv_path)
    if not annotations:
        print("[error] No annotations parsed from TSV")
        conn.close()
        return

    if args.dry_run:
        print(f"\n[dry-run] Would import {len(annotations)} annotations")
        conn.close()
        return

    # Step 4: Import
    print("\n[import] Writing to database...")
    stats = import_annotations(conn, annotations)
    conn.commit()

    # Step 5: Report
    report = generate_report(conn, stats)
    conn.close()

    print("\n" + "=" * 60)
    print("Annotation complete!")
    print("=" * 60)
    print(f"  Domains inserted:    {stats['domains_inserted']}")
    print(f"  GO terms inserted:   {stats['go_inserted']}")
    print(f"  Unique GO terms:     {report['unique_go_terms']}")
    print(f"  Clusters with GO:    {report['clusters_with_go']}")
    print(f"\n  Report: {REPORT_JSON}")
    print(f"  TSV:    {tsv_path}")


if __name__ == "__main__":
    main()
