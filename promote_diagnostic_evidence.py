#!/usr/bin/env python3
"""Promote diagnosis evidence into diagnostic_methods conservatively."""

from __future__ import annotations

import csv
import datetime as dt
import json
import re
import shutil
import sqlite3
from pathlib import Path


APP_DIR = Path(__file__).resolve().parent
DB_PATH = APP_DIR / "crustacean_virus_core.db"
BACKUP_DIR = APP_DIR / "backups"
REPORT_DIR = APP_DIR / "reports"


def stamp() -> str:
    return dt.datetime.now().strftime("%Y%m%d_%H%M%S")


def backup_database() -> Path:
    BACKUP_DIR.mkdir(exist_ok=True)
    backup = BACKUP_DIR / f"crustacean_virus_core_before_diagnostic_promotion_{stamp()}.db"
    shutil.copy2(DB_PATH, backup)
    return backup


def norm(text: str | None) -> str:
    text = (text or "").lower()
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def aliases(row: sqlite3.Row) -> list[str]:
    out = [row["canonical_name"] or ""]
    out.extend(re.split(r"[,;/|]+", row["abbreviations"] or ""))
    return [x.strip() for x in out if x and len(x.strip()) >= 3]


def title_matches_virus(title: str, virus: sqlite3.Row) -> bool:
    ntitle = norm(title)
    utitle = title.upper()
    for alias in aliases(virus):
        nalias = norm(alias)
        if len(nalias) > 6 and nalias in ntitle:
            return True
        if alias.isupper() and re.search(rf"\b{re.escape(alias)}\b", utitle):
            return True
    return False


def infer_method(title: str) -> tuple[str, str, str, int, int] | None:
    lower = title.lower()
    clean = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", title)).strip()
    field_deployable = 1 if any(k in lower for k in ["lateral flow", "visual", "rapid", "colorimetric", "strip"]) else 0
    visual = 1 if any(k in lower for k in ["lateral flow", "visual", "colorimetric", "turbidimetric", "strip"]) else 0

    if "crispr" in lower:
        sub = "crispr-cas12a" if "cas12a" in lower else ("crispr-cas13" if "cas13" in lower else "crispr-cas")
        return "crispr_cas", sub, clean[:180], field_deployable, visual
    if "in situ hybridization" in lower or "in-situ hybridization" in lower:
        return "nucleic_acid_hybridization", "in-situ-hybridization", clean[:180], field_deployable, visual
    if "loop-mediated isothermal amplification" in lower or "lamp" in lower:
        sub = "rt-lamp" if "rt-" in lower or "reverse transcription" in lower else "lamp"
        return "nucleic_acid_amplification", sub, clean[:180], field_deployable, visual
    if "raa" in lower or "rpa" in lower or "mira" in lower:
        sub = "rpa" if "rpa" in lower else ("raa" if "raa" in lower else "mira")
        return "nucleic_acid_amplification", sub, clean[:180], field_deployable, visual
    if "taqman" in lower or "real-time" in lower or "qpcr" in lower or "quantitative real-time" in lower:
        return "nucleic_acid_amplification", "qpcr", clean[:180], field_deployable, visual
    if "rt-pcr" in lower or "reverse transcriptase" in lower or "reverse transcription" in lower:
        return "nucleic_acid_amplification", "rt-pcr", clean[:180], field_deployable, visual
    if re.search(r"\bpcr\b", lower):
        return "nucleic_acid_amplification", "pcr", clean[:180], field_deployable, visual
    if "aptamer" in lower or "aptasensor" in lower:
        return "immunoassay", "aptasensor", clean[:180], field_deployable, visual
    if "immunohistochemical" in lower or "immunohistochemistry" in lower:
        return "immunoassay", "immunohistochemistry", clean[:180], field_deployable, visual
    return None


def ensure_log(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS diagnostic_evidence_promotion_log (
            log_id INTEGER PRIMARY KEY AUTOINCREMENT,
            action TEXT NOT NULL,
            details_json TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )


def candidate_rows(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            """
            SELECT DISTINCT
                er.evidence_id, er.virus_master_id, er.reference_id,
                vm.canonical_name, vm.abbreviations,
                rl.title, rl.year, rl.pmid, rl.doi
            FROM evidence_records er
            JOIN virus_master vm ON vm.master_id = er.virus_master_id
            JOIN ref_literatures rl ON rl.reference_id = er.reference_id
            WHERE er.evidence_type = 'diagnosis'
              AND er.reference_id IS NOT NULL
              AND vm.is_crustacean_virus = 1
              AND vm.entry_type NOT IN ('non_target', 'host_genome')
            ORDER BY er.evidence_id
            """
        )
    )


