"""
Parse CD-HIT .clstr output and update database with 50% identity clusters.
"""
from __future__ import annotations

import re
import sqlite3
from pathlib import Path

DB_PATH = Path(r"F:\甲壳动物数据库\crustacean_virus_core.db")
CLSTR_PATH = Path(r"F:\甲壳动物数据库\downloads\nr_proteins_cdhit50.fasta.clstr")


def add_cdhit_column(conn: sqlite3.Connection) -> None:
    c = conn.cursor()
    c.execute("PRAGMA table_info(nr_protein_clusters)")
    cols = [row[1] for row in c.fetchall()]
    if "cdhit50_cluster_id" not in cols:
        c.execute("ALTER TABLE nr_protein_clusters ADD COLUMN cdhit50_cluster_id INTEGER")
        conn.commit()
        print("[DB] Added cdhit50_cluster_id column")
    if "cdhit50_is_rep" not in cols:
        c.execute("ALTER TABLE nr_protein_clusters ADD COLUMN cdhit50_is_rep INTEGER DEFAULT 0")
        conn.commit()
        print("[DB] Added cdhit50_is_rep column")


def parse_clstr(path: Path) -> dict[str, tuple[int, bool]]:
    """
    Parse CD-HIT .clstr file.
    Returns: {seq_hash_prefix: (cluster_id, is_representative)}
    """
    result: dict[str, tuple[int, bool]] = {}
    current_cluster = -1

    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith(">Cluster"):
            current_cluster = int(line.split()[1])
            continue
        if not line:
            continue

        # Format: 0\t2797aa, >HASH... at 50%/60%/...
        # or: 0\t2797aa, >HASH... *
        m = re.search(r">([a-f0-9]{16})", line)
        if not m:
            continue
        hash_prefix = m.group(1)
        is_rep = line.endswith("*")
        result[hash_prefix] = (current_cluster, is_rep)

    return result


def update_clusters(conn: sqlite3.Connection, mapping: dict[str, tuple[int, bool]]) -> int:
    c = conn.cursor()
    updated = 0
    matched = 0

    c.execute("SELECT cluster_id, representative_seq_hash FROM nr_protein_clusters")
    for row in c.fetchall():
        cid = row["cluster_id"]
        seq_hash = row["representative_seq_hash"]
        # Match by prefix (first 16 chars of SHA256 hash)
        prefix = seq_hash[:16]
        if prefix in mapping:
            cdhit_id, is_rep = mapping[prefix]
            c.execute("""
                UPDATE nr_protein_clusters
                SET cdhit50_cluster_id = ?, cdhit50_is_rep = ?
                WHERE cluster_id = ?
            """, (cdhit_id, 1 if is_rep else 0, cid))
            updated += 1
            if is_rep:
                matched += 1

    conn.commit()
    print(f"    Updated {updated} exact-match clusters with CD-HIT 50 assignments")
    print(f"    Representatives matched: {matched}")
    return updated


def main() -> None:
    print("=" * 60)
    print("Importing CD-HIT 50% Clustering Results")
    print("=" * 60)

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row

    add_cdhit_column(conn)

    print(f"\n[1/2] Parsing {CLSTR_PATH.name}...")
    mapping = parse_clstr(CLSTR_PATH)
    print(f"    Parsed {len(mapping)} sequence entries")
    # Count unique clusters
    unique_clusters = len(set(v[0] for v in mapping.values()))
    print(f"    Unique CD-HIT 50 clusters: {unique_clusters}")

    print("\n[2/2] Updating database...")
    update_clusters(conn, mapping)

    # Summary stats
    c = conn.cursor()
    c.execute("""
        SELECT cdhit50_cluster_id, COUNT(*) as cnt
        FROM nr_protein_clusters
        WHERE cdhit50_cluster_id IS NOT NULL
        GROUP BY cdhit50_cluster_id
        ORDER BY cnt DESC
        LIMIT 10
    """)
    print("\n[Summary] Top 10 CD-HIT 50 clusters by size:")
    for r in c.fetchall():
        print(f"    Cluster {r[0]:5d}: {r[1]:4d} exact-match sub-clusters")

    c.execute("""
        SELECT COUNT(DISTINCT cdhit50_cluster_id) FROM nr_protein_clusters
        WHERE cdhit50_cluster_id IS NOT NULL
    """)
    print(f"\n  Total CD-HIT 50 clusters with data: {c.fetchone()[0]}")

    conn.close()
    print("\n" + "=" * 60)
    print("Done! CD-HIT 50% clustering results imported.")
    print("=" * 60)


if __name__ == "__main__":
    main()
