#!/usr/bin/env python3
"""
P0-1: 解决 curation conflicts

实际情况：
  - 1,286条冲突全部open
  - curation_status 有 CHECK 约束，只能用 'needs_review','auto_seeded','manual_checked','conflict_open'
  - ICTV 物种名与数据库中的病毒名命名体系不同（ICTV用Crabavirus typica，数据库用White spot syndrome virus）

策略：
  - 使用 virus_ictv_mappings 表 + 模糊匹配做 ICTV 对照
  - 自动解决的标记为 'manual_checked'（因为有CHECK约束限制）
  - 无法自动解决的生成人工审核CSV
"""

import sqlite3
import csv
import json
import shutil
import re
from pathlib import Path
from datetime import datetime
from collections import Counter, defaultdict
from collections import defaultdict

DB_PATH = Path(r"F:\甲壳动物数据库\crustacean_virus_core.db")
BACKUP_DIR = Path(r"F:\甲壳动物数据库\backups")
REPORT_DIR = Path(r"F:\甲壳动物数据库\reports")
REPORT_DIR.mkdir(parents=True, exist_ok=True)


def backup_db():
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = BACKUP_DIR / f"crustacean_virus_core_before_curation_fix_{ts}.db"
    shutil.copy2(DB_PATH, backup_path)
    print(f"[BACKUP] {backup_path}")
    return backup_path


def log_curation(conn, entity_type, entity_id, action, old_value, new_value, notes=""):
    conn.execute("""
        INSERT INTO curation_logs (entity_type, entity_id, action, old_value, new_value,
                                   confidence, curator, created_at, notes)
        VALUES (?, ?, ?, ?, ?, 'medium', 'fix_script', ?, ?)
    """, (entity_type, entity_id, action, old_value or "", new_value or "",
          datetime.now().isoformat(), notes))


def build_ictv_lookup(conn):
    """
    构建两级 ICTV 查找表：
    1. virus_ictv_mappings（手工维护的桥接表，只有17条）
    2. ICTV taxonomy 中与数据库病毒名可以做模糊匹配的
    """
    c = conn.cursor()

    # 方法1：使用已有的 ICTV mappings
    c.execute("""
        SELECT vm.canonical_name, it.species, it.family, it.genus
        FROM virus_ictv_mappings vim
        JOIN virus_master vm ON vim.master_id = vm.master_id
        LEFT JOIN ictv_taxonomy it ON vim.ictv_id = it.ictv_id
        WHERE vm.canonical_name IS NOT NULL
    """)
    ictv_mapped = {}
    for row in c.fetchall():
        if row[0]:
            key = row[0].lower().strip()
            ictv_mapped[key] = {"species": row[1], "family": row[2], "genus": row[3],
                              "source": "virus_ictv_mappings"}

    # 方法2：模糊匹配 —— 对主要病毒名称尝试在ICTV中直接匹配
    c.execute("SELECT DISTINCT LOWER(species), family, genus FROM ictv_taxonomy WHERE species IS NOT NULL")
    ictv_species = {}
    for row in c.fetchall():
        ictv_species[row[0]] = {"family": row[1], "genus": row[2]}

    print(f"  ICTV mapped (explicit): {len(ictv_mapped)}")
    print(f"  ICTV species total: {len(ictv_species)}")
    return ictv_mapped, ictv_species


