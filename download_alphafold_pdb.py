"""
批量下载 AlphaFold DB 的 PDB 结构文件到本地

AlphaFold DB 提供了每个预测结构的 PDB 格式文件（URL 已存储在 uniprot_structures 表）。
此脚本批量下载这些 PDB 文件到本地，使：
  1. 3D 查看器可离线加载（不依赖 AlphaFold DB 外部连接）
  2. pLDDT 热力图可直接从 PDB B-factor 列渲染
  3. 支持断点续传和增量更新

使用方式:
    python download_alphafold_pdb.py                     # 下载全部未下载的
    python download_alphafold_pdb.py --limit 100         # 仅下载前 100 个
    python download_alphafold_pdb.py --min-confidence 70 # 仅下载高置信度的
    python download_alphafold_pdb.py --force             # 强制重新下载全部
    python download_alphafold_pdb.py --stats             # 仅显示下载状态
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import requests
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "crustacean_virus_core.db"
AF_STRUCTURES_DIR = BASE_DIR / "downloads" / "structures" / "alphafold"
AF_STRUCTURES_DIR.mkdir(parents=True, exist_ok=True)

RATE_LIMIT_SECONDS = 0.5   # AlphaFold DB 友好速率
CHUNK_SIZE = 65536        # 64 KB 流式下载
REQUEST_TIMEOUT = 120     # 单文件下载超时 (秒)
MAX_RETRIES = 2           # SSL/网络错误最大重试次数


def ensure_local_path_column(conn: sqlite3.Connection) -> None:
    """确保 uniprot_structures 表有 local_pdb_path 列"""
    cols = [c[1] for c in conn.execute("PRAGMA table_info(uniprot_structures)").fetchall()]
    if "local_pdb_path" not in cols:
        conn.execute("ALTER TABLE uniprot_structures ADD COLUMN local_pdb_path TEXT")
        conn.commit()
        print("[Schema] Added local_pdb_path column to uniprot_structures")


def get_download_stats(conn: sqlite3.Connection) -> dict[str, Any]:
    """获取下载状态统计"""
    total = conn.execute(
        "SELECT COUNT(*) FROM uniprot_structures WHERE source = 'alphafold' AND pdb_url IS NOT NULL AND pdb_url != ''"
    ).fetchone()[0]
    downloaded = conn.execute(
        "SELECT COUNT(*) FROM uniprot_structures WHERE source = 'alphafold' AND local_pdb_path IS NOT NULL AND local_pdb_path != ''"
    ).fetchone()[0]
    # 检查下载文件是否真实存在
    actually_exist = 0
    for r in conn.execute(
        "SELECT local_pdb_path FROM uniprot_structures WHERE local_pdb_path IS NOT NULL AND local_pdb_path != ''"
    ).fetchall():
        if Path(r[0]).exists():
            actually_exist += 1

    return {
        "total": total,
        "downloaded_in_db": downloaded,
        "files_actually_exist": actually_exist,
        "pending": total - downloaded,
        "coverage_pct": round(downloaded / total * 100, 1) if total > 0 else 0,
    }


def print_stats(conn: sqlite3.Connection) -> None:
    stats = get_download_stats(conn)
    print("=" * 60)
    print("AlphaFold PDB 本地下载状态")
    print("=" * 60)
    print(f"  结构总数:              {stats['total']}")
    print(f"  已下载 (DB记录):       {stats['downloaded_in_db']}")
    print(f"  文件实际存在:          {stats['files_actually_exist']}")
    print(f"  待下载:                {stats['pending']}")
    print(f"  覆盖率:                {stats['coverage_pct']}%")
    print(f"  存储目录:              {AF_STRUCTURES_DIR}")


def download_pdb(url: str, dest_path: Path) -> tuple[bool, str]:
    """
    下载单个 PDB 文件 (使用 requests，支持重试)。
    返回: (success, error_message)
    """
    last_error = ""
    for attempt in range(MAX_RETRIES + 1):
        try:
            resp = requests.get(
                url,
                headers={"User-Agent": "crustacean-virus-db-curation/1.0"},
                timeout=REQUEST_TIMEOUT,
                stream=True,
                verify=True,  # SSL verification enabled; AlphaFold DB uses trusted HTTPS
            )
            resp.raise_for_status()

            with open(dest_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=CHUNK_SIZE):
                    if chunk:
                        f.write(chunk)

            # 验证文件大小
            file_size = dest_path.stat().st_size
            if file_size < 1000:
                dest_path.unlink(missing_ok=True)
                return False, f"File too small ({file_size} bytes), likely invalid PDB"

            return True, ""

        except requests.exceptions.SSLError as e:
            last_error = f"SSL Error: {e}"
            if attempt < MAX_RETRIES:
                time.sleep(2 * (attempt + 1))
                continue
        except requests.exceptions.HTTPError as e:
            return False, f"HTTP {e.response.status_code}"
        except requests.exceptions.ConnectionError as e:
            last_error = f"Connection Error: {e}"
            if attempt < MAX_RETRIES:
                time.sleep(2 * (attempt + 1))
                continue
        except requests.exceptions.Timeout:
            return False, "Timeout"
        except Exception as e:
            return False, str(e)[:200]

    return False, last_error


def run_download(
    conn: sqlite3.Connection,
    limit: int | None = None,
    min_confidence: float | None = None,
    force: bool = False,
) -> dict[str, int]:
    """执行批量下载"""
    # 构建查询
    query = """
        SELECT struct_id, uniprot_id, pdb_url, confidence, entry_id, local_pdb_path
        FROM uniprot_structures
        WHERE source = 'alphafold'
          AND pdb_url IS NOT NULL AND pdb_url != ''
    """
    params: list[Any] = []

    if min_confidence is not None:
        query += " AND confidence >= ?"
        params.append(min_confidence)

    if not force:
        query += " AND (local_pdb_path IS NULL OR local_pdb_path = '')"

    # 按置信度降序（先下载高质量的）
    query += " ORDER BY COALESCE(confidence, 0) DESC"

    if limit:
        query += " LIMIT ?"
        params.append(limit)

    rows = conn.execute(query, params).fetchall()
    stats: dict[str, int] = {
        "total": len(rows),
        "success": 0,
        "failed": 0,
        "skipped_exists": 0,
        "total_bytes": 0,
    }

    if not rows:
        print("没有需要下载的 PDB 文件。")
        return stats

    conf_label = f"pLDDT >= {min_confidence}" if min_confidence else "全部置信度"
    force_label = " (强制重下)" if force else ""
    print(f"待下载: {len(rows)} 个 PDB 文件 ({conf_label}){force_label}")
    print(f"存储目录: {AF_STRUCTURES_DIR}")
    print()

    start_time = time.time()
    for i, row in enumerate(rows, 1):
        struct_id = row[0]
        uniprot_id = row[1]
        pdb_url = row[2]
        confidence = row[3]
        entry_id = row[4] or f"AF-{uniprot_id}"

        # 构建本地文件路径
        safe_name = entry_id.replace("/", "_").replace("\\", "_")
        dest_path = AF_STRUCTURES_DIR / f"{safe_name}.pdb"

        # 如果是强制模式，删除已存在的文件
        if force and dest_path.exists():
            dest_path.unlink()

        # 如果文件已存在且非强制模式，跳过
        if dest_path.exists() and not force:
            # 只更新数据库记录
            conn.execute(
                "UPDATE uniprot_structures SET local_pdb_path = ? WHERE struct_id = ?",
                (str(dest_path), struct_id),
            )
            stats["skipped_exists"] += 1
            if i % 100 == 0:
                print(f"  [{i}/{len(rows)}] (文件已存在，更新 DB 记录...)")
            continue

        # 下载
        plddt_str = f"pLDDT={confidence:.0f}" if confidence else "pLDDT=?"
        print(f"  [{i}/{len(rows)}] {uniprot_id} ({plddt_str}) ... ", end="", flush=True)
        success, error = download_pdb(pdb_url, dest_path)

        if success:
            conn.execute(
                "UPDATE uniprot_structures SET local_pdb_path = ? WHERE struct_id = ?",
                (str(dest_path), struct_id),
            )
            stats["success"] += 1
            stats["total_bytes"] += dest_path.stat().st_size
            print(f"OK ({dest_path.stat().st_size // 1024} KB)")
        else:
            stats["failed"] += 1
            print(f"FAILED: {error}")
            # 删除可能损坏的文件
            dest_path.unlink(missing_ok=True)

        # 定期提交
        if i % 50 == 0:
            conn.commit()
            elapsed = time.time() - start_time
            rate = i / elapsed if elapsed > 0 else 0
            print(f"  [checkpoint] {i}/{len(rows)} 已提交 ({rate:.1f} files/s)")

        # 速率限制
        if i < len(rows):
            time.sleep(RATE_LIMIT_SECONDS)

    conn.commit()

    elapsed = time.time() - start_time
    stats["elapsed_seconds"] = round(elapsed, 1)
    stats["rate"] = round(stats["success"] / elapsed, 1) if elapsed > 0 else 0
    stats["total_mb"] = round(stats["total_bytes"] / (1024 * 1024), 1)

    return stats


def main() -> None:
    parser = argparse.ArgumentParser(
        description="批量下载 AlphaFold DB 的 PDB 结构文件到本地"
    )
    parser.add_argument("--limit", type=int, default=None, help="最多下载 N 个文件")
    parser.add_argument("--min-confidence", type=float, default=None,
                        help="仅下载 pLDDT >= N 的高置信度结构")
    parser.add_argument("--force", action="store_true", help="强制重新下载全部")
    parser.add_argument("--stats", action="store_true", help="仅显示下载状态")
    parser.add_argument("--dry-run", action="store_true", help="预览，不实际下载")
    args = parser.parse_args()

    conn = sqlite3.connect(str(DB_PATH), timeout=60)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=15000")

    try:
        ensure_local_path_column(conn)

        if args.stats:
            print_stats(conn)
            return

        if args.dry_run:
            print_stats(conn)
            print("\n[DRY RUN] 不实际下载")
            return

        stats = run_download(
            conn,
            limit=args.limit,
            min_confidence=args.min_confidence,
            force=args.force,
        )

        print()
        print("=" * 60)
        print(f"下载完成: 成功={stats['success']} 失败={stats['failed']} "
              f"已存在={stats['skipped_exists']} 总计={stats['total']}")
        print(f"数据量: {stats.get('total_mb', 0)} MB")
        print(f"耗时: {stats.get('elapsed_seconds', 0)} 秒")
        if stats.get("rate", 0) > 0:
            print(f"速率: {stats['rate']} files/s")
        print(f"存储目录: {AF_STRUCTURES_DIR}")

        # 显示更新后的统计
        print()
        print_stats(conn)

    except KeyboardInterrupt:
        print("\n用户中断。正在保存...")
        conn.commit()
        print("已保存。可重新运行断点续传。")
        sys.exit(1)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
