"""
Enrich virus taxonomy classification via name patterns + NCBI Taxonomy API.

Strategy (two-phase):
  Phase 1 — Pattern-based family/genus inference from virus name
             (covers ~85% of cases, no API calls)
  Phase 2 — NCBI Taxonomy API lookup for remaining ambiguous names
             (covers the rest, ~1 req/s)

Usage:
    python enrich_virus_taxonomy.py                        # full run
    python enrich_virus_taxonomy.py --limit 50             # first 50 only
    python enrich_virus_taxonomy.py --dry-run              # preview only
    python enrich_virus_taxonomy.py --ncbi-only            # skip pattern matching
"""

from __future__ import annotations

import json
import re
import shutil
import sqlite3
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "crustacean_virus_core.db"
BACKUP_DIR = BASE_DIR / "backups"
DOWNLOADS_DIR = BASE_DIR / "downloads"

NCBI_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
REQUEST_DELAY = 0.5  # 2 req/s — well within NCBI rate limits (10/s without key)
CONTACT_EMAIL = "curator@crustacean-virus-db.org"


# ── Phase 1: Pattern-based inference ─────────────────────────────────────
# Ordered by specificity (longer/more specific patterns first)

FAMILY_PATTERNS: list[tuple[str, str, str | None]] = [
    # The "Unclassified XXX-like" patterns (family embedded in name)
    (r"^Unclassified\s+(\w+)like\b", None, None),  # handled specially

    # Qianjiang-specific: "marna-like virus" → Marnaviridae
    ("marna-like virus", "Marnaviridae", "Marnavirus"),
    ("marna-like", "Marnaviridae", "Marnavirus"),
    ("marnavirus", "Marnaviridae", "Marnavirus"),
    # Picorna-like
    ("picorna-like virus", "Picornaviridae", None),
    ("picorna-like", "Picornaviridae", None),
    ("picornavirales", "Picornaviridae", None),
    # Sobemo-like
    ("sobemo-like virus", "Sobemoviridae", "Sobemovirus"),
    ("sobemo-like", "Sobemoviridae", "Sobemovirus"),
    ("solemo-like", "Sobemoviridae", "Sobemovirus"),
    # Astro-like
    ("astro-like virus", "Astroviridae", None),
    ("astro-like", "Astroviridae", None),
    # Poty-like
    ("poty-like virus", "Potyviridae", "Potyvirus"),
    ("poty-like", "Potyviridae", "Potyvirus"),
    # Weivirus-like
    ("weivirus-like", "Weiviridae", "Weivirus"),
    ("weivirus", "Weiviridae", "Weivirus"),
    # Yanvirus-like
    ("yanvirus-like", "Yanviridae", "Yanvirus"),
    ("yanvirus", "Yanviridae", "Yanvirus"),
    # Zhaovirus-like
    ("zhaovirus-like", "Zhaoviridae", "Zhaovirus"),
    ("zhaovirus", "Zhaoviridae", "Zhaovirus"),
    # Bunya-like
    ("bunya-like virus", "Bunyaviridae", None),
    ("bunya-like", "Bunyaviridae", None),
    # Iflavirus
    ("iflavirus", "Iflaviridae", "Iflavirus"),
    # Dicistrovirus
    ("dicistro-like virus", "Dicistroviridae", None),
    ("dicistrovirus", "Dicistroviridae", None),
    ("dicistro-like", "Dicistroviridae", None),
    # Noda-like
    ("noda-like virus", "Nodaviridae", None),
    ("noda-like", "Nodaviridae", None),
    # Reo-like
    ("reovirus", "Reoviridae", None),
    ("reo-like virus", "Reoviridae", None),
    ("reo-like", "Reoviridae", None),
    # Rhabdo
    ("rhabdovirus", "Rhabdoviridae", None),
    # Chuvirus
    ("chuvirus", "Chuviridae", None),
    # Toti-like
    ("toti-like virus", "Totiviridae", None),
    ("toti-like", "Totiviridae", None),
    # Partiti-like
    ("partiti-like", "Partitiviridae", None),
    # Botourmia-like
    ("botourmia-like virus", "Botourmiaviridae", "Botourmiavirus"),
    ("botourmia-like", "Botourmiaviridae", "Botourmiavirus"),
    ("botourmiavirus", "Botourmiaviridae", "Botourmiavirus"),
    # Alphatetra-like
    ("alphatetra-like virus", "Alphatetraviridae", None),
    ("alphatetra-like", "Alphatetraviridae", None),
    # Barna-like
    ("barnavirus", "Barnaviridae", "Barnavirus"),
    # Lev-like
    ("levi-like virus", "Leviviridae", None),
    ("levi-like", "Leviviridae", None),
    ("levivirus", "Leviviridae", None),
    # Tombo-like
    ("tombus-like virus", "Tombusviridae", None),
    ("tombus-like", "Tombusviridae", None),
    # Virga-like
    ("virga-like", "Virgaviridae", None),
    # Tymo-like
    ("tymo-like", "Tymoviridae", None),
    # Kita-like
    ("kita-like", "Kitaviridae", None),
    # Tobamo-like
    ("tobamo-like virus", "Virgaviridae", "Tobamovirus"),
    ("tobamo-like", "Virgaviridae", "Tobamovirus"),
    # Calici
    ("calici", "Caliciviridae", None),
    # Flavi
    ("flavi", "Flaviviridae", None),
    # Narna
    ("narna-like", "Narnaviridae", None),
    # Astro
    ("astro", "Astroviridae", None),
    # Nege-like
    ("nege-like virus", "Negevirus", None),
    ("nege-like", "Negevirus", None),
    # Cholera-like (Eriocheir sinensis Cholera-like Virus)
    ("cholera-like", "Unclassified", None),
    # Arlivirus (Brine shrimp arlivirus)
    ("arlivirus", "Unclassified", None),
    # Golda virus
    ("golda virus", "Unclassified", None),
]

