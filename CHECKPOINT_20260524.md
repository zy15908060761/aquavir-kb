# Checkpoint 2026-05-24 — RdRp 系统发育分类完成（FastTree + SH 支持值）

## 当前状态

| 指标 | 值 |
|------|-----|
| 病毒 | 1,283 |
| 分离株 | 11,353 |
| 参考文献 | 7,510 |
| 证据记录 | 347,283 |
| 病毒蛋白 | 26,894 |
| 蛋白结构域 | 65,943 (76.1% 覆盖) |
| GO 术语 | 3,452 |
| 全文已下载 | 2,831 (37.7%) |
| DB 大小 | 603 MB |
| **RdRp 分类** | **131/131 完成 (100%)** |

## 本次会话完成的工作

### RdRp 系统发育分类（核心任务）

**工具安装:**
- MAFFT v7.526 Windows 原生（Python urllib 下载，F:\mafft\mafft-win\）
- IQ-TREE v2.4.0 Windows 原生（F:\iqtree\iqtree-2.4.0-Windows\）
- FastTree v2.2.0 源码编译（gcc -O3，F:\iqtree\FastTree.exe）

**工作流:**
1. 合并序列: 926 known + 131 unknown → 1,057 条 → `all_rdrp.faa`
2. MAFFT 比对: `--auto --thread 4` → 27,406 列 → `all_rdrp_aligned.faa` (29 MB)
3. FastTree 建树: `-lg -gamma -pseudo -spr 4` → 51 分钟 → `rdrp_fasttree.nwk`
4. 分类脚本: `classify_fasttree.py` — 基于最近共同祖先 + SH 支持值

**结果:**
| SH 支持值 | 置信度 | 数量 | 处理状态 |
|-----------|--------|------|----------|
| > 0.70 | high | 87 | 直接赋值入库 |
| 0.50-0.70 | medium | 6 | 待 IQ-TREE 验证 |
| < 0.50 | low | 38 | 待 IQ-TREE 验证 |

**家族分布 (Top 10):**
- Nodaviridae: 28
- Roniviridae: 23
- Unclassified: 16（可能为新科）
- Sedoreoviridae: 13
- Yanviridae: 10
- Astroviridae: 8
- Chuviridae: 8
- Marnaviridae: 4
- Aparvoviridae: 3
- Picornaviridae: 3

## 待完成: IQ-TREE 验证（44 条中/低置信度）

### 策略
对 44 条中低置信度序列，按家族分组提取分支，用 IQ-TREE 精确 Bootstrap 验证。

### 命令
```bash
# 对各家族分支提取序列 → 小比对 → IQ-TREE
cd F:/水生无脊椎动物数据库/blastdb
/f/iqtree/iqtree-2.4.0-Windows/bin/iqtree2.exe -s <subset>.faa -m LG+F+G -B 1000 -T 2 --prefix <subset>_verify
```

### 需要验证的家族 (6 medium + 38 low)
- **Roniviridae**: 13 条 (2 medium)
- **Sedoreoviridae**: 13 条 (1 medium)
- **Unclassified**: 8 条 (2 medium) — 可能为新科
- **Yanviridae**: 6 条 (0 medium)
- **Aparvoviridae**: 3 条 (0 medium)
- **Negevirus**: 1 条 (0 medium)

## 其他待优化项（非紧急，同上次）
- 46 个病毒无基因组类型 (可从科级推断)
- 24 个零证据目标病毒 (21 个在 GenBank 中无文献)
- 125 个经济物种仅 1-5 条证据

## 新增脚本索引

| 脚本 | 用途 |
|------|------|
| `classify_fasttree.py` | FastTree Newick 解析 + 家族分类 |
| `classify_rdrp_tree.py` | IQ-TREE 树解析（备用） |

## 软件位置
```
F:\mafft\mafft-win\        — MAFFT v7.526 (bundled bash 运行)
F:\iqtree\iqtree-2.4.0-Windows\bin\iqtree2.exe  — IQ-TREE v2.4.0
F:\iqtree\FastTree.exe     — FastTree v2.2.0 (源码编译)
```

## 输出文件
```
blastdb/all_rdrp.faa                    — 合并序列 (1,057 条)
blastdb/all_rdrp_aligned.faa            — MAFFT 比对 (27,406 列)
blastdb/rdrp_fasttree.nwk               — FastTree 树 (SH 支持值)
blastdb/rdrp_classification.tsv         — 分类报告 (131 条)
blastdb/iqtree_stdout.log               — IQ-TREE 输出日志 (内存不足)
```

## 恢复此会话
新对话中发送: "读取 F:\水生无脊椎动物数据库\CHECKPOINT_20260523.md，从上次断点继续"
