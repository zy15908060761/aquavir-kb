#!/usr/bin/env python3
"""
Comprehensive Data Validation & Quality Assurance Pipeline
for the Crustacean Virus Database.

Usage:
    python validate_database.py --check          # Run all validation checks
    python validate_database.py --fix             # Auto-fix unambiguous problems
    python validate_database.py --report          # Write JSON validation report
    python validate_database.py --pre-import <file>  # Validate an import Excel/CSV
    python validate_database.py --check --fix     # Check then auto-fix
    python validate_database.py --fix --report    # Fix and generate report
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sqlite3
import sys
import traceback
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable

import pandas as pd

# ── Paths ────────────────────────────────────────────────────────
APP_DIR = Path(__file__).resolve().parent
DB_PATH = APP_DIR / "crustacean_virus_core.db"
REPORTS_DIR = APP_DIR / "reports"

# Current year for validation boundary
CURRENT_YEAR = date.today().year

# ── Issue severity levels ────────────────────────────────────────
CRITICAL = "CRITICAL"
HIGH = "HIGH"
MEDIUM = "MEDIUM"
LOW = "LOW"

# ── Standard country list (ISO 3166-1 English short names) ──────
STANDARD_COUNTRIES: set[str] = {
    "Afghanistan", "Albania", "Algeria", "Andorra", "Angola",
    "Antigua and Barbuda", "Argentina", "Armenia", "Australia", "Austria",
    "Azerbaijan", "Bahamas", "Bahrain", "Bangladesh", "Barbados",
    "Belarus", "Belgium", "Belize", "Benin", "Bhutan",
    "Bolivia", "Bosnia and Herzegovina", "Botswana", "Brazil", "Brunei",
    "Bulgaria", "Burkina Faso", "Burundi", "Cabo Verde", "Cambodia",
    "Cameroon", "Canada", "Central African Republic", "Chad", "Chile",
    "China", "Colombia", "Comoros", "Congo", "Costa Rica",
    "Cote d'Ivoire", "Croatia", "Cuba", "Cyprus", "Czech Republic",
    "Czechia", "Democratic Republic of the Congo", "Denmark", "Djibouti", "Dominica",
    "Dominican Republic", "Ecuador", "Egypt", "El Salvador", "Equatorial Guinea",
    "Eritrea", "Estonia", "Eswatini", "Ethiopia", "Fiji",
    "Finland", "France", "Gabon", "Gambia", "Georgia",
    "Germany", "Ghana", "Greece", "Grenada", "Guatemala",
    "Guinea", "Guinea-Bissau", "Guyana", "Haiti", "Honduras",
    "Hungary", "Iceland", "India", "Indonesia", "Iran",
    "Iraq", "Ireland", "Israel", "Italy", "Jamaica",
    "Japan", "Jordan", "Kazakhstan", "Kenya", "Kiribati",
    "Kuwait", "Kyrgyzstan", "Laos", "Latvia", "Lebanon",
    "Lesotho", "Liberia", "Libya", "Liechtenstein", "Lithuania",
    "Luxembourg", "Madagascar", "Malawi", "Malaysia", "Maldives",
    "Mali", "Malta", "Marshall Islands", "Mauritania", "Mauritius",
    "Mexico", "Micronesia", "Moldova", "Monaco", "Mongolia",
    "Montenegro", "Morocco", "Mozambique", "Myanmar", "Namibia",
    "Nauru", "Nepal", "Netherlands", "New Zealand", "Nicaragua",
    "Niger", "Nigeria", "North Korea", "North Macedonia", "Norway",
    "Oman", "Pakistan", "Palau", "Palestine", "Panama",
    "Papua New Guinea", "Paraguay", "Peru", "Philippines", "Poland",
    "Portugal", "Qatar", "Romania", "Russia", "Rwanda",
    "Saint Kitts and Nevis", "Saint Lucia", "Saint Vincent and the Grenadines",
    "Samoa", "San Marino", "Sao Tome and Principe", "Saudi Arabia",
    "Senegal", "Serbia", "Seychelles", "Sierra Leone", "Singapore",
    "Slovakia", "Slovenia", "Solomon Islands", "Somalia", "South Africa",
    "South Korea", "South Sudan", "Spain", "Sri Lanka", "Sudan",
    "Suriname", "Sweden", "Switzerland", "Syria", "Taiwan",
    "Tajikistan", "Tanzania", "Thailand", "Timor-Leste", "Togo",
    "Tonga", "Trinidad and Tobago", "Tunisia", "Turkey", "Turkmenistan",
    "Tuvalu", "Uganda", "Ukraine", "United Arab Emirates",
    "United Kingdom", "United States", "Uruguay", "Uzbekistan",
    "Vanuatu", "Vatican City", "Venezuela", "Vietnam", "Yemen",
    "Zambia", "Zimbabwe",
    # Additional relevant entries
    "Congo, Democratic Republic of the", "Congo, Republic of the",
    "Côte d'Ivoire", "Korea, North", "Korea, South",
    "United States of America", "UK", "USA",
    "Viet Nam", "Russia Federation", "Russian Federation",
    "China (mainland)", "China (Taiwan)", "Hong Kong", "Macau",
    "Tanzania, United Republic of",
    # ISO 3166-1 dependent territories that appear in marine records.
    "Aruba", "Faroe Islands", "French Polynesia", "New Caledonia",
}

# ── Country name normalization map ──────────────────────────────
COUNTRY_NORMALIZE: dict[str, str] = {
    "america": "United States",
    "america/brazil": "Brazil",
    "australia ": "Australia",
    "brazil": "Brazil",
    "canada": "Canada",
    "china": "China",
    "china mainland": "China",
    "china (mainland)": "China",
    "china (anhui)": "China",
    "china (guangdong)": "China",
    "china (guangxi)": "China",
    "china (hainan)": "China",
    "china (jiangsu)": "China",
    "china (shandong)": "China",
    "china (zhejiang)": "China",
    "china:fujian": "China",
    "french polynesia": "French Polynesia",
    "hong kong": "Hong Kong",
    "india": "India",
    "indonesia": "Indonesia",
    "iran": "Iran",
    "japan": "Japan",
    "korea": "South Korea",
    "korea, republic of": "South Korea",
    "madagascar": "Madagascar",
    "malaysia": "Malaysia",
    "mexico": "Mexico",
    "mexico ": "Mexico",
    "myanmar": "Myanmar",
    "new caledonia": "New Caledonia",
    "new zealand": "New Zealand",
    "philippines": "Philippines",
    "russia": "Russia",
    "russian federation": "Russia",
    "saudi arabia": "Saudi Arabia",
    "singapore": "Singapore",
    "south korea": "South Korea",
    "sri lanka": "Sri Lanka",
    "taiwan": "Taiwan",
    "taiwan ": "Taiwan",
    "taiwan (china)": "Taiwan",
    "thailand": "Thailand",
    "turkey": "Turkey",
    "u.s.a.": "United States",
    "u.s.a": "United States",
    "uk": "United Kingdom",
    "usa": "United States",
    "united states": "United States",
    "united states of america": "United States",
    "viet nam": "Vietnam",
    "vietnam": "Vietnam",
    # Empty / unknown
    "": "",
    "nan": "",
    "none": "",
    "null": "",
    "unknown": "",
    "not provided": "",
    "not applicable": "",
    "n/a": "",
}

# ── Known genome_type values for normalization ──────────────────
GENOME_TYPE_NORMALIZE: dict[str, str] = {
    "dna": "DNA",
    "rna": "RNA",
    "mrna": "mRNA",
    "dsdna": "dsDNA",
    "ssdna": "ssDNA",
    "dsrna": "dsRNA",
    "ssrna": "ssRNA",
    "ssrna(+)": "ssRNA(+)",
    "ssrna(-)": "ssRNA(-)",
    "ssrna+": "ssRNA(+)",
    "ssrna-": "ssRNA(-)",
    "ssrnapositive": "ssRNA(+)",
    "ssrnanegative": "ssRNA(-)",
    "dsdna(r)": "dsDNA(R)",
    "dsdna (r)": "dsDNA(R)",
    "ssdna(r)": "ssDNA(R)",
    "positive-sense ssrna": "ssRNA(+)",
    "negative-sense ssrna": "ssRNA(-)",
    "double-stranded dna": "dsDNA",
    "single-stranded dna": "ssDNA",
    "double-stranded rna": "dsRNA",
    "single-stranded rna": "ssRNA",
}

# ── Valid nucleotide characters ─────────────────────────────────
VALID_NUCLEOTIDES = re.compile(r"^[ACGTURYSWKMBDHVNacgturyswkmbdhvn\-\.]+$")

# ── DOI pattern ─────────────────────────────────────────────────
DOI_PATTERN = re.compile(r"^10\.\d{4,}(\.\d+)?/[^\s]+$")

# ── PMID pattern (digits only) ──────────────────────────────────
PMID_PATTERN = re.compile(r"^\d{1,8}$")

# ── Patent-like ID pattern (e.g., US1234567B2, WO2020123456) ───
PATENT_PATTERN = re.compile(
    r"^(WO|EP|US|JP|CN|KR|AU|CA|DE|FR|GB|IN|RU|ES|AT|BE|BR|CH|DK|FI|IE|IL|IT|MX|NL|NO|NZ|PL|PT|SE|SG|ZA)"
    r"\d{4,12}([A-Z]\d?)?$"
)

# ── Helpers ─────────────────────────────────────────────────────


def stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def rows(conn: sqlite3.Connection, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def value(conn: sqlite3.Connection, sql: str, params: tuple[Any, ...] = ()) -> Any:
    row = conn.execute(sql, params).fetchone()
    return None if row is None else row[0]


def table_exists(conn: sqlite3.Connection, name: str) -> bool:
    return bool(value(conn, "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)))


def table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    if not table_exists(conn, table):
        return set()
    # Sanitize table name to prevent injection via PRAGMA (identifiers cannot be parameterized)
    safe_table = table.replace('"', '""')
    return {r["name"] for r in conn.execute(f'PRAGMA table_info("{safe_table}")')}


# ═══════════════════════════════════════════════════════════════════
# SECTION 1: Pre-import Validation (against a DataFrame)
# ═══════════════════════════════════════════════════════════════════

class ValidationIssue:
    """Represents a single validation finding."""
    __slots__ = ("severity", "entity_type", "entity_id", "field", "message", "suggested_fix")

    def __init__(
        self,
        severity: str,
        entity_type: str,
        entity_id: str,
        field: str,
        message: str,
        suggested_fix: str = "",
    ):
        self.severity = severity
        self.entity_type = entity_type
        self.entity_id = entity_id
        self.field = field
        self.message = message
        self.suggested_fix = suggested_fix

    def to_dict(self) -> dict[str, str]:
        return {
            "severity": self.severity,
            "entity_type": self.entity_type,
            "entity_id": str(self.entity_id),
            "field": self.field,
            "message": self.message,
            "suggested_fix": self.suggested_fix,
        }


def validate_pre_import(df: pd.DataFrame) -> list[ValidationIssue]:
    """
    Validate a DataFrame before importing into the database.
    Designed for metadata Excel/CSV files containing viral isolate records.
    """
    issues: list[ValidationIssue] = []
    df_lower_cols = {c.lower(): c for c in df.columns}

    def col(name: str) -> str | None:
        """Find actual column name by case-insensitive lookup."""
        return df_lower_cols.get(name.lower())

    # ── genome_length ──────────────────────────────────────────
    gl_col = col("genome_length") or col("length") or col("sequence_length")
    if gl_col:
        for idx, val in df.iterrows():
            row_num = idx + 2  # +2 for 1-indexed + header row
            raw = val.get(gl_col)
            if pd.isna(raw):
                continue
            try:
                gl = int(float(str(raw)))
            except (ValueError, TypeError):
                issues.append(ValidationIssue(
                    MEDIUM, "isolate", f"Row {row_num}",
                    gl_col, f"genome_length is not numeric: {raw}",
                    "Set to NULL or provide a valid integer.",
                ))
                continue
            if gl < 100:
                issues.append(ValidationIssue(
                    HIGH, "isolate", f"Row {row_num}",
                    gl_col, f"genome_length={gl} is too short (<100 nt); likely a primer or host chromosome fragment",
                    "Remove this record or confirm it is a valid small viral genome.",
                ))
            elif gl > 2_000_000:
                issues.append(ValidationIssue(
                    HIGH, "isolate", f"Row {row_num}",
                    gl_col, f"genome_length={gl} exceeds 2 Mbp; likely a host chromosome or bacterial contamination",
                    "Remove or flag for manual review.",
                ))

    # ── gc_content ──────────────────────────────────────────────
    gc_col = col("gc_content") or col("gc")
    if gc_col:
        for idx, val in df.iterrows():
            row_num = idx + 2
            raw = val.get(gc_col)
            if pd.isna(raw):
                continue
            try:
                gc = float(str(raw))
            except (ValueError, TypeError):
                issues.append(ValidationIssue(
                    MEDIUM, "isolate", f"Row {row_num}",
                    gc_col, f"gc_content is not numeric: {raw}",
                    "Set to NULL or provide a valid float.",
                ))
                continue
            if gc < 10 or gc > 80:
                issues.append(ValidationIssue(
                    MEDIUM, "isolate", f"Row {row_num}",
                    gc_col, f"gc_content={gc} is outside expected range (10-80%)",
                    "Review and correct the GC content value.",
                ))

    # ── virus_name ──────────────────────────────────────────────
    vn_col = col("virus_name") or col("definition") or col("organism")
    if vn_col:
        for idx, val in df.iterrows():
            row_num = idx + 2
            raw = str(val.get(vn_col, "")).strip()
            if not raw or raw.lower() in ("nan", "none", "null", ""):
                continue
            if raw.upper().startswith("EST"):
                issues.append(ValidationIssue(
                    HIGH, "isolate", f"Row {row_num}",
                    vn_col, f"virus_name starts with 'EST': {raw[:60]}",
                    "This looks like an EST (Expressed Sequence Tag), not a virus. Remove.",
                ))
            if PATENT_PATTERN.match(raw.upper()):
                issues.append(ValidationIssue(
                    HIGH, "isolate", f"Row {row_num}",
                    vn_col, f"virus_name looks like a patent ID: {raw[:60]}",
                    "Replace with the actual virus name from the patent.",
                ))

    # ── sequence validation ────────────────────────────────────
    seq_col = col("sequence") or col("nucleotides") or col("seq")
    if seq_col:
        for idx, val in df.iterrows():
            row_num = idx + 2
            raw = str(val.get(seq_col, "")).strip()
            if not raw or raw.lower() in ("nan", "none", "null", ""):
                continue
            # Remove whitespace for validation
            cleaned = raw.replace(" ", "").replace("\n", "").replace("\r", "")
            if not VALID_NUCLEOTIDES.match(cleaned):
                invalid_chars = set(cleaned.upper()) - set("ACGTURYSWKMBDHVN-.")
                issues.append(ValidationIssue(
                    CRITICAL, "isolate", f"Row {row_num}",
                    seq_col, f"Sequence contains invalid characters: {invalid_chars}",
                    "Remove non-nucleotide characters or fix the sequence.",
                ))

    # ── latitude / longitude ────────────────────────────────────
    lat_col = col("latitude") or col("lat")
    lon_col = col("longitude") or col("lon") or col("lng")
    if lat_col:
        for idx, val in df.iterrows():
            row_num = idx + 2
            raw = val.get(lat_col)
            if pd.isna(raw):
                continue
            try:
                lat = float(str(raw))
            except (ValueError, TypeError):
                issues.append(ValidationIssue(
                    MEDIUM, "isolate", f"Row {row_num}",
                    lat_col, f"latitude is not numeric: {raw}",
                    "Provide a valid latitude value.",
                ))
                continue
            if lat < -90 or lat > 90:
                issues.append(ValidationIssue(
                    HIGH, "isolate", f"Row {row_num}",
                    lat_col, f"latitude={lat} is outside valid range [-90, 90]",
                    "Correct the latitude value.",
                ))
    if lon_col:
        for idx, val in df.iterrows():
            row_num = idx + 2
            raw = val.get(lon_col)
            if pd.isna(raw):
                continue
            try:
                lon = float(str(raw))
            except (ValueError, TypeError):
                issues.append(ValidationIssue(
                    MEDIUM, "isolate", f"Row {row_num}",
                    lon_col, f"longitude is not numeric: {raw}",
                    "Provide a valid longitude value.",
                ))
                continue
            if lon < -180 or lon > 180:
                issues.append(ValidationIssue(
                    HIGH, "isolate", f"Row {row_num}",
                    lon_col, f"longitude={lon} is outside valid range [-180, 180]",
                    "Correct the longitude value.",
                ))

    # ── year validation ────────────────────────────────────────
    year_col = col("year") or col("collection_year") or col("collection_date") or col("publication_year")
    if year_col:
        for idx, val in df.iterrows():
            row_num = idx + 2
            raw = str(val.get(year_col, "")).strip()
            if not raw or raw.lower() in ("nan", "none", "null", ""):
                continue
            # Try to extract a 4-digit year
            m = re.search(r"(19|20)\d{2}", raw)
            if m:
                year_val = int(m.group(0))
                if year_val < 1900:
                    issues.append(ValidationIssue(
                        MEDIUM, "isolate", f"Row {row_num}",
                        year_col, f"year={year_val} is before 1900",
                        "Verify the year is correct.",
                    ))
                elif year_val > CURRENT_YEAR + 1:
                    issues.append(ValidationIssue(
                        MEDIUM, "isolate", f"Row {row_num}",
                        year_col, f"year={year_val} is in the future (>{CURRENT_YEAR+1})",
                        "Correct the year.",
                    ))
            else:
                # Year field is present but no valid year found -- only warn, don't reject
                if len(raw) > 1 and raw.lower() not in ("unknown", "not provided"):
                    issues.append(ValidationIssue(
                        LOW, "isolate", f"Row {row_num}",
                        year_col, f"Cannot parse year from: {raw[:40]}",
                        "Consider reformatting to YYYY.",
                    ))

    # ── DOI validation ──────────────────────────────────────────
    doi_col = col("doi")
    if doi_col:
        for idx, val in df.iterrows():
            row_num = idx + 2
            raw = str(val.get(doi_col, "")).strip()
            if not raw or raw.lower() in ("nan", "none", "null", ""):
                continue
            if not DOI_PATTERN.match(raw):
                issues.append(ValidationIssue(
                    LOW, "reference", f"Row {row_num}",
                    doi_col, f"DOI does not match expected format: {raw[:60]}",
                    "Expected format: 10.xxxx/xxxxx",
                ))

    # ── PMID validation ─────────────────────────────────────────
    pmid_col = col("pmid") or col("pubmed_id") or col("pubmed")
    if pmid_col:
        for idx, val in df.iterrows():
            row_num = idx + 2
            raw = str(val.get(pmid_col, "")).strip()
            if not raw or raw.lower() in ("nan", "none", "null", ""):
                continue
            if raw.endswith(".0"):
                raw = raw[:-2]
            if not PMID_PATTERN.match(raw):
                issues.append(ValidationIssue(
                    LOW, "reference", f"Row {row_num}",
                    pmid_col, f"PMID does not match expected format: {raw}",
                    "Expected: 1-8 digit number.",
                ))

    # ── country validation ─────────────────────────────────────
    ctry_col = col("country")
    if ctry_col:
        for idx, val in df.iterrows():
            row_num = idx + 2
            raw = str(val.get(ctry_col, "")).strip()
            if not raw or raw.lower() in ("nan", "none", "null", ""):
                continue
            lookup = COUNTRY_NORMALIZE.get(raw.lower().strip(), raw.strip())
            if lookup and lookup not in STANDARD_COUNTRIES:
                issues.append(ValidationIssue(
                    LOW, "location", f"Row {row_num}",
                    ctry_col, f"Country not in standard list: {raw[:60]}",
                    f"Suggested standard: {find_closest_country(raw)}",
                ))

    return issues


def find_closest_country(name: str) -> str:
    """Find the closest matching standard country name."""
    name_lower = name.strip().lower()
    # Direct normalization lookup
    if name_lower in COUNTRY_NORMALIZE:
        return COUNTRY_NORMALIZE[name_lower]
    # Fuzzy match: check if it's a partial match
    for std in sorted(STANDARD_COUNTRIES):
        if std.lower() == name_lower:
            return std
    # Check if the input is a substring of any standard country or vice versa
    for std in sorted(STANDARD_COUNTRIES):
        if name_lower in std.lower() or std.lower() in name_lower:
            return std
    return ""


def normalize_country(raw: str) -> str:
    """Normalize a country name to the standard form."""
    cleaned = raw.strip()
    if not cleaned:
        return ""
    lower = cleaned.lower()
    if lower in COUNTRY_NORMALIZE:
        result = COUNTRY_NORMALIZE[lower]
        return result
    # Check if already in standard list
    for std in STANDARD_COUNTRIES:
        if std.lower() == lower:
            return std
    return cleaned


# ═══════════════════════════════════════════════════════════════════
# SECTION 2: Post-Import Consistency Checks (against SQLite DB)
# ═══════════════════════════════════════════════════════════════════

class DatabaseChecker:
    """Runs consistency checks against the live database."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.issues: list[ValidationIssue] = []
        # Table presence flags
        self.tables: set[str] = {
            r["name"] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }

    def check_all(self) -> list[ValidationIssue]:
        """Run all post-import consistency checks."""
        self.issues = []
        self._check_integrity()
        self._check_genome_length_suspicious()
        self._check_master_id_valid()
        self._check_protein_isolate_fk()
        self._check_duplicate_accessions()
        self._check_duplicate_infection_records()
        self._check_country_standard()
        self._check_orphan_records()
        self._check_genome_type_consistency()
        return self.issues

    def _add(self, severity: str, entity_type: str, entity_id: str,
             field: str, message: str, suggested_fix: str = "") -> None:
        self.issues.append(ValidationIssue(
            severity, entity_type, entity_id, field, message, suggested_fix,
        ))

    def _check_integrity(self) -> None:
        """PRAGMA integrity_check and foreign_key_check."""
        # Integrity check
        integrity = value(self.conn, "PRAGMA integrity_check")
        if integrity != "ok":
            self._add(
                CRITICAL, "database", "all",
                "integrity", f"PRAGMA integrity_check failed: {integrity}",
                "Restore from backup or run VACUUM.",
            )
        # Foreign key violations
        fk_violations = rows(self.conn, "PRAGMA foreign_key_check")
        if fk_violations:
            # Group by table
            by_table: dict[str, list[dict]] = defaultdict(list)
            for v in fk_violations:
                by_table[v["table"]].append(v)
            for table_name, viols in by_table.items():
                self._add(
                    CRITICAL, table_name, f"{len(viols)} violations",
                    "foreign_key", f"FK violations in {table_name}: {len(viols)}",
                    f"Run: PRAGMA foreign_key_check; review and fix broken references in {table_name}.",
                )

    def _check_genome_length_suspicious(self) -> None:
        """Flag unquarantined isolates with genome_length < 100."""
        if "viral_isolates" not in self.tables:
            return
        bad = rows(
            self.conn,
            """
            SELECT vi.isolate_id, vi.accession, vi.genome_length, vi.virus_name
            FROM viral_isolates vi
            LEFT JOIN isolate_curated_profiles icp ON icp.isolate_id = vi.isolate_id
            WHERE vi.genome_length IS NOT NULL
              AND vi.genome_length < 100
              AND COALESCE(vi.sequence_scope_status, '') NOT IN (
                  'short_fragment_not_complete_genome',
                  'host_genome_artifact',
                  'transcript_or_est_artifact'
              )
              AND COALESCE(icp.dataset_tier, '') NOT IN (
                  'sequence_scope_artifact',
                  'host_genome_artifact'
              )
            ORDER BY vi.genome_length
            """
        )
        for r in bad:
            self._add(
                HIGH, "viral_isolates", str(r["isolate_id"]),
                "genome_length",
                f"isolate_id={r['isolate_id']} accession={r['accession']} "
                f"genome_length={r['genome_length']} < 100 nt; likely a primer/artifact",
                f"DELETE FROM viral_isolates WHERE isolate_id = ?  (param: {r['isolate_id']})",
            )

    def _check_master_id_valid(self) -> None:
        """Every isolate should have a valid master_id (if virus_master table exists)."""
        if "viral_isolates" not in self.tables or "virus_master" not in self.tables:
            return
        cols = table_columns(self.conn, "viral_isolates")
        if "master_id" not in cols:
            return
        bad = rows(
            self.conn,
            "SELECT vi.isolate_id, vi.accession, vi.master_id "
            "FROM viral_isolates vi "
            "LEFT JOIN virus_master vm ON vm.master_id = vi.master_id "
            "WHERE vi.master_id IS NULL OR vm.master_id IS NULL"
        )
        for r in bad:
            self._add(
                CRITICAL, "viral_isolates", str(r["isolate_id"]),
                "master_id",
                f"isolate_id={r['isolate_id']} accession={r['accession']} "
                f"master_id={r['master_id']} is NULL or references non-existent master",
                f"UPDATE viral_isolates SET master_id = <valid_id> WHERE isolate_id = ?  (param: {r['isolate_id']})",
            )

    def _check_protein_isolate_fk(self) -> None:
        """Every protein should have a valid isolate_id."""
        if "viral_proteins" not in self.tables or "viral_isolates" not in self.tables:
            return
        bad = rows(
            self.conn,
            "SELECT vp.protein_id, vp.protein_accession, vp.isolate_id "
            "FROM viral_proteins vp "
            "LEFT JOIN viral_isolates vi ON vi.isolate_id = vp.isolate_id "
            "WHERE vi.isolate_id IS NULL"
        )
        for r in bad:
            self._add(
                CRITICAL, "viral_proteins", str(r["protein_id"]),
                "isolate_id",
                f"protein_id={r['protein_id']} accession={r['protein_accession']} "
                f"references isolate_id={r['isolate_id']} which does not exist",
                f"UPDATE viral_proteins SET isolate_id = NULL WHERE protein_id = ?  (param: {r['protein_id']})",
            )

    def _check_duplicate_accessions(self) -> None:
        """Check for duplicate accessions in viral_isolates."""
        if "viral_isolates" not in self.tables:
            return
        cols = table_columns(self.conn, "viral_isolates")
        acc_col = "accession"
        if acc_col not in cols:
            # Try genome_accession
            acc_col = "genome_accession" if "genome_accession" in cols else ""
        if not acc_col:
            return
        dupes = rows(
            self.conn,
            f"SELECT {acc_col}, COUNT(*) as cnt, GROUP_CONCAT(isolate_id) as ids "
            f"FROM viral_isolates "
            f"WHERE {acc_col} IS NOT NULL AND TRIM({acc_col}) <> '' "
            f"GROUP BY {acc_col} "
            f"HAVING COUNT(*) > 1"
        )
        for r in dupes:
            self._add(
                CRITICAL, "viral_isolates", f"accession={r[acc_col]}",
                acc_col,
                f"Duplicate {acc_col}: '{r[acc_col]}' appears {r['cnt']} times "
                f"(isolate_ids: {r['ids']})",
                "DELETE duplicate rows or UPDATE accessions to be unique.",
            )

    def _check_duplicate_infection_records(self) -> None:
        """Check for duplicate (isolate_id, host_id) pairs in infection_records."""
        if "infection_records" not in self.tables:
            return
        dupes = rows(
            self.conn,
            "SELECT isolate_id, host_id, COUNT(*) as cnt, GROUP_CONCAT(record_id) as record_ids "
            "FROM infection_records "
            "WHERE isolate_id IS NOT NULL AND host_id IS NOT NULL "
            "GROUP BY isolate_id, host_id "
            "HAVING COUNT(*) > 1"
        )
        for r in dupes:
            self._add(
                MEDIUM, "infection_records", f"isolate_id={r['isolate_id']}, host_id={r['host_id']}",
                "(isolate_id, host_id)",
                f"Duplicate infection record: pair ({r['isolate_id']}, {r['host_id']}) "
                f"appears {r['cnt']} times (record_ids: {r['record_ids']})",
                "DELETE FROM infection_records WHERE record_id IN (keep one, remove others)",
            )

    def _check_country_standard(self) -> None:
        """Check countries against standard list."""
        for tbl in ("sample_collections",):
            if tbl not in self.tables:
                continue
            cols = table_columns(self.conn, tbl)
            if "country" not in cols:
                continue
            countries = rows(
                self.conn,
                f"SELECT DISTINCT country FROM {tbl} "
                f"WHERE country IS NOT NULL AND TRIM(country) <> '' "
                f"ORDER BY country"
            )
            for r in countries:
                c = r["country"]
                normalized = normalize_country(c)
                # Flag if country is not recognized or non-standard
                if normalized and normalized not in STANDARD_COUNTRIES:
                    suggestion = find_closest_country(c)
                    fix_sql = (
                        f"UPDATE {tbl} SET country = ? WHERE country = ?  (params: {suggestion!r}, {c!r})"
                        if suggestion else f"Review country '{c}' manually"
                    )
                    self._add(LOW, tbl, f"country='{c}'", "country",
                              f"Non-standard country: '{c}'", fix_sql)
                elif not normalized:
                    # Completely unrecognized country
                    suggestion = find_closest_country(c)
                    fix_sql = (
                        f"UPDATE {tbl} SET country = ? WHERE country = ?  (params: {suggestion!r}, {c!r})"
                        if suggestion else f"Review country '{c}' manually"
                    )
                    self._add(LOW, tbl, f"country='{c}'", "country",
                              f"Non-standard country (unrecognized): '{c}'", fix_sql)

    def _check_orphan_records(self) -> None:
        """Check for orphaned records (referenced entities that don't exist)."""
        # References with no isolates pointing to them
        if "ref_literatures" in self.tables and "viral_isolates" in self.tables:
            cols = table_columns(self.conn, "viral_isolates")
            if "reference_id" in cols:
                orphan_refs = rows(
                    self.conn,
                    "SELECT r.reference_id, r.pmid, r.title "
                    "FROM ref_literatures r "
                    "LEFT JOIN viral_isolates vi ON vi.reference_id = r.reference_id "
                    "WHERE vi.isolate_id IS NULL"
                )
                if len(orphan_refs) > 10:
                    # Summarize if many
                    self._add(
                        LOW, "ref_literatures", f"{len(orphan_refs)} references",
                        "reference_id",
                        f"{len(orphan_refs)} references have no associated isolates",
                        "Review and remove orphaned references if unneeded.",
                    )

    def _check_genome_type_consistency(self) -> None:
        """Check for inconsistent genome_type values (case, abbreviations)."""
        if "viral_isolates" not in self.tables:
            return
        cols = table_columns(self.conn, "viral_isolates")
        if "genome_type" not in cols:
            return
        types = rows(
            self.conn,
            "SELECT DISTINCT genome_type FROM viral_isolates "
            "WHERE genome_type IS NOT NULL AND TRIM(genome_type) <> '' "
            "ORDER BY genome_type"
        )
        raw_types = [r["genome_type"] for r in types]
        # Check for non-normalized values
        normalized_set: set[str] = set()
        non_standard: list[str] = []
        for gt in raw_types:
            lower = gt.lower().replace(" ", "")
            if lower in GENOME_TYPE_NORMALIZE:
                norm = GENOME_TYPE_NORMALIZE[lower]
                if norm != gt:
                    non_standard.append(f"'{gt}' -> '{norm}'")
            else:
                non_standard.append(f"'{gt}' -> (no mapping)")
        if non_standard:
            self._add(
                MEDIUM, "viral_isolates", "all isolates",
                "genome_type",
                f"Non-standard genome_type values found ({len(non_standard)} variants): "
                + "; ".join(non_standard[:10]),
                "UPDATE viral_isolates SET genome_type = <normalized> WHERE genome_type = <old>",
            )


