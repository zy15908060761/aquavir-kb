"""
PHI-base pathogen-host interaction matching via DIAMOND.

Workflow:
  1. Export representative protein sequences from nr_protein_clusters
  2. Build DIAMOND database from PHI-base FASTA
  3. Run DIAMOND alignment (cluster reps vs PHI-base)
  4. Filter and annotate hits
  5. Store results in phi_base_hits table

Usage:
    python enrich_phi_base.py                          # full run
    python enrich_phi_base.py --diamond-only           # skip DB export, just align
    python enrich_phi_base.py --eval 1e-3              # custom e-value threshold
    python enrich_phi_base.py --stats                  # coverage stats only
"""

from __future__ import annotations

import csv
import json
import os
import sqlite3
import subprocess
import sys
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any


BASE_DIR = Path(__file__).resolve().parent
DB_PATH = os.environ.get(
    "ENRICH_DB_PATH",
    str(BASE_DIR / "crustacean_virus_core.db"),
)
DATA_DIR = BASE_DIR / "external_data" / "phi_base"
DATA_DIR.mkdir(parents=True, exist_ok=True)

# DIAMOND binary location
DIAMOND_BIN = os.environ.get("DIAMOND_BIN", str(DATA_DIR / "diamond.exe"))
# PHI-base FASTA
PHI_BASE_FASTA = os.environ.get("PHI_BASE_FASTA", str(DATA_DIR / "phi-base.fas"))
# Our cluster FASTA
CLUSTER_FASTA = DATA_DIR / "cluster_reps.faa"
# DIAMOND DB
PHI_BASE_DMND = DATA_DIR / "phi-base.dmnd"
# Output
DIAMOND_OUTPUT = DATA_DIR / "diamond_alignment.tsv"

# Default alignment thresholds
DEFAULT_EVAL = 1e-5
MIN_IDENTITY = 25  # minimum % identity
MIN_COVERAGE = 40  # minimum query coverage %


def download_schema(conn: sqlite3.Connection) -> None:
    """Create phi_base_hits table if not exists."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS phi_base_hits (
            hit_id INTEGER PRIMARY KEY AUTOINCREMENT,
            cluster_id INTEGER NOT NULL,
            phi_accession TEXT NOT NULL,
            phi_id TEXT,
            phi_gene TEXT,
            phi_organism TEXT,
            phi_phenotype TEXT,
            identity REAL,
            alignment_length INTEGER,
            evalue REAL,
            bit_score REAL,
            query_coverage REAL,
            FOREIGN KEY (cluster_id) REFERENCES nr_protein_clusters(cluster_id)
        );
        CREATE INDEX IF NOT EXISTS idx_phi_cluster ON phi_base_hits(cluster_id);
        CREATE INDEX IF NOT EXISTS idx_phi_phenotype ON phi_base_hits(phi_phenotype);
    """)


def export_cluster_sequences(conn: sqlite3.Connection) -> int:
    """Export representative sequences from nr_protein_clusters to FASTA."""
    rows = conn.execute("""
        SELECT cluster_id, representative_aa_seq,
               COALESCE(avg_length, 0) as seq_len
        FROM nr_protein_clusters
        WHERE representative_aa_seq IS NOT NULL
          AND length(representative_aa_seq) >= 30
        ORDER BY cluster_id
    """).fetchall()

    count = 0
    with open(CLUSTER_FASTA, "w", encoding="utf-8") as f:
        for r in rows:
            seq = r[1].strip()
            if len(seq) < 30:
                continue
            f.write(f">cluster_{r[0]}|len={len(seq)}\n{seq}\n")
            count += 1

    print(f"[export] {count} cluster sequences written to {CLUSTER_FASTA}")
    return count


def build_diamond_db() -> bool:
    """Build DIAMOND database from PHI-base FASTA."""
    if PHI_BASE_DMND.exists():
        print(f"[db] DIAMOND database exists: {PHI_BASE_DMND}")
        return True

    if not Path(PHI_BASE_FASTA).exists():
        print(f"[error] PHI-base FASTA not found: {PHI_BASE_FASTA}")
        print("  Download from https://zenodo.org/records/16759421 and place in", DATA_DIR)
        return False

    cmd = [
        str(DIAMOND_BIN), "makedb",
        "--in", PHI_BASE_FASTA,
        "--db", str(PHI_BASE_DMND),
    ]
    print(f"[db] Building DIAMOND database...")
    start = time.time()
    result = subprocess.run(cmd, capture_output=True, text=True)
    elapsed = time.time() - start

    if result.returncode != 0:
        print(f"[error] DIAMOND makedb failed: {result.stderr}")
        return False

    print(f"[db] Database built in {elapsed:.0f}s")
    return True


