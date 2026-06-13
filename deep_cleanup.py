#!/usr/bin/env python3
"""
Deep cleanup script for crustacean_virus_core.db
Fixes data contamination, normalization issues, schema problems.

Usage:
    python deep_cleanup.py              # Apply all fixes
    python deep_cleanup.py --dry-run     # Preview changes only
    python deep_cleanup.py --audit FILE  # Custom audit log path
"""

import argparse
import json
import os
import re
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

DB_PATH = Path("F:/甲壳动物数据库/crustacean_virus_core.db")

# ── Continent lookup ──────────────────────────────────────────────────────────
CONTINENT_MAP = {
    # Asia
    "China": "Asia", "Japan": "Asia", "South Korea": "Asia", "Korea": "Asia",
    "Taiwan": "Asia", "India": "Asia", "Thailand": "Asia", "Vietnam": "Asia",
    "Indonesia": "Asia", "Malaysia": "Asia", "Philippines": "Asia", "Singapore": "Asia",
    "Myanmar": "Asia", "Cambodia": "Asia", "Laos": "Asia", "Bangladesh": "Asia",
    "Pakistan": "Asia", "Sri Lanka": "Asia", "Nepal": "Asia", "Bhutan": "Asia",
    "Maldives": "Asia", "Brunei": "Asia", "Mongolia": "Asia",
    "Israel": "Asia", "Saudi Arabia": "Asia", "Iran": "Asia", "Iraq": "Asia",
    "Jordan": "Asia", "Kuwait": "Asia", "Lebanon": "Asia", "Oman": "Asia",
    "Qatar": "Asia", "Syria": "Asia", "Turkey": "Asia", "United Arab Emirates": "Asia",
    "Yemen": "Asia", "Bahrain": "Asia", "Palestine": "Asia",
    # North America
    "United States": "North America", "United States of America": "North America",
    "USA": "North America", "Canada": "North America", "Mexico": "North America",
    "Costa Rica": "North America", "Panama": "North America", "Guatemala": "North America",
    "Honduras": "North America", "Nicaragua": "North America", "El Salvador": "North America",
    "Belize": "North America", "Cuba": "North America", "Jamaica": "North America",
    "Haiti": "North America", "Dominican Republic": "North America",
    "Bahamas": "North America", "Trinidad and Tobago": "North America",
    "Puerto Rico": "North America", "Bermuda": "North America",
    # South America
    "Brazil": "South America", "Ecuador": "South America", "Peru": "South America",
    "Colombia": "South America", "Venezuela": "South America", "Argentina": "South America",
    "Chile": "South America", "Uruguay": "South America", "Paraguay": "South America",
    "Bolivia": "South America", "Guyana": "South America", "Suriname": "South America",
    # Europe
    "France": "Europe", "Germany": "Europe", "Italy": "Europe", "Spain": "Europe",
    "United Kingdom": "Europe", "UK": "Europe", "Ireland": "Europe",
    "Netherlands": "Europe", "Belgium": "Europe", "Switzerland": "Europe",
    "Austria": "Europe", "Sweden": "Europe", "Norway": "Europe", "Denmark": "Europe",
    "Finland": "Europe", "Iceland": "Europe", "Portugal": "Europe", "Greece": "Europe",
    "Poland": "Europe", "Czech Republic": "Europe", "Hungary": "Europe",
    "Romania": "Europe", "Bulgaria": "Europe", "Croatia": "Europe", "Slovakia": "Europe",
    "Slovenia": "Europe", "Lithuania": "Europe", "Latvia": "Europe", "Estonia": "Europe",
    "Ukraine": "Europe", "Belarus": "Europe", "Russia": "Europe", "Turkey": "Europe",
    "Cyprus": "Europe", "Malta": "Europe", "Luxembourg": "Europe", "Monaco": "Europe",
    # Africa
    "South Africa": "Africa", "Nigeria": "Africa", "Kenya": "Africa",
    "Egypt": "Africa", "Morocco": "Africa", "Tunisia": "Africa", "Algeria": "Africa",
    "Ghana": "Africa", "Tanzania": "Africa", "Uganda": "Africa", "Ethiopia": "Africa",
    "Madagascar": "Africa", "Mozambique": "Africa", "Angola": "Africa",
    "Cameroon": "Africa", "Ivory Coast": "Africa", "Côte d'Ivoire": "Africa",
    "Senegal": "Africa", "Zambia": "Africa", "Zimbabwe": "Africa",
    "Sudan": "Africa", "Libya": "Africa", "Botswana": "Africa", "Namibia": "Africa",
    # Oceania
    "Australia": "Oceania", "New Zealand": "Oceania", "Fiji": "Oceania",
    "Papua New Guinea": "Oceania", "Solomon Islands": "Oceania", "Vanuatu": "Oceania",
    "Samoa": "Oceania", "Tonga": "Oceania", "Micronesia": "Oceania",
    "Marshall Islands": "Oceania", "Palau": "Oceania", "Kiribati": "Oceania",
    "Tuvalu": "Oceania", "Nauru": "Oceania",
    # Antarctica
    "Antarctica": "Antarctica",
}


