# AquaVir-KB 数据采集规格说明书

**项目名称:** AquaVir-KB（Aquatic Invertebrate Virus Knowledge Base，水生无脊椎动物病毒知识库）
**文档用途:** 供专业数据采集团队报价/执行的规格说明书
**文档日期:** 2026-05-26
**版本:** v1.0

---

## 一、项目背景——我们要做什么

### 1.1 一句话总结

我们正在构建**全球唯一专门覆盖水生无脊椎动物病毒的综合知识库**，目标是 2028 年 1 月刊于 *Nucleic Acids Research* (NAR) Database Issue。现有甲壳动物病毒数据 1,283 种，现需将范围扩展至**软体动物、棘皮动物、刺胞动物、海绵动物、被囊动物等全部水生无脊椎动物门类**。

### 1.2 与 NCBI/GenBank/ICTV 的区别

我们的核心差异化优势是**文献证据链 + 病毒-宿主关联**：

- 每条记录可追溯到具体 PubMed 文献 + 段落级原文
- 每条病毒-宿主关联有证据等级标注（确认感染 / 病理观察 / 疾病暴发 / 宏基因组共现 / 环境样本）
- 整合：病毒分类 + 宿主生态 + 地理分布 + 蛋白质功能 + 诊断方法

### 1.3 现有系统概况

| 指标 | 当前值 |
|------|--------|
| 数据库系统 | SQLite 3 → 目标迁移 PostgreSQL |
| 表数量 | 119 |
| 病毒物种 | 1,283（目标水生无脊椎: 902 种） |
| 分离株/蛋白质 | 11,353 / 26,894 |
| 文献证据 | 347,283 条 |
| 参考文献 | 7,508 篇（7,215 有 DOI） |
| 全文 PDF/XML | 2,831 篇 |
| 宿主物种 | 160（主要是甲壳动物 66 种 + 软体动物 4 种） |

### 1.4 本次外包的目标

**将宿主范围从 ~160 种扩展到 ~500+ 种水生无脊椎动物，病毒物种从 1,283 增至 2,500-4,000 种，对应的文献证据、分离株、蛋白质、地理分布等数据全部补齐。**

---

## 二、爬取目标与物种范围

### 2.1 整体分类学框架

按门（Phylum）分批执行，优先级从高到低：

| 优先级 | 门 (Phylum) | 核心类群 | 预估宿主种数 | 预估新增病毒 | 计划完成时间 |
|:---:|------|------|:---:|:---:|------|
| **P0** | Mollusca（软体动物） | 双壳纲、腹足纲、头足纲 | 80-120 | 200-400 | 2026 Q3 |
| **P1** | Echinodermata（棘皮动物） | 海参纲、海胆纲、海星纲 | 30-50 | 80-150 | 2026 Q4 |
| **P1** | Cnidaria（刺胞动物） | 珊瑚纲、水螅纲、钵水母纲 | 40-60 | 80-200 | 2026 Q4 |
| **P1** | Nematoda（线虫动物）* | 海洋/淡水寄生线虫 | 15-30 | 40-80 | 2026 Q4 |
| **P2** | Platyhelminthes（扁形动物）* | 吸虫纲、绦虫纲 | 15-25 | 20-50 | 2027 Q1 |
| **P2** | Porifera（海绵动物） | 寻常海绵纲、钙质海绵纲 | 20-40 | 50-100 | 2027 Q1 |
| **P2** | Annelida（环节动物）* | 多毛纲、蛭纲 | 10-20 | 20-40 | 2027 Q1 |
| **P3** | Rotifera / Tardigrada / Bryozoa / Chaetognatha / 其他 | 轮虫、水熊、苔藓虫、箭虫等 | 各 5-15 | 各 10-30 | 2027 Q1-Q2 |
| **SRA** | 所有门类 | 公共宏基因组/宏转录组数据挖掘 | — | 500-1,500 | 2027 Q1-Q2 |

