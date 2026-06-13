"""
Emergency database cleanup script.
Fixes the most critical data contamination and normalization issues.
Safe to re-run (idempotent). Use --dry-run to preview.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "crustacean_virus_core.db"

COUNTRY_TO_CONTINENT = {
    "China": "Asia", "Taiwan": "Asia", "Japan": "Asia", "South Korea": "Asia",
    "Thailand": "Asia", "Vietnam": "Asia", "Indonesia": "Asia", "India": "Asia",
    "Iran": "Asia", "Malaysia": "Asia", "Philippines": "Asia", "Bangladesh": "Asia",
    "Sri Lanka": "Asia", "Myanmar": "Asia", "Cambodia": "Asia", "Singapore": "Asia",
    "Israel": "Asia", "Turkey": "Asia", "Saudi Arabia": "Asia",
    "United States": "North America", "United States of America": "North America",
    "Mexico": "North America", "Canada": "North America", "Cuba": "North America",
    "Nicaragua": "North America", "Panama": "North America", "Belize": "North America",
    "Honduras": "North America", "Guatemala": "North America", "Costa Rica": "North America",
    "Brazil": "South America", "Ecuador": "South America", "Colombia": "South America",
    "Venezuela": "South America", "Peru": "South America",
    "France": "Europe", "United Kingdom": "Europe", "Germany": "Europe",
    "Spain": "Europe", "Italy": "Europe", "Netherlands": "Europe",
    "Norway": "Europe", "Sweden": "Europe", "Belgium": "Europe",
    "Australia": "Oceania", "New Zealand": "Oceania", "New Caledonia": "Oceania",
    "Egypt": "Africa", "South Africa": "Africa", "Madagascar": "Africa",
    "Nigeria": "Africa", "Kenya": "Africa", "Tanzania": "Africa", "Mozambique": "Africa",
    "Russia": "Europe",
}

ABBREVIATIONS = {
    # Major crustacean viruses with standard abbreviations
    "White spot syndrome virus": "WSSV",
    "Yellow head virus": "YHV",
    "Taura syndrome virus": "TSV",
    "Infectious hypodermal and hematopoietic necrosis virus": "IHHNV",
    "Infectious myonecrosis virus": "IMNV",
    "Macrobrachium rosenbergii nodavirus": "MrNV",
    "Penaeus vannamei nodavirus": "PvNV",
    "Hepatopancreatic parvovirus": "HPV",
    "Shrimp hemocyte iridescent virus": "SHIV",
    "Decapod iridescent virus 1": "DIV1",
    "Covert mortality nodavirus": "CMNV",
    "Mourilyan virus": "MoV",
    "Laem-Singh virus": "LSNV",
    "Gill-associated virus": "GAV",
    "Lymphoid organ vacuolization virus": "LOVV",
    "Penaeus monodon nucleopolyhedrovirus": "PemoNPV",
    "Callinectes sapidus reovirus 1": "CsRV1",
    "Cherax quadricarinatus iridovirus": "CQIV",
    "Cherax destructor systemic parvo-like virus": "CdSPV",
    "Wenzhou shrimp virus": "WzSV",
    "Beihai crab virus": "BhCV",
    "Wenling crustacean virus": "WlCV",
    "Penaeus monodon metallovirus": "PmMV",
    "Macrobrachium rosenbergii Golda virus": "MrGV",
    "Scylla serrata reovirus SZ-2007": "SsRV",
    "Chinese mitten crab virus": "CMCV",
    "Brine shrimp chuvirus 1": "BsCV1",
    "Brine shrimp chuvirus 2": "BsCV2",
    "Brine shrimp chuvirus 3": "BsCV3",
    "Brine shrimp iflavirus 1": "BsIV1",
    "Brine shrimp iflavirus 3": "BsIV3",
    "Crab associated circular virus": "CaCV",
    "Beihai shrimp virus": "BhSV",
    "Wenzhou crab virus": "WzCV",
    "Beihai crab virus": "BhCV",
    "Wenling crustacean virus": "WlCV",
    "Qianjiang marna-like virus 130": "QjMLV130",
    "Qianjiang marna-like virus 147": "QjMLV147",
}

# Virus master entries that are actually host species, not viruses
HOST_NAMES_IN_VIRUS_MASTER = {
    "Portunus trituberculatus",
    "Procambarus clarkii",
}


def run_cleanup(conn: sqlite3.Connection, dry_run: bool = False) -> dict:
    """Execute all cleanup operations. Returns change log."""
    c = conn.cursor()
    log: dict[str, int] = {}

    def count(sql: str, params: tuple = ()) -> int:
        return c.execute(sql, params).fetchone()[0]

    def execute(sql: str, params: tuple = (), label: str = "") -> int:
        if dry_run:
            affected = 0
            if sql.strip().upper().startswith("DELETE"):
                # For dry-run DELETEs, count what would be affected
                affected_sql = sql.replace("DELETE FROM", "SELECT COUNT(*) FROM", 1)
                # Remove ORDER BY / LIMIT for count
                affected_sql = affected_sql.rsplit("ORDER BY", 1)[0] if "ORDER BY" in affected_sql else affected_sql
                try:
                    affected = c.execute(affected_sql, params).fetchone()[0]
                except Exception:
                    affected = 0
            elif sql.strip().upper().startswith("UPDATE"):
                affected_sql = f"SELECT COUNT(*) FROM ({sql.split('SET')[0].replace('UPDATE', 'FROM', 1)} WHERE {sql.split('WHERE', 1)[1] if 'WHERE' in sql else '1=1'}".replace("UPDATE ", "FROM ", 1)
                try:
                    w = sql.split("WHERE", 1)[1].rsplit("ORDER BY", 1)[0] if "ORDER BY" in sql else sql.split("WHERE", 1)[1]
                    tbl = sql.split("UPDATE ")[1].split(" SET")[0]
                    affected = c.execute(f"SELECT COUNT(*) FROM {tbl} WHERE {w}", params).fetchone()[0]
                except Exception:
                    affected = 0
            log[label] = affected
            print(f"  [DRY RUN] {label}: {affected} rows would be affected")
            return affected
        else:
            c.execute(sql, params)
            affected = c.rowcount
            log[label] = affected
            print(f"  {label}: {affected} rows")
            return affected

    print("=" * 60)
    mode = "DRY RUN" if dry_run else "EXECUTING"
    print(f"Emergency Cleanup - {mode}")
    print("=" * 60)

    # Disable FK constraints for batch cleanup of confirmed contamination
    if not dry_run:
        c.execute("PRAGMA foreign_keys = OFF")
        print("(FK constraints temporarily disabled for contamination cleanup)")

    # ── 1. Remove host chromosomes (genome_length > 1M) ──
    print("\n[1] Host chromosome removal (genome_length > 1,000,000)")
    before = count("SELECT COUNT(*) FROM viral_isolates WHERE genome_length > 1000000")
    print(f"  Before: {before} records")
    if before > 0:
        for row in c.execute(
            "SELECT accession, virus_name, genome_length FROM viral_isolates WHERE genome_length > 1000000"
        ).fetchall():
            print(f"    Removing: {row[0]} ({row[1][:60]}) {row[2]:,} bp")
        execute(
            "DELETE FROM viral_isolates WHERE genome_length > 1000000",
            label="host_chromosomes_removed",
        )
    after = count("SELECT COUNT(*) FROM viral_isolates WHERE genome_length > 1000000")
    print(f"  After: {after} records")

    # ── 2. Remove primer/amplicon sequences (genome_length < 50) ──
    print("\n[2] Primer/amplicon removal (genome_length < 50)")
    before = count("SELECT COUNT(*) FROM viral_isolates WHERE genome_length IS NOT NULL AND genome_length < 50")
    print(f"  Before: {before} records")
    if before > 0:
        for row in c.execute(
            "SELECT accession, virus_name, genome_length FROM viral_isolates WHERE genome_length IS NOT NULL AND genome_length < 50 LIMIT 10"
        ).fetchall():
            print(f"    Removing: {row[0]} ({row[1][:60]}) {row[2]} bp")
        execute(
            "DELETE FROM viral_isolates WHERE genome_length IS NOT NULL AND genome_length < 50",
            label="primers_removed",
        )
    after = count("SELECT COUNT(*) FROM viral_isolates WHERE genome_length IS NOT NULL AND genome_length < 50")
    print(f"  After: {after} records")

    # ── 3. Remove EST entries ──
    print("\n[3] EST entry removal (virus_name LIKE 'EST0%' AND completeness='EST')")
    before = count(
        "SELECT COUNT(*) FROM viral_isolates WHERE virus_name LIKE 'EST0%' AND completeness = 'EST'"
    )
    print(f"  Before: {before} records")
    if before > 0:
        execute(
            "DELETE FROM viral_isolates WHERE virus_name LIKE 'EST0%' AND completeness = 'EST'",
            label="est_entries_removed",
        )
    after = count(
        "SELECT COUNT(*) FROM viral_isolates WHERE virus_name LIKE 'EST0%' AND completeness = 'EST'"
    )
    print(f"  After: {after} records")

    # ── 4. Remove unresolved host placeholders ──
    print("\n[4] Unresolved host placeholder removal")
    before = count(
        "SELECT COUNT(*) FROM crustacean_hosts WHERE scientific_name LIKE 'Unresolved host placeholder%'"
    )
    print(f"  Before: {before} records")
    if before > 0:
        # First delete any infection records referencing these hosts
        execute(
            "DELETE FROM infection_records WHERE host_id IN (SELECT host_id FROM crustacean_hosts WHERE scientific_name LIKE 'Unresolved host placeholder%')",
            label="orphaned_infection_records",
        )
        execute(
            "DELETE FROM crustacean_hosts WHERE scientific_name LIKE 'Unresolved host placeholder%'",
            label="placeholder_hosts_removed",
        )
    after = count(
        "SELECT COUNT(*) FROM crustacean_hosts WHERE scientific_name LIKE 'Unresolved host placeholder%'"
    )
    print(f"  After: {after} records")

    # ── 5. Normalize genome_type ──
    print("\n[5] Genome type normalization")
    for old_val, new_val in [("+ssRNA", "ssRNA(+)")]:
        cnt = count("SELECT COUNT(*) FROM viral_isolates WHERE genome_type = ?", (old_val,))
        if cnt > 0:
            execute(
                f"UPDATE viral_isolates SET genome_type = ? WHERE genome_type = ?",
                (new_val, old_val),
                label=f"genome_type '{old_val}' -> '{new_val}'",
            )
    for old_val in ["+ssRNA"]:
        cnt = count("SELECT COUNT(*) FROM virus_master WHERE genome_type = ?", (old_val,))
        if cnt > 0:
            execute(
                "UPDATE virus_master SET genome_type = ? WHERE genome_type = ?",
                ("ssRNA(+)", old_val),
                label=f"master_genome_type '{old_val}' -> 'ssRNA(+)'",
            )

    # ── 6. Normalize country names ──
    print("\n[6] Country name normalization")
    execute(
        "UPDATE sample_collections SET country = 'United States' WHERE country = 'United States of America'",
        label="country_normalized",
    )

    # ── 7. Normalize virus_family ──
    print("\n[7] Virus family normalization")
    for old_fam in ["Unclassified (+ssRNA)", "Unclassified (ssRNA)"]:
        cnt = count("SELECT COUNT(*) FROM virus_master WHERE virus_family = ?", (old_fam,))
        if cnt > 0:
            execute(
                "UPDATE virus_master SET virus_family = 'Unclassified' WHERE virus_family = ?",
                (old_fam,),
                label=f"family '{old_fam}' -> 'Unclassified'",
            )

    # ── 7b. Flag host species leaked into virus_master ──
    print("\n[7b] Host species in virus_master (leaked from host table)")
    for host_name in HOST_NAMES_IN_VIRUS_MASTER:
        cnt = count("SELECT COUNT(*) FROM virus_master WHERE canonical_name = ?", (host_name,))
        if cnt > 0:
            print(f"    WARNING: '{host_name}' is a CRAB SPECIES in virus_master (not a virus)!")
            execute(
                "UPDATE virus_master SET entry_type = 'host_genome', virus_family = NULL WHERE canonical_name = ?",
                (host_name,),
                label=f"host_species_flag '{host_name}' -> entry_type='host_genome'",
            )

    # ── 8. Fill continent from country ──
    print("\n[8] Continent auto-fill from country")
    before = count("SELECT COUNT(*) FROM sample_collections WHERE (continent IS NULL OR continent = '') AND country IS NOT NULL AND country != ''")
    print(f"  Before: {before} NULL continents")
    filled = 0
    for row in c.execute(
        "SELECT collection_id, country FROM sample_collections WHERE (continent IS NULL OR continent = '') AND country IS NOT NULL AND country != ''"
    ).fetchall():
        cid, country = row[0], row[1]
        continent = COUNTRY_TO_CONTINENT.get(country)
        if continent and not dry_run:
            c.execute("UPDATE sample_collections SET continent = ? WHERE collection_id = ?", (continent, cid))
            filled += 1
        elif continent:
            filled += 1
    log["continent_filled"] = filled
    print(f"  Filled: {filled}")
    after = count("SELECT COUNT(*) FROM sample_collections WHERE (continent IS NULL OR continent = '') AND country IS NOT NULL AND country != ''")
    print(f"  Remaining NULL: {after}")

    # ── 9. Fill virus abbreviations ──
    print("\n[9] Virus abbreviation backfill")
    before = count("SELECT COUNT(*) FROM virus_master WHERE abbreviations IS NULL OR TRIM(abbreviations) = ''")
    print(f"  Before: {before} NULL abbreviations")
    filled = 0
    for row in c.execute(
        "SELECT master_id, canonical_name FROM virus_master WHERE abbreviations IS NULL OR TRIM(abbreviations) = ''"
    ).fetchall():
        mid, name = row[0], row[1]
        abbr = ABBREVIATIONS.get(name)
        if abbr and not dry_run:
            c.execute("UPDATE virus_master SET abbreviations = ? WHERE master_id = ?", (abbr, mid))
            filled += 1
        elif abbr:
            filled += 1
    log["abbreviations_filled"] = filled
    print(f"  Filled: {filled}")
    after = count("SELECT COUNT(*) FROM virus_master WHERE abbreviations IS NULL OR TRIM(abbreviations) = ''")
    print(f"  Remaining NULL: {after}")

    # ── 10. Fix schema default values ──
    print("\n[10] Schema default value fixes")
    # SQLite doesn't support ALTER COLUMN default, but we can document the issue
    c.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='virus_master'")
    master_sql = c.fetchone()[0]
    if "''complete_genome''" in master_sql:
        print("  WARNING: virus_master.entry_type has malformed default ''complete_genome''")
        print("  This requires table recreation to fix. Documented as known issue.")
    c.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='sample_collections'")
    sc_sql = c.fetchone()[0]
    if "''country''" in sc_sql:
        print("  WARNING: sample_collections.coordinate_precision has malformed default ''country''")

    # ── 11. Fix molecule_type/completeness overlap ──
    print("\n[11] Fix molecule_type/completeness overlap")
    for val in ["mRNA", "EST"]:
        cnt = count("SELECT COUNT(*) FROM viral_isolates WHERE completeness = ?", (val,))
        if cnt > 0:
            # If molecule_type is NULL, set it to this value
            execute(
                "UPDATE viral_isolates SET molecule_type = ?, completeness = NULL WHERE completeness = ? AND molecule_type IS NULL",
                (val, val),
                label=f"moved completeness='{val}' to molecule_type",
            )
            # If molecule_type already has a value, just clear completeness
            execute(
                "UPDATE viral_isolates SET completeness = NULL WHERE completeness = ? AND molecule_type IS NOT NULL",
                (val,),
                label=f"cleared completeness='{val}' (already in molecule_type)",
            )

    # ── 12. Add collection_year CHECK constraint (best effort) ──
    print("\n[12] Data quality notes")
    bad_years = count(
        "SELECT COUNT(*) FROM sample_collections WHERE collection_year IS NOT NULL AND collection_year NOT GLOB '[0-9][0-9][0-9][0-9]' AND collection_year NOT GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]'"
    )
    print(f"  Non-standard collection_year values: {bad_years}")

    # ── Integrity check ──
    print("\n[13] Integrity check")
    if not dry_run:
        c.execute("PRAGMA foreign_keys = ON")
        print("  (FK constraints re-enabled)")
    result = c.execute("PRAGMA integrity_check").fetchone()[0]
    print(f"  Integrity: {result}")

    if not dry_run:
        conn.commit()
        print("\nAll changes committed.")
    else:
        print("\n[DRY RUN] No changes made. Re-run without --dry-run to execute.")

    return log


def main() -> None:
    parser = argparse.ArgumentParser(description="Emergency database cleanup")
    parser.add_argument("--dry-run", action="store_true", help="Preview changes only")
    args = parser.parse_args()

    conn = sqlite3.connect(str(DB_PATH), timeout=60)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")

    try:
        log = run_cleanup(conn, dry_run=args.dry_run)

        # Export change log
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_path = Path(__file__).resolve().parent / "reports" / f"emergency_cleanup_{stamp}.json"
        log_path.parent.mkdir(exist_ok=True)
        log_path.write_text(json.dumps({
            "script": "emergency_cleanup.py",
            "dry_run": args.dry_run,
            "changes": log,
            "timestamp": datetime.now().isoformat(),
        }, indent=2, ensure_ascii=False), encoding="utf-8")

        print(f"\nChange log: {log_path}")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
