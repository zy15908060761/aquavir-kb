"""Generate/refresh paper figures from current DB state."""
import sqlite3, os, sys
sys.stdout.reconfigure(encoding='utf-8')
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np

DB = os.path.join(os.path.dirname(__file__), 'crustacean_virus_core.db')
OUT = os.path.join(os.path.dirname(__file__), 'reports', 'figures')
os.makedirs(OUT, exist_ok=True)

conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row

ACTIVE = ("vm.is_crustacean_virus=1 AND vm.entry_type NOT IN "
          "('non_target','ictv_non_target','duplicate_ictv_vmr_placeholder',"
          "'duplicate_alias_placeholder','host_genome')")

# ═══════════════════════════════════════════════════════
# Fig 1: Evidence pyramid (high/medium/low + rejected)
# ═══════════════════════════════════════════════════════
def fig_evidence_pyramid():
    print("[1] Evidence pyramid...")

    levels = []
    for label, filt in [
        ('High\n(experimental)', "evidence_strength='high' AND curation_status!='rejected'"),
        ('Medium\n(molecular detection)', "evidence_strength='medium' AND curation_status!='rejected'"),
        ('Low\n(co-occurrence)', "evidence_strength='low' AND curation_status!='rejected'"),
        ('Rejected\n(quality filtered)', "curation_status='rejected'"),
    ]:
        n = conn.execute(f"SELECT COUNT(*) FROM evidence_records WHERE {filt}").fetchone()[0]
        pct = n / 353160 * 100
        levels.append((label, n, pct))

    fig, ax = plt.subplots(figsize=(8, 5))
    colors = ['#2ca02c', '#1f77b4', '#ff7f0e', '#d62728']
    labels = [f"{l}\nn={n:,} ({p:.1f}%)" for l, n, p in levels]
    sizes = [n for _, n, _ in levels]

    wedges, texts = ax.pie(sizes, labels=labels, colors=colors,
                           startangle=90, counterclock=False,
                           textprops={'fontsize': 11})
    ax.set_title('Evidence Strength Distribution\n(353,160 total records)', fontsize=14, fontweight='bold')

    fig.savefig(os.path.join(OUT, 'fig_evidence_pyramid.png'), dpi=200, bbox_inches='tight')
    fig.savefig(os.path.join(OUT, 'fig_evidence_pyramid.pdf'), bbox_inches='tight')
    plt.close()
    print(f"  Saved: fig_evidence_pyramid.png/pdf")

# ═══════════════════════════════════════════════════════
# Fig 2: Host phylum distribution (bar chart)
# ═══════════════════════════════════════════════════════
def fig_phylum_distribution():
    print("[2] Host phylum distribution...")

    rows = conn.execute(f"""
        SELECT host_phylum, COUNT(*) cnt FROM virus_master vm
        WHERE {ACTIVE} AND host_phylum NOT IN ('multiple','unknown')
        AND host_phylum IS NOT NULL AND host_phylum != ''
        GROUP BY host_phylum ORDER BY cnt DESC
    """).fetchall()

    fig, ax = plt.subplots(figsize=(10, 5))
    phyla = [r['host_phylum'] for r in rows]
    counts = [r['cnt'] for r in rows]
    colors = plt.cm.tab10(np.linspace(0, 1, len(phyla)))

    bars = ax.barh(range(len(phyla)), counts, color=colors)
    ax.set_yticks(range(len(phyla)))
    ax.set_yticklabels(phyla)
    ax.set_xlabel('Number of virus species')
    ax.set_title('Active Virus Species by Host Phylum\n(1,295 viruses with single-phylum assignment)',
                 fontsize=14, fontweight='bold')
    ax.invert_yaxis()

    for i, (bar, cnt) in enumerate(zip(bars, counts)):
        ax.text(bar.get_width() + 5, bar.get_y() + bar.get_height()/2,
                str(cnt), va='center', fontsize=10)

    # Add multiple/unknown as annotation
    multi = conn.execute(f"SELECT COUNT(*) FROM virus_master vm WHERE {ACTIVE} AND host_phylum='multiple'").fetchone()[0]
    unknown = conn.execute(f"SELECT COUNT(*) FROM virus_master vm WHERE {ACTIVE} AND host_phylum='unknown'").fetchone()[0]
    ax.text(0.98, 0.02, f'Multiple phyla: {multi}\nUnknown: {unknown}',
            transform=ax.transAxes, ha='right', fontsize=10, style='italic',
            bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.5))

    fig.tight_layout()
    fig.savefig(os.path.join(OUT, 'fig_phylum_distribution.png'), dpi=200, bbox_inches='tight')
    fig.savefig(os.path.join(OUT, 'fig_phylum_distribution.pdf'), bbox_inches='tight')
    plt.close()
    print(f"  Saved: fig_phylum_distribution.png/pdf")

# ═══════════════════════════════════════════════════════
# Fig 3: Top 15 families
# ═══════════════════════════════════════════════════════
def fig_top_families():
    print("[3] Top families...")

    rows = conn.execute(f"""
        SELECT virus_family, COUNT(*) cnt FROM virus_master vm
        WHERE {ACTIVE} AND virus_family IS NOT NULL AND virus_family != ''
        AND virus_family != 'Unclassified'
        GROUP BY virus_family ORDER BY cnt DESC LIMIT 15
    """).fetchall()

    fig, ax = plt.subplots(figsize=(10, 6))
    families = [r['virus_family'] for r in reversed(rows)]
    counts = [r['cnt'] for r in reversed(rows)]
    colors = plt.cm.tab20(np.linspace(0, 1, len(families)))

    bars = ax.barh(range(len(families)), counts, color=colors)
    ax.set_yticks(range(len(families)))
    ax.set_yticklabels(families, fontsize=9)
    ax.set_xlabel('Number of virus species')
    ax.set_title('Top 15 Viral Families in AquaVir-KB', fontsize=14, fontweight='bold')

    for bar, cnt in zip(bars, counts):
        ax.text(bar.get_width() + 2, bar.get_y() + bar.get_height()/2,
                str(cnt), va='center', fontsize=9)

    fig.tight_layout()
    fig.savefig(os.path.join(OUT, 'fig_top_families.png'), dpi=200, bbox_inches='tight')
    fig.savefig(os.path.join(OUT, 'fig_top_families.pdf'), bbox_inches='tight')
    plt.close()
    print(f"  Saved: fig_top_families.png/pdf")

