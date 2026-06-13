"""
Publication-quality RdRp phylogenetic tree.
Circular layout, colored by 18 families, novel lineage candidates highlighted.
Uses ete3 for tree rendering + matplotlib for annotations.
"""
import sys, os
from pathlib import Path
from collections import defaultdict

PROJ = Path(r"F:\水生无脊椎动物数据库")
TREE_FILE = PROJ / "blastdb" / "rdrp_fasttree.nwk"
CLASS_FILE = PROJ / "blastdb" / "final_classification.tsv"
OUTPUT = PROJ / "reports" / "rdrp_tree.png"

# Family colors (18 families + Unclassified)
FAMILY_COLORS = {
    'Nodaviridae':        '#E41A1C',  # red
    'Roniviridae':        '#377EB8',  # blue
    'Sedoreoviridae':     '#4DAF4A',  # green
    'Yanviridae':         '#984EA3',  # purple
    'Chuviridae':         '#FF7F00',  # orange
    'Astroviridae':       '#FFFF33',  # yellow
    'Marnaviridae':       '#A65628',  # brown
    'Phenuiviridae':      '#F781BF',  # pink
    'Narnaviridae':       '#66C2A5',  # teal
    'Picornaviridae':     '#FC8D62',  # salmon
    'Aparvoviridae':      '#8DA0CB',  # lavender
    'Bunyaviridae':       '#E78AC3',  # rose
    'Rhabdoviridae':      '#A6D854',  # lime
    'Dicistroviridae':    '#FFD92F',  # gold
    'Yueviridae':         '#B3B3B3',  # gray
    'Negevirus':          '#1B9E77',  # dark teal
    'Totiviridae':        '#D95F02',  # dark orange
    'Unclassified':       '#999999',  # medium gray
}


def load_classifications():
    """Load final classifications, return {seq_id: {family, confidence}}."""
    import csv
    cls = {}
    with open(CLASS_FILE, encoding='utf-8') as f:
        for row in csv.DictReader(f, delimiter='\t'):
            cls[row['sequence_id']] = row
    return cls


def reduce_tree_for_display(tree_str, max_leaves=300):
    """
    If tree has too many leaves, collapse high-confidence clades.
    For publication, we want to show all 1057 taxa, so we keep all.
    """
    return tree_str


def plot_tree():
    """Main plotting function using ete3."""
    try:
        from ete3 import Tree, TreeStyle, NodeStyle, TextFace, faces, AttrFace
    except ImportError:
        print("ete3 not installed. Install with: pip install ete3")
        return

    cls = load_classifications()
    print(f"Loaded {len(cls)} classifications")

    # Read tree
    with open(TREE_FILE) as f:
        tree_str = f.read().strip()

    # Parse tree
    print("Parsing tree (this may take a moment for 1057 taxa)...")
    tree = Tree(tree_str, format=1)  # format 1 = internal node support

    # Assign family to each leaf
    print("Annotating leaves...")
    family_counts = defaultdict(int)
    for leaf in tree.iter_leaves():
        short_id = leaf.name.split('|')[0]
        info = cls.get(short_id, {})
        fam = info.get('assigned_family', 'Unknown')
        conf = info.get('final_confidence', 'low')
        leaf.add_features(family=fam, confidence=conf, short_id=short_id)
        family_counts[fam] += 1

    print(f"Family distribution in tree: {dict(family_counts)}")

    # Set leaf colors by family
    for leaf in tree.iter_leaves():
        fam = leaf.family
        color = FAMILY_COLORS.get(fam, '#000000')

        # Novel lineage candidates: Unclassified + high confidence → bold red border
        is_novel = (fam == 'Unclassified' and leaf.confidence == 'high')

        nstyle = NodeStyle()
        nstyle['fgcolor'] = color
        nstyle['size'] = 3 if not is_novel else 8
        nstyle['hz_line_color'] = color
        nstyle['vt_line_color'] = color

        if is_novel:
            # Red star-like node for novel candidates
            nstyle['fgcolor'] = '#FF0000'
            nstyle['size'] = 8
            nstyle['hz_line_width'] = 2
            nstyle['vt_line_width'] = 2

        leaf.set_style(nstyle)

        # Add label only for well-known or novel taxa
        if is_novel or leaf.short_id in get_notable_ids():
            leaf.add_face(TextFace(leaf.short_id, fgcolor=color, fsize=6),
                          column=0, position='aligned')

    # Tree style
    ts = TreeStyle()
    ts.mode = 'c'  # circular
    ts.show_leaf_name = False
    ts.show_scale = True
    ts.scale = 200  # pixels per branch length unit
    ts.optimal_scale_level = 'full'
    ts.branch_vertical_margin = 0
    ts.arc_start = -90
    ts.arc_span = 360
    ts.title.add_face(TextFace("RdRp Phylogeny of Aquatic Invertebrate Viruses",
                                fsize=16, bold=True), column=0)

    # Legend (simplified)
    ts.legend_position = 4  # top-right

    # Render
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    print(f"Rendering to {OUTPUT}...")
    tree.render(str(OUTPUT), w=3600, h=3600, units='px', tree_style=ts, dpi=300)
    print(f"Tree saved to: {OUTPUT}")

    # Also save smaller preview
    preview = str(OUTPUT).replace('.png', '_preview.png')
    tree.render(preview, w=1200, h=1200, units='px', tree_style=ts, dpi=150)
    print(f"Preview saved to: {preview}")


