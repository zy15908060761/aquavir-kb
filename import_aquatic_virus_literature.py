#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AquaVir-KB: 水生无脊椎动物病毒文献导入管道
=============================================
从 NCBI PubMed 检索结果中提取结构化数据，生成可直接导入数据库的 TSV 文件。

功能：
1. 将文献导入 ref_literatures 表格式
2. 从标题/摘要中提取病毒-宿主关联候选
3. 按新类群（软体动物/刺胞动物/海绵）分类
4. 生成待审核的 virus_master + host + infection 候选数据
5. 自动标记 host_association_method 和 discovery_context

输入：F:\水生无脊椎动物病毒检索\水生无脊椎动物病毒文献_完整版.csv
输出：import_ready/ 目录下的多个 TSV 文件
"""

import csv
import json
import re
import sqlite3
import unicodedata
from collections import defaultdict
from datetime import datetime
from pathlib import Path

# ============================================================================
# 配置
# ============================================================================
SOURCE_CSV = Path(r"F:\水生无脊椎动物病毒检索\水生无脊椎动物病毒文献_完整版.csv")
OUT_DIR = Path(r"F:\甲壳动物数据库\import_ready")
DB_PATH = Path(r"F:\甲壳动物数据库\crustacean_virus_core.db")
OUT_DIR.mkdir(parents=True, exist_ok=True)

# ============================================================================
# 分类学关键词词典
# ============================================================================
HOST_KEYWORDS = {
    "Mollusca": {
        "phylum": "Mollusca",
        "class_candidates": {
            "Bivalvia": ["oyster", "mussel", "clam", "scallop", "bivalve", "cockle", "ark shell",
                         "crassostrea", "magallana", "saccostrea", "ostrea", "mytilus", "pinctada",
                         "meretrix", "ruditapes", "chlamys", "patinopecten", "argopecten"],
            "Gastropoda": ["abalone", "snail", "slug", "sea slug", "gastropod", "conch", "whelk",
                           "haliotis", "babylonia", "turbo", "aphysia"],
            "Cephalopoda": ["squid", "octopus", "cuttlefish", "nautilus"],
        },
        "common_names": ["oyster", "mussel", "clam", "scallop", "abalone", "snail", "squid", "octopus"],
    },
    "Cnidaria": {
        "phylum": "Cnidaria",
        "class_candidates": {
            "Anthozoa": ["coral", "sea anemone", "actinia", "stony coral", "soft coral",
                         "acropora", "pocillopora", "montipora", "stylophora"],
            "Scyphozoa": ["jellyfish", "scyphozoan", "aurelia", "rhizostoma"],
            "Hydrozoa": ["hydra", "hydrozoan", "obelia", "portuguese man o' war"],
        },
        "common_names": ["coral", "jellyfish", "sea anemone", "hydra"],
    },
    "Porifera": {
        "phylum": "Porifera",
        "class_candidates": {
            "Demospongiae": ["sponge", "demosponge", "bath sponge", "suberites", "halichondria"],
            "Calcarea": ["calcareous sponge", "calcisponge"],
        },
        "common_names": ["sponge"],
    },
    "Arthropoda": {
        "phylum": "Arthropoda",
        "class_candidates": {
            "Malacostraca": ["shrimp", "prawn", "crab", "lobster", "crayfish", "krill", "copepod",
                             "barnacle", "isopod", "amphipod", "mantis shrimp",
                             "penaeus", "litopenaeus", "fenneropenaeus", "marsupenaeus",
                             "macrobrachium", "palaemon", "callinectes", "portunus",
                             "scylla", "eriocheir", "homarus", "astacus", "procambarus",
                             "pandalus", "litopenaeus vannamei", "penaeus monodon"],
            "Maxillopoda": ["copepod", "barnacle", "thecostraca", "calanus", "tigriopus"],
            "Branchiopoda": ["fairy shrimp", "brine shrimp", "artemia", "daphnia", "water flea"],
        },
        "common_names": ["shrimp", "prawn", "crab", "lobster", "crayfish", "krill", "copepod"],
    },
}

# 病毒关键词（用于从标题摘要中提取病毒名候选）
VIRUS_SUFFIXES = [
    "virus", "viruses", "viral", "virome", "viridae", "virinae", "virus-like",
    "nodavirus", "iridovirus", "herpesvirus", "parvovirus", "picornavirus",
    "reovirus", "bunyavirus", "rhabdovirus", "baculovirus", "circovirus",
    "densovirus", "mivirus", "thaumaparvovirus", "hepatopancreatic parvovirus",
]

# 已知重要病毒（快速匹配）
KNOWN_VIRUSES = {
    "white spot syndrome virus": {"abbr": "WSSV", "family": "Nimaviridae", "genus": "Whispovirus"},
    "yellow head virus": {"abbr": "YHV", "family": "Roniviridae", "genus": "Okavirus"},
    "taura syndrome virus": {"abbr": "TSV", "family": "Dicistroviridae", "genus": "Aparavirus"},
    "infectious hypodermal and hematopoietic necrosis virus": {"abbr": "IHHNV", "family": "Parvoviridae", "genus": "Penstyldensovirus"},
    "infectious myonecrosis virus": {"abbr": "IMNV", "family": "Totiviridae", "genus": "Giardiavirus"},
    "macrobrachium rosenbergii nodavirus": {"abbr": "MrNV", "family": "Nodaviridae", "genus": "Alphanodavirus"},
    "ostreid herpesvirus 1": {"abbr": "OsHV-1", "family": "Malacoherpesviridae", "genus": "Ostreavirus"},
    "ostreid herpesvirus": {"abbr": "OsHV", "family": "Malacoherpesviridae", "genus": "Ostreavirus"},
    "haliotid herpesvirus 1": {"abbr": "AbHV-1", "family": "Malacoherpesviridae", "genus": "Aurivirus"},
    "acute viral necrosis virus": {"abbr": "AVNV", "family": "Nodaviridae", "genus": "Alphanodavirus"},
    "hepatopancreatic parvovirus": {"abbr": "HPV", "family": "Parvoviridae", "genus": "Decapodpenstyldensovirus"},
}

# 检测方法关键词
DETECTION_METHODS = {
    "PCR": ["pcr", "rt-pcr", "qpcr", "rt-qpcr", "real-time pcr", "real time pcr", "quantitative pcr"],
    "ISH": ["in situ hybridization", "ish"],
    "TEM": ["transmission electron microscopy", "tem", "electron microscop"],
    "virus isolation": ["virus isolation", "cell culture", "primary culture", "inoculation"],
    "experimental infection": ["experimental infection", "challenge study", "infection trial", "bioassay"],
    "immunohistochemistry": ["immunohistochemistry", "ihc", "immunofluorescence", "ifa"],
    "sequencing": ["sequencing", "genome sequencing", "next-generation sequencing", "ngs", "metagenomic", "metagenome"],
    "histopathology": ["histopathology", "histology", "pathology", "lesion"],
}

# 疾病症状关键词
DISEASE_SYMPTOMS = [
    "mortality", "death", "die-off", "mass mortality", "epizootic",
    "white spot", "white spots", "white tail", "white muscle",
    "yellow head", "yellowing",
    "hematopoietic necrosis", "necrosis", "necrotic",
    "paralysis", "lethargy", "anorexia",
    "gill disease", "shell disease", "slow growth",
    "summer mortality", "winter mortality",
]

# ============================================================================
# 工具函数
# ============================================================================
def normalize(text):
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", text).strip().lower()

def extract_virus_candidates(title, abstract):
    """从文本中提取可能的病毒名称"""
    text = normalize(title + " " + abstract)
    candidates = []
    
    # 1. 匹配已知病毒
    for name, info in KNOWN_VIRUSES.items():
        if name in text:
            candidates.append({"name": name, **info, "match_type": "known"})
    
    # 2. 匹配 "X virus" 模式
    pattern = r'([a-z]+(?:\s+[a-z]+){0,4})\s+((?:nodavirus|iridovirus|herpesvirus|parvovirus|picornavirus|reovirus|bunyavirus|rhabdovirus|baculovirus|circovirus|mivirus|virus))'
    for m in re.finditer(pattern, text):
        prefix, suffix = m.groups()
        full_name = f"{prefix} {suffix}"
        if len(prefix) > 2 and full_name not in [c["name"] for c in candidates]:
            candidates.append({"name": full_name, "abbr": "", "family": "", "genus": "", "match_type": "pattern"})
    
    return candidates

def detect_host_phylum(title, abstract):
    """检测文献涉及的宿主门类"""
    text = normalize(title + " " + abstract)
    results = []
    
    for phylum_name, data in HOST_KEYWORDS.items():
        score = 0
        matched_classes = []
        
        # 通用名匹配
        for cn in data["common_names"]:
            if cn in text:
                score += 2
        
        # 纲级别匹配
        for class_name, keywords in data["class_candidates"].items():
            for kw in keywords:
                if kw in text:
                    score += 1
                    if class_name not in matched_classes:
                        matched_classes.append(class_name)
        
        if score > 0:
            results.append({
                "phylum": data["phylum"],
                "classes": matched_classes,
                "score": score,
            })
    
    # 按分数排序
    results.sort(key=lambda x: x["score"], reverse=True)
    return results

def detect_association_method(title, abstract):
    """推断宿主关联方法"""
    text = normalize(title + " " + abstract)
    
    # 最高优先级：实验感染
    for kw in DETECTION_METHODS["experimental infection"]:
        if kw in text:
            return "confirmed_infection"
    
    # 次高：病毒分离
    for kw in DETECTION_METHODS["virus isolation"]:
        if kw in text:
            return "confirmed_infection"
    
    # 疾病爆发
    for kw in DISEASE_SYMPTOMS:
        if kw in text:
            return "disease_outbreak"
    
    # PCR/ISH/TEM 确认
    for method in ["PCR", "ISH", "TEM", "immunohistochemistry"]:
        for kw in DETECTION_METHODS[method]:
            if kw in text:
                return "confirmed_infection"
    
    # 病理观察
    for kw in DETECTION_METHODS["histopathology"]:
        if kw in text:
            return "pathology_observation"
    
    # 测序/宏基因组（默认）
    for kw in DETECTION_METHODS["sequencing"]:
        if kw in text:
            return "co_occurrence_metagenomic"
    
    return "co_occurrence_metagenomic"

def detect_discovery_context(title, abstract, assoc_method):
    """推断发现背景"""
    text = normalize(title + " " + abstract)
    
    if assoc_method in ("confirmed_infection", "disease_outbreak", "pathology_observation"):
        if any(kw in text for kw in ["cell culture", "isolation", "purified", "propagated", "passage"]):
            return "isolated_and_cultured"
        return "metagenomic_with_host_evidence"
    
    if "virome" in text or "metagenom" in text or "shotgun" in text:
        return "metagenomic_environmental"
    
    return "metagenomic_environmental"

def load_existing_pmids(db_path):
    """从数据库加载已有PMID，避免重复导入"""
    existing = set()
    if not db_path.exists():
        return existing
    try:
        conn = sqlite3.connect(str(db_path), timeout=10)
        cur = conn.cursor()
        cur.execute("SELECT pmid FROM ref_literatures WHERE pmid IS NOT NULL")
        for row in cur.fetchall():
            existing.add(row[0])
        conn.close()
    except Exception as e:
        print(f"Warning: could not read existing PMIDs: {e}")
    return existing

# ============================================================================
# 主处理流程
# ============================================================================
def process_literature():
    print("=" * 60)
    print("AquaVir-KB 文献导入数据准备")
    print("=" * 60)
    
    # 读取源数据
    print(f"\n读取文献数据: {SOURCE_CSV}")
    rows = []
    with SOURCE_CSV.open("r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    print(f"共读取 {len(rows)} 篇文献")
    
    # 检查数据库已有PMID
    existing_pmids = load_existing_pmids(DB_PATH)
    print(f"数据库中已有 {len(existing_pmids)} 条文献记录")
    
    new_rows = [r for r in rows if r.get("pmid") and r["pmid"] not in existing_pmids]
    print(f"新增文献: {len(new_rows)} 篇")
    
    # ========================================================================
    # 输出1: ref_literatures 导入文件
    # ========================================================================
    ref_out = OUT_DIR / "01_ref_literatures.tsv"
    with ref_out.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.writer(fh, delimiter="\t")
        writer.writerow(["pmid", "title", "authors", "journal", "year", "doi", "abstract", "keywords"])
        for row in new_rows:
            writer.writerow([
                row.get("pmid", ""),
                row.get("title", ""),
                row.get("authors", ""),
                row.get("journal", ""),
                row.get("year", ""),
                row.get("doi", ""),
                row.get("abstract", ""),
                row.get("keywords", ""),
            ])
    print(f"\n[输出1] ref_literatures 导入文件: {ref_out} ({len(new_rows)} 条)")
    
    # ========================================================================
    # 输出2: 宿主-病毒关联候选（按新类群分类）
    # ========================================================================
    host_virus_candidates = []
    
    for row in new_rows:
        title = row.get("title", "")
        abstract = row.get("abstract", "")
        pmid = row.get("pmid", "")
        
        if not title:
            continue
        
        # 检测宿主门类
        host_results = detect_host_phylum(title, abstract)
        if not host_results:
            continue
        
        # 检测病毒候选
        virus_candidates = extract_virus_candidates(title, abstract)
        
        # 推断关联方法和发现背景
        assoc_method = detect_association_method(title, abstract)
        discovery_ctx = detect_discovery_context(title, abstract, assoc_method)
        
        # 为每个宿主门类+病毒组合生成候选
        for host_info in host_results:
            phylum = host_info["phylum"]
            classes = host_info["classes"]
            
            # 确定默认class
            default_class = classes[0] if classes else ""
            
            # 确定宿主通用名
            common_name = ""
            if phylum == "Mollusca":
                common_name = "mollusk"
            elif phylum == "Cnidaria":
                common_name = "cnidarian"
            elif phylum == "Porifera":
                common_name = "sponge"
            elif phylum == "Arthropoda":
                common_name = "crustacean"
            
            for virus in virus_candidates:
                host_virus_candidates.append({
                    "pmid": pmid,
                    "title": title[:120],
                    "virus_name": virus["name"],
                    "virus_abbr": virus["abbr"],
                    "virus_family": virus["family"],
                    "virus_genus": virus["genus"],
                    "host_phylum": phylum,
                    "host_class": default_class,
                    "host_common_name": common_name,
                    "host_association_method": assoc_method,
                    "discovery_context": discovery_ctx,
                    "match_type": virus["match_type"],
                    "host_score": host_info["score"],
                })
    
    # 按门类分组输出
    phylum_groups = defaultdict(list)
    for cand in host_virus_candidates:
        phylum_groups[cand["host_phylum"]].append(cand)
    
    for phylum, cands in phylum_groups.items():
        safe_name = phylum.lower()
        out_path = OUT_DIR / f"02_host_virus_candidates_{safe_name}.tsv"
        with out_path.open("w", newline="", encoding="utf-8-sig") as fh:
            writer = csv.DictWriter(fh, delimiter="\t", fieldnames=[
                "pmid", "title", "virus_name", "virus_abbr", "virus_family", "virus_genus",
                "host_phylum", "host_class", "host_common_name",
                "host_association_method", "discovery_context", "match_type", "host_score"
            ])
            writer.writeheader()
            writer.writerows(cands)
        print(f"[输出2-{phylum}] 宿主-病毒候选: {out_path} ({len(cands)} 条)")
    
    # ========================================================================
    # 输出3: 高质量确认关联（可直接进入 infection_records 审核队列）
    # ========================================================================
    high_quality = [
        {k: c[k] for k in ["pmid", "title", "virus_name", "virus_abbr", "virus_family", "virus_genus",
                           "host_phylum", "host_class", "host_common_name",
                           "host_association_method", "discovery_context"]}
        for c in host_virus_candidates
        if c["host_association_method"] in ("confirmed_infection", "disease_outbreak")
        and c["match_type"] == "known"
    ]
    
    hq_out = OUT_DIR / "03_high_quality_associations.tsv"
    with hq_out.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, delimiter="\t", fieldnames=[
            "pmid", "title", "virus_name", "virus_abbr", "virus_family", "virus_genus",
            "host_phylum", "host_class", "host_common_name",
            "host_association_method", "discovery_context"
        ])
        writer.writeheader()
        writer.writerows(high_quality)
    print(f"[输出3] 高质量确认关联: {hq_out} ({len(high_quality)} 条)")
    
    # ========================================================================
    # 输出4: 新类群文献清单（用于Phase 1-3数据策展）
    # ========================================================================
    new_phylum_literature = defaultdict(list)
    for row in new_rows:
        title = row.get("title", "")
        abstract = row.get("abstract", "")
        host_results = detect_host_phylum(title, abstract)
        for hr in host_results:
            if hr["phylum"] in ("Mollusca", "Cnidaria", "Porifera"):
                new_phylum_literature[hr["phylum"]].append(row)
                break
    
    for phylum, lit_rows in new_phylum_literature.items():
        safe_name = phylum.lower()
        out_path = OUT_DIR / f"04_literature_{safe_name}_phase.tsv"
        with out_path.open("w", newline="", encoding="utf-8-sig") as fh:
            writer = csv.writer(fh, delimiter="\t")
            writer.writerow(["pmid", "year", "title", "journal", "doi", "host_phylum", "host_class"])
            for row in lit_rows:
                host_results = detect_host_phylum(row.get("title", ""), row.get("abstract", ""))
                classes = ", ".join(host_results[0]["classes"]) if host_results else ""
                writer.writerow([
                    row.get("pmid", ""), row.get("year", ""), row.get("title", ""),
                    row.get("journal", ""), row.get("doi", ""), phylum, classes,
                ])
        print(f"[输出4-{phylum}] 新类群文献: {out_path} ({len(lit_rows)} 篇)")
    
    # ========================================================================
    # 输出5: 导入SQL（可选，直接执行）
    # ========================================================================
    sql_out = OUT_DIR / "05_import_ref_literatures.sql"
    with sql_out.open("w", encoding="utf-8") as fh:
        fh.write("-- AquaVir-KB: 批量导入 ref_literatures\n")
        fh.write(f"-- Generated: {datetime.now().isoformat()}\n")
        fh.write(f"-- Rows: {len(new_rows)}\n\n")
        fh.write("BEGIN TRANSACTION;\n\n")
        
        for row in new_rows:
            pmid = row.get("pmid", "").replace("'", "''")
            title = row.get("title", "").replace("'", "''")
            authors = row.get("authors", "").replace("'", "''")
            journal = row.get("journal", "").replace("'", "''")
            year = row.get("year", "")
            doi = row.get("doi", "").replace("'", "''")
            abstract = row.get("abstract", "").replace("'", "''")
            keywords = row.get("keywords", "").replace("'", "''")
            
            sql = f"""INSERT OR IGNORE INTO ref_literatures (pmid, title, authors, journal, year, doi, abstract, keywords)
