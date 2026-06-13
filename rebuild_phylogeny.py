"""
重建系统发育树流水线
- RNA病毒：RDRP蛋白序列 → MAFFT → IQ-TREE (LG+G4, UFBoot 1000)
- DNA病毒：基因组核苷酸 → MAFFT → IQ-TREE (MFP, UFBoot 1000)
输出：contree + 环形SVG/PNG图 + iTOL注释文件
"""

import sqlite3
import subprocess
import os
import shutil
from pathlib import Path
from datetime import datetime
from collections import defaultdict

DB_PATH = Path(r"F:\甲壳动物数据库\crustacean_virus_core.db")
SEQ_DIR = Path(r"F:\甲壳动物数据库\sequences")
WORK_DIR = Path(r"F:\甲壳动物数据库\downloads\phylogeny")
FIG_DIR = WORK_DIR / "figures"
FIG_DIR.mkdir(parents=True, exist_ok=True)

MAFFT = r"F:\tools\phylo\mafft\mafft-win\mafft.bat"
IQTREE = r"F:\tools\phylo\iqtree\bin\iqtree2.exe"

MAX_ISOLATES = 50
MIN_ISOLATES = 3
THREADS = 4

HOST_COLORS = {
    "Litopenaeus vannamei": "#E74C3C", "Penaeus monodon": "#3498DB",
    "Macrobrachium rosenbergii": "#2ECC71", "Procambarus clarkii": "#E91E63",
    "Penaeus japonicus": "#FF9800", "Penaeus chinensis": "#00BCD4",
    "Penaeus stylirostris": "#9C27B0", "Fenneropenaeus indicus": "#607D8B",
    "Marsupenaeus japonicus": "#795548", "Cherax quadricarinatus": "#CDDC39",
    "Artemia salina": "#03A9F4", "Artemia sp.": "#03A9F4",
    "Scylla serrata": "#F39C12", "Portunus trituberculatus": "#9B59B6",
    "Callinectes sapidus": "#607D8B", "Homarus americanus": "#795548",
    "Charybdis japonica": "#FF5722", "Unknown": "#95A5A6",
}


def get_rdrp_families():
    """获取RDRP序列>=MIN的科列表"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""SELECT v.taxon_family, COUNT(DISTINCT vp.protein_id) as cnt
        FROM viral_proteins vp JOIN viral_isolates v ON vp.isolate_id = v.isolate_id
        WHERE vp.is_rdrp = 1 AND v.taxon_family IS NOT NULL AND v.taxon_family != ''
        GROUP BY v.taxon_family HAVING cnt >= ? ORDER BY cnt DESC""", (MIN_ISOLATES,))
    families = [(r[0], r[1]) for r in c.fetchall()]
    conn.close()
    return families


