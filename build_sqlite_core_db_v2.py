"""
基于现有 Excel 数据构建 SQLite 核心数据库 v2
修复: 病毒名提取、nan过滤、宿主去重

NOTE: The Excel→5-tables flow below is the ORIGINAL seed builder (legacy).
The current database has 120+ tables, 27 views, and many enrichment layers.
For reproducibility, use:
    python build_sqlite_core_db_v2.py --dump-schema   # Export full DDL
    python build_sqlite_core_db_v2.py --rebuild-from-schema schema.sql  # Rebuild
"""
import re
from pathlib import Path

import pandas as pd

from db_utils import get_db, DB_PATH

META_EXCEL = Path("F:/甲壳动物数据库/ncbi_metadata/crustacean_virus_metadata.xlsx")
LIT_EXCEL = Path("F:/甲壳动物数据库/ncbi_metadata/pubmed_supplements.xlsx")


def extract_virus_name(definition):
    """从 definition 提取病毒名"""
    text = str(definition) if pd.notna(definition) else ""
    # 匹配: 大写开头 + 最多4个单词 + virus
    m = re.search(r"([A-Z][a-z]*(?:\s+[a-z]+){0,4}\s+virus)", text)
    if m:
        return m.group(1).strip()
    # 备选: 尝试匹配 "virus" 前尽可能多的词
    m = re.search(r"([A-Za-z][A-Za-z\s]*virus)", text)
    if m:
        return m.group(1).strip()
    return text[:80].strip()


def parse_taxonomy(taxonomy_str):
    if pd.isna(taxonomy_str) or not taxonomy_str:
        return "", "", ""
    parts = [p.strip() for p in str(taxonomy_str).split(";")]
    family = ""
    genus = ""
    species = ""
    for p in parts:
        if p.endswith("viridae"):
            family = p
        elif p.endswith("virus") and " " not in p:
            genus = p
        elif "virus" in p.lower():
            species = p
    return family, genus, species


def normalize_pmid(val):
    if pd.isna(val):
        return ""
    s = str(val).strip()
    if s.endswith(".0"):
        s = s[:-2]
    return s


def init_database(conn):
    cursor = conn.cursor()
    cursor.executescript("""
    DROP TABLE IF EXISTS infection_records;
    DROP TABLE IF EXISTS sample_collections;
    DROP TABLE IF EXISTS crustacean_hosts;
    DROP TABLE IF EXISTS viral_isolates;
    DROP TABLE IF EXISTS ref_literatures;

    CREATE TABLE ref_literatures (
        reference_id INTEGER PRIMARY KEY AUTOINCREMENT,
        pmid VARCHAR(20) UNIQUE,
        title TEXT,
        authors TEXT,
        journal TEXT,
        year VARCHAR(10),
        doi VARCHAR(100),
        abstract TEXT,
        keywords TEXT
    );

    CREATE TABLE viral_isolates (
        isolate_id INTEGER PRIMARY KEY AUTOINCREMENT,
        accession VARCHAR(50) UNIQUE NOT NULL,
        virus_name VARCHAR(200),
        taxon_family VARCHAR(100),
        taxon_genus VARCHAR(100),
        taxon_species VARCHAR(100),
        genome_accession VARCHAR(50),
        genome_length INTEGER,
        gc_content REAL,
        genome_type VARCHAR(50),
        keywords TEXT,
        reference_id INTEGER,
        FOREIGN KEY (reference_id) REFERENCES ref_literatures(reference_id)
    );

    CREATE TABLE crustacean_hosts (
        host_id INTEGER PRIMARY KEY AUTOINCREMENT,
        scientific_name VARCHAR(100) NOT NULL UNIQUE,
        common_name_cn VARCHAR(100),
        taxon_order VARCHAR(100),
        taxon_family VARCHAR(100),
        host_group VARCHAR(50),
        habitat VARCHAR(100),
        aquaculture_status VARCHAR(50),
        iucn_status VARCHAR(50)
    );

    CREATE TABLE sample_collections (
        collection_id INTEGER PRIMARY KEY AUTOINCREMENT,
        country VARCHAR(100),
        province VARCHAR(100),
        city VARCHAR(100),
        site_name VARCHAR(200),
        latitude REAL,
        longitude REAL,
        collection_year VARCHAR(10),
        collection_date VARCHAR(20),
        source_type VARCHAR(50),
        note TEXT
    );

    CREATE TABLE infection_records (
        record_id INTEGER PRIMARY KEY AUTOINCREMENT,
        isolate_id INTEGER NOT NULL,
        host_id INTEGER,
        collection_id INTEGER,
        detection_method VARCHAR(100),
        disease_symptom TEXT,
        mortality_rate VARCHAR(50),
        isolation_source VARCHAR(100),
        reference_id INTEGER,
        FOREIGN KEY (isolate_id) REFERENCES viral_isolates(isolate_id),
        FOREIGN KEY (host_id) REFERENCES crustacean_hosts(host_id),
        FOREIGN KEY (collection_id) REFERENCES sample_collections(collection_id),
        FOREIGN KEY (reference_id) REFERENCES ref_literatures(reference_id)
    );
    """)
    conn.commit()
    print("[DB] 核心表结构创建完成")


