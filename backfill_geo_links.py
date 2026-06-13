"""
backfill_geo_links.py  —  Backfill geographic data linkage in AquaVir-KB.

Problem
-------
Only 36 of 1,236 public viruses show geographic data through the
sample_collections → infection_records → viral_isolates → virus_master chain,
even though 677 public viruses have country data in geography_quality_profiles.

Root cause
----------
Geography_quality_profiles were created during P0/P1 data ingestion but the
corresponding sample_collections rows were never created for ~1,729 isolates,
breaking the linkage chain. Only GeoBank entries (source_type = 'GenBank source feature')
that already had sample_collections got linked.

Fix
---
For each isolate that has a geography_quality_profile with country data but
lacks a sample_collections link:
  1. Create a sample_collections row from the geo profile data.
  2. Update the geography_quality_profile.collection_id to point to it.
  3. Create or update the infection_record to link isolate → sample_collections.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Ensure we can import db_utils from the project root
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from db_utils import backup_database, db_connection, db_transaction

# ── Helpers ──────────────────────────────────────────────────────────

COUNTRY_TO_CONTINENT: dict[str, str] = {
    "china": "Asia",
    "thailand": "Asia",
    "india": "Asia",
    "viet nam": "Asia",
    "vietnam": "Asia",
    "indonesia": "Asia",
    "japan": "Asia",
    "south korea": "Asia",
    "korea": "Asia",
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
    "ireland": "Europe",
    "serbia": "Europe",
    "croatia": "Europe",
    "czech republic": "Europe",
    "hungary": "Europe",
    "romania": "Europe",
    "russia": "Europe",
    "ukraine": "Europe",
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

# Active entry types (not non_target, host_genome, placeholders)
ACTIVE_TYPES = (
    "complete_genome", "partial_genome", "ictv_vmr",
    "literature_candidate", "palmdb_hit",
    "unclassified_rna_virus", "unconfirmed_candidate",
)


def get_continent(country: str | None) -> str | None:
    if not country:
        return None
    return COUNTRY_TO_CONTINENT.get(country.strip().lower().rstrip("."))


def diagnose(conn) -> dict:
    """Run pre-backfill diagnostics and return summary dict."""
    cur = conn.execute(
        """
        SELECT COUNT(DISTINCT vm.master_id) as total_public
        FROM virus_master vm
        WHERE vm.public_visibility = 'public'
          AND vm.entry_type NOT IN ('non_target','host_genome',
              'duplicate_alias_placeholder','duplicate_ictv_vmr_placeholder')
        """
    )
    total_public = cur.fetchone()[0]

    cur = conn.execute(
        """
        SELECT COUNT(DISTINCT vm.master_id) as with_geo_via_sc
        FROM virus_master vm
        JOIN viral_isolates vi ON vm.master_id = vi.master_id
        JOIN infection_records ir ON vi.isolate_id = ir.isolate_id
        JOIN sample_collections sc ON ir.collection_id = sc.collection_id
        WHERE vm.public_visibility = 'public'
          AND vm.entry_type NOT IN ('non_target','host_genome',
              'duplicate_alias_placeholder','duplicate_ictv_vmr_placeholder')
          AND sc.country IS NOT NULL AND sc.country != ''
        """
    )
    with_sc_link = cur.fetchone()[0]

    cur = conn.execute(
        """
        SELECT COUNT(DISTINCT vm.master_id) as with_geo_via_gqp
        FROM virus_master vm
        JOIN viral_isolates vi ON vm.master_id = vi.master_id
        JOIN geography_quality_profiles gqp ON vi.isolate_id = gqp.isolate_id
        WHERE vm.public_visibility = 'public'
          AND vm.entry_type NOT IN ('non_target','host_genome',
              'duplicate_alias_placeholder','duplicate_ictv_vmr_placeholder')
          AND gqp.standardized_country IS NOT NULL
          AND gqp.standardized_country != ''
        """
    )
    with_gqp = cur.fetchone()[0]

    # Isolates needing work: have geo profile but no sample_collections link
    cur = conn.execute(
        """
        SELECT COUNT(DISTINCT gqp.isolate_id)
        FROM geography_quality_profiles gqp
        JOIN viral_isolates vi ON gqp.isolate_id = vi.isolate_id
        JOIN virus_master vm ON vi.master_id = vm.master_id
        LEFT JOIN infection_records ir
            ON ir.isolate_id = gqp.isolate_id AND ir.collection_id IS NOT NULL
        WHERE vm.public_visibility = 'public'
          AND vm.entry_type NOT IN ('non_target','host_genome',
              'duplicate_alias_placeholder','duplicate_ictv_vmr_placeholder')
          AND gqp.standardized_country IS NOT NULL
          AND gqp.standardized_country != ''
          AND ir.record_id IS NULL
        """
    )
    need_link = cur.fetchone()[0]

    # Distinct countries available in geo profiles (public viruses only)
    cur = conn.execute(
        """
        SELECT COUNT(DISTINCT gqp.standardized_country)
        FROM geography_quality_profiles gqp
        JOIN viral_isolates vi ON gqp.isolate_id = vi.isolate_id
        JOIN virus_master vm ON vi.master_id = vm.master_id
        WHERE vm.public_visibility = 'public'
          AND vm.entry_type NOT IN ('non_target','host_genome',
              'duplicate_alias_placeholder','duplicate_ictv_vmr_placeholder')
          AND gqp.standardized_country IS NOT NULL
          AND gqp.standardized_country != ''
        """
    )
    countries_in_gqp = cur.fetchone()[0]

    result = {
        "total_public_viruses": total_public,
        "with_sample_collections_link": with_sc_link,
        "with_geo_profile": with_gqp,
        "need_link": need_link,
        "countries_available": countries_in_gqp,
    }
    return result


def get_isolates_needing_collections(conn) -> list[sqlite3.Row]:
    """Fetch isolates that need new sample_collections rows created."""
    cur = conn.execute(
        """
        SELECT
            gqp.isolate_id,
            gqp.geo_profile_id,
            gqp.standardized_country AS country,
            gqp.continent,
            gqp.province_state AS province,
            gqp.city,
            gqp.specific_site AS site_name,
            gqp.latitude,
            gqp.longitude,
            gqp.location_precision AS coordinate_precision,
            gqp.coordinate_quality,
            gqp.location_completeness_score,
            gqp.curation_status,
            vi.accession,
            vi.master_id
        FROM geography_quality_profiles gqp
        JOIN viral_isolates vi ON gqp.isolate_id = vi.isolate_id
        JOIN virus_master vm ON vi.master_id = vm.master_id
        WHERE vm.public_visibility = 'public'
          AND vm.entry_type IN ('complete_genome', 'partial_genome', 'ictv_vmr',
              'literature_candidate', 'palmdb_hit',
              'unclassified_rna_virus', 'unconfirmed_candidate')
          AND gqp.standardized_country IS NOT NULL
          AND gqp.standardized_country != ''
          -- Exclude isolates that already have a working chain
          AND gqp.isolate_id NOT IN (
              SELECT ir.isolate_id FROM infection_records ir
              WHERE ir.collection_id IS NOT NULL
          )
        ORDER BY gqp.isolate_id
        """
    )
    return cur.fetchall()


def create_collection(
    conn, iso_row: sqlite3.Row,
) -> int | None:
    """Create a sample_collections row from a geo profile row.
    Returns the new collection_id or None on failure."""
    country = iso_row["country"]
    if not country:
        return None

    continent = iso_row["continent"] or get_continent(country)
    province = iso_row["province"] or ""
    city = iso_row["city"] or ""
    site = iso_row["site_name"] or ""
    lat = iso_row["latitude"]
    lon = iso_row["longitude"]
    coord_precision = iso_row["coordinate_precision"] or "country"
    coord_quality = iso_row["coordinate_quality"] or "manual_curation"
    curation = iso_row["curation_status"] or "auto_seeded"

    cur = conn.execute(
        """
        INSERT INTO sample_collections
            (country, province, city, site_name,
             latitude, longitude, continent,
             coordinate_precision, coordinate_quality,
             collection_year, source_type, note)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            country,
            province if province else None,
            city if city else None,
            site if site else None,
            lat,
            lon,
            continent,
            coord_precision,
            coord_quality,
            None,  # collection_year (rarely available in geo profile)
            "backfill_from_geo_profile",
            f"Auto-created from geography_quality_profile #{iso_row['geo_profile_id']}",
        ),
    )
    return cur.lastrowid


