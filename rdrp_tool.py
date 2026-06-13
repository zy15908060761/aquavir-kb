"""
甲壳动物病毒 RDRP 序列工具
=======================
功能：
  1. 从数据库中识别并标记所有 RDRP 蛋白
  2. 导出 RDRP 序列为 FASTA（按物种筛选）
  3. 从 NCBI 搜索并下载新的 RDRP 序列
  4. RDRP 统计报告

用法：
  python rdrp_tool.py                   # 全流程：识别 → 标记 → 导出 + 统计
  python rdrp_tool.py --mark-only       # 只标记数据库中的 RDRP
  python rdrp_tool.py --export          # 只导出 FASTA
  python rdrp_tool.py --ncbi-search     # 搜索 NCBI 补充新序列
  python rdrp_tool.py --stats           # 只看统计
"""
import argparse
import re
import sqlite3
import time
from collections import Counter, defaultdict
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
DB_PATH = APP_DIR / "crustacean_virus_core.db"
SEQ_DIR = APP_DIR / "sequences"
EXPORT_DIR = APP_DIR / "downloads"

# ── 严格 RDRP 判定规则 ──────────────────────────────────────
# 蛋白名/基因名中含这些关键词 → 判定为 RDRP
RDRP_KEYWORDS = [
    "rna-dependent rna polymerase",
    "rna-directed rna polymerase",
    "rna replicase",
    "rdrp",
]

# 复制酶多聚蛋白也判定为 RDRP（包含 RdRp 结构域）
REPLICASE_KEYWORDS = [
    "replicase polyprotein",
    "replicase precursor",
    "replicase",
    "replication polyprotein",
    "orf1ab",
    "orf1a",
    "orf1b",
]

# 明确不是 RDRP 的排除关键词（即使包含上面的词）
NOT_RDRP_KEYWORDS = [
    "dna polymerase",
    "dna-directed",
    "dna dependent",
    "rna polymerase",   # DNA-directed RNA polymerase 是转录酶，不是 RdRp
]


def normalize_text(*values) -> str:
    return " ".join(str(v or "") for v in values).lower().strip()


def is_rna_genome(*genome_types) -> bool:
    text = normalize_text(*genome_types).replace(" ", "")
    return "rna" in text


def has_explicit_rdrp_name(protein_name: str, gene_symbol: str = "", note: str = "") -> bool:
    text = normalize_text(protein_name, gene_symbol, note)
    if "dna polymerase" in text or "dna-directed" in text or "dna dependent" in text:
        return False
    return (
        re.search(r"\brna[- ]dependent rna polymerase\b", text) is not None
        or re.search(r"\brna[- ]directed rna polymerase\b", text) is not None
        or "rna replicase" in text
        or re.search(r"\brdrp\b", text) is not None
    )


def is_rdrp(protein_name: str, gene_symbol: str = "") -> bool:
    """严格判断一个蛋白是否是 RDRP"""
    text = normalize_text(protein_name, gene_symbol)

    if not text:
        return False

    # ── 正向匹配：RDRP 关键词优先于排除规则 ──
    # RNA-dependent RNA polymerase 的各种写法
    if has_explicit_rdrp_name(protein_name, gene_symbol):
        return True

    # RdRp 基因名/缩写
    if " rdrp" in text or text.startswith("rdrp") or text == "rdrp":
        return True

    # ── 排除已知的非 RDRP（DNA 病毒相关）──
    # "dna polymerase" 和 "dna-directed" → DNA 病毒
    if "dna polymerase" in text or "dna-directed" in text or "dna dependent" in text:
        return False

    # 单独的 "rna polymerase" (没有 -dependent/-directed) → DNA-directed RNA polymerase（转录酶）
    if "rna polymerase" in text:
        # 但如果同时包含 "dependent" 或 "directed" → 是 RDRP
        if "dependent" not in text and "directed" not in text:
            return False

    # ── 复制酶多聚蛋白（含 RdRp 结构域）──
    if any(keyword in text for keyword in REPLICASE_KEYWORDS) and "initiation" not in text:
        return True

    # 含 polyprotein 且包含 replication 相关词 → 大概率含 RdRp
    if "polyprotein" in text and ("replicase" in text or "replication" in text):
        return True

    # 非结构蛋白多聚蛋白 → 含 RdRp（如 TSV 的 non-structural polyprotein）
    if "non-structural polyprotein" in text or "nonstructural polyprotein" in text:
        return True

    # 基因名为 L 或 pol → RNA 病毒常见 RdRp 基因名
    if gene_symbol and gene_symbol.strip().upper() in ("L", "POL", "RDRP"):
        return True

    return False


