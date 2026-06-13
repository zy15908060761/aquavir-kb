#!/usr/bin/env python3
"""
AquaVir-KB Data Dictionary Update
==================================
Updates the v_data_dictionary view with documentation for new fields
added during the aquatic invertebrate expansion migration.
"""

import sqlite3
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "crustacean_virus_core.db")

NEW_FIELD_DOCS = [
    # crustacean_hosts additions
    ("crustacean_hosts", "phylum", "VARCHAR(50)",
     "Taxonomic phylum of the host (e.g., Arthropoda, Mollusca, Echinodermata, Cnidaria). "
     "Added v2.0 for multi-phylum aquatic invertebrate expansion. Backfilled from taxon_order for existing records."),
    ("crustacean_hosts", "class", "VARCHAR(50)",
     "Taxonomic class of the host (e.g., Malacostraca, Bivalvia, Gastropoda, Holothuroidea). "
     "Added v2.0 for multi-phylum expansion."),

    # infection_records additions
    ("infection_records", "host_association_method", "VARCHAR(50)",
     "Evidence quality tier for host-virus association. Values: confirmed_infection (experimental validation), "
     "disease_outbreak (epidemiological evidence), pathology_observation (histopathology), "
     "co_occurrence_metagenomic (default; detected in same sample), environmental_sample (water/sediment source). "
     "Added v2.0."),

    # virus_master additions
    ("virus_master", "discovery_context", "VARCHAR(50)",
     "How the virus was discovered. Values: isolated_and_cultured (traditional virology), "
     "metagenomic_with_host_evidence (sequence + host association evidence), "
     "metagenomic_environmental (default; from environmental sequencing). "
     "Added v2.0."),
    ("virus_master", "host_phylum", "VARCHAR(50)",
     "Primary host phylum associated with this virus. Used for fast filtering by taxonomic scope. "
     "Added v2.0. Backfilled to Arthropoda for all pre-existing records."),
]

NEW_VIEW_DOCS = [
    ("v_host_composition_by_phylum",
     "Summary of host species count by phylum and class, limited to biological hosts. "
     "Added v2.0 for expansion tracking."),
    ("v_virus_discovery_summary",
     "Virus species count by discovery_context and host_phylum. "
     "Added v2.0 for NAR manuscript statistics."),
    ("v_infection_quality",
     "Infection record quality breakdown by host_association_method with unique host/isolate counts. "
     "Added v2.0 for data quality reporting."),
    ("v_host_scope_audit",
     "Per-host audit view with scope_status classification (target_crustacean, target_mollusk, exclude_lab_host, etc.) "
     "and infection record counts. Added v2.0."),
    ("v_nar_database_summary",
     "Single-view summary of key database metrics for NAR manuscript preparation. Added v2.0."),
    ("v_expansion_readiness",
     "Checklist view tracking whether the database is ready for each expansion phase. Added v2.0."),
]

def main():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # Check if v_data_dictionary exists
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='v_data_dictionary'")
    if not cur.fetchone():
        print("v_data_dictionary table not found - creating documentation file instead")
        _write_markdown_docs()
        conn.close()
        return

    # Update data dictionary
    for table, field, dtype, doc in NEW_FIELD_DOCS:
        cur.execute("""
            INSERT OR REPLACE INTO v_data_dictionary (table_name, column_name, data_type, description)
            VALUES (?, ?, ?, ?)
        """, (table, field, dtype, doc))

    conn.commit()
    print(f"Updated {len(NEW_FIELD_DOCS)} field definitions in v_data_dictionary")
    conn.close()

def _write_markdown_docs():
    """Write data dictionary as markdown file."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "DATA_DICTIONARY_EXPANSION.md")
    with open(path, 'w', encoding='utf-8') as f:
        f.write(f"# AquaVir-KB Data Dictionary — Expansion Fields\n\n")
        f.write(f"Generated: {datetime.now().isoformat()}\n\n")

        f.write("## New Columns\n\n")
        f.write("| Table | Column | Type | Description |\n")
        f.write("|-------|--------|------|-------------|\n")
        for table, field, dtype, doc in NEW_FIELD_DOCS:
            f.write(f"| {table} | {field} | {dtype} | {doc} |\n")

        f.write("\n## New Views\n\n")
        f.write("| View | Description |\n")
        f.write("|------|-------------|\n")
        for view, desc in NEW_VIEW_DOCS:
            f.write(f"| {view} | {desc} |\n")

    print(f"Data dictionary written to {path}")

if __name__ == "__main__":
    main()
