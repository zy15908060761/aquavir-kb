"""
重建 diagnostic_methods 表，规范化诊断方法分类体系。

背景：
- 原表中 method_category 存的是具体技术名（PCR/qPCR/RT-PCR…），被 CHECK 约束锁死
- method_subcategory 反而存的是一级大类（核酸扩增、免疫检测…）
- 本脚本交换两个字段的角色，并精细化 21 条 curated 记录的二级分类

执行前会自动完整备份，支持安全回滚。
"""
from __future__ import annotations

import sqlite3
import shutil
from datetime import datetime
from pathlib import Path

DB_PATH = Path(r"F:\甲壳动物数据库\crustacean_virus_core.db")
BACKUP_DIR = Path(r"F:\甲壳动物数据库\backups")

# ========================================================================
# 1. 分类映射规则
# ========================================================================

# 旧 method_category → (新 method_category, 默认新 method_subcategory)
# 注意：旧 method_subcategory 已经是一级分类，旧 method_category 是具体技术
OLD_TO_NEW_MAP = {
    "PCR": ("nucleic_acid_amplification", "pcr"),
    "qPCR": ("nucleic_acid_amplification", "qpcr"),
    "RT-PCR": ("nucleic_acid_amplification", "rt-pcr"),
    "LAMP": ("nucleic_acid_amplification", "lamp"),
    "RPA": ("nucleic_acid_amplification", "rpa"),
    "CRISPR": ("crispr_cas", "crispr-cas"),
    "ISH": ("nucleic_acid_hybridization", "ish"),
    "immunoassay": ("immunoassay", "immunoassay"),
    "sequencing": ("sequencing", "sequencing"),
    "other": ("other", "other"),
}

# 21 条 curated 记录的精细化规则（基于 method_name 关键词）
# 顺序很重要：先匹配更具体的
REFINE_RULES = [
    ("nested", "nested-rt-pcr"),
    ("multiplex", "multiplex-rt-pcr"),
    ("RT-LAMP", "rt-lamp"),
    ("LAMP", "lamp"),
    ("IC strip", "lateral-flow-strip"),
    ("in situ", "in-situ-hybridization"),
    ("CRISPR-Cas12a", "crispr-cas12a"),
    ("qPCR", "qpcr"),
    ("RT-PCR", "rt-pcr"),  # 不含 nested/multiplex 的已在上面过滤
    # 纯 PCR（不含 qPCR/RT-PCR/nested/multiplex）
    ("PCR", "pcr"),
]

# 中文展示映射（供前端使用）
CATEGORY_CN = {
    # 一级分类
    "nucleic_acid_amplification": "核酸扩增检测",
    "immunoassay": "免疫检测",
    "nucleic_acid_hybridization": "核酸杂交检测",
    "sequencing": "测序检测",
    "crispr_cas": "CRISPR 检测",
    "other": "其他",
    # 二级分类
    "pcr": "常规 PCR",
    "rt-pcr": "RT-PCR",
    "qpcr": "实时荧光定量 PCR",
    "nested-rt-pcr": "巢式 RT-PCR",
    "multiplex-rt-pcr": "多重 RT-PCR",
    "lamp": "LAMP",
    "rt-lamp": "RT-LAMP",
    "rpa": "RPA",
    "lateral-flow-strip": "侧流层析试纸条",
    "elisa": "ELISA",
    "ish": "原位杂交",
    "in-situ-hybridization": "原位杂交",
    "crispr-cas": "CRISPR-Cas",
    "crispr-cas12a": "CRISPR-Cas12a",
    "crispr-cas13": "CRISPR-Cas13",
    "sanger-sequencing": "Sanger 测序",
    "ngs": "高通量测序",
    "metagenomic-sequencing": "宏基因组测序",
    "sequencing": "测序",
    "immunoassay": "免疫检测",
}


def refine_subcategory(method_name: str, old_subcategory: str) -> str:
    """基于 method_name 关键词，返回精细化后的二级分类。"""
    mn_lower = method_name.lower()
    for keyword, subcat in REFINE_RULES:
        if keyword.lower() in mn_lower:
            return subcat
    # 兜底：返回默认映射
    return OLD_TO_NEW_MAP.get(old_subcategory, (old_subcategory, old_subcategory))[1]


def backup_database() -> Path:
    """创建数据库完整备份。"""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = BACKUP_DIR / f"crustacean_virus_core_before_rebuild_diagnostic_{ts}.db"
    BACKUP_DIR.mkdir(exist_ok=True)
    shutil.copy2(DB_PATH, backup_path)
    print(f"[备份] 数据库已备份到: {backup_path}")
    return backup_path


