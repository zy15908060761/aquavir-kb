"""
导出 70 条 placeholder 诊断方法记录，供人工核对分类是否正确。

输出格式：CSV（可用 Excel 打开）
包含字段：method_id, virus_name, 当前一级分类(method_subcategory), 当前二级分类(method_category), 
         method_name, evidence_strength, 建议操作
"""
from __future__ import annotations

import csv
import sqlite3
from datetime import datetime
from pathlib import Path

DB_PATH = Path(r"F:\甲壳动物数据库\crustacean_virus_core.db")
OUTPUT_PATH = Path(r"F:\甲壳动物数据库\reports\diagnostic_placeholder_review.csv")


def main() -> None:
    print("=" * 60)
    print("导出 placeholder 诊断方法核对清单")
    print("=" * 60)

    conn = sqlite3.connect(str(DB_PATH))
    c = conn.cursor()

    # 查询 placeholder 记录 + 关联病毒名
    c.execute("""
        SELECT 
            dm.method_id,
            vm.canonical_name AS virus_name,
            dm.method_subcategory AS current_primary_category,
            dm.method_category AS current_secondary_category,
            dm.method_name,
            dm.evidence_strength,
            dm.virus_master_id
        FROM diagnostic_methods dm
        LEFT JOIN virus_master vm ON dm.virus_master_id = vm.master_id
        WHERE dm.data_quality = 'placeholder'
        ORDER BY dm.method_subcategory, dm.method_category, dm.method_id
    """)

    rows = c.fetchall()
    print(f"\n共找到 {len(rows)} 条 placeholder 记录")

    # 确保输出目录存在
    OUTPUT_PATH.parent.mkdir(exist_ok=True)

    # 写入 CSV
    with open(OUTPUT_PATH, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow([
            "method_id",
            "virus_name",
            "当前一级分类(method_subcategory)",
            "当前二级分类(method_category)",
            "method_name",
            "evidence_strength",
            "建议操作",
            "核对后一级分类",
            "核对后二级分类",
            "核对备注",
        ])

        for row in rows:
            method_id, virus_name, primary, secondary, method_name, evidence, vid = row
            # 自动建议
            if method_name == secondary:
                suggestion = "method_name 与二级分类重复，建议补充具体方法信息或删除"
            elif virus_name is None:
                suggestion = "未关联病毒，建议补充 virus_master_id 或删除"
            else:
                suggestion = "请核对一级/二级分类是否正确"

            writer.writerow([
                method_id,
                virus_name or "(未关联)",
                primary or "-",
                secondary or "-",
                method_name,
                evidence,
                suggestion,
                "",  # 核对后一级分类（人工填写）
                "",  # 核对后二级分类（人工填写）
                "",  # 核对备注（人工填写）
            ])

    conn.close()
    print(f"\n[完成] 核对清单已保存到: {OUTPUT_PATH}")
    print("\n使用说明:")
    print("  1. 用 Excel 打开上面的 CSV 文件")
    print("  2. 在最后三列（'核对后一级分类'、'核对后二级分类'、'核对备注'）人工填写")
    print("  3. 核对完成后，可基于此表格写批量更新脚本")

    # 同时在控制台输出摘要
    print("\n" + "=" * 60)
    print("Placeholder 分类分布摘要")
    print("=" * 60)

    conn = sqlite3.connect(str(DB_PATH))
    c = conn.cursor()
    c.execute("""
        SELECT method_subcategory, method_category, COUNT(*) 
        FROM diagnostic_methods 
        WHERE data_quality = 'placeholder'
        GROUP BY method_subcategory, method_category
        ORDER BY method_subcategory, method_category
    """)
    for primary, secondary, cnt in c.fetchall():
        print(f"  {primary or '-':25s} / {secondary or '-':15s} : {cnt} 条")
    conn.close()


if __name__ == "__main__":
    main()
