#!/usr/bin/env python3
"""
从权威来源提取虾类病毒毒力/温度数据 — 数据模板生成 + 导入脚本

数据来源：
  A. WOAH Aquatic Manual (https://www.woah.org/en/what-we-do/standards/codes-and-manuals/)
     - Chapter 2.2.1: Infection with white spot syndrome virus
     - Chapter 2.2.2: Infection with yellow head virus genotype 1
     - Chapter 2.2.3: Infection with Taura syndrome virus
     - Chapter 2.2.4: Infection with infectious hypodermal and haematopoietic necrosis virus
     - Chapter 2.2.5: Infection with infectious myonecrosis virus
     - Chapter 2.2.8: Infection with decapod iridescent virus 1

  B. Key review papers:
     - Lightner DV (2011) Virus diseases of farmed shrimp in the Western Hemisphere
     - Flegel TW (2012) Historic emergence, impact and current status of shrimp pathogens in Asia
     - OIE disease cards for each virus
     - FAO Cultured Aquatic Species Fact Sheets

输出：
  - master_data_template.csv  — 需要人工填写的结构化模板
  - 填完后运行本脚本的 --import 模式即可导入数据库
"""

import csv
import json
import sqlite3
import sys
from pathlib import Path
from datetime import datetime

DB_PATH = Path(r"F:\甲壳动物数据库\crustacean_virus_core.db")
OUT_DIR = Path(r"F:\甲壳动物数据库\external_data\multi_source_mining\woah_review_extraction")
OUT_DIR.mkdir(parents=True, exist_ok=True)

# ═══════════════════════════════════
# 数据模板
# ═══════════════════════════════════

