#!/usr/bin/env python3
"""
P0 Phase 2: Extract references from GenBank records for ICTV VMR entries.

Strategy (prioritized):
  1. Fetch GenBank XML for each accession (efetch nucleotide)
  2. Extract GBReference: title, authors, journal, PMID
  3. For refs with PMID → link to PubMed
  4. For refs without PMID → create reference from GenBank data
  5. Create evidence records from all references

This maximizes coverage since every GenBank record has at least a "Direct Submission"
reference.
"""

from __future__ import annotations

import argparse
import re
import shutil
import sqlite3
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from typing import Optional

APP_DIR = Path(__file__).resolve().parent
DB_PATH = APP_DIR / "crustacean_virus_core.db"
BACKUPS_DIR = APP_DIR / "backups"

NCBI_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
NCBI_RATE = 0.35
BATCH_EFETCH = 30  # accessions per nucleotide efetch


def stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def backup_database() -> Path:
    BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
    ts = stamp()
    bp = BACKUPS_DIR / f"crustacean_virus_core_pre_p2_{ts}.db"
    c = sqlite3.connect(str(DB_PATH))
    c.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    c.close()
    shutil.copy2(str(DB_PATH), str(bp))
    for s in (".db-wal", ".db-shm"):
        src = Path(str(DB_PATH) + s)
        if src.exists():
            shutil.copy2(str(src), str(bp.parent / (bp.stem + s)))
    print(f"[backup] {bp.name}")
    return bp


def ncbi_req(endpoint: str, params: dict) -> Optional[bytes]:
    url = f"{NCBI_BASE}/{endpoint}?{urllib.parse.urlencode(params)}"
    time.sleep(NCBI_RATE)
    try:
        with urllib.request.urlopen(url, timeout=120) as r:
            return r.read()
    except Exception as e:
        print(f"  [warn] {endpoint}: {e}")
        return None


def extract_genbank_refs(xml_data: bytes) -> list[dict]:
    """Extract GBReference entries from GenBank XML."""
    refs = []
    try:
        root = ET.fromstring(xml_data)
        for ref in root.findall('.//GBReference'):
            title = ref.findtext('GBReference_title', '') or ''
            journal = ref.findtext('GBReference_journal', '') or ''
            pmid = ref.findtext('GBReference_pubmed', '') or ''

            authors = []
            authors_el = ref.find('GBReference_authors')
            if authors_el is not None:
                for au in authors_el.findall('GBAuthor'):
                    if au.text:
                        authors.append(au.text)

            # Skip empty/placeholder refs
            if not title and not journal and not pmid and not authors:
                continue
            if title in ('Direct Submission', 'Submitted') and not pmid:
                # Still keep — it's valid provenance
                pass

            refs.append({
                'title': title,
                'authors': '; '.join(authors[:10]),
                'journal': journal,
                'pmid': pmid,
            })
    except ET.ParseError:
        pass
    return refs


def search_pubmed_for_species(species: str) -> list[str]:
    """Fallback: search PubMed by species name."""
    clean = re.sub(r'[^\w\s-]', '', species).strip()
    query = f'"{clean}"[Title/Abstract] AND virus[Title/Abstract]'
    data = ncbi_req("esearch.fcgi", {
        "db": "pubmed", "term": query, "retmax": "3",
        "retmode": "json", "sort": "relevance",
    })
    if not data:
        return []
    try:
        import json
        return json.loads(data).get("esearchresult", {}).get("idlist", [])
    except (json.JSONDecodeError, KeyError):
        return []


