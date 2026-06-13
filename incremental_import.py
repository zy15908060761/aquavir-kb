"""
Incremental import from GenBank raw records into the SQLite database.
"""

import sqlite3
from pathlib import Path

from Bio import SeqIO

from genbank_metadata_utils import extract_record_metadata

DB_PATH = Path(r"F:\甲壳动物数据库\crustacean_virus_core.db")
GB_FILE = Path(r"F:\甲壳动物数据库\ncbi_metadata\crustacean_virus_raw.gb")


def normalize_key_part(value):
    if value is None:
        return None
    if isinstance(value, float):
        return round(value, 6)
    text = str(value).strip()
    return text or ""


def build_collection_key(meta):
    return (
        normalize_key_part(meta.get("country")),
        normalize_key_part(meta.get("province")),
        normalize_key_part(meta.get("city")),
        normalize_key_part(meta.get("latitude")),
        normalize_key_part(meta.get("longitude")),
        normalize_key_part(meta.get("collection_year")),
        normalize_key_part(meta.get("collection_date")),
        normalize_key_part(meta.get("source_type")),
        normalize_key_part(meta.get("note")),
    )


def get_or_create_reference(cursor, ref_cache, ref_meta):
    pmid = (ref_meta or {}).get("pmid", "")
    if not pmid:
        return None
    if pmid in ref_cache:
        return ref_cache[pmid]

    cursor.execute("SELECT reference_id FROM ref_literatures WHERE pmid = ?", (pmid,))
    row = cursor.fetchone()
    if row:
        ref_cache[pmid] = row[0]
        return row[0]

    cursor.execute(
        """
        INSERT INTO ref_literatures (pmid, title, authors, journal)
        VALUES (?, ?, ?, ?)
        """,
        (
            pmid,
            ref_meta.get("title") or None,
            ref_meta.get("authors") or None,
            ref_meta.get("journal") or None,
        ),
    )
    ref_cache[pmid] = cursor.lastrowid
    return cursor.lastrowid


def get_or_create_host(cursor, host_cache, host_name, host_cn):
    if not host_name:
        return None
    if host_name in host_cache:
        return host_cache[host_name]

    cursor.execute("SELECT host_id FROM crustacean_hosts WHERE scientific_name = ?", (host_name,))
    row = cursor.fetchone()
    if row:
        host_cache[host_name] = row[0]
        return row[0]

    cursor.execute(
        """
        INSERT INTO crustacean_hosts (scientific_name, common_name_cn)
        VALUES (?, ?)
        """,
        (host_name, host_cn or None),
    )
    host_cache[host_name] = cursor.lastrowid
    return cursor.lastrowid


def get_or_create_collection(cursor, collection_cache, meta):
    has_collection_data = any(
        meta.get(field)
        for field in [
            "country",
            "province",
            "city",
            "latitude",
            "longitude",
            "collection_year",
            "collection_date",
            "source_type",
            "note",
        ]
    )
    if not has_collection_data:
        return None

    key = build_collection_key(meta)
    if key in collection_cache:
        return collection_cache[key]

    cursor.execute(
        """
        INSERT INTO sample_collections
        (country, province, city, latitude, longitude, collection_year, collection_date, source_type, note)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            meta.get("country") or None,
            meta.get("province") or None,
            meta.get("city") or None,
            meta.get("latitude"),
            meta.get("longitude"),
            meta.get("collection_year") or None,
            meta.get("collection_date") or None,
            meta.get("source_type") or None,
            meta.get("note") or meta.get("isolation_source") or None,
        ),
    )
    collection_cache[key] = cursor.lastrowid
    return cursor.lastrowid


def preload_reference_cache(cursor):
    cursor.execute("SELECT pmid, reference_id FROM ref_literatures WHERE pmid IS NOT NULL AND pmid != ''")
    return {str(pmid): reference_id for pmid, reference_id in cursor.fetchall()}


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


def import_new_records():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("SELECT accession FROM viral_isolates")
    existing = {row[0] for row in cursor.fetchall()}
    print(f"Existing records: {len(existing)}")

    ref_cache = preload_reference_cache(cursor)
    host_cache = preload_host_cache(cursor)
    collection_cache = preload_collection_cache(cursor)

    total_in_gb = 0
    new_count = 0
    host_linked = 0
    collection_linked = 0
    reference_linked = 0

    for record in SeqIO.parse(str(GB_FILE), "genbank"):
        total_in_gb += 1
        accession = str(record.id).strip()
        if accession in existing:
            continue

        meta = extract_record_metadata(record)
        reference_id = get_or_create_reference(cursor, ref_cache, meta.get("reference"))
        host_id = get_or_create_host(cursor, host_cache, meta.get("host_name"), meta.get("host_common_name_cn"))
        collection_id = get_or_create_collection(cursor, collection_cache, meta)

        cursor.execute(
            """
            INSERT INTO viral_isolates
            (accession, virus_name, taxon_family, taxon_genus, taxon_species,
             genome_length, genome_type, keywords, reference_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                meta.get("accession"),
                meta.get("virus_name") or None,
                meta.get("taxon_family") or None,
                meta.get("taxon_genus") or None,
                meta.get("taxon_species") or None,
                meta.get("genome_length"),
                meta.get("genome_type") or None,
                meta.get("keywords") or None,
                reference_id,
            ),
        )
        isolate_id = cursor.lastrowid

        cursor.execute(
            """
            INSERT INTO infection_records
            (isolate_id, host_id, collection_id, detection_method, isolation_source, reference_id)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                isolate_id,
                host_id,
                collection_id,
                "GenBank annotation",
                meta.get("isolation_source") or None,
                reference_id,
            ),
        )

        new_count += 1
        host_linked += 1 if host_id else 0
        collection_linked += 1 if collection_id else 0
        reference_linked += 1 if reference_id else 0
        existing.add(accession)

    conn.commit()
    conn.close()

    print(f"GenBank records: {total_in_gb}")
    print(f"New records imported: {new_count}")
    print(f"Host linked: {host_linked}")
    print(f"Collection linked: {collection_linked}")
    print(f"Reference linked: {reference_linked}")
    return new_count


if __name__ == "__main__":
    import_new_records()