def get_genome_families():
    """获取基因组序列>=MIN的科列表（排除已有RDRP的）"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    rdrp_fams = set(f[0] for f in get_rdrp_families())
    c.execute("""SELECT taxon_family, COUNT(*) as cnt
        FROM viral_isolates WHERE has_sequence=1 AND genome_length > 500
        AND taxon_family IS NOT NULL AND taxon_family != ''
        GROUP BY taxon_family HAVING cnt >= ? ORDER BY cnt DESC""", (MIN_ISOLATES,))
    families = [(r[0], r[1]) for r in c.fetchall() if r[0] not in rdrp_fams]
    conn.close()
    return families


def extract_rdrp_sequences(family, max_seqs=MAX_ISOLATES):
    """提取某科的RDRP蛋白序列"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""SELECT v.accession, vp.protein_accession, vp.translation, vp.aa_length,
        vm.canonical_name, h.scientific_name
        FROM viral_proteins vp
        JOIN viral_isolates v ON vp.isolate_id = v.isolate_id
        JOIN virus_master vm ON v.master_id = vm.master_id
        LEFT JOIN infection_records ir ON v.isolate_id = ir.isolate_id
        LEFT JOIN crustacean_hosts h ON ir.host_id = h.host_id
        WHERE vp.is_rdrp = 1 AND v.taxon_family = ? AND vp.translation IS NOT NULL
        ORDER BY vp.aa_length DESC LIMIT ?""", (family, max_seqs))
    rows = c.fetchall()
    conn.close()
    return rows


def extract_genome_sequences(family, max_seqs=MAX_ISOLATES):
    """提取某科的基因组序列（从本地FASTA文件）"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""SELECT v.accession, v.genome_length, vm.canonical_name, h.scientific_name
        FROM viral_isolates v
        JOIN virus_master vm ON v.master_id = vm.master_id
        LEFT JOIN infection_records ir ON v.isolate_id = ir.isolate_id
        LEFT JOIN crustacean_hosts h ON ir.host_id = h.host_id
        WHERE v.taxon_family = ? AND v.has_sequence = 1 AND v.genome_length > 500
        ORDER BY v.genome_length DESC LIMIT ?""", (family, max_seqs))
    rows = c.fetchall()
    conn.close()

    seqs = []
    for acc, length, virus_name, host in rows:
        fa_file = SEQ_DIR / f"{acc}.fasta"
        if not fa_file.exists():
            continue
        try:
            from Bio import SeqIO
            record = next(SeqIO.parse(str(fa_file), "fasta"))
            seq_str = str(record.seq).upper()
            if seq_str:
                label = f"{acc}|{virus_name or ''}|{host or 'Unknown'}"
                seqs.append((label, seq_str[:50000]))
        except:
            continue
    return seqs


def write_fasta(sequences, outpath, is_protein=False):
    """写FASTA文件"""
    outpath = Path(outpath)
    with open(outpath, 'w', encoding='utf-8') as f:
        for label, seq in sequences:
            label_clean = label.replace(' ', '_').replace(',', '').replace(';', '').replace('(', '').replace(')', '')
            f.write(f'>{label_clean}\n')
            for i in range(0, len(seq), 60):
                f.write(f'{seq[i:i+60]}\n')
    return outpath


def write_itol_annotations(sequences, family, outpath):
    """写iTOL注释文件（宿主颜色）"""
    outpath = Path(outpath)
    with open(outpath, 'w', encoding='utf-8') as f:
        f.write("TREE_COLORS\nSEPARATOR TAB\nDATA\n")
        for label, _ in sequences:
            acc = label.split('|')[0]
            host = label.split('|')[-1] if '|' in label else 'Unknown'
            color = HOST_COLORS.get(host, HOST_COLORS.get('Unknown', '#95A5A6'))
            f.write(f"{acc}\tlabel\t{color}\t{host}\n")
    return outpath


def run_mafft(input_fasta, output_fasta, is_protein=False):
    """运行MAFFT比对"""
    cmd = [MAFFT, "--auto", "--thread", str(THREADS)]
    if is_protein:
        cmd = [MAFFT, "--localpair", "--maxiterate", "1000", "--thread", str(THREADS)]
    cmd.append(str(input_fasta))

    print(f"    MAFFT: {'protein' if is_protein else 'nucleotide'} alignment...")
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
        with open(output_fasta, 'w') as f:
            f.write(result.stdout)
        return output_fasta
    except Exception as e:
        print(f"    MAFFT ERROR: {e}")
        return None


def run_iqtree(aln_fasta, family_outbase, is_protein=False):
    """运行IQ-TREE建树"""
    cmd = [
        IQTREE, "-s", str(aln_fasta),
        "-m", "LG+G4" if is_protein else "MFP",
        "-B", "1000",
        "-alrt", "1000",
        "-nt", str(THREADS),
        "-pre", str(family_outbase),
        "-redo",
    ]
    print(f"    IQ-TREE: {'LG+G4' if is_protein else 'MFP'} + UFBoot 1000...")
    try:
        subprocess.run(cmd, capture_output=True, text=True, timeout=7200)
        return True
    except Exception as e:
        print(f"    IQ-TREE ERROR: {e}")
        return False


def generate_figure(family, contree_file, itol_file, seq_count):
    """生成环形树图"""
    try:
        from Bio import Phylo
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.patches as mpatches
        import numpy as np

        tree = Phylo.read(str(contree_file), "newick")

        # Parse host colors
        tip_colors = {}
        hosts = {}
        if Path(itol_file).exists():
            with open(itol_file, 'r') as f:
                in_data = False
                for line in f:
                    line = line.strip()
                    if line == "DATA": in_data = True; continue
                    if not in_data or not line: continue
                    parts = line.split("\t")
                    if len(parts) >= 4:
                        tip_colors[parts[0]] = parts[2]
                        hosts[parts[0]] = parts[3]

        # Build tree positions
        terminals = tree.get_terminals()
        n_tips = len(terminals)
        fig_height = max(8, n_tips * 0.35)
        fig, ax = plt.subplots(figsize=(14, fig_height))

        y_positions = {tip: i for i, tip in enumerate(terminals)}

        # Calculate x positions from root
        x_positions = {}

        def set_x(clade, x_start):
            x_positions[clade] = x_start
            for child in clade.clades:
                set_x(child, x_start + (child.branch_length or 0.001))
        set_x(tree.root, 0)

        max_x = max(x_positions.values()) if x_positions else 1

        def draw_clade(clade, x_start):
            x = x_positions.get(clade, x_start)
            if clade.is_terminal():
                y = y_positions.get(clade, 0)
                name = clade.name or ""
                acc = name.split('|')[0] if '|' in name else name
                color = tip_colors.get(acc, "#555555")
                ax.plot([x_start, x], [y, y], color="#666666", lw=1.0)
                ax.scatter([x], [y], c=color, s=40, zorder=5, edgecolors="white", linewidths=0.3)

                # Clean label
                parts = name.split('|')
                label = parts[1] if len(parts) > 1 else name
                if len(label) > 40:
                    label = label[:38] + '..'
                ax.text(x + max_x * 0.01, y, label, fontsize=8, va="center", ha="left",
                       family="monospace" if '|' not in name else "sans-serif")
            else:
                child_ys = []
                for child in clade.clades:
                    cy = draw_clade(child, x)
                    child_ys.append(cy)
                if child_ys:
                    y_min, y_max = min(child_ys), max(child_ys)
                    y_mid = (y_min + y_max) / 2
                    ax.plot([x, x], [y_min, y_max], color="#999999", lw=0.8)
                    ax.plot([x_start, x], [y_mid, y_mid], color="#999999", lw=0.8)

                    # Bootstrap
                    conf = None
                    if clade.confidence is not None:
                        conf = float(clade.confidence)
                    if conf is not None and conf >= 70:
                        ax.text(x, y_mid - 0.15, f"{conf:.0f}", fontsize=5, color="#888888", ha="center", va="bottom")
                    return y_mid
            return y_positions.get(clade, 0)

        draw_clade(tree.root, 0)

        ax.set_title(f"{family} ({n_tips} sequences)", fontsize=14, fontweight="bold")
        ax.set_xlabel("Branch length (substitutions/site)", fontsize=10)
        ax.set_ylabel("")
        ax.set_yticks([])
        for spine in ["top", "right", "left"]:
            ax.spines[spine].set_visible(False)

        # Legend
        used_hosts = set()
        for acc, host in hosts.items():
            if acc in tip_colors:
                used_hosts.add((host, tip_colors[acc]))
        if len(used_hosts) <= 12:
            patches = [mpatches.Patch(color=c, label=h) for h, c in sorted(used_hosts)]
            ax.legend(handles=patches, loc="lower right", fontsize=8, title="Host", title_fontsize=9)

        plt.tight_layout()
        png_path = FIG_DIR / f"{family}_tree.png"
        svg_path = FIG_DIR / f"{family}_tree.svg"
        plt.savefig(png_path, dpi=300, bbox_inches="tight")
        plt.savefig(svg_path, format="svg", bbox_inches="tight")
        plt.close()
        print(f"    Figure: {png_path.name} + {svg_path.name}")
        return True
    except Exception as e:
        print(f"    Figure error: {e}")
        return False


def build_family_rdrp(family, count):
    """用RDRP蛋白序列建树"""
    print(f"\n{'='*60}")
    print(f"[RDRP] {family} ({count} sequences)")
    print(f"{'='*60}")

    family_key = family.lower().replace(' ', '_')

    # Extract
    rows = extract_rdrp_sequences(family)
    sequences = [(f"{r[0]}|{r[4] or ''}|{r[5] or 'Unknown'}", r[2]) for r in rows if r[2]]
    if len(sequences) < MIN_ISOLATES:
        print(f"  Too few sequences ({len(sequences)}), skipping")
        return None
    print(f"  Extracted {len(sequences)} RDRP sequences")

    # Write
    fasta_file = WORK_DIR / f"{family_key}_rdrp.fasta"
    write_fasta(sequences, fasta_file, is_protein=True)

    # Align
    aln_file = WORK_DIR / f"{family_key}_rdrp_aln.fasta"
    if not run_mafft(fasta_file, aln_file, is_protein=True):
        return None

    # Tree
    outbase = WORK_DIR / f"{family_key}_rdrp_iqtree"
    if not run_iqtree(aln_file, outbase, is_protein=True):
        return None

    # iTOL annotations
    itol_file = WORK_DIR / f"{family_key}_itol_host.txt"
    write_itol_annotations(sequences, family, itol_file)

    # Rename contree for consistency
    contree = Path(str(outbase) + ".contree")
    if contree.exists():
        target = WORK_DIR / f"{family_key}_iqtree.contree"
        shutil.copy(contree, target)

    # Figure
    if contree.exists():
        generate_figure(family, target, itol_file, len(sequences))

    return contree


def build_family_genome(family, count):
    """用基因组核苷酸序列建树"""
    print(f"\n{'='*60}")
    print(f"[GENOME] {family} ({count} sequences)")
    print(f"{'='*60}")

    family_key = family.lower().replace(' ', '_')

    sequences = extract_genome_sequences(family)
    if len(sequences) < MIN_ISOLATES:
        print(f"  Too few sequences ({len(sequences)}), skipping")
        return None
    print(f"  Extracted {len(sequences)} genome sequences")

    fasta_file = WORK_DIR / f"{family_key}_genomes.fasta"
    write_fasta(sequences, fasta_file)

    aln_file = WORK_DIR / f"{family_key}_genomes_aln.fasta"
    if not run_mafft(fasta_file, aln_file, is_protein=False):
        return None

    outbase = WORK_DIR / f"{family_key}_genomes_iqtree"
    if not run_iqtree(aln_file, outbase, is_protein=False):
        return None

    itol_file = WORK_DIR / f"{family_key}_itol_host.txt"
    write_itol_annotations(sequences, family, itol_file)

    contree = Path(str(outbase) + ".contree")
    if contree.exists():
        target = WORK_DIR / f"{family_key}_iqtree.contree"
        shutil.copy(contree, target)

    if contree.exists():
        generate_figure(family, target, itol_file, len(sequences))

    return contree


def main():
    print("=" * 60)
    print("Phylogeny Rebuild Pipeline")
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    results = {"rdrp": [], "genome": [], "failed": []}

    # RDRP families
    rdrp_fams = get_rdrp_families()
    print(f"\nRDRP families to build: {len(rdrp_fams)}")
    for fam, count in rdrp_fams:
        result = build_family_rdrp(fam, count)
        if result:
            results["rdrp"].append(fam)
        else:
            results["failed"].append(fam)

    # Genome families (DNA viruses)
    genome_fams = get_genome_families()
    print(f"\nGenome families to build: {len(genome_fams)}")
    for fam, count in genome_fams:
        result = build_family_genome(fam, count)
        if result:
            results["genome"].append(fam)
        else:
            results["failed"].append(fam)

    # Summary
    print(f"\n{'='*60}")
    print("BUILD COMPLETE")
    print(f"  RDRP trees: {len(results['rdrp'])} families")
    print(f"  Genome trees: {len(results['genome'])} families")
    print(f"  Failed: {len(results['failed'])} families")
    if results['failed']:
        print(f"  Failed: {', '.join(results['failed'])}")

    # List all figures
    figs = sorted(FIG_DIR.glob("*_tree.png"))
    print(f"\n  Figures in {FIG_DIR}:")
    for f in figs:
        size_kb = f.stat().st_size / 1024
        print(f"    {f.name} ({size_kb:.0f} KB)")


if __name__ == "__main__":
    main()
