#!/usr/bin/env python3
"""
expand_genome_comparisons.py - Expand genome comparative analysis across all virus families.

Performs four tasks:
  a) Genome statistics completion (GC content, length from NCBI)
  b) Within-family pairwise genome_length ratio comparisons (as proxy for size similarity)
  c) Core gene / shared domain analysis by family
  d) Generate comparison summary report

Usage:
    python expand_genome_comparisons.py                     # Full run
    python expand_genome_comparisons.py --dry-run           # Preview only, no writes
    python expand_genome_comparisons.py --skip-ncbi         # Skip NCBI fetch
    python expand_genome_comparisons.py --skip-pairwise     # Skip pairwise comparisons
    python expand_genome_comparisons.py --skip-core         # Skip core gene analysis
    python expand_genome_comparisons.py --family Nimaviridae # Limit to one family
"""

from __future__ import annotations

import argparse
import sqlite3
import os
import sys
import shutil
import time
import json
from datetime import datetime
from pathlib import Path
from itertools import combinations
from collections import defaultdict, Counter

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
DB_PATH = Path(r"F:/水生无脊椎动物数据库/crustacean_virus_core.db")
REPORT_DIR = Path(r"F:/水生无脊椎动物数据库/reports")
BACKUP_DIR = Path(r"F:/水生无脊椎动物数据库/backups")

NCBI_EMAIL = "aquavir-kb@example.com"  # NCBI requires an email
NCBI_API_KEY = None                     # Set if you have one for higher rate limits

# Limits for pairwise comparisons: cap per family to avoid combinatorial explosion
MAX_PAIRS_PER_FAMILY = 5000             # Max comparisons per family
MAX_ISOLATES_PER_FAMILY = 100           # Max isolates sampled per family for pairwise

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------
parser = argparse.ArgumentParser(
    description="Expand genome comparative analysis across all virus families."
)
parser.add_argument("--dry-run", action="store_true",
                    help="Preview only, do not write to database")
parser.add_argument("--skip-ncbi", action="store_true",
                    help="Skip NCBI genome statistics fetch")
parser.add_argument("--skip-pairwise", action="store_true",
                    help="Skip pairwise genome length ratio comparisons")
parser.add_argument("--skip-core", action="store_true",
                    help="Skip core gene / shared domain analysis")
parser.add_argument("--family", type=str, default=None,
                    help="Limit analysis to a single family (e.g., Nimaviridae)")
parser.add_argument("--verbose", action="store_true", default=True,
                    help="Show detailed output")
ARGS = parser.parse_args()

DRY_RUN = ARGS.dry_run

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
LOG_LINES: list[str] = []

def log(msg: str, force: bool = False) -> None:
    if ARGS.verbose or force:
        print(msg)
    LOG_LINES.append(msg)


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------
def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA busy_timeout = 30000")
    conn.row_factory = sqlite3.Row
    return conn


def query(sql: str, params: tuple | None = None) -> list[dict]:
    conn = get_conn()
    cur = conn.cursor()
    if params:
        cur.execute(sql, params)
    else:
        cur.execute(sql)
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def execute(sql: str, params: tuple | None = None) -> int:
    """Execute and return rowcount."""
    conn = get_conn()
    cur = conn.cursor()
    try:
        if params:
            cur.execute(sql, params)
        else:
            cur.execute(sql)
        conn.commit()
        return cur.rowcount
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()


def executemany(sql: str, params_list: list[tuple]) -> int:
    """Execute many and return total rowcount."""
    if not params_list:
        return 0
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.executemany(sql, params_list)
        conn.commit()
        return len(params_list)
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Backup
# ---------------------------------------------------------------------------
def create_backup() -> Path | None:
    """Create a timestamped backup of the database."""
    if DRY_RUN:
        log("[BACKUP] Skipped (dry-run)")
        return None
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = BACKUP_DIR / f"crustacean_virus_core_gencomp_{ts}.db"
    log(f"[BACKUP] Creating backup: {backup_path}")
    shutil.copy2(str(DB_PATH), str(backup_path))
    log(f"[BACKUP] Done ({backup_path.stat().st_size >> 20} MB)")
    return backup_path


