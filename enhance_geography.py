"""
Enhance geographic data in crustacean virus database.
- Reverse geocode lat/lon to fill province, city
- Add continent field
- Normalize country names
- Use Nominatim API with caching and rate limiting.
"""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

import requests

DB_PATH = Path(r"F:\甲壳动物数据库\crustacean_virus_core.db")
CACHE_PATH = Path(r"F:\甲壳动物数据库\geocode_cache.json")
NOMINATIM_URL = "https://nominatim.openstreetmap.org/reverse"
HEADERS = {"User-Agent": "CrustaceanVirusDB-GeoEnhancer/1.0 (academic research)"}

# Country -> Continent mapping (major ones)
COUNTRY_TO_CONTINENT: dict[str, str] = {
    "china": "Asia",
    "people's republic of china": "Asia",
    "thailand": "Asia",
    "india": "Asia",
    "viet nam": "Asia",
    "vietnam": "Asia",
    "indonesia": "Asia",
    "japan": "Asia",
    "south korea": "Asia",
    "korea": "Asia",
    "republic of korea": "Asia",
    "philippines": "Asia",
    "malaysia": "Asia",
    "bangladesh": "Asia",
    "myanmar": "Asia",
    "taiwan": "Asia",
    "iran": "Asia",
    "israel": "Asia",
    "saudi arabia": "Asia",
    "kuwait": "Asia",
    "united states": "North America",
    "usa": "North America",
    "united states of america": "North America",
    "canada": "North America",
    "mexico": "North America",
    "ecuador": "South America",
    "brazil": "South America",
    "peru": "South America",
    "venezuela": "South America",
    "colombia": "South America",
    "chile": "South America",
    "argentina": "South America",
    "france": "Europe",
    "united kingdom": "Europe",
    "uk": "Europe",
    "germany": "Europe",
    "netherlands": "Europe",
    "italy": "Europe",
    "spain": "Europe",
    "greece": "Europe",
    "norway": "Europe",
    "denmark": "Europe",
    "belgium": "Europe",
    "portugal": "Europe",
    "poland": "Europe",
    "switzerland": "Europe",
    "austria": "Europe",
    "sweden": "Europe",
    "finland": "Europe",
    "australia": "Oceania",
    "new zealand": "Oceania",
    "fiji": "Oceania",
    "papua new guinea": "Oceania",
    "madagascar": "Africa",
    "south africa": "Africa",
    "egypt": "Africa",
    "nigeria": "Africa",
    "kenya": "Africa",
    "tanzania": "Africa",
    "morocco": "Africa",
    "namibia": "Africa",
}


def load_cache() -> dict:
    if CACHE_PATH.exists():
        try:
            return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def save_cache(cache: dict) -> None:
    CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")


def get_continent(country: str | None) -> str | None:
    if not country:
        return None
    lowered = country.strip().lower().rstrip(".")
    return COUNTRY_TO_CONTINENT.get(lowered)


