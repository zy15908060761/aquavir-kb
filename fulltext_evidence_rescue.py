#!/usr/bin/env python3
"""Rescue polluted evidence claims from existing full-text sections.

This first pass is deliberately conservative:
- no network access;
- no direct edits to evidence_records;
- no automatic promotion to production evidence;
- sentence-level candidates are stored for manual review/promotion.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from db_utils import DB_PATH, backup_database


BASE_DIR = Path(__file__).resolve().parent
REPORTS_DIR = BASE_DIR / "reports"
SCRIPT_NAME = Path(__file__).name

CLAIM_POLLUTION_SQL = """
(
    claim LIKE '%http%'
    OR claim LIKE '%www.%'
    OR claim LIKE '%doi.org%'
    OR claim LIKE '%Dryad, Table%'
    OR claim LIKE '%Table S%'
    OR claim LIKE '%Supplementary Table%'
    OR claim LIKE '%Full text%'
    OR LENGTH(claim) > 500
)
AND claim NOT LIKE 'Auto-extracted from abstract:%'
AND claim NOT LIKE 'Abstract mentions %'
"""

SECTION_EXCLUDE = {
    "references",
    "reference",
    "acknowledgements",
    "acknowledgments",
    "funding",
    "author contributions",
    "competing interests",
    "data availability",
    "supplementary material",
    "supplementary information",
}

EVIDENCE_RULES = {
    "diagnosis": {
        "strong": [
            "rt-pcr",
            "rt qpcr",
            "qpcr",
            "pcr",
            "lamp",
            "elisa",
            "in situ hybridization",
            "ish",
            "western blot",
            "immunohistochemistry",
            "diagnostic",
            "assay",
            "primer",
            "probe",
        ],
        "context": ["detect", "detected", "detection", "positive", "confirmed"],
    },
    "pathogenicity": {
        "strong": [
            "challenge",
            "challenged",
            "experimental infection",
            "pathogenicity",
            "pathogenic",
            "virulence",
            "histopathology",
            "disease signs",
            "clinical signs",
            "injected",
            "inoculated",
        ],
        "context": ["infected", "infection", "symptom", "lesion", "disease"],
    },
    "mortality": {
        "strong": [
            "mortality",
            "cumulative mortality",
            "death rate",
            "survival rate",
            "lethal",
            "ld50",
        ],
        "context": ["challenge", "infected", "%", "dpi", "days post"],
    },
    "outbreak": {
        "strong": ["outbreak", "epizootic", "mass mortality", "disease outbreak"],
        "context": ["farm", "pond", "field", "affected", "reported"],
    },
    "transmission": {
        "strong": ["transmission", "transmitted", "horizontal transmission", "vertical transmission"],
        "context": ["infection", "infected", "carrier", "spread"],
    },
    "host_range": {
        "strong": [
            "host range",
            "infected",
            "infection",
            "natural infection",
            "isolated from",
            "detected in",
            "sampled from",
            "host",
            "susceptible",
        ],
        "context": [
            "shrimp",
            "crab",
            "crayfish",
            "oyster",
            "abalone",
            "mussel",
            "scallop",
            "clam",
            "prawn",
        ],
    },
    "temperature": {
        "strong": ["temperature", "thermal", "heat", "cold", "acclimated", "water temperature"],
        "context": ["degc", "°c", "celsius", "℃"],
    },
}

TYPE_PRIORITY = {
    "pathogenicity": 0,
    "mortality": 1,
    "diagnosis": 2,
    "outbreak": 3,
    "transmission": 4,
    "host_range": 5,
    "temperature": 6,
}


def stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH), timeout=120)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 120000")
    return conn


def clean_space(text: str) -> str:
    text = text.replace("\xa0", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def split_sentences(text: str) -> list[str]:
    text = clean_space(text)
    if not text:
        return []
    parts = re.split(r"(?<=[.!?。！？])\s+(?=[A-Z0-9(])", text)
    sentences = []
    for part in parts:
        part = clean_space(part)
        if 60 <= len(part) <= 600:
            sentences.append(part)
    return sentences


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def ensure_schema(conn: sqlite3.Connection) -> None:
    existing = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='fulltext_evidence_rescue_candidates'"
    ).fetchone()
    if existing and "UNIQUE(source_evidence_id, section_id, sentence_hash)" in (existing["sql"] or ""):
        legacy_name = f"fulltext_evidence_rescue_candidates_legacy_{stamp()}"
        conn.execute(f"ALTER TABLE fulltext_evidence_rescue_candidates RENAME TO {legacy_name}")
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS fulltext_evidence_rescue_runs (
            run_id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_ts TEXT NOT NULL,
            target_rule TEXT NOT NULL,
            target_evidence_count INTEGER NOT NULL,
            target_reference_count INTEGER NOT NULL,
            references_with_sections INTEGER NOT NULL,
            candidate_count INTEGER NOT NULL DEFAULT 0,
            script_name TEXT NOT NULL,
            notes TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS fulltext_evidence_rescue_candidates (
            candidate_id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id INTEGER NOT NULL,
            source_evidence_id INTEGER NOT NULL,
            source_evidence_type TEXT NOT NULL,
            reference_id INTEGER NOT NULL,
            fulltext_id INTEGER,
            section_id INTEGER,
            section_type TEXT,
            section_title TEXT,
            sentence TEXT NOT NULL,
            sentence_hash TEXT NOT NULL,
            virus_master_id INTEGER,
            host_id INTEGER,
            matched_virus_names TEXT,
            matched_host_names TEXT,
            matched_terms TEXT NOT NULL,
            confidence_score INTEGER NOT NULL,
            confidence_label TEXT NOT NULL,
            rescue_action TEXT NOT NULL DEFAULT 'manual_review',
            promotion_status TEXT NOT NULL DEFAULT 'candidate',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(run_id) REFERENCES fulltext_evidence_rescue_runs(run_id),
            FOREIGN KEY(source_evidence_id) REFERENCES evidence_records(evidence_id),
            FOREIGN KEY(reference_id) REFERENCES ref_literatures(reference_id),
            FOREIGN KEY(section_id) REFERENCES literature_fulltext_sections(section_id),
            UNIQUE(run_id, source_evidence_id, section_id, sentence_hash)
        );

        CREATE INDEX IF NOT EXISTS idx_rescue_candidates_run
            ON fulltext_evidence_rescue_candidates(run_id, confidence_score DESC);
        CREATE INDEX IF NOT EXISTS idx_rescue_candidates_source
            ON fulltext_evidence_rescue_candidates(source_evidence_id);
        CREATE INDEX IF NOT EXISTS idx_rescue_candidates_reference
            ON fulltext_evidence_rescue_candidates(reference_id);

        CREATE TABLE IF NOT EXISTS fulltext_evidence_rescue_targets (
            run_id INTEGER NOT NULL,
            source_evidence_id INTEGER NOT NULL,
            source_evidence_type TEXT NOT NULL,
            reference_id INTEGER NOT NULL,
            virus_master_id INTEGER,
            host_id INTEGER,
            polluted_claim TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY(run_id, source_evidence_id),
            FOREIGN KEY(run_id) REFERENCES fulltext_evidence_rescue_runs(run_id),
            FOREIGN KEY(source_evidence_id) REFERENCES evidence_records(evidence_id),
            FOREIGN KEY(reference_id) REFERENCES ref_literatures(reference_id)
        );
        """
    )