# ===================================================================
# TASK A: Genome statistics completion from NCBI (GC content / length)
# ===================================================================
def task_a_complete_genome_stats() -> dict:
    """
    For isolates with genome_accession but missing GC content or genome_length,
    fetch from NCBI Entrez efetch (nucleotide database).

    Parse GBSeq_length and GBSeq_GC from GenBank XML.
    """
    import xml.etree.ElementTree as ET
    from Bio import Entrez

    Entrez.email = NCBI_EMAIL
    if NCBI_API_KEY:
        Entrez.api_key = NCBI_API_KEY

    log("\n" + "=" * 60)
    log("TASK A: Genome statistics completion from NCBI")
    log("=" * 60)

    # Find candidates: have accession but need GC or length
    rows = query("""
        SELECT isolate_id, accession, genome_accession, genome_length, gc_content,
               taxon_family, virus_name
        FROM viral_isolates
        WHERE genome_accession IS NOT NULL AND genome_accession != ''
          AND (gc_content IS NULL
               OR genome_length IS NULL OR genome_length = 0)
        ORDER BY taxon_family
    """)

    log(f"  Candidates for NCBI fetch: {len(rows)}")

    # For length-only missing
    len_missing = [r for r in rows if r['genome_length'] is None or r['genome_length'] == 0]
    log(f"  Missing genome_length: {len(len_missing)}")

    # For GC-only missing
    gc_missing = [r for r in rows if r['gc_content'] is None]
    log(f"  Missing gc_content: {len(gc_missing)}")

    updates = []  # (gc_content, genome_length, isolate_id)
    ncbi_calls = 0
    ncbi_errors = 0

    if DRY_RUN:
        log("[DRY-RUN] Would fetch from NCBI for GC/length completion")
        return {
            "candidates": len(rows),
            "gc_fetched": 0,
            "length_fetched": 0,
            "errors": 0,
            "candidate_details": {
                "missing_gc": len(gc_missing),
                "missing_length": len(len_missing),
            }
        }

    if ARGS.skip_ncbi:
        log("  Skipped (--skip-ncbi)")
        return {
            "candidates": len(rows),
            "gc_fetched": 0,
            "length_fetched": 0,
            "errors": 0,
            "skipped": True,
        }

    # Clean accessions (remove version numbers for NCBI search)
    def clean_acc(acc: str) -> str:
        acc = acc.strip()
        # Remove version suffix like .1
        if '.' in acc:
            acc = acc.split('.')[0]
        return acc

    # Process in batches to respect NCBI rate limit (3/sec -> 10/sec with API key)
    batch_size = 3 if not NCBI_API_KEY else 10
    processed = 0

    for i in range(0, len(rows), batch_size):
        batch = rows[i:i + batch_size]
        accessions = [clean_acc(r['genome_accession']) for r in batch]

        for j, acc in enumerate(accessions):
            r = batch[j]
            try:
                ncbi_calls += 1
                log(f"  [NCBI {ncbi_calls}] Fetching {acc} for isolate {r['isolate_id']} ({r['virus_name'][:30]})")

                handle = Entrez.efetch(db="nucleotide", id=acc, rettype="gbc", retmode="xml")
                xml_data = handle.read()
                handle.close()

                # Parse XML
                root = ET.fromstring(xml_data)

                # Find GBSeq_length and GBSeq_GC-content
                ns = {}  # default namespace
                new_length = None
                new_gc = None

                for seq in root.iter("GBSeq"):
                    # Length
                    len_elem = seq.find("GBSeq_length")
                    if len_elem is not None and len_elem.text:
                        try:
                            new_length = int(len_elem.text)
                        except ValueError:
                            pass

                    # GC content
                    for xref in seq.iter("GBQualifier"):
                        name_elem = xref.find("GBQualifier_name")
                        val_elem = xref.find("GBQualifier_value")
                        if name_elem is not None and name_elem.text == "GC_content":
                            if val_elem is not None and val_elem.text:
                                try:
                                    new_gc = float(val_elem.text)
                                except ValueError:
                                    pass

                # If we didn't get GC from GenBank qualifiers, estimate from sequence
                if new_gc is None:
                    # Try to get the sequence and calculate GC
                    seq_data = seq.find("GBSeq_sequence")
                    if seq_data is not None and seq_data.text:
                        seq_str = seq_data.text.upper()
                        if len(seq_str) > 0:
                            gc_count = seq_str.count('G') + seq_str.count('C')
                            new_gc = round(gc_count / len(seq_str) * 100, 2)

                if new_length is not None or new_gc is not None:
                    updates.append((
                        new_gc,
                        new_length,
                        r['isolate_id']
                    ))
                    log(f"    -> length={new_length}, gc={new_gc}")
                else:
                    log(f"    -> No data found in XML response")
                    ncbi_errors += 1

            except Exception as e:
                ncbi_errors += 1
                log(f"    -> ERROR: {e}")

        # Rate limiting
        if ncbi_calls >= 3 and not NCBI_API_KEY:
            log(f"  [RATE-LIMIT] Sleeping 1 second...")
            time.sleep(1)
        elif NCBI_API_KEY:
            time.sleep(0.1)  # 10/sec with API key

        processed += len(batch)
        if processed % 30 == 0:
            log(f"  Progress: {processed}/{len(rows)}")

    # Apply updates
    if updates:
        sql = """
            UPDATE viral_isolates
            SET gc_content = COALESCE(?, gc_content),
                genome_length = COALESCE(?, genome_length)
            WHERE isolate_id = ?
        """
        count = executemany(sql, updates)
        log(f"\n  Updated {count} isolates with NCBI data")
    else:
        log("\n  No updates applied")

    return {
        "candidates": len(rows),
        "gc_fetched": len([u for u in updates if u[0] is not None]),
        "length_fetched": len([u for u in updates if u[1] is not None]),
        "total_updated": len(updates),
        "errors": ncbi_errors,
        "ncbi_calls": ncbi_calls,
    }