def get_notable_ids():
    """Return set of interesting sequence IDs to label."""
    return {
        # Novel lineage candidates (Unclassified + high)
        'APG78067.1', 'YP_009330273.1',
        # Key known reference sequences
        'AAD43030.1',  # Roniviridae ref
        'YP_009666324.1',  # Roniviridae ref
        'ACJ12846.1',  # Totiviridae ref
        'APG76113.1',  # Beihai shrimp virus
        'YP_009337345.1',  # Beihai crab virus
        'APG77704.1',  # Wenzhou shrimp virus
    }


def plot_simple_matplotlib():
    """
    Fallback: simpler matplotlib-based tree visualization.
    Works without ete3 but limited to rectangular layout.
    """
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import numpy as np
    import re

    print("Using matplotlib fallback renderer...")

    # Parse Newick tree to get basic structure
    with open(TREE_FILE) as f:
        tree_str = f.read().strip()

    # Extract taxa and their positions in the tree string
    # For a circular layout, use a simple approach: layout taxa by tree order
    taxa = re.findall(r'([A-Za-z0-9_\-\.|]+):(\d+\.?\d*(?:e[+-]?\d+)?)', tree_str)

    cls = load_classifications()

    n = len(taxa)
    print(f"Tree has {n} taxa")

    # Create figure
    fig, ax = plt.subplots(1, 1, figsize=(24, 24), subplot_kw={'projection': None})
    ax.set_aspect('equal')

    # Position taxa in a circle
    radius = 10
    angles = np.linspace(0, 2 * np.pi, n, endpoint=False)

    # Draw family-colored dots
    for i, (name, blen) in enumerate(taxa):
        short_id = name.split('|')[0]
        info = cls.get(short_id, {})
        fam = info.get('assigned_family', 'Unknown')
        conf = info.get('final_confidence', 'low')

        color = FAMILY_COLORS.get(fam, '#000000')
        alpha = 1.0 if conf == 'high' else 0.6 if conf == 'medium' else 0.3
        size = 15 if conf == 'high' else 8 if conf == 'medium' else 3

        x = radius * np.cos(angles[i])
        y = radius * np.sin(angles[i])

        is_novel = (fam == 'Unclassified' and conf == 'high')
        if is_novel:
            ax.scatter(x, y, s=80, c='red', marker='*', zorder=10, edgecolors='darkred', linewidths=1)
        else:
            ax.scatter(x, y, s=size, c=color, alpha=alpha, edgecolors='none')

        # Label notable taxa
        if is_novel or short_id in get_notable_ids():
            ax.annotate(short_id, (x, y), fontsize=4, rotation=np.degrees(angles[i]),
                        ha='center', va='bottom')

    # Draw concentric rings
    for r in [radius * 0.33, radius * 0.66, radius]:
        circle = plt.Circle((0, 0), r, fill=False, color='lightgray', linewidth=0.5)
        ax.add_patch(circle)

    # Legend
    legend_elements = []
    for fam, color in FAMILY_COLORS.items():
        if fam in ['Unclassified']:
            continue
        legend_elements.append(plt.Line2D([0], [0], marker='o', color='w',
                                          markerfacecolor=color, markersize=10, label=fam))
    # Novel candidates
    legend_elements.append(plt.Line2D([0], [0], marker='*', color='w',
                                      markerfacecolor='red', markersize=12, label='Novel candidate'))
    ax.legend(handles=legend_elements, loc='upper right', fontsize=7, ncol=2,
              bbox_to_anchor=(1.15, 1.0))

    ax.set_xlim(-radius * 1.3, radius * 1.3)
    ax.set_ylim(-radius * 1.3, radius * 1.3)
    ax.axis('off')
    ax.set_title('RdRp Phylogeny of Aquatic Invertebrate Viruses\n(1057 taxa, 18 families, FastTree LG+Gamma)',
                 fontsize=14, fontweight='bold', pad=20)

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    plt.tight_layout()
    plt.savefig(str(OUTPUT), dpi=200, bbox_inches='tight', facecolor='white')
    plt.close()
    print(f"Tree saved to: {OUTPUT}")

    # Family legend
    fig2, ax2 = plt.subplots(figsize=(12, 6))
    ax2.axis('off')
    summary_text = "Family Distribution:\n\n"
    fam_counts = defaultdict(int)
    conf_counts = defaultdict(lambda: defaultdict(int))
    for name, blen in taxa:
        short_id = name.split('|')[0]
        info = cls.get(short_id, {})
        fam = info.get('assigned_family', 'Unknown')
        conf = info.get('final_confidence', 'low')
        fam_counts[fam] += 1
        conf_counts[fam][conf] += 1

    for fam, cnt in sorted(fam_counts.items(), key=lambda x: -x[1]):
        h = conf_counts[fam].get('high', 0)
        m = conf_counts[fam].get('medium', 0)
        l = conf_counts[fam].get('low', 0)
        summary_text += f"  {fam}: {cnt} (H={h} M={m} L={l})\n"

    ax2.text(0.1, 0.9, summary_text, fontsize=10, fontfamily='monospace',
             transform=ax2.transAxes, verticalalignment='top')
    ax2.set_title('RdRp Classification Summary', fontsize=14, fontweight='bold')
    legend_out = str(OUTPUT).replace('.png', '_legend.png')
    plt.savefig(legend_out, dpi=150, bbox_inches='tight', facecolor='white')
    plt.close()
    print(f"Legend saved to: {legend_out}")


if __name__ == '__main__':
    # Try ete3 first, fall back to matplotlib
    try:
        plot_tree()
    except Exception as e:
        print(f"ete3 rendering failed: {e}")
        print("Falling back to matplotlib...")
        try:
            plot_simple_matplotlib()
        except Exception as e2:
            print(f"matplotlib also failed: {e2}")
            sys.exit(1)
