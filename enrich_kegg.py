"""
Enrich viral protein annotations with KEGG pathway and orthology data.

KEGG (Kyoto Encyclopedia of Genes and Genomes, https://www.genome.jp/kegg/)
provides KEGG Orthology (KO), KEGG Pathway, and KEGG Enzyme annotations.

Strategy:
  1. Use KEGG REST API (https://rest.kegg.jp/) to link EC numbers to KO
  2. For each EC number found in local viral protein annotations, query KEGG
  3. Fetch KEGG pathway maps for virus-relevant pathways
  4. Also query KEGG GENES viral category for crustacean virus reference genes
  5. Store in kegg_annotations + kegg_pathways tables

Usage:
    python enrich_kegg.py                          # full run
    python enrich_kegg.py --dry-run                # preview only
    python enrich_kegg.py --limit 500              # process first N
    python enrich_kegg.py --stats                  # coverage stats
    python enrich_kegg.py --fetch-pathways         # also download pathway maps
"""

from __future__ import annotations

import json
import re
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "crustacean_virus_core.db"
CACHE_DIR = BASE_DIR / "external_data" / "kegg"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

KEGG_REST = "https://rest.kegg.jp"
RATE_LIMIT = 0.3  # seconds between requests
BATCH_SIZE = 10   # EC numbers per link query

# Virus-relevant KEGG pathway IDs
VIRUS_PATHWAYS = {
    "ko05164": "Influenza A",
    "ko05165": "Human papillomavirus infection",
    "ko05166": "Human T-cell leukemia virus 1 infection",
    "ko05167": "Kaposi sarcoma-associated herpesvirus infection",
    "ko05168": "Herpes simplex virus 1 infection",
    "ko05169": "Epstein-Barr virus infection",
    "ko05170": "Human immunodeficiency virus 1 infection",
    "ko05171": "Coronavirus disease - COVID-19",
    "ko03230": "Viral genome structure",
    "ko03250": "Viral life cycle - HIV-1",
    "ko03013": "Nucleocytoplasmic transport",
    "ko04144": "Endocytosis",
    "ko04145": "Phagosome",
    "ko04612": "Antigen processing and presentation",
    "ko04620": "Toll-like receptor signaling pathway",
    "ko04621": "NOD-like receptor signaling pathway",
    "ko04622": "RIG-I-like receptor signaling pathway",
    "ko04623": "Cytosolic DNA-sensing pathway",
}


def _kegg_rest(endpoint: str, timeout: int = 120) -> str | None:
    """Call KEGG REST API, return text response."""
    url = f"{KEGG_REST}/{endpoint}"
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "crustacean-virus-db-curation/1.0"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        print(f"  [warn] KEGG HTTP {exc.code} for {url}")
        return None
    except Exception as exc:
        print(f"  [warn] KEGG request failed: {exc}")
        return None


def link_ec_to_ko(ec_numbers: list[str]) -> dict[str, list[str]]:
    """Map EC numbers -> KO identifiers using KEGG LINK."""
    result: dict[str, list[str]] = {}
    if not ec_numbers:
        return result

    # Filter valid EC numbers
    valid_ec = []
    for ec in ec_numbers:
        ec_clean = ec.strip()
        if re.match(r'^\d+\.\d+\.\d+\.\d+$', ec_clean) or re.match(r'^\d+\.\d+\.\d+\.\w+$', ec_clean):
            valid_ec.append(ec_clean)
        elif re.match(r'^\d+\.\d+\.\d+\.-$', ec_clean) or re.match(r'^\d+\.\d+\.-$', ec_clean):
            valid_ec.append(ec_clean)

    if not valid_ec:
        return result

    # Process in batches
    for i in range(0, len(valid_ec), BATCH_SIZE):
        batch = valid_ec[i:i + BATCH_SIZE]
        ec_str = "+".join(batch)
        text = _kegg_rest(f"link/ko/ec:{ec_str}")
        if text:
            for line in text.strip().split("\n"):
                if "\t" in line:
                    parts = line.strip().split("\t")
                    ec_num = parts[0].replace("ec:", "")
                    ko_id = parts[1].replace("ko:", "")
                    if ec_num not in result:
                        result[ec_num] = []
                    result[ec_num].append(ko_id)
        time.sleep(RATE_LIMIT)

    return result


