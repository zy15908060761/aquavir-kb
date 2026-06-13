"""
导入 NCBI 下载的 RDRP 候选序列到数据库 v2
策略：
  1. 排除已知非甲壳动物病毒（鱼类病毒等）
  2. 已知病毒名 → 匹配现有 virus_master
  3. 未知病毒名 → 自动创建 virus_master + viral_isolates 记录
  4. 全部标记为 RDRP

用法:
    python import_ncbi_rdrp.py                  # 全流程导入
    python import_ncbi_rdrp.py --dry-run        # 预览
    python import_ncbi_rdrp.py --stats          # 看统计
"""
import re
import sqlite3
from collections import Counter
from pathlib import Path

from Bio import SeqIO

APP_DIR = Path(__file__).resolve().parent
DB_PATH = APP_DIR / "crustacean_virus_core.db"
GB_FILE = APP_DIR / "downloads" / "ncbi_rdrp_candidates.gb"

# ── 明确不是甲壳动物病毒的排除列表 ──────────────────────────
EXCLUDE_VIRUS_PATTERNS = [
    "viral hemorrhagic septicemia",   # 鱼类病毒
    "infectious hematopoietic necrosis",  # 鱼类病毒 (IHNV ≠ IHHNV)
    "salmon",                         # 鲑鱼病毒
    "trout",                          # 鳟鱼病毒
    "human immuno",                   # 人类病毒
    "influenza",                      # 流感
    "sars-cov",                       # 新冠
    "rainbow trout",                  # 虹鳟鱼
    "channel catfish",                # 鲶鱼
    "frog virus",                     # 蛙病毒
    "ambystoma",                      # 蝾螈病毒
    "lymphocystis",                   # 鱼类病毒
    "oncorhynchus",                   # 大麻哈鱼属（宿主名而非病毒名时）
    "ictalurid",                      # 鲶鱼病毒
    "cyprinid",                       # 鲤鱼病毒
    "vibrio parahaemolyticus",        # 细菌，不是病毒
]


def is_excluded(ncbi_name: str) -> bool:
    lower = ncbi_name.lower()
    for pat in EXCLUDE_VIRUS_PATTERNS:
        if pat in lower:
            return True
    return False


# ── 已知病毒名 → 标准名映射 ──────────────────────────────────
KNOWN_VIRUS_MAP = {
    "laem singh virus": "Laem-Singh virus",
    "laem-singh virus": "Laem-Singh virus",
    "covert mortality nodavirus": "Covert mortality nodavirus",
    "macrobrachium rosenbergii nodavirus": "Macrobrachium rosenbergii nodavirus",
    "infectious myonecrosis virus": "Infectious myonecrosis virus",
    "penaeid shrimp infectious myonecrosis virus": "Infectious myonecrosis virus",
    "taura syndrome virus": "Taura syndrome virus",
    "yellow head virus": "Yellow head virus",
    "white spot syndrome virus": "White spot syndrome virus",
    "infectious hypodermal and hematopoietic necrosis virus": "Infectious hypodermal and hematopoietic necrosis virus",
    "decapod iridescent virus": "Decapod iridescent virus",
    "beihai shrimp virus": "Beihai shrimp virus",
    "beihai crab virus": "Beihai crab virus",
    "wenzhou shrimp virus": "Wenzhou shrimp virus",
    "wenzhou crab virus": "Wenzhou crab virus",
    "chinese mitten crab virus": "Chinese mitten crab virus",
    "crab associated circular virus": "Crab associated circular virus",
    "mourilyan virus": "Mourilyan virus",
    "infectious precocity virus": "Infectious precocity virus",
    "iridovirus cn01": "Iridovirus CN01",
    "mud crab virus": "Mud crab virus",
    "european shore crab virus 1": "European shore crab virus 1",
}


def normalize_name(ncbi_name: str) -> str | None:
    """已知病毒 → 标准名，未知病毒 → 保留原名作为新物种"""
    lower = ncbi_name.lower().strip()
    if lower in KNOWN_VIRUS_MAP:
        return KNOWN_VIRUS_MAP[lower]

    # 包含已知关键词
    for pattern, canonical in [
        ("laem singh", "Laem-Singh virus"),
        ("iridovirus", "Iridovirus CN01"),
    ]:
        if pattern in lower:
            return canonical

    # 未知病毒：保留原名，清理一下格式
    name = ncbi_name.strip()
    # 首字母大写
    if name and name[0].islower():
        name = name[0].upper() + name[1:]
    return name


def get_virus_host(record) -> str:
    """从记录提取宿主名称"""
    for feat in record.features:
        if feat.type == "source":
            host = feat.qualifiers.get("host", [""])[0]
            if host:
                return host
    # fallback: 从 organism 行看是否包含宿主名
    return ""


