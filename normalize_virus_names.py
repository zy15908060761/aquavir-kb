"""
病毒名称归一化脚本
目标：将188个原始名称映射到标准名称（canonical name）
"""

import sqlite3
import re
from collections import defaultdict

DB_PATH = r'F:\甲壳动物数据库\crustacean_virus_core.db'

def analyze_names():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT DISTINCT virus_name FROM viral_isolates WHERE virus_name IS NOT NULL ORDER BY virus_name")
    names = [r[0] for r in c.fetchall()]
    conn.close()
    
    print(f"Total distinct names: {len(names)}")
    print("\n=== Pattern Analysis ===")
    
    # Categorize by patterns
    categories = {
        'EST/cDNA': [],
        'Patent': [],
        'WSSV_related': [],
        'YHV_related': [],
        'TSV_related': [],
        'Beihai_viruses': [],
        'Wenzhou_viruses': [],
        'Other_crustacean': [],
        'Non_crustacean': [],
        'Generic': [],
    }
    
    for name in names:
        lower = name.lower()
        if 'EST' in name or 'cDNA' in name or 'expressed sequence' in lower:
            categories['EST/cDNA'].append(name)
        elif name.startswith('JP ') or name.startswith('KR '):
            categories['Patent'].append(name)
        elif 'white spot' in lower or 'wssv' in lower:
            categories['WSSV_related'].append(name)
        elif 'yellow head' in lower or 'yhv' in lower or 'lymphoid organ expressed' in lower:
            categories['YHV_related'].append(name)
        elif 'taura' in lower or 'tsv' in lower:
            categories['TSV_related'].append(name)
        elif 'beihai' in lower:
            categories['Beihai_viruses'].append(name)
        elif 'wenzhou' in lower or 'whenzhou' in lower:
            categories['Wenzhou_viruses'].append(name)
        elif any(x in lower for x in ['shrimp', 'crab', 'crayfish', 'lobster', 'prawn', 'decapod', 'penaeus', 'macrobrachium', 'callinectes']):
            categories['Other_crustacean'].append(name)
        elif any(x in lower for x in ['human', 'avian', 'bovine', 'swine', 'simian', 'african swine', 'murine', 'bean', 'soybean', 'tomato']):
            categories['Non_crustacean'].append(name)
        else:
            categories['Generic'].append(name)
    
    for cat, items in categories.items():
        if items:
            print(f"\n{cat} ({len(items)}):")
            for item in items[:5]:
                print(f"  - {item}")
            if len(items) > 5:
                print(f"  ... and {len(items)-5} more")
    
    return names, categories


