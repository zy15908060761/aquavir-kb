# AquaVir-KB 数据库构建技术规格书

**项目名称:** AquaVir-KB (Aquatic Invertebrate Virus Knowledge Base，水生无脊椎动物病毒知识库)
**前身:** CrustaVirus DB v1（甲壳动物病毒数据库）
**目标期刊:** Nucleic Acids Research (NAR) Database Issue 2028年1月刊
**当前阶段:** v1 数据模型已完成，准备交接技术团队进行生产化部署
**文档日期:** 2026-05-19

---

## 一、数据库构建目标与理念

### 1.1 我们要建什么

一个**全球水生无脊椎动物病毒的综合知识库**，以文献证据链和宿主-病毒关联为核心差异化优势。

### 1.2 与现有数据库的区别

| 现有资源 | 缺陷 | AquaVir-KB 的优势 |
|----------|------|-------------------|
| NCBI/GenBank | 只有序列，无宿主关联、无证据分级 | 每条病毒-宿主关联都有文献证据支撑 + 证据等级 |
| ICTV | 只有分类，无生态/地理/宿主数据 | 整合分类学 + 宿主生态 + 地理分布 + 蛋白质功能 |
| VIRIDIC/ViralZone | 通用病毒学，不专门覆盖水生无脊椎动物 | 唯一专门覆盖甲壳/软体/棘皮/刺胞/海绵病毒的知识库 |
| RVDB | 无证据溯源 | 全文文献 → 结构化证据 → 蛋白质 → 序列 完整追溯链 |

### 1.3 核心设计原则

1. **证据驱动** — 每条数据可追溯到具体文献（PubMed/DOI）+ 段落级原文
2. **证据分级** — host_association_method 区分：确认感染 / 病理观察 / 疾病暴发 / 宏基因组共现 / 环境样本
3. **策展透明** — 所有数据修改记入 curation_logs，数据来源记入 data_provenance
4. **多门兼容** — Schema 设计支持 Arthropoda → Mollusca → Echinodermata → Cnidaria → Porifera 渐进扩展
5. **生产就绪** — 支持 REST API + 公网部署 + Zenodo DOI + Docker 容器化

### 1.4 最终规模目标

| 阶段 | 时间 | 内容 | 病毒物种 |
|------|------|------|:---:|
| 现状 v1 | 2026 Q2 | 甲壳 + 部分软体动物 | 1,283 |
| Phase 1 | 2026 Q3 | 软体动物完整导入 | +200-400 |
| Phase 2 | 2026 Q4 | 棘皮 + 刺胞动物 | +150-300 |
| Phase 3 | 2027 Q1 | 剩余类群 + SRA 大规模挖掘 | +500-1,500 |
| **最终** | 2027 Q2 | 全库策展冲刺 | **2,500-4,000+** |

---

## 二、数据库整体架构（7 层 119 表）

```
┌─────────────────────────────────────────────────────┐
│  Layer 7: 策展与质量 (Curation & Quality)            │
│  curation_logs, curation_conflicts, data_provenance, │
│  release_manifest, release_gate, schema_version       │
├─────────────────────────────────────────────────────┤
│  Layer 6: 地理与生态 (Geography & Ecology)           │
│  sample_collections, geography_quality_profiles,      │
│  gbif_occurrences, obis_occurrences,                  │
│  temperature_profiles, virulence_profiles             │
├─────────────────────────────────────────────────────┤
│  Layer 5: 蛋白功能注释 (Protein Annotation)          │
│  protein_domains, interpro_go_terms,                  │
│  interpro_annotations, kegg_annotations,              │
│  uniprot_annotations, protein_structures              │
├─────────────────────────────────────────────────────┤
│  Layer 4: 文献层 (Literature)                        │
│  ref_literatures, literature_fulltext_sources,        │
│  literature_fulltext_sections,                        │
│  literature_evidence_candidates                       │
├─────────────────────────────────────────────────────┤
│  Layer 3: 关联证据层 (Evidence — 核心竞争力)          │
│  evidence_records, infection_records,                 │
│  host_range_evidence, pathogenicity_evidence,         │
│  outbreak_events, environmental_evidence,             │
│  diagnostic_methods                                   │
├─────────────────────────────────────────────────────┤
│  Layer 2: 宿主层 (Host)                              │
│  crustacean_hosts, host_taxonomy_profiles,            │
│  host_biology_profiles, host_aliases,                 │
│  host_ecological_traits                               │
├─────────────────────────────────────────────────────┤
│  Layer 1: 核心病毒层 (Core Virus)                    │
│  virus_master, viral_isolates, viral_proteins,        │
│  nucleotide_records, core_genes, nr_protein_clusters, │
│  reannotated_orfs, virus_ictv_mappings                │
└─────────────────────────────────────────────────────┘
```

