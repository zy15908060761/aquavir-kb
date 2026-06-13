#!/usr/bin/env python3
"""
CNKI (中国知网) & 万方文献检索辅助脚本

CNKI没有开放的API，但可以通过以下方式批量检索：
  1. 生成检索URL列表，在浏览器中打开
  2. 使用CNKI的跨库检索接口导出题录
  3. 手动下载摘要后用本脚本提取数据

本脚本生成：
  - CNKI检索URL列表（按病毒名+关键词）
  - 万方检索URL列表
  - 从导出的CNKI文本文件中提取温度/毒力数据
"""

from pathlib import Path
import csv
import re
from collections import defaultdict

OUT_DIR = Path(r"F:\甲壳动物数据库\external_data\multi_source_mining\cnki")
OUT_DIR.mkdir(parents=True, exist_ok=True)

# ── 检索目标病毒（中英文名） ──
TARGET_VIRUSES = [
    ("White spot syndrome virus", "白斑综合征病毒", "WSSV"),
    ("Yellow head virus", "黄头病毒", "YHV"),
    ("Taura syndrome virus", "桃拉综合征病毒", "TSV"),
    ("Infectious hypodermal and hematopoietic necrosis virus", "传染性皮下及造血组织坏死病毒", "IHHNV"),
    ("Infectious myonecrosis virus", "传染性肌坏死病毒", "IMNV"),
    ("Macrobrachium rosenbergii nodavirus", "罗氏沼虾野田村病毒", "MrNV"),
    ("Decapod iridescent virus", "十足目虹彩病毒", "DIV1"),
    ("Covert mortality nodavirus", "偷死野田村病毒", "CMNV"),
    ("Hepatopancreatic parvovirus", "肝胰腺细小病毒", "HPV"),
    ("Chinese mitten crab virus", "中华绒螯蟹病毒", "EsRNV"),
    ("Mud crab virus", "青蟹病毒", ""),
    ("Wenzhou shrimp virus", "温州虾病毒", "WzSV"),
    ("Penaeus vannamei nodavirus", "凡纳滨对虾野田村病毒", "PvNV"),
    ("Shrimp hemocyte iridescent virus", "虾血细胞虹彩病毒", "SHIV"),
    ("Callinectes sapidus reovirus", "蓝蟹呼肠孤病毒", "CsRV"),
    ("Eriocheir sinensis reovirus", "中华绒螯蟹呼肠孤病毒", "EsRV"),
    ("Macrobrachium rosenbergii Golda virus", "罗氏沼虾Golda病毒", ""),
]

# ── 检索关键词（中文） ──
CN_TEMP_KEYWORDS = ["温度", "热灭活", "最适温度", "耐热", "低温", "冷链", "水温"]
CN_VIR_KEYWORDS = ["毒力", "致病性", "死亡率", "半数致死", "LD50", "累计死亡率", "攻毒"]

# ── 生成 CNKI 检索URL ──
def generate_cnki_urls():
    """生成CNKI专业检索URL"""
    base = "https://kns.cnki.net/kns8s/defaultresult/index"

    urls = []
    for en_name, cn_name, abbr in TARGET_VIRUSES:
        search_name = cn_name or en_name

        # 温度检索
        for kw in CN_TEMP_KEYWORDS[:3]:  # 只取前3个关键词避免太多
            urls.append({
                "virus_en": en_name,
                "virus_cn": cn_name,
                "source": "CNKI",
                "search_type": "temperature",
                "keyword": kw,
                "manual_search_query": f'SU=("{search_name}") * ({kw})',
                "url": f'https://kns.cnki.net/kns8s/defaultresult/index?kwd={search_name}%20{kw}',
            })

        # 毒力检索
        for kw in CN_VIR_KEYWORDS[:3]:
            urls.append({
                "virus_en": en_name,
                "virus_cn": cn_name,
                "source": "CNKI",
                "search_type": "virulence",
                "keyword": kw,
                "manual_search_query": f'SU=("{search_name}") * ({kw})',
                "url": f'https://kns.cnki.net/kns8s/defaultresult/index?kwd={search_name}%20{kw}',
            })

    csv_path = OUT_DIR / "cnki_search_urls.csv"
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(urls[0].keys()))
        writer.writeheader()
        writer.writerows(urls)
    print(f"[CNKI] Generated {len(urls)} search URLs → {csv_path}")

    # 按病毒分组统计
    by_virus = defaultdict(list)
    for u in urls:
        by_virus[u["virus_en"]].append(u)

    print(f"\n  搜索URL按病毒分布:")
    for v, items in sorted(by_virus.items()):
        print(f"    {len(items):>3} URLs | {v}")

    return urls


