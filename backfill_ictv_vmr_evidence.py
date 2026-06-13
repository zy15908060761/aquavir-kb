#!/usr/bin/env python3
"""
P0: ICTV VMR backfill — resolve names, fix taxonomy, link PubMed evidence.

Two-phase approach:
  Phase 1 (no network): Resolve numeric canonical_names to real virus names
    from ictv_vmr table. Update virus_master with proper taxonomy. Mark non-
    target entries.

  Phase 2 (network): Use GenBank accessions → NCBI ELink → PubMed IDs.
    Fetch reference metadata. Link isolates + create evidence records.

Safety: --dry-run, WAL-safe backup, idempotent
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sqlite3
import sys
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
BATCH_SIZE = 80
EFETCH_BATCH = 30


def stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def backup_database() -> Path:
    BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
    ts = stamp()
    bp = BACKUPS_DIR / f"crustacean_virus_core_pre_ictv_backfill_{ts}.db"
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


def ncbi_request(endpoint: str, params: dict) -> Optional[bytes]:
    url = f"{NCBI_BASE}/{endpoint}?{urllib.parse.urlencode(params)}"
    time.sleep(NCBI_RATE)
    try:
        with urllib.request.urlopen(url, timeout=60) as r:
            return r.read()
    except Exception as e:
        print(f"  [warn] NCBI {endpoint}: {e}")
        return None


# ── Phase 1: Metadata resolution ────────────────────────────────────

def resolve_ictv_vmr_metadata(conn, dry_run: bool) -> dict:
    """Resolve numeric canonical_names to real virus data from ictv_vmr."""
    cur = conn.cursor()

    # Collect all ICTV VMR virus_master entries that need fixing
    rows = conn.execute("""
        SELECT v.master_id, v.canonical_name, v.virus_family, v.host_phylum, v.genome_type,
               i.species, i.virus_name, i.family, i.genus, i.genome_composition,
               i.host_source, i.genbank_accession
        FROM virus_master v
        JOIN ictv_vmr i ON CAST(v.canonical_name AS INTEGER) = i.vmr_id
        WHERE v.entry_type = 'ictv_vmr'
    """).fetchall()

    print(f"\n[Phase 1] Resolving metadata for {len(rows)} ICTV VMR entries...")

    # Categorize
    AQUATIC_HOSTS = {"invertebrates", "invertebrates (S)",
                     "invertebrates, vertebrates", "invertebrates, plants"}
    stats = {"aquatic": 0, "non_target": 0, "name_fixed": 0,
             "family_fixed": 0, "genome_fixed": 0, "updated": 0}

    updates = []  # (master_id, canonical_name, family, genus, genome_type, host_phylum, entry_type, notes)
    name_counter: dict[str, int] = {}  # for uniqueness within new names

    # Pre-build set of existing canonical names (non-ICTV) to avoid conflicts
    existing_names = set()
    for r in conn.execute("SELECT canonical_name FROM virus_master WHERE entry_type != 'ictv_vmr'").fetchall():
        existing_names.add(r["canonical_name"])

    for r in rows:
        mid = r["master_id"]
        host_src = r["host_source"] or ""
        species = r["species"] or ""
        virus_name = r["virus_name"] or ""
        family = r["family"] or ""
        genus = r["genus"] or ""
        genome = r["genome_composition"] or ""
        genbank = r["genbank_accession"] or ""

        # Determine target status
        is_aquatic = host_src in AQUATIC_HOSTS
        if is_aquatic:
            stats["aquatic"] += 1
            new_entry_type = "ictv_vmr"
        else:
            stats["non_target"] += 1
            new_entry_type = "non_target"

        # Determine new name
        base_name = species if species else (virus_name if virus_name else r["canonical_name"])

        # Check for conflicts with existing non-ICTV entries
        if base_name in existing_names and base_name != r["canonical_name"]:
            # This species already exists in DB — keep numeric name to avoid conflict
            # TODO: merge these entries later
            new_name = r["canonical_name"]
        elif base_name != r["canonical_name"]:
            # Ensure unique name using counter
            if base_name in name_counter:
                name_counter[base_name] += 1
                new_name = f"{base_name} (isolate {name_counter[base_name]})"
            else:
                name_counter[base_name] = 1
                new_name = base_name
            stats["name_fixed"] += 1
        else:
            new_name = r["canonical_name"]

        # Determine family
        new_family = family if family else r["virus_family"] or ""
        if new_family and new_family != (r["virus_family"] or ""):
            stats["family_fixed"] += 1
        elif not r["virus_family"] and new_family:
            stats["family_fixed"] += 1

        # Determine genome_type
        new_genome = genome if genome else r["genome_type"] or ""
        if new_genome and new_genome != (r["genome_type"] or ""):
            stats["genome_fixed"] += 1

        # Determine host_phylum
        new_phylum = r["host_phylum"] or ""
        if not new_phylum and is_aquatic:
            new_phylum = "multiple"  # default for aquatic invertebrates

        updates.append((new_name, new_family, genus, new_genome, new_phylum,
                        new_entry_type, host_src, genbank, mid))
        stats["updated"] += 1

    # Apply updates
    if not dry_run:
        cur.executemany("""
            UPDATE virus_master SET
                canonical_name = ?,
                virus_family = ?,
                virus_genus = ?,
                genome_type = ?,
                host_phylum = ?,
                entry_type = ?,
                notes = COALESCE(notes || '; ','') || 'ICTV VMR backfill: host_source=' || ? ||
                        ', GenBank=' || COALESCE(?, 'N/A')
            WHERE master_id = ?
        """, updates)
        conn.commit()
        print(f"  Applied {stats['updated']} metadata updates")
    else:
        print(f"  [DRY RUN] Would update {stats['updated']} viruses")

    # Print stats
    print(f"  Aquatic (kept): {stats['aquatic']}")
    print(f"  Non-target (marked): {stats['non_target']}")
    print(f"  Name fixes: {stats['name_fixed']}")
    print(f"  Family fixes: {stats['family_fixed']}")
    print(f"  Genome type fixes: {stats['genome_fixed']}")

    return stats


# ── Phase 2: PubMed evidence linkage ─────────────────────────────────

def extract_valid_accessions(accession_str: str) -> list[str]:
    """Parse GenBank accessions, handling multi-accession fields like 'A: EU623082; B: EU623083'."""
    if not accession_str:
        return []
    accs = []
    # Remove prefixes like "A: ", "B: "
    cleaned = re.sub(r'[A-Z]:\s*', '', accession_str)
    parts = re.split(r'[;,]\s*', cleaned)
    for p in parts:
        p = p.strip()
        # Valid GenBank accession: 1-2 letters + 5-6 digits, or 4 letters + 8 digits
        if re.match(r'^[A-Z]{1,2}\d{5,6}$', p) or re.match(r'^[A-Z]{4}\d{8,}$', p):
            accs.append(p)
        elif re.match(r'^[A-Z]_\d+$', p):  # RefSeq style
            accs.append(p)
        elif p and len(p) <= 20:
            accs.append(p)  # Accept and let NCBI sort it out
    return accs


def elink_accessions_to_pmids(accessions: list[str]) -> dict[str, list[str]]:
    """NCBI ELink: nucleotide accession → PubMed IDs."""
    result: dict[str, list[str]] = {}
    total = len(accessions)
    for i in range(0, total, BATCH_SIZE):
        batch = accessions[i:i + BATCH_SIZE]
        ids = ",".join(batch)
        data = ncbi_request("elink.fcgi", {
            "dbfrom": "nucleotide",
            "db": "pubmed",
            "id": ids,
            "linkname": "nucleotide_pubmed",
            "retmode": "json",
        })
        if not data:
            continue
        try:
            parsed = json.loads(data)
            for ls in parsed.get("linksets", []):
                uid = str(ls.get("ids", [None])[0] or "")
                if not uid:
                    continue
                pmids = [str(p) for p in ls.get("linksetdbs", [{}])[0].get("links", [])]
                if pmids:
                    result[uid] = pmids
        except (json.JSONDecodeError, KeyError):
            continue
        done = min(i + BATCH_SIZE, total)
        print(f"  elink: {done}/{total} → {len(result)} mapped")
    return result


def efetch_pubmed_summaries(pmids: list[str]) -> dict[str, dict]:
    """EFetch PubMed summaries."""
    result: dict[str, dict] = {}
    total = len(pmids)
    for i in range(0, total, EFETCH_BATCH):
        batch = pmids[i:i + EFETCH_BATCH]
        data = ncbi_request("efetch.fcgi", {
            "db": "pubmed", "id": ",".join(batch),
            "retmode": "xml", "rettype": "abstract",
        })
        if not data:
            continue
        try:
            root = ET.fromstring(data)
            for art in root.findall(".//PubmedArticle"):
                medline = art.find(".//MedlineCitation")
                if medline is None:
                    continue
                pmid_el = medline.find(".//PMID")
                if pmid_el is None or not pmid_el.text:
                    continue
                pmid = pmid_el.text

                art_info = medline.find(".//Article")
                title = ""
                abstract = ""
                authors = ""
                journal = ""
                year = ""
                doi = ""

                if art_info is not None:
                    t = art_info.find(".//ArticleTitle")
                    if t is not None:
                        title = "".join(t.itertext())

                    abs_parts = []
                    for a in art_info.findall(".//AbstractText"):
                        lbl = a.get("Label", "")
                        txt = "".join(a.itertext())
                        abs_parts.append(f"{lbl}: {txt}" if lbl else txt)
                    abstract = " ".join(abs_parts)

                    auth_list = []
                    for au in art_info.findall(".//Author"):
                        ln = au.findtext("LastName", "") or ""
                        fn = au.findtext("ForeName", "") or ""
                        if ln:
                            auth_list.append(f"{ln} {fn}" if fn else ln)
                    authors = "; ".join(auth_list[:10])

                    jn = art_info.find(".//Journal/Title")
                    if jn is not None and jn.text:
                        journal = jn.text

                    pd = art_info.find(".//PubDate")
                    if pd is not None:
                        y = pd.findtext("Year", "")
                        if y:
                            year = y

                    for eid in art_info.findall(".//ELocationID"):
                        if eid.get("EIdType") == "doi":
                            doi = eid.text or ""

                result[pmid] = {
                    "pmid": pmid, "title": title, "abstract": abstract,
                    "authors": authors, "journal": journal, "year": year, "doi": doi,
                }
        except ET.ParseError:
            continue
        done = min(i + EFETCH_BATCH, total)
        print(f"  efetch: {done}/{total} → {len(result)} fetched")
    return result


def generate_claim(virus_name: str, abstract: str, pmid: str) -> str:
    """Generate evidence claim from abstract."""
    if not abstract:
        return f"Auto-linked from NCBI Nucleotide-PubMed. PMID:{pmid}"
    sentences = re.split(r'(?<=[.!?])\s+', abstract)
    keywords = ["virus", "genome", "sequence", "isolate", "detect", "infection",
                "host", "novel", "identif", "phylogen"]
    name_parts = virus_name.lower().split()[:3]  # Use first 3 parts of species name

    scored = []
    for sent in sentences:
        s = sent.strip()
        if len(s) < 40 or len(s) > 600:
            continue
        sl = s.lower()
        score = sum(3 for p in name_parts if p in sl) + sum(1 for kw in keywords if kw in sl)
        if score > 0:
            scored.append((score, s))

    scored.sort(key=lambda x: -x[0])
    if scored:
        best = scored[0][1]
        return f"Auto-extracted from abstract: {best[:497]}... PMID:{pmid}" if len(best) > 500 else f"Auto-extracted from abstract: {best} PMID:{pmid}"
    elif len(abstract) > 50:
        return f"Auto-extracted from abstract: {abstract[:500]} PMID:{pmid}"
    return f"Auto-linked from NCBI Nucleotide-PubMed. PMID:{pmid}"


def link_pubmed_evidence(conn, dry_run: bool, limit: int = 0) -> dict:
    """Phase 2: Link GenBank accessions to PubMed, fetch refs, create evidence."""
    print("\n[Phase 2] PubMed evidence linkage...")

    # Get aquatic ICTV VMR viruses with GenBank accessions
    # Join via isolate accession (VMR1000046) → ictv_vmr.virus_isolate
    # This is independent of Phase 1 canonical_name changes
    rows = conn.execute("""
        SELECT v.master_id, v.canonical_name, v.virus_family,
               vi.isolate_id, vi.accession as vmr_isolate,
               i.genbank_accession, i.species, i.virus_name
        FROM virus_master v
        JOIN viral_isolates vi ON v.master_id = vi.master_id
        JOIN ictv_vmr i ON vi.accession = i.virus_isolate
        WHERE v.entry_type = 'ictv_vmr'
          AND i.genbank_accession IS NOT NULL
          AND i.genbank_accession != ''
          AND LENGTH(i.genbank_accession) <= 20
        ORDER BY v.master_id
    """).fetchall()

    if limit:
        rows = rows[:limit]

    print(f"  Target viruses (with GenBank acc): {len(rows)}")

    # Extract unique valid GenBank accessions
    gb_to_viruses: dict[str, list] = {}
    for r in rows:
        accs = extract_valid_accessions(r["genbank_accession"])
        for acc in accs:
            if acc not in gb_to_viruses:
                gb_to_viruses[acc] = []
            gb_to_viruses[acc].append(dict(r))

    unique_accs = list(gb_to_viruses.keys())
    print(f"  Unique GenBank accessions: {len(unique_accs)}")

    if not unique_accs:
        print("  No valid GenBank accessions found.")
        return {"linked": 0, "refs_new": 0, "evidence_new": 0}

    # ELink to PubMed
    acc_to_pmids = elink_accessions_to_pmids(unique_accs)
    print(f"  Accessions with PubMed links: {len(acc_to_pmids)}")

    all_pmids = set()
    for pmids in acc_to_pmids.values():
        all_pmids.update(pmids)
    print(f"  Total unique PMIDs: {len(all_pmids)}")

    if not all_pmids:
        return {"linked": 0, "refs_new": 0, "evidence_new": 0}

    # Separate existing vs new PMIDs
    pmid_list = list(all_pmids)
    existing_map: dict[str, int] = {}  # pmid → reference_id
    for i in range(0, len(pmid_list), 500):
        batch = pmid_list[i:i+500]
        ph = ",".join("?" for _ in batch)
        refs = conn.execute(
            f"SELECT reference_id, pmid FROM ref_literatures WHERE pmid IN ({ph})", batch
        ).fetchall()
        for ref in refs:
            existing_map[ref["pmid"]] = ref["reference_id"]

    new_pmids = [p for p in pmid_list if p not in existing_map]
    print(f"  Existing PMIDs: {len(existing_map)}, New: {len(new_pmids)}")

    # Fetch new references
    new_refs = {}
    if new_pmids:
        new_refs = efetch_pubmed_summaries(new_pmids)
        print(f"  Fetched new refs: {len(new_refs)}")

    if dry_run:
        # Count how many isolates could be linked
        linked_count = 0
        for acc, pmids in acc_to_pmids.items():
            if pmids:
                linked_count += len(gb_to_viruses.get(acc, []))
        print(f"\n  [DRY RUN] Would:")
        print(f"    - Insert {len(new_refs)} new references")
        print(f"    - Link ~{linked_count} isolates to references")
        # Show samples
        for acc, pmids in list(acc_to_pmids.items())[:5]:
            viruses = gb_to_viruses.get(acc, [])
            if viruses:
                v = viruses[0]
                print(f"    {acc} ({v['species']}) → PMID:{pmids[:3]}")
        return {"linked": linked_count, "refs_new": len(new_refs), "evidence_new": linked_count}

    # ── Apply writes ──
    cur = conn.cursor()

    # Insert new references
    new_ref_id: dict[str, int] = {}
    for pmid, data in new_refs.items():
        try:
            cur.execute("""
                INSERT INTO ref_literatures (pmid, title, authors, journal, year, doi, abstract)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (pmid, data["title"], data["authors"], data["journal"],
                  data["year"], data["doi"], data["abstract"]))
            new_ref_id[pmid] = cur.lastrowid
        except Exception as e:
            print(f"  [warn] insert PMID {pmid}: {e}")

    all_ref_map = {**existing_map, **new_ref_id}
    print(f"  Inserted references: {len(new_ref_id)}")

    # Link isolates and create evidence
    linked = 0
    evidence_count = 0
    evidence_batch = []

    for acc, pmids in acc_to_pmids.items():
        viruses = gb_to_viruses.get(acc, [])
        if not viruses or not pmids:
            continue

        primary_pmid = pmids[0]
        ref_id = all_ref_map.get(primary_pmid)
        if not ref_id:
            continue

        # Update isolates with this GenBank accession
        for vdata in viruses:
            try:
                cur.execute(
                    "UPDATE viral_isolates SET reference_id = ? WHERE isolate_id = ?",
                    (ref_id, vdata["isolate_id"]))
                linked += 1
            except:
                pass

        # Create evidence for all PMIDs → virus pairs
        seen_pairs = set()
        for vdata in viruses:
            virus_id = vdata["master_id"]
            # Use resolved species name if available, otherwise canonical_name
            virus_name = vdata.get("species") or vdata.get("virus_name") or vdata["canonical_name"]

            for pmid in pmids:
                PMID_ref_id = all_ref_map.get(pmid)
                if not PMID_ref_id:
                    continue
                pair_key = (virus_id, PMID_ref_id, "host_range")
                if pair_key in seen_pairs:
                    continue
                seen_pairs.add(pair_key)

                # Get abstract
                abstract = ""
                if pmid in new_refs:
                    abstract = new_refs[pmid].get("abstract", "")
                elif pmid in existing_map:
                    r = conn.execute(
                        "SELECT abstract FROM ref_literatures WHERE pmid=?", (pmid,)
                    ).fetchone()
                    if r:
                        abstract = r["abstract"] or ""

                claim = generate_claim(virus_name, abstract, pmid)
                ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                evidence_batch.append((
                    "host_range", virus_id, None, vdata["isolate_id"],
                    PMID_ref_id, None, claim, None, None, None, None,
                    "NCBI Nucleotide-PubMed linkage",
                    "auto_extracted_ictv_backfill",
                    "low", ts, ts,
                ))

                if len(evidence_batch) >= 500:
                    cur.executemany("""
                        INSERT INTO evidence_records (
                            evidence_type, virus_master_id, host_id, isolate_id,
                            reference_id, source_id, claim, value_text,
                            value_numeric_min, value_numeric_max, unit,
                            observation_type, extraction_method, evidence_strength,
                            created_at, updated_at
                        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """, evidence_batch)
                    evidence_count += len(evidence_batch)
                    evidence_batch = []

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
        evidence_count += len(evidence_batch)

    conn.commit()

    result = {"linked": linked, "refs_new": len(new_ref_id), "evidence_new": evidence_count}
    return result