### 层级关系（ER 关系核心链）

```
virus_master (1) ────< (N) viral_isolates ────< (N) viral_proteins
      │                         │
      │                         ├──< nucleotide_records
      │                         ├──< sample_collections
      │                         └──< geography_quality_profiles
      │
      ├──< infection_records >── crustacean_hosts
      ├──< evidence_records >── ref_literatures
      ├──< host_range_evidence >── crustacean_hosts
      ├──< pathogenicity_evidence
      ├──< outbreak_events
      ├──< diagnostic_methods
      └──< virus_ictv_mappings >── ictv_taxonomy

ref_literatures (1) ────< (N) literature_fulltext_sources
literature_fulltext_sources (1) ────< (N) literature_fulltext_sections
```

---

## 三、核心表详细定义 (Table Schema)

### Layer 1: 核心病毒层

#### virus_master（病毒物种主表）
| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| master_id | INTEGER | PK | 主键 |
| canonical_name | VARCHAR(200) | NOT NULL | 标准病毒名 |
| abbreviations | TEXT | | 缩写（逗号分隔） |
| chinese_name | VARCHAR(200) | | 中文名 |
| virus_family | VARCHAR(100) | | 病毒科（如 Marnaviridae） |
| virus_genus | VARCHAR(100) | | 病毒属 |
| genome_type | VARCHAR(50) | | 基因组类型（ssRNA+/dsDNA 等） |
| is_crustacean_virus | INTEGER | DEFAULT 1 | 目标范围标记（逐步替换为 host_phylum） |
| entry_type | VARCHAR(50) | DEFAULT 'complete_genome' | 数据完整度（complete_genome/partial_genome） |
| notes | TEXT | | 备注 |
| discovery_context | VARCHAR(50) | DEFAULT 'metagenomic_environmental' | 发现方式：isolated_and_cultured / metagenomic_with_host_evidence / metagenomic_environmental |
| host_phylum | VARCHAR(50) | | 关联宿主门（Arthropoda / Mollusca / Echinodermata / 等） |

#### viral_isolates（病毒分离株 / GenBank 记录）
| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| isolate_id | INTEGER | PK | 主键 |
| accession | VARCHAR(50) | NOT NULL | GenBank accession |
| virus_name | VARCHAR(200) | | 原始记录中的病毒名 |
| taxon_family | VARCHAR(100) | | NCBI 分类：科 |
| taxon_genus | VARCHAR(100) | | NCBI 分类：属 |
| taxon_species | VARCHAR(100) | | NCBI 分类：种 |
| genome_accession | VARCHAR(50) | | 基因组 accession（如有不同） |
| genome_length | INTEGER | | 基因组全长（bp） |
| gc_content | REAL | | GC 含量（%） |
| genome_type | VARCHAR(50) | | 基因组类型 |
| keywords | TEXT | | NCBI 关键词 |
| reference_id | INTEGER | | 关联文献 |
| sequence_length | INTEGER | | 序列长度 |
| molecule_type | VARCHAR(20) | | 分子类型（genomic RNA/DNA） |
| has_sequence | INTEGER | DEFAULT 0 | 是否有序列数据 |
| master_id | INTEGER | | 外键 → virus_master.master_id |
| completeness | VARCHAR(50) | | 基因组完整度 |
| raw_record_name | TEXT | | 原始记录名 |
| raw_completeness | TEXT | | 原始完整度标注 |
| sequence_scope_status | TEXT | | 序列范围状态 |
| sequence_scope_note | TEXT | | 范围备注 |

