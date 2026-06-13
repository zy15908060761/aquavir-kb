"""
基于 requests 的甲壳类病毒 NCBI metadata 批量下载工具
解决 Biopython urllib SSL 握手不稳定的问题
"""
import ssl
import urllib3
import xml.etree.ElementTree as ET
import time
from pathlib import Path

import pandas as pd
import requests
from Bio import SeqIO

# 解决部分环境下 NCBI HTTPS SSL 握手失败的问题
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
requests.packages.urllib3.util.ssl_.DEFAULT_CIPHERS = "ALL:@SECLEVEL=1"

# ==================== 必须修改 ====================
EMAIL = "your_email@sysu.edu.cn"  # <-- 改成你的真实邮箱
# =================================================

OUT_DIR = Path("F:/甲壳动物数据库/ncbi_metadata")
OUT_DIR.mkdir(exist_ok=True)
GB_CACHE = OUT_DIR / "crustacean_virus_raw.gb"

QUERIES = [
    '(shrimp[Title] OR prawn[Title]) AND virus[Title]',
    '(crab[Title] OR crayfish[Title]) AND virus[Title]',
    '(lobster[Title] OR decapod[Title]) AND virus[Title]',
    'crustacean[Title] AND virus[Title]',
    'white spot syndrome virus[Title]',
    'infectious hypodermal and hematopoietic necrosis virus[Title]',
    'Taura syndrome virus[Title]',
    'yellow head virus[Title] OR gill associated virus[Title]',
    'Macrobrachium rosenbergii nodavirus[Title]',
]

BATCH_SIZE = 200
SLEEP = 0.4
TIMEOUT = 20

ESEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
EFETCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"


def esearch_ids(query, retmax=20000):
    """用 requests 执行 esearch，返回 Accession 列表"""
    params = {
        "db": "nucleotide",
        "term": query,
        "retmax": retmax,
        "idtype": "acc",
        "email": EMAIL,
        "tool": "crustacean_db_downloader",
    }
    for attempt in range(3):
        try:
            r = requests.get(ESEARCH_URL, params=params, timeout=TIMEOUT, verify=True)
            r.raise_for_status()
            root = ET.fromstring(r.text)
            ids = [elem.text for elem in root.findall("IdList/Id")]
            return ids
        except Exception as e:
            print(f"  [Retry {attempt + 1}/3] {e}")
            time.sleep(2 ** attempt)
    return []


def efetch_gb_text(id_list):
    """用 requests 执行 efetch，返回 GenBank 文本"""
    params = {
        "db": "nucleotide",
        "id": ",".join(id_list),
        "rettype": "gb",
        "retmode": "text",
        "email": EMAIL,
        "tool": "crustacean_db_downloader",
    }
    for attempt in range(3):
        try:
            r = requests.get(EFETCH_URL, params=params, timeout=120, verify=True)
            r.raise_for_status()
            return r.text
        except Exception as e:
            print(f"  [Retry {attempt + 1}/3] {e}")
            time.sleep(2 ** attempt)
    return ""