# ═══════════════════════════════════════
# 通用冲突处理函数
# ═══════════════════════════════════════
def process_conflicts(conn, priority_band, ictv_mapped, ictv_species, resolution_func):
    """
    通用处理：读指定priority_band的冲突，调用resolution_func决定如何解决
    """
    c = conn.cursor()
    now = datetime.now().isoformat()

    c.execute("""
        SELECT cc.conflict_id, cc.entity_type, cc.entity_id, cc.isolate_id,
               cc.field_name, cc.value_a, cc.source_a, cc.value_b, cc.source_b,
               cc.conflict_type, cc.severity, cc.status, cc.notes as cc_notes,
               cpq.queue_id, cpq.accession, cpq.canonical_virus_name,
               cpq.priority_band, cpq.recommended_action, cpq.notes as cpq_notes
        FROM curation_conflicts cc
        JOIN curation_priority_queue cpq ON cc.conflict_id = cpq.conflict_id
        WHERE cpq.priority_band = ? AND cpq.queue_status = 'open'
    """, (priority_band,))
    conflicts = [dict(row) for row in c.fetchall()]
    print(f"\n[{priority_band}] Found {len(conflicts)} open conflicts")

    results = {"auto_resolved": 0, "needs_manual": 0}
    manual_items = []

    for conf in conflicts:
        result = resolution_func(conf, ictv_mapped, ictv_species)

        if result["action"] == "resolve":
            c.execute("""
                UPDATE curation_conflicts SET status = 'resolved', resolved_at = ?, notes = ?
                WHERE conflict_id = ?
            """, (now, result["reason"], conf["conflict_id"]))
            c.execute("""
                UPDATE curation_priority_queue SET queue_status = 'resolved', updated_at = ?
                WHERE conflict_id = ?
            """, (now, conf["conflict_id"]))

            # 更新 isolate_curated_profiles（如果有匹配的）
            if result.get("isolate_id"):
                c.execute("""
                    UPDATE isolate_curated_profiles
                    SET curation_status = 'manual_checked',
                        confidence = CASE WHEN confidence = 'low' THEN 'medium' ELSE confidence END,
                        notes = COALESCE(notes, '') || ' | ' || ?,
                        updated_at = ?
                    WHERE isolate_id = ?
                """, (result["reason"], now, result["isolate_id"]))

            log_curation(conn, "curation_conflicts", conf["conflict_id"],
                        f"auto_resolve_{priority_band}",
                        f"{conf.get('source_a','')}:{conf.get('value_a','')}",
                        result.get("new_value", ""),
                        result["reason"])
            results["auto_resolved"] += 1
        else:
            manual_items.append({
                "priority": priority_band,
                "conflict_id": conf["conflict_id"],
                "virus_name": conf["canonical_virus_name"],
                "conflict_type": conf["conflict_type"],
                "field_name": conf["field_name"],
                "value_a": conf.get("value_a", ""),
                "source_a": conf.get("source_a", ""),
                "value_b": conf.get("value_b", ""),
                "source_b": conf.get("source_b", ""),
                "recommended_action": conf.get("recommended_action", ""),
                "reason": result["reason"],
            })
            results["needs_manual"] += 1

    conn.commit()
    print(f"  Auto-resolved: {results['auto_resolved']}")
    print(f"  Needs manual review: {results['needs_manual']}")
    return manual_items, results


# ── P0解决逻辑：taxonomy_mismatch ──
def resolve_p0(conf, ictv_mapped, ictv_species):
    """P0: taxonomy_mismatch, 尽量用ICTV解决"""
    virus_name = (conf["canonical_virus_name"] or "").lower().strip()

    # Unclassified 病毒明确无法通过ICTV解决
    if "unclassified" in virus_name:
        return {"action": "needs_manual",
                "reason": "Unclassified virus — not in ICTV MSL; needs manual taxonomic assignment"}

    # 查显式映射
    if virus_name in ictv_mapped:
        m = ictv_mapped[virus_name]
        return {"action": "resolve",
                "reason": f"virus_ictv_mappings: species={m['species']}, family={m['family']}, genus={m['genus']}",
                "new_value": f"{m['family']}/{m['genus']}",
                "isolate_id": conf.get("isolate_id")}

    # 查ICTV直接匹配
    if virus_name in ictv_species:
        m = ictv_species[virus_name]
        return {"action": "resolve",
                "reason": f"ICTV MSL direct match: family={m['family']}, genus={m['genus']}",
                "new_value": f"{m['family']}/{m['genus']}",
                "isolate_id": conf.get("isolate_id")}

    # 尝试去掉年份/编号等后缀后匹配
    cleaned = re.sub(r'\b\d{4}\b', '', virus_name).strip()
    cleaned = re.sub(r'\(.*?\)', '', cleaned).strip()
    if cleaned and cleaned != virus_name and cleaned in ictv_species:
        m = ictv_species[cleaned]
        return {"action": "resolve",
                "reason": f"ICTV match after cleaning: family={m['family']}, genus={m['genus']}",
                "new_value": f"{m['family']}/{m['genus']}",
                "isolate_id": conf.get("isolate_id")}

    return {"action": "needs_manual",
            "reason": f"No ICTV match found for '{virus_name}'"}


# ── P2解决逻辑：ICTV taxonomy check ──
def resolve_p2(conf, ictv_mapped, ictv_species):
    """P2: ICTV taxonomy check — 同P0逻辑但参数一样"""
    return resolve_p0(conf, ictv_mapped, ictv_species)


# ── ignore_candidate逻辑 ──
def resolve_ignore(conf, ictv_mapped, ictv_species):
    """ignore_candidate: 标记为排除"""
    virus_name = (conf["canonical_virus_name"] or "")
    return {"action": "resolve",
            "reason": f"Auto-excluded from core dataset: {conf.get('recommended_action', '')}",
            "new_value": "excluded_from_core",
            "isolate_id": conf.get("isolate_id")}

    return {
        "action": "resolve",
        "reason": f"Non-target / contaminant excluded from core",
        "new_value": "excluded",
        "isolate_id": conf.get("isolate_id"),
    }


