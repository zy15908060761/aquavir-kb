"""
Enrich protein interaction data from STRING database.

STRING (https://string-db.org/) provides known and predicted protein-protein
interactions (PPI), including physical and functional associations.

For crustacean virus research, STRING can help identify:
  - Virus-virus protein interactions (e.g., structural proteins assembly)
  - Virus-host protein interactions (e.g., immune evasion targets)
  - Functional modules and pathways

Strategy:
  1. Get UniProt IDs from local uniprot_annotations
  2. Query STRING API for protein interaction networks
  3. Use STRING's "viral" species or map to host species
  4. Store interaction pairs in string_interactions table

Usage:
    python enrich_string.py                         # full run
    python enrich_string.py --limit 500              # process first N proteins
    python enrich_string.py --species 9606           # human host PPI (taxid 9606)
    python enrich_string.py --dry-run                # preview only
    python enrich_string.py --stats                  # coverage stats
"""

from __future__ import annotations

import json
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
CACHE_DIR = BASE_DIR / "external_data" / "string"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

STRING_API = "https://string-db.org/api/json"
RATE_LIMIT = 0.5

# Crustacean host STRING species IDs
# STRING uses NCBI Taxonomy IDs
CRUSTACEAN_HOST_TAXIDS = {
    "6669": "Penaeus vannamei (whiteleg shrimp)",
    "6685": "Penaeus monodon (giant tiger prawn)",
    "29920": "Macrobrachium rosenbergii (giant freshwater prawn)",
    "7207": "Drosophila melanogaster (model arthropod)",
    "9606": "Homo sapiens (for virus-human PPI)",
}


def create_tables(conn: sqlite3.Connection) -> None:
    """Create STRING interaction tables."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS string_interactions (
            interaction_id INTEGER PRIMARY KEY AUTOINCREMENT,
            protein_a TEXT NOT NULL,
            protein_b TEXT NOT NULL,
            protein_a_name TEXT,
            protein_b_name TEXT,
            combined_score REAL,
            neighborhood_score REAL,
            fusion_score REAL,
            cooccurrence_score REAL,
            coexpression_score REAL,
            experimental_score REAL,
            database_score REAL,
            textmining_score REAL,
            species_taxid INTEGER,
            source_uniprot_id TEXT,
            local_protein_id INTEGER,
            interaction_type TEXT DEFAULT 'functional',
            fetched_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (local_protein_id) REFERENCES viral_proteins(protein_id)
        );

        CREATE TABLE IF NOT EXISTS string_enrichment (
            enrichment_id INTEGER PRIMARY KEY AUTOINCREMENT,
            uniprot_id TEXT NOT NULL,
            species_taxid INTEGER,
            category TEXT,
            term TEXT,
            description TEXT,
            number_of_genes INTEGER,
            p_value REAL,
            fdr REAL,
            genes_json TEXT,
            fetched_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE INDEX IF NOT EXISTS idx_string_prot ON string_interactions(protein_a);
        CREATE INDEX IF NOT EXISTS idx_string_score ON string_interactions(combined_score);
        CREATE INDEX IF NOT EXISTS idx_string_uniprot ON string_interactions(source_uniprot_id);
    """)
    conn.commit()


def get_interaction_network(
    identifiers: list[str],
    species: int = 6669,
    required_score: int = 700,
) -> list[dict] | None:
    """Fetch STRING interaction network for a set of protein identifiers."""
    if not identifiers:
        return None

    ids_str = "%0d".join(identifiers)
    params = urllib.parse.urlencode({
        "identifiers": ids_str,
        "species": species,
        "required_score": required_score,
        "network_type": "functional",
    })

    url = f"{STRING_API}/network?{params}"
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "crustacean-virus-db-curation/1.0"},
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read().decode())
    except Exception as exc:
        print(f"  [warn] STRING API failed: {exc}")
        return None


