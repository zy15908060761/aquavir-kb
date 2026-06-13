"""
Build a non-redundant (NR) protein database from reannotated ORFs.

Phase 1 (this script): Exact-match deduplication (100% identity) using dictionary hashing.
  This removes fully identical sequences in O(N) time.

Phase 2 (recommended): Run CD-HIT with -c 0.5 -n 3 on the exported FASTA to get
  true 50%-identity clusters, then update cluster assignments in the database.

Tables created:
  - nr_protein_clusters: cluster representatives and metadata
  - viral_proteins_nr: mapping from each protein to its NR cluster
"""
from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path
from collections import defaultdict

DB_PATH = Path(r"F:\甲壳动物数据库\crustacean_virus_core.db")
NR_FASTA_PATH = Path(r"F:\甲壳动物数据库\downloads\nr_proteins_exact.fasta")
MIN_AA_LENGTH = 50


def create_nr_tables(conn: sqlite3.Connection) -> None:
    c = conn.cursor()
    c.executescript("""
    DROP TABLE IF EXISTS nr_protein_clusters;
    DROP TABLE IF EXISTS viral_proteins_nr;

    CREATE TABLE nr_protein_clusters (
        cluster_id INTEGER PRIMARY KEY AUTOINCREMENT,
        representative_seq_hash VARCHAR(64) UNIQUE,
        representative_aa_seq TEXT,
        representative_dna_seq TEXT,
        cluster_size INTEGER DEFAULT 1,
        cluster_method TEXT DEFAULT 'exact_match',
        cd_hit_threshold REAL,
        avg_length REAL,
        functional_category VARCHAR(50),
        source_count INTEGER DEFAULT 0,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE viral_proteins_nr (
        mapping_id INTEGER PRIMARY KEY AUTOINCREMENT,
        protein_id INTEGER,
        reanno_id INTEGER,
        cluster_id INTEGER NOT NULL,
        identity_to_rep REAL DEFAULT 100.0,
        alignment_length INTEGER,
        FOREIGN KEY (protein_id) REFERENCES viral_proteins(protein_id),
        FOREIGN KEY (reanno_id) REFERENCES reannotated_orfs(reanno_id),
        FOREIGN KEY (cluster_id) REFERENCES nr_protein_clusters(cluster_id)
    );

    CREATE INDEX idx_vpnr_cluster ON viral_proteins_nr(cluster_id);
    CREATE INDEX idx_vpnr_protein ON viral_proteins_nr(protein_id);
    CREATE INDEX idx_vpnr_reanno ON viral_proteins_nr(reanno_id);
    """)
    conn.commit()
    print("[DB] Created NR tables")


def exact_match_clustering(conn: sqlite3.Connection) -> dict[str, list[dict]]:
    """Cluster reannotated ORFs by exact amino-acid sequence match."""
    c = conn.cursor()
    print("\n[1/4] Loading reannotated ORFs...")
    c.execute("""
        SELECT 
            r.reanno_id,
            r.isolate_id,
            r.aa_sequence,
            r.dna_sequence,
            r.aa_length,
            r.locus_tag,
            v.accession,
            vm.canonical_name
        FROM reannotated_orfs r
        JOIN viral_isolates v ON r.isolate_id = v.isolate_id
        LEFT JOIN virus_master vm ON v.master_id = vm.master_id
        WHERE r.aa_sequence IS NOT NULL AND r.aa_sequence != ''
    """)

    clusters: dict[str, list[dict]] = defaultdict(list)
    total = 0
    for row in c.fetchall():
        seq = row["aa_sequence"].strip().upper()
        if len(seq) < MIN_AA_LENGTH:
            continue
        seq_hash = hashlib.sha256(seq.encode()).hexdigest()
        clusters[seq_hash].append({
            "reanno_id": row["reanno_id"],
            "isolate_id": row["isolate_id"],
            "aa_seq": seq,
            "dna_seq": row["dna_sequence"],
            "length": row["aa_length"],
            "locus_tag": row["locus_tag"],
            "accession": row["accession"],
            "virus_name": row["canonical_name"],
        })
        total += 1

    print(f"    Loaded {total} valid ORFs")
    print(f"    Exact-match clusters: {len(clusters)}")
    print(f"    Redundancy reduction: {total} -> {len(clusters)} ({len(clusters)/total*100:.1f}%)")
    return clusters


