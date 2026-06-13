#!/usr/bin/env python3
"""Import collected SRA metadata into sra_runs table."""
import json, sqlite3, datetime

conn = sqlite3.connect('F:/水生无脊椎动物数据库/crustacean_virus_core.db')

with open('F:/水生无脊椎动物数据库/sra_metadata_new.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

ts = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
existing = {r[0] for r in conn.execute("SELECT sra_accession FROM sra_runs").fetchall()}

def nid():
    return conn.execute("SELECT COALESCE(MAX(sra_id), 0) FROM sra_runs").fetchone()[0] + 1

imported = 0
for label, runs in data.items():
    for r in runs:
        acc = r['run']
        if acc in existing:
            continue
        sid = nid()
        try:
            conn.execute("""
            INSERT INTO sra_runs (sra_id, sra_accession, bioproject, biosample, title,
                library_strategy, library_source, library_layout, platform, total_bases, fetched_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (sid, acc, r['bp'], r['bs'], r['title'][:500] if r['title'] else '',
                  r['lib_strategy'], r['lib_source'], r['lib_layout'],
                  r['platform'], r['bases'], ts))
            imported += 1
            existing.add(acc)
        except Exception as e:
            pass

conn.commit()
total = conn.execute("SELECT COUNT(*) FROM sra_runs").fetchone()[0]
print(f"Imported: {imported} new SRA runs")
print(f"Total sra_runs: {total}")

# Summary by strategy
for r in conn.execute("""
    SELECT library_strategy, COUNT(*) FROM sra_runs
    GROUP BY library_strategy ORDER BY COUNT(*) DESC
""").fetchall():
    print(f"  Strategy: {r[0] or 'NULL':<30} {r[1]}")

conn.close()