class AuditLogger:
    """Collects all changes for audit trail."""

    def __init__(self):
        self.entries = []
        self.before_counts = {}
        self.after_counts = {}

    def add(self, category, action, detail, count=1):
        self.entries.append({
            "category": category,
            "action": action,
            "detail": detail,
            "count": count,
            "timestamp": datetime.now().isoformat(),
        })

    def set_count(self, key, before, after):
        self.before_counts[key] = before
        self.after_counts[key] = after

    def write_log(self, path=None):
        if path is None:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            path = Path(f"F:/甲壳动物数据库/audit_cleanup_{ts}.json")
        report = {
            "timestamp": datetime.now().isoformat(),
            "database": str(DB_PATH),
            "dry_run": DRY_RUN,
            "before_counts": self.before_counts,
            "after_counts": self.after_counts,
            "changes": self.entries,
            "summary": {
                "total_changes": len(self.entries),
                "total_records_affected": sum(e["count"] for e in self.entries if e["count"]),
            },
        }
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n[Audit] Log written to {path}")
        return path


audit = AuditLogger()
DRY_RUN = False


def connect_db():
    """Open connection with foreign keys enabled."""
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    return conn


def count_rows(conn, table):
    """Return row count for a table."""
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


# ═══════════════════════════════════════════════════════════════════════════════
# 1. REMOVE host chromosomes from viral_isolates
# ═══════════════════════════════════════════════════════════════════════════════
def fix_chromosomes(conn):
    print("\n" + "=" * 70)
    print("FIX 1: Remove host chromosomes (genome_length > 1,000,000 bp)")
    print("=" * 70)

    before = count_rows(conn, "viral_isolates")

    rows = conn.execute("""
        SELECT isolate_id, accession, virus_name, genome_length
        FROM viral_isolates
        WHERE genome_length > 1000000
        ORDER BY genome_length DESC
    """).fetchall()

    print(f"  Found {len(rows)} suspected chromosome records:")
    for r in rows:
        print(f"    ID={r['isolate_id']:>5}  acc={r['accession']:<20}  "
              f"len={r['genome_length']:>10}  name={r['virus_name'] or 'NULL'}")

    ids = [r["isolate_id"] for r in rows]

    if not DRY_RUN and ids:
        # Also need to clean related infection_records first
        infected = conn.execute(
            f"SELECT COUNT(*) FROM infection_records WHERE isolate_id IN ({','.join('?'*len(ids))})",
            ids
        ).fetchone()[0]
        if infected:
            conn.execute(
                f"DELETE FROM infection_records WHERE isolate_id IN ({','.join('?'*len(ids))})",
                ids
            )
            print(f"  Deleted {infected} related infection_records")

        conn.execute(
            f"DELETE FROM viral_isolates WHERE isolate_id IN ({','.join('?'*len(ids))})",
            ids
        )
        print(f"  Deleted {len(ids)} chromosome records from viral_isolates")

    after = before - len(ids) if not DRY_RUN else before
    audit.set_count("fix_chromosomes", before, after)
    for r in rows:
        audit.add("chromosomes", "delete",
                  f"isolate_id={r['isolate_id']}, accession={r['accession']}, "
                  f"genome_length={r['genome_length']}")


# ═══════════════════════════════════════════════════════════════════════════════
# 2. REMOVE primer/amplicon sequences (genome_length < 50 bp)
# ═══════════════════════════════════════════════════════════════════════════════
def fix_primers(conn):
    print("\n" + "=" * 70)
    print("FIX 2: Remove primer/amplicon sequences (genome_length < 50 bp)")
    print("=" * 70)

    before = count_rows(conn, "viral_isolates")

    rows = conn.execute("""
        SELECT isolate_id, accession, virus_name, genome_length
        FROM viral_isolates
        WHERE genome_length < 50 AND genome_length IS NOT NULL
        ORDER BY genome_length
    """).fetchall()

    print(f"  Found {len(rows)} primer/amplicon records:")
    for r in rows:
        print(f"    ID={r['isolate_id']:>5}  acc={r['accession']:<20}  "
              f"len={r['genome_length']:>5}  name={r['virus_name'] or 'NULL'}")

    ids = [r["isolate_id"] for r in rows]

    if not DRY_RUN and ids:
        infected = conn.execute(
            f"SELECT COUNT(*) FROM infection_records WHERE isolate_id IN ({','.join('?'*len(ids))})",
            ids
        ).fetchone()[0]
        if infected:
            conn.execute(
                f"DELETE FROM infection_records WHERE isolate_id IN ({','.join('?'*len(ids))})",
                ids
            )
            print(f"  Deleted {infected} related infection_records")

        conn.execute(
            f"DELETE FROM viral_isolates WHERE isolate_id IN ({','.join('?'*len(ids))})",
            ids
        )
        print(f"  Deleted {len(ids)} primer/amplicon records")

    after = before - len(ids) if not DRY_RUN else before
    audit.set_count("fix_primers", before, after)
    for r in rows:
        audit.add("primers", "delete",
                  f"isolate_id={r['isolate_id']}, accession={r['accession']}, "
                  f"genome_length={r['genome_length']}")


