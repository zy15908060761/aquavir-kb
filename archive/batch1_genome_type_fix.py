"""
Batch 1a: 补全 genome_type
策略:
  1. molecule_type -> genome_type 映射
  2. viralzone_families 的 family name 匹配 (genome_type列)
  3. ICTV taxonomy 的 genome_composition 列
"""
import sqlite3
from pathlib import Path

DB = Path("F:/甲壳动物数据库/crustacean_virus_core.db")
conn = sqlite3.connect(str(DB))
conn.execute("PRAGMA foreign_keys = ON")
cur = conn.cursor()

MOLECULE_MAP = {
    "DNA": "dsDNA",
    "RNA": None,  # ambiguous
    "mRNA": "ssRNA(+)",
    "cRNA": "ssRNA",
    "ss-RNA": "ssRNA",
    "ss-DNA": "ssDNA",
    "ds-RNA": "dsRNA",
    "ds-DNA": "dsDNA",
}

ICTV_GENOME_MAP = {
    "dsDNA": "dsDNA",
    "ssDNA": "ssDNA",
    "dsRNA": "dsRNA",
    "ssRNA(+)": "ssRNA(+)",
    "ssRNA(-)": "ssRNA(-)",
    "ssRNA": "ssRNA",
    "ssRNA-RT": "ssRNA-RT",
    "dsDNA-RT": "dsDNA-RT",
}

# Step 1: From molecule_type
print("[1] Filling genome_type from molecule_type...")
for mol, gt in MOLECULE_MAP.items():
    if gt is None:
        continue
    cur.execute("""
        UPDATE viral_isolates SET genome_type = ?
        WHERE genome_type IS NULL AND molecule_type = ?
    """, (gt, mol))
    print(f"  {mol} -> {gt}: {cur.rowcount} rows")

# Step 2: From viralzone_families (check column names)
print("\n[2] Checking viralzone_families schema...")
cols = [d[0] for d in cur.execute("PRAGMA table_info(viralzone_families)").fetchall()]
print(f"  Columns: {cols}")
# Column 1 = family name, check col for genome_type
# Try column "genome_type" if exists
has_genome_type = "genome_type" in cols
has_family = "family" in cols

if has_genome_type and has_family:
    cur.execute("""
        UPDATE viral_isolates SET genome_type = (
            SELECT vf.genome_type FROM viralzone_families vf
            WHERE vf.family = viral_isolates.taxon_family
            LIMIT 1
        )
        WHERE genome_type IS NULL
          AND taxon_family IS NOT NULL
          AND EXISTS (
            SELECT 1 FROM viralzone_families vf
            WHERE vf.family = viral_isolates.taxon_family
              AND vf.genome_type IS NOT NULL
          )
    """)
    print(f"  viralzone_families match: {cur.rowcount} rows")
else:
    print("  (skipped - genome_type column not found in viralzone_families)")

# Step 3: From ICTV taxonomy genome_composition
print("\n[3] Filling from ICTV taxonomy genome_composition...")
cur.execute("""
    UPDATE viral_isolates SET genome_type = (
        SELECT it.genome_composition FROM ictv_taxonomy it
        WHERE it.family = viral_isolates.taxon_family
        LIMIT 1
    )
    WHERE genome_type IS NULL
      AND taxon_family IS NOT NULL
      AND EXISTS (
        SELECT 1 FROM ictv_taxonomy it
        WHERE it.family = viral_isolates.taxon_family
          AND it.genome_composition IS NOT NULL
      )
""")
print(f"  ICTV taxonomy match: {cur.rowcount} rows")

# Step 4: Infer from keywords/definition text
print("\n[4] Inferring from definition text keywords...")
for keyword, gt in [
    ("double-strand", "dsDNA"), ("double stranded", "dsDNA"),
    ("dsDNA", "dsDNA"), ("dsRNA", "dsRNA"),
    ("ssRNA", "ssRNA"), ("ssDNA", "ssDNA"),
    ("single-strand", "ssRNA"), ("single stranded", "ssRNA"),
    ("positive-sense", "ssRNA(+)"), ("positive sense", "ssRNA(+)"),
    ("negative-sense", "ssRNA(-)"), ("negative sense", "ssRNA(-)"),
]:
    cur.execute("""
        UPDATE viral_isolates SET genome_type = ?
        WHERE genome_type IS NULL
          AND (virus_name LIKE ? OR keywords LIKE ?)
    """, (gt, f"%{keyword}%", f"%{keyword}%"))
    n = cur.rowcount
    if n:
        print(f"  '{keyword}' -> {gt}: {n} rows")

# Report remaining
remaining = cur.execute("SELECT COUNT(*) FROM viral_isolates WHERE genome_type IS NULL").fetchone()[0]
total = cur.execute("SELECT COUNT(*) FROM viral_isolates").fetchone()[0]
print(f"\n[Done] genome_type still NULL: {remaining}/{total} ({remaining*100//total if total else 0}%)")

conn.commit()
conn.close()
print("Saved.")
