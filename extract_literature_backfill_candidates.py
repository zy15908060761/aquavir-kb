#!/usr/bin/env python3
"""Extract evidence candidates from local full text/XML/abstract caches.

The script is deliberately conservative:
- no network access
- read-only SQLite connection
- no writes to production tables
- outputs CSV/JSON/MD files for review
"""

from __future__ import annotations

import csv
import gzip
import json
import re
import sqlite3
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

try:
    from pypdf import PdfReader
except Exception:  # pragma: no cover - optional dependency
    PdfReader = None


ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "crustacean_virus_core.db"
CURATION_DIR = ROOT / "literature_curation_v2"
OUT_DIR = ROOT / "reports" / "literature_backfill_candidates"

MAX_CANDIDATES_PER_REFERENCE = 20


SIGNAL_RULES = {
    "diagnostic_method": {
        "target_tables": "diagnostic_methods,infection_records",
        "terms": [
            "PCR",
            "qPCR",
            "real-time PCR",
            "RT-PCR",
            "nested PCR",
            "LAMP",
            "ELISA",
            "immunoassay",
            "in situ hybridization",
            "western blot",
            "NGS",
            "metagenomic sequencing",
            "detection limit",
            "diagnostic",
            "detected by",
        ],
    },
    "pathogenicity": {
        "target_tables": "pathogenicity_evidence,infection_records",
        "terms": [
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
            "clinical signs",
            "moribund",
        ],
    },
    "host_infection": {
        "target_tables": "infection_records,host_range_evidence",
        "terms": [
            "infected",
            "infection",
            "natural infection",
            "experimental infection",
            "susceptible",
            "host range",
            "carrier",
            "reservoir",
            "transmission",
        ],
    },
    "outbreak_geography": {
        "target_tables": "outbreak_events,sample_collections",
        "terms": [
            "outbreak",
            "epidemic",
            "prevalence",
            "farm",
            "pond",
            "Ecuador",
            "China",
            "Thailand",
            "Vietnam",
            "India",
            "Korea",
            "Japan",
            "Indonesia",
            "Malaysia",
            "Brazil",
            "Mexico",
        ],
    },
    "temperature_environment": {
        "target_tables": "temperature_profiles,environmental_evidence",
        "terms": [
            "temperature",
            "thermal",
            "heat",
            "cold",
            "incubated at",
            "°C",
            "degrees C",
            "salinity",
            "pH",
            "water temperature",
        ],
    },
}

METHOD_TERMS = [
    "qPCR",
    "real-time PCR",
    "RT-PCR",
    "nested PCR",
    "PCR",
    "LAMP",
    "ELISA",
    "in situ hybridization",
    "western blot",
    "NGS",
    "metagenomic sequencing",
]

TARGET_GENE_RE = re.compile(
    r"\b(VP\d+|ORF\d+|RdRp|polymerase|capsid|envelope|helicase|p[0-9]{2,3}|MCP|ATPase)\b",
    re.IGNORECASE,
)
MORTALITY_RE = re.compile(r"(?:(?:mortality|mortalities)[^.\n;]{0,80})?(\d{1,3}(?:\.\d+)?)\s*%", re.IGNORECASE)
TEMP_RE = re.compile(r"(\d{1,2}(?:\.\d+)?)\s*(?:°C|degrees C|deg C|C\b)")
MORTALITY_CONTEXT_RE = re.compile(
    r"(?:mortality|mortalities|dead|death|lethal|survival)[^.\n;]{0,100}?(\d{1,3}(?:\.\d+)?)\s*%"
    r"|(\d{1,3}(?:\.\d+)?)\s*%[^.\n;]{0,100}?(?:mortality|mortalities|dead|death|lethal|survival)",
    re.IGNORECASE,
)
NOISE_PHRASES = [
    "no associated publication",
    "not available",
    "were not available",
    "unable to link",
    "could not be found",
    "not found",
    "not shown",
    "hot chains",
    "cold chains",
    "confidence interval",
    "95% ci",
    "coverage of the reference genome",
]
COUNTRY_TERMS = [
    "China",
    "Thailand",
    "Vietnam",
    "India",
    "Korea",
    "Japan",
    "Indonesia",
    "Malaysia",
    "Brazil",
    "Ecuador",
    "Mexico",
    "Australia",
    "Philippines",
    "USA",
    "United States",
]


