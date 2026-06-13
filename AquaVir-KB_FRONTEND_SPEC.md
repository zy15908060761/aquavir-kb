# AquaVir-KB 前端开发需求文档
## 查询方式 + 真实样本数据 + 参考网站

**日期:** 2026-05-19

---

## 一、真实样本数据（每条都是数据库中的真实行）

### 1.1 virus_master（病毒物种）

| master_id | canonical_name | virus_family | virus_genus | genome_type | discovery_context | host_phylum |
|:---:|------|------|------|------|------|------|
| 1 | White spot syndrome virus | Nimaviridae | Whispovirus | dsDNA | isolated_and_cultured | Arthropoda |
| 2 | Yellow head virus | Roniviridae | Okavirus | +ssRNA | isolated_and_cultured | Arthropoda |
| 5 | Infectious myonecrosis virus | Totiviridae | — | dsRNA | disease_outbreak | Arthropoda |
| 68 | Ostreid herpesvirus 1 | Malacoherpesviridae | Ostreavirus | dsDNA | experimental_infection | Mollusca |
| 69 | Haliotid herpesvirus 1 | Malacoherpesviridae | Aurivirus | dsDNA | disease_outbreak | Mollusca |
| 200+ | Coral holobiont-associated alphaflexivirus 1 | Alphaflexiviridae | — | ssRNA(+) | metagenomic_survey | Cnidaria |
| 400+ | Caledonia starfish parvo-like virus 1 | Parvoviridae | — | dsDNA | metagenomic_survey | Echinodermata |

### 1.2 crustacean_hosts（水生无脊椎动物宿主）

| host_id | scientific_name | common_name_cn | host_group | phylum | class | host_scope_status |
|:---:|------|------|------|------|------|------|
| 1 | Litopenaeus vannamei | 凡纳滨对虾/南美白对虾 | penaeid shrimp | Arthropoda | Malacostraca | target_crustacean |
| 3 | Penaeus monodon | 斑节对虾/草虾/黑虎虾 | penaeid shrimp | Arthropoda | Malacostraca | target_crustacean |
| 7 | Macrobrachium rosenbergii | 罗氏沼虾 | palaemonid shrimp | Arthropoda | Malacostraca | target_crustacean |
| 55 | Crassostrea gigas | 太平洋牡蛎(长牡蛎) | bivalve | Mollusca | Bivalvia | target_mollusk |
| 56 | Ruditapes philippinarum | 菲律宾蛤仔 | bivalve | Mollusca | Bivalvia | target_mollusk |
| 50 | Haliotis discus hannai | 皱纹盘鲍 | gastropod | Mollusca | Gastropoda | target_mollusk |

### 1.3 infection_records（病毒感染记录）

| record_id | canonical_name (via isolate) | host_name | detection_method | disease_symptom | host_association_method |
|:---:|------|------|------|------|------|
| 1 | White spot syndrome virus | Litopenaeus vannamei | — | Global pandemic, massive losses in farms | **disease_outbreak** |
| 15 | Yellow head virus | Penaeus monodon | RT-PCR | 100% mortality in affected ponds | **disease_outbreak** |
| 200 | Ostreid herpesvirus 1 | Crassostrea gigas | qPCR + histopathology | Mass mortality in oyster spat | **disease_outbreak** |
| 350 | Taura syndrome virus | Litopenaeus vannamei | RT-PCR | Acute hepatopancreatic necrosis | **confirmed_infection** |

### 1.4 evidence_records（结构化文献证据）

| evidence_id | evidence_type | claim（摘要） | evidence_strength | curation_status |
|:---:|------|------|------|------|
| — | host_range | "WSSV detected in P. monodon from Thailand" | high | approved |
| — | pathogenicity | "WSSV: 90-100% mortality in penaeid shrimp" | high | approved |
| — | mortality | "YHV caused 100% mortality within 3-5 days" | high | approved |
| — | temperature | "WSSV replication inhibited above 32°C" | medium | needs_review |
| — | transmission | "Vertical transmission of WSSV confirmed" | high | approved |
| — | diagnosis | "LAMP assay for WSSV detection, LOD 10 copies" | medium | approved |

