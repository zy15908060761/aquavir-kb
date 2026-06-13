"""
序列完整性分级标注
从GenBank定义中提取关键词判断序列类型
"""

import sqlite3
from Bio import SeqIO

DB_PATH = r'F:\甲壳动物数据库\crustacean_virus_core.db'
GB_FILE = r'F:\甲壳动物数据库\ncbi_metadata\crustacean_virus_raw.gb'

def classify_sequence(record):
    """根据GenBank记录判断序列完整性"""
    desc = record.description.lower()
    
    # EST entries
    if 'EST' in record.description or 'expressed sequence tag' in desc:
        return 'EST'
    
    # mRNA entries
    if record.annotations.get('molecule_type') == 'mRNA':
        return 'mRNA'
    
    # Check for completeness indicators
    if 'complete genome' in desc or 'complete sequence' in desc:
        return 'complete_genome'
    
    if 'partial' in desc:
        return 'partial_sequence'
    
    if 'segment' in desc:
        return 'genome_segment'
    
    # Gene-level entries
    if any(x in desc for x in ['gene,', 'cds,', 'protein', 'polyprotein', 'orf']):
        return 'gene_fragment'
    
    if 'unverified' in desc:
        return 'unverified'
    
    return 'unknown'


def main():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    # Add completeness column
    try:
        c.execute("ALTER TABLE viral_isolates ADD COLUMN completeness VARCHAR(50)")
    except sqlite3.OperationalError:
        pass
    
    # Check if running in incremental mode
    c.execute("SELECT COUNT(*) FROM viral_isolates WHERE completeness IS NULL")
    null_count = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM viral_isolates")
    total_count = c.fetchone()[0]
    
    if null_count > 0 and null_count < total_count:
        incremental = True
        print(f"Incremental mode: {null_count} records need classification")
    else:
        incremental = False
        print("Full mode: classifying all records")
    
    print("Classifying sequences...")
    stats = {}
    total = 0
    updated = 0
    
    for rec in SeqIO.parse(GB_FILE, 'genbank'):
        acc = rec.id
        comp = classify_sequence(rec)
        stats[comp] = stats.get(comp, 0) + 1
        total += 1
        
        if incremental:
            # Only update if completeness is NULL
            c.execute("UPDATE viral_isolates SET completeness = ? WHERE accession = ? AND completeness IS NULL",
                      (comp, acc))
            if c.rowcount > 0:
                updated += 1
        else:
            c.execute("UPDATE viral_isolates SET completeness = ? WHERE accession = ?",
                      (comp, acc))
            updated += c.rowcount
        
        if total % 500 == 0:
            print(f"  Processed {total}...")
    
    conn.commit()
    
    print(f"\nClassification complete. Total in GB: {total}")
    print(f"Records updated: {updated}")
    print("Distribution:")
    for comp, count in sorted(stats.items(), key=lambda x: -x[1]):
        print(f"  {comp:20s}: {count:4d}")
    
    conn.close()


if __name__ == "__main__":
    main()
