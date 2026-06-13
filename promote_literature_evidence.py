#!/usr/bin/env python3
"""Promote reviewed-looking literature evidence into conclusion tables.

This script links existing conclusion rows to references. It does not invent new
pathogenicity/control conclusions; it only fills ``reference_id`` when a scored
match is strong enough. Lower-scoring matches are exported for manual review.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import re
import shutil
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any


BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "crustacean_virus_core.db"
BACKUP_DIR = BASE_DIR / "backups"
REPORT_DIR = BASE_DIR / "reports"

PATH_THRESHOLD = 75
CONTROL_THRESHOLD = 72
REVIEW_THRESHOLD = 55


@dataclass
class Match:
    table_name: str
    row_id: int
    reference_id: int
    score: int
    reasons: list[str]
    source_key: str
    evidence_type: str
    title: str
    year: str
    pmid: str
    doi: str
    virus_name: str


def stamp() -> str:
    return dt.datetime.now().strftime("%Y%m%d_%H%M%S")


def backup_database() -> Path:
    BACKUP_DIR.mkdir(exist_ok=True)
    backup = BACKUP_DIR / f"crustacean_virus_core_before_evidence_promotion_{stamp()}.db"
    shutil.copy2(DB_PATH, backup)
    return backup


def norm(text: str | None) -> str:
    text = (text or "").lower()
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def split_aliases(row: sqlite3.Row) -> list[str]:
    aliases = [row["canonical_name"] or "", row["chinese_name"] or ""]
    aliases.extend(re.split(r"[,;/|]+", row["abbreviations"] or ""))
    cleaned: list[str] = []
    for alias in aliases:
        alias = alias.strip()
        if not alias or alias.lower() in {"unknown", "unclassified"}:
            continue
        if alias not in cleaned:
            cleaned.append(alias)
    return cleaned


def year_tokens(text: str | None) -> set[str]:
    return set(re.findall(r"\b(?:19|20)\d{2}\b", text or ""))


def author_tokens(text: str | None) -> set[str]:
    text = text or ""
    tokens = set()
    for m in re.finditer(r"\b([A-Z][a-z]{2,})\s+(?:et\s+al\.?|\()", text):
        tokens.add(m.group(1).lower())
    for m in re.finditer(r"\b([A-Z][a-z]{2,})\s*&\s+[A-Z][a-z]{2,}", text):
        tokens.add(m.group(1).lower())
    return tokens


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS literature_evidence_promotion_log (
            promotion_id INTEGER PRIMARY KEY AUTOINCREMENT,
            target_table TEXT NOT NULL,
            target_id INTEGER NOT NULL,
            reference_id INTEGER NOT NULL,
            score INTEGER NOT NULL,
            reasons_json TEXT NOT NULL,
            previous_reference_id INTEGER,
            applied INTEGER NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )


def virus_rows(conn: sqlite3.Connection) -> dict[int, sqlite3.Row]:
    return {
        int(row["master_id"]): row
        for row in conn.execute(
            "SELECT master_id, canonical_name, abbreviations, chinese_name FROM virus_master"
        )
    }


def alias_match_score(aliases: list[str], text: str) -> tuple[int, list[str]]:
    ntext = norm(text)
    utext = text.upper()
    best = 0
    reasons: list[str] = []
    for alias in aliases:
        if not alias:
            continue
        nalias = norm(alias)
        if nalias and nalias in ntext:
            score = 35 if len(nalias) > 6 else 22
            if score > best:
                best = score
                reasons = [f"alias:{alias}"]
        if alias.isupper() and len(alias) >= 3 and re.search(rf"\b{re.escape(alias)}\b", utext):
            if 32 > best:
                best = 32
                reasons = [f"abbr:{alias}"]
    return best, reasons


def title_alias_score(aliases: list[str], title: str) -> tuple[int, list[str]]:
    add, why = alias_match_score(aliases, title)
    if add >= 30:
        return add, why
    return 0, []


def has_any(text: str, keywords: list[str]) -> bool:
    ntext = norm(text)
    return any(norm(k) in ntext for k in keywords)


def has_temperature_management_title(title: str) -> bool:
    lower = title.lower()
    if "isothermal amplification" in lower and "temperature" not in lower:
        return False
    return re.search(r"\b(temperature|thermal|heat|cold)\b", lower) is not None


def candidate_references(conn: sqlite3.Connection, master_id: int) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            """
            SELECT
                er.evidence_id,
                er.evidence_type,
                er.claim,
                er.context,
                er.reference_id,
                er.extraction_method,
                er.evidence_strength,
                er.source_pmid,
                er.source_doi,
                rl.title,
                rl.authors,
                rl.journal,
                rl.year,
                rl.pmid,
                rl.doi,
                rl.abstract,
                COALESCE(es.source_key, lec.source_key, '') AS source_key,
                COALESCE(lec.evidence_scope, '') AS evidence_scope,
                COALESCE(lec.target_virus, '') AS target_virus,
                COALESCE(lec.relevance_score, 0) AS relevance_score
            FROM evidence_records er
            JOIN ref_literatures rl ON rl.reference_id = er.reference_id
            LEFT JOIN external_sources es ON es.source_id = er.source_id
            LEFT JOIN literature_evidence_candidates lec
              ON lec.reference_id = er.reference_id
             AND lec.master_id = er.virus_master_id
            WHERE er.virus_master_id = ?
              AND er.reference_id IS NOT NULL
            ORDER BY er.evidence_id DESC
            """,
            (master_id,),
        )
    )


def source_score(source_key: str, pmid: str, doi: str) -> tuple[int, list[str]]:
    score = 0
    reasons: list[str] = []
    if source_key in {"genbank_pubmed", "manual_queue"}:
        score += 12
        reasons.append(f"source:{source_key}")
    elif source_key in {"europe_pmc", "crossref", "openalex", "semantic_scholar"}:
        score += 7
        reasons.append(f"source:{source_key}")
    elif source_key in {"woah", "fao", "naca", "cabi"}:
        score += 10
        reasons.append(f"authority:{source_key}")
    if pmid:
        score += 7
        reasons.append("pmid")
    if doi:
        score += 7
        reasons.append("doi")
    return score, reasons


def score_pathogenicity(row: sqlite3.Row, ref: sqlite3.Row, virus: sqlite3.Row) -> tuple[int, list[str]]:
    score = 0
    reasons: list[str] = []
    etype = ref["evidence_type"] or ""
    escope = ref["evidence_scope"] or ""
    if etype in {"mortality", "virulence"} or (etype == "other" and escope in {"mortality", "virulence"}):
        score += 28
        reasons.append(f"type:{etype or escope}")
    else:
        score -= 30
        reasons.append(f"penalty:type_mismatch:{ref['evidence_type'] or ref['evidence_scope']}")
    aliases = split_aliases(virus)
    title = str(ref["title"] or "")
    text = " ".join(str(ref[x] or "") for x in ["title", "abstract", "claim", "context"])
    title_add, title_why = title_alias_score(aliases, title)
    add, why = alias_match_score(aliases, text)
    if title_add:
        add = max(add, title_add)
        why = title_why
        reasons.append("title_match")
    elif add:
        # Abstract-only virus mentions are too weak for automatic conclusion promotion.
        score -= 18
        reasons.append("weak_alias_not_in_title")
    score += add
    reasons.extend(why)
    s, why = source_score(ref["source_key"] or "", ref["pmid"] or ref["source_pmid"] or "", ref["doi"] or ref["source_doi"] or "")
    score += s
    reasons.extend(why)
    src_text = " ".join(str(row[x] or "") for x in ["source_text", "notes"])
    years = year_tokens(src_text)
    if ref["year"] and ref["year"] in years:
        score += 10
        reasons.append(f"year:{ref['year']}")
    authors = author_tokens(src_text)
    ref_authors = norm(ref["authors"])
    matched_authors = [a for a in authors if a in ref_authors]
    if matched_authors:
        score += 14
        reasons.append("author:" + ",".join(matched_authors[:3]))
    if has_any(title, ["diagnostic", "diagnosis", "detection", "pcr", "lamp", "assay", "lateral flow", "crispr"]):
        score -= 28
        reasons.append("penalty:diagnostic_title")
    if has_any(title, ["sea cucumber", "apostichopus"]) and not has_any(title, ["shrimp", "crab", "prawn", "crustacean"]):
        score -= 30
        reasons.append("penalty:non_crustacean_host_title")
    if not title_add and not (matched_authors and ref["year"] and ref["year"] in years):
        score -= 35
        reasons.append("penalty:no_title_or_citation_match")
    if ref["evidence_strength"] == "high":
        score += 5
        reasons.append("evidence_strength:high")
    return score, reasons


def control_expected_types(row: sqlite3.Row) -> set[str]:
    category = row["method_category"] or ""
    method = f"{row['method_name'] or ''} {row['effect_summary'] or ''} {row['validation_context'] or ''}".lower()
    if category == "thermal_management":
        return {"temperature"}
    if category in {"vaccine", "immunostimulant", "selective_breeding"}:
        return {"other", "virulence", "mortality"}
    if category in {"biosecurity", "disinfection", "pond_management"}:
        if "pcr" in method or "screen" in method or "diagnos" in method:
            return {"diagnosis", "other", "virulence"}
        return {"other", "virulence", "host_range"}
    return {"other", "virulence", "mortality", "temperature", "diagnosis"}


def score_control(row: sqlite3.Row, ref: sqlite3.Row, virus: sqlite3.Row) -> tuple[int, list[str]]:
    score = 0
    reasons: list[str] = []
    expected = control_expected_types(row)
    etype = ref["evidence_type"] or ref["evidence_scope"] or "other"
    if etype in expected or ref["evidence_scope"] in expected:
        score += 25
        reasons.append(f"type:{etype}")
    else:
        score -= 18
        reasons.append(f"penalty:type_mismatch:{etype}")
    aliases = split_aliases(virus)
    title = str(ref["title"] or "")
    text = " ".join(str(ref[x] or "") for x in ["title", "abstract", "claim", "context"])
    title_add, title_why = title_alias_score(aliases, title)
    add, why = alias_match_score(aliases, text)
    if title_add:
        add = max(add, title_add)
        why = title_why
        reasons.append("title_match")
    elif add:
        score -= 18
        reasons.append("weak_alias_not_in_title")
    score += add
    reasons.extend(why)
    s, why = source_score(ref["source_key"] or "", ref["pmid"] or ref["source_pmid"] or "", ref["doi"] or ref["source_doi"] or "")
    score += s
    reasons.extend(why)
    method_text = " ".join(str(row[x] or "") for x in ["method_category", "method_name", "effect_summary", "validation_context", "notes"])
    ref_text = norm(text)
    method_keywords = {
        "vaccine": ["vaccine", "vp28", "inactivated", "dna vaccine", "subunit"],
        "biosecurity": ["screening", "spf", "biosecurity", "pcr", "diagnosis", "detection"],
        "selective_breeding": ["resistant", "resistance", "selective breeding", "selection"],
        "immunostimulant": ["immunostimulant", "probiotic", "glucan", "immune"],
        "thermal_management": ["temperature", "thermal inactivation", "heat", "cold"],
    }
    hits = [k for k in method_keywords.get(row["method_category"] or "", []) if norm(k) in ref_text]
    if hits:
        score += 12
        reasons.append("method_keyword:" + ",".join(hits[:3]))
    else:
        score -= 20
        reasons.append("penalty:no_method_keyword")
    years = year_tokens(method_text)
    if ref["year"] and ref["year"] in years:
        score += 10
        reasons.append(f"year:{ref['year']}")
    authors = author_tokens(method_text)
    ref_authors = norm(ref["authors"])
    matched_authors = [a for a in authors if a in ref_authors]
    if matched_authors:
        score += 14
        reasons.append("author:" + ",".join(matched_authors[:3]))
    if row["method_category"] == "thermal_management" and "temperature" not in {etype, ref["evidence_scope"]}:
        score -= 35
        reasons.append("penalty:thermal_requires_temperature_evidence")
    if row["method_category"] == "thermal_management" and not has_temperature_management_title(title):
        score -= 40
        reasons.append("penalty:thermal_title_not_temperature")
    if row["method_category"] == "biosecurity":
        method_norm = norm(method_text)
        needs_detection = any(k in method_norm for k in ["pcr", "screen", "spf", "certification"])
        if needs_detection and not has_any(title, ["pcr", "screen", "diagnosis", "detection", "assay", "crispr"]):
            score -= 35
            reasons.append("penalty:biosecurity_title_not_detection")
    if not title_add and not (matched_authors and ref["year"] and ref["year"] in years):
        score -= 30
        reasons.append("penalty:no_title_or_citation_match")
    return score, reasons


def best_match_for_row(
    table_name: str,
    row: sqlite3.Row,
    refs: list[sqlite3.Row],
    virus: sqlite3.Row,
) -> Match | None:
    best: Match | None = None
    seen_refs: set[int] = set()
    for ref in refs:
        ref_id = int(ref["reference_id"])
        if ref_id in seen_refs:
            continue
        seen_refs.add(ref_id)
        if table_name == "pathogenicity_evidence":
            score, reasons = score_pathogenicity(row, ref, virus)
            row_id = int(row["pathogenicity_id"])
        else:
            score, reasons = score_control(row, ref, virus)
            row_id = int(row["control_id"])
        match = Match(
            table_name=table_name,
            row_id=row_id,
            reference_id=ref_id,
            score=score,
            reasons=reasons,
            source_key=ref["source_key"] or "",
            evidence_type=ref["evidence_type"] or ref["evidence_scope"] or "",
            title=ref["title"] or "",
            year=ref["year"] or "",
            pmid=ref["pmid"] or ref["source_pmid"] or "",
            doi=ref["doi"] or ref["source_doi"] or "",
            virus_name=virus["canonical_name"] or "",
        )
        if best is None or match.score > best.score:
            best = match
    return best


def collect_matches(conn: sqlite3.Connection) -> tuple[list[Match], list[Match]]:
    viruses = virus_rows(conn)
    apply_matches: list[Match] = []
    review_matches: list[Match] = []
    refs_cache: dict[int, list[sqlite3.Row]] = {}

    path_rows = list(
        conn.execute(
            """
            SELECT * FROM pathogenicity_evidence
            WHERE reference_id IS NULL
              AND virus_master_id IS NOT NULL
            """
        )
    )
    control_rows = list(
        conn.execute(
            """
            SELECT * FROM control_management_methods
            WHERE reference_id IS NULL
              AND virus_master_id IS NOT NULL
            """
        )
    )

    for table_name, rows, threshold in [
        ("pathogenicity_evidence", path_rows, PATH_THRESHOLD),
        ("control_management_methods", control_rows, CONTROL_THRESHOLD),
    ]:
        for row in rows:
            master_id = int(row["virus_master_id"])
            virus = viruses.get(master_id)
            if not virus:
                continue
            if master_id not in refs_cache:
                refs_cache[master_id] = candidate_references(conn, master_id)
            best = best_match_for_row(table_name, row, refs_cache[master_id], virus)
            if not best:
                continue
            if best.score >= threshold:
                apply_matches.append(best)
            elif best.score >= REVIEW_THRESHOLD:
                review_matches.append(best)
    return apply_matches, review_matches


def append_note(existing: str | None, match: Match) -> str:
    marker = (
        f"literature_reference_auto_linked: ref_id={match.reference_id}; "
        f"score={match.score}; source={match.source_key}; reasons={','.join(match.reasons[:6])}"
    )
    existing = (existing or "").strip()
    if marker in existing:
        return existing
    return (existing + " | " + marker).strip(" |")


def apply_matches(conn: sqlite3.Connection, matches: list[Match]) -> int:
    applied = 0
    for m in matches:
        if m.table_name == "pathogenicity_evidence":
            row = conn.execute(
                "SELECT reference_id, notes FROM pathogenicity_evidence WHERE pathogenicity_id = ?",
                (m.row_id,),
            ).fetchone()
            if not row or row["reference_id"] is not None:
                continue
            conn.execute(
                """
                UPDATE pathogenicity_evidence
                SET reference_id = ?,
                    notes = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE pathogenicity_id = ?
                """,
                (m.reference_id, append_note(row["notes"], m), m.row_id),
            )
        else:
            row = conn.execute(
                "SELECT reference_id, notes FROM control_management_methods WHERE control_id = ?",
                (m.row_id,),
            ).fetchone()
            if not row or row["reference_id"] is not None:
                continue
            conn.execute(
                """
                UPDATE control_management_methods
                SET reference_id = ?,
                    notes = ?
                WHERE control_id = ?
                """,
                (m.reference_id, append_note(row["notes"], m), m.row_id),
            )
        conn.execute(
            """
            INSERT INTO literature_evidence_promotion_log(
                target_table, target_id, reference_id, score, reasons_json,
                previous_reference_id, applied
            )
            VALUES (?, ?, ?, ?, ?, NULL, 1)
            """,
            (m.table_name, m.row_id, m.reference_id, m.score, json.dumps(m.reasons, ensure_ascii=False)),
        )
        applied += 1
    return applied


def write_review_csv(matches: list[Match], path: Path) -> None:
    path.parent.mkdir(exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "target_table",
                "target_id",
                "virus_name",
                "score",
                "reference_id",
                "source_key",
                "evidence_type",
                "year",
                "pmid",
                "doi",
                "title",
                "reasons",
            ],
        )
        writer.writeheader()
        for m in matches:
            writer.writerow(
                {
                    "target_table": m.table_name,
                    "target_id": m.row_id,
                    "virus_name": m.virus_name,
                    "score": m.score,
                    "reference_id": m.reference_id,
                    "source_key": m.source_key,
                    "evidence_type": m.evidence_type,
                    "year": m.year,
                    "pmid": m.pmid,
                    "doi": m.doi,
                    "title": m.title,
                    "reasons": "; ".join(m.reasons),
                }
            )


def coverage(conn: sqlite3.Connection) -> dict[str, Any]:
    def one(sql: str) -> int:
        return int(conn.execute(sql).fetchone()[0])

    return {
        "pathogenicity_total": one("SELECT COUNT(*) FROM pathogenicity_evidence"),
        "pathogenicity_with_reference": one("SELECT COUNT(*) FROM pathogenicity_evidence WHERE reference_id IS NOT NULL"),
        "control_total": one("SELECT COUNT(*) FROM control_management_methods"),
        "control_with_reference": one("SELECT COUNT(*) FROM control_management_methods WHERE reference_id IS NOT NULL"),
        "evidence_records_with_reference": one("SELECT COUNT(*) FROM evidence_records WHERE reference_id IS NOT NULL"),
        "promotion_log_applied": one(
            "SELECT COUNT(*) FROM literature_evidence_promotion_log WHERE applied = 1"
        )
        if conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='literature_evidence_promotion_log'"
        ).fetchone()
        else 0,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="Write selected links to the database.")
    args = parser.parse_args()

    REPORT_DIR.mkdir(exist_ok=True)
    backup = str(backup_database()) if args.apply else None

    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        ensure_schema(conn)
        before = coverage(conn)
        auto_matches, review_matches = collect_matches(conn)
        review_path = REPORT_DIR / f"literature_promotion_review_{stamp()}.csv"
        write_review_csv(review_matches, review_path)
        applied = 0
        if args.apply:
            with conn:
                applied = apply_matches(conn, auto_matches)
        after = coverage(conn)
        details = {
            "apply": args.apply,
            "backup": backup,
            "auto_match_count": len(auto_matches),
            "review_match_count": len(review_matches),
            "applied": applied,
            "review_csv": str(review_path),
            "before": before,
            "after": after,
            "auto_match_examples": [
                {
                    "table": m.table_name,
                    "row_id": m.row_id,
                    "virus": m.virus_name,
                    "reference_id": m.reference_id,
                    "score": m.score,
                    "source": m.source_key,
                    "title": m.title,
                    "reasons": m.reasons,
                }
                for m in auto_matches[:20]
            ],
        }
    report_path = REPORT_DIR / f"literature_evidence_promotion_{stamp()}.json"
    report_path.write_text(json.dumps(details, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(details, ensure_ascii=False, indent=2))
    print(f"Report: {report_path}")


if __name__ == "__main__":
    main()
