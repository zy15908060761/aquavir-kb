#!/usr/bin/env python3
"""Strengthen literature evidence for the crustacean virus database.

The importer is conservative: it creates a backup, keeps non-PubMed hits in a
reviewable candidate table, and imports extracted claims as ``needs_review``.
It intentionally uses more than PubMed: cached Semantic Scholar results,
Crossref/OpenAlex/Europe PMC live searches, GenBank-linked references, and
authoritative-source queues such as WOAH/FAO/CNKI/Wanfang guides.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import re
import shutil
import sqlite3
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "crustacean_virus_core.db"
BACKUP_DIR = BASE_DIR / "backups"
EXTERNAL_DIR = BASE_DIR / "external_data" / "multi_source_mining"
REPORT_DIR = BASE_DIR / "reports"

CONTACT_EMAIL = "curator@crustacean-virus-db.org"
REQUEST_DELAY = 0.7
USER_AGENT = f"crustacean-virus-db-literature/1.0 (mailto:{CONTACT_EMAIL})"

EVIDENCE_KEYWORDS = {
    "mortality": ["mortality", "lethal", "death", "survival", "ld50"],
    "temperature": ["temperature", "thermal", "heat", "cold", "inactivation", "climate"],
    "virulence": ["virulence", "pathogenic", "pathogenicity", "infection", "disease"],
    "diagnosis": ["diagnostic", "diagnosis", "pcr", "lamp", "elisa", "qpcr", "rt-pcr", "detection"],
    "control": ["control", "vaccine", "immunostimulant", "biosecurity", "disinfection", "dsrna", "rna interference"],
    "host_range": ["host range", "susceptibility", "natural infection", "experimental infection"],
}

SOURCE_DEFS = [
    ("genbank_pubmed", "GenBank-linked literature", "literature", "https://www.ncbi.nlm.nih.gov/nuccore/", 10),
    ("semantic_scholar", "Semantic Scholar", "literature_index", "https://www.semanticscholar.org/", 30),
    ("crossref", "Crossref Works", "literature_index", "https://api.crossref.org/works", 35),
    ("openalex", "OpenAlex", "literature_index", "https://openalex.org/", 36),
    ("europe_pmc", "Europe PMC", "literature_index", "https://europepmc.org/", 37),
    ("woah", "WOAH Aquatic Manual / Code / WAHIS", "authority", "https://www.woah.org/", 15),
    ("fao", "FAO Fisheries and Aquaculture", "authority", "https://www.fao.org/fishery/", 20),
    ("naca", "Network of Aquaculture Centres in Asia-Pacific", "authority", "https://enaca.org/", 25),
    ("cabi", "CABI Compendium", "authority", "https://www.cabidigitallibrary.org/", 28),
    ("cnki", "CNKI", "chinese_literature", "https://www.cnki.net/", 40),
    ("wanfang", "Wanfang Data", "chinese_literature", "https://www.wanfangdata.com.cn/", 41),
    ("manual_queue", "Manual literature review queue", "curation_queue", None, 50),
]


@dataclass
class Candidate:
    source_key: str
    target_virus: str
    title: str
    authors: str = ""
    journal: str = ""
    year: str = ""
    doi: str = ""
    pmid: str = ""
    url: str = ""
    abstract: str = ""
    evidence_scope: str = "other"
    claim_hint: str = ""
    relevance_score: float = 0.0
    raw: dict[str, Any] | None = None


def now_stamp() -> str:
    return dt.datetime.now().strftime("%Y%m%d_%H%M%S")


def normalize_text(value: str | None) -> str:
    value = (value or "").lower()
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def evidence_scope_for(text: str) -> str:
    haystack = text.lower()
    scores: dict[str, int] = {}
    for scope, keywords in EVIDENCE_KEYWORDS.items():
        scores[scope] = sum(1 for k in keywords if k in haystack)
    best, score = max(scores.items(), key=lambda x: x[1])
    return best if score else "other"


def get_json(url: str, timeout: int = 40) -> dict[str, Any]:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))


def table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name = ?", (table,)
        ).fetchone()
        is not None
    )


def backup_database() -> Path:
    BACKUP_DIR.mkdir(exist_ok=True)
    backup = BACKUP_DIR / f"crustacean_virus_core_before_lit_evidence_{now_stamp()}.db"
    shutil.copy2(DB_PATH, backup)
    return backup


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS literature_evidence_candidates (
            candidate_id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_id INTEGER,
            source_key TEXT NOT NULL,
            target_virus TEXT NOT NULL,
            master_id INTEGER,
            reference_id INTEGER,
            title TEXT NOT NULL,
            authors TEXT,
            journal TEXT,
            year TEXT,
            doi TEXT,
            pmid TEXT,
            url TEXT,
            evidence_scope TEXT DEFAULT 'other',
            claim_hint TEXT,
            relevance_score REAL DEFAULT 0,
            abstract TEXT,
            raw_json TEXT,
            curation_status TEXT DEFAULT 'needs_review',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (source_id) REFERENCES external_sources(source_id),
            FOREIGN KEY (master_id) REFERENCES virus_master(master_id),
            FOREIGN KEY (reference_id) REFERENCES ref_literatures(reference_id)
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_lit_candidates_virus
        ON literature_evidence_candidates(master_id, target_virus)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_lit_candidates_source
        ON literature_evidence_candidates(source_key)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_lit_candidates_identifier
        ON literature_evidence_candidates(pmid, doi)
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS literature_evidence_import_log (
            log_id INTEGER PRIMARY KEY AUTOINCREMENT,
            action TEXT NOT NULL,
            details_json TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    for key, name, category, base_url, priority in SOURCE_DEFS:
        conn.execute(
            """
            INSERT INTO external_sources(source_key, name, category, base_url, description, update_policy, priority)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(source_key) DO UPDATE SET
                name = excluded.name,
                category = excluded.category,
                base_url = excluded.base_url,
                priority = excluded.priority,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                key,
                name,
                category,
                base_url,
                f"Literature/evidence source for crustacean virus curation: {name}",
                "manual_or_scripted_refresh",
                priority,
            ),
        )


