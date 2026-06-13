#!/usr/bin/env python3
"""Read-only assessment for literature-driven database backfill.

This script does not modify the SQLite database. It scans existing literature
records and local entities to estimate which gaps can be filled from the
already ingested reference corpus.
"""

from __future__ import annotations

import csv
import json
import re
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "crustacean_virus_core.db"
OUT_DIR = ROOT / "reports" / "literature_backfill_assessment"

TEXT_FIELDS = "coalesce(title,'') || ' ' || coalesce(abstract,'') || ' ' || coalesce(keywords,'')"

SIGNALS = {
    "diagnostic_method": [
        "PCR",
        "qPCR",
        "RT-PCR",
        "RT qPCR",
        "LAMP",
        "ELISA",
        "immunoassay",
        "in situ hybridization",
        "ISH",
        "western blot",
        "metagenomic",
        "next-generation sequencing",
        "NGS",
        "diagnostic",
        "detection",
    ],
    "pathogenicity": [
        "mortality",
        "cumulative mortality",
        "lethal",
        "LD50",
        "challenge",
        "experimental infection",
        "pathogenicity",
        "virulence",
        "tissue tropism",
        "histopathology",
        "disease signs",
        "symptom",
    ],
    "host_range_or_infection": [
        "host range",
        "infected",
        "infection",
        "natural infection",
        "experimental infection",
        "susceptible",
        "carrier",
        "reservoir",
        "transmission",
    ],
    "geography_or_outbreak": [
        "outbreak",
        "epidemic",
        "prevalence",
        "farm",
        "pond",
        "China",
        "Thailand",
        "Vietnam",
        "India",
        "Korea",
        "Japan",
        "Brazil",
        "Ecuador",
        "Mexico",
        "Australia",
        "Indonesia",
        "Malaysia",
        "Philippines",
    ],
    "temperature_environment": [
        "temperature",
        "thermal",
        "heat",
        "cold",
        "salinity",
        "pH",
        "climate",
        "water temperature",
    ],
    "genome_or_function": [
        "genome",
        "complete genome",
        "ORF",
        "open reading frame",
        "RdRp",
        "polymerase",
        "capsid",
        "envelope",
        "phylogenetic",
        "genotype",
    ],
}

TARGET_FIELDS = {
    "virus_master": ["chinese_name", "virus_family", "virus_genus", "genome_type", "notes"],
    "viral_isolates": [
        "taxon_family",
        "taxon_genus",
        "taxon_species",
        "genome_length",
        "gc_content",
        "genome_type",
        "keywords",
        "sequence_length",
        "molecule_type",
        "completeness",
    ],
    "crustacean_hosts": [
        "common_name_cn",
        "taxon_order",
        "taxon_family",
        "host_group",
        "habitat",
        "aquaculture_status",
        "iucn_status",
        "host_type",
    ],
    "infection_records": ["host_id", "detection_method", "disease_symptom", "mortality_rate", "isolation_source", "reference_id"],
    "pathogenicity_evidence": [
        "host_id",
        "reference_id",
        "virulence_level",
        "mortality_rate_min",
        "mortality_rate_max",
        "disease_symptoms",
        "tissue_tropism",
        "pathogenic_mechanism",
        "observation_type",
        "source_text",
    ],
    "diagnostic_methods": [
        "virus_master_id",
        "method_subcategory",
        "target_gene_or_region",
        "sample_type",
        "detection_limit",
        "validation_context",
        "reference_id",
    ],
    "temperature_profiles": ["reference_id", "temperature", "condition_type", "effect_description", "source_text"],
    "outbreak_events": [
        "host_id",
        "country",
        "province_state",
        "start_year",
        "end_year",
        "economic_impact",
        "mortality_rate_min",
        "mortality_rate_max",
        "reference_id",
    ],
    "sample_collections": ["country", "province", "city", "site_name", "latitude", "longitude", "collection_year", "source_type"],
}


def connect_readonly() -> sqlite3.Connection:
    uri = DB_PATH.as_uri() + "?mode=ro"
    con = sqlite3.connect(uri, uri=True)
    con.row_factory = sqlite3.Row
    return con


def table_exists(con: sqlite3.Connection, table: str) -> bool:
    return con.execute(
        "select 1 from sqlite_master where type='table' and name=?",
        (table,),
    ).fetchone() is not None


def columns(con: sqlite3.Connection, table: str) -> set[str]:
    return {row["name"] for row in con.execute(f"pragma table_info({table})")}


def count(con: sqlite3.Connection, sql: str, params: tuple = ()) -> int:
    return int(con.execute(sql, params).fetchone()[0])


