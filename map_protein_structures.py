#!/usr/bin/env python3
"""P3-9: Map viral proteins to PDB/AlphaFold structures via UniProt API."""
import sqlite3, json, urllib.request, time, argparse
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent
DB = BASE / "crustacean_virus_core.db"
RATE = 0.5  # UniProt API: allow generous rate limit

def fetch_uniprot(uniprot_id: str) -> dict | None:
    """Fetch UniProt entry and extract PDB cross-references."""
    url = f"https://rest.uniprot.org/uniprotkb/{uniprot_id}.json"
    req = urllib.request.Request(url, headers={"User-Agent": "AquaVir-KB/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.loads(r.read())
            # Extract PDB references
            pdb_refs = []
            for ref in data.get("uniProtKBCrossReferences", []):
                if ref.get("database") == "PDB":
                    pdb_refs.append({
                        "pdb_id": ref.get("id", ""),
                        "method": next((p.get("value") for p in ref.get("properties", [])
                                       if p.get("key") == "Method"), ""),
                        "resolution": next((p.get("value") for p in ref.get("properties", [])
                                           if p.get("key") == "Resolution"), ""),
                        "chains": next((p.get("value") for p in ref.get("properties", [])
                                       if p.get("key") == "Chains"), ""),
                    })
            return {
                "uniprot_id": uniprot_id,
                "protein_name": data.get("proteinDescription", {}).get("recommendedName", {}).get("fullName", {}).get("value", ""),
                "length": data.get("sequence", {}).get("length", 0),
                "pdb_refs": pdb_refs,
                "alphafold_url": f"https://alphafold.ebi.ac.uk/entry/{uniprot_id}",
            }
    except Exception as e:
        return None


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--limit", type=int, default=200, help="Max proteins to query")
    args = p.parse_args()

    conn = sqlite3.connect(str(DB))
    conn.row_factory = sqlite3.Row

    # Check current structure coverage
    struct_count = conn.execute("SELECT COUNT(*) FROM protein_structures").fetchone()[0]
    uniprot_struct = conn.execute("SELECT COUNT(*) FROM uniprot_structures").fetchone()[0]
    print(f"Current protein_structures: {struct_count}")
    print(f"Current uniprot_structures: {uniprot_struct}")

    # Get priority proteins: RdRp and structural proteins that have uniprot links
    candidates = conn.execute("""
        SELECT vp.protein_id, vp.protein_accession, vp.protein_name,
               vp.functional_category, upl.uniprot_id
        FROM viral_proteins vp
        JOIN uniprot_protein_links upl ON vp.protein_id = upl.protein_id
        WHERE vp.functional_category IN ('RdRP', 'structural')
          AND vp.protein_accession IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM protein_structures ps WHERE ps.protein_id = vp.protein_id
          )
        ORDER BY CASE WHEN vp.functional_category = 'RdRP' THEN 0 ELSE 1 END,
                 vp.aa_length DESC
        LIMIT ?
    """, (args.limit,)).fetchall()

    print(f"Candidates for structure mapping: {len(candidates)}")

    if args.dry_run:
        print(f"\n[DRY RUN] Would query {len(candidates)} proteins")
        for c in candidates[:10]:
            print(f"  {c['uniprot_id']}: {c['protein_name'][:60]} ({c['functional_category']})")
        conn.close()
        return

    # Fetch UniProt data
    mapped = 0
    pdb_total = 0
    cur = conn.cursor()
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    for i, c in enumerate(candidates):
        if not c['uniprot_id']:
            continue

        data = fetch_uniprot(c['uniprot_id'])
        time.sleep(RATE)
        if not data:
            continue

        # Insert PDB structures
        for pdb in data['pdb_refs']:
            try:
                cur.execute("""
                    INSERT OR IGNORE INTO protein_structures
                        (protein_id, structure_source, structure_id, confidence, url, created_at)
                    VALUES (?, 'PDB', ?, ?, ?, ?)
                """, (
                    c['protein_id'], pdb['pdb_id'],
                    float(pdb['resolution']) if pdb['resolution'] and pdb['resolution'].replace('.','').isdigit() else None,
                    f"https://www.rcsb.org/structure/{pdb['pdb_id']}",
                    ts
                ))
                if cur.lastrowid:
                    pdb_total += 1
            except:
                pass

        # Insert AlphaFold reference
        if data['alphafold_url']:
            try:
                cur.execute("""
                    INSERT OR IGNORE INTO protein_structures
                        (protein_id, structure_source, structure_id, confidence, url, created_at)
                    VALUES (?, 'AlphaFold', ?, NULL, ?, ?)
                """, (
                    c['protein_id'], data['uniprot_id'],
                    data['alphafold_url'], ts
                ))
                if cur.lastrowid:
                    mapped += 1
            except:
                pass

        if mapped > 0 and mapped % 50 == 0:
            conn.commit()
            print(f"  {mapped} AlphaFold + {pdb_total} PDB mapped...")

    conn.commit()

    new_struct = conn.execute("SELECT COUNT(*) FROM protein_structures").fetchone()[0]
    print(f"\n[Done]")
    print(f"  PDB structures mapped: {pdb_total}")
    print(f"  AlphaFold references mapped: {mapped}")
    print(f"  Total protein_structures now: {new_struct}")

    # Category breakdown
    for row in conn.execute("""
        SELECT vp.functional_category, COUNT(*) as n
        FROM protein_structures ps
        JOIN viral_proteins vp ON ps.protein_id = vp.protein_id
        GROUP BY vp.functional_category ORDER BY n DESC
    """):
        print(f"  {row['functional_category']}: {row['n']} structures")

    conn.close()

if __name__ == "__main__":
    main()
