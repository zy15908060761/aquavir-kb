#!/usr/bin/env python3
"""
P1-8: Search Europe PMC for new literature not yet in database.
For 1,826 aquatic invertebrate viruses, search EPMC for 2023-2026 papers.
"""
import sqlite3, json, urllib.request, urllib.parse, time, argparse
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent
DB = BASE / "crustacean_virus_core.db"
RATE = 0.3

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--limit", type=int, default=100, help="Max viruses to search")
    p.add_argument("--max-results", type=int, default=5, help="Results per virus")
    args = p.parse_args()

    conn = sqlite3.connect(str(DB))
    conn.row_factory = sqlite3.Row

    # Get viruses ordered by evidence scarcity (prioritize those with least evidence)
    viruses = conn.execute("""
        SELECT v.master_id, v.canonical_name, v.virus_family, v.host_phylum,
               COUNT(e.evidence_id) as ev_count
        FROM virus_master v
        LEFT JOIN evidence_records e ON v.master_id = e.virus_master_id
        WHERE v.entry_type != 'non_target'
          AND v.canonical_name NOT LIKE '0-9%'  -- skip numeric names
        GROUP BY v.master_id
        ORDER BY ev_count ASC
        LIMIT ?
    """, (args.limit,)).fetchall()

    print(f"Searching EPMC for {len(viruses)} viruses (prioritizing low-evidence)...")

    existing_pmids = set()
    for row in conn.execute("SELECT pmid FROM ref_literatures WHERE pmid IS NOT NULL AND pmid != ''"):
        existing_pmids.add(row['pmid'])

    new_papers = 0
    total_found = 0

    for idx, v in enumerate(viruses):
        # Build search query: species name + virus + (aquatic OR marine OR shrimp OR mollusk etc)
        name = v['canonical_name']
        # Clean the name for search
        name_clean = name.split('(')[0].strip()
        if len(name_clean) < 3:
            continue

        query = f'("{urllib.parse.quote(name_clean)}" AND virus) AND (FIRST_PDATE:[2023-01-01 TO 2026-12-31])'
        url = f"https://www.ebi.ac.uk/europepmc/webservices/rest/search?query={query}&format=json&pageSize={args.max_results}&sort=RELEVANCE"

        time.sleep(RATE)
        try:
            with urllib.request.urlopen(url, timeout=30) as r:
                data = json.loads(r.read())
                results = data.get("resultList", {}).get("result", [])

                for paper in results:
                    pmid = paper.get("pmid", "") or paper.get("id", "")
                    if pmid in existing_pmids:
                        continue

                    total_found += 1
                    print(f"  [{idx+1}/{len(viruses)}] {name_clean[:40]}: {paper.get('title','')[:80]}")

                    if not args.dry_run:
                        # Add to ref_literatures
                        try:
                            conn.execute("""
                                INSERT OR IGNORE INTO ref_literatures
                                    (pmid, title, authors, journal, year, doi, abstract)
                                VALUES (?,?,?,?,?,?,?)
                            """, (
                                pmid,
                                paper.get("title", ""),
                                paper.get("authorString", ""),
                                paper.get("journalTitle", ""),
                                paper.get("pubYear", ""),
                                paper.get("doi", ""),
                                (paper.get("abstractText", "") or "")[:2000]
                            ))
                            new_papers += 1
                            existing_pmids.add(pmid)
                        except:
                            pass
        except Exception as e:
            pass

        if (idx+1) % 20 == 0:
            conn.commit()
            print(f"  Progress: {idx+1}/{len(viruses)}, new papers: {new_papers}, total hits: {total_found}")

    conn.commit()

    print(f"\n[Done]")
    print(f"  Viruses searched: {len(viruses)}")
    print(f"  New papers found: {new_papers}")
    print(f"  Total EPMC hits: {total_found}")

    if not args.dry_run and new_papers > 0:
        print(f"  New refs in DB: {conn.execute('SELECT COUNT(*) FROM ref_literatures').fetchone()[0]:,}")

    conn.close()

if __name__ == "__main__":
    main()
