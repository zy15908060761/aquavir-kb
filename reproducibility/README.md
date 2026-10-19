# AquaVir-KB reproducibility package

Companion code and source data for the AquaVir-KB manuscript (a curated knowledge base of viruses in aquatic invertebrates; prepared for submission to *iMetaOmics*).

- Package version: 2026-10-19
- Database snapshot cited by the manuscript: freeze of 2026-10-05, SHA-256 `490ba87a10cf1b82a2f53dcb0aeddabffc51939994c281336bb8a8f3cd2bf796`
- Display-layer withdrawal applied 2026-10-14 (host 37 and 523 records; zero database writes). Public counts in the manuscript and figure data reflect the post-withdrawal surface.

This package contains **code and figure source data only**. It does not contain the database file, full texts, or the frozen snapshot. The snapshot and public download packages are distributed separately (see *Data availability* in the manuscript).

## Layout

```
literature_search/        PubMed / Europe PMC query scripts
evidence_extraction/      rule- and pattern-based evidence extraction
rdrp/                     RdRp classification and phylogeny scripts
figures/                  R plotting scripts and figure source data
statistics/               public statistic dictionary and definitions
environment.yml           Python dependencies
SHA256SUMS.txt            checksums for every file in this package
```

## Requirements

- Python >= 3.10 (the production runs used Python 3.12.7)
- R >= 4.5 with `ggplot2`, `ggtree`, `treeio`, `svglite`, `png`, `magick`, `jsonlite`, `dplyr`, `patchwork`
- Biopython 1.81 or later
- PyMuPDF 1.27.2.2 (only for PDF text extraction)
- MAFFT 7.526, IQ-TREE 2.4.0 and FastTree 2.2.0 (only for the RdRp workflows)
- Network access to NCBI E-utilities and the Europe PMC REST API

Install the Python dependencies with:

```bash
conda env create -f environment.yml
```

## Important notes before running

1. **Absolute paths.** The scripts were run on the original workstation and contain absolute paths such as `F:\甲壳动物数据库\...` and `D:\桌面\AquaVir_Figures_20261005\...`. Edit the `DB_PATH`, `SEQ_DIR`, `WORK_DIR`, `OUT` and `*_PATH` constants at the top of each script before running.
2. **Database not included.** Scripts that read `crustacean_virus_core.db` require the frozen snapshot, which is distributed separately.
3. **Figure numbers.** `figures/fig_stats.tsv` is the single canonical source of the numbers plotted in the figures; do not hand-copy values from the manuscript.
4. **Figure 4 has two alternative versions.** `fig4_render.py` + `fig4_assemble.R` assemble live screenshots (route A); `fig4_redraw.R` produces a vector redrawing (route B). Only one should be used in the final submission.
5. **Figure 5A is one tree, not three.** `fig5_plot.R` reads `fig5_data/marnaviridae_rdrp_iqtree.contree`. The `nimaviridae_iqtree.contree` and `roniviridae_iqtree.contree` files are genome trees from the same production run and are not used in Figure 5A.

## Reproducing the main steps

### 1. Literature search

See `METHODS_literature_search.md`. Scripts are in `literature_search/`. The main per-virus search was run on 2026-05-16 (834 viruses, 16,672 unique PMIDs); the phenotype searches were run on 2026-05-08.

### 2. Evidence extraction

See `METHODS_evidence_extraction.md`. Scripts are in `evidence_extraction/`. Extraction is rule- and pattern-based (regular expressions plus token matching); **no NLP model and no large language model was used**.

### 3. RdRp classification and trees

See `METHODS_rdrp.md`. Two distinct workflows are included:

- global classification of 1,213 sequences (131 phylogeny-based + 1,082 k-mer-based);
- the representative Figure 5A Marnaviridae tree (IQ-TREE 2.4.0, LG+G4, UFBoot 1,000).

### 4. Figures

See `FIGURES.md`. Run the R scripts from `figures/` after adjusting `BASE`/`OUT` paths. All figure data needed by the scripts are included.

## Citation

If you use this code or the figure source data, please cite the AquaVir-KB manuscript. A machine-readable citation stub is provided in `CITATION.cff`; author names and the final DOI will be updated at acceptance.

## License

Code and figure source data in this package are released under **Creative Commons Attribution-NonCommercial-NoDerivatives 4.0 International (CC BY-NC-ND 4.0)**. You may download and run the code for non-commercial research and for peer review; you may not redistribute modified versions or use it commercially. See `LICENSE`.

Third-party data included in `figures/` remain subject to their original source terms (GenBank/NCBI, ICTV, AlphaFold/PDB, and the publications cited in the manuscript).
