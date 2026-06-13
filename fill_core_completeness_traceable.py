from __future__ import annotations

import csv
import json
import re
import sqlite3
from collections import Counter
from datetime import datetime
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "crustacean_virus_core.db"
REPORT_DIR = BASE_DIR / "reports"


COUNTRY_ALIASES = {
    "usa": "United States",
    "u.s.a.": "United States",
    "united states of america": "United States",
    "viet nam": "Vietnam",
    "korea": "South Korea",
    "republic of korea": "South Korea",
    "pr china": "China",
    "p.r. china": "China",
    "taiwan": "Taiwan",
}


MOL_TYPE_TO_GENOME = {
    "genomic dna": "dsDNA",
    "dna": "DNA",
    "genomic rna": "RNA",
    "rna": "RNA",
    "mrna": "RNA",
    "viral cRNA": "RNA",
}


FAMILY_TO_GENOME = {
    "Nimaviridae": "dsDNA",
    "Iridoviridae": "dsDNA",
    "Malacoherpesviridae": "dsDNA",
    "Nudiviridae": "dsDNA",
    "Baculoviridae": "dsDNA",
    "Parvoviridae": "ssDNA",
    "Picornaviridae": "ssRNA(+)",
    "Dicistroviridae": "ssRNA(+)",
    "Roniviridae": "ssRNA(+)",
    "Nodaviridae": "ssRNA(+)",
    "Rhabdoviridae": "ssRNA(-)",
    "Orthomyxoviridae": "ssRNA(-)",
    "Reoviridae": "dsRNA",
    "Birnaviridae": "dsRNA",
    "Totiviridae": "dsRNA",
}


def norm_blank(value: object) -> str:
    return str(value or "").strip()


def clean_country(value: str) -> str:
    raw = norm_blank(value)
    if not raw:
        return ""
    country = raw.split(":", 1)[0].strip()
    country = re.sub(r"\s+", " ", country)
    return COUNTRY_ALIASES.get(country.lower(), country)


def collection_year(date_text: str) -> str:
    text = norm_blank(date_text)
    m = re.search(r"(19|20)\d{2}", text)
    return m.group(0) if m else ""


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        PRAGMA foreign_keys=ON;

        CREATE TABLE IF NOT EXISTS auto_completeness_fills (
            fill_id INTEGER PRIMARY KEY AUTOINCREMENT,
            entity_type TEXT NOT NULL,
            entity_id INTEGER NOT NULL,
            field_name TEXT NOT NULL,
            old_value TEXT,
            new_value TEXT NOT NULL,
            method TEXT NOT NULL,
            confidence TEXT NOT NULL,
            source_table TEXT,
            source_id TEXT,
            needs_manual_review INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(entity_type, entity_id, field_name, method, new_value)
        );

        CREATE INDEX IF NOT EXISTS idx_auto_fills_entity
            ON auto_completeness_fills(entity_type, entity_id);
        CREATE INDEX IF NOT EXISTS idx_auto_fills_field
            ON auto_completeness_fills(field_name, confidence);
        """
    )


def log_fill(
    conn: sqlite3.Connection,
    entity_type: str,
    entity_id: int,
    field: str,
    old_value: object,
    new_value: object,
    method: str,
    confidence: str,
    source_table: str = "",
    source_id: object = "",
    needs_manual_review: int = 0,
) -> None:
    conn.execute(
        """
        INSERT OR IGNORE INTO auto_completeness_fills
            (entity_type, entity_id, field_name, old_value, new_value, method,
             confidence, source_table, source_id, needs_manual_review)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            entity_type,
            entity_id,
            field,
            norm_blank(old_value),
            norm_blank(new_value),
            method,
            confidence,
            source_table,
            norm_blank(source_id),
            needs_manual_review,
        ),
    )


