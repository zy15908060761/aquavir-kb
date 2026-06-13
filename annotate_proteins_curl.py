#!/usr/bin/env python3
"""
P3: Protein functional annotation via NCBI CD-Search (curl-based, no Java).
- Uses curl to submit protein sequences to NCBI Conserved Domain Database
- Batch processing: 100 sequences per request
- Imports domain hits into protein_domains

Usage: python annotate_proteins_curl.py
"""
import sqlite3, json, subprocess, time, re
from pathlib import Path
from collections import Counter

DB_PATH = Path(r"F:\水生无脊椎动物数据库\crustacean_virus_core.db")
FASTA_DIR = Path(r"F:\水生无脊椎动物数据库\sequences")
LOG_DIR = Path(r"F:\水生无脊椎动物数据库\downloads")
CKPT_PATH = LOG_DIR / "cdd_annotation_checkpoint.json"

for d in [FASTA_DIR, LOG_DIR]:
    d.mkdir(parents=True, exist_ok=True)

UA = "Mozilla/5.0 AquaVir-KB/3.0"
TIMEOUT = 60
SLEEP = 1.0  # NCBI rate limit
BATCH_SIZE = 200


def curl_fetch(url, timeout=TIMEOUT):
    cmd = ["curl", "-sL", "--max-time", str(timeout), "-w", "%{http_code}", "-o", "-",
           "-H", f"User-Agent: {UA}", url]
    result = subprocess.run(cmd, capture_output=True, timeout=timeout + 15)
    raw = result.stdout
    if len(raw) >= 3:
        code = int(raw[-3:].decode().strip())
        body = raw[:-3]
        return code, body
    return 0, None


def load_ckpt():
    if CKPT_PATH.exists():
        return json.loads(CKPT_PATH.read_text(encoding="utf-8"))
    return {"done": [], "annotated": 0}


def save_ckpt(cp):
    CKPT_PATH.write_text(json.dumps(cp, ensure_ascii=False, indent=2), encoding="utf-8")


def get_unannotated_proteins():
    """Get proteins without any domain annotations, with valid accessions."""
    con = sqlite3.connect(str(DB_PATH), timeout=60)
    cur = con.cursor()

    # Proteins with GenBank accessions, no domains
    cur.execute("""
        SELECT vp.protein_id, vp.protein_name, vp.protein_accession, vp.translation, vp.aa_length
        FROM viral_proteins vp
        WHERE vp.protein_accession IS NOT NULL AND vp.protein_accession != ''
          AND vp.translation IS NOT NULL AND length(vp.translation) >= 30
          AND vp.protein_id NOT IN (SELECT DISTINCT protein_id FROM protein_domains WHERE protein_id IS NOT NULL)
        ORDER BY vp.aa_length DESC
    """)
    proteins = cur.fetchall()
    con.close()
    return proteins


def query_cdd_batch(accessions):
    """Batch query: send all accessions in one elink call, then batch esummary."""
    results = {}

    # Step 1: Batch elink — send all accessions at once (NCBI accepts up to 200)
    ids_str = ",".join(accessions)
    url = (f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/elink.fcgi?"
           f"dbfrom=protein&db=cdd&id={ids_str}&linkname=protein_cdd&retmode=json&idtype=acc")
    code, body = curl_fetch(url)
    if not body:
        return results

    try:
        data = json.loads(body.decode("utf-8"))
    except Exception:
        return results

    # Parse linksets: each linkset maps one protein accession → domain IDs
    acc_domain_map = {}  # acc → [domain_uid, ...]
    all_domain_ids = set()
    for ls in data.get("linksets", []):
        # The linkset doesn't directly give us the protein accession, but the order matches input
        # Actually, each linkset has 'ids' which are the input IDs
        for linksetdb in ls.get("linksetdbs", []):
            if linksetdb.get("linkname") == "protein_cdd":
                domain_uids = linksetdb.get("links", [])
                # The protein accession is in ls["ids"]
                for protein_id in ls.get("ids", []):
                    if protein_id not in acc_domain_map:
                        acc_domain_map[protein_id] = []
                    acc_domain_map[protein_id].extend(domain_uids)
                all_domain_ids.update(domain_uids)

    if not all_domain_ids:
        return results

    # Step 2: Batch esummary for all domain IDs (up to 500 at a time)
    domain_ids_list = list(all_domain_ids)
    domain_info = {}
    for i in range(0, len(domain_ids_list), 500):
        batch = domain_ids_list[i:i+500]
        dom_url = (f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi?"
                   f"db=cdd&id={','.join(str(d) for d in batch)}&retmode=json")
        code2, body2 = curl_fetch(dom_url)
        if body2:
            try:
                dom_data = json.loads(body2.decode("utf-8"))
                for uid, rec in dom_data.get("result", {}).items():
                    if uid == "uids":
                        continue
                    domain_info[uid] = {
                        "accession": rec.get("accession", ""),
                        "title": rec.get("title", "")[:200],
                    }
            except Exception:
                pass
        time.sleep(0.3)

    # Step 3: Assemble results
    for acc, domain_uids in acc_domain_map.items():
        results[acc] = []
        for uid in domain_uids[:10]:  # top 10 domains per protein
            if uid in domain_info:
                results[acc].append({
                    "accession": domain_info[uid]["accession"],
                    "title": domain_info[uid]["title"],
                    "uid": uid,
                })

    return results


