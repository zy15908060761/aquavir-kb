# Checkpoint 2026-06-01 POST-AUDIT

本文件是在 `CHECKPOINT_20260601_FINAL.md` 之后，根据 2026-06-01 全面审计结果做的修订版状态说明。后续恢复工作时优先读取本文件；`CHECKPOINT_20260601.md` 和 `CHECKPOINT_20260601_QUALITY.md` 为过时中间状态，只作为历史记录。

## 一、已直接修复的问题

### 1. 数字 canonical_name 的 ICTV/VMR 占位条目

审计指出 14 个活跃 ICTV 病毒的 `canonical_name` 为数字：

`48, 49, 7442, 7443, 7444, 7445, 7446, 8163, 13810, 13871, 14429, 14435, 14874, 14893`

复查发现这些数字不是 ICTV 官方物种 ID，而是本地 `ictv_vmr.vmr_id` 行号。更重要的是，库内已经存在对应正式物种名的 canonical master，因此这些数字记录不是缺名独立病毒，而是重复的 ICTV VMR 占位条目。

已运行：

```bash
python fix_numeric_ictv_canonical_names.py
```

处理策略：

- 将 14 条数字占位 master 的 `evidence_records` 转移到已有正式物种名 master；
- 为正式 master 增加 VMR/ICTV 映射和 `ICTV VMR row <id>` alias；
- 将数字占位 master 标记为 `entry_type='duplicate_ictv_vmr_placeholder'`、`public_visibility='internal'`、`is_crustacean_virus=0`；
- 记录 `curation_logs`，并输出报告：
  - `reports/numeric_ictv_name_resolution_applied_20260601_142309.json`
  - `reports/numeric_ictv_name_resolution_applied_20260601_142309.csv`

备份：

`backups/crustacean_virus_core_before_numeric_ictv_name_resolution_20260601_142247.db`

## 二、修复后的关键指标

| 指标 | 修复后 |
|------|------:|
| 活跃靶标病毒 broad | 1,704 |
| release-confirmed active masters | 1,699 |
| raw `analysis_target_isolates` | 8,993 |
| active-scoped 靶标分离株 | 8,993 |
| strict target isolates | 8,590 |
| 参考文献 | 9,065 |
| 证据记录 | 353,160 |
| 活跃数字 canonical_name | 0 |
| duplicate_ictv_vmr_placeholder | 14 |
| 占位条目残留证据 | 0 |
| needs_review 证据 | 13,109 |
| active 零 isolate 病毒 broad | 867 |
| release-confirmed 零 isolate 病毒 | 862 |
| active 有 NULL-reference 证据的病毒 | 769 |

说明：活跃靶标病毒数低于 `FINAL`，是因为 14 条重复 ICTV/VMR 占位条目不应再计入 active master；第三轮重新激活 OsHV-1 后，AVNV ambiguous shell (`master_id=1307`) 又按 follow-up 审计降级为 `unconfirmed_candidate` 且 `is_crustacean_virus=0`。当前 broad active master 为 1,704；若发布口径进一步排除 `unconfirmed_candidate`，release-confirmed active master 为 1,699。`analysis_target_isolates` 是 view，当前 raw/active-scoped 均为 8,993；`analysis_strict_target_isolates` 进一步排除 `conflict_open`，为 8,590。若论文继续沿用 1,717，需要明确这是“含 ICTV 编录占位条目且未修复贝类误排除”的旧口径，不建议使用。

## 三、仍需在论文/数据说明中正面披露的问题

### 1. 零 isolate 并非 20，而是 broad active 口径下 867

follow-up 审计后 broad active 零 isolate 病毒为 867；若发布口径排除 `unconfirmed_candidate`，为 862。

| 类别 | 数量 |
|------|----:|
| metagenomic/environmental | 388 |
| ICTV species list/catalog-only | 350 |
| metagenomic survey | 76 |
| RdRp/Palmscan assembly | 48 |
| DOV 2023 literature candidate | 11 |
| ncbi_mollusk_import / unconfirmed_candidate | 4 |
| metagenomic_with_host_evidence / complete_genome | 2 |
| disease_outbreak / complete_genome | 2 |

论文中应将这类记录定义为“catalog-only / metagenome-derived virus taxa”，不要称为拥有分离株的 isolate-backed records。

### 2. needs_review 为 13,109

`needs_review` 证据集中来自全文自动抽取：