# ── 生成万方检索URL ──
def generate_wanfang_urls():
    """生成万方数据检索URL"""
    base = "https://s.wanfangdata.com.cn/paper"

    urls = []
    for en_name, cn_name, abbr in TARGET_VIRUSES:
        if not cn_name:
            continue
        urls.append({
            "virus_en": en_name,
            "virus_cn": cn_name,
            "source": "万方",
            "search_query": f'主题:("{cn_name}") AND (主题:"温度" OR 主题:"毒力" OR 主题:"死亡率")',
            "url": f'{base}?q=主题%3A("{cn_name}")%20AND%20(主题%3A"温度"%20OR%20主题%3A"毒力")',
        })

    csv_path = OUT_DIR / "wanfang_search_urls.csv"
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(urls[0].keys()))
        writer.writeheader()
        writer.writerows(urls)
    print(f"\n[万方] Generated {len(urls)} search URLs → {csv_path}")
    return urls


# ── 生成 FAO / WOAH 检索指引 ──
def generate_fao_woah_guide():
    """FAO和WOAH有关于虾类病毒病的公开报告"""
    guide = [
        {
            "source": "FAO Fisheries",
            "description": "FAO Cultured Aquatic Species Fact Sheets",
            "url": "https://www.fao.org/fishery/en/culturedspecies/search",
            "relevant_diseases": "WSSV, TSV, YHV, IHHNV, IMNV, CMNV, DIV1",
            "note": "搜索名称后查看 Disease 段落，通常包含温度和死亡率信息",
        },
        {
            "source": "WOAH (OIE)",
            "description": "Aquatic Animal Health Code — Disease chapters",
            "url": "https://www.woah.org/en/what-we-do/standards/codes-and-manuals/aquatic-code-online-access/",
            "relevant_diseases": "Infection with WSSV, Infection with TSV, Infection with YHV, Infection with IHHNV, Infection with DIV1",
            "note": "每个Disease Chapter都包含病原特性、温度敏感性、防控措施的标准化描述",
        },
        {
            "source": "WOAH WAHIS",
            "description": "World Animal Health Information System — disease outbreak database",
            "url": "https://wahis.woah.org/",
            "relevant_diseases": "所有报告的甲壳动物疾病",
            "note": "可查询各疾病的全球分布和暴发记录，提供quantitative的流行数据",
        },
        {
            "source": "CABI Compendium",
            "description": "Invasive Species & Diseases Compendium",
            "url": "https://www.cabidigitallibrary.org/journal/cabicompendium",
            "relevant_diseases": "WSSV, YHV, TSV, IHHNV等",
            "note": "每个条目包含详细的病原学、流行病学和温度数据摘要",
        },
        {
            "source": "NACA (亚太水产养殖中心网)",
            "description": "Network of Aquaculture Centres in Asia-Pacific — disease advisory",
            "url": "https://enaca.org/",
            "relevant_diseases": "亚太地区虾类病毒病",
            "note": "亚洲水产养殖主要病害的区域性报告和数据",
        },
    ]

    csv_path = OUT_DIR / "fao_woah_reference_guide.csv"
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(guide[0].keys()))
        writer.writeheader()
        writer.writerows(guide)
    print(f"\n[FAO/WOAH] Generated reference guide → {csv_path}")
    return guide


