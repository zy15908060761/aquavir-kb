"""
CrustaVirus DB — Deep Annotation Pipeline (Multi-Phase Orchestrator)

Phase 1: InterPro domain/GO annotation via EBI Proteins API (proteins with UniProt IDs)
Phase 2: KEGG pathway linking (KO→pathway via KEGG REST API)
Phase 4: Literature evidence backfill (Europe PMC → evidence_records)
Phase 5: Rebuild protein_annotation_bridge

Usage:
  python run_deep_annotation_pipeline.py --phase 1 --limit 50     # test batch
  python run_deep_annotation_pipeline.py --phase 1                 # full run
  python run_deep_annotation_pipeline.py --phase 2                 # KEGG linking
  python run_deep_annotation_pipeline.py --phase 4 --limit 50      # lit backfill test
  python run_deep_annotation_pipeline.py --phase 5                 # rebuild bridge
  python run_deep_annotation_pipeline.py --audit                   # coverage audit only
"""
import json
import sqlite3
import time
import urllib.error
import urllib.request
import urllib.parse
import sys
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "crustacean_virus_core.db"
CACHE_DIR = BASE_DIR / "external_data" / "pipeline_cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

EBI_PROTEINS_API = "https://www.ebi.ac.uk/proteins/api/proteins"
KEGG_REST = "https://rest.kegg.jp"
EPMC_SEARCH = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"

RATE = 0.3
BATCH_SIZE = 100


def get_conn():
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")


# =====================================================================
# AUDIT
# =====================================================================
def audit(conn):
    """Report current annotation coverage."""
    c = conn.cursor()
    total_proteins = c.execute("SELECT COUNT(*) FROM viral_proteins").fetchone()[0]
    total_isolates = c.execute("SELECT COUNT(*) FROM viral_isolates").fetchone()[0]

    c.execute("""SELECT
        SUM(CASE WHEN has_uniprot = 1 THEN 1 ELSE 0 END) as uniprot,
        SUM(CASE WHEN has_interpro = 1 THEN 1 ELSE 0 END) as interpro,
        SUM(CASE WHEN has_interpro_go = 1 THEN 1 ELSE 0 END) as go,
        SUM(CASE WHEN has_kegg = 1 THEN 1 ELSE 0 END) as kegg,
        SUM(CASE WHEN has_structure = 1 THEN 1 ELSE 0 END) as structure,
        COUNT(*) as total
    FROM protein_annotation_bridge""")
    row = c.fetchone()
    bridge_total = row[5]

    c.execute("SELECT COUNT(*) FROM protein_structures")
    structure_rows = c.fetchone()[0]

    c.execute("SELECT COUNT(*) FROM interpro_annotations")
    interpro_rows = c.fetchone()[0]

    c.execute("SELECT COUNT(*) FROM kegg_pathways")
    kegg_pathways = c.fetchone()[0]

    c.execute("SELECT COUNT(*) FROM evidence_records")
    evidence = c.fetchone()[0]

    c.execute("SELECT COUNT(*) FROM ref_literatures")
    refs = c.fetchone()[0]

    print("=" * 60)
    print("ANNOTATION COVERAGE AUDIT")
    print("=" * 60)
    print(f"  Total proteins:               {total_proteins}")
    print(f"  Total isolates:               {total_isolates}")
    print(f"  Bridge records:               {bridge_total}")
    print(f"  UniProt links:                {row[0]} ({row[0]/max(bridge_total,1)*100:.1f}%)")
    print(f"  InterPro domains:             {row[1]} ({row[1]/max(bridge_total,1)*100:.1f}%)")
    print(f"  InterPro annotation rows:     {interpro_rows}")
    print(f"  GO terms:                     {row[2]} ({row[2]/max(bridge_total,1)*100:.1f}%)")
    print(f"  KEGG annotations:             {row[3]} ({row[3]/max(bridge_total,1)*100:.1f}%)")
    print(f"  KEGG pathway rows:            {kegg_pathways}")
    print(f"  Structure (bridge flag):      {row[4]} ({row[4]/max(bridge_total,1)*100:.1f}%)")
    print(f"  Structure rows:               {structure_rows}")
    print(f"  Evidence records:             {evidence}")
    print(f"  References:                   {refs}")
    print()

    # Proteins needing annotation (prioritize complete genomes)
    c.execute("""SELECT COUNT(*) FROM viral_isolates vi
                 JOIN protein_annotation_bridge pab ON vi.isolate_id = pab.isolate_id
                 WHERE vi.completeness = 'complete_genome' AND pab.has_interpro = 0""")
    complete_no_interpro = c.fetchone()[0]
    print(f"  Complete genome proteins missing InterPro: {complete_no_interpro}")

    c.execute("""SELECT COUNT(*) FROM viral_isolates vi
                 JOIN protein_annotation_bridge pab ON vi.isolate_id = pab.isolate_id
                 WHERE pab.has_uniprot = 1 AND pab.has_interpro = 0""")
    uniprot_no_interpro = c.fetchone()[0]
    print(f"  Proteins with UniProt but NO InterPro:     {uniprot_no_interpro}")

    return {
        "total_proteins": total_proteins,
        "uniprot": row[0], "interpro": row[1], "go": row[2],
        "kegg": row[3], "structure": row[4], "bridge_total": bridge_total,
        "interpro_rows": interpro_rows, "structure_rows": structure_rows,
        "kegg_pathways": kegg_pathways, "evidence": evidence, "refs": refs,
        "uniprot_no_interpro": uniprot_no_interpro,
    }