def add_rdrp_column(conn):
    """给 viral_proteins 表添加 is_rdrp 标记列"""
    c = conn.cursor()
    try:
        c.execute("ALTER TABLE viral_proteins ADD COLUMN is_rdrp INTEGER DEFAULT 0")
        print("[OK] is_rdrp 列已添加")
    except sqlite3.OperationalError:
        print("[OK] is_rdrp 列已存在")
    conn.commit()


def mark_rdrp(conn, reset_existing: bool = False):
    """识别并标记所有 RDRP 蛋白（仅 RNA 病毒）"""
    c = conn.cursor()

    if reset_existing:
        c.execute("UPDATE viral_proteins SET is_rdrp = 0")
        conn.commit()

    # 获取所有蛋白记录（关联病毒类型，RDRP 只存在于 RNA 病毒中）
    c.execute("""
        SELECT vp.protein_id, vp.protein_name, vp.gene_symbol, vp.translation,
               vi.genome_type AS isolate_genome_type,
               vm.genome_type AS master_genome_type,
               vm.canonical_name
        FROM viral_proteins vp
        JOIN viral_isolates vi ON vp.isolate_id = vi.isolate_id
        JOIN virus_master vm ON vi.master_id = vm.master_id
    """)
    all_proteins = c.fetchall()
    total = len(all_proteins)

    # 逐条判断
    marked = 0
    rdrp_ids = []
    explicit_without_rna_type = 0
    review_master_name_count = 0
    for pid, pname, gene, trans, isolate_gtype, master_gtype, vname in all_proteins:
        explicit = has_explicit_rdrp_name(pname, gene)
        is_rna = is_rna_genome(isolate_gtype, master_gtype)

        if not is_rdrp(pname, gene):
            continue

        # Strong RdRp names are allowed even when genome_type is missing or stale.
        # Weaker replicase/polyprotein/L/POL matches still need RNA genome context.
        if not explicit and not is_rna:
            continue

        rdrp_ids.append(pid)
        marked += 1
        if explicit and not is_rna:
            explicit_without_rna_type += 1
        if "white spot" in (vname or "").lower():
            review_master_name_count += 1

    if explicit_without_rna_type:
        print(f"  [Info] {explicit_without_rna_type} 个明确 RdRp 蛋白缺少 RNA genome_type，仍按蛋白名标记")
    if review_master_name_count:
        print(f"  [Review] {review_master_name_count} 个 RdRp 记录归到 White spot syndrome virus，请复核病毒名归一化")

    # 批量更新
    if rdrp_ids:
        # SQLite 限制每次 bind 参数数量，分批更新
        batch_size = 500
        for i in range(0, len(rdrp_ids), batch_size):
            batch = rdrp_ids[i:i + batch_size]
            placeholders = ",".join("?" * len(batch))
            c.execute(
                f"UPDATE viral_proteins SET is_rdrp = 1 WHERE protein_id IN ({placeholders})",
                batch,
            )
        conn.commit()

    print(f"[OK] RDRP 标记完成: {marked}/{total} 个蛋白符合当前规则")

    # 按物种输出概要
    c.execute("""
        SELECT vm.canonical_name, COUNT(vp.protein_id) as cnt
        FROM viral_proteins vp
        JOIN viral_isolates vi ON vp.isolate_id = vi.isolate_id
        JOIN virus_master vm ON vi.master_id = vm.master_id
        WHERE vp.is_rdrp = 1
        GROUP BY vm.canonical_name
        ORDER BY cnt DESC
    """)
    print("\nRDRP 按病毒物种分布:")
    for name, cnt in c.fetchall():
        print(f"  {name:45s} {cnt}")

    return marked