def pct(numerator: int, denominator: int) -> float:
    if denominator == 0:
        return 0.0
    return round(numerator * 100.0 / denominator, 2)


def field_gap_summary(con: sqlite3.Connection) -> list[dict]:
    rows = []
    for table, fields in TARGET_FIELDS.items():
        if not table_exists(con, table):
            continue
        total = count(con, f"select count(*) from {table}")
        cols = columns(con, table)
        for field in fields:
            if field not in cols:
                continue
            missing = count(
                con,
                f"""
                select count(*) from {table}
                where {field} is null
                   or trim(cast({field} as text)) = ''
                   or lower(trim(cast({field} as text))) in ('unknown','unk','na','n/a','none','placeholder')
                """,
            )
            rows.append(
                {
                    "table": table,
                    "field": field,
                    "total_rows": total,
                    "missing_or_placeholder": missing,
                    "missing_pct": pct(missing, total),
                }
            )
    rows.sort(key=lambda r: (r["missing_pct"], r["missing_or_placeholder"]), reverse=True)
    return rows


def compile_entity_terms(con: sqlite3.Connection) -> tuple[list[dict], list[dict]]:
    virus_terms: dict[str, dict] = {}
    if table_exists(con, "virus_master"):
        vm_cols = columns(con, "virus_master")
        where = "where is_crustacean_virus = 1" if "is_crustacean_virus" in vm_cols else ""
        if "entry_type" in vm_cols:
            where += (" and " if where else "where ") + "entry_type not in ('host_genome','non_target')"
        for row in con.execute(f"select master_id, canonical_name, abbreviations from virus_master {where}"):
            for term, kind in [(row["canonical_name"], "canonical"), (row["abbreviations"], "abbreviation")]:
                add_entity_term(virus_terms, term, "virus", row["master_id"], row["canonical_name"], kind)
    if table_exists(con, "virus_aliases"):
        for row in con.execute(
            """
            select va.master_id, va.alias, va.alias_type, vm.canonical_name
            from virus_aliases va
            left join virus_master vm on vm.master_id = va.master_id
            where coalesce(vm.is_crustacean_virus, 1) = 1
              and coalesce(vm.entry_type, '') not in ('host_genome','non_target')
            """
        ):
            add_entity_term(virus_terms, row["alias"], "virus", row["master_id"], row["canonical_name"], row["alias_type"])

    host_terms: dict[str, dict] = {}
    if table_exists(con, "crustacean_hosts"):
        host_cols = columns(con, "crustacean_hosts")
        where_parts = []
        if "host_scope_status" in host_cols:
            where_parts.append(
                "coalesce(host_scope_status, '') not in ('excluded_environmental','excluded_technical','non_target')"
            )
        if "host_type" in host_cols:
            where_parts.append("coalesce(host_type, '') not in ('technical_host','vertebrate','non_crustacean')")
        where = "where " + " and ".join(where_parts) if where_parts else ""
        for row in con.execute(f"select host_id, scientific_name, common_name_cn from crustacean_hosts {where}"):
            add_entity_term(host_terms, row["scientific_name"], "host", row["host_id"], row["scientific_name"], "scientific_name")
            add_entity_term(host_terms, row["common_name_cn"], "host", row["host_id"], row["scientific_name"], "common_name_cn")
    if table_exists(con, "host_aliases"):
        host_cols = columns(con, "host_aliases")
        alias_col = "alias" if "alias" in host_cols else None
        if alias_col:
            for row in con.execute(f"select host_id, {alias_col} as alias from host_aliases"):
                add_entity_term(host_terms, row["alias"], "host", row["host_id"], None, "alias")

    return list(virus_terms.values()), list(host_terms.values())


def add_entity_term(
    terms: dict[str, dict],
    term_text: str | None,
    entity_type: str,
    entity_id: int | None,
    canonical: str | None,
    term_type: str,
) -> None:
    if not term_text:
        return
    for raw_part in re.split(r"[;,/|]", str(term_text)):
        term = raw_part.strip()
        if len(term) < 4:
            continue
        norm = term.casefold()
        if norm not in terms or len(term) > len(terms[norm]["term"]):
            terms[norm] = {
                "term": term,
                "entity_type": entity_type,
                "entity_id": entity_id,
                "canonical": canonical or term,
                "term_type": term_type,
            }


def literature_signal_summary(con: sqlite3.Connection) -> list[dict]:
    rows = []
    total = count(con, "select count(*) from ref_literatures")
    for signal, terms in SIGNALS.items():
        clauses = []
        params = []
        for term in terms:
            clauses.append(f"lower({TEXT_FIELDS}) like ?")
            params.append(f"%{term.casefold()}%")
        sql = f"select count(*) from ref_literatures where {' or '.join(clauses)}"
        n = count(con, sql, tuple(params))
        rows.append({"signal": signal, "matching_references": n, "pct_of_literature": pct(n, total)})
    rows.sort(key=lambda r: r["matching_references"], reverse=True)
    return rows


