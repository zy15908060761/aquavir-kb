#!/usr/bin/env python3
"""Audit fulltext quality and build an actionable cleanup/OCR/redownload queue."""

from __future__ import annotations

import argparse
import csv
import json
import re
import sqlite3
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from xml.etree import ElementTree as ET

try:
    import fitz  # PyMuPDF
except ImportError:  # pragma: no cover
    fitz = None


ROOT = Path.cwd()
DB_PATH = ROOT / "crustacean_virus_core.db"
OUT_DIR = ROOT / "downloads" / "fulltext_quality"


HIGH_VALUE_TERMS = [
    "white spot syndrome virus", "wssv",
    "yellow head virus", "yhv",
    "infectious hypodermal", "ihhnv",
    "taura syndrome virus", "tsv",
    "ostreid herpesvirus", "oshv", "oshv-1",
    "shrimp", "penaeus", "litopenaeus", "crayfish", "crab", "oyster", "mollusc", "mollusk",
    "pathogenicity", "mortality", "challenge", "diagnostic", "pcr", "qpcr", "lamp",
    "outbreak", "temperature", "host range", "virome", "metagenomic",
]

LIKELY_IRRELEVANT_TERMS = [
    "rat", "mice", "mouse", "human", "patients", "cancer", "tumor", "carcinoma",
    "sars-cov-2", "covid", "depression", "osteoarthritis", "allergic rhinitis",
    "cucumber mosaic virus", "pepper mild mottle", "plant virus",
]

ERROR_MARKERS = [
    "[error]", "no result can be found", "does not allow downloading of the full text",
    "access denied", "forbidden", "not found", "captcha",
]