# ═══════════════════════════════════════════════════════════════════
# SECTION 3: Coverage Metrics
# ═══════════════════════════════════════════════════════════════════

def compute_coverage_metrics(conn: sqlite3.Connection) -> dict[str, Any]:
    """Compute coverage and completeness metrics across the database."""
    metrics: dict[str, Any] = {}
    tables = {
        r["name"] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }

    # Total isolates
    if "viral_isolates" in tables:
        total_isolates = value(conn, "SELECT COUNT(*) FROM viral_isolates") or 0
        metrics["total_isolates"] = total_isolates

        # % isolates with proteins
        if "viral_proteins" in tables:
            isolates_with_proteins = value(
                conn,
                "SELECT COUNT(DISTINCT isolate_id) FROM viral_proteins"
            ) or 0
            metrics["isolates_with_proteins"] = isolates_with_proteins
            metrics["pct_isolates_with_proteins"] = (
                round(isolates_with_proteins / total_isolates * 100, 2)
                if total_isolates else 0.0
            )
        else:
            metrics["isolates_with_proteins"] = 0
            metrics["pct_isolates_with_proteins"] = 0.0

        # % isolates with hosts
        iso_cols = table_columns(conn, "viral_isolates")
        if "host_id" in iso_cols:
            isolates_with_hosts = value(
                conn,
                "SELECT COUNT(*) FROM viral_isolates WHERE host_id IS NOT NULL"
            ) or 0
        elif "infection_records" in tables:
            isolates_with_hosts = value(
                conn,
                "SELECT COUNT(DISTINCT isolate_id) FROM infection_records WHERE host_id IS NOT NULL"
            ) or 0
        else:
            isolates_with_hosts = 0
        metrics["isolates_with_hosts"] = isolates_with_hosts
        metrics["pct_isolates_with_hosts"] = (
            round(isolates_with_hosts / total_isolates * 100, 2)
            if total_isolates else 0.0
        )

        # % isolates with literature
        if "reference_id" in iso_cols:
            isolates_with_ref = value(
                conn,
                "SELECT COUNT(*) FROM viral_isolates WHERE reference_id IS NOT NULL"
            ) or 0
        else:
            isolates_with_ref = 0
        metrics["isolates_with_literature"] = isolates_with_ref
        metrics["pct_isolates_with_literature"] = (
            round(isolates_with_ref / total_isolates * 100, 2)
            if total_isolates else 0.0
        )

        # % isolates with genome_type
        if "genome_type" in iso_cols:
            isolates_with_genome_type = value(
                conn,
                "SELECT COUNT(*) FROM viral_isolates "
                "WHERE genome_type IS NOT NULL AND TRIM(genome_type) <> ''"
            ) or 0
            metrics["isolates_with_genome_type"] = isolates_with_genome_type
            metrics["pct_isolates_with_genome_type"] = (
                round(isolates_with_genome_type / total_isolates * 100, 2)
                if total_isolates else 0.0
            )

        # % isolates with gc_content
        if "gc_content" in iso_cols:
            isolates_with_gc = value(
                conn,
                "SELECT COUNT(*) FROM viral_isolates WHERE gc_content IS NOT NULL"
            ) or 0
            metrics["isolates_with_gc_content"] = isolates_with_gc
            metrics["pct_isolates_with_gc_content"] = (
                round(isolates_with_gc / total_isolates * 100, 2)
                if total_isolates else 0.0
            )

        # % isolates with genome_length
        if "genome_length" in iso_cols:
            isolates_with_length = value(
                conn,
                "SELECT COUNT(*) FROM viral_isolates WHERE genome_length IS NOT NULL"
            ) or 0
            metrics["isolates_with_genome_length"] = isolates_with_length
            metrics["pct_isolates_with_genome_length"] = (
                round(isolates_with_length / total_isolates * 100, 2)
                if total_isolates else 0.0
            )

        # % isolates with country
        if "infection_records" in tables and "sample_collections" in tables:
            isolates_with_country = value(
                conn,
                "SELECT COUNT(DISTINCT ir.isolate_id) "
                "FROM infection_records ir "
                "JOIN sample_collections sc ON sc.collection_id = ir.collection_id "
                "WHERE sc.country IS NOT NULL AND TRIM(sc.country) <> ''"
            ) or 0
            metrics["isolates_with_country"] = isolates_with_country
            metrics["pct_isolates_with_country"] = (
                round(isolates_with_country / total_isolates * 100, 2)
                if total_isolates else 0.0
            )

        # % isolates with coordinates
        if "infection_records" in tables and "sample_collections" in tables:
            isolates_with_coords = value(
                conn,
                "SELECT COUNT(DISTINCT ir.isolate_id) "
                "FROM infection_records ir "
                "JOIN sample_collections sc ON sc.collection_id = ir.collection_id "
                "WHERE sc.latitude IS NOT NULL AND sc.longitude IS NOT NULL"
            ) or 0
            metrics["isolates_with_coordinates"] = isolates_with_coords
            metrics["pct_isolates_with_coordinates"] = (
                round(isolates_with_coords / total_isolates * 100, 2)
                if total_isolates else 0.0
            )
    else:
        metrics["total_isolates"] = 0

    # Protein-level metrics
    if "viral_proteins" in tables:
        total_proteins = value(conn, "SELECT COUNT(*) FROM viral_proteins") or 0
        metrics["total_proteins"] = total_proteins

        # % proteins with functional_category != 'unknown'
        proteins_with_func = value(
            conn,
            "SELECT COUNT(*) FROM viral_proteins "
            "WHERE functional_category IS NOT NULL "
            "AND functional_category <> 'unknown'"
        ) or 0
        metrics["proteins_with_functional_category"] = proteins_with_func
        metrics["pct_proteins_with_functional_category"] = (
            round(proteins_with_func / total_proteins * 100, 2)
            if total_proteins else 0.0
        )

        # % proteins with structures
        if "protein_structures" in tables:
            proteins_with_structures = value(
                conn,
                "SELECT COUNT(DISTINCT protein_id) FROM protein_structures "
                "WHERE protein_id IS NOT NULL"
            ) or 0
            metrics["proteins_with_structures"] = proteins_with_structures
            metrics["pct_proteins_with_structures"] = (
                round(proteins_with_structures / total_proteins * 100, 2)
                if total_proteins else 0.0
            )
        else:
            metrics["proteins_with_structures"] = 0
            metrics["pct_proteins_with_structures"] = 0.0

        # % proteins with domains
        if "protein_domains" in tables:
            proteins_with_domains = value(
                conn,
                "SELECT COUNT(DISTINCT protein_id) FROM protein_domains "
                "WHERE protein_id IS NOT NULL"
            ) or 0
            metrics["proteins_with_domains"] = proteins_with_domains
            metrics["pct_proteins_with_domains"] = (
                round(proteins_with_domains / total_proteins * 100, 2)
                if total_proteins else 0.0
            )
        else:
            metrics["proteins_with_domains"] = 0
            metrics["pct_proteins_with_domains"] = 0.0
    else:
        metrics["total_proteins"] = 0

    # Reference-level metrics
    if "ref_literatures" in tables:
        total_refs = value(conn, "SELECT COUNT(*) FROM ref_literatures") or 0
        metrics["total_references"] = total_refs
        refs_with_pmid = value(
            conn,
            "SELECT COUNT(*) FROM ref_literatures "
            "WHERE pmid IS NOT NULL AND TRIM(pmid) <> ''"
        ) or 0
        refs_with_doi = value(
            conn,
            "SELECT COUNT(*) FROM ref_literatures "
            "WHERE doi IS NOT NULL AND TRIM(doi) <> ''"
        ) or 0
        refs_with_either = value(
            conn,
            "SELECT COUNT(*) FROM ref_literatures "
            "WHERE (pmid IS NOT NULL AND TRIM(pmid) <> '') "
            "OR (doi IS NOT NULL AND TRIM(doi) <> '')"
        ) or 0
        metrics["references_with_pmid"] = refs_with_pmid
        metrics["references_with_doi"] = refs_with_doi
        metrics["references_with_pmid_or_doi"] = refs_with_either
        metrics["pct_references_with_pmid_or_doi"] = (
            round(refs_with_either / total_refs * 100, 2)
            if total_refs else 0.0
        )
    else:
        metrics["total_references"] = 0

    # Host-level
    if "crustacean_hosts" in tables:
        total_hosts = value(conn, "SELECT COUNT(*) FROM crustacean_hosts") or 0
        metrics["total_hosts"] = total_hosts
        hosts_with_type = value(
            conn,
            "SELECT COUNT(*) FROM crustacean_hosts WHERE host_type IS NOT NULL"
        ) or 0
        metrics["hosts_with_type"] = hosts_with_type
        metrics["pct_hosts_with_type"] = (
            round(hosts_with_type / total_hosts * 100, 2)
            if total_hosts else 0.0
        )
        hosts_with_iucn = value(
            conn,
            "SELECT COUNT(*) FROM crustacean_hosts WHERE iucn_status IS NOT NULL"
        ) or 0
        metrics["hosts_with_iucn_status"] = hosts_with_iucn
        metrics["pct_hosts_with_iucn_status"] = (
            round(hosts_with_iucn / total_hosts * 100, 2)
            if total_hosts else 0.0
        )

    return metrics