#### viral_proteins（病毒蛋白质）
| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| protein_id | INTEGER | PK | 主键 |
| isolate_id | INTEGER | NOT NULL | 外键 → viral_isolates.isolate_id |
| protein_accession | VARCHAR(50) | | NCBI 蛋白质 accession |
| protein_name | VARCHAR(500) | | 蛋白质名 |
| gene_symbol | VARCHAR(100) | | 基因符号 |
| locus_tag | VARCHAR(100) | | 位点标签 |
| aa_length | INTEGER | | 氨基酸长度 |
| genome_start | INTEGER | | 起始位点 |
| genome_end | INTEGER | | 终止位点 |
| translation | TEXT | | 氨基酸序列 |
| ec_number | VARCHAR(50) | | EC 酶编号 |
| note | TEXT | | 备注 |
| functional_category | VARCHAR(50) | DEFAULT 'unknown' | 功能类别 |
| is_rdrp | INTEGER | DEFAULT 0 | 是否为 RdRp |
| functional_annotation_status | TEXT | DEFAULT 'unannotated' | 注释状态 |
| functional_category_source | TEXT | | 功能类别来源 |

---

### Layer 2: 宿主层

#### crustacean_hosts（水生无脊椎动物宿主 — 已扩展为多门）
| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| host_id | INTEGER | PK | 主键 |
| scientific_name | VARCHAR(100) | NOT NULL | 宿主学名 |
| common_name_cn | VARCHAR(100) | | 中文俗名 |
| taxon_order | VARCHAR(100) | | 目 |
| taxon_family | VARCHAR(100) | | 科 |
| host_group | VARCHAR(50) | | 宿主类群（shrimp / crab / oyster 等） |
| habitat | VARCHAR(100) | | 栖息地（marine / freshwater / brackish） |
| aquaculture_status | VARCHAR(50) | | 养殖地位（major / minor / wild_only） |
| iucn_status | VARCHAR(50) | | IUCN 红色名录状态 |
| host_type | VARCHAR(30) | | 宿主类型 |
| iucn_assessment_year | VARCHAR(10) | | IUCN 评估年份 |
| phylum | VARCHAR(50) | | **门**（扩展字段：Arthropoda / Mollusca / Echinodermata / Cnidaria） |
| class | VARCHAR(50) | | **纲**（扩展字段：Malacostraca / Bivalvia / Gastropoda） |
| host_scope_status | VARCHAR(30) | DEFAULT 'needs_review' | 策展范围标记（target_crustacean / target_mollusk / excluded_environmental） |

#### host_taxonomy_profiles（宿主 NCBI 分类学）
| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| profile_id | INTEGER | PK | 主键 |
| host_id | INTEGER | NOT NULL | 外键 → crustacean_hosts |
| ncbi_taxid | TEXT | | NCBI Taxonomy ID |
| accepted_name | TEXT | | 接受名 |
| lineage | TEXT | | 完整 lineage 串 |
| lineage_superkingdom | TEXT | | 超界 |
| lineage_kingdom | TEXT | | 界 |
| lineage_phylum | TEXT | | 门 |
| lineage_class | TEXT | | 纲 |
| lineage_order | TEXT | | 目 |
| lineage_family | TEXT | | 科 |
| lineage_genus | TEXT | | 属 |
| is_crustacean | INTEGER | | 历史标记 |
| is_target_host | INTEGER | | 是否目标宿主 |
| match_status | TEXT | DEFAULT 'from_cache' | 匹配状态 |
| confidence | TEXT | DEFAULT 'medium' | 置信度 |

#### host_biology_profiles（宿主生物学特征）
| 字段 | 类型 | 说明 |
|------|------|------|
| profile_id | INTEGER PK | 主键 |
| host_id | INTEGER | 外键 → crustacean_hosts |
| scientific_name | TEXT | 学名 |
| habitat_type | TEXT | 栖息地类型 |
| depth_range_min / max | REAL | 深度范围（米） |
| temperature_tolerance_min / max | REAL | 温度耐受（°C） |
| salinity_tolerance | TEXT | 盐度耐受 |
| max_body_length_cm | REAL | 最大体长 |
| trophic_level | REAL | 营养级 |
| feeding_type | TEXT | 摄食方式（filter_feeder / predator / scavenger） |
| generation_time_days | INTEGER | 世代时间（天） |
| longevity_days | INTEGER | 寿命（天） |
| fecundity_min / max | INTEGER | 繁殖力范围 |
| aquaculture_production_tonnes | REAL | 养殖产量（吨） |
| commercial_importance | TEXT | 商业重要性 |

---

### Layer 3: 证据层（核心竞争力）

