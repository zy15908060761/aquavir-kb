"""
Import the ICTV Virus Metadata Resource (VMR) and bridge common virus names
to ICTV MSL species records.

VMR is used because MSL41 stores official binomial species names, while VMR
also contains exemplar virus names, suggested abbreviations, GenBank/RefSeq
accessions, genome composition, and host source.
"""

from __future__ import annotations

import hashlib
import json
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

VMR_VERSION = "VMR_MSL41.v1.20260320"
MSL_VERSION = "MSL41"
VMR_FILENAME = "VMR_MSL41.v1.20260320.xlsx"
VMR_URL = "https://ictv.global/vmr/current"
VMR_ARCHIVE_URL = "https://doi.org/10.5281/zenodo.19154144"


BUCKET_NAMES = {"Unknown/Unclassified", "Non-crustacean virus"}


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
    backup_path = BACKUP_DIR / f"crustacean_virus_core_before_ictv_vmr_import_{stamp}.db"
    shutil.copy2(DB_PATH, backup_path)
    return backup_path


def download_vmr(force: bool = False) -> Path:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    target = DATA_DIR / VMR_FILENAME
    if target.exists() and not force:
        return target
    req = urllib.request.Request(
        VMR_URL,
        headers={
            "User-Agent": "Mozilla/5.0 crustacean-virus-db/1.0",
            "Accept": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,*/*",
        },
    )
    with urllib.request.urlopen(req, timeout=180) as response:
        target.write_bytes(response.read())
    return target


def normalize_header(value: object) -> str:
    text = str(value or "").strip().lower()
    text = text.replace("refseq", "ref_seq")
    text = re.sub(r"[^a-z0-9]+", "_", text).strip("_")
    return text


def normalize_name(value: object) -> str:
    text = str(value or "").strip().lower()
    text = text.replace("\u2010", "-").replace("\u2011", "-").replace("\u2013", "-").replace("\u2014", "-")
    text = re.sub(r"\([^)]*\)", " ", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


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


def find_vmr_sheet(path: Path) -> str | int:
    xls = pd.ExcelFile(path)
    for name in xls.sheet_names:
        lowered = name.lower()
        if "vmr" in lowered or "virus" in lowered:
            return name
    return 0


def find_header_row(path: Path, sheet: str | int) -> int:
    preview = pd.read_excel(path, sheet_name=sheet, header=None, nrows=25)
    for idx, row in preview.iterrows():
        joined = " ".join(str(x).lower() for x in row.tolist() if pd.notna(x))
        if "species" in joined and "virus" in joined and ("genbank" in joined or "accession" in joined):
            return int(idx)
    return 0


def pick_col(columns: list[str], *patterns: str) -> str | None:
    for pattern in patterns:
        rx = re.compile(pattern)
        for col in columns:
            if rx.search(col):
                return col
    return None


def read_vmr(path: Path) -> pd.DataFrame:
    sheet = find_vmr_sheet(path)
    header_row = find_header_row(path, sheet)
    raw = pd.read_excel(path, sheet_name=sheet, header=header_row)
    raw.columns = [normalize_header(c) for c in raw.columns]
    raw = raw.dropna(how="all")
    columns = list(raw.columns)

    colmap = {
        "official_ictv_id": pick_col(columns, r"^ictv_id$", r"ictv.*id"),
        "exemplar_type": pick_col(columns, r"exemplar", r"additional.*isolate"),
        "virus_name": pick_col(columns, r"^virus_name$", r"virus_names?$", r"exemplar.*virus.*name"),
        "virus_abbreviation": pick_col(columns, r"abbrev", r"suggested.*abbrev"),
        "virus_isolate": pick_col(columns, r"isolate"),
        "genbank_accession": pick_col(columns, r"genbank.*accession", r"gen_bank.*accession"),
        "refseq_accession": pick_col(columns, r"ref_seq.*accession", r"refseq.*accession"),
        "genome_composition": pick_col(columns, r"genome.*composition", r"^genome$"),
        "host_source": pick_col(columns, r"host.*source", r"natural.*host", r"host"),
    }
    for rank in RANK_COLUMNS:
        source_name = "order" if rank == "order_name" else rank
        colmap[rank] = pick_col(columns, rf"^{source_name}$")

    rows = []
    for _, source in raw.iterrows():
        species_col = colmap.get("species")
        species = clean_text(source.get(species_col)) if species_col else None
        virus_name_col = colmap.get("virus_name")
        virus_name = clean_text(source.get(virus_name_col)) if virus_name_col else None
        if not species and not virus_name:
            continue
        record = {}
        for key, col in colmap.items():
            record[key] = clean_text(source.get(col)) if col else None
        record["raw_json"] = json.dumps(
            {col: clean_text(source.get(col)) for col in columns if clean_text(source.get(col)) is not None},
            ensure_ascii=False,
            sort_keys=True,
        )
        record["row_hash"] = row_hash([record.get(key) for key in sorted(colmap)] + [record["raw_json"]])
        rows.append(record)

    if not rows:
        raise RuntimeError(f"No VMR rows parsed from sheet={sheet!r}, header_row={header_row}")
    return pd.DataFrame(rows)


def ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        PRAGMA foreign_keys = ON;

        CREATE TABLE IF NOT EXISTS ictv_vmr (
            vmr_id INTEGER PRIMARY KEY AUTOINCREMENT,
            vmr_version TEXT NOT NULL,
            official_ictv_id TEXT,
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
            species TEXT,
            exemplar_type TEXT,
            virus_name TEXT,
            virus_abbreviation TEXT,
            virus_isolate TEXT,
            genbank_accession TEXT,
            refseq_accession TEXT,
            genome_composition TEXT,
            host_source TEXT,
            raw_json TEXT,
            row_hash TEXT NOT NULL,
            source_file TEXT,
            imported_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (vmr_version, row_hash)
        );

        CREATE TABLE IF NOT EXISTS virus_vmr_mappings (
            mapping_id INTEGER PRIMARY KEY AUTOINCREMENT,
            master_id INTEGER NOT NULL,
            vmr_id INTEGER NOT NULL,
            ictv_id INTEGER,
            match_type TEXT NOT NULL CHECK (
                match_type IN (
                    'accession_exact',
                    'accession_base_exact',
                    'virus_name_exact',
                    'abbreviation_exact',
                    'species_exact',
                    'manual_alias'
                )
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
            FOREIGN KEY (vmr_id) REFERENCES ictv_vmr(vmr_id),
            FOREIGN KEY (ictv_id) REFERENCES ictv_taxonomy(ictv_id),
            FOREIGN KEY (source_id) REFERENCES external_sources(source_id),
            UNIQUE (master_id, vmr_id, match_type, matched_value)
        );

        CREATE INDEX IF NOT EXISTS idx_ictv_vmr_species ON ictv_vmr(species);
        CREATE INDEX IF NOT EXISTS idx_ictv_vmr_virus_name ON ictv_vmr(virus_name);
        CREATE INDEX IF NOT EXISTS idx_ictv_vmr_genbank ON ictv_vmr(genbank_accession);
        CREATE INDEX IF NOT EXISTS idx_ictv_vmr_refseq ON ictv_vmr(refseq_accession);
        CREATE INDEX IF NOT EXISTS idx_vvm_master ON virus_vmr_mappings(master_id);
        CREATE INDEX IF NOT EXISTS idx_vvm_vmr ON virus_vmr_mappings(vmr_id);
        CREATE INDEX IF NOT EXISTS idx_vvm_ictv ON virus_vmr_mappings(ictv_id);
        """
    )


def ensure_vmr_source(conn: sqlite3.Connection) -> int:
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
            "ictv_vmr",
            "ICTV Virus Metadata Resource",
            "virus_metadata",
            "https://ictv.global/vmr/current",
            "ICTV exemplar virus metadata with common names, abbreviations, accessions, genome composition, and host source.",
            VMR_VERSION,
            31,
        ),
    )
    return conn.execute("SELECT source_id FROM external_sources WHERE source_key = 'ictv_vmr'").fetchone()["source_id"]


def import_vmr(conn: sqlite3.Connection, df: pd.DataFrame, source_file: Path) -> int:
    before = conn.total_changes
    records = []
    for _, row in df.iterrows():
        records.append(
            tuple([VMR_VERSION] + [row.get(col) for col in [
                "official_ictv_id",
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
                "exemplar_type",
                "virus_name",
                "virus_abbreviation",
                "virus_isolate",
                "genbank_accession",
                "refseq_accession",
                "genome_composition",
                "host_source",
                "raw_json",
                "row_hash",
            ]] + [source_file.name])
        )

    conn.executemany(
        """
        INSERT INTO ictv_vmr
            (
                vmr_version, official_ictv_id, realm, subrealm, kingdom, subkingdom,
                phylum, subphylum, class, subclass, order_name, suborder,
                family, subfamily, genus, subgenus, species, exemplar_type,
                virus_name, virus_abbreviation, virus_isolate, genbank_accession,
                refseq_accession, genome_composition, host_source, raw_json,
                row_hash, source_file
            )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(vmr_version, row_hash) DO UPDATE SET
            official_ictv_id = excluded.official_ictv_id,
            realm = excluded.realm,
            subrealm = excluded.subrealm,
            kingdom = excluded.kingdom,
            subkingdom = excluded.subkingdom,
            phylum = excluded.phylum,
            subphylum = excluded.subphylum,
            class = excluded.class,
            subclass = excluded.subclass,
            order_name = excluded.order_name,
            suborder = excluded.suborder,
            family = excluded.family,
            subfamily = excluded.subfamily,
            genus = excluded.genus,
            subgenus = excluded.subgenus,
            species = excluded.species,
            exemplar_type = excluded.exemplar_type,
            virus_name = excluded.virus_name,
            virus_abbreviation = excluded.virus_abbreviation,
            virus_isolate = excluded.virus_isolate,
            genbank_accession = excluded.genbank_accession,
            refseq_accession = excluded.refseq_accession,
            genome_composition = excluded.genome_composition,
            host_source = excluded.host_source,
            raw_json = excluded.raw_json,
            source_file = excluded.source_file,
            imported_at = CURRENT_TIMESTAMP
        """,
        records,
    )
    return conn.total_changes - before


def split_tokens(value: str | None) -> list[str]:
    if not value:
        return []
    tokens = re.split(r"[;,/|]+", value)
    return [token.strip() for token in tokens if token and token.strip()]


def accession_tokens(value: str | None) -> list[str]:
    tokens = []
    for token in split_tokens(value):
        for part in re.split(r"\s+", token):
            part = part.strip()
            if part:
                tokens.append(part)
    return tokens


def base_accession(value: str) -> str:
    return value.split(".", 1)[0].upper()


def find_ictv_id(conn: sqlite3.Connection, vmr_row: sqlite3.Row) -> int | None:
    if vmr_row["official_ictv_id"]:
        row = conn.execute(
            "SELECT ictv_id FROM ictv_taxonomy WHERE official_ictv_id = ? LIMIT 1",
            (vmr_row["official_ictv_id"],),
        ).fetchone()
        if row:
            return row["ictv_id"]
    if vmr_row["species"]:
        row = conn.execute(
            "SELECT ictv_id FROM ictv_taxonomy WHERE msl_version = ? AND species = ? LIMIT 1",
            (MSL_VERSION, vmr_row["species"]),
        ).fetchone()
        if row:
            return row["ictv_id"]
    return None


def local_name_lookup(conn: sqlite3.Connection) -> dict[str, list[tuple[int, str]]]:
    lookup: dict[str, list[tuple[int, str]]] = {}
    for row in conn.execute("SELECT master_id, canonical_name, abbreviations FROM virus_master"):
        if row["canonical_name"] in BUCKET_NAMES:
            continue
        if row["canonical_name"]:
            lookup.setdefault(normalize_name(row["canonical_name"]), []).append((row["master_id"], "virus_name_exact"))
        for abbr in split_tokens(row["abbreviations"]):
            lookup.setdefault(normalize_name(abbr), []).append((row["master_id"], "abbreviation_exact"))
    for row in conn.execute(
        """
        SELECT master_id, alias, alias_type
        FROM virus_aliases
        WHERE match_status <> 'rejected'
        """
    ):
        key = normalize_name(row["alias"])
        if not key:
            continue
        match_type = "abbreviation_exact" if row["alias_type"] == "abbreviation" else "virus_name_exact"
        lookup.setdefault(key, []).append((row["master_id"], match_type))
    return lookup


def local_accession_lookup(conn: sqlite3.Connection) -> tuple[dict[str, int], dict[str, int]]:
    exact = {}
    base = {}
    for row in conn.execute("SELECT isolate_id, master_id, accession FROM viral_isolates WHERE master_id IS NOT NULL"):
        accession = row["accession"].strip().upper()
        exact[accession] = row["master_id"]
        base[base_accession(accession)] = row["master_id"]
    return exact, base


def insert_mapping(
    conn: sqlite3.Connection,
    master_id: int,
    vmr_row: sqlite3.Row,
    ictv_id: int | None,
    match_type: str,
    matched_value: str,
    source_id: int,
    notes: str,
) -> None:
    conn.execute(
        """
        INSERT OR IGNORE INTO virus_vmr_mappings
            (master_id, vmr_id, ictv_id, match_type, matched_value, confidence, source_id, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (master_id, vmr_row["vmr_id"], ictv_id, match_type, matched_value, "high", source_id, notes),
    )
    external_id = vmr_row["official_ictv_id"] or vmr_row["species"] or matched_value
    conn.execute(
        """
        INSERT OR IGNORE INTO external_xrefs
            (entity_type, entity_id, source_id, external_id, external_url, match_status, confidence, matched_by, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "virus_master",
            master_id,
            source_id,
            external_id,
            "https://ictv.global/vmr",
            "exact",
            "high",
            "import_ictv_vmr.py",
            notes,
        ),
    )
    if ictv_id:
        species = conn.execute("SELECT species FROM ictv_taxonomy WHERE ictv_id = ?", (ictv_id,)).fetchone()["species"]
        conn.execute(
            """
            INSERT OR IGNORE INTO virus_ictv_mappings
                (master_id, ictv_id, match_type, matched_value, confidence, source_id, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                master_id,
                ictv_id,
                "virus_name_exact" if match_type in {"virus_name_exact", "abbreviation_exact"} else "species_exact",
                matched_value,
                "high",
                source_id,
                f"VMR bridge to ICTV species={species}; {notes}",
            ),
        )


def map_vmr(conn: sqlite3.Connection, source_id: int) -> int:
    before = conn.total_changes
    name_lookup = local_name_lookup(conn)
    accession_exact, accession_base = local_accession_lookup(conn)

    for vmr_row in conn.execute("SELECT * FROM ictv_vmr WHERE vmr_version = ?", (VMR_VERSION,)):
        ictv_id = find_ictv_id(conn, vmr_row)

        for field in ("genbank_accession", "refseq_accession"):
            for accession in accession_tokens(vmr_row[field]):
                upper = accession.upper()
                if upper in accession_exact:
                    insert_mapping(
                        conn,
                        accession_exact[upper],
                        vmr_row,
                        ictv_id,
                        "accession_exact",
                        accession,
                        source_id,
                        f"Matched VMR {field} to local accession.",
                    )
                elif base_accession(upper) in accession_base:
                    insert_mapping(
                        conn,
                        accession_base[base_accession(upper)],
                        vmr_row,
                        ictv_id,
                        "accession_base_exact",
                        accession,
                        source_id,
                        f"Matched VMR {field} base accession to local accession.",
                    )

        for name in split_tokens(vmr_row["virus_name"]):
            key = normalize_name(name)
            for master_id, match_type in name_lookup.get(key, []):
                insert_mapping(conn, master_id, vmr_row, ictv_id, match_type, name, source_id, "Matched VMR virus name.")

        for abbr in split_tokens(vmr_row["virus_abbreviation"]):
            key = normalize_name(abbr)
            for master_id, _ in name_lookup.get(key, []):
                insert_mapping(conn, master_id, vmr_row, ictv_id, "abbreviation_exact", abbr, source_id, "Matched VMR abbreviation.")

    return conn.total_changes - before


def update_master_from_vmr(conn: sqlite3.Connection) -> int:
    before = conn.total_changes
    rows = conn.execute(
        """
        SELECT vm.master_id,
               MIN(iv.family) AS family,
               MIN(iv.genus) AS genus,
               MIN(iv.genome_composition) AS genome_type,
               COUNT(DISTINCT COALESCE(iv.family, '')) AS family_count,
               COUNT(DISTINCT COALESCE(iv.genus, '')) AS genus_count,
               COUNT(DISTINCT COALESCE(iv.genome_composition, '')) AS genome_count
        FROM virus_master vm
        JOIN virus_vmr_mappings vvm ON vm.master_id = vvm.master_id
        JOIN ictv_vmr iv ON vvm.vmr_id = iv.vmr_id
        WHERE vvm.match_status <> 'rejected'
          AND vm.canonical_name NOT IN ('Unknown/Unclassified', 'Non-crustacean virus')
        GROUP BY vm.master_id
        HAVING family_count <= 1 AND genus_count <= 1 AND genome_count <= 1
        """
    ).fetchall()
    for row in rows:
        conn.execute(
            """
            UPDATE virus_master
            SET virus_family = COALESCE(?, virus_family),
                virus_genus = COALESCE(?, virus_genus),
                genome_type = COALESCE(?, genome_type)
            WHERE master_id = ?
            """,
            (row["family"], row["genus"], row["genome_type"], row["master_id"]),
        )
    return conn.total_changes - before


def seed_aliases_from_vmr(conn: sqlite3.Connection, source_id: int) -> int:
    before = conn.total_changes
    for row in conn.execute(
        """
        SELECT vvm.master_id, iv.virus_name, iv.virus_abbreviation, iv.official_ictv_id
        FROM virus_vmr_mappings vvm
        JOIN ictv_vmr iv ON vvm.vmr_id = iv.vmr_id
        WHERE vvm.match_status <> 'rejected'
        """
    ):
        for name in split_tokens(row["virus_name"]):
            conn.execute(
                """
                INSERT OR IGNORE INTO virus_aliases
                    (master_id, alias, alias_type, source_id, external_id, match_status, confidence, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (row["master_id"], name, "synonym", source_id, row["official_ictv_id"], "exact", "high", "Seeded from ICTV VMR virus name."),
            )
        for abbr in split_tokens(row["virus_abbreviation"]):
            conn.execute(
                """
                INSERT OR IGNORE INTO virus_aliases
                    (master_id, alias, alias_type, source_id, external_id, match_status, confidence, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (row["master_id"], abbr, "abbreviation", source_id, row["official_ictv_id"], "exact", "high", "Seeded from ICTV VMR abbreviation."),
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
            "ictv_vmr",
            "import_ictv_vmr",
            source_id,
            VMR_VERSION,
            "high",
            "import_ictv_vmr.py",
            f"File={file_path.name}; imported_or_updated={imported}; mapping_changes={mapped}",
        ),
    )


def main(force_download: bool = False) -> None:
    backup_path = backup_database()
    print(f"[backup] {backup_path}")
    file_path = download_vmr(force=force_download)
    print(f"[vmr] {file_path}")
    df = read_vmr(file_path)
    print(f"[vmr] parsed_rows={len(df)}")
    print(f"[vmr] parsed_columns={','.join(df.columns)}")

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        ensure_schema(conn)
        source_id = ensure_vmr_source(conn)
        imported = import_vmr(conn, df, file_path)
        mapped = map_vmr(conn, source_id)
        aliases = seed_aliases_from_vmr(conn, source_id)
        updated = update_master_from_vmr(conn)
        log_import(conn, source_id, file_path, imported, mapped)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    print(f"[done] imported_or_updated={imported}")
    print(f"[done] mapping_changes={mapped}")
    print(f"[done] aliases_seeded={aliases}")
    print(f"[done] virus_master_updates={updated}")


if __name__ == "__main__":
    main()