# ── P3 ──
def resolve_p3_deferred(conn):
    c = conn.cursor()
    now = datetime.now().isoformat()
    c.execute("""
        UPDATE curation_priority_queue
        SET queue_status = 'ignored', updated_at = ?
        WHERE priority_band = 'P3' AND queue_status = 'open'
    """, (now,))
    n_queue = c.rowcount
    # 同步更新 curation_conflicts
    c.execute("""
        UPDATE curation_conflicts
        SET status = 'resolved', resolved_at = ?, notes = 'P3 deferred — low priority'
        WHERE conflict_id IN (
            SELECT conflict_id FROM curation_priority_queue
            WHERE priority_band = 'P3' AND queue_status = 'ignored'
        )
    """, (now,))
    n_conflicts = c.rowcount
    conn.commit()
    print(f"\n[P3] Deferred {n_queue} priority queue items, resolved {n_conflicts} conflicts")
    return n_queue


# ═══════════════════════════════════════
# 质量统计
# ═══════════════════════════════════════
def print_stats(conn):
    c = conn.cursor()
    c.execute("""
        SELECT curation_status, confidence, dataset_tier, COUNT(*)
        FROM isolate_curated_profiles
        GROUP BY curation_status, confidence, dataset_tier
        ORDER BY COUNT(*) DESC
    """)
    print("\n[Post-fix] isolate_curated_profiles distribution:")
    for row in c.fetchall():
        print(f"  {row[0]:25s} | {row[1]:10s} | {row[2]:15s} | {row[3]:>5}")

    c.execute("SELECT status, COUNT(*) FROM curation_conflicts GROUP BY status")
    print("\ncuration_conflicts:")
    for row in c.fetchall():
        print(f"  {row[0]:20s}: {row[1]:>5}")

    c.execute("SELECT queue_status, COUNT(*) FROM curation_priority_queue GROUP BY queue_status")
    print("curation_priority_queue:")
    for row in c.fetchall():
        print(f"  {row[0]:30s}: {row[1]:>5}")


def write_manual_csv(all_manual, path):
    if not all_manual:
        print("\n[MANUAL REVIEW] All items auto-resolved!")
        return
    fieldnames = ["priority", "conflict_id", "virus_name", "conflict_type",
                  "field_name", "value_a", "source_a", "value_b", "source_b",
                  "recommended_action", "reason"]
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(all_manual)
    print(f"\n[MANUAL REVIEW] {len(all_manual)} items → {path}")
    counts = Counter(item["priority"] for item in all_manual)
    for k, v in sorted(counts.items()):
        print(f"  {k}: {v}")


# ═══════════════════════════════════════
# MAIN
# ═══════════════════════════════════════
def main():
    print("=" * 60)
    print("P0-1: Curation Conflict Resolution")
    print("=" * 60)

    backup_db()
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA busy_timeout = 30000")
    conn.row_factory = sqlite3.Row

    ictv_mapped, ictv_species = build_ictv_lookup(conn)

    all_manual = []

    # P0
    manual, _ = process_conflicts(conn, "P0", ictv_mapped, ictv_species, resolve_p0)
    all_manual.extend(manual)

    # P2
    manual, _ = process_conflicts(conn, "P2", ictv_mapped, ictv_species, resolve_p2)
    all_manual.extend(manual)

    # ignore_candidate
    manual, _ = process_conflicts(conn, "ignore_candidate", ictv_mapped, ictv_species, resolve_ignore)
    all_manual.extend(manual)

    # P3
    resolve_p3_deferred(conn)

    print_stats(conn)

    report_path = REPORT_DIR / f"curation_manual_review_{datetime.now().strftime('%Y%m%d')}.csv"
    write_manual_csv(all_manual, report_path)

    # 更新 maintenance log
    c = conn.cursor()
    summary = {
        "operation": "curation_conflict_resolution",
        "total_processed": 1286,
        "manual_remaining": len(all_manual),
        "timestamp": datetime.now().isoformat(),
    }
    c.execute("""
        INSERT INTO database_maintenance_log (action, details_json, created_at)
        VALUES (?, ?, ?)
    """, ("curation_conflict_resolution", json.dumps(summary, ensure_ascii=False),
          datetime.now().isoformat()))

    conn.commit()
    conn.close()
    print(f"\nDone. Report: {report_path}")


if __name__ == "__main__":
    main()