- `fulltext_deep_extraction` / `fulltext_deep_extraction_v2`
- 主要 observation_type 为 `lab`
- 主要 evidence_type 为 `diagnosis` 和 `pathogenicity`

论文和数据发布中应把这部分作为自动抽取待复核层，不应等同于人工确认事实。建议在导出表中保留 `curation_status`，并在主文/方法中报告 manual_checked、auto_imported、needs_review、rejected 的比例。

### 3. NULL-reference 证据不是论文证据

active 病毒中 769 个有 `reference_id IS NULL` 的证据记录。主要来源包括：

- `ncbi_nucleotide_search`
- `sra_metagenomic_detection`
- `metagenomic_rdrp_assembly`
- `palmdb_rdrp_assembly`
- `final_integration`

这些应归类为数据库/序列/宏基因组来源证据，而不是文献证据。建议后续补充 `source_id` 或外部 accession/provenance，并在论文中分开统计 literature-backed 与 database-backed evidence。

### 4. 蛋白注释是计算推断，不是实验验证

`viral_proteins` 中：

- `domain_inferred`: 23,638
- `unannotated`: 3,290
- `rule_suggested_unreviewed`: 168

应在方法中写明蛋白功能主要来自 domain/pattern inference，未注释比例约 12.1%，不能表述为大规模实验验证注释。

### 5. 证据分布长尾和 review 主导

当前证据层仍高度不均衡，且 `observation_type='review'` 占主导。论文应强调数据库是知识库/证据索引，而不是均衡实验数据集。

## 四、建议的发布前动作

1. 更新论文和 README 中所有核心数字：broad active master 使用 1,704；release-confirmed active master 使用 1,699；零 isolate 对应使用 867 或 862；needs_review 使用 13,109。
2. 前端/API 默认隐藏 `entry_type='duplicate_ictv_vmr_placeholder'` 和 `public_visibility='internal'`。
3. 导出数据时增加口径说明：是否包含 internal / duplicate placeholder / non_target。
4. 不删除旧 checkpoint，但在 README 或恢复说明中声明本文件为最新状态。
5. 后续若要继续降低 `needs_review`，优先抽样审核 `fulltext_deep_extraction*` 的 diagnosis/pathogenicity 证据。

## 五、验证结果

已执行：

```sql
PRAGMA foreign_key_check;
PRAGMA integrity_check;
```

结果：

- `foreign_key_check`: 0 violations
- `integrity_check`: ok

---

## 八、第四轮论文前 QC 修复 (2026-06-01)

### 处理原则

第四轮审计中的 P0 问题已按“确定性修复直接执行、可能误伤的数据只导出 review queue”的原则处理。尤其是：

- 未按 family 规则批量改 `genome_type`。`parvo-like`、`circovirus-like`、旧 `Bunyaviridae` 候选和多重 ICTV 映射记录只进入 review queue。
- 未按 `(virus_master_id, evidence_type, claim)` 三列物理删除 13,737 条证据。该规则会误删不同文献来源的独立证据，例如 WSSV 的 backfill 文献证据。
- 严格重复证据只在完整核心字段一致时处理，并保留原始行、写入 quarantine、标记为 `rejected`，避免破坏外键和溯源。

已运行：

```bash
python fix_fourth_round_pre_paper_qc.py
```

### 已修复的 P0/P1 项

| 项目 | 处理结果 |
|---|---:|
| `Yingvirus charybdis` 分类错误 | 已从 `Rhabdoviridae/dsDNA` 修为 `Qinviridae/ssRNA(-)` |
| high/manual/唯一 ICTV 同步 | 5 个 master 已同步 |
| 截断证据片段 `VP`/`An `/`A `/`N` | 30 条已标记 `rejected` |
| 非 PMID 标识符混入 `pmid` | 111 条已迁移到 `external_xrefs(entity_type='reference')`，`pmid` 清空 |
| DOI=`N/A` | 1 条已清为 `NULL` |
| 严格重复证据 | 2,324 条写入 `evidence_dedup_quarantine` 并标记 `rejected` |
| RdRP `aa_length=NULL` | 仍为 48；无 `translation` 可直接回填，保留 review queue |

ICTV 同步的 5 个 master：