# ===================================================================
# TASK B: Within-family pairwise genome_length ratio comparisons
# ===================================================================
def task_b_pairwise_comparisons() -> dict:
    """
    For families with >=3 isolates that have genome_length, compute pairwise
    genome_length ratios as a proxy for genome size similarity.

    The ratio = min(len_a, len_b) / max(len_a, len_b), so 1.0 = identical length.
    This is a quick proxy for genome size similarity without needing sequence files.
    """
    log("\n" + "=" * 60)
    log("TASK B: Within-family pairwise genome length ratio comparisons")
    log("=" * 60)

    # Get all isolates with genome_length, grouped by family
    # Use virus_master for family assignment (more reliable), fall back to taxon_family
    rows = query("""
        SELECT vi.isolate_id, vi.accession, vi.genome_length, vi.gc_content,
               vi.taxon_family,
               vm.virus_family AS master_family,
               COALESCE(vm.canonical_name, vi.virus_name) AS species_name,
               vm.master_id
        FROM viral_isolates vi
        LEFT JOIN virus_master vm ON vi.master_id = vm.master_id
        WHERE vi.genome_length IS NOT NULL AND vi.genome_length > 0
          AND vi.has_sequence = 1
        ORDER BY vi.isolate_id
    """)

    # Group by family (use master_family as primary, fallback to taxon_family)
    families: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        family = (r['master_family'] or r['taxon_family'] or 'Unassigned').strip()
        if family == '':
            family = 'Unassigned'
        if family == 'Dataset':
            continue  # Skip generic Dataset group
        families[family].append(r)

    log(f"  Loaded {len(rows)} isolates with genome_length across {len(families)} families")

    # Filter to families with >=3 isolates
    families_with_3 = {f: isolates for f, isolates in families.items() if len(isolates) >= 3}

    if ARGS.family:
        if ARGS.family in families_with_3:
            families_with_3 = {ARGS.family: families_with_3[ARGS.family]}
        else:
            log(f"  WARNING: Family '{ARGS.family}' not found among families with >=3 isolates")
            return {"families_analyzed": 0, "comparisons_added": 0, "species_covered": 0}

    log(f"  Families with >=3 isolates: {len(families_with_3)}")
    for fam, isolates in sorted(families_with_3.items(), key=lambda x: -len(x[1]))[:10]:
        log(f"    {fam}: {len(isolates)} isolates")

    # Prepare pairwise comparisons
    comparisons = []
    families_covered = set()
    species_covered = set()

    for family, isolates in families_with_3.items():
        families_covered.add(family)

        # Sort by genome_length for better readability
        isolates_sorted = sorted(isolates, key=lambda x: x['genome_length'])

        # Cap the number of isolates sampled for large families (combinatorial explosion)
        if len(isolates_sorted) > MAX_ISOLATES_PER_FAMILY:
            # Sample evenly across genome length range to capture diversity
            step = len(isolates_sorted) / MAX_ISOLATES_PER_FAMILY
            sampled = [isolates_sorted[int(i * step)] for i in range(MAX_ISOLATES_PER_FAMILY)]
            log(f"    {family}: {len(isolates)} isolates capped to {MAX_ISOLATES_PER_FAMILY} for pairwise")
            isolates_sorted = sampled

        # For each pair within the family
        pair_count = 0
        for iso_a, iso_b in combinations(isolates_sorted, 2):
            len_a = iso_a['genome_length']
            len_b = iso_b['genome_length']

            if len_a <= 0 or len_b <= 0:
                continue

            # Length ratio: smaller / larger = proxy for size similarity
            ratio = min(len_a, len_b) / max(len_a, len_b)

            # Only store if the ratio is meaningful (>0.5 = same order of magnitude)
            # This filters out clearly different genome sizes
            if ratio < 0.5:
                continue

            # Use isolate accession for the comparison
            acc_a = iso_a['accession']
            acc_b = iso_b['accession']

            if acc_a == acc_b:
                continue

            # Use species name
            species = iso_a['species_name'] or family

            comparisons.append((
                acc_a,
                acc_b,
                species,
                round(ratio, 4),
                len_a,
                len_b,
            ))
            species_covered.add(species)
            pair_count += 1

            # Per-family cap to avoid massive inserts
            if pair_count >= MAX_PAIRS_PER_FAMILY:
                log(f"    {family}: capped at {MAX_PAIRS_PER_FAMILY} comparisons")
                break

        if len(isolates) >= 3 and len(isolates) <= MAX_ISOLATES_PER_FAMILY:
            total_possible = len(list(combinations(isolates_sorted, 2)))
            log(f"    {family}: {len(isolates)} isolates -> "
                f"{total_possible} possible pairs "
                f"({pair_count} with ratio>=0.5)")

    log(f"\n  Total comparisons to insert: {len(comparisons)}")
    log(f"  Families covered: {len(families_covered)}")
    log(f"  Species covered: {len(species_covered)}")

    # Insert into database
    if DRY_RUN:
        log("[DRY-RUN] Would insert these comparisons into genome_pairwise_identity")
        return {
            "families_analyzed": len(families_covered),
            "comparisons_computed": len(comparisons),
            "species_covered": len(species_covered),
            "method": "length_ratio",
            "dry_run": True,
        }

    if ARGS.skip_pairwise:
        log("  Skipped (--skip-pairwise)")
        return {
            "families_analyzed": len(families_covered),
            "comparisons_added": 0,
            "species_covered": len(species_covered),
            "skipped": True,
        }

    # Check if the existing table has the right columns
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(genome_pairwise_identity)")
    existing_cols = [row['name'] for row in cur.fetchall()]
    conn.close()

    has_length_cols = 'genome_length_a' in existing_cols and 'genome_length_b' in existing_cols

    # Insert in batches
    BATCH_SIZE = 500
    total_inserted = 0
    total_skipped_dup = 0

    for i in range(0, len(comparisons), BATCH_SIZE):
        batch = comparisons[i:i + BATCH_SIZE]

        for comp in batch:
            acc_a, acc_b, species, ratio, len_a, len_b = comp

            # Check if pair already exists (in either order)
            existing = query("""
                SELECT identity_id FROM genome_pairwise_identity
                WHERE (accession_a = ? AND accession_b = ?)
                   OR (accession_a = ? AND accession_b = ?)
            """, (acc_a, acc_b, acc_b, acc_a))

            if existing:
                total_skipped_dup += 1
                # Update with new method if existing is older k-mer approach
                execute("""
                    UPDATE genome_pairwise_identity
                    SET identity_percent = ?,
                        method = 'length_ratio_hybrid'
                    WHERE identity_id = ?
                """, (ratio * 100, existing[0]['identity_id']))
                continue

            # Insert new record
            try:
                execute("""
                    INSERT INTO genome_pairwise_identity
                        (accession_a, accession_b, virus_species, identity_percent, method)
                    VALUES (?, ?, ?, ?, 'length_ratio')
                """, (acc_a, acc_b, species, ratio * 100))
                total_inserted += 1
            except sqlite3.IntegrityError:
                total_skipped_dup += 1

        if (i + BATCH_SIZE) % 1000 == 0 or (i + BATCH_SIZE) >= len(comparisons):
            log(f"  Insert progress: {total_inserted} inserted, {total_skipped_dup} skipped")

    log(f"\n  Done: {total_inserted} new comparisons, {total_skipped_dup} skipped/updated")

    return {
        "families_analyzed": len(families_covered),
        "comparisons_added": total_inserted,
        "comparisons_skipped": total_skipped_dup,
        "species_covered": len(species_covered),
        "method": "length_ratio",
    }


