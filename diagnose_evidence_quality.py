#!/usr/bin/env python3
"""Diagnose evidence quality bottlenecks across multiple dimensions."""
import sqlite3

conn = sqlite3.connect('F:/水生无脊椎动物数据库/crustacean_virus_core.db')
conn.row_factory = sqlite3.Row
total = 348027.0

print('=== 1. 质量×实验信号 ===')
exp_kws = ['PCR', 'qPCR', 'ELISA', 'western blot', 'challenge', 'histopath',
           'TEM', 'cell culture', 'virus isolat', 'LD50', 'sequencing']
for kw in exp_kws:
    n = conn.execute(
        "SELECT COUNT(*) FROM evidence_records WHERE evidence_strength='medium' AND claim LIKE ?",
        (f'%{kw}%',)).fetchone()[0]
    if n > 100:
        print(f'  medium claims with "{kw}": {n:,}')

print()
print('=== 2. 质量×定量数值 ===')
for row in conn.execute('''
    SELECT evidence_strength,
           CASE WHEN value_numeric_min IS NOT NULL OR value_numeric_max IS NOT NULL
                THEN 'quantitative' ELSE 'qualitative' END as qtype,
           COUNT(*) as n FROM evidence_records
    GROUP BY 1, 2 ORDER BY 1, n DESC
'''):
    print(f'  [{row[0]:6s}] {row[1]:15s}: {row[2]:>8,}')

print()
print('=== 3. 质量×DOI ===')
for row in conn.execute('''
    SELECT e.evidence_strength,
           CASE WHEN r.doi IS NOT NULL AND r.doi != "" THEN "DOI" ELSE "no_DOI" END,
           COUNT(*) as n
    FROM evidence_records e LEFT JOIN ref_literatures r ON e.reference_id = r.reference_id
    GROUP BY 1, 2 ORDER BY 1, n DESC
'''):
    print(f'  [{row[0]:6s}] {row[1]:10s}: {row[2]:>8,}')

print()
print('=== 4. 质量×出版年 ===')
for row in conn.execute('''
    SELECT e.evidence_strength,
           CASE WHEN CAST(r.year AS INTEGER) >= 2020 THEN "2020+"
                WHEN CAST(r.year AS INTEGER) >= 2010 THEN "2010-2019"
                WHEN r.year IS NOT NULL AND r.year != "" THEN "<2010"
                ELSE "unknown" END,
           COUNT(*) as n
    FROM evidence_records e LEFT JOIN ref_literatures r ON e.reference_id = r.reference_id
    GROUP BY 1, 2 ORDER BY 1, n DESC
'''):
    print(f'  [{row[0]:6s}] {row[1]:10s}: {row[2]:>8,}')

print()
print('=== 5. 质量×分离株关联 ===')
for row in conn.execute('''
    SELECT evidence_strength,
           CASE WHEN isolate_id IS NOT NULL THEN "linked" ELSE "orphan" END,
           COUNT(*) as n FROM evidence_records
    GROUP BY 1, 2 ORDER BY 1, n DESC
'''):
    print(f'  [{row[0]:6s}] {row[1]:10s}: {row[2]:>8,}')

print()
print('=== 6. 质量×是否有序列 ===')
for row in conn.execute('''
    SELECT e.evidence_strength,
           CASE WHEN vi.genome_accession IS NOT NULL THEN "has_sequence" ELSE "no_sequence" END,
           COUNT(DISTINCT e.evidence_id) as n
    FROM evidence_records e
    LEFT JOIN viral_isolates vi ON e.isolate_id = vi.isolate_id
    GROUP BY 1, 2 ORDER BY 1, n DESC
'''):
    print(f'  [{row[0]:6s}] {row[1]:15s}: {row[2]:>8,}')

print()
print('=== 7. 同一claim被多证据支持的情况 ===')
for row in conn.execute('''
    SELECT evidence_strength,
           CASE WHEN claim_count BETWEEN 2 AND 5 THEN "2-5 sources"
                WHEN claim_count > 5 THEN ">5 sources"
                ELSE "single source" END,
           COUNT(*) as n
    FROM (
        SELECT evidence_strength,
               COUNT(*) OVER (PARTITION BY substr(claim, 1, 200)) as claim_count
        FROM evidence_records WHERE claim IS NOT NULL
    )
    GROUP BY 1, 2 ORDER BY 1, n DESC
'''):
    print(f'  [{row[0]:6s}] {row[1]:15s}: {row[2]:>8,}')

print()
print('=== 8. medium中潜在可升级为high的条件组合 ===')
# Multi-condition upgrade potential
n1 = conn.execute("""
    SELECT COUNT(*) FROM evidence_records e
    JOIN ref_literatures r ON e.reference_id = r.reference_id
    WHERE e.evidence_strength = 'medium'
      AND e.isolate_id IS NOT NULL
      AND r.doi IS NOT NULL AND r.doi != ''
      AND (e.claim LIKE '%PCR%' OR e.claim LIKE '%qPCR%' OR e.claim LIKE '%challenge%'
           OR e.claim LIKE '%histopath%' OR e.claim LIKE '%TEM%'
           OR e.claim LIKE '%virus isolat%' OR e.claim LIKE '%ELISA%')
""").fetchone()[0]
print(f'  Medium + isolate_linked + DOI + experimental = {n1:,}')

n2 = conn.execute("""
    SELECT COUNT(*) FROM evidence_records e
    JOIN ref_literatures r ON e.reference_id = r.reference_id
    JOIN literature_fulltext_sources lfs ON e.reference_id = lfs.reference_id
    WHERE e.evidence_strength = 'medium'
      AND (e.claim LIKE '%PCR%' OR e.claim LIKE '%qPCR%' OR e.claim LIKE '%challenge%'
           OR e.claim LIKE '%histopath%' OR e.claim LIKE '%mortality%')
""").fetchone()[0]
print(f'  Medium + fulltext + experimental = {n2:,}')

n3 = conn.execute("""
    SELECT COUNT(*) FROM evidence_records e
    WHERE e.evidence_strength = 'medium'
      AND e.curation_status = 'manual_checked'
""").fetchone()[0]
print(f'  Medium + manual_checked = {n3:,}')

# Count how many medium evidence are "fulltext_deep_extraction" — these are the most reliable medium
n4 = conn.execute("""
    SELECT COUNT(*) FROM evidence_records
    WHERE evidence_strength = 'medium'
      AND extraction_method = 'fulltext_deep_extraction'
""").fetchone()[0]
print(f'  Medium + fulltext_deep_extraction = {n4:,}')

print()
print('=== 9. LOW quality bottleneck ===')
for row in conn.execute('''
    SELECT extraction_method, observation_type, COUNT(*) as n
    FROM evidence_records WHERE evidence_strength = 'low'
    GROUP BY 1, 2 ORDER BY n DESC LIMIT 10
'''):
    print(f'  {row[0]:40s} | {str(row[1]):15s}: {row[2]:>5,}')

print()
print('=== 10. 有全文但claim为空的low证据 ===')
n = conn.execute("""
    SELECT COUNT(*) FROM evidence_records e
    JOIN literature_fulltext_sources lfs ON e.reference_id = lfs.reference_id
    WHERE e.evidence_strength = 'low' AND (e.claim IS NULL OR e.claim = '')
""").fetchone()[0]
print(f'  Low + fulltext + empty_claim: {n}')

conn.close()
