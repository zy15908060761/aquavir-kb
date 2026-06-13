import argparse
import csv
import json
import re
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path


APP_DIR = Path(__file__).resolve().parent
DB_PATH = APP_DIR / "crustacean_virus_core.db"
REPORT_DIR = APP_DIR / "reports"
NCBI_METADATA_CSV = APP_DIR / "ncbi_metadata" / "crustacean_virus_metadata.csv"
RUN_TS = datetime.now().strftime("%Y%m%d_%H%M%S")


UNKNOWN = {"", "na", "n/a", "none", "null", "unknown", "not provided", "not available", "-"}


COUNTRY_ALIASES = {
    "usa": "United States",
    "u.s.a.": "United States",
    "u.s.": "United States",
    "united states of america": "United States",
    "pr china": "China",
    "p.r. china": "China",
    "people's republic of china": "China",
    "viet nam": "Vietnam",
    "south korea": "South Korea",
    "republic of korea": "South Korea",
    "taiwan": "Taiwan",
    "iran": "Iran",
}


HOST_TAXON_HINTS = {
    "penaeus vannamei": 6689,
    "litopenaeus vannamei": 6689,
    "penaeus monodon": 6687,
    "macrobrachium rosenbergii": 79674,
    "procambarus clarkii": 6728,
    "eriocheir sinensis": 95602,
    "scylla paramamosain": 85552,
    "scylla serrata": 6761,
    "callinectes sapidus": 6763,
    "carcinus maenas": 6759,
    "portunus trituberculatus": 210409,
    "marsupenaeus japonicus": 27405,
    "fenneropenaeus chinensis": 139456,
    "exopalaemon carinicauda": 392228,
}


def connect():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    return con


def table_exists(cur, table):
    return cur.execute(
        "SELECT 1 FROM sqlite_master WHERE type IN ('table','view') AND name=?", (table,)
    ).fetchone() is not None


def columns(cur, table):
    return {r["name"] for r in cur.execute(f'PRAGMA table_info("{table}")')}


def has_cols(cur, table, needed):
    cols = columns(cur, table)
    return all(c in cols for c in needed)


def clean(v):
    if v is None:
        return None
    s = str(v).strip()
    if s.lower() in UNKNOWN:
        return None
    return s


def norm_country(raw):
    s = clean(raw)
    if not s:
        return None
    first = re.split(r"[:;,]", s, maxsplit=1)[0].strip()
    first = re.sub(r"\s+", " ", first)
    return COUNTRY_ALIASES.get(first.lower(), first)


def date_precision(raw):
    s = clean(raw)
    if not s:
        return None
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        return "day"
    if re.fullmatch(r"\d{4}-\d{2}", s):
        return "month"
    if re.fullmatch(r"\d{4}", s):
        return "year"
    if re.search(r"\d{4}", s):
        return "inferred"
    return "text"


def split_lat_lon(raw):
    s = clean(raw)
    if not s:
        return None, None
    nums = re.findall(r"[-+]?\d+(?:\.\d+)?", s)
    if len(nums) < 2:
        return None, None
    lat, lon = float(nums[0]), float(nums[1])
    if re.search(r"\bS\b|south", s, re.I):
        lat = -abs(lat)
    if re.search(r"\bW\b|west", s, re.I):
        lon = -abs(lon)
    return lat, lon


def infer_source_type(text):
    s = (clean(text) or "").lower()
    if not s:
        return None
    rules = [
        ("gill", "gill"),
        ("hepatopancreas", "hepatopancreas"),
        ("hemolymph", "hemolymph"),
        ("haemolymph", "hemolymph"),
        ("muscle", "muscle"),
        ("gut", "gut"),
        ("intestin", "intestine"),
        ("stomach", "stomach"),
        ("ovary", "ovary"),
        ("larva", "larvae"),
        ("postlarva", "postlarvae"),
        ("feces", "feces"),
        ("faeces", "feces"),
        ("water", "water"),
        ("pond", "pond"),
        ("farm", "farm"),
        ("sediment", "sediment"),
        ("whole", "whole organism"),
    ]
    for needle, value in rules:
        if needle in s:
            return value
    if "shrimp" in s or "crab" in s or "crayfish" in s or "prawn" in s:
        return "host organism"
    return s[:80]