| master_id | 病毒 | 修复 |
|---:|---|---|
| 775 | Robaratusivirus semberis | `Unclassified/dsDNA` -> `Draupnirviridae/ssDNA(+/-)` |
| 1167 | Mivirus wuhanense | `Mypoviridae/ssRNA(+)` -> `Chuviridae/ssRNA(-)` |
| 1173 | Yingvirus charybdis | `Rhabdoviridae/dsDNA` -> `Qinviridae/ssRNA(-)` |
| 1198 | Ohlsrhavirus riverside | `ssRNA(+)` -> `ssRNA(-)` |
| 3516 | Alphaplatrhavirus turkestanicum | `Alphaflexiviridae/ssRNA(+)` -> `Rhabdoviridae/ssRNA(-)` |

### 修复后验证

```sql
PRAGMA foreign_key_check;
PRAGMA integrity_check;
```

结果：

- `foreign_key_check`: 0 violations
- `integrity_check`: ok

关键验证结果：

| 指标 | 修复后 |
|---|---:|
| `Yingvirus charybdis` family/genome_type | `Qinviridae` / `ssRNA(-)` |
| 非数字 PMID | 0 |
| DOI=`N/A` | 0 |
| 截断片段未 rejected | 0 |
| 严格重复证据 quarantine | 2,324 |
| 严格重复证据未 rejected | 0 |
| `evidence_records` 总行数 | 353,160 |
| non-rejected effective evidence | 350,716 |
| `needs_review` evidence | 12,682 |
| `rejected` evidence | 2,444 |

### 剩余 review-only 队列

修复后重新导出的队列：

- `reports/family_genome_type_incompatibility_review_20260601_163306.csv`：62 条 family/genome_type 冲突，需人工判断，不能按 family 规则批量改。
- `reports/ictv_taxonomy_mismatch_review_20260601_163306.csv`：ICTV 映射与主表不一致的候选，多数含中低置信度或多重映射。
- `reports/broad_duplicate_evidence_review_20260601_163306.csv`：宽松三列重复证据组；这些大多是不同 reference 的独立证据，不应自动删除。
- `reports/missing_reference_year_review_20260601_163306.csv`：465 条缺年份参考文献，其中 331 条被证据引用。
- `reports/short_protein_rdrp_review_20260601_163306.csv`：短蛋白和短/缺长度 RdRP 队列。

### 备份与报告

实际成功运行前备份：

- `backups/crustacean_virus_core_before_fourth_round_pre_paper_qc_20260601_162626.db`

执行摘要：

- `reports/fourth_round_pre_paper_qc_summary_20260601_162615.json`

修复后只读复核摘要：

- `reports/fourth_round_pre_paper_qc_summary_20260601_163306.json`

---

## 九、第五轮 scope/tier 口径修复 (2026-06-02)

### public_visibility 是发布分层，不是错误 flag

`public_visibility` 当前三档逻辑保持不改：

| Tier | public_visibility | 数量 | 解释 |
|---:|---|---:|---|
| 1 | `public` | 919 | 有 isolate 或有强证据支撑的核心公开记录 |
| 2 | `limited` | 739 | 无 isolate 的扩展编目记录，含 ICTV/VMR、partial genome、literature candidate、PalmDB/RdRp 等 |
| 3 | `internal_only` | 46 | host_phylum=unknown 等环境宏基因组/内部待审记录 |

论文建议表述：

> The curated public core contains 919 virus entries with isolate support or strong curated evidence, while the broader catalogue contains 1,704 active target entries including metagenome-derived, ICTV catalogue-only, and literature-candidate records.

这不是数据 bug；后续统计必须明确是 public core、limited extended catalogue，还是 broad active catalogue。

### 已修复：analysis_target_isolates 口径统一

旧 `analysis_target_isolates` 用 5 个硬编码 host phylum：

```sql
vm.host_phylum IN ('Arthropoda', 'Mollusca', 'Cnidaria', 'Echinodermata', 'Porifera')
```

这与主表 scope flag 不一致，会遗漏 `Annelida`、`Nematoda`、`Platyhelminthes`，以及 `multiple`/`unknown` 但 `is_crustacean_virus=1` 的 target records。

已运行：

```bash
python fix_fifth_round_scope_views.py
```

新 view 定义改为使用主表 target flag：

```sql
vm.is_crustacean_virus = 1
AND vm.entry_type NOT IN (
  'non_target',
  'ictv_non_target',
  'host_genome',
  'duplicate_ictv_vmr_placeholder',
  'duplicate_alias_placeholder'
)
```

修复后：

