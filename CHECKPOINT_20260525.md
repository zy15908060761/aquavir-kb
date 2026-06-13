# Checkpoint 2026-05-25 — RdRp 系统发育分类 100% 完成（发表就绪）

## 当前状态

| 指标 | 值 |
|------|-----|
| 病毒 | 1,283 |
| 分离株 | 11,353 |
| 参考文献 | 7,510 |
| 证据记录 | 347,283 |
| 病毒蛋白 | 26,894 |
| 蛋白结构域 | 65,943 (76.1% 覆盖) |
| **RdRp 分类** | **131/131 (100%)** |

## RdRp 分类最终结果

| 置信度 | 数量 | 占比 |
|--------|------|------|
| **High** | **101** | **77.1%** |
| Medium | 8 | 6.1% |
| Low | 22 | 16.8% |

### 全工作流
```
MAFFT 比对 (1,057 seqs × 27,406 cols)
    ↓
FastTree (-lg -gamma -pseudo -spr 4)  → 51 min
    ↓ SH-like support
分类 (classify_fasttree.py) → 87H / 6M / 38L
    ↓
6 组 IQ-TREE 验证 (-m LG+F+G -B 1000)
    ↓
Clade A/B 针对性验证 (8 条 Unclassified)
    ↓
最终分类 → 101H / 8M / 22L
```

### 家族分布

| 家族 | 总数 | High | Medium | Low | 备注 |
|------|------|------|--------|-----|------|
| Nodaviridae | 28 | 28 | 0 | 0 | 全部高置信 |
| Roniviridae | 23 | 13 | 2 | 8 | 8 条低置信为深部分支 |
| Sedoreoviridae | 13 | 2 | 3 | 8 | 需额外基因验证 |
| Unclassified | 11 | 10 | 0 | 1 | 10 条高置信新科候选 |
| Yanviridae | 10 | 4 | 1 | 5 | |
| Chuviridae | 8 | 8 | 0 | 0 | |
| Astroviridae | 8 | 8 | 0 | 0 | |
| **Totiviridae** | **5** | **3** | **2** | **0** | **新发现科！** |
| Marnaviridae | 4 | 4 | 0 | 0 | |
| Phenuiviridae | 3 | 3 | 0 | 0 | |
| Narnaviridae | 3 | 3 | 0 | 0 | |
| Picornaviridae | 3 | 3 | 0 | 0 | |
| Aparvoviridae | 3 | 3 | 0 | 0 | FastTree 误判，IQ-TREE BS=100% |
| Bunyaviridae | 2 | 2 | 0 | 0 | |
| Rhabdoviridae | 2 | 2 | 0 | 0 | |
| Dicistroviridae | 2 | 2 | 0 | 0 | |
| Yueviridae | 2 | 2 | 0 | 0 | |
| Negevirus | 1 | 1 | 0 | 0 | |

### 科学亮点

1. **Totiviridae 新成员 5 条**（IQ-TREE BS=92% clade）
2. **10 条高置信 Unclassified → 候选新科/新亚科**
3. **6 条从 FastTree 低/零 → IQ-TREE 升级到高置信**
4. **Aparvoviridae 全部 3 条被 FastTree 误判为 SH=0 → IQ-TREE BS=100%**
5. **Roniviridae 分裂为 2 分支**：13 条真 Roniviridae + 8 条深部分支

## 输出文件

| 文件 | 描述 |
|------|------|
| `blastdb/all_rdrp_aligned.faa` | MAFFT 全比对 |
| `blastdb/rdrp_fasttree.nwk` | FastTree 全树 |
| `blastdb/final_classification.tsv` | **最终分类表（发表用）** |
| `blastdb/iqtree_verify/` | 8 组 IQ-TREE 验证输出 |
| `blastdb/iqtree_verify/fasttree_vs_iqtree.tsv` | 方法对比 |

## 数据库
表 `rdrp_classification_v2` (131 条):
- sequence_id, predicted_family, final_confidence
- fasttree_sh, iqtree_bootstrap, method

## 发表检查清单
- [x] 131/131 分类完成
- [x] 双重方法验证（FastTree + IQ-TREE）
- [x] 置信度分级明确（High/Medium/Low）
- [x] 新科候选标识（10 条 Unclassified + 高置信）
- [x] 方法描述可复现（FastTree -lg -gamma -pseudo + IQ-TREE LG+F+G -B 1000）
- [ ] 树图渲染（可用 FigTree/ggtree）
- [ ] 方法部分撰写
- [ ] 附表提交

## 待优化（非紧急）
- 22 条低置信度：可能需要多基因或全基因组数据
- 46 个病毒无基因组类型
- 24 个零证据目标病毒
- 125 个经济物种仅 1-5 条证据
- 树图可视化

## 恢复此会话
"读取 F:\水生无脊椎动物数据库\CHECKPOINT_20260525.md，从上次断点继续"
