"""
从 GenBank 文件提取 CDS/ORF 蛋白注释，构建 viral_proteins 表和 core_genes 表。

用法:
    python annotate_proteins.py          # 完整运行（从GB解析+建表+插入）
    python annotate_proteins.py --stats  # 只查看当前蛋白统计
"""
import argparse
import re
import sqlite3
import sys
import time
from collections import defaultdict
from pathlib import Path

from Bio import SeqIO

APP_DIR = Path(__file__).resolve().parent
DB_PATH = APP_DIR / "crustacean_virus_core.db"
GB_FILE = APP_DIR / "ncbi_metadata" / "crustacean_virus_raw.gb"


# ── 功能分类关键词映射 ──────────────────────────────────────────
FUNCTION_CATEGORY_RULES = [
    # (keywords, category)
    # 结构蛋白
    (["coat protein", "capsid", "nucleocapsid", "core protein", "matrix",
      "envelope", "spike", "peplomer", "tegument", "virion protein",
      "VP1", "VP2", "VP3", "VP4", "VP5", "VP6", "VP7", "VP8", "VP9",
      "VP10", "VP11", "VP12", "VP13", "VP14", "VP15", "VP16",
      "outer membrane", "inner membrane", "membrane protein",
      "fiber protein", "pilus", "fimbrial",
      "surface protein", "surface antigen",
      "head protein", "tail protein", "baseplate", "portal",
      "p22", "p23", "p24", "p25", "p26", "p28",
      "viral protein", "hypothetical structural",
      "virion-associated", "virion structural"], "structural"),

    # 复制/转录/翻译
    (["polymerase", "replicase", "helicase", "primase", "topoisomerase",
      "integrase", "ligase", "nuclease", "endonuclease", "exonuclease",
      "rnase", "dnase", "ribonuclease", "deoxyribonuclease",
      "rna-dependent rna polymerase", "reverse transcriptase",
      "dna polymerase", "rna polymerase",
      "transcriptase", "transcription factor",
      "elongation factor", "initiation factor",
      "ribosomal protein", "ribosome",
      "mrna capping", "poly(a) polymerase",
      "replication", "replication-associated",
      "replication initiation", "replication origin binding",
      "dna binding protein", "rna binding protein",
      "ssb", "single-strand binding",
      "clamp loader", "sliding clamp",
      "dna-directed", "rna-directed",
      "genome-linked", "vp-g", "vpglink",
      # 多聚蛋白（病毒 polyprotein 含 RdRp 结构域）
      "non-structural polyprotein", "nonstructural polyprotein",
      "non-structural protein", "nonstructural protein",
      "polyprotein precursor", "large polyprotein",
      # 复制酶相关
      "replicase polyprotein", "replicase precursor",
      "orf1ab", "orf1a", "orf1b",
      "pp1ab", "pp1a"], "replication"),

    # 包装/组装/蛋白酶
    (["protease", "proteinase", "peptidase",
      "terminase", "packaging", "encapsidation",
      "scaffold", "maturation", "assembly",
      "chaperone", "heat shock",
      "transporter", "atpase", "atp-binding",
      "motor protein", "portal protein",
      "dsdna binding", "packaging",
      "dna packaging", "rna packaging",
      "cleavage", "maturational"], "assembly"),

    # 免疫调节/宿主互作
    (["anti-apoptosis", "apoptosis", "apoptotic",
      "immune", "immune evasion", "immune suppression",
      "interferon", "cytokine", "chemokine",
      "host range", "virulence factor", "pathogenicity",
      "toxin", "enterotoxin", "neurotoxin",
      "fc receptor", "complement",
      "mhc", "t cell", "b cell",
      "signal transduction", "kinase", "phosphatase",
      "growth factor", "receptor",
      "host shutoff", "host cell",
      "anti-", "suppressor",
      "dUTPase", "dutp",
      "immunoglobulin", "ig-domain",
      "serpin", "serine protease inhibitor",
      "ubiquitin", "sumo", "nedd", "proteasome",
      "ranbp2", "nuclear transport",
      "sh2 domain", "sh3 domain",
      "ankyrin", "arm repeat", "leucine-rich repeat",
      "ig-like", "fn3", "fibronectin"], "host_interaction"),

    # 核苷酸/核酸代谢
    (["thymidine kinase", "thymidylate synthase",
      "dihydrofolate reductase", "dhfr",
      "ribonucleotide reductase", "rr",
      "dna methyltransferase", "methylase",
      "uracil-dna glycosylase", "udg",
      "dutpase", "dutp pyrophosphatase",
      "deoxyuridine", "deoxythymidine",
      "nucleotide kinase", "phosphorylase",
      "nucleoside triphosphatase", "ntpase",
      "guanylyltransferase", "guanylate kinase",
      "adenylate kinase", "atpase",
      "nrd", "nucleotide reductase",
      "nicotinamidase", "nad-dependent",
      "sir2", "sirtuin",
      "nucleotidyltransferase",
      "phosphotransferase"], "metabolism"),

    # 未知功能
    (["hypothetical protein", "uncharacterized",
      "unknown", "putative uncharacterized",
      "orf", "unknown function",
      "conserved protein", "uncharacterized protein"], "unknown"),
]


