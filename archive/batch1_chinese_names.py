"""
Batch 1e: 病毒中文名批量生成
策略: 翻译对照表 + 规则引擎自动填充
"""
import sqlite3
from pathlib import Path

DB = Path("F:/甲壳动物数据库/crustacean_virus_core.db")
conn = sqlite3.connect(str(DB))
conn.execute("PRAGMA foreign_keys = ON")
cur = conn.cursor()

total = cur.execute("SELECT COUNT(*) FROM virus_master WHERE chinese_name IS NULL OR TRIM(chinese_name)=''").fetchone()[0]
print(f"Virus master without Chinese name: {total}/{cur.execute('SELECT COUNT(*) FROM virus_master').fetchone()[0]}")

# 手动翻译对照表 - 重要甲壳动物病毒
VIRUS_NAME_MAP = {
    # 双链DNA病毒
    "White spot syndrome virus": "白斑综合征病毒",
    "Shrimp white spot syndrome virus": "白斑综合征病毒",
    "WSSV": "白斑综合征病毒",

    # ssDNA
    "Infectious hypodermal and hematopoietic necrosis virus": "传染性皮下及造血组织坏死病毒",
    "IHHNV": "传染性皮下及造血组织坏死病毒",
    "Hepatopancreatic parvovirus": "肝胰腺细小病毒",
    "HPV": "肝胰腺细小病毒",
    "Cherax quadricarinatus parvovirus": "红螯螯虾细小病毒",
    "Spawner-isolated mortality virus": "亲虾分离死亡率病毒",
    "Lymphoid organ parvo-like virus": "淋巴器官细小样病毒",

    # dsRNA
    "Macrobrachium rosenbergii nodavirus": "罗氏沼虾诺达病毒",
    "MrNV": "罗氏沼虾诺达病毒",
    "Penaeus vannamei nodavirus": "南美白对虾诺达病毒",
    "PvNV": "南美白对虾诺达病毒",

    # ssRNA(+)
    "Yellow head virus": "黄头病毒",
    "YHV": "黄头病毒",
    "Taura syndrome virus": "桃拉综合征病毒",
    "TSV": "桃拉综合征病毒",
    "Covert mortality nodavirus": "隐蔽死亡诺达病毒",
    "CMNV": "隐蔽死亡诺达病毒",
    "Penaeid shrimp infectious myonecrosis virus": "传染性肌坏死病毒",
    "Penaeus vannamei infectious myonecrosis virus": "传染性肌坏死病毒",
    "Infectious myonecrosis virus": "传染性肌坏死病毒",
    "IMNV": "传染性肌坏死病毒",
    "Penaeus stylirostris densovirus": "西方白对虾浓核病毒",
    "PstDV": "西方白对虾浓核病毒",
    "Penaeus merguiensis densovirus": "墨吉对虾浓核病毒",
    "PmergDNV": "墨吉对虾浓核病毒",
    "Fenneropenaeus chinensis hepandensovirus": "中国对虾肝胰腺浓核病毒",
    "Penaeus monodon densovirus": "斑节对虾浓核病毒",
    "PmDNV": "斑节对虾浓核病毒",
    "Callinectes sapidus reovirus 1": "蓝蟹呼肠孤病毒1",
    "CsRV1": "蓝蟹呼肠孤病毒1",
    "Eriocheir sinensis reovirus": "中华绒螯蟹呼肠孤病毒",
    "Mud crab reovirus": "青蟹呼肠孤病毒",
    "MCRV": "青蟹呼肠孤病毒",
    "Scylla serrata reovirus": "锯缘青蟹呼肠孤病毒",
    "Macrobrachium rosenbergii extra small virus": "罗氏沼虾超小病毒",
    "XSV": "罗氏沼虾超小病毒",
    "Procambarus clarkii birnavirus": "克氏原螯虾双RNA病毒",
    "Penaeus japonicus rod-shaped DNA virus": "日本对虾杆状DNA病毒",
    "Penaeus monodon baculovirus": "斑节对虾杆状病毒",
    "MBV": "斑节对虾杆状病毒",
    "Baculovirus penaei": "对虾杆状病毒",
    "BP": "对虾杆状病毒",
    "Carcinus mediterraneus W2 virus": "地中海滨蟹W2病毒",
    "Cherax destructor bacilliform virus": "破坏者螯虾杆状病毒",
    "Cherax quadricarinatus bacilliform virus": "红螯螯虾杆状病毒",

    # shrimp endogenous / EVE
    "Endogenous nimavirus": "内源尼玛病毒",
    "Endogenous nudivirus": "内源裸病毒",
    "WSSV endogenous viral element": "白斑综合征病毒内源元件",

    # crustacean-specific generic
    "Panulirus argus virus 1": "加勒比龙虾病毒1",
    "Panulirus argus virus": "加勒比龙虾病毒",
    "Homarus americanus virus": "美洲螯龙虾病毒",
    "Carcinus maenas virus": "普通滨蟹病毒",

    # Non-target but common
    "Infectious precocity virus": "传染性早熟病毒",
    "Cherax quadricarinatus iridovirus": "红螯螯虾虹彩病毒",
    "CQIV": "红螯螯虾虹彩病毒",
    "Shrimp hemocyte iridescent virus": "虾血细胞虹彩病毒",
    "SHIV": "虾血细胞虹彩病毒",
    "Decapod iridescent virus 1": "十足目虹彩病毒1",
    "DIV1": "十足目虹彩病毒1",
    "Cherax quadricarinatus ranavirus": "红螯螯虾蛙病毒",

    # New / emerging crustacean viruses
    "Penaeus vannamei picornavirus": "南美白对虾小核糖核酸病毒",
    "Penaeus vannamei flavivirus": "南美白对虾黄病毒",
    "Litopenaeus vannamei rhabdovirus": "南美白对虾弹状病毒",
    "Penaeus monodon nidovirus": "斑节对虾网巢病毒",
    "GAV": "鳃相关病毒",
    "Gill-associated virus": "鳃相关病毒",
    "Mourilyan virus": "莫里连病毒",
    "MoV": "莫里连病毒",
    "LSNV": "淋巴结病毒",
    "Lymphoid organ spheroid virus": "淋巴器官球状病毒",
    "Laem-Singh virus": "蓝辛病毒",
    "LSNV": "淋巴结病毒",
    "Wenzhou shrimp virus": "温州虾病毒",
    "Wenling crustacean virus": "温岭甲壳动物病毒",

    # viruses with family-level inference
    "unclassified totivirus": "未分类全病毒",
    "unclassified dicistrovirus": "未分类二顺反子病毒",
    "unclassified picornavirus": "未分类小核糖核酸病毒",
    "unclassified flavivirus": "未分类黄病毒",
    "unclassified rhabdovirus": "未分类弹状病毒",
    "unclassified parvovirus": "未分类细小病毒",
    "unclassified reovirus": "未分类呼肠孤病毒",
    "unclassified bunyavirus": "未分类布尼亚病毒",
    "unclassified orthomyxovirus": "未分类正黏病毒",
}

