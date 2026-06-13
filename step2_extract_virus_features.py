#!/usr/bin/env python3
"""
Step 2: Extract predictive features for each virus from the database.

Features extracted:
  - Genome features: length, gc_content, genome_type, has_complete_genome
  - Taxonomic features: virus_family (one-hot encoded later)
  - Protein features: ORF count, mean ORF length, protein functional category proportions
  - Host features: host_range_breadth (number of distinct host species), isolate_count
  - Ecological features: geographic_range (number of distinct countries)

Output:
    external_data/virus_features_for_ml.csv
"""
from __future__ import annotations

import csv
import sqlite3
from pathlib import Path
from collections import Counter

DB_PATH = Path(r"F:\甲壳动物数据库\crustacean_virus_core.db")
OUT_CSV = Path(r"F:\甲壳动物数据库\external_data\virus_features_for_ml.csv")
OUT_CSV.parent.mkdir(parents=True, exist_ok=True)


def extract_features(conn: sqlite3.Connection) -> list[dict]:
    c = conn.cursor()

    # Get all viruses with at least some data
    c.execute("""
        SELECT master_id, canonical_name, virus_family, genome_type
        FROM virus_master
        WHERE canonical_name IS NOT NULL AND canonical_name != ''
          AND LOWER(canonical_name) NOT LIKE '%unknown%'
          AND LOWER(canonical_name) NOT LIKE '%unclassified%'
          AND LOWER(canonical_name) NOT LIKE '%non-crustacean%'
    """)
    viruses = [dict(row) for row in c.fetchall()]
    print(f"Found {len(viruses)} named viruses")

    features = []
    for v in viruses:
        mid = v["master_id"]
        name = v["canonical_name"]
        family = v["virus_family"] or "Unknown"
        genome_type = v["genome_type"] or "Unknown"

        # ── Genome features ──
        c.execute("""
            SELECT COUNT(*) as isolate_count,
                   AVG(genome_length) as avg_genome_length,
                   AVG(gc_content) as avg_gc,
                   MAX(CASE WHEN completeness = 'complete_genome' THEN 1 ELSE 0 END) as has_complete
            FROM viral_isolates
            WHERE master_id = ?
        """, (mid,))
        row = c.fetchone()
        isolate_count = row[0] or 0
        avg_genome_length = row[1] or 0
        avg_gc = row[2] or 0
        has_complete_genome = row[3] or 0

        # ── ORF features ──
        c.execute("""
            SELECT COUNT(*) as orf_count, AVG(aa_length) as avg_orf_length
            FROM reannotated_orfs
            WHERE isolate_id IN (
                SELECT isolate_id FROM viral_isolates WHERE master_id = ?
            )
        """, (mid,))
        row = c.fetchone()
        orf_count = row[0] or 0
        avg_orf_length = row[1] or 0

        # ── Protein functional category proportions ──
        c.execute("""
            SELECT vp.protein_name, vp.gene_symbol
            FROM viral_proteins vp
            JOIN viral_isolates vi ON vp.isolate_id = vi.isolate_id
            WHERE vi.master_id = ?
        """, (mid,))

        func_counts = Counter({"structural": 0, "replication": 0, "assembly": 0,
                               "host_interaction": 0, "metabolism": 0, "unknown": 0})
        total_proteins = 0

        # Simple keyword-based classification (same logic as annotate_proteins.py)
        structural_kw = {"coat", "capsid", "nucleocapsid", "core protein", "matrix",
                         "envelope", "spike", "virion", "vp1", "vp2", "vp3", "vp4", "vp5"}
        replication_kw = {"polymerase", "replicase", "helicase", "primase", "reverse transcriptase",
                          "rna-dependent", "replication", "transcriptase", "polyprotein"}
        assembly_kw = {"protease", "proteinase", "peptidase", "packaging", "assembly", "maturation"}
        host_kw = {"immune", "apoptosis", "virulence", "pathogenicity", "toxin",
                   "kinase", "receptor", "host cell", "suppressor"}
        metabolism_kw = {"kinase", "synthase", "reductase", "methyltransferase", "atpase",
                         "phosphorylase", "nucleotide", "dutpase"}

        for prow in c.fetchall():
            text = f"{prow[0] or ''} {prow[1] or ''}".lower()
            total_proteins += 1
            if any(kw in text for kw in structural_kw):
                func_counts["structural"] += 1
            elif any(kw in text for kw in replication_kw):
                func_counts["replication"] += 1
            elif any(kw in text for kw in assembly_kw):
                func_counts["assembly"] += 1
            elif any(kw in text for kw in host_kw):
                func_counts["host_interaction"] += 1
            elif any(kw in text for kw in metabolism_kw):
                func_counts["metabolism"] += 1
            else:
                func_counts["unknown"] += 1

        # ── Host range ──
        c.execute("""
            SELECT COUNT(DISTINCT ir.host_id) as host_count
            FROM infection_records ir
            JOIN viral_isolates vi ON ir.isolate_id = vi.isolate_id
            WHERE vi.master_id = ?
        """, (mid,))
        host_count = c.fetchone()[0] or 0

        # Also from isolate_curated_profiles as backup
        if host_count == 0:
            c.execute("""
                SELECT COUNT(DISTINCT host_id) as host_count
                FROM isolate_curated_profiles
                WHERE master_id = ? AND host_id IS NOT NULL
            """, (mid,))
            host_count = c.fetchone()[0] or 0

        # ── Geographic range ──
        c.execute("""
            SELECT COUNT(DISTINCT sc.country) as country_count
            FROM sample_collections sc
            JOIN infection_records ir ON sc.collection_id = ir.collection_id
            JOIN viral_isolates vi ON ir.isolate_id = vi.isolate_id
            WHERE vi.master_id = ?
        """, (mid,))
        country_count = c.fetchone()[0] or 0

        if country_count == 0:
            c.execute("""
                SELECT COUNT(DISTINCT country) as country_count
                FROM isolate_curated_profiles
                WHERE master_id = ? AND country IS NOT NULL AND country != ''
            """, (mid,))
            country_count = c.fetchone()[0] or 0

        # ── Calculate proportions ──
        if total_proteins > 0:
            pct_structural = func_counts["structural"] / total_proteins
            pct_replication = func_counts["replication"] / total_proteins
            pct_assembly = func_counts["assembly"] / total_proteins
            pct_host = func_counts["host_interaction"] / total_proteins
            pct_metabolism = func_counts["metabolism"] / total_proteins
            pct_unknown = func_counts["unknown"] / total_proteins
        else:
            pct_structural = pct_replication = pct_assembly = pct_host = pct_metabolism = pct_unknown = 0

        features.append({
            "master_id": mid,
            "virus_name": name,
            "virus_family": family,
            "genome_type": genome_type,
            "isolate_count": isolate_count,
            "avg_genome_length": round(avg_genome_length, 1) if avg_genome_length else 0,
            "avg_gc_content": round(avg_gc, 3) if avg_gc else 0,
            "has_complete_genome": has_complete_genome,
            "orf_count": orf_count,
            "avg_orf_length": round(avg_orf_length, 1) if avg_orf_length else 0,
            "total_proteins": total_proteins,
            "pct_structural": round(pct_structural, 4),
            "pct_replication": round(pct_replication, 4),
            "pct_assembly": round(pct_assembly, 4),
            "pct_host_interaction": round(pct_host, 4),
            "pct_metabolism": round(pct_metabolism, 4),
            "pct_unknown": round(pct_unknown, 4),
            "host_range_breadth": host_count,
            "geographic_range": country_count,
        })

    return features


def save_features(features: list[dict]) -> None:
    if not features:
        print("No features extracted!")
        return

    fieldnames = list(features[0].keys())
    with open(OUT_CSV, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(features)

    print(f"\nSaved {len(features)} virus feature vectors to {OUT_CSV}")
    print("\nFeature summary:")
    print(f"  Avg genome length: {sum(v['avg_genome_length'] for v in features)/len(features):.0f}")
    print(f"  Avg GC content: {sum(v['avg_gc_content'] for v in features)/len(features):.3f}")
    print(f"  Avg host range: {sum(v['host_range_breadth'] for v in features)/len(features):.1f}")
    print(f"  Avg isolate count: {sum(v['isolate_count'] for v in features)/len(features):.1f}")


def main():
    print("=" * 60)
    print("Step 2: Extracting virus features for machine learning")
    print("=" * 60)

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row

    features = extract_features(conn)
    save_features(features)

    conn.close()
    print("\nDone! Next: run step3_predict_virulence_temperature.py")


if __name__ == "__main__":
    main()
