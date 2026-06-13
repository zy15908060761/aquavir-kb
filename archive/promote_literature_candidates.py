#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""智能提升 literature_evidence_candidates → evidence_records"""

import sqlite3
import re
from pathlib import Path
from collections import defaultdict

DB_PATH = Path(r"F:\甲壳动物数据库\crustacean_virus_core.db")

# 最小匹配词长度阈值 — 短词匹配容易误报
MIN_TERM_LENGTH = 8

# 已知的高置信度 virus_id -> reference_id 映射 (来自全网检索)
MANUAL_HIGH_CONFIDENCE = {
    # Shi et al. 2016 Nature PMID:27880757 → 23 viruses
    "27880757": [
        "Beihai crab virus", "Beihai shrimp virus", "Wenzhou shrimp virus",
        "Wenzhou crab virus", "Wenzhou Shrimp Virus 1", "Wenzhou Shrimp Virus 2",
        "Crab associated circular virus", "Chinese mitten crab virus",
    ],
    # Guo et al. 2025 Virology PMID:39556981 → 10 Qianjiang viruses
    "39556981": [
        "Qianjiang marna-like virus 130", "Qianjiang marna-like virus 137",
        "Qianjiang marna-like virus 147", "Qianjiang marna-like virus 156",
        "Qianjiang marna-like virus 174", "Qianjiang marna-like virus 185",
        "Qianjiang marna-like virus 187", "Qianjiang marna-like virus 222",
        "Qianjiang picorna-like virus 98", "Qianjiang picorna-like virus 109",
    ],
    # Dong et al. 2024 mSystems PMID:39329483
    "39329483": [
        "Macrobrachium rosenbergii virus 10",
    ],
    # Hooper et al. 2020 PMID:33023199 — MrGV
    "33023199": ["Macrobrachium rosenbergii Golda virus"],
    # Guo et al. 2023 PMID:37358426 — Chinese mitten crab
    "37358426": ["Chinese mitten crab virus"],
}


