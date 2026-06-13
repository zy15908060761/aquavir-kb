"""
Import Virus-Host DB data into host_range_evidence.

Virus-Host DB (https://www.genome.jp/virushostdb/) provides structured
virus-host association pairs based on NCBI Taxonomy IDs.

Strategy:
  1. Download the Virus-Host DB flat file (TSV) to local cache
  2. Parse all entries, filter for virus TaxIDs that match crustacean viruses
     (via external_xrefs ncbi_taxonomy xrefs on virus_master)
  3. Also match host TaxIDs against host_taxonomy_profiles
  4. Insert matched pairs into host_range_evidence

Usage:
    python import_virushostdb.py                        # full run
    python import_virushostdb.py --rebuild-cache        # re-download
    python import_virushostdb.py --dry-run              # preview only

Source:
    https://www.genome.jp/virushostdb/wh.tsv
"""

from __future__ import annotations

import csv
import io
import json
import re
import shutil
import sqlite3
import time
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "crustacean_virus_core.db"
BACKUP_DIR = BASE_DIR / "backups"
DOWNLOADS_DIR = BASE_DIR / "downloads"
CACHE_DIR = BASE_DIR / "external_data" / "virushostdb"

VHDB_URL = "https://ftp.genome.jp/pub/db/virushostdb/virushostdb.daily.tsv"
VHDB_URL_FALLBACK = "https://www.genome.jp/ftp/db/virushostdb/virushostdb.daily.tsv"
VHDB_FILENAME = "virushostdb.daily.tsv"
CACHE_DAYS_VALID = 7


@dataclass
class VHDBEntry:
    virus_taxid: str
    virus_name: str
    virus_lineage: str
    host_taxid: str
    host_name: str
    host_lineage: str
    reference_pmids: list[str]


# ── caching ──────────────────────────────────────────────────────────


def cache_path() -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR / VHDB_FILENAME


def cache_valid(cache_file: Path) -> bool:
    if not cache_file.exists():
        return False
    age = datetime.now() - datetime.fromtimestamp(cache_file.stat().st_mtime)
    return age.days < CACHE_DAYS_VALID


def download_vhdb(rebuild: bool = False) -> Path:
    cache_file = cache_path()
    if cache_valid(cache_file) and not rebuild:
        print(f"[cache] using cached {cache_file} (age valid)")
        return cache_file

    urls = [
        VHDB_URL,
        VHDB_URL_FALLBACK,
    ]
    last_error: Exception | None = None
    for url in urls:
        print(f"[download] fetching {url} ...")
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "crustacean-virus-db-curation/1.0"},
            )
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = resp.read()
            cache_file.write_bytes(data)
            print(f"[download] saved {len(data)} bytes to {cache_file}")
            return cache_file
        except Exception as exc:
            last_error = exc
            print(f"  [warn] {exc}")
            continue
    # All URLs failed
    if cache_file.exists():
        print(f"[warn] all downloads failed, using cached version (may be stale)")
        return cache_file
    raise RuntimeError(f"Failed to download Virus-Host DB from any mirror: {last_error}")


def parse_vhdb(file_path: Path) -> list[VHDBEntry]:
    """Parse the Virus-Host DB TSV file."""
    entries: list[VHDBEntry] = []
    raw = file_path.read_text(encoding="utf-8", errors="replace")
    reader = csv.reader(io.StringIO(raw), delimiter="\t", quotechar='"')

    for row_num, row in enumerate(reader):
        if row_num == 0:
            continue  # skip header
        if len(row) < 9:
            continue

        virus_taxid = row[0].strip()
        virus_name = row[1].strip()
        virus_lineage = row[2].strip() if len(row) > 2 else ""
        # col 3 = refseq id, 4 = KEGG GENOME, 5 = KEGG DISEASE, 6 = DISEASE
        host_taxid = row[7].strip() if len(row) > 7 else ""
        host_name = row[8].strip() if len(row) > 8 else ""
        host_lineage = row[9].strip() if len(row) > 9 else ""
        ref_pmid_str = row[10].strip() if len(row) > 10 else ""

        pmids: list[str] = []
        if ref_pmid_str:
            pmids = [
                p.strip() for p in ref_pmid_str.replace("PMID:", "").split(",")
                if p.strip().isdigit()
            ]

        if virus_taxid and host_taxid and host_taxid.isdigit():
            entries.append(VHDBEntry(
                virus_taxid=virus_taxid,
                virus_name=virus_name,
                virus_lineage=virus_lineage,
                host_taxid=host_taxid,
                host_name=host_name,
                host_lineage=host_lineage,
                reference_pmids=pmids,
            ))

    return entries


