#!/usr/bin/env python3
"""
Submission-grade Graphical Abstract for NAR Database Issue.
AquaVir-KB: Aquatic Invertebrate Virus Knowledge Base

Panel composition (5:2 landscape):
  Left (30%):   Database overview with key stats
  Center (40%): Host phylum distribution (horizontal bar chart)
  Right (30%):  Evidence & Annotation layers (stacked bar / ICTV donut)
  Bottom strip: Key features row

Output: graphical_abstract.tif (300 dpi) + graphical_abstract.png (preview)
"""

import sqlite3, os, sys, warnings
warnings.filterwarnings("ignore")
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np
from matplotlib.font_manager import FontProperties, findfont, fontManager
import matplotlib.ticker as mticker
from PIL import Image

# ── Paths ──────────────────────────────────────────────────────────
BASE = os.path.dirname(os.path.abspath(__file__))
DB   = os.path.join(BASE, "crustacean_virus_core.db")
OUT_TIF = os.path.join(BASE, "graphical_abstract.tif")
OUT_PNG = os.path.join(BASE, "graphical_abstract.png")

# ── Colors ─────────────────────────────────────────────────────────
TEAL       = "#0f766e"   # primary accent
TEAL_LIGHT = "#14b8a6"
TEAL_DARK  = "#0b5e57"
TEAL_BG    = "#ecfdf5"   # very light teal bg blocks
GRAY_TEXT  = "#475569"
GRAY_MED   = "#94a3b8"
GRAY_LIGHT = "#e2e8f0"
WHITE      = "#ffffff"
BLACK      = "#1e293b"

# Evidence colors (teal gradient + complement)
EVI_COLORS = {
    "host_range":        "#0f766e",
    "diagnosis":         "#2dd4bf",
    "pathogenicity":     "#5eead4",
    "temperature":       "#99f6e4",
    "natural_infection": "#14b8a6",
    "other":             "#ccfbf1",
}

# ── Font setup ─────────────────────────────────────────────────────
plt.rcParams.update({
    "font.family": "sans-serif",
    "font.sans-serif": ["Arial", "DejaVu Sans"],
    "font.size": 11,
    "axes.edgecolor": GRAY_MED,
    "axes.labelcolor": GRAY_TEXT,
    "text.color": BLACK,
    "xtick.color": GRAY_TEXT,
    "ytick.color": GRAY_TEXT,
})

# ── Query database ─────────────────────────────────────────────────
conn = sqlite3.connect(DB)
c = conn.cursor()

# --- Counts ---
c.execute("SELECT COUNT(*) FROM virus_master")
viruses_total = c.fetchone()[0]

c.execute("SELECT COUNT(*) FROM virus_master WHERE entry_type NOT IN "
          "('non_target','duplicate_alias_placeholder','duplicate_ictv_vmr_placeholder',"
          "'host_genome','unclassified_rna_virus','unconfirmed_candidate')")
viruses_target = c.fetchone()[0]

c.execute("SELECT COUNT(*) FROM evidence_records")
evidence_total = c.fetchone()[0]

c.execute("SELECT COUNT(*) FROM viral_proteins")
proteins_total = c.fetchone()[0]

# ICTV mapped
c.execute("""SELECT COUNT(*) FROM virus_master vm
JOIN virus_ictv_status vis ON vm.master_id = vis.master_id
WHERE vm.entry_type NOT IN ('non_target','duplicate_alias_placeholder',
      'duplicate_ictv_vmr_placeholder','host_genome','unclassified_rna_virus',
      'unconfirmed_candidate')
  AND vis.ictv_status = 'mapped'""")
ictv_mapped = c.fetchone()[0]
ictv_pct = ictv_mapped / viruses_target * 100

# --- Host phylum distribution (top 9 aquatic invertebrate phyla) ---
c.execute("""SELECT host_phylum, COUNT(*) as cnt FROM virus_master
WHERE host_phylum IS NOT NULL AND host_phylum != ''
  AND host_phylum NOT IN ('multiple','non_aquatic','unknown')
  AND host_phylum NOT LIKE 'non_target%'
  AND entry_type NOT IN ('non_target','duplicate_alias_placeholder',
      'duplicate_ictv_vmr_placeholder','host_genome',
      'unclassified_rna_virus','unconfirmed_candidate')
GROUP BY host_phylum ORDER BY cnt DESC""")
phylum_rows = c.fetchall()
phylum_names = [r[0] for r in phylum_rows]
phylum_counts = [r[1] for r in phylum_rows]

