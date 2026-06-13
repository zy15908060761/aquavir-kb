#!/usr/bin/env python3
"""
P1 Protein Domain Annotation Optimization for AquaVir-KB.

Identifies unannotated proteins, exports them to FASTA, and provides
parsing for InterProScan/CDD batch results.

Usage:
  python optimize_protein_domains.py --export-fasta    Export unannotated proteins to FASTA
  python optimize_protein_domains.py --dry-run          Show what would be annotated
  python optimize_protein_domains.py --parse-results <interproscan.tsv>   Parse results
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

# ── Paths ────────────────────────────────────────────────────────
APP_DIR = Path(__file__).resolve().parent
DB_PATH = APP_DIR / "crustacean_virus_core.db"
REPORTS_DIR = APP_DIR / "reports"
FASTA_DIR = APP_DIR / "sequences"
BACKUPS_DIR = APP_DIR / "backups"


def stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def scalar(conn, sql: str, params=()) -> Any:
    cur = conn.execute(sql, params)
    row = cur.fetchone()
    return row[0] if row else None


def backup_database(db_path: Path, backup_dir: Path, label: str) -> Path:
    import shutil
    import sqlite3 as _sqlite3
    backup_dir.mkdir(parents=True, exist_ok=True)
    ts = stamp()
    safe_label = label.replace(" ", "_").replace("/", "_").replace("\\", "_")
    backup_base = backup_dir / f"crustacean_virus_core_{safe_label}_{ts}"

    conn = _sqlite3.connect(str(db_path))
    try:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        conn.close()

    shutil.copy2(str(db_path), str(backup_base.with_suffix(".db")))
    for suffix in (".db-wal", ".db-shm"):
        src = Path(str(db_path) + suffix)
        if src.exists():
            dst = Path(str(backup_base.with_suffix("")) + suffix)
            shutil.copy2(str(src), str(dst))

    print(f"[backup] WAL-safe backup → {backup_base.with_suffix('.db').name}")
    return backup_base.with_suffix(".db")


def export_unannotated_fasta(db_path: Path, output_path: Path) -> dict:
    """Export unannotated protein sequences to FASTA file."""
    import sqlite3
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    # Find proteins without domain annotations
    rows = conn.execute("""
        SELECT vp.protein_id, vp.protein_accession, vp.protein_name,
               vp.translation, vp.aa_length, vi.accession AS isolate_acc,
               vi.virus_name
        FROM viral_proteins vp
        JOIN viral_isolates vi ON vp.isolate_id = vi.isolate_id
        WHERE NOT EXISTS (
            SELECT 1 FROM protein_domains pd WHERE pd.protein_id = vp.protein_id
        )
        AND vp.translation IS NOT NULL AND vp.translation != ''
        ORDER BY vp.protein_id
    """).fetchall()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with open(output_path, "w", encoding="utf-8") as f:
        for row in rows:
            seq = row["translation"]
            if len(seq) < 20:  # Skip very short peptides
                continue
            header = f">{row['protein_id']}|{row['protein_accession']}|{row['protein_name'] or 'unnamed'}|{row['isolate_acc']}|{row['virus_name'] or 'unknown'}"
            f.write(f"{header}\n")
            # Wrap sequence at 60 chars
            for i in range(0, len(seq), 60):
                f.write(f"{seq[i:i+60]}\n")
            count += 1

    conn.close()
    return {"total_unannotated": len(rows), "exported_to_fasta": count, "path": str(output_path)}


def parse_interproscan_tsv(db_path: Path, tsv_path: Path, dry_run: bool) -> dict:
    """Parse InterProScan TSV output and insert domain annotations.

    Expected TSV format (InterProScan 5):
    protein_id  md5  seq_length  analysis  signature_accession  signature_description
    start  stop  score  status  date  interpro_accession  interpro_description  [go_terms]  [pathways]
    """
    import sqlite3
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")

    result = {"parsed": 0, "inserted": 0, "skipped_exists": 0, "skipped_no_match": 0, "errors": []}

    if not tsv_path.exists():
        print(f"ERROR: TSV file not found: {tsv_path}")
        conn.close()
        return result

    with open(tsv_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    domain_inserts = []
    seen = set()

    for line_num, line in enumerate(lines, 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        cols = line.split("\t")
        if len(cols) < 9:
            result["errors"].append(f"Line {line_num}: too few columns ({len(cols)})")
            continue

        # Extract protein_id from the first column (format: "protein_id|accession|name|isolate|virus")
        protein_id_str = cols[0]
        protein_id = None
        if "|" in protein_id_str:
            protein_id = int(protein_id_str.split("|")[0])
        else:
            try:
                protein_id = int(protein_id_str)
            except ValueError:
                result["errors"].append(f"Line {line_num}: cannot parse protein_id from '{protein_id_str}'")
                continue

        signature_acc = cols[4] if len(cols) > 4 else ""
        signature_desc = cols[5] if len(cols) > 5 else ""
        interpro_acc = cols[11] if len(cols) > 11 else ""
        interpro_desc = cols[12] if len(cols) > 12 else ""
        start_pos = int(cols[6]) if len(cols) > 6 and cols[6].isdigit() else None
        stop_pos = int(cols[7]) if len(cols) > 7 and cols[7].isdigit() else None
        score = float(cols[8]) if len(cols) > 8 and cols[8].replace(".", "").replace("e", "").replace("E", "").replace("-", "").isdigit() else None

        result["parsed"] += 1

        # Deduplicate
        dedupe_key = (protein_id, signature_acc, start_pos or 0, stop_pos or 0)
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)

        # Check if already exists
        if not dry_run:
            existing = conn.execute(
                "SELECT 1 FROM protein_domains WHERE protein_id = ? AND domain_model = ? AND start_pos = ?",
                (protein_id, signature_acc, start_pos),
            ).fetchone()
            if existing:
                result["skipped_exists"] += 1
                continue

            domain_inserts.append({
                "protein_id": protein_id,
                "domain_model": signature_acc[:100] if signature_acc else "",
                "domain_name": signature_desc[:200] if signature_desc else "",
                "domain_description": interpro_desc[:500] if interpro_desc else "",
                "domain_source": "interproscan",
                "interpro_id": interpro_acc[:50] if interpro_acc else "",
                "start_pos": start_pos,
                "end_pos": stop_pos,
                "confidence_score": score,
            })
        result["inserted"] += 1

    # Batch insert
    if not dry_run and domain_inserts:
        batch_size = 500
        for i in range(0, len(domain_inserts), batch_size):
            batch = domain_inserts[i:i+batch_size]
            conn.execute("BEGIN IMMEDIATE")
            try:
                for d in batch:
                    conn.execute(
                        """INSERT INTO protein_domains
                        (protein_id, domain_model, domain_name, domain_description,
                         domain_source, interpro_id, start_pos, end_pos, confidence_score)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (d["protein_id"], d["domain_model"], d["domain_name"],
                         d["domain_description"], d["domain_source"], d["interpro_id"],
                         d["start_pos"], d["end_pos"], d["confidence_score"]),
                    )
                conn.commit()
            except BaseException:
                conn.rollback()
                raise
        print(f"[insert] {len(domain_inserts)} domains inserted (batched)")

    conn.close()
    return result


