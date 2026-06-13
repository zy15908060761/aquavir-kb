#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
从已下载的全文 (PMC XML + 元数据) 中提取结构化证据
- 624 PMC XML → 解析<article>提取病毒/宿主/疾病/温度信息
- 519+41 PDF → 从文件名匹配(基于已有的PMID元数据)
"""

import re
import json
import sqlite3
from pathlib import Path
from xml.etree import ElementTree as ET
from collections import defaultdict, Counter
from datetime import datetime

DB_PATH = Path(r"F:\甲壳动物数据库\crustacean_virus_core.db")
XML_DIR = Path(r"F:\甲壳动物数据库\literature_curation_v2\pmc_xml")
PDF_DIR = Path(r"F:\甲壳动物数据库\literature_curation_v2\fulltext")
OA_DIR = Path(r"F:\甲壳动物数据库\literature_curation_v2\oa_fulltext")
LOG_DIR = Path(r"F:\甲壳动物数据库\downloads\fulltext_extraction")
LOG_DIR.mkdir(parents=True, exist_ok=True)

# 数据库中的病毒名→master_id
VIRUS_DICT = {}
HOST_DICT = {}

# 证据信号词
DIAG_SIGNALS = [
    "PCR", "qPCR", "RT-PCR", "RT-qPCR", "LAMP", "ELISA", "immunoassay",
    "in situ hybridization", "ISH", "western blot", "immunohistochemistry",
    "metagenomic", "next-generation sequencing", "NGS", "diagnostic",
    "detection method", "TaqMan", "SYBR Green", "RPA", "recombinase polymerase",
]

PATHOGEN_SIGNALS = [
    "mortality", "cumulative mortality", "lethal", "LD50",
    "challenge", "experimental infection", "pathogenicity", "virulence",
    "tissue tropism", "histopathology", "disease signs", "symptom",
    "survival rate", "death rate",
]

TEMPERATURE_SIGNALS = [
    "temperature", "thermal", "water temperature", "heat",
    "heat shock", "degree", "°C", "℃",
]

HOST_SIGNALS = [
    "host range", "infected", "infection", "natural infection",
    "experimental infection", "susceptible", "carrier", "reservoir",
    "transmission", "host", "Penaeus", "Litopenaeus", "Macrobrachium",
    "Scylla", "Cherax", "Procambarus", "Eriocheir", "Portunus",
    "Crassostrea", "Haliotis", "Chlamys", "Scapharca",
]


def load_lookup_tables(con):
    """加载病毒名和宿主名查找表"""
    global VIRUS_DICT, HOST_DICT

    for row in con.execute("SELECT master_id, canonical_name, abbreviations FROM virus_master"):
        names = [row[1] or ""]
        if row[2]:
            names.extend([a.strip() for a in row[2].split(",")])
        for n in names:
            if n and len(n) >= 8:
                VIRUS_DICT[n.lower()] = row[0]

    for row in con.execute("SELECT host_id, scientific_name, common_name_cn FROM crustacean_hosts"):
        if row[1]:
            HOST_DICT[row[1].lower()] = row[0]
        if row[2]:
            HOST_DICT[row[2].lower()] = row[0]


def extract_text_from_xml(filepath):
    """从PMC NXML提取有效文本 (兼容 JATS 和 NLM DTD 格式)"""
    try:
        with open(filepath, 'r', encoding='utf-8-sig', errors='ignore') as f:
            content = f.read()

        # 跳过 publisher 限制的
        if 'does not allow downloading of the full text' in content:
            return ""

        root = ET.fromstring(content)

        texts = []
        # 遍历所有元素收集文本
        for el in root.iter():
            tag = el.tag.split('}')[-1] if '}' in el.tag else el.tag

            # 收集 article-title
            if tag == 'article-title':
                t = ''.join(el.itertext()).strip()
                if t:
                    texts.append(t)

            # 收集 abstract
            if tag == 'abstract' or tag.endswith('abstract'):
                t = ''.join(el.itertext()).strip()
                if t and len(t) > 20:
                    texts.append(t)

            # 收集段落
            if tag == 'p' or tag.endswith('}p'):
                t = ''.join(el.itertext()).strip()
                if len(t) > 80:
                    texts.append(t)

            # 收集标题
            if tag in ('title', 'sec-title', 'caption') or tag.endswith('}title'):
                t = ''.join(el.itertext()).strip()
                if t and len(t) > 10:
                    texts.append(t)

        full_text = ' '.join(texts)
        return full_text
    except Exception:
        return ""


def find_viruses_in_text(text):
    """在全文文本中查找数据库病毒"""
    text_lower = text.lower()
    found = set()

    for vname, master_id in VIRUS_DICT.items():
        if len(vname) < 8:
            continue
        if vname in text_lower:
            found.add(master_id)

    return found


def find_signal_matches(text):
    """查找证据信号"""
    text_lower = text.lower()
    results = {}

    results['diagnostic'] = [sig for sig in DIAG_SIGNALS if sig.lower() in text_lower]
    results['pathogenicity'] = [sig for sig in PATHOGEN_SIGNALS if sig.lower() in text_lower]
    results['temperature'] = [sig for sig in TEMPERATURE_SIGNALS if sig.lower() in text_lower]
    results['host_range'] = [sig for sig in HOST_SIGNALS if sig.lower() in text_lower]

    return results


def extract_all():
    con = sqlite3.connect(str(DB_PATH))
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    load_lookup_tables(con)
    print(f"加载病毒名: {len(VIRUS_DICT)}, 宿主名: {len(HOST_DICT)}")

    # 获取所有已下载但未提取evidence的文献
    to_process = cur.execute("""
        SELECT DISTINCT lfs.reference_id, lfs.pmid, lfs.doi, lfs.local_path,
               rl.title, rl.abstract
        FROM literature_fulltext_sources lfs
        JOIN ref_literatures rl ON lfs.reference_id = rl.reference_id
        WHERE lfs.status = 'downloaded'
        AND lfs.reference_id NOT IN (
            SELECT DISTINCT reference_id FROM evidence_records
            WHERE reference_id IS NOT NULL
            AND extraction_method = 'fulltext_parsed'
        )
        LIMIT 2000
    """).fetchall()

    print(f"待处理文献: {len(to_process)}")

    stats = {
        "processed": 0,
        "xml_parsed": 0,
        "new_evidence": 0,
        "viruses_found": Counter(),
        "signals_found": defaultdict(int),
        "skipped_no_text": 0,
    }

    for ref in to_process:
        ref_id = ref["reference_id"]
        pmid = ref["pmid"]
        title = ref["title"] or ""

        # 找到对应的XML文件
        full_text = ""
        xml_path = None

        # 按PMID找XML
        if pmid:
            candidates = list(XML_DIR.glob(f"*{pmid}*"))
            if not candidates:
                candidates = list(XML_DIR.glob(f"*PMC*{pmid}*"))
            if candidates:
                xml_path = candidates[0]
                full_text = extract_text_from_xml(xml_path)
                if full_text:
                    stats["xml_parsed"] += 1

        # 如果没XML, 使用title+abstract
        if not full_text:
            abstract = ref["abstract"] or ""
            full_text = title + " " + abstract
            if len(full_text.strip()) < 50:
                stats["skipped_no_text"] += 1
                continue

        # 查找病毒
        virus_ids = find_viruses_in_text(full_text)
        if not virus_ids:
            # 也检查标题
            virus_ids = find_viruses_in_text(title)

        # 查找信号
        signals = find_signal_matches(full_text)

        # 为每个找到的病毒创建evidence
        for master_id in virus_ids:
            stats["viruses_found"][master_id] += 1

            # 1. host_range
            if signals['host_range']:
                cur.execute("""
                    INSERT OR IGNORE INTO evidence_records
                    (evidence_type, virus_master_id, reference_id, claim,
                     evidence_strength, source_pmid, source_doi,
                     extraction_method, curation_status, observation_type)
                    VALUES (?, ?, ?, ?, 'low', ?, ?, 'fulltext_parsed', 'auto_imported', 'review')
                """, (
                    "host_range", master_id, ref_id,
                    f"Host-related terms found in fulltext: {', '.join(signals['host_range'][:5])}",
                    pmid, ref["doi"],
                ))
                stats["new_evidence"] += 1
                stats["signals_found"]["host_range"] += 1

            # 2. diagnostic
            if signals['diagnostic']:
                cur.execute("""
                    INSERT OR IGNORE INTO evidence_records
                    (evidence_type, virus_master_id, reference_id, claim,
                     evidence_strength, source_pmid, source_doi,
                     extraction_method, curation_status, observation_type)
                    VALUES (?, ?, ?, ?, 'low', ?, ?, 'fulltext_parsed', 'auto_imported', 'review')
                """, (
                    "diagnosis", master_id, ref_id,
                    f"Diagnostic methods found: {', '.join(signals['diagnostic'][:5])}",
                    pmid, ref["doi"],
                ))
                stats["new_evidence"] += 1
                stats["signals_found"]["diagnosis"] += 1

            # 3. pathogenicity/mortality
            if signals['pathogenicity']:
                cur.execute("""
                    INSERT OR IGNORE INTO evidence_records
                    (evidence_type, virus_master_id, reference_id, claim,
                     evidence_strength, source_pmid, source_doi,
                     extraction_method, curation_status, observation_type)
                    VALUES (?, ?, ?, ?, 'low', ?, ?, 'fulltext_parsed', 'auto_imported', 'review')
                """, (
                    "pathogenicity", master_id, ref_id,
                    f"Pathogenicity terms found: {', '.join(signals['pathogenicity'][:5])}",
                    pmid, ref["doi"],
                ))
                stats["new_evidence"] += 1
                stats["signals_found"]["pathogenicity"] += 1

            # 4. temperature
            if signals['temperature']:
                cur.execute("""
                    INSERT OR IGNORE INTO evidence_records
                    (evidence_type, virus_master_id, reference_id, claim,
                     evidence_strength, source_pmid, source_doi,
                     extraction_method, curation_status, observation_type)
                    VALUES (?, ?, ?, ?, 'low', ?, ?, 'fulltext_parsed', 'auto_imported', 'review')
                """, (
                    "temperature", master_id, ref_id,
                    f"Temperature data found: {', '.join(signals['temperature'][:5])}",
                    pmid, ref["doi"],
                ))
                stats["new_evidence"] += 1
                stats["signals_found"]["temperature"] += 1

        stats["processed"] += 1
        if stats["processed"] % 50 == 0:
            con.commit()
            print(f"  已处理: {stats['processed']}/{len(to_process)}, "
                  f"新增证据: {stats['new_evidence']}", end='\r')

    con.commit()

    # 输出统计
    print(f"\n\n{'=' * 60}")
    print("全文证据提取完成")
    print(f"{'=' * 60}")
    print(f"已处理文献: {stats['processed']}")
    print(f"解析XML: {stats['xml_parsed']}")
    print(f"跳过(无文本): {stats['skipped_no_text']}")
    print(f"新增证据记录: {stats['new_evidence']}")
    print(f"匹配病毒数: {len(stats['viruses_found'])}")

    print(f"\n按证据类型:")
    for sig, cnt in sorted(stats['signals_found'].items(), key=lambda x: -x[1]):
        print(f"  {sig}: {cnt}")

    # 被引用最多的病毒
    print(f"\n提取证据最多的病毒 (Top 20):")
    for i, (mid, cnt) in enumerate(stats['viruses_found'].most_common(20)):
        vname = cur.execute(
            "SELECT canonical_name FROM virus_master WHERE master_id = ?", (mid,)
        ).fetchone()
        name = vname[0] if vname else f"ID={mid}"
        print(f"  {name[:60]}: {cnt}")

    # 最终覆盖率
    total_v = cur.execute("SELECT COUNT(*) FROM virus_master").fetchone()[0]
    with_evidence = cur.execute(
        "SELECT COUNT(DISTINCT virus_master_id) FROM evidence_records WHERE virus_master_id IS NOT NULL"
    ).fetchone()[0]
    print(f"\n证据覆盖率: {with_evidence}/{total_v} = {with_evidence/total_v*100:.1f}%")

    con.close()

    # 保存日志
    stats_copy = {
        "timestamp": datetime.now().isoformat(),
        "processed": stats["processed"],
        "xml_parsed": stats["xml_parsed"],
        "new_evidence": stats["new_evidence"],
        "viruses_found": stats["viruses_found"].most_common(100),
        "signals_found": dict(stats["signals_found"]),
    }
    log_path = LOG_DIR / f"extraction_log_{int(datetime.now().timestamp())}.json"
    with open(log_path, 'w', encoding='utf-8') as f:
        json.dump(stats_copy, f, ensure_ascii=False, indent=2)
    print(f"\n日志: {log_path}")

    return stats


if __name__ == "__main__":
    extract_all()
