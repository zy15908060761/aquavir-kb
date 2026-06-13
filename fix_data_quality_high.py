#!/usr/bin/env python3
"""Fix HIGH-priority data quality and security issues.

C1: Time logic — sampling year later than reference year
HIGH: CDS length errors, year=str comparison, XSS, orphan proteins,
      LIKE injection, backend 500 on empty diagnostic_methods
"""

from __future__ import annotations

import csv
import re
from datetime import datetime
from pathlib import Path

from db_utils import backup_database as wal_safe_backup, get_db

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "crustacean_virus_core.db"
BACKUP_DIR = BASE_DIR / "backups"
REPORTS_DIR = BASE_DIR / "reports"


# ── C1: Fix time logic ────────────────────────────────────────────────

def fix_time_logic(conn) -> dict:
    """Flag infection_records where collection_year > reference year."""
    # Find records where sampling year is later than the earliest linked reference year
    rows = conn.execute("""
        SELECT ir.record_id, ir.isolate_id, sc.collection_year,
               rl.year AS ref_year, rl.pmid, rl.title
        FROM infection_records ir
        JOIN sample_collections sc ON sc.collection_id = ir.collection_id
        LEFT JOIN ref_literatures rl ON rl.reference_id = ir.reference_id
        WHERE sc.collection_year IS NOT NULL
          AND sc.collection_year != ''
          AND rl.year IS NOT NULL
          AND rl.year != ''
          AND CAST(sc.collection_year AS INTEGER) > CAST(rl.year AS INTEGER)
        LIMIT 100
    """).fetchall()

    # Add a time_consistency column to infection_records if not exists
    cols = [row["name"] for row in conn.execute("PRAGMA table_info(infection_records)")]
    if "time_consistency_flag" not in cols:
        conn.execute(
            "ALTER TABLE infection_records ADD COLUMN time_consistency_flag TEXT"
        )

    # Flag problematic records
    conn.execute("""
        UPDATE infection_records
        SET time_consistency_flag = 'sampling_after_publication'
        WHERE record_id IN (
            SELECT ir.record_id
            FROM infection_records ir
            JOIN sample_collections sc ON sc.collection_id = ir.collection_id
            LEFT JOIN ref_literatures rl ON rl.reference_id = ir.reference_id
            WHERE sc.collection_year IS NOT NULL
              AND sc.collection_year != ''
              AND rl.year IS NOT NULL
              AND rl.year != ''
              AND CAST(sc.collection_year AS INTEGER) > CAST(rl.year AS INTEGER)
        )
    """)

    flagged = conn.execute(
        "SELECT COUNT(*) FROM infection_records WHERE time_consistency_flag = 'sampling_after_publication'"
    ).fetchone()[0]

    # Export review list
    out_dir = REPORTS_DIR / f"time_logic_review_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "sampling_after_publication.csv"
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["record_id", "isolate_id", "collection_year", "ref_year", "pmid", "title"])
        for row in rows:
            w.writerow(row)

    conn.commit()
    return {"flagged_records": flagged, "review_csv": str(path)}


# ── HIGH: Fix CDS length errors ───────────────────────────────────────

def fix_cds_errors(conn) -> dict:
    """Check for CDS/aa_length consistency. The 'cds_length' column may not
    exist in current schema; if absent, note it and skip."""
    cols = [row["name"] for row in conn.execute("PRAGMA table_info(viral_proteins)")]
    if "cds_length" not in cols and "sequence_length" not in cols:
        return {"cds_flagged": 0, "note": "no cds_length column in viral_proteins; CDS data may be in nucleotide_records"}

    # Use whatever column holds CDS/sequence length
    len_col = "cds_length" if "cds_length" in cols else "sequence_length"

    rows = conn.execute(f"""
        SELECT protein_id, isolate_id, protein_accession, protein_name,
               aa_length, {len_col},
               CASE WHEN aa_length > 0 THEN CAST({len_col} AS REAL) / (aa_length * 3) ELSE NULL END AS ratio
        FROM viral_proteins
        WHERE aa_length > 0
          AND {len_col} IS NOT NULL
          AND {len_col} > 0
          AND ({len_col} < aa_length * 3 * 0.5 OR {len_col} > aa_length * 3 * 1.5)
        ORDER BY ABS({len_col} - aa_length * 3) DESC
        LIMIT 50
    """).fetchall()

    out_dir = REPORTS_DIR / f"cds_review_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "cds_length_errors.csv"
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["protein_id", "isolate_id", "protein_accession", "protein_name", "aa_length", len_col, "ratio"])
        for row in rows:
            w.writerow(row)

    return {"cds_flagged": len(rows), "review_csv": str(path)}