# Specific known virus → family/genus overrides (exact match needed)
KNOWN_VIRUS_TAXONOMY: dict[str, tuple[str, str | None]] = {
    "white spot syndrome virus": ("Nimaviridae", "Whispovirus"),
    "yellow head virus": ("Roniviridae", "Okavirus"),
    "taura syndrome virus": ("Dicistroviridae", "Aparavirus"),
    "infectious myonecrosis virus": ("Artiviridae", "Artivirus"),
    "infectious hypodermal and hematopoietic necrosis virus": ("Parvoviridae", "Shripenbrevirus"),
    "hepatopancreatic parvovirus": ("Parvoviridae", None),
    "macrobrachium rosenbergii nodavirus": ("Nodaviridae", None),
    "covert mortality nodavirus": ("Nodaviridae", None),
    "decapod iridescent virus": ("Iridoviridae", "Decapodiridovirus"),
    "crab associated circular virus": ("Roniviridae", "Okavirus"),
    "mourilyan virus": ("Unclassified", None),
    "laem-singh virus": ("Unclassified", None),
    "iridovirus cn01": ("Iridoviridae", None),
    "infectious precocity virus": ("Unclassified", None),
    "european shore crab virus 1": ("Unclassified", None),
    "mud crab virus": ("Unclassified", None),
    "shrimp glass disease virus": ("Unclassified", None),
    "penaeus monodon endogenous virus": ("Parvoviridae", None),
    "penaeus monodon rna virus": ("Unclassified", None),
    "portunus trituberculatus": ("Unclassified", None),
    "procambarus clarkii": ("Unclassified", None),
    "ellivirales sp.": ("Unclassified", None),
    "picornavirales sp. 2": ("Picornaviridae", None),
    "macrobrachium rosenbergii golda virus": ("Unclassified", None),
}

# Genome type → family hints (for specific ambiguous viruses)
GENOME_TYPE_FAMILIES: dict[str, str] = {
    "+ssRNA": "Unclassified (+ssRNA)",
    "-ssRNA": "Unclassified (-ssRNA)",
    "dsRNA": "Unclassified (dsRNA)",
    "dsDNA": "Unclassified (dsDNA)",
    "ssDNA": "Unclassified (ssDNA)",
    "RNA": "Unclassified (RNA)",
}