def efetch_pubmed(pmids: list[str]) -> dict[str, dict]:
    """EFetch PubMed summaries for PMIDs."""
    import json
    result: dict[str, dict] = {}
    for i in range(0, len(pmids), 30):
        batch = pmids[i:i+30]
        data = ncbi_req("efetch.fcgi", {
            "db": "pubmed", "id": ",".join(batch),
            "retmode": "xml", "rettype": "abstract",
        })
        if not data:
            continue
        try:
            root = ET.fromstring(data)
            for art in root.findall(".//PubmedArticle"):
                med = art.find(".//MedlineCitation")
                if med is None:
                    continue
                pm = med.findtext(".//PMID", "")
                if not pm:
                    continue
                ai = med.find(".//Article")
                title = ""
                abstract = ""
                authors = ""
                journal = ""
                year = ""
                doi = ""
                if ai is not None:
                    t = ai.find(".//ArticleTitle")
                    title = "".join(t.itertext()) if t is not None else ""
                    abs_parts = []
                    for a in ai.findall(".//AbstractText"):
                        lbl = a.get("Label", "")
                        txt = "".join(a.itertext())
                        abs_parts.append(f"{lbl}: {txt}" if lbl else txt)
                    abstract = " ".join(abs_parts)
                    auths = []
                    for au in ai.findall(".//Author"):
                        ln = au.findtext("LastName", "") or ""
                        fn = au.findtext("ForeName", "") or ""
                        if ln:
                            auths.append(f"{ln} {fn}" if fn else ln)
                    authors = "; ".join(auths[:10])
                    jn = ai.find(".//Journal/Title")
                    if jn is not None and jn.text:
                        journal = jn.text
                    pd = ai.find(".//PubDate")
                    if pd is not None:
                        y = pd.findtext("Year", "")
                        if y:
                            year = y
                    for eid in ai.findall(".//ELocationID"):
                        if eid.get("EIdType") == "doi":
                            doi = eid.text or ""
                result[pm] = {
                    "pmid": pm, "title": title, "abstract": abstract,
                    "authors": authors, "journal": journal, "year": year, "doi": doi,
                }
        except ET.ParseError:
            continue
    return result


