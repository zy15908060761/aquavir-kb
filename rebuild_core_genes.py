#!/usr/bin/env python3
"""
P1-4: 核心基因按分类层级重新鉴定

方法（参考IVCDB + Qin et al. 2014）：
  1. 对core_genes表增加taxonomic_level列
  2. 现有基因标记为'species'层级
  3. 利用CD-HIT50聚类结果，跨物种鉴定科级/属级核心基因
     - 科级(family): 蛋白质簇在>=75%的科内物种中存在
     - 属级(genus):  蛋白质簇在>=100%的属内物种中存在
  4. 计算avg_identity（从viral_proteins_nr.identity_to_rep获取）
  5. 输出论文用统计数据和韦恩图数据
"""

import sqlite3
import csv
import json
from pathlib import Path
from datetime import datetime
from collections import defaultdict, Counter

DB_PATH = Path(r"F:\甲壳动物数据库\crustacean_virus_core.db")
REPORT_DIR = Path(r"F:\甲壳动物数据库\reports")
REPORT_DIR.mkdir(parents=True, exist_ok=True)


def rebuild_core_genes():
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA busy_timeout = 30000")
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    # ── Step 1: 备份并修改表结构 ──
    print("Step 1: Adding taxonomic_level column")

    # 检查列是否已存在
    c.execute("PRAGMA table_info(core_genes)")
    existing_cols = [row[1] for row in c.fetchall()]

    if "taxonomic_level" not in existing_cols:
        c.execute("ALTER TABLE core_genes ADD COLUMN taxonomic_level TEXT DEFAULT 'species'")
        print("  Added taxonomic_level column")

    if "taxonomic_group" not in existing_cols:
        c.execute("ALTER TABLE core_genes ADD COLUMN taxonomic_group TEXT")
        print("  Added taxonomic_group column (stores family/genus name)")

    if "min_coverage_pct" not in existing_cols:
        c.execute("ALTER TABLE core_genes ADD COLUMN min_coverage_pct REAL")
        print("  Added min_coverage_pct column")

    conn.commit()

    # 标记现有基因为species级
    c.execute("UPDATE core_genes SET taxonomic_level = 'species' WHERE taxonomic_level IS NULL")
    updated = c.rowcount
    print(f"  Tagged {updated} existing genes as taxonomic_level='species'")

    # 更新species级基因的taxonomic_group为自己的病毒种名
    c.execute("UPDATE core_genes SET taxonomic_group = virus_species WHERE taxonomic_level = 'species' AND taxonomic_group IS NULL")
    conn.commit()

    # ── Step 2: 计算species级基因的avg_identity ──
    print("\nStep 2: Computing avg_identity for species-level core genes")

    # 对每个core_gene，通过reannotated_orfs → viral_proteins_nr找identity_to_rep
    c.execute("""
        UPDATE core_genes
        SET avg_identity = (
            SELECT AVG(vpnr.identity_to_rep)
            FROM reannotated_orfs ro
            JOIN viral_proteins_nr vpnr ON ro.reanno_id = vpnr.reanno_id
            JOIN viral_isolates vi ON ro.isolate_id = vi.isolate_id
            JOIN virus_master vm ON vi.master_id = vm.master_id
            JOIN nr_protein_clusters npc ON vpnr.cluster_id = npc.cluster_id
            WHERE vm.canonical_name = core_genes.virus_species
              AND (ro.aa_sequence LIKE '%' || core_genes.gene_symbol || '%'
                   OR core_genes.gene_symbol LIKE '%' || COALESCE(npc.functional_category, '') || '%')
            LIMIT 1
        )
    """)
    # 上述更新太慢，用更简单的方法：每基因找其对应的cluster，从cluster中的所有蛋白算avg identity

    # 简化方法：遍历每个有core gene的病毒种，批量计算
    c.execute("""
        SELECT DISTINCT virus_species FROM core_genes WHERE taxonomic_level = 'species'
    """)
    species_list = [row[0] for row in c.fetchall()]

    n_updated = 0
    for sp in species_list:
        # 找到该物种的所有基因和其对应的cluster
        c.execute("""
            SELECT cg.gene_id, cg.gene_symbol, cg.protein_name, npc.cluster_id
            FROM core_genes cg
            LEFT JOIN viral_proteins vp ON cg.virus_species = (
                SELECT vm.canonical_name FROM virus_master vm WHERE vm.canonical_name = cg.virus_species LIMIT 1
            )
            LEFT JOIN viral_proteins_nr vpnr ON vp.protein_id = vpnr.protein_id
            LEFT JOIN nr_protein_clusters npc ON vpnr.cluster_id = npc.cluster_id
            WHERE cg.virus_species = ?
        """, (sp,))
        rows = c.fetchall()

        for row in rows:
            if row["cluster_id"]:
                # 该cluster中所有蛋白的identity分布
                c.execute("""
                    SELECT AVG(identity_to_rep), MIN(identity_to_rep), MAX(identity_to_rep), COUNT(*)
                    FROM viral_proteins_nr
                    WHERE cluster_id = ?
                """, (row["cluster_id"],))
                stats = c.fetchone()
                if stats and stats[0]:
                    c.execute("""
                        UPDATE core_genes
                        SET avg_identity = ?, conservation_rate = ?, total_isolates = ?,
                            present_isolates = (SELECT COUNT(DISTINCT vpnr.protein_id)
                                FROM viral_proteins_nr vpnr
                                WHERE vpnr.cluster_id = ?)
                        WHERE gene_id = ?
                    """, (round(stats[0], 2), round(stats[0] / 100, 2) if stats[0] else 0, stats[3], row["cluster_id"], row["gene_id"]))
                    n_updated += 1

    conn.commit()
    print(f"  Updated avg_identity for {n_updated} core genes (via protein clusters)")

    # ── Step 3: 鉴定科级核心基因 ──
    print("\nStep 3: Identifying family-level core genes")

    # 先看哪些科有>=3个物种
    c.execute("""
        SELECT vm.virus_family, COUNT(DISTINCT vm.master_id) as n_species,
               COUNT(DISTINCT vi.isolate_id) as n_isolates
        FROM virus_master vm
        JOIN viral_isolates vi ON vm.master_id = vi.master_id
        WHERE vm.virus_family IS NOT NULL AND vm.virus_family != ''
          AND LOWER(vm.canonical_name) NOT LIKE '%unknown%'
          AND LOWER(vm.canonical_name) NOT LIKE '%unclassified%'
        GROUP BY vm.virus_family
        HAVING n_species >= 3
        ORDER BY n_isolates DESC
    """)
    eligible_families = [dict(row) for row in c.fetchall()]
    print(f"  Families with >=3 named species: {len(eligible_families)}")

    family_core_genes = []
    for fam in eligible_families:
        fam_name = fam["virus_family"]
        n_species = fam["n_species"]

        # 找到该科内跨物种保守的CD-HIT50蛋白质簇
        # 方法：找出在该科的>= ceil(0.75 * n_species)个物种中都出现的聚类
        min_coverage = max(3, int(0.75 * n_species))  # 至少3种

        c.execute("""
            SELECT npc.cdhit50_cluster_id as cluster_id,
                   COUNT(DISTINCT vm.master_id) as species_count,
                   COUNT(DISTINCT vi.isolate_id) as isolate_count,
                   GROUP_CONCAT(DISTINCT vm.canonical_name) as species_names,
                   npc.representative_aa_seq,
                   npc.avg_length,
                   AVG(vpnr.identity_to_rep) as avg_identity
            FROM nr_protein_clusters npc
            JOIN viral_proteins_nr vpnr ON npc.cluster_id = vpnr.cluster_id
            JOIN reannotated_orfs ro ON vpnr.reanno_id = ro.reanno_id
            JOIN viral_isolates vi ON ro.isolate_id = vi.isolate_id
            JOIN virus_master vm ON vi.master_id = vm.master_id
            WHERE vm.virus_family = ?
              AND vm.canonical_name IS NOT NULL
              AND LOWER(vm.canonical_name) NOT LIKE '%unknown%'
              AND npc.cdhit50_cluster_id IS NOT NULL
              AND npc.cdhit50_cluster_id > 0
            GROUP BY npc.cdhit50_cluster_id
            HAVING species_count >= ?
            ORDER BY species_count DESC, isolate_count DESC
        """, (fam_name, min_coverage))

        fam_genes = [dict(row) for row in c.fetchall()]
        print(f"\n  [{fam_name}]: {n_species} species, {len(fam_genes)} family-level core genes (>= {min_coverage}/{n_species} species)")

        for i, gene in enumerate(fam_genes):
            c.execute("""
                INSERT INTO core_genes (virus_species, gene_symbol, protein_name,
                    functional_category, conservation_rate, total_isolates,
                    present_isolates, avg_identity, taxonomic_level, taxonomic_group,
                    min_coverage_pct, function_summary)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'family', ?, ?, ?)
            """, (
                f"CONSERVED_{fam_name}",
                f"CDHIT50_cluster_{gene['cluster_id']}",
                f"Core protein conserved in {gene['species_count']}/{n_species} {fam_name} species",
                'conserved_core',
                round(gene['species_count'] / n_species, 3),
                gene['isolate_count'],
                gene['species_count'],
                round(gene['avg_identity'], 2) if gene['avg_identity'] else None,
                fam_name,
                round(gene['species_count'] / n_species * 100, 1),
                f"Species: {gene['species_names']}"
            ))
            family_core_genes.append({**gene, "family": fam_name, "species_count_in_family": gene["species_count"]})

    conn.commit()
    print(f"\n  Total family-level core genes identified: {len(family_core_genes)}")

    # ── Step 4: 鉴定属级核心基因 ──
    print("\nStep 4: Identifying genus-level core genes")

    # 从ICTV taxonomy查找有属级分类的病毒
    c.execute("""
        SELECT DISTINCT vm.virus_genus, vm.virus_family, COUNT(DISTINCT vm.master_id) as n_species
        FROM virus_master vm
        WHERE vm.virus_genus IS NOT NULL AND vm.virus_genus != ''
          AND LOWER(vm.canonical_name) NOT LIKE '%unknown%'
        GROUP BY vm.virus_genus, vm.virus_family
        HAVING n_species >= 2
        ORDER BY n_species DESC
    """)
    eligible_genera = [dict(row) for row in c.fetchall()]
    print(f"  Genera with >=2 named species: {len(eligible_genera)}")

    genus_core_genes = []
    for gen in eligible_genera:
        genus_name = gen["virus_genus"]
        n_species = gen["n_species"]

        # 属级: 100%的属内物种都有
        c.execute("""
            SELECT npc.cdhit50_cluster_id as cluster_id,
                   COUNT(DISTINCT vm.master_id) as species_count,
                   COUNT(DISTINCT vi.isolate_id) as isolate_count,
                   GROUP_CONCAT(DISTINCT vm.canonical_name) as species_names,
                   AVG(vpnr.identity_to_rep) as avg_identity
            FROM nr_protein_clusters npc
            JOIN viral_proteins_nr vpnr ON npc.cluster_id = vpnr.cluster_id
            JOIN reannotated_orfs ro ON vpnr.reanno_id = ro.reanno_id
            JOIN viral_isolates vi ON ro.isolate_id = vi.isolate_id
            JOIN virus_master vm ON vi.master_id = vm.master_id
            WHERE vm.virus_genus = ?
              AND vm.canonical_name IS NOT NULL
              AND LOWER(vm.canonical_name) NOT LIKE '%unknown%'
              AND npc.cdhit50_cluster_id IS NOT NULL
              AND npc.cdhit50_cluster_id > 0
            GROUP BY npc.cdhit50_cluster_id
            HAVING species_count = ?
            ORDER BY isolate_count DESC
        """, (genus_name, n_species))

        gen_genes = [dict(row) for row in c.fetchall()]

        if gen_genes:
            print(f"  [{genus_name}]: {n_species} species, {len(gen_genes)} genus-level core genes (100% coverage)")

            for gene in gen_genes:
                c.execute("""
                    INSERT INTO core_genes (virus_species, gene_symbol, protein_name,
                        functional_category, conservation_rate, total_isolates,
                        present_isolates, avg_identity, taxonomic_level, taxonomic_group,
                        min_coverage_pct, function_summary)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'genus', ?, ?, ?)
                """, (
                    f"CONSERVED_{genus_name}",
                    f"CDHIT50_cluster_{gene['cluster_id']}",
                    f"Core protein conserved in {gene['species_count']}/{n_species} {genus_name} species",
                    'conserved_core',
                    round(gene['species_count'] / n_species, 3),
                    gene['isolate_count'],
                    gene['species_count'],
                    round(gene['avg_identity'], 2) if gene['avg_identity'] else None,
                    genus_name,
                    round(gene['species_count'] / n_species * 100, 1),
                    f"Species: {gene['species_names']}"
                ))
                genus_core_genes.append({**gene, "genus": genus_name})

    conn.commit()
    print(f"  Total genus-level core genes identified: {len(genus_core_genes)}")

    # ── Step 5: 统计总结 ──
    print("\nStep 5: Summary statistics")

    c.execute("""
        SELECT taxonomic_level, COUNT(*) as n_genes,
               COUNT(DISTINCT taxonomic_group) as n_groups,
               ROUND(AVG(avg_identity), 1) as mean_identity,
               ROUND(AVG(conservation_rate), 3) as mean_conservation
        FROM core_genes
        GROUP BY taxonomic_level
        ORDER BY COUNT(*) DESC
    """)
    print(f"\n  {'Level':10s} {'Genes':>7s} {'Groups':>7s} {'Mean Identity':>13s} {'Mean Conservation':>18s}")
    print("  " + "-" * 60)
    for row in c.fetchall():
        print(f"  {row[0]:10s} {row[1]:>7} {row[2]:>7} {row[3]:>13} {row[4]:>18}")

    # 韦恩图数据：cross-level overlap
    c.execute("""
        SELECT taxonomic_level, COUNT(DISTINCT gene_symbol) FROM core_genes
        GROUP BY taxonomic_level
    """)
    level_counts = {row[0]: row[1] for row in c.fetchall()}
    print(f"\n  Venn diagram data (unique gene counts):")
    for level, cnt in sorted(level_counts.items()):
        print(f"    {level}: {cnt}")

    # 跨层级重叠（通过cdhit50_cluster_id）
    c.execute("""
        SELECT cg1.taxonomic_level as level1, cg2.taxonomic_level as level2,
               COUNT(DISTINCT cg1.gene_symbol) as shared_genes
        FROM core_genes cg1
        JOIN core_genes cg2 ON cg1.gene_symbol = cg2.gene_symbol
        WHERE cg1.taxonomic_level < cg2.taxonomic_level
        GROUP BY cg1.taxonomic_level, cg2.taxonomic_level
    """)
    overlap = [dict(row) for row in c.fetchall()]
    print(f"\n  Cross-level overlap:")
    for o in overlap:
        print(f"    {o['level1']} ∩ {o['level2']}: {o['shared_genes']} genes")

    # ── 保存输出 ──
    # 按层级的核心基因列表
    for level in ['species', 'genus', 'family']:
        c.execute("""
            SELECT virus_species, gene_symbol, protein_name, functional_category,
                   conservation_rate, total_isolates, present_isolates,
                   avg_identity, taxonomic_group, function_summary
            FROM core_genes
            WHERE taxonomic_level = ?
            ORDER BY conservation_rate DESC, total_isolates DESC
        """, (level,))

        csv_path = REPORT_DIR / f"core_genes_{level}_level.csv"
        with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
            fieldnames = ["virus_species", "gene_symbol", "protein_name", "functional_category",
                         "conservation_rate", "total_isolates", "present_isolates",
                         "avg_identity", "taxonomic_group", "function_summary"]
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for row in c.fetchall():
                writer.writerow(dict(row))
        print(f"\n  Saved: {csv_path}")

    # JSON summary for frontend
    summary = {
        "timestamp": datetime.now().isoformat(),
        "core_genes_by_level": {
            "species": level_counts.get("species", 0),
            "genus": level_counts.get("genus", 0),
            "family": level_counts.get("family", 0),
        },
        "cross_level_overlap": overlap,
        "families_analyzed": len(eligible_families),
        "genera_analyzed": len(eligible_genera),
    }

    json_path = REPORT_DIR / "core_genes_summary.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    print(f"  Saved: {json_path}")

    conn.close()
    return summary


def main():
    print("=" * 60)
    print("P1-4: Core Gene Reorganization by Taxonomic Level")
    print("=" * 60)
    summary = rebuild_core_genes()
    print(f"\nDone. Next: use core_genes_*_level.csv for manuscript tables.")
    print(f"Use core_genes_summary.json for Venn diagram data (like IVCDB Fig 2G/H).")


if __name__ == "__main__":
    main()
