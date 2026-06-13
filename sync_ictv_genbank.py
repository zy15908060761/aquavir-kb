"""
sync_ictv_genbank.py — AquaVir-KB ICTV & GenBank sync workflow
==============================================================

Three phases:
  1. ICTV version check     — compares local MSL with latest available
  2. GenBank incremental    — queries NCBI for new aquatic-invertebrate virus records
  3. Cross-reference check  — validates FK integrity and mapping coverage

Output: detailed report plus a Markdown report in reports/ (if --report).
Run modes:
    python sync_ictv_genbank.py              # full sync, print report
    python sync_ictv_genbank.py --quick      # skip NCBI queries
    python sync_ictv_genbank.py --report     # write Markdown report to reports/
    python sync_ictv_genbank.py --check-ictv # only check ICTV version
"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime
from pathlib import Path

from Bio import Entrez

from db_utils import db_connection

# ── Paths ──────────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent
REPORTS_DIR = BASE_DIR / "reports"

# ── Constants ───────────────────────────────────────────────────────────────────
CURRENT_MSL = "MSL41"
CURRENT_VMR = "VMR_MSL41.v1.20260320"
CURRENT_VMR_DATE = "2026-03-20"
LAST_IMPORT_DATE = "2026-05-07"

NCBI_EMAIL = "aquavir-kb-sync@example.com"
NCBI_TOOL = "AquaVir-KB-Sync"

# ── NCBI search queries ───────────────────────────────────────────────────────
NCBI_QUERIES = [
    (
        "shrimp virus[All Fields] AND 2026[dp]",
        "Shrimp viruses (2026 publication date)",
    ),
    (
        "crustacean virus[All Fields] AND 2026[dp]",
        "Crustacean viruses (2026 publication date)",
    ),
    (
        (
            "(aquatic OR marine OR freshwater) AND "
            "invertebrate AND virus[Organism] AND 2026/05:2026/12[PDAT]"
        ),
        "Aquatic invertebrate viruses by publication date (2026-05 onward)",
    ),
    (
        "invertebrate virus[Organism] AND 2026/05:2026/12[EDAT]",
        "Invertebrate viruses by entry date (2026-05 onward)",
    ),
    (
        "decapod virus[All Fields] AND 2026[dp]",
        "Decapod viruses (2026 publication date)",
    ),
    (
        "(oyster OR coral OR mollusc) AND virus[Organism] AND 2026[dp]",
        "Mollusk/coral viruses (2026 publication date)",
    ),
]


# ══════════════════════════════════════════════════════════════════════════════
# Phase 1 — ICTV version check
# ══════════════════════════════════════════════════════════════════════════════

def check_ictv_version() -> dict:
    """Check whether the local MSL is still current.

    Reads the ICTV website to confirm the current release number.
    Returns a dict with status information.
    """
    import urllib.request
    import re

    result = {
        "local_msl": CURRENT_MSL,
        "local_vmr": CURRENT_VMR,
        "latest_msl": CURRENT_MSL,  # default to current unless proven otherwise
        "latest_vmr": CURRENT_VMR,
        "is_current": True,
        "notes": [],
    }

    urls_to_check = [
        ("ICTV taxonomy page (authoritative)", "https://ictv.global/taxonomy",
         r'"currentMslRelease":"(\d+)"'),
    ]

    authoritative_version = None

    for label, url, pattern in urls_to_check:
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "Mozilla/5.0 AquaVir-KB/1.0"},
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                html = resp.read().decode("utf-8", errors="replace")
            matches = re.findall(pattern, html)
            if matches:
                authoritative_version = int(matches[0])
                result["latest_msl"] = f"MSL{authoritative_version}"
                result["latest_vmr"] = f"VMR_MSL{authoritative_version}"
        except Exception as exc:
            result["notes"].append(f"Could not fetch {label}: {exc}")

    # Also check VMR page for the downloadable filename
    try:
        req = urllib.request.Request(
            "https://ictv.global/vmr",
            headers={"User-Agent": "Mozilla/5.0 AquaVir-KB/1.0"},
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            html = resp.read().decode("utf-8", errors="replace")
        vmr_match = re.search(r'VMR_MSL(\d+)\.v?\d+\.\d+', html)
        if vmr_match:
            vmr_ver = int(vmr_match.group(1))
            result["latest_vmr"] = f"VMR_MSL{vmr_ver}"
            if authoritative_version is None:
                authoritative_version = vmr_ver
                result["latest_msl"] = f"MSL{vmr_ver}"
    except Exception as exc:
        result["notes"].append(f"Could not fetch VMR page: {exc}")

    # Determine status
    if authoritative_version is not None:
        local_num = int(re.search(r"(\d+)", CURRENT_MSL).group(1))  # type: ignore[union-attr]
        if authoritative_version > local_num:
            result["is_current"] = False
            result["notes"].append(
                f"NEW VERSION AVAILABLE: MSL{authoritative_version} "
                f"(local: {CURRENT_MSL})"
            )
        elif authoritative_version == local_num:
            result["is_current"] = True
            result["notes"].append("Already on latest MSL release (MSL41)")
        else:
            result["is_current"] = True
            result["notes"].append(
                f"Local version ({CURRENT_MSL}) ahead of or matches online"
            )
    else:
        result["notes"].append(
            "Could not confirm version from ICTV website (unreachable?)"
        )

    return result


# ══════════════════════════════════════════════════════════════════════════════
# Phase 2 — GenBank incremental sync
# ══════════════════════════════════════════════════════════════════════════════

def query_ncbi(term: str, retmax: int = 1000, db: str = "nucleotide") -> dict:
    """Run a single ESearch query and return counts + sample IDs."""
    Entrez.email = NCBI_EMAIL
    Entrez.tool = NCBI_TOOL
    Entrez.sleep_between_tries = 1

    try:
        handle = Entrez.esearch(db=db, term=term, retmax=retmax, idtype="acc")
        record = Entrez.read(handle)
        handle.close()
        time.sleep(0.7)
        return {
            "count": int(record.get("Count", 0)),
            "ids": record.get("IdList", []),
        }
    except Exception as exc:
        return {"count": 0, "ids": [], "error": str(exc)}


def check_db_accessions() -> tuple[set[str], set[str]]:
    """Return (exact_accessions, base_accessions) from viral_isolates."""
    with db_connection(read_only=True) as conn:
        existing = {
            r["accession"].strip().upper()
            for r in conn.execute("SELECT accession FROM viral_isolates")
        }
    base = {a.split(".")[0] for a in existing}
    return existing, base


def check_new_records_against_db(new_ids: list[str]) -> dict:
    """Cross-check a list of NCBI accessions against the local DB."""
    exact, base = check_db_accessions()
    known = []
    unknown = []
    for acc in new_ids:
        a = acc.strip().upper()
        b = a.split(".")[0]
        if a in exact or b in base:
            known.append(acc)
        else:
            unknown.append(acc)
    return {"known": known, "unknown": unknown, "total_new": len(unknown)}


def sync_genbank() -> dict:
    """Query NCBI for new aquatic invertebrate virus records.

    Returns summary dict.
    """
    results = {}
    all_new_ids: set[str] = set()

    for term, label in NCBI_QUERIES:
        r = query_ncbi(term)
        results[label] = r
        all_new_ids.update(r.get("ids", []))

    # Cross-check against DB
    xref = check_new_records_against_db(list(all_new_ids))
    results["_crosscheck"] = xref
    results["_total_unique"] = len(all_new_ids)

    return results


# ══════════════════════════════════════════════════════════════════════════════
# Phase 3 — Cross-reference validation
# ══════════════════════════════════════════════════════════════════════════════

def validate_references() -> dict:
    """Run integrity checks on ICTV/VMR mappings."""
    checks = {}

    with db_connection(read_only=True) as conn:
        # 1. Broken master_id in virus_ictv_mappings
        checks["broken_ictv_master_ids"] = conn.execute(
            """
            SELECT COUNT(*)
            FROM virus_ictv_mappings vim
            LEFT JOIN virus_master vm ON vim.master_id = vm.master_id
            WHERE vm.master_id IS NULL
            """
        ).fetchone()[0]

        # 2. Broken master_id in virus_vmr_mappings
        checks["broken_vmr_master_ids"] = conn.execute(
            """
            SELECT COUNT(*)
            FROM virus_vmr_mappings vvm
            LEFT JOIN virus_master vm ON vvm.master_id = vm.master_id
            WHERE vm.master_id IS NULL
            """
        ).fetchone()[0]

        # 3. Broken vmr_id in virus_vmr_mappings
        checks["broken_vmr_vmr_ids"] = conn.execute(
            """
            SELECT COUNT(*)
            FROM virus_vmr_mappings vvm
            LEFT JOIN ictv_vmr iv ON vvm.vmr_id = iv.vmr_id
            WHERE iv.vmr_id IS NULL
            """
        ).fetchone()[0]

        # 4. ICTV mappings without VMR counterpart
        checks["ictv_mapped_no_vmr"] = conn.execute(
            """
            SELECT COUNT(DISTINCT vim.master_id)
            FROM virus_ictv_mappings vim
            WHERE vim.master_id NOT IN (
                SELECT DISTINCT master_id FROM virus_vmr_mappings
            )
            """
        ).fetchone()[0]

        # 5. Counts
        checks["virus_master_total"] = conn.execute(
            "SELECT COUNT(*) FROM virus_master"
        ).fetchone()[0]
        checks["virus_master_target"] = conn.execute(
            """
            SELECT COUNT(*) FROM virus_master
            WHERE is_crustacean_virus = 1
            """
        ).fetchone()[0]
        checks["ictv_vmr_total"] = conn.execute(
            "SELECT COUNT(*) FROM ictv_vmr"
        ).fetchone()[0]
        checks["virus_ictv_mappings"] = conn.execute(
            "SELECT COUNT(*) FROM virus_ictv_mappings"
        ).fetchone()[0]
        checks["virus_vmr_mappings"] = conn.execute(
            "SELECT COUNT(*) FROM virus_vmr_mappings"
        ).fetchone()[0]
        checks["viral_isolates"] = conn.execute(
            "SELECT COUNT(*) FROM viral_isolates"
        ).fetchone()[0]

        # 6. Unmapped target viruses with family
        checks["unmapped_with_family"] = conn.execute(
            """
            SELECT COUNT(*)
            FROM virus_master vm
            WHERE vm.virus_family IS NOT NULL
              AND vm.virus_family != ''
              AND vm.canonical_name NOT IN (
                  'Unknown/Unclassified', 'Non-crustacean virus'
              )
              AND vm.master_id NOT IN (
                  SELECT DISTINCT master_id FROM virus_vmr_mappings
                  UNION
                  SELECT DISTINCT master_id FROM virus_ictv_mappings
              )
            """
        ).fetchone()[0]

        # 7. Host source distribution summary for aquatic relevance
        host_counts = conn.execute(
            """
            SELECT host_source, COUNT(*) AS cnt
            FROM ictv_vmr
            WHERE host_source IS NOT NULL AND host_source != ''
            GROUP BY host_source
            ORDER BY cnt DESC
            LIMIT 10
            """
        ).fetchall()
        checks["top_host_sources"] = {
            r["host_source"]: r["cnt"] for r in host_counts
        }

    return checks


# ══════════════════════════════════════════════════════════════════════════════
# Report generation
# ══════════════════════════════════════════════════════════════════════════════

def generate_report(
    ictv: dict,
    genbank: dict | None,
    refs: dict,
    duration: float,
) -> str:
    """Assemble a plain-text report string."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = [
        "=" * 72,
        "  AquaVir-KB ICTV & GenBank Sync Report",
        f"  Generated: {now}",
        f"  Duration:  {duration:.1f} seconds",
        "=" * 72,
        "",
    ]

    # ── Phase 1: ICTV ──
    lines.append("─── Phase 1: ICTV Version Check ──────────────────────────────")
    lines.append(f"  Local MSL:     {ictv['local_msl']}")
    lines.append(f"  Local VMR:     {ictv['local_vmr']}")
    lines.append(f"  Latest MSL:    {ictv['latest_msl'] or 'unreachable'}")
    lines.append(f"  Latest VMR:    {ictv['latest_vmr'] or 'unreachable'}")
    if ictv["is_current"]:
        lines.append("  Status:        [OK] Already on latest MSL release")
    else:
        lines.append("  Status:        [UPDATE AVAILABLE] New ICTV release found!")
    for note in ictv.get("notes", []):
        lines.append(f"  Note:          {note}")
    lines.append("")

    # ── Phase 2: GenBank ──
    lines.append("─── Phase 2: GenBank Incremental Sync ────────────────────────")
    if genbank is None:
        lines.append("  (skipped by --quick)")
    else:
        for label, r in genbank.items():
            if label.startswith("_"):
                continue
            count = r.get("count", "?")
            err = r.get("error")
            marker = "[OK]" if not err else "[ERR]"
            lines.append(f"  {marker} {label}")
            lines.append(f"         Records found: {count}")
            if err:
                lines.append(f"         Error: {err}")
            sample = r.get("ids", [])[:5]
            if sample:
                lines.append(f"         Sample: {', '.join(sample)}")
        lines.append("")
        xc = genbank.get("_crosscheck", {})
        lines.append(f"  Total unique NCBI accessions found:   "
                      f"{genbank.get('_total_unique', '?')}")
        lines.append(f"  Already in local DB:                  "
                      f"{len(xc.get('known', []))}")
        lines.append(f"  New records (not in DB):              "
                      f"{len(xc.get('unknown', []))}")
        if xc.get("unknown"):
            lines.append(f"  New accessions: {', '.join(xc['unknown'][:12])}")
        lines.append("")

    # ── Phase 3: References ──
    lines.append("─── Phase 3: Cross-Reference Validation ──────────────────────")
    lines.append(f"  virus_master total:                   {refs['virus_master_total']}")
    lines.append(f"  virus_master (target):                {refs['virus_master_target']}")
    lines.append(f"  ictv_vmr entries:                     {refs['ictv_vmr_total']}")
    lines.append(f"  virus_ictv_mappings:                  {refs['virus_ictv_mappings']}")
    lines.append(f"  virus_vmr_mappings:                   {refs['virus_vmr_mappings']}")
    lines.append(f"  viral_isolates:                       {refs['viral_isolates']}")
    lines.append("")
    lines.append("  Integrity checks:")
    lines.append(f"    Broken master_id in virus_ictv_mappings:   "
                  f"{refs['broken_ictv_master_ids']}  "
                  f"{'[OK]' if refs['broken_ictv_master_ids'] == 0 else '[BROKEN]'}")
    lines.append(f"    Broken master_id in virus_vmr_mappings:    "
                  f"{refs['broken_vmr_master_ids']}  "
                  f"{'[OK]' if refs['broken_vmr_master_ids'] == 0 else '[BROKEN]'}")
    lines.append(f"    Broken vmr_id in virus_vmr_mappings:       "
                  f"{refs['broken_vmr_vmr_ids']}  "
                  f"{'[OK]' if refs['broken_vmr_vmr_ids'] == 0 else '[BROKEN]'}")
    lines.append(f"    ICTV-mapped viruses missing VMR mapping:   "
                  f"{refs['ictv_mapped_no_vmr']}  "
                  f"{'[NOTE]' if refs['ictv_mapped_no_vmr'] > 0 else '[OK]'}")
    lines.append(f"    Unmapped virus_master (with family):       "
                  f"{refs['unmapped_with_family']}  "
                  f"{'[NOTE]' if refs['unmapped_with_family'] < 100 else '[MANY]'}")
    lines.append("")
    lines.append("  Top host_source values (ictv_vmr):")
    for src, cnt in list(refs.get("top_host_sources", {}).items())[:10]:
        lines.append(f"    {src}: {cnt}")
    lines.append("")

    lines.append("─── Recommendations ──────────────────────────────────────────")
    if genbank and genbank.get("_crosscheck", {}).get("unknown"):
        n = len(genbank["_crosscheck"]["unknown"])
        lines.append(
            f"  - {n} new NCBI accessions not yet in local DB. "
            f"Consider importing with incremental_import.py."
        )
    if refs.get("unmapped_with_family", 0) > 100:
        lines.append(
            f"  - {refs['unmapped_with_family']} virus_master entries have a "
            "family but no ICTV/VMR mapping. Consider running match_ictv.py."
        )
    if ictv["is_current"]:
        lines.append("  - ICTV is up to date (MSL41). Next expected: MSL42 (~2026-09).")
    else:
        lines.append("  - URGENT: New ICTV release available. Plan VMR re-import.")
    lines.append("")

    return "\n".join(lines)


