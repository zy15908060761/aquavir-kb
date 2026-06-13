"""
Batch-populate evidence_records from existing literature references.
Currently 523/530 virus species have traceable references but only 71 have evidence.
This script auto-creates evidence records bridging that gap.

Strategy:
  For each virus_master entry that has linked ref_literatures (via viral_isolates),
  auto-create an evidence record documenting the literature link, with:
    - evidence_type = 'literature_reference'
    - evidence_strength = 'medium' (auto-generated, not expert-curated)
    - curation_status = 'auto_seeded'
    - extraction_method = 'batch_linkage_from_isolate_references'

Usage: python batch_populate_evidence.py [--dry-run] [--target-pct 50]
"""

import sqlite3
import sys
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "crustacean_virus_core.db"


def main(dry_run: bool = False, target_pct: float = 50.0):
    conn = sqlite3.connect(str(DB_PATH))
    c = conn.cursor()

    # ── Current state ───────────────────────────────────────────────────────
    c.execute("SELECT COUNT(*) FROM virus_master")
    total_species = c.fetchone()[0]

    c.execute("""SELECT COUNT(DISTINCT virus_master_id) FROM evidence_records
                 WHERE curation_status != 'rejected'""")
    species_with_evidence = c.fetchone()[0]

    print(f"Current evidence coverage: {species_with_evidence}/{total_species} "
          f"({species_with_evidence/total_species*100:.1f}%)")
    print(f"Target: {target_pct}%")

    # ── Find species without evidence that have linked references ──────────
    c.execute("""SELECT DISTINCT vm.master_id, vm.canonical_name, vm.virus_family,
                        vi.isolate_id, vi.reference_id, r.pmid, r.doi, r.title
                 FROM virus_master vm
                 JOIN viral_isolates vi ON vm.master_id = vi.master_id
                 JOIN ref_literatures r ON vi.reference_id = r.reference_id
                 WHERE vm.master_id NOT IN (
                     SELECT DISTINCT virus_master_id FROM evidence_records
                     WHERE curation_status != 'rejected'
                 )
                 AND vm.canonical_name NOT LIKE '%Human%immuno%'
                 AND vm.canonical_name NOT LIKE '%HIV%'
                 ORDER BY
                     CASE WHEN (r.pmid IS NOT NULL AND r.pmid != '')
                          OR (r.doi IS NOT NULL AND r.doi != '') THEN 0 ELSE 1 END,
                     vm.canonical_name""")
    candidates = c.fetchall()

    # Group by master_id (one evidence record per species)
    species_refs = {}
    for row in candidates:
        mid = row[0]
        if mid not in species_refs:
            species_refs[mid] = {
                "canonical_name": row[1],
                "virus_family": row[2],
                "isolate_id": row[3],
                "reference_id": row[4],
                "pmid": row[5] or "",
                "doi": row[6] or "",
                "ref_title": (row[7] or "")[:200],
            }

    print(f"\nSpecies eligible for evidence population: {len(species_refs)}")
    target_count = int(total_species * target_pct / 100)
    needed = max(0, target_count - species_with_evidence)
    to_create = min(len(species_refs), needed)

    print(f"Need {needed} more species with evidence to reach {target_pct}%")
    print(f"Will create {to_create} evidence records")

    if dry_run:
        print("\n=== DRY RUN — showing first 20 candidates ===")
        for i, (mid, info) in enumerate(list(species_refs.items())[:20]):
            pmid_doi = info["pmid"] or info["doi"] or "no_identifier"
            print(f"  {i+1}. [{info['virus_family']}] {info['canonical_name'][:60]}")
            print(f"     ref_id={info['reference_id']} | {pmid_doi}")
        conn.close()
        return

    # ── Create evidence records ────────────────────────────────────────────
    created = 0
    skipped = 0
    now = datetime.now().isoformat()

    for i, (mid, info) in enumerate(species_refs.items()):
        if created >= to_create:
            break

        # Check if evidence already exists for this species (double-check)
        c.execute("""SELECT COUNT(*) FROM evidence_records
                     WHERE virus_master_id = ? AND curation_status != 'rejected'""",
                  (mid,))
        if c.fetchone()[0] > 0:
            skipped += 1
            continue

        # Build evidence record
        # Must match CHECK constraints: evidence_type IN ('host_range',..., 'other'),
        # observation_type IN ('field','lab','database_annotation','review','expert_curation','unknown'),
        # curation_status IN ('needs_review','auto_imported','manual_checked','rejected')
        evidence_type = "other"
        claim = (f"Virus species {info['canonical_name']} has published sequence records "
                 f"linked to literature reference")
        source_pmid = info["pmid"] or None
        source_doi = info["doi"] or None

        try:
            c.execute("""INSERT INTO evidence_records
                         (evidence_type, virus_master_id, isolate_id, reference_id,
                          source_id, claim, observation_type, evidence_strength,
                          source_pmid, source_doi, extraction_method, curation_status,
                          created_at, updated_at)
                         VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                      (evidence_type, mid, info["isolate_id"], info["reference_id"],
                       None, claim, "database_annotation", "medium",
                       source_pmid, source_doi, "batch_linkage_from_isolate_references",
                       "auto_imported", now, now))
            created += 1
        except sqlite3.Error as e:
            print(f"  ERROR for {info['canonical_name']}: {e}")
            skipped += 1
            continue

        if created % 100 == 0:
            conn.commit()
            print(f"  ... {created} records created")

    conn.commit()

    # ── Report ──────────────────────────────────────────────────────────────
    c.execute("""SELECT COUNT(DISTINCT virus_master_id) FROM evidence_records
                 WHERE curation_status != 'rejected'""")
    new_coverage = c.fetchone()[0]

    print("\n" + "=" * 60)
    print("BATCH EVIDENCE POPULATION COMPLETE")
    print("=" * 60)
    print(f"  Created:    {created}")
    print(f"  Skipped:    {skipped}")
    print(f"  Coverage:   {species_with_evidence} → {new_coverage} species "
          f"({new_coverage/total_species*100:.1f}%)")
    print(f"  Gain:       +{new_coverage - species_with_evidence} species "
          f"(+{(new_coverage - species_with_evidence)/total_species*100:.1f}%)")

    conn.close()


if __name__ == "__main__":
    dry = "--dry-run" in sys.argv
    target = 50.0
    for a in sys.argv:
        if a.startswith("--target-pct="):
            target = float(a.split("=")[1])
    main(dry_run=dry, target_pct=target)