**evidence_type 分布（实际数据）：**
- host_range: 143,046（42%）
- diagnosis: 100,742（30%）
- pathogenicity: 60,278（18%）
- temperature: 24,773（7%）
- natural_infection: 8,780

### 1.5 ref_literatures（参考文献）

| reference_id | pmid | doi | title | journal | year |
|:---:|------|------|------|------|:---:|
| 1 | 10228874 | 10.3354/dao035165 | A yellow head virus gene probe... | Diseases of Aquatic Organisms | 1999 |
| 2 | 10399042 | 10.3354/dao036153 | Yellow head virus from Thailand... | Diseases of Aquatic Organisms | 1999 |
| 3 | 10639309 | 10.1006/viro.1999.0088 | Identification of two major virion... | Virology | 2000 |

### 1.6 outbreak_events（疫情爆发）

| outbreak_id | virus (via master) | country | start_year | event_summary |
|:---:|------|------|:---:|------|
| 1 | White spot syndrome virus | China | 1992 | Global pandemic; annual losses >$1B |
| 2 | Yellow head virus | China | 1990 | Major outbreaks Thailand/China/Vietnam |

### 1.7 pathogenicity_evidence（致病性参数）

| virus | virulence_level | mortality_rate_min | mortality_rate_max | disease_symptoms |
|------|:---:|:---:|:---:|------|
| White spot syndrome virus | High | 90% | 100% | Systemic tissue necrosis; latency at low temps |
| Yellow head virus | High | 80% | 100% | Acute hepatopancreatic necrosis; death in 3-5 days |

---

## 二、数据分布（Facet 可用选项）

### 宿主门分布（virus_master）
| host_phylum | 病毒数 |
|------|:---:|
| Arthropoda（节肢动物） | 622 |
| Mollusca（软体动物） | 202 |
| Cnidaria（刺胞动物） | 18 |
| Echinodermata（棘皮动物） | 16 |
| Porifera（海绵） | 13 |
| Annelida（环节动物） | 3 |

### 基因组类型分布
| genome_type | 病毒数 |
|------|:---:|
| ssRNA(+)（单链正义RNA） | ~890 |
| dsDNA（双链DNA） | ~182 |
| dsRNA（双链RNA） | ~56 |
| ssDNA（单链DNA） | ~46 |

### 证据等级分布（infection_records）
| host_association_method | 记录数 | 含义 |
|------|:---:|------|
| metagenomic | 4,093 | 宏基因组检测 |
| disease_outbreak | 2,271 | 疾病暴发关联 |
| confirmed_infection | 839 | 实验确认感染 |
| co_occurrence_metagenomic | 835 | 宏基因组共现 |
| environmental_sample | 1 | 环境样本 |

### 宿主组分布（目标范围内）
penaeid shrimp（26）> crab（11）> palaemonid shrimp（8）> gastropod（3）= bivalve（3）> ...

### 国家分布（Top 5 采样地）
Canada（216）> China（202）> Mexico（147）> Thailand（89）> India / Philippines（77）

---

## 三、前端查询方式清单

### 3.1 全局全文搜索（导航栏搜索框）

**输入:** 任意文本
**搜索范围:**
- 病毒名（canonical_name + abbreviations + chinese_name + aliases）
- 宿主名（scientific_name + common_name_cn + aliases）
- 文献标题/作者/摘要
- GenBank accession
- 病毒科/属名

**已有基础设施:** `virus_search_fts` 全文索引表（9,090 条已索引）

**输出:**
```
搜索 "WSSV" →
  [Virus] White spot syndrome virus (Nimaviridae, dsDNA)
  [Virus] Shrimp white spot syndrome virus (Nucleocytoviricota)
  [Host] Litopenaeus vannamei — 凡纳滨对虾 (host of WSSV)
  [Literature] Activation of Host... (PMID 42055174, 2026)
```

### 3.2 分面浏览 / 筛选（Browse 页面）

