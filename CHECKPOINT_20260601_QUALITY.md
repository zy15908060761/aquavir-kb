# Checkpoint 2026-06-01 — 证据质量5策略优化完成

## 质量分布

| 等级 | 优化前 | 优化后 | 变化 |
|------|--------|--------|------|
| high | 2,398 (0.7%) | **26,940 (7.7%)** | **+11.2x** |
| medium | 343,513 (98.7%) | 319,676 (91.9%) | - |
| low | 2,116 (0.6%) | 1,411 (0.4%) | - |
| 定量数据 | 15 | **12,178** | **+812x** |

## 5策略执行详情

### S1: 三角互证 (≥3独立文献)
- 288个相似claim组，2,790条升级为high
- 条件: 同一病毒+证据类型+相似claim前缀，≥3个不同reference_id

### S2: 加权多因子评分 (≥7/9分)
- 9,584条升级为high
- 因子: DOI(1pt) + fulltext(2pt) + isolate(2pt) + experimental(2pt) + extracted(1pt) + reviewed(1pt)

### S3: 定量数值提取
- 12,163条证据提取了数值 (温度11,268 + 死亡率871 + LD50 4 + 其他)
- 12,168条升级为high (含数值的中等证据自动升级)
- 正则模式: 死亡率%, LD50, 温度°C, 生存率%, 患病率%

### S4: Low质量清理
- 705条升级 (DOI/fulltext → medium)
- 88条拒绝 (不可追溯的ncbi_nucleotide_search)

### S5: 共识评分系统
- 创建virus_evidence_quality_score表 (1,826行)
- 评分维度: high证据数、实验方法、定量数据、DOI覆盖、全文覆盖、审核率、分离株关联
- 分布: excellent 8.7%, good 36.0%, fair 35.5%, minimal 19.7%

## 脚本
`upgrade_evidence_to_high.py` — 策略1-4综合升级脚本 (支持--dry-run, --skip)

## 恢复
"读取 F:\水生无脊椎动物数据库\CHECKPOINT_20260601_QUALITY.md"