# --- Evidence type distribution ---
c.execute("""SELECT evidence_type, COUNT(*) as cnt FROM evidence_records
GROUP BY evidence_type ORDER BY cnt DESC""")
evi_rows = c.fetchall()
evi_types = [r[0] for r in evi_rows]
evi_counts = [r[1] for r in evi_rows]
evi_total = sum(evi_counts)

# Combine small ones into "other"
EVI_CUTOFF = 0.02  # 2%
evi_clean_types = []
evi_clean_counts = []
evi_other = 0
for t, cnt in zip(evi_types, evi_counts):
    if cnt / evi_total >= EVI_CUTOFF:
        evi_clean_types.append(t.replace("_", " ").title())
        evi_clean_counts.append(cnt)
    else:
        evi_other += cnt
if evi_other > 0:
    evi_clean_types.append("Other")
    evi_clean_counts.append(evi_other)

# Evidence strength pyramid
c.execute("SELECT COUNT(*) FROM evidence_records WHERE evidence_strength='high' AND curation_status!='rejected'")
evi_high = c.fetchone()[0]
c.execute("SELECT COUNT(*) FROM evidence_records WHERE evidence_strength='medium' AND curation_status!='rejected'")
evi_medium = c.fetchone()[0]
c.execute("SELECT COUNT(*) FROM evidence_records WHERE evidence_strength='low' AND curation_status!='rejected'")
evi_low = c.fetchone()[0]

# --- Reference/fulltext counts ---
c.execute("SELECT COUNT(*) FROM ref_literatures")
refs_total = c.fetchone()[0]
c.execute("SELECT COUNT(DISTINCT reference_id) FROM evidence_records WHERE reference_id IS NOT NULL")
refs_evi = c.fetchone()[0]
c.execute("SELECT COUNT(DISTINCT reference_id) FROM literature_fulltext_sections")
fulltext_total = c.fetchone()[0]

# --- multi/unknown host counts (for annotation on phylum chart) ---
c.execute("""SELECT COUNT(*) FROM virus_master
WHERE host_phylum='multiple'
  AND entry_type NOT IN ('non_target','duplicate_alias_placeholder',
      'duplicate_ictv_vmr_placeholder','host_genome',
      'unclassified_rna_virus','unconfirmed_candidate')""")
multi_cnt = c.fetchone()[0]
c.execute("""SELECT COUNT(*) FROM virus_master
WHERE host_phylum='unknown'
  AND entry_type NOT IN ('non_target','duplicate_alias_placeholder',
      'duplicate_ictv_vmr_placeholder','host_genome',
      'unclassified_rna_virus','unconfirmed_candidate')""")
unk_cnt = c.fetchone()[0]

conn.close()

# ═══════════════════════════════════════════════════════════════════
# BUILD FIGURE — 5:2 aspect ratio
# ═══════════════════════════════════════════════════════════════════
FIG_W = 15       # inches
FIG_H = 6        # inches  -> 15:6 = 5:2
DPI   = 300

fig = plt.figure(figsize=(FIG_W, FIG_H), facecolor=WHITE)

# Grid: 3 columns (30/40/30), 2 rows (top 85% + bottom 15%)
gs = fig.add_gridspec(2, 3, width_ratios=[30, 40, 30],
                      height_ratios=[85, 15],
                      hspace=0.08, wspace=0.08,
                      left=0.03, right=0.97, top=0.95, bottom=0.02)

# ─────────────────────────────────────────────────────────────────────
# PANEL 1 — Database Overview (left, 30%)
# ─────────────────────────────────────────────────────────────────────
ax1 = fig.add_subplot(gs[0, 0])
ax1.set_facecolor(TEAL_BG)
ax1.axis("off")

# Title block
ax1.text(0.5, 0.92, "AquaVir-KB", transform=ax1.transAxes,
         fontsize=24, fontweight="bold", color=TEAL_DARK,
         ha="center", va="top",
         fontfamily="Arial")

ax1.text(0.5, 0.84, "Aquatic Invertebrate\nVirus Knowledge Base",
         transform=ax1.transAxes, fontsize=11, color=GRAY_TEXT,
         ha="center", va="top", linespacing=1.3,
         fontfamily="Arial")

# Divider line (use axline instead of axhline for transform support)
ax1.axline((0.15, 0.78), (0.85, 0.78), color=TEAL, linewidth=1.5,
           transform=ax1.transAxes)