def run_diamond(evalue: float = DEFAULT_EVAL) -> bool:
    """Run DIAMOND alignment (cluster reps vs PHI-base)."""
    # Check if output exists and is non-empty
    if DIAMOND_OUTPUT.exists() and DIAMOND_OUTPUT.stat().st_size > 0:
        print(f"[diamond] Output exists: {DIAMOND_OUTPUT}, skipping alignment")
        return True

    if not CLUSTER_FASTA.exists():
        print(f"[error] Cluster FASTA not found: {CLUSTER_FASTA}")
        return False

    cmd = [
        str(DIAMOND_BIN), "blastp",
        "--db", str(PHI_BASE_DMND),
        "--query", str(CLUSTER_FASTA),
        "--out", str(DIAMOND_OUTPUT),
        "--outfmt", "6",
        "--evalue", str(evalue),
        "--max-target-seqs", "5",
        "--threads", "4",
        "--sensitive",  # more sensitive than default
    ]
    print(f"[diamond] Running DIAMOND blastp (e-value={evalue})...")
    print(f"  Query: {CLUSTER_FASTA}")
    print(f"  Target: {PHI_BASE_DMND}")
    start = time.time()
    result = subprocess.run(cmd, capture_output=True, text=True)
    elapsed = time.time() - start

    if result.returncode != 0:
        print(f"[error] DIAMOND blastp failed: {result.stderr}")
        return False

    n_output = 0
    if DIAMOND_OUTPUT.exists():
        n_output = sum(1 for _ in open(DIAMOND_OUTPUT))

    print(f"[diamond] Alignment completed in {elapsed:.0f}s, {n_output} hits")
    return True


def parse_diamond_output() -> list[dict[str, Any]]:
    """Parse DIAMOND tabular output into hit records."""
    if not DIAMOND_OUTPUT.exists():
        return []

    # Format 6 columns:
    # qseqid, sseqid, pident, length, mismatch, gapopen, qstart, qend, sstart, send, evalue, bitscore
    hits = []
    seen_pairs: set = set()

    for line in open(DIAMOND_OUTPUT):
        parts = line.strip().split("\t")
        if len(parts) < 12:
            continue

        qseqid = parts[0]
        sseqid = parts[1]
        pident = float(parts[2])
        length = int(parts[3])
        evalue = float(parts[10])
        bitscore = float(parts[11])

        # Parse cluster_id from query (format: "cluster_123|len=456")
        cluster_id = None
        if qseqid.startswith("cluster_"):
            cluster_id = int(qseqid.split("_")[1].split("|")[0])

        # Parse PHI-base entry (format: "UniProtID#PHI:ID#Gene#TaxID#Organism#Phenotype")
        phi_parts = sseqid.split("#")
        phi_accession = phi_parts[0] if len(phi_parts) > 0 else sseqid
        phi_id = phi_parts[1] if len(phi_parts) > 1 else ""
        phi_gene = phi_parts[2] if len(phi_parts) > 2 else ""
        phi_organism = phi_parts[3] if len(phi_parts) > 3 else ""
        phi_phenotype = "#".join(phi_parts[4:]) if len(phi_parts) > 4 else ""

        # Query coverage
        qstart = int(parts[6])
        qend = int(parts[7])
        # Calculate query coverage from the query header
        qlen = None
        if "len=" in qseqid:
            qlen = int(qseqid.split("len=")[1])
        query_coverage = ((qend - qstart + 1) / qlen * 100) if qlen else 0

        # Apply coverage filter
        if query_coverage < MIN_COVERAGE:
            continue
        if pident < MIN_IDENTITY:
            continue

        # Deduplicate: keep best hit per cluster per PHI entry
        key = (cluster_id, phi_id)
        if key in seen_pairs:
            continue
        seen_pairs.add(key)

        hits.append({
            "cluster_id": cluster_id,
            "phi_accession": phi_accession,
            "phi_id": phi_id,
            "phi_gene": phi_gene,
            "phi_organism": phi_organism,
            "phi_phenotype": phi_phenotype,
            "identity": pident,
            "alignment_length": length,
            "evalue": evalue,
            "bit_score": bitscore,
            "query_coverage": query_coverage,
            "qseqid": qseqid,
        })

    # Sort by evalue, keep best per cluster
    hits.sort(key=lambda x: (x["cluster_id"] or 0, x["evalue"]))

    return hits