# ═══════════════════════════════════════════════════════════════════
# SECTION 4: Auto-Fix Functions
# ═══════════════════════════════════════════════════════════════════

def auto_fix(conn: sqlite3.Connection, dry_run: bool = True) -> dict[str, int]:
    """
    Apply automatic fixes for unambiguous problems.
    Returns a dict of fix_name -> count of affected rows.
    """
    fixes: dict[str, int] = {}
    if not dry_run:
        conn.execute("BEGIN TRANSACTION")

    # 4.1 Country name normalization
    if table_exists(conn, "sample_collections"):
        affected = 0
        for tbl in ("sample_collections",):
            countries = rows(
                conn,
                f"SELECT DISTINCT country FROM {tbl} "
                f"WHERE country IS NOT NULL AND TRIM(country) <> ''"
            )
            for r in countries:
                raw = r["country"]
                normalized = normalize_country(raw)
                if normalized and normalized != raw and normalized in STANDARD_COUNTRIES:
                    if not dry_run:
                        conn.execute(
                            f"UPDATE {tbl} SET country = ? WHERE country = ?",
                            (normalized, raw),
                        )
                    affected += 1
        fixes["normalize_country"] = affected

    # 4.2 Genome type normalization
    if table_exists(conn, "viral_isolates"):
        cols = table_columns(conn, "viral_isolates")
        if "genome_type" in cols:
            affected = 0
            types = rows(
                conn,
                "SELECT DISTINCT genome_type FROM viral_isolates "
                "WHERE genome_type IS NOT NULL AND TRIM(genome_type) <> ''"
            )
            for r in types:
                raw = r["genome_type"]
                lower = raw.lower().replace(" ", "")
                if lower in GENOME_TYPE_NORMALIZE:
                    norm = GENOME_TYPE_NORMALIZE[lower]
                    if norm != raw:
                        if not dry_run:
                            conn.execute(
                                "UPDATE viral_isolates SET genome_type = ? WHERE genome_type = ?",
                                (norm, raw),
                            )
                        affected += 1
            fixes["normalize_genome_type"] = affected

    # 4.3 Remove genome_length < 50 (unambiguous artifacts)
    if table_exists(conn, "viral_isolates"):
        cols = table_columns(conn, "viral_isolates")
        if "genome_length" in cols:
            tiny = value(
                conn,
                "SELECT COUNT(*) FROM viral_isolates "
                "WHERE genome_length IS NOT NULL AND genome_length < 50"
            )
            if tiny and tiny > 0:
                if not dry_run:
                    conn.execute(
                        "DELETE FROM viral_isolates WHERE genome_length IS NOT NULL AND genome_length < 50"
                    )
            fixes["remove_tiny_genomes_under_50"] = tiny or 0

    # 4.4 Normalize empty/whitespace-only text fields to NULL
    for tbl in ("viral_isolates", "crustacean_hosts", "ref_literatures", "sample_collections"):
        if not table_exists(conn, tbl):
            continue
        if tbl == "viral_isolates":
            for field in ("virus_name", "genome_type", "keywords"):
                affected = 0
                cols = table_columns(conn, tbl)
                if field in cols:
                    if not dry_run:
                        conn.execute(
                            f"UPDATE {tbl} SET {field} = NULL "
                            f"WHERE {field} IS NOT NULL AND TRIM({field}) = ''"
                        )
                    # Count what would be affected
                    cnt = value(
                        conn,
                        f"SELECT COUNT(*) FROM {tbl} "
                        f"WHERE {field} IS NOT NULL AND TRIM({field}) = ''"
                    ) or 0
                    if cnt:
                        affected = cnt
                fixes[f"trim_empty_{tbl}_{field}"] = affected

    if not dry_run:
        conn.execute("COMMIT")

    fixes["_dry_run"] = 1 if dry_run else 0
    return fixes


