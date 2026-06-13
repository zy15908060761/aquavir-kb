"""
Enrich protein domain annotations from InterPro via EBI REST API.

Uses the EBI Proteins API (https://www.ebi.ac.uk/proteins/api/) to fetch
InterPro domain annotations for viral proteins without requiring local
InterProScan installation.

Strategy:
  1. Get UniProt IDs from uniprot_annotations
  2. Query EBI Proteins API for InterPro entries per UniProt ID
  3. Parse domain coordinates, names, GO terms, and pathway links
  4. Store in protein_domains (existing table) + interpro_go table

This complements the existing run_interproscan_annotation.py which requires
local InterProScan binary. This script uses the REST API for on-demand queries.

Usage:
    python enrich_interpro_api.py                       # full run
    python enrich_interpro_api.py --limit 100            # process first N
    python enrich_interpro_api.py --dry-run              # preview only
    python enrich_interpro_api.py --stats                # coverage stats
"""

from __future__ import annotations

import json
import re
import sqlite3
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "crustacean_virus_core.db"
CACHE_DIR = BASE_DIR / "external_data" / "interpro"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

EBI_PROTEINS_API = "https://www.ebi.ac.uk/proteins/api/proteins"
INTERPRO_API = "https://www.ebi.ac.uk/interpro/api/entry"

RATE_LIMIT = 0.3  # seconds between requests
BATCH_SIZE = 200


def create_tables(conn: sqlite3.Connection) -> None:
    """Ensure protein_domains and related tables exist."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS interpro_annotations (
            interpro_anno_id INTEGER PRIMARY KEY AUTOINCREMENT,
            uniprot_id TEXT NOT NULL,
            interpro_id TEXT NOT NULL,
            interpro_name TEXT,
            interpro_type TEXT,
            source_database TEXT,
            start_pos INTEGER,
            end_pos INTEGER,
            score REAL,
            go_terms TEXT,
            pathways TEXT,
            protein_id INTEGER,
            fetched_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (protein_id) REFERENCES viral_proteins(protein_id)
        );

        CREATE TABLE IF NOT EXISTS interpro_go_terms (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            protein_id INTEGER,
            interpro_id TEXT,
            go_id TEXT,
            go_name TEXT,
            go_namespace TEXT,
            evidence_source TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(protein_id, interpro_id, go_id)
        );

        CREATE INDEX IF NOT EXISTS idx_ip_uniprot ON interpro_annotations(uniprot_id);
        CREATE INDEX IF NOT EXISTS idx_ip_interpro ON interpro_annotations(interpro_id);
        CREATE INDEX IF NOT EXISTS idx_ip_protein ON interpro_annotations(protein_id);
        CREATE INDEX IF NOT EXISTS idx_ipgo_protein ON interpro_go_terms(protein_id);
        CREATE INDEX IF NOT EXISTS idx_ipgo_go ON interpro_go_terms(go_id);

        CREATE TABLE IF NOT EXISTS interpro_api_query_log (
            query_id INTEGER PRIMARY KEY AUTOINCREMENT,
            uniprot_id TEXT NOT NULL,
            protein_id INTEGER,
            status TEXT NOT NULL,
            interpro_count INTEGER DEFAULT 0,
            go_count INTEGER DEFAULT 0,
            message TEXT,
            queried_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(uniprot_id)
        );
    """)
    conn.commit()


def fetch_uniprot_protein(uniprot_id: str) -> dict | None:
    """Fetch protein data from EBI Proteins API for a UniProt ID."""
    url = f"{EBI_PROTEINS_API}/{uniprot_id}"
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "crustacean-virus-db-curation/1.0",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        print(f"  [warn] HTTP {exc.code} for {uniprot_id}")
        return None
    except Exception as exc:
        print(f"  [warn] Failed to fetch {uniprot_id}: {exc}")
        return None


def parse_interpro_entries(data: dict) -> list[dict[str, Any]]:
    """Extract InterPro domain entries from EBI Proteins API response."""
    results = []
    if not data:
        return results

    for dbref in data.get("dbReferences", []):
        if dbref.get("type") != "InterPro":
            continue
        interpro_id = dbref.get("id", "")
        interpro_name = dbref.get("properties", {}).get("entry name", "")

        for prop_name, prop_value in dbref.get("properties", {}).items():
            if prop_name in ("entry name", "source database"):
                continue
            if isinstance(prop_value, str) and "GO:" in prop_value:
                continue

        results.append({
            "interpro_id": interpro_id,
            "interpro_name": interpro_name,
            "source_database": dbref.get("properties", {}).get("source database", ""),
        })

    # Get domain positions from features
    for feature in data.get("features", []):
        if feature.get("type") in ("DOMAIN", "REGION", "MOTIF", "CHAIN", "REPEAT"):
            feat_interpro = None
            interpro_name = None

            # Check if this feature has InterPro cross-refs
            for xref in feature.get("crossReferences", []):
                if xref.get("database") == "InterPro":
                    feat_interpro = xref.get("id")
                    interpro_name = xref.get("properties", {}).get("Name", "")

            if feat_interpro:
                results.append({
                    "interpro_id": feat_interpro,
                    "interpro_name": interpro_name or "",
                    "interpro_type": feature.get("type", ""),
                    "source_database": "InterPro",
                    "start_pos": feature.get("begin"),
                    "end_pos": feature.get("end"),
                    "score": feature.get("score"),
                })

    return results