# --- Stats boxes ---
stats = [
    (f"{viruses_target:,}",   "Virus Species\n(target)"),
    ("9",                     "Host Phyla\n(aquatic invertebrate)"),
    (f"{evidence_total:,}",   "Evidence\nRecords"),
    (f"{proteins_total:,}",   "Annotated\nProteins"),
    (f"{ictv_pct:.0f}%",      "ICTV\nMapped"),
    (f"{refs_evi:,}",         "Supporting\nReferences"),
]

stat_y_start = 0.72
for i, (num, label) in enumerate(stats):
    row = i // 2
    col = i % 2
    x = 0.08 + col * 0.48
    y = stat_y_start - row * 0.18

    # Stat number
    ax1.text(x, y, num, transform=ax1.transAxes,
             fontsize=15, fontweight="bold", color=TEAL_DARK,
             ha="left", va="top", fontfamily="Arial")
    # Stat label
    ax1.text(x, y - 0.08, label, transform=ax1.transAxes,
             fontsize=7, color=GRAY_TEXT, ha="left", va="top",
             linespacing=1.2, fontfamily="Arial")

# Data source badges
ax1.text(0.5, 0.00, "Data Sources:", transform=ax1.transAxes,
         fontsize=7, color=GRAY_TEXT, ha="center", va="bottom",
         fontweight="bold", fontfamily="Arial")

badges = ["NCBI\nGenBank", "UniProt", "ICTV\nMSL", "KEGG"]
badge_x = np.linspace(0.08, 0.85, 4)
for bx, badge in zip(badge_x, badges):
    ax1.text(bx, -0.04, badge, transform=ax1.transAxes,
             fontsize=5.5, color=TEAL_DARK, ha="center", va="bottom",
             bbox=dict(boxstyle="round,pad=0.25", facecolor=WHITE,
                       edgecolor=TEAL, linewidth=0.8),
             fontfamily="Arial")

# ─────────────────────────────────────────────────────────────────────
# PANEL 2 — Host Phylum Distribution (center, 40%)
# ─────────────────────────────────────────────────────────────────────
ax2 = fig.add_subplot(gs[0, 1])
ax2.set_facecolor(WHITE)

# Horizontal bar chart — top 9 phyla
colors_phylum = plt.cm.Greys(np.linspace(0.3, 0.65, len(phylum_names)))[::-1]
# Replace with custom teal gradient
teal_cmap = plt.cm.Blues(np.linspace(0.45, 0.85, len(phylum_names)))[::-1]

bars = ax2.barh(range(len(phylum_names)), phylum_counts,
                color=teal_cmap, edgecolor=WHITE, height=0.65, linewidth=0.5)

ax2.set_yticks(range(len(phylum_names)))
ax2.set_yticklabels(phylum_names, fontsize=9, fontfamily="Arial")
ax2.set_xlabel("Number of Virus Species", fontsize=9, color=GRAY_TEXT,
               fontfamily="Arial")
ax2.set_title("Host Phylum Coverage", fontsize=14, fontweight="bold",
              color=TEAL_DARK, pad=8, fontfamily="Arial")

# Data labels on bars
for i, (bar, cnt) in enumerate(zip(bars, phylum_counts)):
    if cnt >= 30:
        ax2.text(bar.get_width() + 8, bar.get_y() + bar.get_height()/2,
                 str(cnt), va="center", fontsize=8, color=GRAY_TEXT,
                 fontfamily="Arial")
    else:
        ax2.text(bar.get_width() + 5, bar.get_y() + bar.get_height()/2,
                 f"({cnt})", va="center", fontsize=7, color=GRAY_MED,
                 fontstyle="italic", fontfamily="Arial")

# Add annotation about "multiple" counts
ax2.text(0.98, 0.02,
         f"Multi-phylum: {multi_cnt}  |  Unknown: {unk_cnt}",
         transform=ax2.transAxes, fontsize=7, color=GRAY_MED,
         ha="right", va="bottom", fontstyle="italic", fontfamily="Arial")

ax2.invert_yaxis()
ax2.spines["top"].set_visible(False)
ax2.spines["right"].set_visible(False)
ax2.spines["left"].set_color(GRAY_LIGHT)
ax2.spines["bottom"].set_color(GRAY_LIGHT)
ax2.tick_params(colors=GRAY_TEXT, labelsize=8)
ax2.xaxis.set_major_locator(mticker.MaxNLocator(integer=True))