| 指标 | 修复前 | 修复后 | 变化 |
|---|---:|---:|---:|
| `analysis_target_isolates` | 8,993 | 9,171 | +178 |
| `analysis_strict_target_isolates` | 8,590 | 8,768 | +178 |

新增 178 条的来源：

| host_phylum | entry_type | curation_status | isolate |
|---|---|---|---:|
| unknown | partial_genome | needs_review | 126 |
| multiple | partial_genome | needs_review | 42 |
| Annelida | partial_genome | needs_review | 7 |
| Nematoda | partial_genome | needs_review | 2 |
| Platyhelminthes | partial_genome | needs_review | 1 |

注意：若只补新增三门类，差异是 +10；按主表 scope flag 完整统一后，`multiple` 和 `unknown` 也应纳入 broad target isolate view，因此总变化为 +178。论文中应把 `analysis_target_isolates=9,171` 定义为 broad target isolate set，把 `analysis_strict_target_isolates=8,768` 定义为 conflict-free subset。

修复后 `analysis_target_isolates` host_phylum 分布：

| host_phylum | isolate |
|---|---:|
| Mollusca | 5,070 |
| Arthropoda | 3,844 |
| unknown | 126 |
| multiple | 42 |
| Porifera | 33 |
| Cnidaria | 23 |
| Echinodermata | 23 |
| Annelida | 7 |
| Nematoda | 2 |
| Platyhelminthes | 1 |

### 已修复：v_data_dictionary 动态化

旧 `v_data_dictionary` 是早期 schema 的静态 UNION 快照，仍可查询但不会覆盖新增表/视图。已重建为动态视图：

```sql
FROM sqlite_schema AS m
JOIN pragma_table_info(m.name) AS p
WHERE m.type IN ('table', 'view')
  AND m.name NOT LIKE 'sqlite_%'
```

修复后：

| 指标 | 修复前 | 修复后 |
|---|---:|---:|
| `v_data_dictionary` rows | 1,284 | 2,336 |
| schema tables | 138 | 138 |
| schema views | 45 | 45 |

### 验证与备份

结果：

- `foreign_key_check`: 0 violations
- `integrity_check`: ok

报告：

- `reports/fifth_round_scope_views_20260602_083024.json`

备份：

- `backups/crustacean_virus_core_before_fifth_round_scope_views_20260602_083024.db`

---

## 十、最终扫描残留修复 (2026-06-02)

### 已修复：VMR 重复映射

最终扫描指出 WSSV 存在重复 VMR 映射。复核发现重复不止 WSSV，还包括少数 Wenzhou/Beihai 等条目；按 `(master_id, vmr_id)` 统一去重，保留高置信、人工/更精确匹配优先的记录。

已运行：

```bash
python fix_final_scan_residuals.py
```

结果：

| 指标 | 修复前 | 修复后 |
|---|---:|---:|
| `virus_vmr_mappings` duplicate extra rows | 25 | 0 |
| `virus_ictv_mappings` exact duplicate extra rows | 0 | 0 |

去重行清单：

- `reports/final_scan_vmr_deduplicated_rows_20260602_085930.csv`

### 已修复：Ostreid herpesvirus 1 ICTV status

`master_id=1304 Ostreid herpesvirus 1` 是已重新激活的 OsHV-1 主条目，缺少 ICTV status。已补充：

| 字段 | 值 |
|---|---|
| `ictv_id` | 49 |
| ICTV species | `Ostreavirus ostreidmalaco1` |
| family | `Malacoherpesviridae` |
| genus | `Ostreavirus` |
| genome_type | `dsDNA` |
| `ictv_status` | `mapped` |
| confidence | `high` |

注意：库内仍保留 `master_id=1370 Ostreavirus ostreidmalaco1` 作为 ICTV 官方名条目。本轮只补 1304 的 manual mapping/status，不合并 1304 与 1370，避免在最终扫描阶段引入高风险合并。

### 已修复：ATI 与 isolate_reference_links 口径

第五轮后 `analysis_target_isolates` 已按 `is_crustacean_virus=1` 统一 scope，但仍要求 `isolate_curated_profiles` 存在。最终扫描的 2,674 条 `isolate_reference_links` outside ATI 中，有 2,357 条是 target Mollusca `partial_genome` isolate，原因是这些 isolate 有 `viral_isolates` 和文献链接，但没有 curated profile。

因此再次刷新 `analysis_target_isolates`：

