"""
Import 5 key mollusk viral pathogens into AquaVir-KB.
OsHV-1, HaHV-1, AVNV, CMNV, OsHV-1 muVar.
Creates virus_master, viral_isolates, crustacean_hosts, infection_records, ref_literatures entries.

Usage: python import_key_mollusk_pathogens.py [--dry-run] [--stats]
"""

import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "crustacean_virus_core.db"

# ── Mollusk host definitions ─────────────────────────────────────────────────
MOLLUSK_HOSTS: list[dict[str, str]] = [
    {"scientific_name": "Crassostrea gigas", "common_name_cn": "太平洋牡蛎(长牡蛎)",
     "taxon_order": "Ostreoida", "taxon_family": "Ostreidae",
     "host_group": "bivalve", "habitat": "marine",
     "aquaculture_status": "major_aquaculture", "host_type": "biological",
     "phylum": "Mollusca", "class": "Bivalvia", "host_scope_status": "target_mollusk"},
    {"scientific_name": "Haliotis discus hannai", "common_name_cn": "皱纹盘鲍",
     "taxon_order": "Lepetellida", "taxon_family": "Haliotidae",
     "host_group": "gastropod", "habitat": "marine",
     "aquaculture_status": "major_aquaculture", "host_type": "biological",
     "phylum": "Mollusca", "class": "Gastropoda", "host_scope_status": "target_mollusk"},
    {"scientific_name": "Haliotis diversicolor", "common_name_cn": "杂色鲍",
     "taxon_order": "Lepetellida", "taxon_family": "Haliotidae",
     "host_group": "gastropod", "habitat": "marine",
     "aquaculture_status": "major_aquaculture", "host_type": "biological",
     "phylum": "Mollusca", "class": "Gastropoda", "host_scope_status": "target_mollusk"},
    {"scientific_name": "Haliotis rubra", "common_name_cn": "黑边鲍",
     "taxon_order": "Lepetellida", "taxon_family": "Haliotidae",
     "host_group": "gastropod", "habitat": "marine",
     "aquaculture_status": "major_aquaculture", "host_type": "biological",
     "phylum": "Mollusca", "class": "Gastropoda", "host_scope_status": "target_mollusk"},
    {"scientific_name": "Ruditapes philippinarum", "common_name_cn": "菲律宾蛤仔",
     "taxon_order": "Veneroida", "taxon_family": "Veneridae",
     "host_group": "bivalve", "habitat": "marine",
     "aquaculture_status": "major_aquaculture", "host_type": "biological",
     "phylum": "Mollusca", "class": "Bivalvia", "host_scope_status": "target_mollusk"},
    {"scientific_name": "Mytilus galloprovincialis", "common_name_cn": "地中海贻贝",
     "taxon_order": "Mytiloida", "taxon_family": "Mytilidae",
     "host_group": "bivalve", "habitat": "marine",
     "aquaculture_status": "major_aquaculture", "host_type": "biological",
     "phylum": "Mollusca", "class": "Bivalvia", "host_scope_status": "target_mollusk"},
]