def fetch_gb_batches(id_list, cache_file=GB_CACHE):
    """分批下载 GenBank，追加写入缓存，支持断点续传"""
    total = len(id_list)
    done = 0
    if cache_file.exists() and cache_file.stat().st_size > 0:
        try:
            done = len(list(SeqIO.parse(str(cache_file), "genbank")))
            print(f"[Resume] 检测到已有 {done} 条记录，继续下载...")
        except Exception:
            print("[Warn] 缓存文件损坏，重新下载")
            cache_file.write_text("", encoding="utf-8")
    else:
        cache_file.write_text("", encoding="utf-8")

    start_batch = (done // BATCH_SIZE) * BATCH_SIZE
    print(f"[Fetch] 总计 {total} 条，从第 {start_batch + 1} 条继续，缓存: {cache_file}")

    with cache_file.open("a", encoding="utf-8") as f_out:
        for start in range(start_batch, total, BATCH_SIZE):
            end = min(total, start + BATCH_SIZE)
            batch = id_list[start:end]
            print(f"  批次 {start + 1} - {end} / {total}")
            gb_text = efetch_gb_text(batch)
            if gb_text:
                f_out.write(gb_text)
            else:
                print(f"  [WARN] 本批最终失败 {start + 1}-{end}")
            time.sleep(SLEEP)

    print(f"[Done] 下载完成")


def parse_gb_cache(cache_file=GB_CACHE):
    """解析缓存的 GenBank"""
    print(f"[Parse] 解析 {cache_file} ...")
    records = list(SeqIO.parse(str(cache_file), "genbank"))
    print(f"  -> 解析到 {len(records)} 条记录")
    return records


def extract_metadata(records):
    """提取 IVCDB 式标准化字段"""
    rows = []
    for rec in records:
        source = rec.features[0] if rec.features else None
        quals = source.qualifiers if source else {}
        refs = rec.annotations.get("references", [])
        first_ref = refs[0] if refs else None

        db_xrefs = quals.get("db_xref", [])
        taxon_id = ""
        for xref in db_xrefs:
            if xref.startswith("taxon:"):
                taxon_id = xref.replace("taxon:", "")
                break

        authors = ""
        if first_ref and getattr(first_ref, "authors", None):
            parts = [a.strip() for a in first_ref.authors.split(",") if a.strip()]
            if len(parts) > 3:
                authors = ", ".join(parts[:3]) + ", et al."
            else:
                authors = ", ".join(parts)

        row = {
            "accession": rec.id,
            "name": rec.name,
            "definition": rec.description,
            "length": len(rec.seq),
            "topology": rec.annotations.get("topology", ""),
            "date": rec.annotations.get("date", ""),
            "molecule_type": rec.annotations.get("molecule_type", ""),
            "organism": rec.annotations.get("organism", ""),
            "taxonomy": "; ".join(rec.annotations.get("taxonomy", [])),
            "taxon_id": taxon_id,
            "keywords": "; ".join(rec.annotations.get("keywords", [])),
            "source_organism": "; ".join(quals.get("organism", [])),
            "host": "; ".join(quals.get("host", [])),
            "isolate": "; ".join(quals.get("isolate", [])),
            "strain": "; ".join(quals.get("strain", [])),
            "country": "; ".join(quals.get("country", [])),
            "collection_date": "; ".join(quals.get("collection_date", [])),
            "isolation_source": "; ".join(quals.get("isolation_source", [])),
            "lat_lon": "; ".join(quals.get("lat_lon", [])),
            "collected_by": "; ".join(quals.get("collected_by", [])),
            "note": "; ".join(quals.get("note", [])),
            "reference_title": first_ref.title if first_ref else "",
            "reference_authors": authors,
            "reference_journal": first_ref.journal if first_ref else "",
            "pubmed_id": first_ref.pubmed_id if first_ref else "",
        }
        rows.append(row)
    return rows


ID_LIST_FILE = OUT_DIR / "unique_ids.txt"


def run_pipeline():
    print("=" * 60)
    print("甲壳类病毒 NCBI Metadata 批量下载工具 (requests 版)")
    print("=" * 60)

    # Step 1: 搜索（如果已有 ID 列表则跳过）
    if ID_LIST_FILE.exists():
        print(f"[Load] 从已有文件读取 ID 列表: {ID_LIST_FILE}")
        unique_ids = ID_LIST_FILE.read_text(encoding="utf-8").strip().splitlines()
        unique_ids = [x.strip() for x in unique_ids if x.strip()]
        print(f"[Total] 共 {len(unique_ids)} 条唯一记录")
    else:
        all_ids = []
        query_stats = {}
        for q in QUERIES:
            ids = esearch_ids(q)
            query_stats[q] = len(ids)
            print(f"{len(ids):5d} | {q}")
            all_ids.extend(ids)
            time.sleep(SLEEP)

        seen = set()
        unique_ids = [x for x in all_ids if not (x in seen or seen.add(x))]

        print(f"\n[Summary]")
        for q, c in query_stats.items():
            print(f"  {c:5d} | {q}")
        print(f"\n[Total] 去重后共 {len(unique_ids)} 条唯一记录")

        # 保存 ID 列表
        ID_LIST_FILE.write_text("\n".join(unique_ids), encoding="utf-8")
        print(f"[Save] ID 列表已保存到 {ID_LIST_FILE}")

    if not unique_ids:
        print("未找到任何记录，请检查网络或搜索词。")
        return

    # Step 2: 下载
    fetch_gb_batches(unique_ids)

    # Step 3: 解析
    records = parse_gb_cache()
    rows = extract_metadata(records)
    df = pd.DataFrame(rows)
    df = df.dropna(axis=1, how="all")
    df = df.sort_values(by="accession").reset_index(drop=True)

    # Step 4: 导出
    excel_path = OUT_DIR / "crustacean_virus_metadata.xlsx"
    csv_path = OUT_DIR / "crustacean_virus_metadata.csv"
    df.to_excel(excel_path, index=False, engine="openpyxl")
    df.to_csv(csv_path, index=False, encoding="utf-8-sig")

    print(f"\n[Output] Excel: {excel_path}")
    print(f"[Output] CSV : {csv_path}")
    print(f"[Output] 总记录数: {len(df)}")
    print("=" * 60)
    print("提示：")
    print("1. 请检查 'host' 和 'country' 列是否为空，若缺失较多需后续补文献。")
    print(f"2. 原始 GenBank 缓存: {GB_CACHE}")
    print("=" * 60)


if __name__ == "__main__":
    run_pipeline()