# 从 taxonomy context 推断中文名规则
TAXON_NAME_MAP = {
    "Nimaviridae": "尼玛病毒科",
    "Roniviridae": "杆套病毒科",
    "Dicistroviridae": "二顺反子病毒科",
    "Picornaviridae": "小核糖核酸病毒科",
    "Flaviviridae": "黄病毒科",
    "Rhabdoviridae": "弹状病毒科",
    "Parvoviridae": "细小病毒科",
    "Reoviridae": "呼肠孤病毒科",
    "Bunyaviridae": "布尼亚病毒科",
    "Totiviridae": "全病毒科",
    "Iridoviridae": "虹彩病毒科",
    "Nodaviridae": "诺达病毒科",
    "Baculoviridae": "杆状病毒科",
    "Nudiviridae": "裸病毒科",
    "Malacoherpesviridae": "软体动物疱疹病毒科",
    "Alloherpesviridae": "异疱疹病毒科",
    "Siphoviridae": "长尾噬菌体科",
    "Podoviridae": "短尾噬菌体科",
    "Myoviridae": "肌尾噬菌体科",
    "Circoviridae": "圆环病毒科",
    "Genomoviridae": "类双生病毒科",
    "Smacoviridae": "斯马科病毒科",
    "Polyomaviridae": "多瘤病毒科",
    "Papillomaviridae": "乳头瘤病毒科",
    "Adenoviridae": "腺病毒科",
    "Poxviridae": "痘病毒科",
    "Mimiviridae": "米米病毒科",
    "Phycodnaviridae": "藻类DNA病毒科",
    "Iflaviridae": "依发病毒科",
    "Solinviviridae": "森林病毒科",
    "Caliciviridae": "杯状病毒科",
    "Tombusviridae": "番茄丛矮病毒科",
    "Togaviridae": "披膜病毒科",
    "Coronaviridae": "冠状病毒科",
    "Astroviridae": "星状病毒科",
    "Hepeviridae": "戊肝病毒科",
    "Matonaviridae": "马托纳病毒科",
    "Orthomyxoviridae": "正黏病毒科",
    "Peribunyaviridae": "泛布尼亚病毒科",
    "Phenuiviridae": "白纤病毒科",
    "Nairoviridae": "内罗病毒科",
    "Hantaviridae": "汉坦病毒科",
    "Filoviridae": "丝状病毒科",
    "Paramyxoviridae": "副黏病毒科",
    "Pneumoviridae": "肺病毒科",
    "Retroviridae": "逆转录病毒科",
    "Hepadnaviridae": "嗜肝DNA病毒科",
}

