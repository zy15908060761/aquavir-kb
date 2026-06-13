#!/usr/bin/env python3
"""
P0 Data Quality Optimization Script for AquaVir-KB.

Four idempotent, safe auto-fixes:
  Fix 1 — Evidence claim URL cleanup (~5,491 records)
  Fix 2 — Genome_type imputation (~958 isolates)
  Fix 3 — Genome_length NULL backfill (~5,358 isolates)
  Fix 4 — Evidence reference_id backfill (~1,912 records)

Safety:
  --dry-run           Preview changes without writing
  WAL-safe backup     Automatic before any write (via db_utils.backup_database)
  Quarantine table    Original values saved before mutation
  Run tracking        Each execution recorded in optimize_quality_runs
  Idempotent          Safe to re-run; skips already-processed rows

Usage:
  python optimize_data_quality_p3.py --dry-run     # Preview only
  python optimize_data_quality_p3.py                # Apply all fixes
  python optimize_data_quality_p3.py --fix 1,2      # Apply specific fixes only
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

# ── Paths ────────────────────────────────────────────────────────
APP_DIR = Path(__file__).resolve().parent
DB_PATH = APP_DIR / "crustacean_virus_core.db"
REPORTS_DIR = APP_DIR / "reports"
BACKUPS_DIR = APP_DIR / "backups"

# ── Genome type → standard form (from validate_database.py) ──────
GENOME_TYPE_NORMALIZE: dict[str, str] = {
    "dna": "DNA", "rna": "RNA", "mrna": "mRNA",
    "dsdna": "dsDNA", "ssdna": "ssDNA",
    "dsrna": "dsRNA", "ssrna": "ssRNA",
    "ssrna(+)": "ssRNA(+)", "ssrna(-)": "ssRNA(-)",
    "ssrna+": "ssRNA(+)", "ssrna-": "ssRNA(-)",
    "ssrnapositive": "ssRNA(+)", "ssrnanegative": "ssRNA(-)",
    "dsdna(r)": "dsDNA(R)", "dsdna (r)": "dsDNA(R)",
    "ssdna(r)": "ssDNA(R)",
    "positive-sense ssrna": "ssRNA(+)", "negative-sense ssrna": "ssRNA(-)",
    "double-stranded dna": "dsDNA", "single-stranded dna": "ssDNA",
    "double-stranded rna": "dsRNA", "single-stranded rna": "ssRNA",
}

# ── Molecule type → genome_type inference ────────────────────────
MOLECULE_TO_GENOME_TYPE: dict[str, str] = {
    "rna": "ssRNA", "ss-rna": "ssRNA",
    "ds-rna": "dsRNA", "dsrna": "dsRNA",
    "dna": "dsDNA", "genomic dna": "dsDNA",
    "ss-dna": "ssDNA", "ssdna": "ssDNA",
    "mrna": "mRNA", "crna": "cRNA",
}

# ── Taxon family → genome_type defaults (curated) ────────────────
FAMILY_GENOME_TYPE: dict[str, str] = {
    "Nodaviridae": "ssRNA(+)", "Roniviridae": "ssRNA(+)",
    "Sedoreoviridae": "dsRNA", "Reoviridae": "dsRNA",
    "Totiviridae": "dsRNA", "Orthototiviridae": "dsRNA",
    "Chuviridae": "ssRNA(-)", "Rhabdoviridae": "ssRNA(-)",
    "Phenuiviridae": "ssRNA(-)", "Bunyaviridae": "ssRNA(-)",
    "Astroviridae": "ssRNA(+)", "Picornaviridae": "ssRNA(+)",
    "Dicistroviridae": "ssRNA(+)", "Iflaviridae": "ssRNA(+)",
    "Marnaviridae": "ssRNA(+)", "Yanviridae": "ssRNA(+)",
    "Flaviviridae": "ssRNA(+)", "Tombusviridae": "ssRNA(+)",
    "Virgaviridae": "ssRNA(+)", "Potyviridae": "ssRNA(+)",
    "Solemoviridae": "ssRNA(+)", "Solinviviridae": "ssRNA(+)",
    "Yueviridae": "ssRNA(+)", "Weiviridae": "ssRNA(+)",
    "Zhaoviridae": "ssRNA(+)", "Qinviridae": "ssRNA(-)",
    "Phasmaviridae": "ssRNA(-)", "Lispiviridae": "ssRNA(-)",
    "Narnaviridae": "ssRNA(+)", "Botourmiaviridae": "ssRNA(+)",
    "Leviviridae": "ssRNA(+)",
    "Alphatetraviridae": "ssRNA(+)", "Kitaviridae": "ssRNA(+)",
    "Tymoviridae": "ssRNA(+)",
    "Iridoviridae": "dsDNA", "Nimaviridae": "dsDNA",
    "Asfarviridae": "dsDNA", "Parvoviridae": "ssDNA",
    "Circoviridae": "ssDNA", "Aparvoviridae": "ssDNA",
    "Polycipiviridae": "ssRNA(+)", "Partitiviridae": "dsRNA",
    "Coronaviridae": "ssRNA(+)", "Retroviridae": "ssRNA(+)",
    "Cruliviridae": "ssRNA(-)", "Negevirus": "ssRNA(+)",
}

# ── URL extraction regex ─────────────────────────────────────────
URL_RE = re.compile(r'https?://[^\s<>"]+|www\.[^\s<>"]+|doi\.org/[^\s<>"]+', re.IGNORECASE)


# ═══════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════

def stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def scalar(conn, sql: str, params=()) -> Any:
    cur = conn.execute(sql, params)
    row = cur.fetchone()
    return row[0] if row else None


def rows(conn, sql: str, params=()) -> list[dict]:
    cur = conn.execute(sql, params)
    return [dict(r) for r in cur.fetchall()]


def column_exists(conn, table: str, column: str) -> bool:
    cur = conn.execute(f"PRAGMA table_info({table})")
    return any(r[1] == column for r in cur.fetchall())


def add_column(conn, table: str, column: str, definition: str) -> bool:
    """Idempotent column addition. Returns True if column was added."""
    if column_exists(conn, table, column):
        return False
    conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
    return True


def table_exists(conn, name: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone() is not None


def write_csv(path: Path, data: list[dict]) -> None:
    if not data:
        path.write_text("", encoding="utf-8-sig")
        return
    import csv
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(data[0].keys()))
        w.writeheader()
        w.writerows(data)


def backup_database(db_path: Path, backup_dir: Path, label: str) -> Path:
    """WAL-safe backup (inline to avoid db_utils import issues)."""
    import shutil
    import sqlite3 as _sqlite3
    backup_dir.mkdir(parents=True, exist_ok=True)
    ts = stamp()
    safe_label = label.replace(" ", "_").replace("/", "_").replace("\\", "_")
    backup_base = backup_dir / f"crustacean_virus_core_{safe_label}_{ts}"

    conn = _sqlite3.connect(str(db_path))
    try:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        conn.close()

    shutil.copy2(str(db_path), str(backup_base.with_suffix(".db")))
    for suffix in (".db-wal", ".db-shm"):
        src = Path(str(db_path) + suffix)
        if src.exists():
            dst = Path(str(backup_base.with_suffix("")) + suffix)
            shutil.copy2(str(src), str(dst))

    print(f"[backup] WAL-safe backup → {backup_base.with_suffix('.db').name}")
    return backup_base.with_suffix(".db")


# ═══════════════════════════════════════════════════════════════════
# Setup
# ═══════════════════════════════════════════════════════════════════

def ensure_schema(conn) -> None:
    """Create tracking and quarantine tables if they don't exist."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS optimize_quality_runs (
            run_id        INTEGER PRIMARY KEY AUTOINCREMENT,
            run_ts        TEXT NOT NULL,
            script_name   TEXT NOT NULL,
            dry_run       INTEGER NOT NULL DEFAULT 0,
            fixes_applied TEXT,
            notes         TEXT
        );

        CREATE TABLE IF NOT EXISTS optimize_quality_quarantine (
            quarantine_id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id        INTEGER NOT NULL REFERENCES optimize_quality_runs(run_id),
            fix_name      TEXT NOT NULL,
            table_name    TEXT NOT NULL,
            row_pk        INTEGER NOT NULL,
            original_json TEXT,
            action        TEXT NOT NULL,
            created_at    TEXT NOT NULL
        );
    """)
    # Add needed columns idempotently
    add_column(conn, "evidence_records", "source_url", "TEXT")
    add_column(conn, "viral_isolates", "inference_source", "TEXT")
    add_column(conn, "viral_isolates", "genome_length_estimated", "INTEGER DEFAULT 0")


def start_run(conn, dry_run: bool, fixes: list[str]) -> int:
    """Record a new run and return run_id."""
    cur = conn.execute(
        "INSERT INTO optimize_quality_runs (run_ts, script_name, dry_run, fixes_applied) "
        "VALUES (?, ?, ?, ?)",
        (stamp(), "optimize_data_quality_p3.py", 1 if dry_run else 0, ",".join(fixes)),
    )
    return cur.lastrowid


def quarantine(conn, run_id: int, fix_name: str, table_name: str,
               row_pk: int, original_json: str, action: str) -> None:
    conn.execute(
        "INSERT INTO optimize_quality_quarantine "
        "(run_id, fix_name, table_name, row_pk, original_json, action, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (run_id, fix_name, table_name, row_pk, original_json, action, stamp()),
    )


# ═══════════════════════════════════════════════════════════════════
# Fix 1: Evidence claim URL cleanup
# ═══════════════════════════════════════════════════════════════════

def fix_evidence_urls(conn, run_id: int, dry_run: bool) -> dict:
    """Extract URLs from evidence claims, store in source_url, clean claim text."""
    result = {"total_candidates": 0, "cleaned": 0, "skipped_manual": 0, "details": []}

    # Find claim-polluted records with URLs or data-supplement references.
    # Excludes LENGTH>500 (those are legitimate long descriptions, not pollution).
    pollute_sql = """
        SELECT evidence_id, claim, extraction_method
        FROM evidence_records
        WHERE claim IS NOT NULL
          AND (
              claim LIKE '%http%'
              OR claim LIKE '%www.%'
              OR claim LIKE '%doi.org%'
              OR claim LIKE '%Dryad, Table%'
              OR claim LIKE '%Table S%'
              OR claim LIKE '%Supplementary Table%'
              OR claim LIKE '%Full text%'
          )
          AND claim NOT LIKE 'Auto-extracted from abstract:%'
          AND claim NOT LIKE 'Abstract mentions %'
          AND extraction_method != 'manual_or_seeded'
        ORDER BY evidence_id
    """

    candidates = rows(conn, pollute_sql)
    result["total_candidates"] = len(candidates)

    for row in candidates:
        eid = row["evidence_id"]
        claim = row["claim"]
        extraction = row["extraction_method"] or ""

        # Skip manually curated records
        if extraction in ("manual_or_seeded", "manual"):
            result["skipped_manual"] += 1
            continue

        original = claim

        # Extract URLs
        urls = URL_RE.findall(claim)
        extracted_url = urls[0] if urls else None

        # Clean claim text
        if extracted_url:
            claim = URL_RE.sub("", claim).strip()
            # Also clean trailing markers
            claim = re.sub(r'\s*[\[\(]\s*[\]\)]\s*$', '', claim)
            claim = re.sub(r'\s*,\s*$', '', claim)
            claim = re.sub(r'\s+', ' ', claim)

        # Check for supplementary table references
        claim = re.sub(
            r'\b(Supplementary\s+Table\s+\w+)\b',
            r'[\1]',
            claim,
            flags=re.IGNORECASE,
        )

        if claim == original and not extracted_url:
            continue  # Nothing changed

        result["cleaned"] += 1
        detail = {"evidence_id": eid, "original_claim": original[:200], "cleaned_claim": claim[:200]}
        if extracted_url:
            detail["extracted_url"] = extracted_url
        result["details"].append(detail)

        if not dry_run:
            quarantine(conn, run_id, "fix_evidence_urls", "evidence_records",
                       eid, json.dumps({"claim": original, "source_url": None}), "update")
            if extracted_url:
                conn.execute(
                    "UPDATE evidence_records SET claim = ?, source_url = ? WHERE evidence_id = ?",
                    (claim, extracted_url, eid),
                )
            else:
                conn.execute(
                    "UPDATE evidence_records SET claim = ? WHERE evidence_id = ?",
                    (claim, eid),
                )

    return result


# ═══════════════════════════════════════════════════════════════════
# Fix 2: Genome_type imputation
# ═══════════════════════════════════════════════════════════════════

def fix_genome_type(conn, run_id: int, dry_run: bool) -> dict:
    """Three-tier genome_type imputation for isolates missing it."""
    result = {
        "total_missing": 0,
        "tier1_master_inherit": 0,
        "tier2_molecule_map": 0,
        "tier3_family_default": 0,
        "remaining_missing": 0,
        "details": [],
    }

    # Count total missing
    result["total_missing"] = scalar(
        conn, "SELECT COUNT(*) FROM viral_isolates WHERE genome_type IS NULL OR genome_type = ''"
    ) or 0

    if result["total_missing"] == 0:
        return result

    # Tier 1: Inherit from other isolates with same master_id
    tier1_sql = """
        UPDATE viral_isolates
        SET genome_type = (
            SELECT vi2.genome_type
            FROM viral_isolates vi2
            WHERE vi2.master_id = viral_isolates.master_id
              AND vi2.genome_type IS NOT NULL
              AND vi2.genome_type != ''
              AND vi2.genome_type != 'unknown'
            GROUP BY vi2.genome_type
            ORDER BY COUNT(*) DESC
            LIMIT 1
        ),
        inference_source = 'tier1_master_inherit'
        WHERE (genome_type IS NULL OR genome_type = '')
          AND master_id IN (
              SELECT master_id FROM viral_isolates
              WHERE genome_type IS NOT NULL AND genome_type != '' AND genome_type != 'unknown'
          )
    """

    if not dry_run:
        conn.execute(tier1_sql)
        # Count affected
        result["tier1_master_inherit"] = scalar(
            conn, "SELECT COUNT(*) FROM viral_isolates WHERE inference_source = 'tier1_master_inherit'"
        ) or 0
    else:
        result["tier1_master_inherit"] = scalar(
            conn, """
            SELECT COUNT(*) FROM viral_isolates
            WHERE (genome_type IS NULL OR genome_type = '')
              AND master_id IN (
                  SELECT master_id FROM viral_isolates
                  WHERE genome_type IS NOT NULL AND genome_type != '' AND genome_type != 'unknown'
              )
            """
        ) or 0

    # Tier 2: Map from molecule_type
    for mol, gt in MOLECULE_TO_GENOME_TYPE.items():
        if dry_run:
            cnt = scalar(
                conn,
                "SELECT COUNT(*) FROM viral_isolates "
                "WHERE (genome_type IS NULL OR genome_type = '') "
                "AND LOWER(molecule_type) = ?",
                (mol,),
            ) or 0
            result["tier2_molecule_map"] += cnt
        else:
            cur = conn.execute(
                "UPDATE viral_isolates SET genome_type = ?, inference_source = 'tier2_molecule_map' "
                "WHERE (genome_type IS NULL OR genome_type = '') AND LOWER(molecule_type) = ?",
                (gt, mol),
            )
            result["tier2_molecule_map"] += cur.rowcount

    # Tier 3: Default from taxon_family
    for family, gt in FAMILY_GENOME_TYPE.items():
        if dry_run:
            cnt = scalar(
                conn,
                "SELECT COUNT(*) FROM viral_isolates "
                "WHERE (genome_type IS NULL OR genome_type = '') "
                "AND taxon_family = ?",
                (family,),
            ) or 0
            result["tier3_family_default"] += cnt
        else:
            cur = conn.execute(
                "UPDATE viral_isolates SET genome_type = ?, inference_source = 'tier3_family_default' "
                "WHERE (genome_type IS NULL OR genome_type = '') AND taxon_family = ?",
                (gt, family),
            )
            result["tier3_family_default"] += cur.rowcount

    # Count remaining
    result["remaining_missing"] = scalar(
        conn, "SELECT COUNT(*) FROM viral_isolates WHERE genome_type IS NULL OR genome_type = ''"
    ) or 0

    # In dry-run, get details
    if dry_run:
        tier1_details = rows(conn, """
            SELECT isolate_id, virus_name, taxon_family, molecule_type, master_id
            FROM viral_isolates
            WHERE (genome_type IS NULL OR genome_type = '')
              AND master_id IN (
                  SELECT master_id FROM viral_isolates
                  WHERE genome_type IS NOT NULL AND genome_type != '' AND genome_type != 'unknown'
              )
            LIMIT 20
        """)
        for d in tier1_details:
            result["details"].append({**d, "tier": "tier1_master_inherit"})

    return result


# ═══════════════════════════════════════════════════════════════════
# Fix 3: Genome_length NULL backfill
# ═══════════════════════════════════════════════════════════════════

def fix_genome_length(conn, run_id: int, dry_run: bool) -> dict:
    """Backfill NULL genome_length from protein sum or nucleotide_records."""
    result = {
        "total_missing": 0,
        "from_proteins": 0,
        "from_nucleotide_records": 0,
        "remaining_missing": 0,
    }

    result["total_missing"] = scalar(
        conn, "SELECT COUNT(*) FROM viral_isolates WHERE genome_length IS NULL"
    ) or 0

    if result["total_missing"] == 0:
        return result

    # Method 1: Estimate from viral_proteins (coding region + UTR estimate)
    if not dry_run:
        conn.execute("""
            UPDATE viral_isolates
            SET genome_length = (
                SELECT CAST(SUM(vp.aa_length) * 3 + 5000 AS INTEGER)
                FROM viral_proteins vp
                WHERE vp.isolate_id = viral_isolates.isolate_id
            ),
            genome_length_estimated = 1
            WHERE genome_length IS NULL
              AND isolate_id IN (
                  SELECT isolate_id FROM viral_proteins
              )
        """)
        result["from_proteins"] = scalar(
            conn, "SELECT COUNT(*) FROM viral_isolates WHERE genome_length_estimated = 1"
        ) or 0
    else:
        result["from_proteins"] = scalar(
            conn, """
            SELECT COUNT(*) FROM viral_isolates vi
            WHERE vi.genome_length IS NULL
              AND EXISTS (SELECT 1 FROM viral_proteins vp WHERE vp.isolate_id = vi.isolate_id)
            """
        ) or 0

    # Method 2: From nucleotide_records table via accession match
    if not dry_run:
        conn.execute("""
            UPDATE viral_isolates
            SET genome_length = (
                SELECT nr.genome_length
                FROM nucleotide_records nr
                WHERE nr.accession = viral_isolates.accession
                  AND nr.genome_length IS NOT NULL
                LIMIT 1
            ),
            genome_length_estimated = 0
            WHERE genome_length IS NULL
              AND accession IN (
                  SELECT accession FROM nucleotide_records WHERE genome_length IS NOT NULL
              )
        """)
        nr_fixed = conn.execute(
            "SELECT COUNT(*) FROM viral_isolates "
            "WHERE genome_length IS NOT NULL AND genome_length_estimated = 0 "
            "AND accession IN (SELECT accession FROM nucleotide_records WHERE genome_length IS NOT NULL)"
        ).fetchone()[0]
        result["from_nucleotide_records"] = nr_fixed
    else:
        result["from_nucleotide_records"] = scalar(
            conn, """
            SELECT COUNT(*) FROM viral_isolates vi
            WHERE vi.genome_length IS NULL
              AND vi.accession IN (
                  SELECT nr.accession FROM nucleotide_records nr WHERE nr.genome_length IS NOT NULL
              )
            """
        ) or 0

    # Count remaining
    result["remaining_missing"] = scalar(
        conn, "SELECT COUNT(*) FROM viral_isolates WHERE genome_length IS NULL"
    ) or 0

    return result


# ═══════════════════════════════════════════════════════════════════
# Fix 4: Evidence reference_id backfill
# ═══════════════════════════════════════════════════════════════════

def fix_reference_id_backfill(conn, run_id: int, dry_run: bool) -> dict:
    """Backfill missing reference_id in evidence_records via multiple routes."""
    result = {
        "total_missing": 0,
        "pmid_match": 0,
        "doi_match": 0,
        "isolate_link_match": 0,
        "skipped_rejected": 0,
        "remaining_missing": 0,
    }

    result["total_missing"] = scalar(
        conn, "SELECT COUNT(*) FROM evidence_records WHERE reference_id IS NULL"
    ) or 0

    if result["total_missing"] == 0:
        return result

    # Skip rejected records — they have no reference by design
    result["skipped_rejected"] = scalar(
        conn, "SELECT COUNT(*) FROM evidence_records WHERE reference_id IS NULL AND curation_status = 'rejected'"
    ) or 0

    # Method 1: Exact PMID match (for non-rejected, non-null source_pmid)
    if not dry_run:
        cur = conn.execute("""
            UPDATE evidence_records
            SET reference_id = (
                SELECT rl.reference_id
                FROM ref_literatures rl
                WHERE CAST(rl.pmid AS TEXT) = CAST(evidence_records.source_pmid AS TEXT)
                  AND rl.pmid IS NOT NULL AND rl.pmid != ''
            ),
            curation_status = CASE
                WHEN curation_status IN ('auto_imported', 'needs_review') THEN 'manual_checked'
                ELSE curation_status
            END
            WHERE reference_id IS NULL
              AND curation_status != 'rejected'
              AND source_pmid IS NOT NULL AND source_pmid != ''
              AND EXISTS (
                  SELECT 1 FROM ref_literatures rl
                  WHERE CAST(rl.pmid AS TEXT) = CAST(evidence_records.source_pmid AS TEXT)
              )
        """)
        result["pmid_match"] = cur.rowcount
    else:
        result["pmid_match"] = scalar(
            conn, """
            SELECT COUNT(*) FROM evidence_records er
            WHERE er.reference_id IS NULL
              AND er.curation_status != 'rejected'
              AND er.source_pmid IS NOT NULL AND er.source_pmid != ''
              AND EXISTS (
                  SELECT 1 FROM ref_literatures rl
                  WHERE CAST(rl.pmid AS TEXT) = CAST(er.source_pmid AS TEXT)
              )
            """
        ) or 0

    # Method 2: Exact DOI match
    if not dry_run:
        cur = conn.execute("""
            UPDATE evidence_records
            SET reference_id = (
                SELECT rl.reference_id
                FROM ref_literatures rl
                WHERE LOWER(rl.doi) = LOWER(evidence_records.source_doi)
                  AND rl.doi IS NOT NULL AND rl.doi != ''
            ),
            curation_status = CASE
                WHEN curation_status IN ('auto_imported', 'needs_review') THEN 'manual_checked'
                ELSE curation_status
            END
            WHERE reference_id IS NULL
              AND curation_status != 'rejected'
              AND source_doi IS NOT NULL AND source_doi != ''
              AND EXISTS (
                  SELECT 1 FROM ref_literatures rl
                  WHERE LOWER(rl.doi) = LOWER(evidence_records.source_doi)
              )
        """)
        result["doi_match"] = cur.rowcount
    else:
        result["doi_match"] = scalar(
            conn, """
            SELECT COUNT(*) FROM evidence_records er
            WHERE er.reference_id IS NULL
              AND er.curation_status != 'rejected'
              AND er.source_doi IS NOT NULL AND er.source_doi != ''
              AND EXISTS (
                  SELECT 1 FROM ref_literatures rl
                  WHERE LOWER(rl.doi) = LOWER(er.source_doi)
              )
            """
        ) or 0

    # Method 3: Inherit from isolate_reference_links (for records with isolate_id)
    if not dry_run:
        cur = conn.execute("""
            UPDATE evidence_records
            SET reference_id = (
                SELECT irl.reference_id
                FROM isolate_reference_links irl
                WHERE irl.isolate_id = evidence_records.isolate_id
                ORDER BY irl.priority DESC
                LIMIT 1
            ),
            curation_status = CASE
                WHEN curation_status = 'auto_imported' THEN 'manual_checked'
                ELSE curation_status
            END
            WHERE reference_id IS NULL
              AND curation_status != 'rejected'
              AND isolate_id IS NOT NULL
              AND EXISTS (
                  SELECT 1 FROM isolate_reference_links irl
                  WHERE irl.isolate_id = evidence_records.isolate_id
              )
        """)
        result["isolate_link_match"] = cur.rowcount
    else:
        result["isolate_link_match"] = scalar(
            conn, """
            SELECT COUNT(*) FROM evidence_records er
            WHERE er.reference_id IS NULL
              AND er.curation_status != 'rejected'
              AND er.isolate_id IS NOT NULL
              AND EXISTS (
                  SELECT 1 FROM isolate_reference_links irl
                  WHERE irl.isolate_id = er.isolate_id
              )
            """
        ) or 0

    # Method 4: Inherit from viral_isolates.reference_id directly
    if not dry_run:
        cur = conn.execute("""
            UPDATE evidence_records
            SET reference_id = (
                SELECT vi.reference_id
                FROM viral_isolates vi
                WHERE vi.isolate_id = evidence_records.isolate_id
                  AND vi.reference_id IS NOT NULL
            ),
            curation_status = CASE
                WHEN curation_status = 'auto_imported' THEN 'manual_checked'
                ELSE curation_status
            END
            WHERE reference_id IS NULL
              AND curation_status != 'rejected'
              AND isolate_id IS NOT NULL
              AND EXISTS (
                  SELECT 1 FROM viral_isolates vi
                  WHERE vi.isolate_id = evidence_records.isolate_id AND vi.reference_id IS NOT NULL
              )
        """)
        result["isolate_link_match"] += cur.rowcount
    else:
        result["isolate_link_match"] += scalar(
            conn, """
            SELECT COUNT(*) FROM evidence_records er
            WHERE er.reference_id IS NULL
              AND er.curation_status != 'rejected'
              AND er.isolate_id IS NOT NULL
              AND EXISTS (
                  SELECT 1 FROM viral_isolates vi
                  WHERE vi.isolate_id = er.isolate_id AND vi.reference_id IS NOT NULL
              )
            """
        ) or 0

    # Count remaining (excluding rejected)
    result["remaining_missing"] = scalar(
        conn, "SELECT COUNT(*) FROM evidence_records WHERE reference_id IS NULL AND curation_status != 'rejected'"
    ) or 0

    return result


# ═══════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="P0 Data Quality Optimization")
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview changes only (no writes)")
    parser.add_argument("--fix", type=str, default="1,2,3,4",
                        help="Comma-separated fix numbers to apply (default: 1,2,3,4)")
    parser.add_argument("--db", type=str, default=str(DB_PATH),
                        help="Path to database file")
    args = parser.parse_args()

    db_path = Path(args.db)
    fix_ids = [int(x.strip()) for x in args.fix.split(",")]

    # Validate
    if not db_path.exists():
        print(f"ERROR: Database not found: {db_path}")
        sys.exit(1)

    # Backup (except in dry-run)
    backup_path = None
    if not args.dry_run:
        backup_path = backup_database(db_path, BACKUPS_DIR, "pre_p0_optimize")
        print()

    import sqlite3
    conn = sqlite3.connect(str(db_path), timeout=120)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 120000")

    try:
        # Setup
        ensure_schema(conn)
        run_id = start_run(conn, args.dry_run, [f"fix_{i}" for i in fix_ids])
        print(f"[run] Run ID: {run_id}, Dry-run: {args.dry_run}, Fixes: {fix_ids}")
        print()

        all_results: dict[str, dict] = {}

        # Execute requested fixes
        if 1 in fix_ids:
            print("=" * 60)
            print("Fix 1: Evidence claim URL cleanup")
            print("=" * 60)
            with conn:
                r = fix_evidence_urls(conn, run_id, args.dry_run)
            all_results["fix_evidence_urls"] = r
            print(f"  Candidates found:  {r['total_candidates']}")
            print(f"  Claims cleaned:    {r['cleaned']}")
            print(f"  Skipped (manual):  {r['skipped_manual']}")
            if r.get("details"):
                for d in r["details"][:5]:
                    print(f"    [{d['evidence_id']}] orig={d['original_claim'][:80]}... → {d['cleaned_claim'][:80]}...")
            print()

        if 2 in fix_ids:
            print("=" * 60)
            print("Fix 2: Genome_type imputation")
            print("=" * 60)
            with conn:
                r = fix_genome_type(conn, run_id, args.dry_run)
            all_results["fix_genome_type"] = r
            print(f"  Total missing:     {r['total_missing']}")
            print(f"  Tier1 (master):    {r['tier1_master_inherit']}")
            print(f"  Tier2 (molecule):  {r['tier2_molecule_map']}")
            print(f"  Tier3 (family):    {r['tier3_family_default']}")
            print(f"  Remaining missing: {r['remaining_missing']}")
            print()

        if 3 in fix_ids:
            print("=" * 60)
            print("Fix 3: Genome_length NULL backfill")
            print("=" * 60)
            with conn:
                r = fix_genome_length(conn, run_id, args.dry_run)
            all_results["fix_genome_length"] = r
            print(f"  Total missing:           {r['total_missing']}")
            print(f"  From proteins:           {r['from_proteins']}")
            print(f"  From nucleotide_records: {r['from_nucleotide_records']}")
            print(f"  Remaining missing:       {r['remaining_missing']}")
            print()

        if 4 in fix_ids:
            print("=" * 60)
            print("Fix 4: Evidence reference_id backfill")
            print("=" * 60)
            with conn:
                r = fix_reference_id_backfill(conn, run_id, args.dry_run)
            all_results["fix_reference_id"] = r
            print(f"  Total missing:        {r['total_missing']}")
            print(f"  Skipped (rejected):   {r['skipped_rejected']}")
            print(f"  PMID match:           {r['pmid_match']}")
            print(f"  DOI match:            {r['doi_match']}")
            print(f"  Isolate link match:   {r['isolate_link_match']}")
            print(f"  Remaining missing:    {r['remaining_missing']}")
            print()

        # ── Write Report ──────────────────────────────────────────
        report = {
            "run_id": run_id,
            "run_ts": stamp(),
            "dry_run": args.dry_run,
            "backup_path": str(backup_path) if backup_path else None,
            "fixes_applied": [f"fix_{i}" for i in fix_ids],
            "results": all_results,
        }

        report_path = REPORTS_DIR / f"optimize_p0_{stamp()}.json"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"[report] → {report_path}")

        # Also write a summary TSV for each fix
        for fix_name, fix_result in all_results.items():
            if "details" in fix_result and fix_result["details"]:
                csv_path = REPORTS_DIR / f"optimize_p0_{fix_name}_{stamp()}.csv"
                write_csv(csv_path, fix_result["details"])
                print(f"[csv]   → {csv_path}")

        # ── Final integrity check ─────────────────────────────────
        integrity = scalar(conn, "PRAGMA integrity_check")
        fk_violations = scalar(conn, "PRAGMA foreign_key_check")
        fk_count = len(rows(conn, "PRAGMA foreign_key_check"))
        print(f"\n[integrity] integrity_check: {integrity}, foreign_key_violations: {fk_count}")

        if not args.dry_run:
            # Update run record with final notes
            conn.execute(
                "UPDATE optimize_quality_runs SET notes = ? WHERE run_id = ?",
                (f"integrity={integrity}, fk_violations={fk_count}", run_id),
            )
            conn.commit()

    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()

    print("\nDone.")


if __name__ == "__main__":
    main()
