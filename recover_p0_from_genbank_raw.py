"""
Recover high-priority curation gaps from the local GenBank flat file.

This script handles the next prioritized cleanup pass after the IVCDB-inspired
curation layers were added:
- parse host, country/date, isolation source, and PubMed IDs from
  ncbi_metadata/crustacean_virus_raw.gb
- store every prioritized recovery signal in a reviewable candidate table
- automatically apply only conservative matches:
    * primary_reference_id: exactly one GenBank PMID already exists in ref_literatures
    * host_id: GenBank host exactly matches an existing host or verified alias
- export a P0 worklist for manual review

The migration is non-destructive and does not update the original core
infection_records table.
"""

from __future__ import annotations

import re
import shutil
import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pandas as pd
from Bio import SeqIO

from add_geo_host_qc_layer import COUNTRY_TO_CONTINENT, seed_geo_profiles
from genbank_metadata_utils import extract_record_metadata


BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "crustacean_virus_core.db"
GB_PATH = BASE_DIR / "ncbi_metadata" / "crustacean_virus_raw.gb"
BACKUP_DIR = BASE_DIR / "backups"
DOWNLOADS_DIR = BASE_DIR / "downloads"


AUTO_HOST_STATUSES = {"exact", "alias_exact"}
RECOVERY_BANDS = ("P0", "P1", "P2", "P3")


@dataclass(frozen=True)
class GenBankRecord:
    accession: str
    host_raw: str
    host_normalized: str
    geo_raw: str
    country: str
    province: str
    city: str
    collection_date: str
    collection_year: str
    isolation_source: str
    pmids: tuple[str, ...]
    definition: str