def load_name_maps(conn: sqlite3.Connection) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    viruses: dict[str, int] = {}
    for row in conn.execute("SELECT master_id, canonical_name, abbreviations FROM virus_master"):
        names = [row["canonical_name"]]
        if row["abbreviations"]:
            names.extend([x.strip() for x in str(row["abbreviations"]).split(",")])
        for name in names:
            name = clean_space(str(name or ""))
            if len(name) >= 4:
                viruses[name] = row["master_id"]
    for row in conn.execute("SELECT master_id, alias FROM virus_aliases"):
        name = clean_space(str(row["alias"] or ""))
        if len(name) >= 4:
            viruses[name] = row["master_id"]

    hosts: dict[str, int] = {}
    for row in conn.execute("SELECT host_id, scientific_name, common_name_cn FROM crustacean_hosts"):
        for name in [row["scientific_name"], row["common_name_cn"]]:
            name = clean_space(str(name or ""))
            if len(name) >= 4:
                hosts[name] = row["host_id"]
    for row in conn.execute("SELECT host_id, alias FROM host_aliases"):
        name = clean_space(str(row["alias"] or ""))
        if len(name) >= 4:
            hosts[name] = row["host_id"]

    virus_list = [
        {"name": name, "name_lower": name.lower(), "id": master_id}
        for name, master_id in viruses.items()
    ]
    host_list = [
        {"name": name, "name_lower": name.lower(), "id": host_id}
        for name, host_id in hosts.items()
    ]
    virus_list.sort(key=lambda x: len(x["name"]), reverse=True)
    host_list.sort(key=lambda x: len(x["name"]), reverse=True)
    return virus_list, host_list