VALUES ('{pmid}', '{title}', '{authors}', '{journal}', '{year}', '{doi}', '{abstract}', '{keywords}');\n"""
            fh.write(sql)
        
        fh.write("\nCOMMIT;\n")
    print(f"[输出5] SQL导入脚本: {sql_out}")
    
    # ========================================================================
    # 统计摘要
    # ========================================================================
    summary = {
        "total_literature": len(rows),
        "new_literature": len(new_rows),
        "existing_in_db": len(existing_pmids),
        "host_virus_candidates": len(host_virus_candidates),
        "high_quality_associations": len(high_quality),
        "by_phylum": {phylum: len(cands) for phylum, cands in phylum_groups.items()},
        "new_phylum_literature": {phylum: len(lit) for phylum, lit in new_phylum_literature.items()},
    }
    
    summary_out = OUT_DIR / "import_summary.json"
    with summary_out.open("w", encoding="utf-8") as fh:
        json.dump(summary, fh, ensure_ascii=False, indent=2)
    print(f"\n[输出6] 统计摘要: {summary_out}")
    
    print("\n" + "=" * 60)
    print("处理完成！")
    print("=" * 60)
    print(f"\n总文献: {len(rows)}")
    print(f"新增文献: {len(new_rows)}")
    print(f"宿主-病毒候选: {len(host_virus_candidates)}")
    print(f"  高质量确认关联: {len(high_quality)}")
    print(f"\n按门类候选分布:")
    for phylum, count in sorted(summary["by_phylum"].items(), key=lambda x: x[1], reverse=True):
        print(f"  {phylum}: {count} 条")
    print(f"\n新类群文献分布:")
    for phylum, count in sorted(summary["new_phylum_literature"].items(), key=lambda x: x[1], reverse=True):
        print(f"  {phylum}: {count} 篇")
    print(f"\n所有输出文件位于: {OUT_DIR}")


if __name__ == "__main__":
    process_literature()
