import sqlite3
from pathlib import Path

from db_utils import get_db

con = get_db()
cur = con.cursor()

cur.execute(
    """
    CREATE TABLE IF NOT EXISTS uniprot_protein_links (
        link_id INTEGER PRIMARY KEY AUTOINCREMENT,
        uniprot_id TEXT NOT NULL,
        ncbi_protein_acc TEXT,
        protein_id INTEGER,
        match_type TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(uniprot_id, ncbi_protein_acc, protein_id),
        FOREIGN KEY (protein_id) REFERENCES viral_proteins(protein_id)
    )
    """
)

cur.execute("DELETE FROM uniprot_protein_links")  # Intentional: repopulating the entire staging table
cur.execute(
    """
    INSERT OR IGNORE INTO uniprot_protein_links (uniprot_id, ncbi_protein_acc, protein_id, match_type)
    SELECT DISTINCT u.uniprot_id, u.ncbi_protein_acc, vp.protein_id, 'accession_without_version'
    FROM uniprot_annotations u
    JOIN viral_proteins vp
      ON replace(vp.protein_accession, '.' || substr(vp.protein_accession, instr(vp.protein_accession,'.')+1), '') = u.ncbi_protein_acc
    WHERE u.uniprot_id IS NOT NULL AND trim(u.uniprot_id)!=''
      AND u.ncbi_protein_acc IS NOT NULL AND trim(u.ncbi_protein_acc)!=''
      AND vp.protein_accession IS NOT NULL AND trim(vp.protein_accession)!=''
    """
)
links = cur.rowcount

cur.execute(
    """
    UPDATE interpro_go_terms
    SET protein_id = (
        SELECT upl.protein_id
        FROM uniprot_annotations u
        JOIN uniprot_protein_links upl ON upl.uniprot_id = u.uniprot_id
        WHERE interpro_go_terms.protein_id IS NULL
          AND interpro_go_terms.evidence_source='UniProt'
          AND u.go_terms LIKE '%' || interpro_go_terms.go_id || '%'
        LIMIT 1
    )
    WHERE protein_id IS NULL AND evidence_source='UniProt'
    """
)
go_updated = cur.rowcount

cur.execute(
    "INSERT INTO database_maintenance_log (action, details_json, created_at) VALUES ('uniprot_protein_mapping', ?, CURRENT_TIMESTAMP)",
    (f'{{"links": {links}, "go_updated": {go_updated}}}',),
)
con.commit()
print({"links": links, "go_updated": go_updated})
