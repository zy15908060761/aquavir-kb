#!/usr/bin/env python3
"""
Resolve numeric canonical_name values imported from ICTV VMR row ids.

Some catalog-only ICTV entries were inserted into virus_master with
canonical_name equal to ictv_vmr.vmr_id (for example "7442").  For these
records, ictv_taxonomy.ictv_id may point to a different species, so this script
uses the local VMR row first, then joins taxonomy by official_ictv_id.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from db_utils import DB_PATH, backup_database, db_connection, db_transaction

BASE_DIR = Path(__file__).resolve().parent
REPORTS_DIR = BASE_DIR / "reports"


def stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def numeric_candidates(conn) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT
            vm.master_id,
            vm.canonical_name,
            vm.virus_family,
            vm.virus_genus,
            vm.genome_type,
            vm.entry_type,
            vm.discovery_context,
            vis.ictv_status,
            vis.reason
        FROM virus_master vm
        LEFT JOIN virus_ictv_status vis ON vis.master_id = vm.master_id
        WHERE vm.canonical_name GLOB '[0-9]*'
          AND vm.canonical_name NOT GLOB '*[^0-9]*'
          AND vm.entry_type != 'non_target'
          AND vm.entry_type != 'ictv_non_target'
        ORDER BY CAST(vm.canonical_name AS INTEGER)
        """
    ).fetchall()
    return [dict(r) for r in rows]


def resolve_candidate(conn, candidate: dict[str, Any]) -> dict[str, Any] | None:
    vmr_id = int(candidate["canonical_name"])
    vmr = conn.execute(
        """
        SELECT
            vmr_id,
            official_ictv_id,
            species,
            virus_name,
            virus_abbreviation,
            family,
            genus,
            genome_composition,
            genbank_accession,
            source_file
        FROM ictv_vmr
        WHERE vmr_id = ?
        """,
        (vmr_id,),
    ).fetchone()
    if not vmr or not vmr["species"]:
        return None

    tax = conn.execute(
        """
        SELECT ictv_id, official_ictv_id, species, family, genus, genome_composition
        FROM ictv_taxonomy
        WHERE official_ictv_id = ?
        """,
        (vmr["official_ictv_id"],),
    ).fetchone()
    if not tax:
        return None

    if tax["species"] != vmr["species"]:
        raise RuntimeError(
            f"VMR/taxonomy species mismatch for master_id={candidate['master_id']}: "
            f"{vmr['species']!r} vs {tax['species']!r}"
        )

    existing = conn.execute(
        """
        SELECT master_id, canonical_name, entry_type, discovery_context
        FROM virus_master
        WHERE canonical_name = ?
          AND master_id != ?
        """,
        (vmr["species"], candidate["master_id"]),
    ).fetchone()

    return {
        "master_id": candidate["master_id"],
        "target_master_id": existing["master_id"] if existing else candidate["master_id"],
        "resolution_mode": "merge_duplicate_placeholder" if existing else "rename_in_place",
        "old_canonical_name": candidate["canonical_name"],
        "new_canonical_name": vmr["species"],
        "old_family": candidate["virus_family"],
        "new_family": vmr["family"] or tax["family"],
        "old_genus": candidate["virus_genus"],
        "new_genus": vmr["genus"] or tax["genus"],
        "old_genome_type": candidate["genome_type"],
        "new_genome_type": normalize_genome_type(vmr["genome_composition"] or tax["genome_composition"]),
        "vmr_id": vmr["vmr_id"],
        "ictv_id": tax["ictv_id"],
        "official_ictv_id": vmr["official_ictv_id"],
        "genbank_accession": vmr["genbank_accession"],
        "source_file": vmr["source_file"],
        "old_ictv_status": candidate["ictv_status"],
        "old_ictv_reason": candidate["reason"],
        "existing_entry_type": existing["entry_type"] if existing else None,
        "existing_discovery_context": existing["discovery_context"] if existing else None,
    }