# ── database helpers ─────────────────────────────────────────────────


def backup_database() -> Path:
    BACKUP_DIR.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = BACKUP_DIR / f"crustacean_virus_core_before_vhdb_{stamp}.db"
    shutil.copy2(DB_PATH, backup_path)
    return backup_path


def source_id(conn: sqlite3.Connection, key: str) -> int | None:
    row = conn.execute(
        "SELECT source_id FROM external_sources WHERE source_key = ?", (key,)
    ).fetchone()
    return row["source_id"] if row else None


def build_virus_name_map(conn: sqlite3.Connection) -> dict[str, int]:
    """Map lowercased virus name -> master_id.

    Builds from virus_master.canonical_name, virus_aliases, and viral_isolates names.
    """
    mapping: dict[str, int] = {}

    # Primary: canonical names
    rows = conn.execute(
        "SELECT master_id, canonical_name FROM virus_master"
    ).fetchall()
    for row in rows:
        key = row["canonical_name"].strip().lower()
        if key:
            mapping[key] = row["master_id"]

    # Aliases
    rows2 = conn.execute(
        "SELECT alias, master_id FROM virus_aliases WHERE master_id IS NOT NULL"
    ).fetchall()
    for row in rows2:
        key = row["alias"].strip().lower()
        if key:
            mapping.setdefault(key, row["master_id"])

    # Isolate-level virus names
    rows3 = conn.execute(
        """
        SELECT DISTINCT v.virus_name, COALESCE(v.master_id,
            (SELECT master_id FROM virus_master WHERE canonical_name = 'Unknown/Unclassified'))
        FROM viral_isolates v
        WHERE v.virus_name IS NOT NULL AND TRIM(v.virus_name) <> ''
        """
    ).fetchall()
    for row in rows3:
        key = row["virus_name"].strip().lower()
        if key:
            mapping.setdefault(key, row[1])

    return mapping


def build_host_taxid_map(conn: sqlite3.Connection) -> dict[str, int]:
    """Map NCBI TaxID string -> crustacean_hosts.host_id."""
    mapping: dict[str, int] = {}
    rows = conn.execute(
        """
        SELECT htp.ncbi_taxid, h.host_id
        FROM host_taxonomy_profiles htp
        JOIN crustacean_hosts h ON htp.host_id = h.host_id
        WHERE htp.ncbi_taxid IS NOT NULL
          AND TRIM(htp.ncbi_taxid) <> ''
          AND htp.ncbi_taxid NOT LIKE 'WoRMS:%'
        """
    ).fetchall()
    for row in rows:
        tid = str(row["ncbi_taxid"]).strip()
        mapping[tid] = row["host_id"]
    return mapping


def build_host_name_map(conn: sqlite3.Connection) -> dict[str, int]:
    """Map lowercase scientific name -> host_id as fallback."""
    mapping: dict[str, int] = {}
    rows = conn.execute(
        "SELECT host_id, scientific_name FROM crustacean_hosts"
    ).fetchall()
    for row in rows:
        key = row["scientific_name"].strip().lower()
        mapping[key] = row["host_id"]
    return mapping


def ensure_reference_from_pmid(conn: sqlite3.Connection, pmid: str) -> int | None:
    """Ensure a ref_literatures entry exists for a PMID. Returns reference_id or None."""
    if not pmid or not pmid.strip().isdigit():
        return None
    pmid = pmid.strip()
    existing = conn.execute(
        "SELECT reference_id FROM ref_literatures WHERE pmid = ?", (pmid,)
    ).fetchone()
    if existing:
        return existing["reference_id"]
    return None


