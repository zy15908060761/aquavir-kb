# Checkpoint 2026-05-23 — 数据库优化完成，待跑 RdRp 建树

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
| DB 表/视图/索引 | 112 表 + 37 视图 + 224 索引 |

## 本次会话完成的工作

### P1: 全文解析
- 解析了 2,023 篇新下载的全文
- +680 条证据 (fulltext_parsed_p1: 5,207→5,887)
- 证据总量: 341,394 → 347,283

### P2: 证据质量升级
- low→medium: 171,383 条 (基于全文提取 + DOI + 实验方法信号)
- 分布: low 50% / medium 49% / high 0.8%

### P3: 蛋白功能注释
- 使用 NCBI CDD (curl 批量，无 Java): 18,781 蛋白
- 结构域覆盖率: 30.1% → 76.1%
- 新增 52,511 个结构域

### P4: 数据质量清理
- NAR 7 个 warning 全部清除
- 47 组重复 DOI 合并
- 10 张空表删除
- 缺失索引补齐
- 4 条孤立证据标记

### 文献下载
- Sci-Hub + NCBI PMC 下载 819 篇全文
- 全文总量: 2,002 → 2,831
- 下载脚本: `download_stable_final.py` (curl 引擎，断点续传)

## 待完成: RdRp 系统发育分类

### 背景
- 120 个目标病毒无科级分类
- 926 条已知家族 RdRp + 131 条未知家族 RdRp 已导出

### 序列文件位置
```
F:\水生无脊椎动物数据库\blastdb\known_rdrp.faa   (926 条, 含家族标签)
F:\水生无脊椎动物数据库\blastdb\unknown_rdrp.faa  (131 条, 待分类)
```

### 安装 MAFFT + IQ-TREE

WSL 已重装但需重启生效。重启后验证:
```bash
wsl --version
```

然后装工具:
```bash
wsl sudo apt-get update
wsl sudo apt-get install -y mafft iqtree
wsl mafft --version
wsl iqtree --version
```

备选: Windows 原生版 (不需要 WSL):
- MAFFT: https://mafft.cbrc.jp/alignment/software/windows_portable.html
- IQ-TREE: https://github.com/iqtree/iqtree2/releases
- 解压到 `F:\mafft\` 和 `F:\iqtree\`

### 建树工作流 (装好工具后)

1. 合并序列:
```bash
cat F:/水生无脊椎动物数据库/blastdb/known_rdrp.faa \
    F:/水生无脊椎动物数据库/blastdb/unknown_rdrp.faa \
    > F:/水生无脊椎动物数据库/blastdb/all_rdrp.faa
```

2. MAFFT 比对:
```bash
mafft --auto --thread 4 F:/水生无脊椎动物数据库/blastdb/all_rdrp.faa \
    > F:/水生无脊椎动物数据库/blastdb/all_rdrp_aligned.faa
```

3. IQ-TREE 建树:
```bash
iqtree2 -s F:/水生无脊椎动物数据库/blastdb/all_rdrp_aligned.faa \
    -m MFP -B 1000 -T 4 --prefix F:/水生无脊椎动物数据库/blastdb/rdrp_tree
```

4. 解析树 + 写入 DB (我写脚本):
   - 对每个未知病毒，找最近邻的已知家族病毒
   - 家族一致性 > 阈值即赋值

### 其他待优化项 (非紧急)
- 46 个病毒无基因组类型 (可从科级推断)
- 24 个零证据目标病毒 (21 个在 GenBank 中无文献)
- 125 个经济物种仅 1-5 条证据

## 关键脚本索引

| 脚本 | 用途 |
|------|------|
| `download_stable_final.py` | 文献下载 (curl 引擎) |
| `extract_unparsed_fulltext.py` | 全文证据提取 |
| `upgrade_quality_balanced.py` | 证据质量升级 |
| `annotate_proteins_curl.py` | 蛋白 NCBI CDD 注释 |
| `build_review_workflow.py` | 审核工作流 |
| `reports/build_dashboard.py` | 仪表盘生成 |
| `audit_comprehensive.py` | 全面质量审查 |

## 仪表盘
浏览器打开: `F:\水生无脊椎动物数据库\reports\dashboard.html`

## 恢复此会话
新对话中发送: "读取 F:\水生无脊椎动物数据库\CHECKPOINT_20260523.md，从上次断点继续"
