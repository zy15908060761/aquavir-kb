# RdRp classification and phylogeny: exact parameters

Two distinct workflows produced the RdRp results. They must not be conflated in the manuscript.

## A. Global classification of 1,213 sequences

### Input

- **1,057 sequences**: 926 known reference RdRp sequences (`blastdb/known_rdrp.faa`) + 131 unknown sequences (`blastdb/unknown_rdrp.faa`).
- The 1,213-sequence classification collection is broader than this tree input: it includes reference sequences and environmental contigs as well as curated-isolate sequences.

### Alignment and trimming

```text
MAFFT 7.526   --auto --thread 4
```

- Alignment length: **27,406 columns**.
- Trimming: **columns with more than 50% gaps were removed**, reducing the alignment to **498 columns**. This was implemented as a gap-stripping fallback in `classify_rdrp_extended.py` (`strip_gappy_columns`, `gap_threshold=0.5`), not with trimAl. The 498-column result was verified against the archived trimmed alignment.

### Tree and classification

```text
FastTree 2.2.0   -lg -gamma -pseudo -spr 4
```

- Support: SH-like 1,000 replicates.
- Classification of the 131 unknown sequences: nearest common ancestor plus SH support.

```text
IQ-TREE 2.4.0   -s all_rdrp_trimmed.faa -m LG+F+G -B 1000 -T 2 --prefix rdrp_tree
```

- The IQ-TREE run was used as a cross-check of the FastTree result.

### Confidence thresholds

- Tree-based (FastTree SH support), in `classify_fasttree.py`:
  - `high`: SH >= 0.70
  - `medium`: 0.50 <= SH < 0.70
  - `low`: SH < 0.50
- k-mer based, in `classify_rdrp_extended.py`:
  - `high`: agreement >= 0.8 or cosine similarity > 0.95
  - `medium`: agreement >= 0.6 or cosine similarity > 0.85
  - `low`: otherwise
- When both methods were available, the final confidence was the higher of the two.

### Composition of the 1,213-sequence collection

- **131** sequences classified with the phylogenetic method (`FastTree_phylogeny`; high 87 / medium 6 / low 38).
- **1,082** sequences classified with the k-mer method (89.2%).

The manuscript must state this explicitly. It is not correct to describe all 1,213 assignments as phylogeny-based.

### Version note

The global workflow used **MAFFT 7.526**, **FastTree 2.2.0** and **IQ-TREE 2.4.0**. These versions are recorded in `CHECKPOINT_20260524.md` and in the IQ-TREE log header.

## B. Figure 5A representative tree (Marnaviridae)

`figures/fig5_plot.R` reads exactly one tree:

```text
figures/fig5_data/marnaviridae_rdrp_iqtree.contree
```

### Input

- **10 RdRp protein sequences**, alignment length **2,562 amino-acid sites**.
- Sequences were selected from the database per family: the longest sequences, up to 50 per family, minimum 3 (`rebuild_phylogeny.py`).

### Commands

```text
mafft --localpair --maxiterate 1000 --thread 4 marnaviridae_rdrp.fasta > marnaviridae_rdrp_aln.fasta

iqtree2 -s marnaviridae_rdrp_aln.fasta -m LG+G4 -B 1000 -alrt 1000 -nt 4 \
        -pre marnaviridae_rdrp_iqtree -redo
```

- Software: **IQ-TREE 2.4.0** (built 2025-02-07).
- Model: **LG+G4** (protein).
- Support: **UFBoot 1,000 + aLRT 1,000**.
- Trimming: **none** (the alignment was used directly; trimAl was not used).
- Run date: **2026-05-06**.
- Random seed recorded in the IQ-TREE log: **605847**.

The tree file is byte-identical to the published download at `/public_downloads/phylogeny/marnaviridae_rdrp_iqtree.contree` on the AquaVir-KB server (SHA-256 `becace569aac9b685db577386e7d70d896171e58ea612076c51eb8e9a72152c5`).

### Other trees in `fig5_data/`

- `nimaviridae_iqtree.contree`: **genome nucleotide** tree, 15 sequences x 389,600 sites, ModelFinder best model HKY+F+I, `-B 1000 -bnni -alrt 1000`, 2026-05-06.
- `roniviridae_iqtree.contree`: **genome nucleotide** tree, 15 sequences x 26,932 sites, ModelFinder best model TIM2+F+I+R2, `-B 1000 -bnni -alrt 1000`, 2026-05-03.
- These are **not** RdRp trees and are **not** used in Figure 5A.

## Reproducibility caveats

- The per-family tree pipeline was run on a Windows workstation; `rebuild_phylogeny.py` contains the original absolute paths.
- The MAFFT version used for the May 2026 per-family runs is not recorded in the IQ-TREE log. The global workflow (May 2026) used MAFFT 7.526; the per-family runs used the same `mafft` installation family but this cannot be proven from the log. If a reviewer requires an exact MAFFT version for Figure 5A, state the parameters and note that the version was not logged.
- Sequence selection is deterministic given the frozen database, but the database is distributed separately.