def reverse_geocode(lat: float, lon: float, cache: dict) -> dict | None:
    key = f"{lat:.6f},{lon:.6f}"
    if key in cache:
        return cache[key]

    try:
        resp = requests.get(
            NOMINATIM_URL,
            params={"lat": lat, "lon": lon, "format": "json", "zoom": 10, "addressdetails": 1},
            headers=HEADERS,
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        time.sleep(1.0)  # Nominatim policy: max 1 req/sec
    except Exception as e:
        print(f"    [Error] Nominatim failed for {key}: {e}")
        time.sleep(1.0)
        return None

    addr = data.get("address", {})
    result = {
        "country": addr.get("country", ""),
        "province": addr.get("state", "") or addr.get("province", "") or addr.get("region", ""),
        "city": (
            addr.get("city", "")
            or addr.get("town", "")
            or addr.get("village", "")
            or addr.get("county", "")
        ),
        "display_name": data.get("display_name", ""),
    }
    cache[key] = result
    return result


def add_continent_column(conn: sqlite3.Connection) -> None:
    c = conn.cursor()
    # Check if continent column exists
    c.execute("PRAGMA table_info(sample_collections)")
    cols = [row[1] for row in c.fetchall()]
    if "continent" not in cols:
        c.execute("ALTER TABLE sample_collections ADD COLUMN continent VARCHAR(50)")
        conn.commit()
        print("[DB] Added column: sample_collections.continent")
    if "site_name" not in cols:
        c.execute("ALTER TABLE sample_collections ADD COLUMN site_name VARCHAR(200)")
        conn.commit()
        print("[DB] Added column: sample_collections.site_name")


def enhance_geography() -> None:
    print("=" * 60)
    print("Enhancing Geographic Data (5-tier hierarchy + continent)")
    print("=" * 60)

    cache = load_cache()
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    add_continent_column(conn)

    # Select records with lat/lon but missing province/city
    c.execute(
        """
        SELECT collection_id, country, province, city, latitude, longitude
        FROM sample_collections
        WHERE latitude IS NOT NULL AND longitude IS NOT NULL
          AND (province IS NULL OR province = '' OR city IS NULL OR city = '' OR continent IS NULL)
        """
    )
    rows = c.fetchall()
    print(f"\n[1/3] Found {len(rows)} records needing geographic enhancement via reverse geocoding")

    updated = 0
    skipped = 0
    for i, row in enumerate(rows, 1):
        cid = row["collection_id"]
        lat = row["latitude"]
        lon = row["longitude"]
        if lat is None or lon is None:
            skipped += 1
            continue

        geo = reverse_geocode(lat, lon, cache)
        if not geo:
            skipped += 1
            continue

        # Only overwrite empty fields; keep existing data
        new_province = geo.get("province", "") if not row["province"] else row["province"]
        new_city = geo.get("city", "") if not row["city"] else row["city"]
        country_from_geo = geo.get("country", "")
        new_country = row["country"] or country_from_geo
        new_continent = get_continent(new_country)

        c.execute(
            """
            UPDATE sample_collections
            SET country = COALESCE(NULLIF(?, ''), country),
                province = COALESCE(NULLIF(?, ''), province),
                city = COALESCE(NULLIF(?, ''), city),
                continent = ?
            WHERE collection_id = ?
            """,
            (new_country, new_province, new_city, new_continent, cid),
        )
        updated += 1

        if i % 10 == 0:
            print(f"    Processed {i}/{len(rows)}...")
            save_cache(cache)
            conn.commit()

    conn.commit()
    save_cache(cache)
    print(f"    Updated {updated} records, skipped {skipped}")

    # Step 2: Fill continent for records with country but no continent
    print("\n[2/3] Filling continent for records with country but missing continent...")
    c.execute(
        """
        SELECT collection_id, country FROM sample_collections
        WHERE continent IS NULL AND country IS NOT NULL AND country != ''
        """
    )
    rows2 = c.fetchall()
    updated2 = 0
    for row in rows2:
        continent = get_continent(row["country"])
        if continent:
            c.execute(
                "UPDATE sample_collections SET continent = ? WHERE collection_id = ?",
                (continent, row["collection_id"]),
            )
            updated2 += 1
    conn.commit()
    print(f"    Updated {updated2} records with continent from country mapping")

    # Step 3: Verify stats
    print("\n[3/3] Verification statistics:")
    for col in ["country", "province", "city", "site_name", "latitude", "longitude", "continent"]:
        c.execute(f"SELECT COUNT(*) FROM sample_collections WHERE {col} IS NOT NULL AND {col} != ''")
        has = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM sample_collections")
        total = c.fetchone()[0]
        print(f"    {col:12s}: {has:5d}/{total} ({has/total*100:5.1f}%)")

    # Continent distribution
    print("\n    Continent distribution:")
    c.execute(
        """
        SELECT continent, COUNT(*) as cnt
        FROM sample_collections
        WHERE continent IS NOT NULL AND continent != ''
        GROUP BY continent
        ORDER BY cnt DESC
        """
    )
    for r in c.fetchall():
        print(f"      {r[0] or 'NULL':15s}: {r[1]:4d}")

    conn.close()
    print("\n" + "=" * 60)
    print("Done! Geographic enhancement complete.")
    print("=" * 60)


if __name__ == "__main__":
    enhance_geography()