def entity_name_lookup(conn: sqlite3.Connection) -> tuple[dict[int, list[str]], dict[int, list[str]]]:
    virus_names: dict[int, list[str]] = {}
    for row in conn.execute("SELECT master_id, canonical_name, abbreviations FROM virus_master"):
        names = [clean_space(str(row["canonical_name"] or ""))]
        if row["abbreviations"]:
            names.extend(clean_space(x) for x in str(row["abbreviations"]).split(","))
        virus_names[int(row["master_id"])] = [n for n in names if len(n) >= 3]
    for row in conn.execute("SELECT master_id, alias FROM virus_aliases"):
        name = clean_space(str(row["alias"] or ""))
        if len(name) >= 3:
            virus_names.setdefault(int(row["master_id"]), []).append(name)

    host_names: dict[int, list[str]] = {}
    for row in conn.execute("SELECT host_id, scientific_name, common_name_cn FROM crustacean_hosts"):
        names = [clean_space(str(row["scientific_name"] or "")), clean_space(str(row["common_name_cn"] or ""))]
        host_names[int(row["host_id"])] = [n for n in names if len(n) >= 3]
    for row in conn.execute("SELECT host_id, alias FROM host_aliases"):
        name = clean_space(str(row["alias"] or ""))
        if len(name) >= 3:
            host_names.setdefault(int(row["host_id"]), []).append(name)

    return virus_names, host_names


def target_evidence(
    conn: sqlite3.Connection,
    limit: int | None = None,
    mode: str = "pollution",
    only_with_sections: bool = False,
) -> list[sqlite3.Row]:
    if mode == "abstract-mention":
        where_clause = "(er.claim LIKE 'Abstract mentions %' OR er.claim LIKE 'Auto-extracted from abstract:%')"
        target_rule = "abstract_mention_weak_evidence"
    else:
        where_clause = CLAIM_POLLUTION_SQL
        target_rule = "evidence_claim_text_pollution"
    sql = f"""
        SELECT er.evidence_id, er.evidence_type, er.virus_master_id, er.host_id,
               er.reference_id, er.claim, er.curation_status, er.evidence_strength,
               rl.title, rl.year, rl.pmid, rl.doi
        FROM evidence_records er
        LEFT JOIN ref_literatures rl ON rl.reference_id = er.reference_id
        WHERE er.claim IS NOT NULL
          AND er.reference_id IS NOT NULL
          AND {where_clause}
          {"AND EXISTS (SELECT 1 FROM literature_fulltext_sections lfs WHERE lfs.reference_id = er.reference_id)" if only_with_sections else ""}
        ORDER BY
          CASE er.evidence_type
            WHEN 'pathogenicity' THEN 0
            WHEN 'mortality' THEN 1
            WHEN 'diagnosis' THEN 2
            WHEN 'outbreak' THEN 3
            WHEN 'transmission' THEN 4
            WHEN 'host_range' THEN 5
            ELSE 6
          END,
          er.reference_id,
          er.evidence_id
    """
    if limit:
        sql += " LIMIT ?"
        return conn.execute(sql, (limit,)).fetchall()
    return conn.execute(sql).fetchall()