# ═══════════════════════════════════════════════════════════════════
# SECTION 5: Report Generation
# ═══════════════════════════════════════════════════════════════════

def generate_report(conn: sqlite3.Connection, issues: list[ValidationIssue],
                    metrics: dict[str, Any], fixes: dict[str, int] | None = None,
                    pre_import_issues: list[ValidationIssue] | None = None) -> dict[str, Any]:
    """Generate a complete validation report."""
    now = datetime.now()
    report: dict[str, Any] = {
        "generated_at": now.isoformat(timespec="seconds"),
        "database": str(DB_PATH),
        "db_size_mb": round(DB_PATH.stat().st_size / (1024 * 1024), 2) if DB_PATH.exists() else 0,
        "validation_summary": {
            "total_issues": len(issues),
            "by_severity": {},
            "by_entity": {},
        },
        "issues": [i.to_dict() for i in issues],
        "coverage_metrics": metrics,
    }

    if pre_import_issues:
        report["pre_import_validation"] = {
            "total_issues": len(pre_import_issues),
            "issues": [i.to_dict() for i in pre_import_issues],
        }

    if fixes:
        report["auto_fixes"] = fixes

    # Summarize by severity
    severity_counts: dict[str, int] = defaultdict(int)
    entity_counts: dict[str, int] = defaultdict(int)
    for i in issues:
        severity_counts[i.severity] += 1
        entity_counts[i.entity_type] += 1
    report["validation_summary"]["by_severity"] = dict(severity_counts)
    report["validation_summary"]["by_entity"] = dict(entity_counts)

    # Database health score
    total_issues_count = len(issues)
    if total_issues_count == 0:
        health_score = 100
    else:
        weights = {CRITICAL: 10, HIGH: 5, MEDIUM: 2, LOW: 1}
        weighted_sum = sum(weights.get(i.severity, 1) for i in issues)
        health_score = max(0, 100 - weighted_sum)
    report["health_score"] = health_score

    return report


