from __future__ import annotations

import csv
import json
import sqlite3
from datetime import datetime
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "crustacean_virus_core.db"
REPORTS_DIR = BASE_DIR / "reports"


def main() -> None:
    REPORTS_DIR.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    conn = sqlite3.connect(DB_PATH, timeout=60)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys=ON")
        conn.executescript(
            """
            DROP TABLE IF EXISTS _tmp_interpro_proteins;
            CREATE TEMP TABLE _tmp_interpro_proteins AS
            SELECT DISTINCT protein_id FROM interpro_annotations WHERE protein_id IS NOT NULL
            UNION
            SELECT DISTINCT pab.protein_id
            FROM protein_annotation_bridge pab
            JOIN interpro_annotations ia ON ia.uniprot_id = pab.uniprot_id
            WHERE pab.uniprot_id IS NOT NULL;

            DROP TABLE IF EXISTS _tmp_go_proteins;
            CREATE TEMP TABLE _tmp_go_proteins AS
            SELECT DISTINCT protein_id FROM interpro_go_terms WHERE protein_id IS NOT NULL;

            DROP TABLE IF EXISTS _tmp_kegg_proteins;
            CREATE TEMP TABLE _tmp_kegg_proteins AS
            SELECT DISTINCT protein_id FROM kegg_annotations WHERE protein_id IS NOT NULL
            UNION
            SELECT DISTINCT pab.protein_id
            FROM protein_annotation_bridge pab
            JOIN kegg_annotations ka
              ON ka.uniprot_id = pab.uniprot_id
              OR ka.ncbi_protein_acc = pab.protein_accession
              OR ka.ncbi_protein_acc = pab.accession_root;

            DROP TABLE IF EXISTS _tmp_uniprot_structure_proteins;
            CREATE TEMP TABLE _tmp_uniprot_structure_proteins AS
            SELECT DISTINCT protein_id FROM uniprot_structures WHERE protein_id IS NOT NULL
            UNION
            SELECT DISTINCT pab.protein_id
            FROM protein_annotation_bridge pab
            JOIN uniprot_structures us ON us.uniprot_id = pab.uniprot_id
            WHERE pab.uniprot_id IS NOT NULL;

            DROP TABLE IF EXISTS _tmp_local_structure_proteins;
            CREATE TEMP TABLE _tmp_local_structure_proteins AS
            SELECT DISTINCT protein_id FROM protein_structures WHERE protein_id IS NOT NULL;

            UPDATE protein_annotation_bridge
            SET has_interpro = CASE WHEN protein_id IN (SELECT protein_id FROM _tmp_interpro_proteins) THEN 1 ELSE 0 END,
                has_interpro_go = CASE WHEN protein_id IN (SELECT protein_id FROM _tmp_go_proteins) THEN 1 ELSE 0 END,
                has_kegg = CASE WHEN protein_id IN (SELECT protein_id FROM _tmp_kegg_proteins) THEN 1 ELSE 0 END,
                has_structure = CASE
                    WHEN protein_id IN (SELECT protein_id FROM _tmp_uniprot_structure_proteins)
                      OR protein_id IN (SELECT protein_id FROM _tmp_local_structure_proteins)
                    THEN 1 ELSE 0 END,
                updated_at = CURRENT_TIMESTAMP;

            UPDATE protein_annotation_bridge
            SET annotation_sources =
                trim(
                    (CASE WHEN has_uniprot=1 THEN 'UniProt;' ELSE '' END) ||
                    (CASE WHEN has_interpro=1 THEN 'InterPro;' ELSE '' END) ||
                    (CASE WHEN has_interpro_go=1 THEN 'GO;' ELSE '' END) ||
                    (CASE WHEN has_kegg=1 THEN 'KEGG;' ELSE '' END) ||
                    (CASE WHEN has_structure=1 THEN 'Structure;' ELSE '' END),
                    ';'
                );
            """
        )
        conn.commit()

        summary = {}
        for key, sql in {
            "viral_proteins": "SELECT COUNT(*) FROM viral_proteins",
            "bridge_rows": "SELECT COUNT(*) FROM protein_annotation_bridge",
            "proteins_with_uniprot": "SELECT COUNT(DISTINCT protein_id) FROM protein_annotation_bridge WHERE has_uniprot=1",
            "proteins_with_interpro": "SELECT COUNT(DISTINCT protein_id) FROM protein_annotation_bridge WHERE has_interpro=1",
            "proteins_with_go": "SELECT COUNT(DISTINCT protein_id) FROM protein_annotation_bridge WHERE has_interpro_go=1",
            "proteins_with_kegg": "SELECT COUNT(DISTINCT protein_id) FROM protein_annotation_bridge WHERE has_kegg=1",
            "proteins_with_any_structure": "SELECT COUNT(DISTINCT protein_id) FROM protein_annotation_bridge WHERE has_structure=1",
            "proteins_with_local_protein_structures": "SELECT COUNT(DISTINCT protein_id) FROM protein_structures WHERE protein_id IS NOT NULL",
            "proteins_with_uniprot_structures": "SELECT COUNT(DISTINCT protein_id) FROM _tmp_uniprot_structure_proteins",
        }.items():
            summary[key] = conn.execute(sql).fetchone()[0]

        conflicts = conn.execute(
            """
            SELECT pab.protein_id, pab.protein_accession, pab.uniprot_id,
                   pab.has_structure AS bridge_has_structure,
                   CASE WHEN lsp.protein_id IS NOT NULL THEN 1 ELSE 0 END AS local_protein_structures,
                   CASE WHEN usp.protein_id IS NOT NULL THEN 1 ELSE 0 END AS uniprot_structures,
                   CASE
                       WHEN pab.has_structure=1 AND lsp.protein_id IS NULL THEN 'bridge_uses_uniprot_structure_not_local_table'
                       WHEN pab.has_structure=0 AND lsp.protein_id IS NOT NULL THEN 'local_structure_missing_from_bridge'
                       ELSE 'consistent'
                   END AS status
            FROM protein_annotation_bridge pab
            LEFT JOIN _tmp_local_structure_proteins lsp ON lsp.protein_id = pab.protein_id
            LEFT JOIN _tmp_uniprot_structure_proteins usp ON usp.protein_id = pab.protein_id
            WHERE status <> 'consistent'
            ORDER BY status, pab.protein_id
            LIMIT 50000
            """
        ).fetchall()
        csv_path = REPORTS_DIR / f"protein_structure_reconciliation_{stamp}.csv"
        with csv_path.open("w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(conflicts[0].keys() if conflicts else ["protein_id"])
            for row in conflicts:
                writer.writerow([row[k] for k in row.keys()])

        json_path = REPORTS_DIR / f"protein_annotation_bridge_reconciled_{stamp}.json"
        json_path.write_text(
            json.dumps({"generated_at": datetime.now().isoformat(timespec="seconds"), "summary": summary, "conflict_report": str(csv_path)}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(json.dumps({"summary": summary, "conflicts": len(conflicts), "report": str(json_path)}, ensure_ascii=False, indent=2))
    finally:
        conn.close()


if __name__ == "__main__":
    main()