def start_run(conn: sqlite3.Connection, target_rows: list[sqlite3.Row], target_rule: str) -> int:
    refs = {r["reference_id"] for r in target_rows}
    refs_with_sections = {
        r["reference_id"]
        for r in conn.execute(
            f"""
            SELECT DISTINCT reference_id
            FROM literature_fulltext_sections
            WHERE reference_id IN ({','.join('?' for _ in refs) if refs else 'NULL'})
            """,
            tuple(refs),
        )
    } if refs else set()
    cur = conn.execute(
        """
        INSERT INTO fulltext_evidence_rescue_runs(
            run_ts, target_rule, target_evidence_count, target_reference_count,
            references_with_sections, script_name, notes
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            datetime.now().isoformat(timespec="seconds"),
            target_rule,
            len(target_rows),
            len(refs),
            len(refs_with_sections),
            SCRIPT_NAME,
            "Existing fulltext sections only; candidates require manual review.",
        ),
    )
    run_id = int(cur.lastrowid)
    for row in target_rows:
        conn.execute(
            """
            INSERT OR IGNORE INTO fulltext_evidence_rescue_targets(
                run_id, source_evidence_id, source_evidence_type, reference_id,
                virus_master_id, host_id, polluted_claim
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                row["evidence_id"],
                row["evidence_type"],
                row["reference_id"],
                row["virus_master_id"],
                row["host_id"],
                (row["claim"] or "")[:500],
            ),
        )
    return run_id


def section_allowed(row: sqlite3.Row) -> bool:
    section_type = (row["section_type"] or "").strip().lower()
    title = (row["section_title"] or "").strip().lower()
    combined = f"{section_type} {title}"
    if any(token in combined for token in SECTION_EXCLUDE):
        return False
    if section_type in {"references", "funding", "acknowledgements", "acknowledgments"}:
        return False
    return True


def find_names(sentence: str, items: list[dict[str, Any]], max_items: int = 5) -> tuple[list[str], list[int]]:
    lower = sentence.lower()
    names: list[str] = []
    ids: list[int] = []
    for item in items:
        name = item["name"]
        key = item["name_lower"]
        if len(key) < 4:
            continue
        if re.search(rf"(?<![A-Za-z0-9]){re.escape(key)}(?![A-Za-z0-9])", lower):
            names.append(name)
            ids.append(int(item["id"]))
            if len(names) >= max_items:
                break
    return names, ids


COMMON_HOST_TERMS = [
    "Penaeus",
    "Litopenaeus",
    "Fenneropenaeus",
    "Marsupenaeus",
    "Macrobrachium",
    "Procambarus",
    "Cherax",
    "Eriocheir",
    "Scylla",
    "Portunus",
    "Callinectes",
    "Crassostrea",
    "Ostrea",
    "Haliotis",
    "Mytilus",
    "Chlamys",
    "Argopecten",
    "Ruditapes",
    "Scapharca",
    "shrimp",
    "prawn",
    "crab",
    "crayfish",
    "oyster",
    "abalone",
    "mussel",
    "scallop",
    "clam",
]


def names_in_sentence(sentence: str, names: list[str]) -> list[str]:
    lower = sentence.lower()
    found = []
    for name in names:
        key = name.lower()
        if len(key) < 3:
            continue
        if re.search(rf"(?<![A-Za-z0-9]){re.escape(key)}(?![A-Za-z0-9])", lower):
            found.append(name)
    return found