```sql
LEFT JOIN isolate_curated_profiles icp ON vi.isolate_id = icp.isolate_id
JOIN virus_master vm ON COALESCE(icp.master_id, vi.master_id) = vm.master_id
WHERE vm.is_crustacean_virus = 1
```

修复后：

| 指标 | 修复前 | 修复后 |
|---|---:|---:|
| `analysis_target_isolates` broad | 9,171 | 14,636 |
| with curated profile | 9,171 | 9,171 |
| without curated profile | 0 | 5,465 |
| `analysis_strict_target_isolates` | 8,768 | 8,768 |
| `isolate_reference_links` outside ATI | 2,674 | 317 |
| target `isolate_reference_links` outside ATI | 2,357 | 0 |

剩余 317 条 outside ATI 均为非靶标或 host genome：

| scope | links | isolates |
|---|---:|---:|
| non_target algae | 179 | 179 |
| host_genome Arthropoda | 129 | 106 |
| non_target Arthropoda | 8 | 4 |
| non_target Porifera | 1 | 1 |

新的 isolate 口径建议：

- `analysis_target_isolates=14,636`：broad target sequence set，包含没有 curated profile 但 master 已判定 target 的序列。
- `analysis_target_isolates` with curated profile = 9,171：profile-backed target sequence set。
- `analysis_strict_target_isolates=8,768`：conflict-free curated/profile-backed publication subset。

论文中如果强调 curated/profile-backed 数据，应使用 9,171 或 8,768；如果强调全部 target sequence catalogue，可使用 14,636，但必须说明包含未 profile 化的 partial genome/metagenomic contigs。

### 备份膨胀处理

未自动删除备份。当前备份目录：

| 指标 | 数值 |
|---|---:|
| backup files | 72 |
| total size | 52.27 GB |

已导出清单：

- `reports/backup_inventory_20260602_085930.csv`

发布前建议：

1. 本地保留关键备份：R1/数字 ICTV 修复前、第三轮 OsHV 修复前、第四轮 pre-paper QC 前、第五轮 scope view 前、最终扫描修复前、当前最终库。
2. 其余 2026-06-01 中间失败/重复 dry-run 备份转移到外部存储后再删除。
3. 不建议脚本自动删除，避免丢失可回滚点。

### 验证与报告

验证结果：

- `foreign_key_check`: 0 violations
- `integrity_check`: ok

报告：

- `reports/final_scan_residuals_20260602_085930.json`

备份：

- `backups/crustacean_virus_core_before_final_scan_residuals_20260602_085930.db`

---

## 十一、最终 profile 指向修复 (2026-06-02)

最终扫描后新增发现 3 条 `isolate_curated_profiles.master_id` 指向错误：

| isolate_id | accession | 错误 master_id | 正确 master_id |
|---:|---|---:|---:|
| 2092 | MK861116.1 | 26 (`Non-crustacean virus`) | 346 (`European shore crab virus 1`) |
| 2093 | MK861117.1 | 26 | 346 |
| 2094 | MK861118.1 | 26 | 346 |

已执行最小修复：

```sql
UPDATE isolate_curated_profiles
SET master_id=346
WHERE isolate_id IN (2092,2093,2094)
  AND master_id=26;
```

未创建全库备份，原因是当前备份目录已经膨胀到 52GB+；已导出修复前快照：

- `reports/final_profile_master_fix_before_20260602_103712.csv`

修复结果：

| 指标 | 修复后 |
|---|---:|
| 3 条 isolate 进入 `analysis_target_isolates` | 3/3 |
| 3 条 isolate 进入 `analysis_strict_target_isolates` | 3/3 |
| 相关 `isolate_reference_links` outside ATI | 0 |
| `analysis_target_isolates` broad | 14,639 |
| `analysis_strict_target_isolates` | 8,771 |

验证：

- `foreign_key_check`: 0 violations
- `integrity_check`: ok

报告：

- `reports/final_profile_master_fix_20260602_103956.json`

---

## 六、第二轮审计修复 (2026-06-01)

### 已修复：non_target scope flag 脏数据

第二轮审计发现多数 `entry_type='non_target'` 记录仍保留 `is_crustacean_virus=1`。已运行：

```bash
python fix_second_round_audit_flags.py
```

修复内容：

