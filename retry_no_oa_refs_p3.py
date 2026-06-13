#!/usr/bin/env python3
"""
P3: Attempt to recover downloads for 'no_oa' refs.
Strategy:
  1. Re-check OA journal refs (Frontiers, Viruses, PLOS, BMC, etc.) — these should be OA
  2. For no_oa refs WITH PMIDs (1,913), batch PMID→PMCID and download via PMC OA
  3. For remaining, attempt Unpaywall + Semantic Scholar fresh lookups
"""
import json, sqlite3, time, urllib.request, urllib.error
from pathlib import Path
from datetime import datetime
from collections import Counter

DB_PATH = Path(r"F:\水生无脊椎动物数据库\crustacean_virus_core.db")
PROJECT_DIR = Path(r"F:\水生无脊椎动物数据库")
LIT_DIR = PROJECT_DIR / "literature_curation_v2"
PMC_XML_DIR = LIT_DIR / "pmc_xml"
FULLTEXT_DIR = LIT_DIR / "fulltext"
OA_DIR = LIT_DIR / "oa_fulltext"
LOG_DIR = PROJECT_DIR / "downloads" / "p3_logs"

for d in [PMC_XML_DIR, FULLTEXT_DIR, OA_DIR, LOG_DIR]:
    d.mkdir(parents=True, exist_ok=True)

CHECKPOINT_PATH = LOG_DIR / "p3_checkpoint.json"
UA = "AquaVir-KB/2.0 (mailto:crustacean-db@proton.me)"
TIMEOUT = 45
SLEEP = 0.6

# Known fully-OA journals that may have been misclassified
OA_JOURNAL_PATTERNS = [
    "Frontiers in", "Viruses", "PLOS", "mBio", "eLife",
    "BMC", "Scientific Reports", "Nature Communications",
    "PeerJ", "mSystems", "Microbiome", "Biomedicines",
    "International Journal of Molecular Sciences", "IJMS",
    "Marine Drugs", "Biology", "Microorganisms", "Pathogens",
    "Cells", "Antioxidants", "Toxins", "Vaccines", "Pharmaceutics",
    "eLife", "Journal of Visualized Experiments", "JoVE",
]


def load_cp():
    if CHECKPOINT_PATH.exists():
        return json.loads(CHECKPOINT_PATH.read_text(encoding="utf-8"))
    return {"done": [], "still_no_oa": [], "pmcid_map": {}}


def save_cp(cp):
    CHECKPOINT_PATH.write_text(json.dumps(cp, ensure_ascii=False, indent=2), encoding="utf-8")


def get_no_oa_refs():
    con = sqlite3.connect(str(DB_PATH), timeout=60)
    con.row_factory = sqlite3.Row
    cp = load_cp()
    already = set(cp.get("done", [])) | set(cp.get("still_no_oa", []))
    cur = con.execute("""
        SELECT DISTINCT lfs.reference_id, lfs.pmid, lfs.doi,
               rl.title, rl.journal, rl.year
        FROM literature_fulltext_sources lfs
        JOIN ref_literatures rl ON lfs.reference_id = rl.reference_id
        WHERE lfs.status = 'no_oa'
        ORDER BY rl.year DESC
    """)
    refs = [dict(r) for r in cur.fetchall() if r["reference_id"] not in already]
    con.close()
    return refs


def is_oa_journal(journal_name):
    """Check if journal is a known OA journal (likely misclassified)."""
    if not journal_name:
        return False
    jl = journal_name.lower()
    for pat in OA_JOURNAL_PATTERNS:
        if pat.lower() in jl:
            return True
    return False


def batch_pmid_to_pmcid(pmids):
    """Batch convert PMIDs to PMCIDs."""
    results = {}
    for i in range(0, len(pmids), 200):
        batch = pmids[i:i+200]
        ids_str = ",".join(str(p) for p in batch if p)
        url = f"https://www.ncbi.nlm.nih.gov/pmc/utils/idconv/v1.0/?ids={ids_str}&format=json&tool=AquaVirKB&email=crustacean-db@proton.me"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            for rec in data.get("records", []):
                pmid = rec.get("pmid")
                pmcid = rec.get("pmcid")
                if pmid and pmcid:
                    results[str(pmid)] = pmcid
        except Exception as e:
            print(f"  Batch PMID error: {e}")
        time.sleep(0.3)
    return results


