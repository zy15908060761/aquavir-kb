#!/usr/bin/env python3
"""
P0-6: ELink nucleotide accessions → PubMed IDs, fill sequence-evidence gap.
For 8,367 isolates with sequences, find linked PubMed references via NCBI ELink.
Creates new reference records and evidence_records linking isolates to literature.
"""
import sqlite3, json, urllib.request, urllib.parse, time, shutil, argparse
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent
DB = BASE / "crustacean_virus_core.db"
NCBI = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
RATE = 0.35
BATCH = 80

def stamp(): return datetime.now().strftime("%Y%m%d_%H%M%S")

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--limit", type=int, default=0)
    args = p.parse_args()

    conn = sqlite3.connect(str(DB))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")

    # Get isolates with genome_accession but no reference_id
    isolates = conn.execute("""
        SELECT vi.isolate_id, vi.accession, vi.genome_accession, vi.master_id,
               v.canonical_name, v.virus_family
        FROM viral_isolates vi
        JOIN virus_master v ON vi.master_id = v.master_id
        WHERE v.entry_type != 'non_target'
          AND vi.genome_accession IS NOT NULL AND vi.genome_accession != ''
          AND (vi.reference_id IS NULL)
        ORDER BY vi.master_id
    """).fetchall()

    # Also get isolates with sequences (has_sequence=1) that lack reference
    seq_isolates = conn.execute("""
        SELECT vi.isolate_id, vi.accession, vi.genome_accession, vi.master_id,
               v.canonical_name
        FROM viral_isolates vi
        JOIN virus_master v ON vi.master_id = v.master_id
        WHERE v.entry_type != 'non_target'
          AND vi.has_sequence = 1
          AND (vi.reference_id IS NULL)
          AND (vi.genome_accession IS NULL OR vi.genome_accession = '')
        ORDER BY vi.master_id
    """).fetchall()

    print(f"Isolates with genome_accession, no ref: {len(isolates)}")
    print(f"Isolates with sequence, no genome_acc, no ref: {len(seq_isolates)}")

    # Build accession list from genome_accession field
    all_accs = set()
    acc_to_isolates = {}

    for iso in isolates:
        gb = iso['genome_accession']
        if gb:
            # Handle multi-accession fields like "A: EU623082; B: EU623083"
            import re
            accs = re.findall(r'[A-Z]{1,2}\d{5,8}', gb)
            if not accs:
                accs = [gb.strip().split(':')[-1].strip()]
            for acc in accs:
                if len(acc) <= 15 and acc not in all_accs:
                    all_accs.add(acc)
                if acc not in acc_to_isolates:
                    acc_to_isolates[acc] = []
                acc_to_isolates[acc].append(dict(iso))

    # For seq-only isolates, try using their primary accession
    for iso in seq_isolates:
        acc = iso['accession']
        if acc and acc not in all_accs and len(acc) <= 15:
            all_accs.add(acc)
            if acc not in acc_to_isolates:
                acc_to_isolates[acc] = []
            acc_to_isolates[acc].append(dict(iso))

    acc_list = sorted(all_accs)
    if args.limit:
        acc_list = acc_list[:args.limit]
    print(f"Unique accessions to query: {len(acc_list)}")

    if not acc_list:
        print("Nothing to do.")
        conn.close()
        return

    # Phase 1: ELink — accession → PMID
    print("\n[Phase 1] ELink accession → PMID...")
    acc_to_pmids = {}
    for i in range(0, len(acc_list), BATCH):
        batch = acc_list[i:i+BATCH]
        ids = ",".join(batch)
        url = f"{NCBI}/elink.fcgi?dbfrom=nucleotide&db=pubmed&id={ids}&linkname=nucleotide_pubmed&retmode=json"
        time.sleep(RATE)
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                data = json.loads(r.read())
                for ls in data.get("linksets", []):
                    uid = str(ls.get("ids", [None])[0] or "")
                    pmids = [str(p) for p in ls.get("linksetdbs", [{}])[0].get("links", [])]
                    if uid and pmids:
                        acc_to_pmids[uid] = pmids
        except Exception as e:
            pass
        done = min(i+BATCH, len(acc_list))
        if (i//BATCH) % 10 == 0:
            print(f"  {done}/{len(acc_list)} → {len(acc_to_pmids)} linked")

    print(f"  Accessions with PubMed links: {len(acc_to_pmids)}")

    all_pmids = set()
    for pmids in acc_to_pmids.values():
        all_pmids.update(pmids)
    print(f"  Unique PMIDs: {len(all_pmids)}")

    if not all_pmids:
        print("No links found.")
        conn.close()
        return

    # Check existing PMIDs
    pmid_list = list(all_pmids)
    existing_pmids = {}
    for i in range(0, len(pmid_list), 500):
        batch = pmid_list[i:i+500]
        ph = ",".join("?" for _ in batch)
        refs = conn.execute(
            f"SELECT reference_id, pmid FROM ref_literatures WHERE pmid IN ({ph})", batch
        ).fetchall()
        for r in refs:
            existing_pmids[r['pmid']] = r['reference_id']

    new_pmids = [p for p in pmid_list if p not in existing_pmids]
    print(f"  Existing: {len(existing_pmids)}, New to fetch: {len(new_pmids)}")

    if args.dry_run:
        linked_isolates = sum(len(acc_to_isolates.get(a, [])) for a in acc_to_pmids)
        print(f"\n[DRY RUN] Would:")
        print(f"  - Fetch {len(new_pmids)} new PubMed references")
        print(f"  - Link ~{linked_isolates} isolates to references")
        print(f"  - Create evidence records for linked pairs")
        for acc in list(acc_to_pmids.keys())[:5]:
            isos = acc_to_isolates.get(acc, [])
            names = [i.get('canonical_name','?') for i in isos[:3]]
            print(f"    {acc}: {', '.join(names)} → {acc_to_pmids[acc]}")
        conn.close()
        return

    # Backup
    bp = BASE / "backups" / f"db_pre_elink_{stamp()}.db"
    bp.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(str(DB))
    c.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    c.close()
    shutil.copy2(str(DB), str(bp))
    print(f"\n[backup] {bp.name}")

    cur = conn.cursor()
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Phase 2: Fetch new PubMed references
    new_refs = {}
    if new_pmids:
        print(f"\n[Phase 2] Fetching {len(new_pmids)} new PubMed references...")
        import xml.etree.ElementTree as ET
        for i in range(0, len(new_pmids), 30):
            batch = new_pmids[i:i+30]
            url = f"{NCBI}/efetch.fcgi?db=pubmed&id={','.join(batch)}&retmode=xml&rettype=abstract"
            time.sleep(RATE)
            try:
                with urllib.request.urlopen(url, timeout=60) as r:
                    root = ET.fromstring(r.read())
                    for art in root.findall(".//PubmedArticle"):
                        med = art.find(".//MedlineCitation")
                        if med is None: continue
                        pm = med.findtext(".//PMID", "")
                        if not pm: continue
                        ai = med.find(".//Article")
                        title = "".join(ai.find(".//ArticleTitle").itertext()) if ai is not None and ai.find(".//ArticleTitle") is not None else ""
                        abs_text = " ".join("".join(a.itertext()) for a in art.findall(".//AbstractText"))
                        auths = []
                        if ai is not None:
                            for au in ai.findall(".//Author"):
                                ln = au.findtext("LastName", "") or ""
                                fn = au.findtext("ForeName", "") or ""
                                if ln: auths.append(f"{ln} {fn}" if fn else ln)
                        jn = ai.find(".//Journal/Title") if ai is not None else None
                        jn_text = jn.text if jn is not None and jn.text else ""
                        yr = ""
                        if ai is not None:
                            pd = ai.find(".//PubDate")
                            if pd is not None:
                                y = pd.findtext("Year", "")
                                if y: yr = y
                        doi = ""
                        if ai is not None:
                            for eid in ai.findall(".//ELocationID"):
                                if eid.get("EIdType") == "doi":
                                    doi = eid.text or ""
                        new_refs[pm] = {"pmid": pm, "title": title, "abstract": abs_text,
                                        "authors": "; ".join(auths[:10]), "journal": jn_text,
                                        "year": yr, "doi": doi}
            except Exception as e:
                pass
            if (i//30) % 10 == 0:
                print(f"  {min(i+30, len(new_pmids))}/{len(new_pmids)} → {len(new_refs)} fetched")

    # Insert new refs
    new_ref_id = {}
    for pmid, data in new_refs.items():
        try:
            cur.execute("""
                INSERT INTO ref_literatures (pmid, title, authors, journal, year, doi, abstract)
                VALUES (?,?,?,?,?,?,?)
            """, (pmid, data['title'], data['authors'], data['journal'],
                  data['year'], data['doi'], data['abstract']))
            if cur.lastrowid:
                new_ref_id[pmid] = cur.lastrowid
        except: pass
    conn.commit()
    print(f"  New references inserted: {len(new_ref_id)}")

    all_refs = {**existing_pmids, **new_ref_id}

    # Phase 3: Link isolates + create evidence
    print(f"\n[Phase 3] Linking isolates and creating evidence...")
    linked = 0
    ev_created = 0
    ev_batch = []

    for acc, pmids in acc_to_pmids.items():
        isolates_list = acc_to_isolates.get(acc, [])
        if not isolates_list or not pmids:
            continue

        ref_id = all_refs.get(pmids[0])
        if not ref_id:
            continue

        for iso in isolates_list:
            # Update isolate reference_id
            try:
                cur.execute(
                    "UPDATE viral_isolates SET reference_id=? WHERE isolate_id=? AND reference_id IS NULL",
                    (ref_id, iso['isolate_id']))
                if cur.rowcount: linked += 1
            except: pass

            # Create evidence for each PMID
            for pmid in pmids[:3]:
                rid = all_refs.get(pmid)
                if not rid: continue

                dup = conn.execute(
                    "SELECT 1 FROM evidence_records WHERE virus_master_id=? AND reference_id=? AND evidence_type='host_range'",
                    (iso['master_id'], rid)).fetchone()
                if dup: continue

                claim = f"NCBI ELink: GenBank {acc} linked to PubMed. PMID:{pmid}"
                ev_batch.append((
                    "host_range", iso['master_id'], None, iso['isolate_id'],
                    rid, None, claim, None, None, None, None,
                    "database_annotation", "ncbi_elink_accession_pubmed",
                    "medium", ts, ts
                ))
                if len(ev_batch) >= 500:
                    cur.executemany("""INSERT INTO evidence_records (
                        evidence_type,virus_master_id,host_id,isolate_id,reference_id,source_id,
                        claim,value_text,value_numeric_min,value_numeric_max,unit,
                        observation_type,extraction_method,evidence_strength,created_at,updated_at
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", ev_batch)
                    ev_created += len(ev_batch)
                    ev_batch = []

    if ev_batch:
        cur.executemany("""INSERT INTO evidence_records (
            evidence_type,virus_master_id,host_id,isolate_id,reference_id,source_id,
            claim,value_text,value_numeric_min,value_numeric_max,unit,
            observation_type,extraction_method,evidence_strength,created_at,updated_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", ev_batch)
        ev_created += len(ev_batch)

    conn.commit()

    print(f"\n[Done]")
    print(f"  New references: {len(new_ref_id)}")
    print(f"  Isolates linked: {linked}")
    print(f"  Evidence created: {ev_created}")

    total_ev = conn.execute("SELECT COUNT(*) FROM evidence_records").fetchone()[0]
    linked_iso = conn.execute("SELECT COUNT(*) FROM viral_isolates WHERE reference_id IS NOT NULL").fetchone()[0]
    print(f"  Total evidence: {total_ev:,}")
    print(f"  Total linked isolates: {linked_iso:,}")

    conn.close()

if __name__ == "__main__":
    main()