def normalize_genome_type(value: str | None) -> str | None:
    if not value:
        return None
    mapping = {
        "dsDNA": "dsDNA",
        "ssDNA": "ssDNA",
        "ssDNA(+/-)": "ssDNA",
        "dsRNA": "dsRNA",
        "ssRNA(+)": "ssRNA(+)",
        "ssRNA(-)": "ssRNA(-)",
        "ssRNA(+/-)": "ssRNA",
        "ssRNA": "ssRNA",
    }
    return mapping.get(value, value)


def apply_resolution(conn, row: dict[str, Any], dry_run: bool) -> None:
    if dry_run:
        return

    if row["resolution_mode"] == "merge_duplicate_placeholder":
        apply_duplicate_merge(conn, row)
        return

    conn.execute(
        """
        UPDATE virus_master
        SET canonical_name = ?,
            virus_family = COALESCE(?, virus_family),
            virus_genus = COALESCE(?, virus_genus),
            genome_type = COALESCE(?, genome_type),
            notes = CASE
                WHEN notes IS NULL OR notes = '' THEN ?
                WHEN notes LIKE '%' || ? || '%' THEN notes
                ELSE notes || '; ' || ?
            END
        WHERE master_id = ?
        """,
        (
            row["new_canonical_name"],
            row["new_family"],
            row["new_genus"],
            row["new_genome_type"],
            f"Resolved numeric ICTV VMR row id {row['old_canonical_name']} to species name {row['new_canonical_name']} ({row['official_ictv_id']}).",
            f"numeric ICTV VMR row id {row['old_canonical_name']}",
            f"Resolved numeric ICTV VMR row id {row['old_canonical_name']} to species name {row['new_canonical_name']} ({row['official_ictv_id']}).",
            row["master_id"],
        ),
    )

    conn.execute(
        """
        INSERT INTO virus_ictv_status
            (master_id, ictv_status, mapping_count, best_confidence, reason, updated_at)
        VALUES (?, 'mapped', 1, 'high', ?, CURRENT_TIMESTAMP)
        ON CONFLICT(master_id) DO UPDATE SET
            ictv_status = 'mapped',
            mapping_count = MAX(virus_ictv_status.mapping_count, 1),
            best_confidence = 'high',
            reason = excluded.reason,
            updated_at = CURRENT_TIMESTAMP
        """,
        (
            row["master_id"],
            f"Resolved from local ICTV VMR row {row['vmr_id']} and official ICTV id {row['official_ictv_id']}.",
        ),
    )

    conn.execute(
        """
        INSERT INTO virus_vmr_mappings
            (master_id, vmr_id, ictv_id, match_type, matched_value, match_status, confidence, notes)
        SELECT ?, ?, ?, 'manual_alias', ?, 'manual_checked', 'high', ?
        WHERE NOT EXISTS (
            SELECT 1 FROM virus_vmr_mappings
            WHERE master_id = ? AND vmr_id = ?
        )
        """,
        (
            row["master_id"],
            row["vmr_id"],
            row["ictv_id"],
            row["old_canonical_name"],
            f"Numeric canonical_name resolved to {row['new_canonical_name']} via {row['official_ictv_id']}.",
            row["master_id"],
            row["vmr_id"],
        ),
    )

    conn.execute(
        """
        INSERT INTO virus_ictv_mappings
            (master_id, ictv_id, match_type, matched_value, match_status, confidence, notes)
        SELECT ?, ?, 'normalized_exact', ?, 'manual_checked', 'high', ?
        WHERE NOT EXISTS (
            SELECT 1 FROM virus_ictv_mappings
            WHERE master_id = ? AND ictv_id = ?
        )
        """,
        (
            row["master_id"],
            row["ictv_id"],
            row["official_ictv_id"],
            f"Linked through VMR row {row['vmr_id']}; avoids ictv_taxonomy row-id ambiguity.",
            row["master_id"],
            row["ictv_id"],
        ),
    )