def download_pmc(pmcid, content_type="xml"):
    """Download from PMC OA."""
    if content_type == "xml":
        url = f"https://www.ncbi.nlm.nih.gov/research/bionlp/RESTful/pmcoa.cgi/BioC_xml/{pmcid}/unicode"
    else:
        url = f"https://www.ncbi.nlm.nih.gov/pmc/articles/{pmcid}/pdf/main.pdf"

    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            content = resp.read()
        if len(content) > 500:
            ext = "xml" if content_type == "xml" else "pdf"
            path = (PMC_XML_DIR if ext == "xml" else FULLTEXT_DIR) / f"{pmcid}_PMC.{ext}"
            path.write_bytes(content)
            return str(path)
    except Exception:
        pass
    return None


def download_unpaywall(doi):
    if not doi:
        return None
    try:
        url = f"https://api.unpaywall.org/v2/{doi}?email=crustacean-db@proton.me"
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        best = data.get("best_oa_location")
        if best and best.get("url_for_pdf"):
            req2 = urllib.request.Request(best["url_for_pdf"], headers={"User-Agent": UA})
            with urllib.request.urlopen(req2, timeout=TIMEOUT) as resp2:
                content = resp2.read()
            if len(content) > 5000:
                clean = doi.replace("/", "_").replace(".", "_")[:80]
                path = OA_DIR / f"{clean}_unpaywall.pdf"
                path.write_bytes(content)
                return str(path)
    except Exception:
        pass
    return None


def download_s2(doi):
    if not doi:
        return None
    try:
        url = f"https://api.semanticscholar.org/graph/v1/paper/DOI:{doi}?fields=openAccessPdf"
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        oa = data.get("openAccessPdf")
        if oa and oa.get("url"):
            req2 = urllib.request.Request(oa["url"], headers={"User-Agent": UA})
            with urllib.request.urlopen(req2, timeout=TIMEOUT) as resp2:
                content = resp2.read()
            if len(content) > 5000:
                clean = doi.replace("/", "_").replace(".", "_")[:80]
                path = OA_DIR / f"{clean}_s2.pdf"
                path.write_bytes(content)
                return str(path)
    except Exception:
        pass
    return None


def update_db(con, ref_id, status, source, local_path=None, content_type=None):
    con.execute("""
        UPDATE literature_fulltext_sources
        SET status = ?, source = ?, local_path = ?, content_type = ?
        WHERE reference_id = ? AND status = 'no_oa'
    """, (status, source, local_path, content_type, ref_id))