def main():
    print("=" * 70)
    print("P3: PROTEIN ANNOTATION via NCBI CDD (curl, no Java)")
    print("=" * 70)

    cp = load_ckpt()
    proteins = get_unannotated_proteins()
    already_done = set(cp.get("done", []))
    proteins = [(pid, pn, pa, ps, pl) for pid, pn, pa, ps, pl in proteins if pid not in already_done]

    print(f"Unannotated proteins: {len(proteins):,}")
    print(f"Already processed: {len(already_done):,}")
    print()

    con = sqlite3.connect(str(DB_PATH), timeout=60)
    cur = con.cursor()

    stats = Counter()
    t0 = time.time()

    for batch_start in range(0, len(proteins), BATCH_SIZE):
        batch = proteins[batch_start:batch_start + BATCH_SIZE]
        accessions = [p[2] for p in batch if p[2]]
        protein_map = {p[2]: p for p in batch if p[2]}

        print(f"  Batch {batch_start//BATCH_SIZE + 1}: "
              f"{batch_start+1}-{min(batch_start+BATCH_SIZE, len(proteins))}/{len(proteins)} "
              f"({len(accessions)} accessions)...", end=" ", flush=True)

        results = query_cdd_batch(accessions)

        batch_new = 0
        for acc, domains in results.items():
            if acc not in protein_map:
                continue  # skip IDs returned by elink that aren't in our batch
            pid = protein_map[acc][0]
            for d in domains:
                try:
                    cur.execute("""INSERT OR IGNORE INTO protein_domains
                        (protein_id, domain_source, domain_name, domain_description,
                         interpro_id, confidence_score)
                        VALUES (?, 'NCBI_CDD', ?, ?, ?, 0.7)""",
                        (pid, d["title"][:100], d["title"][:200], d.get("accession", "")))
                    if cur.rowcount > 0:
                        batch_new += 1
                except Exception:
                    pass

            # Also store CDD accession as interpro_id for traceability
            cp["done"].append(pid)

        stats["batches"] += 1
        stats["new_domains"] += batch_new
        stats["proteins_processed"] += len(accessions)

        if batch_new:
            con.commit()

        cp["annotated"] = stats["new_domains"]
        save_ckpt(cp)

        elapsed = time.time() - t0
        rate = stats["proteins_processed"] / max(1, elapsed) * 60
        print(f"+{batch_new} domains | {stats['proteins_processed']}/{len(proteins)} proteins "
              f"| {rate:.0f}/min", flush=True)

        time.sleep(SLEEP)

    con.commit()
    con.close()

    # Final stats
    elapsed = time.time() - t0
    con2 = sqlite3.connect(str(DB_PATH), timeout=60)
    cur2 = con2.cursor()
    total_p = cur2.execute("SELECT COUNT(*) FROM viral_proteins").fetchone()[0]
    with_d = cur2.execute("SELECT COUNT(DISTINCT protein_id) FROM protein_domains").fetchone()[0]
    total_d = cur2.execute("SELECT COUNT(*) FROM protein_domains").fetchone()[0]
    con2.close()

    print(f"\n{'=' * 70}")
    print("COMPLETE")
    print(f"{'=' * 70}")
    print(f"  Time: {elapsed/60:.0f} min")
    print(f"  New domains: {stats['new_domains']:,}")
    print(f"  Proteins processed: {stats['proteins_processed']:,}")
    print(f"  Coverage: {with_d}/{total_p} = {with_d/total_p*100:.1f}%")
    print(f"  Total domains: {total_d:,}")


if __name__ == "__main__":
    main()