def update_existing(conn: sqlite3.Connection, row: sqlite3.Row, method: tuple[str, str, str, int, int]) -> int:
    category, subcategory, _method_name, _field, _visual = method
    cur = conn.execute(
        """
        SELECT method_id
        FROM diagnostic_methods
        WHERE virus_master_id = ?
          AND data_quality = 'curated'
          AND reference_id IS NULL
          AND (
              method_subcategory = ?
              OR lower(method_name) LIKE '%' || lower(?) || '%'
          )
        ORDER BY method_id
        LIMIT 1
        """,
        (row["virus_master_id"], subcategory, subcategory.replace("-", " ")),
    ).fetchone()
    if not cur:
        return 0
    conn.execute(
        """
        UPDATE diagnostic_methods
        SET reference_id = ?,
            notes = trim(COALESCE(notes, '') || ' | diagnostic_reference_promoted_from_evidence:' || ?)
        WHERE method_id = ?
        """,
        (row["reference_id"], row["evidence_id"], cur["method_id"]),
    )
    return 1


def insert_candidate(conn: sqlite3.Connection, row: sqlite3.Row, method: tuple[str, str, str, int, int]) -> int:
    category, subcategory, method_name, field, visual = method
    exists = conn.execute(
        """
        SELECT 1
        FROM diagnostic_methods
        WHERE virus_master_id = ?
          AND method_category = ?
          AND method_name = ?
          AND COALESCE(reference_id, -1) = ?
        """,
        (row["virus_master_id"], category, method_name, row["reference_id"]),
    ).fetchone()
    if exists:
        return 0
    conn.execute(
        """
        INSERT INTO diagnostic_methods(
            virus_master_id, method_category, method_subcategory, method_name,
            field_deployable, visual_readout, reference_id, evidence_strength,
            curation_status, notes, data_quality
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, 'medium', 'needs_review', ?, 'curated')
        """,
        (
            row["virus_master_id"],
            category,
            subcategory,
            method_name,
            field,
            visual,
            row["reference_id"],
            f"Auto-promoted from diagnosis evidence_id={row['evidence_id']}; verify target gene/sample/detection limit before manual_checked.",
        ),
    )
    return 1


def write_review_csv(rows: list[dict], path: Path) -> None:
    path.parent.mkdir(exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["evidence_id", "virus", "reference_id", "year", "pmid", "doi", "title", "reason"],
        )
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    backup = backup_database()
    review_rows: list[dict] = []
    details = {"backup": str(backup)}
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        with conn:
            ensure_log(conn)
            inserted = 0
            updated = 0
            considered = 0
            skipped = 0
            for row in candidate_rows(conn):
                considered += 1
                method = infer_method(row["title"] or "")
                reason = ""
                if not method:
                    reason = "no_supported_method_keyword"
                elif not title_matches_virus(row["title"] or "", row):
                    reason = "title_does_not_match_target_virus"
                if reason:
                    skipped += 1
                    review_rows.append(
                        {
                            "evidence_id": row["evidence_id"],
                            "virus": row["canonical_name"],
                            "reference_id": row["reference_id"],
                            "year": row["year"],
                            "pmid": row["pmid"],
                            "doi": row["doi"],
                            "title": row["title"],
                            "reason": reason,
                        }
                    )
                    continue
                updated += update_existing(conn, row, method)
                inserted += insert_candidate(conn, row, method)
            review_path = REPORT_DIR / f"diagnostic_evidence_review_{stamp()}.csv"
            write_review_csv(review_rows, review_path)
            details.update(
                {
                    "considered": considered,
                    "existing_curated_reference_filled": updated,
                    "new_diagnostic_candidates_inserted": inserted,
                    "skipped_for_review": skipped,
                    "review_csv": str(review_path),
                    "integrity_check": conn.execute("PRAGMA integrity_check").fetchone()[0],
                    "foreign_key_violations": len(conn.execute("PRAGMA foreign_key_check").fetchall()),
                    "curated_methods_with_reference": conn.execute(
                        "SELECT COUNT(*) FROM diagnostic_methods WHERE data_quality='curated' AND reference_id IS NOT NULL"
                    ).fetchone()[0],
                }
            )
            conn.execute(
                "INSERT INTO diagnostic_evidence_promotion_log(action, details_json) VALUES (?, ?)",
                ("promote_diagnostic_evidence", json.dumps(details, ensure_ascii=False, sort_keys=True)),
            )
    print(json.dumps(details, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