def apply_duplicate_merge(conn, row: dict[str, Any]) -> None:
    source_master_id = row["master_id"]
    target_master_id = row["target_master_id"]

    conn.execute(
        """
        UPDATE evidence_records
        SET virus_master_id = ?,
            notes = CASE
                WHEN notes IS NULL OR notes = '' THEN ?
                WHEN notes LIKE '%' || ? || '%' THEN notes
                ELSE notes || '; ' || ?
            END,
            updated_at = CURRENT_TIMESTAMP
        WHERE virus_master_id = ?
        """,
        (
            target_master_id,
            f"Reassigned from numeric ICTV VMR placeholder master_id {source_master_id} ({row['old_canonical_name']}).",
            f"numeric ICTV VMR placeholder master_id {source_master_id}",
            f"Reassigned from numeric ICTV VMR placeholder master_id {source_master_id} ({row['old_canonical_name']}).",
            source_master_id,
        ),
    )

    conn.execute(
        """
        UPDATE virus_master
        SET canonical_name = ?,
            is_crustacean_virus = 0,
            entry_type = 'duplicate_ictv_vmr_placeholder',
            public_visibility = 'internal',
            notes = CASE
                WHEN notes IS NULL OR notes = '' THEN ?
                ELSE notes || '; ' || ?
            END
        WHERE master_id = ?
        """,
        (
            f"ICTV VMR row {row['old_canonical_name']} duplicate of {row['new_canonical_name']}",
            f"Archived duplicate placeholder merged into master_id {target_master_id} ({row['new_canonical_name']}); source VMR row {row['vmr_id']}, official ICTV id {row['official_ictv_id']}.",
            f"Archived duplicate placeholder merged into master_id {target_master_id} ({row['new_canonical_name']}); source VMR row {row['vmr_id']}, official ICTV id {row['official_ictv_id']}.",
            source_master_id,
        ),
    )

    conn.execute(
        """
        INSERT INTO virus_aliases
            (master_id, alias, alias_type, external_id, match_status, confidence, is_preferred, notes)
        SELECT ?, ?, 'manual_alias', ?, 'manual_checked', 'high', 0, ?
        WHERE NOT EXISTS (
            SELECT 1 FROM virus_aliases
            WHERE master_id = ? AND alias = ?
        )
        """,
        (
            target_master_id,
            f"ICTV VMR row {row['old_canonical_name']}",
            str(row["vmr_id"]),
            f"Numeric placeholder master_id {source_master_id} merged into this canonical record.",
            target_master_id,
            f"ICTV VMR row {row['old_canonical_name']}",
        ),
    )

    conn.execute(
        """
        INSERT INTO virus_vmr_mappings
            (master_id, vmr_id, ictv_id, match_type, matched_value, match_status, confidence, notes)
        SELECT ?, ?, ?, 'manual_alias', ?, 'manual_checked', 'high', ?
        WHERE NOT EXISTS (
            SELECT 1 FROM virus_vmr_mappings
            WHERE master_id = ? AND vmr_id = ?
        )
        """,
        (
            target_master_id,
            row["vmr_id"],
            row["ictv_id"],
            row["old_canonical_name"],
            f"Numeric placeholder master_id {source_master_id} resolved to canonical master_id {target_master_id}.",
            target_master_id,
            row["vmr_id"],
        ),
    )

    conn.execute(
        """
        INSERT INTO virus_ictv_mappings
            (master_id, ictv_id, match_type, matched_value, match_status, confidence, notes)
        SELECT ?, ?, 'normalized_exact', ?, 'manual_checked', 'high', ?
        WHERE NOT EXISTS (
            SELECT 1 FROM virus_ictv_mappings
            WHERE master_id = ? AND ictv_id = ?
        )
        """,
        (
            target_master_id,
            row["ictv_id"],
            row["official_ictv_id"],
            f"Linked through VMR row {row['vmr_id']}; numeric placeholder master_id {source_master_id} was archived.",
            target_master_id,
            row["ictv_id"],
        ),
    )

    conn.execute(
        """
        INSERT INTO virus_ictv_status
            (master_id, ictv_status, mapping_count, best_confidence, reason, updated_at)
        VALUES (?, 'mapped', 1, 'high', ?, CURRENT_TIMESTAMP)
        ON CONFLICT(master_id) DO UPDATE SET
            ictv_status = 'mapped',
            mapping_count = MAX(virus_ictv_status.mapping_count, 1),
            best_confidence = 'high',
            reason = excluded.reason,
            updated_at = CURRENT_TIMESTAMP
        """,
        (
            target_master_id,
            f"Resolved from local ICTV VMR row {row['vmr_id']} and official ICTV id {row['official_ictv_id']}.",
        ),
    )

    conn.execute(
        """
        INSERT INTO virus_ictv_status
            (master_id, ictv_status, mapping_count, best_confidence, reason, updated_at)
        VALUES (?, 'rejected', 0, 'high', ?, CURRENT_TIMESTAMP)
        ON CONFLICT(master_id) DO UPDATE SET
            ictv_status = 'rejected',
            mapping_count = 0,
            best_confidence = 'high',
            reason = excluded.reason,
            updated_at = CURRENT_TIMESTAMP
        """,
        (
            source_master_id,
            f"Duplicate numeric ICTV VMR placeholder merged into master_id {target_master_id} ({row['new_canonical_name']}).",
        ),
    )

    conn.execute(
        """
        INSERT INTO curation_logs
            (entity_type, entity_id, action, old_value, new_value, confidence, curator, notes)
        VALUES
            ('virus_master', ?, 'merge_numeric_ictv_placeholder', ?, ?, 'high', 'fix_numeric_ictv_canonical_names.py', ?)
        """,
        (
            source_master_id,
            row["old_canonical_name"],
            f"master_id {target_master_id}: {row['new_canonical_name']}",
            f"Evidence reassigned and source archived as duplicate placeholder; VMR row {row['vmr_id']}, official ICTV id {row['official_ictv_id']}.",
        ),
    )