# 每行=一种病毒的毒力/温度数据，注释标注了数据应从哪里获取
TEMPLATE_ROWS = [
    # ─── 已有实验数据的病毒（从数据库提取，可补充新数据）───
    {
        "virus_name": "White spot syndrome virus",
        "virus_family": "Nimaviridae",
        "virulence_level": "High",
        "mortality_rate_min": "",
        "mortality_rate_max": "100",
        "ld50_value": "",
        "pathogenic_mechanism": "Systemic infection of mesodermal and ectodermal tissues; broad host range (>100 species)",
        "optimal_temp_min": "25",
        "optimal_temp_max": "30",
        "temp_range_min": "4",
        "temp_range_max": "35",
        "thermal_inactivation_temp": "50",
        "thermal_inactivation_time": "120",
        "cold_storage_temp": "-20",
        "cold_storage_viability": "Infectious after freeze-thaw at -20 C for 30 days",
        "data_source": "WOAH Aquatic Manual Ch.2.2.1; Lightner 2011; existing DB record",
        "confidence": "high",
        "needs_verification": "YES — verify numbers against original WOAH chapter",
        "woah_chapter_url": "https://www.woah.org/en/what-we-do/standards/codes-and-manuals/aquatic-code-online-access/?id=169&L=1&htmfile=chapitre_wsd.htm",
        "lit_search_query": "WSSV AND (temperature OR thermal inactivation) AND (mortality OR LD50) — filter: review",
        "notes_from_automated_mining": "已有DB记录(high confidence); step1b挖掘未发现新temperature数据(摘要中无)",
    },
    {
        "virus_name": "Yellow head virus",
        "virus_family": "Roniviridae",
        "virulence_level": "High",
        "mortality_rate_min": "",
        "mortality_rate_max": "100",
        "ld50_value": "",
        "pathogenic_mechanism": "Systemic infection; genotype 1 highly pathogenic; genotypes 2-7 variable; lymphoid organ primary target",
        "optimal_temp_min": "28",
        "optimal_temp_max": "30",
        "temp_range_min": "15",
        "temp_range_max": "33",
        "thermal_inactivation_temp": "55",
        "thermal_inactivation_time": "30",
        "cold_storage_temp": "-80",
        "cold_storage_viability": "Stable at -80 C; loses infectivity at -20 C after repeated freeze-thaw",
        "data_source": "WOAH Aquatic Manual Ch.2.2.2; Flegel 2012; existing DB record",
        "confidence": "high",
        "needs_verification": "YES — verify temp numbers against WOAH chapter",
        "woah_chapter_url": "https://www.woah.org/en/what-we-do/standards/codes-and-manuals/aquatic-code-online-access/?id=169&L=1&htmfile=chapitre_yhd.htm",
        "lit_search_query": "yellow head virus AND (temperature OR thermal) AND (mortality OR cumulative)",
        "notes_from_automated_mining": "已有DB记录; step1b挖掘找到5条死亡率候选",
    },
    {
        "virus_name": "Taura syndrome virus",
        "virus_family": "Dicistroviridae",
        "virulence_level": "High",
        "mortality_rate_min": "",
        "mortality_rate_max": "95",
        "ld50_value": "",
        "pathogenic_mechanism": "Genotype-dependent; acute phase in post-larvae/juveniles; cuticular epithelium necrosis",
        "optimal_temp_min": "26",
        "optimal_temp_max": "32",
        "temp_range_min": "15",
        "temp_range_max": "35",
        "thermal_inactivation_temp": "60",
        "thermal_inactivation_time": "30",
        "cold_storage_temp": "-20",
        "cold_storage_viability": "Stable in frozen tissue; survives freeze-thaw cycles",
        "data_source": "WOAH Aquatic Manual Ch.2.2.3; Lightner 2011; existing DB record",
        "confidence": "high",
        "needs_verification": "YES — verify against WOAH chapter",
        "woah_chapter_url": "https://www.woah.org/en/what-we-do/standards/codes-and-manuals/aquatic-code-online-access/?id=169&L=1&htmfile=chapitre_tsd.htm",
        "lit_search_query": "Taura syndrome virus AND (temperature OR thermal) AND (mortality OR virulence)",
        "notes_from_automated_mining": "已有DB记录; step1b挖掘找到4条温度候选",
    },

    # ─── WOAH有标准化数据的病毒（需从WOAH章节提取后填入）───
    {
        "virus_name": "Infectious hypodermal and hematopoietic necrosis virus",
        "virus_family": "Parvoviridae",
        "virulence_level": "Moderate",
        "mortality_rate_min": "",
        "mortality_rate_max": "90",
        "ld50_value": "",
        "pathogenic_mechanism": "Strain-dependent; causes runt deformity syndrome (RDS); some strains subclinical",
        "optimal_temp_min": "",
        "optimal_temp_max": "",
        "temp_range_min": "",
        "temp_range_max": "",
        "thermal_inactivation_temp": "",
        "thermal_inactivation_time": "",
        "cold_storage_temp": "",
        "cold_storage_viability": "",
        "data_source": "WOAH Aquatic Manual Ch.2.2.4; existing DB record",
        "confidence": "high",
        "needs_verification": "YES — temperature data needs extraction from WOAH chapter",
        "woah_chapter_url": "https://www.woah.org/en/what-we-do/standards/codes-and-manuals/aquatic-code-online-access/?id=169&L=1&htmfile=chapitre_ihhn.htm",
        "lit_search_query": "IHHNV AND (temperature OR thermal) — mostly in review articles",
        "notes_from_automated_mining": "已有DB记录(virulence=Moderate); 温度数据需从WOAH提取",
    },
    {
        "virus_name": "Infectious myonecrosis virus",
        "virus_family": "Totiviridae",
        "virulence_level": "High",
        "mortality_rate_min": "",
        "mortality_rate_max": "85",
        "ld50_value": "",
        "pathogenic_mechanism": "Chronic course with periodic acute episodes; stress-triggered; muscle necrosis",
        "optimal_temp_min": "",
        "optimal_temp_max": "",
        "temp_range_min": "",
        "temp_range_max": "",
        "thermal_inactivation_temp": "",
        "thermal_inactivation_time": "",
        "cold_storage_temp": "",
        "cold_storage_viability": "",
        "data_source": "WOAH Aquatic Manual Ch.2.2.5; existing DB record",
        "confidence": "high",
        "needs_verification": "YES — temperature data needs extraction from WOAH",
        "woah_chapter_url": "https://www.woah.org/en/what-we-do/standards/codes-and-manuals/aquatic-code-online-access/?id=169&L=1&htmfile=chapitre_imn.htm",
        "lit_search_query": "infectious myonecrosis virus AND (temperature OR thermal)",
        "notes_from_automated_mining": "已有DB记录(virulence=High); 温度数据需从WOAH提取",
    },
    {
        "virus_name": "Decapod iridescent virus",
        "virus_family": "Iridoviridae",
        "virulence_level": "",
        "mortality_rate_min": "",
        "mortality_rate_max": "",
        "ld50_value": "",
        "pathogenic_mechanism": "Systemic infection; hematopoietic tissue primary target; causes high mortality in farmed shrimp",
        "optimal_temp_min": "",
        "optimal_temp_max": "",
        "temp_range_min": "",
        "temp_range_max": "",
        "thermal_inactivation_temp": "",
        "thermal_inactivation_time": "",
        "cold_storage_temp": "",
        "cold_storage_viability": "",
        "data_source": "WOAH Aquatic Manual Ch.2.2.8 (DIV1); Qiu et al. 2018; recent publications",
        "confidence": "medium",
        "needs_verification": "YES — newer disease, check WOAH chapter and recent lit",
        "woah_chapter_url": "https://www.woah.org/en/what-we-do/standards/codes-and-manuals/aquatic-code-online-access/?id=169&L=1&htmfile=chapitre_div1.htm",
        "lit_search_query": "decapod iridescent virus OR shrimp hemocyte iridescent virus AND (virulence OR mortality OR temperature)",
        "notes_from_automated_mining": "step1b挖掘找到5条死亡率候选; 无温度数据; 需WOAH+全文提取",
    },

    # ─── 需从综述文献提取的病毒 ───
    {
        "virus_name": "Covert mortality nodavirus",
        "virus_family": "Nodaviridae",
        "virulence_level": "",
        "mortality_rate_min": "",
        "mortality_rate_max": "",
        "ld50_value": "",
        "pathogenic_mechanism": "Causes covert mortality disease; hepatopancreas atrophy; frequently co-infects with other pathogens",
        "optimal_temp_min": "",
        "optimal_temp_max": "",
        "temp_range_min": "",
        "temp_range_max": "",
        "thermal_inactivation_temp": "",
        "thermal_inactivation_time": "",
        "cold_storage_temp": "",
        "cold_storage_viability": "",
        "data_source": "Zhang et al. 2014; Li et al. 2021; FAO/NACA reports",
        "confidence": "medium",
        "needs_verification": "YES — search PubMed: covert mortality nodavirus AND (temperature OR mortality)",
        "woah_chapter_url": "Not in WOAH Aquatic Manual (not yet listed)",
        "lit_search_query": "covert mortality nodavirus AND (virulence OR mortality OR temperature OR infection)",
        "notes_from_automated_mining": "",
    },
    {
        "virus_name": "Macrobrachium rosenbergii nodavirus",
        "virus_family": "Nodaviridae",
        "virulence_level": "Low",
        "mortality_rate_min": "",
        "mortality_rate_max": "",
        "ld50_value": "",
        "pathogenic_mechanism": "MrNV alone non-pathogenic; requires extra small virus (XSV) co-infection for white tail disease",
        "optimal_temp_min": "",
        "optimal_temp_max": "",
        "temp_range_min": "",
        "temp_range_max": "",
        "thermal_inactivation_temp": "",
        "thermal_inactivation_time": "",
        "cold_storage_temp": "",
        "cold_storage_viability": "",
        "data_source": "Bonami et al. 2005; Qian et al. 2003; existing DB record",
        "confidence": "medium",
        "needs_verification": "YES — MrNV+XSV co-infection data; existing DB has Low virulence but no temp data",
        "woah_chapter_url": "",
        "lit_search_query": "Macrobrachium rosenbergii nodavirus AND (temperature OR thermal inactivation) AND (mortality OR virulence)",
        "notes_from_automated_mining": "step1b挖掘找到24条候选(最多); 需人工核实是否含有实验数据",
    },
    {
        "virus_name": "Hepatopancreatic parvovirus",
        "virus_family": "Parvoviridae",
        "virulence_level": "",
        "mortality_rate_min": "",
        "mortality_rate_max": "",
        "ld50_value": "",
        "pathogenic_mechanism": "Hepatopancreas infection; chronic disease; growth retardation rather than acute mortality",
        "optimal_temp_min": "",
        "optimal_temp_max": "",
        "temp_range_min": "",
        "temp_range_max": "",
        "thermal_inactivation_temp": "",
        "thermal_inactivation_time": "",
        "cold_storage_temp": "",
        "cold_storage_viability": "",
        "data_source": "Lightner & Redman 1985; Flegel 2006; Bonami et al. review",
        "confidence": "medium",
        "needs_verification": "YES — search review articles for temperature/virulence data",
        "woah_chapter_url": "",
        "lit_search_query": "hepatopancreatic parvovirus OR HPV AND shrimp AND (virulence OR mortality OR temperature)",
        "notes_from_automated_mining": "step1b挖掘找到3条死亡率候选",
    },
    {
        "virus_name": "Mud crab virus",
        "virus_family": "",
        "virulence_level": "",
        "mortality_rate_min": "",
        "mortality_rate_max": "",
        "ld50_value": "",
        "pathogenic_mechanism": "",
        "optimal_temp_min": "",
        "optimal_temp_max": "",
        "temp_range_min": "",
        "temp_range_max": "",
        "thermal_inactivation_temp": "",
        "thermal_inactivation_time": "",
        "cold_storage_temp": "",
        "cold_storage_viability": "",
        "data_source": "Literature search: mud crab reovirus OR mud crab dicistrovirus",
        "confidence": "low",
        "needs_verification": "YES — limited literature; may need Chinese literature (CNKI)",
        "woah_chapter_url": "",
        "lit_search_query": "mud crab AND (reovirus OR dicistrovirus) AND (virulence OR mortality OR temperature)",
        "notes_from_automated_mining": "step1b找到2条死亡率候选",
    },
    {
        "virus_name": "Chinese mitten crab virus",
        "virus_family": "Cruliviridae",
        "virulence_level": "",
        "mortality_rate_min": "",
        "mortality_rate_max": "",
        "ld50_value": "",
        "pathogenic_mechanism": "Emerging pathogen of Eriocheir sinensis; associated with trembling disease",
        "optimal_temp_min": "",
        "optimal_temp_max": "",
        "temp_range_min": "",
        "temp_range_max": "",
        "thermal_inactivation_temp": "",
        "thermal_inactivation_time": "",
        "cold_storage_temp": "",
        "cold_storage_viability": "",
        "data_source": "Chinese literature; CNKI search recommended",
        "confidence": "low",
        "needs_verification": "YES — primarily Chinese literature; CNKI search recommended",
        "woah_chapter_url": "",
        "lit_search_query": "中华绒螯蟹 病毒 AND (温度 OR 毒力 OR 死亡率) # CNKI",
        "notes_from_automated_mining": "step1b找到1条候选",
    },
    {
        "virus_name": "Penaeus vannamei nodavirus",
        "virus_family": "Nodaviridae",
        "virulence_level": "",
        "mortality_rate_min": "",
        "mortality_rate_max": "",
        "ld50_value": "",
        "pathogenic_mechanism": "Causes muscle necrosis; similar to IMNV; reported in Brazil and Southeast Asia",
        "optimal_temp_min": "",
        "optimal_temp_max": "",
        "temp_range_min": "",
        "temp_range_max": "",
        "thermal_inactivation_temp": "",
        "thermal_inactivation_time": "",
        "cold_storage_temp": "",
        "cold_storage_viability": "",
        "data_source": "Tang et al. 2011; literature search",
        "confidence": "low",
        "needs_verification": "YES",
        "woah_chapter_url": "",
        "lit_search_query": "Penaeus vannamei nodavirus OR PvNV AND (virulence OR mortality OR temperature)",
        "notes_from_automated_mining": "",
    },
    {
        "virus_name": "Shrimp hemocyte iridescent virus",
        "virus_family": "Iridoviridae",
        "virulence_level": "",
        "mortality_rate_min": "",
        "mortality_rate_max": "",
        "ld50_value": "",
        "pathogenic_mechanism": "Same species as DIV1; synonym entry",
        "optimal_temp_min": "",
        "optimal_temp_max": "",
        "temp_range_min": "",
        "temp_range_max": "",
        "thermal_inactivation_temp": "",
        "thermal_inactivation_time": "",
        "cold_storage_temp": "",
        "cold_storage_viability": "",
        "data_source": "Same as DIV1 (WOAH Ch.2.2.8)",
        "confidence": "medium",
        "needs_verification": "YES — consolidate with DIV1 record",
        "woah_chapter_url": "https://www.woah.org/en/what-we-do/standards/codes-and-manuals/aquatic-code-online-access/?id=169&L=1&htmfile=chapitre_div1.htm",
        "lit_search_query": "",
        "notes_from_automated_mining": "与DIV1是同一病毒，建议合并",
    },
    {
        "virus_name": "Laem-Singh virus",
        "virus_family": "",
        "virulence_level": "",
        "mortality_rate_min": "",
        "mortality_rate_max": "",
        "ld50_value": "",
        "pathogenic_mechanism": "Associated with slow growth syndrome in P. monodon; may require co-factors",
        "optimal_temp_min": "",
        "optimal_temp_max": "",
        "temp_range_min": "",
        "temp_range_max": "",
        "thermal_inactivation_temp": "",
        "thermal_inactivation_time": "",
        "cold_storage_temp": "",
        "cold_storage_viability": "",
        "data_source": "Sritunyalucksana et al. 2006; literature search",
        "confidence": "low",
        "needs_verification": "YES",
        "woah_chapter_url": "",
        "lit_search_query": "Laem Singh virus AND shrimp AND (virulence OR mortality OR pathology)",
        "notes_from_automated_mining": "",
    },
    {
        "virus_name": "Wenzhou shrimp virus",
        "virus_family": "",
        "virulence_level": "",
        "mortality_rate_min": "",
        "mortality_rate_max": "",
        "ld50_value": "",
        "pathogenic_mechanism": "Discovered via metagenomics; pathogenicity not well characterized",
        "optimal_temp_min": "",
        "optimal_temp_max": "",
        "temp_range_min": "",
        "temp_range_max": "",
        "thermal_inactivation_temp": "",
        "thermal_inactivation_time": "",
        "cold_storage_temp": "",
        "cold_storage_viability": "",
        "data_source": "Li et al. 2015 (eLife); Shi et al. 2016 (Nature)",
        "confidence": "low",
        "needs_verification": "YES — primarily discovery papers; limited virulence data",
        "woah_chapter_url": "",
        "lit_search_query": "Wenzhou shrimp virus AND (pathogenicity OR virulence OR infection)",
        "notes_from_automated_mining": "",
    },
    {
        "virus_name": "Callinectes sapidus reovirus",
        "virus_family": "Reoviridae",
        "virulence_level": "",
        "mortality_rate_min": "",
        "mortality_rate_max": "",
        "ld50_value": "",
        "pathogenic_mechanism": "Blue crab reovirus; associated with lethargy and mortality in wild and aquaculture",
        "optimal_temp_min": "",
        "optimal_temp_max": "",
        "temp_range_min": "",
        "temp_range_max": "",
        "thermal_inactivation_temp": "",
        "thermal_inactivation_time": "",
        "cold_storage_temp": "",
        "cold_storage_viability": "",
        "data_source": "Bowers et al. 2010; Flowers et al. 2016; literature search",
        "confidence": "low",
        "needs_verification": "YES",
        "woah_chapter_url": "",
        "lit_search_query": "Callinectes sapidus reovirus AND (virulence OR mortality OR temperature)",
        "notes_from_automated_mining": "",
    },
    {
        "virus_name": "Eriocheir sinensis reovirus",
        "virus_family": "Reoviridae",
        "virulence_level": "",
        "mortality_rate_min": "",
        "mortality_rate_max": "",
        "ld50_value": "",
        "pathogenic_mechanism": "Associated with trembling disease in Chinese mitten crab",
        "optimal_temp_min": "",
        "optimal_temp_max": "",
        "temp_range_min": "",
        "temp_range_max": "",
        "thermal_inactivation_temp": "",
        "thermal_inactivation_time": "",
        "cold_storage_temp": "",
        "cold_storage_viability": "",
        "data_source": "Chinese literature; CNKI search: 中华绒螯蟹 呼肠孤病毒",
        "confidence": "low",
        "needs_verification": "YES — primarily Chinese literature",
        "woah_chapter_url": "",
        "lit_search_query": "中华绒螯蟹呼肠孤病毒 AND (温度 OR 毒力 OR 死亡率) # CNKI",
        "notes_from_automated_mining": "",
    },
]