# ═══════════════════════════════════════════════════════════════════════════════
# 3. REMOVE EST entries misclassified as viruses
# ═══════════════════════════════════════════════════════════════════════════════
def fix_est_entries(conn):
    print("\n" + "=" * 70)
    print("FIX 3: Remove EST entries (completeness='EST' or name pattern EST)")
    print("=" * 70)

    before = count_rows(conn, "viral_isolates")

    rows = conn.execute("""
        SELECT isolate_id, accession, virus_name
        FROM viral_isolates
        WHERE completeness = 'EST'
           OR virus_name LIKE 'EST%'
           OR virus_name LIKE 'est%'
    """).fetchall()

    print(f"  Found {len(rows)} EST records:")
    for r in rows:
        print(f"    ID={r['isolate_id']:>5}  acc={r['accession']:<20}  "
              f"name={r['virus_name'] or 'NULL'}")

    ids = [r["isolate_id"] for r in rows]

    if not DRY_RUN and ids:
        infected = conn.execute(
            f"SELECT COUNT(*) FROM infection_records WHERE isolate_id IN ({','.join('?'*len(ids))})",
            ids
        ).fetchone()[0]
        if infected:
            conn.execute(
                f"DELETE FROM infection_records WHERE isolate_id IN ({','.join('?'*len(ids))})",
                ids
            )
            print(f"  Deleted {infected} related infection_records")

        conn.execute(
            f"DELETE FROM viral_isolates WHERE isolate_id IN ({','.join('?'*len(ids))})",
            ids
        )
        print(f"  Deleted {len(ids)} EST records")

    after = before - len(ids) if not DRY_RUN else before
    audit.set_count("fix_est", before, after)
    for r in rows:
        audit.add("est_entries", "delete",
                  f"isolate_id={r['isolate_id']}, accession={r['accession']}, name={r['virus_name']}")


# ═══════════════════════════════════════════════════════════════════════════════
# 4. REMOVE unresolved host placeholders
# ═══════════════════════════════════════════════════════════════════════════════
def fix_host_placeholders(conn):
    print("\n" + "=" * 70)
    print("FIX 4: Remove unresolved host placeholders")
    print("=" * 70)

    before = count_rows(conn, "crustacean_hosts")

    rows = conn.execute("""
        SELECT host_id, scientific_name
        FROM crustacean_hosts
        WHERE scientific_name LIKE 'Unresolved host placeholder%'
        ORDER BY host_id
    """).fetchall()

    print(f"  Found {len(rows)} unresolved host placeholders:")
    for r in rows:
        print(f"    ID={r['host_id']:>5}  name={r['scientific_name']}")

    ids = [r["host_id"] for r in rows]

    if not DRY_RUN and ids:
        # Nullify foreign keys in infection_records before deleting
        infected = conn.execute(
            f"SELECT COUNT(*) FROM infection_records WHERE host_id IN ({','.join('?'*len(ids))})",
            ids
        ).fetchone()[0]
        if infected:
            conn.execute(
                f"UPDATE infection_records SET host_id = NULL "
                f"WHERE host_id IN ({','.join('?'*len(ids))})",
                ids
            )
            print(f"  Nullified {infected} infection_records referencing these hosts")

        conn.execute(
            f"DELETE FROM crustacean_hosts WHERE host_id IN ({','.join('?'*len(ids))})",
            ids
        )
        print(f"  Deleted {len(ids)} host placeholder records")

    after = before - len(ids) if not DRY_RUN else before
    audit.set_count("fix_host_placeholders", before, after)
    for r in rows:
        audit.add("host_placeholders", "delete",
                  f"host_id={r['host_id']}, name={r['scientific_name']}")


# ═══════════════════════════════════════════════════════════════════════════════
# 5. Normalize genome_type values
# ═══════════════════════════════════════════════════════════════════════════════
def fix_genome_type(conn):
    print("\n" + "=" * 70)
    print("FIX 5: Normalize genome_type values")
    print("=" * 70)

    # First, see distinct values
    distinct = conn.execute("""
        SELECT DISTINCT genome_type, COUNT(*) as cnt
        FROM viral_isolates
        WHERE genome_type IS NOT NULL
        GROUP BY genome_type
        ORDER BY cnt DESC
    """).fetchall()

    print("  Current genome_type distribution:")
    for r in distinct:
        print(f"    {str(r['genome_type']):<20}  count={r['cnt']}")

    # Mapping of old -> new
    canonical_map = {
        "+ssRNA": "ssRNA(+)",
        "ssRNA(+)": "ssRNA(+)",
        "ssRNA(-)": "ssRNA(-)",
        "dsRNA": "dsRNA",
        "ssDNA": "ssDNA",
        "dsDNA": "dsDNA",
        "ssDNA-RT": "ssDNA-RT",
        "dsDNA-RT": "dsDNA-RT",
    }

    changes = []
    for old_val, new_val in canonical_map.items():
        changed = conn.execute(
            "SELECT COUNT(*) FROM viral_isolates WHERE genome_type = ?",
            (old_val,)
        ).fetchone()[0]
        if changed > 0 and old_val != new_val:
            changes.append((old_val, new_val, changed))

    if changes:
        print("  Changes to apply:")
        for old_val, new_val, cnt in changes:
            print(f"    '{old_val}' -> '{new_val}' ({cnt} records)")
    else:
        print("  No changes needed.")

    if not DRY_RUN and changes:
        for old_val, new_val, _ in changes:
            conn.execute(
                "UPDATE viral_isolates SET genome_type = ? WHERE genome_type = ?",
                (new_val, old_val)
            )
        print(f"  Applied {len(changes)} genome_type normalizations")

        # Verify
        remaining = conn.execute("""
            SELECT DISTINCT genome_type, COUNT(*) as cnt
            FROM viral_isolates
            WHERE genome_type IS NOT NULL
            GROUP BY genome_type
            ORDER BY cnt DESC
        """).fetchall()
        print("  After normalization:")
        for r in remaining:
            print(f"    {str(r['genome_type']):<20}  count={r['cnt']}")

    for old_val, new_val, cnt in changes:
        audit.add("genome_type", "normalize",
                  f"'{old_val}' -> '{new_val}'", count=cnt)