# =====================================================================
# PHASE 1: InterPro via EBI Proteins API
# =====================================================================
def phase1_interpro(conn, limit=None):
    """Fetch InterPro annotations for proteins with UniProt but no InterPro."""
    c = conn.cursor()
    c.execute("""SELECT DISTINCT pab.uniprot_id, pab.protein_id
        FROM protein_annotation_bridge pab
        WHERE pab.has_uniprot = 1 AND pab.has_interpro = 0
          AND pab.uniprot_id IS NOT NULL AND pab.uniprot_id != ''
        ORDER BY pab.protein_id""")
    candidates = c.fetchall()
    if limit:
        candidates = candidates[:limit]

    log(f"Phase 1: {len(candidates)} proteins to process (has UniProt, no InterPro)")

    processed = 0
    new_interpro = 0

    for i, (uniprot_id, protein_id) in enumerate(candidates):
        # Check cache
        cache_file = CACHE_DIR / "interpro" / f"{uniprot_id}.json"
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        data = None

        if cache_file.exists():
            try:
                data = json.loads(cache_file.read_text())
            except:
                pass

        if data is None:
            url = f"{EBI_PROTEINS_API}/{uniprot_id}"
            time.sleep(RATE)
            try:
                req = urllib.request.Request(url)
                req.add_header("Accept", "application/json")
                with urllib.request.urlopen(req, timeout=20) as resp:
                    data = json.loads(resp.read().decode())
                cache_file.write_text(json.dumps(data))
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    continue
                time.sleep(1)
                continue
            except Exception as e:
                continue

        # Parse features
        features = data.get("features", [])
        for feat in features:
            if feat.get("type") in ("DOMAIN", "REGION", "REPEAT", "MOTIF"):
                begin = feat.get("begin", "")
                end = feat.get("end", "")
                description = feat.get("description", "")
                interpro_id = None
                interpro_name = None
                source_db = feat.get("source", {}).get("name", "")

                # Extract InterPro cross-reference
                for xref in feat.get("xrefs", []):
                    if xref.get("database") == "InterPro":
                        interpro_id = xref.get("id", "")
                        interpro_name = xref.get("name", "")

                if interpro_id:
                    try:
                        c.execute("""INSERT OR IGNORE INTO interpro_annotations
                            (uniprot_id, interpro_id, interpro_name, interpro_type,
                             source_database, start_pos, end_pos, protein_id, fetched_at)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)""",
                            (uniprot_id, interpro_id, interpro_name or description,
                             feat.get("type"), source_db, begin, end, protein_id))
                        new_interpro += 1

                        # Extract GO terms
                        for xref in feat.get("xrefs", []):
                            if xref.get("database") == "GO":
                                go_id = xref.get("id", "")
                                go_name = xref.get("name", "")
                                go_ns = xref.get("properties", {}).get("GoNamespace", "")
                                if go_id:
                                    c.execute("""INSERT OR IGNORE INTO interpro_go_terms
                                        (protein_id, interpro_id, go_id, go_name,
                                         go_namespace, evidence_source, created_at)
                                        VALUES (?, ?, ?, ?, ?, 'InterPro_via_EBI_API', CURRENT_TIMESTAMP)""",
                                        (protein_id, interpro_id, go_id, go_name, go_ns))
                    except Exception:
                        pass

        processed += 1
        if processed % 50 == 0:
            conn.commit()
            log(f"  Phase 1 progress: {processed}/{len(candidates)} proteins, {new_interpro} new InterPro entries")

        # Log API query
        try:
            c.execute("""INSERT OR REPLACE INTO interpro_api_query_log
                (uniprot_id, query_ts, status) VALUES (?, CURRENT_TIMESTAMP, 'success')""",
                (uniprot_id,))
        except:
            pass

    conn.commit()
    log(f"Phase 1 complete: {processed} proteins processed, {new_interpro} InterPro entries added")
    return processed, new_interpro