#### evidence_records（结构化文献证据 — 核心表）
| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| evidence_id | INTEGER | PK | 主键 |
| evidence_type | TEXT | NOT NULL | 证据类型（host_association / genome / transmission / mortality / prevalence / temperature / diagnostic） |
| virus_master_id | INTEGER | | 外键 → virus_master |
| host_id | INTEGER | | 外键 → crustacean_hosts |
| isolate_id | INTEGER | | 外键 → viral_isolates |
| reference_id | INTEGER | | 外键 → ref_literatures |
| source_id | INTEGER | | 外键 → external_sources |
| claim | TEXT | NOT NULL | 核心声明（如"LSNV detected in P. monodon by RT-PCR"） |
| value_text | TEXT | | 文本型值 |
| value_numeric_min | REAL | | 数值型下界 |
| value_numeric_max | REAL | | 数值型上界 |
| unit | TEXT | | 单位 |
| context | TEXT | | 上下文 |
| observation_type | TEXT | | 观察类型 |
| evidence_strength | TEXT | DEFAULT 'medium' | 证据强度（high / medium / low） |
| source_pmid | TEXT | | PubMed ID |
| source_doi | TEXT | | DOI |
| extraction_method | TEXT | DEFAULT 'manual_or_seeded' | 提取方式 |
| curation_status | TEXT | DEFAULT 'needs_review' | 策展状态 |

#### infection_records（病毒感染记录 — 含证据等级核心字段）
| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| record_id | INTEGER | PK | 主键 |
| isolate_id | INTEGER | NOT NULL | 外键 → viral_isolates |
| host_id | INTEGER | | 外键 → crustacean_hosts |
| collection_id | INTEGER | | 外键 → sample_collections |
| detection_method | VARCHAR(100) | | 检测方法（RT-PCR / metagenomics / histopathology / TEM） |
| disease_symptom | TEXT | | 疾病症状 |
| mortality_rate | VARCHAR(50) | | 死亡率描述 |
| isolation_source | VARCHAR(100) | | 分离来源组织 |
| reference_id | INTEGER | | 文献 |
| time_consistency_flag | TEXT | | 时间一致性标记 |
| orphan_flag | TEXT | | 孤儿标记（无宿主匹配） |
| **host_association_method** | VARCHAR(50) | DEFAULT 'co_occurrence_metagenomic' | **证据等级核心字段** |

**host_association_method 枚举值（证据等级从高到低）：**
- `confirmed_infection` — 实验确认感染（Koch's postulates）
- `pathology_observation` — 病理组织学观察
- `disease_outbreak` — 疾病暴发关联
- `co_occurrence_metagenomic` — 宏基因组共现
- `environmental_sample` — 环境样本检出

#### host_range_evidence（宿主范围证据）
| 字段 | 类型 | 说明 |
|------|------|------|
| host_range_id | INTEGER PK | 主键 |
| virus_master_id | INTEGER | 病毒 |
| host_id | INTEGER | 宿主 |
| evidence_category | TEXT | 证据类别 |
| isolate_count | INTEGER | 分离株数量 |
| representative_isolate_id | INTEGER | 代表性分离株 |
| reference_id | INTEGER | 文献 |
| host_life_stage | TEXT | 宿主生活阶段 |
| tissue_or_sample | TEXT | 组织/样本类型 |
| geography_summary | TEXT | 地理分布总结 |
| first_observed_year | TEXT | 首次观察年份 |
| last_observed_year | TEXT | 最后观察年份 |
| evidence_strength | TEXT | 证据强度 |

#### pathogenicity_evidence（致病性证据）
| 字段 | 类型 | 说明 |
|------|------|------|
| pathogenicity_id | INTEGER PK | 主键 |
| virus_master_id | INTEGER | 病毒 |
| host_id | INTEGER | 宿主 |
| isolate_id | INTEGER | 分离株 |
| reference_id | INTEGER | 文献 |
| virulence_level | TEXT | 毒力等级 |
| virulence_label | INTEGER | 毒力标签（1-5 级） |
| mortality_rate_min / max | REAL | 死亡率范围 |
| ld50_value | TEXT | LD50 |
| disease_symptoms | TEXT | 临床症状 |
| tissue_tropism | TEXT | 组织嗜性 |
| pathogenic_mechanism | TEXT | 致病机制 |
| host_age_susceptibility | TEXT | 年龄易感性 |

