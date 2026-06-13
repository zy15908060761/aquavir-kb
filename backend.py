from contextlib import contextmanager

"""FastAPI backend for AquaVir-KB: the aquatic invertebrate virus knowledge base."""
import json
import logging
import os
import re
import shutil
import sqlite3
import subprocess
import tempfile
import threading
import time
import uuid
from pathlib import Path
from typing import List, Optional

import requests
from fastapi import Body, Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from api_models import (
    ExpansionStats,
    HostDetailResponse,
    HostPhylumStats,
    InfectionRecordResponse,
    PaginatedProteinResponse,
    PaginatedRDRPResponse,
    ProteinResponse,
    RDRPResponse,
    StatsResponse,
    StructureResponse,
    VirusDetailResponse,
)
from db_utils import get_db_connection, get_db as _db_get_db
from db_pg import get_query_connection, check_db_connection, get_raw_db_connection, _IS_PG
from sync_runtime import HISTORY_FILE, NOTIFICATION_LOG_FILE, load_status

APP_DIR = Path(__file__).resolve().parent
DB_PATH = APP_DIR / "crustacean_virus_core.db"
SEQUENCES_DIR = APP_DIR / "sequences"
DOWNLOADS_DIR = APP_DIR / "downloads"
PUBLIC_DOWNLOADS_DIR = APP_DIR / "public_downloads"
NCBI_METADATA_DIR = APP_DIR / "ncbi_metadata"
TEMPLATES_DIR = APP_DIR / "templates"
PUBLIC_ASSETS_DIR = APP_DIR / "public_assets"
PUBLIC_ASSETS_DIR.mkdir(exist_ok=True)
PUBLIC_DOWNLOADS_DIR.mkdir(exist_ok=True)
STRICT_TARGET_SUBQUERY = "SELECT isolate_id FROM analysis_strict_target_isolates"
STRICT_TARGET_CONDITION = f"v.isolate_id IN ({STRICT_TARGET_SUBQUERY})"

# Inclusive target: covers ALL aquatic invertebrate phyla (not just crustaceans).
# Used by public search/export endpoints so mollusk, cnidarian, echinoderm and
# other non-crustacean viruses are visible.
_INCLUSIVE_TARGET_NON_TYPES = (
    "'non_target'", "'ictv_non_target'", "'host_genome'",
    "'duplicate_ictv_vmr_placeholder'", "'duplicate_alias_placeholder'",
)
INCLUSIVE_TARGET_SUBQUERY = (
    "SELECT vi.isolate_id FROM viral_isolates vi "
    "JOIN virus_master vm ON vi.master_id = vm.master_id "
    f"WHERE vm.entry_type NOT IN ({', '.join(_INCLUSIVE_TARGET_NON_TYPES)}) "
    "AND vm.host_phylum IS NOT NULL "
    "AND vi.isolate_id IN ("
    "  SELECT isolate_id FROM isolate_curated_profiles"
    "  WHERE COALESCE(curation_status, 'auto_seeded') <> 'conflict_open'"
    ")"
)
INCLUSIVE_TARGET_CONDITION = f"v.isolate_id IN ({INCLUSIVE_TARGET_SUBQUERY})"

def _escape_like(text: str) -> str:
    """Escape SQL LIKE wildcards to prevent unintended pattern matching.
    NOTE: Requires ESCAPE '\\' in the SQL query for the escaping to take effect."""
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")

VIRULENCE_EVIDENCE_TYPES = ("virulence", "pathogenicity", "mortality")
TEMPERATURE_EVIDENCE_TYPES = ("temperature", "thermal_stability", "thermal_inactivation", "temperature_range")

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
BLAST_DIR = Path(os.environ.get("AQUAVIR_BLAST_DIR", str(Path(__file__).resolve().parent / "blastdb")))
RDRP_BLAST_FASTA = BLAST_DIR / "rdrp_proteins.faa"
RDRP_BLAST_DB = BLAST_DIR / "rdrp_proteins"
LOGGER = logging.getLogger("aquavir.backend")

ACCESSION_RE = re.compile(r"^[A-Za-z0-9_.-]{1,80}$")
SQL_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
DEFAULT_CORS_ORIGINS = [
    "http://127.0.0.1:8000",
    "http://localhost:8000",
    "http://127.0.0.1:3000",
    "http://localhost:3000",
]
PUBLIC_DOWNLOAD_EXTENSIONS = {
    ".csv",
    ".tsv",
    ".xlsx",
    ".xls",
    ".fasta",
    ".faa",
    ".fna",
    ".fa",
    ".zip",
    ".json",
    ".md",
    ".txt",
    ".svg",
    ".png",
    ".jpg",
    ".jpeg",
    ".pdf",
    ".contree",
    ".tree",
    ".nwk",
    ".newick",
}
PUBLIC_DOWNLOAD_ALLOWLIST = {
    "all_sequences.fasta",
    "complete_genomes.fasta",
    "crustacean_virus_metadata_standardized.xlsx",
    "host_virus_network.csv",
    "reviewed_evidence_records.xlsx",
    "SHA256SUMS.csv",
    "README.md",
    "LICENSE.txt",
    "CITATION.cff",
    "DATA_USE_AGREEMENT.md",
}
PHYLOGENY_DOWNLOAD_RE = re.compile(
    r"^phylogeny/(?:figures/)?[A-Za-z0-9_.-]+(?:_tree)?\.(?:png|svg|contree|tree|nwk|newick)$"
)


def _configured_cors_origins() -> list[str]:
    raw = os.environ.get("AQUAVIR_CORS_ORIGINS", "")
    origins = [item.strip() for item in raw.split(",") if item.strip()] if raw else DEFAULT_CORS_ORIGINS
    if "*" in origins and os.environ.get("AQUAVIR_ENV", "").lower() in {"prod", "production"}:
        raise RuntimeError("AQUAVIR_CORS_ORIGINS must not contain '*' when AQUAVIR_ENV=production")
    return origins


def _safe_sql_identifier(name: str, allowed: set[str]) -> str:
    if name not in allowed or not SQL_IDENTIFIER_RE.fullmatch(name):
        raise ValueError(f"Unsafe SQL identifier: {name}")
    return name


def _safe_child_path(base_dir: Path, relative_path: str, allowed_extensions: set[str]) -> Path:
    raw_path = Path(relative_path)
    if raw_path.is_absolute() or any(part in {"", ".", ".."} for part in raw_path.parts):
        raise HTTPException(status_code=400, detail="Invalid path")
    if raw_path.suffix.lower() not in allowed_extensions:
        raise HTTPException(status_code=403, detail="File type is not available for public download")
    base = base_dir.resolve()
    candidate = (base / raw_path).resolve()
    if candidate != base and base not in candidate.parents:
        raise HTTPException(status_code=400, detail="Invalid path")
    return candidate


def _safe_public_download_path(relative_path: str) -> Path:
    normalized = Path(relative_path).as_posix()
    if normalized not in PUBLIC_DOWNLOAD_ALLOWLIST and not PHYLOGENY_DOWNLOAD_RE.fullmatch(normalized):
        raise HTTPException(status_code=403, detail="File is not in the public download allowlist")
    return _safe_child_path(PUBLIC_DOWNLOADS_DIR, normalized, PUBLIC_DOWNLOAD_EXTENSIONS)


def _safe_accession_fasta(accession: str) -> Path:
    if not ACCESSION_RE.fullmatch(accession or ""):
        raise HTTPException(status_code=400, detail="Invalid accession")
    return _safe_child_path(SEQUENCES_DIR, f"{accession}.fasta", {".fasta"})

app = FastAPI(
    title="AquaVir-KB API",
    description=(
        "A comprehensive knowledge base of aquatic invertebrate viruses across 5 phyla "
        "(Arthropoda, Mollusca, Cnidaria, Echinodermata, Porifera), integrating release-filtered isolate records, "
        "genomic annotations, protein structures (AlphaFold / ESMFold / PDB), enrichment data "
        "(KEGG, InterPro, UniProt, STRING, PRIDE, ViralZone), literature mining (Europe PMC, "
        "bioRxiv), and ecological observations (GBIF, OBIS). Exploratory prediction tables, "
        "when present, are not manual-reviewed evidence and are not exposed as validated claims.\n\n"
        "This API powers the AquaVir-KB web frontend and is also available for scripting, "
        "notebooks, and third-party integrations."
    ),
    version="2.0.0",
    contact={
        "name": "AquaVir-KB Team",
        "url": "https://aquavir-kb.org",
    },
    license_info={
        "name": "Creative Commons Attribution 4.0 International (CC BY 4.0)",
        "url": "https://creativecommons.org/licenses/by/4.0/",
    },
    openapi_tags=[
        {
            "name": "Core Data",
            "description": "Virus isolates, hosts, families, search and detail retrieval",
        },
        {
            "name": "Proteins",
            "description": "Viral protein annotations, core/conserved genes, and 3D structures",
        },
        {
            "name": "RDRP",
            "description": "RNA-dependent RNA polymerase annotations, BLAST search, and species overview",
        },
        {
            "name": "Enrichment",
            "description": "External data source integrations: KEGG, InterPro, UniProt, ViralZone, STRING, PRIDE, GEO/SRA, GBIF, Europe PMC, bioRxiv, host ecology, and AlphaFold structures",
        },
        {
            "name": "Stats",
            "description": "Aggregated database statistics: overall counts, protein stats, genome stats, completeness, and structure coverage",
        },
        {
            "name": "Downloads",
            "description": "File download endpoints for FASTA sequences, exports, and PDB files",
        },
        {
            "name": "Sync",
            "description": "Data synchronization status and history for automated ingestion pipelines",
        },
        {
            "name": "Pages",
            "description": "Server-side rendered HTML pages (Jinja2 templates)",
        },
    ],
)

# --- API Key protection for POST endpoints ---
import secrets

_API_KEY = os.environ.get("AQUAVIR_API_KEY", secrets.token_urlsafe(32))
if "AQUAVIR_API_KEY" not in os.environ:
    print(f"[WARNING] AQUAVIR_API_KEY not set. Using random key: {_API_KEY[:8]}...")
    print(f"  Set via: export AQUAVIR_API_KEY=your-secret-key")


def require_api_key(x_api_key: str = Header(None, alias="X-API-Key")):
    """Dependency that validates X-API-Key header for POST endpoints.

    The header is declared as optional (default None) so FastAPI does not
    reject missing headers with a 422 Validation Error.  We perform the
    check manually to return a proper 401 Unauthorized."""
    if not x_api_key or not secrets.compare_digest(x_api_key, _API_KEY):
        raise HTTPException(status_code=401, detail="Invalid or missing API key. Provide X-API-Key header.")
    return x_api_key


# Diagnostic category display labels.
DIAGNOSTIC_CATEGORY_CN = {
    "nucleic_acid_amplification": "Nucleic acid amplification",
    "immunoassay": "Immunoassay",
    "nucleic_acid_hybridization": "Nucleic acid hybridization",
    "sequencing": "Sequencing",
    "crispr_cas": "CRISPR-Cas",
    "other": "Other",
    "pcr": "PCR",
    "rt-pcr": "RT-PCR",
    "qpcr": "qPCR",
    "nested-rt-pcr": "nested RT-PCR",
    "multiplex-rt-pcr": "multiplex RT-PCR",
    "lamp": "LAMP",
    "rt-lamp": "RT-LAMP",
    "rpa": "RPA",
    "lateral-flow-strip": "lateral-flow strip",
    "elisa": "ELISA",
    "in-situ-hybridization": "in situ hybridization",
    "ish": "ISH",
    "crispr-cas": "CRISPR-Cas",
    "crispr-cas12a": "CRISPR-Cas12a",
    "crispr-cas13": "CRISPR-Cas13",
    "sanger-sequencing": "Sanger sequencing",
    "ngs": "NGS",
    "metagenomic-sequencing": "metagenomic sequencing",
    "PCR": "PCR",
    "RT-PCR": "RT-PCR",
    "qPCR": "qPCR",
    "LAMP": "LAMP",
    "RPA": "RPA",
    "CRISPR": "CRISPR",
    "ISH": "ISH",
}
# Corrupted legacy comment removed.

# Corrupted legacy comment removed.
app.mount("/static", StaticFiles(directory=str(PUBLIC_ASSETS_DIR)), name="static")

app.add_middleware(
    CORSMiddleware,
    allow_origins=_configured_cors_origins(),
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Accept", "X-API-Key"],
)


# ============================================================
# Corrupted legacy comment removed.
# ============================================================
from starlette.exceptions import HTTPException as StarletteHTTPException


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    if exc.status_code == 404:
        return templates.TemplateResponse(
            request, "error.html",
            {"status_code": 404, "detail": str(exc.detail)},
            status_code=404
        )
    return templates.TemplateResponse(
        request, "error.html",
        {"status_code": exc.status_code, "detail": str(exc.detail)},
        status_code=exc.status_code
    )


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    import traceback, datetime
    log_path = APP_DIR / "error.log"
    try:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.datetime.now()}] {request.url}\n")
            f.write(traceback.format_exc())
            f.write("\n" + "=" * 50 + "\n")
    except Exception:
        pass
    if request.url.path.startswith("/api/"):
        return JSONResponse(
            status_code=500,
            content={"error_code": "internal_server_error", "message": "Internal server error"},
        )
    return templates.TemplateResponse(
        request, "error.html",
        {"status_code": 500, "detail": "Internal server error"},
        status_code=500
    )

@contextmanager
def get_db():
    """Unified DB connection context-manager (SQLite or PostgreSQL, auto-detected).

    Yields a PEP-249 connection whose rows support dict-like access.
    """
    from db_pg import _IS_PG, _pool
    if _IS_PG:
        conn = _pool.getconn()
        try:
            with conn.cursor() as cur:
                cur.execute("SET timezone = 'UTC'")
                cur.execute("SET default_transaction_read_only = on")
            yield conn
        finally:
            try: conn.rollback()
            except Exception: pass
            _pool.putconn(conn)
    else:
        conn = _db_get_db(wal_mode=True, timeout=60)
        try:
            yield conn
        finally:
            conn.close()


def table_exists(conn, table_name: str) -> bool:
    """Return True when a table/view exists in the current database."""
    if _IS_PG:
        return conn.execute(
            "SELECT 1 FROM information_schema.tables WHERE table_name = ?",
            (table_name,),
        ).fetchone() is not None
    # SQLite
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE name = ? AND type IN ('table', 'view')",
        (table_name,),
    ).fetchone() is not None


def count_optional_table(conn: sqlite3.Connection, table_name: str, where: str = "") -> int:
    """Count an optional table; missing feature tables report 0 instead of breaking /api/stats."""
    table_name = _safe_sql_identifier(table_name, {"external_literature_hits", "isolate_media_assets"})
    if where:
        raise ValueError("count_optional_table does not accept ad hoc WHERE clauses")
    if not table_exists(conn, table_name):
        return 0
    return int(conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0] or 0)


def has_fts_search(conn) -> bool:
    """Return True when full-text search index is available."""
    if _IS_PG:
        # PostgreSQL — check for tsvector column or GIN index
        return conn.execute(
            "SELECT 1 FROM information_schema.columns WHERE table_name = 'virus_master' AND column_name = 'search_vector'"
        ).fetchone() is not None
    return (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'virus_search_fts'"
        ).fetchone()
        is not None
    )


def build_fts_match_query(query: str) -> Optional[str]:
    tokens = re.findall(r"[0-9A-Za-z_\u4e00-\u9fff]+", query or "")
    tokens = [token for token in tokens if token]
    if not tokens:
        return None
    if _IS_PG:
        # PostgreSQL tsquery: token:* & token:* ...
        return " & ".join(f"{token[:64]}:*" for token in tokens[:8])
    # SQLite FTS5: "token"* AND "token"* ...
    return " AND ".join(f'"{token[:64]}"*' for token in tokens[:8])


def build_search_where(
    q: Optional[str] = None,
    host: Optional[str] = None,
    family: Optional[str] = None,
    country: Optional[str] = None,
    completeness: Optional[str] = None,
    year_from: Optional[str] = None,
    year_to: Optional[str] = None,
    phylum: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None,
):
    """Build a release-scoped WHERE clause and parameter list for search/export.

    NOTE: Uses INCLUSIVE_TARGET_CONDITION (all aquatic invertebrate phyla)
    instead of STRICT_TARGET_CONDITION (crustacean-only).  If callers need
    the old crustacean-only scope they must add their own condition.
    """
    where_clauses = [INCLUSIVE_TARGET_CONDITION]
    params = []

    if q:
        fts_query = build_fts_match_query(q)
        like_q = f"%{_escape_like(q)}%"
        if conn is not None and fts_query and has_fts_search(conn):
            # Use BOTH FTS and LIKE together with OR for robustness,
            # so abbreviations like "WSSV" match even if FTS doesn't index them.
            if _IS_PG:
                where_clauses.append(
                    "(vm.search_vector @@ to_tsquery('english', ?) OR vm.canonical_name ILIKE ? OR vm.abbreviations ILIKE ?)"
                )
                params.extend([fts_query, like_q, like_q])
            else:
                where_clauses.append(
                    "(v.master_id IN (SELECT rowid FROM virus_search_fts WHERE virus_search_fts MATCH ?) OR v.virus_name LIKE ? ESCAPE '\\' OR vm.canonical_name LIKE ? ESCAPE '\\')"
                )
                params.extend([fts_query, like_q, like_q])
        else:
            where_clauses.append(
                "(v.virus_name LIKE ? ESCAPE '\\' OR v.accession LIKE ? ESCAPE '\\' OR v.taxon_family LIKE ? ESCAPE '\\' OR v.taxon_genus LIKE ? ESCAPE '\\' OR vm.canonical_name LIKE ? ESCAPE '\\' OR vm.abbreviations LIKE ? ESCAPE '\\' OR vm.chinese_name LIKE ? ESCAPE '\\')"
            )
            params.extend([like_q, like_q, like_q, like_q, like_q, like_q, like_q])

    if host:
        like_host = f"%{_escape_like(host)}%"
        where_clauses.append("(h.scientific_name LIKE ? ESCAPE '\\' OR h.common_name_cn LIKE ? ESCAPE '\\')")
        params.extend([like_host, like_host])

    if phylum:
        where_clauses.append("vm.host_phylum = ?")
        params.append(phylum)

    if family:
        where_clauses.append("v.taxon_family = ?")
        params.append(family)

    if country:
        where_clauses.append("s.country = ?")
        params.append(country)

    if completeness:
        where_clauses.append("v.completeness = ?")
        params.append(completeness)

    if year_from:
        where_clauses.append("s.collection_year >= ?")
        params.append(year_from)

    if year_to:
        where_clauses.append("s.collection_year <= ?")
        params.append(year_to)

    return " AND ".join(where_clauses), params


def read_jsonl_tail(path: Path, limit: int):
    if not path.exists():
        return []
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows[-limit:][::-1]


def normalize_protein_sequence(raw_sequence: str) -> str:
    """Accept plain amino-acid text or FASTA and return uppercase AA letters."""
    lines = []
    for line in (raw_sequence or "").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(">"):
            continue
        lines.append(stripped)
    sequence = "".join(lines).upper()
    return "".join(ch for ch in sequence if "A" <= ch <= "Z" or ch == "*")


def protein_kmers(sequence: str, k: int) -> set[str]:
    if len(sequence) < k:
        return {sequence} if sequence else set()
    return {sequence[i:i + k] for i in range(0, len(sequence) - k + 1)}


def find_blast_binary(binary_name: str) -> Optional[str]:
    """Find NCBI BLAST+ binaries from PATH or common local tool folders."""
    found = shutil.which(binary_name)
    if found:
        return found

    candidates = []
    for tools_dir in [APP_DIR / "tools", APP_DIR / "blast", APP_DIR / "ncbi-blast"]:
        if not tools_dir.exists():
            continue
        candidates.extend(tools_dir.glob(f"**/{binary_name}.exe"))
        candidates.extend(tools_dir.glob(f"**/{binary_name}"))

    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return None


def rdrp_blast_db_exists() -> bool:
    return (
        RDRP_BLAST_FASTA.exists()
        and (Path(str(RDRP_BLAST_DB) + ".pin").exists() or Path(str(RDRP_BLAST_DB) + ".psq").exists())
    )


