import json
import sqlite3
from pathlib import Path

db = Path(__file__).resolve().parent / "crustacean_virus_core.db"
con = sqlite3.connect(db)
cur = con.cursor()

count = cur.execute("SELECT COUNT(*) FROM interpro_go_terms").fetchone()[0]
if count:
    raise SystemExit("interpro_go_terms is not empty; refusing automatic FK rebuild")

old_sql = cur.execute(
    "SELECT sql FROM sqlite_master WHERE type='table' AND name='interpro_go_terms'"
).fetchone()[0]

cur.execute("ALTER TABLE interpro_go_terms RENAME TO interpro_go_terms_bad_fk")
cur.execute(
    """
    CREATE TABLE interpro_go_terms (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        protein_id INTEGER,
        interpro_id TEXT,
        go_id TEXT,
        go_name TEXT,
        go_namespace TEXT,
        evidence_source TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(protein_id, interpro_id, go_id)
    )
    """
)
cur.execute("DROP TABLE interpro_go_terms_bad_fk")
cur.execute(
    """
    INSERT INTO database_maintenance_log
    (action, details_json, created_at)
    VALUES (?, ?, CURRENT_TIMESTAMP)
    """,
    (
        "schema_fix",
        json.dumps(
            {
                "table": "interpro_go_terms",
                "reason": "invalid FK to non-unique interpro_annotations.interpro_id blocked PRAGMA foreign_key_check",
                "previous_sql": old_sql,
            },
            ensure_ascii=False,
        ),
    ),
)
con.commit()
print("fixed interpro_go_terms foreign key mismatch")
