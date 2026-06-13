"""
Batch 1d: 宿主养殖状态批量填充 + 宿主分类学补全
策略: 对已知重要养殖物种标注FAO/NACA养殖状态
"""
import sqlite3
from pathlib import Path

DB = Path("F:/甲壳动物数据库/crustacean_virus_core.db")
conn = sqlite3.connect(str(DB))
conn.execute("PRAGMA foreign_keys = ON")
cur = conn.cursor()

# === 宿主养殖状态填充 ===
print("=== 宿主养殖状态填充 ===")

# 已知重要养殖物种及其养殖状态  (FAO/NACA标准的简化)
AQUACULTURE_STATUS = {
    # 主要养殖对虾 (Major cultured penaeid shrimp)
    "Litopenaeus vannamei": "major_commercial",
    "Penaeus vannamei (shrimp)": "major_commercial",
    "Penaeus vannamei (synonym: Litopenaeus vannamei)": "major_commercial",
    "Litopenaeus vannamei (shrimp)": "major_commercial",
    "Penaeus monodon": "major_commercial",
    "tiger shrimp (Penaeus monodon)": "major_commercial",
    "Penaeus monodon (tiger shrimp)": "major_commercial",
    "Penaeus spp.": "major_commercial",
    "Penaeid shrimp": "major_commercial",
    "Penaeus chinensis": "major_commercial",
    "Fenneropenaeus chinensis": "major_commercial",
    "Marsupenaeus japonicus": "major_commercial",
    "Penaeus japonicus": "major_commercial",
    "Penaeus stylirostris": "commercial",
    "Penaeus indicus": "commercial",
    "Penaeus indicus (synonym: Fenneropenaeus indicus)": "commercial",
    "penaeus indicus (shrimp)": "commercial",
    "Fenneropenaeus indicus": "commercial",
    "Farfantepenaeus californiensis": "commercial",
    "Penaeus merguiensis": "commercial",
    "Penaeus semisulcatus": "commercial",
    "Penaeus setiferus": "commercial",
    "Metapenaeus ensis": "commercial",
    "Metapenaeus affinis": "commercial",
    "Metapenaeus monoceros": "commercial",
    "Trachypenaeus curvirostris": "commercial",
    "Trachysalambria curvirostris": "commercial",
    "Litopenaeus sp.": "commercial",
    "Exopalaemon orientis": "commercial",
    "Metapenaeopsis lamellata": "minor_commercial",

    # 淡水虾 (Freshwater prawns)
    "Macrobrachium rosenbergii": "major_commercial",
    "Macrobrachium rosenbergii de Man": "major_commercial",
    "Macrobrachium rosenbergii (giant freshwater prawn)": "major_commercial",
    "Macrobrachium nipponense": "commercial",
    "Macrobrachium sp.": "commercial",

    # 螯虾 (Crayfish)
    "Procambarus clarkii": "major_commercial",
    "Procambarus alleni": "minor_commercial",
    "Astacidea": "commercial",
    "signal crayfish": "commercial",
    "Cherax quadricarinatus": "commercial",

    # 蟹 (Crabs)
    "Eriocheir sinensis": "major_commercial",
    "Scylla serrata": "major_commercial",
    "Scylla sp. (crab)": "commercial",
    "Callinectes sapidus": "commercial",
    "Callinectes arcuatus": "minor_commercial",
    "Portunus trituberculatus": "commercial",
    "Portunus pelagicus": "commercial",
    "blue swimmer crab": "commercial",
    "Carcinus maenas": "invasive_not_cultured",
    "Brachyura": "commercial",
    "Charybdis japonica": "commercial",
    "Charybdis crab": "commercial",
    "Orisarma dehaani": "commercial",
    "Sesarmid crab": "minor_commercial",

    # 龙虾 (Lobsters)
    "Homarus americanus": "major_commercial",
    "Panulirus homarus (spiny lobster)": "commercial",
    "Panulirus ornatus": "commercial",
    "Panulirus echinatus (wild population)": "wild_fishery",

    # 卤虫 (Brine shrimp - aquaculture feed)
    "Artemia sp.": "aquaculture_feed",
    "Artemia salina": "aquaculture_feed",
    "Artemia sinica": "aquaculture_feed",
    "Artemia franciscana": "aquaculture_feed",
    "Artemia tibetiana": "aquaculture_feed",
    "Artemia parthenogenetic lineage": "aquaculture_feed",

    # 其他甲壳动物
    "Alpheus distinguendus": "minor_commercial",
    "Mantis shrimp": "commercial",
    "Crustacea": "mixed",
    "Palaemon gravieri": "commercial",
    "Palaemonetes intermedius": "wild_fishery",
    "Palaemonetes kadiakensis": "wild_fishery",
    "Palaemonetes sp.": "wild_fishery",
    "Crangon sp.": "commercial",
    "fiddler crab": "wild_fishery",
    "hermit crab": "wild_fishery",
    "hermit crab mix Beihai": "wild_fishery",
    "Petrochirus diogenes": "wild_fishery",
    "tiger crab": "wild_fishery",
    "Goniopsis cruentata": "wild_fishery",
    "Chasmagnathus granulata": "wild_fishery",
    "Capitulum mitella": "commercial",

    # 非甲壳类 (non-crustacean hosts - 数据库中的误分类)
    "Bellamya sp.": "not_crustacean",
    "Bivalva": "not_crustacean",
    "Gerres cinereus": "not_crustacean",
    "Lile stolifera": "not_crustacean",
    "Oreochromis sp.": "not_crustacean",
    "small fish": "not_crustacean",
    "tadpole": "not_crustacean",
    "water boatman": "not_crustacean",
    "water strider": "not_crustacean",
    "insects": "not_crustacean",
    "plankton": "not_crustacean",
    "crustacean mix": "mixed",
    "Bioflake": "not_applicable",
    "Woodlouse": "not_cultured",
    "woodlouse": "not_cultured",
    "horseshoe crab": "not_crustacean",
    "Acanthaster planci": "not_crustacean",
    "Gallus gallus": "not_crustacean",
    "DH10B E.coli": "not_crustacean",
    "DH10B cells": "not_crustacean",
    "E. coli (ElectroMAX DH5?-E": "not_crustacean",
    "E.coli DH5 alpha": "not_crustacean",
    "E.coli SOLR strain": "not_crustacean",
    "GH K12": "not_crustacean",
    "Margaritifera falcata": "not_crustacean",
    "Octolasmis neptuni": "not_cultured",
    "freshwater atyid shrimp": "wild_fishery",

    # 未列出的常见养殖物种补充
    "Penaeus (Litopenaeus) vannamei": "major_commercial",
    "Litopenaeus stylirostris": "commercial",
    "Farfantepenaeus duorarum": "commercial",
    "Callinectes ornatus": "minor_commercial",
}