# ═══════════════════════════════════════
def generate_template():
    """生成填写模板"""
    output_path = OUT_DIR / "master_data_template.csv"
    fieldnames = list(TEMPLATE_ROWS[0].keys())

    with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(TEMPLATE_ROWS)

    print(f"[TEMPLATE] {len(TEMPLATE_ROWS)} virus records → {output_path}")
    print(f"\n  Viruses with temperature fields blank (need extraction):")
    blank_temp = [r for r in TEMPLATE_ROWS if not r["thermal_inactivation_temp"]]
    for r in blank_temp:
        print(f"    - {r['virus_name']} [{r['data_source'][:60]}...]")

    blank_vir = [r for r in TEMPLATE_ROWS if not r["virulence_level"]]
    print(f"\n  Viruses with virulence_level blank (need extraction):")
    for r in blank_vir:
        print(f"    - {r['virus_name']} [{r['data_source'][:60]}...]")

    return output_path


# ═══════════════════════════════════════
def generate_extraction_guide():
    """生成提取指南：每个病毒去哪里找数据"""
    guide_path = OUT_DIR / "extraction_guide.md"

    guide = """# 甲壳动物病毒毒力/温度数据提取指南

## 第一步：WOAH Aquatic Manual（数据质量最高）

访问：https://www.woah.org/en/what-we-do/standards/codes-and-manuals/aquatic-code-online-access/

每个Disease Chapter的标准章节结构：
  1. Agent characteristics → 找温度稳定性数据
  2. Survival outside the host → 找热灭活条件、冷冻存活
  3. Stability and inactivation → 可能以表格形式列出

**重点提取字段**：
  - 热灭活温度(°C)和时间(min)
  - 最适增殖温度范围
  - 存活温度范围
  - 冷冻保存条件
  - 50%灭活的时间/温度

### 各病毒WOAH章节

| 病毒 | WOAH Chapter | URL |
|------|-------------|-----|
| WSSV | Ch. 2.2.1 | https://www.woah.org/en/what-we-do/standards/codes-and-manuals/aquatic-code-online-access/?id=169&L=1&htmfile=chapitre_wsd.htm |
| YHV | Ch. 2.2.2 | https://www.woah.org/en/what-we-do/standards/codes-and-manuals/aquatic-code-online-access/?id=169&L=1&htmfile=chapitre_yhd.htm |
| TSV | Ch. 2.2.3 | https://www.woah.org/en/what-we-do/standards/codes-and-manuals/aquatic-code-online-access/?id=169&L=1&htmfile=chapitre_tsd.htm |
| IHHNV | Ch. 2.2.4 | https://www.woah.org/en/what-we-do/standards/codes-and-manuals/aquatic-code-online-access/?id=169&L=1&htmfile=chapitre_ihhn.htm |
| IMNV | Ch. 2.2.5 | https://www.woah.org/en/what-we-do/standards/codes-and-manuals/aquatic-code-online-access/?id=169&L=1&htmfile=chapitre_imn.htm |
| DIV1 | Ch. 2.2.8 | https://www.woah.org/en/what-we-do/standards/codes-and-manuals/aquatic-code-online-access/?id=169&L=1&htmfile=chapitre_div1.htm |

## 第二步：关键综述论文

以下综述包含了多种病毒的温度/毒力汇总数据，一篇可提供多个病毒的数据：

1. **Lightner DV (2011)** Virus diseases of farmed shrimp in the Western Hemisphere
   - J Invertebr Pathol 106:110-130
   - DOI: 10.1016/j.jip.2010.09.012
   - 覆盖：WSSV, TSV, IHHNV, YHV, IMNV, NHP

2. **Flegel TW (2012)** Historic emergence, impact and current status of shrimp pathogens in Asia
   - J Invertebr Pathol 110:166-173
   - DOI: 10.1016/j.jip.2012.03.004
   - 覆盖：WSSV, YHV, IHHNV, TSV, MrNV, PvNV, CMNV

3. **OIE (2019)** Manual of Diagnostic Tests for Aquatic Animals
   - https://www.woah.org/en/what-we-do/standards/codes-and-manuals/aquatic-manual-online-access/
   - 每个疾病的诊断手册章节包含病原基本信息

4. **Walker PJ & Winton JR (2010)** Emerging viral diseases of fish and shrimp
   - Vet Res 41:51
   - DOI: 10.1051/vetres/2010022

5. **Bonami JR & Zhang S (2011)** Viral diseases in commercially exploited crustaceans
   - J Invertebr Pathol 106:6-17

## 第三步：特定病毒文献

对每个缺少数据的病毒，按以下策略搜索：

### 有WOAH章节的病毒（先看WOAH，数据最可靠）
- WSSV, YHV, TSV, IHHNV, IMNV, DIV1
- **优先提取WOAH数据**（标准化、有引用来源、不需要再查原始论文）

### WOAH未列出但研究较多的病毒（搜综述）
- CMNV: Zhang et al. 2014, Li et al. 2021
- MrNV+XSV: Bonami et al. 2005, Qian et al. 2003
- HPV: Lightner & Redman 1985
- LSNV: Sritunyalucksana et al. 2006

### 中文文献（CNKI搜索）
- 中华绒螯蟹相关病毒: "中华绒螯蟹" + "病毒" + "温度/死亡率"
- 青蟹病毒: "青蟹" + "病毒" + "感染"
- WzSV等温州病毒: "温州" + "虾病毒"

## 第四步：填写模板

1. 打开 `master_data_template.csv`
2. 对每个病毒：
   a. 先查WOAH章节（如有）
   b. 再查综述论文（如无WOAH）
   c. 搜索PubMed/CNKI（如综述中无数据）
3. 填入缺失的字段
4. 每条数据标注 `data_source`（章节/PMID/DOI）
5. 将 `needs_verification` 改为 "DONE"
6. 保存后运行：`python step1e_woah_review_extraction.py --import <填好的CSV>`

## 第五步：导入数据库

填完模板后运行：
```bash
python step1e_woah_review_extraction.py --import master_data_template.csv
```
"""

    with open(guide_path, "w", encoding="utf-8") as f:
        f.write(guide)
    print(f"[GUIDE] Extraction guide → {guide_path}")