def source_confidence(source):
    if not source:
        return None
    if source in {
        "gill",
        "hepatopancreas",
        "hemolymph",
        "muscle",
        "intestine",
        "stomach",
        "ovary",
        "larvae",
        "postlarvae",
        "feces",
        "water",
        "pond",
        "sediment",
        "whole organism",
    }:
        return "medium"
    if source in {"host organism", "farm"}:
        return "low"
    return "low"


def profile(cur):
    out = {}
    total = cur.execute("SELECT COUNT(*) FROM analysis_target_isolates").fetchone()[0]
    out["target_isolates"] = total
    checks = {
        "genome_type": "genome_type IS NOT NULL AND trim(genome_type)<>''",
        "sequence_length": "sequence_length IS NOT NULL AND sequence_length>0",
        "sample_metadata": "m.isolate_id IS NOT NULL",
        "host_name": "m.host_name IS NOT NULL AND trim(m.host_name)<>''",
        "geo_loc_name": "m.geo_loc_name IS NOT NULL AND trim(m.geo_loc_name)<>''",
        "collection_date": "m.collection_date IS NOT NULL AND trim(m.collection_date)<>''",
        "isolation_source": "m.isolation_source IS NOT NULL AND trim(m.isolation_source)<>''",
        "ncbi_taxid": "m.ncbi_taxid IS NOT NULL",
    }
    for label, where in checks.items():
        if label in {"genome_type", "sequence_length"}:
            sql = f"SELECT COUNT(*) FROM analysis_target_isolates WHERE {where}"
        else:
            sql = (
                "SELECT COUNT(*) FROM analysis_target_isolates i "
                "LEFT JOIN sample_metadata m ON m.isolate_id=i.isolate_id "
                f"WHERE {where}"
            )
        n = cur.execute(sql).fetchone()[0]
        out[label] = {"n": n, "pct": round(n * 100 / total, 1) if total else 0}

    geo = {
        "collection_row": "c.collection_id IS NOT NULL",
        "country": "c.country IS NOT NULL AND trim(c.country)<>''",
        "lat_lon": "c.latitude IS NOT NULL AND c.longitude IS NOT NULL",
    }
    for label, where in geo.items():
        n = cur.execute(
            "SELECT COUNT(DISTINCT i.isolate_id) FROM analysis_target_isolates i "
            "LEFT JOIN infection_records ir ON ir.isolate_id=i.isolate_id "
            "LEFT JOIN sample_collections c ON c.collection_id=ir.collection_id "
            f"WHERE {where}"
        ).fetchone()[0]
        out[f"geo_{label}"] = {"n": n, "pct": round(n * 100 / total, 1) if total else 0}

    for table in [
        "host_taxonomy_profiles",
        "host_ecological_traits",
        "evidence_review_priority_queue",
        "interpro_annotations",
        "interpro_go_terms",
        "sra_runs",
        "pride_virus_links",
    ]:
        if table_exists(cur, table):
            out[table] = cur.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
    return out


def load_metadata_csv():
    by_acc = {}
    if not NCBI_METADATA_CSV.exists():
        return by_acc
    with NCBI_METADATA_CSV.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            acc = clean(row.get("accession") or row.get("Accession") or row.get("genome_accession"))
            if acc:
                by_acc[acc] = row
    return by_acc


def pick(row, *names):
    lower = {k.lower(): k for k in row.keys()}
    for name in names:
        key = lower.get(name.lower())
        if key is not None:
            val = clean(row.get(key))
            if val:
                return val
    return None