def backup_database() -> Path:
    BACKUP_DIR.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = BACKUP_DIR / f"crustacean_virus_core_before_genbank_p0_recovery_{stamp}.db"
    shutil.copy2(DB_PATH, backup_path)
    return backup_path


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        PRAGMA foreign_keys = ON;

        CREATE TABLE IF NOT EXISTS genbank_recovery_candidates (
            candidate_id INTEGER PRIMARY KEY AUTOINCREMENT,
            isolate_id INTEGER NOT NULL,
            accession TEXT NOT NULL,
            priority_band TEXT,
            canonical_virus_name TEXT,
            field_name TEXT NOT NULL,
            candidate_value TEXT NOT NULL,
            source TEXT NOT NULL DEFAULT 'genbank_raw',
            matched_entity_type TEXT,
            matched_entity_id INTEGER,
            match_status TEXT NOT NULL CHECK (
                match_status IN (
                    'exact',
                    'alias_exact',
                    'multiple_reference_pmids',
                    'no_local_reference',
                    'unresolved',
                    'ambiguous',
                    'applied',
                    'not_applicable'
                )
            ),
            confidence TEXT NOT NULL CHECK (
                confidence IN ('high', 'medium', 'low', 'unknown')
            ),
            applied INTEGER NOT NULL DEFAULT 0 CHECK (applied IN (0, 1)),
            raw_context TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            notes TEXT,
            FOREIGN KEY (isolate_id) REFERENCES viral_isolates(isolate_id)
        );

        CREATE UNIQUE INDEX IF NOT EXISTS idx_genbank_recovery_candidate_unique
            ON genbank_recovery_candidates(isolate_id, field_name, candidate_value, matched_entity_type, matched_entity_id);
        CREATE INDEX IF NOT EXISTS idx_genbank_recovery_accession
            ON genbank_recovery_candidates(accession);
        CREATE INDEX IF NOT EXISTS idx_genbank_recovery_field
            ON genbank_recovery_candidates(field_name);
        CREATE INDEX IF NOT EXISTS idx_genbank_recovery_status
            ON genbank_recovery_candidates(match_status);
        """
    )


def normalize_accession(accession: str | None) -> str:
    return (accession or "").strip()


def accession_base(accession: str | None) -> str:
    return normalize_accession(accession).split(".", 1)[0]


def clean_host_text(value: str | None) -> str:
    text = (value or "").strip()
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def parse_pmids(record) -> tuple[str, ...]:
    pmids: list[str] = []
    for ref in record.annotations.get("references", []) or []:
        pmid = str(getattr(ref, "pubmed_id", "") or "").strip()
        if pmid and pmid not in pmids:
            pmids.append(pmid)
    return tuple(pmids)


def parse_genbank_records() -> dict[str, GenBankRecord]:
    records: dict[str, GenBankRecord] = {}
    for record in SeqIO.parse(str(GB_PATH), "genbank"):
        meta = extract_record_metadata(record)
        accession = normalize_accession(record.id)
        gb_record = GenBankRecord(
            accession=accession,
            host_raw=clean_host_text(meta.get("host_raw")),
            host_normalized=clean_host_text(meta.get("host_name")),
            geo_raw=(meta.get("geo_raw") or "").strip(),
            country=(meta.get("country") or "").strip(),
            province=(meta.get("province") or "").strip(),
            city=(meta.get("city") or "").strip(),
            collection_date=(meta.get("collection_date") or "").strip(),
            collection_year=(meta.get("collection_year") or "").strip(),
            isolation_source=(meta.get("isolation_source") or "").strip(),
            pmids=parse_pmids(record),
            definition=(meta.get("definition") or "").strip(),
        )
        records[accession] = gb_record
        records.setdefault(accession_base(accession), gb_record)
    return records


def load_reference_map(conn: sqlite3.Connection) -> dict[str, list[int]]:
    refs: dict[str, list[int]] = defaultdict(list)
    for row in conn.execute(
        """
        SELECT reference_id, pmid
        FROM ref_literatures
        WHERE pmid IS NOT NULL AND TRIM(pmid) <> ''
        """
    ):
        refs[str(row["pmid"]).strip()].append(row["reference_id"])
    return refs


def load_host_maps(conn: sqlite3.Connection) -> tuple[dict[str, list[int]], dict[str, list[int]]]:
    hosts: dict[str, list[int]] = defaultdict(list)
    aliases: dict[str, list[int]] = defaultdict(list)
    for row in conn.execute("SELECT host_id, scientific_name FROM crustacean_hosts"):
        key = clean_host_text(row["scientific_name"]).lower()
        if key:
            hosts[key].append(row["host_id"])
    for row in conn.execute("SELECT host_id, alias FROM host_aliases"):
        key = clean_host_text(row["alias"]).lower()
        if key:
            aliases[key].append(row["host_id"])
    return hosts, aliases


def match_host(
    gb_record: GenBankRecord,
    host_map: dict[str, list[int]],
    alias_map: dict[str, list[int]],
) -> tuple[str, int | None, str, str]:
    candidates = [gb_record.host_raw, gb_record.host_normalized]
    seen: set[str] = set()
    for value in candidates:
        key = clean_host_text(value).lower()
        if not key or key in seen:
            continue
        seen.add(key)
        direct = sorted(set(host_map.get(key, [])))
        if len(direct) == 1:
            return "exact", direct[0], "high", f"host={gb_record.host_raw}; normalized={gb_record.host_normalized}"
        if len(direct) > 1:
            return "ambiguous", None, "low", f"host matched multiple host_id values: {direct}"

        alias = sorted(set(alias_map.get(key, [])))
        if len(alias) == 1:
            return "alias_exact", alias[0], "high", f"host={gb_record.host_raw}; normalized={gb_record.host_normalized}"
        if len(alias) > 1:
            return "ambiguous", None, "low", f"host alias matched multiple host_id values: {alias}"

    if gb_record.host_raw:
        return "unresolved", None, "medium", f"host={gb_record.host_raw}; normalized={gb_record.host_normalized}"
    return "not_applicable", None, "unknown", "No GenBank host qualifier."


def upsert_candidate(
    conn: sqlite3.Connection,
    isolate_id: int,
    accession: str,
    priority_band: str,
    canonical_virus_name: str | None,
    field_name: str,
    candidate_value: str,
    matched_entity_type: str | None,
    matched_entity_id: int | None,
    match_status: str,
    confidence: str,
    raw_context: str,
    notes: str,
    applied: int = 0,
) -> None:
    conn.execute(
        """
        UPDATE genbank_recovery_candidates
        SET
            accession = ?,
            priority_band = ?,
            canonical_virus_name = ?,
            match_status = ?,
            confidence = ?,
            raw_context = ?,
            notes = ?,
            applied = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE isolate_id = ?
          AND field_name = ?
          AND candidate_value = ?
          AND COALESCE(matched_entity_type, '') = COALESCE(?, '')
          AND COALESCE(matched_entity_id, -1) = COALESCE(?, -1)
        """,
        (
            accession,
            priority_band,
            canonical_virus_name,
            match_status,
            confidence,
            raw_context,
            notes,
            applied,
            isolate_id,
            field_name,
            candidate_value,
            matched_entity_type,
            matched_entity_id,
        ),
    )
    if conn.total_changes and conn.execute("SELECT changes()").fetchone()[0] > 0:
        return

    conn.execute(
        """
        INSERT INTO genbank_recovery_candidates
            (
                isolate_id, accession, priority_band, canonical_virus_name,
                field_name, candidate_value, matched_entity_type, matched_entity_id,
                match_status, confidence, raw_context, notes, applied
            )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            isolate_id,
            accession,
            priority_band,
            canonical_virus_name,
            field_name,
            candidate_value,
            matched_entity_type,
            matched_entity_id,
            match_status,
            confidence,
            raw_context,
            notes,
            applied,
        ),
    )