> *注：Nematoda / Platyhelminthes / Annelida 仅包含**水生/水产养殖相关**物种，不含陆生自由生活或人类寄生虫。

### 2.2 宿主物种清单交付物

我们已有 160 种甲壳动物宿主的基础数据。**数据团队需要**：

1. 从 NCBI Taxonomy、WoRMS（World Register of Marine Species）、FAO水产统计等来源，按上述门类构建**目标宿主物种候选清单**
2. 每个物种至少包含：**学名、中文俗名、NCBI TaxID、分类层级（门-纲-目-科）、栖息环境（海/淡/半咸）、养殖地位**
3. 我方审核确认后，该清单即为爬取范围

---

## 三、数据来源（从哪里爬）

### 3.1 必须覆盖的数据源

| 来源类别 | 具体来源 | 用途 | 获取方式 |
|------|------|------|------|
| **文献主库** | PubMed / Europe PMC | 文献检索、摘要、PMID/DOI 获取 | 官方 API（E-utilities / EPMC API） |
| **序列数据库** | NCBI Nucleotide (nt/nr)、NCBI Protein、RefSeq | 病毒分离株 accession、基因组、蛋白序列 | NCBI E-utilities + Entrez Direct |
| **病毒专门库** | ICTV Master Species List (MSL)、Virus-Host DB | 病毒分类学标准名、病毒-宿主关联 | 官网下载 / API |
| **蛋白质注释** | UniProt、InterPro、Pfam、KEGG | 病毒蛋白功能注释、结构域 | 各官方 API |
| **全文获取** | PubMed Central (PMC) OA、Europe PMC、Unpaywall、Semantic Scholar | 全文 PDF/XML 下载 | 官方 API + OA 链接 |
| **宿主分类** | NCBI Taxonomy、WoRMS、FAO | 宿主物种分类学 | 官网 / API |
| **地理生态** | GBIF、OBIS | 宿主地理分布、生态位 | API |

### 3.2 建议覆盖的数据源

| 来源类别 | 具体来源 | 用途 |
|------|------|------|
| **中文文献** | CNKI（中国知网）、万方 | 中文水产病害文献（中国沿海养殖软体/甲壳病害） |
| **日韩文献** | J-STAGE、KCI | 日韩水产病毒学文献 |
| **预印本** | bioRxiv、medRxiv | 最新病毒发现（尚未正式发表） |
| **专利** | Google Patents、WIPO | 病毒检测/疫苗专利 |
| **SRA** | NCBI SRA / ENA | 宏基因组/宏转录组原始数据挖掘 |

### 3.3 关于中文文献的特别说明

中国是全球最大的水产养殖国，大量软体动物（牡蛎、扇贝、蛤、鲍鱼、珍珠贝）和甲壳动物（虾、蟹）病害文献发表在中文期刊（《水产学报》《海洋与湖沼》《中国水产科学》《渔业科学进展》等）。**中文文献覆盖对数据库的完整性至关重要**，请团队确认是否具备中文文献检索与数据提取能力。

---

## 四、数据字段需求详表

以下按数据库层级列出需要采集的字段。"来源"列说明该字段应从何处获取。

### 4.1 病毒核心信息（对应 virus_master 表）

| 字段 | 类型 | 必填 | 说明 | 数据来源 | 示例 |
|------|------|:---:|------|------|------|
| canonical_name | VARCHAR(200) | ✅ | 病毒标准名 | ICTV / NCBI Taxonomy | White spot syndrome virus |
| chinese_name | VARCHAR(200) | | 中文名 | 中文文献 / ICTV 中文版 | 白斑综合征病毒 |
| virus_family | VARCHAR(100) | ✅ | 病毒科 | ICTV / NCBI Taxonomy | Nimaviridae |
| virus_genus | VARCHAR(100) | | 病毒属 | ICTV / NCBI Taxonomy | Whispovirus |
| genome_type | VARCHAR(50) | ✅ | 基因组类型 | NCBI Nucleotide / 文献 | dsDNA |
| entry_type | VARCHAR(50) | | 数据完整度 | 自行判断 | complete_genome / partial_genome |
| discovery_context | VARCHAR(50) | ✅ | 发现方式 | 文献方法部分 | metagenomic_environmental / isolated_and_cultured |
| host_phylum | VARCHAR(50) | ✅ | 关联宿主门 | 文献 / NCBI Taxonomy | Mollusca |

