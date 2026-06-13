"""
数据库索引优化脚本
提升搜索、JOIN、统计查询的性能
"""

import sqlite3
import time

DB_PATH = r'F:\甲壳动物数据库\crustacean_virus_core.db'

INDEXES = [
    # 病毒表
    ("idx_vi_accession", "CREATE INDEX IF NOT EXISTS idx_vi_accession ON viral_isolates(accession)"),
    ("idx_vi_master_id", "CREATE INDEX IF NOT EXISTS idx_vi_master_id ON viral_isolates(master_id)"),
    ("idx_vi_completeness", "CREATE INDEX IF NOT EXISTS idx_vi_completeness ON viral_isolates(completeness)"),
    ("idx_vi_virus_name", "CREATE INDEX IF NOT EXISTS idx_vi_virus_name ON viral_isolates(virus_name)"),
    ("idx_vi_reference_id", "CREATE INDEX IF NOT EXISTS idx_vi_reference_id ON viral_isolates(reference_id)"),
    
    # 感染记录桥表
    ("idx_ir_isolate_id", "CREATE INDEX IF NOT EXISTS idx_ir_isolate_id ON infection_records(isolate_id)"),
    ("idx_ir_host_id", "CREATE INDEX IF NOT EXISTS idx_ir_host_id ON infection_records(host_id)"),
    ("idx_ir_collection_id", "CREATE INDEX IF NOT EXISTS idx_ir_collection_id ON infection_records(collection_id)"),
    
    # 宿主表
    ("idx_ch_scientific_name", "CREATE INDEX IF NOT EXISTS idx_ch_scientific_name ON crustacean_hosts(scientific_name)"),
    
    # 采样表
    ("idx_sc_country", "CREATE INDEX IF NOT EXISTS idx_sc_country ON sample_collections(country)"),
    ("idx_sc_province", "CREATE INDEX IF NOT EXISTS idx_sc_province ON sample_collections(province)"),
    ("idx_sc_year", "CREATE INDEX IF NOT EXISTS idx_sc_year ON sample_collections(collection_year)"),
    
    # 文献表
    ("idx_rl_pmid", "CREATE INDEX IF NOT EXISTS idx_rl_pmid ON ref_literatures(pmid)"),
    
    # 标准名称表
    ("idx_vm_canonical", "CREATE INDEX IF NOT EXISTS idx_vm_canonical ON virus_master(canonical_name)"),
]


def create_indexes():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    print("Creating indexes...")
    created = 0
    for name, sql in INDEXES:
        try:
            start = time.time()
            c.execute(sql)
            elapsed = (time.time() - start) * 1000
            print(f"  [OK] {name:30s} ({elapsed:6.1f}ms)")
            created += 1
        except sqlite3.OperationalError as e:
            print(f"  [SKIP] {name}: {e}")
    
    conn.commit()
    conn.close()
    
    print(f"\nTotal indexes created: {created}/{len(INDEXES)}")
    
    # Verify
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_%'")
    existing = [r[0] for r in c.fetchall()]
    conn.close()
    
    print(f"\nExisting custom indexes: {len(existing)}")
    for idx in existing:
        print(f"  - {idx}")


def benchmark_search():
    """Benchmark search performance before/after indexing"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    queries = [
        ("Full-text search (WSSV)", """
            SELECT v.accession FROM viral_isolates v
            LEFT JOIN virus_master vm ON v.master_id = vm.master_id
            WHERE v.virus_name LIKE '%white%' OR vm.canonical_name LIKE '%white%'
            LIMIT 20
        """),
        ("Join infection records", """
            SELECT v.accession, h.scientific_name 
            FROM viral_isolates v
            JOIN infection_records ir ON v.isolate_id = ir.isolate_id
            JOIN crustacean_hosts h ON ir.host_id = h.host_id
            WHERE v.completeness = 'complete_genome'
            LIMIT 20
        """),
        ("Country filter", """
            SELECT v.accession, s.country 
            FROM viral_isolates v
            JOIN infection_records ir ON v.isolate_id = ir.isolate_id
            JOIN sample_collections s ON ir.collection_id = s.collection_id
            WHERE s.country = 'China'
            LIMIT 20
        """),
    ]
    
    print("\nBenchmark results:")
    for name, sql in queries:
        start = time.time()
        c.execute(sql)
        c.fetchall()
        elapsed = (time.time() - start) * 1000
        print(f"  {name:30s}: {elapsed:6.2f}ms")
    
    conn.close()


if __name__ == '__main__':
    create_indexes()
    benchmark_search()