def terms_for_type(evidence_type: str, sentence: str) -> tuple[list[str], int]:
    etype = evidence_type if evidence_type in EVIDENCE_RULES else "host_range"
    rules = EVIDENCE_RULES[etype]
    lower = sentence.lower()
    matched: list[str] = []
    score = 0
    for term in rules["strong"]:
        if term.lower() in lower:
            matched.append(term)
            score += 18
    for term in rules["context"]:
        if term.lower() in lower:
            matched.append(term)
            score += 7
    return sorted(set(matched)), score


def pollution_penalty(sentence: str) -> int:
    lower = sentence.lower()
    penalty = 0
    if "http" in lower or "doi.org" in lower or "www." in lower:
        penalty += 35
    if "dryad" in lower or "supplementary table" in lower or "table s" in lower:
        penalty += 25
    if len(sentence) > 400:
        penalty += 10
    return penalty


def confidence_label(score: int) -> str:
    if score >= 70:
        return "high"
    if score >= 45:
        return "medium"
    return "low"


def candidate_sentences_for_evidence(
    conn: sqlite3.Connection,
    evidence: sqlite3.Row,
    virus_names_by_id: dict[int, list[str]],
    host_names_by_id: dict[int, list[str]],
    section_cache: dict[int, list[dict[str, Any]]],
    max_per_evidence: int,
) -> list[dict[str, Any]]:
    if evidence["reference_id"] not in section_cache:
        section_rows = conn.execute(
            """
            SELECT section_id, fulltext_id, reference_id, section_title, section_type, text
            FROM literature_fulltext_sections
            WHERE reference_id = ?
            ORDER BY CASE section_type
                WHEN 'results' THEN 0
                WHEN 'methods' THEN 1
                WHEN 'discussion' THEN 2
                WHEN 'body' THEN 3
                WHEN 'background' THEN 4
                ELSE 5
            END, section_id
            """,
            (evidence["reference_id"],),
        ).fetchall()
        prepared = []
        for section in section_rows:
            if not section_allowed(section):
                continue
            prepared.append(
                {
                    "section": section,
                    "sentences": split_sentences(section["text"]),
                }
            )
        section_cache[evidence["reference_id"]] = prepared
    sections = section_cache[evidence["reference_id"]]
    candidates: list[dict[str, Any]] = []
    original_virus = evidence["virus_master_id"]
    original_host = evidence["host_id"]
    expected_virus_names = virus_names_by_id.get(int(original_virus), []) if original_virus else []
    expected_host_names = host_names_by_id.get(int(original_host), []) if original_host else []
    expected_host_names = expected_host_names + COMMON_HOST_TERMS
    for prepared in sections:
        section = prepared["section"]
        section_bonus = {
            "results": 12,
            "methods": 8,
            "discussion": 6,
            "body": 4,
            "background": 0,
        }.get((section["section_type"] or "").lower(), 0)
        for sentence in prepared["sentences"]:
            if re.search(r"\b(references|copyright|creative commons|all rights reserved)\b", sentence, re.I):
                continue
            matched_terms, term_score = terms_for_type(evidence["evidence_type"], sentence)
            if not matched_terms:
                continue
            matched_expected_virus = names_in_sentence(sentence, expected_virus_names)
            matched_expected_host = names_in_sentence(sentence, expected_host_names)
            score = term_score + section_bonus
            if original_virus and matched_expected_virus:
                score += 20
            elif original_virus:
                score += 4
            if original_host and matched_expected_host:
                score += 15
            elif matched_expected_host:
                score += 8
            elif original_host:
                score += 3
            if evidence["evidence_type"] == "host_range" and not matched_expected_host:
                continue
            score -= pollution_penalty(sentence)
            if score < 25:
                continue
            candidates.append(
                {
                    "source_evidence_id": evidence["evidence_id"],
                    "source_evidence_type": evidence["evidence_type"],
                    "reference_id": evidence["reference_id"],
                    "fulltext_id": section["fulltext_id"],
                    "section_id": section["section_id"],
                    "section_type": section["section_type"],
                    "section_title": section["section_title"],
                    "sentence": sentence,
                    "sentence_hash": sha256_text(sentence),
                    "virus_master_id": original_virus,
                    "host_id": original_host,
                    "matched_virus_names": "; ".join(matched_expected_virus),
                    "matched_host_names": "; ".join(matched_expected_host),
                    "matched_terms": "; ".join(matched_terms),
                    "confidence_score": max(0, min(100, score)),
                    "confidence_label": confidence_label(score),
                    "rescue_action": "replace_polluted_claim_candidate",
                    "promotion_status": "candidate",
                }
            )
    candidates.sort(key=lambda x: x["confidence_score"], reverse=True)
    return candidates[:max_per_evidence]


