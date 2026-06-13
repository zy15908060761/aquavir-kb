"""
Fetch and analyze full NCBI Nucleotide records for virus isolates.

Extracts:
  - Genome length, topology (linear/circular)
  - Molecule type (DNA/RNA), strand (ss/ds)
  - Definition line, organism, taxonomy
  - CDS count and feature summary
  - Create/update dates

Usage:
    python enrich_nucleotide.py                          # full run
    python enrich_nucleotide.py --limit 100              # process first N
    python enrich_nucleotide.py --rebuild-cache          # re-fetch all
    python enrich_nucleotide.py --stats                  # coverage stats
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import time
import urllib.request
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any


BASE_DIR = Path(__file__).resolve().parent
DB_PATH = os.environ.get(
    "ENRICH_DB_PATH",
    str(BASE_DIR / "crustacean_virus_core.db"),
)
CACHE_DIR = BASE_DIR / "external_data" / "nucleotide_records"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

NCBI_API_KEY = ""
RATE_LIMIT = 0.35  # seconds between requests (3/sec without API key)

# Accession patterns that are NOT real nucleotide accessions
SKIP_PREFIXES = ("8E", "8EV", "8EW", "XM_", "XR_", "NW_", "NC_", "NT_", "join(", "RDRP_", "COMPLETE_")


def is_real_nucleotide(acc: str | None) -> bool:
    """Check if an accession is a real GenBank nucleotide accession."""
    if not acc or not acc.strip():
        return False
    acc = acc.strip().split(".")[0]
    if acc.startswith(SKIP_PREFIXES):
        return False
    # Standard GenBank: 2+ uppercase letters followed by 5+ digits
    if not re.match(r"^[A-Z]{2}\d{5,}", acc):
        return False
    return True


def cache_path(accession: str) -> Path:
    """Path to cached XML for an accession."""
    sub = accession[:3].lower()
    (CACHE_DIR / sub).mkdir(exist_ok=True)
    return CACHE_DIR / sub / f"{accession}.xml"


# Secondary cache from enrich_isolate_metadata.py
META_CACHE_DIR = BASE_DIR / "external_data" / "genbank_metadata"


def fetch_nucleotide_xml(accession: str, rebuild: bool = False) -> str | None:
    """Fetch GenBank XML, using cache if available."""
    acc = accession.strip().split(".")[0]
    cache_file = cache_path(acc)

    if cache_file.exists() and not rebuild:
        data = cache_file.read_text(encoding="utf-8", errors="replace")
        if data.strip():
            return data
        return None

    url = (
        f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
        f"?db=nucleotide&id={acc}&retmode=xml"
    )
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "crustacean-virus-db-curation/1.0"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = resp.read().decode("utf-8", errors="replace")
        cache_file.write_text(data, encoding="utf-8")
        return data
    except Exception:
        if not cache_file.exists():
            cache_file.write_text("", encoding="utf-8")
        return None


def parse_nucleotide_record(xml_str: str) -> dict[str, Any]:
    """Parse GenBank XML for genome-level metadata."""
    if not xml_str or not xml_str.strip():
        return {}

    try:
        root = ET.fromstring(xml_str)
    except ET.ParseError:
        return {}

    ns = {}  # no namespace

    record: dict[str, Any] = {
        "accession": None,
        "definition": None,
        "organism": None,
        "taxonomy_lineage": None,
        "genome_length": None,
        "topology": None,
        "molecule_type": None,
        "strand": None,
        "cds_count": 0,
        "gene_count": 0,
        "feature_count": 0,
        "create_date": None,
        "update_date": None,
        "taxid": None,
    }

    for gbseq in root.findall(".//GBSeq"):
        # Basic identifiers
        for tag, field in [
            ("GBSeq_primary-accession", "accession"),
            ("GBSeq_definition", "definition"),
            ("GBSeq_create-date", "create_date"),
            ("GBSeq_update-date", "update_date"),
            ("GBSeq_source", "organism"),
            ("GBSeq_taxonomy", "taxonomy_lineage"),
            ("GBSeq_strandedness", "strand"),
            ("GBSeq_topology", "topology"),
            ("GBSeq_moltype", "molecule_type"),
        ]:
            elem = gbseq.find(f".//{tag}")
            if elem is not None and elem.text:
                record[field] = elem.text.strip()

        # Genome length
        length_elem = gbseq.find(".//GBSeq_length")
        if length_elem is not None and length_elem.text:
            record["genome_length"] = int(length_elem.text)

        # Count features
        features = gbseq.find(".//GBSeq_feature-table")
        if features is not None:
            for feature in features.findall("GBFeature"):
                key_elem = feature.find("GBFeature_key")
                if key_elem is not None and key_elem.text:
                    record["feature_count"] += 1
                    if key_elem.text == "CDS":
                        record["cds_count"] += 1
                    elif key_elem.text == "gene":
                        record["gene_count"] += 1

        # Extract taxid from source feature cross-reference
        features = gbseq.find(".//GBSeq_feature-table")
        if features is not None:
            for feature in features.findall("GBFeature"):
                key_elem = feature.find("GBFeature_key")
                if key_elem is None or key_elem.text != "source":
                    continue
                quals = feature.find("GBFeature_quals")
                if quals is None:
                    continue
                for qual in quals.findall("GBQualifier"):
                    name_elem = qual.find("GBQualifier_name")
                    val_elem = qual.find("GBQualifier_value")
                    if name_elem is not None and val_elem is not None:
                        if name_elem.text == "db_xref" and val_elem.text:
                            m = re.search(r"taxon:(\d+)", val_elem.text)
                            if m:
                                record["taxid"] = int(m.group(1))

    return {k: v for k, v in record.items() if v is not None and v != 0}


def download_schema(conn: sqlite3.Connection) -> None:
    """Create nucleotide_records table."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS nucleotide_records (
            record_id INTEGER PRIMARY KEY AUTOINCREMENT,
            isolate_id INTEGER NOT NULL,
            accession TEXT NOT NULL,
            definition TEXT,
            organism TEXT,
            taxonomy_lineage TEXT,
            genome_length INTEGER,
            topology TEXT,
            molecule_type TEXT,
            strand TEXT,
            cds_count INTEGER DEFAULT 0,
            gene_count INTEGER DEFAULT 0,
            feature_count INTEGER DEFAULT 0,
            taxid INTEGER,
            create_date TEXT,
            update_date TEXT,
            fetched_at TEXT,
            FOREIGN KEY (isolate_id) REFERENCES viral_isolates(isolate_id),
            UNIQUE(isolate_id, accession)
        );
        CREATE INDEX IF NOT EXISTS idx_nr_acc ON nucleotide_records(accession);
    """)


def find_isolates(conn: sqlite3.Connection, limit: int | None = None) -> list[dict]:
    """Find isolates pending nucleotide record fetching."""
    query = """
        SELECT vi.isolate_id, vi.accession, vi.virus_name, vm.canonical_name
        FROM viral_isolates vi
        LEFT JOIN virus_master vm ON vi.master_id = vm.master_id
        WHERE vi.accession IS NOT NULL AND TRIM(vi.accession) <> ''
    """
    # Exclude those already fetched
    query += """
        AND vi.isolate_id NOT IN (
            SELECT isolate_id FROM nucleotide_records WHERE fetched_at IS NOT NULL
        )
    """
    query += " ORDER BY vi.isolate_id"
    if limit:
        query += f" LIMIT {limit}"

    rows = conn.execute(query).fetchall()
    return [dict(r) for r in rows]


def get_stats(conn: sqlite3.Connection) -> dict[str, Any]:
    """Get nucleotide coverage stats."""
    stats: dict[str, Any] = {}

    stats["total_isolates"] = conn.execute(
        "SELECT COUNT(*) FROM viral_isolates WHERE accession IS NOT NULL AND TRIM(accession) <> ''"
    ).fetchone()[0]

    stats["records_fetched"] = conn.execute(
        "SELECT COUNT(*) FROM nucleotide_records"
    ).fetchone()[0]

    if stats["records_fetched"] > 0:
        stats["with_topology"] = conn.execute(
            "SELECT COUNT(*) FROM nucleotide_records WHERE topology IS NOT NULL"
        ).fetchone()[0]
        stats["with_strand"] = conn.execute(
            "SELECT COUNT(*) FROM nucleotide_records WHERE strand IS NOT NULL"
        ).fetchone()[0]
        stats["with_molecule_type"] = conn.execute(
            "SELECT COUNT(*) FROM nucleotide_records WHERE molecule_type IS NOT NULL"
        ).fetchone()[0]
        stats["avg_genome_length"] = round(
            conn.execute("SELECT AVG(genome_length) FROM nucleotide_records WHERE genome_length IS NOT NULL").fetchone()[0] or 0
        )
        stats["total_cds"] = conn.execute(
            "SELECT SUM(cds_count) FROM nucleotide_records"
        ).fetchone()[0]

        # Topology distribution
        topo_rows = conn.execute(
            "SELECT topology, COUNT(*) FROM nucleotide_records WHERE topology IS NOT NULL GROUP BY topology"
        ).fetchall()
        stats["topology_distribution"] = {r[0]: r[1] for r in topo_rows}

        # Molecule type distribution
        mol_rows = conn.execute(
            "SELECT molecule_type, COUNT(*) FROM nucleotide_records WHERE molecule_type IS NOT NULL GROUP BY molecule_type"
        ).fetchall()
        stats["molecule_type_distribution"] = {r[0]: r[1] for r in mol_rows}

        # By virus
        virus_rows = conn.execute("""
            SELECT vm.canonical_name, COUNT(DISTINCT nr.isolate_id) as cnt
            FROM nucleotide_records nr
            JOIN viral_isolates vi ON nr.isolate_id = vi.isolate_id
            JOIN virus_master vm ON vi.master_id = vm.master_id
            GROUP BY vm.canonical_name
            ORDER BY cnt DESC LIMIT 15
        """).fetchall()
        stats["by_virus"] = {r[0]: r[1] for r in virus_rows}

        # Genome length distribution
        len_rows = conn.execute("""
            SELECT
                SUM(CASE WHEN genome_length < 5000 THEN 1 ELSE 0 END) as small,
                SUM(CASE WHEN genome_length >= 5000 AND genome_length < 20000 THEN 1 ELSE 0 END) as medium,
                SUM(CASE WHEN genome_length >= 20000 AND genome_length < 100000 THEN 1 ELSE 0 END) as large,
                SUM(CASE WHEN genome_length >= 100000 THEN 1 ELSE 0 END) as very_large
            FROM nucleotide_records WHERE genome_length IS NOT NULL
        """).fetchone()
        stats["genome_length_distribution"] = {
            "small (<5kb)": len_rows[0],
            "medium (5-20kb)": len_rows[1],
            "large (20-100kb)": len_rows[2] or 0,
            "very_large (>=100kb)": len_rows[3] or 0,
        }

    return stats


def enrich(conn: sqlite3.Connection, rebuild_cache: bool = False, limit: int | None = None) -> dict[str, int]:
    """Main enrichment logic."""
    stats = {"processed": 0, "fetched": 0, "cached": 0, "failed": 0, "skipped_accession": 0, "empty_xml": 0}

    isolates = find_isolates(conn, limit=limit)
    if not isolates:
        print("[info] No isolates pending nucleotide fetching.")
        return stats

    print(f"[isolates] {len(isolates)} pending nucleotide fetching")
    stats["total_pending"] = len(isolates)

    COMMIT_INTERVAL = 50
    last_commit = 0

    for i, iso in enumerate(isolates, 1):
        acc = iso["accession"].strip()
        if not is_real_nucleotide(acc):
            stats["skipped_accession"] += 1
            continue

        try:
            acc_clean = acc.split(".")[0]
            cache_file = cache_path(acc_clean)
            using_cache = False

            if cache_file.exists() and not rebuild_cache:
                xml_str = cache_file.read_text(encoding="utf-8", errors="replace")
                if not xml_str.strip():
                    stats["empty_xml"] += 1
                    continue
                stats["cached"] += 1
                using_cache = True
            else:
                # Check secondary cache before fetching
                meta_sub = META_CACHE_DIR / acc_clean[:3].lower()
                meta_file = meta_sub / f"{acc_clean}.xml"
                if meta_file.exists() and not rebuild_cache:
                    xml_str = meta_file.read_text(encoding="utf-8", errors="replace")
                    if xml_str.strip():
                        cache_file.write_text(xml_str, encoding="utf-8")
                        stats["cached"] += 1
                        using_cache = True
                    else:
                        xml_str = None
                else:
                    xml_str = None

            if xml_str is None:
                xml_str = fetch_nucleotide_xml(acc, rebuild=True)
                if xml_str is None:
                    stats["failed"] += 1
                    if i % 25 == 0:
                        print(f"  [{i}/{len(isolates)}] failed: {acc}")
                    time.sleep(RATE_LIMIT)
                    continue
                stats["fetched"] += 1

            if not using_cache:
                time.sleep(RATE_LIMIT)

            record = parse_nucleotide_record(xml_str)
            if not record or not record.get("accession"):
                stats["empty_xml"] += 1
                if i % 50 == 0:
                    print(f"  [{i}/{len(isolates)}] no record: {acc}")
                continue

            # Print progress every 50
            if i % 50 == 0 or i == 1:
                length = record.get("genome_length", "?")
                topo = record.get("topology", "?")
                mol = record.get("molecule_type", "?")
                cds = record.get("cds_count", "?")
                print(f"  [{i}/{len(isolates)}] {acc}: len={length}, {topo}, {mol}, CDS={cds}")

            conn.execute(
                """
                INSERT OR REPLACE INTO nucleotide_records
                    (isolate_id, accession, definition, organism, taxonomy_lineage,
                     genome_length, topology, molecule_type, strand,
                     cds_count, gene_count, feature_count, taxid,
                     create_date, update_date, fetched_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    iso["isolate_id"], acc_clean,
                    record.get("definition"),
                    record.get("organism"),
                    record.get("taxonomy_lineage"),
                    record.get("genome_length"),
                    record.get("topology"),
                    record.get("molecule_type"),
                    record.get("strand"),
                    record.get("cds_count", 0),
                    record.get("gene_count", 0),
                    record.get("feature_count", 0),
                    record.get("taxid"),
                    record.get("create_date"),
                    record.get("update_date"),
                    datetime.now().isoformat(timespec="seconds"),
                ),
            )

            stats["processed"] += 1

            # Periodic commit
            if (i - last_commit) >= COMMIT_INTERVAL:
                conn.commit()
                last_commit = i
                print(f"  [commit] checkpoint at {i}/{len(isolates)}")

        except Exception as exc:
            print(f"  [error] {acc} (isolate_id={iso['isolate_id']}): {exc}")
            stats["failed"] += 1
            continue

    if last_commit < stats["processed"]:
        conn.commit()

    return stats


