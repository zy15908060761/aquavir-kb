"""
Enrich protein structure data from AlphaFold DB and RCSB PDB.

Strategy:
  1. Read all unique UniProt IDs from uniprot_annotations
  2. Query AlphaFold DB API for predicted structures (per UniProt ID)
  3. Query RCSB PDB Search API for experimental structures (per UniProt ID)
  4. Store results in uniprot_structures table

Usage:
    python enrich_structures.py                          # full run
    python enrich_structures.py --limit 100              # process first N
    python enrich_structures.py --skip-pdb               # skip PDB queries
    python enrich_structures.py --skip-alphafold         # skip AlphaFold queries
    python enrich_structures.py --stats                  # coverage stats only
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any


BASE_DIR = Path(__file__).resolve().parent
DB_PATH = os.environ.get(
    "ENRICH_DB_PATH",
    str(BASE_DIR / "crustacean_virus_core.db"),
)

ALPHAFOLD_API = "https://alphafold.ebi.ac.uk/api/prediction"
RCSB_SEARCH_API = "https://search.rcsb.org/rcsbsearch/v2/query"

CACHE_DIR = BASE_DIR / "external_data" / "structures"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

RATE_LIMIT_AF = 0.3   # seconds between AlphaFold requests
RATE_LIMIT_PDB = 0.5  # seconds between PDB requests


def download_schema(conn: sqlite3.Connection) -> None:
    """Create uniprot_structures table if not exists."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS uniprot_structures (
            struct_id INTEGER PRIMARY KEY AUTOINCREMENT,
            uniprot_id TEXT NOT NULL,
            source TEXT NOT NULL CHECK (source IN ('alphafold', 'pdb')),
            entry_id TEXT NOT NULL,
            confidence REAL,
            sequence_length INTEGER,
            pdb_url TEXT,
            gene TEXT,
            protein_description TEXT,
            organism TEXT,
            fetched_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_us_uniprot ON uniprot_structures(uniprot_id);
        CREATE INDEX IF NOT EXISTS idx_us_source ON uniprot_structures(source);

        CREATE TABLE IF NOT EXISTS structure_query_log (
            query_id INTEGER PRIMARY KEY AUTOINCREMENT,
            uniprot_id TEXT NOT NULL,
            source TEXT NOT NULL CHECK (source IN ('alphafold', 'pdb')),
            status TEXT NOT NULL,
            hit_count INTEGER DEFAULT 0,
            message TEXT,
            queried_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(uniprot_id, source)
        );
        CREATE INDEX IF NOT EXISTS idx_structure_query_log_source
            ON structure_query_log(source, status);
    """)


def get_uniprot_ids(conn: sqlite3.Connection) -> list[str]:
    """Get all unique UniProt IDs from uniprot_annotations."""
    rows = conn.execute(
        "SELECT DISTINCT uniprot_id FROM uniprot_annotations WHERE uniprot_id IS NOT NULL ORDER BY uniprot_id"
    ).fetchall()
    return [r[0] for r in rows]


def get_existing(conn: sqlite3.Connection, source: str) -> set[str]:
    """Get set of already-processed UniProt IDs for a given source."""
    rows = conn.execute(
        "SELECT DISTINCT uniprot_id FROM uniprot_structures WHERE source = ?",
        (source,),
    ).fetchall()
    existing = {r[0] for r in rows}
    rows = conn.execute(
        """
        SELECT DISTINCT uniprot_id
        FROM structure_query_log
        WHERE source = ? AND status IN ('found', 'no_structure', 'not_found')
        """,
        (source,),
    ).fetchall()
    existing.update(r[0] for r in rows)
    return existing


def log_structure_query(
    conn: sqlite3.Connection,
    uniprot_id: str,
    source: str,
    status: str,
    hit_count: int = 0,
    message: str = "",
) -> None:
    conn.execute(
        """
        INSERT INTO structure_query_log
            (uniprot_id, source, status, hit_count, message)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(uniprot_id, source) DO UPDATE SET
            status=excluded.status,
            hit_count=excluded.hit_count,
            message=excluded.message,
            queried_at=CURRENT_TIMESTAMP
        """,
        (uniprot_id, source, status, hit_count, message),
    )


def query_alphafold(uniprot_id: str) -> list[dict[str, Any]]:
    """Query AlphaFold DB for a single UniProt ID. Returns list of structure dicts."""
    url = f"{ALPHAFOLD_API}/{uniprot_id}"
    req = urllib.request.Request(url, headers={"User-Agent": "crustacean-virus-db-curation/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        if e.code in (404, 422):
            return []  # No prediction available
        if e.code == 429:
            time.sleep(5)
            return query_alphafold(uniprot_id)  # retry after rate limit
        raise
    except (json.JSONDecodeError, urllib.error.URLError):
        return []

    results = []
    if not data:
        return results

    for entry in data:
        pdb_url = entry.get("pdbUrl", "") or ""
        # Some entries have bcifUrl instead
        if not pdb_url:
            pdb_url = entry.get("bcifUrl", "") or ""

        results.append({
            "uniprot_id": uniprot_id,
            "source": "alphafold",
            "entry_id": entry.get("entryId", f"AF-{uniprot_id}"),
            "confidence": entry.get("globalMetricValue"),
            "sequence_length": entry.get("sequenceLength")
                              or (len(entry.get("sequence", "")) if entry.get("sequence") else None),
            "pdb_url": pdb_url,
            "gene": entry.get("gene", ""),
            "protein_description": entry.get("uniprotDescription", ""),
            "organism": entry.get("organismScientificName", ""),
        })

    return results


def query_pdb(uniprot_id: str) -> list[dict[str, Any]]:
    """Query RCSB PDB Search API for experimental structures matching a UniProt ID."""
    payload = {
        "query": {
            "type": "group",
            "logical_operator": "and",
            "nodes": [
                {
                    "type": "terminal",
                    "service": "text",
                    "parameters": {
                        "attribute": "rcsb_polymer_entity_container_identifiers.reference_sequence_identifiers.database_accession",
                        "operator": "exact_match",
                        "value": uniprot_id,
                    },
                },
                {
                    "type": "terminal",
                    "service": "text",
                    "parameters": {
                        "attribute": "rcsb_polymer_entity_container_identifiers.reference_sequence_identifiers.database_name",
                        "operator": "exact_match",
                        "value": "UniProt",
                    },
                },
            ],
        },
        "return_type": "entry",
        "request_options": {
            "paginate": {"start": 0, "rows": 50},
        },
    }

    req = urllib.request.Request(
        RCSB_SEARCH_API,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read()
            if not raw:
                return []
            data = json.loads(raw.decode())
    except urllib.error.HTTPError as e:
        if e.code in (400, 422):
            return []  # No results or invalid query
        raise
    except (json.JSONDecodeError, urllib.error.URLError):
        return []

    total = data.get("total_count", 0)
    if total == 0:
        return []

    results = []
    for entry in data.get("result_set", []):
        pdb_id = entry.get("identifier", "")
        if not pdb_id:
            continue

        pdb_url = f"https://files.rcsb.org/download/{pdb_id}.pdb"

        results.append({
            "uniprot_id": uniprot_id,
            "source": "pdb",
            "entry_id": pdb_id,
            "confidence": None,  # resolution would need a separate API call
            "sequence_length": None,
            "pdb_url": pdb_url,
            "gene": "",
            "protein_description": "",
            "organism": "",
        })

    return results


def run_alphafold(
    conn: sqlite3.Connection,
    uniprot_ids: list[str],
    existing: set[str],
    dry_run: bool = False,
    limit: int | None = None,
) -> dict[str, int]:
    """Query AlphaFold DB for all UniProt IDs."""
    stats: dict[str, int] = {"total": 0, "found": 0, "not_found": 0, "error": 0, "skipped_existing": 0}

    pending = [uid for uid in uniprot_ids if uid not in existing]
    if limit:
        pending = pending[:limit]
    stats["total"] = len(pending)
    stats["skipped_existing"] = len(uniprot_ids) - len(pending)

    print(f"\n[alphafold] {len(pending)} UniProt IDs to query ({stats['skipped_existing']} already done)")

    commit_counter = 0
    COMMIT_INTERVAL = 50

    for i, uid in enumerate(pending, 1):
        try:
            results = query_alphafold(uid)
        except Exception as exc:
            print(f"  [{i}/{len(pending)}] AF {uid}: ERROR {exc}")
            stats["error"] += 1
            if not dry_run:
                log_structure_query(conn, uid, "alphafold", "error", 0, str(exc)[:500])
            time.sleep(RATE_LIMIT_AF)
            continue

        if results:
            stats["found"] += 1
            if not dry_run:
                for r in results:
                    conn.execute(
                        """
                        INSERT INTO uniprot_structures
                            (uniprot_id, source, entry_id, confidence, sequence_length,
                             pdb_url, gene, protein_description, organism, fetched_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            r["uniprot_id"], r["source"], r["entry_id"], r["confidence"],
                            r["sequence_length"], r["pdb_url"], r["gene"],
                            r["protein_description"], r["organism"],
                            datetime.now().isoformat(timespec="seconds"),
                        ),
                    )
                log_structure_query(conn, uid, "alphafold", "found", len(results), "")
                commit_counter += 1

            if (i) % 50 == 0 or i == 1 or i == len(pending):
                desc = results[0].get("protein_description", "")[:60] if results else "?"
                plddt = results[0].get("confidence", "?") if results else "?"
                print(f"  [{i}/{len(pending)}] AF {uid}: pLDDT={plddt} | {desc}")
        else:
            stats["not_found"] += 1
            if not dry_run:
                log_structure_query(conn, uid, "alphafold", "no_structure", 0, "AlphaFold returned no prediction")
            if (i) % 200 == 0:
                print(f"  [{i}/{len(pending)}] AF {uid}: no prediction")

        # Periodic commit (with retry)
        if not dry_run and commit_counter > 0 and commit_counter % COMMIT_INTERVAL == 0:
            for attempt in range(3):
                try:
                    conn.commit()
                    print(f"  [commit] checkpoint at {i}/{len(pending)}")
                    break
                except sqlite3.OperationalError as exc:
                    if attempt == 2:
                        raise
                    print(f"  [retry] commit attempt {attempt+1} failed: {exc}")
                    time.sleep(2)

        time.sleep(RATE_LIMIT_AF)

    if not dry_run and commit_counter > 0:
        conn.commit()

    return stats


