"""
Add geography and host-quality control layer.

P2 goals:
- standardize country/continent fields for isolate profiles
- record location quality, missing components, and coordinate confidence
- create a prioritized curation queue so high-value missing host/location/reference
  issues are handled before low-value non-target/noise records
"""

from __future__ import annotations

import shutil
import sqlite3
from datetime import datetime
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "crustacean_virus_core.db"
BACKUP_DIR = BASE_DIR / "backups"


COUNTRY_ALIASES = {
    "USA": "United States",
    "U.S.A.": "United States",
    "US": "United States",
    "Taiwan": "China",
    "Republic of Korea": "South Korea",
    "Korea": "South Korea",
    "Viet Nam": "Vietnam",
}


COUNTRY_TO_CONTINENT = {
    "Argentina": "South America",
    "Australia": "Oceania",
    "Bangladesh": "Asia",
    "Belize": "North America",
    "Brazil": "South America",
    "Canada": "North America",
    "Chile": "South America",
    "China": "Asia",
    "Colombia": "South America",
    "Costa Rica": "North America",
    "Croatia": "Europe",
    "Ecuador": "South America",
    "Egypt": "Africa",
    "Eritrea": "Africa",
    "France": "Europe",
    "India": "Asia",
    "Indonesia": "Asia",
    "Iran": "Asia",
    "Israel": "Asia",
    "Italy": "Europe",
    "Japan": "Asia",
    "Kazakhstan": "Asia",
    "Libya": "Africa",
    "Madagascar": "Africa",
    "Malaysia": "Asia",
    "Mexico": "North America",
    "Mozambique": "Africa",
    "Myanmar": "Asia",
    "Netherlands": "Europe",
    "New Zealand": "Oceania",
    "Panama": "North America",
    "Peru": "South America",
    "Philippines": "Asia",
    "Russia": "Europe/Asia",
    "Saudi Arabia": "Asia",
    "Singapore": "Asia",
    "South Africa": "Africa",
    "South Korea": "Asia",
    "Spain": "Europe",
    "Sri Lanka": "Asia",
    "Thailand": "Asia",
    "Tunisia": "Africa",
    "United Kingdom": "Europe",
    "United States": "North America",
    "Venezuela": "South America",
    "Vietnam": "Asia",
}


HIGH_VALUE_VIRUSES = {
    "White spot syndrome virus": 30,
    "Taura syndrome virus": 24,
    "Yellow head virus": 22,
    "Infectious hypodermal and hematopoietic necrosis virus": 20,
    "Infectious myonecrosis virus": 18,
    "Macrobrachium rosenbergii nodavirus": 16,
    "Decapod iridescent virus": 16,
}


NOISE_VIRUSES = {"Unknown/Unclassified", "Non-crustacean virus", "Human immunodeficiency virus", "African swine fever virus", "SARS-CoV-2"}