# ═══════════════════════════════════════════════════════════════════════════════
# 6. Normalize country names
# ═══════════════════════════════════════════════════════════════════════════════
def fix_country_names(conn):
    print("\n" + "=" * 70)
    print("FIX 6: Normalize country names")
    print("=" * 70)

    for table in ("crustacean_hosts", "sample_collections"):
        distinct = conn.execute(f"""
            SELECT DISTINCT country, COUNT(*) as cnt
            FROM {table}
            WHERE country IS NOT NULL
            GROUP BY country
            ORDER BY cnt DESC
        """).fetchall()

        print(f"\n  Table '{table}' country distribution:")
        for r in distinct:
            print(f"    {str(r['country']):<35}  count={r['cnt']}")

    changes = []
    for table in ("crustacean_hosts", "sample_collections"):
        changed = conn.execute(
            f"SELECT COUNT(*) FROM {table} WHERE country = 'United States of America'"
        ).fetchone()[0]
        if changed:
            changes.append((table, changed))

    if changes:
        print("\n  Changes to apply:")
        for table, cnt in changes:
            print(f"    '{table}': 'United States of America' -> 'United States' ({cnt} records)")
    else:
        print("\n  No 'United States of America' entries found.")

    if not DRY_RUN and changes:
        for table, cnt in changes:
            conn.execute(
                f"UPDATE {table} SET country = 'United States' "
                f"WHERE country = 'United States of America'"
            )
        print(f"  Applied {len(changes)} country normalizations")

    for table, cnt in changes:
        audit.add("country_names", "normalize",
                  f"{table}: 'United States of America' -> 'United States'", count=cnt)


# ═══════════════════════════════════════════════════════════════════════════════
# 7. Fix virus_family unclassified variants
# ═══════════════════════════════════════════════════════════════════════════════
def fix_unclassified_family(conn):
    print("\n" + "=" * 70)
    print("FIX 7: Fix unclassified virus family variants")
    print("=" * 70)

    for col in ("virus_family", "taxon_family"):
        distinct = conn.execute(f"""
            SELECT DISTINCT {col}, COUNT(*) as cnt
            FROM viral_isolates
            WHERE {col} IS NOT NULL
            GROUP BY {col}
            ORDER BY cnt DESC
        """).fetchall()

        print(f"\n  Column '{col}' distribution:")
        for r in distinct:
            print(f"    {str(r[col]):<40}  count={r['cnt']}")

    patterns = [
        ("Unclassified (+ssRNA)", "Unclassified"),
        ("Unclassified (ssRNA)", "Unclassified"),
        ("Unclassified (dsDNA)", "Unclassified"),
        ("Unclassified (dsRNA)", "Unclassified"),
        ("Unclassified (ssDNA)", "Unclassified"),
    ]

    changes = []
    for table in ("viral_isolates",):
        for col in ("virus_family", "taxon_family"):
            for old_val, new_val in patterns:
                cnt = conn.execute(
                    f"SELECT COUNT(*) FROM {table} WHERE {col} = ?", (old_val,)
                ).fetchone()[0]
                if cnt > 0:
                    changes.append((table, col, old_val, new_val, cnt))

    if changes:
        print(f"\n  Changes to apply ({len(changes)}):")
        for table, col, old_val, new_val, cnt in changes:
            print(f"    {table}.{col}: '{old_val}' -> '{new_val}' ({cnt} records)")
    else:
        print("\n  No unclassified variant fixes needed.")

    if not DRY_RUN and changes:
        for table, col, old_val, new_val, cnt in changes:
            conn.execute(
                f"UPDATE {table} SET {col} = ? WHERE {col} = ?",
                (new_val, old_val)
            )
        print(f"  Applied {len(changes)} unclassified family fixes")

    for table, col, old_val, new_val, cnt in changes:
        audit.add("unclassified_family", "normalize",
                  f"{table}.{col}: '{old_val}' -> '{new_val}'", count=cnt)