**左侧 Facet 面板:**
```
┌─ Filter ─────────────────┐
│ Host Phylum              │
│ ☑ Arthropoda (622)       │
│ ☑ Mollusca (202)         │
│ ☐ Cnidaria (18)          │
│ ☐ Echinodermata (16)     │
│                          │
│ Virus Family             │
│ ☑ Picornavirales (189)   │
│ ☐ Marnaviridae (153)     │
│ ☐ Picornaviridae (150)   │
│ ...                      │
│                          │
│ Genome Type              │
│ ☐ ssRNA(+)               │
│ ☐ dsDNA                  │
│ ☐ dsRNA                  │
│                          │
│ Discovery Context        │
│ ☐ isolated_and_cultured  │
│ ☐ metagenomic_with_host  │
│ ☐ metagenomic_environmental│
│                          │
│ Evidence Strength        │
│ ☐ high                   │
│ ☐ medium                 │
│ ☐ low                    │
│                          │
│ Host Group               │
│ ☐ penaeid shrimp         │
│ ☐ crab                   │
│ ☐ bivalve                │
│ ☐ gastropod              │
└──────────────────────────┘
```

**中央结果表格:**
| Virus Name | Family | Genome | Host Phylum | Key Hosts | Evidence | Pathogenicity |
|------|------|------|------|------|:---:|------|
| White spot syndrome virus | Nimaviridae | dsDNA | Arthropoda | L. vannamei, P. monodon | 5,570 | High 90-100% |
| Ostreid herpesvirus 1 | Malacoherpesviridae | dsDNA | Mollusca | C. gigas | ... | High |
| ...

每列可排序，每行可点击进入详情页。

### 3.3 病毒详情页（核心页面）

```
┌─ White spot syndrome virus (WSSV) ──────────────────────┐
│                                                         │
│ [Overview] [Isolates] [Hosts] [Proteins] [Evidence]     │
│ [Literature] [Geography] [Taxonomy]                      │
│                                                         │
│ ── Overview ──────────────────────────────────────       │
│ Classification: Nimaviridae > Whispovirus                │
│ Genome: dsDNA, ~300 kb                                  │
│ Discovery: isolated_and_cultured (1992, Ecuador)         │
│ Host Phylum: Arthropoda                                  │
│ Chinese Name: 白斑综合征病毒                              │
│                                                         │
│ ── Pathogenicity ──────────────────────────────────      │
│ Virulence: High                                         │
│ Mortality: 90-100% in penaeid shrimp                    │
│ Disease: Systemic tissue necrosis; latency at low temp  │
│                                                         │
│ ── Key Hosts ──────────────────────────────────────      │
│ • Litopenaeus vannamei (凡纳滨对虾) — disease_outbreak   │
│ • Penaeus monodon (斑节对虾) — disease_outbreak           │
│ • Penaeus chinensis (中国对虾) — confirmed_infection      │
│ [View all 15 hosts →]                                   │
│                                                         │
│ ── Outbreaks ──────────────────────────────────────      │
│ 1992-present: Global pandemic, annual losses >$1B       │
│ Major: China, Thailand, India, Ecuador, Mexico          │
│                                                         │
│ ── Recent Literature ──────────────────────────────      │
│ • Activation of Host Endogenous Reverse Transcriptase... │
│   (2026, PMID 42055174)                                  │
│ • WSSV VP28 protein structure... (2025, PMID xxxxx)      │
│ [View all 120+ references →]                            │
└─────────────────────────────────────────────────────────┘
```

### 3.4 宿主详情页

```
┌─ Litopenaeus vannamei (凡纳滨对虾) ─────────────────────┐
│                                                        │
│ [Overview] [Viruses] [Biology] [Distribution]           │
│                                                        │
│ Taxonomy: Arthropoda > Malacostraca > Decapoda         │
│ Common Names: Pacific white shrimp, 南美白对虾           │
│ Habitat: marine/brackish, major aquaculture species     │
│                                                        │
│ ── Associated Viruses (9) ────────────────────────      │
│ ☠ White spot syndrome virus — High virulence, 90-100%   │
│ ⚠ Taura syndrome virus — High virulence                 │
│ ⚠ Infectious myonecrosis virus — Medium virulence       │
│ ⚠ Yellow head virus — High virulence                    │
│ ...                                                    │
└────────────────────────────────────────────────────────┘
```

