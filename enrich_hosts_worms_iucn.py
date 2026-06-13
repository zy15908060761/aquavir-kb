"""
Enrich host taxonomy profiles via WoRMS API and IUCN Red List API.

WoRMS:
  - Query marine species taxonomy, accepted names, AphiaID
  - Fill host_taxonomy_profiles with WoRMS classification
  - Record external_xrefs for WoRMS AphiaID

IUCN:
  - Query conservation status for each host
  - Fill crustacean_hosts.iucn_status and iucn_assessment_year

Usage:
    python enrich_hosts_worms_iucn.py                     # full run
    python enrich_hosts_worms_iucn.py --iucn-token XXX    # with IUCN API token
    python enrich_hosts_worms_iucn.py --limit 10          # first 10 only
    python enrich_hosts_worms_iucn.py --dry-run           # preview only

WoRMS API: https://www.marinespecies.org/rest/ (no token needed, ~1 req/s limit)
IUCN API:  https://api.iucnredlist.org/api/v4 (free token from https://apiv3.iucnredlist.org/)
"""

from __future__ import annotations

import json
import re
import shutil
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "crustacean_virus_core.db"
BACKUP_DIR = BASE_DIR / "backups"
DOWNLOADS_DIR = BASE_DIR / "downloads"

WORMS_BASE = "https://www.marinespecies.org/rest"
IUCN_BASE = "https://api.iucnredlist.org/api/v4"
REQUEST_DELAY = 1.0  # WoRMS asks for max 1 req/s


@dataclass
class WoRMSRecord:
    aphia_id: int
    accepted_name: str
    scientific_name: str
    authority: str
    rank: str
    kingdom: str
    phylum: str
    class_name: str
    order_name: str
    family: str
    genus: str
    is_marine: int
    is_extinct: int
    match_type: str  # 'exact', 'like', 'accepted_name_differs'


@dataclass
class IUCNRecord:
    status: str  # LC, NT, VU, EN, CR, EW, EX, DD, NE
    assessment_year: str
    population_trend: str


# ── backup and schema ────────────────────────────────────────────────


