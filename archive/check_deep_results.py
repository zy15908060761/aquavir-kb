import json
with open(r'F:\甲壳动物数据库\reports\comprehensive_audit_20260509\deep_check_results.json', 'r', encoding='utf-8') as f:
    d = json.load(f)

for k, v in d.items():
    print(f"=== {k} ===")
    if isinstance(v, list):
        print(f"Count: {len(v)}")
        for item in v[:10]:
            print(f"  {item}")
    else:
        print(v)
    print()