def write_rdrp_blast_fasta() -> int:
    """Export database RDRP proteins to a BLAST-ready FASTA file."""
    BLAST_DIR.mkdir(parents=True, exist_ok=True)
    with get_db() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT
                vp.protein_id, vp.protein_accession, vp.protein_name,
                vp.gene_symbol, vp.aa_length, vp.translation,
                vi.accession,
                vm.canonical_name AS virus_species,
                vm.virus_family,
                vm.genome_type
            FROM viral_proteins vp
            JOIN viral_isolates vi ON vp.isolate_id = vi.isolate_id
            JOIN virus_master vm ON vi.master_id = vm.master_id
            WHERE vp.is_rdrp = 1
              AND vp.translation IS NOT NULL
              AND LENGTH(vp.translation) > 0
            ORDER BY vp.protein_id
        """)
        rows = c.fetchall()

    with RDRP_BLAST_FASTA.open("w", encoding="utf-8", newline="\n") as f:
        for row in rows:
            seq = normalize_protein_sequence(row["translation"]).replace("*", "")
            if not seq:
                continue
            header_parts = [
                f"rdrp_{row['protein_id']}",
                f"protein_accession={row['protein_accession'] or '-'}",
                f"isolate={row['accession'] or '-'}",
                f"virus={row['virus_species'] or '-'}",
                f"protein={row['protein_name'] or '-'}",
            ]
            f.write(">" + " ".join(header_parts) + "\n")
            for i in range(0, len(seq), 60):
                f.write(seq[i:i + 60] + "\n")
    return len(rows)


def get_rdrp_hit_metadata(protein_ids: list[int]) -> dict[int, dict]:
    if not protein_ids:
        return {}
    placeholders = ",".join("?" for _ in protein_ids)
    with get_db() as conn:
        c = conn.cursor()
        c.execute(f"""
            SELECT
                vp.protein_id, vp.protein_accession, vp.protein_name,
                vp.gene_symbol, vp.aa_length,
                vi.accession,
                vm.canonical_name AS virus_species,
                vm.virus_family,
                vm.genome_type
            FROM viral_proteins vp
            JOIN viral_isolates vi ON vp.isolate_id = vi.isolate_id
            JOIN virus_master vm ON vi.master_id = vm.master_id
            WHERE vp.protein_id IN ({placeholders})
        """, protein_ids)
        rows = {row["protein_id"]: dict(row) for row in c.fetchall()}
    return rows


def run_local_rdrp_blast(
    query_sequence: str,
    program: str,
    limit: int,
    evalue: float,
    build_if_missing: bool = True,
) -> dict:
    program = program.lower()
    if program not in {"blastp", "blastx"}:
        return {"engine": "blast", "results": [], "error": "program must be blastp or blastx"}

    blast_bin = find_blast_binary(program)
    makeblastdb_bin = find_blast_binary("makeblastdb")
    if not blast_bin or not makeblastdb_bin:
        return {
            "engine": program,
            "available": False,
            "results": [],
            "error": "NCBI BLAST+ is not installed or not on PATH. Install BLAST+ and make sure blastp/blastx/makeblastdb are available.",
        }

    if not rdrp_blast_db_exists():
        if not build_if_missing:
            return {"engine": program, "available": True, "results": [], "error": "RDRP BLAST database has not been built."}
        build_result = build_rdrp_blast_database()
        if build_result.get("error"):
            return {"engine": program, "available": True, "results": [], "error": build_result["error"]}

    seq = normalize_protein_sequence(query_sequence).replace("*", "") if program == "blastp" else "".join(
        ch for ch in (query_sequence or "").upper() if ch in "ACGTUN"
    )
    if (program == "blastp" and len(seq) < 3) or (program == "blastx" and len(seq) < 9):
        return {"engine": program, "available": True, "results": [], "error": "Query sequence is too short for BLAST."}

    suffix = ".faa" if program == "blastp" else ".fna"
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=suffix, delete=False) as query_file:
        query_path = Path(query_file.name)
        query_file.write(">query\n")
        for i in range(0, len(seq), 60):
            query_file.write(seq[i:i + 60] + "\n")

    outfmt = "6 qseqid sseqid pident length mismatch gapopen qstart qend sstart send evalue bitscore qlen slen"
    cmd = [
        blast_bin,
        "-query", str(query_path),
        "-db", str(RDRP_BLAST_DB),
        "-outfmt", outfmt,
        "-max_target_seqs", str(limit),
        "-evalue", str(evalue),
    ]
    try:
        completed = subprocess.run(cmd, capture_output=True, text=True, timeout=120, check=False)
    finally:
        try:
            query_path.unlink()
        except OSError:
            pass

    if completed.returncode != 0:
        LOGGER.warning("RDRP BLAST failed with return code %s: %s", completed.returncode, completed.stderr.strip())
        return {
            "engine": program,
            "available": True,
            "results": [],
            "error": "BLAST failed. Check server logs for details.",
        }

    rows = []
    protein_ids = []
    for line in completed.stdout.splitlines():
        fields = line.split("\t")
        if len(fields) != 14:
            continue
        subject_id = fields[1]
        try:
            protein_id = int(subject_id.replace("rdrp_", "", 1))
        except ValueError:
            continue
        protein_ids.append(protein_id)
        rows.append((protein_id, fields))

    metadata = get_rdrp_hit_metadata(list(dict.fromkeys(protein_ids)))
    results = []
    for protein_id, fields in rows:
        meta = metadata.get(protein_id, {})
        qlen = int(float(fields[12])) if fields[12] else 0
        slen = int(float(fields[13])) if fields[13] else 0
        align_len = int(float(fields[3]))
        results.append({
            **meta,
            "program": program,
            "pident": round(float(fields[2]), 3),
            "alignment_length": align_len,
            "mismatches": int(float(fields[4])),
            "gap_opens": int(float(fields[5])),
            "qstart": int(float(fields[6])),
            "qend": int(float(fields[7])),
            "sstart": int(float(fields[8])),
            "send": int(float(fields[9])),
            "evalue": fields[10],
            "bitscore": round(float(fields[11]), 1),
            "query_length": qlen,
            "subject_length": slen,
            "query_coverage": round((align_len / qlen * 100), 2) if qlen else 0,
            "subject_coverage": round((align_len / slen * 100), 2) if slen else 0,
        })

    return {
        "engine": program,
        "available": True,
        "query_length": len(seq),
        "returned": len(results),
        "classification": classify_rdrp_blast_results(results, program),
        "results": results,
    }


def build_rdrp_blast_database() -> dict:
    makeblastdb_bin = find_blast_binary("makeblastdb")
    if not makeblastdb_bin:
        return {"available": False, "error": "makeblastdb was not found. Install NCBI BLAST+ first."}
    count = write_rdrp_blast_fasta()
    cmd = [
        makeblastdb_bin,
        "-in", RDRP_BLAST_FASTA.name,
        "-dbtype", "prot",
        "-out", RDRP_BLAST_DB.name,
        "-parse_seqids",
    ]
    completed = subprocess.run(cmd, cwd=str(BLAST_DIR), capture_output=True, text=True, timeout=120, check=False)
    if completed.returncode != 0:
        LOGGER.warning("makeblastdb failed with return code %s: %s", completed.returncode, completed.stderr.strip())
        return {"available": True, "records": count, "error": "makeblastdb failed. Check server logs for details."}
    return {
        "available": True,
        "records": count,
        "status": "built",
    }


def classify_rdrp_blast_results(results: list[dict], program: str) -> dict:
    """Create a compact interpretation layer over BLAST hits."""
    if not results:
        return {
            "assignment": "no_hit",
            "confidence": "none",
            "summary": "No RDRP hit was found in the local database.",
            "recommended_action": "Try a lower stringency E-value, use BLASTX for nucleotide contigs, or search public NCBI databases.",
            "best_hit": None,
            "species_votes": [],
        }

    best = results[0]
    pident = float(best.get("pident") or 0)
    qcov = float(best.get("query_coverage") or 0)
    bitscore = float(best.get("bitscore") or 0)
    species_counts = {}
    family_counts = {}
    for hit in results[:10]:
        species = hit.get("virus_species") or "Unknown"
        family = hit.get("virus_family") or "Unknown"
        species_counts[species] = species_counts.get(species, 0) + 1
        family_counts[family] = family_counts.get(family, 0) + 1

    if pident >= 95 and qcov >= 70:
        assignment = "species_level_match"
        confidence = "high"
        summary = f"Best hit strongly supports assignment close to {best.get('virus_species') or 'the top hit'}."
        action = "Use the top-hit species as the working annotation, then confirm with full-length genome context and metadata."
    elif pident >= 80 and qcov >= 50:
        assignment = "close_relative"
        confidence = "medium"
        summary = f"Best hit indicates a close relative of {best.get('virus_species') or 'the top hit'}, but coverage/identity is below strong species-level criteria."
        action = "Build an RdRp phylogenetic tree with the top hits and inspect genome completeness before naming."
    elif pident >= 40 and qcov >= 30 and bitscore >= 50:
        assignment = "distant_rdrp_hit"
        confidence = "low"
        summary = "The query has a distant RDRP-like hit, but current evidence is not enough for species-level assignment."
        action = "Run BLAST against NCBI nr, check conserved RdRp motifs, and try to extend the contig/genome."
    else:
        assignment = "weak_hit"
        confidence = "low"
        summary = "Only weak similarity was detected against the local RDRP database."
        action = "Treat this as unclassified until public BLAST, motif search, and phylogeny provide stronger evidence."

    return {
        "assignment": assignment,
        "confidence": confidence,
        "summary": summary,
        "recommended_action": action,
        "best_hit": {
            "virus_species": best.get("virus_species"),
            "virus_family": best.get("virus_family"),
            "accession": best.get("accession"),
            "protein_accession": best.get("protein_accession"),
            "pident": best.get("pident"),
            "query_coverage": best.get("query_coverage"),
            "evalue": best.get("evalue"),
            "bitscore": best.get("bitscore"),
            "program": program,
        },
        "species_votes": [
            {"species": species, "count": count}
            for species, count in sorted(species_counts.items(), key=lambda item: item[1], reverse=True)
        ],
        "family_votes": [
            {"family": family, "count": count}
            for family, count in sorted(family_counts.items(), key=lambda item: item[1], reverse=True)
        ],
    }


# Corrupted legacy comment removed.
_APP_START_TIME = time.time()


@app.get("/api/health", tags=["Stats"])
def health_check():
    """Health-check endpoint reporting database connectivity, table record
    counts, and server uptime.  Intended for monitoring / load-balancer
    probes and quick sanity checks from the frontend."""
    db_info = check_db_connection()
    db_ok = db_info["healthy"]
    tables = {}
    try:
        with get_db() as conn:
            c = conn.cursor()
            for tbl in [
                "analysis_strict_target_isolates",
                "viral_proteins",
                "virus_master",
                "crustacean_hosts",
            ]:
                tbl = _safe_sql_identifier(
                    tbl,
                    {"analysis_strict_target_isolates", "viral_proteins", "virus_master", "crustacean_hosts"},
                )
                c.execute(f"SELECT COUNT(*) FROM {tbl}")
                tables[tbl] = c.fetchone()[0]
    except Exception as exc:
        LOGGER.exception("Health-check database query failed")
        db_ok = False
        tables["error"] = "Database query failed"

    return {
        "status": "healthy" if db_ok else "degraded",
        "backend": db_info["backend"],
        "database": {"connected": db_ok, "tables": tables},
        "uptime_seconds": int(time.time() - _APP_START_TIME),
        "version": "2.0.0",
    }


@app.get("/api/sync/status", tags=["Sync"])
def get_sync_status():
    """Return the latest sync status for automation checks."""
    return load_status()


@app.get("/api/sync/history", tags=["Sync"])
def get_sync_history(limit: int = Query(10, ge=1, le=100)):
    """Return recent sync history entries."""
    return {"items": read_jsonl_tail(HISTORY_FILE, limit)}


@app.get("/api/sync/notifications", tags=["Sync"])
def get_notification_history(limit: int = Query(10, ge=1, le=100)):
    """Return recent notification delivery attempts."""
    return {"items": read_jsonl_tail(NOTIFICATION_LOG_FILE, limit)}


@app.get("/api/stats", tags=["Stats"])
def get_stats():
    """
    Return aggregated database statistics for the homepage dashboard.

    This endpoint returns counts at THREE scopes, all clearly labelled:

    * ``strict_target_*`` -- scoped to ``analysis_strict_target_isolates``
      (release-filtered records; not necessarily manual-reviewed).
    * ``target_*`` -- scoped to ``analysis_target_isolates``
      (broad target set; excludes only serious conflicts).
    * ``total_*`` -- raw table counts (the full database).

    Backward-compatible aliases: ``viral_isolates``, ``aquatic_invertebrate_hosts`` (formerly ``crustacean_hosts``),
    and ``virus_species`` all alias the *strict_target_* values.

    The ``scope_note`` field explains the difference for reviewers.
    """
    with get_db() as conn:
        c = conn.cursor()
        stats = {}

        # ── 1. Raw table counts (full database) ────────────────────
        c.execute("SELECT COUNT(*) FROM viral_isolates")
        stats["total_isolates"] = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM virus_master")
        stats["total_species"] = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM crustacean_hosts")
        stats["total_hosts"] = c.fetchone()[0]

        # 2. analysis_target_isolates view (broad target set)
        c.execute("SELECT COUNT(*) FROM analysis_target_isolates")
        stats["target_isolates"] = c.fetchone()[0]
        stats["target_species"] = 0
        stats["target_hosts"] = 0
        if stats["target_isolates"]:
            c.execute("""
                SELECT COUNT(DISTINCT vm.canonical_name)
                FROM analysis_target_isolates v
                JOIN virus_master vm ON v.master_id = vm.master_id
                WHERE vm.host_phylum IN ('Arthropoda','Mollusca','Cnidaria','Echinodermata','Porifera','Annelida','Nematoda','Platyhelminthes','Rotifera')
            """)
            stats["target_species"] = c.fetchone()[0]
            c.execute("""
                SELECT COUNT(DISTINCT ir.host_id)
                FROM infection_records ir
                WHERE ir.isolate_id IN (SELECT isolate_id FROM analysis_target_isolates)
                  AND ir.host_id IS NOT NULL
            """)
            stats["target_hosts"] = c.fetchone()[0]

        # ── 3. analysis_strict_target_isolates (strict publication) ─
        c.execute("SELECT COUNT(*) FROM analysis_strict_target_isolates")
        strict_iso = c.fetchone()[0]
        c.execute("""
            SELECT COUNT(DISTINCT vm.canonical_name)
            FROM analysis_strict_target_isolates v
            JOIN virus_master vm ON v.master_id = vm.master_id
            WHERE vm.host_phylum IN ('Arthropoda','Mollusca','Cnidaria','Echinodermata','Porifera','Annelida','Nematoda','Platyhelminthes','Rotifera')
        """)
        strict_spp = c.fetchone()[0]
        c.execute("""
            SELECT COUNT(DISTINCT ir.host_id)
            FROM infection_records ir
            WHERE ir.isolate_id IN (SELECT isolate_id FROM analysis_strict_target_isolates)
              AND ir.host_id IS NOT NULL
        """)
        strict_hosts = c.fetchone()[0]
        stats["strict_target_isolates"] = strict_iso
        stats["strict_target_species"] = strict_spp
        stats["strict_target_hosts"] = strict_hosts
        # Main display numbers (use total counts for full database)
        # Main display numbers: use TOTAL database counts
        stats["viral_isolates"] = c.execute("SELECT COUNT(*) FROM viral_isolates").fetchone()[0]
        stats["virus_species"] = c.execute("SELECT COUNT(*) FROM virus_master WHERE canonical_name IS NOT NULL AND canonical_name != ''").fetchone()[0]
        stats["aquatic_invertebrate_hosts"] = c.execute("SELECT COUNT(*) FROM crustacean_hosts").fetchone()[0]

        # ── Scope note ─────────────────────────────────────────────
        stats["scope_note"] = (
            "'target_*' counts use analysis_target_isolates (publication set, "
            "excludes conflict_open); 'strict_target_*' uses "
            "analysis_strict_target_isolates (also excludes unpublished "
            "candidates); 'total_*' counts use the raw database tables "
            "(full database)."
        )

        # ── 4. Remaining counts (strict-target or table, unchanged) ─
        base_counts = {
            "ref_literatures": """
                SELECT COUNT(DISTINCT reference_id)
                FROM analysis_strict_target_isolates
                WHERE reference_id IS NOT NULL
            """,
            "sample_collections": """
                SELECT COUNT(DISTINCT ir.collection_id)
                FROM infection_records ir
                WHERE ir.isolate_id IN (SELECT isolate_id FROM analysis_strict_target_isolates)
                  AND ir.collection_id IS NOT NULL
            """,
            "virulence_profiles": """
                SELECT COUNT(*) FROM analysis_reviewed_evidence_records
                WHERE evidence_type IN ('virulence','pathogenicity','mortality')
            """,
            "temperature_profiles": """
                SELECT COUNT(*) FROM analysis_reviewed_evidence_records
                WHERE evidence_type IN ('temperature','thermal_stability','thermal_inactivation','temperature_range')
            """,
        }
        for table, sql in base_counts.items():
            c.execute(sql)
            stats[table] = c.fetchone()[0]
        # Corrupted legacy comment removed.
        stats["viral_proteins"] = c.execute("SELECT COUNT(*) FROM viral_proteins").fetchone()[0]
        c.execute("SELECT COUNT(*) FROM core_genes")
        stats["core_genes"] = c.fetchone()[0]
        c.execute(f"SELECT COUNT(DISTINCT isolate_id) FROM viral_proteins WHERE isolate_id IN ({STRICT_TARGET_SUBQUERY})")
        stats["isolates_with_proteins"] = c.fetchone()[0]
        # Corrupted legacy comment removed.
        c.execute("""
            SELECT COUNT(DISTINCT protein_id) FROM (
                SELECT protein_id FROM uniprot_structures WHERE protein_id IS NOT NULL
                UNION
                SELECT protein_id FROM protein_structures WHERE protein_id IS NOT NULL
            )
        """)
        stats["proteins_with_structure"] = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM uniprot_structures WHERE source='alphafold'")
        stats["alphafold_structures"] = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM protein_structures WHERE prediction_method='esmfold'")
        stats["esmfold_structures"] = c.fetchone()[0]
        # Corrupted legacy comment removed.
        c.execute("""
            SELECT COUNT(*)
            FROM viral_proteins vp
            JOIN analysis_strict_target_isolates ati ON ati.isolate_id = vp.isolate_id
            WHERE vp.is_rdrp = 1
              AND COALESCE(vp.functional_annotation_status, '') <> 'rule_suggested_unreviewed'
        """)
        stats["rdrp_count"] = c.fetchone()[0]
        c.execute("""
            SELECT COUNT(DISTINCT vm.canonical_name)
            FROM viral_proteins vp
            JOIN analysis_strict_target_isolates vi ON vp.isolate_id = vi.isolate_id
            JOIN virus_master vm ON vi.master_id = vm.master_id
            WHERE vp.is_rdrp = 1
              AND COALESCE(vp.functional_annotation_status, '') <> 'rule_suggested_unreviewed'
        """)
        stats["rdrp_species"] = c.fetchone()[0]

        # ── Expansion fields (v2.0) ─────────────────────────────────────
        try:
            c.execute("""
                SELECT COALESCE(phylum, 'Unknown') AS phylum, COUNT(*) AS cnt
                FROM crustacean_hosts
                GROUP BY COALESCE(phylum, 'Unknown')
                ORDER BY cnt DESC
            """)
            stats["hosts_by_phylum"] = {r["phylum"]: r["cnt"] for r in c.fetchall()}
        except sqlite3.Error:
            stats["hosts_by_phylum"] = {}

        # Virus distribution by host_phylum (v2.1 — reflects expansion)
        try:
            c.execute("""
                SELECT COALESCE(host_phylum, 'Unknown') AS phylum, COUNT(*) AS cnt
                FROM virus_master
                WHERE host_phylum NOT IN ('non_target', 'non_target (vertebrate)',
                    'non_target (fungus)', 'non_target (plant)', 'non_target (algae)',
                    'non_target (bacteria)', 'non_aquatic', 'unknown')
                GROUP BY host_phylum
                ORDER BY cnt DESC
            """)
            stats["viruses_by_phylum"] = {r["phylum"]: r["cnt"] for r in c.fetchall()}
        except sqlite3.Error:
            stats["viruses_by_phylum"] = {}

        # SRA runs count
        try:
            c.execute("SELECT COUNT(*) FROM sra_runs")
            stats["sra_runs"] = c.fetchone()[0]
        except sqlite3.Error:
            stats["sra_runs"] = 0

        try:
            c.execute("""
                SELECT COUNT(DISTINCT COALESCE(phylum, 'Unknown'))
                FROM crustacean_hosts
            """)
            stats["phyla_covered"] = c.fetchone()[0]
        except sqlite3.Error:
            stats["phyla_covered"] = 0

        try:
            c.execute("""
                SELECT ROUND(
                    CAST(SUM(CASE WHEN host_association_method IS NOT NULL
                                  AND host_association_method != '' THEN 1 ELSE 0 END) AS REAL)
                    / CAST(NULLIF(COUNT(*), 0) AS REAL) * 100, 1
                )
                FROM infection_records
            """)
            row = c.fetchone()
            stats["evidence_coverage_pct"] = row[0] if row and row[0] is not None else 0.0
        except sqlite3.Error:
            stats["evidence_coverage_pct"] = 0.0
        # Experimentally validated profiles
        try:
            c.execute("SELECT COUNT(*) FROM virulence_profiles WHERE data_source LIKE '%Expert curation%'")
            stats["experimentally_validated"] = c.fetchone()[0]
        except sqlite3.Error:
            stats["experimentally_validated"] = 0
        # Data update date
        try:
            c.execute("SELECT MAX(updated_at) FROM sync_runtime")
            row = c.fetchone()
            stats["data_update_date"] = row[0] if row and row[0] else ""
        except sqlite3.Error:
            stats["data_update_date"] = ""
        # Corrupted legacy comment removed.
        c.execute("""
            SELECT COUNT(DISTINCT COALESCE(virus_master_id, isolate_id, evidence_id))
            FROM analysis_reviewed_evidence_records
            WHERE evidence_type IN ('virulence','pathogenicity','mortality')
        """)
        stats["virulence_covered"] = c.fetchone()[0]
        c.execute("""
            SELECT COUNT(DISTINCT COALESCE(virus_master_id, isolate_id, evidence_id))
            FROM analysis_reviewed_evidence_records
            WHERE evidence_type IN ('temperature','thermal_stability','thermal_inactivation','temperature_range')
        """)
        stats["temperature_covered"] = c.fetchone()[0]
        # Genome stats
        c.execute(f"SELECT COUNT(*) FROM analysis_strict_target_isolates WHERE gc_content IS NOT NULL")
        stats["genomes_with_gc"] = c.fetchone()[0]
        c.execute("SELECT ROUND(AVG(gc_content), 1) FROM analysis_strict_target_isolates WHERE gc_content IS NOT NULL")
        stats["avg_gc_content"] = c.fetchone()[0]
        c.execute("SELECT ROUND(AVG(genome_length), 0) FROM analysis_strict_target_isolates WHERE genome_length IS NOT NULL")
        stats["avg_genome_length"] = c.fetchone()[0]
        # Entry type distribution
        c.execute("""
            SELECT vm.entry_type, COUNT(*) 
            FROM analysis_strict_target_isolates v
            JOIN virus_master vm ON v.master_id = vm.master_id
            GROUP BY vm.entry_type
        """)
        stats["entry_types"] = {r[0]: r[1] for r in c.fetchall()}
        # Data quality metrics
        c.execute("SELECT COUNT(DISTINCT master_id) FROM analysis_strict_target_isolates")
        total_species = c.fetchone()[0]
        c.execute("""
            SELECT COUNT(DISTINCT vim.master_id)
            FROM virus_ictv_mappings vim
            JOIN analysis_strict_target_isolates ati ON ati.master_id = vim.master_id
            WHERE vim.confidence = 'high'
              AND vim.match_status <> 'rejected'
        """)
        mapped_species = c.fetchone()[0]
        stats["ictv_mapping_rate"] = round(mapped_species / total_species * 100, 1) if total_species else 0
        c.execute("SELECT COUNT(*) FROM infection_records ir JOIN sample_collections sc ON ir.collection_id = sc.collection_id WHERE sc.country IS NOT NULL AND sc.country != ''")
        stats["geo_covered_isolates"] = c.fetchone()[0]
        c.execute(f"SELECT COUNT(DISTINCT isolate_id) FROM infection_records WHERE host_id IS NOT NULL AND isolate_id IN ({STRICT_TARGET_SUBQUERY})")
        stats["host_covered_isolates"] = c.fetchone()[0]
        # Current release-quality completeness metrics use the curated analysis
        # views. Keep legacy fields above for older widgets, and expose target
        # denominators for pages that show data quality rates.
        try:
            c.execute("SELECT COUNT(*) FROM analysis_strict_target_isolates")
            stats["analysis_target_isolates_total"] = c.fetchone()[0]
            target_checks = {
                "target_host_covered": "has_host",
                "target_country_covered": "has_country",
                "target_reference_covered": "has_reference",
                "target_genome_type_covered": "has_genome_type",
                "target_collection_year_covered": "has_collection_year",
                "target_isolation_source_covered": "has_isolation_source",
            }
            for key, field in target_checks.items():
                c.execute(
                    f"""
                    SELECT COALESCE(SUM({field}), 0)
                    FROM analysis_isolate_completeness
                    WHERE isolate_id IN (SELECT isolate_id FROM analysis_strict_target_isolates)
                    """
                )
                stats[key] = c.fetchone()[0] or 0
        except sqlite3.Error:
            stats["analysis_target_isolates_total"] = 0
        # Dataset tier stats
        c.execute("SELECT COUNT(*) FROM isolate_curated_profiles WHERE dataset_tier = 'core'")
        stats["core_dataset_count"] = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM isolate_curated_profiles WHERE dataset_tier = 'extended_hq'")
        stats["extended_hq_count"] = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM isolate_curated_profiles WHERE dataset_tier = 'extended'")
        stats["extended_count"] = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM isolate_curated_profiles WHERE dataset_tier = 'unverified'")
        stats["unverified_count"] = c.fetchone()[0]
        # Feature module status
        stats["feature_ext_lit"] = count_optional_table(conn, "external_literature_hits")
        stats["feature_media"] = count_optional_table(conn, "isolate_media_assets")
        # Diagnostic methods stats
        # Corrupted legacy comment removed.
        c.execute("SELECT method_category FROM diagnostic_methods LIMIT 1")
        _test_cat = c.fetchone()[0]
        _is_rebuilt = _test_cat in ('nucleic_acid_amplification', 'immunoassay', 'nucleic_acid_hybridization', 'sequencing', 'crispr_cas', 'other')
        _primary_field = _safe_sql_identifier(
            'method_category' if _is_rebuilt else 'method_subcategory',
            {"method_category", "method_subcategory"},
        )
        c.execute(f"SELECT {_primary_field}, COUNT(*) FROM diagnostic_methods WHERE data_quality = 'curated' GROUP BY {_primary_field} ORDER BY COUNT(*) DESC")
        stats["diagnostic_categories"] = {r[0]: r[1] for r in c.fetchall()}
        c.execute("SELECT COUNT(*) FROM diagnostic_methods WHERE data_quality = 'curated'")
        stats["diagnostic_curated_count"] = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM diagnostic_methods WHERE data_quality = 'placeholder'")
        stats["diagnostic_placeholder_count"] = c.fetchone()[0]
        # Control methods stats
        c.execute("SELECT COUNT(*) FROM control_management_methods WHERE curation_status = 'manual_checked'")
        stats["control_methods_count"] = c.fetchone()[0]
        c.execute("""
            SELECT vaccine_type, COUNT(*)
            FROM control_management_methods
            WHERE vaccine_type IS NOT NULL
              AND curation_status = 'manual_checked'
            GROUP BY vaccine_type
        """)
        stats["vaccine_types"] = {r[0]: r[1] for r in c.fetchall()}
    return stats


@app.get("/api/quality/metadata", tags=["Stats"])
def get_metadata_quality():
    """Summarize metadata completeness and curation backlog."""
    with get_db() as conn:
        c = conn.cursor()
    
        total_isolates = c.execute("SELECT COUNT(*) FROM viral_isolates").fetchone()[0]
        curated_total = c.execute("SELECT COUNT(*) FROM isolate_curated_profiles").fetchone()[0]
        denominator = curated_total or total_isolates or 1
    
        fields = [
            ("virus_name", "Virus name", "canonical_virus_name IS NOT NULL AND TRIM(canonical_virus_name) <> ''"),
            ("host", "Host", "host_id IS NOT NULL"),
            ("country", "Country", "country IS NOT NULL AND TRIM(country) <> ''"),
            ("province_state", "Province/state", "province_state IS NOT NULL AND TRIM(province_state) <> ''"),
            ("city", "City", "city IS NOT NULL AND TRIM(city) <> ''"),
            ("specific_site", "Specific site", "specific_site IS NOT NULL AND TRIM(specific_site) <> ''"),
            ("coordinates", "Coordinates", "latitude IS NOT NULL AND longitude IS NOT NULL"),
            ("collection_year", "Collection year", "collection_year IS NOT NULL"),
            ("primary_reference", "Primary reference", "primary_reference_id IS NOT NULL"),
            ("genome_reference", "Genome reference", "genome_reference_id IS NOT NULL"),
            ("discovery_reference", "Discovery reference", "discovery_reference_id IS NOT NULL"),
            ("gc_content", "GC content", "gc_content IS NOT NULL"),
            ("sequence_length", "Sequence length", "sequence_length IS NOT NULL OR genome_length IS NOT NULL"),
        ]
        coverage = []
        for key, label, condition in fields:
            count = c.execute(f"SELECT COUNT(*) FROM isolate_curated_profiles WHERE {condition}").fetchone()[0]
            coverage.append({
                "key": key,
                "label": label,
                "count": count,
                "missing": max(denominator - count, 0),
                "percent": round(count / denominator * 100, 1),
            })
    
        overall_score = round(sum(item["percent"] for item in coverage) / len(coverage), 1) if coverage else 0
    
        c.execute("""
            SELECT COALESCE(curation_status, 'blank') AS status, COUNT(*) AS count
            FROM isolate_curated_profiles
            GROUP BY COALESCE(curation_status, 'blank')
            ORDER BY count DESC
        """)
        status_counts = [dict(row) for row in c.fetchall()]
    
        c.execute("""
            SELECT COALESCE(missing_components, 'blank') AS missing_components, COUNT(*) AS count
            FROM geography_quality_profiles
            GROUP BY COALESCE(missing_components, 'blank')
            ORDER BY count DESC
            LIMIT 10
        """)
        missing_components = [dict(row) for row in c.fetchall()]
    
        c.execute("""
            SELECT
                queue_id, accession, canonical_virus_name, field_name,
                conflict_type, severity, priority_score, recommended_action
            FROM curation_priority_queue
            WHERE COALESCE(queue_status, 'open') <> 'closed'
            ORDER BY priority_score DESC, severity DESC
            LIMIT 20
        """)
        priority_items = [dict(row) for row in c.fetchall()]
    
        c.execute("""
            SELECT
                icp.accession, icp.canonical_virus_name, icp.host_scientific_name,
                icp.country, icp.province_state, icp.city, icp.collection_year,
                icp.primary_reference_id, icp.genome_reference_id, icp.discovery_reference_id,
                (
                    CASE WHEN icp.host_id IS NULL THEN 1 ELSE 0 END +
                    CASE WHEN icp.country IS NULL OR TRIM(icp.country) = '' THEN 1 ELSE 0 END +
                    CASE WHEN icp.province_state IS NULL OR TRIM(icp.province_state) = '' THEN 1 ELSE 0 END +
                    CASE WHEN icp.city IS NULL OR TRIM(icp.city) = '' THEN 1 ELSE 0 END +
                    CASE WHEN icp.collection_year IS NULL THEN 1 ELSE 0 END +
                    CASE WHEN icp.primary_reference_id IS NULL THEN 1 ELSE 0 END +
                    CASE WHEN icp.genome_reference_id IS NULL THEN 1 ELSE 0 END +
                    CASE WHEN icp.discovery_reference_id IS NULL THEN 1 ELSE 0 END
                ) AS missing_score
            FROM isolate_curated_profiles icp
            ORDER BY missing_score DESC, icp.accession
            LIMIT 20
        """)
        incomplete_records = [dict(row) for row in c.fetchall()]
    
    return {
        "total_isolates": total_isolates,
        "curated_profiles": curated_total,
        "overall_score": overall_score,
        "coverage": coverage,
        "status_counts": status_counts,
        "missing_components": missing_components,
        "priority_items": priority_items,
        "incomplete_records": incomplete_records,
    }


@app.get("/api/hosts", tags=["Core Data"])
def get_hosts():
    """Return host autocomplete records."""
    with get_db() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT host_id, scientific_name, common_name_cn
            FROM crustacean_hosts
            ORDER BY scientific_name
        """)
        rows = [dict(r) for r in c.fetchall()]
    return {"hosts": rows, "count": len(rows)}


