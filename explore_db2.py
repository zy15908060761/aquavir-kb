#!/usr/bin/env python3
"""Explore database structure - find isolates table and related tables."""
import sqlite3

DB = "F:/水生无脊椎动物数据库/crustacean_virus_core.db"

def query(sql, params=None):
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    if params:
        cur.execute(sql, params)
    else:
        cur.execute(sql)
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows

# List all tables
print("ALL TABLES:")
rows = query("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
for r in rows:
    print(f"  {r['name']}")

# Find tables that might hold isolate data
print("\n\nTables with 'isolate' or 'virus' in name:")
for r in rows:
    name = r['name'].lower()
    if 'isolate' in name or 'virus' in name or 'genome' in name or 'seq' in name:
        print(f"\n  == {r['name']} ==")
        cols = query(f"PRAGMA table_info({r['name']})")
        for c in cols:
            print(f"    {c['name']:30s} {c['type']:10s}")
        cnt = query(f"SELECT COUNT(*) as c FROM [{r['name']}]")[0]['c']
        print(f"    ---> {cnt} rows")