# ═══════════════════════════════════════════════════════════════════════════════
# 8. Fix collection_date format
# ═══════════════════════════════════════════════════════════════════════════════
def normalize_date(date_str):
    """Convert various date formats to YYYY-MM-DD, returns (normalized, note)."""
    if date_str is None or date_str.strip() == "":
        return date_str, "empty"
    s = date_str.strip()

    # Already YYYY-MM-DD
    if re.match(r"^\d{4}-\d{2}-\d{2}$", s):
        return s, "already_iso"

    # Already YYYY-MM
    if re.match(r"^\d{4}-\d{2}$", s):
        return s, "iso_year_month"

    # Bare YYYY
    if re.match(r"^\d{4}$", s):
        return s, "bare_year"

    # YYYY/YYYY range - flag for review
    if re.match(r"^\d{4}/\d{4}$", s):
        return s, "range_flag"

    # DD-Mon-YYYY (e.g., 15-Jan-2020, 15-jan-2020, 15-JAN-2020)
    m = re.match(r"^(\d{1,2})-([A-Za-z]{3,9})-(\d{4})$", s)
    if m:
        day, mon, year = m.group(1), m.group(2), m.group(3)
        month_map = {
            "jan": "01", "feb": "02", "mar": "03", "apr": "04",
            "may": "05", "jun": "06", "jul": "07", "aug": "08",
            "sep": "09", "oct": "10", "nov": "11", "dec": "12",
        }
        mon_lower = mon.lower()[:3]
        if mon_lower in month_map:
            return f"{year}-{month_map[mon_lower]}-{int(day):02d}", "converted_dd_mon_yyyy"
        else:
            return s, f"unparseable_month:{mon}"

    # Mon-YYYY (e.g., Jan-2020)
    m = re.match(r"^([A-Za-z]{3,9})-(\d{4})$", s)
    if m:
        mon, year = m.group(1), m.group(2)
        month_map = {
            "jan": "01", "feb": "02", "mar": "03", "apr": "04",
            "may": "05", "jun": "06", "jul": "07", "aug": "08",
            "sep": "09", "oct": "10", "nov": "11", "dec": "12",
        }
        mon_lower = mon.lower()[:3]
        if mon_lower in month_map:
            return f"{year}-{month_map[mon_lower]}", "converted_mon_yyyy"
        else:
            return s, f"unparseable_month:{mon}"

    # DD-Mon-YY (2-digit year)
    m = re.match(r"^(\d{1,2})-([A-Za-z]{3,9})-(\d{2})$", s)
    if m:
        day, mon, year = m.group(1), m.group(2), m.group(3)
        year_full = "19" + year if int(year) >= 50 else "20" + year
        month_map = {
            "jan": "01", "feb": "02", "mar": "03", "apr": "04",
            "may": "05", "jun": "06", "jul": "07", "aug": "08",
            "sep": "09", "oct": "10", "nov": "11", "dec": "12",
        }
        mon_lower = mon.lower()[:3]
        if mon_lower in month_map:
            return f"{year_full}-{month_map[mon_lower]}-{int(day):02d}", "converted_dd_mon_yy"
        else:
            return s, f"unparseable_month:{mon}"

    return s, "unhandled_format"


def fix_collection_dates(conn):
    print("\n" + "=" * 70)
    print("FIX 8: Normalize collection_date format")
    print("=" * 70)

    rows = conn.execute("""
        SELECT collection_id, collection_date
        FROM sample_collections
        WHERE collection_date IS NOT NULL AND collection_date != ''
        ORDER BY collection_id
    """).fetchall()

    print(f"  Total records with dates: {len(rows)}")

    # Group by current format
    format_counts = defaultdict(int)
    for r in rows:
        _, note = normalize_date(r["collection_date"])
        format_counts[note] += 1

    print("  Date format distribution:")
    for fmt, cnt in sorted(format_counts.items()):
        print(f"    {fmt:<35}  count={cnt}")

    changes = []
    unhandled = []
    for r in rows:
        old_date = r["collection_date"]
        new_date, note = normalize_date(old_date)
        if new_date != old_date and note not in ("already_iso",):
            changes.append((r["collection_id"], old_date, new_date, note))
            if note == "unhandled_format":
                unhandled.append((r["collection_id"], old_date))

    print(f"\n  Records to update: {len(changes)}")
    if unhandled:
        print(f"  WARNING: {len(unhandled)} unhandled date formats:")
        for cid, val in unhandled[:10]:
            print(f"    collection_id={cid}: '{val}'")

    if not DRY_RUN and changes:
        for cid, old_date, new_date, note in changes:
            conn.execute(
                "UPDATE sample_collections SET collection_date = ? WHERE collection_id = ?",
                (new_date, cid)
            )
        print(f"  Updated {len(changes)} collection_date values")

    for cid, old_date, new_date, note in changes:
        audit.add("collection_date", "normalize",
                  f"collection_id={cid}: '{old_date}' -> '{new_date}' ({note})")


