"""
Comprehensive taxonomy and data quality fix script for crustacean virus database.

Fixes:
1. Fill missing abbreviations (abbreviations column) in virus_master for all known viruses
2. Consolidate genome_type vocabulary (ssRNA(+) vs +ssRNA)
3. Normalize virus_family 'Unclassified*' variants to plain 'Unclassified'
4. Fill NULL virus_family entries (5 expected) via NCBI taxonomy lookup or mark as Unclassified
5. Fill missing continent values in sample_collections using country->continent mapping
6. Verify ICTV taxonomy mapping coverage and print gap analysis

Usage:
    python fix_taxonomy.py               # full run (with backup)
    python fix_taxonomy.py --dry-run     # preview only, no changes
    python fix_taxonomy.py --no-backup   # skip backup
"""

from __future__ import annotations

import json
import re
import shutil
import sqlite3
import time
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any


BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "crustacean_virus_core.db"
BACKUP_DIR = BASE_DIR / "backups"
NCBI_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
REQUEST_DELAY = 0.35
CONTACT_EMAIL = "curator@crustacean-virus-db.org"

# ═══════════════════════════════════════════════════════════════════════════════
# 1. Comprehensive canonical_name -> abbreviation mapping
# ═══════════════════════════════════════════════════════════════════════════════
# Includes every virus from normalize_virus_names.py rules plus additional
# literature-standard abbreviations for crustacean viruses.
# Key: lowercase canonical_name (for matching)
# Value: standard abbreviation string
ABBREVIATION_MAP: dict[str, str] = {
    # Major shrimp viruses (OIE-listed + well known)
    "white spot syndrome virus": "WSSV",
    "yellow head virus": "YHV",
    "taura syndrome virus": "TSV",
    "infectious hypodermal and hematopoietic necrosis virus": "IHHNV",
    "infectious myonecrosis virus": "IMNV",
    "macrobrachium rosenbergii nodavirus": "MrNV",
    "covert mortality nodavirus": "CMNV",
    "hepatopancreatic parvovirus": "HPV",
    "laem-singh virus": "LSNV",
    "gill-associated virus": "GAV",
    "mourilyan virus": "MoV",
    "decapod iridescent virus": "DIV1",
    "shrimp hemocyte iridescent virus": "SHIV",
    "penaeus vannamei nodavirus": "PvNV",
    "crab associated circular virus": "CACV",
    "penaeus monodon endogenous virus": "PMEV",

    # Wenzhou viruses
    "wenzhou shrimp virus": "WZSV",
    "wenzhou shrimp virus 1": "WZSV-1",
    "wenzhou shrimp virus 2": "WZSV-2",
    "wenzhou crab virus": "WZCV",
    "wenzhou crab virus 2": "WZCV-2",
    "wenzhou crab virus 3": "WZCV-3",

    # Beihai viruses
    "beihai shrimp virus": "BHSV",
    "beihai crab virus": "BHCV",

    # Other crustacean viruses
    "chinese mitten crab virus": "CMCV",
    "shrimp glass disease virus": "SGDV",
    "infectious precocity virus": "IPV",
    "iridovirus cn01": "IVCN01",
    "european shore crab virus 1": "ESCV-1",
    "mud crab virus": "MCV",
    "penaeus monodon rna virus": "PMRV",
    "penaeus stylirostris penstyldensovirus": "PstDNV",
    "penaeus monodon densovirus": "PmoDNV",
    "macrobrachium rosenbergii golda virus": "MrGV",
    "portunus trituberculatus alphacoronavirus": "PtACV",
    "portunus trituberculatus coronavirus": "PtCV",
    "eriocheir sinensis picornavirus": "EsPV",
    "eriocheir sinensis reovirus": "EsRV",
    "eriocheir sinensis coronavirus": "EsCV",
    "eriocheir sinensis hepacivirus": "EsHV",
    "eriocheir sinensis cholera-like virus": "EsCLV",
    "eriocheir sinensis densovirus": "EsDNV",
    "scylla serrata reovirus": "SsRV",
    "scylla serrata nudivirus": "SsNV",
    "homarus gammarus nudivirus": "HgNV",
    "procambarus clarkii virus": "PcV",
    "cherax quadricarinatus densovirus": "CqDNV",
    "cherax quadricarinatus iridovirus": "CqIV",
    "astacus astacus virus": "AaV",

    # Non-crustacean (included for completeness)
    "human immunodeficiency virus": "HIV",
    "african swine fever virus": "ASFV",
    "sars-cov-2": "SARS-CoV-2",

    # Generic bucket
    "unknown/unclassified": "",
    "non-crustacean virus": "",
}


# ═══════════════════════════════════════════════════════════════════════════════
# 2. Genome_type consolidation mapping
# ═══════════════════════════════════════════════════════════════════════════════
# Maps variant values to the standard form
GENOME_TYPE_VARIANTS: dict[str, str] = {
    "+ssRNA": "ssRNA(+)",
    "ssRNA(+)": "ssRNA(+)",       # already canonical, identity mapping
    # Keep others as they are — these are the standard values
    "-ssRNA": "-ssRNA",
    "dsRNA": "dsRNA",
    "dsDNA": "dsDNA",
    "ssDNA": "ssDNA",
    "RNA": "RNA",
}

# Values that should be consolidated TO ssRNA(+)
GENOME_TYPE_CONSOLIDATE_SRC = {"+ssRNA"}