def classify_function(product_name: str, gene_symbol: str = "") -> str:
    """根据产物名称和基因符号分类蛋白功能"""
    text = f"{product_name or ''} {gene_symbol or ''}".lower()

    # 优先匹配规则
    for keywords, category in FUNCTION_CATEGORY_RULES:
        for kw in keywords:
            if kw in text:
                return category

    return "unknown"


def extract_proteins_from_gb() -> list[dict]:
    """解析 GenBank 文件中所有 CDS 特征"""
    if not GB_FILE.exists():
        print(f"[Error] GenBank 文件未找到: {GB_FILE}")
        return []

    records = []
    total_cds = 0
    skipped = 0

    for rec in SeqIO.parse(str(GB_FILE), "genbank"):
        accession = rec.id
        # 有些记录 accession 带版本号，去掉 .1 .2 等
        acc_clean = accession.split(".")[0]

        # 检查 CDS 特征
        for feat in rec.features:
            if feat.type != "CDS":
                continue

            quals = feat.qualifiers
            protein_id = quals.get("protein_id", [""])[0]
            product = quals.get("product", [""])[0]
            gene = quals.get("gene", [""])[0]
            translation = quals.get("translation", [""])[0]
            locus_tag = quals.get("locus_tag", [""])[0]
            note = quals.get("note", [""])[0]
            ec_number = quals.get("EC_number", [""])[0]

            # 计算位置（可能存在  join 情况，取总长度）
            try:
                # Simple case: single location
                loc = feat.location
                aa_length = len(loc) // 3  # DNA length / 3 = AA length
                start = int(loc.start) + 1  # 1-based
                end = int(loc.end)
            except Exception:
                aa_length = len(translation) if translation else 0
                start = 0
                end = 0

            # 如果没有翻译序列，尝试从 location 推导长度
            if not translation and aa_length == 0:
                skipped += 1
                continue

            if not translation:
                aa_length = aa_length
            else:
                aa_length = len(translation)

            func_cat = classify_function(product, gene)
            records.append({
                "accession": acc_clean,
                "protein_accession": protein_id,
                "protein_name": product,
                "gene_symbol": gene,
                "locus_tag": locus_tag,
                "aa_length": aa_length if aa_length else (len(translation) if translation else None),
                "genome_start": start,
                "genome_end": end,
                "translation": translation,
                "ec_number": ec_number,
                "note": note,
                "functional_category": func_cat,
            })
            total_cds += 1

    print(f"  解析到 {total_cds} 个 CDS，跳过 {skipped} 个无翻译序列的记录")
    return records


def create_protein_tables(conn):
    """创建蛋白注释表和核心基因表"""
    c = conn.cursor()

    c.executescript("""
    CREATE TABLE IF NOT EXISTS viral_proteins (
        protein_id INTEGER PRIMARY KEY AUTOINCREMENT,
        isolate_id INTEGER NOT NULL,
        protein_accession VARCHAR(50),
        protein_name VARCHAR(500),
        gene_symbol VARCHAR(100),
        locus_tag VARCHAR(100),
        aa_length INTEGER,
        genome_start INTEGER,
        genome_end INTEGER,
        translation TEXT,
        ec_number VARCHAR(50),
        note TEXT,
        functional_category VARCHAR(50) DEFAULT 'unknown',
        FOREIGN KEY (isolate_id) REFERENCES viral_isolates(isolate_id)
    );

    CREATE TABLE IF NOT EXISTS core_genes (
        gene_id INTEGER PRIMARY KEY AUTOINCREMENT,
        virus_species VARCHAR(200) NOT NULL,
        gene_symbol VARCHAR(100),
        protein_name VARCHAR(500),
        functional_category VARCHAR(50),
        conservation_rate REAL,
        total_isolates INTEGER,
        present_isolates INTEGER,
        avg_identity REAL,
        function_summary TEXT,
        UNIQUE(virus_species, gene_symbol)
    );

    CREATE INDEX IF NOT EXISTS idx_vp_isolate_id ON viral_proteins(isolate_id);
    CREATE INDEX IF NOT EXISTS idx_vp_accession ON viral_proteins(protein_accession);
    CREATE INDEX IF NOT EXISTS idx_vp_gene ON viral_proteins(gene_symbol);
    CREATE INDEX IF NOT EXISTS idx_vp_category ON viral_proteins(functional_category);
    CREATE INDEX IF NOT EXISTS idx_cg_species ON core_genes(virus_species);
    """)

    conn.commit()
    print("[OK] 蛋白表 viral_proteins 和 core_genes 创建完成")


