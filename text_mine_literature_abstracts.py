#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文本挖掘: 从7,512条参考文献摘要中自动匹配病毒名称
创建 literature_evidence_candidates 关联文献与病毒

策略:
1. 对每个病毒，用 canonical_name + abbreviations + chinese_name 搜索摘要
2. 用正则确保精确匹配（避免 "virus" 匹配所有）
3. 为匹配的文献创建 evidence_candidates
4. 去重: 同一个 virus-reference 对只创建一个候选
"""

import sqlite3
import re
import json
from datetime import datetime
from pathlib import Path
from collections import defaultdict

DB_PATH = Path(r"F:\甲壳动物数据库\crustacean_virus_core.db")
OUT_DIR = Path(r"F:\甲壳动物数据库\downloads\literature_import_20260516")
OUT_DIR.mkdir(parents=True, exist_ok=True)

# 短词黑名单: 太通用的词不要单独搜索
STOP_WORDS = {
    "virus", "viral", "virome", "viruses", "rna", "dna", "ssrna", "dsrna",
    "ssdna", "dsdna", "positive", "negative", "stranded", "unclassified",
    "unknown", "crustacean", "shrimp", "crab", "prawn", "crayfish",
    "associated", "related", "novel", "new", "putative", "like",
    "family", "genus", "species", "order", "isolate", "strain",
    "invertebrate", "aquatic", "marine", "freshwater",
}

def build_search_terms(virus_row):
    """为每个病毒构建搜索词列表"""
    terms = []

    canonical = virus_row["canonical_name"] or ""
    abbrev = virus_row["abbreviations"] or ""
    chinese = virus_row["chinese_name"] or ""

    # 1. canonical name 本身
    if canonical:
        terms.append(canonical)

    # 2. 拆解 canonical name 中的重要词 (至少8个字符的名词短语)
    parts = re.split(r'[,\s/;]+', canonical)
    for part in parts:
        part = part.strip().strip('()[]')
        if len(part) >= 8 and part.lower() not in STOP_WORDS:
            # 检查不是纯数字、不是纯generic
            if not re.match(r'^[\d.]+$', part) and 'unclassified' not in part.lower():
                terms.append(part)

    # 3. 缩略词 (如 WSSV, IHHNV, DIV1)
    if abbrev:
        for a in re.split(r'[,;\s/]+', abbrev):
            a = a.strip()
            if len(a) >= 3 and a.lower() not in STOP_WORDS:
                terms.append(a)

    # 4. 中文名
    if chinese:
        terms.append(chinese)

    # 去重并排序(长的优先, 长词匹配更精确)
    terms = sorted(set(terms), key=lambda x: -len(x))

    # 过滤: 至少4个字符, 不能太通用
    filtered = []
    for t in terms:
        if len(t) < 4:
            continue
        if t.lower() in STOP_WORDS:
            continue
        # 如果只是一个字母+数字(如S1, VP12)跳过
        if re.match(r'^[A-Za-z]\d+$', t):
            continue
        filtered.append(t)

    return filtered[:20]  # 最多20个搜索词


def text_mine_abstracts():
    con = sqlite3.connect(str(DB_PATH))
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    # 获取所有病毒及其搜索词
    viruses = cur.execute("""
        SELECT master_id, canonical_name, abbreviations, chinese_name,
               virus_family, virus_genus
        FROM virus_master
        ORDER BY master_id
    """).fetchall()

    print(f"总病毒数: {len(viruses)}")

    # 获取所有有摘要的参考文献
    refs = cur.execute("""
        SELECT reference_id, pmid, doi, title, abstract, authors, journal, year
        FROM ref_literatures
        WHERE abstract IS NOT NULL AND abstract != ''
        ORDER BY reference_id
    """).fetchall()

    print(f"有摘要的参考文献: {len(refs)}")

    # 统计
    stats = {
        "total_viruses": len(viruses),
        "total_refs_with_abstract": len(refs),
        "new_candidates": 0,
        "skipped_existing": 0,
        "viruses_matched": set(),
        "refs_matched": set(),
        "virus_match_counts": defaultdict(int),
        "no_terms_viruses": [],
    }

    # 为每个病毒建立搜索词
    virus_terms = {}
    for v in viruses:
        terms = build_search_terms(v)
        if terms:
            virus_terms[v["master_id"]] = {
                "name": v["canonical_name"],
                "terms": terms,
                "family": v["virus_family"] or "",
                "genus": v["virus_genus"] or "",
            }
        else:
            stats["no_terms_viruses"].append(v["canonical_name"])

    print(f"有搜索词的病毒: {len(virus_terms)}")

    # 构建已存在的 (master_id, reference_id) 去重集合
    existing_pairs = set()
    for row in cur.execute("""
        SELECT master_id, reference_id FROM literature_evidence_candidates
        WHERE reference_id IS NOT NULL AND master_id IS NOT NULL
    """):
        existing_pairs.add((row[0], row[1]))

    # 也为 evidence_records 构建去重
    for row in cur.execute("""
        SELECT virus_master_id, reference_id FROM evidence_records
        WHERE reference_id IS NOT NULL AND virus_master_id IS NOT NULL
    """):
        existing_pairs.add((row[0], row[1]))

    print(f"已有 (virus, ref) 对: {len(existing_pairs)}")

    # 开始匹配
    batch_size = 500
    insert_batch = []
    total_checked = 0

    for ref in refs:
        ref_id = ref["reference_id"]
        # 合并 title + abstract 用于搜索
        text = (ref["title"] or "") + " " + (ref["abstract"] or "")
        text_lower = text.lower()

        # 对每个病毒检查匹配
        for master_id, vinfo in virus_terms.items():
            if (master_id, ref_id) in existing_pairs:
                continue

            matched_term = None
            for term in vinfo["terms"]:
                # 用大小写不敏感搜索
                if term.lower() in text_lower:
                    matched_term = term
                    break

            if matched_term:
                # 创建候选
                source_key = f"textmine_{master_id}_{ref_id}"
                insert_batch.append({
                    "source_key": source_key,
                    "target_virus": vinfo["name"],
                    "master_id": master_id,
                    "reference_id": ref_id,
                    "title": ref["title"],
                    "authors": ref["authors"],
                    "journal": ref["journal"],
                    "year": ref["year"],
                    "doi": ref["doi"],
                    "pmid": ref["pmid"],
                    "evidence_scope": "host_range",
                    "claim_hint": f"Abstract mentions '{matched_term}'. Auto-detected via text mining.",
                    "relevance_score": 0.6,
                    "abstract": (ref["abstract"] or "")[:2000],
                })

                stats["viruses_matched"].add(master_id)
                stats["refs_matched"].add(ref_id)
                stats["virus_match_counts"][master_id] += 1

        total_checked += 1
        if total_checked % 500 == 0:
            print(f"  已处理: {total_checked}/{len(refs)} 篇文献, 已匹配: {len(insert_batch)} 条候选")

        # 批量插入
        if len(insert_batch) >= batch_size:
            _insert_batch(cur, insert_batch)
            stats["new_candidates"] += len(insert_batch)
            insert_batch = []

    # 插入剩余
    if insert_batch:
        _insert_batch(cur, insert_batch)
        stats["new_candidates"] += len(insert_batch)

    con.commit()

    # 输出统计
    print()
    print("=" * 60)
    print("文本挖掘完成")
    print("=" * 60)
    print(f"总病毒数: {stats['total_viruses']}")
    print(f"有搜索词的病毒: {len(virus_terms)}")
    print(f"无搜索词的病毒: {len(stats['no_terms_viruses'])}")
    print(f"有摘要的文献: {stats['total_refs_with_abstract']}")
    print(f"新增候选证据: {stats['new_candidates']}")
    print(f"匹配到的病毒: {len(stats['viruses_matched'])}")
    print(f"匹配到的文献: {len(stats['refs_matched'])}")

    # 匹配最多的病毒 (Top 30)
    print(f"\n--- 匹配文献最多的病毒 (Top 30) ---")
    top_viruses = sorted(stats["virus_match_counts"].items(), key=lambda x: -x[1])
    for master_id, cnt in top_viruses[:30]:
        vname = virus_terms[master_id]["name"] if master_id in virus_terms else "???"
        print(f"  {vname[:70]}: {cnt} 篇文献")

    # 未匹配到的病毒
    unmatched = set(virus_terms.keys()) - stats["viruses_matched"]
    if unmatched:
        print(f"\n--- 未匹配到任何文献的病毒 ({len(unmatched)}) ---")
        for mid in list(unmatched)[:30]:
            print(f"  - {virus_terms[mid]['name']}")

    # 保存报告
    report = {
        "timestamp": datetime.now().isoformat(),
        "total_viruses": stats["total_viruses"],
        "viruses_with_terms": len(virus_terms),
        "viruses_matched": len(stats["viruses_matched"]),
        "viruses_unmatched": len(unmatched),
        "refs_matched": len(stats["refs_matched"]),
        "new_candidates": stats["new_candidates"],
        "top_matched_viruses": [
            {"master_id": mid, "name": virus_terms[mid]["name"], "count": cnt}
            for mid, cnt in top_viruses[:50]
        ],
    }
    report_path = OUT_DIR / "text_mine_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n报告已保存: {report_path}")

    con.close()
    return stats


def _insert_batch(cur, batch):
    """批量插入 literature_evidence_candidates"""
    for item in batch:
        try:
            cur.execute("""
                INSERT OR IGNORE INTO literature_evidence_candidates
                (source_key, target_virus, master_id, reference_id, title, authors,
                 journal, year, doi, pmid, evidence_scope, claim_hint, relevance_score,
                 abstract, curation_status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'needs_review')
            """, (
                item["source_key"],
                item["target_virus"],
                item["master_id"],
                item["reference_id"],
                item["title"],
                item["authors"],
                item["journal"],
                item["year"],
                item["doi"],
                item["pmid"],
                item["evidence_scope"],
                item["claim_hint"],
                item["relevance_score"],
                item["abstract"],
            ))
        except Exception:
            pass  # 跳过重复


if __name__ == "__main__":
    text_mine_abstracts()