def get_ko_info(ko_ids: list[str]) -> dict[str, dict[str, str]]:
    """Fetch KO definition and name for KO identifiers."""
    result: dict[str, dict[str, str]] = {}
    if not ko_ids:
        return result

    for i in range(0, len(ko_ids), BATCH_SIZE):
        batch = ko_ids[i:i + BATCH_SIZE]
        ko_str = "+".join(batch)
        text = _kegg_rest(f"get/{ko_str}")
        if text:
            current_ko = None
            for line in text.strip().split("\n"):
                if line.startswith("ENTRY"):
                    current_ko = line.split()[1].strip()
                    result[current_ko] = {"ko_id": current_ko, "name": "", "definition": ""}
                elif current_ko and line.startswith("NAME"):
                    name = line.replace("NAME", "").strip()
                    result[current_ko]["name"] = name
                elif current_ko and line.startswith("DEFINITION"):
                    definition = line.replace("DEFINITION", "").strip()
                    result[current_ko]["definition"] = definition
        time.sleep(RATE_LIMIT)

    return result


def get_ko_pathways(ko_ids: list[str]) -> dict[str, list[dict[str, str]]]:
    """Link KO -> KEGG Pathways."""
    result: dict[str, list[dict[str, str]]] = {}
    if not ko_ids:
        return result

    for i in range(0, len(ko_ids), BATCH_SIZE):
        batch = ko_ids[i:i + BATCH_SIZE]
        ko_str = "+".join(batch)
        text = _kegg_rest(f"link/pathway/{ko_str}")
        if text:
            for line in text.strip().split("\n"):
                if "\t" in line:
                    parts = line.strip().split("\t")
                    ko_id = parts[0].replace("ko:", "")
                    path_id = parts[1].replace("path:", "")
                    if ko_id not in result:
                        result[ko_id] = []
                    result[ko_id].append({
                        "pathway_id": path_id,
                        "pathway_name": VIRUS_PATHWAYS.get(path_id, ""),
                    })
        time.sleep(RATE_LIMIT)

    return result


def fetch_virus_genes(search_term: str = "iridovirus") -> dict[str, dict[str, str]]:
    """Search KEGG GENES viral database for relevant entries."""
    result: dict[str, dict[str, str]] = {}
    text = _kegg_rest(f"find/genes/{urllib.parse.quote(search_term)}")
    if text:
        for line in text.strip().split("\n"):
            if "\t" in line:
                parts = line.strip().split("\t", 1)
                gene_id = parts[0]
                description = parts[1] if len(parts) > 1 else ""
                result[gene_id] = {"gene_id": gene_id, "description": description}
    return result


def create_tables(conn: sqlite3.Connection) -> None:
    """Create KEGG annotation tables."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS kegg_annotations (
            kegg_id INTEGER PRIMARY KEY AUTOINCREMENT,
            ncbi_protein_acc TEXT,
            uniprot_id TEXT,
            ec_number TEXT,
            ko_id TEXT,
            ko_name TEXT,
            ko_definition TEXT,
            protein_id INTEGER,
            fetched_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (protein_id) REFERENCES viral_proteins(protein_id)
        );

        CREATE TABLE IF NOT EXISTS kegg_pathways (
            pathway_id INTEGER PRIMARY KEY AUTOINCREMENT,
            kegg_pathway_id TEXT NOT NULL,
            pathway_name TEXT,
            pathway_description TEXT,
            category TEXT,
            ko_count INTEGER,
            fetched_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS kegg_protein_pathways (
            link_id INTEGER PRIMARY KEY AUTOINCREMENT,
            ko_id TEXT NOT NULL,
            kegg_pathway_id TEXT NOT NULL,
            protein_id INTEGER,
            ncbi_protein_acc TEXT,
            UNIQUE(ko_id, kegg_pathway_id, ncbi_protein_acc),
            FOREIGN KEY (protein_id) REFERENCES viral_proteins(protein_id)
        );

        CREATE INDEX IF NOT EXISTS idx_kegg_ec ON kegg_annotations(ec_number);
        CREATE INDEX IF NOT EXISTS idx_kegg_ko ON kegg_annotations(ko_id);
        CREATE INDEX IF NOT EXISTS idx_kegg_protein ON kegg_annotations(protein_id);
        CREATE INDEX IF NOT EXISTS idx_kegg_pathway_ko ON kegg_protein_pathways(ko_id);
    """)
    conn.commit()