def run_pdb(
    conn: sqlite3.Connection,
    uniprot_ids: list[str],
    existing: set[str],
    dry_run: bool = False,
    limit: int | None = None,
) -> dict[str, int]:
    """Query RCSB PDB for all UniProt IDs."""
    stats: dict[str, int] = {"total": 0, "found": 0, "not_found": 0, "error": 0, "skipped_existing": 0, "total_hits": 0}

    pending = [uid for uid in uniprot_ids if uid not in existing]
    if limit:
        pending = pending[:limit]
    stats["total"] = len(pending)
    stats["skipped_existing"] = len(uniprot_ids) - len(pending)

    print(f"\n[pdb] {len(pending)} UniProt IDs to query ({stats['skipped_existing']} already done)")

    commit_counter = 0
    COMMIT_INTERVAL = 50

    for i, uid in enumerate(pending, 1):
        try:
            results = query_pdb(uid)
        except Exception as exc:
            print(f"  [{i}/{len(pending)}] PDB {uid}: ERROR {exc}")
            stats["error"] += 1
            if not dry_run:
                log_structure_query(conn, uid, "pdb", "error", 0, str(exc)[:500])
            time.sleep(RATE_LIMIT_PDB)
            continue

        if results:
            stats["found"] += 1
            stats["total_hits"] += len(results)
            if not dry_run:
                for r in results:
                    conn.execute(
                        """
                        INSERT INTO uniprot_structures
                            (uniprot_id, source, entry_id, confidence, sequence_length,
                             pdb_url, gene, protein_description, organism, fetched_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            r["uniprot_id"], r["source"], r["entry_id"], r["confidence"],
                            r["sequence_length"], r["pdb_url"], r["gene"],
                            r["protein_description"], r["organism"],
                            datetime.now().isoformat(timespec="seconds"),
                        ),
                    )
                log_structure_query(conn, uid, "pdb", "found", len(results), "")
                commit_counter += 1

            if (i) % 100 == 0 or i == 1 or i == len(pending):
                entries = [r["entry_id"] for r in results[:5]]
                print(f"  [{i}/{len(pending)}] PDB {uid}: {len(results)} entries {entries}")
        else:
            stats["not_found"] += 1
            if not dry_run:
                log_structure_query(conn, uid, "pdb", "no_structure", 0, "RCSB PDB returned no entries")
            if len(pending) <= 100 or (i) % 500 == 0:
                pass  # don't print every miss unless verbose

        # Periodic commit (with retry)
        if not dry_run and commit_counter > 0 and commit_counter % COMMIT_INTERVAL == 0:
            for attempt in range(3):
                try:
                    conn.commit()
                    print(f"  [commit] PDB checkpoint at {i}/{len(pending)}")
                    break
                except sqlite3.OperationalError as exc:
                    if attempt == 2:
                        raise
                    print(f"  [retry] PDB commit attempt {attempt+1} failed: {exc}")
                    time.sleep(2)

        time.sleep(RATE_LIMIT_PDB)

    if not dry_run and commit_counter > 0:
        conn.commit()

    return stats


def get_stats(conn: sqlite3.Connection) -> dict[str, Any]:
    """Get structure coverage stats."""
    stats: dict[str, Any] = {}

    total_uniprot = conn.execute(
        "SELECT COUNT(DISTINCT uniprot_id) FROM uniprot_annotations WHERE uniprot_id IS NOT NULL"
    ).fetchone()[0]
    stats["total_uniprot_ids"] = total_uniprot

    # AlphaFold
    af_total = conn.execute(
        "SELECT COUNT(DISTINCT uniprot_id) FROM uniprot_structures WHERE source = 'alphafold'"
    ).fetchone()[0]
    stats["alphafold_with_structure"] = af_total

    if af_total > 0:
        stats["alphafold_avg_plddt"] = round(
            conn.execute(
                "SELECT AVG(confidence) FROM uniprot_structures WHERE source = 'alphafold' AND confidence IS NOT NULL"
            ).fetchone()[0] or 0,
            2,
        )
        stats["alphafold_high_confidence"] = conn.execute(
            "SELECT COUNT(DISTINCT uniprot_id) FROM uniprot_structures WHERE source = 'alphafold' AND confidence >= 70"
        ).fetchone()[0]
        stats["alphafold_low_confidence"] = conn.execute(
            "SELECT COUNT(DISTINCT uniprot_id) FROM uniprot_structures WHERE source = 'alphafold' AND confidence < 50"
        ).fetchone()[0]

    # PDB
    pdb_total = conn.execute(
        "SELECT COUNT(DISTINCT uniprot_id) FROM uniprot_structures WHERE source = 'pdb'"
    ).fetchone()[0]
    stats["pdb_with_structure"] = pdb_total

    if pdb_total > 0:
        stats["pdb_total_entries"] = conn.execute(
            "SELECT COUNT(*) FROM uniprot_structures WHERE source = 'pdb'"
        ).fetchone()[0]

    # By organism
    org_rows = conn.execute("""
        SELECT COALESCE(NULLIF(organism, ''), '(unknown)') as org,
               COUNT(DISTINCT uniprot_id) as cnt
        FROM uniprot_structures
        WHERE source = 'alphafold'
        GROUP BY org
        ORDER BY cnt DESC
        LIMIT 10
    """).fetchall()
    stats["alphafold_by_organism"] = {r[0]: r[1] for r in org_rows}

    # Confidence distribution
    if af_total > 0:
        dist = conn.execute("""
            SELECT
                SUM(CASE WHEN confidence >= 90 THEN 1 ELSE 0 END) as very_high,
                SUM(CASE WHEN confidence >= 70 AND confidence < 90 THEN 1 ELSE 0 END) as high,
                SUM(CASE WHEN confidence >= 50 AND confidence < 70 THEN 1 ELSE 0 END) as medium,
                SUM(CASE WHEN confidence < 50 THEN 1 ELSE 0 END) as low
            FROM uniprot_structures WHERE source = 'alphafold'
        """).fetchone()
        stats["af_very_high"] = dist[0] or 0
        stats["af_high"] = dist[1] or 0
        stats["af_medium"] = dist[2] or 0
        stats["af_low"] = dist[3] or 0

    return stats


def print_stats(stats: dict[str, Any]) -> None:
    """Print stats in Chinese."""
    print()
    print("=" * 60)
    print("蛋白结构匹配结果")
    print("=" * 60)

    total = stats["total_uniprot_ids"]
    print(f"\n  UniProt ID 总数:            {total}")

    af = stats.get("alphafold_with_structure", 0)
    print(f"\n【AlphaFold 预测结构】")
    print(f"  已有预测结构的蛋白数:        {af}")
    print(f"  覆盖率:                      {af/total*100:.1f}%" if total > 0 else "  N/A")

    if "alphafold_avg_plddt" in stats:
        print(f"  平均 pLDDT 置信度:           {stats['alphafold_avg_plddt']}")
        print(f"  高置信度 (pLDDT>=70):        {stats.get('alphafold_high_confidence', 0)}")
        print(f"  低置信度 (pLDDT<50):         {stats.get('alphafold_low_confidence', 0)}")

    if "af_very_high" in stats:
        print(f"\n  置信度分布:")
        print(f"    极高 (pLDDT>=90):           {stats['af_very_high']}")
        print(f"    高   (70<=pLDDT<90):        {stats['af_high']}")
        print(f"    中   (50<=pLDDT<70):        {stats['af_medium']}")
        print(f"    低   (pLDDT<50):            {stats['af_low']}")

    pdb = stats.get("pdb_with_structure", 0)
    print(f"\n【PDB 实验结构】")
    print(f"  有实验结构的蛋白数:          {pdb}")
    if pdb > 0:
        print(f"  总 PDB 条目数:                {stats.get('pdb_total_entries', 0)}")

    print(f"\n【AlphaFold 按物种分布 Top 10】")
    for org, cnt in stats.get("alphafold_by_organism", {}).items():
        print(f"  {org[:40]:40s} {cnt}")


def export_results(stats: dict[str, Any]) -> Path:
    """Export stats to JSON."""
    out_dir = BASE_DIR / "downloads"
    out_dir.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = out_dir / f"structure_enrich_{stamp}.json"

    # Convert any non-serializable values
    clean: dict[str, Any] = {}
    for k, v in stats.items():
        if isinstance(v, dict):
            clean[k] = {str(kk): vv for kk, vv in v.items()}
        else:
            clean[k] = v

    data = {
        "script": "enrich_structures.py",
        "stats": clean,
        "completed_at": datetime.now().isoformat(timespec="seconds"),
    }
    out_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_path


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Enrich protein structures from AlphaFold and PDB")
    parser.add_argument("--limit", type=int, default=None, help="Process first N pending UniProt IDs per source")
    parser.add_argument("--skip-alphafold", action="store_true", help="Skip AlphaFold queries")
    parser.add_argument("--skip-pdb", action="store_true", help="Skip PDB queries")
    parser.add_argument("--dry-run", action="store_true", help="Preview only, no DB writes")
    parser.add_argument("--stats", action="store_true", help="Show coverage stats only")
    args = parser.parse_args()

    conn = sqlite3.connect(str(DB_PATH), timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=15000")
    conn.execute("PRAGMA wal_autocheckpoint=500")

    try:
        if args.stats:
            download_schema(conn)
            s = get_stats(conn)
            print_stats(s)
            return

        download_schema(conn)

        uniprot_ids = get_uniprot_ids(conn)
        print(f"开始蛋白结构匹配...")
        print(f"  UniProt IDs: {len(uniprot_ids)}")
        print(f"  Pending limit per source: {args.limit or 'all'}")
        print(f"  Dry run: {args.dry_run}")
        print(f"  跳过 AlphaFold: {args.skip_alphafold}")
        print(f"  跳过 PDB: {args.skip_pdb}")

        combined_stats: dict[str, Any] = {"total_uniprot_ids": len(uniprot_ids)}

        if not args.skip_alphafold:
            existing_af = get_existing(conn, "alphafold")
            af_stats = run_alphafold(conn, uniprot_ids, existing_af, dry_run=args.dry_run, limit=args.limit)
            combined_stats.update({f"alphafold_{k}": v for k, v in af_stats.items()})
            print(f"\n  AlphaFold 完成: {af_stats['found']} found, {af_stats['not_found']} not found")

        if not args.skip_pdb:
            existing_pdb = get_existing(conn, "pdb")
            pdb_stats = run_pdb(conn, uniprot_ids, existing_pdb, dry_run=args.dry_run, limit=args.limit)
            combined_stats.update({f"pdb_{k}": v for k, v in pdb_stats.items()})
            print(f"\n  PDB 完成: {pdb_stats['found']} found, {pdb_stats['not_found']} not found, {pdb_stats['total_hits']} total entries")

        final_stats = get_stats(conn)
        print_stats(final_stats)

        if not args.dry_run:
            export_path = export_results(final_stats)
            print(f"\n[导出] 结果已保存至 {export_path}")

    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