def print_stats(stats: dict[str, Any]) -> None:
    """Print stats in Chinese."""
    print()
    print("=" * 60)
    print("NCBI Nucleotide 全长分析结果")
    print("=" * 60)

    print(f"\n  总分离株数:              {stats.get('total_isolates', 0)}")
    print(f"  已获取记录:              {stats.get('records_fetched', 0)}")

    if stats.get("records_fetched", 0) > 0:
        print(f"\n【基因组覆盖】")
        print(f"  有拓扑信息:              {stats.get('with_topology', 0)}")
        print(f"  有链型信息:              {stats.get('with_strand', 0)}")
        print(f"  有核酸类型:              {stats.get('with_molecule_type', 0)}")
        print(f"  平均基因组长度:          {stats.get('avg_genome_length', 0):,} bp")
        print(f"  总 CDS 数量:             {stats.get('total_cds', 0):,}")

        print(f"\n【拓扑结构分布】")
        for k, v in stats.get("topology_distribution", {}).items():
            print(f"  {k:15s} {v}")

        print(f"\n【核酸类型分布】")
        for k, v in stats.get("molecule_type_distribution", {}).items():
            print(f"  {k:15s} {v}")

        print(f"\n【基因组长度分布】")
        for k, v in stats.get("genome_length_distribution", {}).items():
            print(f"  {k:20s} {v}")

        print(f"\n【按病毒分布 Top 10】")
        for k, v in list(stats.get("by_virus", {}).items())[:10]:
            print(f"  {k[:45]:45s} {v}")