def populate_references(conn):
    df = pd.read_excel(LIT_EXCEL, sheet_name="literatures")
    records = []
    for _, row in df.iterrows():
        records.append((
            str(row.get("pmid", "")).strip(),
            str(row.get("title", "")).strip(),
            str(row.get("authors", "")).strip(),
            str(row.get("journal", "")).strip(),
            str(row.get("year", "")).strip(),
            str(row.get("doi", "")).strip(),
            str(row.get("abstract", "")).strip(),
            str(row.get("keywords", "")).strip(),
        ))
    cursor = conn.cursor()
    cursor.executemany("""
        INSERT INTO ref_literatures (pmid, title, authors, journal, year, doi, abstract, keywords)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, records)
    conn.commit()
    print(f"[DB] 插入 {len(records)} 条文献记录")


def populate_viral_isolates(conn, meta_df):
    cursor = conn.cursor()
    cursor.execute("SELECT reference_id, pmid FROM ref_literatures")
    pmid_map = {str(pmid): ref_id for ref_id, pmid in cursor.fetchall()}

    records = []
    for _, row in meta_df.iterrows():
        accession = str(row.get("accession", "")).strip()
        if not accession:
            continue
        virus_name = extract_virus_name(row.get("definition"))
        family, genus, species = parse_taxonomy(row.get("taxonomy"))
        length = row.get("length")
        try:
            length = int(length) if pd.notna(length) else None
        except:
            length = None
        pmid = normalize_pmid(row.get("pubmed_id"))
        ref_id = pmid_map.get(pmid)
        records.append((
            accession, virus_name, family, genus, species,
            accession, length, None, None,
            str(row.get("keywords", "")).strip() if pd.notna(row.get("keywords")) else None,
            ref_id,
        ))

    cursor.executemany("""
        INSERT INTO viral_isolates
        (accession, virus_name, taxon_family, taxon_genus, taxon_species,
         genome_accession, genome_length, gc_content, genome_type, keywords, reference_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, records)
    conn.commit()
    print(f"[DB] 插入 {len(records)} 条病毒分离株记录")


def populate_crustacean_hosts(conn, meta_df):
    hosts = meta_df["host"].dropna().astype(str).str.strip()
    hosts = hosts[hosts != ""].unique()

    host_map = {
        "Penaeus vannamei": "Litopenaeus vannamei",
        "shrimp": "Penaeus spp.",
        "shrimps": "Penaeus spp.",
        "penaeid shrimp": "Penaeus spp.",
        "crustacean": "Crustacea",
        "crustaceans": "Crustacea",
        "crayfish": "Astacidea",
        "crab": "Brachyura",
    }
    cn_map = {
        "Litopenaeus vannamei": "南美白对虾",
        "Penaeus monodon": "斑节对虾",
        "Penaeus spp.": "对虾属",
        "Artemia sp.": "卤虫",
        "Artemia salina": "丰年虫",
        "Macrobrachium rosenbergii": "罗氏沼虾",
        "Macrobrachium nipponense": "日本沼虾",
        "Crustacea": "甲壳动物",
        "Astacidea": "螯虾类",
        "Brachyura": "短尾类(蟹)",
        "Penaeus stylirostris": "西方白对虾",
        "Penaeus japonicus": "日本对虾",
        "Fenneropenaeus chinensis": "中国对虾",
        "Marsupenaeus japonicus": "日本囊对虾",
        "Carcinus maenas": "普通滨蟹",
        "Callinectes sapidus": "蓝蟹",
        "Scylla serrata": "锯缘青蟹",
        "Eriocheir sinensis": "中华绒螯蟹",
        "Homarus americanus": "美洲螯龙虾",
        "Procambarus clarkii": "克氏原螯虾",
    }

    # 去重并标准化
    seen = set()
    records = []
    for h in hosts:
        sci_name = host_map.get(h, h)
        if sci_name in seen:
            continue
        seen.add(sci_name)
        common_name = cn_map.get(sci_name, "")
        records.append((sci_name, common_name, None, None, None, None, None, None))

    cursor = conn.cursor()
    cursor.executemany("""
        INSERT OR IGNORE INTO crustacean_hosts
        (scientific_name, common_name_cn, taxon_order, taxon_family, host_group, habitat, aquaculture_status, iucn_status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, records)
    conn.commit()
    print(f"[DB] 插入 {len(records)} 条唯一宿主记录")


def populate_sample_collections(conn, meta_df):
    records = []
    seen = set()
    for _, row in meta_df.iterrows():
        country = str(row.get("country", "")).strip()
        if country.lower() in ("nan", "none", "null", ""):
            country = ""
        date_raw = str(row.get("collection_date", "")).strip()
        lat_lon = str(row.get("lat_lon", "")).strip()
        isolation_source = str(row.get("isolation_source", "")).strip()
        if isolation_source.lower() in ("nan", "none", "null"):
            isolation_source = ""

        year = ""
        if date_raw and date_raw.lower() not in ("nan", "none", "null"):
            m = re.search(r"(\d{4})", date_raw)
            if m:
                year = m.group(1)

        lat, lon = None, None
        if lat_lon and lat_lon.lower() not in ("nan", "none", "null"):
            parts = lat_lon.replace(",", " ").split()
            if len(parts) >= 2:
                try:
                    lat = float(parts[0])
                    lon = float(parts[1])
                except:
                    pass

        key = (country, year, lat, lon)
        if key in seen:
            continue
        seen.add(key)

        records.append((country, None, None, None, lat, lon, year, date_raw, None, isolation_source))

    cursor = conn.cursor()
    cursor.executemany("""
        INSERT INTO sample_collections
        (country, province, city, site_name, latitude, longitude, collection_year, collection_date, source_type, note)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, records)
    conn.commit()
    print(f"[DB] 插入 {len(records)} 条采样记录")


def populate_infection_records(conn, meta_df):
    cursor = conn.cursor()

    cursor.execute("SELECT isolate_id, accession FROM viral_isolates")
    acc_map = {acc: iid for iid, acc in cursor.fetchall()}

    cursor.execute("SELECT host_id, scientific_name FROM crustacean_hosts")
    host_map = {name: hid for hid, name in cursor.fetchall()}

    cursor.execute("SELECT collection_id, country, collection_year, latitude, longitude FROM sample_collections")
    col_map = {}
    for cid, country, year, lat, lon in cursor.fetchall():
        col_map[(country if country else "", year if year else "", lat, lon)] = cid

    cursor.execute("SELECT reference_id, pmid FROM ref_literatures")
    pmid_map = {str(pmid): ref_id for ref_id, pmid in cursor.fetchall()}

    records = []
    for _, row in meta_df.iterrows():
        accession = str(row.get("accession", "")).strip()
        if accession not in acc_map:
            continue
        isolate_id = acc_map[accession]

        host_raw = str(row.get("host", "")).strip()
        # 标准化映射必须与 populate_crustacean_hosts 一致
        host_map_std = {
            "Penaeus vannamei": "Litopenaeus vannamei",
            "shrimp": "Penaeus spp.",
            "shrimps": "Penaeus spp.",
            "penaeid shrimp": "Penaeus spp.",
            "crustacean": "Crustacea",
            "crustaceans": "Crustacea",
            "crayfish": "Astacidea",
            "crab": "Brachyura",
        }
        host_std = host_map_std.get(host_raw, host_raw)
        host_id = host_map.get(host_std) if host_std else None

        country = str(row.get("country", "")).strip()
        if country.lower() in ("nan", "none", "null", ""):
            country = ""
        date_raw = str(row.get("collection_date", "")).strip()
        year = ""
        if date_raw and date_raw.lower() not in ("nan", "none", "null"):
            m = re.search(r"(\d{4})", date_raw)
            if m:
                year = m.group(1)
        lat_lon = str(row.get("lat_lon", "")).strip()
        lat, lon = None, None
        if lat_lon and lat_lon.lower() not in ("nan", "none", "null"):
            parts = lat_lon.replace(",", " ").split()
            if len(parts) >= 2:
                try:
                    lat = float(parts[0])
                    lon = float(parts[1])
                except:
                    pass
        col_id = col_map.get((country, year, lat, lon))

        pmid = normalize_pmid(row.get("pubmed_id"))
        ref_id = pmid_map.get(pmid)

        isolation_source = str(row.get("isolation_source", "")).strip()
        if isolation_source.lower() in ("nan", "none", "null", ""):
            isolation_source = None

        records.append((isolate_id, host_id, col_id, None, None, None, isolation_source, ref_id))

    cursor.executemany("""
        INSERT INTO infection_records
        (isolate_id, host_id, collection_id, detection_method, disease_symptom, mortality_rate, isolation_source, reference_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, records)
    conn.commit()
    print(f"[DB] 插入 {len(records)} 条感染事件记录")


def build_db():
    print("=" * 60)
    print("构建 SQLite 核心数据库 v2")
    print("=" * 60)

    print("[Load] 读取病毒元数据...")
    meta_df = pd.read_excel(META_EXCEL)
    print(f"  共 {len(meta_df)} 条记录")

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = get_db()

    init_database(conn)
    populate_references(conn)
    populate_viral_isolates(conn, meta_df)
    populate_crustacean_hosts(conn, meta_df)
    populate_sample_collections(conn, meta_df)
    populate_infection_records(conn, meta_df)

    cursor = conn.cursor()
    print("\n[Verify] 数据库统计:")
    for table in ["ref_literatures", "viral_isolates", "crustacean_hosts", "sample_collections", "infection_records"]:
        cursor.execute(f"SELECT COUNT(*) FROM {table}")
        count = cursor.fetchone()[0]
        print(f"  {table:25s}: {count:5d} 条")

    conn.close()
    print(f"\n[Done] 数据库已保存到: {DB_PATH}")
    print("=" * 60)


def dump_schema(output_path: str | Path = None) -> Path:
    """Export the full DDL (all tables, views, indexes, triggers) from the
    live database to a SQL file that can be used for reproducibility.

    Parameters
    ----------
    output_path : str or Path, optional
        Where to write the schema SQL file. Defaults to ``schema_dump.sql``
        alongside the database.

    Returns
    -------
    Path
        Path to the written SQL file.
    """
    import sqlite3
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT type, name, sql
            FROM sqlite_master
            WHERE sql IS NOT NULL
              AND name NOT LIKE 'sqlite_%'
            ORDER BY
                CASE type
                    WHEN 'table' THEN 0
                    WHEN 'index' THEN 1
                    WHEN 'view' THEN 2
                    WHEN 'trigger' THEN 3
                    ELSE 4
                END,
                name
            """
        ).fetchall()

        out = Path(output_path) if output_path else DB_PATH.parent / "schema_dump.sql"
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with out.open("w", encoding="utf-8") as f:
            f.write(f"-- Full schema dump from {DB_PATH.name}\n")
            f.write(f"-- Exported: {stamp}\n")
            f.write(f"-- Tables: {sum(1 for r in rows if r['type'] == 'table')}\n")
            f.write(f"-- Views:  {sum(1 for r in rows if r['type'] == 'view')}\n")
            f.write(f"-- Indexes: {sum(1 for r in rows if r['type'] == 'index')}\n")
            f.write(f"-- Triggers: {sum(1 for r in rows if r['type'] == 'trigger')}\n")
            f.write("\nBEGIN TRANSACTION;\n\n")

            for row in rows:
                f.write(f"-- {row['type']}: {row['name']}\n")
                f.write(row["sql"].rstrip() + ";\n\n")

            f.write("COMMIT;\n")

        print(f"Schema dumped to: {out}")
        print(f"  {sum(1 for r in rows if r['type'] == 'table')} tables, "
              f"{sum(1 for r in rows if r['type'] == 'view')} views, "
              f"{sum(1 for r in rows if r['type'] == 'index')} indexes, "
              f"{sum(1 for r in rows if r['type'] == 'trigger')} triggers")
        return out
    finally:
        conn.close()


def rebuild_from_schema(schema_path: str | Path, output_db: str | Path = None) -> Path:
    """Rebuild an empty database from a schema dump file.

    Parameters
    ----------
    schema_path : str or Path
        Path to the schema SQL file (produced by --dump-schema).
    output_db : str or Path, optional
        Where to write the new database file. Defaults to
        ``crustacean_virus_core_rebuilt.db`` alongside the schema.

    Returns
    -------
    Path
        Path to the created database file.
    """
    import sqlite3
    schema = Path(schema_path)
    if not schema.exists():
        raise FileNotFoundError(f"Schema file not found: {schema}")

    out = Path(output_db) if output_db else schema.parent / "crustacean_virus_core_rebuilt.db"
    if out.exists():
        out.unlink()

    conn = sqlite3.connect(str(out))
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute("PRAGMA journal_mode = WAL")
    try:
        sql = schema.read_text(encoding="utf-8")
        # Remove the BEGIN/COMMIT wrapper since we're executing line by line
        conn.executescript(sql)
        conn.commit()
    except sqlite3.Error:
        conn.rollback()
        raise
    finally:
        conn.close()

    # Verify
    conn2 = sqlite3.connect(str(out))
    try:
        tables = conn2.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table'"
        ).fetchone()[0]
        views = conn2.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='view'"
        ).fetchone()[0]
        print(f"Database rebuilt at: {out}")
        print(f"  {tables} tables, {views} views")
        return out
    finally:
        conn2.close()