def reference_entity_matches(con: sqlite3.Connection, virus_terms: list[dict], host_terms: list[dict]) -> dict:
    ref_total = count(con, "select count(*) from ref_literatures")
    matched_ref_ids: set[int] = set()
    virus_counts: Counter[int] = Counter()
    host_counts: Counter[int] = Counter()
    top_pairs: Counter[tuple[int, str]] = Counter()
    top_host_pairs: Counter[tuple[int, str]] = Counter()

    refs = con.execute(
        """
        select reference_id, title, abstract, keywords
        from ref_literatures
        where title is not null or abstract is not null or keywords is not null
        """
    )
    virus_terms_sorted = sorted(virus_terms, key=lambda t: len(t["term"]), reverse=True)
    host_terms_sorted = sorted(host_terms, key=lambda t: len(t["term"]), reverse=True)

    for ref in refs:
        text = " ".join(str(ref[k] or "") for k in ("title", "abstract", "keywords")).casefold()
        if not text:
            continue
        ref_virus_hits = []
        for item in virus_terms_sorted:
            if item["term"].casefold() in text:
                matched_ref_ids.add(ref["reference_id"])
                virus_counts[item["entity_id"]] += 1
                ref_virus_hits.append(item)
                top_pairs[(item["entity_id"], item["canonical"])] += 1
                if len(ref_virus_hits) >= 6:
                    break
        for item in host_terms_sorted:
            if item["term"].casefold() in text:
                matched_ref_ids.add(ref["reference_id"])
                host_counts[item["entity_id"]] += 1
                top_host_pairs[(item["entity_id"], item["canonical"])] += 1
                break

    return {
        "references_total": ref_total,
        "references_with_entity_match": len(matched_ref_ids),
        "references_with_entity_match_pct": pct(len(matched_ref_ids), ref_total),
        "virus_entities_with_match": len(virus_counts),
        "host_entities_with_match": len(host_counts),
        "top_virus_matches": [
            {"master_id": mid, "canonical_name": name, "matching_references": n}
            for (mid, name), n in top_pairs.most_common(30)
        ],
        "top_host_matches": [
            {"host_id": hid, "scientific_name": name, "matching_references": n}
            for (hid, name), n in top_host_pairs.most_common(30)
        ],
    }


def linked_reference_summary(con: sqlite3.Connection) -> dict:
    summary = {}
    refs = count(con, "select count(*) from ref_literatures")
    summary["total_ref_literatures"] = refs
    if table_exists(con, "isolate_reference_links"):
        linked_refs = count(con, "select count(distinct reference_id) from isolate_reference_links")
        summary["references_linked_to_isolates"] = linked_refs
        summary["references_linked_to_isolates_pct"] = pct(linked_refs, refs)
        summary["isolate_reference_links"] = count(con, "select count(*) from isolate_reference_links")
    for table in ["infection_records", "pathogenicity_evidence", "diagnostic_methods", "temperature_profiles", "outbreak_events"]:
        if table_exists(con, table) and "reference_id" in columns(con, table):
            total = count(con, f"select count(*) from {table}")
            linked = count(con, f"select count(*) from {table} where reference_id is not null")
            summary[f"{table}_rows"] = total
            summary[f"{table}_with_reference"] = linked
            summary[f"{table}_with_reference_pct"] = pct(linked, total)
    return summary


def sample_candidates(con: sqlite3.Connection, limit_per_signal: int = 30) -> list[dict]:
    candidates = []
    for signal, terms in SIGNALS.items():
        clauses = []
        params = []
        for term in terms:
            clauses.append(f"lower({TEXT_FIELDS}) like ?")
            params.append(f"%{term.casefold()}%")
        sql = f"""
            select reference_id, pmid, doi, year, title, abstract, keywords
            from ref_literatures
            where {' or '.join(clauses)}
            order by
              case when abstract is not null and trim(abstract) != '' then 0 else 1 end,
              cast(coalesce(year, '0') as integer) desc,
              reference_id desc
            limit ?
        """
        for row in con.execute(sql, tuple(params + [limit_per_signal])):
            snippet = make_snippet(row["abstract"] or row["title"] or "", terms)
            candidates.append(
                {
                    "signal": signal,
                    "reference_id": row["reference_id"],
                    "pmid": row["pmid"],
                    "doi": row["doi"],
                    "year": row["year"],
                    "title": row["title"],
                    "snippet": snippet,
                }
            )
    return candidates


