# Checkpoint 2026-05-31 — P0-P2 数据质量优化完成

## 当前状态

| 指标 | 值 |
|------|-----|
| 活跃病毒 | 1,826 |
| 病毒总量 | 3,531 (含 1,705 非靶标) |
| 分离株 | 17,866 |
| 参考文献 | 8,999 |
| 证据记录 | 340,026 |
| 病毒蛋白 | 27,096 |
| 蛋白结构域 | 71,537 (87.8% 蛋白已注释) |
| RdRp 分类 | 131/131 (100%) |
| DB 大小 | 819 MB |

## 本次会话完成的工作

### P0: ICTV VMR 零证据回填
- Phase 1: 从 ictv_vmr 表解析 1,782 条数字 ID → 真实物种名
  - 368 条水生条目保留，1,414 条非靶标标记为 non_target
  - 修复: 1,767 名称、1,757 科级、1,782 基因组类型
- Phase 2: GenBank EFetch 提取参考文献
  - 新增 87 PubMed 文献 + 385 GenBank 提交记录
  - 创建 362 条证据记录
  - 零证据: 1,782 → 18 (99% 解决)
  - 6,725 分离株关联到参考文献

### P0: 蛋白质功能注释
- 扩展域→功能映射模式 (97 条规则)
- 23,638 蛋白标记为 domain_inferred (原 0)
- 未注释率: 99.4% → 12.2%
- 功能分布: structural 32.4%, RdRP 21.4%, replication 20.3%, unknown 12.2%, metabolism 6.9%, host_interaction 6.6%, assembly 0.2%

### P1: 证据质量升级
- low→medium 升级: 157,259 条 (基于 DOI 可追溯性)
- low: 46.9% → 0.6%
- medium: 52.4% → 98.7%

### P1: 证据去重
- 0 条新增重复（前序会话已完成 20,145 条去重）

### P2: 元数据缺口修复
- genome_type: 从科级推断 107 条 (剩余 192)
- 非靶标标记: 287 条 (藻类/陆生/脊椎动物)
- 总非靶标条目: 1,705

## 关键脚本索引

| 脚本 | 用途 |
|------|------|
| `backfill_ictv_vmr_evidence.py` | Phase 1: ICTV VMR 名称解析 + 分类修复 |
| `backfill_ictv_vmr_phase2.py` | Phase 2: GenBank 参考文献提取 + 证据创建 |
| `annotate_proteins_from_domains.py` | 域→功能推断 (97 条规则) |
| `upgrade_evidence_tiers.py` | 证据质量升级 v3 |
| `fix_p2_gaps.py` | genome_type/family 修复 + 非靶标清理 |

## 剩余待优化

- 61 条活跃病毒零证据 (多为无 PubMed/GenBank 记录的新物种)
- 192 条缺 genome_type + 143 条缺 family
- 3,290 蛋白未注释 (需跑 InterProScan)
- 次要门类深度不足 (Cnidaria/Porifera/Echinodermata)
- 树图可视化 (RdRp 发表用图)
- 方法部分 + 附表撰写

## 恢复此会话
"读取 F:\水生无脊椎动物数据库\CHECKPOINT_20260531.md，从上次断点继续"
