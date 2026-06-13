"""
Seed host standardization records from the local NCBI taxonomy cache.

This script is non-destructive:
- it does not rename rows in crustacean_hosts
- it adds NCBI Taxonomy xrefs and accepted-name aliases where available
- it creates review queues for ambiguous, non-target, and likely duplicate hosts
"""

from __future__ import annotations

import json
import re
import shutil
import sqlite3
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "crustacean_virus_core.db"
BACKUP_DIR = BASE_DIR / "backups"
TAXON_CACHE = BASE_DIR / "ncbi_metadata" / "taxon_cache.json"


NON_TARGET_KEYWORDS = [
    "e.coli",
    "e. coli",
    "dh10b",
    "dh5",
    "k12",
    "bioflake",
    "plankton",
    "small fish",
    "tadpole",
    "bivalva",
    "bellamya",
    "acanthaster",
    "insects",
]


def backup_database() -> Path:
    BACKUP_DIR.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = BACKUP_DIR / f"crustacean_virus_core_before_host_standardization_{stamp}.db"
    shutil.copy2(DB_PATH, backup_path)
    return backup_path


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        PRAGMA foreign_keys = ON;

        CREATE TABLE IF NOT EXISTS host_taxonomy_profiles (
            profile_id INTEGER PRIMARY KEY AUTOINCREMENT,
            host_id INTEGER NOT NULL UNIQUE,
            ncbi_taxid TEXT,
            accepted_name TEXT,
            lineage TEXT,
            lineage_superkingdom TEXT,
            lineage_kingdom TEXT,
            lineage_phylum TEXT,
            lineage_class TEXT,
            lineage_order TEXT,
            lineage_family TEXT,
            lineage_genus TEXT,
            is_crustacean INTEGER CHECK (is_crustacean IN (0, 1)),
            is_target_host INTEGER CHECK (is_target_host IN (0, 1)),
            match_status TEXT NOT NULL DEFAULT 'from_cache' CHECK (
                match_status IN ('from_cache', 'manual_checked', 'needs_review', 'not_found')
            ),
            confidence TEXT NOT NULL DEFAULT 'medium' CHECK (
                confidence IN ('high', 'medium', 'low', 'unknown')
            ),
            source_id INTEGER,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            notes TEXT,
            FOREIGN KEY (host_id) REFERENCES crustacean_hosts(host_id),
            FOREIGN KEY (source_id) REFERENCES external_sources(source_id)
        );

        CREATE TABLE IF NOT EXISTS host_review_candidates (
            candidate_id INTEGER PRIMARY KEY AUTOINCREMENT,
            host_id INTEGER NOT NULL,
            issue_type TEXT NOT NULL CHECK (
                issue_type IN (
                    'missing_taxonomy',
                    'non_target_host',
                    'likely_duplicate',
                    'accepted_name_differs',
                    'ambiguous_group',
                    'not_found_in_cache'
                )
            ),
            suggested_host_id INTEGER,
            suggested_name TEXT,
            evidence TEXT,
            confidence TEXT NOT NULL DEFAULT 'medium' CHECK (
                confidence IN ('high', 'medium', 'low', 'unknown')
            ),
            status TEXT NOT NULL DEFAULT 'open' CHECK (
                status IN ('open', 'accepted', 'rejected', 'manual_checked')
            ),
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            notes TEXT,
            FOREIGN KEY (host_id) REFERENCES crustacean_hosts(host_id),
            FOREIGN KEY (suggested_host_id) REFERENCES crustacean_hosts(host_id)
        );

        CREATE INDEX IF NOT EXISTS idx_host_taxonomy_profiles_taxid
            ON host_taxonomy_profiles(ncbi_taxid);
        CREATE INDEX IF NOT EXISTS idx_host_taxonomy_profiles_host
            ON host_taxonomy_profiles(host_id);
        CREATE INDEX IF NOT EXISTS idx_host_review_candidates_host
            ON host_review_candidates(host_id);
        CREATE INDEX IF NOT EXISTS idx_host_review_candidates_issue
            ON host_review_candidates(issue_type);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_host_review_candidates_unique
            ON host_review_candidates(
                host_id,
                issue_type,
                COALESCE(suggested_host_id, -1),
                COALESCE(suggested_name, '')
            );
        """
    )


def source_id(conn: sqlite3.Connection, key: str) -> int:
    row = conn.execute("SELECT source_id FROM external_sources WHERE source_key = ?", (key,)).fetchone()
    if not row:
        raise RuntimeError(f"Missing external source: {key}")
    return row["source_id"]


def load_cache() -> dict[str, list[str] | None]:
    if not TAXON_CACHE.exists():
        raise FileNotFoundError(TAXON_CACHE)
    return json.loads(TAXON_CACHE.read_text(encoding="utf-8"))


def lineage_part(lineage: str, suffix: str) -> str | None:
    parts = [part.strip() for part in lineage.split(";") if part.strip()]
    for part in parts:
        if part == suffix or part.endswith(suffix):
            return part
    return None


def parse_profile(host_id: int, cache_row: list[str] | None, source_id_value: int) -> tuple | None:
    if not cache_row:
        return None
    taxid, lineage, accepted_name = cache_row
    is_crustacean = 1 if "Pancrustacea" in lineage or "Crustacea" in lineage or "Malacostraca" in lineage else 0
    is_target = 1 if is_crustacean else 0
    parts = [part.strip() for part in lineage.split(";") if part.strip()]
    return (
        host_id,
        taxid,
        accepted_name,
        lineage,
        "Eukaryota" if "Eukaryota" in parts else None,
        "Metazoa" if "Metazoa" in parts else None,
        "Arthropoda" if "Arthropoda" in parts else None,
        "Malacostraca" if "Malacostraca" in parts else None,
        lineage_part(lineage, "Decapoda") or lineage_part(lineage, "Anostraca") or lineage_part(lineage, "Stomatopoda"),
        infer_family(lineage),
        accepted_name.split()[0] if accepted_name and " " in accepted_name else None,
        is_crustacean,
        is_target,
        "from_cache",
        "high",
        source_id_value,
        None,
    )


def infer_family(lineage: str) -> str | None:
    parts = [part.strip() for part in lineage.split(";") if part.strip()]
    for part in reversed(parts):
        if part.endswith("idae"):
            return part
    return None


def normalize_name(value: str) -> str:
    text = value.lower().strip()
    text = text.replace("?", "a")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def is_non_target_name(name: str, group: str | None) -> bool:
    lowered = normalize_name(name)
    if group == "non-crustacean":
        return True
    return any(keyword in lowered for keyword in NON_TARGET_KEYWORDS)


def add_review(
    conn: sqlite3.Connection,
    host_id: int,
    issue_type: str,
    suggested_host_id: int | None,
    suggested_name: str | None,
    evidence: str,
    confidence: str = "medium",
) -> None:
    conn.execute(
        """
        INSERT OR IGNORE INTO host_review_candidates
            (host_id, issue_type, suggested_host_id, suggested_name, evidence, confidence)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (host_id, issue_type, suggested_host_id, suggested_name, evidence, confidence),
    )


