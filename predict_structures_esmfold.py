"""
ESMFold 批量蛋白结构预测脚本

通过 ESMFold Atlas API (api.esmatlas.com) 对 NR 蛋白簇的代表序列进行
3D 结构预测。不需要 UniProt ID，直接提交氨基酸序列即可。

使用方式:
    python predict_structures_esmfold.py                          # 预测所有未覆盖的 clusters
    python predict_structures_esmfold.py --limit 50               # 仅预测前 50 个
    python predict_structures_esmfold.py --limit 100 --no-resume  # 强制重新预测
    python predict_structures_esmfold.py --cluster-ids 10,15,20   # 仅预测指定 clusters
    python predict_structures_esmfold.py --min-length 100 --max-length 1200
    python predict_structures_esmfold.py --priority-unmapped      # 优先预测无 UniProt 映射的
    python predict_structures_esmfold.py --stats                  # 仅显示覆盖统计

表:
    - protein_structures: 存储预测结果 (已有表，由 setup_protein_structures_and_domains.py 创建)
    - nr_protein_clusters: 从该表读取代表序列
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import requests

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "crustacean_virus_core.db"
STRUCTURES_DIR = BASE_DIR / "downloads" / "structures"
STRUCTURES_DIR.mkdir(parents=True, exist_ok=True)

ESMFOLD_URL = "https://api.esmatlas.com/foldSequence/v1/pdb/"
RATE_LIMIT_SECONDS = 3.0  # 友好速率限制
REQUEST_TIMEOUT = 180  # ESMFold 可能需要较长时间


def get_coverage_stats(conn: sqlite3.Connection) -> dict[str, int]:
    """获取覆盖率统计"""
    c = conn.cursor()
    total_clusters = c.execute(
        "SELECT COUNT(*) FROM nr_protein_clusters WHERE representative_aa_seq IS NOT NULL"
    ).fetchone()[0]
    with_structure = c.execute(
        "SELECT COUNT(DISTINCT cluster_id) FROM protein_structures WHERE prediction_method = 'esmfold'"
    ).fetchone()[0]
    # 检查哪些 clusters 有 UniProt 映射
    with_uniprot = c.execute("""
        SELECT COUNT(DISTINCT vpnr.cluster_id)
        FROM viral_proteins_nr vpnr
        JOIN uniprot_protein_links upl ON vpnr.protein_id = upl.protein_id
    """).fetchone()[0] if 0 else 0
    return {
        "total_clusters_with_seq": total_clusters,
        "clusters_with_structure": with_structure,
        "clusters_with_uniprot": with_uniprot,
        "coverage_pct": round(with_structure / total_clusters * 100, 1) if total_clusters > 0 else 0,
    }


def print_stats(conn: sqlite3.Connection) -> None:
    stats = get_coverage_stats(conn)
    print("=" * 60)
    print("ESMFold 结构预测覆盖统计")
    print("=" * 60)
    print(f"  有代表序列的 NR clusters:        {stats['total_clusters_with_seq']}")
    print(f"  已有 ESMFold 结构的 clusters:     {stats['clusters_with_structure']}")
    print(f"  覆盖率:                           {stats['coverage_pct']}%")
    print(f"  有 UniProt 映射的 clusters:       {stats['clusters_with_uniprot']}")
    print()
    # 按 pLDDT 分布
    c = conn.cursor()
    dist = c.execute("""
        SELECT
            SUM(CASE WHEN plddt_score >= 90 THEN 1 ELSE 0 END) as very_high,
            SUM(CASE WHEN plddt_score >= 70 AND plddt_score < 90 THEN 1 ELSE 0 END) as high,
            SUM(CASE WHEN plddt_score >= 50 AND plddt_score < 70 THEN 1 ELSE 0 END) as medium,
            SUM(CASE WHEN plddt_score < 50 THEN 1 ELSE 0 END) as low
        FROM protein_structures WHERE prediction_method = 'esmfold'
    """).fetchone()
    if dist:
        print(f"  pLDDT 分布:")
        print(f"    极高 (>=90):    {dist[0] or 0}")
        print(f"    高   (70-90):   {dist[1] or 0}")
        print(f"    中   (50-70):   {dist[2] or 0}")
        print(f"    低   (<50):     {dist[3] or 0}")


def parse_plddt_from_pdb(pdb_content: str) -> float | None:
    """从 PDB 文件的 B-factor 列提取 pLDDT 分数（仅 CA 原子）"""
    values = []
    for line in pdb_content.splitlines():
        if line.startswith("ATOM") and line[13:15].strip() == "CA":
            try:
                val = float(line[60:66].strip())
                values.append(val)
            except ValueError:
                pass
    if not values:
        return None
    return round(sum(values) / len(values), 1)


def predict_structure(sequence: str, timeout: int = REQUEST_TIMEOUT) -> tuple[str | None, float | None, str | None]:
    """
    调用 ESMFold API 预测单条序列的结构。
    返回: (pdb_content, plddt_score, error_message)
    """
    try:
        resp = requests.post(
            ESMFOLD_URL,
            data=sequence,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=timeout,
        )
        resp.raise_for_status()
        pdb_content = resp.text

        if not pdb_content or len(pdb_content) < 100:
            return None, None, "ESMFold returned empty or invalid PDB content"

        plddt = parse_plddt_from_pdb(pdb_content)
        return pdb_content, plddt, None

    except requests.exceptions.Timeout:
        return None, None, "Request timed out"
    except requests.exceptions.HTTPError as e:
        return None, None, f"HTTP error {e.response.status_code}: {e.response.text[:200]}"
    except requests.exceptions.ConnectionError as e:
        return None, None, f"Connection error: {e}"
    except Exception as e:
        return None, None, str(e)


def get_pending_clusters(
    conn: sqlite3.Connection,
    limit: int | None = None,
    cluster_ids: list[int] | None = None,
    min_length: int = 50,
    max_length: int = 1500,
    resume: bool = True,
    priority_unmapped: bool = False,
) -> list[dict[str, Any]]:
    """获取待预测的 clusters 列表"""
    c = conn.cursor()

    if cluster_ids:
        placeholders = ",".join("?" * len(cluster_ids))
        base_query = f"""
            SELECT npc.cluster_id, npc.representative_aa_seq, npc.cluster_size,
                   length(npc.representative_aa_seq) as seq_len
            FROM nr_protein_clusters npc
            WHERE npc.cluster_id IN ({placeholders})
              AND npc.representative_aa_seq IS NOT NULL
              AND length(npc.representative_aa_seq) BETWEEN ? AND ?
        """
        params = cluster_ids + [min_length, max_length]
    else:
        base_query = """
            SELECT npc.cluster_id, npc.representative_aa_seq, npc.cluster_size,
                   length(npc.representative_aa_seq) as seq_len
            FROM nr_protein_clusters npc
            WHERE npc.representative_aa_seq IS NOT NULL
              AND length(npc.representative_aa_seq) BETWEEN ? AND ?
        """
        params = [min_length, max_length]

    # 跳过已有结构的 clusters
    if resume:
        base_query = base_query.replace(
            "FROM nr_protein_clusters npc",
            """FROM nr_protein_clusters npc
            WHERE NOT EXISTS (
                SELECT 1 FROM protein_structures ps
                WHERE ps.cluster_id = npc.cluster_id
                  AND ps.prediction_method = 'esmfold'
            )""",
        )
        # Remove the initial WHERE since it's already in the subquery filter
        base_query = base_query.replace(
            "WHERE npc.representative_aa_seq IS NOT NULL",
            "AND npc.representative_aa_seq IS NOT NULL",
        )

    # 优先预测无 UniProt 映射的 clusters
    if priority_unmapped:
        order_clause = """
            ORDER BY
                CASE WHEN EXISTS (
                    SELECT 1 FROM viral_proteins_nr vpnr
                    JOIN uniprot_protein_links upl ON vpnr.protein_id = upl.protein_id
                    WHERE vpnr.cluster_id = npc.cluster_id
                ) THEN 1 ELSE 0 END,
                npc.cluster_size DESC
        """
    else:
        order_clause = "ORDER BY npc.cluster_size DESC"

    query = base_query + order_clause

    if limit:
        query += " LIMIT ?"
        params.append(limit)

    c.execute(query, params)
    return [dict(r) for r in c.fetchall()]


def save_structure(
    conn: sqlite3.Connection,
    cluster_id: int,
    pdb_content: str,
    plddt_score: float | None,
    sequence_length: int,
    model_version: str = "esmfold_v1",
) -> int:
    """保存结构到数据库和磁盘"""
    c = conn.cursor()

    # 保存 PDB 文件
    pdb_path = STRUCTURES_DIR / f"cluster_{cluster_id}_esmfold.pdb"
    pdb_path.write_text(pdb_content, encoding="utf-8")

    # 插入数据库
    c.execute("""
        INSERT INTO protein_structures
        (cluster_id, prediction_method, model_version, pdb_file_path,
         plddt_score, sequence_length, protein_id)
        VALUES (?, 'esmfold', ?, ?, ?, ?,
            (SELECT vpnr.protein_id FROM viral_proteins_nr vpnr
             WHERE vpnr.cluster_id = ? LIMIT 1))
    """, (cluster_id, model_version, str(pdb_path), plddt_score, sequence_length, cluster_id))

    return c.lastrowid


def run_prediction(
    conn: sqlite3.Connection,
    limit: int | None = None,
    cluster_ids: list[int] | None = None,
    min_length: int = 50,
    max_length: int = 1500,
    resume: bool = True,
    priority_unmapped: bool = False,
    dry_run: bool = False,
) -> dict[str, int]:
    """运行批量预测"""
    clusters = get_pending_clusters(
        conn, limit=limit, cluster_ids=cluster_ids,
        min_length=min_length, max_length=max_length,
        resume=resume, priority_unmapped=priority_unmapped,
    )

    stats = {"total": len(clusters), "success": 0, "failed": 0, "skipped_empty": 0}

    if not clusters:
        print("没有待预测的 clusters。")
        return stats

    um_label = " (优先无 UniProt)" if priority_unmapped else ""
    resume_label = " (跳过已有)" if resume else ""
    print(f"待预测 clusters: {len(clusters)}{um_label}{resume_label}")
    print(f"序列长度范围: {min_length} - {max_length} AA")
    if dry_run:
        print("[DRY RUN] 仅预览，不发送请求\n")
        for i, cl in enumerate(clusters, 1):
            print(f"  [{i}/{len(clusters)}] cluster_id={cl['cluster_id']} "
                  f"size={cl['cluster_size']} len={cl['seq_len']}")
        return stats
    print()

    commit_interval = 10
    for i, cl in enumerate(clusters, 1):
        cid = cl["cluster_id"]
        seq = cl["representative_aa_seq"]
        seq_len = cl["seq_len"]

        print(f"  [{i}/{len(clusters)}] cluster_id={cid} size={cl['cluster_size']} "
              f"len={seq_len} ... ", end="", flush=True)

        pdb_content, plddt, error = predict_structure(seq)

        if error:
            print(f"FAILED: {error}")
            stats["failed"] += 1
        elif not pdb_content:
            print("EMPTY (no structure returned)")
            stats["skipped_empty"] += 1
        else:
            if dry_run:
                print(f"OK (pLDDT={plddt})")
            else:
                structure_id = save_structure(conn, cid, pdb_content, plddt, seq_len)
                print(f"OK (pLDDT={plddt}, structure_id={structure_id})")
            stats["success"] += 1

        # 定期提交
        if not dry_run and i % commit_interval == 0:
            conn.commit()
            print(f"  [checkpoint] 已提交 {i}/{len(clusters)}")

        # 速率限制
        if i < len(clusters):
            time.sleep(RATE_LIMIT_SECONDS)

    if not dry_run:
        conn.commit()

    return stats


def main() -> None:
    parser = argparse.ArgumentParser(
        description="ESMFold 批量蛋白结构预测",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  %(prog)s --stats                    # 查看覆盖统计
  %(prog)s --limit 50                 # 预测前 50 个未覆盖的 clusters
  %(prog)s --limit 100 --no-resume    # 强制重预测前 100 个
  %(prog)s --priority-unmapped --limit 50  # 优先预测无 UniProt 映射的
  %(prog)s --cluster-ids 10,15,20     # 仅预测指定的 clusters
        """,
    )
    parser.add_argument("--limit", type=int, default=None, help="最多预测 N 个 clusters")
    parser.add_argument("--cluster-ids", type=str, default=None,
                        help="逗号分隔的 cluster ID 列表")
    parser.add_argument("--min-length", type=int, default=50, help="最小序列长度 (AA)")
    parser.add_argument("--max-length", type=int, default=1500, help="最大序列长度 (AA)")
    parser.add_argument("--no-resume", action="store_true", help="强制重新预测已有结构的 clusters")
    parser.add_argument("--priority-unmapped", action="store_true",
                        help="优先预测无 UniProt 映射的 clusters")
    parser.add_argument("--dry-run", action="store_true", help="仅预览，不实际请求")
    parser.add_argument("--stats", action="store_true", help="仅显示覆盖统计")
    args = parser.parse_args()

    conn = sqlite3.connect(str(DB_PATH), timeout=60)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=15000")

    try:
        if args.stats:
            print_stats(conn)
            return

        # 解析 cluster IDs
        cluster_ids = None
        if args.cluster_ids:
            cluster_ids = [int(x.strip()) for x in args.cluster_ids.split(",") if x.strip()]

        stats = run_prediction(
            conn,
            limit=args.limit,
            cluster_ids=cluster_ids,
            min_length=args.min_length,
            max_length=args.max_length,
            resume=not args.no_resume,
            priority_unmapped=args.priority_unmapped,
            dry_run=args.dry_run,
        )

        print()
        print("=" * 60)
        print(f"预测完成: 成功={stats['success']} 失败={stats['failed']} "
              f"空结果={stats['skipped_empty']} 总计={stats['total']}")

        # 显示更新后的统计
        if not args.dry_run and stats["success"] > 0:
            print()
            print_stats(conn)

            # 导出结果摘要
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            summary_path = BASE_DIR / "downloads" / f"esmfold_prediction_{stamp}.json"
            summary_path.write_text(json.dumps({
                "script": "predict_structures_esmfold.py",
                "stats": stats,
                "completed_at": datetime.now().isoformat(timespec="seconds"),
            }, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"\n结果摘要: {summary_path}")

    except KeyboardInterrupt:
        print("\n用户中断。正在保存...")
        conn.commit()
        print("已保存。")
        sys.exit(1)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