@app.get("/api/hosts/by-phylum", response_model=List[HostPhylumStats], tags=["Core Data"])
def get_hosts_by_phylum():
    """Return virus/host statistics grouped by host phylum."""
    with get_db() as conn:
        c = conn.cursor()
        try:
            c.execute("""
                SELECT COALESCE(h.phylum, 'Unknown') AS phylum,
                       COUNT(DISTINCT vm.master_id) AS virus_species_count,
                       COUNT(DISTINCT ir.isolate_id) AS isolate_count,
                       COUNT(DISTINCT h.host_id) AS host_species_count
                FROM crustacean_hosts h
                LEFT JOIN infection_records ir ON h.host_id = ir.host_id
                LEFT JOIN viral_isolates vi ON ir.isolate_id = vi.isolate_id
                LEFT JOIN virus_master vm ON vi.master_id = vm.master_id
                GROUP BY COALESCE(h.phylum, 'Unknown')
                ORDER BY virus_species_count DESC
            """)
            rows = [dict(r) for r in c.fetchall()]
        except sqlite3.Error:
            rows = []
    return rows


@app.get("/api/expansion/status", response_model=ExpansionStats, tags=["Stats"])
def get_expansion_status():
    """Return expansion progress tracking metrics."""
    with get_db() as conn:
        c = conn.cursor()
        result = {}
        try:
            c.execute("SELECT COUNT(*) FROM virus_master")
            result["total_virus_species"] = c.fetchone()[0]
            c.execute("""SELECT COUNT(DISTINCT phylum) FROM crustacean_hosts
                         WHERE phylum IS NOT NULL AND phylum != ''""")
            result["phyla_covered"] = c.fetchone()[0]
            c.execute("""SELECT host_scope_status, COUNT(*) AS cnt
                         FROM crustacean_hosts
                         WHERE host_scope_status LIKE 'target%'
                         GROUP BY host_scope_status""")
            result["target_hosts_by_phylum"] = {r["host_scope_status"]: r["cnt"] for r in c.fetchall()}
            c.execute("""SELECT ROUND(CAST(SUM(CASE WHEN host_association_method IS NOT NULL
                         AND host_association_method != '' THEN 1 ELSE 0 END) AS REAL)
                         / CAST(NULLIF(COUNT(*), 0) AS REAL) * 100, 1)
                         FROM infection_records""")
            row = c.fetchone()
            result["evidence_coverage_pct"] = row[0] if row and row[0] is not None else 0.0
            c.execute("""SELECT COUNT(DISTINCT vm.master_id) FROM virus_master vm
                         WHERE vm.master_id IN (SELECT DISTINCT vp.master_id FROM viral_proteins vp
                         WHERE vp.protein_id IN (SELECT protein_id FROM uniprot_structures
                         WHERE protein_id IS NOT NULL UNION SELECT protein_id FROM protein_structures
                         WHERE protein_id IS NOT NULL))""")
            result["species_with_structures"] = c.fetchone()[0]
        except sqlite3.Error:
            result = {"total_virus_species": 0, "phyla_covered": 0,
                      "target_hosts_by_phylum": {}, "evidence_coverage_pct": 0.0,
                      "species_with_structures": 0}
    return result


@app.get("/api/infection-records", response_model=List[InfectionRecordResponse], tags=["Core Data"])
def get_infection_records(phylum: Optional[str] = Query(None, description="Filter by host phylum")):
    """Return virus-host infection/association records, optionally filtered by phylum."""
    with get_db() as conn:
        c = conn.cursor()
        try:
            sql = """SELECT ir.record_id AS infection_id,
                            COALESCE(vm.canonical_name, vi.virus_name, '') AS virus_name,
                            COALESCE(h.scientific_name, '') AS host_name,
                            COALESCE(h.phylum, '') AS host_phylum,
                            COALESCE(h.class, '') AS host_class,
                            COALESCE(ir.host_association_method, '') AS association_method,
                            ir.detection_method,
                            NULL AS evidence_strength
                     FROM infection_records ir
                     LEFT JOIN viral_isolates vi ON ir.isolate_id = vi.isolate_id
                     LEFT JOIN virus_master vm ON vi.master_id = vm.master_id
                     LEFT JOIN crustacean_hosts h ON ir.host_id = h.host_id"""
            params = []
            if phylum:
                sql += " WHERE h.phylum = ?"
                params.append(phylum)
            sql += " ORDER BY ir.record_id DESC LIMIT 500"
            c.execute(sql, params)
            rows = [dict(r) for r in c.fetchall()]
        except sqlite3.Error:
            rows = []
    return rows


@app.get("/api/hosts/detail", response_model=List[HostDetailResponse], tags=["Core Data"])
def get_hosts_detail(
    phylum: Optional[str] = Query(None, description="Filter by host phylum"),
    scope: Optional[str] = Query(None, alias="scope_status", description="Filter by scope status"),
):
    """Return detailed host species information, optionally filtered."""
    with get_db() as conn:
        c = conn.cursor()
        try:
            sql = """SELECT h.host_id, h.scientific_name,
                            COALESCE(h.phylum, '') AS phylum,
                            COALESCE(h.class, '') AS class,
                            COALESCE(h.host_scope_status, '') AS host_scope_status,
                            COALESCE(h.aquaculture_status, '') AS aquaculture_status,
                            COUNT(DISTINCT vm.master_id) AS virus_count
                     FROM crustacean_hosts h
                     LEFT JOIN infection_records ir ON h.host_id = ir.host_id
                     LEFT JOIN viral_isolates vi ON ir.isolate_id = vi.isolate_id
                     LEFT JOIN virus_master vm ON vi.master_id = vm.master_id"""
            conditions = []
            params = []
            if phylum:
                conditions.append("h.phylum = ?")
                params.append(phylum)
            if scope:
                conditions.append("h.host_scope_status = ?")
                params.append(scope)
            if conditions:
                sql += " WHERE " + " AND ".join(conditions)
            sql += " GROUP BY h.host_id ORDER BY h.scientific_name"
            c.execute(sql, params)
            rows = []
            for r in c.fetchall():
                d = dict(r)
                d["class_name"] = d.pop("class", "")
                rows.append(d)
        except sqlite3.Error:
            rows = []
    return rows


@app.get("/api/suggestions", tags=["Core Data"])
def get_suggestions(
    kind: str = Query("virus", pattern="^(virus|host)$"),
    q: Optional[str] = Query(None, description="Auto-complete query"),
    limit: int = Query(8, ge=1, le=20),
):
    """Return lightweight suggestions for homepage auto-complete."""
    with get_db() as conn:
        c = conn.cursor()
        keyword = (q or "").strip()
    
        if kind == "host":
            if keyword:
                like_q = f"%{_escape_like(keyword)}%"
                prefix_q = f"{_escape_like(keyword)}%"
                c.execute(
                    """
                    SELECT
                        scientific_name AS value,
                        common_name_cn AS subtitle
                    FROM crustacean_hosts
                    WHERE scientific_name LIKE ? ESCAPE '\\' OR common_name_cn LIKE ? ESCAPE '\\'
                    ORDER BY
                        CASE WHEN scientific_name LIKE ? ESCAPE '\\' THEN 0 ELSE 1 END,
                        scientific_name
                    LIMIT ?
                    """,
                    (like_q, like_q, prefix_q, limit),
                )
            else:
                c.execute(
                    """
                    SELECT
                        h.scientific_name AS value,
                        h.common_name_cn AS subtitle,
                        COUNT(*) AS cnt
                    FROM crustacean_hosts h
                    JOIN infection_records ir ON h.host_id = ir.host_id
                    GROUP BY h.host_id
                    ORDER BY cnt DESC, h.scientific_name
                    LIMIT ?
                    """,
                    (limit,),
                )
        else:
            if keyword:
                like_q = f"%{_escape_like(keyword)}%"
                prefix_q = f"{_escape_like(keyword)}%"
                c.execute(
                    """
                    SELECT
                        vm.canonical_name AS value,
                        vm.chinese_name AS subtitle,
                        COUNT(*) AS cnt
                    FROM analysis_strict_target_isolates v
                    JOIN virus_master vm ON v.master_id = vm.master_id
                    WHERE vm.host_phylum IN ('Arthropoda','Mollusca','Cnidaria','Echinodermata','Porifera')
                      AND (
                          vm.canonical_name LIKE ? ESCAPE '\\'
                          OR vm.chinese_name LIKE ? ESCAPE '\\'
                          OR vm.abbreviations LIKE ? ESCAPE '\\'
                          OR v.virus_name LIKE ? ESCAPE '\\'
                      )
                    GROUP BY vm.canonical_name, vm.chinese_name
                    ORDER BY
                        CASE WHEN vm.canonical_name LIKE ? ESCAPE '\\' THEN 0 ELSE 1 END,
                        cnt DESC,
                        vm.canonical_name
                    LIMIT ?
                    """,
                    (like_q, like_q, like_q, like_q, prefix_q, limit),
                )
            else:
                c.execute(
                    """
                    SELECT
                        vm.canonical_name AS value,
                        vm.chinese_name AS subtitle,
                        COUNT(*) AS cnt
                    FROM analysis_strict_target_isolates v
                    JOIN virus_master vm ON v.master_id = vm.master_id
                    WHERE vm.host_phylum IN ('Arthropoda','Mollusca','Cnidaria','Echinodermata','Porifera')
                      AND vm.entry_type NOT IN ('EST', 'patent', 'non_target', 'unknown')
                    GROUP BY vm.canonical_name, vm.chinese_name
                    ORDER BY cnt DESC, vm.canonical_name
                    LIMIT ?
                    """,
                    (limit,),
                )
    
        rows = [{"value": r["value"], "subtitle": r["subtitle"]} for r in c.fetchall() if r["value"]]
    return {"items": rows}


@app.get("/api/search", tags=["Core Data"])
def search_viruses(
    q: Optional[str] = Query(None, description="Search keyword (virus name, accession, canonical name). Supports FTS if available."),
    host: Optional[str] = Query(None, description="Filter by aquatic invertebrate host scientific name"),
    country: Optional[str] = Query(None, description="Filter by collection country"),
    completeness: Optional[str] = Query(None, description="Sequence completeness: complete_genome, partial_sequence, gene_fragment, EST"),
    year_from: Optional[str] = Query(None, description="Earliest collection year (inclusive)"),
    year_to: Optional[str] = Query(None, description="Latest collection year (inclusive)"),
    phylum: Optional[str] = Query(None, description="Filter by host phylum (Arthropoda, Mollusca, Cnidaria, etc.)"),
    page: int = Query(1, ge=1, description="Result page number (1-indexed)"),
    page_size: int = Query(20, ge=1, le=100, description="Number of results per page"),
):
    """
    Search virus records with multi-dimensional filtering.

    Supports combined keyword search (virus name, accession, canonical name),
    host species, country, sequence completeness, and collection year range.
    Paginated with total count.  When no keyword is provided, returns all
    release-filtered strict-target isolates sorted by accession.

    Query parameters serve as filters; all are optional.  When multiple
    filters are supplied they are combined with AND logic.

    Example:
        GET /api/search?q=white+spot&host=Penaeus+vannamei&page=1&page_size=10
        -> {"total": 25, "page": 1, "page_size": 10, "results": [...]}
    """
    with get_db() as conn:
        c = conn.cursor()
    
        where_sql, params = build_search_where(
            q=q, host=host, country=country,
            completeness=completeness, year_from=year_from, year_to=year_to,
            phylum=phylum, conn=conn,
        )
    
        offset = (page - 1) * page_size
        count_sql = f"""
            SELECT COUNT(*) FROM viral_isolates v
            LEFT JOIN virus_master vm ON v.master_id = vm.master_id
            LEFT JOIN infection_records ir ON v.isolate_id = ir.isolate_id
            LEFT JOIN crustacean_hosts h ON ir.host_id = h.host_id
            LEFT JOIN sample_collections s ON ir.collection_id = s.collection_id
            WHERE {where_sql}
        """
        c.execute(count_sql, params)
        total = c.fetchone()[0]

        data_sql = f"""
            SELECT
                v.isolate_id,
                v.accession,
                v.virus_name,
                vm.canonical_name,
                vm.chinese_name as canonical_name_cn,
                vm.abbreviations,
                vm.entry_type,
                v.taxon_family,
                v.taxon_genus,
                v.genome_length,
                h.scientific_name AS host_name,
                h.common_name_cn AS host_cn,
                s.country,
                s.collection_year,
                s.collection_date,
                s.note AS isolation_source,
                l.title AS ref_title,
                l.pmid,
                l.doi,
                icp.dataset_tier,
                icp.curation_status,
                icp.confidence AS curation_confidence
            FROM viral_isolates v
            LEFT JOIN virus_master vm ON v.master_id = vm.master_id
            LEFT JOIN infection_records ir ON v.isolate_id = ir.isolate_id
            LEFT JOIN crustacean_hosts h ON ir.host_id = h.host_id
            LEFT JOIN sample_collections s ON ir.collection_id = s.collection_id
            LEFT JOIN ref_literatures l ON v.reference_id = l.reference_id
            LEFT JOIN isolate_curated_profiles icp ON icp.isolate_id = v.isolate_id
            WHERE {where_sql}
            ORDER BY v.isolate_id
            LIMIT ? OFFSET ?
        """
        c.execute(data_sql, params + [page_size, offset])
        rows = [dict(r) for r in c.fetchall()]

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "results": rows,
    }


