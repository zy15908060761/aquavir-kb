#!/usr/bin/env python3
"""
Follow-up correction after third-round OsHV/AVNV review.

The third-round deterministic script reactivated master_id=1307, but a
follow-up review found it is an ambiguous AVNV shell with no isolates and high
reference overlap with master_id=548 (Abalone viral necrosis virus). This script
demotes 1307 to a limited unconfirmed candidate and records the review signal.
It does not merge evidence into 548.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from db_utils import DB_PATH, backup_database, db_connection, db_transaction

BASE_DIR = Path(__file__).resolve().parent
REPORTS_DIR = BASE_DIR / "reports"


def stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def scalar(conn, sql: str) -> int:
    return int(conn.execute(sql).fetchone()[0])


def metrics(conn) -> dict:
    return {
        "active_target_masters": scalar(
            conn,
            """
            SELECT COUNT(*) FROM virus_master
            WHERE is_crustacean_virus=1
              AND entry_type NOT IN ('non_target','ictv_non_target','duplicate_ictv_vmr_placeholder',
                                     'duplicate_alias_placeholder','unconfirmed_candidate')
            """,
        ),
        "active_target_masters_including_unconfirmed": scalar(
            conn,
            """
            SELECT COUNT(*) FROM virus_master
            WHERE is_crustacean_virus=1
              AND entry_type NOT IN ('non_target','ictv_non_target','duplicate_ictv_vmr_placeholder',
                                     'duplicate_alias_placeholder')
            """,
        ),
        "master_1307": dict(
            conn.execute(
                """
                SELECT master_id, canonical_name, is_crustacean_virus, entry_type,
                       public_visibility, virus_family, virus_genus, genome_type, notes
                FROM virus_master WHERE master_id=1307
                """
            ).fetchone()
        ),
        "master_1307_evidence": scalar(conn, "SELECT COUNT(*) FROM evidence_records WHERE virus_master_id=1307"),
        "master_1307_isolates": scalar(conn, "SELECT COUNT(*) FROM viral_isolates WHERE master_id=1307"),
    }


def ref_overlap(conn, a: int, b: int) -> dict:
    refs_a = {
        r["reference_id"]
        for r in conn.execute(
            "SELECT DISTINCT reference_id FROM evidence_records WHERE virus_master_id=? AND reference_id IS NOT NULL AND COALESCE(curation_status,'')!='rejected'",
            (a,),
        )
    }
    refs_b = {
        r["reference_id"]
        for r in conn.execute(
            "SELECT DISTINCT reference_id FROM evidence_records WHERE virus_master_id=? AND reference_id IS NOT NULL AND COALESCE(curation_status,'')!='rejected'",
            (b,),
        )
    }
    return {
        "a": a,
        "b": b,
        "a_refs": len(refs_a),
        "b_refs": len(refs_b),
        "overlap": len(refs_a & refs_b),
        "a_only": len(refs_a - refs_b),
        "b_only": len(refs_b - refs_a),
    }


def apply(conn) -> dict:
    note = (
        "follow-up audit: AVNV shell is ambiguous, has no isolates, and has high "
        "reference overlap with master_id 548; kept as limited unconfirmed candidate "
        "pending manual taxonomic review."
    )
    cur = conn.execute(
        """
        UPDATE virus_master
        SET is_crustacean_virus=0,
            entry_type='unconfirmed_candidate',
            public_visibility='limited',
            notes=CASE
                WHEN notes IS NULL OR notes='' THEN ?
                WHEN notes LIKE '%' || ? || '%' THEN notes
                ELSE notes || '; ' || ?
            END
        WHERE master_id=1307
        """,
        (note, "follow-up audit: AVNV shell is ambiguous", note),
    )
    conn.execute(
        """
        INSERT INTO curation_logs
            (entity_type, entity_id, action, old_value, new_value, confidence, curator, notes)
        VALUES ('virus_master', 1307, 'demote_ambiguous_avnv_shell',
                'active target complete_genome', 'limited unconfirmed_candidate', 'high',
                'fix_third_round_followup_avnv.py', ?)
        """,
        (note,),
    )
    conn.execute(
        """
        INSERT INTO database_maintenance_log (action, details_json)
        VALUES ('third_round_followup_avnv_demotion', ?)
        """,
        (json.dumps({"master_id": 1307, "changed_rows": cur.rowcount, "note": note}, ensure_ascii=False),),
    )
    return {"demoted_1307": cur.rowcount}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=str(DB_PATH))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    ts = stamp()
    with db_connection(args.db, read_only=True) as conn:
        before = metrics(conn)
        overlap = ref_overlap(conn, 1307, 548)

    changed = {}
    if not args.dry_run:
        backup_database(args.db, label="before_third_round_followup_avnv")
        with db_transaction(args.db) as conn:
            changed = apply(conn)

    with db_connection(args.db, read_only=True) as conn:
        after = metrics(conn)

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    path = REPORTS_DIR / f"third_round_followup_avnv_{ts}.json"
    path.write_text(
        json.dumps(
            {
                "timestamp": ts,
                "dry_run": args.dry_run,
                "before": before,
                "after": after,
                "changed": changed,
                "reference_overlap_1307_548": overlap,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"dry_run={args.dry_run}")
    print(f"report={path}")
    print(json.dumps({"before": before, "after": after, "changed": changed, "overlap": overlap}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