def parse_go_terms(data: dict) -> list[dict[str, str]]:
    """Extract GO terms from EBI Proteins API response."""
    terms: dict[str, dict[str, str]] = {}
    if not data:
        return []
    for dbref in data.get("dbReferences", []):
        props = dbref.get("properties", {}) or {}
        for value in props.values():
            if not isinstance(value, str) or "GO:" not in value:
                continue
            for go_id in re.findall(r"GO:\d{7}", value):
                terms.setdefault(go_id, {"go_id": go_id, "go_name": "", "go_namespace": ""})
    for ref in data.get("uniProtKBCrossReferences", []) or []:
        if ref.get("database") != "GO":
            continue
        go_id = ref.get("id")
        if not go_id:
            continue
        props = {p.get("key"): p.get("value") for p in ref.get("properties", []) if isinstance(p, dict)}
        term = props.get("GoTerm") or props.get("term") or ""
        namespace = ""
        name = term
        if ":" in term:
            prefix, rest = term.split(":", 1)
            namespace = {"C": "cellular_component", "F": "molecular_function", "P": "biological_process"}.get(prefix, prefix)
            name = rest
        terms[go_id] = {"go_id": go_id, "go_name": name, "go_namespace": namespace}
    return list(terms.values())


def fetch_interpro_entry(interpro_id: str) -> dict | None:
    """Fetch detailed InterPro entry info."""
    url = f"{INTERPRO_API}/{interpro_id}"
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "crustacean-virus-db-curation/1.0",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode())
    except Exception:
        return None


def get_uniprot_ids(conn: sqlite3.Connection, limit: int | None = None) -> list[tuple[str, int | None]]:
    """Get UniProt IDs from local database with protein_id."""
    limit_clause = f"LIMIT {limit}" if limit else ""
    rows = conn.execute(
        f"""
        SELECT DISTINCT u.uniprot_id, u.ncbi_protein_acc
        FROM uniprot_annotations u
        WHERE u.uniprot_id IS NOT NULL AND u.uniprot_id != ''
        {limit_clause}
        """
    ).fetchall()

    result = []
    for r in rows:
        # Find protein_id
        protein_row = conn.execute(
            """
            SELECT protein_id FROM uniprot_protein_links
            WHERE uniprot_id = ? AND ncbi_protein_acc = ?
            LIMIT 1
            """,
            (r[0], r[1]),
        ).fetchone()
        if not protein_row:
            protein_row = conn.execute(
                """
                SELECT protein_id FROM viral_proteins
                WHERE protein_accession = ?
                   OR substr(protein_accession, 1, instr(protein_accession || '.', '.') - 1) = ?
                LIMIT 1
                """,
                (r[1], r[1]),
            ).fetchone()
        pid = protein_row[0] if protein_row else None
        result.append((r[0], pid))

    return result