def generate_claim(species: str, ref_title: str, ref_journal: str, pmid: str) -> str:
    """Generate an evidence claim from a reference."""
    pmid_str = f" PMID:{pmid}" if pmid else ""
    if ref_title and ref_title not in ("Direct Submission", "Submitted"):
        return f"GenBank reference: {ref_title[:400]}. {ref_journal[:200]}{pmid_str}"
    elif ref_journal:
        return f"GenBank submission: {ref_journal[:400]}{pmid_str}"
    else:
        return f"GenBank reference for {species}{pmid_str}"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--start-from", type=int, default=0)
    args = parser.parse_args()

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=120000")

    # Get aquatic ICTV VMR viruses with GenBank accessions, no evidence
    # Join via canonical_name = i.species (post-Phase1 name resolution)
    rows1 = conn.execute("""
        SELECT v.master_id, v.canonical_name, v.virus_family,
               vi.isolate_id, vi.accession as vmr_isolate,
               i.species, i.genbank_accession, i.virus_name
        FROM virus_master v
        JOIN viral_isolates vi ON v.master_id = vi.master_id
        JOIN ictv_vmr i ON v.canonical_name = i.species
        WHERE v.entry_type = 'ictv_vmr'
          AND i.genbank_accession IS NOT NULL AND i.genbank_accession != ''
          AND LENGTH(i.genbank_accession) <= 20
          AND NOT EXISTS (SELECT 1 FROM evidence_records e WHERE e.virus_master_id=v.master_id)
        ORDER BY v.master_id
    """).fetchall()

    # Also include entries with numeric canonical_name (conflict cases)
    rows2 = conn.execute("""
        SELECT v.master_id, v.canonical_name, v.virus_family,
               vi.isolate_id, vi.accession as vmr_isolate,
               i.species, i.genbank_accession, i.virus_name
        FROM virus_master v
        JOIN viral_isolates vi ON v.master_id = vi.master_id
        JOIN ictv_vmr i ON CAST(v.canonical_name AS INTEGER) = i.vmr_id
        WHERE v.entry_type = 'ictv_vmr'
          AND i.genbank_accession IS NOT NULL AND i.genbank_accession != ''
          AND LENGTH(i.genbank_accession) <= 20
          AND NOT EXISTS (SELECT 1 FROM evidence_records e WHERE e.virus_master_id=v.master_id)
        ORDER BY v.master_id
    """).fetchall()

    # Deduplicate
    seen_mid = set()
    all_rows = []
    for r in list(rows1) + list(rows2):
        if r["master_id"] not in seen_mid:
            seen_mid.add(r["master_id"])
            all_rows.append(r)

    print(f"Target viruses (no evidence, valid GenBank acc): {len(all_rows)}")

    if args.start_from:
        all_rows = all_rows[args.start_from:]
    if args.limit:
        all_rows = all_rows[:args.limit]
    print(f"Processing: {len(all_rows)}")

    if not all_rows:
        print("Nothing to do.")
        conn.close()
        return

    # Build accession → virus mapping
    # Extract first valid GenBank accession from each entry
    acc_to_virus: dict[str, list[dict]] = {}
    for r in all_rows:
        acc_raw = r["genbank_accession"]
        # Parse accessions (handle "A: EU623082; B: EU623083")
        accs = re.findall(r'[A-Z]{1,2}\d{5,8}', acc_raw)
        if not accs:
            accs = [acc_raw.split(';')[0].strip().split(':')[-1].strip()]
        for acc in accs:
            if len(acc) <= 15:
                if acc not in acc_to_virus:
                    acc_to_virus[acc] = []
                acc_to_virus[acc].append(dict(r))

    unique_accs = list(acc_to_virus.keys())
    print(f"Unique GenBank accessions: {len(unique_accs)}")

    if not unique_accs:
        print("No valid accessions found.")
        conn.close()
        return

    # Phase 2A: Fetch GenBank records for references
    print(f"\n[Phase 2A] Fetching GenBank references for {len(unique_accs)} accessions...")
    acc_refs: dict[str, list[dict]] = {}  # accession → [GBReference]
    all_pmids_found = set()
    accs_no_ref = 0

    for i in range(0, len(unique_accs), BATCH_EFETCH):
        batch = unique_accs[i:i+BATCH_EFETCH]
        ids = ",".join(batch)
        data = ncbi_req("efetch.fcgi", {
            "db": "nucleotide", "id": ids,
            "rettype": "gb", "retmode": "xml",
        })
        if not data:
            # Try individually
            for acc in batch:
                d2 = ncbi_req("efetch.fcgi", {
                    "db": "nucleotide", "id": acc,
                    "rettype": "gb", "retmode": "xml",
                })
                if d2:
                    refs = extract_genbank_refs(d2)
                    if refs:
                        acc_refs[acc] = refs
                        for r in refs:
                            if r["pmid"]:
                                all_pmids_found.add(r["pmid"])
                    else:
                        accs_no_ref += 1
            continue

        # Parse per-accession refs from batch XML
        # GenBank XML batch returns GBSet with multiple GBSeq entries
        root = ET.fromstring(data)
        for gbseq in root.findall('.//GBSeq'):
            # Find the accession for this GBSeq
            acc_el = gbseq.find('GBSeq_primary-accession')
            if acc_el is None:
                acc_el = gbseq.find('GBSeq_accession-version')
            if acc_el is None:
                continue
            acc = acc_el.text.split('.')[0] if acc_el.text else None
            if not acc:
                continue

            # Extract references from this GBSeq
            refs = extract_genbank_refs(ET.tostring(gbseq, 'utf-8'))
            if refs:
                if acc not in acc_refs:
                    acc_refs[acc] = refs
                else:
                    acc_refs[acc].extend(refs)
                for r in refs:
                    if r["pmid"]:
                        all_pmids_found.add(r["pmid"])
            else:
                accs_no_ref += 1

        done = min(i+BATCH_EFETCH, len(unique_accs))
        print(f"  genbank: {done}/{len(unique_accs)} → {len(acc_refs)} with refs, {len(all_pmids_found)} PMIDs")

    print(f"\n  Accs with references: {len(acc_refs)}/{len(unique_accs)}")
    print(f"  Accs without references: {accs_no_ref}")
    print(f"  Unique PMIDs from GenBank: {len(all_pmids_found)}")

    # Phase 2B: PubMed fallback for viruses with no GenBank refs
    missed_viruses = []
    for r in all_rows:
        accs = re.findall(r'[A-Z]{1,2}\d{5,8}', r["genbank_accession"])
        has_ref = any(a in acc_refs and acc_refs[a] for a in accs)
        if not has_ref:
            missed_viruses.append(r)

    print(f"\n  Viruses still without references: {len(missed_viruses)}")

    pubmed_fallback_pmids = set()
    if missed_viruses:
        print(f"\n[Phase 2B] PubMed fallback for {len(missed_viruses)} viruses...")
        for idx, r in enumerate(missed_viruses):
            species = r["species"] or r["virus_name"] or r["canonical_name"]
            pmids = search_pubmed_for_species(species)
            if pmids:
                # Store result — we'll handle later
                acc = r["genbank_accession"].split(';')[0].strip().split(':')[-1].strip()
                if acc not in acc_refs:
                    acc_refs[acc] = [{"title": "PubMed search", "journal": "", "pmid": p, "authors": ""} for p in pmids]
                for p in pmids:
                    pubmed_fallback_pmids.add(p)
            if (idx+1) % 50 == 0:
                print(f"  pubmed search: {idx+1}/{len(missed_viruses)} → {len(pubmed_fallback_pmids)} PMIDs")
        print(f"  PubMed fallback PMIDs: {len(pubmed_fallback_pmids)}")

    # Collect all PMIDs
    all_pmids = all_pmids_found | pubmed_fallback_pmids

    # Phase 2C: Fetch PubMed metadata for PMIDs
    existing_map: dict[str, int] = {}  # pmid → reference_id
    pmid_list = list(all_pmids)

    if pmid_list:
        for i in range(0, len(pmid_list), 500):
            batch = pmid_list[i:i+500]
            ph = ",".join("?" for _ in batch)
            refs = conn.execute(
                f"SELECT reference_id, pmid FROM ref_literatures WHERE pmid IN ({ph})", batch
            ).fetchall()
            for r in refs:
                existing_map[r["pmid"]] = r["reference_id"]

    new_pmids = [p for p in pmid_list if p not in existing_map]
    print(f"\n  PMIDs already in DB: {len(existing_map)}, New: {len(new_pmids)}")

    pubmed_data = {}
    if new_pmids:
        print(f"\n[Phase 2C] Fetching {len(new_pmids)} new PubMed references...")
        pubmed_data = efetch_pubmed(new_pmids)

    if args.dry_run:
        # Count expected evidence
        evidence_est = 0
        refs_new = len(new_pmids)
        for acc, refs in acc_refs.items():
            viruses = acc_to_virus.get(acc, [])
            evidence_est += len(viruses) * min(len(refs), 3)
        print(f"\n[DRY RUN] Would:")
        print(f"  - Insert {refs_new} PubMed references")
        print(f"  - Insert ~{sum(1 for acc, refs in acc_refs.items() if not any(r['pmid'] for r in refs))} non-PubMed (GenBank submission) references")
        print(f"  - Create ~{evidence_est} evidence records")
        for acc, refs in list(acc_refs.items())[:5]:
            viruses = acc_to_virus.get(acc, [])
            names = [v.get('species', v['canonical_name']) for v in viruses]
            print(f"    {acc} ({', '.join(names[:2])}) → {len(refs)} refs")
        conn.close()
        return

    # ── Apply writes ──
    backup_database()
    cur = conn.cursor()

    # Insert new PubMed references
    new_ref_id: dict[str, int] = {}
    for pmid, data in pubmed_data.items():
        try:
            cur.execute("""
                INSERT OR IGNORE INTO ref_literatures (pmid, title, authors, journal, year, doi, abstract)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (pmid, data["title"], data["authors"], data["journal"],
                  data["year"], data["doi"], data["abstract"]))
            if cur.lastrowid:
                new_ref_id[pmid] = cur.lastrowid
        except:
            pass

    # Re-fetch inserted IDs for OR IGNORE cases
    for i in range(0, len(new_pmids), 500):
        batch = new_pmids[i:i+500]
        ph = ",".join("?" for _ in batch)
        refs = conn.execute(
            f"SELECT reference_id, pmid FROM ref_literatures WHERE pmid IN ({ph})", batch
        ).fetchall()
        for r in refs:
            if r["pmid"] not in existing_map:
                new_ref_id[r["pmid"]] = r["reference_id"]

    all_ref_map = {**existing_map, **new_ref_id}
    print(f"\n  PubMed refs inserted: {len(new_ref_id)}")

    # Insert GenBank submission references (no PMID)
    gb_submission_refs = 0
    for acc, refs in acc_refs.items():
        for ref in refs:
            if ref["pmid"]:
                continue  # Already handled via PubMed
            # Create a reference from GenBank data
            title = ref["title"]
            if not title or title in ("Direct Submission", "Submitted"):
                title = f"GenBank submission for {acc}"
            try:
                cur.execute("""
                    INSERT INTO ref_literatures (pmid, title, authors, journal)
                    VALUES (NULL, ?, ?, ?)
                """, (title, ref["authors"], ref["journal"]))
                ref["_ref_id"] = cur.lastrowid
                gb_submission_refs += 1
            except:
                pass
    print(f"  GenBank submission refs inserted: {gb_submission_refs}")

    conn.commit()

    # Create evidence records
    print(f"\n[Phase 2D] Creating evidence records...")
    evidence_created = 0
    evidence_batch = []
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    for acc, refs in acc_refs.items():
        viruses = acc_to_virus.get(acc, [])
        if not viruses:
            continue

        for vdata in viruses:
            master_id = vdata["master_id"]
            species = vdata.get("species") or vdata.get("virus_name") or vdata["canonical_name"]
            isolate_id = vdata.get("isolate_id")

            for ref in refs[:3]:  # Max 3 evidence per accession
                pmid = ref.get("pmid", "")
                if pmid:
                    ref_id = all_ref_map.get(pmid)
                else:
                    ref_id = ref.get("_ref_id")

                if not ref_id:
                    continue

                # Check duplicate
                dup = conn.execute(
                    "SELECT 1 FROM evidence_records WHERE virus_master_id=? AND reference_id=? AND evidence_type='host_range'",
                    (master_id, ref_id)
                ).fetchone()
                if dup:
                    continue

                claim = generate_claim(species, ref.get("title", ""), ref.get("journal", ""), pmid)

                evidence_batch.append((
                    "host_range", master_id, None, isolate_id,
                    ref_id, None, claim, None, None, None, None,
                    "database_annotation",
                    "genbank_efetch_extracted",
                    "low", ts, ts,
                ))

                if len(evidence_batch) >= 300:
                    cur.executemany("""
                        INSERT INTO evidence_records (
                            evidence_type, virus_master_id, host_id, isolate_id,
                            reference_id, source_id, claim, value_text,
                            value_numeric_min, value_numeric_max, unit,
                            observation_type, extraction_method, evidence_strength,
                            created_at, updated_at
                        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """, evidence_batch)
                    evidence_created += len(evidence_batch)
                    evidence_batch = []
                    conn.commit()

    if evidence_batch:
        cur.executemany("""
            INSERT INTO evidence_records (
                evidence_type, virus_master_id, host_id, isolate_id,
                reference_id, source_id, claim, value_text,
                value_numeric_min, value_numeric_max, unit,
                observation_type, extraction_method, evidence_strength,
                created_at, updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, evidence_batch)
        evidence_created += len(evidence_batch)

    # Update isolate reference_id
    linked = 0
    for acc, refs in acc_refs.items():
        viruses = acc_to_virus.get(acc, [])
        if not refs or not viruses:
            continue
        first_ref_id = None
        if refs[0].get("pmid"):
            first_ref_id = all_ref_map.get(refs[0]["pmid"])
        else:
            first_ref_id = refs[0].get("_ref_id")
        if not first_ref_id:
            continue
        for vdata in viruses:
            cur.execute(
                "UPDATE viral_isolates SET reference_id=? WHERE isolate_id=? AND reference_id IS NULL",
                (first_ref_id, vdata["isolate_id"]))
            linked += cur.rowcount

    conn.commit()

    # Final stats
    zero = conn.execute("""
        SELECT COUNT(*) FROM virus_master v
        WHERE v.entry_type = 'ictv_vmr'
          AND NOT EXISTS (SELECT 1 FROM evidence_records e WHERE e.virus_master_id=v.master_id)
    """).fetchone()[0]
    total_ictv = conn.execute(
        "SELECT COUNT(*) FROM virus_master WHERE entry_type='ictv_vmr'"
    ).fetchone()[0]

    print(f"\n[Done]")
    print(f"  PubMed refs inserted: {len(new_ref_id)}")
    print(f"  GenBank submission refs: {gb_submission_refs}")
    print(f"  Evidence records created: {evidence_created}")
    print(f"  Isolates linked: {linked}")
    print(f"  ICTV VMR still zero-evidence: {zero}/{total_ictv}")

    # Summary
    total_ev = conn.execute("SELECT COUNT(*) FROM evidence_records").fetchone()[0]
    print(f"\n  Total evidence in DB: {total_ev:,}")

    conn.close()


if __name__ == "__main__":
    main()
