#!/usr/bin/env python3
"""
Option C v2: Enhanced GenBank coordinate mining with progress bar.

Mines lat_lon, isolation_source, and note from cached GenBank XML files.
"""
from __future__ import annotations

import re
import sqlite3
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path
from datetime import datetime

DB_PATH = Path(r"F:\甲壳动物数据库\crustacean_virus_core.db")
CACHE_DIR = Path(r"F:\甲壳动物数据库\external_data\genbank_metadata")
BACKUP_DIR = Path(r"F:\甲壳动物数据库\backups")


def backup_database() -> Path:
    BACKUP_DIR.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    bp = BACKUP_DIR / f"crustacean_virus_core_before_coords_{stamp}.db"
    shutil.copy2(DB_PATH, bp)
    return bp


def parse_lat_lon(text: str) -> tuple[float, float] | None:
    if not text:
        return None
    pattern = r"([+-]?\d+(?:\.\d+)?)\s*([NS]?)\s*,?\s*([+-]?\d+(?:\.\d+)?)\s*([EW]?)"
    m = re.search(pattern, text.strip())
    if not m:
        return None
    lat = float(m.group(1))
    ns = m.group(2).upper()
    lon = float(m.group(3))
    ew = m.group(4).upper()
    if ns == "S":
        lat = -lat
    if ew == "W":
        lon = -lon
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    return lat, lon


def parse_genbank_xml(xml_path: Path) -> dict[str, str | None]:
    if not xml_path.exists() or xml_path.stat().st_size == 0:
        return {}
    try:
        text = xml_path.read_text(encoding="utf-8", errors="replace")
        root = ET.fromstring(text)
    except ET.ParseError:
        return {}

    result = {"lat_lon": None, "isolation_source": None, "note": None}
    for gbseq in root.findall(".//GBSeq"):
        features = gbseq.find(".//GBSeq_feature-table")
        if features is None:
            continue
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
                    name = name_elem.text.strip() if name_elem.text else ""
                    value = val_elem.text.strip() if val_elem.text else ""
                    if name in result and value:
                        result[name] = value
    return result


def find_all_xml_files() -> list[Path]:
    if not CACHE_DIR.exists():
        return []
    files = []
    for subdir in CACHE_DIR.iterdir():
        if subdir.is_dir():
            files.extend(subdir.glob("*.xml"))
    return sorted(files)


def build_accession_to_isolate_map(conn: sqlite3.Connection) -> dict[str, int]:
    c = conn.cursor()
    mapping = {}
    c.execute("SELECT isolate_id, accession FROM viral_isolates WHERE accession IS NOT NULL")
    for row in c.fetchall():
        iso_id, acc = row
        if acc:
            base = acc.split(".")[0].strip().upper()
            mapping[base] = iso_id
    return mapping


def build_isolate_to_collection_map(conn: sqlite3.Connection) -> dict[int, int]:
    c = conn.cursor()
    mapping = {}
    c.execute("""
        SELECT ir.isolate_id, ir.collection_id
        FROM infection_records ir
        WHERE ir.collection_id IS NOT NULL
    """)
    for row in c.fetchall():
        mapping[row[0]] = row[1]
    return mapping


def safe_update(conn: sqlite3.Connection, sql: str, params: tuple) -> bool:
    try:
        c = conn.cursor()
        c.execute(sql, params)
        return c.rowcount > 0
    except sqlite3.OperationalError:
        return False


def main():
    print("=" * 60)
    print("Option C v2: Enhancing coordinates from GenBank XML cache")
    print("=" * 60)

    xml_files = find_all_xml_files()
    total = len(xml_files)
    print(f"Found {total} cached GenBank XML files")

    if not total:
        print("No cached XML found. Run enrich_isolate_metadata.py first.")
        return

    bp = backup_database()
    print(f"[backup] {bp}")

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 30000")

    acc_map = build_accession_to_isolate_map(conn)
    iso_to_coll = build_isolate_to_collection_map(conn)
    print(f"[map] {len(acc_map)} accessions -> isolate_id")
    print(f"[map] {len(iso_to_coll)} isolates -> collection_id")
    print()

    stats = {
        "xml_processed": 0,
        "lat_lon_parsed": 0,
        "coordinates_updated": 0,
        "isolation_source_updated": 0,
        "notes_updated": 0,
        "no_match": 0,
        "skipped_locked": 0,
    }

    for i, xml_path in enumerate(xml_files, 1):
        stats["xml_processed"] += 1
        acc_base = xml_path.stem.upper()
        isolate_id = acc_map.get(acc_base)
        if not isolate_id:
            stats["no_match"] += 1
            continue

        parsed = parse_genbank_xml(xml_path)
        if not parsed:
            continue

        # Coordinates
        if parsed.get("lat_lon"):
            coords = parse_lat_lon(parsed["lat_lon"])
            if coords:
                stats["lat_lon_parsed"] += 1
                lat, lon = coords
                coll_id = iso_to_coll.get(isolate_id)
                if coll_id:
                    if safe_update(conn, """
                        UPDATE sample_collections
                        SET latitude = ?, longitude = ?, note = COALESCE(note, '') || ' [from GenBank lat_lon]'
                        WHERE collection_id = ? AND latitude IS NULL
                    """, (lat, lon, coll_id)):
                        stats["coordinates_updated"] += 1

        # Isolation source
        if parsed.get("isolation_source"):
            if safe_update(conn, """
                UPDATE infection_records
                SET isolation_source = ?, notes = COALESCE(notes, '') || ' [GenBank: ' || ? || ']'
                WHERE isolate_id = ? AND (isolation_source IS NULL OR isolation_source = '')
            """, (parsed["isolation_source"], parsed["isolation_source"], isolate_id)):
                stats["isolation_source_updated"] += 1

        # Notes
        if parsed.get("note"):
            if safe_update(conn, """
                UPDATE isolate_curated_profiles
                SET notes = COALESCE(notes, '') || ' [GenBank note: ' || substr(?, 1, 200) || '...]'
                WHERE isolate_id = ?
            """, (parsed["note"], isolate_id)):
                stats["notes_updated"] += 1

        # Progress report every 500 files
        if i % 500 == 0:
            pct = i / total * 100
            print(f"  Progress: {i}/{total} ({pct:.1f}%) | coords={stats['coordinates_updated']} | iso_src={stats['isolation_source_updated']} | notes={stats['notes_updated']}")

    conn.commit()
    conn.close()

    print("\n" + "=" * 60)
    print("Results:")
    for k, v in sorted(stats.items()):
        print(f"  {k}: {v}")
    print("=" * 60)


if __name__ == "__main__":
    main()