# ═══════════════════════════════════════════════════════════════════════════════
# 9. Fix schema default value quoting errors
# ═══════════════════════════════════════════════════════════════════════════════
def fix_schema_defaults(conn):
    print("\n" + "=" * 70)
    print("FIX 9: Fix schema default value quoting errors")
    print("=" * 70)

    # The table already exists; we need ALTER to drop/recreate defaults.
    # SQLite doesn't support ALTER COLUMN. We must recreate the tables.
    # For SQLite, default values only apply on INSERT. We can fix the
    # schema by recreating the table via CREATE TABLE AS or by using
    # PRAGMA writable_schema to fix the SQL directly.

    # Check current schema
    for table in ("virus_master", "sample_collections"):
        info = conn.execute(f"PRAGMA table_info({table})").fetchall()
        print(f"\n  Table '{table}' columns with defaults:")
        for col in info:
            if col[4] is not None:  # default value
                print(f"    {col[1]:<30} default={repr(col[4])}")

    # Fix using PRAGMA writable_schema to correct the SQL definitions
    # This is the only way to fix defaults without full table rebuilds.
    fixes = {
        "virus_master": ("entry_type", "''complete_genome''", "'complete_genome'"),
        "sample_collections": ("coordinate_precision", "''country''", "'country'"),
    }

    for table, (col, bad, good) in fixes.items():
        # Check if the table actually exists
        try:
            cur = conn.execute(f"PRAGMA table_info({table})")
            cols = {c[1]: c for c in cur.fetchall()}
            if col not in cols:
                print(f"  Table '{table}' has no column '{col}', skipping.")
                continue
            current_default = cols[col][4]
            if current_default == good:
                print(f"  {table}.{col} default already correct: {good}")
                continue
            if current_default != bad:
                print(f"  {table}.{col} default is {repr(current_default)}, expected {repr(bad)} or {repr(good)}, skipping.")
                continue
        except sqlite3.OperationalError:
            print(f"  Table '{table}' does not exist, skipping.")
            continue

        # Fix via writable_schema
        if not DRY_RUN:
            conn.execute("PRAGMA writable_schema = ON")
            # Get current SQL
            sql_row = conn.execute(
                "SELECT sql FROM sqlite_master WHERE name = ?", (table,)
            ).fetchone()[0]
            new_sql = sql_row.replace(bad, good)
            conn.execute(
                "UPDATE sqlite_master SET sql = ? WHERE name = ?",
                (new_sql, table)
            )
            conn.execute("PRAGMA writable_schema = OFF")
            print(f"  Fixed {table}.{col}: {repr(bad)} -> {repr(good)}")
            audit.add("schema_defaults", "fix",
                      f"{table}.{col}: {repr(bad)} -> {repr(good)}")
        else:
            print(f"  Would fix {table}.{col}: {repr(bad)} -> {repr(good)} (dry-run)")
            audit.add("schema_defaults", "fix_would",
                      f"{table}.{col}: {repr(bad)} -> {repr(good)}")


# ═══════════════════════════════════════════════════════════════════════════════
# 10. Add NOT NULL constraints
# ═══════════════════════════════════════════════════════════════════════════════
def fix_not_null_constraints(conn):
    print("\n" + "=" * 70)
    print("FIX 10: Verify and add NOT NULL constraints")
    print("=" * 70)

    checks = [
        ("viral_isolates", "accession", True),
        ("virus_master", "canonical_name", False),
    ]

    for table, col, should_add in checks:
        try:
            cur = conn.execute(f"PRAGMA table_info({table})")
            cols = {c[1]: c for c in cur.fetchall()}
            if col not in cols:
                print(f"  Table '{table}' has no column '{col}', skipping.")
                continue
            col_info = cols[col]
            is_not_null = col_info[3]  # 1 = NOT NULL, 0 = nullable
            null_count = conn.execute(
                f"SELECT COUNT(*) FROM {table} WHERE {col} IS NULL"
            ).fetchone()[0]

            print(f"  {table}.{col}: not_null={is_not_null}, null_count={null_count}")

            if is_not_null:
                print(f"    Already NOT NULL, no action needed.")
            elif should_add:
                if null_count > 0:
                    print(f"    WARNING: {null_count} NULL values exist. "
                          f"Cannot add NOT NULL constraint without fixing them first.")
                    if not DRY_RUN:
                        if table == "viral_isolates":
                            # Delete rows with NULL accession (these are invalid anyway)
                            conn.execute(f"DELETE FROM {table} WHERE {col} IS NULL")
                            print(f"    Deleted {null_count} rows with NULL {col}")
                            audit.add("not_null", "delete_nulls",
                                      f"{table}.{col}: deleted {null_count} rows")
                # Add NOT NULL via table rebuild
                if not DRY_RUN:
                    _recreate_table_add_not_null(conn, table, col)
                    print(f"    Added NOT NULL constraint on {table}.{col}")
                    audit.add("not_null", "add_constraint",
                              f"{table}.{col}")
        except sqlite3.OperationalError as e:
            print(f"  Table '{table}' error: {e}")


def _recreate_table_add_not_null(conn, table, col):
    """Recreate a table to add a NOT NULL constraint on a column."""
    # Get current SQL
    sql_row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE name = ?", (table,)
    ).fetchone()[0]

    # Add NOT NULL after the column name
    # e.g., "accession VARCHAR(50)" -> "accession VARCHAR(50) NOT NULL"
    import re as _re
    pattern = rf"({_re.escape(col)}\s+\S[^,]*?)(,|\))"
    replacement = r"\1 NOT NULL\2"
    # Apply carefully - only once
    seen = set()

    def replacer(m):
        key = m.group(0)
        if key in seen:
            return m.group(0)
        seen.add(key)
        return m.group(1) + " NOT NULL" + m.group(2)

    new_sql = _re.sub(pattern, replacer, sql_row, count=1)

    if new_sql == sql_row:
        print(f"    Regex replacement failed for {table}.{col}")
        return

    conn.execute("PRAGMA writable_schema = ON")
    conn.execute(
        "UPDATE sqlite_master SET sql = ? WHERE name = ?",
        (new_sql, table)
    )
    conn.execute("PRAGMA writable_schema = OFF")


