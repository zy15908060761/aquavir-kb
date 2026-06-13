#!/usr/bin/env python3
"""Merge 4 duplicate refs into their canonical PMID-indexed versions."""

import sqlite3, shutil
from pathlib import Path

DB_PATH = Path(r"F:\甲壳动物数据库\crustacean_virus_core.db")

# Verified duplicate → canonical mapping (from Crossref + manual verification)
MERGES = {
    300:   1582,   # Toti-like viruses in blue crab
    305:   1751,   # Virome of Macrobrachium rosenbergii
    14646: 6696,   # Penaeus vannamei nudivirus genome
    14653: 5209,   # WSSV genome reconstruction
}

def main():
    # Backup
    backup = DB_PATH.with_suffix(".db.pre_merge_backup")
    shutil.copy2(DB_PATH, backup)
    print(f"Backup: {backup}")

    con = sqlite3.connect(DB_PATH)
    con.execute("PRAGMA foreign_keys = OFF")  # Temporarily disable for manual FK handling
    con.execute("PRAGMA busy_timeout = 60000")
    cur = con.cursor()

    total_ev = 0
    total_lfs = 0
    total_lec = 0

    for dup_id, canon_id in MERGES.items():
        print(f"\n--- Merging ref {dup_id} → ref {canon_id} ---")

        # Get titles for logging
        cur.execute("SELECT title FROM ref_literatures WHERE reference_id = ?", (dup_id,))
        dup_title = (cur.fetchone() or ("?",))[0]
        cur.execute("SELECT title FROM ref_literatures WHERE reference_id = ?", (canon_id,))
        canon_title = (cur.fetchone() or ("?",))[0]
        print(f"  Duplicate: {str(dup_title)[:80]}")
        print(f"  Canonical: {str(canon_title)[:80]}")

        # 1. Reassign evidence_records
        cur.execute("SELECT COUNT(*) FROM evidence_records WHERE reference_id = ?", (dup_id,))
        ev_count = cur.fetchone()[0]
        if ev_count > 0:
            cur.execute(
                "UPDATE evidence_records SET reference_id = ? WHERE reference_id = ?",
                (canon_id, dup_id)
            )
            print(f"  Reassigned {ev_count} evidence records → ref {canon_id}")
            total_ev += ev_count

        # 2. Reassign literature_fulltext_sources
        cur.execute("SELECT COUNT(*) FROM literature_fulltext_sources WHERE reference_id = ?", (dup_id,))
        lfs_count = cur.fetchone()[0]
        if lfs_count > 0:
            cur.execute(
                "UPDATE literature_fulltext_sources SET reference_id = ? WHERE reference_id = ?",
                (canon_id, dup_id)
            )
            print(f"  Reassigned {lfs_count} fulltext sources → ref {canon_id}")
            total_lfs += lfs_count

        # 3. Reassign literature_fulltext_sections
        cur.execute("SELECT COUNT(*) FROM literature_fulltext_sections WHERE reference_id = ?", (dup_id,))
        sec_count = cur.fetchone()[0]
        if sec_count > 0:
            cur.execute(
                "UPDATE literature_fulltext_sections SET reference_id = ? WHERE reference_id = ?",
                (canon_id, dup_id)
            )
            print(f"  Reassigned {sec_count} sections → ref {canon_id}")

        # 4. Reassign literature_evidence_candidates
        cur.execute("SELECT COUNT(*) FROM literature_evidence_candidates WHERE reference_id = ?", (dup_id,))
        lec_count = cur.fetchone()[0]
        if lec_count > 0:
            cur.execute(
                "UPDATE literature_evidence_candidates SET reference_id = ? WHERE reference_id = ?",
                (canon_id, dup_id)
            )
            print(f"  Reassigned {lec_count} evidence candidates → ref {canon_id}")
            total_lec += lec_count

        # 5. Delete duplicate ref
        cur.execute("DELETE FROM ref_literatures WHERE reference_id = ?", (dup_id,))
        print(f"  Deleted duplicate ref {dup_id}")

    con.commit()

    # Verify integrity
    print(f"\n=== Post-merge verification ===")
    cur.execute("SELECT COUNT(*) FROM ref_literatures")
    n_refs = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM evidence_records")
    n_ev = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM evidence_records WHERE reference_id NOT IN (SELECT reference_id FROM ref_literatures)")
    orphans = cur.fetchone()[0]

    print(f"  ref_literatures: {n_refs} (was 7512, expect 7508)")
    print(f"  evidence_records: {n_ev}")
    print(f"  Orphan evidence (FK broken): {orphans}")
    print(f"  Total evidence reassigned: {total_ev}")
    print(f"  Total fulltext sources reassigned: {total_lfs}")
    print(f"  Total candidates reassigned: {total_lec}")

    # Clean up duplicate tags on canonical refs
    for dup_id, canon_id in MERGES.items():
        cur.execute(
            "UPDATE ref_literatures SET keywords = REPLACE(keywords, ?, '') WHERE reference_id = ?",
            (f"potential_duplicate_of_ref_{canon_id};", canon_id)
        )
        cur.execute(
            "UPDATE ref_literatures SET keywords = REPLACE(keywords, ?, '') WHERE reference_id = ?",
            (f";potential_duplicate_of_ref_{canon_id}", canon_id)
        )
    con.commit()

    con.close()
    print("\nDone.")


if __name__ == "__main__":
    main()