def create_master_table(conn):
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS virus_master (
            master_id INTEGER PRIMARY KEY AUTOINCREMENT,
            canonical_name VARCHAR(200) NOT NULL UNIQUE,
            abbreviations TEXT,
            chinese_name VARCHAR(200),
            virus_family VARCHAR(100),
            virus_genus VARCHAR(100),
            genome_type VARCHAR(50),
            is_crustacean_virus INTEGER DEFAULT 1,
            entry_type VARCHAR(50) DEFAULT 'complete_genome',
            notes TEXT
        )
    ''')
    
    # Add master_id reference to viral_isolates
    try:
        c.execute("ALTER TABLE viral_isolates ADD COLUMN master_id INTEGER")
    except sqlite3.OperationalError:
        pass
    
    conn.commit()
    print("\nTable virus_master created.")


def build_normalization_rules():
    """Define mapping from raw names to canonical names"""
    
    # (
    #   canonical_name, [patterns], chinese_name, abbreviations,
    #   family, genus, genome_type, entry_type, is_crustacean_virus
    # )
    rules = [
        # WSSV group
        ("White spot syndrome virus", 
         ["white spot syndrome virus", "shrimp white spot syndrome virus", "wssv"],
         "白斑综合征病毒", "WSSV", "Nimaviridae", "Whispovirus", "dsDNA", "complete_genome", 1),
        
        # YHV group  
        ("Yellow head virus",
         ["yellow head virus", "lymphoid organ expressed yellow head virus", "gill-associated virus", "gav"],
         "黄头病毒", "YHV/GAV", "Roniviridae", "Okavirus", "+ssRNA", "complete_genome", 1),
        
        # TSV group
        ("Taura syndrome virus",
         ["taura syndrome virus", "tsv"],
         "陶拉综合征病毒", "TSV", "Aparvoviridae", "Aparavirus", "+ssRNA", "complete_genome", 1),
        
        # IHHNV group
        ("Infectious hypodermal and hematopoietic necrosis virus",
         ["infectious hypodermal and hematopoietic necrosis virus", "ihhnv"],
         "传染性皮下和造血组织坏死病毒", "IHHNV", "Parvoviridae", "Penstyldensovirus", "ssDNA", "complete_genome", 1),
        
        # IMNV group
        ("Infectious myonecrosis virus",
         ["infectious myonecrosis virus", "penaeid shrimp infectious myonecrosis virus", "imnv"],
         "传染性肌肉坏死病毒", "IMNV", "Totiviridae", "", "dsRNA", "complete_genome", 1),
        
        # MrNV group
        ("Macrobrachium rosenbergii nodavirus",
         ["macrobrachium rosenbergii nodavirus", "mrnv"],
         "罗氏沼虾诺达病毒", "MrNV", "Nodaviridae", "", "+ssRNA", "complete_genome", 1),
        
        # CMNV
        ("Covert mortality nodavirus",
         ["covert mortality nodavirus", "cmnv"],
         "偷死病诺达病毒", "CMNV", "Nodaviridae", "", "+ssRNA", "complete_genome", 1),
        
        # HPV
        ("Hepatopancreatic parvovirus",
         ["hepatopancreatic parvovirus", "hpv"],
         "肝胰腺细小病毒", "HPV", "Parvoviridae", "", "ssDNA", "complete_genome", 1),
        
        # LSNV
        ("Laem-Singh virus",
         ["laem-singh virus", "laem singh virus", "lsnv"],
         "Laem-Singh病毒", "LSNV", "", "", "+ssRNA", "complete_genome", 1),
        
        # Decapod iridescent virus
        ("Decapod iridescent virus",
         ["decapod iridescent virus", "invertebrate iridescent virus", "shrimp hemocyte iridescent virus"],
         "甲壳类虹彩病毒", "DIV", "Iridoviridae", "", "dsDNA", "complete_genome", 1),
        
        # Beihai viruses
        ("Beihai shrimp virus",
         ["beihai shrimp virus"],
         "北海虾病毒", "", "", "", "", "complete_genome", 1),
        ("Beihai crab virus",
         ["beihai crab virus", "beihai blue swimmer crab virus", "beihai charybdis crab virus", 
          "beihai hermit crab virus", "beihai horseshoe crab virus", "beihai mantis shrimp virus",
          "beihai sesarmid crab virus", "beihai tiger crab virus"],
         "北海蟹类病毒", "", "", "", "", "complete_genome", 1),
        
        # Wenzhou viruses
        ("Wenzhou shrimp virus",
         ["wenzhou shrimp virus", "wenling crustacean virus"],
         "温州虾病毒", "", "", "", "", "complete_genome", 1),
        ("Wenzhou crab virus",
         ["wenzhou crab virus"],
         "温州蟹病毒", "", "", "", "", "complete_genome", 1),
        ("Wenzhou Shrimp Virus 1",
         ["wenzhou shrimp virus 1", "whenzhou shrimp virus 1"],
         "温州虾病毒1型", "WZSV-1", "", "", "", "complete_genome", 1),
        ("Wenzhou Shrimp Virus 2",
         ["wenzhou shrimp virus 2", "whenzhou shrimp virus 2"],
         "温州虾病毒2型", "WZSV-2", "", "", "", "complete_genome", 1),
        ("Wenzhou Crab Virus 2",
         ["wenzhou crab virus 2"],
         "温州蟹病毒2型", "WZCV-2", "", "", "", "complete_genome", 1),
        ("Wenzhou Crab Virus 3",
         ["wenzhou crab virus 3"],
         "温州蟹病毒3型", "WZCV-3", "", "", "", "complete_genome", 1),
        
        # Chinese mitten crab virus
        ("Chinese mitten crab virus",
         ["chinese mitten crab virus"],
         "中华绒螯蟹病毒", "", "", "", "", "complete_genome", 1),
        
        # Circular viruses
        ("Crab associated circular virus",
         ["crab associated circular virus", "callinectes ornatus blue crab associated circular virus",
          "hermit crab associated circular virus", "farfantepenaeus duorarum pink shrimp associated circular virus",
          "mississippi grass shrimp associated circular virus", "palaemonetes intermedius brackish grass shrimp associated circular virus",
          "common grass shrimp associated circular virus", "petrochirus diogenes giant hermit crab associated circular virus"],
         "甲壳类环状病毒", "", "Circoviridae", "", "ssDNA", "complete_genome", 1),
        
        # Penaeus monodon endogenous virus
        ("Penaeus monodon endogenous virus",
         ["penaeus monodon endogenous virus"],
         "斑节对虾内源性病毒", "", "", "", "", "complete_genome", 1),
        
        # Non-crustacean (should be filtered)
        ("Human immunodeficiency virus",
         ["human immunodeficiency virus"],
         "人类免疫缺陷病毒", "HIV", "Retroviridae", "Lentivirus", "+ssRNA", "non_target", 0),
        ("African swine fever virus",
         ["african swine fever virus"],
         "非洲猪瘟病毒", "ASFV", "Asfarviridae", "Asfivirus", "dsDNA", "non_target", 0),
        ("SARS-CoV-2",
         ["sars-cov-2", "severe acute respiratory syndrome coronavirus"],
         "SARS冠状病毒2型", "", "Coronaviridae", "Betacoronavirus", "+ssRNA", "non_target", 0),
    ]
    
    return rules


def apply_normalization(incremental=True):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    # Create tables
    create_master_table(conn)
    
    if incremental:
        # Only process records without master_id or with Unknown/Unclassified
        c.execute("""
            SELECT DISTINCT virus_name FROM viral_isolates 
            WHERE virus_name IS NOT NULL
              AND (master_id IS NULL OR master_id = (SELECT master_id FROM virus_master WHERE canonical_name = 'Unknown/Unclassified'))
        """)
        all_names = [r[0] for r in c.fetchall()]
        print(f"Incremental mode: {len(all_names)} new/unknown names to process")
    else:
        c.execute("SELECT DISTINCT virus_name FROM viral_isolates WHERE virus_name IS NOT NULL")
        all_names = [r[0] for r in c.fetchall()]
        print(f"Full mode: {len(all_names)} names to process")
    
    if not all_names:
        print("No names to process.")
        conn.close()
        return
    
    rules = build_normalization_rules()
    
    # Insert master records
    master_map = {}  # canonical_name -> master_id
    for rule in rules:
        canonical, patterns, cn_name, abbr, family, genus, gtype, etype, crust_flag = rule
        try:
            c.execute('''
                INSERT INTO virus_master (canonical_name, abbreviations, chinese_name, 
                    virus_family, virus_genus, genome_type, entry_type, is_crustacean_virus)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (canonical, abbr, cn_name, family, genus, gtype, etype, crust_flag))
            master_id = c.lastrowid
            master_map[canonical] = master_id
        except sqlite3.IntegrityError:
            c.execute('''
                UPDATE virus_master
                SET abbreviations = ?, chinese_name = ?, virus_family = ?, virus_genus = ?,
                    genome_type = ?, entry_type = ?, is_crustacean_virus = ?
                WHERE canonical_name = ?
            ''', (abbr, cn_name, family, genus, gtype, etype, crust_flag, canonical))
            c.execute("SELECT master_id FROM virus_master WHERE canonical_name = ?", (canonical,))
            master_id = c.fetchone()[0]
            master_map[canonical] = master_id
    
    # Also add an "Unknown" entry
    c.execute('''
        INSERT OR IGNORE INTO virus_master (canonical_name, chinese_name, entry_type, is_crustacean_virus)
        VALUES (?, ?, ?, ?)
    ''', ("Unknown/Unclassified", "未知/未分类", "unknown", 0))
    c.execute("SELECT master_id FROM virus_master WHERE canonical_name = ?", ("Unknown/Unclassified",))
    unknown_id = c.fetchone()[0]
    master_map["Unknown/Unclassified"] = unknown_id
    
    # Map each raw name to canonical
    mapped = 0
    unmapped = []
    
    for raw_name in all_names:
        lower = raw_name.lower()
        matched = False
        
        for rule in rules:
            canonical, patterns, _, _, _, _, _, _, _ = rule
            for pattern in patterns:
                if pattern in lower:
                    c.execute('''
                        UPDATE viral_isolates SET master_id = ? WHERE virus_name = ?
                    ''', (master_map[canonical], raw_name))
                    mapped += c.rowcount
                    matched = True
                    break
            if matched:
                break
        
        if not matched:
            unmapped.append(raw_name)
    
    # Mark remaining as unknown
    c.execute("UPDATE viral_isolates SET master_id = ? WHERE master_id IS NULL", (unknown_id,))
    
    conn.commit()
    
    # Print summary
    print(f"\n=== Normalization Summary ===")
    print(f"Processed names: {len(all_names)}")
    print(f"Mapped records: {mapped}")
    print(f"Unmapped names: {len(unmapped)}")
    if unmapped:
        print("\nUnmapped names (need manual review):")
        for name in unmapped[:10]:
            c.execute("SELECT COUNT(*) FROM viral_isolates WHERE virus_name = ?", (name,))
            count = c.fetchone()[0]
            print(f"  [{count}] {name}")
    
    conn.close()


if __name__ == "__main__":
    names, cats = analyze_names()
    apply_normalization()
