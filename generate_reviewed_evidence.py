#!/usr/bin/env python3
"""
Generate the public-facing reviewed evidence export for AquaVir-KB NAR submission.

Produces:
  - public_downloads/reviewed_evidence_records.xlsx  (Excel)
  - public_downloads/reviewed_evidence_records.tsv   (tab-separated)

Selection criteria (descending priority):
  1. curation_status = 'manual_checked'              (highest quality)
  2. curation_status = 'auto_imported' AND evidence_strength = 'high'
  3. evidence_origin = 'primary'                     (primary literature)
  4. evidence_type IN ('host_range', 'natural_infection')  (top-interest types)

Limited to 10 000 records to keep the download manageable.
"""

import re
import sqlite3
import os
from pathlib import Path

import pandas as pd


# Regex matching all illegal XML characters (openpyxl rejects these)
# Only the following are legal in XML 1.0:
#   #x9 | #xA | #xD | [#x20-#xD7FF] | [#xE000-#xFFFD] | [#x10000-#x10FFFF]
_ILLEGAL_XML = re.compile(
    "[\\x00-\\x08\\x0b\\x0c\\x0e-\\x1f\\x7f\\x80\\x81\\x82\\x83\\x84\\x85\\x86\\x87"
    "\\x88\\x89\\x8a\\x8b\\x8c\\x8d\\x8e\\x8f\\x90\\x91\\x92\\x93\\x94\\x95\\x96\\x97"
    "\\x98\\x99\\x9a\\x9b\\x9c\\x9d\\x9e\\x9f\\ufffe\\uffff]"
)


def _clean_illegal(value):
    """Replace illegal XML characters with a space."""
    if isinstance(value, str):
        return _ILLEGAL_XML.sub(" ", value)
    return value

DB_PATH = Path(__file__).parent / "crustacean_virus_core.db"
OUT_DIR = Path(__file__).parent / "public_downloads"
OUT_DIR.mkdir(parents=True, exist_ok=True)

XLSX_PATH = OUT_DIR / "reviewed_evidence_records.xlsx"
TSV_PATH  = OUT_DIR / "reviewed_evidence_records.tsv"

SELECT_SQL = """
    SELECT
        e.evidence_id,
        v.canonical_name          AS virus_name,
        h.scientific_name         AS host_name,
        e.evidence_type,
        e.evidence_strength,
        e.curation_status,
        e.claim                   AS summary,
        COALESCE(e.source_pmid, r.pmid) AS ref_pmid,
        COALESCE(e.source_doi,  r.doi)  AS ref_doi,
        r.title                   AS ref_title,
        r.journal                 AS ref_journal,
        r.year                    AS ref_year,
        e.evidence_origin,
        e.observation_type,
        e.unit,
        e.value_text,
        e.value_numeric_min,
        e.value_numeric_max
    FROM evidence_records e
    LEFT JOIN virus_master v ON v.master_id = e.virus_master_id
    LEFT JOIN crustacean_hosts h ON h.host_id = e.host_id
    LEFT JOIN ref_literatures r ON r.reference_id = e.reference_id
    WHERE e.curation_status = 'manual_checked'
       OR (e.curation_status = 'auto_imported' AND e.evidence_strength = 'high')
       OR e.evidence_origin = 'primary'
       OR e.evidence_type IN ('host_range', 'natural_infection')
    ORDER BY
        CASE e.curation_status
            WHEN 'manual_checked' THEN 1
            WHEN 'auto_imported'  THEN 2
            ELSE 3
        END,
        CASE e.evidence_strength
            WHEN 'high'   THEN 1
            WHEN 'medium' THEN 2
            WHEN 'low'    THEN 3
            ELSE 4
        END,
        e.evidence_id
    LIMIT 10000
"""


def main():
    print("Connecting to database ...")
    conn = sqlite3.connect(str(DB_PATH))

    print("Querying reviewed evidence (10 000 record limit) ...")
    df = pd.read_sql_query(SELECT_SQL, conn)
    conn.close()

    if df.empty:
        print("ERROR: No records returned. Check database and query.")
        return

    # --- Summary statistics ---
    print(f"\n{'='*50}")
    print(f"Exported: {len(df):,} evidence records")
    print(f"{'='*50}")

    print("\n--- By evidence_type ---")
    type_counts = df["evidence_type"].value_counts()
    for k, v in type_counts.items():
        print(f"  {k:25s} {v:>6,}")

    print("\n--- By evidence_strength ---")
    strength_counts = df["evidence_strength"].value_counts()
    for k, v in strength_counts.items():
        print(f"  {k:25s} {v:>6,}")

    print("\n--- By curation_status ---")
    status_counts = df["curation_status"].value_counts()
    for k, v in status_counts.items():
        print(f"  {k:25s} {v:>6,}")

    print("\n--- By evidence_origin ---")
    origin_counts = df["evidence_origin"].value_counts()
    for k, v in origin_counts.items():
        print(f"  {k:25s} {v:>6,}")

    # --- Clean illegal XML characters from all string columns ---
    str_cols = df.select_dtypes(include="str").columns
    for col in str_cols:
        df[col] = df[col].apply(_clean_illegal)

    # --- Export ---
    print(f"\nWriting {XLSX_PATH} ...")
    df.to_excel(str(XLSX_PATH), index=False, engine="openpyxl")
    xlsx_size = os.path.getsize(XLSX_PATH)
    print(f"  Size: {xlsx_size / 1024:.1f} KB")

    print(f"Writing {TSV_PATH} ...")
    df.to_csv(str(TSV_PATH), sep="\t", index=False)
    tsv_size = os.path.getsize(TSV_PATH)
    print(f"  Size: {tsv_size / 1024:.1f} KB")

    print(f"\nDone. Both files written to {OUT_DIR.resolve()}")


if __name__ == "__main__":
    main()