# ─────────────────────────────────────────────────────────────────────
# PANEL 3 — Evidence & Annotation Layers (right, 30%)
# ─────────────────────────────────────────────────────────────────────
ax3 = fig.add_subplot(gs[0, 2])
ax3.set_facecolor(WHITE)
ax3.axis("off")

# Sub-section: Evidence type distribution (donut chart)
ax3_donut = fig.add_axes([0.58, 0.55, 0.38, 0.35], facecolor=WHITE)
# Adjusted bounds

# Recompute donut position based on the right panel
donut_left = 0.685
donut_bottom = 0.56
donut_w = 0.28
donut_h = 0.36

ax3_donut = fig.add_axes([donut_left, donut_bottom, donut_w, donut_h],
                          facecolor=WHITE)

# Prepare evidence data for donut
evi_labels = evi_clean_types
evi_sizes  = evi_clean_counts
evi_colors_list = ["#0f766e", "#2dd4bf", "#5eead4", "#99f6e4",
                   "#14b8a6", "#ccfbf1"][:len(evi_labels)]
# Map evidence types to colors
evi_color_map = {
    "Host Range":                  "#0f766e",
    "Diagnosis":                   "#2dd4bf",
    "Pathogenicity":              "#5eead4",
    "Temperature":                "#99f6e4",
    "Natural Infection":          "#14b8a6",
    "Other":                      "#ccfbf1",
    "Mortality":                  "#bae6fd",
    "Transmission":               "#a7f3d0",
    "Outbreak":                   "#fecaca",
    "Virulence":                  "#fed7aa",
}
colors_donut = [evi_color_map.get(l, "#ccfbf1") for l in evi_labels]

wedges, texts, autotexts = ax3_donut.pie(
    evi_sizes, labels=None, autopct="%1.0f%%",
    startangle=90, pctdistance=0.75,
    colors=colors_donut,
    wedgeprops=dict(width=0.45, edgecolor=WHITE, linewidth=1.5),
    textprops=dict(fontsize=7, color=GRAY_TEXT, fontfamily="Arial"),
)

for at in autotexts:
    at.set_fontsize(7)
    at.set_fontweight("bold")
    at.set_color(TEAL_DARK)

ax3_donut.set_title("Evidence Composition", fontsize=11, fontweight="bold",
                     color=TEAL_DARK, pad=5, fontfamily="Arial")

# Evidence strength pyramid (simple stacked bar below donut)
ax3_bar = fig.add_axes([0.68, 0.28, 0.27, 0.18], facecolor=WHITE)

evi_str_labels = ["High", "Medium", "Low"]
evi_str_counts = [evi_high, evi_medium, evi_low]
evi_str_colors = [TEAL_DARK, TEAL, TEAL_LIGHT]

bars3 = ax3_bar.barh([0], [evi_high], height=0.4, color=TEAL_DARK,
                     label=f"High ({evi_high:,})", edgecolor=WHITE)
bars3_left = evi_high
ax3_bar.barh([0], [evi_medium], height=0.4, left=bars3_left,
             color=TEAL, label=f"Medium ({evi_medium:,})", edgecolor=WHITE)
bars3_left += evi_medium
ax3_bar.barh([0], [evi_low], height=0.4, left=bars3_left,
             color=TEAL_LIGHT, label=f"Low ({evi_low:,})", edgecolor=WHITE)

ax3_bar.set_yticks([])
ax3_bar.set_xlabel("Evidence Strength", fontsize=7, color=GRAY_TEXT,
                   fontfamily="Arial")
ax3_bar.set_title("Evidence Quality", fontsize=11, fontweight="bold",
                   color=TEAL_DARK, pad=5, fontfamily="Arial")
ax3_bar.spines["top"].set_visible(False)
ax3_bar.spines["right"].set_visible(False)
ax3_bar.spines["left"].set_visible(False)
ax3_bar.spines["bottom"].set_color(GRAY_LIGHT)
ax3_bar.tick_params(labelsize=6, colors=GRAY_TEXT)
ax3_bar.xaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{int(x):,}"))

# Legend for evidence types (small)
# Place legend below bar chart
legend_labels = [f"{l}" for l in evi_labels[:5]]
legend_patches = [mpatches.Patch(color=evi_color_map.get(l, "#ccc"), label=l)
                  for l in legend_labels]
