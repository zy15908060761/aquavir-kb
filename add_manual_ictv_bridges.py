"""
Add reviewed ICTV bridges for high-priority viruses whose common names are not
directly represented as species names in ICTV MSL41.

This is a small, auditable bridge. It does not replace the VMR import; it keeps
the most important local records usable while VMR download/import is pending.
"""

from __future__ import annotations

import shutil
import sqlite3
from datetime import datetime
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "crustacean_virus_core.db"
BACKUP_DIR = BASE_DIR / "backups"


BRIDGES = [
    {
        "canonical_name": "White spot syndrome virus",
        "ictv_species": "Whispovirus xiabaidian",
        "alias_values": ["White spot syndrome virus", "Shrimp white spot syndrome virus", "WSSV"],
        "reason": (
            "Reviewed bridge from historical/common WSSV name to current ICTV MSL41 "
            "Whispovirus species. ICTV_ID ICTV20021201."
        ),
    },
    {
        "canonical_name": "Infectious hypodermal and hematopoietic necrosis virus",
        "ictv_species": "Shripenbrevirus decapod1",
        "alias_values": [
            "Infectious hypodermal and hematopoietic necrosis virus",
            "IHHNV",
            "Penstylhamaparvovirus decapod1",
        ],
        "reason": (
            "Reviewed bridge from IHHNV and older NCBI species label "
            "Penstylhamaparvovirus decapod1 to current ICTV MSL41 species "
            "Shripenbrevirus decapod1."
        ),
    },
]


def backup_database() -> Path:
    BACKUP_DIR.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = BACKUP_DIR / f"crustacean_virus_core_before_manual_ictv_bridges_{stamp}.db"
    shutil.copy2(DB_PATH, backup_path)
    return backup_path


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS manual_ictv_bridges (
            bridge_id INTEGER PRIMARY KEY AUTOINCREMENT,
            master_id INTEGER NOT NULL,
            ictv_id INTEGER NOT NULL,
            canonical_name TEXT NOT NULL,
            ictv_species TEXT NOT NULL,
            reason TEXT NOT NULL,
            curator TEXT DEFAULT 'add_manual_ictv_bridges.py',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (master_id) REFERENCES virus_master(master_id),
            FOREIGN KEY (ictv_id) REFERENCES ictv_taxonomy(ictv_id),
            UNIQUE (master_id, ictv_id)
        );
        CREATE INDEX IF NOT EXISTS idx_manual_ictv_bridges_master
            ON manual_ictv_bridges(master_id);
        CREATE INDEX IF NOT EXISTS idx_manual_ictv_bridges_ictv
            ON manual_ictv_bridges(ictv_id);
        """
    )


def source_id(conn: sqlite3.Connection, key: str) -> int:
    row = conn.execute("SELECT source_id FROM external_sources WHERE source_key = ?", (key,)).fetchone()
    if not row:
        raise RuntimeError(f"Missing external source: {key}")
    return row["source_id"]


def apply_bridge(conn: sqlite3.Connection, bridge: dict[str, object], ictv_source_id: int) -> int:
    before = conn.total_changes
    master = conn.execute(
        "SELECT master_id FROM virus_master WHERE canonical_name = ?",
        (bridge["canonical_name"],),
    ).fetchone()
    if not master:
        raise RuntimeError(f"Missing virus_master row: {bridge['canonical_name']}")

    ictv = conn.execute(
        """
        SELECT ictv_id, official_ictv_id, species, family, genus, genome_composition
        FROM ictv_taxonomy
        WHERE species = ?
        LIMIT 1
        """,
        (bridge["ictv_species"],),
    ).fetchone()
    if not ictv:
        raise RuntimeError(f"Missing ICTV species row: {bridge['ictv_species']}")

    master_id = master["master_id"]
    ictv_id = ictv["ictv_id"]
    reason = bridge["reason"]

    conn.execute(
        """
        INSERT OR IGNORE INTO manual_ictv_bridges
            (master_id, ictv_id, canonical_name, ictv_species, reason)
        VALUES (?, ?, ?, ?, ?)
        """,
        (master_id, ictv_id, bridge["canonical_name"], bridge["ictv_species"], reason),
    )

    conn.execute(
        """
        INSERT OR IGNORE INTO virus_ictv_mappings
            (master_id, ictv_id, match_type, matched_value, match_status, confidence, source_id, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            master_id,
            ictv_id,
            "normalized_exact",
            bridge["canonical_name"],
            "manual_checked",
            "high",
            ictv_source_id,
            reason,
        ),
    )

    conn.execute(
        """
        INSERT OR IGNORE INTO external_xrefs
            (entity_type, entity_id, source_id, external_id, external_url, match_status, confidence, matched_by, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "virus_master",
            master_id,
            ictv_source_id,
            ictv["official_ictv_id"] or ictv["species"],
            "https://ictv.global/taxonomy",
            "manual_checked",
            "high",
            "add_manual_ictv_bridges.py",
            reason,
        ),
    )

    for alias in bridge["alias_values"]:
        conn.execute(
            """
            INSERT OR IGNORE INTO virus_aliases
                (master_id, alias, alias_type, source_id, external_id, match_status, confidence, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                master_id,
                alias,
                "manual_alias",
                ictv_source_id,
                ictv["official_ictv_id"] or ictv["species"],
                "manual_checked",
                "high",
                reason,
            ),
        )

    conn.execute(
        """
        UPDATE virus_master
        SET virus_family = COALESCE(?, virus_family),
            virus_genus = COALESCE(?, virus_genus),
            genome_type = COALESCE(?, genome_type)
        WHERE master_id = ?
        """,
        (ictv["family"], ictv["genus"], ictv["genome_composition"], master_id),
    )

    return conn.total_changes - before


def main() -> None:
    backup_path = backup_database()
    print(f"[backup] {backup_path}")

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        ensure_schema(conn)
        ictv_source_id = source_id(conn, "ictv")
        changes = 0
        for bridge in BRIDGES:
            changes += apply_bridge(conn, bridge, ictv_source_id)
        conn.execute(
            """
            INSERT INTO curation_logs
                (entity_type, action, source_id, new_value, confidence, curator, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "manual_ictv_bridges",
                "add_manual_ictv_bridges",
                ictv_source_id,
                ",".join(bridge["ictv_species"] for bridge in BRIDGES),
                "high",
                "add_manual_ictv_bridges.py",
                "Manual reviewed bridges for common virus names missing from direct MSL species-name matching.",
            ),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    print(f"[done] changes={changes}")


if __name__ == "__main__":
    main()