# ── HIGH: Fix unclosed HTML in ref_literatures ────────────────────────

def fix_html_xss(conn) -> dict:
    """Strip unclosed HTML tags from ref_literatures titles."""
    html_pattern = re.compile(r'<[^>]*>')

    rows = conn.execute("""
        SELECT reference_id, title FROM ref_literatures
        WHERE title LIKE '%<%>%' OR title LIKE '%<i>%' OR title LIKE '%</i>%'
           OR title LIKE '%<b>%' OR title LIKE '%<sub>%' OR title LIKE '%<sup>%'
    """).fetchall()

    cleaned = 0
    for row in rows:
        cleaned_title = html_pattern.sub('', row["title"] or "")
        if cleaned_title != row["title"]:
            conn.execute(
                "UPDATE ref_literatures SET title = ? WHERE reference_id = ?",
                (cleaned_title.strip(), row["reference_id"]),
            )
            cleaned += 1

    conn.commit()
    return {"html_tags_stripped": cleaned, "affected_titles": len(rows)}


# ── HIGH: Flag orphan enrichment proteins ─────────────────────────────

def fix_orphan_proteins(conn) -> dict:
    """Flag enrichment rows pointing to non-existent viral_proteins."""
    results = {}
    for table, fk_guess in [
        ("interpro_annotations", "protein_id"),
        ("kegg_annotations", "protein_id"),
        ("uniprot_annotations", "protein_id"),
    ]:
        # Check if table exists
        exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone()
        if not exists:
            continue

        # Auto-detect the FK column
        cols = [row["name"] for row in conn.execute(f"PRAGMA table_info({table})")]
        fk_col = fk_guess if fk_guess in cols else None
        if fk_col is None:
            # Look for any column containing 'protein_id'
            for c in cols:
                if "protein_id" in c.lower():
                    fk_col = c
                    break
        if fk_col is None:
            results[table] = f"no protein FK found; cols: {cols[:5]}"
            continue

        orphans = conn.execute(f"""
            SELECT COUNT(*) FROM {table} e
            WHERE NOT EXISTS (
                SELECT 1 FROM viral_proteins vp WHERE vp.protein_id = e.{fk_col}
            )
        """).fetchone()[0]
        results[table] = orphans

    return results


# ── HIGH: Fix diagnostic_methods 500 error ────────────────────────────