# =====================================================================
# PHASE 2: KEGG Pathway Linking (KO → pathways)
# =====================================================================
def phase2_kegg_pathways(conn, limit=None):
    """Link existing KEGG KO IDs to pathways via KEGG REST API.
    Uses correct schema: kegg_pathways(pathway_id, kegg_pathway_id, pathway_name, ...)
                       kegg_protein_pathways(link_id, ko_id, kegg_pathway_id, protein_id, ...)
    """
    c = conn.cursor()

    # Get all unique KO IDs from kegg_annotations
    c.execute("SELECT DISTINCT ko_id FROM kegg_annotations WHERE ko_id IS NOT NULL AND ko_id != ''")
    ko_ids = [row[0] for row in c.fetchall()]
    if limit:
        ko_ids = ko_ids[:limit]

    log(f"Phase 2: {len(ko_ids)} unique KO IDs to link to pathways")

    pathway_cache = {}
    cache_file = CACHE_DIR / "kegg_pathway_cache.json"
    if cache_file.exists():
        try:
            pathway_cache = json.loads(cache_file.read_text())
        except:
            pass

    new_pathways = 0
    new_links = 0
    skipped = 0

    for i, ko_id in enumerate(ko_ids):
        if ko_id in pathway_cache:
            pathways = pathway_cache[ko_id]
        else:
            url = f"{KEGG_REST}/link/pathway/{ko_id}"
            time.sleep(0.5)
            try:
                req = urllib.request.Request(url)
                with urllib.request.urlopen(req, timeout=15) as resp:
                    text = resp.read().decode()
                pathways = []
                for line in text.strip().split("\n"):
                    if "\t" in line:
                        parts = line.strip().split("\t")
                        if len(parts) >= 2:
                            # Format: ko:K00525  path:map00010
                            pw_id = parts[1].replace("path:", "").replace("ko:", "")
                            if pw_id.startswith("map"):
                                pathways.append(pw_id)
                pathway_cache[ko_id] = pathways
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    pathway_cache[ko_id] = []
                else:
                    skipped += 1
                continue
            except Exception:
                skipped += 1
                continue

        if not pathways:
            continue

        # Get protein accessions for this KO
        c.execute("SELECT ncbi_protein_acc FROM kegg_annotations WHERE ko_id = ? AND ncbi_protein_acc IS NOT NULL", (ko_id,))
        acc_rows = c.fetchall()

        # Resolve ncbi_protein_acc → protein_id via bridge accession_root
        # kegg_annotations.ncbi_protein_acc = "XQJ32652.1"
        # protein_annotation_bridge.accession_root = "XQJ32652" (without version)
        protein_ids = set()
        for (acc,) in acc_rows:
            # Strip version number for matching
            acc_root = acc.split('.')[0] if '.' in acc else acc
            c.execute("SELECT DISTINCT protein_id FROM protein_annotation_bridge WHERE accession_root = ?", (acc_root,))
            for (pid,) in c.fetchall():
                if pid:
                    protein_ids.add(pid)

        if not protein_ids:
            continue

        for pw_id in pathways:
            kegg_pw_id = pw_id
            try:
                c.execute("""INSERT OR IGNORE INTO kegg_pathways
                    (pathway_id, kegg_pathway_id, pathway_name, category, fetched_at)
                    VALUES (?, ?, 'from KEGG REST API', 'auto_mapped', CURRENT_TIMESTAMP)""",
                    (kegg_pw_id, kegg_pw_id))
            except Exception:
                pass

            for pid in protein_ids:
                try:
                    c.execute("""INSERT OR IGNORE INTO kegg_protein_pathways
                        (ko_id, kegg_pathway_id, protein_id)
                        VALUES (?, ?, ?)""",
                        (ko_id, kegg_pw_id, pid))
                    new_links += 1
                except Exception:
                    pass

        new_pathways += 1
        if new_pathways % 20 == 0:
            conn.commit()
            log(f"  Phase 2 progress: {new_pathways}/{len(ko_ids)} KOs, {new_links} pathway links, {skipped} skipped")

    # Save cache
    try:
        cache_file.write_text(json.dumps(pathway_cache))
    except:
        pass

    conn.commit()
    log(f"Phase 2 complete: {new_pathways} KOs processed, {new_links} links, {skipped} skipped")
    return new_pathways, new_links