- `entry_type IN ('non_target','ictv_non_target')` 的记录统一设置 `is_crustacean_virus=0`；
- non_target 中 `public_visibility IN ('public','limited')` 的记录改为 `internal_only`；
- 修复后：
  - `non_target_is_cv_1 = 0`
  - `non_target_public_or_limited = 0`
  - `is_crustacean_virus=1` 总数 = 1,703，与 active target master 数一致。

报告：

- `reports/second_round_audit_fix_summary_20260601_145418.json`

备份：

- `backups/crustacean_virus_core_before_second_round_audit_fixes_20260601_145419.db`

### 已修复：非标准 genome_type

3 条主表非标准值已处理：

| master_id | 病毒 | 原值 | 修复后 |
|---:|------|------|------|
| 1327 | Oyster-associated Riboviria (DOV 2023) | RNA | ssRNA |
| 1554 | Crassostrea gigas Riboviria virus 1 | RNA | ssRNA |
| 3525 | Philippines blood fluke virus 2 | mRNA | NULL |

修复后 `virus_master.genome_type IN ('RNA','mRNA') = 0`。

### 未批量覆盖：genome_type 主表/Profile 冲突

第二轮审计报告称 429 处冲突。按当前库修复后重新统计：

| 口径 | 冲突数 |
|------|------:|
| 全库 master/profile 冲突 | 438 |
| active target master/profile 冲突 | 208 |
| active 中 Profile 可能错误：master=analysis_target=viral_isolate，profile 不同 | 153 |
| active 中 master 可能错误：profile=analysis_target=viral_isolate，master 不同 | 23 |
| active 中混合/部分支持 | 32 |

结论：不能直接用 `isolate_curated_profiles.genome_type` 覆盖 `virus_master.genome_type`。很多记录中 `analysis_target_isolates` 和 `viral_isolates` 都与 master 一致，反而是 Profile 字段陈旧或错误。已导出复核队列：

- `reports/genome_type_conflict_review_queue_20260601_145418.csv`

建议下一步优先处理该 CSV 中 `conflict_class='master_differs_from_profile_and_isolate_tables'` 的 23 条，再处理 `mixed_or_missing_isolate_table_support` 的 32 条。153 条 Profile 可能错误的记录应更新 Profile，而不是改 master。

### 尚未修复但需披露：蛋白覆盖缺口

当前 active sequenced isolates：

- `has_sequence=1` active isolates: 3,416
- 有序列但无蛋白注释: 736
- 仅 1 个蛋白记录: 2,300
- protein 记录不在 `analysis_target_isolates`: 675 个蛋白，涉及 505 个 isolate

论文中不能笼统写“蛋白注释覆盖 87%”。更准确的写法是：蛋白层主要覆盖可预测 ORF / RdRp / domain-inferred annotations，完整 ORF 注释在 WSSV/Nimaviridae 等高价值类群仍有缺口。

### 尚未修复但需披露：灰色文献

参考文献中 480 条无 PMID 且无 DOI，其中 318 条被证据引用。主要是机构报告、GenBank Direct Submission、WOAH/CABI/NACA 等灰色文献。论文中应单列 literature-backed、database-backed、grey-literature evidence。

### 低危保留

- active `host_phylum='unknown'`: 43，均为 metagenomic_survey/环境来源，可作为宿主未知记录保留。
- raw isolate 表与 target isolate 表差异很大是预期设计，不是错误。发布时必须说明 `viral_isolates`、`analysis_target_isolates`、active master 过滤口径不同。

### 第二轮验证结果

已执行：

```sql
PRAGMA foreign_key_check;
PRAGMA integrity_check;
```

结果：

- `foreign_key_check`: 0 violations
- `integrity_check`: ok

---

## 七、第三轮审计修复 (2026-06-01)

### 已修复：重要贝类病毒误排除

第三轮审计发现多个 Mollusca 靶标病毒被 `is_crustacean_virus=0` 排除。已运行：

```bash
python fix_third_round_mollusk_and_isolate_qc.py
```

修复内容：

| master_id | 病毒 | 修复 |
|---:|------|------|
| 1304 | Ostreid herpesvirus 1 | 重新激活为 target；保留 `entry_type='complete_genome'`、`host_phylum='Mollusca'` |
| 1307 | acute viral necrosis virus | 初始重新激活；follow-up 后因 AVNV/548 高重叠且无 isolate，降级为 limited unconfirmed candidate |
| 1303 | ostreid herpesvirus | 作为小写重复壳归档，证据并入 1304 |