# ═══════════════════════════════════════════════════════════════════════════════
# 11. Fix molecule_type/completeness overlap
# ═══════════════════════════════════════════════════════════════════════════════
def fix_completeness_overlap(conn):
    print("\n" + "=" * 70)
    print("FIX 11: Fix molecule_type/completeness overlap")
    print("=" * 70)

    # Set completeness to NULL where it's 'mRNA' or 'EST'
    for bad_val in ("mRNA", "EST"):
        before = conn.execute(
            "SELECT COUNT(*) FROM viral_isolates WHERE completeness = ?",
            (bad_val,)
        ).fetchone()[0]

        rows = conn.execute("""
            SELECT isolate_id, completeness, molecule_type
            FROM viral_isolates
            WHERE completeness = ?
        """, (bad_val,)).fetchall()

        if rows:
            print(f"  Found {len(rows)} records with completeness='{bad_val}':")
            for r in rows[:5]:
                print(f"    ID={r['isolate_id']}  completeness={r['completeness']}  "
                      f"molecule_type={r['molecule_type']}")
            if len(rows) > 5:
                print(f"    ... and {len(rows)-5} more")

        if not DRY_RUN:
            conn.execute(
                "UPDATE viral_isolates SET completeness = NULL WHERE completeness = ?",
                (bad_val,)
            )
            print(f"  Set completeness=NULL for {before} records with '{bad_val}'")

        audit.add("completeness_overlap", "fix",
                  f"Set completeness=NULL for {before} records with value '{bad_val}'")

    # Verify after
    remaining = conn.execute("""
        SELECT DISTINCT completeness, COUNT(*) as cnt
        FROM viral_isolates
        WHERE completeness IS NOT NULL
        GROUP BY completeness
        ORDER BY cnt DESC
    """).fetchall() if not DRY_RUN else []
    if remaining:
        print("\n  Remaining completeness values:")
        for r in remaining:
            print(f"    {str(r['completeness']):<25}  count={r['cnt']}")


# ═══════════════════════════════════════════════════════════════════════════════
# 12. Auto-fill continent from country
# ═══════════════════════════════════════════════════════════════════════════════
def fix_continent(conn):
    print("\n" + "=" * 70)
    print("FIX 12: Auto-fill continent from country")
    print("=" * 70)

    # Check if continent column exists
    try:
        conn.execute("SELECT continent FROM sample_collections LIMIT 1")
    except sqlite3.OperationalError:
        print("  'continent' column does not exist in sample_collections. Adding it.")
        if not DRY_RUN:
            conn.execute("ALTER TABLE sample_collections ADD COLUMN continent VARCHAR(50)")
            print("  Added continent column.")

    # Also check crustacean_hosts
    for table in ("sample_collections", "crustacean_hosts"):
        try:
            conn.execute(f"SELECT continent FROM {table} LIMIT 1")
        except sqlite3.OperationalError:
            print(f"  'continent' column does not exist in {table}. Adding it.")
            if not DRY_RUN:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN continent VARCHAR(50)")
                print(f"  Added continent column to {table}.")

    for table in ("sample_collections", "crustacean_hosts"):
        null_continent = conn.execute(f"""
            SELECT COUNT(*) FROM {table}
            WHERE continent IS NULL
        """).fetchone()[0]

        total = count_rows(conn, table)
        print(f"\n  {table}: {null_continent}/{total} records with NULL continent")

        # Show country distribution for those with NULL continent
        if null_continent > 0:
            countries = conn.execute(f"""
                SELECT DISTINCT country, COUNT(*) as cnt
                FROM {table}
                WHERE continent IS NULL AND country IS NOT NULL
                GROUP BY country
                ORDER BY cnt DESC
            """).fetchall()
            print(f"  Countries needing continent fill:")
            unmapped = []
            for r in countries:
                c = r["country"]
                if c in CONTINENT_MAP:
                    print(f"    {c:<35} -> {CONTINENT_MAP[c]:<15} ({r['cnt']} records)")
                else:
                    unmapped.append(c)
                    print(f"    {c:<35} -> UNMAPPED ({r['cnt']} records)")

            if unmapped:
                print(f"  WARNING: {len(unmapped)} countries not in continent map: {unmapped}")

        if not DRY_RUN and null_continent > 0:
            # Build CASE statement for continent mapping
            when_clauses = []
            for country, continent in CONTINENT_MAP.items():
                when_clauses.append(f"WHEN country = '{country.replace(chr(39), chr(39)+chr(39))}' THEN '{continent}'")

            if when_clauses:
                sql = f"""
                    UPDATE {table}
                    SET continent = CASE {''.join(when_clauses)} ELSE continent END
                    WHERE continent IS NULL AND country IS NOT NULL
                """
                conn.execute(sql)
                affected = conn.execute(
                    f"SELECT COUNT(*) FROM {table} WHERE continent IS NOT NULL"
                ).fetchone()[0] - (total - null_continent)
                print(f"  Filled continent for {affected} records in {table}")
                audit.add("continent", "auto_fill",
                          f"Filled continent for {affected} records in {table}")

                # Show remaining nulls
                remaining = conn.execute(
                    f"SELECT COUNT(*) FROM {table} WHERE continent IS NULL"
                ).fetchone()[0]
                if remaining:
                    print(f"  {remaining} records still NULL (no country or unmapped)")