### 4.2 病毒分离株与序列（对应 viral_isolates 表）

| 字段 | 类型 | 必填 | 说明 | 数据来源 | 示例 |
|------|------|:---:|------|------|------|
| accession | VARCHAR(50) | ✅ | GenBank accession | NCBI Nucleotide | NC_003225 |
| virus_name | VARCHAR(200) | | 原始记录中的病毒名 | NCBI 记录 | WSSV isolate CN-01 |
| taxon_family / genus / species | VARCHAR(100) | | NCBI 分类 | NCBI Taxonomy | Nimaviridae / Whispovirus / WSSV |
| genome_accession | VARCHAR(50) | | 基因组 accession（如有不同） | NCBI Assembly | GCF_000844185 |
| genome_length | INTEGER | ✅ | 基因组全长（bp） | NCBI Nucleotide / Assembly | 305107 |
| gc_content | REAL | | GC 含量（%） | NCBI / 自算 | 41.2 |
| molecule_type | VARCHAR(20) | | 分子类型 | NCBI Nucleotide | genomic DNA |
| sequence_length | INTEGER | ✅ | 序列长度 | NCBI Nucleotide | 305107 |
| has_sequence | INTEGER | | 0=无序列, 1=有 | 自动判断 | 1 |
| completeness | VARCHAR(50) | | 基因组完整度 | NCBI / 文献 | complete / partial / segment |
| reference_id | INTEGER | | 关联文献 ID | PubMed / NCBI | 对应 ref_literatures.reference_id |

### 4.3 病毒蛋白质（对应 viral_proteins 表）

| 字段 | 类型 | 必填 | 说明 | 数据来源 | 示例 |
|------|------|:---:|------|------|------|
| protein_accession | VARCHAR(50) | ✅ | NCBI 蛋白质 accession | NCBI Protein | NP_477651 |
| protein_name | VARCHAR(500) | ✅ | 蛋白质名 | NCBI Protein | RNA-dependent RNA polymerase |
| gene_symbol | VARCHAR(100) | | 基因符号 | NCBI Gene | RdRp |
| locus_tag | VARCHAR(100) | | 位点标签 | NCBI / RefSeq | WSSV_001 |
| aa_length | INTEGER | ✅ | 氨基酸长度 | NCBI Protein / 自算 | 1825 |
| genome_start / end | INTEGER | | 基因组位置 | NCBI 注释 | 1..5478 |
| translation | TEXT | | 氨基酸序列 | NCBI Protein / FASTA | (sequence string) |
| functional_category | VARCHAR(50) | | 功能类别 | UniProt / InterPro / 文献 | replicase |
| is_rdrp | INTEGER | | 0/1 是否为 RdRp | Pfam / UniProt | 1 |

### 4.4 宿主信息（对应 crustacean_hosts 表，将扩展为 aquatic_invertebrate_hosts）

