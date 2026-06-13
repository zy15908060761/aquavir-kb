"""
Create tables for protein 3D structures and domain annotations.
Provide a framework for AlphaFold3/ESMFold integration and rule-based domain prediction.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

DB_PATH = Path(r"F:\甲壳动物数据库\crustacean_virus_core.db")
STRUCTURES_DIR = Path(r"F:\甲壳动物数据库\downloads\structures")
STRUCTURES_DIR.mkdir(parents=True, exist_ok=True)


def create_tables(conn: sqlite3.Connection) -> None:
    c = conn.cursor()
    c.executescript("""
    -- Protein 3D structure predictions
    CREATE TABLE IF NOT EXISTS protein_structures (
        structure_id INTEGER PRIMARY KEY AUTOINCREMENT,
        cluster_id INTEGER,
        protein_id INTEGER,
        reanno_id INTEGER,
        prediction_method TEXT DEFAULT 'esmfold',
        model_version TEXT,
        pdb_file_path TEXT,
        plddt_score REAL,
        sequence_length INTEGER,
        prediction_date TEXT DEFAULT CURRENT_TIMESTAMP,
        api_source TEXT DEFAULT 'https://api.esmatlas.com',
        FOREIGN KEY (cluster_id) REFERENCES nr_protein_clusters(cluster_id),
        FOREIGN KEY (protein_id) REFERENCES viral_proteins(protein_id),
        FOREIGN KEY (reanno_id) REFERENCES reannotated_orfs(reanno_id),
        UNIQUE(cluster_id, prediction_method)
    );

    -- Protein domain annotations (rule-based or InterProScan)
    CREATE TABLE IF NOT EXISTS protein_domains (
        domain_id INTEGER PRIMARY KEY AUTOINCREMENT,
        cluster_id INTEGER,
        protein_id INTEGER,
        reanno_id INTEGER,
        domain_source TEXT DEFAULT 'rule_based',
        domain_name TEXT,
        domain_description TEXT,
        start_pos INTEGER,
        end_pos INTEGER,
        confidence_score REAL,
        domain_model TEXT,
        interpro_id TEXT,
        pfam_id TEXT,
        cdd_id TEXT,
        FOREIGN KEY (cluster_id) REFERENCES nr_protein_clusters(cluster_id),
        FOREIGN KEY (protein_id) REFERENCES viral_proteins(protein_id),
        FOREIGN KEY (reanno_id) REFERENCES reannotated_orfs(reanno_id)
    );

    CREATE INDEX IF NOT EXISTS idx_ps_cluster ON protein_structures(cluster_id);
    CREATE INDEX IF NOT EXISTS idx_ps_protein ON protein_structures(protein_id);
    CREATE INDEX IF NOT EXISTS idx_pd_cluster ON protein_domains(cluster_id);
    CREATE INDEX IF NOT EXISTS idx_pd_name ON protein_domains(domain_name);
    """)
    conn.commit()
    print("[DB] Created protein_structures and protein_domains tables")


# Rule-based domain annotation keywords
DOMAIN_RULES: list[tuple[set[str], str, str]] = [
    ({"rdrp", "rna-dependent rna polymerase", "rna dependent rna polymerase",
      "rna polymerase", "polymerase", "replicase"},
     "RdRp_domain", "RNA-dependent RNA polymerase catalytic domain"),
    ({"helicase", "rna helicase", "dna helicase", "superfamily 1 helicase",
      "sf1 helicase", "superfamily 2 helicase", "sf2 helicase"},
     "Helicase_domain", "NTP-dependent helicase domain"),
    ({"protease", "proteinase", "peptidase", "3c protease", "3c-like protease",
      "chymotrypsin-like protease", "serine protease", "cysteine protease"},
     "Protease_domain", "Viral protease domain"),
    ({"methyltransferase", "mtase", "rna methyltransferase", "cap methyltransferase"},
     "Methyltransferase_domain", "RNA cap methyltransferase domain"),
    ({"capsid", "coat protein", "nucleocapsid", "core protein", "vp1", "vp2", "vp3", "vp4"},
     "Capsid_domain", "Viral capsid protein"),
    ({"envelope", "spike protein", "peplomer", "surface protein", "glycoprotein"},
     "Envelope_domain", "Viral envelope glycoprotein"),
    ({"integrase", "transposase"},
     "Integrase_domain", "Viral integrase/transposase domain"),
    ({"reverse transcriptase", "rtase", "rna-directed dna polymerase"},
     "RT_domain", "Reverse transcriptase domain"),
    ({"rnaseh", "rnase h"},
     "RNaseH_domain", "Ribonuclease H domain"),
    ({"thymidine kinase", "tk"},
     "Thymidine_kinase", "Thymidine kinase domain"),
    ({"dUTPase", "dutp pyrophosphatase"},
     "dUTPase_domain", "dUTP pyrophosphatase domain"),
    ({"ankyrin repeat", "ank repeat"},
     "Ankyrin_repeat", "Ankyrin repeat domain (host interaction)"),
    ({"ring finger", "ring domain", "e3 ubiquitin ligase"},
     "RING_domain", "RING finger E3 ubiquitin ligase domain"),
    ({"bromodomain", "brd"},
     "Bromodomain", "Bromodomain (chromatin binding)"),
    ({"leucine-rich repeat", "lrr"},
     "LRR_domain", "Leucine-rich repeat domain"),
    ({"immunoglobulin", "ig domain", "ig-like"},
     "Ig_domain", "Immunoglobulin-like domain"),
]


def annotate_domains_rule_based(conn: sqlite3.Connection) -> int:
    """Annotate domains based on protein name keywords."""
    c = conn.cursor()
    c.execute("""
        SELECT protein_id, protein_name, gene_symbol, translation, isolate_id
        FROM viral_proteins
        WHERE (protein_name IS NOT NULL AND protein_name != '')
           OR (gene_symbol IS NOT NULL AND gene_symbol != '')
    """)
    rows = c.fetchall()
    print(f"\n[1/3] Annotating domains for {len(rows)} proteins...")

    inserted = 0
    for row in rows:
        text = f"{row['protein_name'] or ''} {row['gene_symbol'] or ''}".lower()
        for keywords, domain_name, desc in DOMAIN_RULES:
            if any(kw in text for kw in keywords):
                c.execute("""
                    INSERT OR IGNORE INTO protein_domains
                    (protein_id, domain_source, domain_name, domain_description,
                     start_pos, end_pos, confidence_score)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (row["protein_id"], "rule_based", domain_name, desc,
                      None, None, 0.6))
                inserted += c.rowcount
                break  # Only top match per protein

    conn.commit()
    print(f"    Inserted {inserted} domain annotations")
    return inserted


