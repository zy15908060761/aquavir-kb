"""
定期数据同步脚本：从NCBI查询新增甲壳类病毒记录并下载
运行方式: python ncbi_sync.py
"""

import sqlite3
import time
from pathlib import Path
from Bio import Entrez, SeqIO
import xml.etree.ElementTree as ET

DB_PATH = Path(r'F:\甲壳动物数据库\crustacean_virus_core.db')
GB_FILE = Path(r'F:\甲壳动物数据库\ncbi_metadata\crustacean_virus_raw.gb')
SEQ_DIR = Path(r'F:\甲壳动物数据库\sequences')

# NCBI API config
Entrez.email = "user@example.com"  # Replace with your email
Entrez.tool = "CrustaceanVirusDB"

# Search terms for crustacean viruses (reduced for speed)
SEARCH_TERMS = [
    "shrimp virus",
    "crab virus",
    "crustacean virus",
    "penaeus virus",
]


def get_existing_ids():
    """获取数据库中已有的accession列表"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT accession FROM viral_isolates")
    existing = {r[0] for r in c.fetchall()}
    conn.close()
    return existing


def search_ncbi(term, retmax=100):
    """在NCBI搜索新记录"""
    try:
        handle = Entrez.esearch(db="nucleotide", term=term, retmax=retmax, idtype="acc")
        record = Entrez.read(handle)
        handle.close()
        return record.get("IdList", [])
    except Exception as e:
        print(f"  Search failed for '{term}': {e}")
        return []


def fetch_gb_records(id_list, batch_size=50):
    """批量下载GenBank记录"""
    records = []
    for i in range(0, len(id_list), batch_size):
        batch = id_list[i:i+batch_size]
        print(f"  Fetching batch {i//batch_size + 1}/{(len(id_list)-1)//batch_size + 1} ({len(batch)} records)...")
        try:
            handle = Entrez.efetch(db="nucleotide", id=batch, rettype="gb", retmode="text")
            for rec in SeqIO.parse(handle, "genbank"):
                records.append(rec)
            handle.close()
            time.sleep(0.5)  # Be nice to NCBI
        except Exception as e:
            print(f"    Batch fetch failed: {e}")
            time.sleep(2)
    return records


def filter_crustacean_records(records):
    """过滤非甲壳类病毒的记录"""
    crustacean_keywords = ['shrimp', 'crab', 'crustacean', 'penaeus', 'macrobrachium', 'callinectes', 'crayfish', 'lobster']
    filtered = []
    for rec in records:
        desc = rec.description.lower()
        if any(kw in desc for kw in crustacean_keywords):
            filtered.append(rec)
    return filtered


def sync():
    print("=" * 60)
    print("NCBI Crustacean Virus Data Sync")
    print("=" * 60)
    
    existing_ids = get_existing_ids()
    print(f"\nExisting records in database: {len(existing_ids)}")
    
    # Search NCBI
    print("\nSearching NCBI...")
    all_new_ids = set()
    for term in SEARCH_TERMS:
        ids = search_ncbi(term, retmax=200)
        new_ids = [id for id in ids if id not in existing_ids]
        all_new_ids.update(new_ids)
        print(f"  '{term}': {len(ids)} found, {len(new_ids)} new")
        time.sleep(0.5)
    
    if not all_new_ids:
        print("\nNo new records found. Database is up to date.")
        return
    
    print(f"\nTotal new records to download: {len(all_new_ids)}")
    
    # Fetch records
    records = fetch_gb_records(list(all_new_ids))
    print(f"Downloaded {len(records)} records")
    
    # Filter
    crustacean_records = filter_crustacean_records(records)
    print(f"Crustacean-related records: {len(crustacean_records)}")
    
    if not crustacean_records:
        print("No new crustacean virus records.")
        return
    
    # Append to raw.gb
    print(f"\nAppending {len(crustacean_records)} records to {GB_FILE}...")
    with open(GB_FILE, 'a') as f:
        SeqIO.write(crustacean_records, f, "genbank")
    
    print("\nSync complete!")
    print(f"  New records: {len(crustacean_records)}")
    print(f"  Total database: {len(existing_ids) + len(crustacean_records)}")
    print("\nNote: Run 'build_sqlite_core_db_v2.py' to update the SQLite database with new records.")


if __name__ == "__main__":
    sync()