def get_ec_numbers(conn: sqlite3.Connection, limit: int | None = None) -> list[tuple[int, str, str | None]]:
    """Get distinct EC numbers from viral proteins and UniProt annotations."""
    ec_set: dict[str, tuple[int, str, str | None]] = {}  # ec -> (protein_id, acc, uniprot_id)

    # From viral_proteins
    limit_clause = f"LIMIT {limit}" if limit else ""
    rows = conn.execute(
        f"""
        SELECT protein_id, protein_accession, ec_number
        FROM viral_proteins
        WHERE ec_number IS NOT NULL AND ec_number != '' AND ec_number != 'unknown'
        {limit_clause}
        """
    ).fetchall()
    for r in rows:
        for ec in re.split(r'[;,]', r[2]):
            ec = ec.strip()
            if ec and ec not in ec_set:
                ec_set[ec] = (r[0], r[1], None)

    # From UniProt annotations (EC numbers stored there too)
    rows = conn.execute(
        """
        SELECT ncbi_protein_acc, uniprot_id, ec_numbers
        FROM uniprot_annotations
        WHERE ec_numbers IS NOT NULL AND ec_numbers != ''
        """
    ).fetchall()
    for r in rows:
        for ec in re.split(r'[;,]', r[2]):
            ec = ec.strip()
            if ec and ec not in ec_set:
                ec_set[ec] = (-1, r[0], r[1])

    return [(ec, pid, acc, uid) for ec, (pid, acc, uid) in ec_set.items()]


def enrich_kegg(
    conn: sqlite3.Connection,
    dry_run: bool = False,
    limit: int | None = None,
    fetch_pathways: bool = False,
) -> int:
    """Main enrichment logic. Returns number of KO annotations added."""
    ec_entries = get_ec_numbers(conn, limit=limit)
    print(f"[kegg] Found {len(ec_entries)} unique EC numbers to query")

    if dry_run:
        for ec, pid, acc, uid in ec_entries[:20]:
            print(f"  [dry-run] EC={ec} protein={acc}")
        return 0

    # Step 1: Link EC -> KO
    ec_list = [e[0] for e in ec_entries]
    ec_to_ko = link_ec_to_ko(ec_list)
    print(f"[kegg] Mapped {len(ec_to_ko)} EC numbers to KO")

    # Step 2: Get KO info
    all_ko = set()
    for ko_list in ec_to_ko.values():
        all_ko.update(ko_list)
    print(f"[kegg] Found {len(all_ko)} unique KO identifiers")
    ko_info = get_ko_info(list(all_ko))
    print(f"[kegg] Fetched info for {len(ko_info)} KO entries")

    # Step 3: Store in database
    inserted = 0
    for ec, pid, acc, uid in ec_entries:
        if ec not in ec_to_ko:
            continue
        for ko_id in ec_to_ko[ec]:
            info = ko_info.get(ko_id, {})
            try:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO kegg_annotations
                        (ncbi_protein_acc, uniprot_id, ec_number, ko_id, ko_name, ko_definition, protein_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        acc,
                        uid,
                        ec,
                        ko_id,
                        info.get("name", ""),
                        info.get("definition", ""),
                        pid if pid > 0 else None,
                    ),
                )
                if conn.total_changes > 0:
                    inserted += 1
            except Exception:
                pass

    conn.commit()
    print(f"[kegg] Inserted {inserted} KO annotations")

    # Step 4: Fetch pathways (optional)
    if fetch_pathways:
        ko_to_pathways = get_ko_pathways(list(all_ko))
        print(f"[kegg] Mapped {len(ko_to_pathways)} KO to pathways")

        # Store pathways
        all_pathways = set()
        for p_list in ko_to_pathways.values():
            for p in p_list:
                all_pathways.add(p["pathway_id"])

        for path_id in all_pathways:
            path_name = VIRUS_PATHWAYS.get(path_id, "")
            conn.execute(
                """
                INSERT OR IGNORE INTO kegg_pathways
                    (kegg_pathway_id, pathway_name, category)
                VALUES (?, ?, 'viral')
                """,
                (path_id, path_name),
            )

        # Link proteins to pathways
        pathway_links = 0
        for ec, pid, acc, uid in ec_entries:
            if ec not in ec_to_ko:
                continue
            for ko_id in ec_to_ko[ec]:
                if ko_id not in ko_to_pathways:
                    continue
                for p in ko_to_pathways[ko_id]:
                    try:
                        conn.execute(
                            """
                            INSERT OR IGNORE INTO kegg_protein_pathways
                                (ko_id, kegg_pathway_id, protein_id, ncbi_protein_acc)
                            VALUES (?, ?, ?, ?)
                            """,
                            (ko_id, p["pathway_id"], pid if pid > 0 else None, acc),
                        )
                        if conn.total_changes > 0:
                            pathway_links += 1
                    except Exception:
                        pass

        conn.commit()
        print(f"[kegg] Inserted {pathway_links} protein-pathway links")

    # Also try to find KEGG GENES viral references
    print("[kegg] Searching KEGG GENES for crustacean virus references ...")
    virus_genes = {}
    for term in ["iridovirus", "white spot syndrome virus", "shrimp virus", "crab virus"]:
        genes = fetch_virus_genes(term)
        virus_genes.update(genes)
        time.sleep(RATE_LIMIT)
    print(f"[kegg] Found {len(virus_genes)} KEGG GENES entries")

    # Store virus gene references
    for gene_id, info in virus_genes.items():
        conn.execute(
            """
            INSERT OR IGNORE INTO kegg_annotations
                (ncbi_protein_acc, ko_id, ko_name)
            VALUES (?, ?, ?)
            """,
            (gene_id, gene_id, info.get("description", "")),
        )

    conn.commit()
    return inserted


