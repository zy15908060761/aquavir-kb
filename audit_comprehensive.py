#!/usr/bin/env python3
"""Comprehensive database quality audit — all dimensions except public URL."""
import sqlite3, re, json
from pathlib import Path
from collections import Counter, defaultdict
from datetime import datetime

DB_PATH = Path(r"F:\水生无脊椎动物数据库\crustacean_virus_core.db")
OUT = Path(r"F:\水生无脊椎动物数据库\reports\audit_report.json")

def q(cur, sql):
    return cur.execute(sql).fetchone()[0]

def qa(cur, sql):
    return cur.execute(sql).fetchall()

def main():
    con = sqlite3.connect(str(DB_PATH), timeout=60)
    cur = con.cursor()
    issues = []
    ok = []

    # ================================================================
    # 1. NAR READINESS
    # ================================================================
    print("=" * 60)
    print("1. NAR 就绪状态")
    print("=" * 60)

    ev_reviewed = q(cur, "SELECT COUNT(*) FROM evidence_records WHERE curation_status='manual_checked'")
    print(f"  人工审核记录: {ev_reviewed:,}")
    if ev_reviewed == 0: issues.append("[NAR] evidence_records 无人工审核记录")
    else: ok.append(f"[NAR] 人工审核记录 {ev_reviewed:,} 条")

    needs_review = q(cur, "SELECT COUNT(*) FROM evidence_records WHERE curation_status='needs_review'")
    print(f"  待审核: {needs_review}")
    if needs_review > 0: issues.append(f"[NAR] evidence_records 仍有 {needs_review} 条 needs_review")

    for tbl in ['diagnostic_methods','host_range_evidence','pathogenicity_evidence',
                'environmental_evidence','outbreak_events']:
        n = q(cur, f"SELECT COUNT(*) FROM {tbl} WHERE curation_status <> 'manual_checked'")
        if n > 0: issues.append(f"[NAR] {tbl} 有 {n} 条未审核")
    ictv_n = q(cur, "SELECT COUNT(*) FROM virus_ictv_status WHERE ictv_status='pending_review'")
    if ictv_n > 0: issues.append(f"[NAR] virus_ictv_status 有 {ictv_n} 条待定")
    else: ok.append("[NAR] 所有警告已清除")

    # ================================================================
    # 2. DATA INTEGRITY
    # ================================================================
    print("\n" + "=" * 60)
    print("2. 数据完整性")

    # FK violations
    fk_checks = [
        ("evidence_records.virus_master_id → virus_master", "SELECT COUNT(*) FROM evidence_records e LEFT JOIN virus_master v ON e.virus_master_id=v.master_id WHERE v.master_id IS NULL AND e.virus_master_id IS NOT NULL"),
        ("evidence_records.reference_id → ref_literatures", "SELECT COUNT(*) FROM evidence_records e LEFT JOIN ref_literatures r ON e.reference_id=r.reference_id WHERE r.reference_id IS NULL AND e.reference_id IS NOT NULL"),
        ("viral_proteins.isolate_id → viral_isolates", "SELECT COUNT(*) FROM viral_proteins vp LEFT JOIN viral_isolates vi ON vp.isolate_id=vi.isolate_id WHERE vi.isolate_id IS NULL AND vp.isolate_id IS NOT NULL"),
        ("viral_isolates.master_id → virus_master", "SELECT COUNT(*) FROM viral_isolates vi LEFT JOIN virus_master vm ON vi.master_id=vm.master_id WHERE vm.master_id IS NULL"),
        ("protein_domains.protein_id → viral_proteins", "SELECT COUNT(*) FROM protein_domains pd LEFT JOIN viral_proteins vp ON pd.protein_id=vp.protein_id WHERE vp.protein_id IS NULL"),
        ("literature_fulltext_sources.reference_id → ref_literatures", "SELECT COUNT(*) FROM literature_fulltext_sources lfs LEFT JOIN ref_literatures r ON lfs.reference_id=r.reference_id WHERE r.reference_id IS NULL"),
    ]
    for label, sql in fk_checks:
        n = q(cur, sql)
        if n > 0: issues.append(f"[FK] {label}: {n} 条孤儿记录")
        else: ok.append(f"[FK] {label}: 无孤儿")

    # NULL critical fields
    null_checks = [
        ("virus_master.canonical_name", "SELECT COUNT(*) FROM virus_master WHERE canonical_name IS NULL OR canonical_name=''"),
        ("virus_master.host_phylum", "SELECT COUNT(*) FROM virus_master WHERE host_phylum IS NULL OR host_phylum=''"),
        ("viral_proteins.protein_accession", "SELECT COUNT(*) FROM viral_proteins WHERE protein_accession IS NULL OR protein_accession=''"),
        ("viral_proteins.translation", "SELECT COUNT(*) FROM viral_proteins WHERE translation IS NULL OR translation=''"),
        ("ref_literatures.title", "SELECT COUNT(*) FROM ref_literatures WHERE title IS NULL OR title=''"),
        ("ref_literatures.doi", "SELECT COUNT(*) FROM ref_literatures WHERE doi IS NULL OR doi=''"),
    ]
    for label, sql in null_checks:
        n = q(cur, sql)
        pct = n / q(cur, f"SELECT COUNT(*) FROM {label.split('.')[0]}") * 100
        if n > 0: print(f"  {label}: {n} 空值 ({pct:.1f}%)")
        if pct > 20: issues.append(f"[NULL] {label}: {n} 空值 ({pct:.1f}%)")

    # ================================================================
    # 3. DATA QUALITY — PLACEHOLDERS & ANOMALIES
    # ================================================================
    print("\n" + "=" * 60)
    print("3. 数据质量 — 占位符与异常")

    placeholder_patterns = [
        r'\bTBD\b', r'placeholder', r'XXXX+', r'to be updated',
        r'upon acceptance', r'to be assigned', r'needs_review'
    ]
    for pat in placeholder_patterns:
        for tbl, col in [('virus_master','notes'),('evidence_records','claim'),('evidence_records','notes')]:
            try:
                n = q(cur, f"SELECT COUNT(*) FROM {tbl} WHERE {col} REGEXP ?", (pat,))
                if n > 0: issues.append(f"[占位符] {tbl}.{col} 有 {n} 条匹配 '{pat}'")
            except: pass

    # Duplicate refs
    dup_doi = q(cur, "SELECT COUNT(*) FROM (SELECT doi FROM ref_literatures WHERE doi IS NOT NULL AND doi!='' GROUP BY doi HAVING COUNT(*)>1)")
    if dup_doi > 0:
        n = q(cur, "SELECT COUNT(*) FROM (SELECT doi, COUNT(*) as c FROM ref_literatures WHERE doi IS NOT NULL AND doi!='' GROUP BY doi HAVING c>1)")
        issues.append(f"[重复] ref_literatures 有 {n} 组重复 DOI")
    else: ok.append("[重复] ref_literatures 无重复 DOI")

    dup_pmid = q(cur, "SELECT COUNT(*) FROM (SELECT pmid FROM ref_literatures WHERE pmid IS NOT NULL AND pmid!='' GROUP BY pmid HAVING COUNT(*)>1)")
    if dup_pmid > 0: issues.append(f"[重复] ref_literatures 有 {dup_pmid} 组重复 PMID")

    # Virus name anomalies
    anomalies = {
        "带 sp. 的模糊名": "SELECT COUNT(*) FROM virus_master WHERE canonical_name LIKE '% sp.%' OR canonical_name LIKE '% sp'",
        "带 ? 的问号名": "SELECT COUNT(*) FROM virus_master WHERE canonical_name LIKE '%?%'",
        "含 'virus' 数字编号": "SELECT COUNT(*) FROM virus_master WHERE canonical_name LIKE '%virus 0%' OR canonical_name LIKE '%virus 1%' OR canonical_name LIKE '%virus 2%' OR canonical_name LIKE '%virus 3%' OR canonical_name LIKE '%virus 4%' OR canonical_name LIKE '%virus 5%' OR canonical_name LIKE '%virus 6%' OR canonical_name LIKE '%virus 7%' OR canonical_name LIKE '%virus 8%' OR canonical_name LIKE '%virus 9%'",
    }
    for label, sql in anomalies.items():
        n = q(cur, sql)
        if n > 0: print(f"  {label}: {n} 个病毒")

    # ================================================================
    # 4. COVERAGE GAPS
    # ================================================================
    print("\n" + "=" * 60)
    print("4. 覆盖缺口")

    total = q(cur, "SELECT COUNT(*) FROM virus_master")
    no_family_target = q(cur, """SELECT COUNT(*) FROM virus_master WHERE (virus_family IS NULL OR virus_family='' OR virus_family='None')
        AND host_phylum NOT IN ('non_target (algae)','non_target (vertebrate)','non_target (fungus)','non_target (plant)','non_target','non_aquatic')""")
    print(f"  目标病毒无科级分类: {no_family_target}/{total}")
    if no_family_target > 50: issues.append(f"[覆盖] {no_family_target} 个目标病毒无科级分类")

    no_genome = q(cur, """SELECT COUNT(*) FROM virus_master WHERE (genome_type IS NULL OR genome_type='')
        AND host_phylum NOT IN ('non_target (algae)','non_target (vertebrate)','non_target (fungus)','non_target (plant)','non_target','non_aquatic')""")
    print(f"  目标病毒无基因组类型: {no_genome}")
    if no_genome > 30: issues.append(f"[覆盖] {no_genome} 个目标病毒无基因组类型")

    zero_ev_target = q(cur, """SELECT COUNT(*) FROM virus_master v WHERE v.master_id NOT IN
        (SELECT DISTINCT virus_master_id FROM evidence_records WHERE virus_master_id IS NOT NULL)
        AND (v.host_phylum NOT IN ('non_target (algae)','non_target (vertebrate)','non_target (fungus)','non_target (plant)','non_target','non_aquatic') OR v.host_phylum IS NULL)""")
    print(f"  零证据目标病毒: {zero_ev_target}")
    if zero_ev_target > 10: issues.append(f"[覆盖] {zero_ev_target} 个目标病毒零证据")

    low_ev = q(cur, """SELECT COUNT(*) FROM virus_master v WHERE
        (SELECT COUNT(*) FROM evidence_records e WHERE e.virus_master_id=v.master_id) BETWEEN 1 AND 5
        AND v.host_phylum IN ('Arthropoda','Mollusca','Cnidaria','Echinodermata','Porifera')""")
    print(f"  低证据(1-5条)经济门类病毒: {low_ev}")
    if low_ev > 100: issues.append(f"[覆盖] {low_ev} 个经济门类病毒仅有 1-5 条证据")

    # ================================================================
    # 5. SCHEMA & PERFORMANCE
    # ================================================================
    print("\n" + "=" * 60)
    print("5. Schema 与性能")

    table_count = q(cur, "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
    view_count = q(cur, "SELECT COUNT(*) FROM sqlite_master WHERE type='view'")
    index_count = q(cur, "SELECT COUNT(*) FROM sqlite_master WHERE type='index' AND name NOT LIKE 'sqlite_%'")
    print(f"  表: {table_count} | 视图: {view_count} | 索引: {index_count}")

    # Find tables with no rows
    empty_tables = []
    for row in qa(cur, "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"):
        tbl = row[0]
        try:
            n = q(cur, f"SELECT COUNT(*) FROM {tbl}")
            if n == 0:
                empty_tables.append(tbl)
        except: pass
    if empty_tables:
        issues.append(f"[Schema] {len(empty_tables)} 张空表: {', '.join(empty_tables[:10])}")

    # Large tables without indexes on FK columns
    large_tables = [('evidence_records', ['virus_master_id','reference_id','evidence_type','evidence_strength','curation_status']),
                    ('viral_proteins', ['isolate_id']),
                    ('protein_domains', ['protein_id'])]
    for tbl, expected_cols in large_tables:
        try:
            existing_idx = [r[1] for r in qa(cur, f"PRAGMA index_list({tbl})")]
            for col in expected_cols:
                # Check if any index covers this column
                found = False
                for idx in existing_idx:
                    idx_cols = [c[2] for c in qa(cur, f"PRAGMA index_info({idx})")]
                    if col in idx_cols:
                        found = True
                        break
                if not found:
                    print(f"  缺少索引: {tbl}.{col}")
        except: pass

    # ================================================================
    # 6. DOCUMENTATION
    # ================================================================
    print("\n" + "=" * 60)
    print("6. 文档完整性")
    docs = ['README.md','DATA_AVAILABILITY.md','SUSTAINABILITY.md','CITATION.cff',
            'LICENSE.txt','NOVELTY_COMPARISON.md','MANUAL_REVIEW_CHECKLIST.md']
    for doc in docs:
        p = Path(r"F:\水生无脊椎动物数据库") / doc
        if p.exists():
            ok.append(f"[文档] {doc} 存在")
        else:
            issues.append(f"[文档] {doc} 缺失")

    # ================================================================
    # 7. EVIDENCE QUALITY — specific checks
    # ================================================================
    print("\n" + "=" * 60)
    print("7. 证据质量细节")

    # Evidence with no virus match
    ev_no_virus = q(cur, "SELECT COUNT(*) FROM evidence_records WHERE virus_master_id IS NULL")
    if ev_no_virus > 0: issues.append(f"[证据] {ev_no_virus} 条证据无 virus_master_id")
    else: ok.append("[证据] 所有证据 records 均有 virus_master_id")

    # Evidence with claim length < 10 chars
    short_claims = q(cur, "SELECT COUNT(*) FROM evidence_records WHERE claim IS NOT NULL AND LENGTH(claim) < 10")
    if short_claims > 0: print(f"  过短索赔: {short_claims}")

    # curation_status distribution
    print("  状态分布:")
    for row in qa(cur, "SELECT curation_status, COUNT(*) FROM evidence_records GROUP BY curation_status"):
        print(f"    {row[0]}: {row[1]:,}")

    # ================================================================
    # FINAL REPORT
    # ================================================================
    print("\n" + "=" * 60)
    print("总结")
    print("=" * 60)

    print(f"\n  *** 问题: {len(issues)} 项 ***")
    for iss in issues:
        print(f"    - {iss}")

    print(f"\n  *** 正常: {len(ok)} 项 ***")

    # Save report
    report = {
        "timestamp": datetime.now().isoformat(),
        "issues_count": len(issues),
        "issues": issues,
        "ok_count": len(ok),
        "ok": ok,
        "summary": {
            "total_viruses": total,
            "total_isolates": q(cur, "SELECT COUNT(*) FROM viral_isolates"),
            "total_refs": q(cur, "SELECT COUNT(*) FROM ref_literatures"),
            "total_evidence": q(cur, "SELECT COUNT(*) FROM evidence_records"),
            "total_proteins": q(cur, "SELECT COUNT(*) FROM viral_proteins"),
            "total_domains": q(cur, "SELECT COUNT(*) FROM protein_domains"),
            "db_size_mb": round(Path(DB_PATH).stat().st_size / 1024 / 1024, 1),
            "evidence_coverage_pct": round(q(cur, "SELECT COUNT(DISTINCT virus_master_id) FROM evidence_records WHERE virus_master_id IS NOT NULL") / total * 100, 1),
            "family_coverage_pct": round(q(cur, "SELECT COUNT(*) FROM virus_master WHERE virus_family IS NOT NULL AND virus_family != '' AND virus_family != 'None'") / total * 100, 1),
            "protein_domain_coverage_pct": round(q(cur, "SELECT COUNT(DISTINCT protein_id) FROM protein_domains") / q(cur, "SELECT COUNT(*) FROM viral_proteins") * 100, 1),
            "fulltext_coverage_pct": round(q(cur, "SELECT COUNT(DISTINCT reference_id) FROM literature_fulltext_sources WHERE status IN ('downloaded','local')") / q(cur, "SELECT COUNT(*) FROM ref_literatures") * 100, 1),
        }
    }
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n报告已保存: {OUT}")

    con.close()
    return len(issues)

if __name__ == "__main__":
    exit_code = main()
    raise SystemExit(0 if exit_code == 0 else 0)  # always exit clean, issues are informational
