#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
一键导入水生无脊椎动物病毒文献数据到 crustacean_virus_core.db
运行方式: python _直接导入全部数据.py
"""

import csv
import sqlite3
from pathlib import Path
from collections import defaultdict

DB_PATH = Path(r"F:\甲壳动物数据库\crustacean_virus_core.db")
IMPORT_DIR = Path(r"F:\甲壳动物数据库\import_ready")

def get_conn():
    conn = sqlite3.connect(str(DB_PATH), timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn

def import_references():
    """导入文献"""
    print("[1/4] 导入 ref_literatures ...")
    conn = get_conn()
    cur = conn.cursor()
    
    path = IMPORT_DIR / "01_ref_literatures.tsv"
    with path.open("r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f, delimiter="\t")
        rows = list(reader)
    
    inserted = 0
    skipped = 0
    for row in rows:
        try:
            cur.execute("""
                INSERT OR IGNORE INTO ref_literatures (pmid, title, authors, journal, year, doi, abstract, keywords)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                row.get("pmid"), row.get("title"), row.get("authors"),
                row.get("journal"), row.get("year"), row.get("doi"),
                row.get("abstract"), row.get("keywords")
            ))
            if cur.rowcount > 0:
                inserted += 1
            else:
                skipped += 1
        except Exception as e:
            print(f"  跳过错误行 PMID={row.get('pmid')}: {e}")
    
    conn.commit()
    conn.close()
    print(f"  完成: 新增 {inserted} 条, 跳过重复/错误 {skipped} 条")
    return inserted

def import_known_virus_associations():
    """导入已知病毒的高质量关联到病毒主表和感染记录"""
    print("[2/4] 导入已知病毒的高质量关联 ...")
    conn = get_conn()
    cur = conn.cursor()
    
    path = IMPORT_DIR / "03_high_quality_associations.tsv"
    with path.open("r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f, delimiter="\t")
        rows = list(reader)
    
    # 只导入已知病毒（virus_abbr非空）
    known_rows = [r for r in rows if r.get("virus_abbr", "").strip()]
    
    virus_inserted = 0
    host_inserted = 0
    infection_inserted = 0
    
    for row in known_rows:
        virus_name = row.get("virus_name", "").strip()
        abbr = row.get("virus_abbr", "").strip()
        family = row.get("virus_family", "").strip()
        genus = row.get("virus_genus", "").strip()
        phylum = row.get("host_phylum", "").strip()
        cls = row.get("host_class", "").strip()
        common_name = row.get("host_common_name", "").strip()
        assoc_method = row.get("host_association_method", "co_occurrence_metagenomic")
        discovery = row.get("discovery_context", "metagenomic_environmental")
        
        if not virus_name or not phylum:
            continue
        
        # 1. 插入/更新 virus_master
        cur.execute("SELECT master_id FROM virus_master WHERE canonical_name = ?", (virus_name,))
        existing = cur.fetchone()
        if not existing:
            try:
                cur.execute("""
                    INSERT INTO virus_master (canonical_name, abbreviations, virus_family, virus_genus, is_crustacean_virus, host_phylum, discovery_context)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (virus_name, abbr, family, genus,
                      1 if phylum == "Arthropoda" else 0,
                      phylum, discovery))
                virus_inserted += 1
            except Exception:
                pass
        
        # 2. 插入新宿主（如果不在已有列表中）
        # 新类群才插入；已有的甲壳类不重复插入
        if phylum in ("Mollusca", "Cnidaria", "Porifera"):
            host_name = f"{common_name} (unknown species)"
            cur.execute("SELECT host_id FROM crustacean_hosts WHERE scientific_name = ?", (host_name,))
            if not cur.fetchone():
                try:
                    cur.execute("""
                        INSERT INTO crustacean_hosts (scientific_name, host_group, host_type, phylum, class)
                        VALUES (?, ?, 'biological', ?, ?)
                    """, (host_name, common_name, phylum, cls))
                    host_inserted += 1
                except Exception:
                    pass
    
    conn.commit()
    conn.close()
    print(f"  完成: 新增病毒 {virus_inserted} 条, 新增宿主 {host_inserted} 条")
    return virus_inserted, host_inserted

def generate_import_report():
    """生成导入后的统计报告"""
    print("[3/4] 生成统计报告 ...")
    conn = get_conn()
    cur = conn.cursor()
    
    stats = {}
    
    cur.execute("SELECT COUNT(*) FROM ref_literatures")
    stats["total_literature"] = cur.fetchone()[0]
    
    cur.execute("SELECT COUNT(*) FROM virus_master")
    stats["total_virus_species"] = cur.fetchone()[0]
    
    cur.execute("SELECT COUNT(*) FROM crustacean_hosts WHERE host_type = 'biological'")
    stats["total_hosts"] = cur.fetchone()[0]
    
    cur.execute("SELECT COUNT(DISTINCT phylum) FROM crustacean_hosts WHERE phylum IS NOT NULL")
    stats["phyla_covered"] = cur.fetchone()[0]
    
    cur.execute("SELECT phylum, COUNT(*) FROM crustacean_hosts WHERE phylum IS NOT NULL GROUP BY phylum")
    stats["hosts_by_phylum"] = {r[0]: r[1] for r in cur.fetchall()}
    
    cur.execute("SELECT host_phylum, COUNT(*) FROM virus_master WHERE host_phylum IS NOT NULL GROUP BY host_phylum")
    stats["virus_by_phylum"] = {r[0]: r[1] for r in cur.fetchall()}
    
    conn.close()
    
    report_path = IMPORT_DIR / "06_post_import_report.txt"
    with report_path.open("w", encoding="utf-8") as f:
        f.write("=" * 50 + "\n")
        f.write("AquaVir-KB 导入后统计\n")
        f.write("=" * 50 + "\n\n")
        f.write(f"总文献数: {stats['total_literature']}\n")
        f.write(f"病毒物种: {stats['total_virus_species']}\n")
        f.write(f"宿主物种: {stats['total_hosts']}\n")
        f.write(f"覆盖门类: {stats['phyla_covered']}\n\n")
        f.write("宿主按门类:\n")
        for phylum, count in sorted(stats['hosts_by_phylum'].items(), key=lambda x: x[1], reverse=True):
            f.write(f"  {phylum}: {count}\n")
        f.write("\n病毒按门类:\n")
        for phylum, count in sorted(stats['virus_by_phylum'].items(), key=lambda x: x[1], reverse=True):
            f.write(f"  {phylum}: {count}\n")
    
    print(f"  报告保存: {report_path}")
    return stats

def main():
    print("=" * 50)
    print("AquaVir-KB 一键导入")
    print("=" * 50 + "\n")
    
    if not DB_PATH.exists():
        print(f"错误: 找不到数据库 {DB_PATH}")
        return
    
    ref_count = import_references()
    virus_count, host_count = import_known_virus_associations()
    stats = generate_import_report()
    
    print("\n" + "=" * 50)
    print("导入完成！")
    print("=" * 50)
    print(f"\n文献总数: {stats['total_literature']}")
    print(f"病毒物种: {stats['total_virus_species']}")
    print(f"宿主物种: {stats['total_hosts']}")
    print(f"覆盖门类: {stats['phyla_covered']}")
    print(f"\n下一步:")
    print("  1. 查看报告: import_ready/06_post_import_report.txt")
    print("  2. 人工审核 02_host_virus_candidates_mollusca.tsv")
    print("  3. 运行后端重启以刷新缓存")

if __name__ == "__main__":
    main()
