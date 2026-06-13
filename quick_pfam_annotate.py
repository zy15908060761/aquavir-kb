"""
Quick Pfam annotation: Extract Pfam accession/name/GA from HMM file,
store as domain catalog. Useful as a lightweight functional annotation reference.
Runs in < 1 minute. Does NOT require hmmscan — just parses the HMM file.

Usage: python quick_pfam_annotate.py
"""

import sqlite3, sys, time
from pathlib import Path

DB = Path('F:/甲壳动物数据库/crustacean_virus_core.db')
HMM_PATH = 'F:/pfam_data/Pfam-A.hmm'

def parse_pfam_metadata(max_hmms=None):
    """Parse Pfam-A.hmm for metadata only (name, accession, GA threshold)."""
    hmms = []
    current = {}
    with open(HMM_PATH, 'r') as f:
        for line in f:
            if line.startswith('HMMER3'):
                if current.get('name'):
                    hmms.append(current)
                    if max_hmms and len(hmms) >= max_hmms:
                        break
                current = {}
            if line.startswith('NAME '):
                current['name'] = line.split(maxsplit=1)[1].strip()
            elif line.startswith('ACC '):
                current['accession'] = line.split(maxsplit=1)[1].strip()
            elif line.startswith('DESC '):
                current['desc'] = line.split(maxsplit=1)[1].strip()
            elif line.startswith('LENG '):
                current['length'] = int(line.split()[1])
            elif line.startswith('GA '):
                parts = line.split()
                if len(parts) >= 3:
                    current['ga_bits'] = float(parts[2].rstrip(';'))
    if current.get('name'):
        hmms.append(current)
    return hmms

def main():
    print('Parsing Pfam-A.hmm metadata...')
    t0 = time.time()
    hmms = parse_pfam_metadata()
    print(f'Parsed {len(hmms)} Pfam entries ({time.time()-t0:.0f}s)')

    # Show sample
    print('\nSample Pfam entries:')
    for h in hmms[:5]:
        print(f'  {h["accession"]}: {h["name"]} (L={h.get("length",0)}, GA={h.get("ga_bits",0)})')

    # Store as reference in a new table
    conn = sqlite3.connect(str(DB))
    c = conn.cursor()

    c.execute('''CREATE TABLE IF NOT EXISTS pfam_catalog (
        pfam_id INTEGER PRIMARY KEY AUTOINCREMENT,
        pfam_accession TEXT UNIQUE,
        pfam_name TEXT,
        description TEXT,
        model_length INTEGER,
        ga_threshold REAL,
        fetched_at TEXT DEFAULT CURRENT_TIMESTAMP
    )''')

    inserted = 0
    for h in hmms:
        try:
            c.execute('''INSERT OR IGNORE INTO pfam_catalog
                (pfam_accession, pfam_name, description, model_length, ga_threshold)
                VALUES (?, ?, ?, ?, ?)''',
                (h.get('accession', ''), h.get('name', ''), h.get('desc', '')[:500],
                 h.get('length', 0), h.get('ga_bits', 0.0)))
            inserted += 1
        except:
            pass

    conn.commit()
    print(f'\nInserted {inserted} Pfam families into pfam_catalog')
    c.execute('SELECT COUNT(*) FROM pfam_catalog')
    print(f'Total in catalog: {c.fetchone()[0]}')
    conn.close()

if __name__ == '__main__':
    main()
