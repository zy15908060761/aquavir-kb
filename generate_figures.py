#!/usr/bin/env python3
"""P1-5: Generate publication-ready visualizations for AquaVir-KB.
1. RdRp circular phylogenetic tree (ETE3)
2. Global sampling map (matplotlib)
3. Host-virus Sankey diagram (plotly or matplotlib)
"""

import sqlite3
import os
from pathlib import Path

BASE = Path(__file__).resolve().parent
DB = BASE / "crustacean_virus_core.db"
OUT = BASE / "reports" / "figures"
OUT.mkdir(parents=True, exist_ok=True)

conn = sqlite3.connect(str(DB))
conn.row_factory = sqlite3.Row

# ═══════════════════════════════════════════════════════════════
# Figure 1: RdRp Phylogenetic Tree
# ═══════════════════════════════════════════════════════════════
def make_rdrp_tree():
    print("[1/3] RdRp phylogenetic tree...")
    try:
        from ete3 import Tree, TreeStyle, NodeStyle, TextFace
    except ImportError:
        print("  ete3 not available, skipping tree")
        return

    nwk_path = BASE / "blastdb" / "rdrp_fasttree.nwk"
    if not nwk_path.exists():
        print(f"  Tree file not found: {nwk_path}")
        return

    # Load classification data for coloring
    families = {}
    try:
        for row in conn.execute("SELECT sequence_id, predicted_family, final_confidence FROM rdrp_classification_v2"):
            families[row[0]] = (row[1], row[2])
    except:
        pass

    # Family colors
    family_colors = {
        'Nodaviridae': '#e41a1c', 'Roniviridae': '#377eb8',
        'Sedoreoviridae': '#4daf4a', 'Totiviridae': '#984ea3',
        'Chuviridae': '#ff7f00', 'Astroviridae': '#ffff33',
        'Marnaviridae': '#a65628', 'Phenuiviridae': '#f781bf',
        'Picornaviridae': '#66c2a5', 'Dicistroviridae': '#fc8d62',
        'Rhabdoviridae': '#8da0cb', 'Bunyaviridae': '#e78ac3',
        'Aparvoviridae': '#a6d854', 'Narnaviridae': '#ffd92f',
        'Yanviridae': '#e5c494', 'Yueviridae': '#b3b3b3',
        'Unclassified': '#999999', 'Negevirus': '#d9d9d9',
    }

    try:
        t = Tree(str(nwk_path))

        # Assign colors based on family
        for leaf in t.iter_leaves():
            name = leaf.name
            fam, conf = families.get(name, ('Unknown', 'Low'))
            color = family_colors.get(fam, '#cccccc')

            nstyle = NodeStyle()
            nstyle["fgcolor"] = color
            nstyle["size"] = 0
            leaf.set_style(nstyle)

            # Add family label
            if fam != 'Unknown':
                leaf.add_face(TextFace(f" {fam}", fgcolor=color, fsize=6), column=0)

        ts = TreeStyle()
        ts.mode = "c"  # circular
        ts.show_leaf_name = False
        ts.min_leaf_separation = 2
        ts.arc_start = -90
        ts.arc_span = 360
        ts.title.add_face(TextFace("AquaVir-KB RdRp Phylogeny", fsize=16), column=0)

        # Render to PNG
        out_png = str(OUT / "rdrp_tree.png")
        t.render(out_png, w=3000, h=3000, units="px", tree_style=ts, dpi=200)
        print(f"  Saved: {out_png}")

        # Also save PDF for publication
        out_pdf = str(OUT / "rdrp_tree.pdf")
        t.render(out_pdf, w=3000, h=3000, units="px", tree_style=ts, dpi=300)
        print(f"  Saved: {out_pdf}")
    except Exception as e:
        print(f"  Tree rendering failed: {e}")