def enrich_interpro(
    conn: sqlite3.Connection,
    dry_run: bool = False,
    limit: int | None = None,
) -> int:
    """Main enrichment logic."""
    # Build the full candidate list first, then apply --limit to the pending
    # set. This makes repeated small runs advance instead of rechecking the
    # same first N UniProt IDs.
    uniprot_ids = get_uniprot_ids(conn, limit=None)
    print(f"[interpro] {len(uniprot_ids)} UniProt IDs to query")

    # Check existing
    existing = set()
    for row in conn.execute("SELECT DISTINCT uniprot_id FROM interpro_annotations").fetchall():
        existing.add(row[0])
    for row in conn.execute("SELECT uniprot_id FROM interpro_api_query_log WHERE status IN ('no_interpro','not_found')").fetchall():
        existing.add(row[0])

    pending = [(uid, pid) for uid, pid in uniprot_ids if uid not in existing]
    if limit:
        pending = pending[:limit]
    print(f"[interpro] {len(pending)} new IDs to process ({len(existing)} already done)")

    if dry_run:
        for uid, pid in pending[:20]:
            print(f"  [dry-run] UniProt={uid} protein_id={pid}")
        return 0

    inserted = 0
    for i, (uid, pid) in enumerate(pending):
        if i % 50 == 0 and i > 0:
            print(f"  [progress] {i}/{len(pending)} ...")
            conn.commit()

        data = fetch_uniprot_protein(uid)
        if not data:
            conn.execute(
                """
                INSERT INTO interpro_api_query_log (uniprot_id, protein_id, status, message)
                VALUES (?, ?, 'not_found', 'EBI Proteins API returned no data')
                ON CONFLICT(uniprot_id) DO UPDATE SET status=excluded.status, message=excluded.message, queried_at=CURRENT_TIMESTAMP
                """,
                (uid, pid),
            )
            time.sleep(RATE_LIMIT)
            continue

        entries = parse_interpro_entries(data)
        go_entries = parse_go_terms(data)

        for entry in entries:
            interpro_id = entry.get("interpro_id", "")
            if not interpro_id:
                continue

            go_terms = entry.get("go_terms", "")
            pathways = entry.get("pathways", "")

            try:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO interpro_annotations
                        (uniprot_id, interpro_id, interpro_name, interpro_type,
                         source_database, start_pos, end_pos, score, go_terms, pathways, protein_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        uid,
                        interpro_id,
                        entry.get("interpro_name", ""),
                        entry.get("interpro_type", ""),
                        entry.get("source_database", ""),
                        entry.get("start_pos"),
                        entry.get("end_pos"),
                        entry.get("score"),
                        go_terms if isinstance(go_terms, str) else json.dumps(go_terms or []),
                        pathways if isinstance(pathways, str) else json.dumps(pathways or []),
                        pid,
                    ),
                )
                inserted += 1
            except Exception as exc:
                print(f"  [warn] DB insert error for {uid}/{interpro_id}: {exc}")

        for go in go_entries:
            try:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO interpro_go_terms
                        (protein_id, interpro_id, go_id, go_name, go_namespace, evidence_source)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        pid,
                        None,
                        go.get("go_id"),
                        go.get("go_name", ""),
                        go.get("go_namespace", ""),
                        "EBI Proteins API",
                    ),
                )
            except Exception as exc:
                print(f"  [warn] GO insert error for {uid}/{go.get('go_id')}: {exc}")

        conn.execute(
            """
            INSERT INTO interpro_api_query_log (uniprot_id, protein_id, status, interpro_count, go_count, message)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(uniprot_id) DO UPDATE SET
                protein_id=excluded.protein_id,
                status=excluded.status,
                interpro_count=excluded.interpro_count,
                go_count=excluded.go_count,
                message=excluded.message,
                queried_at=CURRENT_TIMESTAMP
            """,
            (
                uid,
                pid,
                "ok" if entries else "no_interpro",
                len(entries),
                len(go_entries),
                "" if entries else "No InterPro dbReferences/features returned by EBI Proteins API",
            ),
        )

        time.sleep(RATE_LIMIT)

    conn.commit()
    return inserted


def register_source(conn: sqlite3.Connection) -> None:
    """Update InterPro source registration (already exists from external layer)."""
    conn.execute(
        """
        INSERT INTO external_sources
            (source_key, name, category, base_url, description, update_policy, priority)
        VALUES ('interpro', 'InterPro', 'protein_domain',
                'https://www.ebi.ac.uk/interpro/',
                'Integrated protein family, domain, and functional site annotations via EBI Proteins API.',
                'api', 90)
        ON CONFLICT(source_key) DO UPDATE SET
            name = excluded.name,
            description = excluded.description,
            priority = excluded.priority,
            updated_at = CURRENT_TIMESTAMP
        """
    )
    conn.commit()


def show_stats(conn: sqlite3.Connection) -> None:
    """Print InterPro enrichment stats."""
    print("\n=== InterPro Integration Stats ===")
    row = conn.execute("SELECT COUNT(*) FROM interpro_annotations").fetchone()
    print(f"  InterPro annotations: {row[0]}")
    row = conn.execute("SELECT COUNT(DISTINCT uniprot_id) FROM interpro_annotations").fetchone()
    print(f"  UniProt IDs covered: {row[0]}")
    row = conn.execute("SELECT COUNT(DISTINCT interpro_id) FROM interpro_annotations").fetchone()
    print(f"  Unique InterPro entries: {row[0]}")
    row = conn.execute("SELECT COUNT(*) FROM interpro_go_terms").fetchone()
    print(f"  GO term links: {row[0]}")

    rows = conn.execute(
        "SELECT interpro_type, COUNT(*) as cnt FROM interpro_annotations "
        "WHERE interpro_type != '' GROUP BY interpro_type ORDER BY cnt DESC LIMIT 10"
    ).fetchall()
    print("  Domain types:")
    for r in rows:
        print(f"    {r[0]:30s} {r[1]}")


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="Enrich proteins with InterPro domain annotations via EBI API")
    parser.add_argument("--dry-run", action="store_true", help="Preview only")
    parser.add_argument("--limit", type=int, default=None, help="Process first N UniProt IDs")
    parser.add_argument("--stats", action="store_true", help="Show stats only")
    args = parser.parse_args()

    conn = sqlite3.connect(str(DB_PATH))
    try:
        create_tables(conn)
        register_source(conn)

        if args.stats:
            show_stats(conn)
            return

        inserted = enrich_interpro(
            conn,
            dry_run=args.dry_run,
            limit=args.limit,
        )
        print(f"\n[done] InterPro enrichment complete: {inserted} new annotations")
        show_stats(conn)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