def export_rdrp_fasta(conn, species: str = "", output: str = ""):
    """导出 RDRP 氨基酸序列为 FASTA"""
    c = conn.cursor()

    where = "vp.is_rdrp = 1"
    params = []
    if species:
        where += " AND vm.canonical_name = ?"
        params.append(species)

    c.execute(f"""
        SELECT vi.accession, vm.canonical_name, vp.protein_name,
               vp.gene_symbol, vp.translation, vp.aa_length
        FROM viral_proteins vp
        JOIN viral_isolates vi ON vp.isolate_id = vi.isolate_id
        JOIN virus_master vm ON vi.master_id = vm.master_id
        WHERE {where}
        ORDER BY vm.canonical_name, vi.accession, vp.genome_start
    """, params)
    rows = c.fetchall()

    if not rows:
        print("[Warning] 没有找到 RDRP 序列")
        return

    # 构建 FASTA 内容
    # 使用 virus_name|accession|protein_name|gene_symbol 作为序列名
    fasta_lines = []
    for acc, vname, pname, gene, trans, aalen in rows:
        if not trans:
            continue
        header = f">{vname}|{acc}|{pname}|{gene or '-'}|{aalen or '?'}aa"
        fasta_lines.append(header)
        # 60 字符换行
        for i in range(0, len(trans), 60):
            fasta_lines.append(trans[i:i + 60])

    content = "\n".join(fasta_lines)

    # 确定输出路径
    if not output:
        if species:
            safe_name = re.sub(r'[\\/*?:"<>|]', "_", species).replace(" ", "_")
            output = str(EXPORT_DIR / f"rdrp_{safe_name}.fasta")
        else:
            output = str(EXPORT_DIR / "crustacean_virus_rdrp_all.fasta")

    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    Path(output).write_text(content, encoding="utf-8")

    print(f"[OK] 导出 {len(rows)} 条 RDRP 序列到: {output}")
    return output


def print_rdrp_stats(conn):
    """RDRP 统计报告"""
    c = conn.cursor()

    print("\n" + "=" * 60)
    print("甲壳动物病毒 RDRP 统计报告")
    print("=" * 60)

    c.execute("SELECT COUNT(*) FROM viral_proteins WHERE is_rdrp = 1")
    total = c.fetchone()[0]

    c.execute("SELECT COUNT(*) FROM viral_proteins")
    all_proteins = c.fetchone()[0]

    print(f"\nRDRP 蛋白总数: {total} / {all_proteins} ({total / all_proteins * 100:.1f}%)")

    c.execute("SELECT COUNT(DISTINCT vi.accession) FROM viral_proteins vp JOIN viral_isolates vi ON vp.isolate_id = vi.isolate_id WHERE vp.is_rdrp = 1")
    isolates_with_rdrp = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM viral_isolates")
    total_isolates = c.fetchone()[0]
    print(f"有 RDRP 注释的分离株: {isolates_with_rdrp}/{total_isolates}")

    c.execute("SELECT COUNT(DISTINCT vm.canonical_name) FROM viral_proteins vp JOIN viral_isolates vi ON vp.isolate_id = vi.isolate_id JOIN virus_master vm ON vi.master_id = vm.master_id WHERE vp.is_rdrp = 1")
    species_with_rdrp = c.fetchone()[0]
    print(f"有 RDRP 注释的病毒物种: {species_with_rdrp}")

    # 按物种的 RDRP 数量
    c.execute("""
        SELECT vm.canonical_name, COUNT(*) as cnt,
               COUNT(DISTINCT vp.protein_name) as distinct_names,
               vm.genome_type
        FROM viral_proteins vp
        JOIN viral_isolates vi ON vp.isolate_id = vi.isolate_id
        JOIN virus_master vm ON vi.master_id = vm.master_id
        WHERE vp.is_rdrp = 1
        GROUP BY vm.canonical_name
        ORDER BY cnt DESC
    """)
    print(f"\n按病毒物种分布 ({species_with_rdrp} 物种):")
    print(f"  {'病毒物种':40s} {'RDRP数':>8s} {'变体数':>8s} {'基因组':>10s}")
    print(f"  {'-'*40} {'-'*8} {'-'*8} {'-'*10}")
    for name, cnt, dnames, gtype in c.fetchall():
        print(f"  {name[:38]:40s} {cnt:8d} {dnames:8d} {str(gtype or '?'):>10s}")

    # RDRP 蛋白名变体
    c.execute("""
        SELECT vp.protein_name, COUNT(*) as cnt,
               COUNT(DISTINCT vm.canonical_name) as species_count
        FROM viral_proteins vp
        JOIN viral_isolates vi ON vp.isolate_id = vi.isolate_id
        JOIN virus_master vm ON vi.master_id = vm.master_id
        WHERE vp.is_rdrp = 1
        GROUP BY vp.protein_name
        ORDER BY cnt DESC
    """)
    print(f"\nRDRP 蛋白名变体:")
    for name, cnt, sc in c.fetchall():
        short = (name or "?").strip()[:50]
        print(f"  {short:50s} {cnt:5d} 条 ({sc} 个物种)")