# ═══════════════════════════════════════════════════════════════════
# SECTION 6: CLI
# ═══════════════════════════════════════════════════════════════════

def print_report_summary(report: dict[str, Any]) -> None:
    """Print a human-readable summary of the report to stdout."""
    print("=" * 75)
    print("  CRUSTACEAN VIRUS DATABASE - VALIDATION REPORT")
    print("=" * 75)
    print(f"  Generated: {report['generated_at']}")
    print(f"  Database:  {report['database']}")
    print(f"  Size:      {report['db_size_mb']} MB")
    print(f"  Health:    {report['health_score']}/100")
    print()

    summary = report["validation_summary"]
    print(f"  Total issues found: {summary['total_issues']}")
    print(f"  By severity:")
    for sev in (CRITICAL, HIGH, MEDIUM, LOW):
        cnt = summary["by_severity"].get(sev, 0)
        print(f"    {sev:10s}: {cnt}")
    print()

    if summary["by_entity"]:
        print(f"  By entity type:")
        for entity, cnt in sorted(summary["by_entity"].items()):
            print(f"    {entity}: {cnt}")
        print()

    print("  Coverage Metrics:")
    metrics = report.get("coverage_metrics", {})
    for key, val in metrics.items():
        if isinstance(val, float):
            print(f"    {key}: {val:.2f}")
        else:
            print(f"    {key}: {val}")
    print()

    if report.get("auto_fixes"):
        print("  Auto-Fixes Applied:")
        for fix, count in report["auto_fixes"].items():
            if fix == "_dry_run":
                continue
            print(f"    {fix}: {count} row(s) affected")
        print()

    # Print top issues
    if report["issues"]:
        print("  Top issues:")
        for issue in report["issues"][:20]:
            print(f"    [{issue['severity']}] {issue['entity_type']}#{issue['entity_id']}: "
                  f"{issue['message'][:80]}")
            if issue["suggested_fix"]:
                print(f"      Fix: {issue['suggested_fix'][:100]}")
        if len(report["issues"]) > 20:
            print(f"    ... and {len(report['issues']) - 20} more issues")
    print("=" * 75)