def get_genome_type(record) -> str:
    """从分类信息推断基因组类型"""
    org = record.annotations.get("organism", "")
    tax = str(record.annotations.get("taxonomy", ""))
    tax_lower = tax.lower()

    if "ssrna" in tax_lower:
        if "negative" in tax_lower or "-" in [t[0] for t in tax.split(";")]:
            pass  # 下面细分类
    if "dsrna" in tax_lower or "dsrna" in str(record.features):
        return "dsRNA"
    if "ssrna" in tax_lower or "riboviria" in tax_lower:
        return "+ssRNA"  # 大部分甲壳动物 RNA 病毒是 +ssRNA
    if "dsdna" in tax_lower:
        return "dsDNA"
    return "+ssRNA"  # 默认


def parse_records() -> list[dict]:
    """解析 GenBank 文件，返回可用记录"""
    if not GB_FILE.exists():
        print(f"[Error] GenBank file not found: {GB_FILE}")
        return []

    records = []
    excluded = 0
    virus_counter = Counter()

    for rec in SeqIO.parse(str(GB_FILE), "genbank"):
        virus_name = rec.annotations.get("organism", "").strip()
        if not virus_name:
            continue

        # 排除非甲壳动物病毒
        if is_excluded(virus_name):
            excluded += 1
            continue

        protein_acc = rec.id
        description = rec.description.replace(virus_name, "").strip().strip("[]")
        seq = str(rec.seq) if rec.seq else ""
        aa_len = len(seq)

        if aa_len < 50:  # 太短的不太可能是真正的 RDRP
            continue

        # 从 source 提取宿主
        host_name = get_virus_host(rec)

        # 从 CDS 提取 coded_by（nucleotide accession）
        coded_by = None
        product = description
        for feat in rec.features:
            if feat.type == "CDS":
                product = feat.qualifiers.get("product", [description])[0]
                coded_by = feat.qualifiers.get("coded_by", [None])[0]
                break

        nucl_acc = None
        if coded_by:
            nucl_acc = coded_by.split(":")[0].split(".")[0]

        canonical = normalize_name(virus_name)

        records.append({
            "protein_acc": protein_acc,
            "virus_name": virus_name,
            "canonical_name": canonical,
            "product": product,
            "aa_seq": seq,
            "aa_length": aa_len,
            "host_name": host_name,
            "nucl_acc": nucl_acc,
        })
        virus_counter[canonical] += 1

    print(f"[Parse] 总记录: {len(records) + excluded}, 排除: {excluded}, 可用: {len(records)}")
    print(f"        涉及 {len(virus_counter)} 种病毒")

    # 显示分组
    known = sum(1 for r in records if r["virus_name"].lower() in KNOWN_VIRUS_MAP)
    new_known = sum(1 for r in records if r["virus_name"].lower() not in KNOWN_VIRUS_MAP
                    and any(pat in r["virus_name"].lower() for pat in ["qianjiang", "eriocheir", "scylla", "portunus", "callinectes", "macrobrachium", "shahe", "brine shrimp", "beihai", "wenzhou", "changjiang", "sanya", "hubei", "athtab"]))
    other = len(records) - known - new_known

    print(f"        已知病毒: {known}")
    print(f"        新发现甲壳病毒: {new_known}")
    print(f"        其他: {other}")

    print(f"\nTop 15 病毒:")
    for name, cnt in virus_counter.most_common(15):
        marker = " [known]" if name in KNOWN_VIRUS_MAP.values() else ""
        print(f"  {cnt:4d}  {name[:55]:55s}{marker}")

    return records