total = cur.execute("SELECT COUNT(*) FROM crustacean_hosts WHERE aquaculture_status IS NULL").fetchone()[0]
print(f"Hosts without aquaculture_status: {total}")

# 用精确匹配填充
for sci_name, status in AQUACULTURE_STATUS.items():
    cur.execute("""
        UPDATE crustacean_hosts SET aquaculture_status = ?
        WHERE aquaculture_status IS NULL AND scientific_name = ?
    """, (status, sci_name))

# 用LIKE模糊匹配 (处理名称变体)
fuzzy_patterns = {
    "Penaeus%": "commercial",
    "Litopenaeus%": "major_commercial",
    "Macrobrachium%": "commercial",
    "Procambarus%": "commercial",
    "Artemia%": "aquaculture_feed",
    "Scylla%": "commercial",
    "Portunus%": "commercial",
    "Panulirus%": "commercial",
    "Callinectes%": "commercial",
    "Eriocheir%": "major_commercial",
    "Farfantepenaeus%": "commercial",
    "Fenneropenaeus%": "commercial",
    "Metapenaeus%": "commercial",
    "Marsupenaeus%": "commercial",
    "Palaemon%": "commercial",
    "Palaemonetes%": "commercial",
    "Homarus%": "major_commercial",
    "Cherax%": "commercial",
    "Carcinus%": "not_cultured",
    "Crangon%": "commercial",
    "Charybdis%": "commercial",
    "Trachypenaeus%": "commercial",
    "Trachysalambria%": "commercial",
    "Exopalaemon%": "commercial",
}

for pattern, status in fuzzy_patterns.items():
    cur.execute("""
        UPDATE crustacean_hosts SET aquaculture_status = ?
        WHERE aquaculture_status IS NULL AND scientific_name LIKE ?
    """, (status, pattern))

remaining = cur.execute("SELECT COUNT(*) FROM crustacean_hosts WHERE aquaculture_status IS NULL").fetchone()[0]
print(f"Remaining without aquaculture_status: {remaining}")

# === 宿主分类学补全 ===
print("\n=== 宿主分类学补全 ===")

HOST_TAXONOMY = {
    "plankton": ("Mixed", "Mixed"),
    "Bioflake": ("N/A", "N/A"),
    "Astacidea": ("Decapoda", "Multiple"),
    "Bivalva": ("Veneroida", "Multiple"),
    "crustacean mix": ("Mixed", "Mixed"),
    "insects": ("Hexapoda", "Multiple"),
    "Crustacea": ("Multiple", "Multiple"),
    "Bellamya sp.": ("Architaenioglossa", "Viviparidae"),
    "small fish": ("Mixed", "Mixed"),
    "DH10B cells": ("Enterobacterales", "Enterobacteriaceae"),
    "DH10B E.coli": ("Enterobacterales", "Enterobacteriaceae"),
    "GH K12": ("Enterobacterales", "Enterobacteriaceae"),
    "Brachyura": ("Decapoda", "Multiple"),
    "E. coli (ElectroMAX DH5?-E": ("Enterobacterales", "Enterobacteriaceae"),
    "E.coli DH5 alpha": ("Enterobacterales", "Enterobacteriaceae"),
    "E.coli SOLR strain": ("Enterobacterales", "Enterobacteriaceae"),
    "tadpole": ("Anura", "Multiple"),
}

for sci_name, (order_val, family_val) in HOST_TAXONOMY.items():
    cur.execute("""
        UPDATE crustacean_hosts SET taxon_order = COALESCE(taxon_order, ?),
                                    taxon_family = COALESCE(taxon_family, ?)
        WHERE scientific_name = ?
    """, (order_val, family_val, sci_name))

missing_order = cur.execute("SELECT COUNT(*) FROM crustacean_hosts WHERE taxon_order IS NULL").fetchone()[0]
missing_family = cur.execute("SELECT COUNT(*) FROM crustacean_hosts WHERE taxon_family IS NULL").fetchone()[0]
print(f"Still missing order: {missing_order}, family: {missing_family}")

conn.commit()
conn.close()
print("Saved.")
