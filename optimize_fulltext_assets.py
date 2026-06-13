#!/usr/bin/env python3
"""
Repair and parse local fulltext assets for AquaVir-KB.

This script is intentionally local-only:
- no network access
- no deletes
- no evidence extraction side effects
- all database changes are additive except local_path/status normalization
"""

from __future__ import annotations

import argparse
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


DB_PATH = Path("crustacean_virus_core.db")
LOG_DIR = Path("downloads") / "fulltext_optimization"
OLD_ROOTS = (
    Path(r"F:\甲壳动物数据库"),
)


SECTION_TYPES = {
    "abstract": "background",
    "intro": "background",
    "introduction": "background",
    "background": "background",
    "materials": "methods",
    "methods": "methods",
    "material and methods": "methods",
    "materials and methods": "methods",
    "results": "results",
    "result": "results",
    "discussion": "discussion",
    "conclusion": "discussion",
    "conclusions": "discussion",
}


def normalize_title(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def section_type_from_title(title: str | None, default: str = "body") -> str:
    clean = normalize_title(title).lower()
    for key, value in SECTION_TYPES.items():
        if key in clean:
            return value
    return default


def clean_text(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def candidate_dirs(root: Path) -> list[Path]:
    dirs = [
        root / "literature_curation_v2" / "pmc_xml",
        root / "literature_curation_v2" / "fulltext",
        root / "literature_curation_v2" / "oa_fulltext",
        root / "downloads" / "literature_download_report" / "europe_pmc_pdfs",
    ]
    return [d for d in dirs if d.exists()]


def build_file_index(root: Path) -> dict[str, list[Path]]:
    index: dict[str, list[Path]] = defaultdict(list)
    for directory in candidate_dirs(root):
        for path in directory.rglob("*"):
            if path.is_file() and path.suffix.lower() in {".pdf", ".xml", ".nxml"}:
                index[path.name].append(path)
    return index


def path_exists(path_text: str, root: Path) -> Path | None:
    path = Path(path_text)
    if path.exists():
        return path
    if not path.is_absolute():
        candidate = root / path
        if candidate.exists():
            return candidate
    return None


def remap_old_path(path_text: str, root: Path) -> Path | None:
    path = Path(path_text)
    for old_root in OLD_ROOTS:
        try:
            relative = path.relative_to(old_root)
        except ValueError:
            continue
        candidate = root / relative
        if candidate.exists():
            return candidate
    return None


def find_replacement(path_text: str, root: Path, file_index: dict[str, list[Path]]) -> Path | None:
    existing = path_exists(path_text, root)
    if existing:
        return existing

    remapped = remap_old_path(path_text, root)
    if remapped:
        return remapped

    matches = file_index.get(Path(path_text).name, [])
    if len(matches) == 1:
        return matches[0]
    return None


def extract_xml_sections(path: Path) -> list[tuple[str, str, str]]:
    try:
        content = path.read_text(encoding="utf-8-sig", errors="ignore")
        if "does not allow downloading of the full text" in content:
            return []
        root = ET.fromstring(content)
    except Exception:
        return []

    if root.tag.split("}")[-1] == "collection":
        return extract_bioc_sections(root)

    sections: list[tuple[str, str, str]] = []

    for abstract in root.iter():
        tag = abstract.tag.split("}")[-1]
        if tag != "abstract":
            continue
        text = clean_text(" ".join(abstract.itertext()))
        if len(text) >= 120:
            sections.append(("Abstract", "background", text))
        break

    sec_counter = 0
    for sec in root.iter():
        tag = sec.tag.split("}")[-1]
        if tag != "sec":
            continue

        title = ""
        paragraphs: list[str] = []
        for child in list(sec):
            child_tag = child.tag.split("}")[-1]
            if child_tag == "title" and not title:
                title = clean_text(" ".join(child.itertext()))
            elif child_tag == "p":
                text = clean_text(" ".join(child.itertext()))
                if len(text) >= 80:
                    paragraphs.append(text)

        text = clean_text(" ".join(paragraphs))
        if len(text) < 160:
            continue

        sec_counter += 1
        section_title = title or f"XML section {sec_counter}"
        sections.append((section_title, section_type_from_title(section_title), text))

    if sections:
        return sections

    paragraphs = []
    for elem in root.iter():
        tag = elem.tag.split("}")[-1]
        if tag == "p":
            text = clean_text(" ".join(elem.itertext()))
            if len(text) >= 80:
                paragraphs.append(text)
    text = clean_text(" ".join(paragraphs))
    if len(text) >= 160:
        sections.append(("XML body", "body", text))
    return sections


def extract_bioc_sections(root: ET.Element) -> list[tuple[str, str, str]]:
    grouped: dict[str, list[str]] = defaultdict(list)
    title_by_group: dict[str, str] = {}

    for passage in root.iter():
        if passage.tag.split("}")[-1] != "passage":
            continue

        metadata = {}
        text = ""
        for child in list(passage):
            tag = child.tag.split("}")[-1]
            if tag == "infon":
                key = child.attrib.get("key", "")
                metadata[key] = clean_text(" ".join(child.itertext()))
            elif tag == "text":
                text = clean_text(" ".join(child.itertext()))

        if len(text) < 40:
            continue

        raw_type = (metadata.get("section_type") or metadata.get("type") or "body").lower()
        passage_type = (metadata.get("type") or "").lower()

        if passage_type.startswith("title"):
            title_by_group[raw_type] = text
            continue
        if any(token in raw_type for token in ("ref", "table", "fig", "caption", "front")):
            continue

        grouped[raw_type].append(text)

    sections: list[tuple[str, str, str]] = []
    for raw_type, paragraphs in grouped.items():
        text = clean_text(" ".join(paragraphs))
        if len(text) < 160:
            continue
        title = title_by_group.get(raw_type) or raw_type.upper()
        sections.append((title, section_type_from_title(raw_type), text))

    if sections:
        return sections

    fallback = []
    for text_node in root.iter():
        if text_node.tag.split("}")[-1] == "text":
            text = clean_text(" ".join(text_node.itertext()))
            if len(text) >= 80:
                fallback.append(text)
    text = clean_text(" ".join(fallback))
    if len(text) >= 160:
        return [("BioC body", "body", text)]
    return []


def extract_pdf_sections(path: Path, max_chars: int) -> list[tuple[str, str, str]]:
    if fitz is None:
        return []
    try:
        doc = fitz.open(str(path))
        pages = []
        for page in doc:
            text = page.get_text()
            if text:
                pages.append(text)
        doc.close()
    except Exception:
        return []

    text = clean_text(" ".join(pages))
    if len(text) < 160:
        return []
    return [("PDF extracted body", "body", text[:max_chars])]


def content_type_for_path(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return "application/pdf"
    if suffix in {".xml", ".nxml"}:
        return "application/xml"
    return ""


def repair_paths(con: sqlite3.Connection, root: Path, dry_run: bool) -> dict[str, int]:
    file_index = build_file_index(root)
    cur = con.cursor()
    rows = cur.execute(
        """
        SELECT fulltext_id, reference_id, status, content_type, local_path
        FROM literature_fulltext_sources
        WHERE local_path IS NOT NULL AND trim(local_path) <> ''
        """
    ).fetchall()

    stats = {
        "local_path_rows": len(rows),
        "already_existing": 0,
        "paths_repaired": 0,
        "status_normalized": 0,
        "still_missing": 0,
    }

    for fulltext_id, _reference_id, status, content_type, local_path in rows:
        replacement = find_replacement(local_path, root, file_index)
        if replacement is None:
            stats["still_missing"] += 1
            continue

        if Path(local_path).exists():
            stats["already_existing"] += 1

        new_status = "downloaded" if status in {"failed", "no_oa", "skipped"} else status
        new_content_type = content_type or content_type_for_path(replacement)
        new_path = str(replacement)

        needs_update = (
            new_path != local_path
            or new_status != status
            or (new_content_type and new_content_type != content_type)
        )
        if not needs_update:
            continue

        if new_path != local_path:
            stats["paths_repaired"] += 1
        if new_status != status:
            stats["status_normalized"] += 1

        if not dry_run:
            cur.execute(
                """
                UPDATE literature_fulltext_sources
                SET local_path = ?, status = ?, content_type = ?, error = NULL, checked_at = CURRENT_TIMESTAMP
                WHERE fulltext_id = ?
                """,
                (new_path, new_status, new_content_type, fulltext_id),
            )

    if not dry_run:
        con.commit()
    return stats


def parse_unsectioned(con: sqlite3.Connection, root: Path, dry_run: bool, limit: int, max_pdf_chars: int) -> dict[str, int]:
    cur = con.cursor()
    rows = cur.execute(
        """
        SELECT lfs.fulltext_id, lfs.reference_id, lfs.local_path
        FROM literature_fulltext_sources lfs
        WHERE lfs.status IN ('downloaded', 'local')
          AND lfs.local_path IS NOT NULL
          AND trim(lfs.local_path) <> ''
          AND NOT EXISTS (
              SELECT 1 FROM literature_fulltext_sections s
              WHERE s.fulltext_id = lfs.fulltext_id
          )
        ORDER BY lfs.reference_id, lfs.fulltext_id
        """
    ).fetchall()

    stats = {
        "candidates": len(rows),
        "processed": 0,
        "xml_parsed": 0,
        "pdf_parsed": 0,
        "missing_file": 0,
        "no_text": 0,
        "sections_inserted": 0,
        "refs_newly_sectioned": 0,
    }
    refs_newly_sectioned = set()

    for fulltext_id, reference_id, local_path in rows:
        if limit and stats["processed"] >= limit:
            break

        path = path_exists(local_path, root)
        if path is None:
            stats["missing_file"] += 1
            continue

        suffix = path.suffix.lower()
        if suffix in {".xml", ".nxml"}:
            sections = extract_xml_sections(path)
            if sections:
                stats["xml_parsed"] += 1
        elif suffix == ".pdf":
            sections = extract_pdf_sections(path, max_pdf_chars)
            if sections:
                stats["pdf_parsed"] += 1
        else:
            sections = []

        stats["processed"] += 1
        if not sections:
            stats["no_text"] += 1
            continue

        inserted_for_ref = 0
        for section_title, section_type, text in sections:
            if dry_run:
                inserted_for_ref += 1
                continue
            cur.execute(
                """
                INSERT OR IGNORE INTO literature_fulltext_sections
                (fulltext_id, reference_id, section_title, section_type, text, char_count)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (fulltext_id, reference_id, section_title, section_type, text, len(text)),
            )
            inserted_for_ref += cur.rowcount

        if inserted_for_ref:
            stats["sections_inserted"] += inserted_for_ref
            refs_newly_sectioned.add(reference_id)

        if not dry_run and stats["processed"] % 100 == 0:
            con.commit()

    if not dry_run:
        con.commit()
    stats["refs_newly_sectioned"] = len(refs_newly_sectioned)
    return stats


def current_metrics(con: sqlite3.Connection, root: Path) -> dict[str, int]:
    cur = con.cursor()
    local_rows = cur.execute(
        """
        SELECT reference_id, local_path
        FROM literature_fulltext_sources
        WHERE local_path IS NOT NULL AND trim(local_path) <> ''
        """
    ).fetchall()
    existing_refs = {
        reference_id
        for reference_id, local_path in local_rows
        if reference_id is not None and path_exists(local_path, root)
    }

    return {
        "total_references": cur.execute("SELECT COUNT(*) FROM ref_literatures").fetchone()[0],
        "downloaded_or_local_refs": cur.execute(
            """
            SELECT COUNT(DISTINCT reference_id)
            FROM literature_fulltext_sources
            WHERE status IN ('downloaded', 'local') AND reference_id IS NOT NULL
            """
        ).fetchone()[0],
        "refs_with_existing_local_file": len(existing_refs),
        "refs_with_sections": cur.execute(
            """
            SELECT COUNT(DISTINCT reference_id)
            FROM literature_fulltext_sections
            WHERE reference_id IS NOT NULL
            """
        ).fetchone()[0],
        "section_rows": cur.execute("SELECT COUNT(*) FROM literature_fulltext_sections").fetchone()[0],
        "section_chars": cur.execute("SELECT COALESCE(SUM(char_count), 0) FROM literature_fulltext_sections").fetchone()[0],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=str(DB_PATH))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=0, help="Limit parsed fulltext sources; 0 means no limit.")
    parser.add_argument("--max-pdf-chars", type=int, default=80000)
    args = parser.parse_args()

    root = Path.cwd()
    db = Path(args.db)
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    con = sqlite3.connect(str(db), timeout=120)
    before = current_metrics(con, root)
    started = time.time()
    path_stats = repair_paths(con, root, args.dry_run)
    parse_stats = parse_unsectioned(con, root, args.dry_run, args.limit, args.max_pdf_chars)
    after = current_metrics(con, root)
    con.close()

    report = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "dry_run": args.dry_run,
        "elapsed_seconds": round(time.time() - started, 2),
        "before": before,
        "path_repair": path_stats,
        "parse": parse_stats,
        "after": after,
    }

    log_path = LOG_DIR / f"fulltext_optimization_{int(time.time())}.json"
    log_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"Log: {log_path}")


if __name__ == "__main__":
    main()
