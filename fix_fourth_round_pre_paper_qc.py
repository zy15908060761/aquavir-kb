#!/usr/bin/env python3
"""
Fourth audit round pre-paper QC fixes.

Deterministic fixes:
- Sync ICTV-backed taxonomy for mapped virus masters such as Yingvirus charybdis.
- Reject truncated evidence fragments.
- Move non-PMID identifiers out of ref_literatures.pmid into external_xrefs.
- Clear DOI='N/A'.
- Normalize family/genome_type incompatibilities where the family rule is clear.
- Quarantine exact duplicate evidence rows while retaining one canonical row.
- Backfill protein aa_length from translation.

Review queues:
- Genome-type/family updates that may be biologically ambiguous.
- Missing reference years.
- Short protein/RdRP fragments.
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

FAMILY_GENOME_RULES = {
    "Rhabdoviridae": "ssRNA(-)",
    "Circoviridae": "ssDNA",
    "Parvoviridae": "ssDNA",
    "Bunyaviridae": "ssRNA(-)",
    "Totiviridae": "dsRNA",
}

TRUNCATED_FRAGMENT_CLAIMS = ("VP", "An ", "A ", "N")


def stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def scalar(conn, sql: str, params: tuple[Any, ...] = ()) -> int:
    return int(conn.execute(sql, params).fetchone()[0])


def ensure_external_source(conn, source_key: str, name: str, category: str, description: str) -> int:
    row = conn.execute("SELECT source_id FROM external_sources WHERE source_key=?", (source_key,)).fetchone()
    if row:
        return int(row["source_id"])
    cur = conn.execute(
        """
        INSERT INTO external_sources (source_key, name, category, description, priority)
        VALUES (?, ?, ?, ?, 100)
        """,
        (source_key, name, category, description),
    )
    return int(cur.lastrowid)


def collect_metrics(conn) -> dict[str, Any]:
    return {
        "yingvirus_master": dict(
            conn.execute(
                """
                SELECT master_id, canonical_name, virus_family, virus_genus, genome_type
                FROM virus_master WHERE master_id=1173
                """
            ).fetchone()
        ),
        "truncated_evidence": scalar(
            conn,
            """
            SELECT COUNT(*) FROM evidence_records
            WHERE claim IN ('VP','An ','A ','N')
              AND extraction_method='evidence_v2_fuzzy_match'
            """,
        ),
        "non_numeric_pmid": scalar(
            conn,
            "SELECT COUNT(*) FROM ref_literatures WHERE COALESCE(pmid,'')!='' AND pmid GLOB '*[^0-9]*'",
        ),
        "doi_na": scalar(conn, "SELECT COUNT(*) FROM ref_literatures WHERE lower(COALESCE(doi,''))='n/a'"),
        "family_gt_incompatibilities": family_gt_count(conn),
        "duplicate_evidence_extra_rows": duplicate_extra_count(conn),
        "strict_duplicate_evidence_extra_rows": strict_duplicate_extra_count(conn, include_rejected=True),
        "active_strict_duplicate_evidence_extra_rows": strict_duplicate_extra_count(conn, include_rejected=False),
        "missing_year_refs": scalar(conn, "SELECT COUNT(*) FROM ref_literatures WHERE COALESCE(year,'')=''"),
        "referenced_missing_year_refs": scalar(
            conn,
            """
            SELECT COUNT(DISTINCT r.reference_id)
            FROM ref_literatures r
            WHERE COALESCE(r.year,'')=''
              AND EXISTS (SELECT 1 FROM evidence_records er WHERE er.reference_id=r.reference_id)
            """,
        ),
        "rdrp_aa_length_null": scalar(conn, "SELECT COUNT(*) FROM viral_proteins WHERE is_rdrp=1 AND aa_length IS NULL"),
        "protein_lt_30aa": scalar(conn, "SELECT COUNT(*) FROM viral_proteins WHERE aa_length < 30"),
        "rdrp_lt_100aa": scalar(conn, "SELECT COUNT(*) FROM viral_proteins WHERE is_rdrp=1 AND aa_length < 100"),
    }


def family_gt_count(conn) -> int:
    total = 0
    for family, expected in FAMILY_GENOME_RULES.items():
        total += scalar(
            conn,
            """
            SELECT COUNT(*) FROM virus_master
            WHERE virus_family=?
              AND COALESCE(genome_type,'')!=''
              AND genome_type!=?
              AND is_crustacean_virus=1
              AND entry_type NOT IN ('non_target','ictv_non_target','duplicate_ictv_vmr_placeholder',
                                     'duplicate_alias_placeholder')
            """,
            (family, expected),
        )
    return total


def duplicate_extra_count(conn) -> int:
    row = conn.execute(
        """
        WITH d AS (
          SELECT virus_master_id, evidence_type, claim, COUNT(*) n
          FROM evidence_records
          GROUP BY virus_master_id, evidence_type, claim
          HAVING COUNT(*)>1
        )
        SELECT COALESCE(SUM(n-1),0) FROM d
        """
    ).fetchone()
    return int(row[0] or 0)


def strict_duplicate_extra_count(conn, include_rejected: bool = True) -> int:
    status_filter = "" if include_rejected else "WHERE COALESCE(curation_status,'')!='rejected'"
    row = conn.execute(
        f"""
        WITH d AS (
          SELECT virus_master_id, host_id, isolate_id, reference_id, source_id,
                 evidence_type, claim, value_text, value_numeric_min, value_numeric_max,
                 unit, context, observation_type, evidence_strength, source_pmid,
                 source_doi, extraction_method, curation_status, notes, source_url,
                 COUNT(*) n
          FROM evidence_records
          {status_filter}
          GROUP BY virus_master_id, host_id, isolate_id, reference_id, source_id,
                   evidence_type, claim, value_text, value_numeric_min, value_numeric_max,
                   unit, context, observation_type, evidence_strength, source_pmid,
                   source_doi, extraction_method, curation_status, notes, source_url
          HAVING COUNT(*)>1
        )
        SELECT COALESCE(SUM(n-1),0) FROM d
        """
    ).fetchone()
    return int(row[0] or 0)


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        if rows:
            writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
        else:
            fh.write("status\nempty\n")


def export_review_queues(conn, ts: str) -> dict[str, str]:
    paths: dict[str, str] = {}
    genome_rows = []
    for family, expected in FAMILY_GENOME_RULES.items():
        genome_rows.extend(
            dict(r)
            for r in conn.execute(
                """
                SELECT master_id, canonical_name, virus_family, virus_genus, genome_type,
                       ? AS expected_genome_type, entry_type, discovery_context,
                       (SELECT COUNT(*) FROM virus_ictv_mappings m WHERE m.master_id=vm.master_id) AS ictv_maps,
                       (SELECT COUNT(*) FROM evidence_records er WHERE er.virus_master_id=vm.master_id) AS evidence_count
                FROM virus_master vm
                WHERE virus_family=?
                  AND COALESCE(genome_type,'')!=''
                  AND genome_type!=?
                  AND is_crustacean_virus=1
                  AND entry_type NOT IN ('non_target','ictv_non_target','duplicate_ictv_vmr_placeholder',
                                         'duplicate_alias_placeholder')
                ORDER BY evidence_count DESC, canonical_name
                """,
                (expected, family, expected),
            ).fetchall()
        )
    path = REPORTS_DIR / f"family_genome_type_incompatibility_review_{ts}.csv"
    write_csv(path, genome_rows)
    paths["family_genome_type_review"] = str(path)

    ictv_rows = [
        dict(r)
        for r in conn.execute(
            """
            SELECT vm.master_id, vm.canonical_name, vm.virus_family, vm.virus_genus, vm.genome_type,
                   it.ictv_id, it.family AS ictv_family, it.genus AS ictv_genus,
                   it.genome_composition AS ictv_genome_type,
                   m.match_type, m.match_status, m.confidence, m.notes AS mapping_notes
            FROM virus_master vm
            JOIN virus_ictv_mappings m ON m.master_id=vm.master_id
            JOIN ictv_taxonomy it ON it.ictv_id=m.ictv_id
            WHERE vm.is_crustacean_virus=1
              AND vm.entry_type NOT IN ('non_target','ictv_non_target','duplicate_ictv_vmr_placeholder',
                                         'duplicate_alias_placeholder')
              AND (
                COALESCE(vm.virus_family,'') != COALESCE(it.family,'')
                OR COALESCE(vm.virus_genus,'') != COALESCE(it.genus,'')
                OR COALESCE(vm.genome_type,'') != COALESCE(it.genome_composition,'')
              )
            ORDER BY vm.master_id, m.confidence DESC, m.match_status
            """
        ).fetchall()
    ]
    path = REPORTS_DIR / f"ictv_taxonomy_mismatch_review_{ts}.csv"
    write_csv(path, ictv_rows)
    paths["ictv_taxonomy_mismatch_review"] = str(path)

    duplicate_rows = [
        dict(r)
        for r in conn.execute(
            """
            SELECT er.virus_master_id, vm.canonical_name, er.evidence_type, er.claim, COUNT(*) AS row_count,
                   COUNT(DISTINCT COALESCE(er.reference_id,-1)) AS distinct_refs,
                   COUNT(DISTINCT COALESCE(er.source_id,-1)) AS distinct_sources,
                   COUNT(DISTINCT COALESCE(er.host_id,-1)) AS distinct_hosts,
                   COUNT(DISTINCT COALESCE(er.isolate_id,-1)) AS distinct_isolates,
                   COUNT(DISTINCT COALESCE(er.curation_status,'')) AS distinct_statuses,
                   COUNT(DISTINCT COALESCE(er.evidence_strength,'')) AS distinct_strengths,
                   MIN(er.evidence_id) AS first_evidence_id,
                   MAX(er.evidence_id) AS last_evidence_id
            FROM evidence_records er
            LEFT JOIN virus_master vm ON vm.master_id=er.virus_master_id
            GROUP BY er.virus_master_id, er.evidence_type, er.claim
            HAVING COUNT(*)>1
            ORDER BY row_count DESC, er.virus_master_id, er.evidence_type
            """
        ).fetchall()
    ]
    path = REPORTS_DIR / f"broad_duplicate_evidence_review_{ts}.csv"
    write_csv(path, duplicate_rows)
    paths["broad_duplicate_evidence_review"] = str(path)

    year_rows = [
        dict(r)
        for r in conn.execute(
            """
            SELECT r.reference_id, r.pmid, r.title, r.journal, r.doi,
                   (SELECT COUNT(*) FROM evidence_records er WHERE er.reference_id=r.reference_id) AS evidence_count
            FROM ref_literatures r
            WHERE COALESCE(r.year,'')=''
            ORDER BY evidence_count DESC, r.reference_id
            """
        ).fetchall()
    ]
    path = REPORTS_DIR / f"missing_reference_year_review_{ts}.csv"
    write_csv(path, year_rows)
    paths["missing_reference_year_review"] = str(path)

    protein_rows = [
        dict(r)
        for r in conn.execute(
            """
            SELECT vp.protein_id, vp.isolate_id, vi.accession, vi.master_id, vm.canonical_name,
                   vp.protein_accession, vp.protein_name, vp.aa_length, vp.is_rdrp,
                   LENGTH(COALESCE(vp.translation,'')) AS translation_length,
                   vp.functional_annotation_status
            FROM viral_proteins vp
            LEFT JOIN viral_isolates vi ON vi.isolate_id=vp.isolate_id
            LEFT JOIN virus_master vm ON vm.master_id=vi.master_id
            WHERE vp.aa_length < 30 OR (vp.is_rdrp=1 AND (vp.aa_length IS NULL OR vp.aa_length < 100))
            ORDER BY vp.is_rdrp DESC, vp.aa_length, vp.protein_id
            """
        ).fetchall()
    ]
    path = REPORTS_DIR / f"short_protein_rdrp_review_{ts}.csv"
    write_csv(path, protein_rows)
    paths["short_protein_rdrp_review"] = str(path)
    return paths


def classify_identifier(value: str) -> str:
    upper = value.upper()
    if upper.startswith("PMC"):
        return "pmcid"
    if upper.startswith("PPR"):
        return "preprint_id"
    if upper.startswith("IND"):
        return "index_id"
    return "non_pmid_identifier"


def sync_ictv_mapped_taxonomy(conn) -> int:
    rows = conn.execute(
        """
        SELECT vm.master_id, vm.virus_family, vm.virus_genus, vm.genome_type,
               it.family, it.genus, it.genome_composition
        FROM virus_master vm
        JOIN virus_ictv_mappings m ON m.master_id=vm.master_id
        JOIN ictv_taxonomy it ON it.ictv_id=m.ictv_id
        WHERE vm.is_crustacean_virus=1
          AND vm.entry_type NOT IN ('non_target','ictv_non_target','duplicate_ictv_vmr_placeholder',
                                   'duplicate_alias_placeholder')
          AND m.match_status='manual_checked'
          AND m.confidence='high'
          AND NOT EXISTS (
            SELECT 1 FROM virus_ictv_mappings m2
            WHERE m2.master_id=vm.master_id
              AND m2.ictv_id != m.ictv_id
              AND m2.confidence='high'
          )
          AND (
            COALESCE(vm.virus_genus,'') = COALESCE(it.genus,'')
            OR COALESCE(vm.virus_genus,'') IN ('', 'Unclassified')
            OR COALESCE(vm.virus_family,'') = 'Unclassified'
          )
          AND (
            COALESCE(vm.virus_family,'') != COALESCE(it.family,'')
            OR COALESCE(vm.virus_genus,'') != COALESCE(it.genus,'')
            OR COALESCE(vm.genome_type,'') != COALESCE(it.genome_composition,'')
          )
        """
    ).fetchall()
    changed = 0
    for r in rows:
        conn.execute(
            """
            UPDATE virus_master
            SET virus_family=?,
                virus_genus=?,
                genome_type=?,
                notes=CASE
                    WHEN notes IS NULL OR notes='' THEN ?
                    WHEN notes LIKE '%' || ? || '%' THEN notes
                    ELSE notes || '; ' || ?
                END
            WHERE master_id=?
            """,
            (
                r["family"],
                r["genus"],
                r["genome_composition"],
                "Fourth audit fix: taxonomy/genome_type synchronized from exact ICTV mapping.",
                "Fourth audit fix: taxonomy/genome_type synchronized",
                "Fourth audit fix: taxonomy/genome_type synchronized from exact ICTV mapping.",
                r["master_id"],
            ),
        )
        conn.execute(
            """
            INSERT INTO curation_logs
                (entity_type, entity_id, action, old_value, new_value, confidence, curator, notes)
            VALUES ('virus_master', ?, 'sync_ictv_taxonomy_genome_type', ?, ?, 'high',
                    'fix_fourth_round_pre_paper_qc.py',
                    'Synchronized from virus_ictv_mappings -> ictv_taxonomy.')
            """,
            (
                r["master_id"],
                json.dumps(
                    {
                        "family": r["virus_family"],
                        "genus": r["virus_genus"],
                        "genome_type": r["genome_type"],
                    },
                    ensure_ascii=False,
                ),
                json.dumps(
                    {
                        "family": r["family"],
                        "genus": r["genus"],
                        "genome_type": r["genome_composition"],
                    },
                    ensure_ascii=False,
                ),
            ),
        )
        changed += 1
    return changed


def reject_truncated_evidence(conn) -> int:
    cur = conn.execute(
        """
        UPDATE evidence_records
        SET curation_status='rejected',
            evidence_strength='low',
            notes=CASE
                WHEN notes IS NULL OR notes='' THEN 'Fourth audit fix: rejected truncated extraction fragment.'
                WHEN notes LIKE '%rejected truncated extraction fragment%' THEN notes
                ELSE notes || '; Fourth audit fix: rejected truncated extraction fragment.'
            END,
            updated_at=CURRENT_TIMESTAMP
        WHERE claim IN ('VP','An ','A ','N')
          AND extraction_method='evidence_v2_fuzzy_match'
        """
    )
    return cur.rowcount


def move_non_pmids(conn) -> int:
    source_ids = {
        "pmcid": ensure_external_source(conn, "pmc", "PubMed Central", "literature", "PubMed Central identifier migrated from non-PMID field."),
        "preprint_id": ensure_external_source(conn, "preprint_id", "Preprint identifier", "literature", "Preprint identifier migrated from non-PMID field."),
        "index_id": ensure_external_source(conn, "index_id", "Internal/index identifier", "literature", "Non-PMID index identifier migrated from PMID field."),
        "non_pmid_identifier": ensure_external_source(conn, "non_pmid_identifier", "Non-PMID literature identifier", "literature", "Miscellaneous non-PMID identifier migrated from PMID field."),
    }
    rows = conn.execute(
        """
        SELECT reference_id, pmid
        FROM ref_literatures
        WHERE COALESCE(pmid,'')!='' AND pmid GLOB '*[^0-9]*'
        """
    ).fetchall()
    for row in rows:
        ident = row["pmid"]
        kind = classify_identifier(ident)
        conn.execute(
            """
            INSERT INTO external_xrefs
                (entity_type, entity_id, source_id, external_id, match_status, confidence, matched_by, notes)
            SELECT 'reference', ?, ?, ?, 'manual_checked', 'high',
                   'fix_fourth_round_pre_paper_qc.py', ?
            WHERE NOT EXISTS (
                SELECT 1 FROM external_xrefs
                WHERE entity_type='reference' AND entity_id=? AND source_id=? AND external_id=?
            )
            """,
            (
                row["reference_id"],
                source_ids[kind],
                ident,
                f"Migrated from ref_literatures.pmid; identifier_type={kind}.",
                row["reference_id"],
                source_ids[kind],
                ident,
            ),
        )
    conn.execute(
        """
        UPDATE ref_literatures
        SET pmid=NULL
        WHERE COALESCE(pmid,'')!='' AND pmid GLOB '*[^0-9]*'
        """
    )
    return len(rows)


def clear_na_doi(conn) -> int:
    cur = conn.execute("UPDATE ref_literatures SET doi=NULL WHERE lower(COALESCE(doi,''))='n/a'")
    return cur.rowcount


def normalize_family_genome_types(conn) -> int:
    # Review-only by design. Family-level rules are useful QC flags, but too broad
    # for automatic correction of parvo-like/circovirus-like/metagenomic records.
    return 0


def quarantine_duplicate_evidence(conn, ts: str) -> int:
    cur = conn.execute(
        """
        INSERT INTO evidence_dedup_runs (run_ts, phase, dry_run, removed_count, notes)
        VALUES (?, 'fourth_round_strict_duplicate_quarantine', 0, 0,
                'Strict duplicate across core evidence fields; retained lowest evidence_id and marked duplicates rejected without physical deletion.')
        """,
        (ts,),
    )
    run_id = int(cur.lastrowid)
    dupes = conn.execute(
        """
        WITH ranked AS (
          SELECT evidence_id,
                 MIN(evidence_id) OVER (
                   PARTITION BY virus_master_id, host_id, isolate_id, reference_id, source_id,
                                evidence_type, claim, value_text, value_numeric_min,
                                value_numeric_max, unit, context, observation_type,
                                evidence_strength, source_pmid, source_doi,
                                extraction_method, curation_status, notes, source_url
                 ) AS retained_evidence_id,
                 ROW_NUMBER() OVER (
                   PARTITION BY virus_master_id, host_id, isolate_id, reference_id, source_id,
                                evidence_type, claim, value_text, value_numeric_min,
                                value_numeric_max, unit, context, observation_type,
                                evidence_strength, source_pmid, source_doi,
                                extraction_method, curation_status, notes, source_url
                   ORDER BY evidence_id
                 ) AS rn
          FROM evidence_records
        )
        SELECT evidence_id, retained_evidence_id FROM ranked WHERE rn>1
        """
    ).fetchall()
    for row in dupes:
        evidence_id = row["evidence_id"]
        retained_id = row["retained_evidence_id"]
        record = dict(conn.execute("SELECT * FROM evidence_records WHERE evidence_id=?", (evidence_id,)).fetchone())
        conn.execute(
            """
            INSERT INTO evidence_dedup_quarantine
                (run_id, evidence_id, full_record, reason, created_at)
            VALUES (?, ?, ?, 'strict duplicate across core evidence fields', CURRENT_TIMESTAMP)
            """,
            (run_id, evidence_id, json.dumps(record, ensure_ascii=False, default=str)),
        )
        note = (
            "Fourth audit fix: strict duplicate quarantined; "
            f"retained_evidence_id={retained_id}; duplicate_evidence_id={evidence_id}."
        )
        conn.execute(
            """
            UPDATE evidence_records
            SET curation_status='rejected',
                evidence_strength='low',
                notes=CASE
                    WHEN notes IS NULL OR notes='' THEN ?
                    WHEN notes LIKE '%' || ? || '%' THEN notes
                    ELSE notes || '; ' || ?
                END,
                updated_at=CURRENT_TIMESTAMP
            WHERE evidence_id=?
            """,
            (note, f"duplicate_evidence_id={evidence_id}", note, evidence_id),
        )
    conn.execute("UPDATE evidence_dedup_runs SET removed_count=? WHERE run_id=?", (len(dupes), run_id))
    return len(dupes)


def backfill_protein_lengths(conn) -> int:
    cur = conn.execute(
        """
        UPDATE viral_proteins
        SET aa_length=LENGTH(REPLACE(REPLACE(TRIM(translation), '*', ''), ' ', ''))
        WHERE aa_length IS NULL
          AND COALESCE(translation,'')!=''
        """
    )
    return cur.rowcount


def apply_fixes(conn, ts: str) -> dict[str, int]:
    changed = {
        "ictv_taxonomy_synced": sync_ictv_mapped_taxonomy(conn),
        "truncated_evidence_rejected": reject_truncated_evidence(conn),
        "non_pmids_migrated": move_non_pmids(conn),
        "doi_na_cleared": clear_na_doi(conn),
        "family_genome_type_normalized": normalize_family_genome_types(conn),
        "duplicate_evidence_quarantined": quarantine_duplicate_evidence(conn, ts),
        "protein_lengths_backfilled": backfill_protein_lengths(conn),
    }
    conn.execute(
        """
        INSERT INTO database_maintenance_log (action, details_json)
        VALUES ('fourth_round_pre_paper_qc', ?)
        """,
        (json.dumps(changed, ensure_ascii=False),),
    )
    return changed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=str(DB_PATH))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    ts = stamp()
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    with db_connection(args.db, read_only=True) as conn:
        before = collect_metrics(conn)
        review_paths = export_review_queues(conn, ts)

    changed: dict[str, int] = {}
    if not args.dry_run:
        backup_database(args.db, label="before_fourth_round_pre_paper_qc")
        with db_transaction(args.db) as conn:
            changed = apply_fixes(conn, ts)

    with db_connection(args.db, read_only=True) as conn:
        after = collect_metrics(conn)

    path = REPORTS_DIR / f"fourth_round_pre_paper_qc_summary_{ts}.json"
    path.write_text(
        json.dumps(
            {
                "timestamp": ts,
                "dry_run": args.dry_run,
                "before": before,
                "after": after,
                "changed": changed,
                "review_queues": review_paths,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"dry_run={args.dry_run}")
    print(f"summary={path}")
    print(json.dumps({"before": before, "after": after, "changed": changed, "review_queues": review_paths}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