# ── 从CNKI导出文本中提取数据 ──
def parse_cnki_export(filepath: str):
    """
    解析CNKI导出的文本格式文件（RefWorks或NoteExpress格式）
    提取标题、摘要、年份，然后运行regex提取温度/毒力数据
    """
    with open(filepath, "r", encoding="utf-8") as f:
        text = f.read()

    # 简单解析RefWorks格式
    articles = []
    current = {}
    for line in text.split("\n"):
        line = line.strip()
        if line.startswith("RT "):
            if current:
                articles.append(current)
            current = {"type": line[3:].strip()}
        elif line.startswith("T1 "):
            current["title"] = line[3:].strip()
        elif line.startswith("AB "):
            current["abstract"] = line[3:].strip()
        elif line.startswith("YR "):
            current["year"] = line[3:].strip()
        elif line.startswith("JO "):
            current["journal"] = line[3:].strip()
    if current:
        articles.append(current)

    # 同样提取温度/毒力
    TEMP_PATTERNS = [
        re.compile(r"(\d+(?:\.\d+)?)\s*°?\s*C\s*(?:~|～|至|-)\s*(\d+(?:\.\d+)?)\s*°?\s*C"),
        re.compile(r"(\d+(?:\.\d+)?)\s*°?\s*C.*?(?:最适|最适温度|最适宜)"),
        re.compile(r"(?:热灭活|灭活温度).*?(\d+(?:\.\d+)?)\s*°?\s*C"),
        re.compile(r"(\d+(?:\.\d+)?)\s*℃"),
    ]
    VIR_PATTERNS = [
        re.compile(r"死亡率.*?(\d+(?:\.\d+)?)\s*%"),
        re.compile(r"(\d+(?:\.\d+)?)\s*%[^的]*?死亡率"),
        re.compile(r"LD50[：:]\s*(\S+)"),
        re.compile(r"累计死亡率.*?(\d+(?:\.\d+)?)\s*%"),
    ]

    findings = []
    for art in articles:
        full_text = f"{art.get('title','')} {art.get('abstract','')}"
        for pat in TEMP_PATTERNS:
            for m in pat.finditer(full_text):
                findings.append({
                    "title": art.get("title", ""),
                    "year": art.get("year", ""),
                    "type": "temperature",
                    "match": m.group(0),
                })
        for pat in VIR_PATTERNS:
            for m in pat.finditer(full_text):
                findings.append({
                    "title": art.get("title", ""),
                    "year": art.get("year", ""),
                    "type": "virulence",
                    "match": m.group(0),
                })

    print(f"  Parsed {len(articles)} articles, found {len(findings)} findings")
    return findings


# ═══════════════════════════════════════
def main():
    print("=" * 60)
    print("CNKI / 万方 / FAO-WOAH 文献检索辅助")
    print("=" * 60)

    generate_cnki_urls()
    generate_wanfang_urls()
    generate_fao_woah_guide()

    print(f"\n{'='*60}")
    print("下一步操作指南:")
    print(f"{'='*60}")
    print("""
1. CNKI检索:
   - 打开 cnki_search_urls.csv，点击URL逐个检索
   - 或用CNKI专业检索模式，粘贴 manual_search_query 列
   - 勾选相关结果 → 导出 → RefWorks 格式
   - 将导出文件保存到 cnki/ 目录下
   - 运行: python step1b_multi_source_mining.py --cnki-parse <导出文件>

2. 万方检索:
   - 打开 wanfang_search_urls.csv
   - 每个URL搜索后筛选"学位论文"和"期刊论文"
   - 导出题录为Excel

3. FAO / WOAH:
   - 按 fao_woah_reference_guide.csv 中的链接访问
   - WOAH Aquatic Code的每个Disease Chapter是高质量标准化数据源
   - 直接可引用

4. 人工审核:
   - 将上述来源的候选数据汇总
   - 逐条确认原文（通过PMID或DOI下载全文）
   - 确认后导入 virulence_profiles / temperature_profiles
""")
    print(f"\n所有文件保存在: {OUT_DIR}")


if __name__ == "__main__":
    main()
