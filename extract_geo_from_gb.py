"""
Backfill host and collection metadata from GenBank source features.
"""

import sqlite3
from collections import Counter

from Bio import SeqIO

from genbank_metadata_utils import extract_record_metadata
from incremental_import import (
    get_or_create_collection,
    get_or_create_host,
    normalize_key_part,
)

DB_PATH = r"F:\甲壳动物数据库\crustacean_virus_core.db"
GB_FILE = r"F:\甲壳动物数据库\ncbi_metadata\crustacean_virus_raw.gb"


def preload_host_cache(cursor):
    cursor.execute("SELECT scientific_name, host_id FROM crustacean_hosts")
    return {scientific_name: host_id for scientific_name, host_id in cursor.fetchall()}


def preload_collection_cache(cursor):
    cursor.execute(
        """
        SELECT collection_id, country, province, city, latitude, longitude,
               collection_year, collection_date, source_type, note
        FROM sample_collections
        """
    )
    cache = {}
    for row in cursor.fetchall():
        key = (
            normalize_key_part(row[1]),
            normalize_key_part(row[2]),
            normalize_key_part(row[3]),
            normalize_key_part(row[4]),
            normalize_key_part(row[5]),
            normalize_key_part(row[6]),
            normalize_key_part(row[7]),
            normalize_key_part(row[8]),
            normalize_key_part(row[9]),
        )
        cache[key] = row[0]
    return cache


def remove_orphan_collections(cursor):
    cursor.execute(
        """
        DELETE FROM sample_collections
        WHERE collection_id NOT IN (
            SELECT DISTINCT collection_id
            FROM infection_records
            WHERE collection_id IS NOT NULL
        )
        """
    )
    return cursor.rowcount


def main():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    host_cache = preload_host_cache(cursor)
    collection_cache = preload_collection_cache(cursor)

    print("Backfilling metadata from GenBank...")
    total = 0
    host_updates = 0
    collection_links = 0
    collection_relinks = 0
    country_counts = Counter()

    for record in SeqIO.parse(GB_FILE, "genbank"):
        total += 1
        accession = str(record.id).strip()
        meta = extract_record_metadata(record)

        cursor.execute(
            """
            SELECT ir.record_id, ir.host_id, ir.collection_id, ir.detection_method
            FROM viral_isolates v
            JOIN infection_records ir ON v.isolate_id = ir.isolate_id
            WHERE v.accession = ?
            """,
            (accession,),
        )
        rows = cursor.fetchall()
        if not rows:
            continue

        new_host_id = get_or_create_host(cursor, host_cache, meta.get("host_name"), meta.get("host_common_name_cn"))
        new_collection_id = get_or_create_collection(cursor, collection_cache, meta)

        for record_id, host_id, collection_id, detection_method in rows:
            can_override_host = detection_method == "GenBank annotation"
            if new_host_id and (host_id is None or can_override_host):
                cursor.execute(
                    "UPDATE infection_records SET host_id = ? WHERE record_id = ?",
                    (new_host_id, record_id),
                )
                if cursor.rowcount > 0:
                    host_updates += cursor.rowcount

            if new_collection_id and collection_id != new_collection_id:
                cursor.execute(
                    "UPDATE infection_records SET collection_id = ? WHERE record_id = ?",
                    (new_collection_id, record_id),
                )
                if cursor.rowcount > 0:
                    if collection_id is None:
                        collection_links += cursor.rowcount
                    else:
                        collection_relinks += cursor.rowcount

            if meta.get("country"):
                country_counts[meta["country"]] += 1

        if total % 500 == 0:
            print(
                f"  Processed {total}, host updates {host_updates}, "
                f"new collection links {collection_links}, collection relinks {collection_relinks}"
            )

    removed_orphans = remove_orphan_collections(cursor)

    conn.commit()
    conn.close()

    print(f"\nTotal records scanned: {total}")
    print(f"Host updates: {host_updates}")
    print(f"New collection links: {collection_links}")
    print(f"Collection relinks: {collection_relinks}")
    print(f"Removed orphan collections: {removed_orphans}")
    print("Country coverage from GenBank source:")
    for country, count in country_counts.most_common(15):
        print(f"  {country}: {count}")


if __name__ == "__main__":
    main()
