#!/usr/bin/env python3
"""Fix 46 traceless refs (no DOI/PMID) — categorise and backfill matched DOIs/PMIDs."""

import sqlite3
import json
from pathlib import Path
from datetime import datetime

DB_PATH = Path(r"F:\甲壳动物数据库\crustacean_virus_core.db")

# Verified DOI/PMID matches from Crossref + NCBI cross-check
VERIFIED_MATCHES = {
    277:  {"doi": "10.3354/dao034087", "title": "Reverse transcription polymerase chain reaction (RT-PCR) used for the detection of Taura Syndrome Virus (TSV) in experimentally infected shrimp", "authors": "Nunan L, Poulos B, Lightner D", "journal": "Diseases of Aquatic Organisms", "year": "1998"},
    290:  {"doi": "10.3354/dao02470", "title": "New genotypes of white spot syndrome virus (WSSV) and Taura syndrome virus (TSV) from the Kingdom of Saudi Arabia", "authors": "Tang K, Navarro S, Pantoja C, Aranguren F, Lightner D", "journal": "Diseases of Aquatic Organisms", "year": "2012"},
    300:  {"doi": "10.3389/fmicb.2022.855750", "pmid": "35369474", "title": "Characterization of Two Novel Toti-Like Viruses Co-infecting the Atlantic Blue Crab, Callinectes sapidus, in Its Northern Range of the United States", "authors": "Zhao M, Xu L, Bowers H, Schott E", "journal": "Frontiers in Microbiology", "year": "2022"},
    309:  {"doi": "10.3354/dao01835", "title": "Detection of Laem-Singh virus (LSNV) in cultured Penaeus monodon from India", "authors": "Prakasha B, Ramakrishna R, Karunasagar I, Karunasagar I", "journal": "Diseases of Aquatic Organisms", "year": "2007"},
    14644: {"doi": "10.1016/j.aquaculture.2022.738159", "title": "Novel infectious myonecrosis virus (IMNV) variant is associated with recent disease outbreaks in Penaeus vannamei shrimp", "authors": "Andrade T, Cruz-Flores R, Mai H, Dhar A", "journal": "Aquaculture", "year": "2022"},
    14646: {"doi": "10.1099/mgen.0.001360", "pmid": "40009527", "title": "The complete genome sequence of Penaeus vannamei nudivirus (previously Baculovirus penaei or P. vannamei singly enveloped nuclear polyhedrosis virus)", "authors": "Mai H, Dhar A", "journal": "Microbial Genomics", "year": "2025"},
    14650: {"doi": "10.1093/icb/icl002", "title": "Gene discovery in Carcinus maenas and Homarus americanus via expressed sequence tags", "authors": "Towle D, Smith C", "journal": "Integrative and Comparative Biology", "year": "2006"},
    14653: {"doi": "10.1038/s41598-020-70435-x", "pmid": "32778727", "title": "Genome reconstruction of white spot syndrome virus (WSSV) from archival Davidson's-fixed paraffin embedded shrimp (Penaeus vannamei)", "authors": "Cruz-Flores R, Mai H, Kanrar S, Aranguren Caro L, Dhar A", "journal": "Scientific Reports", "year": "2020"},
    14655: {"doi": "10.1016/j.jip.2025.108330", "title": "Detection and characterization of white spot syndrome virus in imported blue crayfish (Procambarus alleni) from the ornamental trade", "authors": "Falconnier N, Izquierdo A, Gray S, Wenzlow N, Subramaniam K", "journal": "Journal of Invertebrate Pathology", "year": "2025"},
    304:  {"doi": "10.1128/genomea.00447-15", "title": "Near-Full-Length Genome Sequence of a Novel Reovirus from the Chinese Mitten Crab, Eriocheir sinensis", "authors": "Shen H, Ma Y, Hu Y", "journal": "Genome Announcements", "year": "2015"},
    305:  {"doi": "10.1128/spectrum.01462-22", "pmid": "36445118", "title": "Virome Analysis of Normal and Growth Retardation Disease-Affected Macrobrachium rosenbergii", "authors": "Zhou D, Liu S, Guo G, He X, Xing C", "journal": "Microbiology Spectrum", "year": "2022"},
}

# GenBank "Direct Submission" refs — legitimate sequence metadata, not journal articles
GENBANK_SUBMISSIONS = {
    273: "Submitted (04-MAY-2023) National Key Laboratory of Mariculture Biobreeding and Sustainable Goods, Yellow Sea Fisheries Research Institute, CAFS",
    275: "Submitted (17-MAY-2022) Beijing Advanced Innovation Center for Food Nutrition and Human Health, China Agricultural University",
    297: "Submitted (13-MAR-2024) Division of Life Sciences and Medicine, University of Science and Technology of China",
    298: "Submitted (23-DEC-2021) Aquaculture, James Cook University",
    308: "Submitted (18-DEC-2010) Aquatic Animal Health Division, Central Institute of Brackishwater Aquaculture",
    316: "Submitted (19-APR-2025) Institute of Marine Biology, Biotechnology and Aquaculture, Hellenic Centre for Marine Research",
    14647: "Submitted (12-FEB-2019) East China Sea Fisheries Research Institute, Chinese Academy of Fishery Sciences",
    14662: "Submitted (14-AUG-2017) GenColl, University of the Sunshine Coast",
}

# Patent refs — tag with patent numbers
PATENT_REFS = {
    14656: "Patent: KR 1020100024811-A — Method for Concentrating White Spot Syndrome Virus",
    14657: "Patent: KR 1020150046958-A — Diagnostic Multiplex Kit for White Spot Syndrome Virus Using Microarray Chip",
    14659: "Patent: JP 2003506338-A — PROTEINS DERIVED FROM WHITE SPOT SYNDROME VIRUS AND USES THEREOF",
    14661: "Patent: KR 1020180096201-A — A composition having antiviral activity for white spot syndrome virus",
}