# ── NCBI Taxonomy API ───────────────────────────────────────────────────


def ncbi_taxonomy_search(name: str) -> list[dict]:
    """Search NCBI Taxonomy by name.

    Returns list of {taxid, scientific_name, rank, lineage_string,
                     family, genus, phylum, order, class_name}.
    Uses XML mode for efetch to extract full LineageEx.
    """
    import xml.etree.ElementTree as ET

    params = urllib.parse.urlencode({
        "db": "taxonomy",
        "term": name,
        "retmax": "5",
        "retmode": "json",
        "tool": "crustacean_virus_db",
        "email": CONTACT_EMAIL,
    })
    url = f"{NCBI_BASE}/esearch.fcgi?{params}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "crustacean-virus-db-curation/1.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        print(f"    [warn] NCBI search failed for '{name}': {exc}")
        return []

    id_list = (data or {}).get("esearchresult", {}).get("idlist", [])
    if not id_list:
        return []

    # Fetch details in XML mode (lineage information only available in XML)
    fetch_params = urllib.parse.urlencode({
        "db": "taxonomy",
        "id": ",".join(id_list),
        "retmode": "xml",
        "tool": "crustacean_virus_db",
        "email": CONTACT_EMAIL,
    })
    fetch_url = f"{NCBI_BASE}/efetch.fcgi?{fetch_params}"
    try:
        req = urllib.request.Request(fetch_url, headers={"User-Agent": "crustacean-virus-db-curation/1.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            xml_data = resp.read().decode("utf-8")
    except Exception as exc:
        print(f"    [warn] NCBI fetch failed for TaxIDs {id_list}: {exc}")
        return []

    results: list[dict] = []
    try:
        root = ET.fromstring(xml_data)
        for taxon in root.iter("Taxon"):
            tax_id = taxon.findtext("TaxId", "")
            sci_name = taxon.findtext("ScientificName", "")
            rank = taxon.findtext("Rank", "")
            lineage = taxon.findtext("Lineage", "")

            # Extract family, genus, etc. from LineageEx
            family = None
            genus = None
            phylum = None
            order_name = None
            class_name = None
            for lineage_ex in taxon.iter("LineageEx"):
                for tx in lineage_ex.iter("Taxon"):
                    tx_rank = (tx.findtext("Rank") or "").lower().strip()
                    tx_name = (tx.findtext("ScientificName") or "").strip()
                    if tx_rank == "family":
                        family = tx_name
                    elif tx_rank == "genus":
                        genus = tx_name
                    elif tx_rank == "phylum":
                        phylum = tx_name
                    elif tx_rank == "order":
                        order_name = tx_name
                    elif tx_rank == "class":
                        class_name = tx_name

            results.append({
                "taxid": tax_id,
                "name": sci_name,
                "rank": rank,
                "lineage": lineage,
                "family": family,
                "genus": genus,
                "phylum": phylum,
                "order": order_name,
                "class": class_name,
            })
    except ET.ParseError as exc:
        print(f"    [warn] XML parse error for TaxIDs {id_list}: {exc}")

    return results


# ── database operations ─────────────────────────────────────────────────


def backup_database() -> Path:
    BACKUP_DIR.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = BACKUP_DIR / f"crustacean_virus_core_before_taxonomy_{stamp}.db"
    shutil.copy2(DB_PATH, backup_path)
    return backup_path


def source_id(conn: sqlite3.Connection, key: str) -> int | None:
    row = conn.execute(
        "SELECT source_id FROM external_sources WHERE source_key = ?", (key,)
    ).fetchone()
    return row["source_id"] if row else None


def infer_family(name_lower: str) -> tuple[str | None, str | None]:
    """Infer family (and optionally genus) from virus name using patterns."""
    name_lower = name_lower.strip().lower()

    # Check exact known viruses first
    if name_lower in KNOWN_VIRUS_TAXONOMY:
        return KNOWN_VIRUS_TAXONOMY[name_lower]

    # Check pattern-based
    for pattern, family, genus in FAMILY_PATTERNS:
        if re.search(pattern, name_lower):
            return (family, genus)

    return (None, None)


def run_enrich(conn: sqlite3.Connection, limit: int | None, dry_run: bool, ncbi_only: bool) -> dict:
    stats = {
        "viruses_processed": 0,
        "pattern_matched": 0,
        "ncbi_searched": 0,
        "ncbi_matched": 0,
        "families_set": 0,
        "genera_set": 0,
        "ncbi_xrefs_added": 0,
        "no_match": 0,
        "already_had_family": 0,
        "profiles_updated": 0,
    }

    ncbi_src = source_id(conn, "ncbi_taxonomy")

    # Get viruses missing family
    query = """
        SELECT master_id, canonical_name, genome_type, entry_type,
               virus_family, virus_genus
        FROM virus_master
        WHERE (virus_family IS NULL OR virus_family = '')
          AND entry_type != 'non_target'
        ORDER BY master_id
    """
    if limit:
        query += f" LIMIT {limit}"
    viruses = conn.execute(query).fetchall()
    stats["viruses_processed"] = len(viruses)

    # Cache for NCBI results (name -> family/genus/taxid)
    ncbi_cache: dict[str, tuple[str, str | None, str] | None] = {}

    for idx, v in enumerate(viruses, start=1):
        master_id = v["master_id"]
        name = v["canonical_name"]
        name_lower = name.strip().lower()
        genome_type = v["genome_type"] or ""

        # Check if already has family (previously processed)
        if v["virus_family"] and v["virus_family"].strip():
            stats["already_had_family"] += 1
            continue

        # ── Phase 1: Pattern-based inference ──
        family, genus = None, None
        source = None
        ncbi_taxid = None

        if not ncbi_only:
            family, genus = infer_family(name_lower)
            if family:
                stats["pattern_matched"] += 1
                source = "pattern"
                # Mark genome-based classification separately
                if family.startswith("Unclassified"):
                    pass  # still useful as a fallback

        # ── Phase 2: NCBI Taxonomy API ──
        if not family:
            # Check cache
            if name_lower in ncbi_cache:
                cached = ncbi_cache[name_lower]
                if cached is not None:
                    family, genus, ncbi_taxid = cached
                    stats["ncbi_matched"] += 1
                    source = "ncbi_cache"
            else:
                # Query NCBI
                time.sleep(REQUEST_DELAY)
                ncbi_results = ncbi_taxonomy_search(name)
                stats["ncbi_searched"] += 1
                if ncbi_results:
                    # Use the best result (first = most relevant)
                    r = ncbi_results[0]
                    ncbi_taxid = r["taxid"]
                    found_family = r.get("family")
                    found_genus = r.get("genus")

                    if found_family:
                        family = found_family
                        genus = found_genus
                        source = "ncbi"
                        stats["ncbi_matched"] += 1
                    else:
                        # NCBI found the name but no family in lineage
                        # (e.g., genus-level or higher taxonomy term)
                        source = "ncbi_partial"

                # Cache result
                if not family:
                    ncbi_cache[name_lower] = None

        # If still no family, use genome type as last resort
        if not family and genome_type:
            family = GENOME_TYPE_FAMILIES.get(genome_type, f"Unclassified ({genome_type})")
            source = "genome_fallback"

        if not family:
            stats["no_match"] += 1
            if idx % 100 == 0:
                print(f"  [progress] {idx}/{len(viruses)} fam={stats['families_set']} ncbi={stats['ncbi_searched']} no={stats['no_match']}")
            continue

        # ── Write to database ──
        if dry_run:
            print(f"  [{idx}/{len(viruses)}] mid={master_id:4d} {name[:50]:50s} -> {family:25s} genus={str(genus or '')[:20]:20s} [{source}]")
            if idx % 100 == 0:
                print(f"  [progress] {idx}/{len(viruses)} fam={stats['families_set']} ncbi={stats['ncbi_searched']} no={stats['no_match']}")
            continue

        # Update virus_master
        conn.execute(
            "UPDATE virus_master SET virus_family = ?, virus_genus = ? WHERE master_id = ?",
            (family, genus, master_id),
        )
        stats["families_set"] += 1
        if genus:
            stats["genera_set"] += 1

        # Create NCBI TaxID xref if found
        if ncbi_taxid:
            conn.execute(
                """
                INSERT OR IGNORE INTO external_xrefs
                    (entity_type, entity_id, source_id, external_id, external_url,
                     match_status, confidence, matched_by, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "virus_master", master_id, ncbi_src, ncbi_taxid,
                    f"https://www.ncbi.nlm.nih.gov/Taxonomy/Browser/wwwtax.cgi?id={ncbi_taxid}",
                    "exact", "high", "enrich_virus_taxonomy.py",
                    f"NCBI Taxonomy match for {name} -> TaxID {ncbi_taxid}",
                ),
            )
            stats["ncbi_xrefs_added"] += 1

        # Also cache successful result
        if source == "ncbi":
            ncbi_cache[name_lower] = (family, genus, ncbi_taxid)

        if idx % 100 == 0:
            print(f"  [progress] {idx}/{len(viruses)} fam={stats['families_set']} ncbi={stats['ncbi_searched']} no={stats['no_match']}")

    # ── Phase 3: Sync families to isolate_curated_profiles ──
    if not dry_run:
        updated = conn.execute("""
            UPDATE isolate_curated_profiles
            SET virus_family = vm.virus_family,
                virus_genus = vm.virus_genus
            FROM virus_master vm
            WHERE isolate_curated_profiles.master_id = vm.master_id
              AND vm.virus_family IS NOT NULL AND vm.virus_family != ''
              AND (isolate_curated_profiles.virus_family IS NULL
                   OR isolate_curated_profiles.virus_family = '')
        """).rowcount
        stats["profiles_updated"] = updated

    return stats


def export_results(stats: dict) -> Path:
    DOWNLOADS_DIR.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = DOWNLOADS_DIR / f"taxonomy_results_{stamp}.json"
    data = {"stats": stats, "completed_at": datetime.now().isoformat(timespec="seconds")}
    out_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_path


def log_run(conn: sqlite3.Connection, stats: dict) -> None:
    src_id = source_id(conn, "ncbi_taxonomy")
    payload = "; ".join(f"{k}={v}" for k, v in sorted(stats.items()))
    conn.execute(
        """INSERT INTO curation_logs
           (entity_type, action, source_id, new_value, confidence, curator, notes)
         VALUES (?, ?, ?, ?, ?, ?, ?)""",
        ("virus_master", "enrich_taxonomy", src_id, payload,
         "high", "enrich_virus_taxonomy.py",
         "Enriched virus taxonomy via name patterns + NCBI Taxonomy API."),
    )


def validate(conn: sqlite3.Connection) -> None:
    qc = conn.execute("PRAGMA quick_check").fetchone()[0]
    if qc != "ok":
        raise RuntimeError(f"SQLite quick_check failed: {qc}")
    fk = conn.execute("PRAGMA foreign_key_check").fetchall()
    if fk:
        raise RuntimeError(f"Foreign key check failed: {fk[:5]}")


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="Enrich virus taxonomy")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--ncbi-only", action="store_true", help="Skip pattern matching")
    args = parser.parse_args()

    if args.dry_run:
        print("[dry-run] Preview mode — no database changes")
    if args.ncbi_only:
        print("[info] NCBI-only mode — skipping pattern-based inference")

    backup_path = backup_database() if not args.dry_run else None
    if backup_path:
        print(f"[backup] {backup_path}")

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        stats = run_enrich(conn, args.limit, args.dry_run, args.ncbi_only)
        if not args.dry_run:
            export_path = export_results(stats)
            log_run(conn, stats)
            validate(conn)
            conn.commit()
            print(f"[done] export={export_path}")
        else:
            print("[dry-run] skipped writes")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    for k, v in sorted(stats.items()):
        print(f"[done] {k}={v}")


if __name__ == "__main__":
    main()