# ═══════════════════════════════════════════════════════════════════════════════
# 3. Country -> Continent mapping (extended from enhance_geography.py)
# ═══════════════════════════════════════════════════════════════════════════════
COUNTRY_TO_CONTINENT: dict[str, str] = {
    # Asia
    "china": "Asia",
    "people's republic of china": "Asia",
    "thailand": "Asia",
    "india": "Asia",
    "viet nam": "Asia",
    "vietnam": "Asia",
    "indonesia": "Asia",
    "japan": "Asia",
    "south korea": "Asia",
    "korea": "Asia",
    "republic of korea": "Asia",
    "philippines": "Asia",
    "malaysia": "Asia",
    "bangladesh": "Asia",
    "myanmar": "Asia",
    "taiwan": "Asia",
    "iran": "Asia",
    "israel": "Asia",
    "saudi arabia": "Asia",
    "kuwait": "Asia",
    "united arab emirates": "Asia",
    "uae": "Asia",
    "pakistan": "Asia",
    "sri lanka": "Asia",
    "singapore": "Asia",
    "hong kong": "Asia",
    "cambodia": "Asia",
    "laos": "Asia",
    "nepal": "Asia",
    "turkey": "Asia",
    "russia": "Asia",
    "russian federation": "Asia",

    # North America
    "united states": "North America",
    "usa": "North America",
    "united states of america": "North America",
    "canada": "North America",
    "mexico": "North America",
    "greenland": "North America",
    "puerto rico": "North America",
    "costa rica": "North America",
    "panama": "North America",
    "guatemala": "North America",
    "honduras": "North America",
    "nicaragua": "North America",
    "cuba": "North America",
    "jamaica": "North America",
    "dominican republic": "North America",
    "trinidad and tobago": "North America",
    "bahamas": "North America",

    # South America
    "ecuador": "South America",
    "brazil": "South America",
    "peru": "South America",
    "venezuela": "South America",
    "colombia": "South America",
    "chile": "South America",
    "argentina": "South America",
    "uruguay": "South America",
    "paraguay": "South America",
    "bolivia": "South America",
    "guyana": "South America",
    "suriname": "South America",
    "french guiana": "South America",

    # Europe
    "france": "Europe",
    "united kingdom": "Europe",
    "uk": "Europe",
    "germany": "Europe",
    "netherlands": "Europe",
    "italy": "Europe",
    "spain": "Europe",
    "greece": "Europe",
    "norway": "Europe",
    "denmark": "Europe",
    "belgium": "Europe",
    "portugal": "Europe",
    "poland": "Europe",
    "switzerland": "Europe",
    "austria": "Europe",
    "sweden": "Europe",
    "finland": "Europe",
    "ireland": "Europe",
    "iceland": "Europe",
    "croatia": "Europe",
    "czech republic": "Europe",
    "hungary": "Europe",
    "romania": "Europe",
    "ukraine": "Europe",
    "bulgaria": "Europe",
    "serbia": "Europe",
    "slovenia": "Europe",
    "slovakia": "Europe",
    "lithuania": "Europe",
    "latvia": "Europe",
    "estonia": "Europe",
    "cyprus": "Europe",
    "malta": "Europe",
    "luxembourg": "Europe",
    "monaco": "Europe",
    "norway": "Europe",
    "faroe islands": "Europe",

    # Oceania
    "australia": "Oceania",
    "new zealand": "Oceania",
    "fiji": "Oceania",
    "papua new guinea": "Oceania",
    "solomon islands": "Oceania",
    "vanuatu": "Oceania",
    "samoa": "Oceania",
    "tonga": "Oceania",
    "micronesia": "Oceania",
    "palau": "Oceania",
    "marshall islands": "Oceania",
    "new caledonia": "Oceania",
    "french polynesia": "Oceania",
    "guam": "Oceania",
    "northern mariana islands": "Oceania",

    # Africa
    "madagascar": "Africa",
    "south africa": "Africa",
    "egypt": "Africa",
    "nigeria": "Africa",
    "kenya": "Africa",
    "tanzania": "Africa",
    "morocco": "Africa",
    "namibia": "Africa",
    "algeria": "Africa",
    "angola": "Africa",
    "botswana": "Africa",
    "congo": "Africa",
    "democratic republic of the congo": "Africa",
    "ethiopia": "Africa",
    "ghana": "Africa",
    "ivory coast": "Africa",
    "cote d'ivoire": "Africa",
    "libya": "Africa",
    "malawi": "Africa",
    "mauritius": "Africa",
    "mozambique": "Africa",
    "senegal": "Africa",
    "somalia": "Africa",
    "sudan": "Africa",
    "tunisia": "Africa",
    "uganda": "Africa",
    "zambia": "Africa",
    "zimbabwe": "Africa",
    "réunion": "Africa",
    "reunion": "Africa",
    "seychelles": "Africa",
    "sierra leone": "Africa",
    "cameron": "Africa",
    "cameroon": "Africa",
}


# ═══════════════════════════════════════════════════════════════════════════════
# Utility functions
# ═══════════════════════════════════════════════════════════════════════════════

def backup_database() -> Path:
    BACKUP_DIR.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = BACKUP_DIR / f"crustacean_virus_core_before_taxonomy_fix_{stamp}.db"
    shutil.copy2(DB_PATH, backup_path)
    print(f"[backup] {backup_path}")
    return backup_path