@app.get("/api/virus/{accession}", tags=["Core Data"])
def get_virus_detail(accession: str):
    """
    Retrieve full details for a single virus isolate by NCBI accession.

    Returns the complete isolate record joined with its canonical virus
    name (from virus_master), host information, sample collection
    metadata (country, province, city, coordinates, date), and linked
    literature reference.  Also includes:
      - NCBI nucleotide URL for the accession
      - Whether a local FASTA sequence file is available
      - Up to 10 virulence evidence records
      - Up to 10 temperature evidence records

    Parameters
    ----------
    accession : str
        NCBI / INSDC sequence accession (e.g. "AF332093").

    Raises 404 if the accession is not found in the release-filtered strict-target set.

    Example:
        GET /api/virus/AF332093
        -> {"accession": "AF332093", "virus_name": "WSSV", ...}
    """
    with get_db() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT
                v.*,
                vm.canonical_name,
                vm.chinese_name as canonical_name_cn,
                vm.abbreviations,
                vm.entry_type,
                vm.discovery_context,
                vm.host_phylum as virus_host_phylum,
                h.scientific_name AS host_name,
                h.common_name_cn AS host_cn,
                h.phylum AS host_phylum,
                h.class AS host_class,
                h.host_scope_status,
                ir.host_association_method,
                s.country, s.province, s.city, s.latitude, s.longitude,
                s.collection_year, s.collection_date, s.note AS isolation_source,
                l.title AS ref_title, l.authors AS ref_authors, l.journal,
                l.year AS ref_year, l.doi, l.pmid, l.abstract
            FROM analysis_strict_target_isolates v
            LEFT JOIN virus_master vm ON v.master_id = vm.master_id
            LEFT JOIN infection_records ir ON v.isolate_id = ir.isolate_id
            LEFT JOIN crustacean_hosts h ON ir.host_id = h.host_id
            LEFT JOIN sample_collections s ON ir.collection_id = s.collection_id
            LEFT JOIN ref_literatures l ON v.reference_id = l.reference_id
            WHERE v.accession = ?
        """, (accession,))
        row = c.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Virus record not found")

        result = dict(row)
        virus_name = result.get("canonical_name") or result.get("virus_name", "")
        
        # Add NCBI links
        result["ncbi_nucleotide_url"] = f"https://www.ncbi.nlm.nih.gov/nuccore/{accession}"
        
        # Check if sequence file exists
        seq_file = SEQUENCES_DIR / f"{accession}.fasta"
        result["has_sequence_file"] = seq_file.exists()
        
        # Public detail pages expose only reviewed evidence records.
        c.execute("""
            SELECT
                evidence_id, evidence_type, claim, value_text,
                value_numeric_min, value_numeric_max, unit, context,
                observation_type, evidence_strength, source_pmid, source_doi
            FROM analysis_reviewed_evidence_records
            WHERE evidence_type IN ('virulence','pathogenicity','mortality')
              AND (isolate_id = ? OR virus_master_id = ?)
            ORDER BY evidence_strength DESC, evidence_id
            LIMIT 10
        """, (result.get("isolate_id"), result.get("master_id")))
        result["virulence_evidence"] = [dict(r) for r in c.fetchall()]

        c.execute("""
            SELECT
                evidence_id, evidence_type, claim, value_text,
                value_numeric_min, value_numeric_max, unit, context,
                observation_type, evidence_strength, source_pmid, source_doi
            FROM analysis_reviewed_evidence_records
            WHERE evidence_type IN ('temperature','thermal_stability','thermal_inactivation','temperature_range')
              AND (isolate_id = ? OR virus_master_id = ?)
            ORDER BY evidence_strength DESC, evidence_id
            LIMIT 10
        """, (result.get("isolate_id"), result.get("master_id")))
        result["temperature_evidence"] = [dict(r) for r in c.fetchall()]
        
    return result


@app.get("/api/virus/{accession}/sequence", tags=["Core Data"])
def get_virus_sequence(accession: str):
    """Return cached FASTA sequence for one accession."""
    seq_file = _safe_accession_fasta(accession)
    if not seq_file.exists():
        return {"error": "Sequence not found", "accession": accession}
    
    from fastapi.responses import PlainTextResponse
    content = seq_file.read_text(encoding="utf-8")
    return PlainTextResponse(content=content, media_type="text/plain")


@app.get("/api/virus/{accession}/proteins", tags=["Proteins"])
def get_virus_proteins(accession: str):
    """Return annotated protein/CDS records for one virus isolate."""
    with get_db() as conn:
        c = conn.cursor()
        # Get all proteins with structures via direct link and bridge table
        struct_protein_ids = set()
        for r in c.execute(
            "SELECT DISTINCT protein_id FROM uniprot_structures WHERE protein_id IS NOT NULL"
        ).fetchall():
            struct_protein_ids.add(r[0])
        for r in c.execute(
            "SELECT DISTINCT protein_id FROM protein_structures WHERE protein_id IS NOT NULL"
        ).fetchall():
            struct_protein_ids.add(r[0])
        for r in c.execute(
            "SELECT DISTINCT upl.protein_id FROM uniprot_structures us JOIN uniprot_protein_links upl ON us.uniprot_id = upl.uniprot_id"
        ).fetchall():
            struct_protein_ids.add(r[0])

        c.execute("""
            SELECT
                vp.protein_id,
                vp.protein_accession,
                vp.protein_name,
                vp.gene_symbol,
                vp.locus_tag,
                vp.aa_length,
                vp.genome_start,
                vp.genome_end,
                vp.functional_category,
                vp.functional_annotation_status,
                vp.ec_number,
                vp.translation
            FROM viral_proteins vp
            JOIN viral_isolates vi ON vp.isolate_id = vi.isolate_id
            WHERE vi.accession = ?
              AND COALESCE(vp.functional_annotation_status, '') <> 'rule_suggested_unreviewed'
            ORDER BY vp.genome_start
        """, (accession,))
        rows = [dict(r) for r in c.fetchall()]

        # Corrupted legacy comment removed.
        for r in rows:
            r["_has_structure"] = r["protein_id"] in struct_protein_ids

        # Corrupted legacy comment removed.
        categories = {}
        for r in rows:
            cat = r["functional_category"]
            categories[cat] = categories.get(cat, 0) + 1

    return {"accession": accession, "protein_count": len(rows), "proteins": rows, "categories": categories}


@app.get("/api/proteins/search", response_model=PaginatedProteinResponse, tags=["Proteins"])
def search_proteins(
    q: str = Query("", description="Protein keyword"),
    virus: str = Query("", description="Virus name filter"),
    category: str = Query("", description="Functional category filter"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    """
    Search protein annotations across all virus species.

    Supports filtering by protein name / gene symbol (keyword search),
    virus species, and functional category.  Returns paginated results
    with structure availability flags.

    Parameters
    ----------
    q : str
        Keyword to match against protein_name, gene_symbol, or protein_accession.
    virus : str
        Canonical virus species name to narrow results.
    category : str
        Functional category filter (e.g. "structural", "replication").
    page : int
        Page number (1-indexed), default 1.
    page_size : int
        Results per page (1-100), default 20.

    Example:
        GET /api/proteins/search?q=VP28&virus=WSSV&page=1&page_size=10
        -> {"total": 3, "page": 1, "page_size": 10, "results": [...]}
    """
    with get_db() as conn:
        c = conn.cursor()
    
        where_clauses = [
            "vi.isolate_id IN (SELECT isolate_id FROM analysis_strict_target_isolates)",
            "COALESCE(vp.functional_annotation_status, '') <> 'rule_suggested_unreviewed'",
        ]
        params = []
    
        if q:
            like_q = f"%{_escape_like(q)}%"
            where_clauses.append("(vp.protein_name LIKE ? ESCAPE '\\' OR vp.gene_symbol LIKE ? ESCAPE '\\' OR vp.protein_accession LIKE ? ESCAPE '\\')")
            params.extend([like_q, like_q, like_q])
    
        if virus:
            where_clauses.append("vm.canonical_name = ?")
            params.append(virus)
    
        if category:
            where_clauses.append("vp.functional_category = ?")
            params.append(category)
    
        where_sql = " AND ".join(where_clauses)
    
        # Corrupted legacy comment removed.
        count_sql = f"""
            SELECT COUNT(*) FROM viral_proteins vp
            JOIN viral_isolates vi ON vp.isolate_id = vi.isolate_id
            JOIN virus_master vm ON vi.master_id = vm.master_id
            WHERE {where_sql}
        """
        c.execute(count_sql, params)
        total = c.fetchone()[0]
    
        # Corrupted legacy comment removed.
        offset = (page - 1) * page_size
        data_sql = f"""
            SELECT
                vp.protein_id, vp.protein_accession, vp.protein_name,
                vp.gene_symbol, vp.locus_tag, vp.aa_length,
                vp.functional_category,
                vp.functional_annotation_status,
                vi.accession,
                vm.canonical_name AS virus_name,
                CASE WHEN EXISTS (
                    SELECT 1 FROM uniprot_structures us
                    JOIN uniprot_protein_links upl ON us.uniprot_id = upl.uniprot_id
                    WHERE upl.protein_id = vp.protein_id
                    UNION
                    SELECT 1 FROM protein_structures ps
                    WHERE ps.protein_id = vp.protein_id
                ) THEN 1 ELSE 0 END AS has_structure
            FROM viral_proteins vp
            JOIN viral_isolates vi ON vp.isolate_id = vi.isolate_id
            JOIN virus_master vm ON vi.master_id = vm.master_id
            WHERE {where_sql}
            ORDER BY vm.canonical_name, vp.genome_start
            LIMIT ? OFFSET ?
        """
        c.execute(data_sql, params + [page_size, offset])
        rows = [dict(r) for r in c.fetchall()]
        for r in rows:
            r["_has_structure"] = bool(r.pop("has_structure", 0))

    return {"total": total, "page": page, "page_size": page_size, "results": rows}


@app.get("/api/core_genes", tags=["Proteins"])
def get_core_genes(
    virus: str = Query("", description="Filter by canonical virus species name"),
    min_conservation: float = Query(50.0, ge=0, le=100, description="Minimum conservation rate (%) threshold"),
):
    """
    List core / conserved gene analysis across virus species.

    Returns genes grouped by virus species with conservation statistics.
    Core genes are defined as those with >= 80% conservation rate.

    Parameters
    ----------
    virus : str
        Optional species name filter.
    min_conservation : float
        Minimum conservation rate percentage (0-100), default 50.

    Example:
        GET /api/core_genes?virus=WSSV&min_conservation=70
        -> {"total_genes": 15, "total_species": 1, "by_virus": [...], "genes": [...]}
    """
    with get_db() as conn:
        c = conn.cursor()
    
        where_clauses = ["cg.conservation_rate >= ?"]
        params = [min_conservation]
    
        if virus:
            where_clauses.append("cg.virus_species = ?")
            params.append(virus)
    
        where_sql = " AND ".join(where_clauses)
    
        c.execute(f"""
            SELECT
                cg.virus_species,
                cg.gene_symbol,
                cg.protein_name,
                cg.functional_category,
                cg.conservation_rate,
                cg.total_isolates,
                cg.present_isolates,
                cg.function_summary
            FROM core_genes cg
            WHERE {where_sql}
            ORDER BY cg.conservation_rate DESC, cg.virus_species
        """, params)
        rows = [dict(r) for r in c.fetchall()]
    
        # Corrupted legacy comment removed.
        by_virus = {}
        for r in rows:
            vs = r["virus_species"]
            if vs not in by_virus:
                by_virus[vs] = {"virus_species": vs, "genes": [], "core_count": 0, "avg_conservation": 0}
            by_virus[vs]["genes"].append(r)
            if r["conservation_rate"] >= 80:
                by_virus[vs]["core_count"] += 1
    
        for v in by_virus.values():
            v["avg_conservation"] = round(
                sum(g["conservation_rate"] for g in v["genes"]) / len(v["genes"]), 1
            ) if v["genes"] else 0
    
    return {"total_genes": len(rows), "total_species": len(by_virus), "by_virus": list(by_virus.values()), "genes": rows}


@app.get("/api/stats/proteins", tags=["Stats"])
def get_protein_stats():
    """Return protein annotation summary statistics."""
    with get_db() as conn:
        c = conn.cursor()
    
        c.execute("SELECT COUNT(*) FROM viral_proteins")
        total = c.fetchone()[0]
    
        c.execute("SELECT COUNT(DISTINCT isolate_id) FROM viral_proteins")
        isolates_covered = c.fetchone()[0]
    
        c.execute("""
            SELECT functional_category, COUNT(*) as cnt
            FROM viral_proteins
            GROUP BY functional_category
            ORDER BY cnt DESC
        """)
        categories = [{"category": r[0], "count": r[1]} for r in c.fetchall()]
    
        c.execute("""
            SELECT vm.canonical_name, COUNT(vp.protein_id) as cnt
            FROM viral_proteins vp
            JOIN viral_isolates vi ON vp.isolate_id = vi.isolate_id
            JOIN virus_master vm ON vi.master_id = vm.master_id
            GROUP BY vm.canonical_name
            ORDER BY cnt DESC
            LIMIT 10
        """)
        top_viruses = [{"virus": r[0], "protein_count": r[1]} for r in c.fetchall()]
    
        c.execute("SELECT COUNT(*) FROM core_genes")
        core_genes = c.fetchone()[0]
        bridge = {
            "rows": 0,
            "with_uniprot": 0,
            "with_interpro": 0,
            "with_go": 0,
            "with_kegg": 0,
            "with_structure": 0,
        }
        try:
            c.execute("SELECT COUNT(*) FROM protein_annotation_bridge")
            bridge["rows"] = c.fetchone()[0]
            for key, field in [
                ("with_uniprot", "has_uniprot"),
                ("with_interpro", "has_interpro"),
                ("with_go", "has_interpro_go"),
                ("with_kegg", "has_kegg"),
                ("with_structure", "has_structure"),
            ]:
                field = _safe_sql_identifier(
                    field,
                    {"has_uniprot", "has_interpro", "has_interpro_go", "has_kegg", "has_structure"},
                )
                c.execute(f"SELECT COUNT(DISTINCT protein_id) FROM protein_annotation_bridge WHERE {field}=1")
                bridge[key] = c.fetchone()[0]
        except sqlite3.Error:
            pass
    
    return {
        "total_proteins": total,
        "isolates_with_proteins": isolates_covered,
        "categories": categories,
        "top_viruses": top_viruses,
        "core_gene_entries": core_genes,
        "annotation_bridge": bridge,
    }


@app.get("/api/rdrp", response_model=PaginatedRDRPResponse, tags=["RDRP"])
def get_rdrp_list(
    species: str = Query("", description="Filter by canonical virus species name"),
    page: int = Query(1, ge=1, description="Page number (1-indexed)"),
    page_size: int = Query(20, ge=1, le=200, description="Results per page (max 200)"),
):
    """
    List RNA-dependent RNA polymerase (RDRP) annotations across all species.

    Returns paginated RDRP records with protein details, parent isolate
    accession, and a flag indicating whether a 3D structure is available.

    Parameters
    ----------
    species : str
        Optional filter to restrict results to a single virus species.
    page : int
        Page number (1-indexed), default 1.
    page_size : int
        Results per page (1-200), default 20.

    Example:
        GET /api/rdrp?species=WSSV&page=1&page_size=20
        -> {"total": 45, "page": 1, "page_size": 20, "results": [...]}
    """
    with get_db() as conn:
        c = conn.cursor()
    
        where = """
            vp.is_rdrp = 1
            AND vi.isolate_id IN (SELECT isolate_id FROM analysis_strict_target_isolates)
            AND COALESCE(vp.functional_annotation_status, '') <> 'rule_suggested_unreviewed'
        """
        params = []
        if species:
            where += " AND vm.canonical_name = ?"
            params.append(species)
    
        # Corrupted legacy comment removed.
        c.execute(f"""
            SELECT COUNT(*) FROM viral_proteins vp
            JOIN viral_isolates vi ON vp.isolate_id = vi.isolate_id
            JOIN virus_master vm ON vi.master_id = vm.master_id
            WHERE {where}
        """, params)
        total = c.fetchone()[0]
    
        # Corrupted legacy comment removed.
        offset = (page - 1) * page_size
        c.execute(f"""
            SELECT
                vp.protein_id, vp.protein_accession, vp.protein_name,
                vp.gene_symbol, vp.aa_length, vp.functional_category,
                vp.functional_annotation_status,
                vi.accession,
                vm.canonical_name AS virus_species,
                vm.genome_type,
                CASE WHEN EXISTS (
                    SELECT 1 FROM uniprot_structures us
                    JOIN uniprot_protein_links upl ON us.uniprot_id = upl.uniprot_id
                    WHERE upl.protein_id = vp.protein_id
                    UNION
                    SELECT 1 FROM protein_structures ps
                    WHERE ps.protein_id = vp.protein_id
                ) THEN 1 ELSE 0 END AS has_structure
            FROM viral_proteins vp
            JOIN viral_isolates vi ON vp.isolate_id = vi.isolate_id
            JOIN virus_master vm ON vi.master_id = vm.master_id
            WHERE {where}
            ORDER BY vm.canonical_name, vi.accession, vp.genome_start
            LIMIT ? OFFSET ?
        """, params + [page_size, offset])
        rows = [dict(r) for r in c.fetchall()]
        for r in rows:
            r["_has_structure"] = bool(r.pop("has_structure", 0))
    return {"total": total, "page": page, "page_size": page_size, "results": rows}


@app.get("/api/rdrp/species", tags=["RDRP"])
def get_rdrp_species():
    """
    List all virus species that have at least one RDRP annotation.

    Returns species name, genome type, RDRP count, and isolate count,
    sorted by RDRP count descending.

    Example:
        GET /api/rdrp/species
        -> [{"species": "WSSV", "genome_type": "dsDNA", "rdrp_count": 1, "isolate_count": 45}, ...]
    """
    with get_db() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT vm.canonical_name AS species, vm.genome_type,
                   COUNT(vp.protein_id) AS rdrp_count,
                   COUNT(DISTINCT vi.accession) AS isolate_count
            FROM viral_proteins vp
            JOIN viral_isolates vi ON vp.isolate_id = vi.isolate_id
            JOIN virus_master vm ON vi.master_id = vm.master_id
            WHERE vp.is_rdrp = 1
              AND vi.isolate_id IN (SELECT isolate_id FROM analysis_strict_target_isolates)
              AND COALESCE(vp.functional_annotation_status, '') <> 'rule_suggested_unreviewed'
            GROUP BY vm.canonical_name
            ORDER BY rdrp_count DESC
        """)
        rows = [dict(r) for r in c.fetchall()]
    return rows


@app.get("/api/rdrp/blast/status", tags=["RDRP"])
def get_rdrp_blast_status():
    """Return local BLAST+ availability and RDRP database status."""
    blastp_bin = find_blast_binary("blastp")
    blastx_bin = find_blast_binary("blastx")
    makeblastdb_bin = find_blast_binary("makeblastdb")
    fasta_records = 0
    if RDRP_BLAST_FASTA.exists():
        with RDRP_BLAST_FASTA.open("r", encoding="utf-8", errors="ignore") as f:
            fasta_records = sum(1 for line in f if line.startswith(">"))
    return {
        "blastp_available": bool(blastp_bin),
        "blastx_available": bool(blastx_bin),
        "makeblastdb_available": bool(makeblastdb_bin),
        "blast_plus_available": bool(blastp_bin and blastx_bin and makeblastdb_bin),
        "database_ready": rdrp_blast_db_exists(),
        "fasta_records": fasta_records,
    }


# In-memory rate limiter for BLAST database rebuild
_last_blast_build_time: float = 0.0
_blast_build_lock = threading.Lock()
BLAST_BUILD_COOLDOWN_SECONDS = 300  # 5 minutes

# In-memory rate limiter for BLAST search endpoint
_blast_search_lock = threading.Lock()
_last_blast_search_time: float = 0.0
BLAST_SEARCH_COOLDOWN_SECONDS = 10
_blast_search_ip_times: dict[str, float] = {}
_blast_search_ip_counts: dict[str, int] = {}
_blast_search_ip_lock = threading.Lock()
MAX_CONCURRENT_BLAST_SEARCHES_PER_IP = 2

# In-memory rate limiter for k-mer search endpoint
_kmer_search_lock = threading.Lock()
_last_kmer_search_time: float = 0.0
KMER_SEARCH_COOLDOWN_SECONDS = 5

# In-memory rate limiter for structure prediction endpoint
_structure_predict_lock2 = threading.Lock()
_last_structure_predict_time: float = 0.0
STRUCTURE_PREDICT_COOLDOWN_SECONDS = 30


@app.post("/api/rdrp/blast/build", tags=["RDRP"])
def build_rdrp_blast_database_api(api_key: str = Depends(require_api_key)):
    """Export RDRP proteins and build a local NCBI BLAST protein database."""
    global _last_blast_build_time
    with _blast_build_lock:
        now = time.time()
        elapsed = now - _last_blast_build_time
        if _last_blast_build_time > 0 and elapsed < BLAST_BUILD_COOLDOWN_SECONDS:
            remaining = int(BLAST_BUILD_COOLDOWN_SECONDS - elapsed)
            raise HTTPException(
                status_code=429,
                detail=f"BLAST database was recently rebuilt. Please wait {remaining} seconds before rebuilding again."
            )
        _last_blast_build_time = now
    return build_rdrp_blast_database()


@app.post("/api/rdrp/blast", tags=["RDRP"])
def blast_rdrp_sequence(
    request: Request,
    payload: dict = Body(...),
    program: str = Query("blastp", pattern="^(blastp|blastx)$"),
    api_key: str = Depends(require_api_key),
    limit: int = Query(20, ge=1, le=100),
    evalue: float = Query(1e-5, gt=0),
):
    """Run local BLASTP/BLASTX against the built-in RDRP protein database."""
    # Global cooldown: prevent rapid successive searches
    with _blast_search_lock:
        now = time.time()
        elapsed = now - _last_blast_search_time
        if _last_blast_search_time > 0 and elapsed < BLAST_SEARCH_COOLDOWN_SECONDS:
            remaining = int(BLAST_SEARCH_COOLDOWN_SECONDS - elapsed)
            raise HTTPException(
                status_code=429,
                detail=f"BLAST search rate limited. Please wait {remaining} seconds before searching again."
            )
        _last_blast_search_time = now

    # Per-IP concurrent request cap: prevent a single IP from flooding
    client_ip = request.client.host if request.client else "unknown"
    with _blast_search_ip_lock:
        # Clean stale entries
        now = time.time()
        stale_ips = [ip for ip, ts in _blast_search_ip_times.items() if now - ts > 120]
        for ip in stale_ips:
            _blast_search_ip_times.pop(ip, None)
            _blast_search_ip_counts.pop(ip, None)

        current_count = _blast_search_ip_counts.get(client_ip, 0)
        if current_count >= MAX_CONCURRENT_BLAST_SEARCHES_PER_IP:
            raise HTTPException(
                status_code=429,
                detail="Too many concurrent BLAST searches from your IP. Please wait for running searches to complete."
            )
        _blast_search_ip_counts[client_ip] = current_count + 1
        _blast_search_ip_times[client_ip] = now

    try:
        query_sequence = str(payload.get("sequence", ""))
        return run_local_rdrp_blast(query_sequence, program=program, limit=limit, evalue=evalue)
    finally:
        # Decrement IP counter when search completes (or fails)
        with _blast_search_ip_lock:
            count = _blast_search_ip_counts.get(client_ip, 0)
            if count > 1:
                _blast_search_ip_counts[client_ip] = count - 1
            else:
                _blast_search_ip_counts.pop(client_ip, None)
                _blast_search_ip_times.pop(client_ip, None)


@app.post("/api/rdrp/search_sequence", tags=["RDRP"])
def search_rdrp_by_sequence(
    request: Request,
    payload: dict = Body(...),
    limit: int = Query(20, ge=1, le=100),
    api_key: str = Depends(require_api_key),
    k: int = Query(5, ge=3, le=8),
):
    """Search database RDRP proteins by amino-acid k-mer similarity."""
    # Rate limit: 5-second global cooldown for this heavy database scan
    with _kmer_search_lock:
        now = time.time()
        elapsed = now - _last_kmer_search_time
        if _last_kmer_search_time > 0 and elapsed < KMER_SEARCH_COOLDOWN_SECONDS:
            remaining = int(KMER_SEARCH_COOLDOWN_SECONDS - elapsed)
            raise HTTPException(
                status_code=429,
                detail=f"Search rate limited. Please wait {remaining} seconds before searching again."
            )
        _last_kmer_search_time = now

    query_sequence = normalize_protein_sequence(str(payload.get("sequence", "")))
    if len(query_sequence) < k:
        return {
            "engine": "builtin_kmer",
            "query_length": len(query_sequence),
            "k": k,
            "total_targets": 0,
            "results": [],
            "error": f"Query sequence must contain at least {k} amino-acid letters.",
        }

    query_kmers = protein_kmers(query_sequence, k)
    if not query_kmers:
        return {
            "engine": "builtin_kmer",
            "query_length": len(query_sequence),
            "k": k,
            "total_targets": 0,
            "results": [],
            "error": "No valid amino-acid sequence was provided.",
        }

    with get_db() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT
                vp.protein_id, vp.protein_accession, vp.protein_name,
                vp.gene_symbol, vp.aa_length, vp.translation,
                vi.accession,
                vm.canonical_name AS virus_species,
                vm.virus_family,
                vm.genome_type
            FROM viral_proteins vp
            JOIN viral_isolates vi ON vp.isolate_id = vi.isolate_id
            JOIN virus_master vm ON vi.master_id = vm.master_id
            WHERE vp.is_rdrp = 1
              AND vi.isolate_id IN (SELECT isolate_id FROM analysis_strict_target_isolates)
              AND COALESCE(vp.functional_annotation_status, '') <> 'rule_suggested_unreviewed'
              AND vp.translation IS NOT NULL
              AND LENGTH(vp.translation) >= ?
        """, (k,))
        targets = c.fetchall()

    hits = []
    for row in targets:
        target_sequence = normalize_protein_sequence(row["translation"])
        target_kmers = protein_kmers(target_sequence, k)
        if not target_kmers:
            continue
        shared = len(query_kmers & target_kmers)
        if shared == 0:
            continue
        union = len(query_kmers | target_kmers)
        query_coverage = shared / len(query_kmers)
        target_coverage = shared / len(target_kmers)
        jaccard = shared / union if union else 0
        substring_match = query_sequence in target_sequence or target_sequence in query_sequence
        score = (0.65 * query_coverage) + (0.25 * jaccard) + (0.10 * target_coverage)
        if substring_match:
            score += 0.15
        hits.append({
            "protein_id": row["protein_id"],
            "protein_accession": row["protein_accession"],
            "protein_name": row["protein_name"],
            "gene_symbol": row["gene_symbol"],
            "aa_length": row["aa_length"],
            "accession": row["accession"],
            "virus_species": row["virus_species"],
            "virus_family": row["virus_family"],
            "genome_type": row["genome_type"],
            "shared_kmers": shared,
            "query_kmers": len(query_kmers),
            "target_kmers": len(target_kmers),
            "query_coverage": round(query_coverage * 100, 2),
            "target_coverage": round(target_coverage * 100, 2),
            "jaccard": round(jaccard * 100, 2),
            "score": round(min(score, 1.0) * 100, 2),
            "substring_match": substring_match,
        })

    hits.sort(
        key=lambda h: (
            h["score"],
            h["query_coverage"],
            h["shared_kmers"],
            -(abs((h["aa_length"] or 0) - len(query_sequence))),
        ),
        reverse=True,
    )
    return {
        "engine": "builtin_kmer",
        "query_length": len(query_sequence),
        "k": k,
        "total_targets": len(targets),
        "returned": min(limit, len(hits)),
        "results": hits[:limit],
    }


@app.get("/api/rdrp/{accession}", tags=["RDRP"])
def get_rdrp_by_accession(accession: str):
    """Return RDRP protein records linked to a nucleotide accession."""
    with get_db() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT
                vp.protein_id, vp.protein_accession, vp.protein_name,
                vp.gene_symbol, vp.aa_length, vp.genome_start, vp.genome_end,
                vp.translation, vp.functional_category, vp.functional_annotation_status,
                vi.accession,
                vm.canonical_name AS virus_species
            FROM viral_proteins vp
            JOIN viral_isolates vi ON vp.isolate_id = vi.isolate_id
            JOIN virus_master vm ON vi.master_id = vm.master_id
            WHERE vp.is_rdrp = 1 AND vi.accession = ?
              AND vi.isolate_id IN (SELECT isolate_id FROM analysis_strict_target_isolates)
              AND COALESCE(vp.functional_annotation_status, '') <> 'rule_suggested_unreviewed'
            ORDER BY vp.genome_start
        """, (accession,))
        rows = [dict(r) for r in c.fetchall()]
    
        # Corrupted legacy comment removed.
        seq_file = SEQUENCES_DIR / f"{accession}.fasta"
        has_seq = seq_file.exists()
    
    return {"accession": accession, "rdrp_count": len(rows), "has_sequence": has_seq, "proteins": rows}


@app.get("/api/rdrp/export/{species}", tags=["RDRP"])
def export_rdrp_fasta_api(species: str):
    """API endpoint."""
    import re
    from fastapi.responses import PlainTextResponse

    with get_db() as conn:
        c = conn.cursor()
        if species == 'all':
            c.execute("""
                SELECT vi.accession, vm.canonical_name, vp.protein_name,
                       vp.gene_symbol, vp.translation, vp.aa_length,
                       vp.functional_annotation_status
                FROM viral_proteins vp
                JOIN viral_isolates vi ON vp.isolate_id = vi.isolate_id
                JOIN virus_master vm ON vi.master_id = vm.master_id
                WHERE vp.is_rdrp = 1
                  AND vi.isolate_id IN (SELECT isolate_id FROM analysis_strict_target_isolates)
                  AND COALESCE(vp.functional_annotation_status, '') <> 'rule_suggested_unreviewed'
                ORDER BY vm.canonical_name, vi.accession, vp.genome_start
            """)
        else:
            c.execute("""
                SELECT vi.accession, vm.canonical_name, vp.protein_name,
                       vp.gene_symbol, vp.translation, vp.aa_length,
                       vp.functional_annotation_status
                FROM viral_proteins vp
                JOIN viral_isolates vi ON vp.isolate_id = vi.isolate_id
                JOIN virus_master vm ON vi.master_id = vm.master_id
                WHERE vp.is_rdrp = 1 AND vm.canonical_name = ?
                  AND vi.isolate_id IN (SELECT isolate_id FROM analysis_strict_target_isolates)
                  AND COALESCE(vp.functional_annotation_status, '') <> 'rule_suggested_unreviewed'
                ORDER BY vi.accession, vp.genome_start
            """, (species,))
        rows = c.fetchall()

    if not rows:
        return {"error": f"No RDRP sequences found for {species}"}

    lines = []
    for acc, vname, pname, gene, trans, aalen, annotation_status in rows:
        if not trans:
            continue
        header = f">{vname}|{acc}|{pname}|{gene or '-'}|{aalen or '?'}aa|annotation_status={annotation_status or 'source_derived'}"
        lines.append(header)
        for i in range(0, len(trans), 60):
            lines.append(trans[i:i+60])

    safe_name = re.sub(r'[\\/*?:"<>|]', "_", species).replace(" ", "_")
    if species == 'all':
        safe_name = "all_rdrp"
    return PlainTextResponse(
        content="\n".join(lines),
        media_type="text/plain",
        headers={"Content-Disposition": f"attachment; filename=rdrp_{safe_name}.fasta"}
    )