legend_ax = fig.add_axes([0.69, 0.05, 0.22, 0.12], facecolor=WHITE)
legend_ax.axis("off")
legend_ax.legend(handles=legend_patches, loc="center",
                 fontsize=5.5, ncol=2, frameon=False,
                 title="Evidence Type", title_fontsize=6.5,
                 handlelength=0.8, handletextpad=0.4, columnspacing=1.0)

# ICTV mapping improvement annotation
ictv_ax = fig.add_axes([0.68, 0.48, 0.27, 0.06], facecolor=WHITE)
ictv_ax.axis("off")
ictv_ax.text(0.5, 0.5, f"ICTV Classification: {ictv_pct:.0f}% resolved",
             transform=ictv_ax.transAxes, fontsize=8, color=TEAL_DARK,
             ha="center", va="center", fontweight="bold",
             bbox=dict(boxstyle="round,pad=0.4", facecolor=TEAL_BG,
                       edgecolor=TEAL, linewidth=1),
             fontfamily="Arial")

# ─────────────────────────────────────────────────────────────────────
# BOTTOM STRIP — Key Features (full width)
# ─────────────────────────────────────────────────────────────────────
ax_bottom = fig.add_subplot(gs[1, :])
ax_bottom.set_facecolor(TEAL_DARK)
ax_bottom.axis("off")

features = [
    ("BLAST", "Search"),
    ("RdRp", "Phylogeny"),
    ("Interactive", "Map"),
    ("Host-Virus", "Network"),
    ("REST", "API"),
    ("CC-BY", "4.0"),
]

n_feat = len(features)
feat_x = np.linspace(0.05, 0.95, n_feat)

# Simple icons using Unicode symbols
icon_texts = ["B", "R", "M", "N", "A", "CC"]

for i, (feat_name, feat_sub) in enumerate(features):
    x = feat_x[i]
    # Icon circle
    circle = mpatches.Circle((x, 0.55), 0.06, color=WHITE,
                              transform=ax_bottom.transAxes, clip_on=False,
                              alpha=0.2)
    ax_bottom.add_patch(circle)
    # Icon text
    ax_bottom.text(x, 0.55, icon_texts[i],
                   transform=ax_bottom.transAxes, fontsize=10,
                   color=WHITE, ha="center", va="center",
                   fontweight="bold")
    # Feature name
    ax_bottom.text(x, 0.32, feat_name,
                   transform=ax_bottom.transAxes, fontsize=8,
                   color=WHITE, ha="center", va="center",
                   fontweight="bold", fontfamily="Arial")
    # Feature sublabel
    ax_bottom.text(x, 0.18, feat_sub,
                   transform=ax_bottom.transAxes, fontsize=6.5,
                   color=TEAL_BG, ha="center", va="center",
                   alpha=0.8, fontfamily="Arial")

# Bottom strip title
ax_bottom.text(0.5, 0.85, "KEY FEATURES",
               transform=ax_bottom.transAxes, fontsize=8,
               color=WHITE, ha="center", va="center",
               fontweight="bold", fontfamily="Arial",
)

# ── Save ───────────────────────────────────────────────────────────
# Save without bbox_inches to maintain exact 5:2 pixel dimensions
fig.savefig(OUT_TIF, dpi=DPI, facecolor=WHITE,
            pil_kwargs={"compression": "tiff_lzw"})
tif_img = Image.open(OUT_TIF)
print(f"[OK] TIF saved: {OUT_TIF}")
print(f"     Size: {tif_img.width} x {tif_img.height} px at {DPI} dpi")
print(f"     Ratio: {tif_img.width/tif_img.height:.2f}:1 (target 5:2 = 2.5:1)")

fig.savefig(OUT_PNG, dpi=200, facecolor=WHITE)
print(f"[OK] PNG preview: {OUT_PNG}")

plt.close()

# ── Verification ───────────────────────────────────────────────────
from PIL import Image
img = Image.open(OUT_TIF)
w_mm = img.width / DPI * 25.4
h_mm = img.height / DPI * 25.4
print(f"\n── Verification ──")
print(f"  Format:  {img.format}")
print(f"  Mode:    {img.mode}")
print(f"  DPI:     {DPI}")
print(f"  Pixels:  {img.width} x {img.height}")
print(f"  mm:      {w_mm:.1f} x {h_mm:.1f}  (min 127x50)")
print(f"  Ratio:   {img.width/img.height:.2f}:1 (target 2.5:1)")
print(f"  File:    {os.path.getsize(OUT_TIF)/1024:.0f} KB")