def fill_genome_type(conn: sqlite3.Connection) -> Counter:
    stats: Counter = Counter()

    rows = conn.execute(
        """
        SELECT vi.isolate_id, vi.genome_type, vi.molecule_type,
               vi.taxon_family, vi.master_id, vm.genome_type AS master_genome_type,
               vm.virus_family
        FROM viral_isolates vi
        LEFT JOIN virus_master vm ON vm.master_id = vi.master_id
        WHERE vi.isolate_id IN (SELECT isolate_id FROM analysis_target_isolates)
          AND (vi.genome_type IS NULL OR TRIM(vi.genome_type) = '')
        """
    ).fetchall()

    for r in rows:
        isolate_id = r["isolate_id"]
        old = r["genome_type"]
        candidate = ""
        method = ""
        confidence = "medium"
        source_table = ""
        source_id = ""

        if norm_blank(r["master_genome_type"]):
            candidate = r["master_genome_type"]
            method = "from_virus_master"
            confidence = "high"
            source_table = "virus_master"
            source_id = r["master_id"]
        else:
            family = norm_blank(r["taxon_family"]) or norm_blank(r["virus_family"])
            if family in FAMILY_TO_GENOME:
                candidate = FAMILY_TO_GENOME[family]
                method = "from_family_rule"
                confidence = "medium"
                source_table = "family_rule"
                source_id = family
            else:
                mol_type = norm_blank(r["molecule_type"]).lower()
                if mol_type in MOL_TYPE_TO_GENOME:
                    candidate = MOL_TYPE_TO_GENOME[mol_type]
                    method = "from_molecule_type"
                    confidence = "medium"
                    source_table = "viral_isolates"
                    source_id = isolate_id

        if not candidate:
            continue

        conn.execute(
            "UPDATE viral_isolates SET genome_type = ? WHERE isolate_id = ?",
            (candidate, isolate_id),
        )
        conn.execute(
            """
            UPDATE isolate_curated_profiles
            SET genome_type = COALESCE(NULLIF(genome_type, ''), ?),
                updated_at = CURRENT_TIMESTAMP,
                notes = COALESCE(notes || '; ', '') || ?
            WHERE isolate_id = ?
            """,
            (candidate, f"auto genome_type {method}: {candidate}", isolate_id),
        )
        log_fill(
            conn,
            "viral_isolate",
            isolate_id,
            "genome_type",
            old,
            candidate,
            method,
            confidence,
            source_table,
            source_id,
            1 if confidence == "medium" else 0,
        )
        stats[method] += 1

    return stats


def build_host_lookup(conn: sqlite3.Connection) -> dict[str, int]:
    lookup: dict[str, int] = {}
    for r in conn.execute("SELECT host_id, scientific_name FROM crustacean_hosts"):
        name = norm_blank(r["scientific_name"]).lower()
        if name:
            lookup[name] = r["host_id"]
    try:
        for r in conn.execute("SELECT host_id, alias FROM host_aliases"):
            alias = norm_blank(r["alias"]).lower()
            if alias and alias not in lookup:
                lookup[alias] = r["host_id"]
    except sqlite3.OperationalError:
        pass
    return lookup


def fill_host(conn: sqlite3.Connection) -> Counter:
    stats: Counter = Counter()
    host_lookup = build_host_lookup(conn)
    rows = conn.execute(
        """
        SELECT vi.isolate_id, vi.accession, icp.host_id, icp.host_scientific_name,
               sm.host_name, sm.organism
        FROM viral_isolates vi
        LEFT JOIN isolate_curated_profiles icp ON icp.isolate_id = vi.isolate_id
        LEFT JOIN sample_metadata sm ON sm.isolate_id = vi.isolate_id
        WHERE vi.isolate_id IN (SELECT isolate_id FROM analysis_target_isolates)
          AND (icp.host_id IS NULL OR icp.host_id = '')
        """
    ).fetchall()

    for r in rows:
        isolate_id = r["isolate_id"]
        raw = norm_blank(r["host_scientific_name"]) or norm_blank(r["host_name"]) or norm_blank(r["organism"])
        if not raw:
            continue

        candidates = [raw.lower()]
        words = raw.replace("_", " ").split()
        if len(words) >= 2:
            candidates.append(" ".join(words[:2]).lower())

        host_id = None
        matched_name = ""
        for candidate in candidates:
            if candidate in host_lookup:
                host_id = host_lookup[candidate]
                matched_name = candidate
                break

        if not host_id:
            for name, hid in host_lookup.items():
                if len(name) >= 6 and name in raw.lower():
                    host_id = hid
                    matched_name = name
                    break

        if not host_id:
            continue

        host = conn.execute(
            "SELECT scientific_name, common_name_cn FROM crustacean_hosts WHERE host_id = ?",
            (host_id,),
        ).fetchone()
        conn.execute(
            """
            UPDATE isolate_curated_profiles
            SET host_id = ?,
                host_scientific_name = COALESCE(NULLIF(host_scientific_name, ''), ?),
                host_common_name_cn = COALESCE(NULLIF(host_common_name_cn, ''), ?),
                host_is_target = COALESCE(host_is_target, 1),
                updated_at = CURRENT_TIMESTAMP,
                notes = COALESCE(notes || '; ', '') || ?
            WHERE isolate_id = ?
            """,
            (
                host_id,
                host["scientific_name"],
                host["common_name_cn"],
                f"auto host exact/alias match from metadata: {raw}",
                isolate_id,
            ),
        )
        log_fill(
            conn,
            "isolate_curated_profile",
            isolate_id,
            "host_id",
            r["host_id"],
            host_id,
            "from_sample_metadata_host_match",
            "high" if matched_name == raw.lower() else "medium",
            "sample_metadata",
            r["accession"],
            0 if matched_name == raw.lower() else 1,
        )
        stats["host_id"] += 1

    return stats