def promote_candidates():
    con = sqlite3.connect(str(DB_PATH))
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    stats = {
        "promoted": 0,
        "skipped_already_exists": 0,
        "skipped_low_confidence": 0,
        "by_evidence_type": defaultdict(int),
        "viruses_promoted": set(),
    }

    # 1. 先处理手动高置信度映射 (来自全网检索)
    print("=== Phase 1: 手动高置信度候选提升 ===")
    for pmid, virus_names in MANUAL_HIGH_CONFIDENCE.items():
        # 找 reference_id
        ref = cur.execute(
            "SELECT reference_id, pmid, title FROM ref_literatures WHERE pmid = ?",
            (pmid,)
        ).fetchone()
        if not ref:
            print(f"  PMID {pmid}: 数据库中无此文献")
            continue

        ref_id = ref["reference_id"]
        for vname in virus_names:
            virus = cur.execute(
                "SELECT master_id, canonical_name FROM virus_master WHERE canonical_name = ?",
                (vname,)
            ).fetchone()
            if not virus:
                print(f"  PMID {pmid} → {vname}: 数据库中无此病毒")
                continue

            master_id = virus["master_id"]

            # 检查是否已有 evidence_record
            existing = cur.execute("""
                SELECT evidence_id FROM evidence_records
                WHERE virus_master_id = ? AND reference_id = ?
            """, (master_id, ref_id)).fetchone()

            if existing:
                stats["skipped_already_exists"] += 1
                continue

            # 插入 evidence_record
            cur.execute("""
                INSERT INTO evidence_records
                (evidence_type, virus_master_id, reference_id, claim,
                 evidence_strength, source_pmid, source_doi, extraction_method,
                 curation_status, observation_type)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'auto_imported', 'review')
            """, (
                "host_range",
                master_id,
                ref_id,
                f"Discovered/characterized in {ref['title'][:200]}",
                "medium",
                pmid,
                None,
                "literature_text_mine",
            ))

            # 标记候选为 promoted
            cur.execute("""
                UPDATE literature_evidence_candidates
                SET curation_status = 'promoted'
                WHERE master_id = ? AND reference_id = ?
            """, (master_id, ref_id))

            stats["promoted"] += 1
            stats["viruses_promoted"].add(master_id)
            stats["by_evidence_type"]["host_range"] += 1

    print(f"  手动提升: {stats['promoted']} 条")

    # 2. 自动提升 text-mine 高置信度候选
    print("\n=== Phase 2: 文本挖掘候选自动提升 ===")
    auto_promoted = 0

    # 只提升满足以下条件的候选:
    # - 病毒名称在摘要中出现 (claim_hint 包含 'Abstract mentions')
    # - 病毒名长度 >= MIN_TERM_LENGTH (避免短词误报)
    # - 不是 SARS-CoV-2 (污染物)
    candidates = cur.execute("""
        SELECT lec.candidate_id, lec.master_id, lec.reference_id, lec.pmid, lec.doi,
               lec.claim_hint, lec.evidence_scope, lec.title,
               vm.canonical_name as virus_name
        FROM literature_evidence_candidates lec
        JOIN virus_master vm ON lec.master_id = vm.master_id
        WHERE lec.curation_status = 'needs_review'
          AND lec.claim_hint LIKE '%Abstract mentions%'
          AND vm.canonical_name != 'Severe acute respiratory syndrome coronavirus 2'
        ORDER BY lec.relevance_score DESC
    """).fetchall()

    # 去重: 每个 (master_id, reference_id) 只升一个
    seen_pairs = set()
    count_by_virus = defaultdict(int)

    for cand in candidates:
        master_id = cand["master_id"]
        ref_id = cand["reference_id"]
        vname = cand["virus_name"]
        claim = cand["claim_hint"]

        pair = (master_id, ref_id)
        if pair in seen_pairs:
            continue

        # 提取匹配到的词
        match = re.search(r"Abstract mentions '([^']+)'", claim)
        matched_term = match.group(1) if match else ""

        # 质量控制: 跳过低质量匹配
        if len(matched_term) < MIN_TERM_LENGTH:
            stats["skipped_low_confidence"] += 1
            continue

        # 跳过太通用的词
        if matched_term.lower() in {"white spot", "infection", "mortality", "pathogen",
                                      "disease", "shrimp", "crab", "prawn", "crayfish",
                                      "aquaculture", "crustacean", "invertebrate"}:
            stats["skipped_low_confidence"] += 1
            continue

        # 检查是否已有 evidence_record
        existing = cur.execute("""
            SELECT evidence_id FROM evidence_records
            WHERE virus_master_id = ? AND reference_id = ?
        """, (master_id, ref_id)).fetchone()

        if existing:
            stats["skipped_already_exists"] += 1
            seen_pairs.add(pair)
            continue

        # 限制每个病毒最多提升50篇文献
        if count_by_virus[master_id] >= 50:
            continue

        # 提升
        try:
            cur.execute("""
                INSERT INTO evidence_records
                (evidence_type, virus_master_id, reference_id, claim,
                 evidence_strength, source_pmid, source_doi, extraction_method,
                 curation_status, observation_type)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'auto_imported', 'review')
            """, (
                cand["evidence_scope"] or "host_range",
                master_id,
                ref_id,
                f"Abstract mentions '{matched_term}': {(cand['title'] or '')[:150]}",
                "low",  # 自动提升的用 low strength
                cand["pmid"],
                cand["doi"],
                "literature_text_mine",
            ))

            cur.execute("""
                UPDATE literature_evidence_candidates
                SET curation_status = 'promoted'
                WHERE candidate_id = ?
            """, (cand["candidate_id"],))

            auto_promoted += 1
            stats["promoted"] += 1
            stats["viruses_promoted"].add(master_id)
            stats["by_evidence_type"][cand["evidence_scope"] or "host_range"] += 1
            count_by_virus[master_id] += 1
            seen_pairs.add(pair)

        except Exception:
            pass

    print(f"  自动提升: {auto_promoted} 条")

    con.commit()

    # 输出统计
    print(f"\n{'=' * 60}")
    print(f"提升完成")
    print(f"{'=' * 60}")
    print(f"总提升 evidence_records: {stats['promoted']}")
    print(f"  其中手动高置信: {stats['promoted'] - auto_promoted}")
    print(f"  其中自动文本挖掘: {auto_promoted}")
    print(f"跳过(已有): {stats['skipped_already_exists']}")
    print(f"跳过(低质量): {stats['skipped_low_confidence']}")
    print(f"覆盖病毒数: {len(stats['viruses_promoted'])}")

    print(f"\n按 evidence_type 分布:")
    for etype, cnt in sorted(stats["by_evidence_type"].items(), key=lambda x: -x[1]):
        print(f"  {etype}: {cnt}")

    # 检查最终覆盖率
    total_viruses = cur.execute("SELECT COUNT(*) FROM virus_master").fetchone()[0]
    viruses_with_evidence = cur.execute(
        "SELECT COUNT(DISTINCT virus_master_id) FROM evidence_records WHERE virus_master_id IS NOT NULL"
    ).fetchone()[0]
    print(f"\n最终证据覆盖率: {viruses_with_evidence}/{total_viruses} = {viruses_with_evidence/total_viruses*100:.1f}%")

    # 仍未覆盖的病毒
    uncovered = cur.execute("""
        SELECT canonical_name FROM virus_master vm
        WHERE vm.master_id NOT IN (
            SELECT DISTINCT virus_master_id FROM evidence_records WHERE virus_master_id IS NOT NULL
        )
        AND vm.master_id NOT IN (
            SELECT DISTINCT master_id FROM literature_evidence_candidates WHERE master_id IS NOT NULL
        )
        ORDER BY vm.master_id
    """).fetchall()
    print(f"\n完全无文献证据的病毒: {len(uncovered)}")
    for row in uncovered[:20]:
        print(f"  - {row[0]}")

    con.close()
    return stats


if __name__ == "__main__":
    promote_candidates()