#### outbreak_events（疾病暴发事件）
| 字段 | 类型 | 说明 |
|------|------|------|
| outbreak_id | INTEGER PK | 主键 |
| virus_master_id | INTEGER | 病毒 |
| host_id | INTEGER | 宿主 |
| country | TEXT | 国家 |
| province_state | TEXT | 省份/州 |
| start_year / end_year | TEXT | 暴发起止年份 |
| event_summary | TEXT | 事件描述 |
| economic_impact | TEXT | 经济损失 |
| mortality_rate_min / max | REAL | 死亡率范围 |

#### diagnostic_methods（诊断方法）
| 字段 | 类型 | 说明 |
|------|------|------|
| method_id | INTEGER PK | 主键 |
| virus_master_id | INTEGER | 病毒 |
| method_category | TEXT | 方法类别（PCR / LAMP / RPA / histopathology / in_situ_hybridization） |
| method_name | TEXT | 方法名称 |
| target_gene_or_region | TEXT | 靶基因 |
| sample_type | TEXT | 样本类型 |
| field_deployable | INTEGER | 是否现场可用 |
| detection_limit | TEXT | 检测限 |
| reference_id | INTEGER | 文献 |

#### environmental_evidence（环境证据）
| 字段 | 类型 | 说明 |
|------|------|------|
| environmental_id | INTEGER PK | 主键 |
| virus_master_id | INTEGER | 病毒 |
| evidence_type | TEXT | 类型（prevalence / temperature_tolerance / salinity / pH / UV） |
| value_min / max | REAL | 数值范围 |
| unit | TEXT | 单位 |
| context | TEXT | 上下文 |
| reference_id | INTEGER | 文献 |

---

### Layer 4: 文献层

#### ref_literatures（参考文献）
| 字段 | 类型 | 说明 |
|------|------|------|
| reference_id | INTEGER PK | 主键 |
| pmid | VARCHAR(20) | PubMed ID |
| title | TEXT | 标题 |
| authors | TEXT | 作者 |
| journal | TEXT | 期刊 |
| year | VARCHAR(10) | 出版年 |
| doi | VARCHAR(100) | DOI |
| abstract | TEXT | 摘要 |
| keywords | TEXT | 关键词 |

#### literature_fulltext_sources（全文来源与下载状态）
| 字段 | 类型 | 说明 |
|------|------|------|
| fulltext_id | INTEGER PK | 主键 |
| reference_id | INTEGER | 外键 → ref_literatures |
| pmid / doi / pmcid | TEXT | 标识符 |
| source | TEXT | 来源（europe_pmc / semantic_scholar / unpaywall / pubmed_central） |
| status | TEXT | 状态（downloaded / not_found / paywalled） |
| oa_status | TEXT | OA 状态 |
| fulltext_url / pdf_url / xml_url | TEXT | 全文 URLs |
| local_path | TEXT | 本地文件路径 |
| content_type | TEXT | 内容类型（xml / pdf） |
| license | TEXT | 版权许可 |

#### literature_fulltext_sections（全文段落提取）
| 字段 | 类型 | 说明 |
|------|------|------|
| section_id | INTEGER PK | 主键 |
| fulltext_id | INTEGER | 外键 → literature_fulltext_sources |
| reference_id | INTEGER | 外键 → ref_literatures |
| section_title | TEXT | 段落标题 |
| section_type | TEXT | 段落类型（abstract / methods / results / discussion） |
| text | TEXT | 段落原文 |
| char_count | INTEGER | 字符数 |

---

### Layer 5: 蛋白质功能注释层

#### protein_domains（蛋白结构域）
| 字段 | 类型 | 说明 |
|------|------|------|
| domain_id | INTEGER PK | 主键 |
| protein_id | INTEGER | 外键 → viral_proteins |
| domain_source | TEXT | 来源（uniprot_keyword / protein_name_inference / rule_based） |
| domain_name | TEXT | 结构域名 |
| domain_description | TEXT | 描述 |
| start_pos / end_pos | INTEGER | 位置 |
| confidence_score | REAL | 置信度 |
| interpro_id / pfam_id / cdd_id | TEXT | 跨库 ID |

#### interpro_go_terms（GO 术语）
| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 主键 |
| protein_id | INTEGER | 蛋白质 |
| interpro_id | TEXT | InterPro ID |
| go_id | TEXT | GO ID（如 GO:0003968） |
| go_name | TEXT | GO 术语名 |
| go_namespace | TEXT | GO namespace（molecular_function / biological_process / cellular_component） |
| evidence_source | TEXT | 证据来源 |

