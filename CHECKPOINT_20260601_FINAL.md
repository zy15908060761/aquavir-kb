# Checkpoint 2026-06-01 FINAL — 数据库全维度优化完成

## 快速恢复
```
读取本文件了解状态后继续。DB: crustacean_virus_core.db (~874 MB, SQLite WAL)
工具库: db_utils.py (DB_PATH, backup_database, db_connection, db_transaction)
所有优化脚本在项目根目录，均支持 --dry-run
```

---

## 一、最终状态

| 维度 | 数值 | 说明 |
|------|------|------|
| 靶标病毒 | **1,717** | 优化前 1,820 (103 条非水生错配被标记 non_target) |
| 非靶标 | 1,808 | 优化前 1,705 |
| 靶标分离株 | 8,993 | has_sequence 3,416 |
| 参考文献 | 9,065 | PMID 8,455+ / DOI 8,198+ |
| 证据记录 | 353,160 | high 13.5% / medium 86.1% / low 0.4% |
| 蛋白/结构域 | 27,096 / 71,537 | |
| 序列文件 | 3,898 FASTA | |
| 表/视图 | 140 / 45 | |

### 宿主门类 (1,717 active)

Arthropoda **622** > Mollusca **398** > Cnidaria 57 > Nematoda 55 > Echinodermata 51 > Porifera 45 > Annelida 32 > Platyhelminthes 30 > Rotifera 4

### 剩余缺口 (最终)

| 缺口 | 初始 | 最终 | 状态 |
|------|:---:|:---:|------|
| P0-1 缺文献 | 574 | **0** | ✅ 清零 |
| P0-2 零 isolate | 26 | 20 | DOV 编录+Malaco 疱疹 (需人工) |
| P0-3 零证据 | 61 | **2** | Locarnavirus + Antarcticum (pending review) |
| P1-1 缺 genome_type | 192 | **72** | 宏基因组新发现，无 ICTV 记录 |
| P1-2 缺 family | 143 | **68** | 宏基因组新发现，科级未知是正确状态 |
| P1-3/4 缺 geography | 81%→58% | 42.0% | 4,326/10,302 profiles 有 country |
| ICTV mapped | 36 | **443** | 24.3% of 1,820 (was 2.0%) |
| VMR mappings | 95 | **548** | ×5.8 |

---

## 二、本轮完成的工作 (2026-06-01, 两个会话)

### 会话 1: 9维优化
- P0-1: 574→50 (NCBI EFetch 文献回填)
- P0-2: catalog_only/DOV 条目标记
- P0-3: 25 牡蛎病毒 → PMID:36611217 (Microbiome, 2023)
- P0-4: ICTV mapped 36→443, 1,454 status 行创建
- P1-1: genome_type 192→128 (科级推断+isolate回填)
- P1-5: FASTA 同步 (28 RDRP + 143 下载 + 3,904 清理)
- Geography: 1,981→3,005 (sample_metadata 解析)

### 会话 2: 深度清理 + 扩展
- P0-1: 50→**0** (超时批次重试, +47 refs)
- P0-3: 36→**2** (34 non_target, 2 pending)
- ICTV VMR: 95→**548** (accession 匹配 +101, 物种名匹配 +352)
- Geography: 3,005→**4,326** (NCBI GenBank XML 25批, +1,321)
- Minor phyla: 69 错配标记 non_target, 8 phylum 修正
- 缺 family: 137→**68** (均为合理的新发现病毒)
- 缺 genome_type: 120→**72**

---

## 三、所有优化脚本

| 脚本 | 用途 | 
|------|------|
| `backfill_isolate_references.py` | P0-1 NCBI EFetch 文献回填 |
| `remediate_zero_isolate_evidence.py` | P0-2+P0-3 孤儿修复 + DOV 2023 证据 |
| `improve_ictv_classification.py` | P0-4+P1-1+P1-2 ICTV 状态 + 科级推断 |
| `backfill_geography.py` | P1-3/4 本地源地理填充 |
| `fetch_geo_from_ncbi.py` | P1-3/4 NCBI GenBank XML 地理抓取 |
| `sync_fasta_files.py` | P1-5 FASTA 同步 |
| `upgrade_evidence_to_high.py` | 证据5策略升级 (前次) |
| `expand_evidence_depth.py` | 全文深度证据提取 (前次) |

---

## 四、待优化方向

1. **P0-2 孤儿 master 策展** — 20 个需人工确认/文献补充
2. **P0-3 2 个 pending** — Locarnavirus (Marine RNA virus SF-1) + Antarcticum marna-like virus
3. **Geography 继续提升** — 42%→70%+ 需处理非 NCBI accession 的宿主来源推断 + NCBI 超时批次重试
4. **论文准备** — 图6张打磨 / 方法撰写 / 附表 / Zenodo DOI / Docker 部署

---

## 五、常用诊断 SQL

```sql
-- 全状态速查
SELECT 
  (SELECT COUNT(*) FROM virus_master WHERE is_crustacean_virus=1 AND entry_type NOT IN ('non_target','ictv_non_target')) as active,
  (SELECT COUNT(*) FROM analysis_target_isolates) as target_isolates,
  (SELECT COUNT(*) FROM evidence_records) as evidence,
  (SELECT COUNT(*) FROM ref_literatures) as refs,
  (SELECT COUNT(*) FROM virus_vmr_mappings) as vmr_mappings;

-- 零文献
SELECT COUNT(*) FROM analysis_target_isolates WHERE reference_id IS NULL AND isolate_id NOT IN (SELECT isolate_id FROM isolate_reference_links);

-- 零证据
SELECT COUNT(*) FROM virus_master vm WHERE vm.is_crustacean_virus=1 AND vm.entry_type NOT IN ('non_target','ictv_non_target') AND NOT EXISTS (SELECT 1 FROM evidence_records WHERE virus_master_id=vm.master_id);

-- 地理
SELECT COUNT(*) FROM isolate_curated_profiles WHERE country IS NOT NULL AND country != '';

-- ICTV
SELECT ictv_status, COUNT(*) FROM virus_ictv_status GROUP BY ictv_status;
```