def print_issues(issues: list[ValidationIssue]) -> None:
    """Print validation issues to stdout."""
    if not issues:
        print("  No issues found.")
        return
    by_severity: dict[str, list[ValidationIssue]] = defaultdict(list)
    for issue in issues:
        by_severity[issue.severity].append(issue)
    for sev in (CRITICAL, HIGH, MEDIUM, LOW):
        items = by_severity.get(sev, [])
        if not items:
            continue
        print(f"\n  [{sev}] ({len(items)} issue(s))")
        print("-" * 70)
        for issue in items:
            print(f"  {issue.entity_type}#{issue.entity_id} | {issue.field}")
            print(f"    {issue.message}")
            if issue.suggested_fix:
                print(f"    >>> Fix: {issue.suggested_fix}")
            print()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Crustacean Virus Database - Validation & QA Pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--check", action="store_true",
        help="Run all validation checks against the database",
    )
    parser.add_argument(
        "--fix", action="store_true",
        help="Auto-fix unambiguous problems (country names, genome_type, tiny genomes)",
    )
    parser.add_argument(
        "--report", action="store_true",
        help="Generate a JSON validation report",
    )
    parser.add_argument(
        "--pre-import", type=str, metavar="FILE",
        help="Validate an Excel (.xlsx) or CSV file before import",
    )
    parser.add_argument(
        "--dry-run", action="store_true", default=True,
        help="With --fix, show what would be changed without applying (default: True)",
    )
    parser.add_argument(
        "--apply", action="store_true",
        help="With --fix, actually apply changes (disable dry-run)",
    )
    parser.add_argument(
        "--output", type=str, metavar="FILE",
        help="Write report JSON to a specific path instead of default",
    )

    args = parser.parse_args()

    # If no arguments, show help
    if not any([args.check, args.fix, args.report, args.pre_import]):
        parser.print_help()
        sys.exit(0)

    conn = None
    issues: list[ValidationIssue] = []
    pre_import_issues: list[ValidationIssue] = []
    metrics: dict[str, Any] = {}
    fixes: dict[str, int] | None = None

    # ── Pre-import validation ───────────────────────────────────
    if args.pre_import:
        file_path = Path(args.pre_import)
        if not file_path.exists():
            print(f"ERROR: File not found: {file_path}", file=sys.stderr)
            sys.exit(1)

        print(f"\n[Pre-Import] Validating file: {file_path}")
        try:
            if file_path.suffix.lower() in (".xlsx", ".xls"):
                df = pd.read_excel(file_path, sheet_name=None)
                # Validate each sheet
                for sheet_name, sheet_df in df.items():
                    print(f"  Sheet '{sheet_name}': {len(sheet_df)} rows")
                    sheet_issues = validate_pre_import(sheet_df)
                    pre_import_issues.extend(sheet_issues)
                    print(f"    -> {len(sheet_issues)} issue(s)")
            elif file_path.suffix.lower() == ".csv":
                df = pd.read_csv(file_path, encoding="utf-8-sig")
                print(f"  CSV: {len(df)} rows")
                pre_import_issues = validate_pre_import(df)
                print(f"    -> {len(pre_import_issues)} issue(s)")
            else:
                print(f"ERROR: Unsupported file format: {file_path.suffix}", file=sys.stderr)
                sys.exit(1)
        except Exception as e:
            print(f"ERROR reading file: {e}", file=sys.stderr)
            traceback.print_exc()
            sys.exit(1)

        if pre_import_issues:
            print(f"\n  Pre-import validation found {len(pre_import_issues)} issue(s):")
            print_issues(pre_import_issues)
        else:
            print("\n  Pre-import validation passed with no issues.")

    # ── Database operations ─────────────────────────────────────
    if args.check or args.fix or args.report:
        if not DB_PATH.exists():
            print(f"ERROR: Database not found: {DB_PATH}", file=sys.stderr)
            sys.exit(1)

        conn = connect()

        if args.check:
            print(f"\n[Check] Running validation against database...")
            checker = DatabaseChecker(conn)
            issues = checker.check_all()
            metrics = compute_coverage_metrics(conn)

            if issues:
                print(f"\n  Found {len(issues)} issue(s):")
                print_issues(issues)
            else:
                print("\n  No issues found. Database integrity passed.")

            print("\n  Coverage Metrics:")
            for key, val in sorted(metrics.items()):
                if isinstance(val, float):
                    print(f"    {key}: {val:.2f}")
                else:
                    print(f"    {key}: {val}")

        if args.fix:
            dry_run = not args.apply
            print(f"\n[Fix] Running auto-fixes (dry_run={dry_run})...")
            if not table_exists(conn, "sample_collections"):
                print("  WARNING: Core tables don't exist -- auto-fix may be limited.")
            fixes = auto_fix(conn, dry_run=dry_run)
            print(f"  Fixes applied:")
            for fix_name, count in fixes.items():
                if fix_name == "_dry_run":
                    continue
                print(f"    {fix_name}: {count} row(s) affected")
            if fixes.get("_dry_run"):
                print("\n  NOTE: Dry-run mode -- no changes were applied.")
                print("  Re-run with --fix --apply to actually apply changes.")

        if args.report:
            if not issues and args.check:
                # If --check was already run, we already have issues/metrics
                pass
            elif not issues:
                # Run checks if not already done
                checker = DatabaseChecker(conn)
                issues = checker.check_all()
                metrics = compute_coverage_metrics(conn)

            report = generate_report(
                conn=conn,
                issues=issues,
                metrics=metrics,
                fixes=fixes,
                pre_import_issues=pre_import_issues if pre_import_issues else None,
            )

            # Determine output path
            if args.output:
                report_path = Path(args.output)
            else:
                report_path = REPORTS_DIR / f"validation_{stamp()}.json"

            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(
                json.dumps(report, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            print(f"\n[Report] Written to: {report_path}")
            print_report_summary(report)

    # Cleanup
    if conn:
        conn.close()


if __name__ == "__main__":
    main()