def insert_host_range_evidence(
    conn: sqlite3.Connection,
    virus_master_id: int,
    host_id: int,
    entry: VHDBEntry,
) -> bool:
    """Insert a single host_range_evidence row. Returns True if inserted."""
    try:
        conn.execute(
            """
            INSERT OR IGNORE INTO host_range_evidence
                (virus_master_id, host_id, evidence_category, isolate_count,
                 reference_id, evidence_strength, curation_status, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                virus_master_id,
                host_id,
                "database_annotation",
                0,
                None,  # reference_id — could be enriched from PMIDs
                "medium",
                "auto_seeded",
                f"Virus-Host DB pair: {entry.virus_name} -> {entry.host_name}",
            ),
        )
        return conn.total_changes > 0
    except sqlite3.IntegrityError:
        return False


# ── main ─────────────────────────────────────────────────────────────


CRUSTACEAN_HOST_KEYWORDS = [
    # Genus-level names (most specific -> avoid insect false positives)
    "penaeus", "macrobrachium", "litopenaeus", "farfantepenaeus",
    "callinectes", "carcinus", "homarus", "procambarus", "cherax",
    "pacifastacus", "eriocheir", "scylla", "portunus", "charybdis",
    "metapenaeus", "nephrops", "palaemon", "exopalaemon", "neocaridina",
    "halocaridina", "paratya", "caridina", "pandalus", "artemia",
    "daphnia", "fenneropenaeus", "marsupenaeus",
    # Common names
    "shrimp", "crab", "lobster", "crayfish", "prawn", "krill",
    # Broader groups
    "penaeid", "caridean", "decapod", "crustacean",
]


def is_crustacean_host(entry: VHDBEntry) -> bool:
    """Check if VHDB entry host is a crustacean based on host name (not lineage, to avoid insect false-positives through Pancrustacea)."""
    search_text = entry.host_name.lower()
    for kw in CRUSTACEAN_HOST_KEYWORDS:
        if kw in search_text:
            return True
    return False


KNOWN_VIRUS_NAME_MAPPINGS: dict[str, str] = {
    # VHDB name -> canonical name in our virus_master
    # Callinectes-associated circular viruses
    "callinectes sapidus associated circular virus": "crab associated circular virus",
    "callinectes ornatus blue crab associated circular virus": "crab associated circular virus",
    "farfantepenaeus duorarum pink shrimp associated circular virus": "crab associated circular virus",
    "palaemonetes intermedius brackish grass shrimp associated circular virus": "crab associated circular virus",
    "palaemonetes kadiakensis mississippi grass shrimp associated circular virus": "crab associated circular virus",
    "palaemonetes sp. common grass shrimp associated circular virus": "crab associated circular virus",
    # Full-name mappings
    "extra small virus": "macrobrachium rosenbergii nodavirus",  # XSV is a satellite of MrNV
    "gill-associated virus": "yellow head virus",
    "shrimp white spot syndrome virus": "white spot syndrome virus",
    "callinectes sapidus reovirus 1": "crab associated circular virus",
}


def normalize_name_for_match(name: str) -> str:
    """Normalize a virus name for fuzzy matching."""
    text = name.lower().strip()
    # Remove trailing GenBank accessions like "NC_123456" or "123456"
    text = re.sub(r"\s+(nc_|np_|yp_)?\d{4,}$", "", text)
    # Remove parenthesized content
    text = re.sub(r"\s*\([^)]*\)\s*", " ", text)
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def virus_name_match(vhdb_virus_name: str, known_viruses: dict[str, int]) -> int | None:
    """Try to match a VHDB virus name against known virus names. Returns master_id or None."""
    if not vhdb_virus_name:
        return None

    key = vhdb_virus_name.strip().lower()

    # 1. Check explicit mapping first
    if key in KNOWN_VIRUS_NAME_MAPPINGS:
        mapped = KNOWN_VIRUS_NAME_MAPPINGS[key]
        if mapped in known_viruses:
            return known_viruses[mapped]

    # 2. Direct match
    if key in known_viruses:
        return known_viruses[key]

    # 3. Normalized match
    norm = normalize_name_for_match(vhdb_virus_name)
    if norm in known_viruses:
        return known_viruses[norm]

    # 4. Also check mapped name normalized
    if key in KNOWN_VIRUS_NAME_MAPPINGS:
        mapped = KNOWN_VIRUS_NAME_MAPPINGS[key]
        if mapped in known_viruses:
            return known_viruses[mapped]

    # 5. Token overlap: check if most tokens match a known virus
    norm_tokens = set(norm.split())
    if len(norm_tokens) < 2:
        return None

    best_mid: int | None = None
    best_overlap = 0
    for known_key, mid in known_viruses.items():
        known_tokens = set(known_key.split())
        overlap = len(norm_tokens & known_tokens)
        # Require at least 2 overlapping tokens AND the overlap is substantial for both sides
        min_required = max(2, len(norm_tokens) - 1)
        known_min = max(2, len(known_tokens) - 1)
        if overlap >= min_required and overlap >= known_min:
            if overlap > best_overlap:
                best_overlap = overlap
                best_mid = mid

    return best_mid


def run_import(conn: sqlite3.Connection, entries: list[VHDBEntry], dry_run: bool) -> dict:
    stats = {
        "total_entries": len(entries),
        "crustacean_host_entries": 0,
        "virus_matched": 0,
        "virus_unmatched": 0,
        "host_matched": 0,
        "host_unmatched": 0,
        "pairs_inserted": 0,
        "pairs_skipped_existing": 0,
        "pairs_skipped_no_match": 0,
    }

    virus_map = build_virus_name_map(conn)
    host_taxid_map = build_host_taxid_map(conn)
    host_name_map = build_host_name_map(conn)

    print(f"[map] virus names in DB: {len(virus_map)}")
    print(f"[map] hosts with TaxID mapping: {len(host_taxid_map)}")
    print(f"[map] hosts by name fallback: {len(host_name_map)}")

    # Filter to crustacean host entries only
    crustacean_entries = [e for e in entries if is_crustacean_host(e)]
    stats["crustacean_host_entries"] = len(crustacean_entries)
    print(f"[filter] crustacean-host entries: {len(crustacean_entries)} out of {len(entries)} total")

    for entry in crustacean_entries:
        # Match virus by name
        virus_id = virus_name_match(entry.virus_name, virus_map)
        if not virus_id:
            stats["virus_unmatched"] += 1
            continue
        stats["virus_matched"] += 1

        # Match host by TaxID then name
        host_id = host_taxid_map.get(entry.host_taxid)
        if not host_id:
            host_lower = entry.host_name.strip().lower()
            host_id = host_name_map.get(host_lower)
        if not host_id:
            stats["host_unmatched"] += 1
            stats["pairs_skipped_no_match"] += 1
            continue
        stats["host_matched"] += 1

        if dry_run:
            continue

        inserted = insert_host_range_evidence(conn, virus_id, host_id, entry)
        if inserted:
            stats["pairs_inserted"] += 1
        else:
            stats["pairs_skipped_existing"] += 1

    return stats


def export_results(stats: dict) -> Path:
    DOWNLOADS_DIR.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = DOWNLOADS_DIR / f"virushostdb_import_{stamp}.json"
    data = {
        "stats": stats,
        "completed_at": datetime.now().isoformat(timespec="seconds"),
    }
    out_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_path


def log_run(conn: sqlite3.Connection, stats: dict) -> None:
    src_id = source_id(conn, "ncbi_taxonomy")
    payload = "; ".join(f"{k}={v}" for k, v in sorted(stats.items()))
    conn.execute(
        """
        INSERT INTO curation_logs
            (entity_type, action, source_id, new_value, confidence, curator, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "host_range_evidence",
            "import_virushostdb",
            src_id,
            payload,
            "high",
            "import_virushostdb.py",
            "Imported virus-host associations from Virus-Host DB.",
        ),
    )