| 字段 | 类型 | 必填 | 说明 | 数据来源 | 示例 |
|------|------|:---:|------|------|------|
| scientific_name | VARCHAR(100) | ✅ | 宿主学名 | WoRMS / NCBI Taxonomy | Crassostrea gigas |
| common_name_cn | VARCHAR(100) | | 中文俗名 | 中文文献 / FAO | 长牡蛎 / 太平洋牡蛎 |
| taxon_order | VARCHAR(100) | ✅ | 目 | NCBI Taxonomy / WoRMS | Ostreida |
| taxon_family | VARCHAR(100) | ✅ | 科 | NCBI Taxonomy / WoRMS | Ostreidae |
| **phylum** | VARCHAR(50) | ✅ | **门** | NCBI Taxonomy | Mollusca |
| **class** | VARCHAR(50) | ✅ | **纲** | NCBI Taxonomy | Bivalvia |
| host_group | VARCHAR(50) | | 宿主类群 | FAO / 文献 | oyster / clam / abalone |
| habitat | VARCHAR(100) | ✅ | 栖息地 | FAO / WoRMS / 文献 | marine / freshwater / brackish |
| aquaculture_status | VARCHAR(50) | | 养殖地位 | FAO统计 / 文献 | major / minor / wild_only |

### 4.5 文献记录（对应 ref_literatures 表）

| 字段 | 类型 | 必填 | 说明 | 数据来源 | 示例 |
|------|------|:---:|------|------|------|
| pmid | VARCHAR(20) | ✅ | PubMed ID | PubMed / EPMC | 34567890 |
| title | TEXT | ✅ | 标题 | PubMed / Crossref | A novel RNA virus... |
| authors | TEXT | ✅ | 作者 | PubMed | Zhang Y, Li M, ... |
| journal | TEXT | ✅ | 期刊 | PubMed | Journal of Invertebrate Pathology |
| year | VARCHAR(10) | ✅ | 出版年 | PubMed | 2024 |
| doi | VARCHAR(100) | ✅ | DOI | Crossref / PubMed | 10.1016/j.jip.2024.108000 |
| abstract | TEXT | | 摘要 | PubMed / EPMC | (full abstract text) |
| keywords | TEXT | | 关键词 | PubMed / 文献 | aquatic virus, mollusk... |

### 4.6 文献证据记录（对应 evidence_records 表——核心竞争力表）

| 字段 | 类型 | 必填 | 说明 | 数据来源 |
|------|------|:---:|------|------|
| evidence_type | TEXT | ✅ | 证据类型（host_association / genome / transmission / mortality / prevalence / temperature / diagnostic） | 从文献内容判断 |
| virus_master_id | INTEGER | | 关联病毒 ID | 系统内关联 |
| host_id | INTEGER | | 关联宿主 ID | 系统内关联 |
| reference_id | INTEGER | ✅ | 关联文献 ID | 系统内关联 |
| claim | TEXT | ✅ | 核心声明（一句话总结文献发现） | **需从文献段落提取/总结** |
| value_numeric_min / max | REAL | | 数值型值（如检出率、死亡率、温度） | 文献结果部分 |
| unit | TEXT | | 单位 | % / °C / copies/mg |
| context | TEXT | | 上下文信息 | 文献方法/结果 |
| evidence_strength | TEXT | ✅ | 证据强度 high/medium/low | **按以下规则判断** |
| source_pmid | TEXT | ✅ | PubMed ID | PubMed |
| source_doi | TEXT | ✅ | DOI | Crossref / PubMed |
| extraction_method | TEXT | | 提取方式 | auto / manual / hybrid |

**evidence_strength 判断规则（需要人工或高质量 NLP 判断）：**

| 等级 | 判断标准 | 示例 |
|------|------|------|
| **high** | 有实验感染/分离培养 + 病理组织学/电镜照片 | 柯霍氏法则验证、细胞系分离 |
| **medium** | RT-PCR 检测 + 临床症状关联 / 多篇文献佐证 | PCR 检出+组织病变 |
| **low** | 仅宏基因组序列共现、无实验验证 / 单一文献 | 环境样本 BLAST 匹配 |

### 4.7 病毒感染记录（对应 infection_records 表）

