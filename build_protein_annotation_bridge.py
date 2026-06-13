from __future__ import annotations

import csv
import json
import sqlite3
from datetime import datetime
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "crustacean_virus_core.db"
REPORT_DIR = BASE_DIR / "reports"


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        PRAGMA foreign_keys=ON;

        CREATE TABLE IF NOT EXISTS protein_annotation_bridge (
            bridge_id INTEGER PRIMARY KEY AUTOINCREMENT,
            protein_id INTEGER,
            isolate_id INTEGER,
            protein_accession TEXT,
            accession_root TEXT,
            uniprot_id TEXT,
            annotation_sources TEXT,
            has_uniprot INTEGER DEFAULT 0,
            has_interpro INTEGER DEFAULT 0,
            has_interpro_go INTEGER DEFAULT 0,
            has_kegg INTEGER DEFAULT 0,
            has_structure INTEGER DEFAULT 0,
            has_alphafold INTEGER DEFAULT 0,
            has_pdb INTEGER DEFAULT 0,
            interpro_count INTEGER DEFAULT 0,
            go_count INTEGER DEFAULT 0,
            kegg_ko_count INTEGER DEFAULT 0,
            structure_count INTEGER DEFAULT 0,
            best_structure_confidence REAL,
            match_method TEXT,
            needs_review INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(protein_id, uniprot_id)
        );

        CREATE INDEX IF NOT EXISTS idx_bridge_protein ON protein_annotation_bridge(protein_id);
        CREATE INDEX IF NOT EXISTS idx_bridge_uniprot ON protein_annotation_bridge(uniprot_id);
        CREATE INDEX IF NOT EXISTS idx_bridge_accession ON protein_annotation_bridge(protein_accession);
        CREATE INDEX IF NOT EXISTS idx_bridge_sources ON protein_annotation_bridge(has_uniprot, has_interpro, has_kegg, has_structure);
        """
    )


def accession_root(acc: str | None) -> str:
    value = (acc or "").strip()
    return value.split(".", 1)[0] if value else ""


def rebuild_bridge(conn: sqlite3.Connection) -> dict[str, int]:
    conn.execute("DELETE FROM protein_annotation_bridge")

    # Strong mappings from the explicit local link table.
    conn.execute(
        """
        INSERT OR IGNORE INTO protein_annotation_bridge
            (protein_id, isolate_id, protein_accession, accession_root, uniprot_id,
             has_uniprot, match_method, needs_review)
        SELECT vp.protein_id, vp.isolate_id, vp.protein_accession,
               CASE
                   WHEN instr(COALESCE(vp.protein_accession, '') || '.', '.') > 0
                   THEN substr(vp.protein_accession, 1, instr(vp.protein_accession || '.', '.') - 1)
                   ELSE vp.protein_accession
               END,
               upl.uniprot_id, 1,
               COALESCE(NULLIF(upl.match_type, ''), 'uniprot_protein_links'),
               0
        FROM uniprot_protein_links upl
        JOIN viral_proteins vp ON vp.protein_id = upl.protein_id
        WHERE upl.uniprot_id IS NOT NULL AND TRIM(upl.uniprot_id) != ''
        """
    )

    # Fallback mappings by NCBI protein accession.
    conn.execute(
        """
        INSERT OR IGNORE INTO protein_annotation_bridge
            (protein_id, isolate_id, protein_accession, accession_root, uniprot_id,
             has_uniprot, match_method, needs_review)
        SELECT vp.protein_id, vp.isolate_id, vp.protein_accession,
               CASE
                   WHEN instr(COALESCE(vp.protein_accession, '') || '.', '.') > 0
                   THEN substr(vp.protein_accession, 1, instr(vp.protein_accession || '.', '.') - 1)
                   ELSE vp.protein_accession
               END,
               ua.uniprot_id, 1, 'ncbi_protein_acc_exact_or_root', 0
        FROM uniprot_annotations ua
        JOIN viral_proteins vp
          ON ua.ncbi_protein_acc = vp.protein_accession
          OR ua.ncbi_protein_acc = substr(vp.protein_accession, 1, instr(vp.protein_accession || '.', '.') - 1)
        WHERE ua.uniprot_id IS NOT NULL AND TRIM(ua.uniprot_id) != ''
        """
    )

    # Keep proteins without UniProt in the bridge for gap accounting.
    conn.execute(
        """
        INSERT OR IGNORE INTO protein_annotation_bridge
            (protein_id, isolate_id, protein_accession, accession_root,
             has_uniprot, match_method, needs_review)
        SELECT vp.protein_id, vp.isolate_id, vp.protein_accession,
               CASE
                   WHEN instr(COALESCE(vp.protein_accession, '') || '.', '.') > 0
                   THEN substr(vp.protein_accession, 1, instr(vp.protein_accession || '.', '.') - 1)
                   ELSE vp.protein_accession
               END,
               0, 'no_uniprot_mapping', 0
        FROM viral_proteins vp
        """
    )

    conn.execute(
        """
        UPDATE protein_annotation_bridge
        SET has_interpro = CASE WHEN EXISTS (
                SELECT 1 FROM interpro_annotations ia
                WHERE ia.uniprot_id = protein_annotation_bridge.uniprot_id
                   OR (ia.protein_id IS NOT NULL AND ia.protein_id = protein_annotation_bridge.protein_id)
            ) THEN 1 ELSE 0 END,
            interpro_count = (
                SELECT COUNT(*) FROM interpro_annotations ia
                WHERE ia.uniprot_id = protein_annotation_bridge.uniprot_id
                   OR (ia.protein_id IS NOT NULL AND ia.protein_id = protein_annotation_bridge.protein_id)
            ),
            has_interpro_go = CASE WHEN EXISTS (
                SELECT 1 FROM interpro_go_terms gt
                WHERE gt.protein_id = protein_annotation_bridge.protein_id
            ) THEN 1 ELSE 0 END,
            go_count = (
                SELECT COUNT(*) FROM interpro_go_terms gt
                WHERE gt.protein_id = protein_annotation_bridge.protein_id
            )
        """
    )

    conn.execute(
        """
        UPDATE protein_annotation_bridge
        SET has_kegg = CASE WHEN EXISTS (
                SELECT 1 FROM kegg_annotations ka
                WHERE ka.uniprot_id = protein_annotation_bridge.uniprot_id
                   OR ka.ncbi_protein_acc = protein_annotation_bridge.protein_accession
                   OR ka.ncbi_protein_acc = protein_annotation_bridge.accession_root
                   OR (ka.protein_id IS NOT NULL AND ka.protein_id = protein_annotation_bridge.protein_id)
            ) THEN 1 ELSE 0 END,
            kegg_ko_count = (
                SELECT COUNT(DISTINCT ka.ko_id) FROM kegg_annotations ka
                WHERE ka.ko_id IS NOT NULL
                  AND (
                      ka.uniprot_id = protein_annotation_bridge.uniprot_id
                      OR ka.ncbi_protein_acc = protein_annotation_bridge.protein_accession
                      OR ka.ncbi_protein_acc = protein_annotation_bridge.accession_root
                      OR (ka.protein_id IS NOT NULL AND ka.protein_id = protein_annotation_bridge.protein_id)
                  )
            )
        """
    )

    conn.execute(
        """
        UPDATE protein_annotation_bridge
        SET has_structure = CASE WHEN EXISTS (
                SELECT 1 FROM uniprot_structures us
                WHERE us.uniprot_id = protein_annotation_bridge.uniprot_id
                   OR (us.protein_id IS NOT NULL AND us.protein_id = protein_annotation_bridge.protein_id)
            ) THEN 1 ELSE 0 END,
            has_alphafold = CASE WHEN EXISTS (
                SELECT 1 FROM uniprot_structures us
                WHERE us.source = 'alphafold'
                  AND (us.uniprot_id = protein_annotation_bridge.uniprot_id
                       OR (us.protein_id IS NOT NULL AND us.protein_id = protein_annotation_bridge.protein_id))
            ) THEN 1 ELSE 0 END,
            has_pdb = CASE WHEN EXISTS (
                SELECT 1 FROM uniprot_structures us
                WHERE us.source = 'pdb'
                  AND (us.uniprot_id = protein_annotation_bridge.uniprot_id
                       OR (us.protein_id IS NOT NULL AND us.protein_id = protein_annotation_bridge.protein_id))
            ) THEN 1 ELSE 0 END,
            structure_count = (
                SELECT COUNT(*) FROM uniprot_structures us
                WHERE us.uniprot_id = protein_annotation_bridge.uniprot_id
                   OR (us.protein_id IS NOT NULL AND us.protein_id = protein_annotation_bridge.protein_id)
            ),
            best_structure_confidence = (
                SELECT MAX(us.confidence) FROM uniprot_structures us
                WHERE us.uniprot_id = protein_annotation_bridge.uniprot_id
                   OR (us.protein_id IS NOT NULL AND us.protein_id = protein_annotation_bridge.protein_id)
            )
        """
    )

    rows = conn.execute(
        """
        SELECT bridge_id, has_uniprot, has_interpro, has_interpro_go, has_kegg, has_structure
        FROM protein_annotation_bridge
        """
    ).fetchall()
    for r in rows:
        sources = []
        if r["has_uniprot"]:
            sources.append("UniProt")
        if r["has_interpro"]:
            sources.append("InterPro")
        if r["has_interpro_go"]:
            sources.append("GO")
        if r["has_kegg"]:
            sources.append("KEGG")
        if r["has_structure"]:
            sources.append("Structure")
        conn.execute(
            "UPDATE protein_annotation_bridge SET annotation_sources = ?, updated_at = CURRENT_TIMESTAMP WHERE bridge_id = ?",
            (";".join(sources), r["bridge_id"]),
        )

    conn.commit()
    return dict(
        conn.execute(
            """
            SELECT 'bridge_rows', COUNT(*) FROM protein_annotation_bridge
            UNION ALL SELECT 'proteins_with_uniprot', COUNT(DISTINCT protein_id) FROM protein_annotation_bridge WHERE has_uniprot=1
            UNION ALL SELECT 'proteins_with_interpro', COUNT(DISTINCT protein_id) FROM protein_annotation_bridge WHERE has_interpro=1
            UNION ALL SELECT 'proteins_with_go', COUNT(DISTINCT protein_id) FROM protein_annotation_bridge WHERE has_interpro_go=1
            UNION ALL SELECT 'proteins_with_kegg', COUNT(DISTINCT protein_id) FROM protein_annotation_bridge WHERE has_kegg=1
            UNION ALL SELECT 'proteins_with_structure', COUNT(DISTINCT protein_id) FROM protein_annotation_bridge WHERE has_structure=1
            """
        ).fetchall()
    )


def export_report(conn: sqlite3.Connection, summary: dict[str, int]) -> Path:
    REPORT_DIR.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = REPORT_DIR / f"protein_annotation_bridge_{stamp}.json"
    json_path.write_text(
        json.dumps(
            {
                "generated_at": datetime.now().isoformat(timespec="seconds"),
                "summary": summary,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    gap_path = REPORT_DIR / f"protein_annotation_bridge_gaps_{stamp}.csv"
    rows = conn.execute(
        """
        SELECT protein_id, isolate_id, protein_accession, uniprot_id,
               has_uniprot, has_interpro, has_interpro_go, has_kegg, has_structure,
               annotation_sources, match_method
        FROM protein_annotation_bridge
        WHERE has_uniprot=0 OR has_interpro=0 OR has_kegg=0 OR has_structure=0
        ORDER BY has_uniprot, has_interpro, has_kegg, has_structure, protein_id
        LIMIT 50000
        """
    ).fetchall()
    with gap_path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(rows[0].keys() if rows else ["protein_id"])
        for row in rows:
            writer.writerow([row[k] for k in row.keys()])

    return json_path


def main() -> None:
    conn = sqlite3.connect(DB_PATH, timeout=60)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys=ON")
        ensure_schema(conn)
        summary = rebuild_bridge(conn)
        path = export_report(conn, summary)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        print(f"[report] {path}")
        print("integrity", conn.execute("PRAGMA integrity_check").fetchone()[0])
        print("fk", len(conn.execute("PRAGMA foreign_key_check").fetchall()))
    finally:
        conn.close()


if __name__ == "__main__":
    main()