# ===================================================================
# TASK C: Core gene / shared domain analysis by family
# ===================================================================
def task_c_core_gene_analysis() -> dict:
    """
    For isolates in the same family, analyze shared domain patterns
    and store as core_genes entries at the family level.

    Uses protein_domains (71K records) linked through viral_proteins -> viral_isolates -> virus_master.
    """
    log("\n" + "=" * 60)
    log("TASK C: Core gene / shared domain analysis by family")
    log("=" * 60)

    # Get domain presence per isolate per family
    # We look at: for each family, what domain_name values are present across isolates
    rows = query("""
        SELECT
            COALESCE(vm.virus_family, vi.taxon_family, 'Unassigned') AS family,
            vi.isolate_id,
            pd.domain_id,
            pd.domain_name,
            pd.domain_description,
            pd.domain_source,
            vp.protein_name,
            vp.gene_symbol
        FROM viral_proteins vp
        JOIN protein_domains pd ON vp.protein_id = pd.protein_id
        JOIN viral_isolates vi ON vp.isolate_id = vi.isolate_id
        LEFT JOIN virus_master vm ON vi.master_id = vm.master_id
        WHERE (vm.virus_family IS NOT NULL AND vm.virus_family != '' AND vm.virus_family != 'Dataset')
           OR (vi.taxon_family IS NOT NULL AND vi.taxon_family != '')
    """)

    log(f"  Loaded {len(rows)} domain-assigned protein records")

    # Group by family
    family_domains: dict[str, dict] = {}
    family_isolates: dict[str, set] = defaultdict(set)
    family_proteins: dict[str, set] = defaultdict(set)

    for r in rows:
        family = (r['family'] or 'Unassigned').strip()
        if family == '' or family == 'Dataset':
            continue

        if family not in family_domains:
            family_domains[family] = defaultdict(lambda: {
                'isolates': set(),
                'sources': set(),
                'descriptions': set(),
                'protein_names': set(),
            })

        domain_name = r['domain_name']
        if domain_name:
            family_domains[family][domain_name]['isolates'].add(r['isolate_id'])
            if r['domain_source']:
                family_domains[family][domain_name]['sources'].add(r['domain_source'])
            if r['domain_description']:
                family_domains[family][domain_name]['descriptions'].add(r['domain_description'])
            if r['protein_name']:
                family_domains[family][domain_name]['protein_names'].add(r['protein_name'])

        family_isolates[family].add(r['isolate_id'])
        if r['protein_name']:
            family_proteins[family].add(r['protein_name'])

    log(f"  Families with domain data: {len(family_domains)}")

    # Filter to families with >=3 isolates
    families_with_3 = {f: s for f, s in family_isolates.items() if len(s) >= 3}

    if ARGS.family:
        if ARGS.family in families_with_3:
            families_with_3 = {ARGS.family: families_with_3[ARGS.family]}
        else:
            log(f"  WARNING: Family '{ARGS.family}' not in domain data with >=3 isolates")
            return {"families_analyzed": 0, "core_domains_added": 0}

    log(f"  Families with >=3 isolates: {len(families_with_3)}")

    # Compute core domains for each family
    core_entries = []
    families_analyzed = 0

    for family, isolates_set in sorted(families_with_3.items(), key=lambda x: -len(x[1])):
        total_isolates = len(isolates_set)
        domains = family_domains[family]

        log(f"\n  [{family}] {total_isolates} isolates, {len(domains)} unique domains")

        # A "core" domain: use a two-tier threshold plus a top-N fallback
        threshold_50 = max(3, int(total_isolates * 0.50))
        threshold_75 = max(3, int(total_isolates * 0.75))

        core_50 = []
        core_75 = []

        for domain_name, info in sorted(domains.items(), key=lambda x: -len(x[1]['isolates'])):
            present = len(info['isolates'])
            conservation_rate = round(present / total_isolates, 4)

            if present >= threshold_75:
                core_75.append((domain_name, conservation_rate, present, info))
            elif present >= threshold_50:
                core_50.append((domain_name, conservation_rate, present, info))

        if core_75:
            log(f"    Core domains (>={threshold_75}+ isolates, 75% threshold):")
            for dn, cr, pres, info in core_75[:10]:
                desc = list(info['descriptions'])[0] if info['descriptions'] else ''
                log(f"      {dn:30s} {pres:3d}/{total_isolates} ({cr:.1%}) {desc[:40]}")
            if len(core_75) > 10:
                log(f"      ... and {len(core_75) - 10} more")

        # Create core_genes entries: all 75% domains + top 10 from 50% threshold
        # If neither has entries, include top 15 domains by absolute count
        domains_for_entry = core_75
        domains_for_entry += core_50[:10]

        if not domains_for_entry:
            # Fallback: take top 15 domains regardless of threshold
            for domain_name, info in sorted(domains.items(), key=lambda x: -len(x[1]['isolates']))[:15]:
                present = len(info['isolates'])
                conservation_rate = round(present / total_isolates, 4)
                domains_for_entry.append((domain_name, conservation_rate, present, info))
            log(f"    Fallback: top {len(domains_for_entry)} domains by presence count")

        for domain_name, conservation_rate, present_isolates, info in domains_for_entry:
            gene_symbol = domain_name[:100]
            protein_name = list(info['protein_names'])[0][:500] if info['protein_names'] else domain_name[:500]
            function_summary = list(info['descriptions'])[0] if info['descriptions'] else ''
            source = list(info['sources'])[0] if info['sources'] else 'domain_analysis'

            core_entries.append((
                family,
                gene_symbol,
                protein_name,
                'core_domain',
                conservation_rate,
                total_isolates,
                present_isolates,
                None,  # avg_identity - not computed here
                function_summary,
                'family',
                family,
            ))

        families_analyzed += 1
        if families_analyzed <= 5 or len(core_75) > 0:
            log(f"    -> {len(domains_for_entry)} core domain entries prepared")

    log(f"\n  Total core domain entries to add: {len(core_entries)}")
    log(f"  Families analyzed: {families_analyzed}")

    if DRY_RUN:
        log("[DRY-RUN] Would insert these core domain entries into core_genes")
        return {
            "families_analyzed": families_analyzed,
            "core_domains_computed": len(core_entries),
            "dry_run": True,
        }

    if ARGS.skip_core:
        log("  Skipped (--skip-core)")
        return {
            "families_analyzed": families_analyzed,
            "core_domains_added": 0,
            "skipped": True,
        }

    # Check existing entries to avoid duplicates
    existing_entries = query("SELECT virus_species, gene_symbol FROM core_genes WHERE taxonomic_level = 'family'")
    existing_set = set()
    for e in existing_entries:
        key = (str(e['virus_species'] or ''), str(e['gene_symbol'] or ''))
        existing_set.add(key)

    new_count = 0
    skip_count = 0

    for entry in core_entries:
        family_name, gene_symbol = entry[0], entry[1]
        if (family_name, gene_symbol) in existing_set:
            skip_count += 1
            continue

        try:
            execute("""
                INSERT INTO core_genes
                    (virus_species, gene_symbol, protein_name, functional_category,
                     conservation_rate, total_isolates, present_isolates,
                     avg_identity, function_summary, taxonomic_level, taxonomic_group)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, entry)
            new_count += 1
        except sqlite3.IntegrityError:
            skip_count += 1

    log(f"  Inserted: {new_count}, Skipped (duplicates): {skip_count}")

    return {
        "families_analyzed": families_analyzed,
        "core_domains_added": new_count,
        "core_domains_skipped": skip_count,
    }


# ===================================================================
# TASK D: Generate summary report
# ===================================================================
def task_d_generate_report(results: dict) -> str:
    """Generate genome comparison summary markdown report."""
    log("\n" + "=" * 60)
    log("TASK D: Generating comparison summary report")
    log("=" * 60)

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report_path = REPORT_DIR / "genome_comparison_summary.md"

    # Get current stats
    total_isolates = query("SELECT COUNT(*) as c FROM viral_isolates")[0]['c']
    with_seq = query("SELECT COUNT(*) as c FROM viral_isolates WHERE has_sequence=1")[0]['c']
    with_length = query("SELECT COUNT(*) as c FROM viral_isolates WHERE genome_length IS NOT NULL AND genome_length > 0")[0]['c']
    with_gc = query("SELECT COUNT(*) as c FROM viral_isolates WHERE gc_content IS NOT NULL")[0]['c']
    pairwise_count = query("SELECT COUNT(*) as c FROM genome_pairwise_identity")[0]['c']
    synteny_count = query("SELECT COUNT(*) as c FROM genome_synteny_blocks")[0]['c']
    core_count = query("SELECT COUNT(*) as c FROM core_genes")[0]['c']

    # Families with most pairwise comparisons
    top_pairwise = query("""
        SELECT virus_species, COUNT(*) as cnt,
               ROUND(AVG(identity_percent), 2) as avg_id
        FROM genome_pairwise_identity
        GROUP BY virus_species
        ORDER BY cnt DESC
        LIMIT 15
    """)

    # Families coverage
    family_coverage_gc = query("""
        SELECT COALESCE(vm.virus_family, vi.taxon_family, 'Unassigned') as family,
               COUNT(*) as total,
               SUM(CASE WHEN vi.gc_content IS NOT NULL THEN 1 ELSE 0 END) as with_gc,
               SUM(CASE WHEN vi.genome_length > 0 THEN 1 ELSE 0 END) as with_len
        FROM viral_isolates vi
        LEFT JOIN virus_master vm ON vi.master_id = vm.master_id
        WHERE vi.has_sequence = 1
        GROUP BY family
        ORDER BY total DESC
        LIMIT 20
    """)

    # Core genes by taxonomic level
    core_by_level = query("""
        SELECT taxonomic_level, COUNT(*) as cnt
        FROM core_genes
        GROUP BY taxonomic_level
        ORDER BY cnt DESC
    """)

    # Top families by core genes
    top_core_families = query("""
        SELECT taxonomic_group, COUNT(*) as cnt
        FROM core_genes
        WHERE taxonomic_level = 'family'
        GROUP BY taxonomic_group
        ORDER BY cnt DESC
        LIMIT 15
    """)

    # Compare methods used
    methods_used = query("""
        SELECT method, COUNT(*) as cnt
        FROM genome_pairwise_identity
        GROUP BY method
        ORDER BY cnt DESC
    """)

    # Build report
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    lines = []
    lines.append(f"# Genome Comparative Analysis Summary")
    lines.append(f"**Generated: {now}**")
    lines.append(f"")
    lines.append(f"## Overview")
    lines.append(f"")
    lines.append(f"| Metric | Value |")
    lines.append(f"|--------|-------|")
    lines.append(f"| Total viral isolates | {total_isolates} |")
    lines.append(f"| Has sequence | {with_seq} |")
    lines.append(f"| Has genome_length | {with_length} |")
    lines.append(f"| Has GC content | {with_gc} |")
    lines.append(f"| Pairwise identity records | {pairwise_count} |")
    lines.append(f"| Synteny blocks | {synteny_count} |")
    lines.append(f"| Core genes | {core_count} |")
    lines.append(f"")

    # Section: Expansion results
    lines.append(f"## Expansion Results (this run)")
    lines.append(f"")

    ta = results.get('task_a', {})
    tb = results.get('task_b', {})
    tc = results.get('task_c', {})

    if ta.get('candidates', 0) > 0:
        lines.append(f"### A. Genome Statistics Completion")
        lines.append(f"")
        lines.append(f"| Metric | Value |")
        lines.append(f"|--------|-------|")
        lines.append(f"| NCBI fetch candidates | {ta.get('candidates', 0)} |")
        lines.append(f"| GC content fetched | {ta.get('gc_fetched', 0)} |")
        lines.append(f"| Genome length fetched | {ta.get('length_fetched', 0)} |")
        lines.append(f"| NCBI API errors | {ta.get('errors', 0)} |")
        lines.append(f"")

    if tb.get('families_analyzed', 0) > 0:
        lines.append(f"### B. Pairwise Genome Size Comparisons")
        lines.append(f"")
        lines.append(f"| Metric | Value |")
        lines.append(f"|--------|-------|")
        lines.append(f"| Families analyzed | {tb.get('families_analyzed', 0)} |")
        lines.append(f"| New comparisons added | {tb.get('comparisons_added', 0)} |")
        lines.append(f"| Species covered | {tb.get('species_covered', 0)} |")
        lines.append(f"| Method | length_ratio |")
        lines.append(f"")

    if tc.get('families_analyzed', 0) > 0:
        lines.append(f"### C. Core Gene / Domain Analysis")
        lines.append(f"")
        lines.append(f"| Metric | Value |")
        lines.append(f"|--------|-------|")
        lines.append(f"| Families analyzed | {tc.get('families_analyzed', 0)} |")
        lines.append(f"| Core domain entries added | {tc.get('core_domains_added', 0)} |")
        lines.append(f"")

    # Section: Pairwise comparison methods
    lines.append(f"## Pairwise Identity Methods")
    lines.append(f"")
    lines.append(f"| Method | Count |")
    lines.append(f"|--------|-------|")
    for r in methods_used:
        lines.append(f"| {r['method']} | {r['cnt']} |")
    lines.append(f"")

    # Section: GC content coverage improvement
    lines.append(f"## GC Content Coverage")
    lines.append(f"")
    lines.append(f"| Family | Total Isolates | GC Available | Length Available |")
    lines.append(f"|--------|---------------|-------------|-----------------|")
    for r in family_coverage_gc:
        lines.append(f"| {r['family']} | {r['total']} | {r['with_gc']} | {r['with_len']} |")
    lines.append(f"")

    # Section: Top pairwise identities
    lines.append(f"## Top Species by Pairwise Comparisons")
    lines.append(f"")
    lines.append(f"| Species | Comparisons | Avg Identity % |")
    lines.append(f"|---------|-------------|----------------|")
    for r in top_pairwise:
        lines.append(f"| {r['virus_species']} | {r['cnt']} | {r['avg_id']} |")
    lines.append(f"")

    # Section: Core genes by level
    lines.append(f"## Core Genes by Taxonomic Level")
    lines.append(f"")
    lines.append(f"| Level | Count |")
    lines.append(f"|-------|-------|")
    for r in core_by_level:
        lines.append(f"| {r['taxonomic_level']} | {r['cnt']} |")
    lines.append(f"")

    # Section: Top families by core domains
    if top_core_families:
        lines.append(f"## Top Families by Core Domain Count")
        lines.append(f"")
        lines.append(f"| Family | Core Domains |")
        lines.append(f"|--------|-------------|")
        for r in top_core_families:
            lines.append(f"| {r['taxonomic_group']} | {r['cnt']} |")
        lines.append(f"")

    # Write report
    content = "\n".join(lines)

    if DRY_RUN:
        log(f"[DRY-RUN] Would write report to: {report_path}")
        return str(report_path)

    with open(str(report_path), 'w', encoding='utf-8') as f:
        f.write(content)
    log(f"  Report written: {report_path} ({len(content)} bytes)")

    return str(report_path)


# ===================================================================
# MAIN
# ===================================================================
def main():
    log("=" * 60)
    log("  Genome Comparative Analysis Expansion")
    log(f"  Database: {DB_PATH}")
    log(f"  Mode: {'DRY-RUN' if DRY_RUN else 'LIVE'}")
    if ARGS.family:
        log(f"  Family filter: {ARGS.family}")
    log("=" * 60)

    # Create backup
    backup_path = create_backup()

    results = {}

    # Task A: Genome statistics
    if not ARGS.skip_ncbi:
        results['task_a'] = task_a_complete_genome_stats()
    else:
        log("\n[TASK A] Skipped")
        results['task_a'] = {"skipped": True}

    # Task B: Pairwise comparisons
    if not ARGS.skip_pairwise:
        results['task_b'] = task_b_pairwise_comparisons()
    else:
        log("\n[TASK B] Skipped")
        results['task_b'] = {"skipped": True}

    # Task C: Core genes
    if not ARGS.skip_core:
        results['task_c'] = task_c_core_gene_analysis()
    else:
        log("\n[TASK C] Skipped")
        results['task_c'] = {"skipped": True}

    # Task D: Report
    report_path = task_d_generate_report(results)

    # Summary
    log("\n" + "=" * 60)
    log("  SUMMARY")
    log("=" * 60)

    ta = results.get('task_a', {})
    tb = results.get('task_b', {})
    tc = results.get('task_c', {})

    if not ta.get('skipped'):
        log(f"  A. Genome stats: {ta.get('total_updated', 0)} NCBI updates ({ta.get('errors', 0)} errors)")
    if not tb.get('skipped'):
        log(f"  B. Pairwise: {tb.get('comparisons_added', 0)} new comparisons across {tb.get('families_analyzed', 0)} families")
    if not tc.get('skipped'):
        log(f"  C. Core genes: {tc.get('core_domains_added', 0)} new domain entries across {tc.get('families_analyzed', 0)} families")
    log(f"  D. Report: {report_path}")
    log(f"  Backup: {backup_path if backup_path else 'none (dry-run)'}")
    log("=" * 60)

    return results


if __name__ == "__main__":
    main()