def make_snippet(text: str, terms: list[str], size: int = 260) -> str:
    clean = re.sub(r"\s+", " ", text or "").strip()
    if len(clean) <= size:
        return clean
    low = clean.casefold()
    positions = [low.find(term.casefold()) for term in terms if low.find(term.casefold()) >= 0]
    pos = min(positions) if positions else 0
    start = max(0, pos - size // 3)
    return clean[start : start + size].strip()


def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    with path.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def write_markdown(path: Path, report: dict) -> None:
    top_gaps = report["field_gaps"][:25]
    signals = report["literature_signals"]
    matches = report["entity_match_summary"]
    linked = report["linked_reference_summary"]

    lines = [
        "# Literature Backfill Potential Assessment",
        "",
        f"- Generated: {report['generated_at']}",
        f"- Database: `{DB_PATH}`",
        f"- Mode: read-only assessment; no database rows were changed.",
        "",
        "## Headline",
        "",
        f"- Main literature records: **{linked['total_ref_literatures']}**",
        f"- References linked to isolates: **{linked.get('references_linked_to_isolates', 0)}** "
        f"({linked.get('references_linked_to_isolates_pct', 0)}%)",
        f"- References with a direct virus/host text match: **{matches['references_with_entity_match']}** "
        f"({matches['references_with_entity_match_pct']}%)",
        f"- Virus entities with at least one matched reference: **{matches['virus_entities_with_match']}**",
        f"- Host entities with at least one matched reference: **{matches['host_entities_with_match']}**",
        "",
        "## Literature Signals",
        "",
        "| Signal | Matching references | % of literature |",
        "|---|---:|---:|",
    ]
    for row in signals:
        lines.append(f"| {row['signal']} | {row['matching_references']} | {row['pct_of_literature']} |")

    lines.extend(
        [
            "",
            "## Largest Field Gaps",
            "",
            "| Table | Field | Missing / placeholder | Total | Missing % |",
            "|---|---|---:|---:|---:|",
        ]
    )
    for row in top_gaps:
        lines.append(
            f"| {row['table']} | {row['field']} | {row['missing_or_placeholder']} | "
            f"{row['total_rows']} | {row['missing_pct']} |"
        )

    lines.extend(
        [
            "",
            "## Recommended Execution",
            "",
            "1. Use the candidate CSV as the first manual QA sample before writing any database rows.",
            "2. Create a staging/candidate table for high-confidence claims with `reference_id`, source snippet, target entity, field, extracted value, and confidence.",
            "3. Promote only empty-field, high-confidence candidates automatically; route conflicts and low-confidence claims to review queues.",
            "4. Keep a pre-run database backup and write every promoted value to `auto_completeness_fills` or an equivalent provenance table.",
            "",
            "## Output Files",
            "",
            "- `assessment_summary.json`",
            "- `field_gap_summary.csv`",
            "- `literature_signal_summary.csv`",
            "- `candidate_reference_samples.csv`",
            "- `top_virus_literature_matches.csv`",
            "- `top_host_literature_matches.csv`",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    con = connect_readonly()

    virus_terms, host_terms = compile_entity_terms(con)
    report = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "database_path": str(DB_PATH),
        "mode": "readonly",
        "entity_terms": {"virus_terms": len(virus_terms), "host_terms": len(host_terms)},
        "linked_reference_summary": linked_reference_summary(con),
        "field_gaps": field_gap_summary(con),
        "literature_signals": literature_signal_summary(con),
        "entity_match_summary": reference_entity_matches(con, virus_terms, host_terms),
    }
    candidates = sample_candidates(con)

    (OUT_DIR / "assessment_summary.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    write_csv(OUT_DIR / "field_gap_summary.csv", report["field_gaps"])
    write_csv(OUT_DIR / "literature_signal_summary.csv", report["literature_signals"])
    write_csv(OUT_DIR / "candidate_reference_samples.csv", candidates)
    write_csv(OUT_DIR / "top_virus_literature_matches.csv", report["entity_match_summary"]["top_virus_matches"])
    write_csv(OUT_DIR / "top_host_literature_matches.csv", report["entity_match_summary"]["top_host_matches"])
    write_markdown(OUT_DIR / "assessment_report.md", report)

    print(json.dumps({
        "output_dir": str(OUT_DIR),
        "total_ref_literatures": report["linked_reference_summary"]["total_ref_literatures"],
        "references_with_entity_match": report["entity_match_summary"]["references_with_entity_match"],
        "top_gap_count": len(report["field_gaps"]),
        "candidate_samples": len(candidates),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
