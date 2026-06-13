#!/usr/bin/env python3
"""
Option C: Enhance sample metadata from cached GenBank XML files.

Mines fields that enrich_isolate_metadata.py did NOT extract:
  - /lat_lon          -> sample_collections.latitude, longitude
  - /isolation_source -> infection_records.isolation_source
  - /note             -> isolate_curated_profiles.notes
  - /lab_host         -> diagnostic context
  - /serotype         -> virulence subtype info

Reads from:
    external_data/genbank_metadata/  (cached XML files)

Updates:
    sample_collections (coordinates)
    infection_records (isolation_source)
    isolate_curated_profiles (notes enrichment)
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
    """Parse GenBank lat_lon format like '25.5 N 120.3 E' or '-25.5 120.3'"""
    if not text:
        return None
    # Pattern: digits with optional decimal, optional direction letters
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
    # Sanity check
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    return lat, lon


def parse_genbank_xml(xml_path: Path) -> dict[str, str | None]:
    """Extract enriched fields from a GenBank XML cache file."""
    if not xml_path.exists() or xml_path.stat().st_size == 0:
        return {}
    try:
        text = xml_path.read_text(encoding="utf-8", errors="replace")
        root = ET.fromstring(text)
    except ET.ParseError:
        return {}

    result: dict[str, str | None] = {
        "lat_lon": None,
        "isolation_source": None,
        "note": None,
        "lab_host": None,
        "serotype": None,
        "strain": None,
        "bioproject": None,
        "biosample": None,
    }

    ns = {}  # GenBank XML has no namespace
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
    """Map accession (without version) -> isolate_id."""
    c = conn.cursor()
    mapping: dict[str, int] = {}
    c.execute("SELECT isolate_id, accession FROM viral_isolates WHERE accession IS NOT NULL")
    for row in c.fetchall():
        iso_id, acc = row
        if acc:
            # Strip version number (e.g., NC_001.1 -> NC_001)
            base = acc.split(".")[0].strip().upper()
            mapping[base] = iso_id
    return mapping


def build_isolate_to_collection_map(conn: sqlite3.Connection) -> dict[int, int]:
    """Map isolate_id -> collection_id via infection_records."""
    c = conn.cursor()
    mapping: dict[int, int] = {}
    c.execute("""
        SELECT ir.isolate_id, ir.collection_id
        FROM infection_records ir
        WHERE ir.collection_id IS NOT NULL
    """)
    for row in c.fetchall():
        mapping[row[0]] = row[1]
    return mapping


def update_coordinates(conn: sqlite3.Connection, collection_id: int, lat: float, lon: float) -> bool:
    if not collection_id:
        return False
    c = conn.cursor()
    # Only update if currently NULL
    c.execute("SELECT latitude, longitude FROM sample_collections WHERE collection_id = ?", (collection_id,))
    row = c.fetchone()
    if not row:
        return False
    existing_lat, existing_lon = row
    if existing_lat is not None and existing_lon is not None:
        return False  # already has coordinates

    c.execute("""
        UPDATE sample_collections
        SET latitude = ?, longitude = ?, note = COALESCE(note, '') || ' [from GenBank lat_lon]'
        WHERE collection_id = ?
    """, (lat, lon, collection_id))
    return c.rowcount > 0


def update_isolation_source(conn: sqlite3.Connection, isolate_id: int, source: str) -> bool:
    if not isolate_id or not source:
        return False
    c = conn.cursor()
    c.execute("""
        UPDATE infection_records
        SET isolation_source = ?, notes = COALESCE(notes, '') || ' [GenBank: ' || ? || ']'
        WHERE isolate_id = ? AND (isolation_source IS NULL OR isolation_source = '')
    """, (source, source, isolate_id))
    return c.rowcount > 0


def update_isolate_notes(conn: sqlite3.Connection, isolate_id: int, note_text: str) -> bool:
    if not isolate_id or not note_text:
        return False
    c = conn.cursor()
    c.execute("""
        UPDATE isolate_curated_profiles
        SET notes = COALESCE(notes, '') || ' [GenBank note: ' || substr(?, 1, 200) || '...]'
        WHERE isolate_id = ?
    """, (note_text, isolate_id))
    return c.rowcount > 0


def main():
    print("=" * 60)
    print("Option C: Enhance coordinates from GenBank XML cache")
    print("=" * 60)

    xml_files = find_all_xml_files()
    print(f"Found {len(xml_files)} cached GenBank XML files")

    if not xml_files:
        print("No cached XML found. Run enrich_isolate_metadata.py first to download GenBank records.")
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

    stats = {
        "xml_processed": 0,
        "lat_lon_parsed": 0,
        "coordinates_updated": 0,
        "isolation_source_updated": 0,
        "notes_updated": 0,
        "no_match": 0,
    }

    for xml_path in xml_files:
        stats["xml_processed"] += 1
        # Extract accession from filename (e.g., "AB123456.xml")
        acc_base = xml_path.stem.upper()
        isolate_id = acc_map.get(acc_base)
        if not isolate_id:
            stats["no_match"] += 1
            continue

        parsed = parse_genbank_xml(xml_path)
        if not parsed:
            continue

        # 1. Coordinates
        if parsed.get("lat_lon"):
            coords = parse_lat_lon(parsed["lat_lon"])
            if coords:
                stats["lat_lon_parsed"] += 1
                lat, lon = coords
                coll_id = iso_to_coll.get(isolate_id)
                try:
                    if coll_id and update_coordinates(conn, coll_id, lat, lon):
                        stats["coordinates_updated"] += 1
                except sqlite3.OperationalError:
                    stats["skipped_locked"] = stats.get("skipped_locked", 0) + 1

        # 2. Isolation source
        if parsed.get("isolation_source"):
            try:
                if update_isolation_source(conn, isolate_id, parsed["isolation_source"]):
                    stats["isolation_source_updated"] += 1
            except sqlite3.OperationalError:
                stats["skipped_locked"] = stats.get("skipped_locked", 0) + 1

        # 3. Notes
        if parsed.get("note"):
            try:
                if update_isolate_notes(conn, isolate_id, parsed["note"]):
                    stats["notes_updated"] += 1
            except sqlite3.OperationalError:
                stats["skipped_locked"] = stats.get("skipped_locked", 0) + 1

    try:
        conn.commit()
    except sqlite3.OperationalError as e:
        if "locked" in str(e).lower():
            print(f"\n[WARNING] Database locked during final commit. Partial results may be lost.")
            conn.rollback()
        else:
            raise
    conn.close()

    print("\n" + "=" * 60)
    print("Results:")
    for k, v in sorted(stats.items()):
        print(f"  {k}: {v}")
    print("=" * 60)
    print("\nDone! Review the updated sample_collections and infection_records.")


if __name__ == "__main__":
    main()