# ═══════════════════════════════════════
def import_verified_data(csv_path: str):
    """将人工审核确认的数据导入数据库"""
    import sqlite3
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA busy_timeout = 30000")
    c = conn.cursor()

    with open(csv_path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows = [row for row in reader if row.get("needs_verification", "") == "DONE"]

    if not rows:
        print("No rows marked as DONE (needs_verification='DONE'). Nothing to import.")
        return

    now = datetime.now().isoformat()
    imported_vir = 0
    imported_temp = 0

    for row in rows:
        virus_name = row["virus_name"]

        # Import virulence
        if row.get("virulence_level"):
            c.execute("""
                INSERT OR REPLACE INTO virulence_profiles
                (virus_name, virulence_level, virulence_label,
                 mortality_rate_min, mortality_rate_max, ld50_value,
                 pathogenic_mechanism, data_source, confidence, curation_date, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                virus_name,
                row["virulence_level"],
                1 if row["virulence_level"] in ("High", "Moderate") else 0,
                float(row["mortality_rate_min"]) if row["mortality_rate_min"] else None,
                float(row["mortality_rate_max"]) if row["mortality_rate_max"] else None,
                row["ld50_value"] if row["ld50_value"] else None,
                row["pathogenic_mechanism"],
                row["data_source"],
                row["confidence"],
                now,
                f"Imported from WOAH/review extraction pipeline. {row['notes_from_automated_mining']}",
            ))
            imported_vir += 1

        # Import temperature
        temp_fields = ["optimal_temp_min", "optimal_temp_max", "temp_range_min",
                      "temp_range_max", "thermal_inactivation_temp", "thermal_inactivation_time",
                      "cold_storage_temp"]
        has_temp = any(row.get(f) for f in temp_fields)
        if has_temp:
            c.execute("""
                INSERT OR REPLACE INTO temperature_profiles
                (virus_name, optimal_temp_min, optimal_temp_max,
                 temp_range_min, temp_range_max,
                 thermal_inactivation_temp, thermal_inactivation_time,
                 cold_storage_temp, cold_storage_viability,
                 data_source, confidence, curation_date, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                virus_name,
                float(row["optimal_temp_min"]) if row["optimal_temp_min"] else None,
                float(row["optimal_temp_max"]) if row["optimal_temp_max"] else None,
                float(row["temp_range_min"]) if row["temp_range_min"] else None,
                float(row["temp_range_max"]) if row["temp_range_max"] else None,
                float(row["thermal_inactivation_temp"]) if row["thermal_inactivation_temp"] else None,
                float(row["thermal_inactivation_time"]) if row["thermal_inactivation_time"] else None,
                float(row["cold_storage_temp"]) if row["cold_storage_temp"] else None,
                row["cold_storage_viability"],
                row["data_source"],
                row["confidence"],
                now,
                f"Imported from WOAH/review extraction pipeline. {row['notes_from_automated_mining']}",
            ))
            imported_temp += 1

    conn.commit()

    # 验证
    c.execute("SELECT COUNT(*) FROM virulence_profiles WHERE notes NOT LIKE '%FAMILY_INFERRED%'")
    n_exp_vir = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM temperature_profiles WHERE notes NOT LIKE '%FAMILY_INFERRED%'")
    n_exp_temp = c.fetchone()[0]

    conn.close()

    print(f"\n[IMPORT] Done:")
    print(f"  New virulence profiles: {imported_vir}")
    print(f"  New temperature profiles: {imported_temp}")
    print(f"  Total experimental virulence: {n_exp_vir}")
    print(f"  Total experimental temperature: {n_exp_temp}")


# ═══════════════════════════════════════
def main():
    print("=" * 60)
    print("WOAH + Review Literature Data Extraction Pipeline")
    print("=" * 60)

    if "--import" in sys.argv:
        csv_path = sys.argv[sys.argv.index("--import") + 1]
        import_verified_data(csv_path)
    else:
        generate_template()
        generate_extraction_guide()

        print(f"\n{'='*60}")
        print("Workflow:")
        print(f"{'='*60}")
        print("""
1. 打开 WOAH Aquatic Manual 网站（提取指南中的链接）
2. 对照 master_data_template.csv，逐病毒提取数据
3. 再从综述论文中补充 WOAH 未覆盖的病毒
4. 填完后将 needs_verification 列改为 "DONE"
5. 运行: python step1e_woah_review_extraction.py --import master_data_template.csv

预计产出：
  WOAH → WSSV, YHV, TSV, IHHNV, IMNV, DIV1 (6种，高质量温度+毒力)
  综述 → CMNV, HPV, MrNV, PvNV, LSNV (5-8种，中等质量)
  CNKI → 中华绒螯蟹病毒, 青蟹病毒 (2-3种)
  已有数据 → WSSV, YHV, TSV, IHHNV, IMNV, MrNV (7种，已确认)

  总计目标：20-25种病毒有至少部分实验数据支撑
""")


if __name__ == "__main__":
    main()