def seed_profiles(conn: sqlite3.Connection, cache: dict[str, list[str] | None], ncbi_source_id: int) -> int:
    before = conn.total_changes
    hosts = conn.execute("SELECT * FROM crustacean_hosts").fetchall()
    for host in hosts:
        name = host["scientific_name"]
        cache_row = cache.get(name)
        profile = parse_profile(host["host_id"], cache_row, ncbi_source_id)
        if profile:
            conn.execute(
                """
                INSERT INTO host_taxonomy_profiles
                    (
                        host_id, ncbi_taxid, accepted_name, lineage,
                        lineage_superkingdom, lineage_kingdom, lineage_phylum,
                        lineage_class, lineage_order, lineage_family, lineage_genus,
                        is_crustacean, is_target_host, match_status, confidence,
                        source_id, notes
                    )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(host_id) DO UPDATE SET
                    ncbi_taxid = excluded.ncbi_taxid,
                    accepted_name = excluded.accepted_name,
                    lineage = excluded.lineage,
                    lineage_superkingdom = excluded.lineage_superkingdom,
                    lineage_kingdom = excluded.lineage_kingdom,
                    lineage_phylum = excluded.lineage_phylum,
                    lineage_class = excluded.lineage_class,
                    lineage_order = excluded.lineage_order,
                    lineage_family = excluded.lineage_family,
                    lineage_genus = excluded.lineage_genus,
                    is_crustacean = excluded.is_crustacean,
                    is_target_host = excluded.is_target_host,
                    match_status = excluded.match_status,
                    confidence = excluded.confidence,
                    source_id = excluded.source_id,
                    updated_at = CURRENT_TIMESTAMP
                """,
                profile,
            )
            conn.execute(
                """
                INSERT OR IGNORE INTO external_xrefs
                    (entity_type, entity_id, source_id, external_id, external_url, match_status, confidence, matched_by, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "host",
                    host["host_id"],
                    ncbi_source_id,
                    profile[1],
                    f"https://www.ncbi.nlm.nih.gov/Taxonomy/Browser/wwwtax.cgi?id={profile[1]}",
                    "exact",
                    "high",
                    "standardize_hosts_from_cache.py",
                    "Seeded from local NCBI taxonomy cache.",
                ),
            )
            if profile[2] and profile[2] != name:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO host_aliases
                        (host_id, alias, alias_type, source_id, external_id, match_status, confidence, notes)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        host["host_id"],
                        profile[2],
                        "synonym",
                        ncbi_source_id,
                        profile[1],
                        "exact",
                        "high",
                        "Accepted name from local NCBI taxonomy cache.",
                    ),
                )
                add_review(
                    conn,
                    host["host_id"],
                    "accepted_name_differs",
                    None,
                    profile[2],
                    f"Local name differs from NCBI accepted name: {name} -> {profile[2]}",
                    "high",
                )
        else:
            add_review(
                conn,
                host["host_id"],
                "not_found_in_cache",
                None,
                None,
                "No local NCBI taxonomy cache match.",
                "medium",
            )
    return conn.total_changes - before


def seed_review_candidates(conn: sqlite3.Connection) -> int:
    before = conn.total_changes
    hosts = conn.execute("SELECT * FROM crustacean_hosts").fetchall()

    for host in hosts:
        if is_non_target_name(host["scientific_name"], host["host_group"]):
            add_review(
                conn,
                host["host_id"],
                "non_target_host",
                None,
                None,
                f"host_group={host['host_group']}; name={host['scientific_name']}",
                "high",
            )
        if not host["taxon_order"] or not host["taxon_family"]:
            add_review(
                conn,
                host["host_id"],
                "missing_taxonomy",
                None,
                None,
                f"taxon_order={host['taxon_order']}; taxon_family={host['taxon_family']}",
                "medium",
            )
        lowered = normalize_name(host["scientific_name"])
        if lowered.endswith(" sp") or lowered.endswith(" spp") or host["scientific_name"] in {"Crustacea", "Brachyura", "Astacidea"}:
            add_review(
                conn,
                host["host_id"],
                "ambiguous_group",
                None,
                None,
                f"Broad or genus-level host label: {host['scientific_name']}",
                "medium",
            )

    host_rows = [(h["host_id"], h["scientific_name"], normalize_name(h["scientific_name"])) for h in hosts]
    for i, (host_id, name, norm) in enumerate(host_rows):
        for other_id, other_name, other_norm in host_rows[i + 1 :]:
            if host_id == other_id:
                continue
            ratio = SequenceMatcher(None, norm, other_norm).ratio()
            if ratio >= 0.88 and norm != other_norm:
                add_review(
                    conn,
                    host_id,
                    "likely_duplicate",
                    other_id,
                    other_name,
                    f"Name similarity {ratio:.2f}: {name} ~ {other_name}",
                    "medium",
                )
    return conn.total_changes - before


def log_run(conn: sqlite3.Connection, source_id_value: int, profile_changes: int, review_changes: int) -> None:
    conn.execute(
        """
        INSERT INTO curation_logs
            (entity_type, action, source_id, new_value, confidence, curator, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "host_taxonomy",
            "standardize_hosts_from_cache",
            source_id_value,
            f"profile_changes={profile_changes}; review_changes={review_changes}",
            "high",
            "standardize_hosts_from_cache.py",
            "Seeded host taxonomy profiles, NCBI xrefs, accepted-name aliases, and review candidates from local cache.",
        ),
    )


def main() -> None:
    backup_path = backup_database()
    print(f"[backup] {backup_path}")
    cache = load_cache()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        ensure_schema(conn)
        ncbi_source_id = source_id(conn, "ncbi_taxonomy")
        profile_changes = seed_profiles(conn, cache, ncbi_source_id)
        review_changes = seed_review_candidates(conn)
        log_run(conn, ncbi_source_id, profile_changes, review_changes)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    print(f"[done] profile_changes={profile_changes}")
    print(f"[done] review_changes={review_changes}")


if __name__ == "__main__":
    main()