def populate_proteins(conn, proteins: list[dict]):
    """将 CDS 注释插入 viral_proteins 表"""
    c = conn.cursor()

    # 获取 accession → isolate_id 映射（同时存带版本号和不带版本号两种 key）
    c.execute("SELECT isolate_id, accession FROM viral_isolates")
    acc_map = {}
    for iid, acc in c.fetchall():
        acc_map[acc] = iid                    # 原始值（可能带 .1，也可能不带）
        base = acc.split(".")[0]
        if base not in acc_map:               # 避免覆盖不带 .1 的原始值
            acc_map[base] = iid

    records = []
    skipped_no_isolate = 0
    for p in proteins:
        acc = p["accession"]
        isolate_id = acc_map.get(acc)
        if isolate_id is None:
            isolate_id = acc_map.get(acc.split(".")[0])
        if isolate_id is None:
            skipped_no_isolate += 1
            continue

        records.append((
            isolate_id,
            p["protein_accession"],
            p["protein_name"],
            p["gene_symbol"],
            p["locus_tag"],
            p["aa_length"],
            p["genome_start"],
            p["genome_end"],
            p["translation"],
            p["ec_number"],
            p["note"],
            p["functional_category"],
        ))

    if not records:
        print("[Warning] 没有可插入的蛋白记录")
        return

    c.executemany("""
        INSERT INTO viral_proteins
        (isolate_id, protein_accession, protein_name, gene_symbol, locus_tag,
         aa_length, genome_start, genome_end, translation, ec_number, note,
         functional_category)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, records)
    conn.commit()
    print(f"[OK] 插入 {len(records)} 条蛋白记录 (跳过 {skipped_no_isolate} 个未匹配到分离株的)")


def compute_core_genes(conn):
    """计算每种病毒的核心基因（在所有分离株中出现的基因）

    核心基因定义:
    - conservation_rate >= 80%: 核心基因 (Core)
    - 50% <= conservation_rate < 80%: 选择性基因 (Selective)
    - conservation_rate < 50%: 附属基因 (Accessory)
    """
    c = conn.cursor()

    # 清空 core_genes 表 (intentional: repopulating the entire staging table)
    c.execute("DELETE FROM core_genes")

    # 获取所有病毒物种及其分离株计数
    c.execute("""
        SELECT vm.master_id, vm.canonical_name
        FROM virus_master vm
        WHERE vm.is_crustacean_virus = 1
          AND vm.entry_type NOT IN ('EST', 'patent', 'non_target', 'unknown')
          AND EXISTS (
              SELECT 1 FROM viral_isolates vi
              WHERE vi.master_id = vm.master_id
              AND EXISTS (SELECT 1 FROM viral_proteins vp WHERE vp.isolate_id = vi.isolate_id)
          )
    """)
    species_list = c.fetchall()

    if not species_list:
        print("[Warning] 没有找到有蛋白注释的病毒物种")
        return

    # 遍历每种病毒
    total_core = 0
    for master_id, species_name in species_list:
        # 获取该物种的所有 isolate_id
        c.execute("""
            SELECT isolate_id FROM viral_isolates
            WHERE master_id = ?
              AND isolate_id IN (SELECT DISTINCT isolate_id FROM viral_proteins)
        """, (master_id,))
        isolate_ids = [r[0] for r in c.fetchall()]
        total_isolates = len(isolate_ids)

        if total_isolates < 2:
            # 只有一个分离株，跳过核心基因分析
            continue

        # 计算每个基因在所有分离株中出现的次数
        # 这里按 gene_symbol 聚合，如果 gene_symbol 为空则用 protein_name 聚合
        c.execute("""
            SELECT
                COALESCE(NULLIF(gene_symbol, ''), protein_name) as gene_key,
                protein_name,
                gene_symbol,
                functional_category,
                COUNT(DISTINCT isolate_id) as present_count
            FROM viral_proteins
            WHERE isolate_id IN ({})
            GROUP BY gene_key
        """.format(",".join("?" * len(isolate_ids))), isolate_ids)

        gene_stats = c.fetchall()

        for gene_key, protein_name, gene_symbol, func_cat, present_count in gene_stats:
            if not gene_key:
                continue
            conservation_rate = present_count / total_isolates * 100.0

            # 构建功能摘要
            function_summary = ""
            if conservation_rate >= 80:
                if gene_symbol:
                    function_summary = f"核心基因: {gene_symbol}"
                function_summary += f" | 在 {total_isolates} 个分离株中 {present_count} 个出现 ({conservation_rate:.0f}%)"

            c.execute("""
                INSERT OR REPLACE INTO core_genes
                (virus_species, gene_symbol, protein_name, functional_category,
                 conservation_rate, total_isolates, present_isolates, function_summary)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                species_name,
                gene_symbol or gene_key,
                protein_name or "",
                func_cat,
                round(conservation_rate, 1),
                total_isolates,
                present_count,
                function_summary,
            ))
            total_core += 1

    conn.commit()
    print(f"[OK] 计算了 {len(species_list)} 个病毒物种的 {total_core} 个基因保守性数据")