修复后关键状态：

| master_id | canonical_name | is_cv | entry_type | ATI | evidence | refs |
|---:|------|---:|------|---:|---:|---:|
| 1304 | Ostreid herpesvirus 1 | 1 | complete_genome | 801 | 2,097 | 364 |
| 546 | Ostreid herpesvirus 1 microvariant | 1 | complete_genome | 0 | 410 | 220 |
| 1303 | ostreid herpesvirus duplicate of Ostreid herpesvirus 1 | 0 | duplicate_alias_placeholder | 0 | 0 | 0 |
| 1307 | acute viral necrosis virus | 0 | unconfirmed_candidate | 0 | 2,705 | 1,316 |

说明：没有把 `Ostreid herpesvirus 1 microvariant` 合并进 1304。microvariant 是变体/亚型概念，直接合并会丢失语义；后续应在前端/论文中作为 OsHV-1 的 variant/subtype 关系处理，而不是同义词。

### Follow-up：AVNV shell 纠偏

第三轮初始修复把 `master_id=1307 acute viral necrosis virus` 重新激活；随后只读复核发现该记录无 isolate，且与 `master_id=548 Abalone viral necrosis virus` 的 active reference 高度重叠：

| 对比 | refs A | refs B | overlap | A only | B only |
|------|------:|------:|------:|------:|------:|
| 1307 vs 548 | 1,316 | 1,288 | 1,230 | 86 | 58 |

因此已运行：

```bash
python fix_third_round_followup_avnv.py
```

处理结果：

- `1307` 设置为 `is_crustacean_virus=0`
- `entry_type='unconfirmed_candidate'`
- `public_visibility='limited'`
- 证据暂不并入 548，避免把 generic necrosis 弱匹配污染 HaHV-1/AVNV 主记录

报告：

- `reports/third_round_followup_avnv_20260601_154900.json`

备份：

- `backups/crustacean_virus_core_before_third_round_followup_avnv_20260601_154900.db`

报告：

- `reports/third_round_mollusk_isolate_qc_summary_20260601_153432.json`

备份：

- `backups/crustacean_virus_core_before_third_round_mollusk_isolate_qc_20260601_153432.db`

### 已修复：isolate 表 genome_type 非标准值

`analysis_target_isolates` 是 `viral_isolates` 的 view，因此修复底层 `viral_isolates.genome_type` 后，ATI 同步清理。

修复映射：

| 原值 | 修复后 |
|------|------|
| RNA | ssRNA |
| DNA | dsDNA |
| mRNA | NULL |

修复后：

- `analysis_target_isolates genome_type IN ('RNA','DNA','mRNA') = 0`
- `viral_isolates genome_type IN ('RNA','DNA','mRNA') = 0`

### 已修复：created_at 非 ISO 格式

25 条 `metagenomic_dataset_annotation` 证据的 `created_at` 从 `YYYYMMDD_HHMMSS` 规范化为 `YYYY-MM-DD HH:MM:SS`。

修复后：

- 非 ISO `created_at` = 0

### 空表处理

当前发现 5 张空表：

- `auto_annotation_gap_worklist`
- `auto_completeness_fills`
- `auto_quality_metrics`
- `literature_backfill_candidate_promotions`
- `submission_p0_release_blockers`

已导出：

- `reports/empty_tables_review_20260601_153432.csv`

未直接 drop。原因：这些表是 worklist / metrics / release blocker 类结构，空表可表示“当前无待办”，删除可能破坏脚本或前端假设。若要减重，建议在 release bundle 中排除，而不是从工作库删除。

### 第三轮修复后的核心计数

| 指标 | 数值 |
|------|----:|
| broad active target masters | 1,704 |
| release-confirmed active masters | 1,699 |
| raw `analysis_target_isolates` | 8,993 |
| `analysis_strict_target_isolates` | 8,590 |
| evidence_records | 353,160 |

注意：`analysis_target_isolates` 是 view，不是物理表；它不按 `is_crustacean_virus` 过滤，而按 `host_phylum` 和 `entry_type` 过滤。因此激活 1304 不改变 raw ATI 总数，但会改变以 `is_crustacean_virus=1` 为准的 active master 口径。

### 第三轮验证结果

已执行：

```sql
PRAGMA foreign_key_check;
PRAGMA integrity_check;
```

结果：

- `foreign_key_check`: 0 violations
- `integrity_check`: ok