# =====================================================================
# PHASE 4: Literature Evidence Backfill
# =====================================================================
def phase4_literature_evidence(conn, limit=None):
    """Extract evidence claims from literature abstracts via Europe PMC."""
    c = conn.cursor()

    # Get references with DOI or PMID, with abstract data
    c.execute("""SELECT reference_id, title, authors, journal, year, pmid, doi
        FROM ref_literatures
        WHERE (doi IS NOT NULL AND doi != '') OR (pmid IS NOT NULL AND pmid != '')
        ORDER BY reference_id""")
    refs = [dict(zip(["reference_id", "title", "authors", "journal", "year", "pmid", "doi"], row))
            for row in c.fetchall()]
    if limit:
        refs = refs[:limit]

    log(f"Phase 4: Processing {len(refs)} references for evidence extraction")

    # Get virus names for keyword matching
    c.execute("SELECT master_id, canonical_name, abbreviations FROM virus_master")
    virus_map = {row[0]: (row[1], row[2]) for row in c.fetchall()}

    # Get host names
    c.execute("SELECT host_id, scientific_name FROM crustacean_hosts")
    host_names = [row[1] for row in c.fetchall()]

    new_evidence = 0
    for i, ref in enumerate(refs):
        query = ref["doi"] or ref["pmid"]
        if not query:
            continue

        # Fetch abstract from Europe PMC
        if query.startswith("10."):
            epmc_query = f"DOI:{query}"
        else:
            epmc_query = f"EXT_ID:{query}"

        params = {"query": epmc_query, "format": "json", "resultType": "core", "pageSize": 2}
        qs = urllib.parse.urlencode(params)
        url = f"{EPMC_SEARCH}?{qs}"
        time.sleep(0.3)

        abstract = ""
        try:
            req = urllib.request.Request(url)
            req.add_header("User-Agent", "CrustaVirusDB/1.0")
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode())
            results = data.get("resultList", {}).get("result", [])
            if results:
                abstract = results[0].get("abstractText", "") or ""
        except:
            continue

        if not abstract:
            continue

        abstract_lower = abstract.lower()

        # Virus matching with partial name fallback
        for master_id, (canonical_name, abbreviations) in virus_map.items():
            if not canonical_name:
                continue
            vname_lower = canonical_name.lower()
            matched = False
            if len(vname_lower) > 4 and vname_lower in abstract_lower:
                matched = True
            # Partial match for multi-word names (e.g., "white spot" from "white spot syndrome virus")
            elif " " in vname_lower:
                parts = vname_lower.split()
                short_name = " ".join(parts[:2])
                if len(short_name) > 5 and short_name in abstract_lower:
                    matched = True

            if not matched:
                continue

            # Check for evidence keywords mapped to DB-valid enum values
            evidence_types = []
            if any(w in abstract_lower for w in ["mortality", "death", "die", "lethal", "survival rate"]):
                evidence_types.append("mortality")
            if any(w in abstract_lower for w in ["pathogenic", "virulen", "pathogenicity"]):
                evidence_types.append("pathogenicity")
            if any(w in abstract_lower for w in ["outbreak", "epidemic", "mass mortality"]):
                evidence_types.append("outbreak")
            if any(w in abstract_lower for w in ["transmission", "vector", "carrier", "horizontal", "vertical"]):
                evidence_types.append("transmission")
            if any(w in abstract_lower for w in ["temperature", "thermal", "heat", "cold", "water temperature"]):
                evidence_types.append("temperature")
            if any(w in abstract_lower for w in ["detection", "PCR", "diagnostic", "diagnosis", "assay", "RT-PCR"]):
                evidence_types.append("diagnosis")
            if any(w in abstract_lower for w in ["infection", "infected", "disease"]):
                evidence_types.append("natural_infection")
            if any(w in abstract_lower for w in ["host range", "susceptible", "experimental infection"]):
                evidence_types.append("host_range")

            if not evidence_types:
                continue

            # Create evidence records with correct schema
            for etype in set(evidence_types):
                try:
                    c.execute("""INSERT INTO evidence_records
                        (reference_id, virus_master_id, evidence_type, claim,
                         extraction_method, curation_status, evidence_strength,
                         source_doi, created_at)
                        VALUES (?, ?, ?, ?, 'auto_extracted_epmc_abstract',
                         'needs_review', 'medium', ?, CURRENT_TIMESTAMP)""",
                        (ref["reference_id"], master_id, etype,
                         f"Auto-extracted: {etype} in '{ref.get('title','')[:200]}'",
                         ref.get("doi")))
                    new_evidence += 1
                except Exception:
                    pass

        if (i + 1) % 50 == 0:
            conn.commit()
            log(f"  Phase 4 progress: {i+1}/{len(refs)} refs, {new_evidence} new evidence records")

    conn.commit()
    log(f"Phase 4 complete: {len(refs)} refs processed, {new_evidence} evidence records created")
    return len(refs), new_evidence