def log_change(conn: sqlite3.Connection, entity_type: str, action: str,
               new_value: str, notes: str, confidence: str = "high") -> None:
    """Insert a row into curation_logs if the table exists."""
    try:
        conn.execute(
            """INSERT INTO curation_logs
               (entity_type, action, new_value, confidence, curator, notes)
             VALUES (?, ?, ?, ?, ?, ?)""",
            (entity_type, action, new_value, confidence, "fix_taxonomy.py", notes),
        )
    except sqlite3.OperationalError:
        pass  # table may not exist


def ncbi_taxonomy_search(name: str) -> list[dict]:
    """Search NCBI Taxonomy by name."""
    import xml.etree.ElementTree as ET

    params = urllib.parse.urlencode({
        "db": "taxonomy",
        "term": name,
        "retmax": "5",
        "retmode": "json",
        "tool": "crustacean_virus_db",
        "email": CONTACT_EMAIL,
    })
    url = f"{NCBI_BASE}/esearch.fcgi?{params}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "crustacean-virus-db-curation/1.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        print(f"    [warn] NCBI search failed for '{name}': {exc}")
        return []

    id_list = (data or {}).get("esearchresult", {}).get("idlist", [])
    if not id_list:
        return []

    fetch_params = urllib.parse.urlencode({
        "db": "taxonomy",
        "id": ",".join(id_list),
        "retmode": "xml",
        "tool": "crustacean_virus_db",
        "email": CONTACT_EMAIL,
    })
    fetch_url = f"{NCBI_BASE}/efetch.fcgi?{fetch_params}"
    try:
        req = urllib.request.Request(fetch_url, headers={"User-Agent": "crustacean-virus-db-curation/1.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            xml_data = resp.read().decode("utf-8")
    except Exception as exc:
        print(f"    [warn] NCBI fetch failed for TaxIDs {id_list}: {exc}")
        return []

    results: list[dict] = []
    try:
        root = ET.fromstring(xml_data)
        for taxon in root.iter("Taxon"):
            tax_id = taxon.findtext("TaxId", "")
            sci_name = taxon.findtext("ScientificName", "")
            rank = taxon.findtext("Rank", "")
            lineage = taxon.findtext("Lineage", "")

            family = None
            genus = None
            for lineage_ex in taxon.iter("LineageEx"):
                for tx in lineage_ex.iter("Taxon"):
                    tx_rank = (tx.findtext("Rank") or "").lower().strip()
                    tx_name = (tx.findtext("ScientificName") or "").strip()
                    if tx_rank == "family":
                        family = tx_name
                    elif tx_rank == "genus":
                        genus = tx_name

            results.append({
                "taxid": tax_id,
                "name": sci_name,
                "rank": rank,
                "lineage": lineage,
                "family": family,
                "genus": genus,
            })
    except ET.ParseError as exc:
        print(f"    [warn] XML parse error for TaxIDs {id_list}: {exc}")

    return results


def get_ncbi_source_id(conn: sqlite3.Connection) -> int | None:
    """Get the NCBI taxonomy source ID."""
    row = conn.execute(
        "SELECT source_id FROM external_sources WHERE source_key = ?",
        ("ncbi_taxonomy",),
    ).fetchone()
    return row["source_id"] if row else None


# ═══════════════════════════════════════════════════════════════════════════════
# Fix 1: Fill missing abbreviations
# ═══════════════════════════════════════════════════════════════════════════════

def fix_missing_abbreviations(conn: sqlite3.Connection, dry_run: bool) -> dict[str, Any]:
    """Fill empty/NULL abbreviations in virus_master using the ABBREVIATION_MAP."""
    stats: dict[str, Any] = {
        "total_missing": 0,
        "filled": 0,
        "already_had": 0,
        "still_missing": 0,
        "updated_rows": [],
    }

    # Actually we need to find all rows where abbreviations is NULL or empty
    rows = conn.execute(
        "SELECT master_id, canonical_name, abbreviations FROM virus_master"
    ).fetchall()

    missing_rows = [r for r in rows if not r["abbreviations"] or not r["abbreviations"].strip()]
    stats["total_missing"] = len(missing_rows)

    print(f"\n{'='*60}")
    print("FIX 1: Missing abbreviations")
    print(f"{'='*60}")
    print(f"  Records with missing abbreviations: {len(missing_rows)}")

    for row in missing_rows:
        master_id = row["master_id"]
        canonical = row["canonical_name"]
        key = canonical.strip().lower()

        if key in ABBREVIATION_MAP:
            new_abbr = ABBREVIATION_MAP[key]
            if new_abbr:
                if dry_run:
                    print(f"  [dry-run] mid={master_id:4d} {canonical[:50]:50s} -> {new_abbr}")
                else:
                    conn.execute(
                        "UPDATE virus_master SET abbreviations = ? WHERE master_id = ?",
                        (new_abbr, master_id),
                    )
                    log_change(conn, "virus_master", "set_abbreviation",
                               new_abbr, f"Set abbreviation for {canonical} -> {new_abbr}")
                stats["filled"] += 1
                stats["updated_rows"].append({"master_id": master_id, "canonical_name": canonical, "abbreviation": new_abbr})
            else:
                # Explicit empty string in map means "no standard abbreviation" (bucket records)
                if dry_run:
                    print(f"  [dry-run] mid={master_id:4d} {canonical[:50]:50s} -> (intentionally empty)")
                stats["still_missing"] += 1
        else:
            # Not in our map — no known standard abbreviation
            if dry_run:
                print(f"  [dry-run] mid={master_id:4d} {canonical[:50]:50s} -> (no mapping found)")
            stats["still_missing"] += 1

    if not dry_run:
        conn.commit()

    print(f"\n  Result: filled={stats['filled']}, still_missing={stats['still_missing']}")
    return stats


# ═══════════════════════════════════════════════════════════════════════════════
# Fix 2: Consolidate genome_type vocabulary
# ═══════════════════════════════════════════════════════════════════════════════

def fix_genome_type_vocabulary(conn: sqlite3.Connection, dry_run: bool) -> dict[str, Any]:
    """Consolidate genome_type variants: '+ssRNA' -> 'ssRNA(+)'."""
    stats: dict[str, Any] = {
        "variants_found": {},
        "records_affected": 0,
        "updated_per_variant": {},
    }

    # Check all tables that have genome_type column
    tables_to_check = []

    # Check virus_master
    try:
        cols = [r["name"] for r in conn.execute("PRAGMA table_info(virus_master)")]
        if "genome_type" in cols:
            tables_to_check.append("virus_master")
    except Exception:
        pass

    # Check viral_isolates
    try:
        cols = [r["name"] for r in conn.execute("PRAGMA table_info(viral_isolates)")]
        if "genome_type" in cols:
            tables_to_check.append("viral_isolates")
    except Exception:
        pass

    # Check isolate_curated_profiles
    try:
        cols = [r["name"] for r in conn.execute("PRAGMA table_info(isolate_curated_profiles)")]
        if "genome_type" in cols:
            tables_to_check.append("isolate_curated_profiles")
    except Exception:
        pass

    print(f"\n{'='*60}")
    print("FIX 2: Genome type vocabulary consolidation")
    print(f"{'='*60}")

    for table in tables_to_check:
        existing_cols = [c[1] for c in conn.execute(f"PRAGMA table_info({table})").fetchall()]
        if "genome_type" not in existing_cols:
            continue
        # Get distinct values
        values = conn.execute(
            f"SELECT DISTINCT genome_type FROM {table} WHERE genome_type IS NOT NULL"
        ).fetchall()
        for v in values:
            val = v["genome_type"]
            if val not in stats["variants_found"]:
                stats["variants_found"][val] = 0
            # Count records for this value in this table
            cnt = conn.execute(
                f"SELECT COUNT(*) as cnt FROM {table} WHERE genome_type = ?", (val,)
            ).fetchone()["cnt"]
            stats["variants_found"][val] += cnt

    print(f"  Current genome_type distribution:")
    for val, cnt in sorted(stats["variants_found"].items(), key=lambda x: -x[1]):
        src = GENOME_TYPE_CONSOLIDATE_SRC
        target = "ssRNA(+)" if val in src else "(canonical)"
        print(f"    {val:30s} x {cnt:5d}  {target}")

    for variant in GENOME_TYPE_CONSOLIDATE_SRC:
        target = "ssRNA(+)"
        affected = 0
        for table in tables_to_check:
            existing_cols = [c[1] for c in conn.execute(f"PRAGMA table_info({table})").fetchall()]
            if "genome_type" not in existing_cols:
                continue
            cnt = conn.execute(
                f"SELECT COUNT(*) as cnt FROM {table} WHERE genome_type = ?", (variant,)
            ).fetchone()["cnt"]
            if cnt > 0:
                if dry_run:
                    print(f"  [dry-run] {table}: {cnt} records with '{variant}' -> '{target}'")
                else:
                    conn.execute(
                        f"UPDATE {table} SET genome_type = ? WHERE genome_type = ?",
                        (target, variant),
                    )
                affected += cnt
        stats["records_affected"] += affected
        stats["updated_per_variant"][variant] = affected

    if not dry_run and stats["records_affected"] > 0:
        conn.commit()
        log_change(conn, "virus_master", "genome_type_consolidation",
                   f"Consolidated {stats['records_affected']} records",
                   f"Variants consolidated: {dict(stats['updated_per_variant'])}")

    print(f"  Records affected: {stats['records_affected']}")
    return stats


# ═══════════════════════════════════════════════════════════════════════════════
# Fix 3: Normalize 'Unclassified*' virus_family variants
# ═══════════════════════════════════════════════════════════════════════════════

def fix_unclassified_family_variants(conn: sqlite3.Connection, dry_run: bool) -> dict[str, Any]:
    """Normalise all 'Unclassified...' variants to plain 'Unclassified'."""
    stats: dict[str, Any] = {
        "variants_found": {},
        "records_affected": 0,
        "updated_rows": [],
    }

    tables_to_check = ["virus_master", "viral_isolates"]
    # Check if isolate_curated_profiles has virus_family
    try:
        cols = [r["name"] for r in conn.execute("PRAGMA table_info(isolate_curated_profiles)")]
        if "virus_family" in cols:
            tables_to_check.append("isolate_curated_profiles")
    except Exception:
        pass

    # Also check ictv_taxonomy and ictv_vmr for family column
    for t in ["ictv_taxonomy", "ictv_vmr"]:
        try:
            cols = [r["name"] for r in conn.execute(f"PRAGMA table_info({t})")]
            if "family" in cols:
                tables_to_check.append(t)
        except Exception:
            pass

    print(f"\n{'='*60}")
    print("FIX 3: Unclassified family variant normalization")
    print(f"{'='*60}")

    # Find all variant values starting with 'Unclassified' (case-insensitive)
    for table in tables_to_check:
        # Check which family column actually exists
        existing_cols = [c[1] for c in conn.execute(f"PRAGMA table_info({table})").fetchall()]
        family_col = None
        for candidate in ("virus_family", "taxon_family", "family"):
            if candidate in existing_cols:
                family_col = candidate
                break
        if not family_col:
            continue  # skip tables without a family column
        rows = conn.execute(
            f"""SELECT DISTINCT {family_col} as fam FROM {table}
                WHERE {family_col} LIKE 'Unclassified%'
                   OR {family_col} LIKE 'unclassified%'
                   OR {family_col} LIKE 'Unclassified %'"""
        ).fetchall()

        for r in rows:
            val = r["fam"]
            if val and val.lower().startswith("unclassified") and val.strip() != "Unclassified":
                cnt = conn.execute(
                    f"SELECT COUNT(*) as cnt FROM {table} WHERE {family_col} = ?", (val,)
                ).fetchone()["cnt"]
                stats["variants_found"].setdefault(val, 0)
                stats["variants_found"][val] += cnt

    print(f"  Variant values found:")
    for val, cnt in sorted(stats["variants_found"].items(), key=lambda x: -x[1]):
        print(f"    '{val}' x {cnt}")

    # Fix: replace each variant with 'Unclassified'
    for table in tables_to_check:
        existing_cols = [c[1] for c in conn.execute(f"PRAGMA table_info({table})").fetchall()]
        family_col = None
        for candidate in ("virus_family", "taxon_family", "family"):
            if candidate in existing_cols:
                family_col = candidate
                break
        if not family_col:
            continue
        for variant, _ in stats["variants_found"].items():
            cnt = conn.execute(
                f"SELECT COUNT(*) as cnt FROM {table} WHERE {family_col} = ?", (variant,)
            ).fetchone()["cnt"]
            if cnt > 0:
                if dry_run:
                    print(f"  [dry-run] {table}: {cnt} records '{variant}' -> 'Unclassified'")
                else:
                    conn.execute(
                        f"UPDATE {table} SET {family_col} = 'Unclassified' WHERE {family_col} = ?",
                        (variant,),
                    )
                stats["records_affected"] += cnt

    if not dry_run and stats["records_affected"] > 0:
        conn.commit()
        log_change(conn, "virus_master", "unclassified_family_normalization",
                   f"Unclassified", f"Normalized {stats['records_affected']} records from variants: {list(stats['variants_found'].keys())}")

    print(f"  Records affected: {stats['records_affected']}")
    return stats


# ═══════════════════════════════════════════════════════════════════════════════
# Fix 4: Fill NULL virus_family entries via NCBI lookup
# ═══════════════════════════════════════════════════════════════════════════════

def fix_null_virus_family(conn: sqlite3.Connection, dry_run: bool) -> dict[str, Any]:
    """Fill NULL or empty virus_family in virus_master by checking
    ICTT VMR mappings first, then NCBI taxonomy API, then marking as Unclassified."""
    stats: dict[str, Any] = {
        "null_family_count": 0,
        "filled_from_ictv": 0,
        "filled_from_ncbi": 0,
        "filled_from_pattern": 0,
        "marked_unclassified": 0,
        "ncbi_api_calls": 0,
        "details": [],
    }

    print(f"\n{'='*60}")
    print("FIX 4: NULL virus_family entries")
    print(f"{'='*60}")

    # Find rows with NULL or empty virus_family
    null_rows = conn.execute(
        """SELECT master_id, canonical_name, genome_type, entry_type
           FROM virus_master
           WHERE (virus_family IS NULL OR virus_family = '')
           ORDER BY master_id"""
    ).fetchall()

    stats["null_family_count"] = len(null_rows)
    print(f"  Records with NULL/empty virus_family: {len(null_rows)}")

    if not null_rows:
        print("  No NULL virus_family entries to fix.")
        return stats

    # Check ICTV VMR mappings first
    try:
        vmr_mapped = conn.execute(
            """SELECT DISTINCT vvm.master_id, iv.family
               FROM virus_vmr_mappings vvm
               JOIN ictv_vmr iv ON vvm.vmr_id = iv.vmr_id
               WHERE vvm.match_status <> 'rejected'
                 AND iv.family IS NOT NULL AND iv.family != ''"""
        ).fetchall()
        vmr_family_map = {r["master_id"]: r["family"] for r in vmr_mapped}
    except Exception:
        vmr_family_map = {}

    # Check ICTV taxonomy mappings
    try:
        ictv_mapped = conn.execute(
            """SELECT DISTINCT vim.master_id, it.family
               FROM virus_ictv_mappings vim
               JOIN ictv_taxonomy it ON vim.ictv_id = it.ictv_id
               WHERE vim.match_status <> 'rejected'
                 AND it.family IS NOT NULL AND it.family != ''"""
        ).fetchall()
        ictv_family_map = {r["master_id"]: r["family"] for r in ictv_mapped}
    except Exception:
        ictv_family_map = {}

    print(f"  ICTV VMR family mappings available: {len(vmr_family_map)}")
    print(f"  ICTV taxonomy family mappings available: {len(ictv_family_map)}")

    # Pattern-based hints (same as enrich_virus_taxonomy.py)
    KNOWN_HINTS: dict[str, str] = {
        "white spot syndrome virus": "Nimaviridae",
        "yellow head virus": "Roniviridae",
        "taura syndrome virus": "Dicistroviridae",
        "infectious myonecrosis virus": "Artiviridae",
        "infectious hypodermal and hematopoietic necrosis virus": "Parvoviridae",
        "hepatopancreatic parvovirus": "Parvoviridae",
        "macrobrachium rosenbergii nodavirus": "Nodaviridae",
        "covert mortality nodavirus": "Nodaviridae",
        "penaeus vannamei nodavirus": "Nodaviridae",
        "decapod iridescent virus": "Iridoviridae",
        "shrimp hemocyte iridescent virus": "Iridoviridae",
        "crab associated circular virus": "Circoviridae",
        "mourilyan virus": "Unclassified",
        "laem-singh virus": "Unclassified",
        "infectious precocity virus": "Unclassified",
        "shrimp glass disease virus": "Unclassified",
        "european shore crab virus 1": "Unclassified",
        "mud crab virus": "Unclassified",
        "penaeus monodon endogenous virus": "Parvoviridae",
        "penaeus monodon rna virus": "Unclassified",
        "iridovirus cn01": "Iridoviridae",
        "macrobrachium rosenbergii golda virus": "Unclassified",
    }

    ncbi_src = get_ncbi_source_id(conn)
    ncbi_cache: dict[str, tuple[str | None, str | None, str | None]] = {}

    for row in null_rows:
        master_id = row["master_id"]
        canonical = row["canonical_name"]
        key = canonical.strip().lower()

        family = None
        genus = None
        source = None
        ncbi_taxid = None

        # Priority 1: Already in ICTV VMR mapping
        if master_id in vmr_family_map:
            family = vmr_family_map[master_id]
            source = "ictv_vmr"
        # Priority 2: Already in ICTV taxonomy mapping
        elif master_id in ictv_family_map:
            family = ictv_family_map[master_id]
            source = "ictv_taxonomy"
        # Priority 3: Pattern-based known hint
        elif key in KNOWN_HINTS:
            family = KNOWN_HINTS[key]
            source = "pattern_hint"
            if family == "Unclassified":
                source = "pattern_hint_unclassified"
        # Priority 4: NCBI Taxonomy API lookup (only if not dry_run and no family yet)
        elif not dry_run:
            if key in ncbi_cache:
                cached = ncbi_cache[key]
                if cached is not None:
                    family, genus, ncbi_taxid = cached
                    source = "ncbi_cache"
            else:
                time.sleep(REQUEST_DELAY)
                ncbi_results = ncbi_taxonomy_search(canonical)
                stats["ncbi_api_calls"] += 1
                if ncbi_results:
                    r = ncbi_results[0]
                    ncbi_taxid = r["taxid"]
                    found_family = r.get("family")
                    if found_family:
                        family = found_family
                        genus = r.get("genus")
                        source = "ncbi"
                        ncbi_cache[key] = (family, genus, ncbi_taxid)
                    else:
                        ncbi_cache[key] = None
                else:
                    ncbi_cache[key] = None

        # Priority 5: Default to Unclassified
        if not family:
            family = "Unclassified"
            source = "default_unclassified"

        if dry_run:
            print(f"  [dry-run] mid={master_id:4d} {canonical[:50]:50s} -> family={family:25s} [{source}]")
        else:
            conn.execute(
                "UPDATE virus_master SET virus_family = ?, virus_genus = ? WHERE master_id = ?",
                (family, genus, master_id),
            )
            log_change(conn, "virus_master", "set_virus_family",
                       family, f"Set family for {canonical} -> {family} [{source}]")

            # If we got an NCBI taxid and we have a source, create an xref
            if ncbi_taxid and ncbi_src and source in ("ncbi", "ncbi_cache"):
                try:
                    conn.execute(
                        """INSERT OR IGNORE INTO external_xrefs
                           (entity_type, entity_id, source_id, external_id, external_url,
                            match_status, confidence, matched_by, notes)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        ("virus_master", master_id, ncbi_src, ncbi_taxid,
                         f"https://www.ncbi.nlm.nih.gov/Taxonomy/Browser/wwwtax.cgi?id={ncbi_taxid}",
                         "exact", "high", "fix_taxonomy.py",
                         f"NCBI Taxonomy match for {canonical} -> TaxID {ncbi_taxid}"),
                    )
                except Exception:
                    pass

        # Count per source
        source_key = source or "unknown"
        if source_key.startswith("ictv"):
            stats["filled_from_ictv"] += 1
        elif source_key == "ncbi":
            stats["filled_from_ncbi"] += 1
        elif source_key == "ncbi_cache":
            stats["filled_from_ncbi"] += 1
        elif source_key in ("pattern_hint", "pattern_hint_unclassified"):
            stats["filled_from_pattern"] += 1
        elif source_key == "default_unclassified":
            stats["marked_unclassified"] += 1

        stats["details"].append({
            "master_id": master_id,
            "canonical_name": canonical,
            "family": family,
            "genus": genus,
            "source": source,
        })

    if not dry_run and stats["null_family_count"] > 0:
        conn.commit()

    print(f"\n  Source breakdown:")
    print(f"    Filled from ICTV mapping: {stats['filled_from_ictv']}")
    print(f"    Filled from NCBI API:     {stats['filled_from_ncbi']}")
    print(f"    Filled from pattern hint: {stats['filled_from_pattern']}")
    print(f"    Marked as Unclassified:   {stats['marked_unclassified']}")
    print(f"    NCBI API calls:           {stats['ncbi_api_calls']}")
    return stats


# ═══════════════════════════════════════════════════════════════════════════════
# Fix 5: Fill missing continent in sample_collections
# ═══════════════════════════════════════════════════════════════════════════════

def fix_missing_continent(conn: sqlite3.Connection, dry_run: bool) -> dict[str, Any]:
    """Fill NULL continent values in sample_collections using country -> continent mapping."""
    stats: dict[str, Any] = {
        "total_null_continent": 0,
        "filled": 0,
        "unmapped_countries": set(),
        "updated_rows": [],
    }

    print(f"\n{'='*60}")
    print("FIX 5: Missing continent values in sample_collections")
    print(f"{'='*60}")

    # Check if continent column exists
    try:
        cols = [r["name"] for r in conn.execute("PRAGMA table_info(sample_collections)")]
        if "continent" not in cols:
            print("  'continent' column does not exist in sample_collections.")
            return stats
    except Exception:
        print("  sample_collections table does not exist.")
        return stats

    # Get records with NULL continent but non-NULL country
    rows = conn.execute(
        """SELECT collection_id, country
           FROM sample_collections
           WHERE (continent IS NULL OR continent = '')
             AND country IS NOT NULL AND country != ''"""
    ).fetchall()

    stats["total_null_continent"] = len(rows)
    print(f"  Records with NULL continent but known country: {len(rows)}")

    if not rows:
        print("  No missing continent values to fix.")
        return stats

    for row in rows:
        cid = row["collection_id"]
        country = row["country"].strip().lower().rstrip(".")

        continent = COUNTRY_TO_CONTINENT.get(country)
        if not continent:
            # Try partial match for longer strings like "People's Republic of China"
            matched = False
            for ckey, cval in COUNTRY_TO_CONTINENT.items():
                if ckey in country or country in ckey:
                    continent = cval
                    matched = True
                    break
            if not matched:
                stats["unmapped_countries"].add(row["country"].strip())
                continue

        if dry_run:
            print(f"  [dry-run] cid={cid:4d} country={row['country'][:30]:30s} -> continent={continent}")
        else:
            conn.execute(
                "UPDATE sample_collections SET continent = ? WHERE collection_id = ?",
                (continent, cid),
            )
        stats["filled"] += 1
        stats["updated_rows"].append({"collection_id": cid, "country": row["country"], "continent": continent})

    if not dry_run and stats["filled"] > 0:
        conn.commit()
        log_change(conn, "sample_collections", "set_continent",
                   f"Filled {stats['filled']} records",
                   f"Filled missing continent values using country mapping.")

    print(f"\n  Filled: {stats['filled']}")
    if stats["unmapped_countries"]:
        print(f"  Unmapped countries ({len(stats['unmapped_countries'])}):")
        for c in sorted(stats["unmapped_countries"])[:20]:
            print(f"    - {c}")
    return stats


# ═══════════════════════════════════════════════════════════════════════════════
# Fix 6: ICTV mapping gap analysis
# ═══════════════════════════════════════════════════════════════════════════════

def ictv_coverage_analysis(conn: sqlite3.Connection, dry_run: bool) -> dict[str, Any]:
    """Analyze ICTV mapping coverage for virus_master entries."""
    stats: dict[str, Any] = {
        "total_viruses": 0,
        "bucket_viruses": 0,
        "has_ictv_mapping": 0,
        "has_vmr_mapping": 0,
        "has_either_mapping": 0,
        "no_mapping_at_all": 0,
        "mapped_with_family": 0,
        "mapped_without_family": 0,
        "unmapped_with_family": 0,
        "unmapped_without_family": 0,
        "gap_details": [],
    }

    print(f"\n{'='*60}")
    print("FIX 6: ICTV mapping coverage analysis")
    print(f"{'='*60}")

    bucket_names = {"Unknown/Unclassified", "Non-crustacean virus"}

    # Get all virus_master entries
    all_viruses = conn.execute(
        """SELECT master_id, canonical_name, virus_family
           FROM virus_master
           ORDER BY master_id"""
    ).fetchall()

    stats["total_viruses"] = len(all_viruses)
    stats["bucket_viruses"] = sum(1 for v in all_viruses if v["canonical_name"] in bucket_names)
    real_viruses = [v for v in all_viruses if v["canonical_name"] not in bucket_names]

    # Check which have ICTV mappings
    for v in real_viruses:
        master_id = v["master_id"]
        has_ictv = False
        has_vmr = False

        # Check virus_ictv_mappings
        try:
            row = conn.execute(
                """SELECT COUNT(*) as cnt FROM virus_ictv_mappings
                   WHERE master_id = ? AND match_status <> 'rejected'""",
                (master_id,),
            ).fetchone()
            has_ictv = row["cnt"] > 0
        except Exception:
            pass

        # Check virus_vmr_mappings
        try:
            row = conn.execute(
                """SELECT COUNT(*) as cnt FROM virus_vmr_mappings
                   WHERE master_id = ? AND match_status <> 'rejected'""",
                (master_id,),
            ).fetchone()
            has_vmr = row["cnt"] > 0
        except Exception:
            pass

        has_family = bool(v["virus_family"] and v["virus_family"].strip())

        if has_ictv or has_vmr:
            stats["has_either_mapping"] += 1
            if has_ictv:
                stats["has_ictv_mapping"] += 1
            if has_vmr:
                stats["has_vmr_mapping"] += 1
            if has_family:
                stats["mapped_with_family"] += 1
            else:
                stats["mapped_without_family"] += 1
        else:
            stats["no_mapping_at_all"] += 1
            if has_family:
                stats["unmapped_with_family"] += 1
            else:
                stats["unmapped_without_family"] += 1
            stats["gap_details"].append({
                "master_id": master_id,
                "canonical_name": v["canonical_name"],
                "virus_family": v["virus_family"],
            })

    print(f"\n  Total virus_master entries:          {stats['total_viruses']}")
    print(f"  Bucket entries (Unknown/etc):        {stats['bucket_viruses']}")
    print(f"  Real (non-bucket) viruses:           {len(real_viruses)}")
    print(f"")
    print(f"  Have ICTT taxonomy mapping:          {stats['has_ictv_mapping']}")
    print(f"  Have ICTT VMR mapping:               {stats['has_vmr_mapping']}")
    print(f"  Have either ICTV mapping:            {stats['has_either_mapping']}")
    print(f"  No ICTV mapping at all:              {stats['no_mapping_at_all']}")
    print(f"")
    print(f"  Mapped + have virus_family:          {stats['mapped_with_family']}")
    print(f"  Mapped + NO virus_family:            {stats['mapped_without_family']}")
    print(f"  Unmapped + have virus_family:        {stats['unmapped_with_family']}")
    print(f"  Unmapped + NO virus_family:          {stats['unmapped_without_family']}")
    print(f"")

    if stats["gap_details"]:
        print(f"  Viruses missing ICTV mapping:")
        for g in stats["gap_details"][:30]:
            print(f"    mid={g['master_id']:4d} fam={str(g['virus_family'] or ''):25s} {g['canonical_name']}")
        if len(stats["gap_details"]) > 30:
            print(f"    ... and {len(stats['gap_details']) - 30} more")

    return stats


# ═══════════════════════════════════════════════════════════════════════════════
# Main entry point
# ═══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="Fix taxonomy and data quality issues")
    parser.add_argument("--dry-run", action="store_true", help="Preview only, no changes")
    parser.add_argument("--no-backup", action="store_true", help="Skip database backup")
    parser.add_argument("--fix", choices=["all", "abbreviations", "genome_type", "unclassified",
                                          "null_family", "continent", "ictv_analysis"],
                        default="all", help="Which fix to run")
    args = parser.parse_args()

    if args.dry_run:
        print("[dry-run] PREVIEW MODE -- no database changes will be made")
    print(f"[start] fix_taxonomy.py (fix={args.fix})")

    if not args.dry_run and not args.no_backup:
        if args.fix == "all":
            backup_database()

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")

    all_stats: dict[str, Any] = {}
    try:
        if args.fix in ("all", "abbreviations"):
            s = fix_missing_abbreviations(conn, args.dry_run)
            all_stats["abbreviations"] = s

        if args.fix in ("all", "genome_type"):
            s = fix_genome_type_vocabulary(conn, args.dry_run)
            all_stats["genome_type"] = s

        if args.fix in ("all", "unclassified"):
            s = fix_unclassified_family_variants(conn, args.dry_run)
            all_stats["unclassified_family"] = s

        if args.fix in ("all", "null_family"):
            s = fix_null_virus_family(conn, args.dry_run)
            all_stats["null_family"] = s

        if args.fix in ("all", "continent"):
            s = fix_missing_continent(conn, args.dry_run)
            all_stats["continent"] = s

        if args.fix in ("all", "ictv_analysis"):
            s = ictv_coverage_analysis(conn, args.dry_run)
            all_stats["ictv_analysis"] = s

        if not args.dry_run and args.fix != "ictv_analysis":
            # Final commit for the whole transaction
            conn.commit()
            print(f"\n[commit] All changes committed")
        elif args.dry_run:
            conn.rollback()
            print(f"\n[dry-run] No changes made (rolled back)")

    except Exception as e:
        conn.rollback()
        print(f"\n[ERROR] {e}")
        import traceback
        traceback.print_exc()
        raise
    finally:
        conn.close()

    print(f"\n{'='*60}")
    print("SUMMARY")
    print(f"{'='*60}")

    for fix_name, s in all_stats.items():
        print(f"\n  [{fix_name}]")
        for k, v in s.items():
            if k == "details" or k == "updated_rows" or k == "gap_details":
                continue
            if isinstance(v, (int, float)):
                print(f"    {k}: {v}")
            elif isinstance(v, dict) and v:
                print(f"    {k}: {dict(list(v.items())[:10])}")
                if len(v) > 10:
                    print(f"      ... and {len(v)-10} more")
            elif isinstance(v, set):
                print(f"    {k}: {len(v)} items")
            else:
                print(f"    {k}: {v}")

    print(f"\n[done] fix_taxonomy.py completed")


if __name__ == "__main__":
    main()