def get_string_enrichment(
    identifiers: list[str],
    species: int = 6669,
) -> list[dict] | None:
    """Fetch functional enrichment for protein set."""
    if not identifiers:
        return None

    ids_str = "%0d".join(identifiers)
    params = urllib.parse.urlencode({
        "identifiers": ids_str,
        "species": species,
    })

    url = f"{STRING_API}/functional_annotation?{params}"
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "crustacean-virus-db-curation/1.0"},
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read().decode())
    except Exception as exc:
        print(f"  [warn] STRING enrichment API failed: {exc}")
        return None


def get_uniprot_ids(
    conn: sqlite3.Connection,
    limit: int | None = None,
) -> list[tuple[str, int | None]]:
    """Get UniProt IDs with local protein IDs."""
    limit_clause = f"LIMIT {limit}" if limit else ""
    rows = conn.execute(
        f"""
        SELECT DISTINCT u.uniprot_id, vp.protein_id
        FROM uniprot_annotations u
        LEFT JOIN viral_proteins vp ON u.ncbi_protein_acc = vp.protein_accession
        WHERE u.uniprot_id IS NOT NULL AND u.uniprot_id != ''
        {limit_clause}
        """
    ).fetchall()
    return [(r[0], r[1]) for r in rows]


def enrich_string(
    conn: sqlite3.Connection,
    dry_run: bool = False,
    limit: int | None = None,
    species: int | None = None,
) -> int:
    """Main STRING enrichment — use known crustacean host proteins from UniProt.

    Strategy change: STRING doesn't have good coverage for viral proteins,
    so we enrich host-pathogen interaction data by querying known host proteins.
    """
    # Get host species names
    hosts = conn.execute(
        "SELECT host_id, scientific_name FROM crustacean_hosts "
        "WHERE scientific_name IS NOT NULL AND scientific_name != ''"
    ).fetchall()

    print(f"[string] {len(hosts)} host species in database")

    # Key immune and cell-surface proteins commonly involved in virus entry/response
    # We'll query them in STRING for crustacean host species
    host_proteins = [
        ("Rab7", "Ras-related protein Rab7, involved in WSSV entry"),
        ("STAT", "Signal transducer and activator of transcription"),
        ("Toll", "Toll-like receptor, innate immunity"),
        ("Dorsal", "NF-kB transcription factor, innate immunity"),
        ("Crustin", "Antimicrobial peptide, crustacean immune defense"),
        ("ALF", "Anti-lipopolysaccharide factor"),
        ("Penaeidin", "Penaeidin antimicrobial peptide"),
        ("SRC", "Src kinase, WSSV entry co-receptor"),
        ("integrin", "Integrin, possible virus receptor"),
        ("proPO", "Prophenoloxidase, melanization immune response"),
        ("IMD", "Immune deficiency pathway protein"),
        ("STAT5B", "Signal transducer and activator of transcription 5B"),
        ("Calreticulin", "Calreticulin, chaperone protein"),
        ("HSP70", "Heat shock protein 70"),
        ("HSP90", "Heat shock protein 90"),
        ("Caspase", "Caspase, apoptosis pathway"),
        ("IAP", "Inhibitor of apoptosis protein"),
        ("Lectin", "C-type lectin, pathogen recognition"),
        ("LGBP", "Lipopolysaccharide and beta-1,3-glucan binding protein"),
        ("Dscam", "Down syndrome cell adhesion molecule, immune receptor"),
    ]

    target_species = list(CRUSTACEAN_HOST_TAXIDS.keys()) if species is None else [str(species)]

    inserted = 0
    for taxid_str in target_species:
        taxid = int(taxid_str)
        host_name = CRUSTACEAN_HOST_TAXIDS.get(taxid_str, f"taxid_{taxid}")
        print(f"  [string] querying {host_name} (taxid={taxid})...")

        for prot_name, prot_desc in host_proteins[:10] if dry_run else host_proteins:
            if dry_run:
                print(f"    [dry-run] {prot_name} @ {host_name}")
                continue

            # Use STRING network API with protein name as identifier
            network = get_interaction_network(
                [prot_name],
                taxid,
                required_score=700,
            )

            if network:
                for edge in network:
                    try:
                        conn.execute(
                            """
                            INSERT OR IGNORE INTO string_interactions
                                (protein_a, protein_b, protein_a_name, protein_b_name,
                                 combined_score, neighborhood_score, fusion_score,
                                 cooccurrence_score, coexpression_score, experimental_score,
                                 database_score, textmining_score, species_taxid, source_uniprot_id,
                                 interaction_type)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'host_immune')
                            """,
                            (
                                edge.get("preferredName_A", ""),
                                edge.get("preferredName_B", ""),
                                edge.get("proteinAnnotation_A", "") or prot_name,
                                edge.get("proteinAnnotation_B", "") or "",
                                edge.get("score"),
                                edge.get("nscore"),
                                edge.get("fscore"),
                                edge.get("pscore"),
                                edge.get("ascore"),
                                edge.get("escore"),
                                edge.get("dscore"),
                                edge.get("tscore"),
                                taxid,
                                prot_name,
                            ),
                        )
                        inserted += 1
                    except Exception:
                        pass
                conn.commit()

            time.sleep(RATE_LIMIT)

        time.sleep(RATE_LIMIT)

    # Also try enrichment for the protein sets
    print(f"[string] Inserted {inserted} host immune interactions")
    return inserted