def ncbi_search_rdrp():
    """从 NCBI 搜索甲壳动物病毒的 RDRP 序列

    返回搜索建议和 Entrez 查询字符串，供用户手动校验或自动下载。
    """
    print("\n" + "=" * 60)
    print("NCBI RDRP 搜索建议")
    print("=" * 60)

    # 按病毒种类分组的搜索策略
    searches = [
        {
            "label": "对虾类病毒 RDRP",
            "term": '(Penaeus[ORGN] OR Litopenaeus[ORGN] OR Fenneropenaeus[ORGN] OR Marsupenaeus[ORGN]) AND ("RNA-dependent RNA polymerase"[PROT] OR RdRp[GENE]) AND viruses[FILTER]',
        },
        {
            "label": "沼虾/螯虾类病毒 RDRP",
            "term": '(Macrobrachium[ORGN] OR Procambarus[ORGN] OR Cherax[ORGN] OR Pacifastacus[ORGN]) AND ("RNA-dependent RNA polymerase"[PROT] OR RdRp[GENE]) AND viruses[FILTER]',
        },
        {
            "label": "蟹类病毒 RDRP",
            "term": '(Carcinus[ORGN] OR Callinectes[ORGN] OR Scylla[ORGN] OR Eriocheir[ORGN] OR Portunus[ORGN] OR Cancer[ORGN]) AND ("RNA-dependent RNA polymerase"[PROT] OR RdRp[GENE]) AND viruses[FILTER]',
        },
        {
            "label": "宽泛搜索（补充捕获）",
            "term": '(crustacean[ORGN] OR decapod[ORGN]) AND ("RNA-dependent RNA polymerase"[PROT] OR replicase[PROT]) AND viruses[FILTER] AND 2020:2025[PDAT]',
        },
    ]

    for s in searches:
        print(f"\n  [{s['label']}]")
        print(f"    Query: {s['term']}")
        print(f"    NCBI URL: https://www.ncbi.nlm.nih.gov/protein/?term={s['term'].replace(' ', '+')}")

    # 生成可直接用于 esearch 的 Python 代码
    print("\n\n自动搜索代码片段（集成到 pipeline 中使用）:\n")
    print("""
    from Bio import Entrez
    Entrez.email = "your@email.com"

    for label, term in SEARCH_STRATEGIES:
        handle = Entrez.esearch(db="protein", term=term, retmax=500, idtype="acc")
        record = Entrez.read(handle)
        ids = record["IdList"]
        # ids 中排除已有数据库的
        # 用 efetch 下载 GenBank 格式 → 解析 CDS → 提取 RDRP → 导入
    """)

    return searches


