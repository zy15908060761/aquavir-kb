import json
with open(r'F:\甲壳动物数据库\reports\comprehensive_audit_20260509\audit_raw_results.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

print('=== PRAGMA CHECKS ===')
for k, v in data['pragma_checks'].items():
    print(f'{k}: {v}')

print('\n=== CONSTRAINT ISSUES ===')
for item in data['constraint_issues']:
    print(item)

print('\n=== CROSS TABLE ISSUES ===')
for item in data['cross_table_issues']:
    print(item)

print('\n=== INDEX ISSUES (first 30) ===')
for item in data['index_issues'][:30]:
    print(item)

print('\n=== SCHEMA ISSUES ===')
for item in data['schema_issues']:
    print(item)

print('\n=== DATATYPE ISSUES ===')
for item in data['datatype_issues']:
    print(item)

print('\n=== VIEW ISSUES ===')
for item in data['view_issues']:
    print(item)

print('\n=== FTS ISSUES ===')
for item in data['fts_issues']:
    print(item)

print('\n=== TRIGGERS ===')
print(f'Triggers count: {len(data.get("triggers", []))}')
for t in data.get('triggers', [])[:10]:
    print(t)

print('\n=== FILE CHECKS ===')
print(data['file_checks'])

print('\n=== ANALYZE STATUS ===')
print(data['analyze_status'])

print('\n=== FOREIGN KEYS ===')
print(f'Total FKs: {len(data["foreign_keys"])}')

print('\n=== FK WITHOUT INDEX ===')
for item in data['index_issues']:
    if item['issue'] == 'FK_WITHOUT_INDEX':
        print(item)