@dataclass
class TextRecord:
    reference_id: int | None
    pmid: str | None
    doi: str | None
    title: str
    source_type: str
    source_path: str
    section: str
    text: str


def connect_readonly() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH.as_uri() + "?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def split_sentences(text: str) -> list[str]:
    text = normalize_space(text)
    if not text:
        return []
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9])", text)
    return [p.strip() for p in parts if len(p.strip()) >= 40]


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
    for raw_part in re.split(r"[;,|]", str(term_text)):
        term = raw_part.strip()
        if len(term) < 4:
            continue
        if term.lower() in {"unknown", "unclassified", "virus", "shrimp"}:
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


def load_entity_terms(con: sqlite3.Connection) -> tuple[list[dict], list[dict]]:
    virus_terms: dict[str, dict] = {}
    for row in con.execute(
        """
        select master_id, canonical_name, abbreviations
        from virus_master
        where coalesce(is_crustacean_virus, 1) = 1
          and coalesce(entry_type, '') not in ('host_genome','non_target')
        """
    ):
        add_entity_term(virus_terms, row["canonical_name"], "virus", row["master_id"], row["canonical_name"], "canonical")
        add_entity_term(virus_terms, row["abbreviations"], "virus", row["master_id"], row["canonical_name"], "abbreviation")

    for row in con.execute(
        """
        select va.master_id, va.alias, va.alias_type, vm.canonical_name
        from virus_aliases va
        join virus_master vm on vm.master_id = va.master_id
        where coalesce(vm.is_crustacean_virus, 1) = 1
          and coalesce(vm.entry_type, '') not in ('host_genome','non_target')
          and coalesce(va.match_status, '') != 'rejected'
        """
    ):
        add_entity_term(virus_terms, row["alias"], "virus", row["master_id"], row["canonical_name"], row["alias_type"])

    host_terms: dict[str, dict] = {}
    for row in con.execute(
        """
        select host_id, scientific_name, common_name_cn
        from crustacean_hosts
        where coalesce(host_scope_status, '') not in ('excluded_environmental','excluded_technical','non_target')
          and coalesce(host_type, '') not in ('technical_host','vertebrate','non_crustacean')
        """
    ):
        add_entity_term(host_terms, row["scientific_name"], "host", row["host_id"], row["scientific_name"], "scientific_name")
        add_entity_term(host_terms, row["common_name_cn"], "host", row["host_id"], row["scientific_name"], "common_name_cn")

    return (
        sorted(virus_terms.values(), key=lambda x: len(x["term"]), reverse=True),
        sorted(host_terms.values(), key=lambda x: len(x["term"]), reverse=True),
    )


def load_reference_index(con: sqlite3.Connection) -> dict:
    index = {}
    for row in con.execute("select reference_id, pmid, doi, title from ref_literatures"):
        if row["pmid"]:
            index[("pmid", str(row["pmid"]).strip())] = dict(row)
        if row["doi"]:
            index[("doi", str(row["doi"]).strip().lower())] = dict(row)
    return index


def load_db_abstract_records(con: sqlite3.Connection, limit: int | None = None) -> Iterable[TextRecord]:
    sql = """
        select reference_id, pmid, doi, title, abstract, keywords
        from ref_literatures
        where abstract is not null and trim(abstract) != ''
        order by reference_id
    """
    if limit:
        sql += f" limit {int(limit)}"
    for row in con.execute(sql):
        text = " ".join([row["abstract"] or "", row["keywords"] or ""])
        yield TextRecord(
            reference_id=row["reference_id"],
            pmid=row["pmid"],
            doi=row["doi"],
            title=row["title"] or "",
            source_type="db_abstract",
            source_path=str(DB_PATH),
            section="abstract",
            text=normalize_space(text),
        )


def iter_local_text_records(ref_index: dict) -> Iterable[TextRecord]:
    for path in sorted((CURATION_DIR / "pmc_xml").glob("*.xml")):
        yield from parse_pmc_xml(path, ref_index)
    for path in sorted((CURATION_DIR / "pubmed_xml").glob("*.xml")):
        yield from parse_pubmed_xml(path, ref_index)
    for path in sorted((CURATION_DIR / "oa_fulltext").glob("*.pdf")):
        rec = parse_pdf(path, ref_index)
        if rec:
            yield rec
    for path in sorted((CURATION_DIR / "fulltext").glob("*.pdf")):
        rec = parse_pdf(path, ref_index)
        if rec:
            yield rec