| 字段 | 类型 | 必填 | 说明 | 数据来源 |
|------|------|:---:|------|------|
| host_id | INTEGER | ✅ | 宿主 ID | 系统内关联 |
| detection_method | VARCHAR(100) | ✅ | 检测方法 | 文献方法部分 |
| disease_symptom | TEXT | | 疾病症状 | 文献结果/讨论 |
| mortality_rate | VARCHAR(50) | | 死亡率描述 | 文献结果 |
| isolation_source | VARCHAR(100) | | 分离来源（组织/器官） | 文献方法 |
| **host_association_method** | VARCHAR(50) | ✅ | **证据等级——最关键的字段之一** | **按下方枚举值判断** |
| reference_id | INTEGER | ✅ | 文献 ID | 系统内关联 |

**host_association_method 枚举值（证据等级从高到低）：**
1. `confirmed_infection` — 实验确认感染（Koch's postulates、细胞系分离培养）
2. `pathology_observation` — 病理组织学观察（HE 染色、TEM 电镜观察到病毒颗粒 + 组织病变）
3. `disease_outbreak` — 疾病暴发关联（养殖场暴发期间检测阳性，排除其他病原）
4. `co_occurrence_metagenomic` — 宏基因组共现（宏转录组/宏基因组中检出 + 宿主信息明确）
5. `environmental_sample` — 环境样本检出（海水/沉积物样本，宿主关联不确定）

### 4.8 样本采集信息（对应 sample_collections 表）

| 字段 | 类型 | 必填 | 说明 |
|------|------|:---:|------|
| country | VARCHAR(100) | ✅ | 国家 |
| province | VARCHAR(100) | | 省份/州 |
| city | VARCHAR(100) | | 城市 |
| site_name | VARCHAR(200) | | 采集点名称 |
| latitude / longitude | REAL | | 经纬度（若有） |
| collection_year | VARCHAR(10) | ✅ | 采集年份 |
| source_type | VARCHAR(50) | ✅ | 样本类型（tissue / water / sediment / hemolymph） |
| continent | VARCHAR(50) | | 大洲 |

### 4.9 全文获取（对应 literature_fulltext_sources / literature_fulltext_sections）

| 字段 | 类型 | 说明 |
|------|------|------|
| pmid / doi / pmcid | TEXT | 标识符 |
| source | TEXT | 来源（europe_pmc / semantic_scholar / unpaywall / pubmed_central） |
| status | TEXT | 下载状态（downloaded / not_found / paywalled） |
| oa_status | TEXT | OA 状态 |
| fulltext_url / pdf_url / xml_url | TEXT | 全文下载地址 |
| local_path | TEXT | 本地存储路径（PDF 或 XML） |
| content_type | TEXT | 内容类型（xml/pdf） |
| license | TEXT | 版权许可（CC BY / CC BY-NC 等） |

**全文段落提取**（如有 NLP 能力，从 XML/PDF 中提取）：

| 字段 | 说明 |
|------|------|
| section_type | 段落类型（abstract / introduction / methods / results / discussion） |
| section_title | 段落标题 |
| text | 段落原文 |
| char_count | 字符数 |

### 4.10 蛋白质功能注释（对应 Layer 5 各表）

| 字段类别 | 说明 | 数据来源 |
|------|------|------|
| 结构域（Pfam/InterPro/CDD） | 蛋白质功能域位置和注释 | InterPro API / PfamScan |
| GO 术语 | 分子功能/生物学过程/细胞组分 | UniProt / InterPro |
| EC 酶编号 | 酶功能 | UniProt / KEGG |
| 蛋白质 3D 结构预测 | ESMFold 预测（可选） | ESMFold API |

### 4.11 数据来源追踪（对应 data_provenance 表）

**每条记录必须有来源追溯**：

| 字段 | 说明 |
|------|------|
| table_name | 数据类型（virus / isolate / protein / host / evidence） |
| record_id | 对应表记录 ID |
| virus_name | 病毒名 |
| data_source | 来源（NCBI / UniProt / EPMC / CNKI / SRA / manual） |
| confidence_level | 置信度（high / medium / low） |
| verification_method | 验证方式（api_crosscheck / manual_review） |

---

## 五、数据质量要求

### 5.1 质量门槛

