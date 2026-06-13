"""
Import ICTV Master Species List taxonomy and map it to local virus_master rows.

Default source:
ICTV_Master_Species_List_2025_MSL41.v1.xlsx

The script is repeatable:
- ICTV rows are upserted into ictv_taxonomy
- mappings are regenerated only when a better match is found
- local core NCBI-derived tables are not overwritten
"""

from __future__ import annotations

import hashlib
import re
import shutil
import sqlite3
import urllib.request
from datetime import datetime
from pathlib import Path

import pandas as pd


BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "crustacean_virus_core.db"
DATA_DIR = BASE_DIR / "external_data" / "ictv"
BACKUP_DIR = BASE_DIR / "backups"

MSL_VERSION = "MSL41"
RELEASE_YEAR = "2025"
MSL_FILENAME = "ICTV_Master_Species_List_2025_MSL41.v1.xlsx"
MSL_URL = (
    "https://zenodo.org/records/19154110/files/"
    "ICTV_Master_Species_List_2025_MSL41.v1.xlsx?download=1"
)


RANK_COLUMNS = [
    "realm",
    "subrealm",
    "kingdom",
    "subkingdom",
    "phylum",
    "subphylum",
    "class",
    "subclass",
    "order_name",
    "suborder",
    "family",
    "subfamily",
    "genus",
    "subgenus",
    "species",
]


def backup_database() -> Path:
    BACKUP_DIR.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = BACKUP_DIR / f"crustacean_virus_core_before_ictv_import_{stamp}.db"
    shutil.copy2(DB_PATH, backup_path)
    return backup_path


def download_msl(force: bool = False) -> Path:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    target = DATA_DIR / MSL_FILENAME
    if target.exists() and not force:
        return target

    request = urllib.request.Request(
        MSL_URL,
        headers={"User-Agent": "crustacean-virus-db/1.0"},
    )
    with urllib.request.urlopen(request, timeout=180) as response:
        content = response.read()
    target.write_bytes(content)
    return target


def normalize_header(value: object) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"[^a-z0-9]+", "_", text).strip("_")
    return text