# ═══════════════════════════════════════════════════════
# Fig 4: Evidence type distribution
# ═══════════════════════════════════════════════════════
def fig_evidence_types():
    print("[4] Evidence types...")

    rows = conn.execute("""
        SELECT evidence_type, COUNT(*) cnt FROM evidence_records
        WHERE curation_status != 'rejected'
        GROUP BY evidence_type ORDER BY cnt DESC
    """).fetchall()

    fig, ax = plt.subplots(figsize=(10, 5))
    types = [r['evidence_type'].replace('_',' ').title() for r in rows]
    counts = [r['cnt'] for r in rows]
    colors = plt.cm.Set2(np.linspace(0, 1, len(types)))

    bars = ax.bar(range(len(types)), counts, color=colors)
    ax.set_xticks(range(len(types)))
    ax.set_xticklabels(types, rotation=45, ha='right', fontsize=9)
    ax.set_ylabel('Number of evidence records')
    ax.set_title('Evidence Records by Type (350,716 effective)', fontsize=14, fontweight='bold')
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, p: f'{x/1000:.0f}k'))

    for bar, cnt in zip(bars, counts):
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 500,
                f'{cnt:,}', ha='center', fontsize=7, rotation=90)

    fig.tight_layout()
    fig.savefig(os.path.join(OUT, 'fig_evidence_types.png'), dpi=200, bbox_inches='tight')
    fig.savefig(os.path.join(OUT, 'fig_evidence_types.pdf'), bbox_inches='tight')
    plt.close()
    print(f"  Saved: fig_evidence_types.png/pdf")

# ═══════════════════════════════════════════════════════
# Fig 5: Curation status breakdown
# ═══════════════════════════════════════════════════════
def fig_curation_status():
    print("[5] Curation status...")

    rows = conn.execute("""
        SELECT curation_status, COUNT(*) cnt FROM evidence_records
        GROUP BY curation_status ORDER BY cnt DESC
    """).fetchall()

    fig, ax = plt.subplots(figsize=(7, 5))
    labels = [f"{r['curation_status'].replace('_',' ').title()}\n{r['cnt']:,}" for r in rows]
    sizes = [r['cnt'] for r in rows]
    colors = {'manual_checked': '#2ca02c', 'auto_imported': '#1f77b4',
              'needs_review': '#ff7f0e', 'rejected': '#d62728'}
    cs = [colors.get(r['curation_status'], '#999') for r in rows]

    wedges, texts = ax.pie(sizes, labels=labels, colors=cs, startangle=90,
                           textprops={'fontsize': 11})
    ax.set_title('Evidence Curation Status\n(353,160 total records)', fontsize=14, fontweight='bold')

    fig.savefig(os.path.join(OUT, 'fig_curation_status.png'), dpi=200, bbox_inches='tight')
    fig.savefig(os.path.join(OUT, 'fig_curation_status.pdf'), bbox_inches='tight')
    plt.close()
    print(f"  Saved: fig_curation_status.png/pdf")

# ═══════════════════════════════════════════════════════
# Fig 6: Genome type distribution
# ═══════════════════════════════════════════════════════
def fig_genome_types():
    print("[6] Genome types...")

    rows = conn.execute(f"""
        SELECT genome_type, COUNT(*) cnt FROM virus_master vm
        WHERE {ACTIVE} AND genome_type IS NOT NULL AND genome_type != ''
        GROUP BY genome_type ORDER BY cnt DESC
    """).fetchall()

    fig, ax = plt.subplots(figsize=(8, 5))
    gts = [r['genome_type'] for r in rows]
    counts = [r['cnt'] for r in rows]
    colors = plt.cm.tab10(np.linspace(0, 1, len(gts)))

    bars = ax.bar(range(len(gts)), counts, color=colors)
    ax.set_xticks(range(len(gts)))
    ax.set_xticklabels(gts, fontsize=10)
    ax.set_ylabel('Number of virus species')
    ax.set_title('Genome Type Distribution (1,631 classified active viruses)',
                 fontsize=14, fontweight='bold')

    for bar, cnt in zip(bars, counts):
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 3,
                str(cnt), ha='center', fontsize=10)

    fig.tight_layout()
    fig.savefig(os.path.join(OUT, 'fig_genome_types.png'), dpi=200, bbox_inches='tight')
    fig.savefig(os.path.join(OUT, 'fig_genome_types.pdf'), bbox_inches='tight')
    plt.close()
    print(f"  Saved: fig_genome_types.png/pdf")

# ═══════════════════════════════════════════════════════
# RUN
# ═══════════════════════════════════════════════════════
try:
    fig_evidence_pyramid()
    fig_phylum_distribution()
    fig_top_families()
    fig_evidence_types()
    fig_curation_status()
    fig_genome_types()
    print("\nAll figures regenerated successfully.")
except Exception as e:
    print(f"\nERROR: {e}")
    import traceback
    traceback.print_exc()
finally:
    conn.close()
