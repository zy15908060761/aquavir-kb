"""
Enrich viral protein annotations from UniProt.

Strategy:
  1. Read all NCBI protein accessions from viral_proteins
  2. Batch-submit to UniProt ID mapping API (NCBI_Protein -> UniProtKB)
  3. Fetch UniProt entries with fields: protein_name, EC, GO, keywords
  4. Store in uniprot_annotations table
  5. Update functional_category based on UniProt keywords

Usage:
    python enrich_uniprot.py                          # full run
    python enrich_uniprot.py --dry-run                # preview only
    python enrich_uniprot.py --limit 1000             # process first N
    python enrich_uniprot.py --stats                  # coverage stats
    python enrich_uniprot.py --remap                  # re-run ID mapping
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any


BASE_DIR = Path(__file__).resolve().parent
DB_PATH = os.environ.get(
    "ENRICH_DB_PATH",
    str(BASE_DIR / "crustacean_virus_core.db"),
)

UNIPROT_IDMAPPING_URL = "https://rest.uniprot.org/idmapping/run"
UNIPROT_STATUS_URL = "https://rest.uniprot.org/idmapping/status"
UNIPROT_STREAM_URL = "https://rest.uniprot.org/idmapping/stream"

CACHE_DIR = BASE_DIR / "external_data" / "uniprot"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

BATCH_SIZE = 500       # IDs per ID mapping job
SLEEP_BETWEEN = 0.5    # seconds between polling
MAX_POLL_TIME = 600    # max seconds to wait for a mapping job


def parse_idmapping_results(data: dict) -> dict[str, str]:
    """Parse ID mapping results: {from_id -> to_id (UniProt accession)}."""
    mapping: dict[str, str] = {}
    for result in data.get("results", []):
        from_id = result.get("from", "")
        to_id = result.get("to", "")
        if from_id and to_id:
            # Strip version from NCBI accession
            mapping[from_id.split(".")[0]] = to_id
    return mapping


def _get_from_db(acc: str) -> str:
    """Choose the correct UniProt 'from' database based on accession prefix."""
    # RefSeq accessions: NP_, XP_, YP_, WP_, AP_, BP_
    if re.match(r"^(NP|XP|YP|WP|AP|BP)_\d+", acc):
        return "RefSeq_Protein"
    # Default: EMBL/GenBank/DDBJ CDS (covers AA, AB, AC, ... prefixes)
    return "EMBL-GenBank-DDBJ_CDS"


def submit_idmapping_job(ids: list[str], from_db: str | None = None) -> str | None:
    """Submit a UniProt ID mapping job. Returns job ID or None."""
    if not ids:
        return None

    # Determine which from database to use
    if from_db is None:
        from_db = _get_from_db(ids[0])

    ids_str = ",".join(ids)
    data = urllib.parse.urlencode({
        "from": from_db,
        "to": "UniProtKB",
        "ids": ids_str,
    }).encode()

    req = urllib.request.Request(
        UNIPROT_IDMAPPING_URL,
        data=data,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "crustacean-virus-db-curation/1.0",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            result = json.loads(resp.read().decode())
            return result.get("jobId")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode()
        print(f"  [error] HTTP {exc.code}: {body[:200]}")
        return None
    except Exception as exc:
        print(f"  [error] ID mapping submission failed: {exc}")
        return None


def poll_idmapping_job(job_id: str) -> dict | None:
    """Poll until a mapping job completes. Returns the results dict or None.

    After job completion, always fetches from stream endpoint for full results.
    The status response may only contain a partial preview.
    """
    start = time.time()
    while time.time() - start < MAX_POLL_TIME:
        url = f"{UNIPROT_STATUS_URL}/{job_id}"
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "crustacean-virus-db-curation/1.0",
                "Accept": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                status_data = json.loads(resp.read().decode())
        except Exception as exc:
            print(f"  [warn] poll failed: {exc}")
            time.sleep(5)
            continue

        job_status = status_data.get("jobStatus", "")

        # Check if job is done (status either "FINISHED" or has results)
        if job_status == "FINISHED" or "results" in status_data:
            # Always fetch full results from stream endpoint
            results_url = f"{UNIPROT_STREAM_URL}/{job_id}"
            try:
                req2 = urllib.request.Request(
                    results_url,
                    headers={
                        "User-Agent": "crustacean-virus-db-curation/1.0",
                        "Accept": "application/json",
                    },
                )
                with urllib.request.urlopen(req2, timeout=120) as resp2:
                    results_raw = json.loads(resp2.read().decode())
                    # Handle different response formats
                    if isinstance(results_raw, dict) and "results" in results_raw:
                        results_list = results_raw["results"]
                    elif isinstance(results_raw, list):
                        results_list = results_raw
                    else:
                        results_list = []

                    # Extract from/to mapping
                    mapped_results = []
                    for r in results_list:
                        from_id = r.get("from", "")
                        to_data = r.get("to", {})
                        if isinstance(to_data, dict):
                            to_id = to_data.get("primaryAccession", "")
                        else:
                            to_id = str(to_data) if to_data else ""
                        if from_id and to_id:
                            mapped_results.append({"from": from_id, "to": to_id})

                    result_count = len(mapped_results)
                    total_input = status_data.get("jobTitle", {}).get("ids", "").count(",") + 1 if "jobTitle" in status_data else result_count
                    print(f"  [stream] {result_count} results")
                    return {"results": mapped_results}
            except Exception as exc:
                print(f"  [error] fetching stream results failed: {exc}")
                return None

        if job_status in ("ERROR", "FAILED"):
            print(f"  [error] job {job_id} failed: {status_data}")
            return None
        elif job_status == "NOT_FOUND":
            print(f"  [warn] job {job_id} not found (may have expired)")
            return None

        # Still running — wait and retry
        time.sleep(SLEEP_BETWEEN)

    print(f"  [warn] job {job_id} timed out after {MAX_POLL_TIME}s")
    return None


def fetch_uniprot_details(accessions: list[str]) -> dict[str, dict]:
    """Batch-fetch UniProt details for a list of UniProt accessions.

    Returns dict of {ncbi_acc: {details}}.
    """
    if not accessions:
        return {}

    # Query UniProtKB using accession filter
    accession_query = " OR ".join(f"(accession:{a})" for a in accessions)
    query = urllib.parse.urlencode({
        "query": accession_query,
        "fields": "accession,id,protein_name,ec,go,keyword,organism_name,length",
        "format": "json",
        "size": min(len(accessions), 500),
    })
    url = f"https://rest.uniprot.org/uniprotkb/search?{query}"

    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "crustacean-virus-db-curation/1.0",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode())
    except Exception as exc:
        print(f"  [error] UniProt search failed: {exc}")
        return {}

    results: dict[str, dict] = {}
    for entry in data.get("results", []):
        primary_acc = entry.get("primaryAccession", "")
        if not primary_acc:
            continue

        # Protein name
        prot_desc = entry.get("proteinDescription", {}) or {}
        rec_name = prot_desc.get("recommendedName", {}) or {}
        full_name = rec_name.get("fullName", {}).get("value", "")

        # EC numbers
        ecs: list[str] = []
        for rec_name_entry in [rec_name]:
            for ec in rec_name_entry.get("ecNumbers", []):
                val = ec.get("value", "")
                if val and val not in ecs:
                    ecs.append(val)
        # Also check alternative names
        for alt_name in prot_desc.get("alternativeNames", []):
            for ec in alt_name.get("ecNumbers", []):
                val = ec.get("value", "")
                if val and val not in ecs:
                    ecs.append(val)

        # GO terms (stored in uniProtKBCrossReferences with database='GO')
        go_terms: list[dict] = []
        for xref in entry.get("uniProtKBCrossReferences", []):
            if xref.get("database") == "GO":
                go_id = xref.get("id", "")
                go_term = ""
                for prop in xref.get("properties", []):
                    if prop.get("key") == "GoTerm":
                        go_term = prop.get("value", "")
                go_terms.append({"go_id": go_id, "go_term": go_term})

        # Keywords
        keywords: list[str] = []
        for kw in entry.get("keywords", []):
            keywords.append(kw.get("name", ""))

        # Gene name
        gene_name = ""
        genes = entry.get("genes", [])
        if genes:
            gene_name = genes[0].get("geneName", {}).get("value", "")

        # Organism
        organism = entry.get("organism", {}) or {}
        org_name = organism.get("scientificName", "")

        # Determine functional category based on keywords
        func_cat = infer_functional_category(keywords, full_name)

        prot_data = {
            "uniprot_id": primary_acc,
            "protein_name": full_name,
            "gene_name": gene_name,
            "ec_numbers": "; ".join(ecs) if ecs else None,
            "go_terms": json.dumps(go_terms, ensure_ascii=False) if go_terms else None,
            "keywords": "; ".join(keywords) if keywords else None,
            "organism": org_name,
            "length": entry.get("sequence", {}).get("length", 0),
            "functional_category": func_cat,
        }
        # Store under the primary accession (can be looked up by NCBI acc later)
        results[primary_acc] = prot_data

    return results


def infer_functional_category(
    keywords: list[str], protein_name: str
) -> str | None:
    """Infer functional category from UniProt keywords and protein name."""
    kw_lower = " ".join(kw.lower() for kw in keywords) + " " + protein_name.lower()

    # Order matters: more specific first
    if any(kw in kw_lower for kw in ["rna-directed rna polymerase", "rdrp", "rna-dependent rna polymerase", "rna replicase"]):
        return "replication"
    if any(kw in kw_lower for kw in ["viral capsid", "capsid protein", "coat protein", "nucleocapsid", "structural protein", "virion", "capsid assembly", "viral envelope", "spike"]):
        return "structural"
    if any(kw in kw_lower for kw in ["protease", "proteinase", "helicase", "dna polymerase", "rna polymerase", "transcriptase", "replicase", "integrase", "nuclease", "endonuclease", "exonuclease", "primase", "ligase"]):
        return "replication"
    if any(kw in kw_lower for kw in ["host-virus interaction", "host defense", "immune evasion", "interferon antagonist", "apoptosis modulation", "host cell receptor", "viral attachment", "cell fusion"]):
        return "host_interaction"
    if any(kw in kw_lower for kw in ["metabolism", "transferase", "kinase", "methyltransferase", "atpase", "gdp-gtp exchange", "nucleotide-binding", "dna-binding", "rna-binding"]):
        return "metabolism"
    if any(kw in kw_lower for kw in ["virion assembly", "viral assembly", "budding", "virus maturation"]):
        return "assembly"

    return None  # keep existing classification


def get_all_protein_accessions(conn: sqlite3.Connection) -> list[str]:
    """Get all unique NCBI protein accessions (strip version numbers)."""
    rows = conn.execute(
        "SELECT DISTINCT protein_accession FROM viral_proteins WHERE protein_accession IS NOT NULL"
    ).fetchall()
    accs = set()
    for (acc,) in rows:
        acc = acc.strip()
        if not acc:
            continue
        # Strip version suffix
        base = acc.split(".")[0]
        # Validate: NCBI protein accessions are alphanumeric
        if re.match(r"^[A-Z][A-Z0-9_]+$", base):
            accs.add(base)
    return sorted(accs)


def get_mapped_accessions(conn: sqlite3.Connection) -> set[str]:
    """Get set of already mapped NCBI accessions."""
    rows = conn.execute(
        "SELECT DISTINCT ncbi_protein_acc FROM uniprot_annotations"
    ).fetchall()
    return {r[0] for r in rows if r[0]}


def download_schema(conn: sqlite3.Connection) -> None:
    """Create uniprot_annotations table."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS uniprot_annotations (
            annotation_id INTEGER PRIMARY KEY AUTOINCREMENT,
            ncbi_protein_acc TEXT NOT NULL,
            uniprot_id TEXT,
            protein_name TEXT,
            gene_name TEXT,
            ec_numbers TEXT,
            go_terms TEXT,
            keywords TEXT,
            organism TEXT,
            protein_length INTEGER,
            functional_category TEXT,
            fetched_at TEXT,
            UNIQUE(ncbi_protein_acc)
        )
    """)


def run_id_mapping(
    conn: sqlite3.Connection,
    accessions: list[str],
    dry_run: bool = False,
    remap: bool = False,
) -> dict:
    """Run UniProt ID mapping and fetch results."""
    stats = {
        "total_accessions": len(accessions),
        "batches_submitted": 0,
        "batches_succeeded": 0,
        "batches_failed": 0,
        "mapped_count": 0,
        "unmapped_count": 0,
        "details_fetched": 0,
        "existing_skipped": 0,
    }

    already_mapped = get_mapped_accessions(conn) if not remap else set()
    if already_mapped:
        stats["existing_skipped"] = len(
            [a for a in accessions if a in already_mapped]
        )

    # Filter to unmapped accessions only
    to_map = [a for a in accessions if a not in already_mapped or remap]
    stats["to_map"] = len(to_map)
    print(f"[mapping] {len(to_map)} accessions to map ({stats['existing_skipped']} already done)")

    if not to_map:
        return stats

    # Split accessions by type (GenBank vs RefSeq) and batch separately
    gb_accs = [a for a in to_map if _get_from_db(a) == "EMBL-GenBank-DDBJ_CDS"]
    rs_accs = [a for a in to_map if _get_from_db(a) == "RefSeq_Protein"]

    type_batches: list[tuple[str, list[str]]] = []  # (from_db, ids)
    for from_db, acc_list in [("EMBL-GenBank-DDBJ_CDS", gb_accs),
                               ("RefSeq_Protein", rs_accs)]:
        if not acc_list:
            continue
        for i in range(0, len(acc_list), BATCH_SIZE):
            type_batches.append((from_db, acc_list[i:i + BATCH_SIZE]))

    stats["total_batches"] = len(type_batches)
    print(f"[mapping] {len(gb_accs)} GenBank + {len(rs_accs)} RefSeq = {len(type_batches)} batches")

    for batch_idx, (from_db, batch) in enumerate(type_batches, 1):
        print(f"\n[batch {batch_idx}/{len(type_batches)}] ({from_db}) submitting {len(batch)} IDs...")

        # Check cache
        batch_key = f"idmap_batch_{batch_idx}"
        cache_file = CACHE_DIR / f"{batch_key}.json"

        # Cache key includes from_db type
        cache_key = f"idmap_{from_db.replace('-', '_')}_batch_{batch_idx}"
        cache_file = CACHE_DIR / f"{cache_key}.json"

        if cache_file.exists() and not remap:
            mapping_data = json.loads(cache_file.read_text(encoding="utf-8"))
            print(f"  [cache] using cached mapping")
        else:
            # Submit job with correct from_db
            job_id = submit_idmapping_job(batch, from_db=from_db)
            if not job_id:
                stats["batches_failed"] += 1
                continue
            stats["batches_submitted"] += 1
            print(f"  [job] {job_id}")

            # Poll for results
            mapping_data = poll_idmapping_job(job_id)
            if mapping_data is None:
                stats["batches_failed"] += 1
                continue

            # Cache results
            if not dry_run:
                cache_file.write_text(
                    json.dumps(mapping_data, ensure_ascii=False), encoding="utf-8"
                )

        stats["batches_succeeded"] += 1

        # Parse mapping
        mapped = parse_idmapping_results(mapping_data)
        mapped_count = len(mapped)
        stats["mapped_count"] += mapped_count
        stats["unmapped_count"] += len(batch) - mapped_count

        print(f"  [map] {mapped_count}/{len(batch)} mapped to UniProt")

        if dry_run:
            continue

        # Now fetch UniProt details for all mapped accessions
        # Group by UniProt accession (avoid duplicates across NCBI accessions)
        uniprot_to_ncbi: dict[str, list[str]] = defaultdict(list)
        for ncbi_acc, uniprot_acc in mapped.items():
            uniprot_to_ncbi[uniprot_acc].append(ncbi_acc)

        # Fetch details for unique UniProt accessions
        all_uniprot_accs = sorted(uniprot_to_ncbi.keys())
        print(f"  [detail] fetching {len(all_uniprot_accs)} unique UniProt entries...")

        # Batch UniProt detail fetches (100 per request)
        detail_batches = [
            all_uniprot_accs[i:i + 100]
            for i in range(0, len(all_uniprot_accs), 100)
        ]

        for db_idx, dbatch in enumerate(detail_batches, 1):
            # Check detail cache
            detail_cache = CACHE_DIR / f"details_batch{batch_idx}_{db_idx}.json"
            if detail_cache.exists() and not remap:
                details_data = json.loads(detail_cache.read_text(encoding="utf-8"))
            else:
                details_data = fetch_uniprot_details(dbatch)
                if not remap:
                    detail_cache.write_text(
                        json.dumps(details_data, ensure_ascii=False), encoding="utf-8"
                    )
                time.sleep(0.5)  # rate limit

            # Insert into database
            for uniprot_acc, detail in details_data.items():
                for ncbi_acc in uniprot_to_ncbi.get(uniprot_acc, []):
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO uniprot_annotations
                            (ncbi_protein_acc, uniprot_id, protein_name, gene_name,
                             ec_numbers, go_terms, keywords, organism,
                             protein_length, functional_category, fetched_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            ncbi_acc,
                            detail.get("uniprot_id"),
                            detail.get("protein_name"),
                            detail.get("gene_name"),
                            detail.get("ec_numbers"),
                            detail.get("go_terms"),
                            detail.get("keywords"),
                            detail.get("organism"),
                            detail.get("length"),
                            detail.get("functional_category"),
                            datetime.now().isoformat(timespec="seconds"),
                        ),
                    )
                    stats["details_fetched"] += 1

        # Periodic commit
        conn.commit()
        print(f"  [commit] batch {batch_idx} complete")

    return stats


def update_functional_categories(conn: sqlite3.Connection, dry_run: bool = False) -> dict:
    """Update viral_proteins.functional_category from UniProt annotations."""
    stats = {
        "total_updates": 0,
        "replication": 0,
        "structural": 0,
        "host_interaction": 0,
        "metabolism": 0,
        "assembly": 0,
        "skipped_already_set": 0,
    }

    # Find proteins where UniProt suggests a different category
    rows = conn.execute(
        """
        SELECT vp.protein_id, vp.functional_category, ua.functional_category
        FROM viral_proteins vp
        JOIN uniprot_annotations ua ON (
            SUBSTR(vp.protein_accession, 1, INSTR(vp.protein_accession || '.', '.') - 1) = ua.ncbi_protein_acc
        )
        WHERE ua.functional_category IS NOT NULL
          AND vp.functional_category IN ('unknown', '')
    """
    ).fetchall()

    print(f"[update] {len(rows)} unknown proteins with UniProt category suggestions")

    for protein_id, old_cat, new_cat in rows:
        if old_cat not in ("unknown", ""):
            stats["skipped_already_set"] += 1
            continue

        if dry_run:
            stats.setdefault("would_update", []).append((protein_id, old_cat, new_cat))
            stats["total_updates"] += 1
            stats[new_cat] = stats.get(new_cat, 0) + 1
            continue

        conn.execute(
            "UPDATE viral_proteins SET functional_category = ? WHERE protein_id = ?",
            (new_cat, protein_id),
        )
        stats["total_updates"] += 1
        stats[new_cat] = stats.get(new_cat, 0) + 1

    conn.commit()
    return stats


def show_stats(conn: sqlite3.Connection) -> None:
    """Display UniProt annotation stats."""
    c = conn.execute("SELECT COUNT(*) FROM uniprot_annotations")
    total = c.fetchone()[0]

    c = conn.execute("SELECT COUNT(*) FROM uniprot_annotations WHERE uniprot_id IS NOT NULL")
    mapped = c.fetchone()[0]

    c = conn.execute("SELECT COUNT(*) FROM uniprot_annotations WHERE protein_name IS NOT NULL AND protein_name != ''")
    with_name = c.fetchone()[0]

    c = conn.execute("SELECT COUNT(*) FROM uniprot_annotations WHERE ec_numbers IS NOT NULL")
    with_ec = c.fetchone()[0]

    c = conn.execute("SELECT COUNT(*) FROM uniprot_annotations WHERE go_terms IS NOT NULL")
    with_go = c.fetchone()[0]

    c = conn.execute("SELECT COUNT(*) FROM uniprot_annotations WHERE keywords IS NOT NULL")
    with_kw = c.fetchone()[0]

    c = conn.execute("SELECT COUNT(*) FROM uniprot_annotations WHERE functional_category IS NOT NULL")
    with_cat = c.fetchone()[0]

    print(f"\n{'=' * 60}")
    print(f"UniProt 注释统计")
    print(f"{'=' * 60}")
    print(f"  总处理蛋白:                    {total}")
    print(f"  映射到 UniProt:                {mapped}")
    print(f"  获取到蛋白名:                  {with_name}")
    print(f"  获取到 EC 号:                  {with_ec}")
    print(f"  获取到 GO 注释:                {with_go}")
    print(f"  获取到关键词:                  {with_kw}")
    print(f"  建议功能分类:                  {with_cat}")

    # 按病毒物种统计覆盖
    print(f"\n  --- 按病毒物种 UniProt 覆盖率 (Top 10) ---")
    rows = conn.execute(
        """
        SELECT vm.canonical_name,
               COUNT(ua.annotation_id) as mapped_count,
               COUNT(vp.protein_id) as total_count
        FROM viral_proteins vp
        JOIN viral_isolates vi ON vp.isolate_id = vi.isolate_id
        JOIN virus_master vm ON vi.master_id = vm.master_id
        LEFT JOIN uniprot_annotations ua ON (
            SUBSTR(vp.protein_accession, 1, INSTR(vp.protein_accession || '.', '.') - 1) = ua.ncbi_protein_acc
        )
        GROUP BY vm.canonical_name
        HAVING total_count > 10
        ORDER BY mapped_count * 1.0 / total_count ASC
        LIMIT 10
    """
    ).fetchall()
    for name, mapped_cnt, total_cnt in rows:
        pct = mapped_cnt / total_cnt * 100 if total_cnt else 0
        print(f"    {name[:40]:40s} {mapped_cnt:4d}/{total_cnt:4d} ({pct:.0f}%)")

    print(f"\n  --- EC 号统计 ---")
    rows = conn.execute(
        """
        SELECT ec_numbers, COUNT(*) as cnt
        FROM uniprot_annotations
        WHERE ec_numbers IS NOT NULL AND ec_numbers != ''
        GROUP BY ec_numbers
        ORDER BY cnt DESC
        LIMIT 15
    """
    ).fetchall()
    for ec, cnt in rows:
        print(f"    {str(ec):30s} {cnt} 条")


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Enrich protein annotations from UniProt")
    parser.add_argument("--dry-run", action="store_true", help="Preview only")
    parser.add_argument("--remap", action="store_true", help="Re-run ID mapping (ignore cache)")
    parser.add_argument("--limit", type=int, default=None, help="Process only first N accessions")
    parser.add_argument("--stats", action="store_true", help="Show stats only")
    args = parser.parse_args()

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row

    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=30000")

        download_schema(conn)

        if args.stats:
            show_stats(conn)
            return

        if args.dry_run:
            print("[dry-run] 预览模式 — 不会写入数据库")

        # Get all protein accessions
        accessions = get_all_protein_accessions(conn)
        if args.limit:
            accessions = accessions[:args.limit]

        print(f"蛋白质去重 Accession 总数: {len(accessions)}")

        # Phase 1: ID Mapping
        print(f"\n{'=' * 60}")
        print(f"阶段 1: UniProt ID 映射")
        print(f"{'=' * 60}")
        map_stats = run_id_mapping(conn, accessions, dry_run=args.dry_run, remap=args.remap)

        if not args.dry_run and map_stats.get("details_fetched", 0) > 0:
            conn.commit()

        # Phase 2: Update functional categories
        print(f"\n{'=' * 60}")
        print(f"阶段 2: 更新功能分类")
        print(f"{'=' * 60}")
        update_stats = update_functional_categories(conn, dry_run=args.dry_run)

        if not args.dry_run:
            conn.commit()

        # Print stats
        show_stats(conn)

        # Print map stats
        print(f"\n--- 映射统计 ---")
        for k, v in sorted(map_stats.items()):
            print(f"  {k}: {v}")

        print(f"\n--- 功能分类更新 ---")
        for k, v in sorted(update_stats.items()):
            print(f"  {k}: {v}")

    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
