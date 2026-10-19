# Figure scripts and source data

All scripts were used to produce the six main figures for the manuscript. Set the `BASE` / `OUT` constants at the top of each R script to your local paths before running.

## Canonical numbers

`figures/fig_stats.tsv` is the **single canonical source** of the numbers plotted in the figures. Do not hand-copy values from the manuscript. It is read by `fig3_plot.R` and `fig5_plot.R`.

## Figure 1 — resource architecture

- Script: `figures/fig1_plot.R`
- Data: embedded in the script (architecture diagram, no external data table)
- Outputs: `Fig1_architecture.{svg,pdf,tiff,png}`

## Figure 2 — content coverage

- Script: `figures/fig2_plot.R`
- Data: values embedded in the script from the frozen snapshot; see also `fig_stats.tsv`
- Outputs: `Fig2_content_coverage_R.{svg,pdf,tiff,png}`
- Note: the 2026-10-14 version reflects the post-withdrawal host count (158 rather than 159).

## Figure 3 — evidence quality

- Script: `figures/fig3_plot.R`
- Data: `figures/fig_stats.tsv`
- Outputs: `Fig3_evidence_quality_R.{svg,pdf,tiff,png}`
- Note: panel 3D reflects the post-withdrawal grading totals (4,956 / 736 / 1,749 / 1,764 / 701 / 6).

## Figure 4 — web interface (two alternative versions)

### Route A: live screenshots

- Scripts: `figures/fig4_render.py` then `figures/fig4_assemble.R`
- Data: `figures/fig4_data/` (PNG/PDF screenshots of `/search`, `/virus/AB855742.1`, `/host/1` and `/download`)
- Outputs: `Fig4_web_routeA_live.{svg,pdf,tiff,png}`
- If route A is used, the caption must say the panels are **rendered from the live site**, not redrawn.

### Route B: vector redrawing

- Script: `figures/fig4_redraw.R`
- Data: embedded wireframe drawing
- Outputs: `Fig4_web_routeB_redraw.{svg,pdf,tiff,png}`
- If route B is used, the caption should say the panels are **redrawings**.

Only one route should appear in the final submission.

## Figure 5 — analysis functions

- Script: `figures/fig5_plot.R`
- Data: `figures/fig_stats.tsv`, `figures/fig5_data/`
- Outputs: `Fig5_analysis_R.{svg,pdf,tiff,png}`

Panel A uses `fig5_data/marnaviridae_rdrp_iqtree.contree` (see `METHODS_rdrp.md`). Other files in `fig5_data/` include the RdRp family counts, the host-virus network, the VP28 structure and representatives of other families.

Note: panel 5B reflects the post-withdrawal network (83 edges, down from 92).

## Figure 6 — use cases

- Script: `figures/fig6_plot.R`
- Data: `figures/fig6_matrix_synced.tsv` (canonical synchronized matrix), `figures/fig_stats.tsv`
- Outputs: `Fig6_use_cases_R.{svg,pdf,tiff,png}`
- Note: `fig6_matrix_synced.tsv` is the synchronized version; the older `fig6_matrix.tsv` is retained upstream but is not used here.

## Software

- R >= 4.5
- Packages: `ggplot2`, `ggtree`, `treeio`, `svglite`, `cairo_pdf` (grDevices), `png`, `magick`, `jsonlite`, `dplyr`, `patchwork`, `ragg`
- Fonts: Arial must be installed for the PDF/TIFF outputs

## Data provenance and caveats

- Figure data were regenerated on 2026-10-14 after the display-layer withdrawal. Figures 2B, 3D and 5B use post-withdrawal numbers.
- `fig_stats.tsv` is a small, human-readable key-value table; the underlying SQL is documented in `statistics/STAT_DICT_20261016.md`.
- `fig4_data/4a_search.png`, `4b_virus.pdf`, `4c_host.pdf` and `4d_download.png` are screenshots captured from the live site; they may contain the site's then-current interface and numbers.
