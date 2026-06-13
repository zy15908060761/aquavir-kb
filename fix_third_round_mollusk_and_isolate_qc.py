#!/usr/bin/env python3
"""
Third audit round deterministic fixes.

Fixes:
- Reactivate important mollusk target viruses incorrectly flagged as non-target.
- Merge the lowercase "ostreid herpesvirus" duplicate evidence shell into
  "Ostreid herpesvirus 1" and archive the duplicate.
- Normalize raw genome_type values in isolate tables.
- Normalize evidence_records.created_at values that used YYYYMMDD_HHMMSS.

Non-fixes:
- Empty tables are reported but not dropped, because code may rely on their
  existence as work queues.
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

OSHV_DUPLICATE_SOURCE = 1303
OSHV_CANONICAL_TARGET = 1304
REACTIVATE_TARGETS = {
    1304: "Ostreid herpesvirus 1 is a target mollusk virus with isolate-backed OsHV-1 records.",
    1307: "Acute viral necrosis virus is a target scallop/mollusk virus with evidence-backed records.",
}


def stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def scalar(conn, sql: str, params: tuple[Any, ...] = ()) -> int:
    return int(conn.execute(sql, params).fetchone()[0])


def collect_metrics(conn) -> dict[str, Any]:
    return {
        "active_target_masters": scalar(
            conn,
            """
            SELECT COUNT(*) FROM virus_master
            WHERE is_crustacean_virus=1
              AND entry_type NOT IN ('non_target','ictv_non_target','duplicate_ictv_vmr_placeholder','duplicate_alias_placeholder')
            """,
        ),
        "master_1304_is_cv": scalar(conn, "SELECT is_crustacean_virus FROM virus_master WHERE master_id=1304"),
        "master_1307_is_cv": scalar(conn, "SELECT is_crustacean_virus FROM virus_master WHERE master_id=1307"),
        "master_1303_is_cv": scalar(conn, "SELECT is_crustacean_virus FROM virus_master WHERE master_id=1303"),
        "master_1304_evidence": scalar(conn, "SELECT COUNT(*) FROM evidence_records WHERE virus_master_id=1304"),
        "master_1303_evidence": scalar(conn, "SELECT COUNT(*) FROM evidence_records WHERE virus_master_id=1303"),
        "master_1307_evidence": scalar(conn, "SELECT COUNT(*) FROM evidence_records WHERE virus_master_id=1307"),
        "master_1304_ati": scalar(conn, "SELECT COUNT(*) FROM analysis_target_isolates WHERE master_id=1304"),
        "ati_nonstandard_genome_type": {
            row["genome_type"]: row["n"]
            for row in conn.execute(
                """
                SELECT genome_type, COUNT(*) n
                FROM analysis_target_isolates
                WHERE genome_type IN ('RNA','DNA','mRNA')
                GROUP BY genome_type
                """
            ).fetchall()
        },
        "viral_isolates_nonstandard_genome_type": {
            row["genome_type"]: row["n"]
            for row in conn.execute(
                """
                SELECT genome_type, COUNT(*) n
                FROM viral_isolates
                WHERE genome_type IN ('RNA','DNA','mRNA')
                GROUP BY genome_type
                """
            ).fetchall()
        },
        "evidence_created_at_yyyymmdd": scalar(
            conn,
            """
            SELECT COUNT(*) FROM evidence_records
            WHERE created_at GLOB '[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]_[0-9][0-9][0-9][0-9][0-9][0-9]'
            """,
        ),
    }


def empty_tables(conn) -> list[dict[str, Any]]:
    out = []
    for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    ).fetchall():
        name = row["name"]
        try:
            n = scalar(conn, f'SELECT COUNT(*) FROM "{name}"')
        except Exception as exc:  # pragma: no cover - diagnostic only
            out.append({"table": name, "error": str(exc)})
            continue
        if n == 0:
            out.append({"table": name, "row_count": 0})
    return out


def reference_overlap(conn, a: int, b: int) -> dict[str, Any]:
    refs_a = {
        r["reference_id"]
        for r in conn.execute(
            "SELECT DISTINCT reference_id FROM evidence_records WHERE virus_master_id=? AND reference_id IS NOT NULL",
            (a,),
        ).fetchall()
    }
    refs_b = {
        r["reference_id"]
        for r in conn.execute(
            "SELECT DISTINCT reference_id FROM evidence_records WHERE virus_master_id=? AND reference_id IS NOT NULL",
            (b,),
        ).fetchall()
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


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        if rows:
            writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
        else:
            fh.write("status\nempty\n")


def normalize_created_at(value: str) -> str | None:
    m = re.fullmatch(r"(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})", value or "")
    if not m:
        return None
    y, mo, d, h, mi, s = m.groups()
    return f"{y}-{mo}-{d} {h}:{mi}:{s}"


def apply_fixes(conn) -> dict[str, int]:
    changed: dict[str, int] = {}

    for master_id, reason in REACTIVATE_TARGETS.items():
        cur = conn.execute(
            """
            UPDATE virus_master
            SET is_crustacean_virus=1,
                public_visibility=CASE
                    WHEN COALESCE(public_visibility,'public') IN ('internal','internal_only','hidden') THEN 'public'
                    ELSE COALESCE(public_visibility,'public')
                END,
                notes=CASE
                    WHEN notes IS NULL OR notes='' THEN ?
                    WHEN notes LIKE '%' || ? || '%' THEN notes
                    ELSE notes || '; ' || ?
                END
            WHERE master_id=?
            """,
            (
                f"Third audit fix: {reason}",
                "Third audit fix:",
                f"Third audit fix: {reason}",
                master_id,
            ),
        )
        changed[f"reactivated_master_{master_id}"] = cur.rowcount
        conn.execute(
            """
            INSERT INTO curation_logs
                (entity_type, entity_id, action, old_value, new_value, confidence, curator, notes)
            VALUES ('virus_master', ?, 'reactivate_mollusk_target', 'is_crustacean_virus=0',
                    'is_crustacean_virus=1', 'high',
                    'fix_third_round_mollusk_and_isolate_qc.py', ?)
            """,
            (master_id, reason),
        )

    cur = conn.execute(
        """
        UPDATE evidence_records
        SET virus_master_id=?,
            notes=CASE
                WHEN notes IS NULL OR notes='' THEN ?
                WHEN notes LIKE '%' || ? || '%' THEN notes
                ELSE notes || '; ' || ?
            END,
            updated_at=CURRENT_TIMESTAMP
        WHERE virus_master_id=?
        """,
        (
            OSHV_CANONICAL_TARGET,
            f"Reassigned from duplicate lowercase OsHV shell master_id {OSHV_DUPLICATE_SOURCE}.",
            f"duplicate lowercase OsHV shell master_id {OSHV_DUPLICATE_SOURCE}",
            f"Reassigned from duplicate lowercase OsHV shell master_id {OSHV_DUPLICATE_SOURCE}.",
            OSHV_DUPLICATE_SOURCE,
        ),
    )
    changed["osHV_duplicate_evidence_reassigned"] = cur.rowcount

    conn.execute(
        """
        UPDATE virus_master
        SET canonical_name='ostreid herpesvirus duplicate of Ostreid herpesvirus 1',
            is_crustacean_virus=0,
            entry_type='duplicate_alias_placeholder',
            public_visibility='internal',
            notes=CASE
                WHEN notes IS NULL OR notes='' THEN ?
                ELSE notes || '; ' || ?
            END
        WHERE master_id=?
        """,
        (
            f"Third audit fix: duplicate lowercase OsHV shell merged into master_id {OSHV_CANONICAL_TARGET}.",
            f"Third audit fix: duplicate lowercase OsHV shell merged into master_id {OSHV_CANONICAL_TARGET}.",
            OSHV_DUPLICATE_SOURCE,
        ),
    )

    conn.execute(
        """
        INSERT INTO virus_aliases
            (master_id, alias, alias_type, match_status, confidence, is_preferred, notes)
        SELECT ?, 'ostreid herpesvirus', 'manual_alias', 'manual_checked', 'high', 0, ?
        WHERE NOT EXISTS (
            SELECT 1 FROM virus_aliases WHERE master_id=? AND alias='ostreid herpesvirus'
        )
        """,
        (
            OSHV_CANONICAL_TARGET,
            f"Alias preserved from archived duplicate master_id {OSHV_DUPLICATE_SOURCE}.",
            OSHV_CANONICAL_TARGET,
        ),
    )

    conn.execute(
        """
        INSERT INTO curation_logs
            (entity_type, entity_id, action, old_value, new_value, confidence, curator, notes)
        VALUES ('virus_master', ?, 'merge_duplicate_oshv_shell',
                'ostreid herpesvirus', 'Ostreid herpesvirus 1', 'high',
                'fix_third_round_mollusk_and_isolate_qc.py',
                'Evidence records reassigned; duplicate shell archived.')
        """,
        (OSHV_DUPLICATE_SOURCE,),
    )

    # analysis_target_isolates is a view over viral_isolates, so update the
    # base table once; the view reflects these normalized values.
    genome_updates = [
        ("RNA", "ssRNA"),
        ("DNA", "dsDNA"),
        ("mRNA", None),
    ]
    for old, new in genome_updates:
        cur = conn.execute(
            """
            UPDATE viral_isolates
            SET genome_type=?
            WHERE genome_type=?
            """,
            (new, old),
        )
        changed[f"viral_isolates_{old}_to_{new or 'NULL'}"] = cur.rowcount

    rows = conn.execute(
        """
        SELECT evidence_id, created_at
        FROM evidence_records
        WHERE created_at GLOB '[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]_[0-9][0-9][0-9][0-9][0-9][0-9]'
        """
    ).fetchall()
    fixed_dates = 0
    for row in rows:
        new_value = normalize_created_at(row["created_at"])
        if new_value:
            conn.execute(
                "UPDATE evidence_records SET created_at=? WHERE evidence_id=?",
                (new_value, row["evidence_id"]),
            )
            fixed_dates += 1
    changed["evidence_created_at_normalized"] = fixed_dates

    conn.execute(
        """
        INSERT INTO database_maintenance_log (action, details_json)
        VALUES ('third_round_mollusk_and_isolate_qc', ?)
        """,
        (json.dumps(changed, ensure_ascii=False),),
    )
    return changed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=str(DB_PATH), help="SQLite database path")
    parser.add_argument("--dry-run", action="store_true", help="Report only; do not write")
    args = parser.parse_args()

    ts = stamp()
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    with db_connection(args.db, read_only=True) as conn:
        before = collect_metrics(conn)
        overlaps = [
            reference_overlap(conn, 1303, 1304),
            reference_overlap(conn, 1304, 546),
            reference_overlap(conn, 1307, 1304),
        ]
        empty = empty_tables(conn)
        write_csv(REPORTS_DIR / f"empty_tables_review_{ts}.csv", empty)

    changed: dict[str, int] = {}
    if not args.dry_run:
        backup_database(args.db, label="before_third_round_mollusk_isolate_qc")
        with db_transaction(args.db) as conn:
            changed = apply_fixes(conn)

    with db_connection(args.db, read_only=True) as conn:
        after = collect_metrics(conn)

    summary_path = REPORTS_DIR / f"third_round_mollusk_isolate_qc_summary_{ts}.json"
    summary_path.write_text(
        json.dumps(
            {
                "timestamp": ts,
                "dry_run": args.dry_run,
                "before": before,
                "after": after,
                "changed": changed,
                "reference_overlaps": overlaps,
                "empty_tables_review": str(REPORTS_DIR / f"empty_tables_review_{ts}.csv"),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"dry_run={args.dry_run}")
    print(f"summary={summary_path}")
    print(json.dumps({"before": before, "after": after, "changed": changed}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