def normalize_name(value: object) -> str:
    text = str(value or "").strip().lower()
    text = text.replace("\u2010", "-").replace("\u2011", "-").replace("\u2013", "-").replace("\u2014", "-")
    text = re.sub(r"\([^)]*\)", " ", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def clean_text(value: object) -> str | None:
    if pd.isna(value):
        return None
    text = str(value).strip()
    if not text or text.lower() == "nan":
        return None
    return text


def row_hash(values: list[object]) -> str:
    joined = "\x1f".join("" if v is None else str(v) for v in values)
    return hashlib.sha1(joined.encode("utf-8")).hexdigest()


def find_sheet(path: Path) -> str | int:
    xls = pd.ExcelFile(path)
    for name in xls.sheet_names:
        lowered = name.lower()
        if "msl" in lowered or "species" in lowered:
            return name
    return 0


def read_msl(path: Path) -> pd.DataFrame:
    sheet = find_sheet(path)
    raw = pd.read_excel(path, sheet_name=sheet)
    raw.columns = [normalize_header(c) for c in raw.columns]

    aliases = {
        "order": "order_name",
        "ictv_id": "official_ictv_id",
        "genome": "genome_composition",
        "virus_name_s": "virus_names",
        "virus_name": "virus_names",
        "virus_names": "virus_names",
        "virus_name_abbreviation_s": "virus_abbreviations",
        "virus_name_abbreviations": "virus_abbreviations",
        "virus_abbreviation_s": "virus_abbreviations",
        "virus_abbreviations": "virus_abbreviations",
        "isolate": "virus_isolate",
    }
    raw = raw.rename(columns={col: aliases.get(col, col) for col in raw.columns})

    for col in RANK_COLUMNS + ["official_ictv_id", "virus_names", "virus_abbreviations", "genome_composition"]:
        if col not in raw.columns:
            raw[col] = None

    rows = []
    for _, source in raw.iterrows():
        species = clean_text(source.get("species"))
        if not species:
            continue
        record = {col: clean_text(source.get(col)) for col in RANK_COLUMNS}
        record["official_ictv_id"] = clean_text(source.get("official_ictv_id"))
        record["virus_names"] = clean_text(source.get("virus_names"))
        record["virus_abbreviations"] = clean_text(source.get("virus_abbreviations"))
        record["genome_composition"] = clean_text(source.get("genome_composition"))
        record["row_hash"] = row_hash([record.get(col) for col in RANK_COLUMNS + ["virus_names", "virus_abbreviations"]])
        rows.append(record)
    return pd.DataFrame(rows)


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        PRAGMA foreign_keys = ON;

        CREATE TABLE IF NOT EXISTS ictv_taxonomy (
            ictv_id INTEGER PRIMARY KEY AUTOINCREMENT,
            msl_version TEXT NOT NULL,
            release_year TEXT NOT NULL,
            realm TEXT,
            subrealm TEXT,
            kingdom TEXT,
            subkingdom TEXT,
            phylum TEXT,
            subphylum TEXT,
            class TEXT,
            subclass TEXT,
            order_name TEXT,
            suborder TEXT,
            family TEXT,
            subfamily TEXT,
            genus TEXT,
            subgenus TEXT,
            species TEXT NOT NULL,
            official_ictv_id TEXT,
            virus_names TEXT,
            virus_abbreviations TEXT,
            genome_composition TEXT,
            row_hash TEXT NOT NULL,
            source_file TEXT,
            imported_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (msl_version, row_hash)
        );

        CREATE TABLE IF NOT EXISTS virus_ictv_mappings (
            mapping_id INTEGER PRIMARY KEY AUTOINCREMENT,
            master_id INTEGER NOT NULL,
            ictv_id INTEGER NOT NULL,
            match_type TEXT NOT NULL CHECK (
                match_type IN ('species_exact', 'virus_name_exact', 'abbreviation_exact', 'raw_name_exact', 'normalized_exact')
            ),
            matched_value TEXT NOT NULL,
            match_status TEXT NOT NULL DEFAULT 'auto_matched' CHECK (
                match_status IN ('auto_matched', 'manual_checked', 'rejected')
            ),
            confidence TEXT NOT NULL DEFAULT 'high' CHECK (
                confidence IN ('high', 'medium', 'low', 'unknown')
            ),
            source_id INTEGER,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            notes TEXT,
            FOREIGN KEY (master_id) REFERENCES virus_master(master_id),
            FOREIGN KEY (ictv_id) REFERENCES ictv_taxonomy(ictv_id),
            FOREIGN KEY (source_id) REFERENCES external_sources(source_id),
            UNIQUE (master_id, ictv_id, match_type, matched_value)
        );

        CREATE INDEX IF NOT EXISTS idx_ictv_species ON ictv_taxonomy(species);
        CREATE INDEX IF NOT EXISTS idx_ictv_family ON ictv_taxonomy(family);
        CREATE INDEX IF NOT EXISTS idx_ictv_genus ON ictv_taxonomy(genus);
        CREATE INDEX IF NOT EXISTS idx_vim_master ON virus_ictv_mappings(master_id);
        CREATE INDEX IF NOT EXISTS idx_vim_ictv ON virus_ictv_mappings(ictv_id);
        """
    )
    ensure_column(conn, "ictv_taxonomy", "official_ictv_id", "TEXT")


def ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def ensure_ictv_source(conn: sqlite3.Connection) -> int:
    conn.execute(
        """
        INSERT INTO external_sources
            (source_key, name, category, base_url, description, update_policy, priority)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(source_key) DO UPDATE SET
            name = excluded.name,
            category = excluded.category,
            base_url = excluded.base_url,
            description = excluded.description,
            update_policy = excluded.update_policy,
            priority = excluded.priority,
            updated_at = CURRENT_TIMESTAMP
        """,
        (
            "ictv",
            "ICTV",
            "virus_taxonomy",
            "https://ictv.global/",
            "Official virus taxonomy, species names, and higher ranks.",
            f"{MSL_VERSION} {RELEASE_YEAR} release file",
            30,
        ),
    )
    return conn.execute("SELECT source_id FROM external_sources WHERE source_key = 'ictv'").fetchone()["source_id"]


def import_taxonomy(conn: sqlite3.Connection, df: pd.DataFrame, source_file: Path) -> int:
    before = conn.total_changes
    records = []
    for _, row in df.iterrows():
        records.append(
            (
                MSL_VERSION,
                RELEASE_YEAR,
                row.get("realm"),
                row.get("subrealm"),
                row.get("kingdom"),
                row.get("subkingdom"),
                row.get("phylum"),
                row.get("subphylum"),
                row.get("class"),
                row.get("subclass"),
                row.get("order_name"),
                row.get("suborder"),
                row.get("family"),
                row.get("subfamily"),
                row.get("genus"),
                row.get("subgenus"),
                row.get("species"),
                row.get("official_ictv_id"),
                row.get("virus_names"),
                row.get("virus_abbreviations"),
                row.get("genome_composition"),
                row.get("row_hash"),
                str(source_file.name),
            )
        )

    conn.executemany(
        """
        INSERT INTO ictv_taxonomy
            (
                msl_version, release_year, realm, subrealm, kingdom, subkingdom,
                phylum, subphylum, class, subclass, order_name, suborder,
                family, subfamily, genus, subgenus, species, official_ictv_id, virus_names,
                virus_abbreviations, genome_composition, row_hash, source_file
            )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(msl_version, row_hash) DO UPDATE SET
            realm = excluded.realm,
            subrealm = excluded.subrealm,
            kingdom = excluded.kingdom,
            subkingdom = excluded.subkingdom,
            phylum = excluded.phylum,
            subphylum = excluded.subphylum,
            class = excluded.class,
            subclass = excluded.class,
            order_name = excluded.order_name,
            suborder = excluded.suborder,
            family = excluded.family,
            subfamily = excluded.subfamily,
            genus = excluded.genus,
            subgenus = excluded.subgenus,
            species = excluded.species,
            official_ictv_id = excluded.official_ictv_id,
            virus_names = excluded.virus_names,
            virus_abbreviations = excluded.virus_abbreviations,
            genome_composition = excluded.genome_composition,
            source_file = excluded.source_file,
            imported_at = CURRENT_TIMESTAMP
        """,
        records,
    )
    return conn.total_changes - before


def split_names(value: str | None) -> list[str]:
    if not value:
        return []
    parts = re.split(r"[;,/|]+", value)
    cleaned = []
    for part in parts:
        text = part.strip()
        if text:
            cleaned.append(text)
    return cleaned


def build_ictv_lookup(conn: sqlite3.Connection) -> dict[str, list[tuple[int, str, str]]]:
    lookup: dict[str, list[tuple[int, str, str]]] = {}
    rows = conn.execute(
        """
        SELECT ictv_id, species, virus_names, virus_abbreviations
        FROM ictv_taxonomy
        WHERE msl_version = ?
        """,
        (MSL_VERSION,),
    ).fetchall()
    for row in rows:
        candidates = [(row["species"], "species_exact")]
        candidates += [(name, "virus_name_exact") for name in split_names(row["virus_names"])]
        candidates += [(abbr, "abbreviation_exact") for abbr in split_names(row["virus_abbreviations"])]
        for value, match_type in candidates:
            key = normalize_name(value)
            if not key:
                continue
            lookup.setdefault(key, []).append((row["ictv_id"], match_type, value))
    return lookup


def local_candidates(conn: sqlite3.Connection) -> dict[int, list[tuple[str, str]]]:
    candidates: dict[int, list[tuple[str, str]]] = {}
    for row in conn.execute(
        """
        SELECT master_id, canonical_name, abbreviations
        FROM virus_master
        WHERE canonical_name IS NOT NULL AND TRIM(canonical_name) <> ''
        """
    ):
        candidates.setdefault(row["master_id"], []).append((row["canonical_name"], "normalized_exact"))
        for abbr in split_names(row["abbreviations"]):
            candidates[row["master_id"]].append((abbr, "abbreviation_exact"))

    if table_exists(conn, "virus_aliases"):
        for row in conn.execute(
            """
            SELECT master_id, alias, alias_type
            FROM virus_aliases
            WHERE alias IS NOT NULL AND TRIM(alias) <> ''
              AND match_status <> 'rejected'
            """
        ):
            match_type = "abbreviation_exact" if row["alias_type"] == "abbreviation" else "normalized_exact"
            candidates.setdefault(row["master_id"], []).append((row["alias"], match_type))

    for row in conn.execute(
        """
        SELECT DISTINCT master_id, virus_name
        FROM viral_isolates
        WHERE master_id IS NOT NULL
          AND virus_name IS NOT NULL
          AND TRIM(virus_name) <> ''
        """
    ):
        candidates.setdefault(row["master_id"], []).append((row["virus_name"], "raw_name_exact"))

    nonspecific_species = {"viruses", "viruses incertae sedis"}
    for row in conn.execute(
        """
        SELECT DISTINCT master_id, taxon_species
        FROM viral_isolates
        WHERE master_id IS NOT NULL
          AND taxon_species IS NOT NULL
          AND TRIM(taxon_species) <> ''
        """
    ):
        taxon_species = row["taxon_species"].strip()
        if normalize_name(taxon_species) in nonspecific_species:
            continue
        candidates.setdefault(row["master_id"], []).append((taxon_species, "species_exact"))

    return candidates


def table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (name,),
    ).fetchone()
    return row is not None


def insert_mapping_xref(
    conn: sqlite3.Connection,
    master_id: int,
    ictv_id: int,
    source_id: int,
    external_id: str,
    notes: str,
) -> None:
    conn.execute(
        """
        INSERT OR IGNORE INTO external_xrefs
            (
                entity_type, entity_id, source_id, external_id, external_url,
                match_status, confidence, matched_by, notes
            )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "virus_master",
            master_id,
            source_id,
            external_id,
            "https://ictv.global/taxonomy",
            "exact",
            "high",
            "import_ictv_msl.py",
            notes,
        ),
    )


