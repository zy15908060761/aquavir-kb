"""
ICTV 模糊匹配脚本：将 virus_master 的甲壳类病毒匹配到 ICTV 分类系统。

匹配策略：
  Level 1 (high): genus 精确匹配 + 两边数量都有限 → 直接映射
  Level 2 (medium): family + genus 都匹配，但属名有多个物种 → 映射所有
  Level 3 (family_only): family 匹配但 genus 不在 ICTV → 映射到科级别
  Level 4 (no_match): 无匹配 → 记录未匹配原因

输出到 virus_ictv_mappings 表。
"""

import sqlite3
from datetime import datetime

DB_PATH = r'F:\甲壳动物数据库\crustacean_virus_core.db'


def get_genus_stats(c, ictv_genus):
    """返回 ICTV 中某个 genus 的物种数"""
    c.execute("SELECT COUNT(*) FROM ictv_taxonomy WHERE LOWER(genus) = LOWER(?)", (ictv_genus,))
    return c.fetchone()[0]


def get_family_stats(c, ictv_family):
    """返回 ICTV 中某个 family 的物种数"""
    c.execute("SELECT COUNT(*) FROM ictv_taxonomy WHERE LOWER(family) = LOWER(?)", (ictv_family,))
    return c.fetchone()[0]


def main():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # 确保表存在，清空旧的自动匹配（保留手动编辑的）
    c.execute("DELETE FROM virus_ictv_mappings WHERE match_status = 'auto_matched'")
    print(f'Cleared {c.rowcount} old auto-match records')

    # 获取所有甲壳类病毒种（未被手动匹配的）
    c.execute("""
        SELECT vm.master_id, vm.canonical_name, vm.virus_family, vm.virus_genus
        FROM virus_master vm
        WHERE vm.is_crustacean_virus = 1
          AND vm.canonical_name IS NOT NULL
        ORDER BY vm.master_id
    """)
    virus_species = [dict(zip(['master_id','canonical_name','family','genus'], row))
                     for row in c.fetchall()]

    print(f'Total crustacean virus species to match: {len(virus_species)}')

    # 预加载 ICTV 数据
    c.execute("SELECT ictv_id, species, family, genus, realm, class, order_name FROM ictv_taxonomy")
    ictv_entries = [dict(zip(['ictv_id','species','family','genus','realm','class','order_name'], row))
                    for row in c.fetchall()]
    print(f'ICTV taxonomy entries loaded: {len(ictv_entries)}')

    # 建立索引：genus -> [ictv_entries]
    ictv_by_genus = {}
    for e in ictv_entries:
        g = (e['genus'] or '').strip().lower()
        if g:
            ictv_by_genus.setdefault(g, []).append(e)

    # 建立索引：family -> [ictv_entries]
    ictv_by_family = {}
    for e in ictv_entries:
        f = (e['family'] or '').strip().lower()
        if f:
            ictv_by_family.setdefault(f, []).append(e)

    stats = {'high': 0, 'medium': 0, 'family_only': 0, 'no_match': 0}
    total_mapped = 0
    no_match_reasons = []

    for vs in virus_species:
        master_id = vs['master_id']
        name = vs['canonical_name']
        family = (vs['family'] or '').strip()
        genus = (vs['genus'] or '').strip()

        # 跳过无效 genus → 尝试科级别引用
        if genus.lower() in ('', 'none', 'unclassified', 'null'):
            ictv_family_entries = ictv_by_family.get(family.lower(), [])
            if ictv_family_entries:
                # 选科内第一个物种作为代表引用
                rep = ictv_family_entries[0]
                c.execute("""
                    INSERT INTO virus_ictv_mappings
                        (master_id, ictv_id, match_type, matched_value, match_status, confidence, source_id, created_at, notes)
                    VALUES (?, ?, 'normalized_exact', ?, 'auto_matched', 'low', 9, ?, ?)
                """, (
                    master_id, rep['ictv_id'], rep['family'],
                    datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    f'No genus assignment. Family "{family}" reference via {rep["species"]}. Manual review needed.'
                ))
                total_mapped += 1
                stats['family_only'] += 1
            else:
                stats['no_match'] += 1
                no_match_reasons.append(f'{name}: no genus, family={family} not in ICTV')
            continue

        # --- Level 1: genus 精确匹配 ---
        genus_lower = genus.lower()
        ictv_matches = ictv_by_genus.get(genus_lower, [])

        if ictv_matches:
            ictv_species_count = len(ictv_matches)

            # 统计此 virus_master genus 下有多少个病毒种
            c.execute("SELECT COUNT(*) FROM virus_master WHERE LOWER(virus_genus) = LOWER(?) AND is_crustacean_virus=1", (genus,))
            vm_genus_count = c.fetchone()[0]

            # 确定性判断
            if ictv_species_count <= 10 and vm_genus_count <= 3:
                confidence = 'high'
                level = 'high'
            elif ictv_species_count <= 50:
                confidence = 'medium'
                level = 'medium'
            else:
                # 太宽泛（如 Potyvirus 216 species），只匹配科
                stats['family_only'] += 1
                continue

            # 插入匹配记录
            for ictv_e in ictv_matches:
                c.execute("""
                    INSERT INTO virus_ictv_mappings
                        (master_id, ictv_id, match_type, matched_value, match_status, confidence, source_id, created_at, notes)
                    VALUES (?, ?, 'normalized_exact', ?, 'auto_matched', ?, 9, ?, ?)
                """, (
                    master_id,
                    ictv_e['ictv_id'],
                    ictv_e['species'],
                    confidence,
                    datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    f'Auto-matched via genus: {genus} -> {ictv_e["species"]} ({ictv_e["family"]}, {ictv_e["order_name"]})'
                ))
                total_mapped += 1
            stats[level] += 1

        else:
            # Genus 不在 ICTV 中 → 尝试科级别引用
            ictv_family_entries = ictv_by_family.get(family.lower(), [])
            if ictv_family_entries:
                representative = ictv_family_entries[0]
                c.execute("""
                    INSERT INTO virus_ictv_mappings
                        (master_id, ictv_id, match_type, matched_value, match_status, confidence, source_id, created_at, notes)
                    VALUES (?, ?, 'normalized_exact', ?, 'auto_matched', 'low', 9, ?, ?)
                """, (
                    master_id,
                    representative['ictv_id'],
                    representative['family'],
                    datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    f'Genus "{genus}" not in ICTV (novel). Family "{family}" reference via {representative["species"]}. Needs ICTV update.'
                ))
                total_mapped += 1
                stats['family_only'] += 1
            else:
                stats['no_match'] += 1
                no_match_reasons.append(f'{name}: genus={genus} not in ICTV, family={family} not in ICTV (novel)')

    conn.commit()

    # 统计结果
    print(f'\n=== Matching Results ===')
    print(f'High confidence (genus exact, limited scope): {stats["high"]} species')
    print(f'Medium confidence (genus exact, wider scope): {stats["medium"]} species')
    print(f'Family reference only (genus not in ICTV): {stats["family_only"]} species')
    print(f'No match: {stats["no_match"]} species')
    print(f'Total mapping records inserted: {total_mapped}')

    # 最终 ICTV 覆盖率
    c.execute('SELECT COUNT(DISTINCT master_id) FROM virus_ictv_mappings WHERE match_status = "auto_matched"')
    mapped_species = c.fetchone()[0]
    print(f'\nICTV coverage: {mapped_species}/{len(virus_species)} ({mapped_species/len(virus_species)*100:.1f}%)')

    # 未匹配样本
    if no_match_reasons:
        print(f'\nSample unmatched ({len(no_match_reasons)} total):')
        for r in no_match_reasons[:10]:
            print(f'  - {r}')
        if len(no_match_reasons) > 10:
            print(f'  ... and {len(no_match_reasons) - 10} more')

    # 验证数据完整性
    c.execute('SELECT match_type, confidence, COUNT(*) FROM virus_ictv_mappings GROUP BY match_type, confidence')
    print('\nMapping quality breakdown:')
    for row in c.fetchall():
        print(f'  {row[0]} ({row[1]}): {row[2]}')

    conn.close()


if __name__ == '__main__':
    main()