def write_markdown_report(
    ictv: dict,
    genbank: dict | None,
    refs: dict,
    duration: float,
) -> Path:
    """Write a Markdown report to REPORTS_DIR."""
    now = datetime.now()
    stamp = now.strftime("%Y%m%d_%H%M%S")
    report_path = REPORTS_DIR / f"sync_report_{stamp}.md"
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    lines = [
        f"# AquaVir-KB Sync Report — {now.strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        f"- **Duration:** {duration:.1f} seconds",
        f"- **Script:** sync_ictv_genbank.py",
        "",
        "## Phase 1: ICTV Version Check",
        "",
        f"| Metric | Value |",
        f"|--------|-------|",
        f"| Local MSL | {ictv['local_msl']} |",
        f"| Local VMR | {ictv['local_vmr']} |",
        f"| Latest MSL online | {ictv['latest_msl'] or 'unreachable'} |",
        f"| Latest VMR online | {ictv['latest_vmr'] or 'unreachable'} |",
        f"| Status | {'Current' if ictv['is_current'] else 'UPDATE AVAILABLE'} |",
        "",
    ]
    for note in ictv.get("notes", []):
        lines.append(f"- {note}")
    lines.append("")

    lines.extend([
        "## Phase 2: GenBank Incremental Sync",
        "",
    ])
    if genbank is None:
        lines.append("_(skipped by --quick)_\n")
    else:
        lines.append("| Query | Records |")
        lines.append("|-------|---------|")
        for label, r in genbank.items():
            if label.startswith("_"):
                continue
            count = r.get("count", 0)
            lines.append(f"| {label} | {count} |")
        lines.append("")
        xc = genbank.get("_crosscheck", {})
        lines.append(f"- **Total unique NCBI accessions:** {genbank.get('_total_unique', 0)}")
        lines.append(f"- **Already in DB:** {len(xc.get('known', []))}")
        lines.append(f"- **New to DB:** {len(xc.get('unknown', []))}")
        if xc.get("unknown"):
            lines.append(f"- **New accessions:** `{'`, `'.join(xc['unknown'][:12])}`")
        lines.append("")

    lines.extend([
        "## Phase 3: Cross-Reference Validation",
        "",
        "| Check | Result | Status |",
        "|-------|--------|--------|",
        f"| Broken master_id in virus_ictv_mappings | {refs['broken_ictv_master_ids']} | "
        f"{'OK' if refs['broken_ictv_master_ids'] == 0 else 'BROKEN'} |",
        f"| Broken master_id in virus_vmr_mappings | {refs['broken_vmr_master_ids']} | "
        f"{'OK' if refs['broken_vmr_master_ids'] == 0 else 'BROKEN'} |",
        f"| Broken vmr_id in virus_vmr_mappings | {refs['broken_vmr_vmr_ids']} | "
        f"{'OK' if refs['broken_vmr_vmr_ids'] == 0 else 'BROKEN'} |",
        f"| ICTV-mapped no VMR mapping | {refs['ictv_mapped_no_vmr']} | "
        f"{'NOTE' if refs['ictv_mapped_no_vmr'] > 0 else 'OK'} |",
        f"| Unmapped with family | {refs['unmapped_with_family']} | "
        f"{'NOTE' if refs['unmapped_with_family'] < 100 else 'MANY'} |",
        "",
        "### Table Counts",
        "",
        f"| Table | Rows |",
        f"|-------|------|",
        f"| virus_master | {refs['virus_master_total']} |",
        f"| virus_master (target) | {refs['virus_master_target']} |",
        f"| ictv_vmr | {refs['ictv_vmr_total']} |",
        f"| virus_ictv_mappings | {refs['virus_ictv_mappings']} |",
        f"| virus_vmr_mappings | {refs['virus_vmr_mappings']} |",
        f"| viral_isolates | {refs['viral_isolates']} |",
        "",
        "## Top Host Sources in ICTV VMR",
        "",
        "| Host Source | Count |",
        "|-------------|-------|",
    ])
    for src, cnt in list(refs.get("top_host_sources", {}).items())[:10]:
        lines.append(f"| {src} | {cnt} |")
    lines.append("")

    lines.extend([
        "## Recommendations",
        "",
    ])
    if genbank and genbank.get("_crosscheck", {}).get("unknown"):
        n = len(genbank["_crosscheck"]["unknown"])
        lines.append(
            f"- **{n} new NCBI accessions** not in local DB. "
            "Consider `incremental_import.py`."
        )
    if refs.get("unmapped_with_family", 0) > 100:
        lines.append(
            f"- **{refs['unmapped_with_family']} unmapped entries** have a family "
            "but no ICTV/VMR mapping. Consider `match_ictv.py`."
        )
    if ictv["is_current"]:
        lines.append("- ICTV is up to date (MSL41). Next expected: MSL42 (~2026 Q3).")
    else:
        lines.append("- **URGENT:** New ICTV release detected. Plan VMR re-import.")
    lines.append("")

    report_path.write_text("\n".join(lines), encoding="utf-8")
    return report_path