# ═══════════════════════════════════════════════════════════════════════════════
# 13. Add missing indexes
# ═══════════════════════════════════════════════════════════════════════════════
def add_indexes(conn):
    print("\n" + "=" * 70)
    print("FIX 13: Add missing indexes")
    print("=" * 70)

    existing = {r[2] for r in conn.execute("SELECT * FROM sqlite_master WHERE type='index'").fetchall()}

    desired_indexes = [
        ("idx_vi_genome_length", "viral_isolates", "genome_length"),
        ("idx_vi_genome_type", "viral_isolates", "genome_type"),
        ("idx_vi_completeness", "viral_isolates", "completeness"),
        ("idx_vi_virus_name", "viral_isolates", "virus_name"),
        ("idx_vi_taxon_family", "viral_isolates", "taxon_family"),
        ("idx_vi_reference_id", "viral_isolates", "reference_id"),
        ("idx_sc_country", "sample_collections", "country"),
        ("idx_sc_continent", "sample_collections", "continent"),
        ("idx_sc_collection_year", "sample_collections", "collection_year"),
        ("idx_ir_isolate_id", "infection_records", "isolate_id"),
        ("idx_ir_host_id", "infection_records", "host_id"),
        ("idx_ir_collection_id", "infection_records", "collection_id"),
        ("idx_ch_scientific_name", "crustacean_hosts", "scientific_name"),
        ("idx_ch_host_group", "crustacean_hosts", "host_group"),
    ]

    added = 0
    for idx_name, table, col in desired_indexes:
        if idx_name not in existing:
            try:
                if not DRY_RUN:
                    conn.execute(f"CREATE INDEX {idx_name} ON {table}({col})")
                print(f"  + {idx_name} ON {table}({col})")
                added += 1
                audit.add("indexes", "create", f"{idx_name} ON {table}({col})")
            except sqlite3.OperationalError as e:
                print(f"  ! {idx_name}: {e}")
        else:
            print(f"  . {idx_name} (already exists)")

    if added == 0:
        print("  No new indexes needed.")


# ═══════════════════════════════════════════════════════════════════════════════
# 14. PRAGMA integrity_check
# ═══════════════════════════════════════════════════════════════════════════════
def run_integrity_check(conn, label="initial"):
    print(f"\n{'=' * 70}")
    print(f"INTEGRITY CHECK ({label})")
    print(f"{'=' * 70}")
    result = conn.execute("PRAGMA integrity_check").fetchone()[0]
    if result == "ok":
        print("  Result: OK")
    else:
        print(f"  Result: {result}")
    return result


# ═══════════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════════
def main():
    global DRY_RUN

    parser = argparse.ArgumentParser(
        description="Deep cleanup for crustacean_virus_core.db"
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview changes without committing")
    parser.add_argument("--audit", type=str, default=None,
                        help="Custom audit log file path")
    args = parser.parse_args()

    DRY_RUN = args.dry_run

    if DRY_RUN:
        print("=" * 70)
        print("DRY RUN MODE - No changes will be committed")
        print("=" * 70)

    # Before counts
    conn = connect_db()
    print("\nInitial table counts:")
    for table in ("viral_isolates", "crustacean_hosts", "sample_collections",
                  "infection_records", "ref_literatures"):
        try:
            cnt = count_rows(conn, table)
            audit.before_counts[table] = cnt
            print(f"  {table}: {cnt}")
        except sqlite3.OperationalError:
            print(f"  {table}: (does not exist)")

    run_integrity_check(conn, "BEFORE")

    # Apply fixes in order
    fix_chromosomes(conn)          # 1
    fix_primers(conn)              # 2
    fix_est_entries(conn)          # 3
    fix_host_placeholders(conn)    # 4
    fix_genome_type(conn)          # 5
    fix_country_names(conn)        # 6

    # Check if virus_family column exists
    tables_info = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()}

    if "virus_master" in tables_info:
        vm_cols = {r[1] for r in conn.execute("PRAGMA table_info(virus_master)").fetchall()}
        if "virus_family" in vm_cols:
            fix_unclassified_family(conn)   # 7

    fix_collection_dates(conn)     # 8
    fix_schema_defaults(conn)      # 9
    fix_not_null_constraints(conn) # 10
    fix_completeness_overlap(conn) # 11
    fix_continent(conn)            # 12
    add_indexes(conn)              # 13

    if not DRY_RUN:
        conn.commit()
        print("\n" + "=" * 70)
        print("ALL CHANGES COMMITTED")
        print("=" * 70)
    else:
        print("\n" + "=" * 70)
        print("DRY RUN COMPLETE - No changes committed")
        print("=" * 70)

    # After counts
    print("\nFinal table counts:")
    for table in ("viral_isolates", "crustacean_hosts", "sample_collections",
                  "infection_records", "ref_literatures"):
        try:
            cnt = count_rows(conn, table)
            audit.after_counts[table] = cnt
            before = audit.before_counts.get(table, "?")
            print(f"  {table}: {cnt} (was {before})")
        except sqlite3.OperationalError:
            print(f"  {table}: (does not exist)")

    run_integrity_check(conn, "AFTER" if not DRY_RUN else "AFTER (dry-run)")

    # Write audit log
    log_path = args.audit
    if log_path:
        audit.write_log(Path(log_path))
    else:
        audit.write_log()

    conn.close()


if __name__ == "__main__":
    main()