def backup_database() -> Path:
    BACKUP_DIR.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = BACKUP_DIR / f"crustacean_virus_core_before_worms_iucn_{stamp}.db"
    shutil.copy2(DB_PATH, backup_path)
    return backup_path


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        PRAGMA foreign_keys = ON;

        CREATE TABLE IF NOT EXISTS worms_search_log (
            log_id INTEGER PRIMARY KEY AUTOINCREMENT,
            host_id INTEGER NOT NULL,
            search_name TEXT NOT NULL,
            aphia_id INTEGER,
            match_type TEXT,
            found_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS iucn_search_log (
            log_id INTEGER PRIMARY KEY AUTOINCREMENT,
            host_id INTEGER NOT NULL,
            search_name TEXT NOT NULL,
            iucn_status TEXT,
            assessment_year TEXT,
            found_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        """
    )


def source_id(conn: sqlite3.Connection, key: str) -> int | None:
    row = conn.execute(
        "SELECT source_id FROM external_sources WHERE source_key = ?", (key,)
    ).fetchone()
    return row["source_id"] if row else None


# ── WoRMS API ────────────────────────────────────────────────────────


def _worms_request(path: str, **params: Any) -> dict | list | None:
    url = f"{WORMS_BASE}{path}"
    if params:
        url += "?" + urllib.parse.urlencode(
            {k: v for k, v in params.items() if v is not None}
        )
    try:
        req = urllib.request.Request(
            url, headers={"User-Agent": "crustacean-virus-db-curation/1.0"}
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, json.JSONDecodeError) as exc:
        print(f"    [warn] WoRMS request failed ({url[:80]}): {exc}")
        return None


def search_worms(scientific_name: str) -> list[WoRMSRecord]:
    """Search WoRMS by name, return list of matches."""
    data = _worms_request(
        f"/AphiaRecordsByName/{urllib.parse.quote(scientific_name)}",
        marine_only=0,
        like=False,
    )
    if not data or not isinstance(data, list):
        # Try fuzzy/like search
        time.sleep(REQUEST_DELAY)
        data = _worms_request(
            f"/AphiaRecordsByName/{urllib.parse.quote(scientific_name)}",
            marine_only=0,
            like=True,
        )
        if not data or not isinstance(data, list):
            return []

    results: list[WoRMSRecord] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        aphia_id = item.get("AphiaID") or 0
        results.append(
            WoRMSRecord(
                aphia_id=aphia_id,
                accepted_name=(
                    item.get("valid_name") or item.get("scientificname") or ""
                ).strip(),
                scientific_name=(item.get("scientificname") or "").strip(),
                authority=(item.get("authority") or "").strip(),
                rank=(item.get("rank") or "").strip(),
                kingdom=(item.get("kingdom") or "").strip(),
                phylum=(item.get("phylum") or "").strip(),
                class_name=(item.get("class") or "").strip(),
                order_name=(item.get("order") or "").strip(),
                family=(item.get("family") or "").strip(),
                genus=(item.get("genus") or "").strip(),
                is_marine=item.get("isMarine", 0) or 0,
                is_extinct=item.get("isExtinct", 0) or 0,
                match_type="exact",
            )
        )
    return results


def worms_classification(aphia_id: int) -> list[dict]:
    """Get full hierarchical classification from WoRMS."""
    data = _worms_request(
        f"/AphiaClassificationByAphiaID/{aphia_id}"
    )
    if not data:
        return []
    # Walk the nested tree
    items: list[dict] = []
    current = data if isinstance(data, dict) else {}
    while current:
        rank = str(current.get("rank", "")).strip()
        sci_name = str(current.get("scientificname", "")).strip()
        if rank and sci_name:
            items.append({"rank": rank, "name": sci_name})
        current = current.get("child") if isinstance(current, dict) else None
    return items


# ── IUCN API ─────────────────────────────────────────────────────────


def fetch_iucn(scientific_name: str, token: str) -> IUCNRecord | None:
    """Fetch IUCN conservation status by scientific name."""
    encoded = urllib.parse.quote(scientific_name)
    url = f"{IUCN_BASE}/species/scientific_name/{encoded}?token={token}"
    try:
        req = urllib.request.Request(
            url, headers={"User-Agent": "crustacean-virus-db-curation/1.0"}
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, json.JSONDecodeError) as exc:
        # IUCN may return 404 for unassessed species — that's expected
        if isinstance(exc, urllib.error.HTTPError) and exc.code == 404:
            return None
        print(f"    [warn] IUCN request failed ({scientific_name}): {exc}")
        return None

    assessments = (data or {}).get("assessments", [])
    if not assessments:
        return None

    best = assessments[0]  # most recent
    status = (best.get("red_list_category", {}) or {}).get("code") or ""
    year = (best.get("assessment_date") or "")
    if year and len(year) >= 4:
        year = year[:4]
    trend = (best.get("population_trend") or "")
    return IUCNRecord(status=str(status), assessment_year=str(year), population_trend=str(trend))


# ── database operations ──────────────────────────────────────────────


def upsert_host_profile(
    conn: sqlite3.Connection,
    host_id: int,
    host_name: str,
    worms_record: WoRMSRecord | None,
    worms_class_data: list[dict],
    ncbi_source_id: int | None,
    worms_source_id: int | None,
) -> bool:
    """Create or update a host_taxonomy_profiles row. Returns True if changed."""
    if worms_record:
        aphia_id = str(worms_record.aphia_id)
        accepted = worms_record.accepted_name
        lineage = "; ".join(
            f"{c['rank']}: {c['name']}" for c in worms_class_data
        ) if worms_class_data else (
            f"Kingdom: {worms_record.kingdom}; Phylum: {worms_record.phylum}; "
            f"Class: {worms_record.class_name}; Order: {worms_record.order_name}; "
            f"Family: {worms_record.family}; Genus: {worms_record.genus}"
        )

        # Determine if crustacean based on WoRMS classification
        is_crustacean = 1 if (
            "Malacostraca" in str(worms_record.class_name)
            or "Branchiopoda" in str(worms_record.class_name)
            or "Maxillopoda" in str(worms_record.class_name)
            or "Crustacea" in str(lineage)
        ) else 0

        existing = conn.execute(
            "SELECT profile_id FROM host_taxonomy_profiles WHERE host_id = ?",
            (host_id,),
        ).fetchone()

        if existing:
            conn.execute(
                """
                UPDATE host_taxonomy_profiles
                SET ncbi_taxid = COALESCE(ncbi_taxid, ?),
                    accepted_name = ?,
                    lineage = ?,
                    lineage_kingdom = ?, lineage_phylum = ?, lineage_class = ?,
                    lineage_order = ?, lineage_family = ?, lineage_genus = ?,
                    is_crustacean = ?,
                    is_target_host = COALESCE(is_target_host, ?),
                    match_status = 'from_cache',
                    confidence = 'high',
                    source_id = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE host_id = ?
                """,
                (
                    f"WoRMS:{aphia_id}",
                    accepted,
                    lineage,
                    worms_record.kingdom, worms_record.phylum, worms_record.class_name,
                    worms_record.order_name, worms_record.family, worms_record.genus,
                    is_crustacean, is_crustacean,
                    worms_source_id,
                    host_id,
                ),
            )
        else:
            conn.execute(
                """
                INSERT INTO host_taxonomy_profiles
                    (host_id, ncbi_taxid, accepted_name, lineage,
                     lineage_superkingdom, lineage_kingdom, lineage_phylum,
                     lineage_class, lineage_order, lineage_family, lineage_genus,
                     is_crustacean, is_target_host, match_status, confidence, source_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    host_id,
                    f"WoRMS:{aphia_id}",
                    accepted,
                    lineage,
                    "Eukaryota", worms_record.kingdom, worms_record.phylum,
                    worms_record.class_name, worms_record.order_name, worms_record.family, worms_record.genus,
                    is_crustacean, is_crustacean,
                    "from_cache", "high", worms_source_id,
                ),
            )

        # Record external xref
        conn.execute(
            """
            INSERT OR IGNORE INTO external_xrefs
                (entity_type, entity_id, source_id, external_id, external_url,
                 match_status, confidence, matched_by, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "host", host_id, worms_source_id, str(aphia_id),
                f"https://www.marinespecies.org/aphia.php?p=taxdetails&id={aphia_id}",
                "exact", "high", "enrich_hosts_worms_iucn.py",
                f"WoRMS match for {host_name} -> {accepted}",
            ),
        )

        # Record alias if accepted name differs from current host name
        if accepted != host_name:
            conn.execute(
                """
                INSERT OR IGNORE INTO host_aliases
                    (host_id, alias, alias_type, source_id, external_id, match_status, confidence, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    host_id, accepted, "synonym",
                    worms_source_id, str(aphia_id),
                    "exact", "high",
                    f"WoRMS accepted name: {accepted}",
                ),
            )
            # Add review candidate
            conn.execute(
                """
                INSERT OR IGNORE INTO host_review_candidates
                    (host_id, issue_type, suggested_name, evidence, confidence)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    host_id, "accepted_name_differs", accepted,
                    f"WoRMS accepted name: {host_name} -> {accepted}",
                    "high",
                ),
            )
        return True
    return False


def update_iucn_status(
    conn: sqlite3.Connection, host_id: int, iucn: IUCNRecord | None
) -> None:
    """Update crustacean_hosts with IUCN status if currently empty."""
    if not iucn:
        return
    existing = conn.execute(
        "SELECT iucn_status FROM crustacean_hosts WHERE host_id = ?",
        (host_id,),
    ).fetchone()
    if existing and existing["iucn_status"]:
        return  # already has IUCN status
    conn.execute(
        """
        UPDATE crustacean_hosts
        SET iucn_status = ?, iucn_assessment_year = ?
        WHERE host_id = ?
        """,
        (iucn.status, iucn.assessment_year, host_id),
    )


def log_search_worms(conn: sqlite3.Connection, host_id: int, name: str, record: WoRMSRecord | None) -> None:
    if record:
        conn.execute(
            "INSERT INTO worms_search_log (host_id, search_name, aphia_id, match_type) VALUES (?, ?, ?, ?)",
            (host_id, name, record.aphia_id, record.match_type),
        )
    else:
        conn.execute(
            "INSERT INTO worms_search_log (host_id, search_name, aphia_id, match_type) VALUES (?, ?, ?, ?)",
            (host_id, name, None, "not_found"),
        )


def log_search_iucn(conn: sqlite3.Connection, host_id: int, name: str, iucn: IUCNRecord | None) -> None:
    if iucn:
        conn.execute(
            "INSERT INTO iucn_search_log (host_id, search_name, iucn_status, assessment_year) VALUES (?, ?, ?, ?)",
            (host_id, name, iucn.status, iucn.assessment_year),
        )
    else:
        conn.execute(
            "INSERT INTO iucn_search_log (host_id, search_name, iucn_status, assessment_year) VALUES (?, ?, NULL, NULL)",
            (host_id, name, None, None),
        )


# ── main ─────────────────────────────────────────────────────────────


def run_enrich(
    conn: sqlite3.Connection,
    iucn_token: str | None,
    limit: int | None,
    dry_run: bool,
    recheck: bool = False,
) -> dict:
    stats = {
        "hosts_processed": 0,
        "worms_matched": 0,
        "worms_no_match": 0,
        "iucn_checked": 0,
        "iucn_status_found": 0,
        "profiles_created": 0,
        "profiles_updated": 0,
        "xrefs_added": 0,
        "aliases_added": 0,
    }

    worms_src_id = source_id(conn, "worms")
    ncbi_src_id = source_id(conn, "ncbi_taxonomy")

    where = "" if recheck else """
        WHERE NOT EXISTS (
            SELECT 1 FROM worms_search_log w
            WHERE w.host_id = crustacean_hosts.host_id
        )
    """
    hosts = conn.execute(
        f"SELECT * FROM crustacean_hosts {where} ORDER BY host_id"
    ).fetchall()
    if limit:
        hosts = hosts[:limit]

    for host in hosts:
        host_id = host["host_id"]
        name = host["scientific_name"]
        stats["hosts_processed"] += 1

        # ── WoRMS search ──
        time.sleep(REQUEST_DELAY)
        worms_results = search_worms(name)
        best_record = worms_results[0] if worms_results else None

        if best_record:
            stats["worms_matched"] += 1
            time.sleep(REQUEST_DELAY)
            class_data = worms_classification(best_record.aphia_id)
        else:
            stats["worms_no_match"] += 1
            class_data = []

        if not dry_run:
            log_search_worms(conn, host_id, name, best_record)

            changed = upsert_host_profile(
                conn, host_id, name, best_record, class_data,
                ncbi_src_id, worms_src_id,
            )
            if changed:
                existing = conn.execute(
                    "SELECT profile_id FROM host_taxonomy_profiles WHERE host_id = ?",
                    (host_id,),
                ).fetchone()
                if existing:
                    stats["profiles_updated"] += 1
                else:
                    stats["profiles_created"] += 1

            if best_record:
                stats["xrefs_added"] += 1
                if best_record.accepted_name != name:
                    stats["aliases_added"] += 1

        # ── IUCN search ──
        if iucn_token:
            stats["iucn_checked"] += 1
            time.sleep(REQUEST_DELAY)
            search_name = best_record.accepted_name if best_record else name
            iucn = fetch_iucn(search_name, iucn_token)
            if iucn:
                stats["iucn_status_found"] += 1
                if not dry_run:
                    update_iucn_status(conn, host_id, iucn)
            if not dry_run:
                log_search_iucn(conn, host_id, search_name, iucn)

        if stats["hosts_processed"] % 10 == 0:
            print(f"  [progress] {stats['hosts_processed']}/{len(hosts)} "
                  f"worms_matched={stats['worms_matched']} "
                  f"iucn_found={stats['iucn_status_found']}")
            if not dry_run:
                conn.commit()

    return stats


def export_results(conn: sqlite3.Connection, stats: dict) -> Path:
    DOWNLOADS_DIR.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = DOWNLOADS_DIR / f"worms_iucn_results_{stamp}.json"
    data = {
        "stats": stats,
        "completed_at": datetime.now().isoformat(timespec="seconds"),
    }
    out_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_path


def log_run(conn: sqlite3.Connection, stats: dict) -> None:
    src_id = source_id(conn, "worms")
    payload = "; ".join(f"{k}={v}" for k, v in sorted(stats.items()))
    conn.execute(
        """
        INSERT INTO curation_logs
            (entity_type, action, source_id, new_value, confidence, curator, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "host_taxonomy",
            "enrich_hosts_worms_iucn",
            src_id,
            payload,
            "high",
            "enrich_hosts_worms_iucn.py",
            "Enriched host taxonomy via WoRMS and IUCN Red List.",
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

    parser = argparse.ArgumentParser(description="Enrich hosts via WoRMS and IUCN")
    parser.add_argument("--iucn-token", type=str, default=None, help="IUCN Red List API token")
    parser.add_argument("--limit", type=int, default=None, help="Max hosts to process")
    parser.add_argument("--recheck", action="store_true", help="Recheck hosts already present in worms_search_log")
    parser.add_argument("--dry-run", action="store_true", help="Preview only")
    args = parser.parse_args()

    if args.dry_run:
        print("[dry-run] Preview mode — no database changes will be made")
    if not args.iucn_token:
        print("[info] No IUCN token provided — skipping IUCN status lookup")

    backup_path = backup_database() if not args.dry_run else None
    if backup_path:
        print(f"[backup] {backup_path}")

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        ensure_schema(conn)
        stats = run_enrich(conn, args.iucn_token, args.limit, args.dry_run, recheck=args.recheck)
        if not args.dry_run:
            export_path = export_results(conn, stats)
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