def predict_structures_with_esmfold(conn: sqlite3.Connection, limit: int = 20) -> int:
    """Fetch structures from ESMFold API for representative proteins."""
    import requests
    import time

    ESMFOLD_URL = "https://api.esmatlas.com/foldSequence/v1/pdb/"
    c = conn.cursor()

    # Select top NR clusters by size (most abundant proteins)
    c.execute("""
        SELECT cluster_id, representative_aa_seq, cluster_size
        FROM nr_protein_clusters
        WHERE representative_aa_seq IS NOT NULL
          AND length(representative_aa_seq) BETWEEN 50 AND 800
        ORDER BY cluster_size DESC
        LIMIT ?
    """, (limit,))
    clusters = c.fetchall()
    print(f"\n[2/3] Predicting structures for top {len(clusters)} NR clusters via ESMFold...")

    downloaded = 0
    for cl in clusters:
        cid = cl["cluster_id"]
        seq = cl["representative_aa_seq"]
        if not seq or len(seq) < 50 or len(seq) > 800:
            continue

        # Check if already predicted
        c.execute("SELECT 1 FROM protein_structures WHERE cluster_id = ? AND prediction_method = 'esmfold'", (cid,))
        if c.fetchone():
            continue

        try:
            resp = requests.post(ESMFOLD_URL, data=seq, headers={"Content-Type": "application/x-www-form-urlencoded"}, timeout=120)
            resp.raise_for_status()
            pdb_content = resp.text
            time.sleep(2.0)  # Rate limit
        except Exception as e:
            print(f"    [Error] ESMFold failed for cluster {cid}: {e}")
            time.sleep(2.0)
            continue

        if not pdb_content or len(pdb_content) < 100:
            continue

        # Parse pLDDT from PDB B-factor column (approximate)
        plddt_values = []
        for line in pdb_content.splitlines():
            if line.startswith("ATOM") and line[13:15].strip() == "CA":
                try:
                    plddt = float(line[60:66].strip())
                    plddt_values.append(plddt)
                except ValueError:
                    pass
        avg_plddt = round(sum(plddt_values) / len(plddt_values), 1) if plddt_values else None

        # Save PDB file
        pdb_path = STRUCTURES_DIR / f"cluster_{cid}_esmfold.pdb"
        pdb_path.write_text(pdb_content, encoding="utf-8")

        c.execute("""
            INSERT INTO protein_structures
            (cluster_id, prediction_method, model_version, pdb_file_path,
             plddt_score, sequence_length)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (cid, "esmfold", "v1", str(pdb_path), avg_plddt, len(seq)))
        downloaded += 1
        if downloaded % 5 == 0:
            conn.commit()
            print(f"    Downloaded {downloaded}/{len(clusters)} structures...")

    conn.commit()
    print(f"    Downloaded {downloaded} structures")
    return downloaded


def main() -> None:
    print("=" * 60)
    print("Protein Structures & Domain Annotations Setup")
    print("=" * 60)

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row

    create_tables(conn)
    domain_count = annotate_domains_rule_based(conn)
    struct_count = predict_structures_with_esmfold(conn, limit=50)

    # Summary
    print("\n[3/3] Summary:")
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM protein_domains")
    print(f"    Total domain annotations: {c.fetchone()[0]}")
    c.execute("SELECT domain_name, COUNT(*) FROM protein_domains GROUP BY domain_name ORDER BY COUNT(*) DESC LIMIT 10")
    print("    Top domain types:")
    for r in c.fetchall():
        print(f"      {r[0]:25s}: {r[1]:4d}")
    c.execute("SELECT COUNT(*) FROM protein_structures")
    print(f"    Total predicted structures: {c.fetchone()[0]}")
    c.execute("SELECT ROUND(AVG(plddt_score),1) FROM protein_structures WHERE plddt_score IS NOT NULL")
    print(f"    Average pLDDT score: {c.fetchone()[0]}")

    conn.close()
    print("\n" + "=" * 60)
    print("Done! Protein structure & domain framework ready.")
    print("=" * 60)
    print(f"\nStructures saved to: {STRUCTURES_DIR}")
    print("To predict all structures, increase 'limit' in predict_structures_with_esmfold()")
    print("For InterProScan domain annotation, run:")
    print("  interproscan.sh -i proteins.fasta -f tsv -o domains.tsv")


if __name__ == "__main__":
    main()