if __name__ == "__main__":
    import argparse
    from datetime import datetime

    p = argparse.ArgumentParser(
        description="Crustacean Virus Database — schema build / dump / rebuild"
    )
    p.add_argument(
        "--dump-schema", action="store_true",
        help="Export full DDL from the live database to a SQL file."
    )
    p.add_argument(
        "--rebuild-from-schema", type=str, metavar="SCHEMA.sql",
        help="Rebuild an empty database from a schema dump file."
    )
    p.add_argument(
        "--output", type=str,
        help="Output path for --dump-schema or --rebuild-from-schema."
    )
    p.add_argument(
        "--build-from-excel", action="store_true",
        help="Run the LEGACY Excel→5-tables builder (historical; not for reproduction)."
    )
    args = p.parse_args()

    if args.dump_schema:
        dump_schema(args.output)
    elif args.rebuild_from_schema:
        rebuild_from_schema(args.rebuild_from_schema, args.output)
    elif args.build_from_excel:
        build_db()
    else:
        p.print_help()
        print("\nExamples:")
        print("  python build_sqlite_core_db_v2.py --dump-schema")
        print("  python build_sqlite_core_db_v2.py --rebuild-from-schema schema_dump.sql")
        print("  python build_sqlite_core_db_v2.py --build-from-excel  # LEGACY")