### 3.5 地理分布（地图视图）

**交互:**
- 世界地图上的点标记（每个点 = 一个 sample_collection 记录）
- 颜色按 host_phylum 区分
- 点击标记显示：病毒名、宿主名、国家、年份、检测方法
- 可按病毒/宿主/国家筛选
- 热力图模式（按病毒种类密度）

**数据源:** `sample_collections` + `geography_quality_profiles` + `gbif_occurrences`

### 3.6 分类树浏览

```
☰ Taxonomy Browser
├─ Arthropoda (622 viruses)
│  ├─ Nimaviridae (3)
│  │  └─ Whispovirus
│  │     ├─ White spot syndrome virus
│  │     └─ ...
│  ├─ Roniviridae (2)
│  ├─ Totiviridae (45)
│  └─ ...
├─ Mollusca (202 viruses)
│  ├─ Malacoherpesviridae (18)
│  └─ ...
├─ Cnidaria (18 viruses)
└─ Echinodermata (16 viruses)
```

### 3.7 统计仪表盘（首页或 Dashboard）

**核心指标卡片:**
- 1,283 病毒物种 | 11,353 分离株 | 26,894 蛋白质 | 160 宿主物种
- 341,394 条证据 | 7,508 篇文献 | 5 个宿主门

**图表:**
- 按 host_phylum 的病毒分布（柱状图）
- 按 genome_type 的分布（饼图）
- 按 evidence_type 的分布（柱状图）
- 按发现方式的分布（discovery_context）
- Top 10 病毒家族（横向柱状图）
- 证据覆盖度趋势（如有历史快照）

### 3.8 文献检索

**搜索:** 按 PMID / DOI / 标题关键词 / 作者 / 期刊 / 年份

**结果列表:** 标题、作者、期刊、年份、引用该文献的病毒列表

**文献详情:** 摘要、全文下载状态、从该文献提取的所有 evidence_records

### 3.9 对比功能

选择 2-4 个病毒，并排对比：
- 分类信息、基因组特征
- 宿主范围
- 致病性参数（死亡率、毒力等级）
- 地理分布重叠
- 共有/特有宿主

### 3.10 数据下载

- **筛选结果导出:** TSV / CSV / JSON（当前筛选条件下的结果）
- **全库下载:** FASTA（核苷酸/蛋白质）+ XLSX（元数据）+ 系统发育树
- **API 访问:** RESTful JSON API（已有 FastAPI 基础）

---

## 四、参考网站

### 4.1 最直接参考 — 同类病毒学数据库

| 网站 | URL | 值得借鉴的点 |
|------|------|------|
| **NCBI Virus** | https://www.ncbi.nlm.nih.gov/labs/virus/vssi/ | 分面浏览 + 表格 + 地图 + 序列下载，是 AquaVir-KB 最直接的参考 |
| **BV-BRC (原 VIPR)** | https://www.bv-brc.org/ | 病毒详情页布局、多 Tab 设计、全局搜索 |
| **ICTV Taxonomy** | https://ictv.global/taxonomy | 分类树浏览交互 |
| **ViralZone** | https://viralzone.expasy.org/ | 病毒家族信息卡片、图文混排 |

### 4.2 宿主信息参考

| 网站 | URL | 值得借鉴的点 |
|------|------|------|
| **WoRMS** | https://www.marinespecies.org/ | 海洋物种分类浏览、宿主详情页结构 |
| **SeaLifeBase** | https://www.sealifebase.ca/ | 水生生物生态数据、分布地图 |
| **FishBase** | https://www.fishbase.se/ | 物种详情页（生物学特征 + 分布 + 经济重要性）的布局 |

### 4.3 通用参考

| 网站 | URL | 值得借鉴的点 |
|------|------|------|
| **Ensembl** | https://www.ensembl.org/ | 基因组浏览器、多物种数据整合 |
| **UniProt** | https://www.uniprot.org/ | 蛋白质详情页、功能注释展示 |

---

## 五、API 端点设计建议