def backup_database() -> Path:
    BACKUP_DIR.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = BACKUP_DIR / f"crustacean_virus_core_before_geo_host_qc_{stamp}.db"
    shutil.copy2(DB_PATH, backup_path)
    return backup_path


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        PRAGMA foreign_keys = ON;

        CREATE TABLE IF NOT EXISTS geography_quality_profiles (
            geo_profile_id INTEGER PRIMARY KEY AUTOINCREMENT,
            isolate_id INTEGER NOT NULL UNIQUE,
            collection_id INTEGER,
            raw_country TEXT,
            standardized_country TEXT,
            continent TEXT,
            province_state TEXT,
            city TEXT,
            specific_site TEXT,
            latitude REAL,
            longitude REAL,
            location_precision TEXT,
            coordinate_quality TEXT NOT NULL CHECK (
                coordinate_quality IN ('exact_or_reported', 'centroid_or_inferred', 'missing', 'invalid')
            ),
            location_completeness_score INTEGER NOT NULL,
            missing_components TEXT,
            needs_geocoding INTEGER NOT NULL CHECK (needs_geocoding IN (0, 1)),
            curation_status TEXT NOT NULL DEFAULT 'auto_seeded' CHECK (
                curation_status IN ('auto_seeded', 'needs_review', 'manual_checked', 'rejected')
            ),
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            notes TEXT,
            FOREIGN KEY (isolate_id) REFERENCES viral_isolates(isolate_id),
            FOREIGN KEY (collection_id) REFERENCES sample_collections(collection_id)
        );

        CREATE TABLE IF NOT EXISTS curation_priority_queue (
            queue_id INTEGER PRIMARY KEY AUTOINCREMENT,
            conflict_id INTEGER NOT NULL UNIQUE,
            isolate_id INTEGER,
            accession TEXT,
            canonical_virus_name TEXT,
            field_name TEXT NOT NULL,
            conflict_type TEXT NOT NULL,
            severity TEXT NOT NULL,
            priority_score INTEGER NOT NULL,
            priority_band TEXT NOT NULL CHECK (
                priority_band IN ('P0', 'P1', 'P2', 'P3', 'ignore_candidate')
            ),
            recommended_action TEXT NOT NULL,
            queue_status TEXT NOT NULL DEFAULT 'open' CHECK (
                queue_status IN ('open', 'in_progress', 'resolved', 'ignored')
            ),
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            notes TEXT,
            FOREIGN KEY (conflict_id) REFERENCES curation_conflicts(conflict_id),
            FOREIGN KEY (isolate_id) REFERENCES viral_isolates(isolate_id)
        );

        CREATE INDEX IF NOT EXISTS idx_geo_quality_country
            ON geography_quality_profiles(standardized_country);
        CREATE INDEX IF NOT EXISTS idx_geo_quality_continent
            ON geography_quality_profiles(continent);
        CREATE INDEX IF NOT EXISTS idx_geo_quality_precision
            ON geography_quality_profiles(location_precision);
        CREATE INDEX IF NOT EXISTS idx_geo_quality_needs_geocoding
            ON geography_quality_profiles(needs_geocoding);
        CREATE INDEX IF NOT EXISTS idx_queue_band
            ON curation_priority_queue(priority_band);
        CREATE INDEX IF NOT EXISTS idx_queue_score
            ON curation_priority_queue(priority_score);
        CREATE INDEX IF NOT EXISTS idx_queue_field
            ON curation_priority_queue(field_name);
        """
    )


def standard_country(country: str | None) -> str | None:
    if not country:
        return None
    text = country.strip()
    return COUNTRY_ALIASES.get(text, text)


def coordinate_quality(row: sqlite3.Row) -> str:
    lat, lon = row["latitude"], row["longitude"]
    if lat is None or lon is None:
        return "missing"
    if not (-90 <= float(lat) <= 90 and -180 <= float(lon) <= 180):
        return "invalid"
    if row["location_precision"] in {"country", "province_state"}:
        return "centroid_or_inferred"
    return "exact_or_reported"


def completeness(row: sqlite3.Row, std_country: str | None) -> tuple[int, str]:
    fields = [
        ("country", std_country),
        ("province_state", row["province_state"]),
        ("city", row["city"]),
        ("specific_site", row["specific_site"]),
        ("coordinates", row["latitude"] is not None and row["longitude"] is not None),
        ("collection_year", row["collection_year"]),
    ]
    score = 0
    missing = []
    weights = {
        "country": 25,
        "province_state": 15,
        "city": 15,
        "specific_site": 15,
        "coordinates": 20,
        "collection_year": 10,
    }
    for name, value in fields:
        if value:
            score += weights[name]
        else:
            missing.append(name)
    return score, ",".join(missing)


def seed_geo_profiles(conn: sqlite3.Connection) -> int:
    before = conn.total_changes
    rows = conn.execute(
        """
        SELECT isolate_id, collection_id, country, province_state, city, specific_site,
               latitude, longitude, location_precision, collection_year, continent
        FROM isolate_curated_profiles
        """
    ).fetchall()
    for row in rows:
        std_country = standard_country(row["country"])
        continent = COUNTRY_TO_CONTINENT.get(std_country)
        score, missing = completeness(row, std_country)
        quality = coordinate_quality(row)
        needs_geocoding = 1 if quality == "missing" and std_country else 0
        status = "needs_review" if missing or quality in {"missing", "invalid"} else "auto_seeded"
        conn.execute(
            """
            INSERT INTO geography_quality_profiles
                (
                    isolate_id, collection_id, raw_country, standardized_country,
                    continent, province_state, city, specific_site, latitude,
                    longitude, location_precision, coordinate_quality,
                    location_completeness_score, missing_components,
                    needs_geocoding, curation_status, notes
                )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(isolate_id) DO UPDATE SET
                collection_id = excluded.collection_id,
                raw_country = excluded.raw_country,
                standardized_country = excluded.standardized_country,
                continent = excluded.continent,
                province_state = excluded.province_state,
                city = excluded.city,
                specific_site = excluded.specific_site,
                latitude = excluded.latitude,
                longitude = excluded.longitude,
                location_precision = excluded.location_precision,
                coordinate_quality = excluded.coordinate_quality,
                location_completeness_score = excluded.location_completeness_score,
                missing_components = excluded.missing_components,
                needs_geocoding = excluded.needs_geocoding,
                curation_status = excluded.curation_status,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                row["isolate_id"],
                row["collection_id"],
                row["country"],
                std_country,
                continent,
                row["province_state"],
                row["city"],
                row["specific_site"],
                row["latitude"],
                row["longitude"],
                row["location_precision"],
                quality,
                score,
                missing,
                needs_geocoding,
                status,
                "Seeded from isolate_curated_profiles; geocoding source verification pending.",
            ),
        )

        if std_country != row["country"] or continent != row["continent"]:
            conn.execute(
                """
                UPDATE isolate_curated_profiles
                SET country = COALESCE(?, country),
                    continent = COALESCE(?, continent),
                    updated_at = CURRENT_TIMESTAMP
                WHERE isolate_id = ?
                """,
                (std_country, continent, row["isolate_id"]),
            )
    return conn.total_changes - before


