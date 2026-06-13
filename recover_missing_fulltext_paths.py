#!/usr/bin/env python3
"""Relocate missing fulltext paths by strong DOI/PMCID/PMID matches in local files."""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime
from pathlib import Path


LOG_DIR = Path("downloads") / "fulltext_optimization"


def norm_doi(value: str | None) -> str:
    value = (value or "").lower().strip()
    value = re.sub(r"^https?://(dx\.)?doi\.org/", "", value)
    value = re.sub(r"[^a-z0-9]+", "_", value).strip("_")
    return value


def tokens_for(row) -> list[str]:
    _fid, _rid, pmid, doi, pmcid, _source, _local_path = row
    tokens = []
    if pmcid:
        tokens.append(str(pmcid).lower())
        tokens.append(str(pmcid).lower().replace("pmc", ""))
    if pmid:
        tokens.append(str(pmid).lower())
    doi_norm = norm_doi(doi)
    if doi_norm:
        tokens.append(doi_norm)
    return [t for t in tokens if len(t) >= 5]


def build_inventory(root: Path) -> list[Path]:
    dirs = [
        root / "literature_curation_v2" / "pmc_xml",
        root / "literature_curation_v2" / "fulltext",
        root / "literature_curation_v2" / "oa_fulltext",
        root / "downloads" / "literature_download_report" / "europe_pmc_pdfs",
    ]
    files = []
    for directory in dirs:
        if not directory.exists():
            continue
        files.extend(
            p for p in directory.rglob("*")
            if p.is_file() and p.suffix.lower() in {".pdf", ".xml", ".nxml"}
        )
    return files


def content_type(path: Path) -> str:
    if path.suffix.lower() == ".pdf":
        return "application/pdf"
    if path.suffix.lower() in {".xml", ".nxml"}:
        return "application/xml"
    return ""


def main() -> None:
    root = Path.cwd()
    con = sqlite3.connect("crustacean_virus_core.db", timeout=120)
    cur = con.cursor()
    rows = cur.execute(
        """
        SELECT fulltext_id, reference_id, pmid, doi, pmcid, source, local_path
        FROM literature_fulltext_sources
        WHERE local_path IS NOT NULL AND trim(local_path) <> ''
        """
    ).fetchall()

    missing = []
    for row in rows:
        path = Path(row[6])
        if not path.is_absolute():
            path = root / path
        if not path.exists():
            missing.append(row)

    files = build_inventory(root)
    updates = []
    ambiguous = []
    unresolved = []

    for row in missing:
        file_matches = []
        row_tokens = tokens_for(row)
        for path in files:
            name = path.name.lower()
            if any(token in name for token in row_tokens):
                file_matches.append(path)
        if len(file_matches) == 1:
            updates.append((row, file_matches[0]))
        elif len(file_matches) > 1:
            xml_matches = [p for p in file_matches if p.suffix.lower() in {".xml", ".nxml"}]
            if len(xml_matches) == 1:
                updates.append((row, xml_matches[0]))
            elif xml_matches:
                pmc_xml_matches = [p for p in xml_matches if p.name.lower().endswith("_pmc.xml")]
                if len(pmc_xml_matches) == 1:
                    updates.append((row, pmc_xml_matches[0]))
                else:
                    ambiguous.append((row, [str(p) for p in file_matches[:10]]))
            else:
                ambiguous.append((row, [str(p) for p in file_matches[:10]]))
        else:
            unresolved.append(row)

    for row, path in updates:
        fulltext_id = row[0]
        cur.execute(
            """
            UPDATE literature_fulltext_sources
            SET local_path = ?, status = 'downloaded', content_type = ?, error = NULL, checked_at = CURRENT_TIMESTAMP
            WHERE fulltext_id = ?
            """,
            (str(path), content_type(path), fulltext_id),
        )
    con.commit()
    con.close()

    report = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "missing_before": len(missing),
        "updated": len(updates),
        "ambiguous": len(ambiguous),
        "unresolved": len(unresolved),
        "updated_sample": [
            {
                "fulltext_id": row[0],
                "reference_id": row[1],
                "old_path": row[6],
                "new_path": str(path),
            }
            for row, path in updates[:20]
        ],
        "ambiguous_sample": ambiguous[:10],
        "unresolved_sample": unresolved[:20],
    }
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    out = LOG_DIR / "recover_missing_fulltext_paths_report.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"Log: {out}")


if __name__ == "__main__":
    main()