# ═══════════════════════════════════════════════════════════════
# Figure 2: Global Sampling Map
# ═══════════════════════════════════════════════════════════════
def make_geo_map():
    print("[2/3] Global sampling map...")
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        import numpy as np
        from matplotlib.patches import Circle
    except ImportError:
        print("  matplotlib not available, skipping map")
        return

    # Get geographic data
    rows = conn.execute("""
        SELECT sc.latitude, sc.longitude, sc.country, COUNT(DISTINCT vi.master_id) as virus_count
        FROM sample_collections sc
        JOIN infection_records ir ON sc.collection_id = ir.collection_id
        JOIN viral_isolates vi ON ir.isolate_id = vi.isolate_id
        WHERE sc.latitude IS NOT NULL AND sc.longitude IS NOT NULL
        GROUP BY sc.latitude, sc.longitude
        HAVING virus_count > 0
    """).fetchall()

    if not rows:
        print("  No geo data available")
        return

    lats = [r['latitude'] for r in rows]
    lons = [r['longitude'] for r in rows]
    sizes = [max(5, min(200, r['virus_count'] * 5)) for r in rows]

    fig, ax = plt.subplots(figsize=(16, 10))

    # Draw world map outline (simplified)
    ax.set_xlim(-180, 180)
    ax.set_ylim(-90, 90)
    ax.set_xlabel('Longitude')
    ax.set_ylabel('Latitude')
    ax.set_title('AquaVir-KB Global Sampling Distribution', fontsize=16, fontweight='bold')
    ax.grid(True, alpha=0.3, linestyle='--')

    # Plot points colored by host phylum (simplified: use country regions)
    scatter = ax.scatter(lons, lats, s=sizes, c='#2196F3', alpha=0.6, edgecolors='#0D47A1', linewidth=0.5)

    # Add continent outlines (simple boxes)
    continents = {
        'Asia': (60, 110, -10, 75),
        'Europe': (-10, 40, 35, 70),
        'Africa': (-20, 50, -35, 35),
        'North America': (-130, -60, 15, 70),
        'South America': (-80, -35, -55, 10),
        'Australia': (110, 155, -40, -10),
    }
    for name, (x1, x2, y1, y2) in continents.items():
        rect = plt.Rectangle((x1, y1), x2-x1, y2-y1, fill=False, edgecolor='gray',
                             linewidth=0.5, linestyle=':', alpha=0.5)
        ax.add_patch(rect)
        ax.text((x1+x2)/2, (y1+y2)/2, name, ha='center', va='center',
                fontsize=7, color='gray', alpha=0.7)

    # Legend
    ax.text(0.02, 0.98, f'Total: {len(rows)} sampling locations\n{sum(r["virus_count"] for r in rows)} virus-location pairs',
            transform=ax.transAxes, fontsize=10, verticalalignment='top',
            bbox=dict(boxstyle='round', facecolor='white', alpha=0.8))

    plt.tight_layout()
    out_png = str(OUT / "geo_map.png")
    fig.savefig(out_png, dpi=200, bbox_inches='tight')
    out_pdf = str(OUT / "geo_map.pdf")
    fig.savefig(out_pdf, dpi=300, bbox_inches='tight')
    plt.close()
    print(f"  Saved: {out_png}")
    print(f"  Saved: {out_pdf}")