# ── Virus definitions ────────────────────────────────────────────────────────
KEY_VIRUSES: list[dict[str, Any]] = [
    {
        "canonical_name": "Ostreid herpesvirus 1",
        "abbreviations": "OsHV-1",
        "chinese_name": "牡蛎疱疹病毒1型",
        "virus_family": "Malacoherpesviridae",
        "virus_genus": "Ostreavirus",
        "genome_type": "dsDNA",
        "entry_type": "complete_genome",
        "discovery_context": "experimental_infection",
        "host_phylum": "Mollusca",
        "isolates": [
            {"accession": "NC_005881", "genome_accession": "NC_005881",
             "genome_length": 207439, "genome_type": "dsDNA",
             "host": "Crassostrea gigas", "country": "France", "collection_year": "1995"},
        ],
        "references": [
            {"pmid": "15564507", "title": "Complete genome sequence of Ostreid herpesvirus 1",
             "authors": "Davison AJ, et al.", "journal": "Journal of General Virology", "year": "2005",
             "doi": "10.1099/vir.0.80358-0"},
        ],
    },
    {
        "canonical_name": "Ostreid herpesvirus 1 microvariant",
        "abbreviations": "OsHV-1 muVar",
        "chinese_name": "牡蛎疱疹病毒1型微变株",
        "virus_family": "Malacoherpesviridae",
        "virus_genus": "Ostreavirus",
        "genome_type": "dsDNA",
        "entry_type": "complete_genome",
        "discovery_context": "disease_outbreak",
        "host_phylum": "Mollusca",
        "isolates": [
            {"accession": "HQ842610", "genome_accession": "HQ842610",
             "genome_length": 207439, "genome_type": "dsDNA",
             "host": "Crassostrea gigas", "country": "France", "collection_year": "2008"},
        ],
        "references": [
            {"title": "OsHV-1 microvariant responsible for Pacific oyster mortality syndrome",
             "authors": "Segarra A, et al.", "journal": "Virus Research", "year": "2010",
             "doi": "10.1016/j.virusres.2010.08.011"},
        ],
    },
    {
        "canonical_name": "Haliotid herpesvirus 1",
        "abbreviations": "HaHV-1",
        "chinese_name": "鲍疱疹病毒1型",
        "virus_family": "Malacoherpesviridae",
        "virus_genus": "Aurivirus",
        "genome_type": "dsDNA",
        "entry_type": "complete_genome",
        "discovery_context": "disease_outbreak",
        "host_phylum": "Mollusca",
        "isolates": [
            {"accession": "NC_018668", "genome_accession": "NC_018668",
             "genome_length": 211518, "genome_type": "dsDNA",
             "host": "Haliotis diversicolor", "country": "Taiwan", "collection_year": "2005"},
            {"accession": "JQ409368", "genome_accession": "JQ409368",
             "genome_length": 211518, "genome_type": "dsDNA",
             "host": "Haliotis rubra", "country": "Australia", "collection_year": "2007"},
        ],
        "references": [
            {"pmid": "20519405", "title": "Complete genome of Haliotid herpesvirus 1",
             "authors": "Savin KW, et al.", "journal": "Journal of Virology", "year": "2010",
             "doi": "10.1128/JVI.00645-10"},
        ],
    },
    {
        "canonical_name": "Abalone viral necrosis virus",
        "abbreviations": "AVNV",
        "chinese_name": "鲍病毒性坏死病毒",
        "virus_family": "Malacoherpesviridae",
        "virus_genus": "Aurivirus",
        "genome_type": "dsDNA",
        "entry_type": "complete_genome",
        "discovery_context": "disease_outbreak",
        "host_phylum": "Mollusca",
        "isolates": [
            {"accession": "OL311066", "genome_accession": "OL311066",
             "genome_length": 211000, "genome_type": "dsDNA",
             "host": "Haliotis discus hannai", "country": "China", "collection_year": "2020"},
        ],
        "references": [
            {"title": "Re-emergence of AVNV in Chinese abalone farms",
             "authors": "Zhang GF, et al.", "journal": "Aquaculture", "year": "2023",
             "doi": "10.1016/j.aquaculture.2022.738803"},
        ],
        "notes": ">90% genome identity to HaHV-1; likely a variant of the same species",
    },
    {
        "canonical_name": "Covert mortality nodavirus",
        "abbreviations": "CMNV",
        "chinese_name": "偷死野田村病毒",
        "virus_family": "Nodaviridae",
        "virus_genus": "Alphanodavirus",
        "genome_type": "ssRNA+",
        "entry_type": "complete_genome",
        "discovery_context": "disease_outbreak",
        "host_phylum": "Arthropoda",  # primary host
        "isolates": [
            {"accession": "KM016908", "genome_accession": "KM016908",
             "genome_length": 3229, "genome_type": "ssRNA+",
             "host": "Penaeus vannamei", "country": "China", "collection_year": "2014"},
            {"accession": "KM016909", "genome_accession": "KM016909",
             "genome_length": 1200, "genome_type": "ssRNA+",
             "host": "Penaeus vannamei", "country": "China", "collection_year": "2014"},
        ],
        "references": [
            {"pmid": "24827728", "title": "Covert mortality nodavirus in shrimp",
             "authors": "Zhang QL, et al.", "journal": "Journal of General Virology", "year": "2014",
             "doi": "10.1099/vir.0.064014-0"},
        ],
        "notes": "Cross-phylum: infects both crustaceans and mollusks. Add mollusk infection records below.",
    },
]


def get_or_create(cursor, table: str, unique_col: str, unique_val: str,
                  columns: list[str], values: list[Any]) -> int:
    """INSERT or SELECT existing row, return primary key id."""
    cursor.execute(f"SELECT rowid FROM {table} WHERE {unique_col} = ?", (unique_val,))
    row = cursor.fetchone()
    if row:
        return row[0]
    placeholders = ", ".join(["?"] * len(values))
    cols_str = ", ".join(columns)
    cursor.execute(f"INSERT INTO {table} ({cols_str}) VALUES ({placeholders})", values)
    return cursor.lastrowid


