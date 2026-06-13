#!/bin/bash
# Step 2: MAFFT 比对 + IQ-TREE 建起始树 + 时间信号检验
set -e
conda activate beast

DIR="F:/水生无脊椎动物数据库/beast_analysis"

echo "=== 2.1 MAFFT protein alignment ==="
mafft --auto --thread -1 "${DIR}/dicistro_rdrp.fasta" > "${DIR}/dicistro_rdrp_aln.fasta"
echo "Alignment done: $(grep -c '^>' ${DIR}/dicistro_rdrp_aln.fasta) sequences"

echo "=== 2.2 IQ-TREE ML tree (model selection + tree) ==="
iqtree -s "${DIR}/dicistro_rdrp_aln.fasta" \
       -m MFP \
       -B 1000 \
       -nt AUTO \
       -pre "${DIR}/iqtree" \
       --keep-ident

echo "=== 2.3 Temporal signal check (R) ==="
Rscript "${DIR}/03_temporal_signal.R"
