import csv
import sqlite3
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent
DB = BASE / "crustacean_virus_core.db"
OUT = BASE / "downloads" / f"data_dictionary_dashboard_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
OUT.mkdir(parents=True, exist_ok=True)

con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row
cur = con.cursor()

tables = [
    r["name"]
    for r in cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    )
]

with (OUT / "data_dictionary.csv").open("w", encoding="utf-8-sig", newline="") as f:
    writer = csv.writer(f)
    writer.writerow(["table_name", "column_name", "type", "not_null", "default_value", "primary_key", "row_count"])
    for table in tables:
        n = cur.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
        for c in cur.execute(f'PRAGMA table_info("{table}")'):
            writer.writerow([table, c["name"], c["type"], c["notnull"], c["dflt_value"], c["pk"], n])

target_total = cur.execute("SELECT COUNT(*) FROM analysis_target_isolates").fetchone()[0]
metrics = [
    ("target_accession", "SELECT COUNT(*) FROM analysis_target_isolates WHERE accession IS NOT NULL AND trim(accession)!=''", target_total),
    ("target_genome_type", "SELECT COUNT(*) FROM analysis_target_isolates WHERE genome_type IS NOT NULL AND trim(genome_type)!=''", target_total),
    ("target_sequence_length", "SELECT COUNT(*) FROM analysis_target_isolates WHERE sequence_length IS NOT NULL AND sequence_length>0", target_total),
    ("target_sample_metadata", "SELECT COUNT(*) FROM analysis_target_isolates i JOIN sample_metadata m ON m.isolate_id=i.isolate_id", target_total),
    ("target_host_name", "SELECT COUNT(*) FROM analysis_target_isolates i LEFT JOIN sample_metadata m ON m.isolate_id=i.isolate_id WHERE m.host_name IS NOT NULL AND trim(m.host_name)!=''", target_total),
    ("target_collection_date", "SELECT COUNT(*) FROM analysis_target_isolates i LEFT JOIN sample_metadata m ON m.isolate_id=i.isolate_id WHERE m.collection_date IS NOT NULL AND trim(m.collection_date)!=''", target_total),
    ("target_isolation_source", "SELECT COUNT(*) FROM analysis_target_isolates i LEFT JOIN sample_metadata m ON m.isolate_id=i.isolate_id WHERE m.isolation_source IS NOT NULL AND trim(m.isolation_source)!=''", target_total),
    ("target_geo_loc_name", "SELECT COUNT(*) FROM analysis_target_isolates i LEFT JOIN sample_metadata m ON m.isolate_id=i.isolate_id WHERE m.geo_loc_name IS NOT NULL AND trim(m.geo_loc_name)!=''", target_total),
    ("target_collection_country", "SELECT COUNT(DISTINCT i.isolate_id) FROM analysis_target_isolates i LEFT JOIN infection_records ir ON ir.isolate_id=i.isolate_id LEFT JOIN sample_collections c ON c.collection_id=ir.collection_id WHERE c.country IS NOT NULL AND trim(c.country)!=''", target_total),
    ("target_collection_coordinates", "SELECT COUNT(DISTINCT i.isolate_id) FROM analysis_target_isolates i LEFT JOIN infection_records ir ON ir.isolate_id=i.isolate_id LEFT JOIN sample_collections c ON c.collection_id=ir.collection_id WHERE c.latitude IS NOT NULL AND c.longitude IS NOT NULL", target_total),
    ("target_collection_year", "SELECT COUNT(DISTINCT i.isolate_id) FROM analysis_target_isolates i LEFT JOIN infection_records ir ON ir.isolate_id=i.isolate_id LEFT JOIN sample_collections c ON c.collection_id=ir.collection_id WHERE c.collection_year IS NOT NULL AND trim(c.collection_year)!=''", target_total),
    ("target_source_type", "SELECT COUNT(DISTINCT i.isolate_id) FROM analysis_target_isolates i LEFT JOIN infection_records ir ON ir.isolate_id=i.isolate_id LEFT JOIN sample_collections c ON c.collection_id=ir.collection_id WHERE c.source_type IS NOT NULL AND trim(c.source_type)!=''", target_total),
    ("host_taxonomy_profiles", "SELECT COUNT(*) FROM host_taxonomy_profiles", cur.execute("SELECT COUNT(*) FROM crustacean_hosts").fetchone()[0]),
    ("sra_runs", "SELECT COUNT(*) FROM sra_runs", None),
    ("biosample_links", "SELECT COUNT(*) FROM biosample_links", None),
    ("geo_datasets", "SELECT COUNT(*) FROM geo_datasets", None),
    ("geo_virus_links", "SELECT COUNT(*) FROM geo_virus_links", None),
    ("interpro_annotations", "SELECT COUNT(*) FROM interpro_annotations", None),
    ("interpro_go_terms", "SELECT COUNT(*) FROM interpro_go_terms", None),
    ("uniprot_protein_links", "SELECT COUNT(*) FROM uniprot_protein_links", None),
    ("foreign_key_violations", "PRAGMA foreign_key_check", 0),
]

with (OUT / "completeness_dashboard.csv").open("w", encoding="utf-8-sig", newline="") as f:
    writer = csv.writer(f)
    writer.writerow(["metric", "value", "denominator", "pct"])
    for name, sql, den in metrics:
        rows = cur.execute(sql).fetchall()
        value = len(rows) if name == "foreign_key_violations" else rows[0][0]
        pct = "" if not den else round(value * 100 / den, 2)
        writer.writerow([name, value, den if den is not None else "", pct])

controlled = {
    "coordinate_precision": ["reported_lat_lon", "exact", "site", "city_centroid", "province_centroid", "country_centroid", "unknown"],
    "curation_status": ["needs_review", "manual_checked", "auto_seeded", "rejected", "preprint_parent_stub"],
    "match_confidence": ["high", "medium", "low"],
    "source_type": ["whole organism", "gill", "hepatopancreas", "hemolymph", "muscle", "pleopod", "epidermis", "cuticle", "water", "pond", "mixed tissues", "infected tissues"],
}
with (OUT / "controlled_vocab_seed.csv").open("w", encoding="utf-8-sig", newline="") as f:
    writer = csv.writer(f)
    writer.writerow(["vocabulary", "term"])
    for vocab, terms in controlled.items():
        for term in terms:
            writer.writerow([vocab, term])

(OUT / "README.md").write_text(
    "# Data Dictionary and Completeness Dashboard\n\n"
    f"Generated: {datetime.now().isoformat(timespec='seconds')}\n\n"
    "- `data_dictionary.csv`: table and column inventory.\n"
    "- `completeness_dashboard.csv`: metrics for dashboard cards.\n"
    "- `controlled_vocab_seed.csv`: seed controlled vocabulary for curation UI.\n",
    encoding="utf-8",
)

print({"out": str(OUT), "tables": len(tables), "target_total": target_total})