# ═══════════════════════════════════════════════════════════════
# Figure 3: Host-Virus Sankey Diagram
# ═══════════════════════════════════════════════════════════════
def make_sankey():
    print("[3/3] Host-virus Sankey diagram...")
    try:
        import plotly.graph_objects as go
        import plotly.io as pio
    except ImportError:
        print("  plotly not available, trying matplotlib sankey...")
        try:
            make_sankey_matplotlib()
        except:
            print("  Sankey generation failed")
        return

    # Build host phylum → virus family links
    rows = conn.execute("""
        SELECT v.host_phylum, v.virus_family, COUNT(DISTINCT v.master_id) as cnt
        FROM virus_master v
        WHERE v.entry_type != 'non_target'
          AND v.host_phylum IS NOT NULL AND v.host_phylum != ''
          AND v.virus_family IS NOT NULL AND v.virus_family != ''
        GROUP BY v.host_phylum, v.virus_family
        HAVING cnt >= 2
        ORDER BY cnt DESC
        LIMIT 50
    """).fetchall()

    if not rows:
        print("  No data for Sankey")
        return

    # Build nodes and links
    phyla = sorted(set(r['host_phylum'] for r in rows))
    families = sorted(set(r['virus_family'] for r in rows))

    # Filter to keep diagram manageable
    top_phyla = [p for p in phyla if sum(r['cnt'] for r in rows if r['host_phylum']==p) >= 5]
    top_families = [f for f in families if sum(r['cnt'] for r in rows if r['virus_family']==f) >= 3]

    all_nodes = top_phyla + top_families
    node_colors = (['#FF6B6B'] * len(top_phyla)) + (['#4ECDC4'] * len(top_families))

    source = []
    target = []
    value = []
    for r in rows:
        if r['host_phylum'] in all_nodes and r['virus_family'] in all_nodes:
            source.append(all_nodes.index(r['host_phylum']))
            target.append(all_nodes.index(r['virus_family']))
            value.append(r['cnt'])

    fig = go.Figure(data=[go.Sankey(
        node=dict(
            pad=15, thickness=20,
            line=dict(color="black", width=0.5),
            label=all_nodes,
            color=node_colors,
        ),
        link=dict(
            source=source, target=target, value=value,
            color='rgba(150,150,150,0.3)',
        )
    )])

    fig.update_layout(
        title="AquaVir-KB Host-Virus Associations",
        font=dict(size=10),
        width=1600, height=900,
    )

    out_html = str(OUT / "sankey_host_virus.html")
    pio.write_html(fig, file=out_html, auto_open=False)
    print(f"  Saved: {out_html}")

    # Also try PNG
    try:
        out_png = str(OUT / "sankey_host_virus.png")
        fig.write_image(out_png, width=1600, height=900, scale=2)
        print(f"  Saved: {out_png}")
    except:
        print("  (PNG requires kaleido, HTML only)")


def make_sankey_matplotlib():
    """Fallback: simple bar chart showing top host-virus associations."""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import numpy as np

    rows = conn.execute("""
        SELECT v.host_phylum, v.virus_family, COUNT(DISTINCT v.master_id) as cnt
        FROM virus_master v
        WHERE v.entry_type != 'non_target'
          AND v.host_phylum IS NOT NULL AND v.host_phylum != ''
          AND v.virus_family IS NOT NULL AND v.virus_family != ''
        GROUP BY v.host_phylum, v.virus_family
        HAVING cnt >= 3
        ORDER BY cnt DESC
        LIMIT 25
    """).fetchall()

    labels = [f"{r['host_phylum']} → {r['virus_family']}" for r in rows]
    values = [r['cnt'] for r in rows]

    fig, ax = plt.subplots(figsize=(14, 10))
    colors = plt.cm.viridis(np.linspace(0.1, 0.9, len(labels)))
    bars = ax.barh(range(len(labels)), values, color=colors)
    ax.set_yticks(range(len(labels)))
    ax.set_yticklabels(labels, fontsize=8)
    ax.set_xlabel('Number of Viruses')
    ax.set_title('AquaVir-KB: Top Host Phylum → Virus Family Associations', fontsize=14, fontweight='bold')
    ax.invert_yaxis()

    # Add value labels
    for bar, val in zip(bars, values):
        ax.text(bar.get_width() + 0.5, bar.get_y() + bar.get_height()/2,
                str(val), va='center', fontsize=8, fontweight='bold')

    plt.tight_layout()
    out_png = str(OUT / "host_virus_associations.png")
    fig.savefig(out_png, dpi=200, bbox_inches='tight')
    out_pdf = str(OUT / "host_virus_associations.pdf")
    fig.savefig(out_pdf, dpi=300, bbox_inches='tight')
    plt.close()
    print(f"  Saved: {out_png}")
    print(f"  Saved: {out_pdf}")


# ═══════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════
if __name__ == "__main__":
    print("AquaVir-KB Figure Generator")
    print(f"Output: {OUT}")
    print()
    make_rdrp_tree()
    make_geo_map()
    make_sankey()
    print("\nAll figures generated.")
    conn.close()