def store_hits(conn: sqlite3.Connection, hits: list[dict]) -> int:
    """Store filtered hits in the database."""
    stored = 0
    # Delete existing hits if re-running (intentional: repopulating the entire staging table)
    conn.execute("DELETE FROM phi_base_hits")

    for h in hits:
        conn.execute(
            """
            INSERT INTO phi_base_hits
                (cluster_id, phi_accession, phi_id, phi_gene,
                 phi_organism, phi_phenotype, identity, alignment_length,
                 evalue, bit_score, query_coverage)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                h["cluster_id"], h["phi_accession"], h["phi_id"],
                h["phi_gene"], h["phi_organism"], h["phi_phenotype"],
                h["identity"], h["alignment_length"],
                h["evalue"], h["bit_score"], h["query_coverage"],
            ),
        )
        stored += 1

    conn.commit()
    return stored


def get_stats(conn: sqlite3.Connection) -> dict[str, Any]:
    """Get PHI-base matching coverage stats."""
    stats: dict[str, Any] = {}

    stats["total_clusters"] = conn.execute(
        "SELECT COUNT(*) FROM nr_protein_clusters"
    ).fetchone()[0]

    stats["total_hits"] = conn.execute(
        "SELECT COUNT(*) FROM phi_base_hits"
    ).fetchone()[0]

    stats["clusters_with_hits"] = conn.execute(
        "SELECT COUNT(DISTINCT cluster_id) FROM phi_base_hits"
    ).fetchone()[0]

    if stats["clusters_with_hits"] > 0:
        # Phenotype distribution
        pheno_rows = conn.execute("""
            SELECT phi_phenotype, COUNT(DISTINCT cluster_id) as cnt
            FROM phi_base_hits
            GROUP BY phi_phenotype
            ORDER BY cnt DESC
            LIMIT 20
        """).fetchall()
        stats["phenotype_distribution"] = {r[0]: r[1] for r in pheno_rows}

        # Organism distribution (PHI-base source organisms)
        org_rows = conn.execute("""
            SELECT phi_organism, COUNT(DISTINCT cluster_id) as cnt
            FROM phi_base_hits
            GROUP BY phi_organism
            ORDER BY cnt DESC
            LIMIT 15
        """).fetchall()
        stats["phi_organism_distribution"] = {r[0]: r[1] for r in org_rows}

        # Hits by virus (via cluster -> protein -> isolate -> virus_master)
        virus_rows = conn.execute("""
            SELECT vm.canonical_name, COUNT(DISTINCT ph.cluster_id) as cnt
            FROM phi_base_hits ph
            JOIN viral_proteins_nr vpn ON ph.cluster_id = vpn.cluster_id
            JOIN reannotated_orfs ro ON vpn.reanno_id = ro.reanno_id
            JOIN viral_isolates vi ON ro.isolate_id = vi.isolate_id
            JOIN virus_master vm ON vi.master_id = vm.master_id
            GROUP BY vm.canonical_name
            ORDER BY cnt DESC
            LIMIT 15
        """).fetchall()
        stats["virus_distribution"] = {r[0]: r[1] for r in virus_rows}

        # Identity distribution
        ident_rows = conn.execute("""
            SELECT
                SUM(CASE WHEN identity >= 70 THEN 1 ELSE 0 END) as high,
                SUM(CASE WHEN identity >= 50 AND identity < 70 THEN 1 ELSE 0 END) as medium,
                SUM(CASE WHEN identity >= 30 AND identity < 50 THEN 1 ELSE 0 END) as low,
                SUM(CASE WHEN identity < 30 THEN 1 ELSE 0 END) as very_low
            FROM phi_base_hits
        """).fetchone()
        stats["identity_distribution"] = {
            "high (>=70%)": ident_rows[0],
            "medium (50-70%)": ident_rows[1],
            "low (30-50%)": ident_rows[2],
            "very_low (<30%)": ident_rows[3],
        }

        # Average identity and evalue
        stats["avg_identity"] = round(
            conn.execute("SELECT AVG(identity) FROM phi_base_hits").fetchone()[0], 1
        )

        # Top PHI genes matched
        gene_rows = conn.execute("""
            SELECT phi_gene, COUNT(DISTINCT cluster_id) as cnt
            FROM phi_base_hits
            WHERE phi_gene != ''
            GROUP BY phi_gene
            ORDER BY cnt DESC
            LIMIT 20
        """).fetchall()
        stats["top_phi_genes"] = {r[0]: r[1] for r in gene_rows}

    return stats


def print_stats(stats: dict[str, Any]) -> None:
    """Print PHI-base matching stats in Chinese."""
    print()
    print("=" * 60)
    print("PHI-base 病原-宿主互作匹配结果")
    print("=" * 60)

    total = stats["total_clusters"]
    with_hits = stats["clusters_with_hits"]
    print(f"\n  总蛋白簇数:              {total}")
    print(f"  匹配到 PHI-base 的簇数:  {with_hits}")
    print(f"  总比对命中数:            {stats['total_hits']}")
    if total > 0:
        print(f"  覆盖率:                  {with_hits/total*100:.2f}%")

    if with_hits == 0:
        print("\n  无匹配结果")
        return

    if "avg_identity" in stats:
        print(f"\n  平均序列一致性:          {stats['avg_identity']}%")

    print(f"\n【序列一致性分布】")
    for k, v in stats.get("identity_distribution", {}).items():
        print(f"  {k:20s} {v}")

    print(f"\n【表型分布 Top 10】")
    for pheno, cnt in list(stats.get("phenotype_distribution", {}).items())[:10]:
        short = pheno[:50] if len(pheno) > 50 else pheno
        print(f"  {short:50s} {cnt}")

    print(f"\n【匹配的病毒 Top 10】")
    for virus, cnt in list(stats.get("virus_distribution", {}).items())[:10]:
        print(f"  {virus[:45]:45s} {cnt}")

    print(f"\n【PHI 基因 Top 10】")
    for gene, cnt in list(stats.get("top_phi_genes", {}).items())[:10]:
        print(f"  {gene[:40]:40s} {cnt}")


def export_json(stats: dict[str, Any]) -> Path:
    """Export stats to JSON."""
    out_dir = BASE_DIR / "downloads"
    out_dir.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = out_dir / f"phi_base_enrich_{stamp}.json"

    data = {
        "script": "enrich_phi_base.py",
        "stats": {k: v for k, v in sorted(stats.items()) if not k.startswith("_")},
        "completed_at": datetime.now().isoformat(timespec="seconds"),
    }
    out_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_path


def main() -> None:
    import argparse

    # Allow override via environment
    global MIN_IDENTITY, PHI_BASE_DMND

    parser = argparse.ArgumentParser(description="PHI-base pathogen-host interaction matching")
    parser.add_argument("--diamond-only", action="store_true", help="Skip export, just align")
    parser.add_argument("--eval", type=float, default=DEFAULT_EVAL, help=f"E-value threshold (default: {DEFAULT_EVAL})")
    parser.add_argument("--min-identity", type=float, default=MIN_IDENTITY, help=f"Min identity % (default: {MIN_IDENTITY})")
    parser.add_argument("--stats", action="store_true", help="Show coverage stats only")
    args = parser.parse_args()

    MIN_IDENTITY = args.min_identity

    conn = sqlite3.connect(str(DB_PATH), timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")

    try:
        download_schema(conn)

        if args.stats:
            s = get_stats(conn)
            print_stats(s)
            return

        # Step 1: Export cluster sequences
        if not args.diamond_only:
            print("Step 1: Exporting cluster sequences...")
            count = export_cluster_sequences(conn)
            if count == 0:
                print("[error] No sequences exported!")
                return

        # Step 2: Build DIAMOND DB
        print("\nStep 2: Building DIAMOND database...")
        if not build_diamond_db():
            return

        # Step 3: Run DIAMOND
        print(f"\nStep 3: Running DIAMOND alignment (e-value={args.eval})...")
        if not run_diamond(evalue=args.eval):
            return

        # Step 4: Parse and store results
        print("\nStep 4: Parsing DIAMOND output...")
        hits = parse_diamond_output()
        print(f"  {len(hits)} hits after filtering (identity>={MIN_IDENTITY}%, coverage>={MIN_COVERAGE}%)")

        if hits:
            stored = store_hits(conn, hits)
            print(f"  {stored} hits stored in phi_base_hits table")

            # Export
            export_path = export_json(get_stats(conn))
            print(f"\n[export] Results saved to {export_path}")
        else:
            print("  No significant hits found")

        # Print stats
        final_stats = get_stats(conn)
        print_stats(final_stats)

    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