def validate(conn: sqlite3.Connection) -> None:
    quick_check = conn.execute("PRAGMA quick_check").fetchone()[0]
    if quick_check != "ok":
        raise RuntimeError(f"SQLite quick_check failed: {quick_check}")
    fk_errors = conn.execute("PRAGMA foreign_key_check").fetchall()
    if fk_errors:
        raise RuntimeError(f"Foreign key check failed: {fk_errors[:5]}")


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Import Virus-Host DB")
    parser.add_argument("--rebuild-cache", action="store_true", help="Re-download Virus-Host DB")
    parser.add_argument("--dry-run", action="store_true", help="Preview only")
    args = parser.parse_args()

    if args.dry_run:
        print("[dry-run] Preview mode — no database writes")

    # Download and parse
    cache_file = download_vhdb(rebuild=args.rebuild_cache)
    entries = parse_vhdb(cache_file)
    print(f"[parse] {len(entries)} Virus-Host DB entries loaded")

    backup_path = backup_database() if not args.dry_run else None
    if backup_path:
        print(f"[backup] {backup_path}")

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        stats = run_import(conn, entries, args.dry_run)
        if not args.dry_run:
            export_path = export_results(stats)
            log_run(conn, stats)
            validate(conn)
            conn.commit()
            print(f"[done] export={export_path}")
        else:
            print("[dry-run] skipped writes")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    for key, value in sorted(stats.items()):
        print(f"[done] {key}={value}")


if __name__ == "__main__":
    main()