def source_id(conn: sqlite3.Connection, key: str) -> int | None:
    row = conn.execute("SELECT source_id FROM external_sources WHERE source_key = ?", (key,)).fetchone()
    return int(row["source_id"]) if row else None


def master_map(conn: sqlite3.Connection) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for row in conn.execute(
        """
        SELECT master_id, canonical_name, abbreviations, chinese_name
        FROM virus_master
        WHERE is_crustacean_virus = 1
        """
    ):
        names = [row["canonical_name"], row["chinese_name"]]
        names += re.split(r"[,;/|]+", row["abbreviations"] or "")
        for name in names:
            norm = normalize_text(name)
            if norm:
                out[norm] = dict(row)
    return out


def find_master(conn: sqlite3.Connection, virus_name: str, name_map: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    norm = normalize_text(virus_name)
    if norm in name_map:
        return name_map[norm]
    row = conn.execute(
        """
        SELECT master_id, canonical_name, abbreviations, chinese_name
        FROM virus_master
        WHERE lower(canonical_name) = lower(?)
           OR lower(COALESCE(abbreviations, '')) LIKE '%' || lower(?) || '%'
        LIMIT 1
        """,
        (virus_name, virus_name),
    ).fetchone()
    return dict(row) if row else None


def upsert_reference(conn: sqlite3.Connection, c: Candidate) -> int | None:
    pmid = c.pmid.strip()
    doi = c.doi.strip()
    title = c.title.strip()
    if pmid:
        row = conn.execute("SELECT reference_id FROM ref_literatures WHERE pmid = ?", (pmid,)).fetchone()
        if row:
            ref_id = int(row["reference_id"])
            if doi:
                conn.execute("UPDATE ref_literatures SET doi = COALESCE(NULLIF(doi, ''), ?) WHERE reference_id = ?", (doi, ref_id))
            return ref_id
    if doi:
        row = conn.execute(
            "SELECT reference_id FROM ref_literatures WHERE lower(COALESCE(doi, '')) = lower(?)",
            (doi,),
        ).fetchone()
        if row:
            ref_id = int(row["reference_id"])
            if pmid:
                conn.execute("UPDATE ref_literatures SET pmid = COALESCE(NULLIF(pmid, ''), ?) WHERE reference_id = ?", (pmid, ref_id))
            return ref_id
    if title:
        row = conn.execute(
            "SELECT reference_id FROM ref_literatures WHERE lower(title) = lower(?)",
            (title,),
        ).fetchone()
        if row:
            return int(row["reference_id"])
    if not (pmid or doi or title):
        return None
    try:
        cur = conn.execute(
            """
            INSERT INTO ref_literatures(pmid, title, authors, journal, year, doi, abstract, keywords)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                pmid or None,
                title,
                c.authors,
                c.journal,
                c.year,
                doi,
                c.abstract,
                f"source:{c.source_key}; evidence_scope:{c.evidence_scope}",
            ),
        )
        return int(cur.lastrowid)
    except sqlite3.IntegrityError:
        if pmid:
            row = conn.execute("SELECT reference_id FROM ref_literatures WHERE pmid = ?", (pmid,)).fetchone()
            return int(row["reference_id"]) if row else None
        return None


def upsert_candidate(
    conn: sqlite3.Connection,
    c: Candidate,
    ref_id: int | None,
    master: dict[str, Any] | None,
) -> tuple[int | None, bool]:
    key_title = normalize_text(c.title)
    row = conn.execute(
        """
        SELECT candidate_id FROM literature_evidence_candidates
        WHERE source_key = ?
          AND target_virus = ?
          AND (
                (pmid IS NOT NULL AND pmid != '' AND pmid = ?)
             OR (doi IS NOT NULL AND doi != '' AND lower(doi) = lower(?))
             OR lower(title) = lower(?)
          )
        LIMIT 1
        """,
        (c.source_key, c.target_virus, c.pmid, c.doi, c.title),
    ).fetchone()
    if row:
        candidate_id = int(row["candidate_id"])
        conn.execute(
            """
            UPDATE literature_evidence_candidates
            SET reference_id = COALESCE(reference_id, ?),
                master_id = COALESCE(master_id, ?),
                relevance_score = MAX(relevance_score, ?),
                updated_at = CURRENT_TIMESTAMP
            WHERE candidate_id = ?
            """,
            (ref_id, master["master_id"] if master else None, c.relevance_score, candidate_id),
        )
        return candidate_id, False
    if not key_title:
        return None, False
    cur = conn.execute(
        """
        INSERT INTO literature_evidence_candidates(
            source_id, source_key, target_virus, master_id, reference_id, title,
            authors, journal, year, doi, pmid, url, evidence_scope, claim_hint,
            relevance_score, abstract, raw_json
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            source_id(conn, c.source_key),
            c.source_key,
            c.target_virus,
            master["master_id"] if master else None,
            ref_id,
            c.title,
            c.authors,
            c.journal,
            c.year,
            c.doi,
            c.pmid,
            c.url,
            c.evidence_scope,
            c.claim_hint,
            c.relevance_score,
            c.abstract,
            json.dumps(c.raw or {}, ensure_ascii=False, sort_keys=True),
        ),
    )
    return int(cur.lastrowid), True


def add_evidence_record(
    conn: sqlite3.Connection,
    c: Candidate,
    ref_id: int | None,
    master: dict[str, Any] | None,
    evidence_type: str,
    claim: str,
    value_text: str = "",
) -> bool:
    if not master:
        return False
    exists = conn.execute(
        """
        SELECT 1 FROM evidence_records
        WHERE evidence_type = ?
          AND virus_master_id = ?
          AND COALESCE(reference_id, -1) = COALESCE(?, -1)
          AND claim = ?
          AND COALESCE(source_pmid, '') = ?
          AND COALESCE(source_doi, '') = ?
        LIMIT 1
        """,
        (evidence_type, master["master_id"], ref_id, claim, c.pmid, c.doi),
    ).fetchone()
    if exists:
        return False
    conn.execute(
        """
        INSERT INTO evidence_records(
            evidence_type, virus_master_id, reference_id, source_id, claim,
            value_text, context, observation_type, evidence_strength,
            source_pmid, source_doi, extraction_method, curation_status, notes
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            evidence_type,
            master["master_id"],
            ref_id,
            source_id(conn, c.source_key),
            claim,
            value_text,
            c.abstract[:1000] if c.abstract else "",
            "unknown",
            "low" if c.source_key in {"semantic_scholar", "crossref", "openalex"} else "medium",
            c.pmid,
            c.doi,
            f"{c.source_key}_literature_evidence_import",
            "needs_review",
            "Auto-imported as review candidate; verify against full text before promoting.",
        ),
    )
    return True


def load_master_review_queue() -> list[Candidate]:
    path = EXTERNAL_DIR / "master_review_queue.csv"
    if not path.exists():
        return []
    candidates: list[Candidate] = []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            category = (row.get("category") or "").strip()
            target = (row.get("target_virus") or "").strip()
            if not target:
                continue
            evidence_type = "temperature" if category.startswith("temperature") else (
                "mortality" if "mortality" in category or "LD50" in category else "virulence"
            )
            title = (row.get("title") or "").strip()
            candidates.append(
                Candidate(
                    source_key="genbank_pubmed",
                    target_virus=target,
                    title=title,
                    year=row.get("year", ""),
                    pmid=row.get("pmid", ""),
                    abstract=row.get("context_window", ""),
                    evidence_scope=evidence_type,
                    claim_hint=f"{category}: {row.get('value', '')}".strip(": "),
                    relevance_score=80,
                    raw=row,
                )
            )
    return candidates


def load_semantic_scholar_cache() -> list[Candidate]:
    path = EXTERNAL_DIR / "semantic_scholar" / "s2_search_results.csv"
    if not path.exists():
        return []
    candidates: list[Candidate] = []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            target = (row.get("target_virus") or "").strip()
            title = (row.get("title") or "").strip()
            abstract = row.get("abstract", "") or ""
            if not target or not title:
                continue
            text = f"{title} {abstract}"
            scope = evidence_scope_for(text)
            if scope == "other":
                continue
            ext = {}
            try:
                ext = json.loads(row.get("externalIds") or "{}")
            except json.JSONDecodeError:
                ext = {}
            doi = ext.get("DOI") or ""
            pmid = str(ext.get("PubMed") or ext.get("PMID") or "")
            url = f"https://doi.org/{doi}" if doi else (f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if pmid else "")
            candidates.append(
                Candidate(
                    source_key="semantic_scholar",
                    target_virus=target,
                    title=title,
                    journal=row.get("journal", ""),
                    year=row.get("year", ""),
                    doi=doi,
                    pmid=pmid,
                    url=url,
                    abstract=abstract,
                    evidence_scope=scope,
                    claim_hint=f"Potential {scope} evidence from Semantic Scholar search.",
                    relevance_score=float(row.get("citationCount") or 0),
                    raw=row,
                )
            )
    return candidates


def load_authority_guides() -> list[Candidate]:
    path = EXTERNAL_DIR / "cnki" / "fao_woah_reference_guide.csv"
    if not path.exists():
        return []
    candidates: list[Candidate] = []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            source = (row.get("source") or "").lower()
            source_key = "manual_queue"
            if "woah" in source or "oie" in source:
                source_key = "woah"
            elif "fao" in source:
                source_key = "fao"
            elif "naca" in source:
                source_key = "naca"
            elif "cabi" in source:
                source_key = "cabi"
            title = f"{row.get('source', '').strip()}: {row.get('description', '').strip()}"
            diseases = row.get("relevant_diseases", "")
            for target in [x.strip() for x in re.split(r"[,;/]+", diseases) if x.strip()]:
                candidates.append(
                    Candidate(
                        source_key=source_key,
                        target_virus=target,
                        title=title,
                        url=row.get("url", ""),
                        evidence_scope="other",
                        claim_hint=row.get("note", ""),
                        relevance_score=60,
                        raw=row,
                    )
                )
    return candidates


def load_import_suggestions() -> list[Candidate]:
    path = EXTERNAL_DIR / "import_suggestions.csv"
    if not path.exists():
        return []
    candidates: list[Candidate] = []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            target = (row.get("virus_name") or "").strip()
            pmids = [p.strip() for p in (row.get("evidence_pmids") or "").split(";") if p.strip()]
            for pmid in pmids:
                candidates.append(
                    Candidate(
                        source_key="manual_queue",
                        target_virus=target,
                        title=f"Aggregate evidence candidate for {target} ({row.get('data_type', '')})",
                        pmid=pmid,
                        evidence_scope="mortality" if "mortality" in (row.get("data_type") or "") else "virulence",
                        claim_hint=f"{row.get('data_type')}: {row.get('suggested_value')} ({row.get('source_description')})",
                        relevance_score=55,
                        raw=row,
                    )
                )
    return candidates


def target_viruses(conn: sqlite3.Connection, limit: int) -> list[str]:
    priority = [
        "White spot syndrome virus",
        "Yellow head virus",
        "Taura syndrome virus",
        "Infectious hypodermal and hematopoietic necrosis virus",
        "Penaeid shrimp infectious myonecrosis virus",
        "Macrobrachium rosenbergii nodavirus",
        "Decapod iridescent virus",
        "Covert mortality nodavirus",
        "Hepatopancreatic parvovirus",
        "Shrimp hemocyte iridescent virus",
        "Infectious precocity virus",
        "Chinese mitten crab virus",
        "Mud crab virus",
        "Laem-Singh virus",
        "Wenzhou shrimp virus",
    ]
    existing = {r["canonical_name"] for r in conn.execute("SELECT canonical_name FROM virus_master")}
    chosen = [v for v in priority if v in existing]
    if len(chosen) < limit:
        for row in conn.execute(
            """
            SELECT vm.canonical_name, COUNT(v.isolate_id) AS n
            FROM virus_master vm
            LEFT JOIN viral_isolates v ON v.master_id = vm.master_id
            WHERE vm.is_crustacean_virus = 1
            GROUP BY vm.master_id
            ORDER BY n DESC
            """
        ):
            if row["canonical_name"] not in chosen:
                chosen.append(row["canonical_name"])
            if len(chosen) >= limit:
                break
    return chosen[:limit]


def search_crossref(virus: str, rows: int) -> list[Candidate]:
    query = f"{virus} virulence mortality temperature diagnosis shrimp crab crustacean"
    params = urllib.parse.urlencode(
        {"query": query, "rows": str(rows), "sort": "relevance", "order": "desc", "mailto": CONTACT_EMAIL}
    )
    data = get_json(f"https://api.crossref.org/works?{params}")
    out: list[Candidate] = []
    for item in data.get("message", {}).get("items", []):
        titles = item.get("title") or []
        title = str(titles[0]) if titles else ""
        if not title:
            continue
        abstract = re.sub(r"<[^>]+>", " ", item.get("abstract") or "")
        scope = evidence_scope_for(f"{title} {abstract}")
        if scope == "other":
            continue
        authors = "; ".join(
            f"{a.get('given', '')} {a.get('family', '')}".strip()
            for a in item.get("author", [])[:8]
            if a.get("family")
        )
        journal = "; ".join(item.get("container-title") or [])
        date_parts = (
            item.get("published-print", {}).get("date-parts")
            or item.get("published-online", {}).get("date-parts")
            or item.get("created", {}).get("date-parts")
            or [[]]
        )
        year = str(date_parts[0][0]) if date_parts and date_parts[0] else ""
        doi = item.get("DOI") or ""
        out.append(
            Candidate(
                source_key="crossref",
                target_virus=virus,
                title=title,
                authors=authors,
                journal=journal,
                year=year,
                doi=doi,
                url=item.get("URL") or (f"https://doi.org/{doi}" if doi else ""),
                abstract=abstract,
                evidence_scope=scope,
                claim_hint=f"Potential {scope} evidence from Crossref.",
                relevance_score=float(item.get("score") or 0),
                raw=item,
            )
        )
    return out


def search_openalex(virus: str, rows: int) -> list[Candidate]:
    query = f"{virus} virulence mortality temperature diagnosis crustacean"
    params = urllib.parse.urlencode(
        {
            "search": query,
            "per-page": str(rows),
            "mailto": CONTACT_EMAIL,
            "filter": "from_publication_date:1990-01-01",
        }
    )
    data = get_json(f"https://api.openalex.org/works?{params}")
    out: list[Candidate] = []
    for item in data.get("results", []):
        title = item.get("title") or item.get("display_name") or ""
        if not title:
            continue
        abstract = " ".join((item.get("abstract_inverted_index") or {}).keys())
        scope = evidence_scope_for(f"{title} {abstract}")
        if scope == "other":
            continue
        authors = "; ".join(
            a.get("author", {}).get("display_name", "")
            for a in item.get("authorships", [])[:8]
            if a.get("author", {}).get("display_name")
        )
        doi = (item.get("doi") or "").replace("https://doi.org/", "")
        pmid = ""
        for loc in item.get("locations", []) or []:
            ids = ((loc.get("source") or {}).get("ids") or {})
            if ids.get("pmid"):
                pmid = str(ids["pmid"]).rsplit("/", 1)[-1]
        out.append(
            Candidate(
                source_key="openalex",
                target_virus=virus,
                title=title,
                authors=authors,
                journal=((item.get("primary_location") or {}).get("source") or {}).get("display_name", ""),
                year=str(item.get("publication_year") or ""),
                doi=doi,
                pmid=pmid,
                url=item.get("id", ""),
                abstract=abstract,
                evidence_scope=scope,
                claim_hint=f"Potential {scope} evidence from OpenAlex.",
                relevance_score=float(item.get("cited_by_count") or 0),
                raw=item,
            )
        )
    return out


def search_europe_pmc(virus: str, rows: int) -> list[Candidate]:
    query = f'"{virus}" AND (virulence OR mortality OR temperature OR diagnosis OR control)'
    params = urllib.parse.urlencode({"query": query, "format": "json", "pageSize": str(rows)})
    data = get_json(f"https://www.ebi.ac.uk/europepmc/webservices/rest/search?{params}")
    out: list[Candidate] = []
    for item in data.get("resultList", {}).get("result", []):
        title = item.get("title") or ""
        abstract = item.get("abstractText") or ""
        scope = evidence_scope_for(f"{title} {abstract}")
        if not title or scope == "other":
            continue
        out.append(
            Candidate(
                source_key="europe_pmc",
                target_virus=virus,
                title=title,
                authors=item.get("authorString", ""),
                journal=item.get("journalTitle", ""),
                year=str(item.get("pubYear") or ""),
                doi=item.get("doi", ""),
                pmid=item.get("pmid", ""),
                url=f"https://europepmc.org/article/{item.get('source', '')}/{item.get('id', '')}",
                abstract=abstract,
                evidence_scope=scope,
                claim_hint=f"Potential {scope} evidence from Europe PMC.",
                relevance_score=float(item.get("citedByCount") or 0),
                raw=item,
            )
        )
    return out


def write_candidate_csv(candidates: list[Candidate], path: Path) -> None:
    path.parent.mkdir(exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "source_key",
                "target_virus",
                "evidence_scope",
                "year",
                "title",
                "journal",
                "doi",
                "pmid",
                "url",
                "claim_hint",
                "relevance_score",
            ],
        )
        writer.writeheader()
        for c in candidates:
            writer.writerow({k: getattr(c, k) for k in writer.fieldnames})


def coverage_snapshot(conn: sqlite3.Connection) -> dict[str, Any]:
    def one(sql: str, params: tuple = ()) -> int:
        return int(conn.execute(sql, params).fetchone()[0])

    out = {
        "ref_literatures": one("SELECT COUNT(*) FROM ref_literatures"),
        "ref_with_pmid": one("SELECT COUNT(*) FROM ref_literatures WHERE COALESCE(pmid, '') != ''"),
        "ref_with_doi": one("SELECT COUNT(*) FROM ref_literatures WHERE COALESCE(doi, '') != ''"),
        "evidence_records": one("SELECT COUNT(*) FROM evidence_records"),
        "evidence_with_reference": one("SELECT COUNT(*) FROM evidence_records WHERE reference_id IS NOT NULL"),
        "evidence_with_source_pmid": one("SELECT COUNT(*) FROM evidence_records WHERE COALESCE(source_pmid, '') != ''"),
        "evidence_with_source_doi": one("SELECT COUNT(*) FROM evidence_records WHERE COALESCE(source_doi, '') != ''"),
        "pathogenicity_with_reference": one("SELECT COUNT(*) FROM pathogenicity_evidence WHERE reference_id IS NOT NULL"),
        "control_with_reference": one("SELECT COUNT(*) FROM control_management_methods WHERE reference_id IS NOT NULL"),
        "host_range_with_reference": one("SELECT COUNT(*) FROM host_range_evidence WHERE reference_id IS NOT NULL"),
    }
    if table_exists(conn, "literature_evidence_candidates"):
        out["literature_candidates"] = one("SELECT COUNT(*) FROM literature_evidence_candidates")
        out["non_pubmed_candidates"] = one(
            "SELECT COUNT(*) FROM literature_evidence_candidates WHERE source_key != 'genbank_pubmed'"
        )
    return out


def process_candidates(
    conn: sqlite3.Connection,
    candidates: list[Candidate],
    apply: bool,
) -> dict[str, int]:
    stats = {
        "candidates_seen": 0,
        "candidates_inserted": 0,
        "references_inserted_or_linked": 0,
        "evidence_records_inserted": 0,
        "unmatched_virus": 0,
    }
    names = master_map(conn)
    for c in candidates:
        if not c.title.strip():
            continue
        stats["candidates_seen"] += 1
        master = find_master(conn, c.target_virus, names)
        if not master:
            stats["unmatched_virus"] += 1
        ref_id = upsert_reference(conn, c)
        if ref_id:
            stats["references_inserted_or_linked"] += 1
        _, inserted = upsert_candidate(conn, c, ref_id, master)
        if inserted:
            stats["candidates_inserted"] += 1
        if c.claim_hint and c.evidence_scope in {
            "mortality",
            "temperature",
            "virulence",
            "diagnosis",
            "control",
            "host_range",
        }:
            if c.evidence_scope == "control":
                ev_type = "other"
            elif c.evidence_scope == "mortality":
                ev_type = "mortality"
            else:
                ev_type = c.evidence_scope
            if add_evidence_record(conn, c, ref_id, master, ev_type, c.claim_hint, c.claim_hint):
                stats["evidence_records_inserted"] += 1
    if not apply:
        conn.rollback()
    return stats


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="Write changes to the database.")
    parser.add_argument("--online", action="store_true", help="Search Crossref/OpenAlex/Europe PMC in addition to cached files.")
    parser.add_argument("--limit-viruses", type=int, default=15)
    parser.add_argument("--max-per-source", type=int, default=10)
    args = parser.parse_args()

    REPORT_DIR.mkdir(exist_ok=True)
    backup = str(backup_database()) if args.apply else None

    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        before = coverage_snapshot(conn)
        with conn:
            ensure_schema(conn)

            candidates: list[Candidate] = []
            candidates.extend(load_master_review_queue())
            candidates.extend(load_semantic_scholar_cache())
            candidates.extend(load_import_suggestions())
            candidates.extend(load_authority_guides())

            online_errors: list[str] = []
            online_counts: dict[str, int] = {}
            if args.online:
                viruses = target_viruses(conn, args.limit_viruses)
                for virus in viruses:
                    for source_name, fn in [
                        ("crossref", search_crossref),
                        ("openalex", search_openalex),
                        ("europe_pmc", search_europe_pmc),
                    ]:
                        try:
                            found = fn(virus, args.max_per_source)
                            candidates.extend(found)
                            online_counts[source_name] = online_counts.get(source_name, 0) + len(found)
                        except Exception as exc:
                            online_errors.append(f"{source_name}:{virus}: {exc}")
                        time.sleep(REQUEST_DELAY)

            candidate_csv = REPORT_DIR / f"literature_evidence_candidates_{now_stamp()}.csv"
            write_candidate_csv(candidates, candidate_csv)

            stats = process_candidates(conn, candidates, args.apply)
            after = coverage_snapshot(conn)

            details = {
                "apply": args.apply,
                "backup": backup,
                "online": args.online,
                "online_counts": online_counts,
                "online_errors": online_errors[:50],
                "candidate_csv": str(candidate_csv),
                "before": before,
                "after": after,
                "stats": stats,
            }
            conn.execute(
                "INSERT INTO literature_evidence_import_log(action, details_json) VALUES (?, ?)",
                ("strengthen_literature_evidence", json.dumps(details, ensure_ascii=False, sort_keys=True)),
            )
            if args.apply:
                conn.commit()

    report_path = REPORT_DIR / f"literature_evidence_strengthening_{now_stamp()}.json"
    report_path.write_text(json.dumps(details, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(details, ensure_ascii=False, indent=2))
    print(f"Report: {report_path}")


if __name__ == "__main__":
    main()
