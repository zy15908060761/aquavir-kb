#!/usr/bin/env python3
"""
P1-4+5: Enrich reference metadata from CrossRef (citations) and PubMed (MeSH).
- CrossRef: Get citation counts, journal metadata for 8,198 DOIs
- PubMed MeSH: Get MeSH terms and publication types for 8,441 PMIDs
"""
import sqlite3, json, urllib.request, time, argparse, xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent
DB = BASE / "crustacean_virus_core.db"
RATE = 0.2  # CrossRef allows ~50/sec with polite pool

def stamp(): return datetime.now().strftime("%Y%m%d_%H%M%S")

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--skip-crossref", action="store_true")
    p.add_argument("--skip-mesh", action="store_true")
    args = p.parse_args()

    conn = sqlite3.connect(str(DB))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")

    # ── CROSSREF ──
    if not args.skip_crossref:
        print("="*60)
        print("CrossRef Citation Enrichment")
        print("="*60)

        # Ensure table exists first
        conn.execute("""
            CREATE TABLE IF NOT EXISTS ref_citation_metadata (
                reference_id INTEGER PRIMARY KEY,
                citation_count INTEGER,
                journal_impact TEXT,
                publication_type TEXT,
                mesh_terms TEXT,
                enriched_at TEXT,
                FOREIGN KEY (reference_id) REFERENCES ref_literatures(reference_id)
            )
        """)
        conn.commit()

        dois = conn.execute("""
            SELECT r.reference_id, r.doi FROM ref_literatures r
            WHERE r.doi IS NOT NULL AND r.doi != ''
              AND r.reference_id NOT IN (
                  SELECT rcm.reference_id FROM ref_citation_metadata rcm
                  WHERE rcm.citation_count IS NOT NULL
              )
            ORDER BY r.reference_id
        """).fetchall()

        if args.limit:
            dois = dois[:args.limit]

        print(f"DOIs to query: {len(dois)}")

        if not args.dry_run:
            cur = conn.cursor()
            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            enriched = 0

            for i, row in enumerate(dois):
                doi = row['doi'].strip()
                if not doi or doi == 'null':
                    continue

                # CrossRef API
                url = f"https://api.crossref.org/works/{urllib.request.quote(doi, safe='')}"
                time.sleep(RATE)
                try:
                    req = urllib.request.Request(url, headers={"User-Agent": "AquaVir-KB/1.0 (mailto:research@example.com)"})
                    with urllib.request.urlopen(req, timeout=30) as r:
                        data = json.loads(r.read())
                        msg = data.get("message", {})
                        cites = msg.get("is-referenced-by-count", 0)
                        journal = msg.get("container-title", [""])[0] if msg.get("container-title") else ""
                        pub_type = msg.get("type", "")

                        cur.execute("""
                            INSERT OR REPLACE INTO ref_citation_metadata
                                (reference_id, citation_count, journal_impact, publication_type, enriched_at)
                            VALUES (?, ?, ?, ?, ?)
                        """, (row['reference_id'], int(cites), journal, pub_type, ts))
                        enriched += 1
                except Exception as e:
                    pass

                if enriched > 0 and enriched % 500 == 0:
                    conn.commit()
                    print(f"  {enriched:,}/{len(dois)} enriched...")

            conn.commit()
            print(f"  CrossRef enriched: {enriched:,}")

            # Update evidence quality based on citation count
            high_cite = cur.execute("""
                UPDATE evidence_records
                SET evidence_strength = 'high', updated_at = ?
                WHERE evidence_strength = 'medium'
                  AND reference_id IN (
                      SELECT reference_id FROM ref_citation_metadata
                      WHERE citation_count >= 50
                  )
            """, (ts,)).rowcount
            conn.commit()
            print(f"  Evidence upgraded (citation≥50): {high_cite:,}")
        else:
            print(f"  [DRY RUN] Would query {len(dois)} DOIs")

    # ── PUBMED MESH ──
    if not args.skip_mesh:
        print("\n" + "="*60)
        print("PubMed MeSH Enrichment")
        print("="*60)

        # Ensure table exists
        conn.execute("""
            CREATE TABLE IF NOT EXISTS ref_citation_metadata (
                reference_id INTEGER PRIMARY KEY,
                citation_count INTEGER,
                journal_impact TEXT,
                publication_type TEXT,
                mesh_terms TEXT,
                enriched_at TEXT,
                FOREIGN KEY (reference_id) REFERENCES ref_literatures(reference_id)
            )
        """)
        conn.commit()

        pmids = conn.execute("""
            SELECT r.reference_id, r.pmid FROM ref_literatures r
            WHERE r.pmid IS NOT NULL AND r.pmid != ''
              AND r.reference_id NOT IN (
                  SELECT rcm.reference_id FROM ref_citation_metadata rcm
                  WHERE rcm.mesh_terms IS NOT NULL AND rcm.mesh_terms != ''
              )
            ORDER BY r.reference_id
        """).fetchall()

        if args.limit: pmids = pmids[:args.limit]
        print(f"PMIDs to query: {len(pmids)}")

        if not args.dry_run:
            cur = conn.cursor()
            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            mesh_enriched = 0

            for i in range(0, len(pmids), 50):
                batch = pmids[i:i+50]
                uid_str = ",".join(r['pmid'] for r in batch)
                url = f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=pubmed&id={uid_str}&retmode=xml&rettype=medline"
                time.sleep(RATE)

                try:
                    with urllib.request.urlopen(url, timeout=60) as r:
                        root = ET.fromstring(r.read())
                        for art in root.findall(".//PubmedArticle"):
                            med = art.find(".//MedlineCitation")
                            if med is None: continue
                            pmid_el = med.findtext(".//PMID", "")
                            if not pmid_el: continue

                            # Find reference_id
                            ref_id = None
                            for r2 in batch:
                                if r2['pmid'] == pmid_el:
                                    ref_id = r2['reference_id']
                                    break
                            if not ref_id: continue

                            # Get MeSH headings
                            mesh_terms = []
                            for mh in med.findall(".//MeshHeading"):
                                desc = mh.findtext("DescriptorName", "")
                                if desc:
                                    qualifiers = [q.text for q in mh.findall("QualifierName") if q.text]
                                    mesh_terms.append(f"{desc}/{','.join(qualifiers)}" if qualifiers else desc)

                            # Get publication type
                            pub_types = []
                            for pt in art.findall(".//PublicationType"):
                                if pt.text: pub_types.append(pt.text)

                            mesh_str = "; ".join(mesh_terms[:20])
                            pt_str = "; ".join(pub_types[:5])

                            if mesh_str or pt_str:
                                cur.execute("""
                                    INSERT OR REPLACE INTO ref_citation_metadata
                                        (reference_id, mesh_terms, publication_type, enriched_at)
                                    VALUES (?, ?, COALESCE(
                                        (SELECT publication_type FROM ref_citation_metadata WHERE reference_id=?),
                                        ?
                                    ), ?)
                                """, (ref_id, mesh_str, ref_id, pt_str, ts))
                                mesh_enriched += 1

                except Exception as e:
                    pass

                if i > 0 and i % 1000 == 0:
                    conn.commit()
                    print(f"  {min(i+50, len(pmids)):,}/{len(pmids):,} processed, {mesh_enriched:,} with MeSH...")

            conn.commit()
            print(f"  MeSH enriched: {mesh_enriched:,} refs")

            # Upgrade: evidence from "Journal Article" (original research) > "Review" > other
            research = cur.execute("""
                UPDATE evidence_records
                SET evidence_strength = 'high', updated_at = ?
                WHERE evidence_strength = 'medium'
                  AND reference_id IN (
                      SELECT reference_id FROM ref_citation_metadata
                      WHERE publication_type LIKE '%Journal Article%'
                        AND citation_count >= 10
                  )
            """, (ts,)).rowcount
            print(f"  Evidence upgraded (Journal Article + cites≥10): {research:,}")
        else:
            print(f"  [DRY RUN] Would query {len(pmids)} PMIDs")

    # Final stats
    if not args.dry_run:
        print("\n" + "="*60)
        q = conn.execute("SELECT COUNT(*) FROM ref_citation_metadata WHERE citation_count IS NOT NULL").fetchone()[0]
        m = conn.execute("SELECT COUNT(*) FROM ref_citation_metadata WHERE mesh_terms IS NOT NULL AND mesh_terms != ''").fetchone()[0]
        avg = conn.execute("SELECT AVG(citation_count) FROM ref_citation_metadata WHERE citation_count IS NOT NULL").fetchone()[0]
        print(f"  Refs with citation counts: {q:,}")
        print(f"  Refs with MeSH terms: {m:,}")
        print(f"  Average citations: {avg:.1f}")

    conn.close()
    print("\nDone.")

if __name__ == "__main__":
    main()