def clean(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def resolve_path(local_path: str | None) -> Path | None:
    if not local_path:
        return None
    path = Path(local_path)
    if not path.is_absolute():
        path = ROOT / path
    return path


def sniff_text(path: Path, limit: int = 4096) -> str:
    try:
        return path.read_text(encoding="utf-8-sig", errors="ignore")[:limit]
    except Exception:
        return ""


def audit_xml(path: Path) -> dict:
    head = sniff_text(path, 12000)
    lower = head.lower()
    if any(marker in lower for marker in ERROR_MARKERS):
        return {
            "file_type": "xml",
            "quality_label": "error_xml",
            "extractable_text_chars": 0,
            "notes": "XML-like file contains error/no-fulltext marker",
        }
    try:
        root = ET.fromstring(path.read_text(encoding="utf-8-sig", errors="ignore"))
    except Exception as exc:
        return {
            "file_type": "xml",
            "quality_label": "bad_xml",
            "extractable_text_chars": 0,
            "notes": f"XML parse failed: {type(exc).__name__}",
        }

    texts = []
    for elem in root.iter():
        tag = elem.tag.split("}")[-1]
        if tag in {"p", "abstract", "text"}:
            text = clean(" ".join(elem.itertext()))
            if len(text) >= 40:
                texts.append(text)
    total = sum(len(t) for t in texts)
    if total >= 2000:
        label = "valid_xml"
    elif total >= 300:
        label = "short_xml"
    else:
        label = "metadata_only_xml"
    return {
        "file_type": "xml",
        "quality_label": label,
        "extractable_text_chars": total,
        "notes": f"xml_text_blocks={len(texts)}",
    }


def audit_pdf(path: Path, max_pages: int = 8) -> dict:
    if fitz is None:
        return {
            "file_type": "pdf",
            "quality_label": "pdf_unchecked",
            "extractable_text_chars": 0,
            "notes": "PyMuPDF unavailable",
        }
    try:
        doc = fitz.open(str(path))
        page_count = doc.page_count
        texts = []
        for idx, page in enumerate(doc):
            if idx >= max_pages:
                break
            texts.append(page.get_text() or "")
        doc.close()
    except Exception as exc:
        return {
            "file_type": "pdf",
            "quality_label": "bad_pdf",
            "extractable_text_chars": 0,
            "notes": f"PDF parse failed: {type(exc).__name__}",
        }

    text = clean(" ".join(texts))
    text_chars = len(text)
    size = path.stat().st_size
    lower = text.lower()
    if size < 10_000:
        label = "tiny_pdf"
    elif any(marker in lower for marker in ERROR_MARKERS):
        label = "error_pdf"
    elif text_chars >= 3000:
        label = "valid_text_pdf"
    elif text_chars >= 300:
        label = "low_text_pdf"
    else:
        label = "scanned_or_image_pdf"
    return {
        "file_type": "pdf",
        "quality_label": label,
        "extractable_text_chars": text_chars,
        "notes": f"pages={page_count}; sampled_pages={min(page_count, max_pages)}",
    }


def source_rank(row: sqlite3.Row, path: Path | None, has_sections: bool) -> tuple:
    ext = (path.suffix.lower() if path else "")
    return (
        1 if has_sections else 0,
        1 if path and path.exists() else 0,
        2 if ext in {".xml", ".nxml"} else 1 if ext == ".pdf" else 0,
        int(row["fulltext_id"]),
    )


def priority_score(title: str, abstract: str, has_sections: bool, quality_label: str) -> int:
    text = f"{title} {abstract}".lower()
    score = 0
    for term in HIGH_VALUE_TERMS:
        if term in text:
            score += 3
    for term in LIKELY_IRRELEVANT_TERMS:
        if term in text:
            score -= 5
    if not has_sections:
        score += 5
    if quality_label in {"scanned_or_image_pdf", "low_text_pdf"}:
        score += 2
    if quality_label in {"error_xml", "bad_xml", "tiny_pdf", "bad_pdf"}:
        score += 1
    return score


def needs_action(quality_label: str, has_sections: bool, priority: int) -> str:
    if has_sections:
        return "ok_parsed"
    if quality_label in {"valid_xml", "short_xml", "valid_text_pdf"}:
        return "parser_review"
    if quality_label in {"scanned_or_image_pdf", "low_text_pdf"}:
        return "ocr_candidate" if priority >= 5 else "low_priority_ocr"
    if quality_label in {"error_xml", "bad_xml", "metadata_only_xml", "tiny_pdf", "bad_pdf", "missing_file"}:
        return "redownload" if priority >= 5 else "low_priority_redownload"
    return "manual_review"


def ensure_table(con: sqlite3.Connection) -> None:
    con.executescript(
        """
        CREATE TABLE IF NOT EXISTS literature_fulltext_quality (
            quality_id INTEGER PRIMARY KEY AUTOINCREMENT,
            reference_id INTEGER NOT NULL UNIQUE,
            best_fulltext_id INTEGER,
            file_exists INTEGER,
            file_type TEXT,
            file_size INTEGER,
            extractable_text_chars INTEGER,
            has_sections INTEGER,
            quality_label TEXT,
            needs_action TEXT,
            priority_score INTEGER,
            title TEXT,
            year TEXT,
            pmid TEXT,
            doi TEXT,
            pmcid TEXT,
            local_path TEXT,
            notes TEXT,
            audited_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(reference_id) REFERENCES ref_literatures(reference_id)
        );
        CREATE INDEX IF NOT EXISTS idx_fulltext_quality_action
            ON literature_fulltext_quality(needs_action, priority_score);
        """
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--all", action="store_true", help="Audit all references with fulltext sources, not just unsectioned refs.")
    parser.add_argument("--csv", default="")
    args = parser.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(DB_PATH), timeout=120)
    con.row_factory = sqlite3.Row
    ensure_table(con)

    rows = con.execute(
        """
        SELECT lfs.*, rl.title, rl.abstract, rl.year
        FROM literature_fulltext_sources lfs
        JOIN ref_literatures rl ON rl.reference_id = lfs.reference_id
        WHERE lfs.status IN ('downloaded', 'local')
          AND lfs.local_path IS NOT NULL
          AND trim(lfs.local_path) <> ''
        ORDER BY lfs.reference_id, lfs.fulltext_id
        """
    ).fetchall()

    by_ref: dict[int, list[sqlite3.Row]] = defaultdict(list)
    for row in rows:
        by_ref[int(row["reference_id"])].append(row)

    sectioned_refs = {
        int(r[0])
        for r in con.execute(
            "SELECT DISTINCT reference_id FROM literature_fulltext_sections WHERE reference_id IS NOT NULL"
        )
    }

    output_rows = []
    stats = defaultdict(int)
    for reference_id, candidates in by_ref.items():
        has_sections = reference_id in sectioned_refs
        if has_sections and not args.all:
            continue

        ranked = sorted(
            candidates,
            key=lambda r: source_rank(r, resolve_path(r["local_path"]), has_sections),
            reverse=True,
        )
        best = ranked[0]
        path = resolve_path(best["local_path"])
        file_exists = bool(path and path.exists())
        file_size = path.stat().st_size if file_exists else 0

        if not file_exists:
            audit = {
                "file_type": Path(best["local_path"] or "").suffix.lower().lstrip(".") or "",
                "quality_label": "missing_file",
                "extractable_text_chars": 0,
                "notes": "local_path does not exist",
            }
        elif path.suffix.lower() in {".xml", ".nxml"}:
            audit = audit_xml(path)
        elif path.suffix.lower() == ".pdf":
            audit = audit_pdf(path)
        else:
            audit = {
                "file_type": path.suffix.lower().lstrip("."),
                "quality_label": "unknown_file",
                "extractable_text_chars": 0,
                "notes": "unsupported file type",
            }

        priority = priority_score(best["title"] or "", best["abstract"] or "", has_sections, audit["quality_label"])
        action = needs_action(audit["quality_label"], has_sections, priority)

        out = {
            "reference_id": reference_id,
            "best_fulltext_id": int(best["fulltext_id"]),
            "file_exists": int(file_exists),
            "file_type": audit["file_type"],
            "file_size": file_size,
            "extractable_text_chars": audit["extractable_text_chars"],
            "has_sections": int(has_sections),
            "quality_label": audit["quality_label"],
            "needs_action": action,
            "priority_score": priority,
            "title": best["title"] or "",
            "year": best["year"] or "",
            "pmid": best["pmid"] or "",
            "doi": best["doi"] or "",
            "pmcid": best["pmcid"] or "",
            "local_path": best["local_path"] or "",
            "notes": audit["notes"],
        }
        output_rows.append(out)
        stats[f"quality:{out['quality_label']}"] += 1
        stats[f"action:{out['needs_action']}"] += 1

        con.execute(
            """
            INSERT INTO literature_fulltext_quality
            (reference_id, best_fulltext_id, file_exists, file_type, file_size,
             extractable_text_chars, has_sections, quality_label, needs_action,
             priority_score, title, year, pmid, doi, pmcid, local_path, notes, audited_at)
            VALUES
            (:reference_id, :best_fulltext_id, :file_exists, :file_type, :file_size,
             :extractable_text_chars, :has_sections, :quality_label, :needs_action,
             :priority_score, :title, :year, :pmid, :doi, :pmcid, :local_path, :notes,
             CURRENT_TIMESTAMP)
            ON CONFLICT(reference_id) DO UPDATE SET
                best_fulltext_id=excluded.best_fulltext_id,
                file_exists=excluded.file_exists,
                file_type=excluded.file_type,
                file_size=excluded.file_size,
                extractable_text_chars=excluded.extractable_text_chars,
                has_sections=excluded.has_sections,
                quality_label=excluded.quality_label,
                needs_action=excluded.needs_action,
                priority_score=excluded.priority_score,
                title=excluded.title,
                year=excluded.year,
                pmid=excluded.pmid,
                doi=excluded.doi,
                pmcid=excluded.pmcid,
                local_path=excluded.local_path,
                notes=excluded.notes,
                audited_at=CURRENT_TIMESTAMP
            """,
            out,
        )

    con.commit()

    csv_path = Path(args.csv) if args.csv else OUT_DIR / f"fulltext_quality_queue_{int(time.time())}.csv"
    with csv_path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(output_rows[0]) if output_rows else [
            "reference_id", "best_fulltext_id", "file_exists", "file_type", "file_size",
            "extractable_text_chars", "has_sections", "quality_label", "needs_action",
            "priority_score", "title", "year", "pmid", "doi", "pmcid", "local_path", "notes",
        ])
        writer.writeheader()
        writer.writerows(sorted(output_rows, key=lambda r: (-r["priority_score"], r["needs_action"], r["reference_id"])))

    report = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "audited_scope": "all_downloaded_local" if args.all else "unsectioned_downloaded_local",
        "audited_references": len(output_rows),
        "stats": dict(sorted(stats.items())),
        "csv": str(csv_path),
        "integrity_check": con.execute("PRAGMA integrity_check").fetchone()[0],
    }
    report_path = OUT_DIR / f"fulltext_quality_report_{int(time.time())}.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    con.close()

    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"CSV: {csv_path}")
    print(f"Report: {report_path}")


if __name__ == "__main__":
    main()