def fill_country(conn: sqlite3.Connection) -> Counter:
    stats: Counter = Counter()
    rows = conn.execute(
        """
        SELECT vi.isolate_id, vi.accession,
               icp.country, icp.collection_year, icp.collection_date,
               sm.geo_loc_name, sm.collection_date
        FROM viral_isolates vi
        LEFT JOIN isolate_curated_profiles icp ON icp.isolate_id = vi.isolate_id
        LEFT JOIN sample_metadata sm ON sm.isolate_id = vi.isolate_id
        WHERE vi.isolate_id IN (SELECT isolate_id FROM analysis_target_isolates)
          AND (
              icp.country IS NULL OR TRIM(icp.country) = ''
              OR icp.collection_year IS NULL OR TRIM(icp.collection_year) = ''
          )
        """
    ).fetchall()

    for r in rows:
        isolate_id = r["isolate_id"]
        country = clean_country(r["geo_loc_name"])
        year = collection_year(r["collection_date"])

        if country and not norm_blank(r["country"]):
            conn.execute(
                """
                UPDATE isolate_curated_profiles
                SET country = ?, location_precision = COALESCE(NULLIF(location_precision, ''), 'country'),
                    coordinates_source = COALESCE(NULLIF(coordinates_source, ''), 'GenBank geo_loc_name'),
                    updated_at = CURRENT_TIMESTAMP,
                    notes = COALESCE(notes || '; ', '') || ?
                WHERE isolate_id = ?
                """,
                (country, f"auto country from sample_metadata.geo_loc_name: {r['geo_loc_name']}", isolate_id),
            )
            log_fill(
                conn,
                "isolate_curated_profile",
                isolate_id,
                "country",
                r["country"],
                country,
                "from_sample_metadata_geo_loc_name",
                "high",
                "sample_metadata",
                r["accession"],
                0,
            )
            stats["country"] += 1

        if year and not norm_blank(r["collection_year"]):
            conn.execute(
                """
                UPDATE isolate_curated_profiles
                SET collection_year = ?, updated_at = CURRENT_TIMESTAMP,
                    notes = COALESCE(notes || '; ', '') || ?
                WHERE isolate_id = ?
                """,
                (year, f"auto collection_year from sample_metadata.collection_date: {r['collection_date']}", isolate_id),
            )
            log_fill(
                conn,
                "isolate_curated_profile",
                isolate_id,
                "collection_year",
                r["collection_year"],
                year,
                "from_sample_metadata_collection_date",
                "high",
                "sample_metadata",
                r["accession"],
                0,
            )
            stats["collection_year"] += 1

    return stats


def export_report(stats: dict[str, Counter]) -> Path:
    REPORT_DIR.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = REPORT_DIR / f"traceable_completeness_fills_{stamp}.json"
    path.write_text(
        json.dumps(
            {
                "generated_at": datetime.now().isoformat(timespec="seconds"),
                "stats": {k: dict(v) for k, v in stats.items()},
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    csv_path = REPORT_DIR / f"traceable_completeness_fills_{stamp}.csv"
    with csv_path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["category", "method_or_field", "count"])
        for category, counter in stats.items():
            for key, count in counter.items():
                writer.writerow([category, key, count])
    return path


def main() -> None:
    conn = sqlite3.connect(DB_PATH, timeout=60)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys=ON")
        ensure_schema(conn)
        stats = {
            "genome_type": fill_genome_type(conn),
            "host": fill_host(conn),
            "country": fill_country(conn),
        }
        conn.commit()
        path = export_report(stats)
        print(json.dumps({k: dict(v) for k, v in stats.items()}, ensure_ascii=False, indent=2))
        print(f"[report] {path}")
        print("integrity", conn.execute("PRAGMA integrity_check").fetchone()[0])
        print("fk", len(conn.execute("PRAGMA foreign_key_check").fetchall()))
    finally:
        conn.close()


if __name__ == "__main__":
    main()