def run_ncbi_import(conn, email: str = ""):
    """搜索 NCBI 下载甲壳动物病毒 RDRP 新序列"""
    if not email:
        print("[Skip] 未提供 email，跳过 NCBI 自动搜索")
        print("  用法: python rdrp_tool.py --ncbi-search --email your@email.com")
        ncbi_search_rdrp()
        return

    from Bio import Entrez, SeqIO
    Entrez.email = email
    Entrez.tool = "CrustaceanVirusRDRP"

    c = conn.cursor()

    # 获取已有蛋白 accession（去重用）
    c.execute("""
        SELECT DISTINCT protein_accession FROM viral_proteins
        WHERE protein_accession IS NOT NULL AND protein_accession != ''
    """)
    existing_prots = {r[0] for r in c.fetchall()}

    # 按宿主分组搜索
    search_queries = [
        ("对虾 RNA 病毒 RDRP",
         '(Penaeus[All Fields] OR Litopenaeus[All Fields] OR Fenneropenaeus[All Fields] OR Marsupenaeus[All Fields]) '
         'AND ("RNA-dependent RNA polymerase"[All Fields] OR RdRp[All Fields] OR "replicase polyprotein"[All Fields]) '
         'AND Virus[All Fields]'),
        ("螯虾/沼虾 RNA 病毒 RDRP",
         '(Macrobrachium[All Fields] OR Procambarus[All Fields] OR Cherax[All Fields] OR Pacifastacus[All Fields]) '
         'AND ("RNA-dependent RNA polymerase"[All Fields] OR RdRp[All Fields] OR "replicase polyprotein"[All Fields]) '
         'AND Virus[All Fields]'),
        ("蟹类 RNA 病毒 RDRP",
         '(Scylla[All Fields] OR Eriocheir[All Fields] OR Portunus[All Fields] OR Callinectes[All Fields] OR Carcinus[All Fields]) '
         'AND ("RNA-dependent RNA polymerase"[All Fields] OR RdRp[All Fields] OR "replicase polyprotein"[All Fields]) '
         'AND Virus[All Fields]'),
        ("宽泛甲壳动物 RNA 病毒 RDRP",
         '(decapod[All Fields] OR crustacean[All Fields]) '
         'AND ("RNA-dependent RNA polymerase"[All Fields] OR RdRp[All Fields]) '
         'AND Virus[All Fields] AND 2020:2026[Date - Publication]'),
    ]

    print("=" * 60)
    print("NCBI RDRP 搜索和下载")
    print("=" * 60)

    all_new_ids = []
    for label, term in search_queries:
        print(f"\n[{label}]")
        try:
            handle = Entrez.esearch(db="protein", term=term, retmax=500, idtype="acc")
            record = Entrez.read(handle)
            handle.close()
            ids = record.get("IdList", [])
        except Exception as e:
            print(f"  搜索失败: {e}")
            continue

        new_ids = [pid for pid in ids if pid not in existing_prots]
        all_new_ids.extend(new_ids)
        print(f"  找到 {len(ids)} 条, 新 {len(new_ids)} 条")
        time.sleep(0.8)

    # 去重
    all_new_ids = list(set(all_new_ids))
    print(f"\n总共新发现 {len(all_new_ids)} 条蛋白序列")

    if not all_new_ids:
        print("数据库已是最新，没有新序列。")
        return

    # ── 下载 FASTA ──
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    fasta_path = str(EXPORT_DIR / "ncbi_rdrp_candidates.fasta")

    print(f"\n下载新序列到 {fasta_path} ...")
    downloaded = 0
    skipped = 0

    with open(fasta_path, "w", encoding="utf-8") as f:
        for i in range(0, len(all_new_ids), 100):
            batch = all_new_ids[i:i + 100]
            try:
                handle = Entrez.efetch(db="protein", id=batch, rettype="fasta", retmode="text")
                fasta_data = handle.read()
                handle.close()

                # 统计这次下载了多少条（> 开头的行数）
                seq_count = fasta_data.count(">")
                f.write(fasta_data)
                if not fasta_data.endswith("\n"):
                    f.write("\n")
                downloaded += seq_count
                print(f"  批次 {i // 100 + 1}/{(len(all_new_ids) - 1) // 100 + 1}: 下载 {seq_count} 条")
                time.sleep(0.5)
            except Exception as e:
                print(f"  批次 {i // 100 + 1} 下载失败: {e}")
                skipped += len(batch)
                time.sleep(2)

    print(f"\n[OK] 下载完成: {downloaded} 条新序列")
    if skipped:
        print(f"[Warn] 跳过 {skipped} 条下载失败的")

    # ── 附：同时下载 GenBank 格式以便后续导入 ──
    gb_path = str(EXPORT_DIR / "ncbi_rdrp_candidates.gb")
    print(f"\n下载 GenBank 格式到 {gb_path} ...")
    gb_count = 0
    with open(gb_path, "w", encoding="utf-8") as f:
        for i in range(0, len(all_new_ids), 50):
            batch = all_new_ids[i:i + 50]
            try:
                handle = Entrez.efetch(db="protein", id=batch, rettype="gb", retmode="text")
                gb_data = handle.read()
                handle.close()
                f.write(gb_data)
                if not gb_data.endswith("\n"):
                    f.write("\n")
                gb_count += gb_data.count("LOCUS")
                print(f"  批次 {i // 50 + 1}/{(len(all_new_ids) - 1) // 50 + 1}: {gb_data.count('LOCUS')} 条")
                time.sleep(0.8)
            except Exception as e:
                print(f"  批次 {i // 50 + 1} 下载失败: {e}")
                time.sleep(2)

    print(f"\n{'=' * 60}")
    print(f"NCBI 搜索完成!")
    print(f"  FASTA: {fasta_path} ({downloaded} 条)")
    print(f"  GenBank: {gb_path} ({gb_count} 条)")
    print(f"  运行 'python rdrp_tool.py --stats' 查看当前 RDRP 统计")
    print(f"{'=' * 60}")