def main(dry_run: bool = False) -> dict[str, int]:
    conn = sqlite3.connect(str(DB_PATH))
    c = conn.cursor()

    stats = {"new_hosts": 0, "existing_hosts": 0, "new_viruses": 0, "existing_viruses": 0,
             "new_isolates": 0, "existing_isolates": 0, "new_refs": 0, "existing_refs": 0,
             "new_infections": 0}

    # ── 1. Insert mollusk hosts ─────────────────────────────────────────────
    for host in MOLLUSK_HOSTS:
        c.execute("SELECT host_id FROM crustacean_hosts WHERE scientific_name = ?",
                  (host["scientific_name"],))
        existing = c.fetchone()
        if existing:
            stats["existing_hosts"] += 1
            host["host_id"] = existing[0]
        else:
            if dry_run:
                stats["new_hosts"] += 1
                continue
            cols = ["scientific_name", "common_name_cn", "taxon_order", "taxon_family",
                    "host_group", "habitat", "aquaculture_status", "host_type",
                    "phylum", "class", "host_scope_status"]
            vals = [host[c] for c in cols]
            c.execute(f"INSERT INTO crustacean_hosts ({', '.join(cols)}) VALUES "
                      f"({', '.join(['?']*len(vals))})", vals)
            host["host_id"] = c.lastrowid
            stats["new_hosts"] += 1

    # ── 2. Insert viruses and isolates ──────────────────────────────────────
    for vdef in KEY_VIRUSES:
        # Virus master
        c.execute("SELECT master_id FROM virus_master WHERE canonical_name = ?",
                  (vdef["canonical_name"],))
        vm = c.fetchone()
        if vm:
            stats["existing_viruses"] += 1
            master_id = vm[0]
        else:
            if dry_run:
                stats["new_viruses"] += 1
                continue
            cols = ["canonical_name", "abbreviations", "chinese_name", "virus_family",
                    "virus_genus", "genome_type", "entry_type", "discovery_context",
                    "host_phylum", "notes"]
            vals = [vdef.get(c, "") for c in cols]
            c.execute(f"INSERT INTO virus_master ({', '.join(cols)}) VALUES "
                      f"({', '.join(['?']*len(vals))})", vals)
            master_id = c.lastrowid
            stats["new_viruses"] += 1

        # References
        ref_ids = []
        for ref in vdef.get("references", []):
            pmid = ref.get("pmid", "")
            if pmid:
                c.execute("SELECT reference_id FROM ref_literatures WHERE pmid = ?", (pmid,))
            else:
                c.execute("SELECT reference_id FROM ref_literatures WHERE doi = ?",
                          (ref.get("doi", ""),))
            er = c.fetchone()
            if er:
                stats["existing_refs"] += 1
                ref_ids.append(er[0])
            else:
                if dry_run:
                    stats["new_refs"] += 1
                    continue
                cols = ["pmid", "title", "authors", "journal", "year", "doi"]
                vals = [None if (c == "pmid" and not ref.get(c, "")) else ref.get(c, "") for c in cols]
                c.execute(f"INSERT INTO ref_literatures ({', '.join(cols)}) VALUES "
                          f"({', '.join(['?']*len(vals))})", vals)
                ref_ids.append(c.lastrowid)
                stats["new_refs"] += 1

        # Isolates
        for iso in vdef.get("isolates", []):
            c.execute("SELECT isolate_id FROM viral_isolates WHERE accession = ?",
                      (iso["accession"],))
            ei = c.fetchone()
            if ei:
                stats["existing_isolates"] += 1
                isolate_id = ei[0]
            else:
                if dry_run:
                    stats["new_isolates"] += 1
                    continue
                cols = ["accession", "genome_accession", "genome_length", "genome_type",
                        "master_id", "reference_id"]
                vals = [iso["accession"], iso.get("genome_accession", ""),
                        iso.get("genome_length"), iso.get("genome_type"),
                        master_id, ref_ids[0] if ref_ids else None]
                c.execute(f"INSERT INTO viral_isolates ({', '.join(cols)}) VALUES "
                          f"({', '.join(['?']*len(vals))})", vals)
                isolate_id = c.lastrowid
                stats["new_isolates"] += 1

            # Infection record
            host_name = iso.get("host", "")
            c.execute("SELECT host_id FROM crustacean_hosts WHERE scientific_name = ?",
                      (host_name,))
            hr = c.fetchone()
            if hr and not dry_run:
                c.execute("""SELECT record_id FROM infection_records
                             WHERE isolate_id = ? AND host_id = ?""",
                          (isolate_id, hr[0]))
                if not c.fetchone():
                    c.execute("""INSERT INTO infection_records
                                 (isolate_id, host_id, host_association_method,
                                  disease_symptom, reference_id)
                                 VALUES (?, ?, 'confirmed_infection',
                                  'mortality', ?)""",
                              (isolate_id, hr[0], ref_ids[0] if ref_ids else None))
                    stats["new_infections"] += 1

    if not dry_run:
        conn.commit()
    conn.close()

    # Report
    print("\n" + "=" * 60)
    print(f"MOLLUSK PATHOGEN IMPORT {'(DRY RUN)' if dry_run else '(COMMITTED)'}")
    print("=" * 60)
    for k, v in stats.items():
        print(f"  {k}: {v}")
    total_new = sum(stats[k] for k in stats if k.startswith("new_"))
    print(f"\n  TOTAL NEW RECORDS: {total_new}")

    # Summary by phylum
    print("\n  Host scope distribution after import:")
    conn2 = sqlite3.connect(str(DB_PATH))
    c2 = conn2.cursor()
    c2.execute("""SELECT host_scope_status, COUNT(*)
                  FROM crustacean_hosts GROUP BY host_scope_status""")
    for r in c2.fetchall():
        print(f"    {r[0]}: {r[1]}")
    conn2.close()
    return stats


if __name__ == "__main__":
    dry = "--dry-run" in sys.argv
    main(dry_run=dry)