def add_reference_link(conn: sqlite3.Connection, isolate_id: int, reference_id: int) -> None:
    conn.execute(
        """
        INSERT OR IGNORE INTO isolate_reference_links
            (
                isolate_id, reference_id, link_type, source_table,
                source_field, priority, evidence_status, notes
            )
        VALUES (?, ?, 'genbank_reference', 'genbank_recovery_candidates',
                'primary_reference_id', 20, 'auto_seeded',
                'Recovered from local GenBank PUBMED reference.')
        """,
        (isolate_id, reference_id),
    )


def mark_conflict_resolved(conn: sqlite3.Connection, isolate_id: int, field_name: str, note: str) -> None:
    conn.execute(
        """
        UPDATE curation_conflicts
        SET status = 'resolved',
            resolved_at = CURRENT_TIMESTAMP,
            notes = COALESCE(notes || ' | ', '') || ?
        WHERE isolate_id = ?
          AND field_name = ?
          AND status = 'open'
        """,
        (note, isolate_id, field_name),
    )
    conn.execute(
        """
        UPDATE curation_priority_queue
        SET queue_status = 'resolved',
            updated_at = CURRENT_TIMESTAMP,
            notes = COALESCE(notes || ' | ', '') || ?
        WHERE isolate_id = ?
          AND field_name = ?
          AND queue_status = 'open'
        """,
        (note, isolate_id, field_name),
    )


def mark_candidate_found(conn: sqlite3.Connection, isolate_id: int, field_name: str, note: str) -> None:
    conn.execute(
        """
        UPDATE curation_priority_queue
        SET queue_status = 'in_progress',
            updated_at = CURRENT_TIMESTAMP,
            notes = COALESCE(notes || ' | ', '') || ?
        WHERE isolate_id = ?
          AND field_name = ?
          AND queue_status = 'open'
        """,
        (note, isolate_id, field_name),
    )


def update_profile_note(conn: sqlite3.Connection, isolate_id: int, note: str) -> None:
    conn.execute(
        """
        UPDATE isolate_curated_profiles
        SET notes = COALESCE(notes || ' | ', '') || ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE isolate_id = ?
        """,
        (note, isolate_id),
    )


