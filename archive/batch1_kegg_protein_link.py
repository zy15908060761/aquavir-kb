"""
Batch 1b: KEGG注释关联到viral_proteins
策略: 通过ncbi_protein_acc匹配 (含版本号去重)
"""
import sqlite3
from pathlib import Path

DB = Path("F:/甲壳动物数据库/crustacean_virus_core.db")
conn = sqlite3.connect(str(DB))
conn.execute("PRAGMA foreign_keys = ON")
cur = conn.cursor()

total_kegg = cur.execute("SELECT COUNT(*) FROM kegg_annotations").fetchone()[0]
null_protein = cur.execute("SELECT COUNT(*) FROM kegg_annotations WHERE protein_id IS NULL").fetchone()[0]
print(f"KEGG total: {total_kegg}, without protein_id: {null_protein}")

# Strategy 1: Exact match on ncbi_protein_acc = protein_accession
print("\n[1] Exact accession match...")
cur.execute("""
    UPDATE kegg_annotations SET protein_id = (
        SELECT vp.protein_id FROM viral_proteins vp
        WHERE vp.protein_accession = kegg_annotations.ncbi_protein_acc
        LIMIT 1
    )
    WHERE protein_id IS NULL
      AND EXISTS (
        SELECT 1 FROM viral_proteins vp
        WHERE vp.protein_accession = kegg_annotations.ncbi_protein_acc
      )
""")
print(f"  Exact match: {cur.rowcount} rows")

# Strategy 2: Match without version suffix (e.g. "XP_123.1" -> "XP_123")
print("\n[2] Accession without version match...")
cur.execute("""
    UPDATE kegg_annotations SET protein_id = (
        SELECT vp.protein_id FROM viral_proteins vp
        WHERE REPLACE(vp.protein_accession, '.' ||
            CAST(CAST(SUBSTR(vp.protein_accession, INSTR(vp.protein_accession, '.')+1) AS INTEGER) AS TEXT),
            SUBSTR(vp.protein_accession, 1, INSTR(vp.protein_accession, '.')-1)
        ) = kegg_annotations.ncbi_protein_acc
        LIMIT 1
    )
    WHERE protein_id IS NULL
""")
# Simpler: extract base accession from both sides and match
# viral_proteins.protein_accession typically has version like "YBO34883.1"
# kegg_annotations.ncbi_protein_acc also has version like "XQJ32652.1"
# Just strip .version from both and match
cur.execute("""
    UPDATE kegg_annotations SET protein_id = (
        SELECT vp.protein_id FROM viral_proteins vp
        WHERE CASE WHEN INSTR(vp.protein_accession, '.') > 0
              THEN SUBSTR(vp.protein_accession, 1, INSTR(vp.protein_accession, '.') - 1)
              ELSE vp.protein_accession
              END =
              CASE WHEN INSTR(kegg_annotations.ncbi_protein_acc, '.') > 0
              THEN SUBSTR(kegg_annotations.ncbi_protein_acc, 1, INSTR(kegg_annotations.ncbi_protein_acc, '.') - 1)
              ELSE kegg_annotations.ncbi_protein_acc
              END
        LIMIT 1
    )
    WHERE protein_id IS NULL
      AND EXISTS (
        SELECT 1 FROM viral_proteins vp
        WHERE CASE WHEN INSTR(vp.protein_accession, '.') > 0
              THEN SUBSTR(vp.protein_accession, 1, INSTR(vp.protein_accession, '.') - 1)
              ELSE vp.protein_accession
              END =
              CASE WHEN INSTR(kegg_annotations.ncbi_protein_acc, '.') > 0
              THEN SUBSTR(kegg_annotations.ncbi_protein_acc, 1, INSTR(kegg_annotations.ncbi_protein_acc, '.') - 1)
              ELSE kegg_annotations.ncbi_protein_acc
              END
      )
""")
print(f"  Without-version match: {cur.rowcount} rows")

# Strategy 3: Match via uniprot_protein_links
print("\n[3] Via uniprot_protein_links...")
cur.execute("""
    UPDATE kegg_annotations SET protein_id = (
        SELECT upl.protein_id FROM uniprot_protein_links upl
        WHERE upl.uniprot_id = (
            SELECT ua.uniprot_id FROM uniprot_annotations ua
            WHERE ua.ncbi_protein_acc = kegg_annotations.ncbi_protein_acc
            LIMIT 1
        )
        AND upl.protein_id IS NOT NULL
        LIMIT 1
    )
    WHERE protein_id IS NULL
      AND EXISTS (
        SELECT 1 FROM uniprot_protein_links upl
        WHERE upl.uniprot_id = (
            SELECT ua.uniprot_id FROM uniprot_annotations ua
            WHERE ua.ncbi_protein_acc = kegg_annotations.ncbi_protein_acc
            LIMIT 1
        )
        AND upl.protein_id IS NOT NULL
      )
""")
print(f"  Via UniProt link: {cur.rowcount} rows")

# Strategy 4: Match via uniprot_annotations ncbi_protein_acc directly
print("\n[4] Via uniprot_annotations (strip version)...")
cur.execute("""
    UPDATE kegg_annotations SET protein_id = (
        SELECT vp.protein_id FROM viral_proteins vp
        JOIN uniprot_protein_links upl ON vp.protein_id = upl.protein_id
        JOIN uniprot_annotations ua ON upl.uniprot_id = ua.uniprot_id
        WHERE ua.ncbi_protein_acc = kegg_annotations.ncbi_protein_acc
        LIMIT 1
    )
    WHERE protein_id IS NULL
""")
print(f"  Via uniprot_annotations: {cur.rowcount} rows")

remaining = cur.execute("SELECT COUNT(*) FROM kegg_annotations WHERE protein_id IS NULL").fetchone()[0]
print(f"\n[Done] KEGG rows still without protein_id: {remaining}/{total_kegg} ({remaining*100//total_kegg if total_kegg else 0}%)")

conn.commit()
conn.close()
print("Saved.")
