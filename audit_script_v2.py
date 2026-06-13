#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CrustaVirus DB Comprehensive Integrity Audit Script v2
"""

import sqlite3
import json
import os
import re
from collections import defaultdict

DB_PATH = r"F:\甲壳动物数据库\crustacean_virus_core.db"
OUTPUT_DIR = r"F:\甲壳动物数据库\reports\comprehensive_audit_20260509"
os.makedirs(OUTPUT_DIR, exist_ok=True)

conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()

results = {
    "pragma_checks": {},
    "schema_issues": [],
    "datatype_issues": [],
    "cross_table_issues": [],
    "index_issues": [],
    "fts_issues": [],
    "view_issues": [],
    "constraint_issues": []
}

# ============================================================
# 1. PRAGMA CONFIGURATION CHECKS
# ============================================================
print("[*] Checking PRAGMA configurations...")

pragma_checks = [
    "foreign_keys",
    "journal_mode",
    "synchronous",
    "page_size",
    "auto_vacuum",
    "encoding",
    "secure_delete",
    "recursive_triggers",
    "temp_store",
    "wal_autocheckpoint"
]

for pragma in pragma_checks:
    cursor.execute(f"PRAGMA {pragma}")
    row = cursor.fetchone()
    results["pragma_checks"][pragma] = row[0] if row else None

# Check freelist count (indicates fragmentation)
cursor.execute("PRAGMA freelist_count")
results["pragma_checks"]["freelist_count"] = cursor.fetchone()[0]

# Check page count
cursor.execute("PRAGMA page_count")
results["pragma_checks"]["page_count"] = cursor.fetchone()[0]

# Check integrity
print("[*] Running PRAGMA integrity_check...")
cursor.execute("PRAGMA integrity_check")
integrity_result = cursor.fetchall()
results["pragma_checks"]["integrity_check"] = [r[0] for r in integrity_result]

# Check foreign key integrity
print("[*] Running PRAGMA foreign_key_check...")
cursor.execute("PRAGMA foreign_key_check")
fk_violations = cursor.fetchall()
results["pragma_checks"]["foreign_key_check_violations"] = len(fk_violations)
results["pragma_checks"]["foreign_key_check_samples"] = fk_violations[:20]

# ============================================================
# 2. SCHEMA ANALYSIS - Get full schema info
# ============================================================
print("[*] Analyzing schema...")

cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
tables = [r[0] for r in cursor.fetchall()]

schema_info = {}
for table in tables:
    cursor.execute(f"PRAGMA table_info([{table}])")
    columns = []
    pks = []
    for row in cursor.fetchall():
        cid, name, ctype, notnull, dflt, pk = row
        columns.append({
            "cid": cid, "name": name, "type": ctype,
            "notnull": notnull, "dflt_value": dflt, "pk": pk
        })
        if pk:
            pks.append(name)
    
    cursor.execute(f"PRAGMA index_list([{table}])")
    indexes = []
    for row in cursor.fetchall():
        seq, name, unique, origin, partial = row
        indexes.append({"seq": seq, "name": name, "unique": unique, "origin": origin, "partial": partial})
    
    cursor.execute(f"SELECT COUNT(*) FROM [{table}]")
    row_count = cursor.fetchone()[0]
    
    schema_info[table] = {
        "columns": columns,
        "indexes": indexes,
        "row_count": row_count,
        "pks": pks
    }

results["schema_info"] = schema_info

# ============================================================
# 3. NOT NULL CONSTRAINT ANALYSIS ON CORE TABLES
# ============================================================
print("[*] Checking NOT NULL constraints on core tables...")

core_tables = ["viral_isolates", "viral_proteins", "infection_records", 
               "sample_collections", "crustacean_hosts", "virus_master",
               "ref_literatures", "nucleotide_records", "protein_structures"]

for table in core_tables:
    if table not in schema_info:
        continue
    cols_without_nn = [c for c in schema_info[table]["columns"] if c["notnull"] == 0 and c["dflt_value"] is None]
    cols_without_nn = [c for c in cols_without_nn if not c["pk"] and c["name"] not in 
                       ["created_at", "updated_at", "notes", "description", "raw_json", 
                        "additional_info", "metadata", "source", "curator", "comments", 
                        "note", "abstract", "keywords", "fetched_at", "quality_notes"]]
    if cols_without_nn:
        results["constraint_issues"].append({
            "table": table,
            "issue": "NOT_NULL_MISSING",
            "columns": [{"name": c["name"], "type": c["type"]} for c in cols_without_nn],
            "severity": "HIGH" if table in ["viral_isolates", "viral_proteins", "infection_records"] else "MEDIUM"
        })

# ============================================================
# 4. UNIQUE CONSTRAINT ANALYSIS
# ============================================================
print("[*] Checking UNIQUE constraints...")

if "viral_isolates" in schema_info:
    cursor.execute("""
        SELECT accession, COUNT(*) as cnt FROM viral_isolates 
        WHERE accession IS NOT NULL GROUP BY accession HAVING cnt > 1
    """)
    dup_accessions = cursor.fetchall()
    if dup_accessions:
        results["constraint_issues"].append({
            "table": "viral_isolates",
            "issue": "DUPLICATE_ACCESSION",
            "count": len(dup_accessions),
            "samples": dup_accessions[:10],
            "severity": "CRITICAL"
        })

if "virus_master" in schema_info:
    cursor.execute("""
        SELECT canonical_name, COUNT(*) as cnt FROM virus_master 
        WHERE canonical_name IS NOT NULL GROUP BY canonical_name HAVING cnt > 1
    """)
    dup_names = cursor.fetchall()
    if dup_names:
        results["constraint_issues"].append({
            "table": "virus_master",
            "issue": "DUPLICATE_CANONICAL_NAME",
            "count": len(dup_names),
            "samples": dup_names[:10],
            "severity": "CRITICAL"
        })

if "crustacean_hosts" in schema_info:
    cursor.execute("""
        SELECT scientific_name, COUNT(*) as cnt FROM crustacean_hosts 
        WHERE scientific_name IS NOT NULL GROUP BY scientific_name HAVING cnt > 1
    """)
    dup_hosts = cursor.fetchall()
    if dup_hosts:
        results["constraint_issues"].append({
            "table": "crustacean_hosts",
            "issue": "DUPLICATE_SCIENTIFIC_NAME",
            "count": len(dup_hosts),
            "samples": dup_hosts[:10],
            "severity": "HIGH"
        })

# ============================================================
# 5. FOREIGN KEY INDEX CHECKS
# ============================================================
print("[*] Checking foreign key index coverage...")

cursor.execute("SELECT name, sql FROM sqlite_master WHERE type='table'")
table_sqls = {r[0]: r[1] for r in cursor.fetchall()}

fk_patterns = []
for tname, sql in table_sqls.items():
    if not sql:
        continue
    fks = re.findall(r'FOREIGN\s+KEY\s*\(\s*([^)]+)\s*\)\s*REFERENCES\s+(\w+)', sql, re.IGNORECASE)
    for fk_col, ref_table in fks:
        fk_col = fk_col.strip().strip('"').strip("'")
        fk_patterns.append({"table": tname, "column": fk_col, "references": ref_table})

results["foreign_keys"] = fk_patterns

# Check if FK columns are indexed
for fk in fk_patterns:
    table = fk["table"]
    col = fk["column"]
    idxs = schema_info.get(table, {}).get("indexes", [])
    has_index = False
    for idx in idxs:
        cursor.execute(f"PRAGMA index_info([{idx['name']}])")
        idx_cols = [r[2] for r in cursor.fetchall()]
        if col in idx_cols:
            has_index = True
            break
    if not has_index:
        results["index_issues"].append({
            "issue": "FK_WITHOUT_INDEX",
            "table": table,
            "column": col,
            "references": fk["references"],
            "severity": "HIGH"
        })

# ============================================================
# 6. DATA TYPE CONSISTENCY
# ============================================================
print("[*] Checking data type consistency...")

bool_checks = [
    ("viral_isolates", "has_sequence"),
    ("virus_master", "is_crustacean_virus"),
    ("viral_proteins", "is_rdrp"),
]

for table, col in bool_checks:
    if table not in schema_info:
        continue
    col_names = [c["name"] for c in schema_info[table]["columns"]]
    if col not in col_names:
        continue
    cursor.execute(f"SELECT DISTINCT [{col}] FROM [{table}] WHERE [{col}] IS NOT NULL LIMIT 20")
    distinct_vals = [r[0] for r in cursor.fetchall()]
    if distinct_vals:
        results["datatype_issues"].append({
            "issue": "BOOLEAN_REPRESENTATION",
            "table": table,
            "column": col,
            "distinct_values": distinct_vals,
            "severity": "MEDIUM"
        })

# Check TEXT-stored dates
date_columns = [
    ("ref_literatures", "year"),
    ("nucleotide_records", "create_date"),
    ("nucleotide_records", "update_date"),
]

for table, col in date_columns:
    if table not in schema_info:
        continue
    col_names = [c["name"] for c in schema_info[table]["columns"]]
    if col not in col_names:
        continue
    cursor.execute(f"SELECT DISTINCT [{col}] FROM [{table}] WHERE [{col}] IS NOT NULL AND [{col}] != '' ORDER BY [{col}] DESC LIMIT 20")
    samples = [r[0] for r in cursor.fetchall()]
    if samples:
        results["datatype_issues"].append({
            "issue": "DATE_AS_TEXT",
            "table": table,
            "column": col,
            "sample_values": samples,
            "severity": "MEDIUM"
        })

# ============================================================
# 7. CROSS-TABLE CONSISTENCY
# ============================================================
print("[*] Checking cross-table consistency...")

# 7a. viral_isolates.virus_name vs virus_master.canonical_name
if "viral_isolates" in schema_info and "virus_master" in schema_info:
    cursor.execute("""
        SELECT DISTINCT vi.virus_name 
        FROM viral_isolates vi 
        LEFT JOIN virus_master vm ON LOWER(vi.virus_name) = LOWER(vm.canonical_name)
        WHERE vi.virus_name IS NOT NULL AND vm.canonical_name IS NULL
    """)
    orphan_virus_names = cursor.fetchall()
    if orphan_virus_names:
        results["cross_table_issues"].append({
            "issue": "ISOLATE_VIRUS_NAME_NOT_IN_MASTER",
            "count": len(orphan_virus_names),
            "samples": [r[0] for r in orphan_virus_names[:20]],
            "severity": "CRITICAL"
        })

# 7b. viral_isolates.master_id vs virus_master.master_id
if "viral_isolates" in schema_info and "virus_master" in schema_info:
    cursor.execute("""
        SELECT COUNT(*) FROM viral_isolates vi 
        LEFT JOIN virus_master vm ON vi.master_id = vm.master_id
        WHERE vi.master_id IS NOT NULL AND vm.master_id IS NULL
    """)
    orphan_master = cursor.fetchone()[0]
    if orphan_master > 0:
        results["cross_table_issues"].append({
            "issue": "ISOLATE_MASTER_ID_NOT_IN_MASTER",
            "count": orphan_master,
            "severity": "CRITICAL"
        })

# 7c. sample_collections latitude/longitude range
if "sample_collections" in schema_info:
    cursor.execute("""
        SELECT collection_id, latitude, longitude 
        FROM sample_collections 
        WHERE latitude IS NOT NULL AND (CAST(latitude AS REAL) < -90 OR CAST(latitude AS REAL) > 90)
        LIMIT 20
    """)
    bad_lat = cursor.fetchall()
    if bad_lat:
        results["cross_table_issues"].append({
            "issue": "INVALID_LATITUDE",
            "count": len(bad_lat),
            "samples": bad_lat,
            "severity": "HIGH"
        })

    cursor.execute("""
        SELECT collection_id, latitude, longitude 
        FROM sample_collections 
        WHERE longitude IS NOT NULL AND (CAST(longitude AS REAL) < -180 OR CAST(longitude AS REAL) > 180)
        LIMIT 20
    """)
    bad_lon = cursor.fetchall()
    if bad_lon:
        results["cross_table_issues"].append({
            "issue": "INVALID_LONGITUDE",
            "count": len(bad_lon),
            "samples": bad_lon,
            "severity": "HIGH"
        })

    # collection_year合理性
    cursor.execute("""
        SELECT collection_id, collection_year 
        FROM sample_collections 
        WHERE collection_year IS NOT NULL AND collection_year != ''
        AND (CAST(collection_year AS INTEGER) < 1900 OR CAST(collection_year AS INTEGER) > 2026)
        LIMIT 20
    """)
    bad_years = cursor.fetchall()
    if bad_years:
        results["cross_table_issues"].append({
            "issue": "INVALID_COLLECTION_YEAR",
            "count": len(bad_years),
            "samples": bad_years,
            "severity": "HIGH"
        })

# 7d. infection_records 引用不存在的 isolate_id
if "infection_records" in schema_info and "viral_isolates" in schema_info:
    cursor.execute("""
        SELECT COUNT(*) FROM infection_records ir 
        LEFT JOIN viral_isolates vi ON ir.isolate_id = vi.isolate_id
        WHERE ir.isolate_id IS NOT NULL AND vi.isolate_id IS NULL
    """)
    orphan_iso_count = cursor.fetchone()[0]
    if orphan_iso_count > 0:
        results["cross_table_issues"].append({
            "issue": "INFECTION_REFERENCES_INVALID_ISOLATE",
            "count": orphan_iso_count,
            "severity": "CRITICAL"
        })

# 7e. infection_records 引用不存在的 host_id
if "infection_records" in schema_info and "crustacean_hosts" in schema_info:
    cursor.execute("""
        SELECT COUNT(*) FROM infection_records ir 
        LEFT JOIN crustacean_hosts ch ON ir.host_id = ch.host_id
        WHERE ir.host_id IS NOT NULL AND ch.host_id IS NULL
    """)
    orphan_host_count = cursor.fetchone()[0]
    if orphan_host_count > 0:
        results["cross_table_issues"].append({
            "issue": "INFECTION_REFERENCES_INVALID_HOST",
            "count": orphan_host_count,
            "severity": "CRITICAL"
        })

# 7f. infection_records 引用不存在的 collection_id
if "infection_records" in schema_info and "sample_collections" in schema_info:
    cursor.execute("""
        SELECT COUNT(*) FROM infection_records ir 
        LEFT JOIN sample_collections sc ON ir.collection_id = sc.collection_id
        WHERE ir.collection_id IS NOT NULL AND sc.collection_id IS NULL
    """)
    orphan_coll_count = cursor.fetchone()[0]
    if orphan_coll_count > 0:
        results["cross_table_issues"].append({
            "issue": "INFECTION_REFERENCES_INVALID_COLLECTION",
            "count": orphan_coll_count,
            "severity": "CRITICAL"
        })

# 7g. viral_proteins 引用不存在的 isolate_id
if "viral_proteins" in schema_info and "viral_isolates" in schema_info:
    cursor.execute("""
        SELECT COUNT(*) FROM viral_proteins vp 
        LEFT JOIN viral_isolates vi ON vp.isolate_id = vi.isolate_id
        WHERE vp.isolate_id IS NOT NULL AND vi.isolate_id IS NULL
    """)
    orphan_prot_iso = cursor.fetchone()[0]
    if orphan_prot_iso > 0:
        results["cross_table_issues"].append({
            "issue": "PROTEIN_REFERENCES_INVALID_ISOLATE",
            "count": orphan_prot_iso,
            "severity": "CRITICAL"
        })

# 7h. nucleotide_records 引用不存在的 isolate_id
if "nucleotide_records" in schema_info and "viral_isolates" in schema_info:
    cursor.execute("""
        SELECT COUNT(*) FROM nucleotide_records nr 
        LEFT JOIN viral_isolates vi ON nr.isolate_id = vi.isolate_id
        WHERE nr.isolate_id IS NOT NULL AND vi.isolate_id IS NULL
    """)
    orphan_nt_iso = cursor.fetchone()[0]
    if orphan_nt_iso > 0:
        results["cross_table_issues"].append({
            "issue": "NUCLEOTIDE_REFERENCES_INVALID_ISOLATE",
            "count": orphan_nt_iso,
            "severity": "CRITICAL"
        })

# 7i. ref_literatures year format
if "ref_literatures" in schema_info:
    cursor.execute("""
        SELECT DISTINCT year FROM ref_literatures 
        WHERE year IS NOT NULL AND year != '' 
        AND (year GLOB '*[^0-9]*' OR LENGTH(year) != 4)
        LIMIT 20
    """)
    bad_year_fmt = cursor.fetchall()
    if bad_year_fmt:
        results["cross_table_issues"].append({
            "issue": "REFERENCE_YEAR_NON_STANDARD_FORMAT",
            "count": len(bad_year_fmt),
            "samples": [r[0] for r in bad_year_fmt],
            "severity": "MEDIUM"
        })

    # DOI格式检查
    cursor.execute("""
        SELECT doi FROM ref_literatures 
        WHERE doi IS NOT NULL AND doi != '' 
        AND doi NOT LIKE '10.%'
        LIMIT 20
    """)
    bad_doi = cursor.fetchall()
    if bad_doi:
        results["cross_table_issues"].append({
            "issue": "REFERENCE_DOI_INVALID_FORMAT",
            "count": len(bad_doi),
            "samples": [r[0] for r in bad_doi],
            "severity": "MEDIUM"
        })

# ============================================================
# 8. REDUNDANT INDEXES
# ============================================================
print("[*] Checking for redundant indexes...")

for table, info in schema_info.items():
    if table.startswith("sqlite_") or "fts" in table:
        continue
    idx_dict = {}
    for idx in info["indexes"]:
        if idx["name"].startswith("sqlite_autoindex"):
            continue
        cursor.execute(f"PRAGMA index_info([{idx['name']}])")
        cols = tuple(r[2] for r in cursor.fetchall())
        idx_dict[idx["name"]] = {"cols": cols, "unique": idx["unique"]}
    
    names = list(idx_dict.keys())
    for i in range(len(names)):
        for j in range(len(names)):
            if i == j:
                continue
            if len(idx_dict[names[i]]["cols"]) <= len(idx_dict[names[j]]["cols"]):
                if idx_dict[names[i]]["cols"] == idx_dict[names[j]]["cols"][:len(idx_dict[names[i]]["cols"])]:
                    if not idx_dict[names[i]]["unique"]:
                        results["index_issues"].append({
                            "issue": "REDUNDANT_INDEX",
                            "table": table,
                            "index_shorter": names[i],
                            "index_longer": names[j],
                            "severity": "LOW"
                        })

# ============================================================
# 9. MISSING INDEXES ON HIGH-CARDINALITY COLUMNS
# ============================================================
print("[*] Checking for missing indexes on key columns...")

key_columns_to_check = [
    ("viral_isolates", "master_id"),
    ("viral_isolates", "collection_id"),
    ("viral_proteins", "isolate_id"),
    ("infection_records", "reference_id"),
    ("sample_collections", "country"),
    ("ref_literatures", "year"),
]

for table, col in key_columns_to_check:
    if table not in schema_info:
        continue
    col_names = [c["name"] for c in schema_info[table]["columns"]]
    if col not in col_names:
        continue
    has_idx = False
    for idx in schema_info[table]["indexes"]:
        cursor.execute(f"PRAGMA index_info([{idx['name']}])")
        cols = [r[2] for r in cursor.fetchall()]
        if col in cols:
            has_idx = True
            break
    if not has_idx:
        cursor.execute(f"SELECT COUNT(DISTINCT [{col}]) FROM [{table}]")
        card = cursor.fetchone()[0]
        if card > 1:
            results["index_issues"].append({
                "issue": "MISSING_INDEX_ON_KEY_COLUMN",
                "table": table,
                "column": col,
                "cardinality": card,
                "severity": "MEDIUM" if card > 10 else "LOW"
            })

# ============================================================
# 10. FTS TABLE CHECKS
# ============================================================
print("[*] Checking FTS configuration...")

fts_tables = [t for t in tables if "fts" in t]
results["fts_issues"].append({
    "issue": "FTS_TABLES_FOUND",
    "tables": fts_tables,
    "severity": "INFO"
})

for fts in fts_tables:
    if fts.endswith("_content") or fts.endswith("_data") or fts.endswith("_idx") or fts.endswith("_docsize") or fts.endswith("_config"):
        continue
    cursor.execute(f"SELECT sql FROM sqlite_master WHERE name = '{fts}'")
    fts_sql = cursor.fetchone()
    if fts_sql and fts_sql[0]:
        results["fts_issues"].append({
            "issue": "FTS_CONFIG",
            "table": fts,
            "sql": fts_sql[0][:500],
            "severity": "INFO"
        })

# ============================================================
# 11. VIEWS CHECK
# ============================================================
print("[*] Checking views...")

cursor.execute("SELECT name, sql FROM sqlite_master WHERE type='view'")
views = cursor.fetchall()
for vname, vsql in views:
    try:
        cursor.execute(f"SELECT 1 FROM [{vname}] LIMIT 1")
        cursor.fetchone()
        status = "OK"
    except Exception as e:
        status = f"ERROR: {str(e)}"
        results["view_issues"].append({
            "issue": "VIEW_BROKEN",
            "view": vname,
            "error": str(e),
            "severity": "HIGH"
        })

results["views_found"] = [v[0] for v in views]

# ============================================================
# 12. ROWID vs INTEGER PRIMARY KEY
# ============================================================
print("[*] Checking ROWID vs explicit PK design...")

for table in core_tables:
    if table not in schema_info:
        continue
    pks = schema_info[table]["pks"]
    if not pks:
        results["schema_issues"].append({
            "issue": "NO_EXPLICIT_PRIMARY_KEY",
            "table": table,
            "severity": "HIGH"
        })

# ============================================================
# 13. COMPOSITE KEY TABLES WITHOUT ROWID
# ============================================================
print("[*] Checking composite key tables...")

for table, info in schema_info.items():
    if table.startswith("sqlite_") or "fts" in table:
        continue
    pks = info["pks"]
    if len(pks) > 1:
        results["schema_issues"].append({
            "issue": "COMPOSITE_PRIMARY_KEY",
            "table": table,
            "pk_columns": pks,
            "severity": "MEDIUM",
            "note": "SQLite does not support AUTOINCREMENT on composite keys"
        })

# ============================================================
# 14. ORPHAN RECORDS IN BRIDGE/JUNCTION TABLES
# ============================================================
print("[*] Checking bridge table integrity...")

bridge_checks = [
    ("protein_annotation_bridge", "protein_id", "viral_proteins", "protein_id"),
    ("protein_annotation_bridge", "isolate_id", "viral_isolates", "isolate_id"),
    ("kegg_protein_pathways", "protein_id", "viral_proteins", "protein_id"),
    ("isolate_reference_links", "isolate_id", "viral_isolates", "isolate_id"),
    ("isolate_reference_links", "reference_id", "ref_literatures", "reference_id"),
]

for bridge, col, parent, parent_col in bridge_checks:
    if bridge not in schema_info or parent not in schema_info:
        continue
    cursor.execute(f"""
        SELECT COUNT(*) FROM [{bridge}] b
        LEFT JOIN [{parent}] p ON b.{col} = p.{parent_col}
        WHERE b.{col} IS NOT NULL AND p.{parent_col} IS NULL
    """)
    count = cursor.fetchone()[0]
    if count > 0:
        results["cross_table_issues"].append({
            "issue": "BRIDGE_TABLE_ORPHAN",
            "bridge_table": bridge,
            "column": col,
            "referenced_table": parent,
            "count": count,
            "severity": "CRITICAL"
        })

# ============================================================
# 15. GC_CONTENT / NUMERIC RANGE CHECKS
# ============================================================
print("[*] Checking numeric ranges...")

numeric_checks = [
    ("viral_isolates", "gc_content", 0, 100),
    ("viral_isolates", "genome_length", 1, 10000000),
    ("sample_collections", "latitude", -90, 90),
    ("sample_collections", "longitude", -180, 180),
]

for table, col, minv, maxv in numeric_checks:
    if table not in schema_info:
        continue
    col_names = [c["name"] for c in schema_info[table]["columns"]]
    if col not in col_names:
        continue
    cursor.execute(f"""
        SELECT COUNT(*) FROM [{table}] 
        WHERE [{col}] IS NOT NULL AND (CAST([{col}] AS REAL) < {minv} OR CAST([{col}] AS REAL) > {maxv})
    """)
    count = cursor.fetchone()[0]
    if count > 0:
        results["cross_table_issues"].append({
            "issue": "NUMERIC_RANGE_VIOLATION",
            "table": table,
            "column": col,
            "expected_range": f"{minv}-{maxv}",
            "violation_count": count,
            "severity": "HIGH"
        })

# ============================================================
# 16. EMPTY STRING vs NULL INCONSISTENCY
# ============================================================
print("[*] Checking empty string vs NULL...")

for table in ["viral_isolates", "viral_proteins", "infection_records", "ref_literatures"]:
    if table not in schema_info:
        continue
    for col_info in schema_info[table]["columns"]:
        col = col_info["name"]
        if col_info["type"].upper() in ["TEXT", "VARCHAR"]:
            cursor.execute(f"SELECT COUNT(*) FROM [{table}] WHERE [{col}] = ''")
            empty_count = cursor.fetchone()[0]
            cursor.execute(f"SELECT COUNT(*) FROM [{table}] WHERE [{col}] IS NULL")
            null_count = cursor.fetchone()[0]
            if empty_count > 0 and null_count > 0:
                results["datatype_issues"].append({
                    "issue": "EMPTY_STRING_AND_NULL_MIXED",
                    "table": table,
                    "column": col,
                    "empty_count": empty_count,
                    "null_count": null_count,
                    "severity": "MEDIUM"
                })

# ============================================================
# 17. TRIGGERS CHECK
# ============================================================
print("[*] Checking triggers...")

cursor.execute("SELECT name, sql FROM sqlite_master WHERE type='trigger'")
triggers = cursor.fetchall()
results["triggers"] = [{"name": t[0], "sql": t[1][:200] if t[1] else None} for t in triggers]

# ============================================================
# 18. WAL AND JOURNAL CHECK
# ============================================================
print("[*] Checking WAL/journal files...")

db_dir = os.path.dirname(DB_PATH)
db_base = os.path.basename(DB_PATH)
wal_file = os.path.join(db_dir, db_base + "-wal")
shm_file = os.path.join(db_dir, db_base + "-shm")
journal_file = os.path.join(db_dir, db_base + "-journal")

results["file_checks"] = {
    "wal_exists": os.path.exists(wal_file),
    "shm_exists": os.path.exists(shm_file),
    "journal_exists": os.path.exists(journal_file),
    "wal_size": os.path.getsize(wal_file) if os.path.exists(wal_file) else 0,
    "db_size": os.path.getsize(DB_PATH)
}

# ============================================================
# 19. STAT4 / ANALYZE STATUS
# ============================================================
print("[*] Checking analyze status...")

cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='sqlite_stat1'")
has_stat1 = cursor.fetchone() is not None
cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='sqlite_stat4'")
has_stat4 = cursor.fetchone() is not None

results["analyze_status"] = {
    "has_stat1": has_stat1,
    "has_stat4": has_stat4,
    "stat1_row_count": 0
}

if has_stat1:
    cursor.execute("SELECT COUNT(*) FROM sqlite_stat1")
    results["analyze_status"]["stat1_row_count"] = cursor.fetchone()[0]

# ============================================================
# 20. STRICT TABLE CHECK
# ============================================================
print("[*] Checking STRICT table mode...")

for table in core_tables:
    if table not in schema_info:
        continue
    cursor.execute(f"SELECT sql FROM sqlite_master WHERE type='table' AND name='{table}'")
    sql = cursor.fetchone()
    if sql and sql[0]:
        is_strict = "STRICT" in sql[0].upper()
        if not is_strict:
            results["schema_issues"].append({
                "issue": "NOT_STRICT_TABLE",
                "table": table,
                "severity": "LOW"
            })

# ============================================================
# 21. ADDITIONAL CHECKS
# ============================================================
print("[*] Checking coordinate precision issues...")

if "sample_collections" in schema_info:
    cursor.execute("""
        SELECT COUNT(*) FROM sample_collections 
        WHERE latitude IS NOT NULL AND longitude IS NOT NULL 
        AND (latitude = 0 AND longitude = 0)
    """)
    zero_zero = cursor.fetchone()[0]
    if zero_zero > 0:
        results["cross_table_issues"].append({
            "issue": "COORDINATES_ZERO_ZERO",
            "count": zero_zero,
            "severity": "MEDIUM",
            "note": "0,0 is in the Atlantic Ocean; likely default/placeholder coordinates"
        })

# ============================================================
# 22. TABLES WITHOUT INDEXES
# ============================================================
print("[*] Checking tables without indexes...")

for table, info in schema_info.items():
    if table.startswith("sqlite_") or "fts" in table:
        continue
    user_indexes = [i for i in info["indexes"] if not i["name"].startswith("sqlite_autoindex")]
    if not user_indexes and info["row_count"] > 1000:
        results["index_issues"].append({
            "issue": "TABLE_WITHOUT_INDEX",
            "table": table,
            "row_count": info["row_count"],
            "severity": "MEDIUM"
        })

# ============================================================
# 23. CHECK FOR NULL FK REFERENCES
# ============================================================
print("[*] Checking NULL foreign key references in core tables...")

# Check how many infection_records have NULL host_id
if "infection_records" in schema_info:
    cursor.execute("SELECT COUNT(*) FROM infection_records WHERE host_id IS NULL")
    null_host = cursor.fetchone()[0]
    if null_host > 0:
        results["cross_table_issues"].append({
            "issue": "INFECTION_RECORDS_NULL_HOST_ID",
            "count": null_host,
            "severity": "HIGH",
            "note": "These are already flagged in publication_hardening_09 but severity warrants re-emphasis as schema-level issue"
        })

# Check how many viral_isolates have NULL master_id
if "viral_isolates" in schema_info:
    cursor.execute("SELECT COUNT(*) FROM viral_isolates WHERE master_id IS NULL")
    null_master = cursor.fetchone()[0]
    if null_master > 0:
        results["cross_table_issues"].append({
            "issue": "VIRAL_ISOLATES_NULL_MASTER_ID",
            "count": null_master,
            "severity": "HIGH",
            "note": "Isolate not linked to any virus_master entry"
        })

# ============================================================
# 24. CHECK nucleotide_records isolate_id consistency
# ============================================================
print("[*] Checking nucleotide records consistency...")

if "nucleotide_records" in schema_info and "viral_isolates" in schema_info:
    cursor.execute("""
        SELECT COUNT(*) FROM nucleotide_records nr
        WHERE nr.isolate_id IS NOT NULL 
        AND nr.isolate_id NOT IN (SELECT isolate_id FROM viral_isolates)
    """)
    orphan_nt = cursor.fetchone()[0]
    if orphan_nt > 0:
        results["cross_table_issues"].append({
            "issue": "NUCLEOTIDE_RECORDS_ORPHAN_ISOLATE_ID",
            "count": orphan_nt,
            "severity": "CRITICAL"
        })

# ============================================================
# SAVE RESULTS
# ============================================================
print("[*] Saving results...")

with open(os.path.join(OUTPUT_DIR, "audit_raw_results.json"), "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2, default=str)

print("[+] Audit complete. Results saved to audit_raw_results.json")
conn.close()
