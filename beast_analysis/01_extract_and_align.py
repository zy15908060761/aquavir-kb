#!/usr/bin/env python3
"""从数据库提取 Dicistroviridae RdRp 蛋白序列，过滤，写带日期的 FASTA"""
import sqlite3, re, os
from datetime import datetime

DB  = "F:/水生无脊椎动物数据库/crustacean_virus_core.db"
OUT = "F:/水生无脊椎动物数据库/beast_analysis"

MIN_AA = 1000  # 最短氨基酸长度（筛掉碎片）

def parse_date(raw):
    """尽可能解析各种日期格式，返回datetime或None"""
    if not raw or not raw.strip():
        return None
    raw = raw.strip()
    # 2024-08   → 月份取中间或默认
    if re.match(r'^\d{4}-\d{2}$', raw):
        return datetime.strptime(raw, '%Y-%m')
    # 01-OCT-2013
    for fmt in ['%d-%b-%Y', '%d-%B-%Y', '%d-%m-%Y', '%d/%m/%Y',
                '%Y-%m-%d', '%Y/%m/%d', '%b-%Y', '%B-%Y', '%Y']:
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    # Apr-2021 → 默认15号
    if re.match(r'^[A-Za-z]{3}-\d{4}$', raw):
        return datetime.strptime(f"15-{raw}", '%d-%b-%Y')
    # 只匹配年份
    m = re.match(r'^(\d{4})$', raw)
    if m:
        return datetime(year=int(m.group(1)), month=6, day=15)  # 年份取年中
    print(f"  [WARN] Cannot parse date: {raw}")
    return None

def main():
    db = sqlite3.connect(DB)

    cur = db.execute('''
    SELECT sm.accession, sm.collection_date, sm.host_name,
           vi.virus_name, vi.taxon_family, vp.translation, vp.aa_length
    FROM sample_metadata sm
    JOIN viral_isolates vi ON sm.isolate_id = vi.isolate_id
    JOIN viral_proteins vp ON vi.isolate_id = vp.isolate_id
    WHERE sm.collection_date IS NOT NULL AND sm.collection_date != ''
      AND vp.is_rdrp = 1
      AND vi.taxon_family = 'Dicistroviridae'
    ORDER BY sm.collection_date
    ''')

    records = []
    skipped = 0
    for acc, raw_date, host, virus, family, seq, aa_len in cur.fetchall():
        dt = parse_date(raw_date)
        if dt is None:
            skipped += 1
            continue
        if aa_len is None or aa_len < MIN_AA:
            skipped += 1
            continue
        if not seq or len(seq) < MIN_AA:
            skipped += 1
            continue

        dec_year = dt.year + (dt.timetuple().tm_yday - 1) / 365.0
        # 清理名称:替换空格和特殊字符
        safe_acc  = acc.replace(' ', '_')
        safe_virus = (virus or 'Unknown').replace(' ', '_').replace('/', '_')[:30]
        safe_host  = (host or 'Unknown').replace(' ', '_').replace('/', '_')[:20]
        # tip label格式: acc|virus|host|date
        tip_label = f"{safe_acc}|{safe_virus}|{safe_host}|{dec_year:.3f}"

        records.append({
            'tip_label': tip_label,
            'accession': acc,
            'date': dt,
            'dec_year': dec_year,
            'host': host or 'Unknown',
            'virus': virus or 'Unknown',
            'family': family,
            'sequence': seq,
            'aa_len': aa_len,
        })

    print(f"Parsed {len(records)} records, skipped {skipped} (fragments / bad dates)")

    # --- 写 FASTA ---
    fasta_path = os.path.join(OUT, "dicistro_rdrp.fasta")
    with open(fasta_path, 'w') as f:
        for r in records:
            f.write(f">{r['tip_label']}\n")
            # 每行60字符
            seq = r['sequence']
            for i in range(0, len(seq), 60):
                f.write(seq[i:i+60] + '\n')
    print(f"FASTA written: {fasta_path} ({len(records)} sequences)")

    # --- 写元数据 ---
    meta_path = os.path.join(OUT, "metadata.tsv")
    with open(meta_path, 'w') as f:
        f.write("tip_label\taccession\tdate\tdec_year\thost\tvirus\tfamily\taa_len\n")
        for r in records:
            f.write(f"{r['tip_label']}\t{r['accession']}\t{r['date'].strftime('%Y-%m-%d')}\t"
                    f"{r['dec_year']:.3f}\t{r['host']}\t{r['virus']}\t{r['family']}\t{r['aa_len']}\n")
    print(f"Metadata written: {meta_path}")

    # --- 报告时间跨度 ---
    years = [r['dec_year'] for r in records]
    print(f"\nDate range: {min(years):.1f} – {max(years):.1f} (span: {max(years)-min(years):.1f} years)")

    # 检查序列长度一致性
    lens = [r['aa_len'] for r in records]
    print(f"Sequence length: min={min(lens)}, max={max(lens)}, median={sorted(lens)[len(lens)//2]}")

    db.close()

if __name__ == '__main__':
    main()