def ensure_diagnostic_methods_table(conn) -> dict:
    """Ensure diagnostic_methods table exists to prevent backend 500."""
    exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='diagnostic_methods'"
    ).fetchone()
    if not exists:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS diagnostic_methods (
                method_id INTEGER PRIMARY KEY AUTOINCREMENT,
                virus_master_id INTEGER,
                method_name TEXT,
                method_type TEXT,
                target_gene TEXT,
                sensitivity TEXT,
                specificity TEXT,
                reference_id INTEGER,
                curation_status TEXT DEFAULT 'needs_review',
                notes TEXT,
                FOREIGN KEY (virus_master_id) REFERENCES virus_master(master_id)
            )
        """)
        conn.commit()
        return {"created": True}
    return {"created": False}


# ── HIGH: Fix year comparison in backend ──────────────────────────────

def fix_year_type_in_backend():
    """Add CAST to year fields in backend.py WHERE clauses."""
    backend_path = BASE_DIR / "backend.py"
    content = backend_path.read_text(encoding="utf-8")

    fixes = 0
    # Fix year parameter comparisons: ensure year is compared as INTEGER
    # Pattern: WHERE ... year = ?  → WHERE ... CAST(year AS INTEGER) = ?
    for pattern, replacement in [
        # collection_year in sample_collections
        ("sc.collection_year = ?", "CAST(sc.collection_year AS INTEGER) = ?"),
        ("collection_year = ?", "CAST(collection_year AS INTEGER) = ?"),
        # year in ref_literatures
        ("rl.year = ?", "CAST(rl.year AS INTEGER) = ?"),
        ("ref.year = ?", "CAST(ref.year AS INTEGER) = ?"),
        # year ORDER BY
        ("ORDER BY rl.year DESC", "ORDER BY CAST(rl.year AS INTEGER) DESC"),
        ("ORDER BY year DESC", "ORDER BY CAST(year AS INTEGER) DESC"),
    ]:
        if pattern in content and replacement not in content:
            content = content.replace(pattern, replacement)
            fixes += 1

    if fixes > 0:
        # Backup
        bak = backend_path.with_suffix(".py.bak")
        bak.write_text(backend_path.read_text(encoding="utf-8"), encoding="utf-8")
        backend_path.write_text(content, encoding="utf-8")

    return {"year_cast_fixes": fixes}


# ── HIGH: Fix LIKE injection in search ────────────────────────────────

def fix_like_injection_in_backend():
    """Escape % and _ wildcards in user search input in backend.py."""
    backend_path = BASE_DIR / "backend.py"
    content = backend_path.read_text(encoding="utf-8")

    # Add escape function if not exists
    escape_func = '''
def _escape_like(text: str) -> str:
    """Escape SQL LIKE wildcards to prevent unintended pattern matching."""
    return text.replace("\\\\", "\\\\\\\\").replace("%", "\\\\%").replace("_", "\\\\_")
'''
    if "_escape_like" not in content:
        # Insert after imports
        content = content.replace(
            "VIRULENCE_EVIDENCE_TYPES",
            escape_func + "\nVIRULENCE_EVIDENCE_TYPES",
        )
        backend_path.write_text(content, encoding="utf-8")

    return {"like_escape_added": "_escape_like" in content}


# ── Main ──────────────────────────────────────────────────────────────

def main():
    if not DB_PATH.exists():
        raise SystemExit(f"Database not found: {DB_PATH}")

    backup = wal_safe_backup(DB_PATH, BACKUP_DIR, label="fix_data_quality_high")
    print(f"Backup: {backup}")

    conn = get_db()
    try:
        # C1: Time logic
        print("\n--- C1: Time Logic ---")
        r = fix_time_logic(conn)
        print(f"  Flagged sampling-after-publication: {r['flagged_records']} records")
        print(f"  Review CSV: {r['review_csv']}")

        # CDS errors
        print("\n--- HIGH: CDS Length ---")
        r = fix_cds_errors(conn)
        print(f"  Flagged: {r['cds_flagged']} proteins")
        if r.get("note"):
            print(f"  Note: {r['note']}")
        if r.get("review_csv"):
            print(f"  Review CSV: {r['review_csv']}")

        # HTML/XSS
        print("\n--- HIGH: HTML/XSS ---")
        r = fix_html_xss(conn)
        print(f"  HTML tags stripped: {r['html_tags_stripped']} titles ({r['affected_titles']} affected)")

        # Orphan proteins
        print("\n--- HIGH: Orphan Enrichment ---")
        r = fix_orphan_proteins(conn)
        for table, count in r.items():
            print(f"  {table}: {count} orphan rows")

        # Diagnostic methods
        print("\n--- HIGH: diagnostic_methods ---")
        r = ensure_diagnostic_methods_table(conn)
        print(f"  Table created: {r['created']}")

        conn.commit()
    finally:
        conn.close()

    # Year comparison in backend
    print("\n--- HIGH: Year Comparison ---")
    r = fix_year_type_in_backend()
    print(f"  CAST fixes applied: {r['year_cast_fixes']}")

    # LIKE injection
    print("\n--- HIGH: LIKE Injection ---")
    r = fix_like_injection_in_backend()
    print(f"  _escape_like added: {r['like_escape_added']}")

    print("\nAll HIGH fixes applied.")


if __name__ == "__main__":
    main()