def show_stats(db_path: Path) -> dict:
    """Show current protein domain coverage statistics."""
    import sqlite3
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    total_proteins = scalar(conn, "SELECT COUNT(*) FROM viral_proteins") or 0
    annotated = scalar(conn, "SELECT COUNT(DISTINCT protein_id) FROM protein_domains") or 0
    unannotated = total_proteins - annotated
    unannotated_with_seq = scalar(conn, """
        SELECT COUNT(*) FROM viral_proteins vp
        WHERE NOT EXISTS (SELECT 1 FROM protein_domains pd WHERE pd.protein_id = vp.protein_id)
        AND vp.translation IS NOT NULL AND vp.translation != '' AND LENGTH(vp.translation) >= 20
    """) or 0

    total_domains = scalar(conn, "SELECT COUNT(*) FROM protein_domains") or 0
    by_source = conn.execute(
        "SELECT domain_source, COUNT(*) FROM protein_domains GROUP BY domain_source ORDER BY COUNT(*) DESC"
    ).fetchall()

    result = {
        "total_proteins": total_proteins,
        "annotated_proteins": annotated,
        "unannotated_proteins": unannotated,
        "unannotated_with_exportable_seq": unannotated_with_seq,
        "coverage_pct": round(annotated / total_proteins * 100, 1) if total_proteins else 0,
        "total_domains": total_domains,
        "by_source": {r["domain_source"] or "unknown": r[1] for r in by_source},
    }

    print(f"\n{'='*50}")
    print("Protein Domain Coverage")
    print(f"{'='*50}")
    print(f"  Total proteins:       {total_proteins}")
    print(f"  Annotated:            {annotated} ({result['coverage_pct']}%)")
    print(f"  Unannotated:          {unannotated}")
    print(f"  Exportable (has seq): {unannotated_with_seq}")
    print(f"  Total domains:        {total_domains}")
    print(f"  By source:")
    for src, cnt in result["by_source"].items():
        print(f"    {src}: {cnt}")
    print()

    conn.close()
    return result