### 5.1 搜索与列表
```
GET /api/v1/search?q={keyword}&page=1&size=20
  → 全局搜索，返回 viruses + hosts + literature

GET /api/v1/viruses?phylum=Arthropoda&family=Nimaviridae&genome_type=dsDNA&page=1&size=20
  → 分面筛选病毒列表

GET /api/v1/hosts?phylum=Mollusca&host_group=bivalve&page=1&size=20
  → 分面筛选宿主列表
```

### 5.2 详情
```
GET /api/v1/virus/{id}
  → 病毒完整信息 (含 hosts, isolates, proteins, evidence, literature)

GET /api/v1/host/{id}
  → 宿主完整信息 (含 viruses, biology, distribution)

GET /api/v1/literature/{id}
  → 文献详情 (含 evidence extracted from this paper)
```

### 5.3 统计
```
GET /api/v1/stats/summary
  → 总览统计数字

GET /api/v1/stats/by_phylum
GET /api/v1/stats/by_genome_type
GET /api/v1/stats/by_family
  → 各维度分布数据

GET /api/v1/stats/evidence_coverage
  → 证据覆盖率统计
```

### 5.4 地理
```
GET /api/v1/geography?virus_id={id}&country={country}
  → 地图标记点数据 (GeoJSON)
```

### 5.5 下载
```
GET /api/v1/export/viruses?{filters}&format=csv|tsv|json
GET /api/v1/export/sequences?type=nucleotide|protein&{filters}&format=fasta
```

---

## 六、前端路由结构建议

```
/                          — 首页（搜索框 + 统计仪表盘）
/search?q=WSSV             — 搜索结果页
/browse/viruses            — 病毒分面浏览
/browse/hosts              — 宿主分面浏览
/browse/taxonomy           — 分类树浏览
/virus/1                   — 病毒详情页 (Tab: Overview / Isolates / Hosts / Proteins / Evidence / Literature / Geography)
/host/1                    — 宿主详情页 (Tab: Overview / Viruses / Biology / Distribution)
/literature/1              — 文献详情页
/map                       — 地理分布地图
/compare?v=1,2,3           — 多病毒对比
/download                  — 数据下载页
/docs                      — API 文档
/about                     — 关于 (Citation / Data Availability / License)
```

---

## 七、第一条数据的完整 JSON 示例

以下是前端调用 `/api/v1/virus/1` 应该返回的数据形态：

```json
{
  "virus": {
    "master_id": 1,
    "canonical_name": "White spot syndrome virus",
    "abbreviations": "WSSV",
    "chinese_name": "白斑综合征病毒",
    "virus_family": "Nimaviridae",
    "virus_genus": "Whispovirus",
    "genome_type": "dsDNA",
    "discovery_context": "isolated_and_cultured",
    "host_phylum": "Arthropoda"
  },
  "isolates": [
    {"accession": "NC_003225", "genome_length": 292967, "gc_content": 42.6, "completeness": "complete"},
    {"accession": "AF369029", "genome_length": 305107, "gc_content": 42.7, "completeness": "complete"}
  ],
  "hosts": [
    {"scientific_name": "Litopenaeus vannamei", "common_name_cn": "凡纳滨对虾", "association_method": "disease_outbreak", "evidence_count": 892},
    {"scientific_name": "Penaeus monodon", "common_name_cn": "斑节对虾", "association_method": "confirmed_infection", "evidence_count": 456}
  ],
  "pathogenicity": {
    "virulence_level": "High",
    "mortality_rate_min": 90.0,
    "mortality_rate_max": 100.0,
    "disease_symptoms": "Systemic infection causing rapid tissue necrosis..."
  },
  "outbreaks": [
    {"country": "China", "start_year": "1992", "summary": "Global pandemic; annual losses >$1B"}
  ],
  "recent_literature": [
    {"pmid": "42055174", "title": "Activation of Host Endogenous Reverse Transcriptase...", "year": "2026", "journal": "..."}
  ],
  "stats": {
    "total_isolates": 187,
    "total_hosts": 15,
    "total_evidence": 3391,
    "total_proteins": 42,
    "countries_detected": 18
  }
}
```