def get_p0_rows(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    placeholders = ", ".join("?" for _ in RECOVERY_BANDS)
    return conn.execute(
        f"""
        SELECT q.queue_id, q.isolate_id, q.accession, q.canonical_virus_name,
               q.field_name, q.priority_band, q.priority_score,
               p.host_id, p.primary_reference_id, p.country,
               p.collection_date, p.sample_source, p.province_state,
               p.city, p.specific_site, p.location_precision
        FROM curation_priority_queue q
        JOIN isolate_curated_profiles p ON p.isolate_id = q.isolate_id
        WHERE q.priority_band IN ({placeholders})
          AND q.queue_status IN ('open', 'in_progress')
        ORDER BY q.priority_score DESC, q.queue_id
        """,
        RECOVERY_BANDS,
    ).fetchall()


def infer_location_precision(country: str, province: str, city: str, site: str) -> str:
    if site:
        return "site"
    if city:
        return "city"
    if province:
        return "province_state"
    if country:
        return "country"
    return "unknown"


def apply_geo_to_profile(conn: sqlite3.Connection, row: sqlite3.Row, gb_record: GenBankRecord) -> bool:
    if not gb_record.country:
        return False

    country = row["country"] or gb_record.country
    province = row["province_state"] or gb_record.province
    city = row["city"] or gb_record.city
    site = row["specific_site"] or gb_record.isolation_source
    precision = infer_location_precision(country, province, city, site)
    continent = COUNTRY_TO_CONTINENT.get(country)

    conn.execute(
        """
        UPDATE isolate_curated_profiles
        SET country = COALESCE(country, ?),
            continent = COALESCE(continent, ?),
            province_state = COALESCE(province_state, NULLIF(?, '')),
            city = COALESCE(city, NULLIF(?, '')),
            specific_site = COALESCE(specific_site, NULLIF(?, '')),
            collection_date = COALESCE(collection_date, NULLIF(?, '')),
            collection_year = COALESCE(collection_year, NULLIF(?, '')),
            sample_source = COALESCE(sample_source, NULLIF(?, '')),
            location_precision = CASE
                WHEN location_precision IS NULL OR location_precision = 'unknown'
                THEN ?
                ELSE location_precision
            END,
            metadata_source_priority = 'mixed_with_conflicts',
            updated_at = CURRENT_TIMESTAMP
        WHERE isolate_id = ?
        """,
        (
            gb_record.country,
            continent,
            gb_record.province,
            gb_record.city,
            gb_record.isolation_source,
            gb_record.collection_date,
            gb_record.collection_year,
            gb_record.isolation_source,
            precision,
            row["isolate_id"],
        ),
    )
    return True


def process_candidates(conn: sqlite3.Connection, gb_records: dict[str, GenBankRecord]) -> dict[str, int]:
    ref_map = load_reference_map(conn)
    host_map, alias_map = load_host_maps(conn)
    stats = defaultdict(int)
    rows = get_p0_rows(conn)

    for row in rows:
        accession = normalize_accession(row["accession"])
        gb_record = gb_records.get(accession) or gb_records.get(accession_base(accession))
        if not gb_record:
            upsert_candidate(
                conn,
                row["isolate_id"],
                accession,
                row["priority_band"],
                row["canonical_virus_name"],
                row["field_name"],
                accession,
                None,
                None,
                "not_applicable",
                "unknown",
                "No matching record in local GenBank flat file.",
                "No GenBank record found for this accession.",
            )
            stats["missing_genbank_record"] += 1
            continue

        if row["field_name"] == "primary_reference_id":
            matched_refs: list[tuple[str, int]] = []
            for pmid in gb_record.pmids:
                ref_ids = ref_map.get(pmid, [])
                if len(ref_ids) == 1:
                    matched_refs.append((pmid, ref_ids[0]))
                    status = "exact"
                    confidence = "high"
                    matched_entity_type = "reference"
                    matched_entity_id = ref_ids[0]
                    note = "PMID exists in ref_literatures."
                elif len(ref_ids) > 1:
                    status = "ambiguous"
                    confidence = "low"
                    matched_entity_type = "reference"
                    matched_entity_id = None
                    note = f"PMID maps to multiple local references: {ref_ids}."
                else:
                    status = "no_local_reference"
                    confidence = "medium"
                    matched_entity_type = "reference"
                    matched_entity_id = None
                    note = "PMID is present in GenBank but missing from ref_literatures."

                upsert_candidate(
                    conn,
                    row["isolate_id"],
                    accession,
                    row["priority_band"],
                    row["canonical_virus_name"],
                    "primary_reference_id",
                    pmid,
                    matched_entity_type,
                    matched_entity_id,
                    status,
                    confidence,
                    f"PUBMED {pmid}; definition={gb_record.definition[:240]}",
                    note,
                )
                stats[f"reference_candidate_{status}"] += 1

            if not gb_record.pmids:
                upsert_candidate(
                    conn,
                    row["isolate_id"],
                    accession,
                    row["priority_band"],
                    row["canonical_virus_name"],
                    "primary_reference_id",
                    "NO_PUBMED_IN_GENBANK_RECORD",
                    None,
                    None,
                    "not_applicable",
                    "unknown",
                    f"definition={gb_record.definition[:240]}",
                    "No PUBMED reference in the local GenBank record.",
                )
                stats["reference_no_pubmed"] += 1

            unique_matched_refs = sorted(set(matched_refs), key=lambda item: gb_record.pmids.index(item[0]))
            if row["primary_reference_id"] is None and len(unique_matched_refs) == 1:
                pmid, reference_id = unique_matched_refs[0]
                conn.execute(
                    """
                    UPDATE isolate_curated_profiles
                    SET primary_reference_id = ?,
                        metadata_source_priority = 'mixed_with_conflicts',
                        curation_status = 'auto_seeded',
                        confidence = 'high',
                        updated_at = CURRENT_TIMESTAMP
                    WHERE isolate_id = ?
                      AND primary_reference_id IS NULL
                    """,
                    (reference_id, row["isolate_id"]),
                )
                add_reference_link(conn, row["isolate_id"], reference_id)
                upsert_candidate(
                    conn,
                    row["isolate_id"],
                    accession,
                    row["priority_band"],
                    row["canonical_virus_name"],
                    "primary_reference_id",
                    pmid,
                    "reference",
                    reference_id,
                    "applied",
                    "high",
                    f"PUBMED {pmid}; definition={gb_record.definition[:240]}",
                    "Applied as primary_reference_id because it was the only locally matched GenBank PMID.",
                    applied=1,
                )
                mark_conflict_resolved(
                    conn,
                    row["isolate_id"],
                    "primary_reference_id",
                    f"Recovered from GenBank PMID {pmid}.",
                )
                stats["primary_reference_applied"] += 1
            elif matched_refs:
                for _pmid, reference_id in set(matched_refs):
                    add_reference_link(conn, row["isolate_id"], reference_id)
                mark_candidate_found(
                    conn,
                    row["isolate_id"],
                    "primary_reference_id",
                    "GenBank PMID candidate found; manual primary-reference selection required.",
                )
                stats["primary_reference_needs_review"] += 1

        elif row["field_name"] == "host_id":
            status, host_id, confidence, context = match_host(gb_record, host_map, alias_map)
            candidate_value = gb_record.host_raw or "NO_HOST_IN_GENBANK_RECORD"
            upsert_candidate(
                conn,
                row["isolate_id"],
                accession,
                row["priority_band"],
                row["canonical_virus_name"],
                "host_id",
                candidate_value,
                "host" if host_id else None,
                host_id,
                status,
                confidence,
                context,
                "Host recovered from GenBank source feature.",
            )
            stats[f"host_candidate_{status}"] += 1

            if row["host_id"] is None and host_id and status in AUTO_HOST_STATUSES:
                conn.execute(
                    """
                    UPDATE isolate_curated_profiles
                    SET host_id = ?,
                        metadata_source_priority = 'mixed_with_conflicts',
                        curation_status = 'auto_seeded',
                        confidence = 'high',
                        updated_at = CURRENT_TIMESTAMP
                    WHERE isolate_id = ?
                      AND host_id IS NULL
                    """,
                    (host_id, row["isolate_id"]),
                )
                upsert_candidate(
                    conn,
                    row["isolate_id"],
                    accession,
                    row["priority_band"],
                    row["canonical_virus_name"],
                    "host_id",
                    candidate_value,
                    "host",
                    host_id,
                    "applied",
                    "high",
                    context,
                    "Applied to isolate_curated_profiles.host_id; original infection_records is unchanged.",
                    applied=1,
                )
                mark_conflict_resolved(
                    conn,
                    row["isolate_id"],
                    "host_id",
                    f"Recovered from GenBank host qualifier: {candidate_value}.",
                )
                stats["host_applied"] += 1
            elif status not in {"not_applicable", "unresolved"}:
                mark_candidate_found(
                    conn,
                    row["isolate_id"],
                    "host_id",
                    "GenBank host candidate found; manual host review required.",
                )
                stats["host_needs_review"] += 1

        if gb_record.country:
            upsert_candidate(
                conn,
                row["isolate_id"],
                accession,
                row["priority_band"],
                row["canonical_virus_name"],
                "country",
                gb_record.country,
                None,
                None,
                "exact",
                "high",
                f"country={gb_record.geo_raw}; collection_date={gb_record.collection_date}",
                "Country parsed from GenBank source country/geo_loc_name qualifier.",
            )
            if not row["country"] or row["field_name"] in {"country", "location"}:
                applied_geo = apply_geo_to_profile(conn, row, gb_record)
                update_profile_note(conn, row["isolate_id"], "Country/date recovered from GenBank source qualifier.")
                if applied_geo:
                    stats["geo_applied"] += 1
                if row["field_name"] == "country":
                    mark_conflict_resolved(
                        conn,
                        row["isolate_id"],
                        "country",
                        f"Recovered country from GenBank geo qualifier: {gb_record.country}.",
                    )
                    stats["country_conflict_resolved"] += 1
                if row["field_name"] == "location":
                    precision = infer_location_precision(
                        gb_record.country,
                        gb_record.province,
                        gb_record.city,
                        gb_record.isolation_source,
                    )
                    mark_conflict_resolved(
                        conn,
                        row["isolate_id"],
                        "location",
                        f"Recovered usable location from GenBank geo qualifier; precision={precision}.",
                    )
                    stats["location_conflict_resolved"] += 1

        if gb_record.isolation_source:
            upsert_candidate(
                conn,
                row["isolate_id"],
                accession,
                row["priority_band"],
                row["canonical_virus_name"],
                "sample_source",
                gb_record.isolation_source,
                None,
                None,
                "exact",
                "medium",
                f"isolation_source={gb_record.isolation_source}",
                "Isolation source parsed from GenBank source feature.",
            )
            if not row["sample_source"]:
                conn.execute(
                    """
                    UPDATE isolate_curated_profiles
                    SET sample_source = ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE isolate_id = ?
                      AND sample_source IS NULL
                    """,
                    (gb_record.isolation_source, row["isolate_id"]),
                )
                stats["sample_source_applied"] += 1

    return dict(stats)


def cleanup_superseded_reference_candidates(conn: sqlite3.Connection) -> int:
    before = conn.total_changes
    conn.execute(
        """
        DELETE FROM genbank_recovery_candidates
        WHERE field_name = 'primary_reference_id'
          AND match_status = 'no_local_reference'
          AND EXISTS (
              SELECT 1
              FROM genbank_recovery_candidates applied
              WHERE applied.isolate_id = genbank_recovery_candidates.isolate_id
                AND applied.field_name = genbank_recovery_candidates.field_name
                AND applied.candidate_value = genbank_recovery_candidates.candidate_value
                AND applied.match_status = 'applied'
                AND applied.applied = 1
          )
        """
    )
    return conn.total_changes - before


def export_worklist(conn: sqlite3.Connection) -> Path:
    DOWNLOADS_DIR.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = DOWNLOADS_DIR / f"priority_genbank_recovery_worklist_{stamp}.xlsx"

    queue_df = pd.read_sql_query(
        """
        SELECT q.queue_id, q.isolate_id, q.accession, q.canonical_virus_name,
               q.field_name, q.priority_score, q.priority_band, q.queue_status,
               p.host_id, h.scientific_name AS current_host,
               p.primary_reference_id, r.pmid AS current_primary_pmid,
               p.country, p.collection_date, p.sample_source, q.notes
        FROM curation_priority_queue q
        JOIN isolate_curated_profiles p ON p.isolate_id = q.isolate_id
        LEFT JOIN crustacean_hosts h ON h.host_id = p.host_id
        LEFT JOIN ref_literatures r ON r.reference_id = p.primary_reference_id
        WHERE q.priority_band IN ('P0', 'P1', 'P2', 'P3')
        ORDER BY q.queue_status, q.priority_score DESC, q.queue_id
        """,
        conn,
    )
    candidates_df = pd.read_sql_query(
        """
        SELECT candidate_id, isolate_id, accession, canonical_virus_name,
               field_name, candidate_value, matched_entity_type, matched_entity_id,
               match_status, confidence, applied, raw_context, notes, updated_at
        FROM genbank_recovery_candidates
        WHERE priority_band IN ('P0', 'P1', 'P2', 'P3')
        ORDER BY applied DESC, field_name, match_status, accession
        """,
        conn,
    )
    summary_df = pd.read_sql_query(
        """
        SELECT field_name, match_status, applied, COUNT(*) AS n
        FROM genbank_recovery_candidates
        WHERE priority_band IN ('P0', 'P1', 'P2', 'P3')
        GROUP BY field_name, match_status, applied
        ORDER BY field_name, applied DESC, match_status
        """,
        conn,
    )

    with pd.ExcelWriter(out_path, engine="openpyxl") as writer:
        summary_df.to_excel(writer, index=False, sheet_name="summary")
        queue_df.to_excel(writer, index=False, sheet_name="p0_queue")
        candidates_df.to_excel(writer, index=False, sheet_name="genbank_candidates")
    return out_path


def log_run(conn: sqlite3.Connection, stats: dict[str, int], worklist_path: Path) -> None:
    source = conn.execute("SELECT source_id FROM external_sources WHERE source_key='local_curation'").fetchone()
    payload = "; ".join(f"{key}={value}" for key, value in sorted(stats.items()))
    conn.execute(
        """
        INSERT INTO curation_logs
            (entity_type, action, source_id, new_value, confidence, curator, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "genbank_recovery",
            "recover_p0_from_genbank_raw",
            source["source_id"] if source else None,
            payload,
            "high",
            "recover_p0_from_genbank_raw.py",
            f"Recovered P0 candidates from local GenBank flat file; worklist={worklist_path}",
        ),
    )


def validate(conn: sqlite3.Connection) -> None:
    quick_check = conn.execute("PRAGMA quick_check").fetchone()[0]
    if quick_check != "ok":
        raise RuntimeError(f"SQLite quick_check failed: {quick_check}")
    fk_errors = conn.execute("PRAGMA foreign_key_check").fetchall()
    if fk_errors:
        raise RuntimeError(f"Foreign key check failed: {fk_errors[:5]}")


def main() -> None:
    if not GB_PATH.exists():
        raise FileNotFoundError(f"GenBank raw file not found: {GB_PATH}")

    backup_path = backup_database()
    print(f"[backup] {backup_path}")
    gb_records = parse_genbank_records()
    print(f"[genbank] parsed_records={len(gb_records)}")

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        ensure_schema(conn)
        stats = process_candidates(conn, gb_records)
        stats["superseded_candidate_cleanup"] = cleanup_superseded_reference_candidates(conn)
        stats["geo_profile_changes"] = seed_geo_profiles(conn)
        worklist_path = export_worklist(conn)
        log_run(conn, stats, worklist_path)
        validate(conn)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    for key, value in sorted(stats.items()):
        print(f"[done] {key}={value}")
    print(f"[done] worklist={worklist_path}")


if __name__ == "__main__":
    main()