def parse_pmc_xml(path: Path, ref_index: dict) -> Iterable[TextRecord]:
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError:
        return
    pmid = find_first_text(root, ".//article-id[@pub-id-type='pmid']")
    doi = find_first_text(root, ".//article-id[@pub-id-type='doi']")
    title = normalize_space(" ".join(root.findtext(".//article-title", default="").split()))
    ref = match_reference(ref_index, pmid, doi)
    for sec in root.findall(".//sec"):
        title_node = sec.find("title")
        sec_title = normalize_space("".join(title_node.itertext())) if title_node is not None else "body"
        paras = []
        for p in sec.findall(".//p"):
            paras.append(normalize_space("".join(p.itertext())))
        text = normalize_space(" ".join(paras))
        if len(text) >= 80:
            yield TextRecord(
                reference_id=ref.get("reference_id") if ref else None,
                pmid=pmid,
                doi=doi,
                title=ref.get("title") if ref else title,
                source_type="pmc_xml",
                source_path=str(path),
                section=sec_title or "body",
                text=text,
            )


def parse_pubmed_xml(path: Path, ref_index: dict) -> Iterable[TextRecord]:
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError:
        return
    for article in root.findall(".//PubmedArticle"):
        medline = article.find("MedlineCitation")
        if medline is None:
            continue
        pmid = find_first_text(medline, "PMID")
        article_node = medline.find("Article")
        title = ""
        abstract = ""
        doi = None
        if article_node is not None:
            title_node = article_node.find("ArticleTitle")
            if title_node is not None:
                title = normalize_space("".join(title_node.itertext()))
            parts = []
            for node in article_node.findall(".//AbstractText"):
                label = node.get("Label", "")
                text = normalize_space("".join(node.itertext()))
                if text:
                    parts.append(f"{label}: {text}" if label else text)
            abstract = normalize_space(" ".join(parts))
        for aid in article.findall(".//ArticleId"):
            if aid.get("IdType") == "doi" and aid.text:
                doi = aid.text.strip()
        if abstract:
            ref = match_reference(ref_index, pmid, doi)
            yield TextRecord(
                reference_id=ref.get("reference_id") if ref else None,
                pmid=pmid,
                doi=doi,
                title=ref.get("title") if ref else title,
                source_type="pubmed_xml",
                source_path=str(path),
                section="abstract",
                text=abstract,
            )


def parse_pdf(path: Path, ref_index: dict) -> TextRecord | None:
    if PdfReader is None:
        return None
    pmid = None
    doi = None
    m = re.search(r"(\d{6,9})", path.name)
    if m:
        pmid = m.group(1)
    try:
        reader = PdfReader(str(path))
        pages = []
        for page in reader.pages[:30]:
            pages.append(page.extract_text() or "")
        text = normalize_space(" ".join(pages))
    except Exception:
        return None
    if len(text) < 80:
        return None
    ref = match_reference(ref_index, pmid, doi)
    return TextRecord(
        reference_id=ref.get("reference_id") if ref else None,
        pmid=pmid,
        doi=doi,
        title=ref.get("title") if ref else path.stem,
        source_type="pdf",
        source_path=str(path),
        section="fulltext_pdf",
        text=text,
    )


def find_first_text(root: ET.Element, path: str) -> str | None:
    node = root.find(path)
    if node is not None and node.text:
        return node.text.strip()
    return None


def match_reference(ref_index: dict, pmid: str | None, doi: str | None) -> dict | None:
    if pmid and ("pmid", str(pmid).strip()) in ref_index:
        return ref_index[("pmid", str(pmid).strip())]
    if doi and ("doi", str(doi).strip().lower()) in ref_index:
        return ref_index[("doi", str(doi).strip().lower())]
    return None


def find_entities(text: str, terms: list[dict], max_hits: int = 5) -> list[dict]:
    hits = []
    seen = set()
    for item in terms:
        term = item["term"]
        if item["entity_id"] in seen:
            continue
        if entity_term_matches(text, term):
            hits.append(item)
            seen.add(item["entity_id"])
            if len(hits) >= max_hits:
                break
    return hits


