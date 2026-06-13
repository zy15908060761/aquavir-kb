# AquaVir-KB 进度 Checkpoint
## 2026-05-12 会话完成内容 & 下一步

---

## 已完成

### 1. 全网文献调研
- 文件: `RESEARCH_SUMMARY_AQUATIC_INVERT_VIRUSES.md`
- 涵盖了软体动物、珊瑚、棘皮动物、海绵等类群的病毒学现状
- 确认: 没有专门的水生无脊椎动物病毒综合知识库 → 差异化优势

### 2. 数据库 Schema 迁移（已执行）
- 文件: `migrate_schema_aquatic_expansion.py` — 迁移脚本（可重复使用）
- 报告: `expansion_migration_report.json`

**新增字段:**
| 表 | 新字段 | 说明 |
|------|------|------|
| crustacean_hosts | phylum | 宿主门 (Arthropoda/Mollusca/Chordata...) |
| crustacean_hosts | class | 宿主纲 (Malacostraca/Bivalvia...) |
| crustacean_hosts | host_scope_status | 策展范围状态 |
| infection_records | host_association_method | 宿主关联证据等级 |
| virus_master | discovery_context | 病毒发现方式 |
| virus_master | host_phylum | 关联宿主门 |

**数据库基线（迁移后）:**
- 病毒物种: 526
- 分离株: 3,783
- 蛋白: 22,823
- 目标宿主: 70 (Arthropoda 63 + Mollusca 4 + Other aquatic 3)
- 宿主门覆盖: 2 个目标门 (Arthropoda + Mollusca)
- 证据覆盖率: 13.5% (71/526 物种)
- 参考文献: 317 (52 条无 PMID/DOI)
- 数据库大小: 232.3 MB

### 3. 数据库优化（已执行）
- 文件: `optimize_database_post_migration.py`
- 报告: `expansion_baseline.json`

**宿主分类完成:**
| scope_status | 数量 |
|------|:---:|
| target_crustacean | 63 |
| target_mollusk | 4 |
| target_other_aquatic_invert | 3 |
| excluded_environmental | 22 |
| excluded_lab_host | 6 |
| excluded_vertebrate | 5 |
| excluded_non_aquatic | 1 |

### 4. 视图更新（已执行）
- `analysis_target_isolates` — 扩展 scope 包括软体动物和其他水生无脊椎动物 (2,773/3,783 isolates)
- `v_host_composition_by_phylum` — 修复 column 引用
- `v_nar_database_summary` — NAR 论文统计视图
- `v_expansion_readiness` — 阶段就绪检查
- `v_host_scope_audit` — 宿主范围审计
- `v_infection_quality` — 感染记录质量分级

### 5. release_gate.py 更新
- `non_crustacean_hosts_not_excluded` → `non_target_hosts_not_excluded` 使用新 host_scope_status

### 6. 备份
- `backups/pre_expansion_backup_20260512_191302.db` (236.3 MB)
- `backups/pre_replace_20260512_191302.db` (236.5 MB)

---

## 下一步（按优先级）

### P0 — Phase 1: 软体动物病毒数据导入
1. 运行 `search_sra_crustacean_viromes.py` 扩展到所有水生无脊椎动物 SRA
2. 创建 NCBI 软体动物病毒检索 pipeline
3. 从 DOV 数据集 (Jiang et al. 2023) 导入 3,473 个高质量病毒基因组
4. 导入 OsHV-1, HaHV-1, AVNV, CMNV, MDNV 等关键软体动物病原
5. 对接 WoRMS API 标准化软体动物宿主分类
6. 目标: 新增 300-800 种病毒，宿主门从 2 个扩展到 3+ 个

### P1 — 代码库更新
1. 更新 `backend.py` 的 API 模型，加入新字段 (phylum, host_association_method, discovery_context)
2. 更新 `api_models.py` 添加 `HostPhylumStats`, `ExpansionStats` 等响应模型
3. 更新所有 Python 脚本中的 `crustacean_hosts` 查询使其兼容新字段
4. 更新 `release_gate.py` 中剩余的 `crustacean` 硬编码

### P2 — 数据质量
1. 修复 52 条无 PMID/DOI 的参考文献
2. 证据覆盖率从 13.5% 提升到 >50%
3. 更新 `build_sqlite_core_db_v2.py` 支持多门数据

### P3 — 珊瑚 + 棘皮动物
1. 导入全球珊瑚病毒数据库 (>20,000 条序列)
2. 导入海绵病毒数据

### 长期 — NAR 投稿准备
1. PostgreSQL 迁移
2. 公网 URL 部署 + HTTPS
3. Docker Compose + CI/CD
4. Zenodo DOI 注册
5. NAR pre-query (2027年7月1日前)

---

## 关键文件路径

| 文件 | 用途 |
|------|------|
| `EXPANSION_PLAN_AQUATIC_INVERTEBRATE.md` | 完整扩展方案 |
| `RESEARCH_SUMMARY_AQUATIC_INVERT_VIRUSES.md` | 文献调研总结 |
| `migrate_schema_aquatic_expansion.py` | Schema 迁移脚本 |
| `optimize_database_post_migration.py` | 后迁移优化脚本 |
| `expansion_migration_report.json` | 迁移执行报告 |
| `expansion_baseline.json` | 扩展前基线数据 |
| `expansion_worklist.json` | SRA 挖掘候选列表 |
| `crustacean_virus_core.db` | 主数据库 (232.3 MB) |
| `backups/pre_expansion_backup_20260512_191302.db` | 迁移前备份 |

---

## 恢复指南

新对话中：
1. 先读 `EXPANSION_PLAN_AQUATIC_INVERTEBRATE.md` 了解整体计划
2. 读 `expansion_baseline.json` 了解当前数据规模
3. 读 `expansion_migration_report.json` 了解迁移执行结果
4. Schema 变更清单在 `migrate_schema_aquatic_expansion.py` 的 Phase 1-5
5. 数据库路径: `F:/甲壳动物数据库/crustacean_virus_core.db`
