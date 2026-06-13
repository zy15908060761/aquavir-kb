import csv
import sqlite3
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent
DB = BASE / "crustacean_virus_core.db"
OUT = BASE / "downloads" / f"review_worklists_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
OUT.mkdir(parents=True, exist_ok=True)

con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row
cur = con.cursor()


def export(name, sql):
    rows = cur.execute(sql).fetchall()
    path = OUT / name
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        if rows:
            writer.writerow(rows[0].keys())
            for r in rows:
                writer.writerow([r[k] for k in r.keys()])
        else:
            writer.writerow(["empty"])
    return path, len(rows)


exports = []
exports.append(
    export(
        "isolation_source_review.csv",
        """
        SELECT i.isolate_id, i.accession, i.virus_name, vm.canonical_name,
               m.host_name, m.isolation_source, m.geo_loc_name, m.collection_date,
               m.isolate_name, m.strain, m.raw_notes,
               rl.title AS reference_title, rl.pmid, rl.doi,
               dq.notes AS queue_notes,
               '' AS reviewer_source_type,
               '' AS reviewer_confidence,
               '' AS reviewer_notes
        FROM analysis_target_isolates i
        LEFT JOIN virus_master vm ON vm.master_id=i.master_id
        LEFT JOIN sample_metadata m ON m.isolate_id=i.isolate_id
        LEFT JOIN isolate_reference_links l ON l.isolate_id=i.isolate_id
        LEFT JOIN ref_literatures rl ON rl.reference_id=l.reference_id
        LEFT JOIN data_gap_queue dq ON dq.entity_id=CAST(i.isolate_id AS TEXT)
             AND dq.gap_type IN ('review_inferred_isolation_source','missing_isolation_source')
        WHERE m.isolation_source IS NULL OR trim(m.isolation_source)=''
           OR dq.queue_id IS NOT NULL
        GROUP BY i.isolate_id
        ORDER BY CASE WHEN m.isolation_source IS NULL OR trim(m.isolation_source)='' THEN 0 ELSE 1 END,
                 vm.canonical_name, i.accession
        """
    )
)

exports.append(
    export(
        "ictv_pending_review.csv",
        """
        SELECT vm.master_id, vm.canonical_name, vm.abbreviations, vm.virus_family, vm.virus_genus,
               vm.genome_type, vis.ictv_status, vis.reason AS review_reason,
               COUNT(DISTINCT vi.isolate_id) AS isolate_count,
               GROUP_CONCAT(DISTINCT vi.accession) AS accessions,
               '' AS reviewer_decision,
               '' AS reviewer_ictv_species,
               '' AS reviewer_notes
        FROM virus_master vm
        LEFT JOIN virus_ictv_status vis ON vis.master_id=vm.master_id
        LEFT JOIN viral_isolates vi ON vi.master_id=vm.master_id
        WHERE vis.ictv_status='pending_review'
        GROUP BY vm.master_id
        ORDER BY isolate_count DESC, vm.canonical_name
        """
    )
)

exports.append(
    export(
        "sra_biosample_mapping_review.csv",
        """
        SELECT bl.link_id, bl.accession AS sra_accession, bl.biosample_accession,
               bl.bioproject_accession, bl.source_text, bl.match_confidence,
               bl.curation_status,
               sr.title, sr.organism, sr.library_strategy, sr.library_source,
               sr.library_layout, sr.platform, sr.total_bases, sr.total_spots,
               '' AS reviewer_local_isolate_accession,
               '' AS reviewer_virus_name,
               '' AS reviewer_notes
        FROM biosample_links bl
        LEFT JOIN sra_runs sr ON sr.sra_accession=bl.accession
        ORDER BY bl.link_id
        """
    )
)

readme = OUT / "README_review_worklists.md"
readme.write_text(
    "# Review Worklists\n\n"
    + "\n".join(f"- `{p.name}`: {n} rows" for p, n in exports)
    + "\n\nFill reviewer columns, then import curated decisions with a follow-up script.\n",
    encoding="utf-8",
)

print({"out": str(OUT), "exports": [(p.name, n) for p, n in exports]})