def insert_candidate(conn: sqlite3.Connection, run_id: int, item: dict[str, Any]) -> bool:
    cur = conn.execute(
        """
        INSERT OR IGNORE INTO fulltext_evidence_rescue_candidates(
            run_id, source_evidence_id, source_evidence_type, reference_id,
            fulltext_id, section_id, section_type, section_title, sentence,
            sentence_hash, virus_master_id, host_id, matched_virus_names,
            matched_host_names, matched_terms, confidence_score, confidence_label,
            rescue_action, promotion_status
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            run_id,
            item["source_evidence_id"],
            item["source_evidence_type"],
            item["reference_id"],
            item["fulltext_id"],
            item["section_id"],
            item["section_type"],
            item["section_title"],
            item["sentence"],
            item["sentence_hash"],
            item["virus_master_id"],
            item["host_id"],
            item["matched_virus_names"],
            item["matched_host_names"],
            item["matched_terms"],
            item["confidence_score"],
            item["confidence_label"],
            item["rescue_action"],
            item["promotion_status"],
        ),
    )
    return cur.rowcount > 0


def write_csv(path: Path, rows: list[sqlite3.Row] | list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    first = rows[0]
    fieldnames = list(first.keys()) if isinstance(first, sqlite3.Row) else list(first)
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(dict(row))


def export_report(conn: sqlite3.Connection, run_id: int) -> dict[str, str]:
    out_dir = REPORTS_DIR / f"fulltext_evidence_rescue_{run_id}_{stamp()}"
    out_dir.mkdir(parents=True, exist_ok=True)
    artifacts = {
        "summary_json": str(out_dir / "summary.json"),
        "candidate_review_csv": str(out_dir / "candidate_review_top.csv"),
        "source_without_candidate_csv": str(out_dir / "source_evidence_without_candidate.csv"),
        "report_md": str(out_dir / "report.md"),
    }
    summary_rows = conn.execute(
        """
        SELECT source_evidence_type, confidence_label, COUNT(*) AS n,
               COUNT(DISTINCT source_evidence_id) AS source_evidence,
               COUNT(DISTINCT reference_id) AS ref_count
        FROM fulltext_evidence_rescue_candidates
        WHERE run_id = ?
        GROUP BY source_evidence_type, confidence_label
        ORDER BY source_evidence_type, confidence_label
        """,
        (run_id,),
    ).fetchall()
    top = conn.execute(
        """
        SELECT candidate_id, source_evidence_id, source_evidence_type,
               reference_id, section_type, section_title, confidence_score,
               confidence_label, virus_master_id, host_id, matched_terms,
               matched_virus_names, matched_host_names, sentence
        FROM fulltext_evidence_rescue_candidates
        WHERE run_id = ?
        ORDER BY confidence_score DESC, source_evidence_type, source_evidence_id
        LIMIT 5000
        """,
        (run_id,),
    ).fetchall()
    write_csv(Path(artifacts["candidate_review_csv"]), top)

    without_candidate = conn.execute(
        """
        SELECT er.evidence_id, er.evidence_type, er.reference_id, er.virus_master_id,
               er.host_id, substr(er.claim, 1, 300) AS polluted_claim
        FROM fulltext_evidence_rescue_targets t
        JOIN evidence_records er ON er.evidence_id = t.source_evidence_id
        WHERE t.run_id = ?
          AND NOT EXISTS (
              SELECT 1 FROM fulltext_evidence_rescue_candidates c
              WHERE c.run_id = ? AND c.source_evidence_id = er.evidence_id
          )
        ORDER BY er.evidence_type, er.reference_id, er.evidence_id
        """,
        (run_id, run_id),
    ).fetchall()
    write_csv(Path(artifacts["source_without_candidate_csv"]), without_candidate)

    run = dict(conn.execute("SELECT * FROM fulltext_evidence_rescue_runs WHERE run_id=?", (run_id,)).fetchone())
    summary = {
        "run": run,
        "candidate_summary": [dict(r) for r in summary_rows],
        "source_without_candidate_count": len(without_candidate),
        "artifacts": artifacts,
    }
    Path(artifacts["summary_json"]).write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "# Fulltext Evidence Rescue Report",
        "",
        f"- Run ID: `{run_id}`",
        f"- Target evidence: `{run['target_evidence_count']}`",
        f"- Target references: `{run['target_reference_count']}`",
        f"- References with sections: `{run['references_with_sections']}`",
        f"- Candidates: `{run['candidate_count']}`",
        f"- Source evidence without candidate: `{len(without_candidate)}`",
        "",
        "## Candidate Summary",
        "",
    ]
    for row in summary_rows:
        lines.append(
            f"- `{row['source_evidence_type']}` / `{row['confidence_label']}`: "
            f"{row['n']} candidates from {row['source_evidence']} evidence rows, {row['ref_count']} refs"
        )
    lines.extend(["", "## Artifacts", ""])
    for key, value in artifacts.items():
        lines.append(f"- {key}: `{value}`")
    Path(artifacts["report_md"]).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return artifacts


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None, help="Optional evidence-row limit for smoke tests.")
    parser.add_argument("--max-per-evidence", type=int, default=3)
    parser.add_argument(
        "--mode",
        choices=["pollution", "abstract-mention"],
        default="pollution",
        help="Target evidence set.",
    )
    parser.add_argument("--only-with-sections", action="store_true")
    parser.add_argument("--no-backup", action="store_true")
    args = parser.parse_args()

    if not args.no_backup:
        backup_database(label="before_fulltext_evidence_rescue", quiet=True)

    conn = connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        ensure_schema(conn)
        evidence_rows = target_evidence(conn, args.limit, args.mode, args.only_with_sections)
        target_rule = "abstract_mention_weak_evidence" if args.mode == "abstract-mention" else "evidence_claim_text_pollution"
        run_id = start_run(conn, evidence_rows, target_rule)
        virus_names_by_id, host_names_by_id = entity_name_lookup(conn)
        section_cache: dict[int, list[dict[str, Any]]] = {}
        inserted = 0
        for evidence in evidence_rows:
            for candidate in candidate_sentences_for_evidence(
                conn,
                evidence,
                virus_names_by_id,
                host_names_by_id,
                section_cache,
                args.max_per_evidence,
            ):
                if insert_candidate(conn, run_id, candidate):
                    inserted += 1
        conn.execute(
            "UPDATE fulltext_evidence_rescue_runs SET candidate_count=? WHERE run_id=?",
            (inserted, run_id),
        )
        artifacts = export_report(conn, run_id)
        conn.commit()
        result = {
            "run_id": run_id,
            "target_evidence": len(evidence_rows),
            "candidate_count": inserted,
            "integrity_check": conn.execute("PRAGMA integrity_check").fetchone()[0],
            "foreign_key_violations": len(conn.execute("PRAGMA foreign_key_check").fetchall()),
            "artifacts": artifacts,
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