def entity_term_matches(text: str, term: str) -> bool:
    if not term:
        return False
    escaped = re.escape(term)
    if re.search(r"\s", term):
        pattern = rf"(?<![A-Za-z0-9]){escaped}(?![A-Za-z0-9])"
    elif term.isupper() and 4 <= len(term) <= 12:
        pattern = rf"(?<![A-Za-z0-9]){escaped}(?![A-Za-z0-9])"
    else:
        if len(term) < 6:
            return False
        pattern = rf"(?<![A-Za-z0-9]){escaped}(?![A-Za-z0-9])"
    return re.search(pattern, text, re.IGNORECASE) is not None


def find_signal(sentence: str) -> list[tuple[str, list[str]]]:
    low = sentence.casefold()
    found = []
    for signal, spec in SIGNAL_RULES.items():
        matched = [term for term in spec["terms"] if term.casefold() in low]
        if matched:
            found.append((signal, matched[:5]))
    return found


def extract_values(sentence: str, signal: str) -> dict:
    values: dict[str, str] = {}
    methods = [m for m in METHOD_TERMS if m.casefold() in sentence.casefold()]
    if methods:
        values["method"] = "|".join(dict.fromkeys(methods))
    genes = TARGET_GENE_RE.findall(sentence)
    if genes:
        values["target_gene_or_region"] = "|".join(dict.fromkeys(g.strip() for g in genes))
    mortality_matches = []
    for match in MORTALITY_CONTEXT_RE.findall(sentence):
        mortality_matches.extend(x for x in match if x)
    mortalities = [float(x) for x in mortality_matches if 0 <= float(x) <= 100]
    if mortalities:
        values["mortality_rate_min"] = str(min(mortalities))
        values["mortality_rate_max"] = str(max(mortalities))
    temps = [float(x) for x in TEMP_RE.findall(sentence) if -5 <= float(x) <= 100]
    if temps:
        values["temperature_min"] = str(min(temps))
        values["temperature_max"] = str(max(temps))
    countries = [c for c in COUNTRY_TERMS if re.search(rf"\b{re.escape(c)}\b", sentence, re.IGNORECASE)]
    if countries:
        values["country"] = "|".join(dict.fromkeys(countries))
    if signal in {"pathogenicity", "host_infection"}:
        if re.search(r"\b(field|natural infection|naturally infected)\b", sentence, re.IGNORECASE):
            values["observation_type"] = "field"
        elif re.search(r"\b(challenge|experimental infection|injected|immersion|oral)\b", sentence, re.IGNORECASE):
            values["observation_type"] = "lab"
    return values


def is_strict_candidate(signal: str, sentence: str, values: dict, matched_terms: list[str], confidence: str) -> tuple[int, str]:
    """Return strict-review score and a short reason.

    Strict candidates are intended for staging-table review. Raw candidates are
    still kept separately for audit and future rule development.
    """
    low = sentence.casefold()
    if any(phrase in low for phrase in NOISE_PHRASES):
        return 0, "noise_phrase"
    score = 0
    reasons = []
    if confidence == "high":
        score += 2
        reasons.append("high_confidence")
    elif confidence == "medium":
        score += 1
        reasons.append("medium_confidence")
    if values:
        score += 2
        reasons.append("has_extracted_value")

    if signal == "diagnostic_method":
        if "method" not in values:
            return 0, "diagnostic_without_method"
        if re.search(r"\b(detect|detection|diagnos|assay|screen|test|amplif)\w*\b", low):
            score += 2
            reasons.append("diagnostic_context")
    elif signal == "pathogenicity":
        if any(k in values for k in ["mortality_rate_min", "mortality_rate_max", "observation_type"]):
            score += 2
            reasons.append("pathogenicity_value")
        if re.search(r"\b(challenge|infected|infection|mortality|histopathology|clinical signs|disease signs)\b", low):
            score += 1
            reasons.append("pathogenicity_context")
    elif signal == "host_infection":
        if re.search(r"\b(natural infection|experimentally infected|infected with|susceptible to|host range|carrier|reservoir)\b", low):
            score += 2
            reasons.append("host_relation_context")
    elif signal == "outbreak_geography":
        if "country" not in values:
            return 0, "geography_without_country"
        if re.search(r"\b(outbreak|epidemic|prevalence|farm|pond|hatcheries|survey)\b", low):
            score += 2
            reasons.append("geo_event_context")
    elif signal == "temperature_environment":
        if not any(k in values for k in ["temperature_min", "temperature_max"]):
            return 0, "temperature_without_numeric_value"
        if re.search(r"\b(temperature|thermal|heat|inactivation|incubat|water temperature|°c|degrees c)\b", low):
            score += 2
            reasons.append("temperature_context")

    return score, "|".join(reasons) if reasons else "weak"