def register_source(conn: sqlite3.Connection) -> None:
    """Register KEGG in external_sources."""
    conn.execute(
        """
        INSERT INTO external_sources
            (source_key, name, category, base_url, description, update_policy, priority)
        VALUES ('kegg', 'KEGG', 'protein_function',
                'https://www.genome.jp/kegg/',
                'KEGG Orthology, pathway maps, and enzyme annotations for viral proteins.',
                'api', 75)
        ON CONFLICT(source_key) DO UPDATE SET
            name = excluded.name,
            category = excluded.category,
            base_url = excluded.base_url,
            description = excluded.description,
            priority = excluded.priority,
            updated_at = CURRENT_TIMESTAMP
        """
    )
    conn.commit()


def show_stats(conn: sqlite3.Connection) -> None:
    """Print KEGG enrichment stats."""
    print("\n=== KEGG Integration Stats ===")
    row = conn.execute("SELECT COUNT(*) FROM kegg_annotations").fetchone()
    print(f"  KO annotations: {row[0]}")
    row = conn.execute("SELECT COUNT(DISTINCT ec_number) FROM kegg_annotations WHERE ec_number IS NOT NULL").fetchone()
    print(f"  Unique EC numbers mapped: {row[0]}")
    row = conn.execute("SELECT COUNT(DISTINCT ko_id) FROM kegg_annotations WHERE ko_id IS NOT NULL").fetchone()
    print(f"  Unique KO identifiers: {row[0]}")
    row = conn.execute("SELECT COUNT(*) FROM kegg_pathways").fetchone()
    print(f"  Pathways: {row[0]}")
    row = conn.execute("SELECT COUNT(*) FROM kegg_protein_pathways").fetchone()
    print(f"  Protein-pathway links: {row[0]}")

    rows = conn.execute(
        "SELECT ko_id, ko_name FROM kegg_annotations WHERE ko_name != '' LIMIT 10"
    ).fetchall()
    print("  Sample KO entries:")
    for r in rows:
        print(f"    {r[0]:15s} {r[1]}")


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="Enrich viral proteins with KEGG annotations")
    parser.add_argument("--dry-run", action="store_true", help="Preview only")
    parser.add_argument("--limit", type=int, default=None, help="Process first N proteins")
    parser.add_argument("--fetch-pathways", action="store_true", help="Download pathway maps")
    parser.add_argument("--stats", action="store_true", help="Show stats only")
    args = parser.parse_args()

    conn = sqlite3.connect(str(DB_PATH))
    try:
        create_tables(conn)
        register_source(conn)

        if args.stats:
            show_stats(conn)
            return

        inserted = enrich_kegg(
            conn,
            dry_run=args.dry_run,
            limit=args.limit,
            fetch_pathways=args.fetch_pathways,
        )
        print(f"\n[done] KEGG enrichment complete: {inserted} new annotations")
        show_stats(conn)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
