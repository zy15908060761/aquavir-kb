# AquaVir-KB：甲壳动物病毒数据库 → 水生无脊椎动物病毒知识库 扩展方案

**日期:** 2026-05-12
**目标投稿:** NAR Database Issue 2028 年 1 月刊 (pre-query 2027年7月)
**当前状态:** CrustaVirus DB v1 (526 病毒物种, 3,783 分离株, 82 种真甲壳宿主)

---

## 一、范围定义

### 新增类群（按优先级）

| 优先级 | 类群 | 代表经济物种 | 已知病毒估计 | 产业规模 |
|:---:|------|------|:---:|------|
| P0 | 软体动物 Mollusca | 牡蛎、扇贝、蛤蜊、鲍鱼、乌贼 | 200-400 | 全球贝类养殖 >300亿美元 |
| P0 | 甲壳动物 Crustacea | 现有扩展 (SRA挖掘→1,000+) | 526→1,000+ | 已有基础 |
| P1 | 棘皮动物 Echinodermata | 海参、海胆 | 50-100 | 海参养殖快速增长 |
| P2 | 刺胞动物 Cnidaria | 珊瑚、水母 | 100-200 | 生态价值大 |
| P3 | 其他 (环节/海绵/被囊/轮虫) | 沙蚕、海绵 | 80-150 | 小众 |

**最终目标规模:** 病毒物种 2,500-4,000+

---

## 二、Schema 改动

### 核心改动：只改宿主表

```sql
-- 重命名
ALTER TABLE crustacean_hosts RENAME TO aquatic_invertebrate_hosts;

-- 新增分类层级
ALTER TABLE aquatic_invertebrate_hosts ADD COLUMN phylum VARCHAR(50);
ALTER TABLE aquatic_invertebrate_hosts ADD COLUMN class VARCHAR(50);
ALTER TABLE aquatic_invertebrate_hosts ADD COLUMN host_group_new VARCHAR(80);
```

### 关键新增字段（跨表）

- `infection_records.host_association_method`: confirmed_infection | pathology_observation | disease_outbreak | co_occurrence_metagenomic | environmental_sample
- `virus_master.discovery_context`: isolated_and_cultured | metagenomic_with_host_evidence | metagenomic_environmental
- `virus_master.host_phylum`: 快速过滤用

### 不需要改的表（~100张）
序列层、地理层、证据层、注释层、策展层全部复用。

---

## 三、Pipeline 改造

### 直接复用 (~60脚本)
NCBI 导入、序列提取、蛋白质注释 (UniProt/InterPro/KEGG)、数据库构建、验证

### 需要参数化适配 (~30脚本)
- `enrich_hosts_worms_iucn.py` → 扩展数据源
- `fetch_gbif.py`/`fetch_obis.py` → 新类群查询
- `import_obis_fishbase.py` → 替换为 SeaLifeBase
- `standardize_hosts_from_cache.py` → 对接 WoRMS
- `fill_host_biology.py` → 新增滤食性/底栖/固着等字段

### 需要新建 (~15脚本)
- `search_ncbi_mollusca_viruses.py`
- `search_ncbi_echinoderm_viruses.py`
- `search_ncbi_cnidaria_viruses.py`
- `search_sra_aquatic_invert_viromes.py`
- `import_worms_taxonomy.py`
- `reconcile_host_across_phyla.py`
- `curate_mollusc_host_ecology.py`
- `detect_environmental_contamination.py`
- `validate_aquatic_invert_scope.py`

---

## 四、核心难点

### 难点 1: 滤食性动物的环境病毒污染
牡蛎每天滤水 50 加仑，富集环境病毒颗粒。
**对策:** `host_association_method` 字段，默认只将 confirmed_infection/pathology_observation/disease_outbreak 计入确认关联。

### 难点 2: 贝类病毒学领域知识
关键病毒: OsHV-1 (牡蛎), AbHV (鲍鱼), AVNV (扇贝), HaCV (鲍鱼), CMNV (跨宿主?)
**对策:** Phase 1 先做 2-3 周文献调研。

### 难点 3: 宏基因组 vs 确认病原
现有 71.5% 物种来自宏基因组调查，扩展到贝类/珊瑚后比例可能更高。
**对策:** `discovery_context` 字段，论文中分类统计。

---

## 五、分阶段时间表

```
2026 Q2 (5-6月)    甲壳动物 DB v1 收尾 + 投稿 Database 期刊
                   Track A (SRA→2,000+ 甲壳病毒)
                   Track B (蛋白质注释覆盖率)

2026 Q3 (7-9月)    Phase 1: 软体动物
                   文献调研 | Schema 扩展 | WoRMS pipeline
                   NCBI 软体动物病毒检索 | 目标 200-400 种贝类病毒

2026 Q4 (10-12月)  Phase 2: 棘皮动物 + 刺胞动物
                   海参/海胆/珊瑚病毒数据导入
                   SRA 水生无脊椎宏病毒组批量挖掘
                   初次全库质量审计

2027 Q1 (1-3月)    Phase 3: 扩展 + 深挖
                   剩余类群 | 全库策展冲刺 >50% 物种有证据记录
                   蛋白质注释管道批量运行

2027 Q2 (4-6月)    Phase 4: 论文准备
                   PostgreSQL 迁移 | 公有 URL + HTTPS
                   Docker + CI/CD | Zenodo DOI
                   论文撰写 + 内部审阅

2027 年 7月1日      NAR pre-query email
2027 年 8-9月       完整稿件投稿 NAR Database Issue
2028 年 1月         NAR Database Issue 出版
```

---

## 六、命名建议

**AquaVir-KB** (Aquatic Invertebrate Virus Knowledge Base)
— 准确、有区分度、强调 knowledge base 定位。

备选: AquaVirus DB, InvertiVirus DB

---

## 七、风险

| 风险 | 对策 |
|------|------|
| 贝类病毒数据量不如预期 | SRA 宏病毒组补充，降低确认门槛标注 |
| 环境病毒污染混淆 | schema 中主动加 host_association_method |
| 跨门策展质量下降 | 每门至少找 1 位领域专家做 advisor |
| 技术债积累 | GitHub public repo + versioned releases |
| 中文文献重复工作 | 复用 step1c_cnki_wanfang_helper.py |