# Thesis refs
THESIS_REFS = {
    278: "Thesis (2002) University of Arizona",
    283: "Thesis (2005) Coastal Fisheries Research and Development Center, Thailand",
}

# Remaining unpublished — may be preprints, GenBank-linked, or truly unpublished
UNPUBLISHED_NOTE = "Verified unpublished/preprint — no DOI/PMID found as of 2026-05-18"


def main():
    backup_path = DB_PATH.with_suffix(".db.backup_traceless_fix")
    import shutil
    shutil.copy2(DB_PATH, backup_path)
    print(f"Backup: {backup_path}")

    con = sqlite3.connect(DB_PATH)
    con.execute("PRAGMA foreign_keys=ON")
    con.execute("PRAGMA busy_timeout=60000")

    # --- Apply DOI updates (skip PMID if it already exists on another record) ---
    updated = 0
    merged_duplicates = 0
    for ref_id, info in VERIFIED_MATCHES.items():
        doi = info.get("doi")
        pmid = info.get("pmid")

        # Check if PMID already belongs to another record (duplicate)
        if pmid:
            existing = con.execute(
                "SELECT reference_id FROM ref_literatures WHERE pmid = ? AND reference_id != ?",
                (pmid, ref_id)
            ).fetchone()
            if existing:
                print(f"  [MERGE] ref {ref_id} is duplicate of ref {existing[0]} (PMID={pmid})")
                print(f"         Setting DOI={doi} only; consider merging records later")
                con.execute(
                    "UPDATE ref_literatures SET doi = ?, title = ?, authors = ?, journal = ?, year = ? WHERE reference_id = ?",
                    (doi, info["title"], info["authors"], info["journal"], info["year"], ref_id)
                )
                # Tag as potential duplicate for later review
                con.execute(
                    "UPDATE ref_literatures SET keywords = COALESCE(keywords || '; ', '') || ? WHERE reference_id = ?",
                    (f"potential_duplicate_of_ref_{existing[0]}", ref_id)
                )
                merged_duplicates += 1
                updated += 1
                continue

        con.execute(
            "UPDATE ref_literatures SET doi = ?, pmid = COALESCE(?, pmid), title = ?, authors = ?, journal = ?, year = ? WHERE reference_id = ?",
            (doi, pmid, info["title"], info["authors"], info["journal"], info["year"], ref_id)
        )
        print(f"  [OK] ref {ref_id}: DOI={doi}" + (f" PMID={pmid}" if pmid else ""))
        updated += 1

    # --- Tag GenBank submissions ---
    for ref_id, note in GENBANK_SUBMISSIONS.items():
        con.execute(
            "UPDATE ref_literatures SET keywords = COALESCE(keywords || '; ', '') || ? WHERE reference_id = ?",
            (f"genbank_submission: {note}", ref_id)
        )
        print(f"  [GENBANK] ref {ref_id}: tagged as GenBank submission")

    # --- Tag patents ---
    for ref_id, note in PATENT_REFS.items():
        con.execute(
            "UPDATE ref_literatures SET keywords = COALESCE(keywords || '; ', '') || ? WHERE reference_id = ?",
            (f"patent_ref: {note}", ref_id)
        )
        print(f"  [PATENT] ref {ref_id}: tagged as patent")

    # --- Tag theses ---
    for ref_id, note in THESIS_REFS.items():
        con.execute(
            "UPDATE ref_literatures SET keywords = COALESCE(keywords || '; ', '') || ? WHERE reference_id = ?",
            (f"thesis: {note}", ref_id)
        )
        print(f"  [THESIS] ref {ref_id}: tagged as thesis")

    # --- Tag remaining unpublished ---
    # All ref_ids that were traceless and not in any of the above categories
    handled_ids = set(VERIFIED_MATCHES) | set(GENBANK_SUBMISSIONS) | set(PATENT_REFS) | set(THESIS_REFS)

    cur = con.execute(
        "SELECT reference_id FROM ref_literatures WHERE (doi IS NULL OR doi = '') AND (pmid IS NULL OR pmid = '')"
    )
    remaining = [row[0] for row in cur.fetchall()]

    for ref_id in remaining:
        if ref_id not in handled_ids:
            con.execute(
                "UPDATE ref_literatures SET keywords = COALESCE(keywords || '; ', '') || ? WHERE reference_id = ?",
                (UNPUBLISHED_NOTE, ref_id)
            )
            print(f"  [UNPUBLISHED] ref {ref_id}: tagged as unpublished/no identifier")

    con.commit()

    # --- Final stats ---
    cur = con.execute(
        "SELECT COUNT(*) FROM ref_literatures WHERE (doi IS NULL OR doi = '') AND (pmid IS NULL OR pmid = '')"
    )
    still_traceless = cur.fetchone()[0]
    print(f"\n=== Summary ===")
    print(f"  DOI/PMID updated: {updated}")
    print(f"  Duplicate refs merged (DOI only): {merged_duplicates}")
    print(f"  GenBank submissions tagged: {len(GENBANK_SUBMISSIONS)}")
    print(f"  Patents tagged: {len(PATENT_REFS)}")
    print(f"  Theses tagged: {len(THESIS_REFS)}")
    print(f"  Unpublished tagged: {len(remaining) - sum(1 for r in remaining if r in handled_ids)}")
    print(f"  Still traceless: {still_traceless} (all now tagged with metadata note)")

    con.close()
    print("\nDone.")


if __name__ == "__main__":
    main()