def print_stats(conn):
    """打印蛋白注释统计"""
    c = conn.cursor()

    print("\n" + "=" * 60)
    print("蛋白注释统计")
    print("=" * 60)

    c.execute("SELECT COUNT(*) FROM viral_proteins")
    total_proteins = c.fetchone()[0]
    print(f"\n总蛋白数: {total_proteins}")

    c.execute("SELECT COUNT(DISTINCT isolate_id) FROM viral_proteins")
    isolates_with_proteins = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM viral_isolates")
    total_isolates = c.fetchone()[0]
    print(f"有蛋白注释的分离株: {isolates_with_proteins}/{total_isolates} ({isolates_with_proteins/total_isolates*100:.1f}%)")

    c.execute("""
        SELECT functional_category, COUNT(*) as cnt
        FROM viral_proteins
        GROUP BY functional_category
        ORDER BY cnt DESC
    """)
    print("\n功能分类:")
    for cat, cnt in c.fetchall():
        print(f"  {cat:25s}: {cnt:5d} ({cnt/total_proteins*100:.1f}%)")

    c.execute("""
        SELECT vm.canonical_name, COUNT(vp.protein_id) as cnt
        FROM viral_proteins vp
        JOIN viral_isolates vi ON vp.isolate_id = vi.isolate_id
        JOIN virus_master vm ON vi.master_id = vm.master_id
        GROUP BY vm.canonical_name
        ORDER BY cnt DESC
        LIMIT 15
    """)
    print("\nTop 15 病毒物种 (按蛋白数):")
    for name, cnt in c.fetchall():
        print(f"  {name:45s}: {cnt:5d}")

    c.execute("SELECT COUNT(*) FROM core_genes")
    core_count = c.fetchone()[0]
    print(f"\n核心/保守基因条目: {core_count}")

    c.execute("""
        SELECT virus_species, COUNT(*) as cnt,
               ROUND(AVG(conservation_rate), 1) as avg_conservation
        FROM core_genes
        GROUP BY virus_species
        ORDER BY cnt DESC
        LIMIT 10
    """)
    print("\nTop 10 病毒物种 (按保守基因数):")
    for name, cnt, avg_cons in c.fetchall():
        print(f"  {name:45s}: {cnt:3d} 个保守基因, 平均保守率 {avg_cons}%")


def run():
    parser = argparse.ArgumentParser(description="病毒蛋白/CDS 注释工具")
    parser.add_argument("--stats", action="store_true", help="仅查看统计，不执行抽取")
    args = parser.parse_args()

    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA foreign_keys = ON")

    if args.stats:
        print_stats(conn)
        conn.close()
        return

    print("=" * 60)
    print("构建病毒蛋白注释层")
    print("=" * 60)

    # Step 1: 创建表
    print("\n[1/4] 创建蛋白表结构...")
    create_protein_tables(conn)
    print(f"     DB: {DB_PATH}")

    # Step 2: 从 GenBank 提取 CDS
    print("\n[2/4] 从 GenBank 文件提取 CDS/ORF...")
    print(f"     GB: {GB_FILE}")
    proteins = extract_proteins_from_gb()

    if not proteins:
        print("[Error] 没有提取到蛋白数据，终止")
        conn.close()
        return

    print(f"     共提取 {len(proteins)} 个 CDS/蛋白")

    # Step 3: 插入数据库
    print("\n[3/4] 插入蛋白数据到数据库...")
    populate_proteins(conn, proteins)

    # Step 4: 计算核心基因
    print("\n[4/4] 计算病毒核心保守基因...")
    compute_core_genes(conn)

    # 统计摘要
    print_stats(conn)

    conn.close()

    print("\n" + "=" * 60)
    print("蛋白注释层构建完成!")
    print(f"运行 'python {Path(__file__).name} --stats' 可随时查看统计")
    print("=" * 60)


if __name__ == "__main__":
    run()