| 质量指标 | 最低要求 | 目标值 |
|------|:---:|:---:|
| 病毒-宿主关联可溯源（有 PMID 或 DOI） | ≥90% | ≥95% |
| 病毒科（family）分类覆盖率 | ≥80% | ≥90% |
| 宿主门（phylum）覆盖率 | ≥95% | 100% |
| 重复记录率 | ≤5% | ≤2% |
| DOI / PMID 格式正确率 | ≥99% | 100% |
| GenBank accession 有效性 | ≥98% | 100% |
| 中文文献覆盖率（CNKI/万方） | ≥50% 相关中文文献 | ≥80% |

### 5.2 去重规则

以下字段组合视为**重复记录**，不得重复录入：

1. **病毒层面**: 同一 canonical_name + 同一 virus_family → 合并保留最优记录
2. **分离株层面**: 同一 accession（GenBank）→ 唯一记录
3. **文献层面**: 同一 DOI 或 PMID → 唯一记录
4. **宿主层面**: 同一 scientific_name → 唯一记录
5. **证据层面**: 同一 reference_id + virus_master_id + host_id + evidence_type + claim 哈希 → 判重

### 5.3 数据一致性要求

- 同一病毒的 family / genus / genome_type 在所有关联表中必须一致
- 同一宿主的 phylum / class / order / family 在所有关联表中必须一致
- taxonomy 字段应与 NCBI Taxonomy 或 WoRMS 交叉验证

---

## 六、交付格式与工作流

### 6.1 交付格式

**主交付物**：
- **CSV 文件**（UTF-8 编码），每个表一个 CSV，按字段定义表的结构输出
- 或者**直接写入 PostgreSQL 数据库**（我方提供 schema DDL 和连接信息）

**辅助交付物**：
- 爬取日志（每次爬取的日期、数据源、条数、成功率）
- 异常/错误记录清单（未找到、解析失败、paywall 等）
- 去重报告（发现了哪些重复、如何处理）
- 质量自检报告（按 5.1 的指标逐项报告当前达成率）
- 全文 PDF/XML 文件包（按文献 ID 命名，提供映射表）

### 6.2 建议工作流

```
                    ┌─ 检索阶段 ─┐      ┌─ 提取阶段 ─┐      ┌─ 质检阶段 ─┐
[宿主清单]      →  PubMed批检索  →  [候选文献] → DOI/篇名去重 → 全文获取
[NCBI Taxonomy]    EPMC批检索       (PMID+DOI)   标题相似度检查   数据提取
[WoRMS]            CNKI/万方检索                                    ↓
[FAO]              Google Scholar                            [CSV/DB交付]
                                                             [质检报告]
                                                             [日志]
```

### 6.3 与现有数据库的对接

- 我方提供完整的 119 表 SQLite schema DDL 供参考
- 新采集的数据需要能与现有库中的 virus_master / crustacean_hosts / ref_literatures / evidence_records **不重复、可合并**
- 若选择直接写入数据库，我方提供 API 接口；若选择 CSV，我方负责导入

---

## 七、分阶段交付计划

| 阶段 | 时间 | 交付内容 | 预计数据量 | 验收标准 |
|------|------|------|------|------|
| **Phase 0** | 签约后 2 周 | 宿主物种候选清单（所有门类） + 数据采集方案详细设计 | Excel 清单 + 方案文档 | 学名格式正确、NCBI TaxID 完整、分类层级无缺 |
| **Phase 1** | 2026 Q3（7-9月） | P0 软体动物：全部字段的病毒/宿主/文献/证据/序列/蛋白数据 | 病毒 200-400 种，宿主 80-120 种，文献 500-2,000 篇 | 数据质量门槛全部达标，与现有库无冲突合并 |
| **Phase 2** | 2026 Q4（10-12月） | P1 棘皮 + 刺胞 + 线虫：同 Phase 1 全部字段 | 病毒 200-430 种，宿主 85-140 种，文献 800-3,000 篇 | 同上 |
| **Phase 3** | 2027 Q1（1-3月） | P2 扁形 + 海绵 + 环节 + P3 其他小门类 | 病毒 600-1,700 种，宿主 50-100 种 | 同上 |
| **Phase 4** | 2027 Q1-Q2 | SRA 宏基因组数据挖掘（全门类） + 蛋白质功能注释补全 | 病毒 500-1,500 种，蛋白结构域 + GO 批量标注 | 同上 |
| **Phase 5** | 2027 Q2 | 汇总去重 + 全局质量审计 + 补漏 | 质量报告 + 补录数据 | 全库质量达标，准备 NAR 投稿 |