# ── Main ─────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="ICTV VMR backfill")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--phase1-only", action="store_true", help="Only fix metadata (no network)")
    parser.add_argument("--phase2-only", action="store_true", help="Only link evidence (after phase1)")
    parser.add_argument("--limit", type=int, default=0, help="Limit for Phase 2")
    args = parser.parse_args()

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=120000")

    if not args.dry_run and not args.phase1_only:
        backup_database()

    do_phase1 = not args.phase2_only
    do_phase2 = not args.phase1_only

    if do_phase1:
        resolve_ictv_vmr_metadata(conn, args.dry_run)

    if do_phase2:
        link_pubmed_evidence(conn, args.dry_run, args.limit)

    if args.dry_run:
        print("\n[DRY RUN complete — no changes made]")
    else:
        print("\n[Done]")

    # Final stats
    zero = conn.execute("""
        SELECT COUNT(*) FROM virus_master v
        WHERE v.entry_type = 'ictv_vmr'
          AND NOT EXISTS (SELECT 1 FROM evidence_records e WHERE e.virus_master_id=v.master_id)
    """).fetchone()[0]
    total_ictv = conn.execute(
        "SELECT COUNT(*) FROM virus_master WHERE entry_type='ictv_vmr'"
    ).fetchone()[0]
    print(f"ICTV VMR still zero-evidence: {zero}/{total_ictv}")

    conn.close()


if __name__ == "__main__":
    main()