@app.get("/api/stats/sequences", tags=["Stats"])
def get_sequence_stats():
    """API endpoint."""
    with get_db() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT s.country, COUNT(*) as count
            FROM analysis_strict_target_isolates v
            LEFT JOIN infection_records ir ON v.isolate_id = ir.isolate_id
            LEFT JOIN sample_collections s ON ir.collection_id = s.collection_id
            WHERE s.country IS NOT NULL AND s.country != ''
            GROUP BY s.country
            ORDER BY count DESC
        """)
        rows = [dict(r) for r in c.fetchall()]
    return rows


@app.get("/api/stats_by_country", tags=["Stats"])
def get_stats_by_country_legacy():
    """Compatibility route used by the map template."""
    return get_sequence_stats()


@app.get("/api/collection_points", tags=["Core Data"])
def get_collection_points(include_inferred: bool = False):
    """Return exact map points by default. Inferred centroids require opt-in."""
    with get_db() as conn:
        c = conn.cursor()
        if include_inferred:
            c.execute("""
                SELECT
                    v.accession, v.virus_name,
                    h.scientific_name AS host_name,
                    vm.host_phylum,
                    sgp.country, sgp.latitude, sgp.longitude,
                    sgp.map_precision_class AS coordinate_precision,
                    sgp.default_map_eligible
                FROM submission_target_geography_precision sgp
                JOIN analysis_strict_target_isolates v ON v.isolate_id = sgp.isolate_id
                LEFT JOIN virus_master vm ON v.master_id = vm.master_id
                LEFT JOIN infection_records ir ON v.isolate_id = ir.isolate_id
                LEFT JOIN sample_collections s ON ir.collection_id = s.collection_id
                LEFT JOIN crustacean_hosts h ON ir.host_id = h.host_id
                WHERE sgp.latitude IS NOT NULL AND sgp.longitude IS NOT NULL
                LIMIT 1500
            """)
        else:
            c.execute("""
                SELECT
                    v.accession, v.virus_name,
                    h.scientific_name AS host_name,
                    vm.host_phylum,
                    sgp.country, sgp.latitude, sgp.longitude,
                    s.collection_year,
                    sgp.map_precision_class AS coordinate_precision,
                    sgp.default_map_eligible
                FROM submission_target_geography_precision sgp
                JOIN analysis_strict_target_isolates v ON v.isolate_id = sgp.isolate_id
                LEFT JOIN virus_master vm ON v.master_id = vm.master_id
                LEFT JOIN infection_records ir ON v.isolate_id = ir.isolate_id
                LEFT JOIN sample_collections s ON ir.collection_id = s.collection_id
                LEFT JOIN crustacean_hosts h ON ir.host_id = h.host_id
                WHERE sgp.default_map_eligible = 1
                  AND sgp.latitude IS NOT NULL AND sgp.longitude IS NOT NULL
                LIMIT 1500
            """)
        rows = [dict(r) for r in c.fetchall()]
    return rows


@app.get("/api/timeline", tags=["Core Data"])
def get_timeline(by_virus: bool = False):
    """API endpoint."""
    with get_db() as conn:
        c = conn.cursor()
        
        if not by_virus:
            # Simple total count per year
            c.execute("""
                SELECT s.collection_year as year, COUNT(*) as count
                FROM analysis_strict_target_isolates v
                LEFT JOIN infection_records ir ON v.isolate_id = ir.isolate_id
                LEFT JOIN sample_collections s ON ir.collection_id = s.collection_id
                WHERE s.collection_year IS NOT NULL AND s.collection_year != ''
                GROUP BY s.collection_year
                ORDER BY s.collection_year
            """)
            rows = [dict(r) for r in c.fetchall()]
            return rows
        
        # Multi-series: count per virus per year (top 8 viruses only to avoid clutter)
        c.execute("""
            SELECT s.collection_year as year, vm.canonical_name as virus_name, COUNT(*) as count
            FROM analysis_strict_target_isolates v
            JOIN virus_master vm ON v.master_id = vm.master_id
            LEFT JOIN infection_records ir ON v.isolate_id = ir.isolate_id
            LEFT JOIN sample_collections s ON ir.collection_id = s.collection_id
            WHERE s.collection_year IS NOT NULL AND s.collection_year != ''
              AND vm.host_phylum IN ('Arthropoda','Mollusca','Cnidaria','Echinodermata','Porifera')
              AND vm.entry_type NOT IN ('EST', 'patent', 'non_target')
              AND vm.canonical_name IN (
                  SELECT canonical_name FROM (
                      SELECT vm2.canonical_name, COUNT(*) as cnt
                      FROM analysis_strict_target_isolates v2
                      JOIN virus_master vm2 ON v2.master_id = vm2.master_id
                      WHERE vm2.host_phylum IN ('Arthropoda','Mollusca','Cnidaria','Echinodermata','Porifera')
                        AND vm2.entry_type NOT IN ('EST', 'patent', 'non_target')
                      GROUP BY vm2.canonical_name
                      ORDER BY cnt DESC
                      LIMIT 8
                  )
              )
            GROUP BY s.collection_year, vm.canonical_name
            ORDER BY s.collection_year
        """)
        rows = [dict(r) for r in c.fetchall()]
    return rows


@app.get("/api/top_viruses", tags=["Stats"])
def get_top_viruses(limit: int = 10, filter_noise: bool = True):
    """Return the most frequent virus names."""
    with get_db() as conn:
        c = conn.cursor()
        if filter_noise:
            c.execute("""
                SELECT vm.canonical_name as virus_name, COUNT(*) as count
                FROM analysis_strict_target_isolates v
                JOIN virus_master vm ON v.master_id = vm.master_id
                WHERE vm.host_phylum IN ('Arthropoda','Mollusca','Cnidaria','Echinodermata','Porifera') 
                  AND vm.entry_type NOT IN ('EST', 'patent', 'non_target', 'unknown')
                GROUP BY vm.canonical_name
                ORDER BY count DESC
                LIMIT ?
            """, (limit,))
        else:
            c.execute("""
                SELECT vm.canonical_name as virus_name, COUNT(*) as count
                FROM analysis_strict_target_isolates v
                JOIN virus_master vm ON v.master_id = vm.master_id
                GROUP BY vm.canonical_name
                ORDER BY count DESC
                LIMIT ?
            """, (limit,))
        rows = [dict(r) for r in c.fetchall()]
    return rows


@app.get("/api/top_hosts", tags=["Stats"])
def get_top_hosts(limit: int = 10):
    """Return the most frequent host names."""
    with get_db() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT h.scientific_name as host_name, h.common_name_cn, h.phylum AS host_phylum, COUNT(*) as count
            FROM crustacean_hosts h
            JOIN infection_records ir ON h.host_id = ir.host_id
            JOIN analysis_strict_target_isolates v ON ir.isolate_id = v.isolate_id
            GROUP BY h.host_id
            ORDER BY count DESC
            LIMIT ?
        """, (limit,))
        rows = [dict(r) for r in c.fetchall()]
    return rows


@app.get("/api/export", tags=["Downloads"])
def export_search(
    q: Optional[str] = Query(None),
    host: Optional[str] = Query(None),
    country: Optional[str] = Query(None),
    completeness: Optional[str] = Query(None),
    year_from: Optional[str] = Query(None),
    year_to: Optional[str] = Query(None),
):
    """API endpoint."""
    import csv
    import io
    from fastapi.responses import StreamingResponse

    with get_db() as conn:
        c = conn.cursor()

        where_sql, params = build_search_where(
            q=q, host=host, country=country, completeness=completeness,
            year_from=year_from, year_to=year_to, conn=conn
        )
    
        c.execute(f"""
            SELECT
                v.accession, v.virus_name, v.taxon_family, v.taxon_genus,
                v.genome_length, h.scientific_name as host_name, h.common_name_cn,
                s.country, s.collection_year,
                l.title as ref_title, l.pmid, l.doi
            FROM viral_isolates v
            LEFT JOIN virus_master vm ON v.master_id = vm.master_id
            LEFT JOIN infection_records ir ON v.isolate_id = ir.isolate_id
            LEFT JOIN crustacean_hosts h ON ir.host_id = h.host_id
            LEFT JOIN sample_collections s ON ir.collection_id = s.collection_id
            LEFT JOIN ref_literatures l ON v.reference_id = l.reference_id
            WHERE {where_sql}
            ORDER BY v.isolate_id
        """, params)
    
        rows = c.fetchall()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Accession", "VirusName", "Family", "Genus", "GenomeLength",
                     "Host", "HostCN", "Country", "Year", "ReferenceTitle",
                     "PMID", "DOI"])
    for r in rows:
        writer.writerow(r)

    output.seek(0)
    raw_filename = f"aquavir_export_{q or host or 'all'}.csv"
    # Sanitize filename: strip dangerous characters for HTTP header injection prevention
    safe_filename = re.sub(r'[^\w\-.]', '_', raw_filename)
    safe_filename = safe_filename.replace('\n', '_').replace('\r', '_').replace('\0', '_')
    safe_filename = safe_filename[:200]
    return StreamingResponse(
        io.BytesIO(output.getvalue().encode("utf-8-sig")),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={safe_filename}"}
    )


@app.get("/api/virulence", tags=["Core Data"])
def get_virulence_profiles():
    """Return manually reviewed virulence/pathogenicity evidence records."""
    with get_db() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT
                er.evidence_id,
                er.evidence_type,
                er.virus_master_id,
                er.host_id,
                er.isolate_id,
                er.reference_id,
                COALESCE(vm.canonical_name, vi.virus_name) AS virus_name,
                er.claim,
                er.value_text,
                er.value_numeric_min,
                er.value_numeric_max,
                er.value_numeric_min AS mortality_rate_min,
                er.value_numeric_max AS mortality_rate_max,
                er.unit,
                er.context,
                er.observation_type,
                er.evidence_strength,
                er.source_pmid,
                er.source_doi
            FROM analysis_reviewed_evidence_records er
            LEFT JOIN virus_master vm ON vm.master_id = er.virus_master_id
            LEFT JOIN viral_isolates vi ON vi.isolate_id = er.isolate_id
            WHERE er.evidence_type IN ('virulence','pathogenicity','mortality')
            ORDER BY er.evidence_strength DESC, er.evidence_id
        """)
        rows = [dict(r) for r in c.fetchall()]
    return rows


@app.get("/api/temperature", tags=["Core Data"])
def get_temperature_profiles():
    """Return manually reviewed temperature evidence records."""
    with get_db() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT
                er.evidence_id,
                er.evidence_type,
                er.virus_master_id,
                er.host_id,
                er.isolate_id,
                er.reference_id,
                COALESCE(vm.canonical_name, vi.virus_name) AS virus_name,
                er.claim,
                er.value_text,
                er.value_numeric_min,
                er.value_numeric_max,
                er.value_numeric_min AS optimal_temp_min,
                er.value_numeric_max AS optimal_temp_max,
                er.unit,
                er.context,
                er.observation_type,
                er.evidence_strength,
                er.source_pmid,
                er.source_doi
            FROM analysis_reviewed_evidence_records er
            LEFT JOIN virus_master vm ON vm.master_id = er.virus_master_id
            LEFT JOIN viral_isolates vi ON vi.isolate_id = er.isolate_id
            WHERE er.evidence_type IN ('temperature','thermal_stability','thermal_inactivation','temperature_range')
            ORDER BY er.evidence_strength DESC, er.evidence_id
        """)
        rows = [dict(r) for r in c.fetchall()]
    return rows


@app.get("/api/stats/genomes", tags=["Stats"])
def get_genome_stats():
    """Return genome summary distributions."""
    with get_db() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT
                CASE
                    WHEN gc_content < 30 THEN '<30%'
                    WHEN gc_content < 35 THEN '30-35%'
                    WHEN gc_content < 40 THEN '35-40%'
                    WHEN gc_content < 45 THEN '40-45%'
                    WHEN gc_content < 50 THEN '45-50%'
                    WHEN gc_content < 55 THEN '50-55%'
                    WHEN gc_content < 60 THEN '55-60%'
                    ELSE '>=60%'
                END as bucket,
                COUNT(*) as cnt
            FROM analysis_strict_target_isolates
            WHERE gc_content IS NOT NULL
            GROUP BY bucket
            ORDER BY MIN(gc_content)
        """)
        gc_distribution = [{"range": r[0], "count": r[1]} for r in c.fetchall()]

        c.execute("""
            SELECT
                CASE
                    WHEN genome_length < 1000 THEN '<1kb'
                    WHEN genome_length < 3000 THEN '1-3kb'
                    WHEN genome_length < 10000 THEN '3-10kb'
                    WHEN genome_length < 30000 THEN '10-30kb'
                    WHEN genome_length < 100000 THEN '30-100kb'
                    WHEN genome_length < 300000 THEN '100-300kb'
                    ELSE '>=300kb'
                END as bucket,
                COUNT(*) as cnt
            FROM analysis_strict_target_isolates
            WHERE genome_length IS NOT NULL
            GROUP BY bucket
            ORDER BY MIN(genome_length)
        """)
        length_distribution = [{"range": r[0], "count": r[1]} for r in c.fetchall()]

        c.execute("""
            SELECT completeness, COUNT(*) as cnt
            FROM analysis_strict_target_isolates
            GROUP BY completeness
            ORDER BY cnt DESC
        """)
        completeness_dist = [{"status": r[0] or "unknown", "count": r[1]} for r in c.fetchall()]
    return {
        "gc_distribution": gc_distribution,
        "length_distribution": length_distribution,
        "completeness_distribution": completeness_dist,
    }


@app.get("/api/phylogeny", tags=["Core Data"])
def get_phylogeny_tree():
    """Return a placeholder phylogeny response when no reviewed tree is available."""
    return {"tree": None, "newick": None, "taxa_count": 0, "status": "not_available"}


@app.get("/api/network", tags=["Core Data"])
def get_host_virus_network():
    """Return host-virus links from release-filtered strict-target records."""
    with get_db() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT
                vm.canonical_name as virus_name,
                h.scientific_name as host_name,
                h.common_name_cn as host_cn,
                COUNT(*) as count
            FROM analysis_strict_target_isolates v
            JOIN virus_master vm ON v.master_id = vm.master_id
            JOIN infection_records ir ON v.isolate_id = ir.isolate_id
            JOIN crustacean_hosts h ON ir.host_id = h.host_id
            WHERE vm.host_phylum IN ('Arthropoda','Mollusca','Cnidaria','Echinodermata','Porifera')
              AND vm.entry_type NOT IN ('EST', 'patent', 'non_target')
            GROUP BY vm.canonical_name, h.scientific_name
            ORDER BY count DESC
        """)
        rows = [dict(r) for r in c.fetchall()]
    return rows


@app.get("/api/download/{filename}", tags=["Downloads"])
def download_file(filename: str):
    """Download a generated public file."""
    file_path = _safe_public_download_path(filename)
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="Download file not found")
    return FileResponse(file_path, filename=file_path.name)


@app.get("/downloads/{path:path}", tags=["Downloads"])
def download_public_asset(path: str):
    """Backward-compatible public download route with an explicit allowlist."""
    file_path = _safe_public_download_path(path)
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="Download file not found")
    return FileResponse(file_path, filename=file_path.name)


# Corrupted legacy comment removed.
_PROVINCE_SUFFIXES = [
    "\u7701",
    "\u5e02",
    "\u58ee\u65cf\u81ea\u6cbb\u533a",
    "\u56de\u65cf\u81ea\u6cbb\u533a",
    "\u7ef4\u543e\u5c14\u81ea\u6cbb\u533a",
    "\u81ea\u6cbb\u533a",
    "\u7279\u522b\u884c\u653f\u533a",
]


def _normalize_province_name(raw: str, name_map: dict) -> str:
    """API endpoint."""
    if not raw or not raw.strip():
        return ""

    raw = raw.strip()

    # Corrupted legacy comment removed.
    mapped = name_map.get(raw)
    if mapped:
        return mapped

    # Corrupted legacy comment removed.
    # Corrupted legacy comment removed.
    has_chinese = any('\u4e00' <= ch <= '\u9fff' or '\u3400' <= ch <= '\u4dbf' for ch in raw)
    if has_chinese:
        result = raw
        for suffix in _PROVINCE_SUFFIXES:
            if result.endswith(suffix):
                result = result[:-len(suffix)]
                break
        return result

    # Corrupted legacy comment removed.
    return ""
@app.get("/api/stats/province", tags=["Stats"])
def get_stats_by_province(country: str = "China"):
    """Return province-level counts from release-filtered geography fields."""
    with get_db() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT s.province, COUNT(*) as count
            FROM analysis_strict_target_isolates v
            LEFT JOIN infection_records ir ON v.isolate_id = ir.isolate_id
            LEFT JOIN sample_collections s ON ir.collection_id = s.collection_id
            WHERE s.country = ? AND s.province IS NOT NULL AND s.province != ''
            GROUP BY s.province
            ORDER BY count DESC
        """, (country,))
        rows = c.fetchall()
    results = {}
    for row in rows:
        mapped = _normalize_province_name(row[0], {})
        if mapped:
            results[mapped] = results.get(mapped, 0) + row[1]
    data = [{"name": k, "count": v} for k, v in sorted(results.items(), key=lambda item: item[1], reverse=True)]
    return {"country": country, "data": data, "total_mapped": sum(r["count"] for r in data)}


@app.get("/api/stats_by_province", tags=["Stats"])
def get_stats_by_province_legacy(country: str = "China"):
    """Compatibility route used by the map template."""
    return get_stats_by_province(country=country)


@app.get("/api/families", tags=["Core Data"])
def get_families():
    """Return taxonomic families represented in strict target isolates."""
    with get_db() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT DISTINCT taxon_family
            FROM analysis_strict_target_isolates
            WHERE taxon_family IS NOT NULL AND taxon_family != ''
            ORDER BY taxon_family
        """)
        families = [r[0] for r in c.fetchall()]
    return {"families": families}


@app.get("/family/{family_name}", response_class=HTMLResponse, tags=["Pages"])
def family_page(request: Request, family_name: str):
    """Render family summary page."""
    return templates.TemplateResponse(request, "family.html", {
        "family_name": family_name,
        "active_page": "families",
    })


@app.get("/api/family/{family_name}", tags=["Core Data"])
def get_family_detail(family_name: str):
    """Return summary statistics for a family."""
    with get_db() as conn:
        c = conn.cursor()

        # Main stats
        c.execute("""
            SELECT COUNT(*) as isolate_count,
                   COUNT(DISTINCT v.master_id) as species_count,
                   COUNT(DISTINCT h.host_id) as host_count,
                   COUNT(DISTINCT s.country) as country_count,
                   MIN(s.collection_year) as min_year,
                   MAX(s.collection_year) as max_year,
                   ROUND(AVG(v.genome_length), 0) as avg_genome_length,
                   ROUND(AVG(v.gc_content), 1) as avg_gc_content
            FROM analysis_strict_target_isolates v
            LEFT JOIN infection_records ir ON v.isolate_id = ir.isolate_id
            LEFT JOIN crustacean_hosts h ON ir.host_id = h.host_id
            LEFT JOIN sample_collections s ON ir.collection_id = s.collection_id
            WHERE v.taxon_family = ?
        """, (family_name,))
        stats = dict(c.fetchone())

        # Top viruses
        c.execute("""
            SELECT vm.canonical_name as virus_name, COUNT(*) as count
            FROM analysis_strict_target_isolates v
            JOIN virus_master vm ON v.master_id = vm.master_id
            WHERE v.taxon_family = ?
            GROUP BY vm.master_id
            ORDER BY count DESC LIMIT 10
        """, (family_name,))
        top_viruses = [dict(r) for r in c.fetchall()]

        # ICTV mapped count
        c.execute("""
            SELECT COUNT(DISTINCT vim.master_id)
            FROM virus_ictv_mappings vim
            JOIN analysis_strict_target_isolates v ON v.master_id = vim.master_id
            WHERE v.taxon_family = ?
        """, (family_name,))
        ictv_mapped_count = c.fetchone()[0]

        # Top hosts
        c.execute("""
            SELECT h.scientific_name as host_name, h.phylum AS host_phylum, COUNT(*) as count
            FROM analysis_strict_target_isolates v
            JOIN infection_records ir ON v.isolate_id = ir.isolate_id
            JOIN crustacean_hosts h ON ir.host_id = h.host_id
            WHERE v.taxon_family = ?
            GROUP BY h.host_id
            ORDER BY count DESC LIMIT 10
        """, (family_name,))
        top_hosts = [dict(r) for r in c.fetchall()]

        # Genome types
        c.execute("""
            SELECT COALESCE(v.genome_type, 'unknown') as genome_type, COUNT(*) as count
            FROM analysis_strict_target_isolates v
            WHERE v.taxon_family = ?
            GROUP BY v.genome_type
            ORDER BY count DESC
        """, (family_name,))
        genome_types = [dict(r) for r in c.fetchall()]

        # Completeness
        c.execute("""
            SELECT COALESCE(v.completeness, 'unknown') as completeness, COUNT(*) as count
            FROM analysis_strict_target_isolates v
            WHERE v.taxon_family = ?
            GROUP BY v.completeness
            ORDER BY count DESC
        """, (family_name,))
        completeness = [dict(r) for r in c.fetchall()]

        # Timeline
        c.execute("""
            SELECT s.collection_year as year, COUNT(*) as count
            FROM analysis_strict_target_isolates v
            LEFT JOIN infection_records ir ON v.isolate_id = ir.isolate_id
            LEFT JOIN sample_collections s ON ir.collection_id = s.collection_id
            WHERE v.taxon_family = ? AND s.collection_year IS NOT NULL AND s.collection_year != ''
            GROUP BY s.collection_year
            ORDER BY s.collection_year
        """, (family_name,))
        timeline = [dict(r) for r in c.fetchall()]

        # Countries (top 15)
        c.execute("""
            SELECT s.country, COUNT(*) as count
            FROM analysis_strict_target_isolates v
            LEFT JOIN infection_records ir ON v.isolate_id = ir.isolate_id
            LEFT JOIN sample_collections s ON ir.collection_id = s.collection_id
            WHERE v.taxon_family = ? AND s.country IS NOT NULL AND s.country != ''
            GROUP BY s.country
            ORDER BY count DESC LIMIT 15
        """, (family_name,))
        countries = [dict(r) for r in c.fetchall()]

    return {
        "family": family_name,
        "stats": stats,
        "top_viruses": top_viruses,
        "ictv_mapped_count": ictv_mapped_count,
        "top_hosts": top_hosts,
        "genome_types": genome_types,
        "completeness": completeness,
        "timeline": timeline,
        "countries": countries,
    }


@app.get("/api/family/{family_name}/genome_structure", tags=["Core Data"])
def get_genome_structure(family_name: str):
    """Return genome protein coordinates for a family."""
    with get_db() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT v.accession, vp.protein_name, vp.functional_category,
                   vp.genome_start, vp.genome_end, vp.aa_length, v.genome_length, vp.is_rdrp
            FROM viral_proteins vp
            JOIN viral_isolates v ON vp.isolate_id = v.isolate_id
            WHERE v.taxon_family = ? AND vp.genome_start IS NOT NULL AND vp.genome_end IS NOT NULL
            ORDER BY v.genome_length DESC, v.accession, vp.genome_start
            LIMIT 200
        """, (family_name,))
        rows = c.fetchall()
    isolates = {}
    for acc, name, cat, start_pos, end_pos, aa_len, glen, is_rdrp in rows:
        isolates.setdefault(acc, {"accession": acc, "genome_length": glen or 0, "orfs": []})["orfs"].append({
            "name": name or "Unknown",
            "category": cat or "unknown",
            "start": start_pos or 0,
            "end": end_pos or 0,
            "aa_length": aa_len or 0,
            "is_rdrp": bool(is_rdrp),
        })
    return {"family": family_name, "isolates": sorted(isolates.values(), key=lambda x: -x["genome_length"])[:10]}


@app.get("/api/phylogeny/families", tags=["Core Data"])
def get_phylogeny_families():
    """Return families eligible for phylogeny display."""
    with get_db() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT taxon_family, COUNT(*) as seq_count
            FROM analysis_strict_target_isolates
            WHERE taxon_family IS NOT NULL AND taxon_family != ''
            GROUP BY taxon_family
            ORDER BY seq_count DESC
        """)
        families = [
            {"key": r[0], "display_name": r[0], "rep": r[0], "count": r[1], "type": "family", "has_figure": False}
            for r in c.fetchall()
        ]
    return {"families": families}


@app.get("/api/stats/completeness", tags=["Stats"])
def get_completeness_heatmap():
    """Return metadata completeness by family."""
    with get_db() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT taxon_family, COUNT(*) as total,
                   ROUND(100.0*SUM(CASE WHEN genome_length IS NOT NULL THEN 1 ELSE 0 END)/COUNT(*), 1) as genome_len_pct,
                   ROUND(100.0*SUM(CASE WHEN gc_content IS NOT NULL THEN 1 ELSE 0 END)/COUNT(*), 1) as gc_pct
            FROM analysis_strict_target_isolates
            WHERE taxon_family IS NOT NULL AND taxon_family != ''
            GROUP BY taxon_family
            ORDER BY total DESC
        """)
        rows = [dict(r) for r in c.fetchall()]
    return {"rows": rows}


@app.get("/api/stats/completeness_release", tags=["Stats"])
def get_release_completeness_heatmap():
    """Return release-quality metadata completeness based on analysis views."""
    dim_labels = ["Host", "Country", "Collection year", "Isolation source", "Genome type", "Reference", "Coordinates"]
    with get_db() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT COALESCE(aic.canonical_name, aic.virus_name, 'Unknown') AS family_label,
                   COUNT(*) AS total,
                   ROUND(100.0*SUM(has_host)/COUNT(*), 1) AS host_pct,
                   ROUND(100.0*SUM(has_country)/COUNT(*), 1) AS country_pct,
                   ROUND(100.0*SUM(has_collection_year)/COUNT(*), 1) AS year_pct,
                   ROUND(100.0*SUM(has_isolation_source)/COUNT(*), 1) AS source_pct,
                   ROUND(100.0*SUM(has_genome_type)/COUNT(*), 1) AS genome_type_pct,
                   ROUND(100.0*SUM(has_reference)/COUNT(*), 1) AS reference_pct,
                   ROUND(100.0*SUM(has_coordinates)/COUNT(*), 1) AS gps_pct
            FROM analysis_isolate_completeness aic
            WHERE aic.isolate_id IN (SELECT isolate_id FROM analysis_strict_target_isolates)
            GROUP BY COALESCE(aic.canonical_name, aic.virus_name, 'Unknown')
            HAVING COUNT(*) >= 4
            ORDER BY total DESC
        """)
        rows = c.fetchall()

    families = [row[0] for row in rows]
    heatmap_data = []
    for i, row in enumerate(rows):
        for j, pct in enumerate(row[2:9]):
            heatmap_data.append([j, i, pct if pct is not None else 0])
    return {
        "families": families,
        "dimensions": dim_labels,
        "data": heatmap_data,
        "max_total": max(r[1] for r in rows) if rows else 1,
    }