---

## 八、投标/报价时应回答的问题

请数据团队在报价时一并回复以下问题：

1. **团队组成**：多少人？是否有生物信息学/病毒学/分类学背景？是否有中文学术文献处理经验？
2. **技术方案**：
   - 使用什么检索策略（检索词设计方法？布尔逻辑？）
   - 数据提取是纯人工还是 NLP 辅助？（### 4.6 的 evidence_strength 和 4.7 的 host_association_method 需要理解文献内容才能判断）
   - 全文 PDF 如何解析？（pdfplumber / GROBID / 其他？）
   - 如何保证 taxonomy 一致性？
3. **质量控制**：
   - 去重算法是什么？
   - 人工审核比例？（建议至少 10% 人工抽检 + 100% 机器校验）
   - 如何处理数据冲突（如不同文献对同一病毒的 family 有不同分类）？
4. **中文覆盖能力**：能否覆盖 CNKI/万方？团队中有中文阅读能力的人吗？
5. **类似经验**：是否有过学术数据库构建或文献数据挖掘项目经验？
6. **报价方式**：按条数（每条证据/每个病毒）、按时长、还是按阶段固定报价？
7. **知识产权**：确认所有采集数据的所有权归属我方，数据不用于团队自身或其他客户。

---

## 九、我方将提供的基础设施

| 交付物 | 格式 | 说明 |
|------|------|------|
| 完整数据库 schema DDL | SQL（SQLite 方言） | 119 表完整定义 + ER 关系图 |
| 现有数据快照 | SQLite .db 文件 (~629 MB) 或 CSV | 去重和合并用 |
| 已覆盖范围清单 | Excel | 已有 1,283 种病毒 / 160 种宿主 / 7,508 篇文献 |
| 检索词参考 | Excel / TXT | 已使用的关键词组合、检索式模板 |
| NCBI Taxonomy 映射 | CSV | 已有宿主-病毒-taxonomy 映射关系 |
| API key 列表 | 文档 | PubMed/NCBI/EPMC/WoRMS 等的免费 API key（rate limit 管理） |

---

## 十、附录：关键术语解释

| 英文 | 中文 | 说明 |
|------|------|------|
| canonical_name | 标准病毒名 | ICTV 或文献中最权威的病毒名称 |
| host_association_method | 宿主关联方法 | **证据等级核心字段**——区分"确认感染"和"宏基因组共现" |
| evidence_strength | 证据强度 | 该条文献证据的可信度等级（high/medium/low） |
| discovery_context | 发现方式 | 病毒是怎么被发现的——实验室分离 or 宏基因组 or 环境样本 |
| accession | GenBank 登录号 | NCBI 序列数据库的唯一标识符 |
| Pfam / InterPro | 蛋白质结构域数据库 | 用于标注病毒蛋白功能 |
| curation | 策展 | 对数据进行审核、修正、标注的人工过程 |
| ICTV | 国际病毒分类委员会 | 病毒分类的最高权威 |
| WoRMS | 世界海洋物种名录 | 海洋生物分类的最高权威 |

---

## 联系方式

如有疑问，可通过以下方式联系项目负责人。

**项目名称:** AquaVir-KB
**目标期刊:** Nucleic Acids Research (NAR) Database Issue, January 2028
**文档版本:** v1.0 | 2026-05-26
