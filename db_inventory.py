"""Full database inventory report."""
import sqlite3
from pathlib import Path

DB_PATH = Path(r"F:\甲壳动物数据库\crustacean_virus_core.db")

def main():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    # Get all tables
    c.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    tables = [row[0] for row in c.fetchall()]

    print("=" * 75)
    print(" 数据库表清单及记录数")
    print("=" * 75)
    print(f"{'表名':<35} {'记录数':>10}  {'说明'}")
    print("-" * 75)

    desc = {
        "viral_isolates": "病毒分离株主表",
        "species": "病毒物种分类",
        "crustacean_hosts": "甲壳动物宿主信息",
        "sample_collections": "采样点地理信息",
        "references": "文献引用",
        "genomes": "基因组序列",
        "proteins": "病毒蛋白注释(NCBI)",
        "genes": "病毒基因注释(NCBI)",
        "reannotated_orfs": "重新注释的ORF(6-frame)",
        "reannotation_stats": "ORF注释统计",
        "nr_protein_clusters": "NR蛋白精确匹配簇",
        "nr_cluster_members": "NR簇成员关系",
        "genome_pairwise_identity": "基因组两两同一性(k-mer)",
        "genome_synteny_blocks": "基因组共线性块",
        "diagnostics": "诊断方法知识库",
        "control_methods": "控制方法知识库",
        "protein_structures": "蛋白质结构(PDB)",
        "protein_domains": "蛋白质结构域注释",
        "sqlite_sequence": "SQLite自增序列",
    }

    for t in tables:
        try:
            c.execute(f'SELECT COUNT(*) FROM "{t}"')
            count = c.fetchone()[0]
        except:
            count = "N/A"
        d = desc.get(t, "")
        print(f"  {t:<33} {count:>10,}  {d}")

    print()
    print("=" * 75)
    print(" 核心数据维度概览")
    print("=" * 75)

    queries = [
        ("病毒分离株总数", "SELECT COUNT(*) FROM viral_isolates"),
        ("  ├─ 有序列数据", "SELECT COUNT(*) FROM viral_isolates WHERE has_sequence = 1"),
        ("  ├─ 有基因组长度", "SELECT COUNT(*) FROM viral_isolates WHERE genome_length IS NOT NULL"),
        ("  ├─ 有GC含量", "SELECT COUNT(*) FROM viral_isolates WHERE gc_content IS NOT NULL"),
        ("  └─ 有宿主信息", "SELECT COUNT(*) FROM viral_isolates WHERE host_id IS NOT NULL"),
        ("", None),
        ("物种/类群数", "SELECT COUNT(DISTINCT canonical_name) FROM viral_isolates WHERE canonical_name IS NOT NULL"),
        ("宿主物种数", "SELECT COUNT(*) FROM crustacean_hosts"),
        ("  ├─ 有IUCN状态", "SELECT COUNT(*) FROM crustacean_hosts WHERE iucn_status IS NOT NULL"),
        ("  └─ 已分类host_type", "SELECT COUNT(*) FROM crustacean_hosts WHERE host_type IS NOT NULL"),
        ("", None),
        ("采样点数", "SELECT COUNT(*) FROM sample_collections"),
        ("  ├─ 有省份信息", "SELECT COUNT(*) FROM sample_collections WHERE province IS NOT NULL"),
        ("  ├─ 有城市信息", "SELECT COUNT(*) FROM sample_collections WHERE city IS NOT NULL"),
        ("  └─ 有大洲信息", "SELECT COUNT(*) FROM sample_collections WHERE continent IS NOT NULL"),
        ("", None),
        ("ORF总数(6-frame)", "SELECT COUNT(*) FROM reannotated_orfs"),
        ("ORF覆盖的分离株", "SELECT COUNT(DISTINCT isolate_id) FROM reannotated_orfs"),
        ("", None),
        ("NR精确匹配簇", "SELECT COUNT(*) FROM nr_protein_clusters"),
        ("NR CD-HIT 50%簇", "SELECT COUNT(DISTINCT cdhit50_cluster_id) FROM nr_protein_clusters WHERE cdhit50_cluster_id IS NOT NULL"),
        ("", None),
        ("基因组同一性对", "SELECT COUNT(*) FROM genome_pairwise_identity"),
        ("共线性块", "SELECT COUNT(*) FROM genome_synteny_blocks"),
        ("", None),
        ("诊断方法", "SELECT COUNT(*) FROM diagnostics"),
        ("控制方法", "SELECT COUNT(*) FROM control_methods"),
        ("", None),
        ("蛋白质结构(PDB)", "SELECT COUNT(*) FROM protein_structures"),
        ("蛋白质结构域注释", "SELECT COUNT(*) FROM protein_domains"),
        ("文献引用", "SELECT COUNT(*) FROM references"),
    ]

    for label, sql in queries:
        if sql is None:
            print()
            continue
        try:
            c.execute(sql)
            val = c.fetchone()[0]
            print(f"  {label:<32} {val:>10,}")
        except Exception as e:
            print(f"  {label:<32} 错误: {e}")

    # Key column inventory
    print()
    print("=" * 75)
    print(" 关键表结构速览（新增核心字段）")
    print("=" * 75)

    key_tables = [
        "viral_isolates",
        "crustacean_hosts",
        "sample_collections",
        "reannotated_orfs",
        "nr_protein_clusters",
        "genome_pairwise_identity",
        "diagnostics",
        "control_methods",
        "protein_structures",
        "protein_domains",
    ]

    for t in key_tables:
        if t not in tables:
            continue
        c.execute(f'PRAGMA table_info("{t}")')
        cols = c.fetchall()
        print(f"\n  [{t}] ({len(cols)} 字段)")
        for col in cols:
            name, typ, notnull, default = col[1], col[2], col[3], col[4]
            pk = "PK" if col[5] else ""
            null_str = "NOT NULL" if notnull else ""
            print(f"      {name:<28} {typ:<12} {null_str} {pk}")

    conn.close()
    print()
    print("=" * 75)
    print(" 数据库文件大小")
    print("=" * 75)
    size_mb = DB_PATH.stat().st_size / (1024 * 1024)
    print(f"  {DB_PATH.name}: {size_mb:.1f} MB")


if __name__ == "__main__":
    main()
