"""Backfill geography data via NCBI EFetch GenBank XML."""
import sqlite3, urllib.request, json, time, re
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent
DB = BASE / "crustacean_virus_core.db"
RATE = 0.35

def main():
    conn = sqlite3.connect(str(DB))
    conn.execute("PRAGMA journal_mode=WAL")
    cur = conn.cursor()

    # Find isolates in sample_collections without country
    cur.execute("""
        SELECT sc.collection_id, vi.accession
        FROM sample_collections sc
        JOIN infection_records ir ON sc.collection_id = ir.collection_id
        JOIN viral_isolates vi ON ir.isolate_id = vi.isolate_id
        WHERE (sc.country IS NULL OR sc.country = '')
        AND vi.accession IS NOT NULL
        LIMIT 1000
    """)
    missing = cur.fetchall()
    print(f"Geography backfill: {len(missing)} sample_collections without country")

    if not missing:
        print("  No missing geography data found")
        return

    updated = 0
    batch_size = 20
    for i in range(0, len(missing), batch_size):
        batch = missing[i:i+batch_size]
        terms = ' OR '.join(f'{coll[1].split(".")[0]}[Accession]' for coll in batch)

        # ESearch for UIDs
        try:
            url = f'https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?db=nucleotide&term={urllib.parse.quote(terms)}&retmax={batch_size}&retmode=json'
            with urllib.request.urlopen(url, timeout=30) as r:
                uids = json.loads(r.read()).get('esearchresult',{}).get('idlist',[])
        except:
            time.sleep(RATE)
            continue
        time.sleep(RATE)

        if not uids:
            continue

        # EFetch GenBank XML
        try:
            uid_str = ','.join(uids[:30])
            url = f'https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=nucleotide&id={uid_str}&rettype=gb&retmode=xml'
            with urllib.request.urlopen(url, timeout=120) as r:
                xml_data = r.read().decode('utf-8')
        except:
            time.sleep(RATE)
            continue
        time.sleep(RATE)

        # Parse country from GBSeq_feature-table qualifiers
        # Pattern: /country="XXX" in source feature
        for coll_id, accession in batch:
            acc_base = accession.split('.')[0]
            # Find country for this accession in XML
            pattern = re.compile(
                rf'<GBSeq[^>]*>.*?<GBSeq_accession-version>{re.escape(accession)}</GBSeq_accession-version>.*?/country="([^"]+)"',
                re.DOTALL
            )
            m = pattern.search(xml_data)
            if m:
                country = m.group(1)
                # Also try to find lat_lon
                ll_pattern = re.compile(
                    rf'<GBSeq_accession-version>{re.escape(accession)}</GBSeq_accession-version>.*?/lat_lon="([^"]+)"',
                    re.DOTALL
                )
                ll_m = ll_pattern.search(xml_data)
                lat, lon = None, None
                if ll_m:
                    lat_lon = ll_m.group(1)
                    parts = lat_lon.replace('N','').replace('S','-').replace('E','').replace('W','-').split()
                    if len(parts) >= 2:
                        try:
                            lat, lon = float(parts[0]), float(parts[1])
                        except: pass

                try:
                    cur.execute("""
                        UPDATE sample_collections SET country = ?, latitude = COALESCE(latitude, ?),
                            longitude = COALESCE(longitude, ?)
                        WHERE collection_id = ?
                    """, (country, lat, lon, coll_id))
                    updated += 1
                except: pass

        if (i//batch_size + 1) % 10 == 0:
            conn.commit()
            print(f"  {min(i+batch_size, len(missing))}/{len(missing)}: +{updated} updated")

    conn.commit()

    # Final count
    cur.execute("SELECT COUNT(*) FROM sample_collections WHERE country IS NOT NULL AND country != ''")
    has_country = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM sample_collections")
    total = cur.fetchone()[0]
    print(f"Geography backfill done: +{updated} updated")
    print(f"With country: {has_country}/{total} ({round(has_country/total*100,1)}%)")
    conn.close()

if __name__ == "__main__":
    main()