@app.get("/api/status", tags=["Stats"])
def get_api_status():
    """Return API/database status information."""
    from datetime import datetime
    db_update_date = ""
    data_update_date = ""
    database_size_mb = 0

    # Try to get the most recent timestamp from curation_logs
    with get_db() as conn:
        c = conn.cursor()
        try:
            c.execute("SELECT MAX(created_at) FROM curation_logs")
            row = c.fetchone()
            if row and row[0]:
                db_update_date = row[0]
        except sqlite3.Error:
            pass

        # Fallback: check sync_runtime
        if not db_update_date:
            try:
                c.execute("SELECT MAX(updated_at) FROM sync_runtime")
                row = c.fetchone()
                if row and row[0]:
                    db_update_date = row[0]
            except sqlite3.Error:
                pass

        data_update_date = db_update_date

        # File size
        db_path = str(DB_PATH)
        if os.path.exists(db_path):
            database_size_mb = round(os.path.getsize(db_path) / (1024 * 1024), 2)

    return {
        "db_update_date": db_update_date,
        "data_update_date": data_update_date,
        "database_size_mb": database_size_mb,
    }


@app.get("/", response_class=HTMLResponse, tags=["Pages"])
def serve_homepage(request: Request):
    """Render the database homepage."""
    return templates.TemplateResponse(request, "index.html", {"active_page": "home"})


@app.get("/viruses", response_class=HTMLResponse, tags=["Pages"])
def serve_viruses_browse(request: Request, page: int = 1, sort_by: str = "canonical_name",
                         sort_order: str = "asc", family: str = None):
    """Render virus browse page with filters."""
    valid_sort_cols = {"canonical_name", "virus_family", "genome_type", "host_phylum", "isolate_count", "host_count"}
    if sort_by not in valid_sort_cols:
        sort_by = "canonical_name"
    sort_order = "ASC" if sort_order == "asc" else "DESC"
    per_page = 50
    offset = (page - 1) * per_page

    with get_db() as conn:
        c = conn.cursor()
        # Get filter values from query params
        import urllib.parse
        qp = urllib.parse.parse_qs(str(request.query_params))
        selected_phyla = qp.get("phylum", [])
        selected_genome_types = qp.get("genome_type", [])
        selected_contexts = qp.get("discovery_context", [])
        selected_family = family or request.query_params.get("family", "")

        # Build WHERE clause
        where_clauses = ["vm.canonical_name IS NOT NULL"]
        params_ = []
        if selected_family:
            where_clauses.append("vm.virus_family = ?")
            params_.append(selected_family)
        if selected_phyla:
            placeholders = ",".join("?" * len(selected_phyla))
            where_clauses.append(f"vm.host_phylum IN ({placeholders})")
            params_.extend(selected_phyla)
        if selected_genome_types:
            placeholders = ",".join("?" * len(selected_genome_types))
            where_clauses.append(f"vm.genome_type IN ({placeholders})")
            params_.extend(selected_genome_types)
        if selected_contexts:
            placeholders = ",".join("?" * len(selected_contexts))
            where_clauses.append(f"vm.discovery_context IN ({placeholders})")
            params_.extend(selected_contexts)
        where_sql = " AND ".join(where_clauses)

        # Count total
        c.execute(f"SELECT COUNT(*) FROM virus_master vm WHERE {where_sql}", params_)
        total_count = c.fetchone()[0]

        # Fetch viruses
        c.execute(f"""
            SELECT vm.canonical_name, vm.chinese_name, vm.virus_family, vm.genome_type,
                   vm.host_phylum, vm.discovery_context,
                   COUNT(DISTINCT v.isolate_id) as isolate_count,
                   COUNT(DISTINCT ir.host_id) as host_count,
                   COUNT(DISTINCT er.evidence_id) as evidence_count
            FROM virus_master vm
            LEFT JOIN viral_isolates v ON vm.master_id = v.master_id
            LEFT JOIN infection_records ir ON v.isolate_id = ir.isolate_id
            LEFT JOIN evidence_records er ON vm.master_id = er.virus_master_id
            WHERE {where_sql}
            GROUP BY vm.master_id
            ORDER BY {sort_by} {sort_order}
            LIMIT ? OFFSET ?
        """, params_ + [per_page, offset])
        viruses = [dict(r) for r in c.fetchall()]

        # Filter options
        c.execute("SELECT host_phylum as name, COUNT(*) as count FROM virus_master WHERE host_phylum IS NOT NULL GROUP BY host_phylum ORDER BY count DESC")
        phyla = [dict(r) for r in c.fetchall()]
        c.execute("SELECT genome_type as name, COUNT(*) as count FROM virus_master WHERE genome_type IS NOT NULL AND genome_type != '' GROUP BY genome_type ORDER BY count DESC")
        genome_types = [dict(r) for r in c.fetchall()]
        c.execute("SELECT discovery_context as name, COUNT(*) as count FROM virus_master WHERE discovery_context IS NOT NULL GROUP BY discovery_context ORDER BY count DESC")
        discovery_contexts = [dict(r) for r in c.fetchall()]
        c.execute("SELECT virus_family as name, COUNT(*) as count FROM virus_master WHERE virus_family IS NOT NULL GROUP BY virus_family ORDER BY count DESC")
        families = [dict(r) for r in c.fetchall()]

        total_pages = max(1, (total_count + per_page - 1) // per_page)
        start_page = max(1, page - 3)
        end_page = min(total_pages, page + 3)
        page_range = list(range(start_page, end_page + 1))

        def url_for_page(p):
            params_ = dict(request.query_params)
            params_["page"] = str(p)
            return "/viruses?" + urllib.parse.urlencode(params_)

    return templates.TemplateResponse(request, "viruses.html", {
        "active_page": "viruses",
        "viruses": viruses,
        "total_count": total_count,
        "phyla": phyla,
        "genome_types": genome_types,
        "discovery_contexts": discovery_contexts,
        "families": families,
        "selected_phyla": selected_phyla,
        "selected_genome_types": selected_genome_types,
        "selected_contexts": selected_contexts,
        "selected_family": selected_family,
        "page": page,
        "total_pages": total_pages,
        "page_range": page_range,
        "sort_by": request.query_params.get("sort_by", "canonical_name"),
        "sort_order": request.query_params.get("sort_order", "asc"),
        "url_for_page": url_for_page,
    })


@app.get("/hosts", response_class=HTMLResponse, tags=["Pages"])
def serve_hosts_browse(request: Request):
    """Render host browse page with filters."""
    import urllib.parse
    qp = urllib.parse.parse_qs(str(request.query_params))
    selected_phyla = qp.get("phylum", [])
    selected_groups = qp.get("host_group", [])
    selected_aquaculture = qp.get("aquaculture", [])

    with get_db() as conn:
        c = conn.cursor()
        where_clauses = ["h.host_scope_status LIKE 'target%'"]
        params_ = []
        if selected_phyla:
            placeholders = ",".join("?" * len(selected_phyla))
            where_clauses.append(f"h.phylum IN ({placeholders})")
            params_.extend(selected_phyla)
        if selected_groups:
            placeholders = ",".join("?" * len(selected_groups))
            where_clauses.append(f"h.host_group IN ({placeholders})")
            params_.extend(selected_groups)
        if selected_aquaculture:
            placeholders = ",".join("?" * len(selected_aquaculture))
            where_clauses.append(f"h.aquaculture_status IN ({placeholders})")
            params_.extend(selected_aquaculture)
        where_sql = " AND ".join(where_clauses)

        c.execute(f"""
            SELECT h.host_id, h.scientific_name, h.common_name_cn, h.phylum, h.class,
                   h.host_group, h.habitat, h.aquaculture_status,
                   COUNT(DISTINCT ir.isolate_id) as virus_count
            FROM crustacean_hosts h
            LEFT JOIN infection_records ir ON h.host_id = ir.host_id
            WHERE {where_sql}
            GROUP BY h.host_id
            ORDER BY h.phylum, h.host_group, h.scientific_name
        """, params_)
        hosts = [dict(r) for r in c.fetchall()]

        c.execute("SELECT phylum as name, COUNT(*) as count FROM crustacean_hosts WHERE host_scope_status LIKE 'target%' AND phylum IS NOT NULL GROUP BY phylum ORDER BY count DESC")
        phyla = [dict(r) for r in c.fetchall()]
        c.execute("SELECT host_group as name, COUNT(*) as count FROM crustacean_hosts WHERE host_scope_status LIKE 'target%' AND host_group IS NOT NULL GROUP BY host_group ORDER BY count DESC")
        host_groups = [dict(r) for r in c.fetchall()]
        c.execute("SELECT aquaculture_status as name, COUNT(*) as count FROM crustacean_hosts WHERE host_scope_status LIKE 'target%' AND aquaculture_status IS NOT NULL GROUP BY aquaculture_status ORDER BY count DESC")
        aquaculture_statuses = [dict(r) for r in c.fetchall()]

    return templates.TemplateResponse(request, "hosts.html", {
        "active_page": "hosts",
        "hosts": hosts,
        "phyla": phyla,
        "host_groups": host_groups,
        "aquaculture_statuses": aquaculture_statuses,
        "selected_phyla": selected_phyla,
        "selected_groups": selected_groups,
        "selected_aquaculture": selected_aquaculture,
        "page": 1,
        "total_pages": 1,
        "page_range": [1],
        "url_for_page": lambda p: "/hosts",
    })


@app.get("/search", response_class=HTMLResponse, tags=["Pages"])
def serve_search(
    request: Request,
    q: Optional[str] = None,
    host: Optional[str] = None,
    family: Optional[str] = None,
    country: Optional[str] = None,
    completeness: Optional[str] = None,
    year_from: Optional[str] = None,
    year_to: Optional[str] = None,
    phylum: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    """Render the searchable isolate table."""
    with get_db() as conn:
        c = conn.cursor()

        where_sql, params = build_search_where(
            q=q, host=host, family=family, country=country,
            completeness=completeness, year_from=year_from, year_to=year_to,
            phylum=phylum, conn=conn,
        )
    
        # Count
        count_sql = f"""
            SELECT COUNT(*) FROM viral_isolates v
            LEFT JOIN virus_master vm ON v.master_id = vm.master_id
            LEFT JOIN infection_records ir ON v.isolate_id = ir.isolate_id
            LEFT JOIN crustacean_hosts h ON ir.host_id = h.host_id
            LEFT JOIN sample_collections s ON ir.collection_id = s.collection_id
            WHERE {where_sql}
        """
        c.execute(count_sql, params)
        total = c.fetchone()[0]
    
        # Data
        offset = (page - 1) * page_size
        data_sql = f"""
            SELECT
                v.isolate_id, v.accession, v.virus_name,
                vm.canonical_name, vm.chinese_name as canonical_name_cn, vm.abbreviations, vm.entry_type,
                vm.discovery_context, vm.host_phylum as virus_host_phylum,
                v.taxon_family, v.taxon_genus, v.genome_length,
                h.host_id, h.scientific_name AS host_name, h.common_name_cn AS host_cn,
                h.phylum AS host_phylum, h.class AS host_class, h.host_scope_status,
                ir.host_association_method,
                s.country, s.collection_year, s.collection_date, s.note AS isolation_source,
                l.title AS ref_title, l.pmid, l.doi,
                icp.dataset_tier
            FROM viral_isolates v
            LEFT JOIN virus_master vm ON v.master_id = vm.master_id
            LEFT JOIN infection_records ir ON v.isolate_id = ir.isolate_id
            LEFT JOIN crustacean_hosts h ON ir.host_id = h.host_id
            LEFT JOIN sample_collections s ON ir.collection_id = s.collection_id
            LEFT JOIN ref_literatures l ON v.reference_id = l.reference_id
            LEFT JOIN isolate_curated_profiles icp ON v.isolate_id = icp.isolate_id
            WHERE {where_sql}
            ORDER BY v.isolate_id
            LIMIT ? OFFSET ?
        """
        c.execute(data_sql, params + [page_size, offset])
        viruses = [dict(r) for r in c.fetchall()]
    
        # Countries for filter dropdown
        c.execute("""
            SELECT DISTINCT s.country FROM viral_isolates v
            LEFT JOIN infection_records ir ON v.isolate_id = ir.isolate_id
            LEFT JOIN sample_collections s ON ir.collection_id = s.collection_id
            WHERE s.country IS NOT NULL AND s.country != ''
            ORDER BY s.country
        """)
        countries = [r[0] for r in c.fetchall()]

        # Families for filter dropdown (dynamic, not hardcoded)
        c.execute("""
            SELECT DISTINCT v.taxon_family
            FROM analysis_strict_target_isolates v
            WHERE v.taxon_family IS NOT NULL AND v.taxon_family != ''
            ORDER BY v.taxon_family
        """)
        families = [r[0] for r in c.fetchall()]

    total_pages = (total + page_size - 1) // page_size
    context = {

        "active_page": "search",
        "query": q,
        "host": host,
        "family": family,
        "completeness": completeness,
        "country": country,
        "year_from": year_from,
        "year_to": year_to,
        "phylum": phylum,
        "page": page,
        "page_size": page_size,
        "total": total,
        "total_pages": total_pages,
        "viruses": viruses,
        "countries": countries,
        "families": families,
    }

    # HTMX partial render
    if request.headers.get("HX-Request") == "true":
        return templates.TemplateResponse(request, "components/search_results.html", context)
    return templates.TemplateResponse(request, "search.html", context)


@app.get("/virus/{accession}", response_class=HTMLResponse, tags=["Pages"])
def serve_virus_detail(request: Request, accession: str):
    """API endpoint."""
    with get_db() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT
                v.*, vm.canonical_name, vm.chinese_name as canonical_name_cn, vm.abbreviations, vm.entry_type, vm.virus_family,
                vm.discovery_context, vm.host_phylum as virus_host_phylum,
                h.scientific_name AS host_name, h.common_name_cn AS host_cn,
                h.phylum AS host_phylum, h.class AS host_class, h.host_scope_status,
                ir.host_association_method,
                s.country, s.province, s.city, s.latitude, s.longitude,
                s.collection_year, s.collection_date, s.note AS isolation_source,
                l.title AS ref_title, l.authors AS ref_authors, l.journal,
                l.year AS ref_year, l.doi, l.pmid, l.abstract,
                icp.dataset_tier
            FROM analysis_strict_target_isolates v
            LEFT JOIN virus_master vm ON v.master_id = vm.master_id
            LEFT JOIN infection_records ir ON v.isolate_id = ir.isolate_id
            LEFT JOIN crustacean_hosts h ON ir.host_id = h.host_id
            LEFT JOIN sample_collections s ON ir.collection_id = s.collection_id
            LEFT JOIN ref_literatures l ON v.reference_id = l.reference_id
            LEFT JOIN isolate_curated_profiles icp ON v.isolate_id = icp.isolate_id
            WHERE v.accession = ?
        """, (accession,))
        row = c.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Accession not found")
        virus = dict(row)
        master_id = virus.get("master_id")
        if master_id is None:
            raise HTTPException(status_code=404, detail="Virus master record not found")
        virus_name = virus.get("canonical_name") or virus.get("virus_name", "")
    
        # Sequence check
        seq_file = SEQUENCES_DIR / f"{accession}.fasta"
        has_sequence = seq_file.exists()
    
        # Virulence: reviewed evidence only.
        c.execute("""
            SELECT
                evidence_id, evidence_type, claim, value_text,
                value_numeric_min, value_numeric_max, unit, context,
                observation_type, evidence_strength, source_pmid, source_doi
            FROM analysis_reviewed_evidence_records
            WHERE evidence_type IN ('virulence','pathogenicity','mortality')
              AND (isolate_id = ? OR virus_master_id = ?)
            ORDER BY evidence_strength DESC, evidence_id
            LIMIT 10
        """, (virus.get("isolate_id"), master_id))
        virulence_rows = [dict(r) for r in c.fetchall()]
        virulence = {"_source": "reviewed_evidence", "records": virulence_rows} if virulence_rows else None

        # Temperature: reviewed evidence only.
        c.execute("""
            SELECT
                evidence_id, evidence_type, claim, value_text,
                value_numeric_min, value_numeric_max, unit, context,
                observation_type, evidence_strength, source_pmid, source_doi
            FROM analysis_reviewed_evidence_records
            WHERE evidence_type IN ('temperature','thermal_stability','thermal_inactivation','temperature_range')
              AND (isolate_id = ? OR virus_master_id = ?)
            ORDER BY evidence_strength DESC, evidence_id
            LIMIT 10
        """, (virus.get("isolate_id"), master_id))
        temperature_rows = [dict(r) for r in c.fetchall()]
        temperature = {"_source": "reviewed_evidence", "records": temperature_rows} if temperature_rows else None

        # Hosts (via master_id)
        c.execute("""
            SELECT DISTINCT h.host_id, h.scientific_name, h.common_name_cn, h.taxon_order, h.taxon_family,
                h.phylum, h.class, h.host_scope_status, ir.host_association_method
            FROM crustacean_hosts h
            JOIN infection_records ir ON h.host_id = ir.host_id
            JOIN analysis_strict_target_isolates v ON ir.isolate_id = v.isolate_id
            WHERE v.master_id = ?
            ORDER BY h.scientific_name
        """, (master_id,))
        hosts = [dict(r) for r in c.fetchall()]
    
        # Isolates for this master (fallback to curated profiles if sample_collections missing)
        c.execute("""
            SELECT 
                v.accession, v.genome_length, v.gc_content, v.completeness,
                COALESCE(NULLIF(s.country, ''), icp.country) as country,
                COALESCE(NULLIF(s.collection_year, ''), icp.collection_year) as collection_year
            FROM analysis_strict_target_isolates v
            LEFT JOIN infection_records ir ON v.isolate_id = ir.isolate_id
            LEFT JOIN sample_collections s ON ir.collection_id = s.collection_id
            LEFT JOIN isolate_curated_profiles icp ON v.isolate_id = icp.isolate_id
            WHERE v.master_id = ?
            ORDER BY v.accession
        """, (master_id,))
        isolates = [dict(r) for r in c.fetchall()]
    
        # Counts
        c.execute("SELECT COUNT(*) FROM analysis_strict_target_isolates WHERE master_id = ?", (master_id,))
        isolate_count = c.fetchone()[0]
        c.execute("SELECT COUNT(DISTINCT host_id) FROM infection_records WHERE isolate_id IN (SELECT isolate_id FROM analysis_strict_target_isolates WHERE master_id = ?)", (master_id,))
        host_count = c.fetchone()[0]
    
        # Protein count
        c.execute("SELECT COUNT(*) FROM viral_proteins WHERE isolate_id = ?", (virus.get("isolate_id"),))
        protein_count = c.fetchone()[0]
    
        # Corrupted legacy comment removed.
        # Diagnostic methods for this virus (curated only)
        # Corrupted legacy comment removed.
        c.execute("SELECT method_category FROM diagnostic_methods WHERE method_category IS NOT NULL LIMIT 1")
        _sample_category = c.fetchone()
        _test_cat = _sample_category[0] if _sample_category else None
        _is_rebuilt = _test_cat in ('nucleic_acid_amplification', 'immunoassay', 'nucleic_acid_hybridization', 'sequencing', 'crispr_cas', 'other')
        _primary_field = _safe_sql_identifier(
            'method_category' if _is_rebuilt else 'method_subcategory',
            {"method_category", "method_subcategory"},
        )
        _secondary_field = _safe_sql_identifier(
            'method_subcategory' if _is_rebuilt else 'method_category',
            {"method_category", "method_subcategory"},
        )
        c.execute(f"""
            SELECT method_name, {_primary_field}, {_secondary_field}, target_gene_or_region,
                   sample_type, field_deployable, visual_readout, detection_limit, evidence_strength
            FROM diagnostic_methods
            WHERE virus_master_id = ? AND data_quality = 'curated'
            ORDER BY {_primary_field}, method_name
        """, (master_id,))
        _raw_methods = c.fetchall()
        diagnostic_methods = []
        for r in _raw_methods:
            dm = dict(r)
            dm["primary_category"] = dm.pop(_primary_field)
            dm["secondary_category"] = dm.pop(_secondary_field)
            dm["primary_cn"] = DIAGNOSTIC_CATEGORY_CN.get(dm["primary_category"], dm["primary_category"])
            dm["secondary_cn"] = DIAGNOSTIC_CATEGORY_CN.get(dm["secondary_category"], dm["secondary_category"])
            diagnostic_methods.append(dm)
    
        # Control/management methods for this virus
        c.execute("""
            SELECT method_name, method_category, vaccine_type, effect_summary, validation_context, evidence_strength
            FROM control_management_methods
            WHERE virus_master_id = ?
              AND curation_status = 'manual_checked'
            ORDER BY method_category, method_name
        """, (master_id,))
        control_methods = [dict(r) for r in c.fetchall()]
    
        # ICTV mapping info
        ictv_mapped = None
        ictv_family_refs = []
        ictv_family_link = None
        
        c.execute("""
            SELECT it.species, it.genus, it.family, it.msl_version, vim.match_status, vim.confidence
            FROM virus_ictv_mappings vim
            JOIN ictv_taxonomy it ON vim.ictv_id = it.ictv_id
            WHERE vim.master_id = ?
              AND vim.confidence = 'high'
              AND vim.match_status <> 'rejected'
        """, (master_id,))
        ictv_rows = c.fetchall()
        if ictv_rows:
            ictv_mapped = [dict(zip(["species", "genus", "family", "msl_version", "match_status", "confidence"], r)) for r in ictv_rows]
            # Corrupted legacy comment removed.
            confidences = {m['confidence'] for m in ictv_mapped if m['confidence']}
            if 'high' in confidences:
                ictv_confidence_label = ('High confidence', 'bg-green-100 text-green-700')
            elif 'medium' in confidences:
                ictv_confidence_label = ('Medium confidence', 'bg-blue-100 text-blue-700')
            elif 'low' in confidences:
                ictv_confidence_label = ('Low confidence', 'bg-amber-100 text-amber-700')
            else:
                ictv_confidence_label = ('Mapped', 'bg-teal-100 text-teal-700')
        else:
            ictv_confidence_label = None
        
        # ICTV family reference species (if family in ICTV but no species mapping)
        db_family = virus.get("virus_family")
        if db_family:
            c.execute("SELECT family FROM ictv_taxonomy WHERE family = ? LIMIT 1", (db_family,))
            if c.fetchone():
                ictv_family_link = db_family
                # If no species mapping, show top reference species in same family
                if not ictv_mapped:
                    c.execute("""
                        SELECT species, genus FROM ictv_taxonomy 
                        WHERE family = ? AND species IS NOT NULL
                        ORDER BY species
                        LIMIT 5
                    """, (db_family,))
                    ictv_family_refs = [dict(zip(["species", "genus"], r)) for r in c.fetchall()]

        # Phylogeny check
        family_lower = (virus.get("virus_family") or "").lower()
        has_phylogeny = (DOWNLOADS_DIR / "phylogeny" / "figures" / f"{family_lower}_tree.png").exists()

        # Pathogenicity evidence (from dedicated table)
        pathogenicity_rows = []
        try:
            c.execute("""
                SELECT virulence_level, mortality_rate_min, mortality_rate_max,
                       disease_symptoms, tissue_tropism, evidence_strength, host_species
                FROM pathogenicity_evidence
                WHERE virus_master_id = ?
                ORDER BY evidence_strength DESC
                LIMIT 5
            """, (master_id,))
            pathogenicity_rows = [dict(r) for r in c.fetchall()]
        except sqlite3.Error:
            pass

        # Outbreak events
        outbreak_events = []
        try:
            c.execute("""
                SELECT country, province_state, start_year, end_year, event_summary,
                       economic_impact, mortality_rate_min, mortality_rate_max, evidence_strength
                FROM outbreak_events
                WHERE virus_master_id = ?
                ORDER BY start_year DESC
                LIMIT 10
            """, (master_id,))
            outbreak_events = [dict(r) for r in c.fetchall()]
        except sqlite3.Error:
            pass

        # Literature count for this virus
        literature_count = 0
        try:
            c.execute("""
                SELECT COUNT(DISTINCT er.reference_id)
                FROM evidence_records er
                WHERE er.virus_master_id = ?
            """, (master_id,))
            literature_count = c.fetchone()[0] or 0
        except sqlite3.Error:
            pass

        # Geography: countries with distinct isolate evidence
        virus_geo = []
        try:
            c.execute("""
                SELECT s.country, COUNT(DISTINCT v.isolate_id) as cnt
                FROM sample_collections s
                JOIN infection_records ir ON s.collection_id = ir.collection_id
                JOIN analysis_strict_target_isolates v ON ir.isolate_id = v.isolate_id
                WHERE v.master_id = ? AND s.country IS NOT NULL AND s.country != ''
                GROUP BY s.country
                ORDER BY cnt DESC
            """, (master_id,))
            virus_geo = [dict(r) for r in c.fetchall()]
        except sqlite3.Error:
            pass


    return templates.TemplateResponse(request, "virus_detail.html", {
        "active_page": "virus_detail",
        "virus": virus,
        "has_sequence": has_sequence,
        "virulence": virulence,
        "temperature": temperature,
        "hosts": hosts,
        "isolates": isolates,
        "isolate_count": isolate_count,
        "host_count": host_count,
        "protein_count": protein_count,
        "has_phylogeny": has_phylogeny,
        "family_lower": family_lower,
        "diagnostic_methods": diagnostic_methods,
        "control_methods": control_methods,
        "ictv_mapped": ictv_mapped,
        "ictv_family_refs": ictv_family_refs,
        "ictv_family_link": ictv_family_link,
        "ictv_confidence_label": ictv_confidence_label,
        "pathogenicity": pathogenicity_rows,
        "outbreak_events": outbreak_events,
        "literature_count": literature_count,
        "virus_geo": virus_geo,
    })


@app.get("/stats", response_class=HTMLResponse, tags=["Pages"])
def serve_stats(request: Request):
    """Render the statistics page."""
    return templates.TemplateResponse(request, "stats.html", {"active_page": "stats"})


@app.get("/map", response_class=HTMLResponse, tags=["Pages"])
def serve_map(request: Request):
    """Render the geographic map page."""
    return templates.TemplateResponse(request, "map.html", {"active_page": "map"})


@app.get("/network", response_class=HTMLResponse, tags=["Pages"])
def serve_network(request: Request):
    """Render the host-virus network page."""
    return templates.TemplateResponse(request, "network.html", {"active_page": "network"})


@app.get("/phylogeny", response_class=HTMLResponse, tags=["Pages"])
def serve_phylogeny(request: Request):
    """Render the phylogeny page."""
    return templates.TemplateResponse(request, "phylogeny.html", {"active_page": "phylogeny"})


@app.get("/rdrp", response_class=HTMLResponse, tags=["Pages"])
def serve_rdrp(request: Request):
    """Render the RDRP page."""
    return templates.TemplateResponse(request, "rdrp.html", {"active_page": "rdrp"})


@app.get("/download", response_class=HTMLResponse, tags=["Pages"])
def serve_download(request: Request):
    """Render the download page."""
    enrichment_total = 0
    with get_db() as conn:
        c = conn.cursor()
        for table in [
            "interpro_annotations", "kegg_annotations", "kegg_pathways", "string_interactions",
            "gbif_occurrences", "geo_datasets", "pride_datasets", "europe_pmc_annotations",
            "biorxiv_preprints", "viralzone_families", "host_ecological_traits"
        ]:
            try:
                table = _safe_sql_identifier(table, {
                    "interpro_annotations", "kegg_annotations", "kegg_pathways", "string_interactions",
                    "gbif_occurrences", "geo_datasets", "pride_datasets", "europe_pmc_annotations",
                    "biorxiv_preprints", "viralzone_families", "host_ecological_traits",
                })
                c.execute(f"SELECT COUNT(*) FROM {table}")
                enrichment_total += c.fetchone()[0] or 0
            except sqlite3.Error:
                continue
    return templates.TemplateResponse(request, "download.html", {
        "active_page": "download",
        "enrichment_total": enrichment_total,
    })


@app.get("/host/{host_id}", response_class=HTMLResponse, tags=["Pages"])
def serve_host_detail(request: Request, host_id: int):
    """Render host detail page."""
    with get_db() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT h.*, htp.accepted_name, htp.lineage, htp.lineage_phylum, htp.lineage_class,
                   htp.lineage_order, htp.lineage_family as ncbi_family, htp.ncbi_taxid
            FROM crustacean_hosts h
            LEFT JOIN host_taxonomy_profiles htp ON h.host_id = htp.host_id
            WHERE h.host_id = ?
        """, (host_id,))
        host = c.fetchone()
        if not host:
            return templates.TemplateResponse(request, "error.html", {
                "detail": f"Host ID {host_id} was not found",
                "status_code": 404
            }, status_code=404)
        host = dict(host)
        c.execute("""
            SELECT vm.canonical_name as virus_name, vm.virus_family,
                   vm.chinese_name, COUNT(DISTINCT v.isolate_id) as isolate_count
            FROM viral_isolates v
            JOIN virus_master vm ON v.master_id = vm.master_id
            JOIN infection_records ir ON v.isolate_id = ir.isolate_id
            WHERE ir.host_id = ? AND vm.host_phylum IN ('Arthropoda','Mollusca','Cnidaria','Echinodermata','Porifera')
            GROUP BY vm.master_id
            ORDER BY isolate_count DESC
        """, (host_id,))
        viruses = [dict(r) for r in c.fetchall()]
        c.execute("""
            SELECT COUNT(*) as total_records, COUNT(DISTINCT v.isolate_id) as unique_isolates,
                   COUNT(DISTINCT v.master_id) as unique_viruses
            FROM infection_records ir
            JOIN analysis_strict_target_isolates v ON ir.isolate_id = v.isolate_id
            WHERE ir.host_id = ?
        """, (host_id,))
        inf_stats = dict(c.fetchone())
        c.execute("""
            SELECT s.country, COUNT(DISTINCT v.isolate_id) as count
            FROM sample_collections s
            JOIN infection_records ir ON s.collection_id = ir.collection_id
            JOIN analysis_strict_target_isolates v ON ir.isolate_id = v.isolate_id
            WHERE ir.host_id = ? AND s.country IS NOT NULL AND s.country != ''
            GROUP BY s.country
            ORDER BY count DESC
        """, (host_id,))
        geo_dist = [dict(r) for r in c.fetchall()]
        try:
            c.execute("SELECT COUNT(*) FROM gbif_occurrences WHERE host_id = ?", (host_id,))
            gbif_count = c.fetchone()[0]
        except sqlite3.Error:
            gbif_count = 0
        try:
            c.execute("SELECT COUNT(*) FROM obis_occurrences WHERE host_id = ?", (host_id,))
            obis_count = c.fetchone()[0]
        except sqlite3.Error:
            obis_count = 0
        host_biology = []
        try:
            c.execute("SELECT * FROM host_biology_profiles WHERE host_id = ? LIMIT 1", (host_id,))
            row = c.fetchone()
            if row:
                host_biology = dict(row)
        except sqlite3.Error:
            pass
        host_ecology = []
        try:
            c.execute("SELECT * FROM host_ecological_traits WHERE host_id = ? LIMIT 15", (host_id,))
            host_ecology = [dict(r) for r in c.fetchall()]
        except sqlite3.Error:
            pass
    return templates.TemplateResponse(request, "host_detail.html", {
        "active_page": "host_detail",
        "host": host,
        "viruses": viruses,
        "infection_stats": inf_stats,
        "geo_distribution": geo_dist,
        "gbif_count": gbif_count,
        "obis_count": obis_count,
        "host_biology": host_biology,
        "host_ecology": host_ecology,
    })


# ============================================================
# External Data Source API Endpoints (Tier 1-3 Enrichments)
# ============================================================

def _get_db():
    """Return a raw DB connection (SQLite or PostgreSQL, auto-detected).

    Callers MUST close the connection (try/finally pattern).
    """
    return get_raw_db_connection(read_only=True)


def _mark_source_index(row: sqlite3.Row | dict, scope: str = "source_index_not_manual_reviewed") -> dict:
    data = dict(row)
    data.setdefault("curation_scope", scope)
    data.setdefault("source_status", "source-derived; not manual-reviewed evidence")
    data.setdefault("publication_use", "contextual_index_not_primary_claim")
    return data


@app.get("/api/enrichment/status", tags=["Enrichment"])
def get_enrichment_status():
    """Get source-derived enrichment index counts across external sources."""
    conn = _get_db()
    try:
        status = {
            "uniprot": conn.execute("SELECT COUNT(*) FROM uniprot_annotations").fetchone()[0],
            "kegg": conn.execute("SELECT COUNT(*) FROM kegg_annotations").fetchone()[0],
            "kegg_pathways": conn.execute("SELECT COUNT(*) FROM kegg_pathways").fetchone()[0],
            "viralzone": conn.execute("SELECT COUNT(*) FROM viralzone_families").fetchone()[0],
            "interpro": conn.execute("SELECT COUNT(*) FROM interpro_annotations").fetchone()[0],
            "geo_datasets": conn.execute("SELECT COUNT(*) FROM geo_datasets").fetchone()[0],
            "sra_runs": conn.execute("SELECT COUNT(*) FROM sra_runs").fetchone()[0],
            "gbif_occurrences": conn.execute("SELECT COUNT(*) FROM gbif_occurrences").fetchone()[0],
            "gbif_summaries": conn.execute("SELECT COUNT(*) FROM gbif_species_summary").fetchone()[0],
            "europe_pmc": conn.execute("SELECT COUNT(*) FROM epmc_literature").fetchone()[0],
            "europe_pmc_preprints": conn.execute("SELECT COUNT(*) FROM epmc_preprints").fetchone()[0],
            "alphafold": conn.execute("SELECT COUNT(*) FROM uniprot_structures WHERE source='alphafold'").fetchone()[0],
            "pdb": conn.execute("SELECT COUNT(*) FROM uniprot_structures WHERE source='pdb'").fetchone()[0],
            "string": conn.execute("SELECT COUNT(*) FROM string_interactions").fetchone()[0],
            "pride": conn.execute("SELECT COUNT(*) FROM pride_datasets").fetchone()[0],
            "biorxiv": conn.execute("SELECT COUNT(*) FROM biorxiv_preprints").fetchone()[0],
            "obis": conn.execute("SELECT COUNT(*) FROM obis_occurrences").fetchone()[0],
            "host_traits": conn.execute("SELECT COUNT(*) FROM host_ecological_traits").fetchone()[0],
            "host_biology": conn.execute("SELECT COUNT(*) FROM host_biology_profiles").fetchone()[0],
        }
        total = sum(int(v) for v in status.values())
        status["total_enrichment_records"] = total
        status["curation_scope"] = "source_index_not_manual_reviewed"
        status["source_status"] = "counts include source-derived indexes; not manual-reviewed evidence"
        return {"status": "success", "data": status}
    finally:
        conn.close()


@app.get("/api/enrichment/kegg", tags=["Enrichment"])
def get_kegg_annotations(protein_id: int = None, ec_number: str = None, limit: int = Query(100, ge=1, le=5000)):
    """Get source-derived KEGG annotations for strict-release viral proteins."""
    conn = _get_db()
    try:
        if protein_id:
            rows = conn.execute(
                """
                SELECT ka.*
                FROM kegg_annotations ka
                JOIN viral_proteins vp ON vp.protein_id = ka.protein_id
                WHERE ka.protein_id = ?
                  AND vp.isolate_id IN (SELECT isolate_id FROM analysis_strict_target_isolates)
                LIMIT ?
                """,
                (protein_id, limit)).fetchall()
        elif ec_number:
            rows = conn.execute(
                """
                SELECT ka.*
                FROM kegg_annotations ka
                JOIN viral_proteins vp ON vp.protein_id = ka.protein_id
                WHERE ka.ec_number = ?
                  AND vp.isolate_id IN (SELECT isolate_id FROM analysis_strict_target_isolates)
                LIMIT ?
                """,
                (ec_number, limit)).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT ka.*
                FROM kegg_annotations ka
                JOIN viral_proteins vp ON vp.protein_id = ka.protein_id
                WHERE ka.ko_id IS NOT NULL
                  AND vp.isolate_id IN (SELECT isolate_id FROM analysis_strict_target_isolates)
                LIMIT ?
                """,
                (limit,)).fetchall()
        return {"status": "success", "count": len(rows), "data": [_mark_source_index(r) for r in rows]}
    finally:
        conn.close()


@app.get("/api/enrichment/kegg/pathways", tags=["Enrichment"])
def get_kegg_pathways(limit: int = Query(500, ge=1, le=5000)):
    """Get source-derived KEGG pathway index with KO counts."""
    conn = _get_db()
    try:
        rows = conn.execute(
            "SELECT * FROM kegg_pathways ORDER BY ko_count DESC LIMIT ?",
            (limit,)).fetchall()
        return {"status": "success", "count": len(rows), "data": [_mark_source_index(r) for r in rows]}
    finally:
        conn.close()


@app.get("/api/enrichment/viralzone", tags=["Enrichment"])
def get_viralzone_families(family_name: str = None):
    """Get ViralZone family factsheets."""
    conn = _get_db()
    try:
        if family_name:
            rows = conn.execute(
                """
                SELECT family_id, family_name, virion_description, genome_description,
                       genome_type, genome_size_range, replication_cycle, host_range,
                       transmission, taxonomy_lineage, genera_list, reference_strains,
                       viralzone_url
                FROM viralzone_families
                WHERE family_name LIKE ? ESCAPE '\\'
                """,
                (f"%{_escape_like(family_name)}%",)).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT family_id, family_name, virion_description, genome_description,
                       genome_type, genome_size_range, replication_cycle, host_range,
                       transmission, taxonomy_lineage, genera_list, reference_strains,
                       viralzone_url
                FROM viralzone_families
                """
            ).fetchall()
        return {"status": "success", "count": len(rows), "data": [_mark_source_index(r) for r in rows]}
    finally:
        conn.close()


