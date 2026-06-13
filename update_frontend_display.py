"""
更新前端展示逻辑，支持诊断方法分类的中文映射和兼容新旧表结构。

本脚本会自动：
1. 检测当前数据库分类体系版本（是否已重建）
2. 修改 backend.py：添加中文映射、兼容查询逻辑
3. 修改 templates/virus_detail.html：展示中文分类名

执行前会自动备份原文件。
"""
from __future__ import annotations

import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

DB_PATH = Path(r"F:\甲壳动物数据库\crustacean_virus_core.db")
BACKEND_PATH = Path(r"F:\甲壳动物数据库\backend.py")
TEMPLATE_PATH = Path(r"F:\甲壳动物数据库\templates\virus_detail.html")

# ========================================================================
# 中文分类映射
# ========================================================================
CATEGORY_CN_BLOCK = '''
# ── 诊断方法分类中文映射 ──────────────────────────────────────────
DIAGNOSTIC_CATEGORY_CN = {
    # 一级分类
    "nucleic_acid_amplification": "核酸扩增检测",
    "immunoassay": "免疫检测",
    "nucleic_acid_hybridization": "核酸杂交检测",
    "sequencing": "测序检测",
    "crispr_cas": "CRISPR 检测",
    "other": "其他",
    # 二级分类（具体技术）
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
    "in-situ-hybridization": "原位杂交",
    "ish": "原位杂交",
    "crispr-cas": "CRISPR-Cas",
    "crispr-cas12a": "CRISPR-Cas12a",
    "crispr-cas13": "CRISPR-Cas13",
    "sanger-sequencing": "Sanger 测序",
    "ngs": "高通量测序",
    "metagenomic-sequencing": "宏基因组测序",
    # 兜底：旧值也保留映射
    "PCR": "常规 PCR",
    "RT-PCR": "RT-PCR",
    "qPCR": "实时荧光定量 PCR",
    "LAMP": "LAMP",
    "RPA": "RPA",
    "CRISPR": "CRISPR",
    "ISH": "原位杂交",
    "immunoassay": "免疫检测",
    "sequencing": "测序",
}
# ────────────────────────────────────────────────────────────────
'''


def backup_files() -> None:
    """备份原文件。"""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    for src in [BACKEND_PATH, TEMPLATE_PATH]:
        dst = src.parent / f"{src.stem}_bak_{ts}{src.suffix}"
        shutil.copy2(src, dst)
        print(f"[备份] {src.name} -> {dst.name}")


def detect_schema_state() -> str:
    """检测当前表结构版本。"""
    conn = sqlite3.connect(str(DB_PATH))
    c = conn.cursor()
    c.execute("SELECT method_category FROM diagnostic_methods LIMIT 1")
    val = c.fetchone()[0]
    conn.close()
    new_cats = {
        "nucleic_acid_amplification", "immunoassay",
        "nucleic_acid_hybridization", "sequencing",
        "crispr_cas", "other",
    }
    return "rebuilt" if val in new_cats else "legacy"


