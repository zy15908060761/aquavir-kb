import csv
import json
import re
import sqlite3
from collections import Counter
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent
DB = BASE / "crustacean_virus_core.db"
META_CSV = BASE / "ncbi_metadata" / "crustacean_virus_metadata.csv"
REPORTS = BASE / "reports"
DOWNLOADS = BASE / "downloads"
RUN_TS = datetime.now().strftime("%Y%m%d_%H%M%S")


SOURCE_MAP = {
    "whole body": "whole organism",
    "hemolymph": "hemolymph",
    "haemolymph": "hemolymph",
    "hepatopancreas": "hepatopancreas",
    "pooled hepatopancreas samples": "hepatopancreas",
    "gill": "gill",
    "gills": "gill",
    "muscle": "muscle",
    "pleopod": "pleopod",
    "epidermis": "epidermis",
    "cuticle": "cuticle",
    "water": "water",
    "shrimp pond": "pond",
    "shrimp farm water": "pond water",
    "pond": "pond",
    "mixed tissues": "mixed tissues",
    "infected tissues": "infected tissues",
    "tail fans": "tail fan",
    "gut": "gut",
    "intestin": "intestine",
}


def clean(v):
    if v is None:
        return None
    s = str(v).strip()
    return s if s and s.lower() not in {"na", "n/a", "none", "null", "unknown", "-"} else None


def source_norm(v):
    s = clean(v)
    if not s:
        return None, None
    low = s.lower()
    for key, val in SOURCE_MAP.items():
        if key in low:
            return val, "high" if low == key else "medium"
    if any(x in low for x in ["metagenome", "estuary", "sea", "market", "farm", "commodity", "frozen"]):
        return s[:100], "medium"
    return None, None


def year_from_date(v):
    s = clean(v)
    if not s:
        return None
    m = re.search(r"(19|20)\d{2}", s)
    return m.group(0) if m else None


def load_meta():
    rows = {}
    with META_CSV.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            acc = clean(row.get("accession"))
            if acc:
                rows[acc] = row
    return rows