@app.get("/api/enrichment/interpro", tags=["Enrichment"])
def get_interpro_annotations(uniprot_id: str = None, limit: int = Query(100, ge=1, le=5000)):
    """Get source-derived InterPro domain annotations."""
    conn = _get_db()
    try:
        if uniprot_id:
            rows = conn.execute(
                """
                SELECT *,
                       CASE
                           WHEN start_pos IS NOT NULL AND end_pos IS NOT NULL THEN 'positioned'
                           ELSE 'entry_level_only'
                       END AS coordinate_status,
                       CASE
                           WHEN start_pos IS NOT NULL AND end_pos IS NOT NULL
                           THEN 'domain_presence_and_position'
                           ELSE 'domain_presence_only_no_visualization'
                       END AS publication_use
                FROM interpro_annotations
                WHERE uniprot_id = ?
                LIMIT ?
                """,
                (uniprot_id, limit)).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT *,
                       CASE
                           WHEN start_pos IS NOT NULL AND end_pos IS NOT NULL THEN 'positioned'
                           ELSE 'entry_level_only'
                       END AS coordinate_status,
                       CASE
                           WHEN start_pos IS NOT NULL AND end_pos IS NOT NULL
                           THEN 'domain_presence_and_position'
                           ELSE 'domain_presence_only_no_visualization'
                       END AS publication_use
                FROM interpro_annotations
                WHERE interpro_id != ''
                ORDER BY COALESCE(score, -1) DESC, interpro_id
                LIMIT ?
                """,
                (limit,)).fetchall()
        return {"status": "success", "count": len(rows), "data": [_mark_source_index(r, "source_domain_index_not_manual_reviewed") for r in rows]}
    finally:
        conn.close()


@app.get("/api/enrichment/geo-sra", tags=["Enrichment"])
def get_geo_sra_datasets(virus_name: str = None, limit: int = Query(50, ge=1, le=1000)):
    """Get GEO/SRA transcriptomics datasets."""
    conn = _get_db()
    try:
        if virus_name:
            geo_rows = conn.execute(
                """
                SELECT geo_id, gse_accession, title, summary, organism,
                       experiment_type, platform, sample_count, pubmed_ids,
                       submission_date, gds_type, virus_species_matched,
                       host_species_matched
                FROM geo_datasets
                WHERE virus_species_matched LIKE ? ESCAPE '\\'
                LIMIT ?
                """,
                (f"%{_escape_like(virus_name)}%", limit)).fetchall()
            sra_rows = conn.execute(
                """
                SELECT sra_id, sra_accession, bioproject, biosample, title,
                       organism, library_strategy, library_source, library_layout,
                       platform, total_bases, total_spots, run_date, geo_linked,
                       virus_species_matched
                FROM sra_runs
                WHERE virus_species_matched LIKE ? ESCAPE '\\'
                LIMIT ?
                """,
                (f"%{_escape_like(virus_name)}%", limit)).fetchall()
        else:
            geo_rows = conn.execute(
                """
                SELECT geo_id, gse_accession, title, summary, organism,
                       experiment_type, platform, sample_count, pubmed_ids,
                       submission_date, gds_type, virus_species_matched,
                       host_species_matched
                FROM geo_datasets
                ORDER BY submission_date DESC
                LIMIT ?
                """,
                (limit,)).fetchall()
            sra_rows = conn.execute(
                """
                SELECT sra_id, sra_accession, bioproject, biosample, title,
                       organism, library_strategy, library_source, library_layout,
                       platform, total_bases, total_spots, run_date, geo_linked,
                       virus_species_matched
                FROM sra_runs
                ORDER BY run_date DESC
                LIMIT ?
                """,
                (limit,)).fetchall()
        return {
            "status": "success",
            "geo": {"count": len(geo_rows), "data": [_mark_source_index(r) for r in geo_rows]},
            "sra": {"count": len(sra_rows), "data": [_mark_source_index(r) for r in sra_rows]},
        }
    finally:
        conn.close()


@app.get("/api/enrichment/gbif", tags=["Enrichment"])
def get_gbif_occurrences(host_name: str = None, limit: int = Query(200, ge=1, le=5000)):
    """Get source-derived GBIF host occurrence context for strict-release hosts."""
    conn = _get_db()
    try:
        if host_name:
            rows = conn.execute(
                """
                SELECT go.*
                FROM gbif_occurrences go
                WHERE go.scientific_name LIKE ? ESCAPE '\\'
                  AND go.host_id IN (
                      SELECT DISTINCT ir.host_id
                      FROM infection_records ir
                      WHERE ir.isolate_id IN (SELECT isolate_id FROM analysis_strict_target_isolates)
                        AND ir.host_id IS NOT NULL
                  )
                LIMIT ?
                """,
                (f"%{_escape_like(host_name)}%", limit)).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT go.*
                FROM gbif_occurrences go
                WHERE go.host_id IN (
                    SELECT DISTINCT ir.host_id
                    FROM infection_records ir
                    WHERE ir.isolate_id IN (SELECT isolate_id FROM analysis_strict_target_isolates)
                      AND ir.host_id IS NOT NULL
                )
                LIMIT ?
                """,
                (limit,)).fetchall()
        return {"status": "success", "count": len(rows), "data": [_mark_source_index(r, "host_occurrence_context_not_virus_evidence") for r in rows]}
    finally:
        conn.close()


@app.get("/api/enrichment/europe-pmc", tags=["Enrichment"])
def get_europe_pmc_literature(pmid: str = None, match_status: str = None, limit: int = Query(100, ge=1, le=5000)):
    """Get Europe PMC enriched literature."""
    conn = _get_db()
    try:
        query = """
            SELECT epmc_id, pmid, pmcid, doi, title, authors, journal, year,
                   source, publication_type, citation_count, relative_citation_ratio,
                   is_open_access, has_full_text, mesh_terms, keywords,
                   local_reference_id
            FROM epmc_literature
            WHERE 1=1
        """
        params = []
        if pmid:
            query += " AND pmid = ?"
            params.append(pmid)
        if match_status:
            query += " AND match_status = ?"
            params.append(match_status)
        query += " ORDER BY citation_count DESC LIMIT ?"
        params.append(limit)
        rows = conn.execute(query, params).fetchall()
        return {"status": "success", "count": len(rows), "data": [_mark_source_index(r) for r in rows]}
    finally:
        conn.close()