# ── 主入口 ──────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="甲壳动物病毒 RDRP 序列工具")
    parser.add_argument("--mark-only", action="store_true", help="仅标记数据库中的 RDRP")
    parser.add_argument("--export", type=str, nargs="?", const="all", help="导出 RDRP FASTA（可选指定物种名）")
    parser.add_argument("--output", type=str, default="", help="导出文件路径")
    parser.add_argument("--ncbi-search", action="store_true", help="搜索 NCBI RDRP")
    parser.add_argument("--email", type=str, default="", help="NCBI Entrez 邮箱（用于自动搜索）")
    parser.add_argument("--stats", action="store_true", help="查看 RDRP 统计")
    args = parser.parse_args()

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row

    # 默认模式：全流程
    if not any([args.mark_only, args.export, args.ncbi_search, args.stats]):
        print("=" * 60)
        print("甲壳动物病毒 RDRP 序列工具 - 全流程")
        print("=" * 60)

        print("\n[1/4] 添加 is_rdrp 标记列...")
        add_rdrp_column(conn)

        print("\n[2/4] 识别并标记 RDRP 蛋白...")
        mark_rdrp(conn)

        print("\n[3/4] 导出全部 RDRP FASTA...")
        export_rdrp_fasta(conn)

        print("\n[4/4] RDRP 统计报告...")
        print_rdrp_stats(conn)

        print("\n" + "=" * 60)
        print("全流程完成！")
        print(f"  FASTA: {EXPORT_DIR / 'crustacean_virus_rdrp_all.fasta'}")
        print(f"  可用命令:")
        print(f"    python rdrp_tool.py --export WSSV      # 按物种导出")
        print(f"    python rdrp_tool.py --ncbi-search      # 搜索新序列")
        print(f"    python rdrp_tool.py --stats            # 查看统计")
        print("=" * 60)

    elif args.mark_only:
        add_rdrp_column(conn)
        mark_rdrp(conn)

    elif args.export:
        species = None if args.export == "all" else args.export
        add_rdrp_column(conn)
        # 确保标记过
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM viral_proteins WHERE is_rdrp = 1")
        if c.fetchone()[0] == 0:
            print("[Info] 尚未标记 RDRP，先执行标记...")
            mark_rdrp(conn)
        export_rdrp_fasta(conn, species=species or "", output=args.output)

    elif args.ncbi_search:
        run_ncbi_import(conn, email=args.email)

    elif args.stats:
        print_rdrp_stats(conn)

    conn.close()


if __name__ == "__main__":
    main()