def insert_clusters(conn: sqlite3.Connection, clusters: dict[str, list[dict]]) -> dict[str, int]:
    """Insert clusters and return hash->cluster_id mapping."""
    c = conn.cursor()
    hash_to_cluster_id: dict[str, int] = {}

    print("\n[2/4] Inserting clusters into database...")
    for seq_hash, members in clusters.items():
        rep = members[0]
        c.execute("""
            INSERT INTO nr_protein_clusters
            (representative_seq_hash, representative_aa_seq, representative_dna_seq,
             cluster_size, cluster_method, cd_hit_threshold, avg_length, source_count)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            seq_hash,
            rep["aa_seq"],
            rep["dna_seq"],
            len(members),
            "exact_match",
            None,
            rep["length"],
            len(set(m["virus_name"] for m in members)),
        ))
        hash_to_cluster_id[seq_hash] = c.lastrowid

    conn.commit()
    print(f"    Inserted {len(clusters)} clusters")
    return hash_to_cluster_id


def insert_mappings(conn: sqlite3.Connection, clusters: dict[str, list[dict]], hash_to_id: dict[str, int]) -> None:
    c = conn.cursor()
    print("\n[3/4] Inserting protein-to-cluster mappings...")
    records = []
    for seq_hash, members in clusters.items():
        cid = hash_to_id[seq_hash]
        for m in members:
            records.append((m["reanno_id"], cid))

    c.executemany("""
        INSERT INTO viral_proteins_nr (reanno_id, cluster_id, identity_to_rep)
        VALUES (?, ?, 100.0)
    """, records)
    conn.commit()
    print(f"    Inserted {len(records)} mappings")


def export_nr_fasta(clusters: dict[str, list[dict]]) -> None:
    print(f"\n[4/4] Exporting NR FASTA to {NR_FASTA_PATH}...")
    NR_FASTA_PATH.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    for seq_hash, members in clusters.items():
        rep = members[0]
        virus_names = ",".join(sorted(set(m["virus_name"] for m in members if m["virus_name"]))) or "unknown"
        header = f">{seq_hash[:16]}|len={rep['length']}|count={len(members)}|viruses={virus_names}"
        lines.append(header)
        lines.append(rep["aa_seq"])

    NR_FASTA_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"    Exported {len(clusters)} representative sequences")


def main() -> None:
    print("=" * 60)
    print("Building Non-Redundant Protein Database (Exact Match Phase)")
    print("=" * 60)

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row

    create_nr_tables(conn)
    clusters = exact_match_clustering(conn)
    hash_to_id = insert_clusters(conn, clusters)
    insert_mappings(conn, clusters, hash_to_id)
    export_nr_fasta(clusters)

    # Final stats
    print("\n[Summary]")
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM nr_protein_clusters")
    print(f"  NR clusters (exact match): {c.fetchone()[0]}")
    c.execute("SELECT COUNT(*) FROM viral_proteins_nr")
    print(f"  Total protein mappings: {c.fetchone()[0]}")
    c.execute("""
        SELECT cluster_size, COUNT(*) as cnt
        FROM nr_protein_clusters
        GROUP BY cluster_size
        ORDER BY cluster_size DESC
        LIMIT 10
    """)
    print("  Top cluster sizes:")
    for r in c.fetchall():
        print(f"    size={r[0]:4d}: {r[1]:4d} clusters")

    conn.close()
    print("\n" + "=" * 60)
    print("Done! NR database (exact-match phase) built.")
    print("=" * 60)
    print(f"\nNext step: Install CD-HIT and run:")
    print(f"  cd-hit -i {NR_FASTA_PATH} -o nr_proteins_cdhit50.fasta -c 0.5 -n 3")
    print(f"Then update cluster assignments in the database.")


if __name__ == "__main__":
    main()