@app.get("/api/enrichment/pride", tags=["Enrichment"])
def get_pride_datasets(virus_name: str = None, limit: int = Query(50, ge=1, le=1000)):
    """Get PRIDE proteomics datasets."""
    conn = _get_db()
    try:
        if virus_name:
            rows = conn.execute(
                """
                SELECT pride_id, pride_accession, px_accession, title, description,
                       organism, instrument, modification, num_proteins, num_peptides,
                       num_psms, publication_pmid, publication_doi, submission_date,
                       virus_species_matched, host_species_matched, source_repository
                FROM pride_datasets
                WHERE virus_species_matched LIKE ? ESCAPE '\\'
                LIMIT ?
                """,
                (f"%{_escape_like(virus_name)}%", limit)).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT pride_id, pride_accession, px_accession, title, description,
                       organism, instrument, modification, num_proteins, num_peptides,
                       num_psms, publication_pmid, publication_doi, submission_date,
                       virus_species_matched, host_species_matched, source_repository
                FROM pride_datasets
                ORDER BY submission_date DESC
                LIMIT ?
                """,
                (limit,)).fetchall()
        return {"status": "success", "count": len(rows), "data": [dict(r) for r in rows]}
    finally:
        conn.close()


# ============================================================
# Async Structure Prediction Task Queue
# ============================================================
_predict_tasks: dict[str, dict] = {}
_predict_lock = threading.Lock()

ESMFOLD_API = "https://api.esmatlas.com/foldSequence/v1/pdb/"


def _run_esmfold_predict(task_id: str, sequence: str, seq_length: int) -> None:
    """Background worker: call ESMFold API and store result"""
    try:
        resp = requests.post(
            ESMFOLD_API,
            data=sequence,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=180,
        )
        resp.raise_for_status()
        pdb_content = resp.text

        if not pdb_content or len(pdb_content) < 100:
            with _predict_lock:
                _predict_tasks[task_id]["status"] = "failed"
                _predict_tasks[task_id]["error"] = "ESMFold returned empty/invalid PDB"
            return

        # Parse pLDDT
        plddt_values = []
        for line in pdb_content.splitlines():
            if line.startswith("ATOM") and line[13:15].strip() == "CA":
                try:
                    plddt_values.append(float(line[60:66].strip()))
                except ValueError:
                    pass
        avg_plddt = round(sum(plddt_values) / len(plddt_values), 1) if plddt_values else None

        # Save PDB file
        STRUCTURES_DIR = APP_DIR / "downloads" / "structures"
        STRUCTURES_DIR.mkdir(parents=True, exist_ok=True)
        pdb_path = STRUCTURES_DIR / f"predict_{task_id}.pdb"
        pdb_path.write_text(pdb_content, encoding="utf-8")

        with _predict_lock:
            _predict_tasks[task_id]["status"] = "completed"
            _predict_tasks[task_id]["result"] = {
                "pdb_available": True,
                "plddt_score": avg_plddt,
                "sequence_length": seq_length,
                "source": "esmfold",
                "pdb_size_bytes": len(pdb_content),
            }

    except Exception as e:
        with _predict_lock:
            _predict_tasks[task_id]["status"] = "failed"
            _predict_tasks[task_id]["error"] = str(e)[:500]


@app.get("/api/protein/{protein_id}/structure", tags=["Proteins"])
def get_protein_structure(protein_id: int):
    """
    Retrieve 3D structure data for a specific protein.

    Queries UniProt-derived structures (AlphaFold DB, PDB) and locally
    predicted structures (ESMFold).  Also finds structures linked via
    sequence clusters (viral_proteins_nr).  Returns the best structure
    (highest pLDDT) alongside all available structures grouped by source.

    Parameters
    ----------
    protein_id : int
        Internal protein ID (primary key of viral_proteins).

    Raises 404 if the protein is not found.

    Example:
        GET /api/protein/42/structure
        -> {"status": "success", "protein_id": 42, "uniprot_structures": [...], ...}
    """
    conn = _get_db()
    conn.row_factory = sqlite3.Row
    try:
        protein = conn.execute(
            "SELECT * FROM viral_proteins WHERE protein_id = ?", (protein_id,)
        ).fetchone()
        if not protein:
            raise HTTPException(status_code=404, detail="Protein not found")

        protein = dict(protein)

        # Corrupted legacy comment removed.
        uniprot_structures = []
        for upl in conn.execute(
            "SELECT uniprot_id FROM uniprot_protein_links WHERE protein_id = ?",
            (protein_id,),
        ).fetchall():
            for us in conn.execute(
                """
                SELECT struct_id, uniprot_id, source, entry_id, confidence,
                       sequence_length, pdb_url, gene, protein_description,
                       organism, protein_id
                FROM uniprot_structures
                WHERE uniprot_id = ?
                """,
                (upl["uniprot_id"],),
            ).fetchall():
                uniprot_structures.append(dict(us))

        # Corrupted legacy comment removed.
        local_structures = [
            dict(s) for s in conn.execute(
                """
                SELECT structure_id, cluster_id, protein_id, reanno_id,
                       prediction_method, model_version, plddt_score,
                       sequence_length, prediction_date, api_source
                FROM protein_structures
                WHERE protein_id = ? AND plddt_score IS NOT NULL
                """,
                (protein_id,),
            ).fetchall()
        ]

        # Corrupted legacy comment removed.
        cluster_structures = []
        for vpnr in conn.execute(
            "SELECT cluster_id FROM viral_proteins_nr WHERE protein_id = ?",
            (protein_id,),
        ).fetchall():
            for ps in conn.execute(
                """
                SELECT structure_id, cluster_id, protein_id, reanno_id,
                       prediction_method, model_version, plddt_score,
                       sequence_length, prediction_date, api_source
                FROM protein_structures
                WHERE cluster_id = ? AND protein_id IS NULL
                """,
                (vpnr["cluster_id"],),
            ).fetchall():
                cluster_structures.append(dict(ps))

        # Corrupted legacy comment removed.
        best_structure = None
        best_plddt = -1
        for s in uniprot_structures:
            if s.get("confidence") and s["confidence"] > best_plddt:
                best_plddt = s["confidence"]
                best_structure = {"source": s["source"], "plddt": s["confidence"],
                                  "pdb_url": s.get("pdb_url"), "entry_id": s.get("entry_id")}
        for s in local_structures:
            if s.get("plddt_score") and s["plddt_score"] > best_plddt:
                best_plddt = s["plddt_score"]
                best_structure = {"source": "esmfold", "plddt": s["plddt_score"],
                                  "structure_id": s.get("structure_id")}

        return {
            "status": "success",
            "protein_id": protein_id,
            "protein_name": protein.get("protein_name", ""),
            "gene_symbol": protein.get("gene_symbol", ""),
            "aa_length": protein.get("aa_length"),
            "uniprot_structures": uniprot_structures,
            "local_structures": local_structures,
            "cluster_structures": cluster_structures,
            "best_structure": best_structure,
            "total_structures": len(uniprot_structures) + len(local_structures) + len(cluster_structures),
        }
    finally:
        conn.close()


@app.post("/api/structure/predict", tags=["Proteins"])
def predict_structure(
    request: Request,
    sequence: str = Body(..., embed=True),
    sequence_id: str = Body("", embed=True),
    api_key: str = Depends(require_api_key),
):
    """
    Submit a protein sequence for ESMFold structure prediction.

    The prediction runs asynchronously in a background thread.
    Poll GET /api/structure/predict/{task_id} for results.

    Parameters
    ----------
    sequence : str
        Amino-acid sequence (one-letter code) to predict.
    sequence_id : str
        Optional identifier for the sequence (e.g. "VP28_WSSV").

    Example:
        POST /api/structure/predict
        {"sequence": "MGRV...", "sequence_id": "test"}
        -> {"status": "queued", "task_id": "550e8400-...", "message": "..."}
    """
    # Rate limit: 30-second global cooldown (ESMFold is extremely expensive)
    with _structure_predict_lock2:
        now = time.time()
        elapsed = now - _last_structure_predict_time
        if _last_structure_predict_time > 0 and elapsed < STRUCTURE_PREDICT_COOLDOWN_SECONDS:
            remaining = int(STRUCTURE_PREDICT_COOLDOWN_SECONDS - elapsed)
            raise HTTPException(
                status_code=429,
                detail=f"Structure prediction rate limited. Please wait {remaining} seconds before submitting another prediction."
            )
        _last_structure_predict_time = now

    clean_sequence = normalize_protein_sequence(sequence).replace("*", "")
    if len(clean_sequence) < 20:
        raise HTTPException(status_code=400, detail="Protein sequence must contain at least 20 amino acids")
    if len(clean_sequence) > 1000:
        raise HTTPException(status_code=413, detail="Protein sequence is too long for interactive prediction; maximum is 1000 aa")

    valid_aa = set("ACDEFGHIKLMNPQRSTVWY")
    invalid = sorted(set(clean_sequence) - valid_aa)
    if invalid:
        raise HTTPException(status_code=400, detail=f"Unsupported amino-acid code(s): {''.join(invalid)}")

    with _predict_lock:
        active_tasks = sum(1 for task in _predict_tasks.values() if task.get("status") in {"queued", "running"})
        if active_tasks >= 2:
            raise HTTPException(status_code=503, detail="Structure prediction queue is full; try again later")
        task_id = str(uuid.uuid4())
        _predict_tasks[task_id] = {
            "status": "queued",
            "created_at": time.time(),
            "sequence_id": (sequence_id or "").strip()[:120],
            "sequence_length": len(clean_sequence),
        }

    thread = threading.Thread(
        target=_run_esmfold_predict,
        args=(task_id, clean_sequence, len(clean_sequence)),
        daemon=True,
    )
    thread.start()
    return {
        "status": "queued",
        "task_id": task_id,
        "sequence_length": len(clean_sequence),
        "message": "Prediction submitted. Poll /api/structure/predict/{task_id}.",
    }
@app.get("/api/structure/predict/{task_id}", tags=["Proteins"])
def get_structure_prediction_status(task_id: str):
    """Return the status of an async ESMFold structure prediction task."""
    with _predict_lock:
        task = _predict_tasks.get(task_id)

    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    elapsed = time.time() - task["created_at"]
    return {
        "task_id": task_id,
        "status": task["status"],
        "elapsed_seconds": round(elapsed, 1),
        "sequence_length": task.get("sequence_length"),
        "result": task.get("result"),
        "error": task.get("error"),
    }


@app.get("/api/structure/pdb/{structure_id}", tags=["Downloads"])
def get_structure_pdb(structure_id: int, type: str = "esmfold"):
    """
    Retrieve raw PDB file content for the 3D viewer.

    Fetches the PDB data for either an ESMFold prediction or an
    AlphaFold / PDB structure by its internal ID.

    Parameters
    ----------
    structure_id : int
        Internal structure record ID.
    type : str
        Structure source type: "esmfold" (default) or "alphafold".

    Returns the PDB content as a JSON-wrapped string, or detail if
    the file is available locally.

    Example:
        GET /api/structure/pdb/5?type=esmfold
        -> {"status": "success", "structure_id": 5, "pdb_content": "ATOM ..."}
    """
    conn = _get_db()
    conn.row_factory = sqlite3.Row
    try:
        if type == "alphafold":
            # Corrupted legacy comment removed.
            row = conn.execute(
                "SELECT * FROM uniprot_structures WHERE struct_id = ? AND source = 'alphafold'",
                (structure_id,),
            ).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="AlphaFold structure not found")
            row = dict(row)

            # Corrupted legacy comment removed.
            local_path = row.get("local_pdb_path", "")
            if local_path:
                resolved = Path(local_path).resolve()
                allowed_dirs = [DOWNLOADS_DIR.resolve(), APP_DIR.resolve()]
                # Use os.sep suffix to prevent prefix-bypass (e.g. /app/downloads_backup matching /app/downloads)
                if not any(str(resolved) == str(d) or str(resolved).startswith(str(d) + os.sep) for d in allowed_dirs):
                    raise HTTPException(status_code=403, detail="Access denied: invalid PDB path")
                if resolved.exists():
                    pdb_content = resolved.read_text(encoding="utf-8")
                    return {
                        "status": "success",
                        "structure_id": structure_id,
                        "type": "alphafold",
                        "uniprot_id": row.get("uniprot_id"),
                        "plddt_score": row.get("confidence"),
                        "prediction_method": "alphafold_v2",
                        "pdb_content": pdb_content,
                    }
            return {
                "status": "success",
                "structure_id": structure_id,
                "type": "alphafold",
                "plddt_score": row.get("confidence"),
                "pdb_url": row.get("pdb_url", ""),
                "pdb_content": None,
                "message": "PDB file not available. Download first with download_alphafold_pdb.py",
            }
        else:
            # Corrupted legacy comment removed.
            row = conn.execute(
                "SELECT * FROM protein_structures WHERE structure_id = ?",
                (structure_id,),
            ).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Structure not found")

            row = dict(row)
            pdb_path = row.get("pdb_file_path", "")
            if pdb_path:
                resolved = Path(pdb_path).resolve()
                allowed_dirs = [DOWNLOADS_DIR.resolve(), APP_DIR.resolve()]
                # Use os.sep suffix to prevent prefix-bypass
                if not any(str(resolved) == str(d) or str(resolved).startswith(str(d) + os.sep) for d in allowed_dirs):
                    raise HTTPException(status_code=403, detail="Access denied: invalid PDB path")
                if resolved.exists():
                    pdb_content = resolved.read_text(encoding="utf-8")
                    return {
                        "status": "success",
                        "structure_id": structure_id,
                        "type": "esmfold",
                        "plddt_score": row.get("plddt_score"),
                        "prediction_method": row.get("prediction_method"),
                        "pdb_content": pdb_content,
                    }
            return {
                    "status": "success",
                    "structure_id": structure_id,
                    "type": "esmfold",
                    "plddt_score": row.get("plddt_score"),
                    "pdb_url": row.get("pdb_url", ""),
                    "pdb_content": None,
                    "message": "PDB file not available locally",
                }
    finally:
        conn.close()


@app.get("/api/structure/stats", tags=["Stats"])
def get_structure_stats():
    """
    Return protein structure coverage statistics.

    Provides counts of total proteins, AlphaFold structures,
    ESMFold predictions, proteins with any structure, coverage
    percentage, and the pLDDT distribution for ESMFold models
    (very_high >= 90, high 70-90, medium 50-70, low < 50).

    Example:
        GET /api/structure/stats
        -> {"status": "success", "total_proteins": 4520, ...}
    """
    conn = _get_db()
    try:
        total_proteins = conn.execute("SELECT COUNT(*) FROM viral_proteins").fetchone()[0]
        af_count = conn.execute(
            "SELECT COUNT(DISTINCT uniprot_id) FROM uniprot_structures WHERE source='alphafold'"
        ).fetchone()[0]
        esm_count = conn.execute(
            "SELECT COUNT(*) FROM protein_structures WHERE prediction_method='esmfold'"
        ).fetchone()[0]
        proteins_with_structure = conn.execute("""
            SELECT COUNT(DISTINCT protein_id) FROM (
                SELECT protein_id FROM uniprot_structures WHERE protein_id IS NOT NULL
                UNION
                SELECT protein_id FROM protein_structures WHERE protein_id IS NOT NULL
            )
        """).fetchone()[0]

        # Normalize ESMFold pLDDT to the standard 0-100 scale. Older rows in
        # this database stored ESMFold pLDDT on a 0-1 scale.
        plddt_dist = conn.execute("""
            SELECT
                SUM(CASE WHEN plddt_100 >= 90 THEN 1 ELSE 0 END) as very_high,
                SUM(CASE WHEN plddt_100 >= 70 AND plddt_100 < 90 THEN 1 ELSE 0 END) as high,
                SUM(CASE WHEN plddt_100 >= 50 AND plddt_100 < 70 THEN 1 ELSE 0 END) as medium,
                SUM(CASE WHEN plddt_100 < 50 THEN 1 ELSE 0 END) as low
            FROM (
                SELECT CASE
                    WHEN plddt_score IS NULL THEN NULL
                    WHEN plddt_score <= 1.0 THEN plddt_score * 100.0
                    ELSE plddt_score
                END AS plddt_100
                FROM protein_structures
                WHERE prediction_method = 'esmfold'
            )
        """).fetchone()

        return {
            "status": "success",
            "total_proteins": total_proteins,
            "alphafold_count": af_count,
            "esmfold_count": esm_count,
            "proteins_with_structure": proteins_with_structure,
            "coverage_pct": round(proteins_with_structure / total_proteins * 100, 1) if total_proteins > 0 else 0,
            "esmfold_plddt_distribution": {
                "very_high": plddt_dist[0] or 0,
                "high": plddt_dist[1] or 0,
                "medium": plddt_dist[2] or 0,
                "low": plddt_dist[3] or 0,
            } if plddt_dist else {},
        }
    finally:
        conn.close()


@app.get("/api/enrichment/alphafold", tags=["Enrichment"])
def get_alphafold_structures(uniprot_id: str = None, min_confidence: float = None, limit: int = Query(100, ge=1, le=5000),
                            source: str = None):
    """Get predicted protein structures (AlphaFold DB + ESMFold via protein_structures)."""
    conn = _get_db()
    conn.row_factory = sqlite3.Row
    try:
        rows = []

        # Query AlphaFold DB structures
        if not source or source == 'alphafold':
            af_query = """
                SELECT struct_id, uniprot_id, source, entry_id, confidence,
                       sequence_length, pdb_url, gene, protein_description,
                       organism, protein_id
                FROM uniprot_structures
                WHERE source = 'alphafold'
            """
            af_params = []
            if uniprot_id:
                af_query += " AND uniprot_id = ?"
                af_params.append(uniprot_id)
            if min_confidence:
                af_query += " AND confidence >= ?"
                af_params.append(min_confidence)
            af_query += " ORDER BY confidence DESC LIMIT ?"
            af_params.append(limit)
            for r in conn.execute(af_query, af_params).fetchall():
                d = dict(r)
                d["_type"] = "alphafold"
                d["_display_id"] = d["uniprot_id"]
                d["_confidence"] = d.get("confidence")
                d["curation_scope"] = "source_structure_index_not_manual_reviewed"
                d["source_status"] = "AlphaFold/PDB source-derived structure index"
                d["publication_use"] = "contextual_structure_index_not_primary_claim"
                rows.append(d)

        # Query ESMFold structures from protein_structures
        if not source or source == 'esmfold':
            esm_query = """
                SELECT ps.structure_id, ps.cluster_id, ps.protein_id, ps.reanno_id,
                       ps.prediction_method, ps.model_version, ps.plddt_score,
                       CASE
                           WHEN ps.plddt_score IS NULL THEN NULL
                           WHEN ps.plddt_score <= 1.0 THEN ps.plddt_score * 100.0
                           ELSE ps.plddt_score
                       END AS plddt_normalized_100,
                       CASE
                           WHEN ps.plddt_score IS NULL THEN 'unknown'
                           WHEN ps.plddt_score <= 1.0 THEN '0-1'
                           ELSE '0-100'
                       END AS plddt_scale,
                       ps.sequence_length, ps.prediction_date, ps.api_source,
                       upl.uniprot_id
                FROM protein_structures ps
                LEFT JOIN viral_proteins_nr vpnr ON ps.cluster_id = vpnr.cluster_id
                LEFT JOIN uniprot_protein_links upl ON vpnr.protein_id = upl.protein_id
                WHERE ps.prediction_method = 'esmfold'
            """
            esm_params = []
            if uniprot_id:
                esm_query += " AND upl.uniprot_id = ?"
                esm_params.append(uniprot_id)
            if min_confidence:
                esm_query += """
                    AND CASE
                        WHEN ps.plddt_score IS NULL THEN NULL
                        WHEN ps.plddt_score <= 1.0 THEN ps.plddt_score * 100.0
                        ELSE ps.plddt_score
                    END >= ?
                """
                esm_params.append(min_confidence)
            esm_query += """
                ORDER BY CASE
                    WHEN ps.plddt_score IS NULL THEN NULL
                    WHEN ps.plddt_score <= 1.0 THEN ps.plddt_score * 100.0
                    ELSE ps.plddt_score
                END DESC
                LIMIT ?
            """
            esm_params.append(limit)
            for r in conn.execute(esm_query, esm_params).fetchall():
                d = dict(r)
                d["_type"] = "esmfold"
                d["_display_id"] = d.get("uniprot_id") or f"cluster_{d.get('cluster_id', '?')}"
                d["_confidence"] = d.get("plddt_normalized_100")
                d["plddt_raw"] = d.get("plddt_score")
                d["source"] = "esmfold"
                d["entry_id"] = str(d.get("structure_id", ""))
                d["curation_scope"] = "source_structure_index_not_manual_reviewed"
                d["source_status"] = "ESMFold source-derived structure index"
                d["publication_use"] = d.get("publication_use") or "contextual_structure_index_not_primary_claim"
                rows.append(d)

        # Sort all results by confidence
        rows.sort(key=lambda x: x.get("_confidence") or 0, reverse=True)
        rows = rows[:limit]

        return {"status": "success", "count": len(rows), "data": rows}
    finally:
        conn.close()


@app.get("/api/enrichment/string", tags=["Enrichment"])
def get_string_interactions(protein: str = None, min_score: int = 500, limit: int = Query(100, ge=1, le=5000)):
    """Get STRING protein interaction data."""
    conn = _get_db()
    try:
        query = "SELECT * FROM string_interactions WHERE combined_score >= ?"
        params = [min_score]
        if protein:
            query += " AND (protein_a = ? OR protein_b = ?)"
            params.extend([protein, protein])
        query += " ORDER BY combined_score DESC LIMIT ?"
        params.append(limit)
        rows = conn.execute(query, params).fetchall()
        return {"status": "success", "count": len(rows), "data": [_mark_source_index(r) for r in rows]}
    finally:
        conn.close()


@app.get("/api/enrichment/biorxiv", tags=["Enrichment"])
def get_biorxiv_preprints(relevant_only: bool = False, limit: int = Query(100, ge=1, le=5000)):
    """Get bioRxiv/medRxiv preprints."""
    conn = _get_db()
    try:
        if relevant_only:
            rows = conn.execute(
                """
                SELECT preprint_id, doi, title, authors, abstract, date_posted,
                       date_revised, server, category, collection, version,
                       published_doi, published_journal, local_virus_names,
                       local_host_names, relevant
                FROM biorxiv_preprints
                WHERE relevant = 1
                """
                "ORDER BY date_posted DESC LIMIT ?",
                (limit,)).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT preprint_id, doi, title, authors, abstract, date_posted,
                       date_revised, server, category, collection, version,
                       published_doi, published_journal, local_virus_names,
                       local_host_names, relevant
                FROM biorxiv_preprints
                ORDER BY date_posted DESC LIMIT ?
                """,
                (limit,)).fetchall()
        return {"status": "success", "count": len(rows), "data": [_mark_source_index(r) for r in rows]}
    finally:
        conn.close()


@app.get("/api/enrichment/host-ecology", tags=["Enrichment"])
def get_host_ecology(scientific_name: str = None, limit: int = Query(100, ge=1, le=5000)):
    """Get host species ecological traits and biology profiles."""
    conn = _get_db()
    try:
        if scientific_name:
            traits = conn.execute(
                "SELECT * FROM host_ecological_traits WHERE scientific_name LIKE ? ESCAPE '\\' LIMIT ?",
                (f"%{_escape_like(scientific_name)}%", limit)).fetchall()
            profiles = conn.execute(
                "SELECT * FROM host_biology_profiles WHERE scientific_name LIKE ? ESCAPE '\\' LIMIT ?",
                (f"%{_escape_like(scientific_name)}%", limit)).fetchall()
        else:
            traits = conn.execute(
                "SELECT * FROM host_ecological_traits LIMIT ?", (limit,)).fetchall()
            profiles = conn.execute(
                "SELECT * FROM host_biology_profiles LIMIT ?", (limit,)).fetchall()
        return {
            "status": "success",
            "traits": {"count": len(traits), "data": [_mark_source_index(r, "host_ecology_context_not_virus_evidence") for r in traits]},
            "profiles": {"count": len(profiles), "data": [_mark_source_index(r, "host_ecology_context_not_virus_evidence") for r in profiles]},
        }
    finally:
        conn.close()


# ============================================================
# Enrichment HTML Page Routes
# ============================================================

@app.get("/enrichment", response_class=HTMLResponse, tags=["Pages"])
def serve_enrichment_hub(request: Request):
    """API endpoint."""
    return templates.TemplateResponse(request, "enrichment.html", {"active_page": "enrichment"})


@app.get("/enrichment/domains", response_class=HTMLResponse, tags=["Pages"])
def serve_domains_page(request: Request):
    """API endpoint."""
    return templates.TemplateResponse(request, "domains.html", {"active_page": "enrichment"})


@app.get("/enrichment/structures", response_class=HTMLResponse, tags=["Pages"])
def serve_structures_page(request: Request):
    """Render protein structure enrichment page."""
    return templates.TemplateResponse(request, "structures.html", {"active_page": "enrichment"})


@app.get("/enrichment/ppi", response_class=HTMLResponse, tags=["Pages"])
def serve_ppi_page(request: Request):
    """API endpoint."""
    return templates.TemplateResponse(request, "ppi_network.html", {"active_page": "enrichment"})


@app.get("/enrichment/literature", response_class=HTMLResponse, tags=["Pages"])
def serve_literature_page(request: Request):
    """API endpoint."""
    return templates.TemplateResponse(request, "literature.html", {"active_page": "enrichment"})


@app.get("/enrichment/pride", response_class=HTMLResponse, tags=["Pages"])
def serve_pride_page(request: Request):
    """API endpoint."""
    return templates.TemplateResponse(request, "pride.html", {"active_page": "enrichment"})


@app.get("/enrichment/preprints", response_class=HTMLResponse, tags=["Pages"])
def serve_preprints_page(request: Request):
    """API endpoint."""
    return templates.TemplateResponse(request, "literature.html", {"active_page": "enrichment"})


@app.get("/enrichment/kegg", response_class=HTMLResponse, tags=["Pages"])
def serve_kegg_page(request: Request):
    """Render KEGG pathway enrichment page."""
    return templates.TemplateResponse(request, "kegg.html", {"active_page": "enrichment"})


@app.get("/enrichment/geo-sra", response_class=HTMLResponse, tags=["Pages"])
def serve_geo_sra_page(request: Request):
    """Render GEO/SRA datasets enrichment page."""
    return templates.TemplateResponse(request, "geo_sra.html", {"active_page": "enrichment"})


@app.get("/enrichment/host-ecology", response_class=HTMLResponse, tags=["Pages"])
def serve_host_ecology_page(request: Request):
    """Render host ecology enrichment page."""
    return templates.TemplateResponse(request, "host_ecology.html", {"active_page": "enrichment"})


@app.get("/enrichment/viralzone", response_class=HTMLResponse, tags=["Pages"])
def serve_viralzone_page(request: Request):
    """Render ViralZone enrichment page."""
    return templates.TemplateResponse(request, "viralzone.html", {"active_page": "enrichment"})


@app.get("/about", response_class=HTMLResponse, tags=["Pages"])
def serve_about(request: Request):
    """Render about page."""
    return templates.TemplateResponse(request, "about.html", {"active_page": "about"})


@app.get("/help", response_class=HTMLResponse, tags=["Pages"])
def serve_help(request: Request):
    """Render help/tutorial page."""
    return templates.TemplateResponse(request, "help.html", {"active_page": "help"})


@app.get("/browse/taxonomy", response_class=HTMLResponse, tags=["Pages"])
def serve_taxonomy(request: Request):
    """Render taxonomy browser page."""
    with get_db() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT vm.host_phylum, vm.virus_family, COUNT(DISTINCT vm.master_id) as virus_count
            FROM virus_master vm
            WHERE vm.host_phylum IS NOT NULL
            GROUP BY vm.host_phylum, vm.virus_family
            ORDER BY vm.host_phylum, virus_count DESC
        """)
        rows = c.fetchall()
        tree = {}
        for r in rows:
            phylum = r[0] or 'Unknown'
            family = r[1] or 'Unclassified'
            count = r[2]
            if phylum not in tree:
                tree[phylum] = {"families": {}, "total": 0}
            tree[phylum]["families"][family] = count
            tree[phylum]["total"] += count
    phylum_labels = {
        'Arthropoda': '节肢动物 (Arthropoda)',
        'Mollusca': '软体动物 (Mollusca)',
        'Cnidaria': '刺胞动物 (Cnidaria)',
        'Echinodermata': '棘皮动物 (Echinodermata)',
        'Porifera': '海绵动物 (Porifera)',
        'Annelida': '环节动物 (Annelida)',
    }
    return templates.TemplateResponse(request, "taxonomy.html", {
        "active_page": "taxonomy",
        "tree": tree,
        "phylum_labels": phylum_labels,
    })


@app.get("/compare", response_class=HTMLResponse, tags=["Pages"])
def serve_compare(request: Request, v: str = ""):
    """Render virus comparison page."""
    viruses_data = []
    if v:
        names = [n.strip() for n in v.split(",") if n.strip()][:4]
        if names:
            with get_db() as conn:
                c = conn.cursor()
                placeholders = ",".join("?" * len(names))
                c.execute(f"""
                    SELECT vm.canonical_name, vm.chinese_name, vm.virus_family, vm.virus_genus,
                           vm.genome_type, vm.host_phylum, vm.discovery_context,
                           COUNT(DISTINCT vi.isolate_id) as isolate_count,
                           MAX(vi.genome_length) as genome_length
                    FROM virus_master vm
                    LEFT JOIN viral_isolates vi ON vm.master_id = vi.master_id
                    WHERE vm.canonical_name IN ({placeholders})
                       OR vm.abbreviations IN ({placeholders})
                    GROUP BY vm.master_id
                    LIMIT 4
                """, names * 2)
                viruses_data = [dict(r) for r in c.fetchall()]
    return templates.TemplateResponse(request, "virus_compare.html", {
        "active_page": "compare",
        "viruses": viruses_data,
    })


@app.get("/literature/{lit_id}", response_class=HTMLResponse, tags=["Pages"])
def serve_literature_detail(request: Request, lit_id: int):
    """Render literature detail page."""
    with get_db() as conn:
        c = conn.cursor()
        c.execute("SELECT * FROM ref_literatures WHERE reference_id = ?", (lit_id,))
        lit = c.fetchone()
        if not lit:
            return templates.TemplateResponse(request, "literature_detail.html", {
                "active_page": "literature",
                "literature": None,
                "evidence": [],
            })
        lit = dict(lit)
        c.execute("""
            SELECT er.evidence_id, er.evidence_type, er.claim, er.evidence_strength,
                   vm.canonical_name as virus_name
            FROM evidence_records er
            LEFT JOIN virus_master vm ON er.virus_master_id = vm.master_id
            WHERE er.reference_id = ?
            ORDER BY er.evidence_type
            LIMIT 50
        """, (lit_id,))
        evidence = [dict(r) for r in c.fetchall()]
    return templates.TemplateResponse(request, "literature_detail.html", {
        "active_page": "literature",
        "literature": lit,
        "evidence": evidence,
    })
    return templates.TemplateResponse(request, "literature.html", {"active_page": "enrichment"})