def import_records(records: list[dict], dry_run: bool = False):
    """导入到数据库"""
    conn = sqlite3.connect(str(DB_PATH))
    c = conn.cursor()

    # 获取现有数据
    c.execute("SELECT canonical_name, master_id FROM virus_master")
    master_map = {name: mid for name, mid in c.fetchall()}

    c.execute("SELECT accession, isolate_id FROM viral_isolates")
    isolate_map = {acc: iid for acc, iid in c.fetchall()}

    c.execute("SELECT protein_accession FROM viral_proteins WHERE protein_accession IS NOT NULL")
    existing_prots = {r[0] for r in c.fetchall()}

    stats = {
        "known_master_match": 0,
        "new_master_created": 0,
        "existing_isolate": 0,
        "new_isolate": 0,
        "proteins_inserted": 0,
        "skipped_dup": 0,
    }
    new_species = Counter()

    for i, rec in enumerate(records):
        protein_acc = rec["protein_acc"]
        canonical = rec["canonical_name"]
        nucl_acc = rec["nucl_acc"]

        # 跳过重复
        if protein_acc in existing_prots:
            stats["skipped_dup"] += 1
            continue

        # Step 1: master_id
        master_id = master_map.get(canonical)
        if master_id is None:
            if not dry_run:
                c.execute(
                    "INSERT INTO virus_master (canonical_name, entry_type, is_crustacean_virus, genome_type) VALUES (?, 'complete_genome', 1, '+ssRNA')",
                    (canonical,),
                )
                master_id = c.lastrowid
                master_map[canonical] = master_id
                stats["new_master_created"] += 1
                new_species[canonical] += 1
            else:
                continue
        else:
            stats["known_master_match"] += 1

        # Step 2: isolate_id
        isolate_acc = nucl_acc or f"RDRP_{protein_acc}"
        isolate_id = isolate_map.get(isolate_acc)
        if isolate_id is None:
            if not dry_run:
                c.execute(
                    "INSERT INTO viral_isolates (accession, virus_name, master_id) VALUES (?, ?, ?)",
                    (isolate_acc, canonical, master_id),
                )
                isolate_id = c.lastrowid
                isolate_map[isolate_acc] = isolate_id
                stats["new_isolate"] += 1
        else:
            stats["existing_isolate"] += 1

        # Step 3: viral_proteins
        if not dry_run:
            c.execute("""
                INSERT INTO viral_proteins
                (isolate_id, protein_accession, protein_name, gene_symbol,
                 aa_length, translation, functional_category, is_rdrp)
                VALUES (?, ?, ?, ?, ?, ?, 'replication', 1)
            """, (
                isolate_id, protein_acc, rec["product"], "",
                rec["aa_length"], rec["aa_seq"],
            ))
            stats["proteins_inserted"] += 1

        if (i + 1) % 200 == 0:
            if not dry_run:
                conn.commit()
            print(f"  处理 {i + 1}/{len(records)}...")

    if not dry_run:
        conn.commit()

    # ── 输出 ──
    print(f"\n{'=' * 60}")
    print(f"{'预览' if dry_run else '导入'}统计")
    print(f"{'=' * 60}")
    print(f"  总处理:           {len(records)}")
    print(f"  跳过重复蛋白:     {stats['skipped_dup']}")
    print(f"  匹配已知物种:     {stats['known_master_match']}")
    print(f"  新建物种:         {stats['new_master_created']}")
    print(f"  匹配已知分离株:   {stats['existing_isolate']}")
    print(f"  新建分离株:       {stats['new_isolate']}")
    print(f"  插入蛋白:         {stats['proteins_inserted']}")

    if new_species and not dry_run:
        print(f"\n  新增病毒物种列表:")
        for name, cnt in new_species.most_common():
            print(f"    {name[:55]:55s} {cnt} 条")

    conn.close()


def print_stats():
    conn = sqlite3.connect(str(DB_PATH))
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM viral_proteins WHERE is_rdrp = 1")
    total = c.fetchone()[0]
    c.execute("""
        SELECT vm.canonical_name, COUNT(*) as cnt
        FROM viral_proteins vp
        JOIN viral_isolates vi ON vp.isolate_id = vi.isolate_id
        JOIN virus_master vm ON vi.master_id = vm.master_id
        WHERE vp.is_rdrp = 1
        GROUP BY vm.canonical_name
        ORDER BY cnt DESC
    """)
    print(f"\n当前 RDRP 总数: {total}")
    print(f"按病毒物种:")
    for name, cnt in c.fetchall():
        print(f"  {name[:50]:50s} {cnt}")
    conn.close()


def main():
    import argparse
    parser = argparse.ArgumentParser(description="导入 NCBI RDRP")
    parser.add_argument("--dry-run", action="store_true", help="预览")
    parser.add_argument("--stats", action="store_true", help="查看统计")
    args = parser.parse_args()

    if args.stats:
        print_stats()
        return

    print("=" * 60)
    print("NCBI RDRP 序列导入 v2 (自动建新物种)")
    print("=" * 60)

    print("\n[1/2] 解析 GenBank 文件...")
    records = parse_records()
    if not records:
        print("[Error] 没有可导入的记录")
        return

    print(f"\n[2/2] {'预览' if args.dry_run else '导入到数据库'}...")
    import_records(records, dry_run=args.dry_run)

    if not args.dry_run:
        print(f"\n运行 'python import_ncbi_rdrp.py --stats' 查看结果")
        print(f"运行 'python rdrp_tool.py --stats' 查看完整 RDRP 统计")

    print("=" * 60)


if __name__ == "__main__":
    main()