def ensure_tables(cur):
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
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS interpro_go_backfill_queue (
            queue_id INTEGER PRIMARY KEY AUTOINCREMENT,
            protein_id INTEGER,
            ncbi_protein_acc TEXT,
            uniprot_id TEXT,
            reason TEXT,
            status TEXT DEFAULT 'pending',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS field_completeness_snapshots (
            snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_ts TEXT,
            metric TEXT,
            numerator INTEGER,
            denominator INTEGER,
            pct REAL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )


def log(cur, action, details):
    cur.execute(
        "INSERT INTO database_maintenance_log (action, details_json, created_at) VALUES (?, ?, CURRENT_TIMESTAMP)",
        (action, json.dumps(details, ensure_ascii=False)),
    )


def metric(cur, name, sql_num, sql_den="SELECT COUNT(*) FROM analysis_target_isolates"):
    num = cur.execute(sql_num).fetchone()[0]
    den = cur.execute(sql_den).fetchone()[0]
    pct = round(num * 100 / den, 2) if den else 0
    cur.execute(
        "INSERT INTO field_completeness_snapshots (run_ts, metric, numerator, denominator, pct) VALUES (?, ?, ?, ?, ?)",
        (RUN_TS, name, num, den, pct),
    )
    return name, num, den, pct


def main():
    meta = load_meta()
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    ensure_tables(cur)
    changes = Counter()

    # Backup before this phase is expected to be created by caller or prior workflow.
    for r in cur.execute(
        """
        SELECT i.isolate_id, i.accession, m.isolation_source, m.collection_date, m.geo_loc_name,
               ir.record_id, ir.collection_id, ir.isolation_source AS ir_source,
               c.collection_date AS c_date, c.collection_year, c.source_type
        FROM analysis_target_isolates i
        LEFT JOIN sample_metadata m ON m.isolate_id=i.isolate_id
        LEFT JOIN infection_records ir ON ir.isolate_id=i.isolate_id
        LEFT JOIN sample_collections c ON c.collection_id=ir.collection_id
        """
    ).fetchall():
        acc = r["accession"]
        row = meta.get(acc, {})
        raw_source = clean(row.get("isolation_source")) or clean(r["isolation_source"])
        norm, conf = source_norm(raw_source)
        if norm and not clean(r["isolation_source"]):
            cur.execute("UPDATE sample_metadata SET isolation_source=? WHERE isolate_id=?", (norm, r["isolate_id"]))
            changes["sample_metadata.isolation_source"] += 1
        if norm and r["record_id"] and not clean(r["ir_source"]):
            cur.execute("UPDATE infection_records SET isolation_source=? WHERE record_id=?", (norm, r["record_id"]))
            changes["infection_records.isolation_source"] += 1
        if norm and r["collection_id"] and not clean(r["source_type"]):
            cur.execute("UPDATE sample_collections SET source_type=? WHERE collection_id=?", (norm, r["collection_id"]))
            changes["sample_collections.source_type"] += 1

        date = clean(row.get("collection_date")) or clean(r["collection_date"])
        if date and r["collection_id"]:
            if not clean(r["c_date"]):
                cur.execute("UPDATE sample_collections SET collection_date=? WHERE collection_id=?", (date, r["collection_id"]))
                changes["sample_collections.collection_date"] += 1
            yr = year_from_date(date)
            if yr and not clean(r["collection_year"]):
                cur.execute("UPDATE sample_collections SET collection_year=? WHERE collection_id=?", (yr, r["collection_id"]))
                changes["sample_collections.collection_year"] += 1

        text = " ".join(str(x or "") for x in row.values())
        biosample = re.search(r"\bSAM[DEN][A-Z]?\d+\b", text)
        bioproject = re.search(r"\bPRJ[DEN][A-Z]?\d+\b", text)
        if biosample or bioproject:
            exists = cur.execute(
                "SELECT 1 FROM biosample_links WHERE isolate_id=? AND COALESCE(biosample_accession,'')=? AND COALESCE(bioproject_accession,'')=?",
                (r["isolate_id"], biosample.group(0) if biosample else "", bioproject.group(0) if bioproject else ""),
            ).fetchone()
            if not exists:
                cur.execute(
                    """
                    INSERT INTO biosample_links
                    (isolate_id, accession, biosample_accession, bioproject_accession, source_text, match_confidence)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        r["isolate_id"],
                        acc,
                        biosample.group(0) if biosample else None,
                        bioproject.group(0) if bioproject else None,
                        text[:1000],
                        "high",
                    ),
                )
                changes["biosample_links.rows"] += 1

    # Backfill GO terms from UniProt annotations into a normalized local table.
    inserted_go = 0
    for r in cur.execute(
        """
        SELECT u.uniprot_id, u.ncbi_protein_acc, u.go_terms, vp.protein_id
        FROM uniprot_annotations u
        LEFT JOIN viral_proteins vp ON vp.protein_accession=u.ncbi_protein_acc
        WHERE u.go_terms IS NOT NULL AND trim(u.go_terms)!=''
        """
    ).fetchall():
        try:
            terms = json.loads(r["go_terms"])
        except Exception:
            terms = []
        for term in terms:
            go_id = clean(term.get("go_id") if isinstance(term, dict) else None)
            go_term = clean(term.get("go_term") if isinstance(term, dict) else None)
            if not go_id:
                continue
            namespace = None
            name = go_term
            if go_term and ":" in go_term:
                prefix, rest = go_term.split(":", 1)
                namespace = {"C": "cellular_component", "F": "molecular_function", "P": "biological_process"}.get(prefix, prefix)
                name = rest
            exists = cur.execute(
                "SELECT 1 FROM interpro_go_terms WHERE protein_id IS ? AND go_id=? AND evidence_source='UniProt'",
                (r["protein_id"], go_id),
            ).fetchone()
            if not exists:
                cur.execute(
                    """
                    INSERT INTO interpro_go_terms
                    (protein_id, interpro_id, go_id, go_name, go_namespace, evidence_source)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (r["protein_id"], None, go_id, name, namespace, "UniProt"),
                )
                inserted_go += 1
    changes["interpro_go_terms.uniprot_backfill"] = inserted_go

    # Queue UniProt-linked proteins that still lack InterPro entries.
    cur.execute("DELETE FROM interpro_go_backfill_queue")
    cur.execute(
        """
        INSERT INTO interpro_go_backfill_queue (protein_id, ncbi_protein_acc, uniprot_id, reason)
        SELECT DISTINCT vp.protein_id, u.ncbi_protein_acc, u.uniprot_id, 'has_uniprot_but_missing_interpro'
        FROM uniprot_annotations u
        LEFT JOIN viral_proteins vp ON vp.protein_accession=u.ncbi_protein_acc
        LEFT JOIN interpro_annotations ia ON ia.uniprot_id=u.uniprot_id
        WHERE u.uniprot_id IS NOT NULL AND trim(u.uniprot_id)!=''
          AND ia.interpro_anno_id IS NULL
        """
    )
    changes["interpro_go_backfill_queue.rows"] = cur.rowcount

    # Export remote lookup worklists.
    outdir = DOWNLOADS / f"phase2_worklists_{RUN_TS}"
    outdir.mkdir(parents=True, exist_ok=True)
    worklists = {
        "isolation_source_review.tsv": "SELECT * FROM data_gap_queue WHERE gap_type IN ('review_inferred_isolation_source','missing_isolation_source') ORDER BY priority, queue_id",
        "geo_remote_lookup.tsv": "SELECT * FROM data_gap_queue WHERE gap_type IN ('missing_collection_record','missing_coordinates') ORDER BY priority, queue_id",
        "interpro_remote_queue.tsv": "SELECT * FROM interpro_go_backfill_queue ORDER BY queue_id LIMIT 5000",
        "biosample_links.tsv": "SELECT * FROM biosample_links ORDER BY link_id",
    }
    for name, sql in worklists.items():
        rows = cur.execute(sql).fetchall()
        path = outdir / name
        with path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f, delimiter="\t")
            if rows:
                writer.writerow(rows[0].keys())
                for row in rows:
                    writer.writerow([row[k] for k in row.keys()])
            else:
                writer.writerow(["empty"])

    metrics = [
        metric(cur, "target_collection_date", "SELECT COUNT(*) FROM analysis_target_isolates i LEFT JOIN sample_metadata m ON m.isolate_id=i.isolate_id WHERE m.collection_date IS NOT NULL AND trim(m.collection_date)!=''"),
        metric(cur, "target_isolation_source", "SELECT COUNT(*) FROM analysis_target_isolates i LEFT JOIN sample_metadata m ON m.isolate_id=i.isolate_id WHERE m.isolation_source IS NOT NULL AND trim(m.isolation_source)!=''"),
        metric(cur, "target_collection_source_type", "SELECT COUNT(DISTINCT i.isolate_id) FROM analysis_target_isolates i LEFT JOIN infection_records ir ON ir.isolate_id=i.isolate_id LEFT JOIN sample_collections c ON c.collection_id=ir.collection_id WHERE c.source_type IS NOT NULL AND trim(c.source_type)!=''"),
        metric(cur, "target_collection_year", "SELECT COUNT(DISTINCT i.isolate_id) FROM analysis_target_isolates i LEFT JOIN infection_records ir ON ir.isolate_id=i.isolate_id LEFT JOIN sample_collections c ON c.collection_id=ir.collection_id WHERE c.collection_year IS NOT NULL AND trim(c.collection_year)!=''"),
    ]

    report = REPORTS / f"phase2_completeness_report_{RUN_TS}.md"
    report.write_text(
        "# Phase 2 Completeness Deepening Report\n\n"
        f"Generated: {datetime.now().isoformat(timespec='seconds')}\n\n"
        "## Changes\n\n"
        + "\n".join(f"- {k}: {v}" for k, v in sorted(changes.items()))
        + "\n\n## Metrics\n\n"
        + "\n".join(f"- {name}: {num}/{den} ({pct}%)" for name, num, den, pct in metrics)
        + f"\n\n## Worklists\n\n- {outdir}\n",
        encoding="utf-8",
    )
    log(cur, "phase2_completeness_deepening", {"run_ts": RUN_TS, "changes": dict(changes), "worklists": str(outdir)})
    con.commit()
    print(json.dumps({"run_ts": RUN_TS, "changes": changes, "report": str(report), "worklists": str(outdir)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