def conflict_priority(row: sqlite3.Row) -> tuple[int, str, str]:
    score = 0
    if row["severity"] == "high":
        score += 40
    elif row["severity"] == "medium":
        score += 25
    else:
        score += 8

    score += HIGH_VALUE_VIRUSES.get(row["canonical_virus_name"], 5)

    if row["field_name"] == "primary_reference_id":
        score += 25
        action = "Find original publication or sequencing paper; link as primary/genome/discovery reference."
    elif row["field_name"] == "host_id":
        score += 22
        action = "Recover host from GenBank source feature or original literature; map to standardized host_id."
    elif row["field_name"] in {"country", "location"}:
        score += 18
        action = "Recover collection geography from literature/GenBank; add five-tier location and coordinates."
    elif row["conflict_type"] == "non_target_or_noise":
        score -= 30
        action = "Review whether this record should be excluded from disease-focused views."
    elif row["conflict_type"] == "taxonomy_mismatch":
        score += 5
        action = "Check ICTV/current taxonomy versus NCBI legacy metadata; keep both with source labels if needed."
    else:
        action = "Manual review."

    if row["canonical_virus_name"] in NOISE_VIRUSES:
        score -= 35

    if row["host_is_target"] == 0:
        score -= 20

    if score >= 75:
        band = "P0"
    elif score >= 55:
        band = "P1"
    elif score >= 30:
        band = "P2"
    elif score >= 10:
        band = "P3"
    else:
        band = "ignore_candidate"
    return score, band, action


def seed_priority_queue(conn: sqlite3.Connection) -> int:
    before = conn.total_changes
    rows = conn.execute(
        """
        SELECT c.conflict_id, c.isolate_id, c.field_name, c.conflict_type, c.severity,
               p.accession, p.canonical_virus_name, p.host_is_target
        FROM curation_conflicts c
        LEFT JOIN isolate_curated_profiles p ON c.isolate_id = p.isolate_id
        WHERE c.status = 'open'
        """
    ).fetchall()
    for row in rows:
        score, band, action = conflict_priority(row)
        conn.execute(
            """
            INSERT INTO curation_priority_queue
                (
                    conflict_id, isolate_id, accession, canonical_virus_name,
                    field_name, conflict_type, severity, priority_score,
                    priority_band, recommended_action, notes
                )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(conflict_id) DO UPDATE SET
                isolate_id = excluded.isolate_id,
                accession = excluded.accession,
                canonical_virus_name = excluded.canonical_virus_name,
                field_name = excluded.field_name,
                conflict_type = excluded.conflict_type,
                severity = excluded.severity,
                priority_score = excluded.priority_score,
                priority_band = excluded.priority_band,
                recommended_action = excluded.recommended_action,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                row["conflict_id"],
                row["isolate_id"],
                row["accession"],
                row["canonical_virus_name"],
                row["field_name"],
                row["conflict_type"],
                row["severity"],
                score,
                band,
                action,
                "Priority score generated from severity, field type, target virus, and target-host status.",
            ),
        )
    return conn.total_changes - before


def log_run(conn: sqlite3.Connection, geo_changes: int, queue_changes: int) -> None:
    source = conn.execute("SELECT source_id FROM external_sources WHERE source_key='local_curation'").fetchone()
    conn.execute(
        """
        INSERT INTO curation_logs
            (entity_type, action, source_id, new_value, confidence, curator, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "geo_host_qc",
            "add_geo_host_qc_layer",
            source["source_id"] if source else None,
            f"geo_changes={geo_changes}; queue_changes={queue_changes}",
            "high",
            "add_geo_host_qc_layer.py",
            "Generated geography quality profiles and prioritized open curation conflicts.",
        ),
    )


def main() -> None:
    backup_path = backup_database()
    print(f"[backup] {backup_path}")
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        ensure_schema(conn)
        geo_changes = seed_geo_profiles(conn)
        queue_changes = seed_priority_queue(conn)
        log_run(conn, geo_changes, queue_changes)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    print(f"[done] geo_changes={geo_changes}")
    print(f"[done] queue_changes={queue_changes}")


if __name__ == "__main__":
    main()