def register_source(conn: sqlite3.Connection) -> None:
    """Register STRING in external_sources."""
    conn.execute(
        """
        INSERT INTO external_sources
            (source_key, name, category, base_url, description, update_policy, priority)
        VALUES ('string', 'STRING', 'protein_interaction',
                'https://string-db.org/',
                'Known and predicted protein-protein interactions for virus-host interaction analysis.',
                'api', 88)
        ON CONFLICT(source_key) DO UPDATE SET
            name = excluded.name,
            description = excluded.description,
            priority = excluded.priority,
            updated_at = CURRENT_TIMESTAMP
        """
    )
    conn.commit()


def show_stats(conn: sqlite3.Connection) -> None:
    """Print STRING integration stats."""
    print("\n=== STRING Integration Stats ===")
    row = conn.execute("SELECT COUNT(*) FROM string_interactions").fetchone()
    print(f"  Total interactions: {row[0]}")
    row = conn.execute("SELECT COUNT(DISTINCT protein_a) FROM string_interactions").fetchone()
    print(f"  Unique proteins A: {row[0]}")
    row = conn.execute("SELECT COUNT(*) FROM string_enrichment").fetchone()
    print(f"  Enrichment terms: {row[0]}")

    rows = conn.execute(
        "SELECT species_taxid, COUNT(*) as cnt FROM string_interactions "
        "GROUP BY species_taxid ORDER BY cnt DESC"
    ).fetchall()
    print("  By species:")
    for r in rows:
        print(f"    {r[0]} ({CRUSTACEAN_HOST_TAXIDS.get(str(r[0]), 'unknown')}) : {r[1]}")


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="Enrich protein interactions from STRING")
    parser.add_argument("--dry-run", action="store_true", help="Preview only")
    parser.add_argument("--limit", type=int, default=None, help="Process first N proteins")
    parser.add_argument("--species", type=int, default=None, help="STRING species taxid")
    parser.add_argument("--stats", action="store_true", help="Show stats only")
    args = parser.parse_args()

    conn = sqlite3.connect(str(DB_PATH))
    try:
        create_tables(conn)
        register_source(conn)

        if args.stats:
            show_stats(conn)
            return

        inserted = enrich_string(
            conn,
            dry_run=args.dry_run,
            limit=args.limit,
            species=args.species,
        )
        print(f"\n[done] STRING enrichment complete: {inserted} interactions")
        show_stats(conn)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