def write_reports(rows: list[dict[str, Any]], dry_run: bool) -> tuple[Path, Path]:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = stamp()
    tag = "dry_run" if dry_run else "applied"
    json_path = REPORTS_DIR / f"numeric_ictv_name_resolution_{tag}_{ts}.json"
    csv_path = REPORTS_DIR / f"numeric_ictv_name_resolution_{tag}_{ts}.csv"
    payload = {
        "timestamp": ts,
        "dry_run": dry_run,
        "resolved_count": len(rows),
        "rows": rows,
    }
    json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        if rows:
            writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
        else:
            fh.write("resolved_count\n0\n")
    return json_path, csv_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=str(DB_PATH), help="SQLite database path")
    parser.add_argument("--dry-run", action="store_true", help="Report changes without writing")
    args = parser.parse_args()

    with db_connection(args.db, read_only=True) as conn:
        resolved = []
        unresolved = []
        for candidate in numeric_candidates(conn):
            row = resolve_candidate(conn, candidate)
            if row:
                resolved.append(row)
            else:
                unresolved.append(candidate)

    if unresolved:
        raise RuntimeError(f"Unresolved numeric candidates: {unresolved}")

    if not args.dry_run and resolved:
        backup_database(args.db, label="before_numeric_ictv_name_resolution")
        with db_transaction(args.db) as conn:
            for row in resolved:
                apply_resolution(conn, row, dry_run=False)

    json_path, csv_path = write_reports(resolved, args.dry_run)
    print(f"resolved={len(resolved)} dry_run={args.dry_run}")
    print(f"json_report={json_path}")
    print(f"csv_report={csv_path}")
    for row in resolved:
        print(f"{row['master_id']}: {row['old_canonical_name']} -> {row['new_canonical_name']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
