"""
Batch 4: Round 2 completeness fixes
- interpro_annotations.protein_id via uniprot_protein_links
- KEGG additional protein_id via uniprot pathway
- KEGG ko_definition from ko_name inference
- core_genes.function_summary auto-generation
- infection_records.reference_id backfill from isolate_reference_links
- diagnostic_methods.reference_id backfill
"""
import sqlite3
from pathlib import Path

DB = Path("F:/甲壳动物数据库/crustacean_virus_core.db")
conn = sqlite3.connect(str(DB))
conn.execute("PRAGMA foreign_keys = ON")
cur = conn.cursor()

# ============================================================
# 1. interpro_annotations.protein_id via uniprot_protein_links
# ============================================================
print("=" * 60)
print("1. InterPro annotations -> protein_id linking")
before = cur.execute("SELECT COUNT(*) FROM interpro_annotations WHERE protein_id IS NULL").fetchone()[0]

cur.execute("""
    UPDATE interpro_annotations SET protein_id = (
        SELECT upl.protein_id FROM uniprot_protein_links upl
        WHERE upl.uniprot_id = interpro_annotations.uniprot_id
        LIMIT 1
    )
    WHERE protein_id IS NULL
      AND EXISTS (
        SELECT 1 FROM uniprot_protein_links upl
        WHERE upl.uniprot_id = interpro_annotations.uniprot_id
      )
""")
linked = cur.rowcount
after = cur.execute("SELECT COUNT(*) FROM interpro_annotations WHERE protein_id IS NULL").fetchone()[0]
total = cur.execute("SELECT COUNT(*) FROM interpro_annotations").fetchone()[0]
print("  Linked: %d, still NULL: %d/%d (%d%% filled)" % (linked, after, total, (total-after)*100//total))

# ============================================================
# 2. KEGG additional linking via uniprot pathway
# ============================================================
print()
print("2. KEGG additional protein_id via uniprot pathway")
before = cur.execute("SELECT COUNT(*) FROM kegg_annotations WHERE protein_id IS NULL").fetchone()[0]

cur.execute("""
    UPDATE kegg_annotations SET protein_id = (
        SELECT upl.protein_id FROM uniprot_annotations ua
        JOIN uniprot_protein_links upl ON ua.uniprot_id = upl.uniprot_id
        WHERE ua.ncbi_protein_acc = kegg_annotations.ncbi_protein_acc
        LIMIT 1
    )
    WHERE protein_id IS NULL
      AND EXISTS (
        SELECT 1 FROM uniprot_annotations ua
        JOIN uniprot_protein_links upl ON ua.uniprot_id = upl.uniprot_id
        WHERE ua.ncbi_protein_acc = kegg_annotations.ncbi_protein_acc
      )
""")
linked = cur.rowcount
after = cur.execute("SELECT COUNT(*) FROM kegg_annotations WHERE protein_id IS NULL").fetchone()[0]
total = cur.execute("SELECT COUNT(*) FROM kegg_annotations").fetchone()[0]
print("  Linked: %d, still NULL: %d/%d (%d%% filled)" % (linked, after, total, (total-after)*100//total))

# Also try matching via uniprot_id without accession version
cur.execute("""
    UPDATE kegg_annotations SET protein_id = (
        SELECT upl.protein_id FROM uniprot_annotations ua
        JOIN uniprot_protein_links upl ON ua.uniprot_id = upl.uniprot_id
        WHERE REPLACE(ua.ncbi_protein_acc, '.' ||
            CAST(CAST(SUBSTR(ua.ncbi_protein_acc, INSTR(ua.ncbi_protein_acc, '.')+1) AS INTEGER) AS TEXT),
            SUBSTR(ua.ncbi_protein_acc, 1, INSTR(ua.ncbi_protein_acc, '.')-1)
        ) = kegg_annotations.ncbi_protein_acc
        LIMIT 1
    )
    WHERE protein_id IS NULL
""")
# Simpler approach
cur.execute("""
    UPDATE kegg_annotations SET protein_id = (
        SELECT upl.protein_id FROM uniprot_annotations ua
        JOIN uniprot_protein_links upl ON ua.uniprot_id = upl.uniprot_id
        WHERE ua.ncbi_protein_acc = kegg_annotations.ncbi_protein_acc
           OR (INSTR(ua.ncbi_protein_acc,'.') > 0 AND
               SUBSTR(ua.ncbi_protein_acc, 1, INSTR(ua.ncbi_protein_acc,'.')-1) =
               CASE WHEN INSTR(kegg_annotations.ncbi_protein_acc,'.') > 0
               THEN SUBSTR(kegg_annotations.ncbi_protein_acc, 1, INSTR(kegg_annotations.ncbi_protein_acc,'.')-1)
               ELSE kegg_annotations.ncbi_protein_acc END)
        LIMIT 1
    )
    WHERE protein_id IS NULL
""")
print("  Extra via version-stripped match: %d" % cur.rowcount)

after2 = cur.execute("SELECT COUNT(*) FROM kegg_annotations WHERE protein_id IS NULL").fetchone()[0]
print("  Final NULL: %d/%d (%d%% filled)" % (after2, total, (total-after2)*100//total))

# ============================================================
# 3. KEGG ko_definition inference from ko_name
# ============================================================
print()
print("3. KEGG ko_definition inference")
before = cur.execute("SELECT COUNT(*) FROM kegg_annotations WHERE ko_definition IS NULL OR TRIM(ko_definition)=''").fetchone()[0]

# ko_name already provides a description, use it as ko_definition when missing
cur.execute("""
    UPDATE kegg_annotations SET ko_definition = 'inferred: ' || ko_name
    WHERE (ko_definition IS NULL OR TRIM(ko_definition) = '')
      AND ko_name IS NOT NULL AND TRIM(ko_name) <> ''
""")
print("  Filled from ko_name: %d" % cur.rowcount)

after = cur.execute("SELECT COUNT(*) FROM kegg_annotations WHERE ko_definition IS NULL OR TRIM(ko_definition)=''").fetchone()[0]
print("  Still NULL: %d/%d" % (after, total))

# ============================================================
# 4. core_genes.function_summary auto-generation
# ============================================================
print()
print("4. core_genes.function_summary auto-generation")
before = cur.execute("SELECT COUNT(*) FROM core_genes WHERE function_summary IS NULL OR TRIM(function_summary)=''").fetchone()[0]

# Generate from functional_category + gene_symbol + conservation
cur.execute("""
    UPDATE core_genes SET function_summary =
        'Functional category: ' || COALESCE(functional_category, 'unknown') ||
        '; Conservation: ' || CAST(ROUND(COALESCE(conservation_rate, 0) * 100) AS TEXT) || '%' ||
        ' (' || COALESCE(present_isolates, 0) || '/' || COALESCE(total_isolates, 0) || ' isolates)'
    WHERE (function_summary IS NULL OR TRIM(function_summary) = '')
""")
print("  Auto-generated: %d" % cur.rowcount)
after = cur.execute("SELECT COUNT(*) FROM core_genes WHERE function_summary IS NULL OR TRIM(function_summary)=''").fetchone()[0]
total = cur.execute("SELECT COUNT(*) FROM core_genes").fetchone()[0]
print("  Still NULL: %d/%d (%d%% filled)" % (after, total, (total-after)*100//total))

# ============================================================
# 5. infection_records.reference_id from isolate_reference_links
# ============================================================
print()
print("5. infection_records.reference_id backfill")
before = cur.execute("SELECT COUNT(*) FROM infection_records WHERE reference_id IS NULL").fetchone()[0]

cur.execute("""
    UPDATE infection_records SET reference_id = (
        SELECT irl.reference_id FROM isolate_reference_links irl
        WHERE irl.isolate_id = infection_records.isolate_id
        LIMIT 1
    )
    WHERE reference_id IS NULL
      AND EXISTS (
        SELECT 1 FROM isolate_reference_links irl
        WHERE irl.isolate_id = infection_records.isolate_id
      )
""")
print("  From isolate_reference_links: %d" % cur.rowcount)

# Also from viral_isolates.reference_id
cur.execute("""
    UPDATE infection_records SET reference_id = (
        SELECT vi.reference_id FROM viral_isolates vi
        WHERE vi.isolate_id = infection_records.isolate_id
          AND vi.reference_id IS NOT NULL
    )
    WHERE reference_id IS NULL
""")
print("  From viral_isolates: %d" % cur.rowcount)

after = cur.execute("SELECT COUNT(*) FROM infection_records WHERE reference_id IS NULL").fetchone()[0]
total = cur.execute("SELECT COUNT(*) FROM infection_records").fetchone()[0]
print("  Still NULL: %d/%d (%d%% filled)" % (after, total, (total-after)*100//total))

# ============================================================
# 6. diagnostic_methods backfill
# ============================================================
print()
print("6. diagnostic_methods.reference_id backfill")
before = cur.execute("SELECT COUNT(*) FROM diagnostic_methods WHERE reference_id IS NULL").fetchone()[0]

# Check if there are literature records for diagnostic methods
# Backfill from evidence_records or literature
cur.execute("""
    UPDATE diagnostic_methods SET reference_id = (
        SELECT er.reference_id FROM evidence_records er
        WHERE er.evidence_type = 'diagnosis'
          AND er.virus_master_id = diagnostic_methods.virus_master_id
          AND er.reference_id IS NOT NULL
        LIMIT 1
    )
    WHERE reference_id IS NULL
""")
print("  From evidence_records: %d" % cur.rowcount)

after = cur.execute("SELECT COUNT(*) FROM diagnostic_methods WHERE reference_id IS NULL").fetchone()[0]
total = cur.execute("SELECT COUNT(*) FROM diagnostic_methods").fetchone()[0]
print("  Still NULL: %d/%d (%d%% filled)" % (after, total, (total-after)*100//total))

# ============================================================
# 7. interpro_annotations.go_terms enrichment from interpro_go_terms
# ============================================================
print()
print("7. interpro_annotations.go_terms from interpro_go_terms")
# Check if interpro_go_terms has data we can use
gt_count = cur.execute("SELECT COUNT(*) FROM interpro_go_terms").fetchone()[0]
print("  interpro_go_terms available: %d" % gt_count)

# If interpro_go_backfill_queue has mappings, use them
bf_count = cur.execute("SELECT COUNT(*) FROM interpro_go_backfill_queue").fetchone()[0]
print("  interpro_go_backfill_queue: %d" % bf_count)

conn.commit()
conn.close()
print()
print("Batch 4 complete. Saved.")
