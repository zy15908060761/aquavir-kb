import sqlite3
from pathlib import Path

db = Path(__file__).resolve().parent / "crustacean_virus_core.db"
con = sqlite3.connect(db)
cur = con.cursor()

cur.execute(
    """
    CREATE TABLE IF NOT EXISTS biosample_links (
        link_id INTEGER PRIMARY KEY AUTOINCREMENT,
        isolate_id INTEGER,
        accession TEXT,
        biosample_accession TEXT,
        bioproject_accession TEXT,
        source_text TEXT,
        match_confidence TEXT,
        curation_status TEXT DEFAULT 'needs_remote_lookup',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (isolate_id) REFERENCES viral_isolates(isolate_id)
    )
    """
)

inserted = 0
for sra_id, sra_acc, biosample, bioproject, title, organism, matched in cur.execute(
    """
    SELECT sra_id, sra_accession, biosample, bioproject, title, organism, virus_species_matched
    FROM sra_runs
    WHERE biosample IS NOT NULL AND trim(biosample)!=''
    """
).fetchall():
    # SRA runs are not isolate-specific yet; store database-level traceable link.
    exists = cur.execute(
        "SELECT 1 FROM biosample_links WHERE biosample_accession=? AND bioproject_accession IS ? AND source_text LIKE ?",
        (biosample, bioproject, f"%{sra_acc}%"),
    ).fetchone()
    if exists:
        continue
    cur.execute(
        """
        INSERT INTO biosample_links
        (isolate_id, accession, biosample_accession, bioproject_accession, source_text, match_confidence, curation_status)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            None,
            sra_acc,
            biosample,
            bioproject,
            f"SRA={sra_acc}; title={title or ''}; organism={organism or ''}; matched={matched or ''}",
            "medium",
            "sra_dataset_link_needs_isolate_mapping",
        ),
    )
    inserted += 1

cur.execute(
    "INSERT INTO database_maintenance_log (action, details_json, created_at) VALUES ('sra_biosample_linking', ?, CURRENT_TIMESTAMP)",
    (f'{{"inserted": {inserted}}}',),
)
con.commit()
print({"inserted": inserted})