def rebuild_table(conn: sqlite3.Connection) -> None:
    """重建 diagnostic_methods 表。"""
    c = conn.cursor()

    # ------------------------------------------------------------------
    # Step 1: 备份数据到临时表
    # ------------------------------------------------------------------
    print("\n[Step 1/6] 备份原表数据...")
    c.execute("DROP TABLE IF EXISTS _backup_diagnostic_methods")
    c.execute("CREATE TABLE _backup_diagnostic_methods AS SELECT * FROM diagnostic_methods")
    c.execute("SELECT COUNT(*) FROM _backup_diagnostic_methods")
    backup_count = c.fetchone()[0]
    print(f"  已备份 {backup_count} 条记录")

    # ------------------------------------------------------------------
    # Step 2: 删除旧表和索引
    # ------------------------------------------------------------------
    print("\n[Step 2/6] 删除旧表和索引...")
    c.execute("DROP INDEX IF EXISTS idx_diagnostic_virus")
    c.execute("DROP INDEX IF EXISTS idx_diagnostic_unique")
    c.execute("DROP TABLE IF EXISTS diagnostic_methods")
    print("  旧表和索引已删除")

    # ------------------------------------------------------------------
    # Step 3: 创建新表（method_category 为一级分类，无旧 CHECK 约束）
    # ------------------------------------------------------------------
    print("\n[Step 3/6] 创建新表结构...")
    c.execute("""
        CREATE TABLE diagnostic_methods (
            method_id INTEGER PRIMARY KEY AUTOINCREMENT,
            virus_master_id INTEGER,
            method_category TEXT NOT NULL,
            method_subcategory TEXT,
            method_name TEXT NOT NULL,
            target_gene_or_region TEXT,
            sample_type TEXT,
            field_deployable INTEGER CHECK (field_deployable IN (0, 1)),
            visual_readout INTEGER CHECK (visual_readout IN (0, 1)),
            detection_limit TEXT,
            validation_context TEXT,
            reference_id INTEGER,
            evidence_strength TEXT DEFAULT 'medium' CHECK (
                evidence_strength IN ('high', 'medium', 'low', 'unknown')
            ),
            curation_status TEXT DEFAULT 'needs_review' CHECK (
                curation_status IN ('auto_seeded', 'needs_review', 'manual_checked', 'rejected')
            ),
            notes TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            data_quality TEXT DEFAULT 'placeholder',
            FOREIGN KEY (virus_master_id) REFERENCES virus_master(master_id),
            FOREIGN KEY (reference_id) REFERENCES ref_literatures(reference_id)
        )
    """)
    print("  新表创建完成")

    # ------------------------------------------------------------------
    # Step 4: 插入数据（交换字段 + 精细化 curated）
    # ------------------------------------------------------------------
    print("\n[Step 4/6] 插入交换后的数据...")
    c.execute("""
        SELECT method_id, virus_master_id, method_category, method_subcategory, method_name,
               target_gene_or_region, sample_type, field_deployable, visual_readout,
               detection_limit, validation_context, reference_id, evidence_strength,
               curation_status, notes, created_at, data_quality
        FROM _backup_diagnostic_methods
        ORDER BY method_id
    """)

    inserted = 0
    refined = 0
    for row in c.fetchall():
        (mid, vid, old_cat, old_subcat, name, target, sample, field, visual,
         limit_, context, ref_id, evidence, status, notes, created, quality) = row

        # 基础映射：旧 method_category（具体技术）→ 新 method_subcategory
        new_cat, default_subcat = OLD_TO_NEW_MAP.get(old_cat, (old_subcat or old_cat, old_cat))

        # 新 method_category 来自旧 method_subcategory（一级分类）
        new_cat = old_subcat or new_cat

        # 精细化：如果是 curated 且有具体方法名，根据关键词细化二级分类
        new_subcat = default_subcat
        if quality == "curated" and name and name != old_cat:
            new_subcat = refine_subcategory(name, old_cat)
            if new_subcat != default_subcat:
                refined += 1

        c.execute("""
            INSERT INTO diagnostic_methods
            (method_id, virus_master_id, method_category, method_subcategory, method_name,
             target_gene_or_region, sample_type, field_deployable, visual_readout,
             detection_limit, validation_context, reference_id, evidence_strength,
             curation_status, notes, created_at, data_quality)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (mid, vid, new_cat, new_subcat, name, target, sample, field, visual,
              limit_, context, ref_id, evidence, status, notes, created, quality))
        inserted += 1

    conn.commit()
    print(f"  已插入 {inserted} 条记录（其中 {refined} 条二级分类被精细化）")

    # ------------------------------------------------------------------
    # Step 5: 重建索引
    # ------------------------------------------------------------------
    print("\n[Step 5/6] 重建索引...")
    c.execute("CREATE INDEX idx_diagnostic_virus ON diagnostic_methods(virus_master_id)")
    c.execute("""
        CREATE UNIQUE INDEX idx_diagnostic_unique
        ON diagnostic_methods(
            COALESCE(virus_master_id, -1),
            method_category,
            method_name,
            COALESCE(reference_id, -1)
        )
    """)
    print("  索引重建完成")

    # ------------------------------------------------------------------
    # Step 6: 验证
    # ------------------------------------------------------------------
    print("\n[Step 6/6] 数据验证...")
    c.execute("SELECT COUNT(*) FROM diagnostic_methods")
    final_count = c.fetchone()[0]
    assert final_count == backup_count, f"记录数不一致: {final_count} != {backup_count}"

    c.execute("SELECT method_category, COUNT(*) FROM diagnostic_methods GROUP BY method_category ORDER BY COUNT(*) DESC")
    print("\n  一级分类分布:")
    for cat, cnt in c.fetchall():
        cn = CATEGORY_CN.get(cat, cat)
        print(f"    {cat} ({cn}): {cnt}")

    c.execute("SELECT method_subcategory, COUNT(*) FROM diagnostic_methods GROUP BY method_subcategory ORDER BY COUNT(*) DESC")
    print("\n  二级分类分布:")
    for sub, cnt in c.fetchall():
        cn = CATEGORY_CN.get(sub, sub)
        print(f"    {sub} ({cn}): {cnt}")

    c.execute("SELECT method_name, method_category, method_subcategory FROM diagnostic_methods WHERE data_quality = 'curated' ORDER BY method_id")
    print("\n  21 条 curated 记录验证:")
    for name, cat, sub in c.fetchall():
        print(f"    {name:45s} | {cat:25s} | {sub}")

    print("\n[完成] 表重建成功！")


def rollback(conn: sqlite3.Connection) -> None:
    """从备份表回滚。"""
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM _backup_diagnostic_methods")
    backup_count = c.fetchone()[0]

    c.execute("DROP TABLE IF EXISTS diagnostic_methods")
    c.execute("DROP INDEX IF EXISTS idx_diagnostic_virus")
    c.execute("DROP INDEX IF EXISTS idx_diagnostic_unique")

    c.execute("""
        CREATE TABLE diagnostic_methods AS SELECT * FROM _backup_diagnostic_methods
    """)
    # 恢复自增主键属性需要重新创建，这里简化处理
    # 实际生产环境建议保留原 CREATE TABLE SQL

    c.execute("CREATE INDEX idx_diagnostic_virus ON diagnostic_methods(virus_master_id)")
    c.execute("""
        CREATE UNIQUE INDEX idx_diagnostic_unique
        ON diagnostic_methods(
            COALESCE(virus_master_id, -1),
            method_category,
            method_name,
            COALESCE(reference_id, -1)
        )
    """)
    conn.commit()
    print(f"[回滚] 已恢复到备份状态（{backup_count} 条记录）")


def main() -> None:
    print("=" * 60)
    print("诊断方法分类体系重建脚本")
    print("=" * 60)
    print(f"\n目标数据库: {DB_PATH}")
    print("\n说明:")
    print("  1. 本脚本会交换 method_category 和 method_subcategory 的角色")
    print("  2. 会给 21 条 curated 记录做更精细的二级分类")
    print("  3. 执行前会自动完整备份数据库")
    print("  4. 如果出错，可从备份表 _backup_diagnostic_methods 回滚")

    # 备份
    backup_path = backup_database()

    conn = sqlite3.connect(str(DB_PATH))
    try:
        rebuild_table(conn)
        conn.commit()
    except Exception as e:
        conn.rollback()
        print(f"\n[错误] {e}")
        print("正在尝试回滚...")
        rollback(conn)
        raise
    finally:
        conn.close()

    print(f"\n[提示] 如需回滚，可运行:")
    print(f"  python -c \"import sqlite3; c=sqlite3.connect('{DB_PATH}').cursor(); ...\"")
    print(f"[提示] 原始备份文件: {backup_path}")


if __name__ == "__main__":
    main()