def map_local_viruses(conn: sqlite3.Connection, source_id: int) -> int:
    before = conn.total_changes
    lookup = build_ictv_lookup(conn)
    candidates = local_candidates(conn)

    inserted_pairs = set()
    for master_id, values in candidates.items():
        for value, local_type in values:
            key = normalize_name(value)
            if not key or key not in lookup:
                continue
            for ictv_id, ictv_match_type, ictv_value in lookup[key]:
                match_type = ictv_match_type if ictv_match_type != "virus_name_exact" else local_type
                if match_type == "normalized_exact":
                    match_type = "virus_name_exact"
                pair_key = (master_id, ictv_id, match_type, value)
                if pair_key in inserted_pairs:
                    continue
                inserted_pairs.add(pair_key)
                conn.execute(
                    """
                    INSERT OR IGNORE INTO virus_ictv_mappings
                        (master_id, ictv_id, match_type, matched_value, confidence, source_id, notes)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        master_id,
                        ictv_id,
                        match_type,
                        value,
                        "high",
                        source_id,
                        f"Matched local value to ICTV value: {ictv_value}",
                    ),
                )
                ictv_row = conn.execute(
                    "SELECT species, official_ictv_id FROM ictv_taxonomy WHERE ictv_id = ?",
                    (ictv_id,),
                ).fetchone()
                species = ictv_row["species"]
                external_id = ictv_row["official_ictv_id"] or species
                insert_mapping_xref(
                    conn,
                    master_id,
                    ictv_id,
                    source_id,
                    external_id,
                    f"Mapped to ICTV {MSL_VERSION} species={species} by {match_type}: {value}",
                )
    return conn.total_changes - before


def reject_bucket_mappings(conn: sqlite3.Connection) -> int:
    before = conn.total_changes
    conn.execute(
        """
        UPDATE virus_ictv_mappings
        SET match_status = 'rejected',
            notes = COALESCE(notes, '') || CASE
                WHEN notes IS NULL OR notes = '' THEN ''
                ELSE '; '
            END || 'Rejected automatically: bucket master record is not a concrete ICTV species.'
        WHERE master_id IN (
            SELECT master_id
            FROM virus_master
            WHERE canonical_name IN ('Unknown/Unclassified', 'Non-crustacean virus')
        )
          AND match_status <> 'rejected'
        """
    )
    conn.execute(
        """
        UPDATE external_xrefs
        SET match_status = 'rejected',
            confidence = 'low',
            notes = COALESCE(notes, '') || CASE
                WHEN notes IS NULL OR notes = '' THEN ''
                ELSE '; '
            END || 'Rejected automatically: bucket master record is not a concrete ICTV species.'
        WHERE entity_type = 'virus_master'
          AND source_id = (SELECT source_id FROM external_sources WHERE source_key = 'ictv')
          AND entity_id IN (
              SELECT master_id
              FROM virus_master
              WHERE canonical_name IN ('Unknown/Unclassified', 'Non-crustacean virus')
          )
          AND match_status <> 'rejected'
        """
    )
    return conn.total_changes - before


def update_virus_master_taxonomy(conn: sqlite3.Connection) -> int:
    before = conn.total_changes
    eligible = conn.execute(
        """
        SELECT vm.master_id,
               MIN(it.family) AS family,
               MIN(it.genus) AS genus,
               COUNT(DISTINCT it.ictv_id) AS species_count,
               COUNT(DISTINCT COALESCE(it.family, '')) AS family_count,
               COUNT(DISTINCT COALESCE(it.genus, '')) AS genus_count
        FROM virus_master vm
        JOIN virus_ictv_mappings vim ON vm.master_id = vim.master_id
        JOIN ictv_taxonomy it ON vim.ictv_id = it.ictv_id
        WHERE vim.match_status <> 'rejected'
          AND vm.canonical_name NOT IN ('Unknown/Unclassified', 'Non-crustacean virus')
        GROUP BY vm.master_id
        HAVING family_count <= 1
           AND genus_count <= 1
        """
    ).fetchall()

    for row in eligible:
        conn.execute(
            """
            UPDATE virus_master
            SET virus_family = COALESCE(?, virus_family),
                virus_genus = COALESCE(?, virus_genus)
            WHERE master_id = ?
            """,
            (row["family"], row["genus"], row["master_id"]),
        )

    # Clear taxonomy previously written to broad bucket or ambiguous records by older script versions.
    conn.execute(
        """
        UPDATE virus_master
        SET virus_family = NULL,
            virus_genus = NULL
        WHERE canonical_name IN ('Unknown/Unclassified', 'Non-crustacean virus')
           OR master_id IN (
                SELECT master_id
                FROM (
                    SELECT vm.master_id,
                           COUNT(DISTINCT COALESCE(it.family, '')) AS family_count,
                           COUNT(DISTINCT COALESCE(it.genus, '')) AS genus_count
                    FROM virus_master vm
                    JOIN virus_ictv_mappings vim ON vm.master_id = vim.master_id
                    JOIN ictv_taxonomy it ON vim.ictv_id = it.ictv_id
                    WHERE vim.match_status <> 'rejected'
                    GROUP BY vm.master_id
                    HAVING family_count > 1 OR genus_count > 1
                )
           )
        """
    )
    return conn.total_changes - before


def log_import(conn: sqlite3.Connection, source_id: int, file_path: Path, imported: int, mapped: int) -> None:
    conn.execute(
        """
        INSERT INTO curation_logs
            (entity_type, action, source_id, new_value, confidence, curator, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "ictv_taxonomy",
            "import_ictv_msl",
            source_id,
            f"{MSL_VERSION} {RELEASE_YEAR}",
            "high",
            "import_ictv_msl.py",
            f"File={file_path.name}; imported_or_updated={imported}; mapping_changes={mapped}",
        ),
    )


def main(force_download: bool = False) -> None:
    backup_path = backup_database()
    print(f"[backup] {backup_path}")
    file_path = download_msl(force=force_download)
    print(f"[ictv] {file_path}")

    df = read_msl(file_path)
    print(f"[ictv] parsed_rows={len(df)}")

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        ensure_schema(conn)
        source_id = ensure_ictv_source(conn)
        imported = import_taxonomy(conn, df, file_path)
        mapped = map_local_viruses(conn, source_id)
        rejected = reject_bucket_mappings(conn)
        updated_master = update_virus_master_taxonomy(conn)
        log_import(conn, source_id, file_path, imported, mapped)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    print(f"[done] imported_or_updated={imported}")
    print(f"[done] mapping_changes={mapped}")
    print(f"[done] bucket_mappings_rejected={rejected}")
    print(f"[done] virus_master_taxonomy_updates={updated_master}")


if __name__ == "__main__":
    main()
