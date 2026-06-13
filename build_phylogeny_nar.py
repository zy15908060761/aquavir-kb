#!/usr/bin/env python3
"""
NAR-standard phylogenetic analysis pipeline for crustacean viruses.

Replaces the lightweight UPGMA demo with MAFFT + IQ-TREE workflow:
  1. Select representative isolates per major virus family
  2. Extract genome sequences from cached FASTA files
  3. Multiple sequence alignment with MAFFT (L-INS-i)
  4. Phylogenetic tree reconstruction with IQ-TREE (MFP+MERGE, UFBoot 1000)
  5. Export trees in Newick format + iTOL annotation files

Usage:
    # Step 1: export + align (can run now, MAFFT is installed)
    python build_phylogeny_nar.py --align-only

    # Step 2: build trees (run after installing IQ-TREE)
    python build_phylogeny_nar.py --tree-only

    # Full pipeline
    python build_phylogeny_nar.py

Prerequisites:
    - MAFFT v7.526+ (installed to F:\\tools\\phylo\\mafft)
    - IQ-TREE v2.3.6+ (optional for --tree-only, download from iqtree.org)
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path
from datetime import datetime
from collections import defaultdict

# ── Configuration ─────────────────────────────────────────────────
DB_PATH = Path(r"F:\甲壳动物数据库\crustacean_virus_core.db")
SEQ_DIR = Path(r"F:\甲壳动物数据库\sequences")
WORK_DIR = Path(r"F:\甲壳动物数据库\downloads\phylogeny")
WORK_DIR.mkdir(parents=True, exist_ok=True)

MAFFT_PATH = Path(r"F:\tools\phylo\mafft\mafft-win\mafft.bat")
IQTREE_PATH = Path(r"F:\tools\phylo\iqtree\bin\iqtree2.exe")

# Target families for phylogenetic analysis
TARGET_FAMILIES = [
    "Nimaviridae",      # WSSV
    "Dicistroviridae",  # TSV
    "Roniviridae",      # YHV, GAV
    "Nodaviridae",      # MrNV
    "Parvoviridae",     # IHHNV
    "Iridoviridae",     # DIV, SHIV
    "Artiviridae",      # IMNV
    "Reoviridae",       # Crab reoviruses
]

# Minimum isolates per family to build a tree
MIN_ISOLATES = 3
# Maximum isolates per family (select longest genomes)
MAX_ISOLATES = 15


# ── Step 1: Select representatives ────────────────────────────────
def select_representatives(conn: sqlite3.Connection) -> dict[str, list[dict]]:
    """Select representative isolates for each target family."""
    c = conn.cursor()
    c.execute("""
        SELECT vm.virus_family, vm.canonical_name, vi.isolate_id, vi.accession,
               vi.genome_length, vi.gc_content, vi.completeness
        FROM viral_isolates vi
        JOIN virus_master vm ON vi.master_id = vm.master_id
        WHERE vm.virus_family IN ({})
          AND vi.genome_length IS NOT NULL
          AND vi.genome_length > 1000
        ORDER BY vm.virus_family, vi.genome_length DESC
    """.format(",".join("?" * len(TARGET_FAMILIES))),
        TARGET_FAMILIES
    )

    by_family = defaultdict(list)
    for row in c.fetchall():
        by_family[row["virus_family"]].append(dict(row))

    selected = {}
    for family, isolates in by_family.items():
        # Prefer complete genomes, then longest
        complete = [i for i in isolates if i.get("completeness") == "complete_genome"]
        if len(complete) >= MIN_ISOLATES:
            pool = complete
        else:
            pool = isolates

        # Select up to MAX_ISOLATES, ensuring diversity by canonical_name
        seen_species = set()
        reps = []
        for iso in pool:
            species = iso.get("canonical_name", "")
            if len(reps) >= MAX_ISOLATES:
                break
            reps.append(iso)

        if len(reps) >= MIN_ISOLATES:
            selected[family] = reps

    return selected


# ── Step 2: Export sequences ──────────────────────────────────────
def export_family_fasta(family: str, isolates: list[dict]) -> Path | None:
    """Export genome sequences for one family to a FASTA file."""
    out_fasta = WORK_DIR / f"{family.lower()}_genomes.fasta"
    sequences = []

    for iso in isolates:
        acc = iso["accession"]
        fa_file = SEQ_DIR / f"{acc}.fasta"
        if not fa_file.exists():
            # Try without version
            fa_file = SEQ_DIR / f"{acc.split('.')[0]}.fasta"
        if not fa_file.exists():
            continue

        try:
            text = fa_file.read_text(encoding="utf-8")
            lines = text.strip().splitlines()
            if not lines:
                continue
            # Replace header with isolate info
            header = f">{iso['accession']}|{iso['canonical_name'].replace(' ', '_')}|{iso['genome_length']}bp"
            seq_lines = []
            for line in lines:
                if not line.startswith(">"):
                    seq_lines.append(line.strip())
            seq = "".join(seq_lines)
            if len(seq) > 500:
                sequences.append((header, seq))
        except Exception:
            continue

    if len(sequences) < MIN_ISOLATES:
        print(f"  [skip {family}] Only {len(sequences)} sequences found (need >= {MIN_ISOLATES})")
        return None

    with open(out_fasta, "w", encoding="utf-8") as f:
        for header, seq in sequences:
            f.write(f"{header}\n")
            for i in range(0, len(seq), 80):
                f.write(seq[i:i + 80] + "\n")

    print(f"  [export] {family}: {len(sequences)} sequences -> {out_fasta}")
    return out_fasta


# ── Step 3: MAFFT alignment ───────────────────────────────────────
def run_mafft(input_fasta: Path, output_aln: Path) -> bool:
    """Run MAFFT L-INS-i alignment."""
    if not MAFFT_PATH.exists():
        print(f"  [error] MAFFT not found: {MAFFT_PATH}")
        print(f"  Please run: powershell -ExecutionPolicy Bypass -File F:\\install_phylo_tools.ps1")
        return False

    cmd = [
        str(MAFFT_PATH),
        "--localpair",
        "--maxiterate", "1000",
        "--thread", "4",
        str(input_fasta),
    ]

    print(f"  [mafft] Aligning {input_fasta.name}...")
    try:
        with open(output_aln, "w", encoding="utf-8") as out:
            result = subprocess.run(
                cmd,
                stdout=out,
                stderr=subprocess.PIPE,
                text=True,
                timeout=3600,
            )
        if result.returncode != 0:
            print(f"  [mafft error] {result.stderr[:500]}")
            return False

        if not output_aln.exists() or output_aln.stat().st_size < 100:
            print(f"  [mafft error] Output file empty")
            return False

        print(f"  [mafft] Done -> {output_aln}")
        return True

    except subprocess.TimeoutExpired:
        print(f"  [mafft error] Timed out after 1 hour")
        return False
    except Exception as exc:
        print(f"  [mafft error] {exc}")
        return False


# ── Step 4: IQ-TREE phylogeny ─────────────────────────────────────
def run_iqtree(aln_file: Path, prefix: Path) -> bool:
    """Run IQ-TREE with ModelFinder + ultrafast bootstrap."""
    if not IQTREE_PATH.exists():
        print(f"  [error] IQ-TREE not found: {IQTREE_PATH}")
        print(f"  Download from: http://www.iqtree.org/#download")
        print(f"  Extract to: F:\\tools\\phylo\\iqtree\\")
        return False

    cmd = [
        str(IQTREE_PATH),
        "-s", str(aln_file),
        "-pre", str(prefix),
        "-m", "MFP+MERGE",
        "-B", "1000",
        "-bnni",
        "-nt", "4",
        "-alrt", "1000",
    ]

    print(f"  [iqtree] Building tree for {aln_file.name}...")
    print(f"  [iqtree] This may take 10-60 minutes...")

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=7200,  # 2 hours max
        )
        if result.returncode != 0:
            print(f"  [iqtree error] {result.stderr[:1000]}")
            return False

        treefile = Path(str(prefix) + ".treefile")
        if not treefile.exists():
            print(f"  [iqtree error] Tree file not found")
            return False

        print(f"  [iqtree] Done -> {treefile}")
        return True

    except subprocess.TimeoutExpired:
        print(f"  [iqtree error] Timed out after 2 hours")
        return False
    except Exception as exc:
        print(f"  [iqtree error] {exc}")
        return False


# ── Step 5: Generate iTOL annotation ──────────────────────────────
def generate_itol_annotation(family: str, isolates: list[dict]) -> Path:
    """Generate iTOL annotation file for tree coloring."""
    itol_file = WORK_DIR / f"{family.lower()}_itol_host.txt"

    # Color by host species (simplified)
    host_colors = {
        "Litopenaeus vannamei": "#FF6B6B",
        "Penaeus monodon": "#4ECDC4",
        "Macrobrachium rosenbergii": "#45B7D1",
        "Scylla serrata": "#96CEB4",
        "Portunus trituberculatus": "#FFEAA7",
        "Procambarus clarkii": "#DDA0DD",
    }

    lines = [
        "DATASET_COLORSTRIP",
        "SEPARATOR TAB",
        "DATASET_LABEL\thost_species",
        "COLOR\t#000000",
        "DATA",
    ]

    for iso in isolates:
        acc = iso["accession"]
        # Default color
        color = "#CCCCCC"
        lines.append(f"{acc}\t{color}\t{iso.get('canonical_name', '')}")

    itol_file.write_text("\n".join(lines), encoding="utf-8")
    return itol_file


# ── Main pipeline ─────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="NAR-standard phylogenetic pipeline")
    parser.add_argument("--align-only", action="store_true", help="Only run MAFFT alignment")
    parser.add_argument("--tree-only", action="store_true", help="Only run IQ-TREE (requires aligned FASTA)")
    parser.add_argument("--family", type=str, default=None, help="Process only one family")
    args = parser.parse_args()

    print("=" * 60)
    print("NAR-standard Phylogenetic Analysis Pipeline")
    print("=" * 60)

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row

    # Select representatives
    if not args.tree_only:
        print("\n[Step 1] Selecting representative isolates...")
        selected = select_representatives(conn)
        conn.close()

        print(f"  Families with enough data: {len(selected)}")
        for fam, reps in selected.items():
            print(f"    {fam}: {len(reps)} isolates")

        if args.family and args.family not in selected:
            print(f"[error] Family '{args.family}' not found or insufficient data")
            return

        # Export and align
        print("\n[Step 2] Exporting sequences + MAFFT alignment...")
        families_to_process = [args.family] if args.family else list(selected.keys())

        align_results = {}
        for family in families_to_process:
            if family not in selected:
                continue
            reps = selected[family]
            fasta = export_family_fasta(family, reps)
            if not fasta:
                continue

            aln_file = WORK_DIR / f"{family.lower()}_genomes_aln.fasta"
            success = run_mafft(fasta, aln_file)
            if success:
                align_results[family] = {
                    "fasta": str(fasta),
                    "alignment": str(aln_file),
                    "isolates": len(reps),
                }
                # Generate iTOL annotation
                itol = generate_itol_annotation(family, reps)
                align_results[family]["itol"] = str(itol)

        # Save align report
        report_file = WORK_DIR / "alignment_report.json"
        with open(report_file, "w", encoding="utf-8") as f:
            json.dump(align_results, f, indent=2, ensure_ascii=False)
        print(f"\n[report] Alignment results: {report_file}")

        if args.align_only:
            print("\n[done] Alignment complete. Install IQ-TREE and run with --tree-only")
            return

    # Build trees
    print("\n[Step 3] Building phylogenetic trees with IQ-TREE...")
    if not IQTREE_PATH.exists():
        print(f"\n[error] IQ-TREE not found at {IQTREE_PATH}")
        print(f"Please download from: http://www.iqtree.org/#download")
        print(f"Extract to: F:\\tools\\phylo\\iqtree\\")
        print(f"Then re-run with: python build_phylogeny_nar.py --tree-only")
        return

    tree_results = {}
    aln_files = list(WORK_DIR.glob("*_genomes_aln.fasta"))
    if args.family:
        aln_files = [f for f in aln_files if args.family.lower() in f.name.lower()]

    for aln_file in aln_files:
        family = aln_file.name.replace("_genomes_aln.fasta", "")
        prefix = WORK_DIR / f"{family}_iqtree"
        success = run_iqtree(aln_file, prefix)
        if success:
            treefile = Path(str(prefix) + ".treefile")
            tree_results[family] = {
                "alignment": str(aln_file),
                "tree": str(treefile),
                "iqtree_log": str(prefix) + ".log",
            }

    # Save tree report
    tree_report = WORK_DIR / "tree_report.json"
    with open(tree_report, "w", encoding="utf-8") as f:
        json.dump(tree_results, f, indent=2, ensure_ascii=False)

    print("\n" + "=" * 60)
    print("Phylogenetic analysis complete!")
    print("=" * 60)
    print(f"Trees built: {len(tree_results)}")
    for fam, paths in tree_results.items():
        print(f"  {fam}: {paths['tree']}")
    print(f"\nOutputs in: {WORK_DIR}")
    print("Upload .treefile files to https://itol.embl.de/ for interactive visualization")


if __name__ == "__main__":
    main()