def ensure_table(cur):
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS completeness_optimization_log (
            log_id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_ts TEXT NOT NULL,
            priority INTEGER NOT NULL,
            target_table TEXT NOT NULL,
            target_id TEXT,
            field_name TEXT NOT NULL,
            old_value TEXT,
            new_value TEXT,
            source TEXT NOT NULL,
            confidence TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS data_gap_queue (
            queue_id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_ts TEXT NOT NULL,
            priority INTEGER NOT NULL,
            entity_type TEXT NOT NULL,
            entity_id TEXT,
            accession TEXT,
            gap_type TEXT NOT NULL,
            suggested_source TEXT,
            status TEXT DEFAULT 'open',
            notes TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS release_manifest (
            manifest_id INTEGER PRIMARY KEY AUTOINCREMENT,
            release_name TEXT NOT NULL,
            generated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            table_name TEXT NOT NULL,
            row_count INTEGER,
            export_path TEXT,
            notes TEXT
        )
        """
    )


def log(cur, priority, table, target_id, field, old, new, source, confidence="high"):
    cur.execute(
        """
        INSERT INTO completeness_optimization_log
        (run_ts, priority, target_table, target_id, field_name, old_value, new_value, source, confidence)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (RUN_TS, priority, table, str(target_id) if target_id is not None else None, field, old, new, source, confidence),
    )


def queue_gap(cur, priority, entity_type, entity_id, accession, gap_type, suggested_source, notes=None):
    cur.execute(
        """
        INSERT INTO data_gap_queue
        (run_ts, priority, entity_type, entity_id, accession, gap_type, suggested_source, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (RUN_TS, priority, entity_type, str(entity_id) if entity_id is not None else None, accession, gap_type, suggested_source, notes),
    )


def update_if_empty(cur, table, key_col, key_val, field, new_value, priority, source, confidence="high"):
    new_value = clean(new_value)
    if not new_value:
        return 0
    old = cur.execute(
        f'SELECT "{field}" FROM "{table}" WHERE "{key_col}"=?', (key_val,)
    ).fetchone()
    if old is None:
        return 0
    old_val = clean(old[0])
    if old_val:
        return 0
    cur.execute(f'UPDATE "{table}" SET "{field}"=? WHERE "{key_col}"=?', (new_value, key_val))
    log(cur, priority, table, key_val, field, old_val, new_value, source, confidence)
    return 1


def optimize_sample_metadata(cur, metadata):
    changes = Counter()
    rows = cur.execute(
        """
        SELECT i.isolate_id, i.accession, i.genome_type, i.sequence_length,
               m.host_name, m.collection_date, m.isolation_source, m.geo_loc_name,
               m.lat_lon, m.ncbi_taxid, m.raw_notes
        FROM analysis_target_isolates i
        LEFT JOIN sample_metadata m ON m.isolate_id=i.isolate_id
        """
    ).fetchall()
    for r in rows:
        acc = r["accession"]
        meta = metadata.get(acc, {})
        if r["isolate_id"] is not None and r["host_name"] is None and not meta:
            pass

        source_candidates = [
            r["isolation_source"],
            pick(meta, "isolation_source", "source", "host tissue", "tissue", "sample source"),
            r["raw_notes"],
            pick(meta, "definition", "title", "organism", "host"),
        ]
        inferred_source = next((infer_source_type(x) for x in source_candidates if infer_source_type(x)), None)
        if inferred_source:
            confidence = source_confidence(inferred_source)
            if confidence == "medium":
                changes["sample_metadata.isolation_source"] += update_if_empty(
                    cur,
                    "sample_metadata",
                    "isolate_id",
                    r["isolate_id"],
                    "isolation_source",
                    inferred_source,
                    1,
                    "metadata/source-text controlled inference",
                    confidence,
                )
            else:
                queue_gap(
                    cur,
                    1,
                    "isolate",
                    r["isolate_id"],
                    acc,
                    "review_inferred_isolation_source",
                    "BioSample/SRA/literature methods",
                    f"inferred={inferred_source}",
                )
                changes["gap.review_inferred_isolation_source"] += 1

        collection_date = pick(meta, "collection_date", "date", "collection date")
        if collection_date:
            changes["sample_metadata.collection_date"] += update_if_empty(
                cur, "sample_metadata", "isolate_id", r["isolate_id"], "collection_date", collection_date, 3, "ncbi_metadata.csv"
            )

        geo = pick(meta, "geo_loc_name", "country", "location", "geo location")
        if geo:
            changes["sample_metadata.geo_loc_name"] += update_if_empty(
                cur, "sample_metadata", "isolate_id", r["isolate_id"], "geo_loc_name", geo, 2, "ncbi_metadata.csv"
            )

        host = pick(meta, "host", "host_name", "isolation host")
        if host:
            changes["sample_metadata.host_name"] += update_if_empty(
                cur, "sample_metadata", "isolate_id", r["isolate_id"], "host_name", host, 4, "ncbi_metadata.csv"
            )

        taxid = pick(meta, "ncbi_taxid", "taxid", "host_taxid")
        if taxid and str(taxid).isdigit():
            old = cur.execute("SELECT ncbi_taxid FROM sample_metadata WHERE isolate_id=?", (r["isolate_id"],)).fetchone()
            if old and old[0] is None:
                cur.execute("UPDATE sample_metadata SET ncbi_taxid=? WHERE isolate_id=?", (int(taxid), r["isolate_id"]))
                log(cur, 4, "sample_metadata", r["isolate_id"], "ncbi_taxid", None, taxid, "ncbi_metadata.csv")
                changes["sample_metadata.ncbi_taxid"] += 1

    return changes


def optimize_geography(cur):
    changes = Counter()
    rows = cur.execute(
        """
        SELECT i.isolate_id, i.accession, m.geo_loc_name, m.lat_lon, ir.collection_id,
               c.country, c.latitude, c.longitude, c.coordinate_precision
        FROM analysis_target_isolates i
        LEFT JOIN sample_metadata m ON m.isolate_id=i.isolate_id
        LEFT JOIN infection_records ir ON ir.isolate_id=i.isolate_id
        LEFT JOIN sample_collections c ON c.collection_id=ir.collection_id
        """
    ).fetchall()
    for r in rows:
        cid = r["collection_id"]
        if cid is None:
            queue_gap(cur, 2, "isolate", r["isolate_id"], r["accession"], "missing_collection_record", "GenBank/BioSample geo_loc_name")
            continue
        country = norm_country(r["geo_loc_name"])
        if country:
            changes["sample_collections.country"] += update_if_empty(
                cur, "sample_collections", "collection_id", cid, "country", country, 2, "sample_metadata.geo_loc_name"
            )
        lat, lon = split_lat_lon(r["lat_lon"])
        if lat is not None and lon is not None:
            if r["latitude"] is None:
                cur.execute("UPDATE sample_collections SET latitude=? WHERE collection_id=?", (lat, cid))
                log(cur, 2, "sample_collections", cid, "latitude", None, lat, "sample_metadata.lat_lon")
                changes["sample_collections.latitude"] += 1
            if r["longitude"] is None:
                cur.execute("UPDATE sample_collections SET longitude=? WHERE collection_id=?", (lon, cid))
                log(cur, 2, "sample_collections", cid, "longitude", None, lon, "sample_metadata.lat_lon")
                changes["sample_collections.longitude"] += 1
            changes["sample_collections.coordinate_precision"] += update_if_empty(
                cur, "sample_collections", "collection_id", cid, "coordinate_precision", "reported_lat_lon", 2, "sample_metadata.lat_lon"
            )
        elif r["latitude"] is None or r["longitude"] is None:
            queue_gap(cur, 2, "isolate", r["isolate_id"], r["accession"], "missing_coordinates", "GeoNames/geocoding from geo_loc_name", r["geo_loc_name"])
    return changes


def optimize_host_taxonomy(cur):
    changes = Counter()
    if not has_cols(cur, "host_taxonomy_profiles", ["host_id"]):
        return changes
    existing = {r[0] for r in cur.execute("SELECT host_id FROM host_taxonomy_profiles")}
    host_cols = columns(cur, "crustacean_hosts")
    hname_col = "scientific_name" if "scientific_name" in host_cols else "host_name"
    rows = cur.execute(f'SELECT host_id, "{hname_col}" AS name FROM crustacean_hosts').fetchall()
    tax_cols = columns(cur, "host_taxonomy_profiles")
    for r in rows:
        if r["host_id"] in existing:
            continue
        name = clean(r["name"])
        if not name:
            continue
        hint = HOST_TAXON_HINTS.get(name.lower())
        insert_cols = ["host_id"]
        values = [r["host_id"]]
        for col in ["scientific_name", "accepted_name", "canonical_name"]:
            if col in tax_cols:
                insert_cols.append(col)
                values.append(name)
                break
        if hint and "ncbi_taxid" in tax_cols:
            insert_cols.append("ncbi_taxid")
            values.append(hint)
        if "taxonomy_source" in tax_cols:
            insert_cols.append("taxonomy_source")
            values.append("local_high_confidence_taxid_hint" if hint else "queued_for_taxonomy_resolution")
        if "curation_status" in tax_cols:
            insert_cols.append("curation_status")
            values.append("needs_review" if not hint else "auto_seeded")
        placeholders = ",".join(["?"] * len(values))
        cur.execute(
            f'INSERT INTO host_taxonomy_profiles ({",".join(insert_cols)}) VALUES ({placeholders})',
            values,
        )
        log(cur, 4, "host_taxonomy_profiles", r["host_id"], "row", None, name, "crustacean_hosts + local taxid hints", "medium")
        changes["host_taxonomy_profiles.rows"] += 1
        if not hint:
            queue_gap(cur, 4, "host", r["host_id"], None, "missing_host_taxid", "NCBI Taxonomy/WoRMS/GBIF", name)
    return changes


def optimize_virus_master(cur):
    changes = Counter()
    rows = cur.execute(
        """
        SELECT vm.master_id, vm.genome_type AS master_genome_type,
               COUNT(*) AS n,
               MAX(vi.genome_type) AS isolate_genome_type
        FROM virus_master vm
        JOIN viral_isolates vi ON vi.master_id=vm.master_id
        WHERE (vm.genome_type IS NULL OR trim(vm.genome_type)='')
          AND vi.genome_type IS NOT NULL AND trim(vi.genome_type)<>''
        GROUP BY vm.master_id
        """
    ).fetchall()
    for r in rows:
        gt = r["isolate_genome_type"]
        cur.execute("UPDATE virus_master SET genome_type=? WHERE master_id=?", (gt, r["master_id"]))
        log(cur, 5, "virus_master", r["master_id"], "genome_type", None, gt, "viral_isolates consensus", "medium")
        changes["virus_master.genome_type"] += 1

    for r in cur.execute(
        "SELECT isolate_id, accession FROM analysis_target_isolates WHERE genome_type IS NULL OR trim(genome_type)=''"
    ):
        queue_gap(cur, 5, "isolate", r["isolate_id"], r["accession"], "missing_genome_type", "GenBank/ICTV/ViralZone")
    for r in cur.execute(
        "SELECT isolate_id, accession FROM analysis_target_isolates WHERE sequence_length IS NULL OR sequence_length<=0"
    ):
        queue_gap(cur, 5, "isolate", r["isolate_id"], r["accession"], "missing_sequence_length", "GenBank sequence record")
    return changes


def optimize_go_from_interpro(cur):
    changes = Counter()
    if not table_exists(cur, "interpro_go_terms") or not table_exists(cur, "interpro_annotations"):
        return changes
    interpro_cols = columns(cur, "interpro_annotations")
    go_cols = columns(cur, "interpro_go_terms")
    if "go_terms" not in interpro_cols:
        for r in cur.execute("SELECT protein_id FROM viral_proteins LIMIT 2000"):
            queue_gap(cur, 8, "protein", r["protein_id"], None, "missing_interpro_go", "InterProScan/InterPro API")
        return changes
    needed = {"protein_id", "interpro_id", "go_id"}
    if not needed.issubset(go_cols):
        return changes
    for r in cur.execute(
        "SELECT protein_id, interpro_id, go_terms FROM interpro_annotations WHERE go_terms IS NOT NULL AND trim(go_terms)<>''"
    ):
        terms = re.findall(r"GO:\d{7}", r["go_terms"])
        for term in sorted(set(terms)):
            exists = cur.execute(
                "SELECT 1 FROM interpro_go_terms WHERE protein_id=? AND interpro_id=? AND go_id=?",
                (r["protein_id"], r["interpro_id"], term),
            ).fetchone()
            if not exists:
                cur.execute(
                    "INSERT INTO interpro_go_terms (protein_id, interpro_id, go_id) VALUES (?, ?, ?)",
                    (r["protein_id"], r["interpro_id"], term),
                )
                changes["interpro_go_terms.rows"] += 1
    if changes["interpro_go_terms.rows"]:
        log(cur, 8, "interpro_go_terms", "bulk", "rows", None, str(changes["interpro_go_terms.rows"]), "interpro_annotations.go_terms")
    return changes


def optimize_evidence_queue(cur):
    changes = Counter()
    if table_exists(cur, "evidence_review_priority_queue"):
        cur.execute("DELETE FROM evidence_review_priority_queue")
        # Try to preserve current schema by dynamic insertion.
        cols = columns(cur, "evidence_review_priority_queue")
        evidence_cols = columns(cur, "evidence_records")
        rows = cur.execute(
            """
            SELECT evidence_id, evidence_type, virus_master_id, isolate_id, reference_id,
                   claim, evidence_strength, curation_status
            FROM evidence_records
            WHERE curation_status IS NULL OR curation_status<>'manual_checked'
            """
        ).fetchall()
        rank = {"virulence": 1, "mortality": 1, "pathogenicity": 1, "diagnosis": 2, "host_range": 2, "temperature": 3}
        priority_labels = {1: "P1", 2: "P2", 3: "P3", 4: "P4"}
        for r in rows:
            etype = (r["evidence_type"] or "").lower()
            priority = next((p for k, p in rank.items() if k in etype), 4)
            data = {}
            for c in cols:
                if c in evidence_cols:
                    data[c] = r[c] if c in r.keys() else None
            for c, v in {
                "evidence_id": r["evidence_id"],
                "priority": priority_labels.get(priority, "P4"),
                "priority_score": priority,
                "review_priority": priority,
                "queue_status": "open",
                "status": "open",
                "reason": "curation_status not manual_checked",
            }.items():
                if c in cols:
                    data[c] = v
            if data:
                cur.execute(
                    f'INSERT INTO evidence_review_priority_queue ({",".join(data.keys())}) VALUES ({",".join(["?"]*len(data))})',
                    list(data.values()),
                )
                changes["evidence_review_priority_queue.rows"] += 1
    return changes


def build_gap_queue(cur):
    changes = Counter()
    for r in cur.execute(
        """
        SELECT i.isolate_id, i.accession, m.isolation_source, m.collection_date, m.geo_loc_name
        FROM analysis_target_isolates i
        LEFT JOIN sample_metadata m ON m.isolate_id=i.isolate_id
        """
    ):
        if not clean(r["isolation_source"]):
            queue_gap(cur, 1, "isolate", r["isolate_id"], r["accession"], "missing_isolation_source", "GenBank/BioSample/SRA/literature methods")
            changes["gap.missing_isolation_source"] += 1
        if not clean(r["geo_loc_name"]):
            queue_gap(cur, 2, "isolate", r["isolate_id"], r["accession"], "missing_geo_loc_name", "GenBank/BioSample/literature")
            changes["gap.missing_geo_loc_name"] += 1
        if not clean(r["collection_date"]):
            queue_gap(cur, 3, "isolate", r["isolate_id"], r["accession"], "missing_collection_date", "GenBank/BioSample/literature")
            changes["gap.missing_collection_date"] += 1

    for r in cur.execute("SELECT host_id, scientific_name FROM crustacean_hosts"):
        exists = cur.execute("SELECT 1 FROM host_taxonomy_profiles WHERE host_id=?", (r["host_id"],)).fetchone()
        if not exists:
            queue_gap(cur, 4, "host", r["host_id"], None, "missing_host_taxonomy_profile", "NCBI Taxonomy/WoRMS/GBIF", r["scientific_name"])
            changes["gap.missing_host_taxonomy_profile"] += 1

    for table, priority, gap, source in [
        ("sra_runs", 7, "missing_sra_links", "NCBI SRA/BioProject/BioSample"),
        ("pride_virus_links", 7, "missing_pride_virus_links", "PRIDE project text matching + manual review"),
        ("interpro_go_terms", 8, "missing_interpro_go_terms", "InterProScan/InterPro API"),
    ]:
        n = cur.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0] if table_exists(cur, table) else 0
        if n == 0:
            queue_gap(cur, priority, "database", None, None, gap, source, f"{table} has 0 rows")
            changes[f"gap.{gap}"] += 1
    return changes


def export_release_manifest(cur):
    release = f"completeness_release_{RUN_TS}"
    export_dir = APP_DIR / "downloads" / release
    export_dir.mkdir(parents=True, exist_ok=True)
    tables = [
        "virus_master",
        "viral_isolates",
        "crustacean_hosts",
        "host_taxonomy_profiles",
        "sample_metadata",
        "sample_collections",
        "infection_records",
        "ref_literatures",
        "evidence_records",
        "viral_proteins",
        "uniprot_annotations",
        "interpro_annotations",
        "interpro_go_terms",
        "kegg_annotations",
        "data_gap_queue",
        "completeness_optimization_log",
    ]
    exported = 0
    for table in tables:
        if not table_exists(cur, table):
            continue
        rows = cur.execute(f'SELECT * FROM "{table}"').fetchall()
        path = export_dir / f"{table}.tsv"
        cols = [d[0] for d in cur.description]
        with path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f, delimiter="\t")
            writer.writerow(cols)
            for row in rows:
                writer.writerow([row[c] for c in cols])
        cur.execute(
            "INSERT INTO release_manifest (release_name, table_name, row_count, export_path, notes) VALUES (?, ?, ?, ?, ?)",
            (release, table, len(rows), str(path.relative_to(APP_DIR)), "12-priority completeness optimization export"),
        )
        exported += 1
    readme = export_dir / "README_release.md"
    readme.write_text(
        f"# {release}\n\nGenerated: {datetime.now().isoformat(timespec='seconds')}\n\n"
        "This export focuses on database completeness and traceability after the 12-priority optimization pass.\n",
        encoding="utf-8",
    )
    return {"release": release, "export_dir": str(export_dir), "tables": exported}


def write_report(before, after, changes, release_info):
    REPORT_DIR.mkdir(exist_ok=True)
    path = REPORT_DIR / f"12priority_optimization_report_{RUN_TS}.md"
    lines = [
        "# 12-Priority Completeness Optimization Report",
        "",
        f"Generated: {datetime.now().isoformat(timespec='seconds')}",
        f"Database: `{DB_PATH}`",
        "",
        "## Before vs After",
        "",
        "| Metric | Before | After | Delta |",
        "|---|---:|---:|---:|",
    ]
    keys = sorted(set(before) | set(after))
    for k in keys:
        bv = before.get(k)
        av = after.get(k)
        if isinstance(bv, dict) or isinstance(av, dict):
            bn = (bv or {}).get("n", 0)
            an = (av or {}).get("n", 0)
            bp = (bv or {}).get("pct", 0)
            ap = (av or {}).get("pct", 0)
            lines.append(f"| {k} | {bn} ({bp}%) | {an} ({ap}%) | {an-bn:+} |")
        else:
            bn = bv or 0
            an = av or 0
            lines.append(f"| {k} | {bn} | {an} | {an-bn:+} |")
    lines.extend(["", "## Changes Applied", "", "| Change | Count |", "|---|---:|"])
    for k, v in sorted(changes.items()):
        lines.append(f"| {k} | {v} |")
    lines.extend(
        [
            "",
            "## Release Export",
            "",
            f"- Release: `{release_info['release']}`",
            f"- Export directory: `{release_info['export_dir']}`",
            f"- Exported tables: `{release_info['tables']}`",
            "",
            "## Notes",
            "",
            "- This pass only auto-filled fields when the source was already present locally or was a conservative controlled inference.",
            "- Remaining gaps were inserted into `data_gap_queue` with priority and suggested source for auditable follow-up.",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    con = connect()
    cur = con.cursor()
    ensure_table(cur)
    before = profile(cur)
    metadata = load_metadata_csv()

    changes = Counter()
    changes.update(optimize_sample_metadata(cur, metadata))
    changes.update(optimize_geography(cur))
    changes.update(optimize_host_taxonomy(cur))
    changes.update(optimize_virus_master(cur))
    changes.update(optimize_go_from_interpro(cur))
    changes.update(optimize_evidence_queue(cur))
    changes.update(build_gap_queue(cur))
    release_info = export_release_manifest(cur)
    after = profile(cur)
    report = write_report(before, after, changes, release_info)

    if args.dry_run:
        con.rollback()
    else:
        con.commit()
    print(json.dumps({"run_ts": RUN_TS, "dry_run": args.dry_run, "changes": changes, "report": str(report), "release": release_info}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