def confidence_for(record: TextRecord, signal: str, values: dict, virus_hits: list[dict], host_hits: list[dict]) -> str:
    score = 0
    if record.source_type in {"pmc_xml", "pdf"}:
        score += 2
    elif record.source_type == "pubmed_xml":
        score += 1
    if record.reference_id:
        score += 1
    if virus_hits:
        score += 2
    if host_hits:
        score += 1
    if values:
        score += 1
    if signal in {"diagnostic_method", "pathogenicity"} and values:
        score += 1
    section_low = record.section.casefold()
    if any(x in section_low for x in ["results", "methods", "materials", "abstract"]):
        score += 1
    if any(x in section_low for x in ["introduction", "discussion", "references"]):
        score -= 1
    if score >= 7:
        return "high"
    if score >= 5:
        return "medium"
    return "low"


def extract_candidates(records: Iterable[TextRecord], virus_terms: list[dict], host_terms: list[dict]) -> list[dict]:
    candidates = []
    seen = set()
    per_ref_count: Counter[int | str] = Counter()
    for record in records:
        if not record.text:
            continue
        record_key = record.reference_id or record.pmid or record.source_path
        if per_ref_count[record_key] >= MAX_CANDIDATES_PER_REFERENCE:
            continue
        context_text = f"{record.title} {record.text}"
        virus_hits = find_entities(context_text, virus_terms)
        host_hits = find_entities(context_text, host_terms)
        if not virus_hits and not host_hits:
            continue
        for sentence in split_sentences(record.text):
            sentence_entities = find_entities(f"{record.title} {sentence}", virus_terms, max_hits=3)
            entity_match_scope = "sentence"
            if not sentence_entities:
                sentence_entities = virus_hits[:2]
                entity_match_scope = "document_fallback"
            sentence_hosts = find_entities(sentence, host_terms, max_hits=3) or host_hits[:2]
            if not sentence_entities:
                continue
            for signal, matched_terms in find_signal(sentence):
                values = extract_values(sentence, signal)
                confidence = confidence_for(record, signal, values, sentence_entities, sentence_hosts)
                strict_score, strict_reason = is_strict_candidate(signal, sentence, values, matched_terms, confidence)
                if entity_match_scope != "sentence":
                    strict_score = min(strict_score, 4)
                    strict_reason = f"{strict_reason}|document_entity_fallback"
                key = (
                    record.reference_id,
                    signal,
                    sentence_entities[0]["entity_id"],
                    normalize_space(sentence[:180]).casefold(),
                )
                if key in seen:
                    continue
                seen.add(key)
                per_ref_count[record_key] += 1
                candidates.append(
                    {
                        "candidate_id": len(candidates) + 1,
                        "reference_id": record.reference_id,
                        "pmid": record.pmid,
                        "doi": record.doi,
                        "title": record.title,
                        "source_type": record.source_type,
                        "source_path": record.source_path,
                        "section": record.section,
                        "signal": signal,
                        "target_tables": SIGNAL_RULES[signal]["target_tables"],
                        "matched_terms": "|".join(matched_terms),
                        "virus_master_ids": "|".join(str(v["entity_id"]) for v in sentence_entities),
                        "virus_names": "|".join(v["canonical"] for v in sentence_entities),
                        "host_ids": "|".join(str(h["entity_id"]) for h in sentence_hosts),
                        "host_names": "|".join(h["canonical"] for h in sentence_hosts),
                        "entity_match_scope": entity_match_scope,
                        "extracted_values_json": json.dumps(values, ensure_ascii=False, sort_keys=True),
                        "confidence": confidence,
                        "strict_score": strict_score,
                        "strict_reason": strict_reason,
                        "strict_candidate": 1 if strict_score >= 5 else 0,
                        "evidence_text": sentence[:1200],
                        "curation_status": "needs_review",
                    }
                )
                if per_ref_count[record_key] >= MAX_CANDIDATES_PER_REFERENCE:
                    break
            if per_ref_count[record_key] >= MAX_CANDIDATES_PER_REFERENCE:
                break
    return candidates