# ══════════════════════════════════════════════════════════════════════════════
# Main
# ══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="AquaVir-KB ICTV & GenBank sync workflow"
    )
    parser.add_argument("--quick", action="store_true",
                        help="Skip NCBI queries (only ICTV check + validation)")
    parser.add_argument("--report", action="store_true",
                        help="Write Markdown report to reports/")
    parser.add_argument("--check-ictv", action="store_true",
                        help="Only check ICTV version, skip everything else")
    args = parser.parse_args()

    t0 = time.time()

    # Phase 1 always runs
    print("[1/3] Checking ICTV version...")
    ictv = check_ictv_version()
    print(f"  Local: {ictv['local_msl']}, Online: {ictv['latest_msl']}")
    print(f"  Status: {'Current' if ictv['is_current'] else 'UPDATE AVAILABLE'}")

    # Phase 2 — optional
    genbank = None
    if args.check_ictv:
        print("[2/3] Skipped (--check-ictv)")
    elif args.quick:
        print("[2/3] Skipped (--quick)")
    else:
        print("[2/3] Querying NCBI for new aquatic invertebrate virus records...")
        genbank = sync_genbank()
        total_new = genbank.get("_total_unique", 0)
        xc = genbank.get("_crosscheck", {})
        print(f"  Total unique NCBI accessions found: {total_new}")
        print(f"  Already in local DB: {len(xc.get('known', []))}")
        print(f"  New records: {len(xc.get('unknown', []))}")
        if xc.get("unknown"):
            print(f"  New accessions: {', '.join(xc['unknown'][:12])}")

    # Phase 3 — always runs
    print("[3/3] Validating cross-references...")
    refs = validate_references()
    print(f"  Integrity: {refs['broken_ictv_master_ids']} broken ICTV links, "
          f"{refs['broken_vmr_master_ids']} broken VMR links")
    print(f"  Unmapped with family: {refs['unmapped_with_family']}")

    duration = time.time() - t0

    # Report
    report_text = generate_report(ictv, genbank, refs, duration)
    print()
    print(report_text)

    # Markdown output
    if args.report:
        md_path = write_markdown_report(ictv, genbank, refs, duration)
        print(f"[report] Markdown report saved to {md_path}")

    print(f"[done] Total time: {duration:.1f}s")


if __name__ == "__main__":
    main()