# =====================================================================
# PHASE 5: Rebuild Annotation Bridge
# =====================================================================
def phase5_rebuild_bridge(conn):
    """Rebuild annotation bridge with all current annotation counts."""
    log("Phase 5: Rebuilding protein_annotation_bridge...")
    c = conn.cursor()

    # Update all annotation flags
    c.execute("""UPDATE protein_annotation_bridge SET
        has_interpro = CASE WHEN protein_id IN (SELECT DISTINCT protein_id FROM interpro_annotations) THEN 1 ELSE 0 END,
        interpro_count = (SELECT COUNT(*) FROM interpro_annotations ia WHERE ia.protein_id = protein_annotation_bridge.protein_id),
        has_interpro_go = CASE WHEN protein_id IN (SELECT DISTINCT protein_id FROM interpro_go_terms) THEN 1 ELSE 0 END,
        go_count = (SELECT COUNT(*) FROM interpro_go_terms igt WHERE igt.protein_id = protein_annotation_bridge.protein_id),
        has_kegg = CASE WHEN protein_id IN (SELECT DISTINCT protein_id FROM kegg_protein_pathways) THEN 1 ELSE 0 END,
        kegg_ko_count = (SELECT COUNT(DISTINCT ko_id) FROM kegg_protein_pathways kpp WHERE kpp.protein_id = protein_annotation_bridge.protein_id),
        has_structure = CASE WHEN protein_id IN (SELECT DISTINCT protein_id FROM protein_structures) THEN 1 ELSE 0 END,
        structure_count = (SELECT COUNT(*) FROM protein_structures ps WHERE ps.protein_id = protein_annotation_bridge.protein_id),
        updated_at = CURRENT_TIMESTAMP""")
    bridge_updated = c.rowcount
    conn.commit()
    log(f"Phase 5 complete: {bridge_updated} bridge records updated")
    return bridge_updated


# =====================================================================
# MAIN
# =====================================================================
def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", type=int, default=0, help="Phase to run (1-5, 0=all)")
    ap.add_argument("--limit", type=int, default=None, help="Limit processing to N items")
    ap.add_argument("--audit", action="store_true", help="Run coverage audit only")
    args = ap.parse_args()

    conn = get_conn()

    if args.audit:
        audit(conn)
        conn.close()
        return

    results = {}

    if args.phase == 0 or args.phase == 1:
        log("=" * 40)
        log("PHASE 1: InterPro annotation via EBI API")
        log("=" * 40)
        processed, new_ip = phase1_interpro(conn, limit=args.limit)
        results["phase1"] = {"processed": processed, "new_interpro": new_ip}

    if args.phase == 0 or args.phase == 2:
        log("=" * 40)
        log("PHASE 2: KEGG pathway linking")
        log("=" * 40)
        n_kos, n_links = phase2_kegg_pathways(conn, limit=args.limit)
        results["phase2"] = {"ko_processed": n_kos, "pathway_links": n_links}

    if args.phase == 0 or args.phase == 4:
        log("=" * 40)
        log("PHASE 4: Literature evidence backfill")
        log("=" * 40)
        n_refs, n_evidence = phase4_literature_evidence(conn, limit=args.limit)
        results["phase4"] = {"refs_processed": n_refs, "new_evidence": n_evidence}

    if args.phase == 0 or args.phase == 5:
        log("=" * 40)
        log("PHASE 5: Rebuild annotation bridge")
        log("=" * 40)
        updated = phase5_rebuild_bridge(conn)
        results["phase5"] = {"bridge_updated": updated}

    # Final audit
    log("=" * 40)
    log("FINAL AUDIT")
    log("=" * 40)
    audit(conn)

    conn.close()

    # Save results
    out_path = BASE_DIR / "pipeline_results.json"
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    log(f"Results written to {out_path}")


if __name__ == "__main__":
    main()