#### uniprot_annotations（UniProt 注释）
| 字段 | 类型 | 说明 |
|------|------|------|
| annotation_id | INTEGER PK | 主键 |
| ncbi_protein_acc | TEXT | NCBI 蛋白质 accession |
| uniprot_id | TEXT | UniProt ID |
| protein_name | TEXT | 蛋白质名 |
| gene_name | TEXT | 基因名 |
| ec_numbers | TEXT | EC 编号 |
| go_terms | TEXT | GO 术语（JSON） |
| keywords | TEXT | 关键词 |
| functional_category | TEXT | 功能类别 |

#### protein_structures（蛋白质3D结构）
| 字段 | 类型 | 说明 |
|------|------|------|
| structure_id | INTEGER PK | 主键 |
| protein_id | INTEGER | 蛋白质 |
| prediction_method | TEXT | 预测方法（esmfold） |
| pdb_file_path | TEXT | PDB 文件路径 |
| plddt_score | REAL | pLDDT 置信度 |
| sequence_length | INTEGER | 序列长度 |
| api_source | TEXT | API 来源 |

---

### Layer 6: 地理与生态层

#### sample_collections（样本采集信息）
| 字段 | 类型 | 说明 |
|------|------|------|
| collection_id | INTEGER PK | 主键 |
| country | VARCHAR(100) | 国家 |
| province | VARCHAR(100) | 省份 |
| city | VARCHAR(100) | 城市 |
| site_name | VARCHAR(200) | 具体采集点 |
| latitude / longitude | REAL | 经纬度 |
| collection_year | VARCHAR(10) | 采集年份 |
| collection_date | VARCHAR(20) | 采集日期 |
| source_type | VARCHAR(50) | 样本类型（tissue / water / sediment） |
| continent | VARCHAR(50) | 大洲 |
| coordinate_precision | TEXT | 坐标精度（country / province / exact） |
| coordinate_quality | TEXT | 坐标质量标记 |

#### geography_quality_profiles（地理信息质量评估）
| 字段 | 类型 | 说明 |
|------|------|------|
| geo_profile_id | INTEGER PK | 主键 |
| isolate_id | INTEGER | 分离株 |
| raw_country | TEXT | 原始国家记录 |
| standardized_country | TEXT | 标准化后的国家 |
| continent / province_state / city | TEXT | 地理位置 |
| latitude / longitude | REAL | 坐标 |
| location_precision | TEXT | 精度级别 |
| coordinate_quality | TEXT | 质量标记 |
| location_completeness_score | INTEGER | 完整度评分 |
| missing_components | TEXT | 缺失成分 |
| needs_geocoding | INTEGER | 是否需要地理编码 |

#### temperature_profiles / virulence_profiles
温度耐受性和毒力档案，各含约 19-21 个字段，包含 virus_name、各类阈值数值、data_source、confidence、curation_date 等。

---

### Layer 7: 策展与质量层

#### curation_logs（策展日志 — 全库审计追踪）
| 字段 | 类型 | 说明 |
|------|------|------|
| log_id | INTEGER PK | 主键 |
| entity_type | TEXT | 实体类型（virus / isolate / protein / host / evidence） |
| entity_id | INTEGER | 实体 ID |
| action | TEXT | 操作类型（update / insert / delete / promote） |
| source_id | INTEGER | 数据来源 |
| old_value / new_value | TEXT | 变更前后值 |
| confidence | TEXT | 置信度 |
| curator | TEXT | 策展人（script 或 curator 名） |
| created_at | TEXT | 时间戳 |

#### data_provenance（数据来源追踪）
| 字段 | 类型 | 说明 |
|------|------|------|
| provenance_id | INTEGER PK | 主键 |
| table_name | TEXT | 表名 |
| record_id | INTEGER | 记录 ID |
| virus_master_id | INTEGER | 病毒 ID |
| virus_name | TEXT | 病毒名 |
| data_source | TEXT | 数据来源（NCBI / UniProt / EPMC / manual / SRA） |
| confidence_level | TEXT | 置信度 |
| verification_method | TEXT | 验证方法 |
| curator_notes | TEXT | 备注 |