def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    with path.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def write_report(path: Path, summary: dict) -> None:
    lines = [
        "# Literature Backfill Candidate Extraction",
        "",
        f"- Generated: {summary['generated_at']}",
        "- Mode: local cache/read-only extraction; no production database rows changed.",
        f"- Candidate rows: **{summary['candidate_count']}**",
        f"- Strict candidate rows: **{summary['strict_candidate_count']}**",
        f"- References covered by candidates: **{summary['references_with_candidates']}**",
        "",
        "## By Source",
        "",
        "| Source | Candidates |",
        "|---|---:|",
    ]
    for source, n in summary["by_source"].items():
        lines.append(f"| {source} | {n} |")
    lines.extend(["", "## By Signal", "", "| Signal | Candidates |", "|---|---:|"])
    for signal, n in summary["by_signal"].items():
        lines.append(f"| {signal} | {n} |")
    lines.extend(["", "## By Confidence", "", "| Confidence | Candidates |", "|---|---:|"])
    for conf, n in summary["by_confidence"].items():
        lines.append(f"| {conf} | {n} |")
    lines.extend(["", "## Strict Candidates By Signal", "", "| Signal | Strict candidates |", "|---|---:|"])
    for signal, n in summary["strict_by_signal"].items():
        lines.append(f"| {signal} | {n} |")
    lines.extend(["", "## Strict Candidates By Source", "", "| Source | Strict candidates |", "|---|---:|"])
    for source, n in summary["strict_by_source"].items():
        lines.append(f"| {source} | {n} |")
    lines.extend(
        [
            "",
            "## Next Gate",
            "",
            "Review `candidate_evidence_strict.csv` first. Keep `candidate_evidence.csv` as a raw audit/debug set.",
            "After QA, promote only empty-field, high-confidence candidates into a staging table with full provenance.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    con = connect_readonly()
    ref_index = load_reference_index(con)
    virus_terms, host_terms = load_entity_terms(con)

    local_records = list(iter_local_text_records(ref_index))
    abstract_records = list(load_db_abstract_records(con))
    candidates = extract_candidates(local_records + abstract_records, virus_terms, host_terms)
    strict_candidates = [row for row in candidates if int(row["strict_candidate"]) == 1]

    by_source = Counter(row["source_type"] for row in candidates)
    by_signal = Counter(row["signal"] for row in candidates)
    by_confidence = Counter(row["confidence"] for row in candidates)
    strict_by_source = Counter(row["source_type"] for row in strict_candidates)
    strict_by_signal = Counter(row["signal"] for row in strict_candidates)
    strict_by_confidence = Counter(row["confidence"] for row in strict_candidates)
    refs_with_candidates = {
        row["reference_id"] or row["pmid"] or row["source_path"]
        for row in candidates
    }
    summary = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "db_path": str(DB_PATH),
        "local_text_records": len(local_records),
        "abstract_records": len(abstract_records),
        "candidate_count": len(candidates),
        "strict_candidate_count": len(strict_candidates),
        "references_with_candidates": len(refs_with_candidates),
        "by_source": dict(by_source.most_common()),
        "by_signal": dict(by_signal.most_common()),
        "by_confidence": dict(by_confidence.most_common()),
        "strict_by_source": dict(strict_by_source.most_common()),
        "strict_by_signal": dict(strict_by_signal.most_common()),
        "strict_by_confidence": dict(strict_by_confidence.most_common()),
    }

    write_csv(OUT_DIR / "candidate_evidence.csv", candidates)
    write_csv(OUT_DIR / "candidate_evidence_strict.csv", strict_candidates)
    (OUT_DIR / "candidate_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    write_report(OUT_DIR / "candidate_report.md", summary)

    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