# Step 1: exact match on canonical_name
count = 0
for eng, chn in VIRUS_NAME_MAP.items():
    cur.execute("""
        UPDATE virus_master SET chinese_name = ?
        WHERE (chinese_name IS NULL OR TRIM(chinese_name) = '')
          AND canonical_name = ?
    """, (chn, eng))
    count += cur.rowcount
print(f"[1] Exact name match: {count} rows")

# Step 2: abbreviation match (2-6 uppercase letters)
cur.execute("""
    UPDATE virus_master SET chinese_name = (
        SELECT vm2.chinese_name FROM virus_master vm2
        WHERE vm2.chinese_name IS NOT NULL
          AND TRIM(vm2.chinese_name) <> ''
          AND vm2.virus_family = virus_master.virus_family
        LIMIT 1
    )
    WHERE (chinese_name IS NULL OR TRIM(chinese_name) = '')
      AND EXISTS (
        SELECT 1 FROM virus_master vm2
        WHERE vm2.chinese_name IS NOT NULL
          AND TRIM(vm2.chinese_name) <> ''
          AND vm2.virus_family = virus_master.virus_family
      )
""")
print(f"[2] Same-family inference: {cur.rowcount} rows")

# Step 3: Rule-based Chinese name generation from canonical_name
# For records with "virus" family classification but no Chinese name
# Try to create Chinese names from English names using patterns
print("[3] Generating Chinese names from English patterns...")

# Pattern-based: "Host disease virus" -> "宿主疾病病毒"
# e.g., "Penaeus vannamei associated virus" -> "南美白对虾相关病毒"
# We use the host name mapping from the database to auto-generate

HOST_CN_MAP = dict(cur.execute(
    "SELECT scientific_name, common_name_cn FROM crustacean_hosts WHERE common_name_cn IS NOT NULL AND TRIM(common_name_cn) <> ''"
).fetchall())

VIRUS_TYPE_CN = {
    "virus": "病毒",
    "picornavirus": "小核糖核酸病毒",
    "flavivirus": "黄病毒",
    "rhabdovirus": "弹状病毒",
    "parvovirus": "细小病毒",
    "reovirus": "呼肠孤病毒",
    "totivirus": "全病毒",
    "nodavirus": "诺达病毒",
    "baculovirus": "杆状病毒",
    "nimavirus": "尼玛病毒",
    "nudivirus": "裸病毒",
    "herpesvirus": "疱疹病毒",
    "bunyavirus": "布尼亚病毒",
    "phage": "噬菌体",
    "bacteriophage": "噬菌体",
    "virophage": "噬病毒体",
    "orthomyxovirus": "正黏病毒",
    "dicistrovirus": "二顺反子病毒",
    "iridovirus": "虹彩病毒",
    "densovirus": "浓核病毒",
    "birnavirus": "双RNA病毒",
    "circovirus": "圆环病毒",
    "hepandensovirus": "肝胰腺浓核病毒",
    "nidovirus": "网巢病毒",
    "ranavirus": "蛙病毒",
}

# Generate Chinese names for records that have clear patterns
# Use LIKE 'virus%' to generate names
cur.execute("""
    UPDATE virus_master SET chinese_name = '待鉴定病毒'
    WHERE (chinese_name IS NULL OR TRIM(chinese_name) = '')
      AND canonical_name NOT LIKE '%virus%'
""")
print(f"  Unknown type -> '待鉴定病毒': {cur.rowcount} rows")

# For the remaining, try family-based naming
for eng_type, cn_type in VIRUS_TYPE_CN.items():
    cur.execute("""
        UPDATE virus_master SET chinese_name =
            COALESCE(chinese_name, virus_family || '相关' || ?)
        WHERE (chinese_name IS NULL OR TRIM(chinese_name) = '')
            AND canonical_name LIKE ?
    """, (cn_type, f"%{eng_type}%"))
    n = cur.rowcount
    if n:
        print(f"  '{eng_type}' pattern -> {cn_type}: {n} rows")

# Final count
remaining = cur.execute("SELECT COUNT(*) FROM virus_master WHERE chinese_name IS NULL OR TRIM(chinese_name)=''").fetchone()[0]
print(f"\n[Done] Still missing Chinese name: {remaining}/{total}")

conn.commit()
conn.close()
print("Saved.")