def main():
    parser = argparse.ArgumentParser(description="P1 Protein Domain Annotation Optimization")
    parser.add_argument("--export-fasta", action="store_true",
                        help="Export unannotated proteins to FASTA")
    parser.add_argument("--parse-results", type=str, metavar="TSV",
                        help="Parse InterProScan TSV output and insert domains")
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview only, no writes")
    parser.add_argument("--db", type=str, default=str(DB_PATH),
                        help="Path to database file")
    parser.add_argument("--fasta-out", type=str, default=None,
                        help="Output FASTA path (default: sequences/unannotated_proteins_<ts>.fasta)")
    args = parser.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"ERROR: Database not found: {db_path}")
        sys.exit(1)

    # Always show stats first
    stats = show_stats(db_path)

    if args.export_fasta:
        fasta_path = Path(args.fasta_out) if args.fasta_out else \
            FASTA_DIR / f"unannotated_proteins_{stamp()}.fasta"
        result = export_unannotated_fasta(db_path, fasta_path)
        print(f"Exported {result['exported_to_fasta']} proteins → {result['path']}")
        print(f"Skipped {result['total_unannotated'] - result['exported_to_fasta']} short peptides (<20aa)")
        print()
        print("Next step: Run InterProScan on the FASTA file:")
        print(f"  interproscan.sh -i {result['path']} -f tsv -o {result['path']}.tsv --goterms --pathways")
        print(f"Then parse results:")
        print(f"  python optimize_protein_domains.py --parse-results {result['path']}.tsv")

    if args.parse_results:
        if not args.dry_run and not args.export_fasta:
            backup_database(db_path, BACKUPS_DIR, "pre_domain_import")
        tsv_path = Path(args.parse_results)
        result = parse_interproscan_tsv(db_path, tsv_path, args.dry_run)
        print(f"\nParsed {result['parsed']} entries from {tsv_path.name}")
        if args.dry_run:
            print(f"  Would insert: {result['inserted']} domains")
            print(f"  Would skip (exists): {result['skipped_exists']}")
        else:
            print(f"  Inserted: {result['inserted']} domains")
            print(f"  Skipped (exists): {result['skipped_exists']}")
        if result["errors"]:
            print(f"  Errors: {len(result['errors'])}")
            for e in result["errors"][:10]:
                print(f"    {e}")

    if not args.export_fasta and not args.parse_results:
        print("Usage: specify --export-fasta and/or --parse-results <tsv>")
        print(f"  {parser.prog} --export-fasta")
        print(f"  {parser.prog} --parse-results interproscan_output.tsv [--dry-run]")


if __name__ == "__main__":
    main()