def patch_backend() -> None:
    """修改 backend.py，添加中文映射和兼容查询。"""
    content = BACKEND_PATH.read_text(encoding="utf-8")

    # ------------------------------------------------------------------
    # 1. 在导入区之后插入中文映射字典
    # ------------------------------------------------------------------
    if "DIAGNOSTIC_CATEGORY_CN" not in content:
        # 找到合适的插入位置（在 imports 之后，第一个函数/路由之前）
        insert_marker = "def get_db():"
        if insert_marker in content:
            content = content.replace(
                insert_marker,
                CATEGORY_CN_BLOCK + "\n" + insert_marker,
                1,
            )
            print("  [+] 已插入 DIAGNOSTIC_CATEGORY_CN 映射字典")
        else:
            print("  [!] 未找到插入位置，跳过映射字典插入")

    # ------------------------------------------------------------------
    # 2. 替换 stats 中的诊断方法统计查询（兼容新旧结构）
    # ------------------------------------------------------------------
    old_stats_query = '''        # Diagnostic methods stats
        c.execute("SELECT method_subcategory, COUNT(*) FROM diagnostic_methods WHERE data_quality = 'curated' GROUP BY method_subcategory ORDER BY COUNT(*) DESC")
        stats["diagnostic_categories"] = {r[0]: r[1] for r in c.fetchall()}'''

    new_stats_query = '''        # Diagnostic methods stats
        # 自动检测分类体系版本
        c.execute("SELECT method_category FROM diagnostic_methods LIMIT 1")
        _test_cat = c.fetchone()[0]
        _is_rebuilt = _test_cat in ('nucleic_acid_amplification', 'immunoassay', 'nucleic_acid_hybridization', 'sequencing', 'crispr_cas', 'other')
        _primary_field = 'method_category' if _is_rebuilt else 'method_subcategory'
        c.execute(f"SELECT {_primary_field}, COUNT(*) FROM diagnostic_methods WHERE data_quality = 'curated' GROUP BY {_primary_field} ORDER BY COUNT(*) DESC")
        stats["diagnostic_categories"] = {r[0]: r[1] for r in c.fetchall()}'''

    if old_stats_query in content:
        content = content.replace(old_stats_query, new_stats_query, 1)
        print("  [+] 已更新 stats 诊断方法统计查询")
    else:
        print("  [!] 未找到 stats 查询代码块，可能已修改过")

    # ------------------------------------------------------------------
    # 3. 替换 virus_detail 路由中的诊断方法查询
    # ------------------------------------------------------------------
    old_detail_query = '''        # Diagnostic methods for this virus (curated only)
        c.execute("""
            SELECT method_name, method_category, method_subcategory, target_gene_or_region,
                   sample_type, field_deployable, visual_readout, detection_limit, evidence_strength
            FROM diagnostic_methods
            WHERE virus_master_id = ? AND data_quality = 'curated'
            ORDER BY method_subcategory, method_name
        """, (master_id,))
        diagnostic_methods = [dict(r) for r in c.fetchall()]'''

    new_detail_query = '''        # Diagnostic methods for this virus (curated only)
        # 自动检测分类体系版本并统一输出格式
        c.execute("SELECT method_category FROM diagnostic_methods LIMIT 1")
        _test_cat = c.fetchone()[0]
        _is_rebuilt = _test_cat in ('nucleic_acid_amplification', 'immunoassay', 'nucleic_acid_hybridization', 'sequencing', 'crispr_cas', 'other')
        _primary_field = 'method_category' if _is_rebuilt else 'method_subcategory'
        _secondary_field = 'method_subcategory' if _is_rebuilt else 'method_category'
        c.execute(f"""
            SELECT method_name, {_primary_field}, {_secondary_field}, target_gene_or_region,
                   sample_type, field_deployable, visual_readout, detection_limit, evidence_strength
            FROM diagnostic_methods
            WHERE virus_master_id = ? AND data_quality = 'curated'
            ORDER BY {_primary_field}, method_name
        """, (master_id,))
        _raw_methods = c.fetchall()
        diagnostic_methods = []
        for r in _raw_methods:
            dm = dict(r)
            dm["primary_category"] = dm.pop(_primary_field)
            dm["secondary_category"] = dm.pop(_secondary_field)
            dm["primary_cn"] = DIAGNOSTIC_CATEGORY_CN.get(dm["primary_category"], dm["primary_category"])
            dm["secondary_cn"] = DIAGNOSTIC_CATEGORY_CN.get(dm["secondary_category"], dm["secondary_category"])
            diagnostic_methods.append(dm)'''

    if old_detail_query in content:
        content = content.replace(old_detail_query, new_detail_query, 1)
        print("  [+] 已更新 virus_detail 诊断方法查询")
    else:
        print("  [!] 未找到 virus_detail 查询代码块，可能已修改过")

    BACKEND_PATH.write_text(content, encoding="utf-8")
    print("  [✓] backend.py 更新完成")


def patch_template() -> None:
    """修改 virus_detail.html，展示中文分类名。"""
    content = TEMPLATE_PATH.read_text(encoding="utf-8")

    # 替换诊断方法分类展示单元格
    old_cell = '''                                <td class="px-4 py-2">
                                    <span class="px-2 py-0.5 text-xs rounded bg-blue-50 text-blue-700">{{ dm.method_subcategory }}</span>
                                    <span class="text-xs text-gray-400">{{ dm.method_category }}</span>
                                </td>'''

    new_cell = '''                                <td class="px-4 py-2">
                                    <span class="px-2 py-0.5 text-xs rounded bg-blue-50 text-blue-700">{{ dm.primary_cn or dm.primary_category }}</span>
                                    {% if dm.secondary_category %}
                                    <span class="text-xs text-gray-400">{{ dm.secondary_cn or dm.secondary_category }}</span>
                                    {% endif %}
                                </td>'''

    if old_cell in content:
        content = content.replace(old_cell, new_cell, 1)
        print("  [+] 已更新诊断方法分类展示单元格")
    else:
        print("  [!] 未找到模板中的分类展示代码，可能已修改过")

    TEMPLATE_PATH.write_text(content, encoding="utf-8")
    print("  [✓] virus_detail.html 更新完成")


def main() -> None:
    print("=" * 60)
    print("更新前端诊断方法展示逻辑")
    print("=" * 60)

    state = detect_schema_state()
    print(f"\n[检测] 当前数据库状态: {state}")
    if state == "rebuilt":
        print("  说明: method_category 已是一级分类（已重建）")
    else:
        print("  说明: method_subcategory 当前是一级分类（尚未重建）")
        print("  提示: 运行 rebuild_diagnostic_schema.py 后再执行本脚本，效果最佳")

    print("\n[Step 1/3] 备份原文件...")
    backup_files()

    print("\n[Step 2/3] 修改 backend.py...")
    patch_backend()

    print("\n[Step 3/3] 修改 virus_detail.html...")
    patch_template()

    print("\n" + "=" * 60)
    print("完成!")
    print("=" * 60)
    print("\n后续步骤:")
    if state == "legacy":
        print("  1. 先运行: python rebuild_diagnostic_schema.py  （重建表结构）")
        print("  2. 再运行: python update_frontend_display.py   （本脚本，更新前端）")
    print("  3. 重启后端服务，查看效果")


if __name__ == "__main__":
    main()