def export_results(stats: dict[str, Any]) -> Path:
    """Export stats to JSON."""
    out_dir = BASE_DIR / "downloads"
    out_dir.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = out_dir / f"nucleotide_enrich_{stamp}.json"

    data = {
        "script": "enrich_nucleotide.py",
        "stats": {k: v for k, v in sorted(stats.items()) if not k.startswith("_")},
        "completed_at": datetime.now().isoformat(timespec="seconds"),
    }
    out_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_path


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Enrich NCBI Nucleotide records")
    parser.add_argument("--limit", type=int, default=None, help="Process only first N")
    parser.add_argument("--rebuild-cache", action="store_true", help="Re-fetch all")
    parser.add_argument("--stats", action="store_true", help="Show coverage stats only")
    args = parser.parse_args()

    conn = sqlite3.connect(str(DB_PATH), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")

    try:
        download_schema(conn)

        if args.stats:
            s = get_stats(conn)
            print_stats(s)
            return

        print("Starting NCBI Nucleotide full record fetch...")
        print(f"  Rebuild cache: {args.rebuild_cache}")
        print(f"  Limit: {args.limit or 'unlimited'}")

        fetch_stats = enrich(conn, rebuild_cache=args.rebuild_cache, limit=args.limit)

        if fetch_stats.get("processed", 0) > 0:
            export_path = export_results(get_stats(conn))
            print(f"\n[export] Results saved to {export_path}")

        s = get_stats(conn)
        print_stats(s)

    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