#### curation_conflicts（数据冲突记录）
| 字段 | 类型 | 说明 |
|------|------|------|
| conflict_id | INTEGER PK | 主键 |
| entity_type / entity_id | TEXT/INT | 冲突实体 |
| field_name | TEXT | 冲突字段 |
| value_a / source_a | TEXT | 来源A 的值和出处 |
| value_b / source_b | TEXT | 来源B 的值和出处 |
| conflict_type | TEXT | 冲突类型 |
| severity | TEXT | 严重度（high / medium / low） |
| status | TEXT | 状态（open / resolved） |

---

## 四、当前数据规模快照

| 指标 | 数值 |
|------|------|
| **表总数** | 119 |
| **病毒物种** | 1,283（目标水生无脊椎: 902, 70.3%） |
| **分离株** | 11,353 |
| **蛋白质** | 26,894（30.9% 有功能注释） |
| **蛋白质结构域** | 13,432 |
| **GO 术语** | 3,452 条 |
| **宿主物种** | 160（66 目标甲壳 + 4 目标软体） |
| **感染记录** | 9,541 |
| **文献证据** | 341,394 条 |
| **参考文献** | 7,508 篇（7,215 有 DOI） |
| **全文下载** | 1,882 篇 |
| **全文段落** | 12,862 段 |
| **证据覆盖率** | 91.8%（1,178/1,283） |
| **Family 分类率** | 79.7% |
| **数据来源记录** | 100,559 条 |
| **当前数据库大小** | ~629 MB（SQLite） |

---

## 五、关键技术栈与未来迁移路径

### 当前状态
- **数据库**: SQLite 3（单文件，~629 MB）
- **后端 API**: Python FastAPI (`backend.py`)
- **数据导入**: ~60 个 Python 脚本（NCBI / UniProt / InterPro / KEGG / EPMC / SRA pipeline）
- **前端**: 待开发

### 生产化迁移目标（2027 Q2 前）
1. **SQLite → PostgreSQL**（支持并发访问、全文检索、GIS 扩展）
2. **REST API 部署**（FastAPI + Gunicorn + Nginx + HTTPS）
3. **Docker Compose** 容器化部署
4. **Zenodo DOI** 注册（代码 + 数据版本化）
5. **全文搜索**（PostgreSQL `tsvector` 或 Elasticsearch）
6. **公网域名 + HTTPS**

### 开发团队需要做的事（建议）

| 优先级 | 任务 | 说明 |
|:---:|------|------|
| P0 | 数据模型审查 | 确认 119 表 schema 是否符合生产需求 |
| P0 | PostgreSQL 建表脚本 | 把 SQLite schema 转为 PostgreSQL DDL |
| P0 | 数据迁移 ETL | 从 SQLite 导出 → PostgreSQL 导入 |
| P1 | REST API 开发 | 基于现有 FastAPI 代码重写/完善 |
| P1 | 前端界面 | Web 搜索 + 浏览 + 可视化 |
| P2 | 全文检索 | 文献、病毒、宿主全文搜索 |
| P2 | 管理后台 | 策展工作台（人工审核队列） |
| P3 | CI/CD Pipeline | 自动化测试 + 部署 |
| P3 | 监控与备份 | 数据库备份策略 + 运行监控 |

---

## 六、需要特别注意的设计要点

1. **host_association_method 字段是核心** — 前端展示、统计图表、NAR 论文中的"确认病原 vs 宏基因组关联"分类，全部依赖这个字段的 5 级枚举值。

2. **discovery_context 字段影响论文叙述** — 论文中需要分类统计：多少病毒是传统分离培养的，多少是宏基因组发现的，多少是环境样本。

3. **evidence_records 是最大的表（341K 行）** — 每条 evidence 的 `evidence_strength`（high/medium/low）和 `curation_status` 直接影响数据质量的对外宣称。

4. **crustacean_hosts 虽然名字还带 crustacean**，但已扩展 phylum/class 字段支持多门类。如果觉得表名别扭，可以重命名为 `aquatic_invertebrate_hosts`，但需要同步更新所有 Python 脚本中的引用。

5. **119 张表不是全部都需要对外暴露** — 面向用户的 API/前端主要用到约 20 张核心表，其余是内部策展和 pipeline 用的。

6. **文献全文 PDF 本地存储** — ~1,882 篇全文 PDF 存储在本地文件系统，需要考虑如何与数据库记录关联、以及版权合规问题。