def main():
    print("=" * 70)
    print("P3: Recovering 'no_OA' Refs (OA Journal Check + PMC + Unpaywall + S2)")
    print("=" * 70)

    con = sqlite3.connect(str(DB_PATH), timeout=60)
    con.row_factory = sqlite3.Row

    refs = get_no_oa_refs()
    print(f"No-OA refs to retry: {len(refs)}")

    # Count OA journal refs
    oa_journal_refs = [r for r in refs if is_oa_journal(r["journal"])]
    print(f"Of which from known-OA journals: {len(oa_journal_refs)}")

    cp = load_cp()

    # Phase 0: Batch PMID→PMCID conversion for all no_oa refs with PMIDs
    refs_with_pmid = [(r["pmid"], r["doi"]) for r in refs if r["pmid"]]
    pmids_new = [str(p) for p, d in refs_with_pmid if p and str(p) not in cp.get("pmcid_map", {})]

    if pmids_new:
        print(f"Phase 0: Converting {len(pmids_new)} PMIDs to PMCIDs...")
        new_map = batch_pmid_to_pmcid(pmids_new)
        if "pmcid_map" not in cp:
            cp["pmcid_map"] = {}
        cp["pmcid_map"].update(new_map)
        save_cp(cp)
        print(f"  Got {len(new_map)} new PMCIDs (total: {len(cp['pmcid_map'])})")

    pmcid_map = cp.get("pmcid_map", {})

    stats = Counter()
    t0 = time.time()

    for i, ref in enumerate(refs):
        ref_id = ref["reference_id"]
        pmid = str(ref["pmid"]) if ref["pmid"] else ""
        doi = ref["doi"] or ""
        journal = ref["journal"] or ""

        local_path = None
        source = "p3"
        content_type = None

        # Strategy depends on journal type
        oa_journal = is_oa_journal(journal)

        # Channel 1: PMC OA via PMID→PMCID (works for any journal)
        pmcid = pmcid_map.get(pmid) if pmid else None
        if pmcid:
            local_path = download_pmc(pmcid, "xml")
            if local_path:
                source = "p3_pmc_xml"
                content_type = "application/xml"
                stats["pmc_xml"] += 1
            else:
                local_path = download_pmc(pmcid, "pdf")
                if local_path:
                    source = "p3_pmc_pdf"
                    content_type = "application/pdf"
                    stats["pmc_pdf"] += 1

        # Channel 2: For OA journals, try Unpaywall (fresh lookup)
        if not local_path and oa_journal and doi:
            local_path = download_unpaywall(doi)
            if local_path:
                source = "p3_unpaywall_oa_j"
                content_type = "application/pdf"
                stats["unpaywall_oa_j"] += 1

        # Channel 3: Unpaywall for all
        if not local_path and doi:
            local_path = download_unpaywall(doi)
            if local_path:
                source = "p3_unpaywall"
                content_type = "application/pdf"
                stats["unpaywall"] += 1

        # Channel 4: Semantic Scholar
        if not local_path and doi:
            local_path = download_s2(doi)
            if local_path:
                source = "p3_s2"
                content_type = "application/pdf"
                stats["s2"] += 1

        if local_path:
            update_db(con, ref_id, "downloaded", source, local_path, content_type)
            cp.setdefault("done", []).append(ref_id)
            stats["success"] += 1
        else:
            # Keep as no_oa — we genuinely can't get it
            cp.setdefault("still_no_oa", []).append(ref_id)
            stats["still_no_oa"] += 1

        stats["total"] += 1

        if stats["total"] % 100 == 0:
            con.commit()
            save_cp(cp)
            elapsed = time.time() - t0
            rate = stats["total"] / elapsed if elapsed > 0 else 0
            print(f"  [{stats['total']}/{len(refs)}] {rate:.1f}/s | "
                  f"OK={stats['success']} noOA={stats['still_no_oa']} | "
                  f"pmc={stats['pmc_xml']+stats['pmc_pdf']} "
                  f"upw={stats['unpaywall']+stats['unpaywall_oa_j']} s2={stats['s2']}")

        time.sleep(SLEEP)

    con.commit()
    save_cp(cp)

    elapsed = time.time() - t0
    print(f"\n{'=' * 70}")
    print("P3 COMPLETE")
    print(f"{'=' * 70}")
    print(f"  Time: {elapsed:.0f}s ({elapsed/60:.1f} min)")
    print(f"  Total: {stats['total']}")
    print(f"  Recovered (now downloaded): {stats['success']}")
    print(f"  Confirmed no OA: {stats['still_no_oa']}")
    print(f"  Channels: pmc_xml={stats['pmc_xml']} pmc_pdf={stats['pmc_pdf']} "
          f"upw_oa_j={stats['unpaywall_oa_j']} upw={stats['unpaywall']} s2={stats['s2']}")

    # DB state
    dled = con.execute("SELECT COUNT(DISTINCT reference_id) FROM literature_fulltext_sources WHERE status IN ('downloaded','local')").fetchone()[0]
    no_oa = con.execute("SELECT COUNT(DISTINCT reference_id) FROM literature_fulltext_sources WHERE status='no_oa'").fetchone()[0]
    print(f"  DB: downloaded={dled}, no_oa={no_oa}")

    con.close()

    log = {"timestamp": datetime.now().isoformat(), "elapsed_s": elapsed,
           "stats": dict(stats), "db": {"downloaded": dled, "no_oa": no_oa}}
    log_path = LOG_DIR / f"p3_{int(time.time())}.json"
    log_path.write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  Log: {log_path}")


if __name__ == "__main__":
    main()