def link_infection_record(
    conn, isolate_id: int, collection_id: int,
) -> None:
    """Create or update infection_record to link isolate → collection."""
    # Check if this isolate already has an infection_record
    cur = conn.execute(
        "SELECT record_id, collection_id FROM infection_records WHERE isolate_id = ?",
        (isolate_id,),
    )
    existing = cur.fetchone()

    if existing:
        if existing["collection_id"] != collection_id:
            conn.execute(
                "UPDATE infection_records SET collection_id = ? WHERE record_id = ?",
                (collection_id, existing["record_id"]),
            )
    else:
        # Create a minimal infection_record for geo-linkage only
        conn.execute(
            """
            INSERT INTO infection_records
                (isolate_id, collection_id, detection_method, host_association_method)
            VALUES (?, ?, 'geographic_inference', 'geographic_inference')
            """,
            (isolate_id, collection_id),
        )


def backfill_geo_links(dry_run: bool = False) -> None:
    """Main backfill logic."""

    print("=" * 72)
    print("  Geographic Data Linkage Backfill  —  AquaVir-KB")
    print("=" * 72)

    # ── Phase 1: Diagnose ────────────────────────────────────────────
    print("\n[Phase 1] Pre-backfill diagnostics...")
    with db_connection(read_only=True) as conn:
        before = diagnose(conn)

    print(f"  Total public viruses:        {before['total_public_viruses']:>5d}")
    print(f"  With sample_collections link:{before['with_sample_collections_link']:>5d}")
    print(f"  With geo profile data:       {before['with_geo_profile']:>5d}")
    print(f"  Needing linkage fix:         {before['need_link']:>5d}")
    print(f"  Countries available:         {before['countries_available']:>5d}")

    if before["need_link"] == 0:
        print("\n  Nothing to do!  All isolates already linked.")
        return

    # ── Phase 2: Backup ──────────────────────────────────────────────
    if not dry_run:
        print("\n[Phase 2] Creating backup...")
        backup_path = backup_database(label="pre_geo_backfill")
        print(f"  Backup at: {backup_path}")
    else:
        print(f"\n[Phase 2] DRY RUN — no backup created.")

    # ── Phase 3: Create collections & link ──────────────────────────
    print(f"\n[Phase 3] {'DRY RUN: ' if dry_run else ''}Creating sample_collections and linking...")

    with db_connection(read_only=True) as diag_conn:
        isolates_needing = get_isolates_needing_collections(diag_conn)
    total = len(isolates_needing)
    print(f"  Found {total} isolates needing new sample_collections rows.")

    new_collections = 0
    updated_ir = 0
    created_ir = 0
    updated_geo_profile = 0
    skipped = 0
    isolates_with_country = {}

    # Track country distribution even in dry run
    for iso in isolates_needing:
        country = iso["country"]
        if country:
            isolates_with_country[country] = isolates_with_country.get(country, 0) + 1

    if not dry_run:
        with db_transaction() as conn:
            for idx, iso in enumerate(isolates_needing, 1):
                isolate_id = iso["isolate_id"]
                country = iso["country"]

                if not country:
                    skipped += 1
                    continue

                # Step 1: Create sample_collections row
                cid = create_collection(conn, iso)
                if cid is None:
                    skipped += 1
                    continue
                new_collections += 1

                # Step 2: Link geography_quality_profile → collection
                conn.execute(
                    "UPDATE geography_quality_profiles SET collection_id = ? WHERE geo_profile_id = ?",
                    (cid, iso["geo_profile_id"]),
                )
                updated_geo_profile += 1

                # Step 3: Link isolate → collection via infection_records
                cur = conn.execute(
                    "SELECT record_id, collection_id FROM infection_records WHERE isolate_id = ?",
                    (isolate_id,),
                )
                existing = cur.fetchone()
                if existing:
                    if existing["collection_id"] != cid:
                        conn.execute(
                            "UPDATE infection_records SET collection_id = ? WHERE record_id = ?",
                            (cid, existing["record_id"]),
                        )
                        updated_ir += 1
                else:
                    conn.execute(
                        """
                        INSERT INTO infection_records
                            (isolate_id, collection_id, detection_method, host_association_method)
                        VALUES (?, ?, 'geographic_inference', 'geographic_inference')
                        """,
                        (isolate_id, cid),
                    )
                    created_ir += 1

                if (idx) % 200 == 0:
                    print(f"    Progress: {idx}/{total} isolates processed...")
        new_collections = sum(1 for iso in isolates_needing if iso["country"])
    else:
        new_collections = len(isolates_needing)

    # In dry run, count how many WOULD be created/updated
    if dry_run:
        with db_connection(read_only=True) as diag_conn:
            isolate_ids = tuple(i["isolate_id"] for i in isolates_needing if i["country"])
            if isolate_ids:
                placeholders = ",".join("?" for _ in isolate_ids)
                cur = diag_conn.execute(
                    f"SELECT isolate_id FROM infection_records "
                    f"WHERE isolate_id IN ({placeholders}) AND collection_id IS NOT NULL",
                    isolate_ids,
                )
                existing_with_cid = set(r[0] for r in cur.fetchall())
                updated_ir = len(existing_with_cid)
            else:
                existing_with_cid = set()

    print(f"\n  Results:")
    print(f"    New sample_collections rows:   {new_collections:>5d}")
    print(f"    Infection records updated:     {updated_ir:>5d}")
    print(f"    Infection records created:     {created_ir:>5d}")
    print(f"    Geo profiles back-linked:      {updated_geo_profile:>5d}")
    print(f"    Skipped (no country):          {skipped:>5d}")

    # ── Phase 4: Post-backfill diagnostics ───────────────────────────
    print(f"\n[Phase 4] {'DRY RUN — ' if dry_run else ''}Post-backfill diagnostics...")
    with db_connection(read_only=True) as conn:
        after = diagnose(conn)

    print(f"  Total public viruses:        {after['total_public_viruses']:>5d}")
    print(f"  With sample_collections link:{after['with_sample_collections_link']:>5d}  "
          f"(+{after['with_sample_collections_link'] - before['with_sample_collections_link']})")
    print(f"  With geo profile data:       {after['with_geo_profile']:>5d}")
    print(f"  Still needing linkage:       {after['need_link']:>5d}")
    print(f"  Countries available:         {after['countries_available']:>5d}")

    # Coverage
    coverage_before = before["with_sample_collections_link"] / max(before["total_public_viruses"], 1) * 100
    coverage_after = after["with_sample_collections_link"] / max(after["total_public_viruses"], 1) * 100
    print(f"\n  Geographic coverage: {coverage_before:.1f}% → {coverage_after:.1f}%")

    # Country distribution top-10
    print(f"\n  Country distribution (top 15):")
    for country, cnt in sorted(isolates_with_country.items(), key=lambda x: -x[1])[:15]:
        print(f"    {country:25s}: {cnt:>4d} isolates")

    print(f"\n{'=' * 72}")
    if dry_run:
        print("  DRY RUN COMPLETE.  Re-run without --dry-run to apply changes.")
    else:
        print("  Backfill complete.  Geographic data linkage restored.")
    print("=" * 72)


if __name__ == "__main__":
    dry_run = "--dry-run" in sys.argv or "-n" in sys.argv
    backfill_geo_links(dry_run=dry_run)
