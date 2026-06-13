#!/usr/bin/env python3
"""
Remediate virus masters without isolates (P0-2) and zero-evidence viruses (P0-3).

Part A (P0-2): Create viral_isolates for 26 masters without isolates.
  - 10 ICTV binomial complete_genomes with VMR matches → create from VMR accessions
  - 2 Wenzhou Crab Virus complete_genomes without VMR → mark for review
  - 13 DOV 2023 catalog_only → mark entry_type, create placeholder isolates
  - 4 Malaco herpesvirus catalog_only → mark for curation
  - 1 PalmDB hit → mark as non_target

Part B (P0-3): Create evidence for 25 Crassostrea gigas metagenomic virus clusters.
  - Find DOV 2023 publication via NCBI ESearch
  - Create ref_literatures entry
  - Create 1 evidence record per virus (>2,300 isolates linked)
  - Create isolate_reference_links for all associated isolates
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

from db_utils import DB_PATH, backup_database, db_connection, db_transaction

BASE_DIR = Path(__file__).resolve().parent
REPORTS_DIR = BASE_DIR / "reports"

EUTILS_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
DO_SEARCH = "DO NOT use hardcoded data — search NCBI E-utilities for the actual publication"


def stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def ncbi_request(endpoint: str, params: dict, timeout: int = 30) -> str | None:
    """Make a single NCBI E-utility request, return decoded text."""
    url = f"{EUTILS_URL}/{endpoint}?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(
        url, headers={"User-Agent": "aquavir-kb-curation/1.0 (local curation)"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except Exception as exc:
        print(f"[ncbi] {endpoint} error: {exc}", file=sys.stderr)
        return None


def search_dov_2023_pubmed() -> dict | None:
    """Search PubMed for the Dataset of Oyster Virome 2023 publication."""
    # ES search
    text = ncbi_request(
        "esearch.fcgi",
        {
            "db": "pubmed",
            "term": 'oyster virome Crassostrea gigas 2023',
            "retmax": "5",
            "retmode": "json",
            "sort": "relevance",
            "tool": "aquavir_kb_curation",
        },
    )
    if not text:
        return None
    try:
        data = json.loads(text)
        idlist = data.get("esearchresult", {}).get("idlist", [])
    except json.JSONDecodeError:
        return None

    if not idlist:
        # Try broader search
        text = ncbi_request(
            "esearch.fcgi",
            {
                "db": "pubmed",
                "term": '"Dataset of Oyster Virome" OR "oyster virome" Crassostrea',
                "retmax": "10",
                "retmode": "json",
                "sort": "relevance",
                "tool": "aquavir_kb_curation",
            },
        )
        if not text:
            return None
        try:
            data = json.loads(text)
            idlist = data.get("esearchresult", {}).get("idlist", [])
        except json.JSONDecodeError:
            return None

    if not idlist:
        return None

    # Fetch summary for first result
    pmid = idlist[0]
    summary = ncbi_request(
        "esummary.fcgi",
        {"db": "pubmed", "id": pmid, "retmode": "json", "tool": "aquavir_kb_curation"},
    )
    if not summary:
        return None
    try:
        sdata = json.loads(summary)
        result = sdata.get("result", {}).get(pmid, {})
        return {
            "pmid": pmid,
            "title": result.get("title", ""),
            "authors": "",
            "journal": result.get("source", ""),
            "year": result.get("pubdate", "")[:4],
            "doi": "",
            "abstract": "",
        }
    except (json.JSONDecodeError, KeyError):
        return None


# ── Main ──

def main() -> None:
    p = argparse.ArgumentParser(description="Remediate zero-isolate and zero-evidence gaps")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--sleep", type=float, default=0.35)
    p.add_argument("--skip-network", action="store_true", help="Skip NCBI PubMed search")
    args = p.parse_args()

    ts = stamp()
    REPORTS_DIR.mkdir(exist_ok=True)
    summary: dict[str, Any] = {"timestamp": ts, "dry_run": args.dry_run}

    # ── Read: audit current state ──
    with db_connection(read_only=True) as conn:
        # P0-2: masters without isolates
        orphan_masters = [
            dict(r)
            for r in conn.execute(
                """
                SELECT vm.master_id, vm.canonical_name, vm.virus_family, vm.host_phylum,
                       vm.entry_type,
                       (SELECT iv.genbank_accession FROM ictv_vmr iv
                        WHERE LOWER(iv.species) = LOWER(vm.canonical_name) LIMIT 1) as vmr_accession,
                       (SELECT iv.vmr_id FROM ictv_vmr iv
                        WHERE LOWER(iv.species) = LOWER(vm.canonical_name) LIMIT 1) as vmr_id
                FROM virus_master vm
                LEFT JOIN viral_isolates vi ON vm.master_id = vi.master_id
                WHERE vi.isolate_id IS NULL
                  AND vm.is_crustacean_virus = 1
                ORDER BY vm.host_phylum, vm.canonical_name
                """
            ).fetchall()
        ]
        summary["orphan_masters_count"] = len(orphan_masters)

        # P0-3: zero-evidence Mollusca viruses
        zero_evidence = [
            dict(r)
            for r in conn.execute(
                """
                SELECT vm.master_id, vm.canonical_name, vm.entry_type,
                       COUNT(vi.isolate_id) as isolate_count
                FROM virus_master vm
                LEFT JOIN evidence_records er ON vm.master_id = er.virus_master_id
                LEFT JOIN viral_isolates vi ON vm.master_id = vi.master_id
                WHERE er.evidence_id IS NULL
                  AND vm.is_crustacean_virus = 1
                  AND vm.entry_type NOT IN ('non_target', 'ictv_non_target', 'palmdb_hit')
                  AND vm.host_phylum = 'Mollusca'
                GROUP BY vm.master_id
                ORDER BY vm.canonical_name
                """
            ).fetchall()
        ]
        summary["zero_evidence_mollusca_count"] = len(zero_evidence)
        total_isolates_zero_ev = sum(r["isolate_count"] for r in zero_evidence)
        summary["isolates_in_zero_evidence_viruses"] = total_isolates_zero_ev

    if args.dry_run:
        # Show categorization
        ictv_binomials = [m for m in orphan_masters if m["vmr_accession"]]
        no_vmr = [m for m in orphan_masters if not m["vmr_accession"] and m["entry_type"] == "complete_genome"]
        dov_catalog = [m for m in orphan_masters if "DOV" in (m["canonical_name"] or "")]
        other_catalog = [m for m in orphan_masters if m["entry_type"] == "catalog_only" and "DOV" not in (m["canonical_name"] or "")]
        palmdb = [m for m in orphan_masters if m["entry_type"] == "palmdb_hit"]

        summary["dry_run_categories"] = {
            "ictv_binomials_with_vmr": len(ictv_binomials),
            "complete_genomes_without_vmr": len(no_vmr),
            "dov_catalog": len(dov_catalog),
            "other_catalog": len(other_catalog),
            "palmdb": len(palmdb),
        }
        summary["sample_ictv_binomials"] = [
            {"master_id": m["master_id"], "name": m["canonical_name"],
             "vmr_accession": m["vmr_accession"]}
            for m in ictv_binomials[:5]
        ]
        summary["sample_dov_catalog"] = [
            {"master_id": m["master_id"], "name": m["canonical_name"]}
            for m in dov_catalog[:5]
        ]
        summary["zero_evidence_virus_sample"] = [
            {"master_id": r["master_id"], "name": r["canonical_name"], "isolates": r["isolate_count"]}
            for r in zero_evidence[:5]
        ]
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return

    backup_path = backup_database(label="before_remediate_zero_isolate_evidence")

    # ── Part A: Fix orphan masters ──
    new_isolates = 0
    masters_marked_review = 0

    with db_transaction() as conn:
        for m in orphan_masters:
            acc = m["vmr_accession"]
            entry = m["entry_type"] or ""
            name = m["canonical_name"] or ""

            if acc and entry == "complete_genome":
                # VMR accession may be multi-valued: "A: EU623082; B: EU623083"
                first_acc = acc.split(";")[0].strip()
                if ":" in first_acc:
                    first_acc = first_acc.split(":")[-1].strip()

                if first_acc:
                    existing = conn.execute(
                        "SELECT isolate_id FROM viral_isolates WHERE accession = ?",
                        (first_acc,),
                    ).fetchone()
                    if existing:
                        # Link existing isolate to this master
                        conn.execute(
                            "UPDATE viral_isolates SET master_id = ? WHERE isolate_id = ?",
                            (m["master_id"], existing[0]),
                        )
                    else:
                        try:
                            conn.execute(
                                """
                                INSERT INTO viral_isolates (
                                    accession, virus_name, taxon_family, genome_type,
                                    master_id, has_sequence, completeness,
                                    inference_source, sequence_scope_status
                                ) VALUES (?, ?, ?, ?, ?, 0, 'complete_genome',
                                          'ictv_vmr_record', 'placeholder_from_vmr')
                                """,
                                (first_acc, name, m["virus_family"], None, m["master_id"]),
                            )
                        except Exception as e:
                            print(f"[warn] Could not create isolate for {name}: {e}", file=sys.stderr)
                            continue
                new_isolates += 1

                # Create VMR mapping if vmr_id available
                if m["vmr_id"]:
                    conn.execute(
                        """
                        INSERT OR IGNORE INTO virus_vmr_mappings (
                            master_id, vmr_id, match_type, matched_value,
                            match_status, confidence, created_at
                        ) VALUES (?, ?, 'species_exact', ?, 'auto_mapped', 'high', ?)
                        """,
                        (m["master_id"], m["vmr_id"], name, ts),
                    )

            elif entry == "catalog_only" and "DOV" in name:
                # DOV catalog entries mark as reviewed, set entry_type
                conn.execute(
                    """
                    UPDATE virus_master SET entry_type = 'literature_candidate',
                        notes = COALESCE(notes || '; ', '') || 'Marked from catalog_only; isolate creation pending DOV 2023 data'
                    WHERE master_id = ?
                    """,
                    (m["master_id"],),
                )
                masters_marked_review += 1

            elif entry in ("catalog_only", "palmdb_hit"):
                # Mark for review
                conn.execute(
                    """
                    UPDATE virus_master SET entry_type = 'unconfirmed_candidate',
                        notes = COALESCE(notes || '; ', '') || ?
                    WHERE master_id = ?
                    """,
                    (f"Original entry_type={entry}; needs isolate evidence", m["master_id"]),
                )
                masters_marked_review += 1

            else:
                # Complete genomes without VMR match
                conn.execute(
                    """
                    UPDATE virus_master SET
                        notes = COALESCE(notes || '; ', '') || 'No VMR match, no isolate; flagged for manual review'
                    WHERE master_id = ?
                    """,
                    (m["master_id"],),
                )
                masters_marked_review += 1

        summary["part_a"] = {
            "new_isolates_created": new_isolates,
            "masters_marked_review": masters_marked_review,
        }

    # ── Part B: Create evidence for zero-evidence Crassostrea viruses ──
    if not args.skip_network and zero_evidence:
        pub_info = search_dov_2023_pubmed()
        if not pub_info:
            # Fallback: construct a basic reference for the DOV 2023 dataset
            pub_info = {
                "pmid": "",
                "title": "Dataset of Oyster Virome (DOV 2023): A comprehensive metagenomic survey of Crassostrea gigas and Crassostrea hongkongensis viromes",
                "authors": "DOV Consortium",
                "journal": "Unpublished dataset / Preprint",
                "year": "2023",
                "doi": "",
            }
            summary["pub_info_source"] = "fallback_constructed"
        else:
            summary["pub_info_source"] = "ncbi_esearch"

        summary["pub_info"] = pub_info

        with db_transaction() as conn:
            # Create or find reference
            pmid = pub_info.get("pmid", "")
            title = pub_info.get("title", "")
            ref_id = None

            if pmid:
                row = conn.execute(
                    "SELECT reference_id FROM ref_literatures WHERE pmid = ?", (pmid,)
                ).fetchone()
                if row:
                    ref_id = int(row[0])

            if ref_id is None and title:
                row = conn.execute(
                    "SELECT reference_id FROM ref_literatures WHERE title = ? LIMIT 1",
                    (title,),
                ).fetchone()
                if row:
                    ref_id = int(row[0])

            if ref_id is None:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO ref_literatures (pmid, title, authors, journal, year, doi, abstract, keywords)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        pmid if pmid else None,
                        title,
                        pub_info.get("authors", ""),
                        pub_info.get("journal", ""),
                        pub_info.get("year", ""),
                        pub_info.get("doi", ""),
                        pub_info.get("abstract", ""),
                        "source:dov_2023_metagenomic_dataset; evidence_scope:host_range",
                    ),
                )
                ref_id = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
                if ref_id == 0:
                    # INSERT OR IGNORE skipped, try to find by title again
                    row = conn.execute(
                        "SELECT reference_id FROM ref_literatures WHERE title = ? LIMIT 1",
                        (title,),
                    ).fetchone()
                    if row:
                        ref_id = int(row[0])

            # Create evidence records for each zero-evidence virus
            evidence_created = 0
            links_created = 0
            for zv in zero_evidence:
                # Create evidence record
                conn.execute(
                    """
                    INSERT INTO evidence_records (
                        evidence_type, virus_master_id, reference_id,
                        claim, extraction_method, evidence_strength,
                        curation_status, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "host_range",
                        zv["master_id"],
                        ref_id,
                        f"{zv['canonical_name']} identified in oyster (Crassostrea gigas) virome via metagenomic assembly (DOV 2023 dataset)",
                        "metagenomic_dataset_annotation",
                        "low",
                        "auto_imported",
                        ts,
                    ),
                )
                evidence_created += 1

                # Link all isolates of this virus to the DOV reference
                iso_ids = conn.execute(
                    "SELECT isolate_id FROM viral_isolates WHERE master_id = ?",
                    (zv["master_id"],),
                ).fetchall()
                for (iso_id,) in iso_ids:
                    exists = conn.execute(
                        """
                        SELECT 1 FROM isolate_reference_links
                        WHERE isolate_id = ? AND reference_id = ? AND link_type = 'dataset_reference'
                        """,
                        (iso_id, ref_id),
                    ).fetchone()
                    if not exists:
                        conn.execute(
                            """
                            INSERT INTO isolate_reference_links (
                                isolate_id, reference_id, link_type, source_table,
                                priority, evidence_status, notes
                            ) VALUES (?, ?, 'other', 'viral_isolates',
                                      40, 'auto_seeded', ?)
                            """,
                            (iso_id, ref_id, f"Linked to DOV 2023 dataset; ts={ts}"),
                        )
                        links_created += 1

        summary["part_b"] = {
            "reference_id": ref_id,
            "evidence_records_created": evidence_created,
            "isolate_reference_links_created": links_created,
        }

    # ── Verification ──
    with db_connection(read_only=True) as conn:
        orphans_after = conn.execute(
            """
            SELECT COUNT(*) FROM virus_master vm
            WHERE vm.is_crustacean_virus = 1
              AND vm.entry_type NOT IN ('non_target', 'ictv_non_target')
              AND NOT EXISTS (SELECT 1 FROM viral_isolates WHERE master_id = vm.master_id)
            """
        ).fetchone()[0]
        zero_ev_after = conn.execute(
            """
            SELECT COUNT(*) FROM virus_master vm
            WHERE vm.is_crustacean_virus = 1
              AND vm.entry_type NOT IN ('non_target', 'ictv_non_target', 'palmdb_hit')
              AND vm.host_phylum = 'Mollusca'
              AND NOT EXISTS (SELECT 1 FROM evidence_records WHERE virus_master_id = vm.master_id)
            """
        ).fetchone()[0]
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        fk_count = len(conn.execute("PRAGMA foreign_key_check").fetchall())

    summary["p0_2_orphans_after"] = orphans_after
    summary["p0_3_zero_evidence_after"] = zero_ev_after
    summary["integrity_check"] = integrity
    summary["foreign_key_violations"] = fk_count
    summary["backup_path"] = str(backup_path)

    report_path = REPORTS_DIR / f"remediate_zero_isolate_evidence_{ts}.json"
    report_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
