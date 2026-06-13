#!/usr/bin/env python3
"""
P2 FAST: Retry failed downloads via PMC only (fast path).
- Only attempts download for refs with known PMCIDs
- Skips Unpaywall/S2 (already failed, unlikely to work)
- Processes the 5,174 refs in ~5 min instead of 4 hours
"""
import json, sqlite3, time, urllib.request
from pathlib import Path
from collections import Counter

DB_PATH = Path(r"F:\水生无脊椎动物数据库\crustacean_virus_core.db")
PROJECT_DIR = Path(r"F:\水生无脊椎动物数据库")
LIT_DIR = PROJECT_DIR / "literature_curation_v2"
PMC_XML_DIR = LIT_DIR / "pmc_xml"
FULLTEXT_DIR = LIT_DIR / "fulltext"
LOG_DIR = PROJECT_DIR / "downloads" / "retry_logs"

for d in [PMC_XML_DIR, FULLTEXT_DIR, LOG_DIR]:
    d.mkdir(parents=True, exist_ok=True)

CHECKPOINT_PATH = LOG_DIR / "retry_fast_checkpoint.json"
UA = "AquaVir-KB/2.0 (mailto:crustacean-db@proton.me)"
TIMEOUT = 30
SLEEP = 0.3


def load_cp():
    if CHECKPOINT_PATH.exists():
        return json.loads(CHECKPOINT_PATH.read_text(encoding="utf-8"))
    return {"done": [], "no_oa": [], "pmcid_map": {}}


def save_cp(cp):
    CHECKPOINT_PATH.write_text(json.dumps(cp, ensure_ascii=False, indent=2), encoding="utf-8")


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
            print(f"  Batch error: {e}")
        time.sleep(0.3)
    return results


def download_pmc_xml(pmcid):
    url = f"https://www.ncbi.nlm.nih.gov/research/bionlp/RESTful/pmcoa.cgi/BioC_xml/{pmcid}/unicode"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            content = resp.read()
        if len(content) > 500 and b"<" in content[:100]:
            path = PMC_XML_DIR / f"{pmcid}_PMC.xml"
            path.write_bytes(content)
            return str(path)
    except Exception:
        pass
    return None


def download_pmc_pdf(pmcid):
    url = f"https://www.ncbi.nlm.nih.gov/pmc/articles/{pmcid}/pdf/main.pdf"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            content = resp.read()
        if len(content) > 5000:
            path = FULLTEXT_DIR / f"{pmcid}_PMC.pdf"
            path.write_bytes(content)
            return str(path)
    except Exception:
        pass
    return None


def update_db(con, ref_id, status, source, local_path=None, content_type=None):
    con.execute("""UPDATE literature_fulltext_sources
        SET status=?, source=?, local_path=?, content_type=?
        WHERE reference_id=? AND status='failed'""",
        (status, source, local_path, content_type, ref_id))


def main():
    print("=" * 70)
    print("P2 FAST: PMC-only Retry for Failed Downloads")
    print("=" * 70)

    con = sqlite3.connect(str(DB_PATH), timeout=60)
    con.row_factory = sqlite3.Row

    # Get failed refs
    cp = load_cp()
    already = set(cp.get("done", [])) | set(cp.get("no_oa", []))

    refs = []
    for row in con.execute("""SELECT DISTINCT lfs.reference_id, lfs.pmid, lfs.doi
        FROM literature_fulltext_sources lfs
        WHERE lfs.status='failed' ORDER BY lfs.reference_id"""):
        if row["reference_id"] not in already:
            refs.append({"reference_id": row["reference_id"], "pmid": row["pmid"], "doi": row["doi"]})

    print(f"Failed refs to process: {len(refs)}")

    # Phase 0: PMID → PMCID
    pmids_new = [str(r["pmid"]) for r in refs if r["pmid"] and str(r["pmid"]) not in cp.get("pmcid_map", {})]
    if pmids_new:
        print(f"Phase 0: Converting {len(pmids_new)} PMIDs → PMCIDs...")
        new_map = batch_pmid_to_pmcid(pmids_new)
        if "pmcid_map" not in cp:
            cp["pmcid_map"] = {}
        cp["pmcid_map"].update(new_map)
        save_cp(cp)
        print(f"  Got {len(new_map)} new PMCIDs (total: {len(cp['pmcid_map'])})")
    else:
        print(f"Phase 0: All PMIDs already converted ({len(cp.get('pmcid_map', {}))} PMCIDs)")

    pmcid_map = cp.get("pmcid_map", {})

    # Phase 1: Download PMCOA for refs with PMCIDs
    stats = Counter()
    t0 = time.time()

    for i, ref in enumerate(refs):
        ref_id = ref["reference_id"]
        pmid = str(ref["pmid"]) if ref["pmid"] else ""

        local_path = None
        source = None
        content_type = None

        pmcid = pmcid_map.get(pmid)
        if pmcid:
            local_path = download_pmc_xml(pmcid)
            if local_path:
                source = "retry_fast_pmc_xml"
                content_type = "application/xml"
                stats["pmc_xml"] += 1
            else:
                local_path = download_pmc_pdf(pmcid)
                if local_path:
                    source = "retry_fast_pmc_pdf"
                    content_type = "application/pdf"
                    stats["pmc_pdf"] += 1

        if local_path:
            update_db(con, ref_id, "downloaded", source, local_path, content_type)
            cp.setdefault("done", []).append(ref_id)
            stats["success"] += 1
        else:
            update_db(con, ref_id, "no_oa", "retry_fast_no_oa")
            cp.setdefault("no_oa", []).append(ref_id)
            stats["no_oa"] += 1

        stats["total"] += 1

        if stats["total"] % 200 == 0:
            con.commit()
            save_cp(cp)
            elapsed = time.time() - t0
            rate = stats["total"] / elapsed if elapsed > 0 else 0
            print(f"  [{stats['total']}/{len(refs)}] {rate:.1f}/s | "
                  f"OK={stats['success']} noOA={stats['no_oa']} "
                  f"xml={stats['pmc_xml']} pdf={stats['pmc_pdf']}")

        time.sleep(SLEEP)

    con.commit()
    save_cp(cp)

    elapsed = time.time() - t0
    print(f"\n{'=' * 70}")
    print("P2 FAST COMPLETE")
    print(f"{'=' * 70}")
    print(f"  Time: {elapsed:.0f}s ({elapsed/60:.1f} min)")
    print(f"  Total: {stats['total']}")
    print(f"  Downloaded: {stats['success']} (via PMC)")
    print(f"  No OA: {stats['no_oa']}")

    dled = con.execute("SELECT COUNT(DISTINCT reference_id) FROM literature_fulltext_sources WHERE status IN ('downloaded','local')").fetchone()[0]
    failed = con.execute("SELECT COUNT(DISTINCT reference_id) FROM literature_fulltext_sources WHERE status='failed'").fetchone()[0]
    no_oa = con.execute("SELECT COUNT(DISTINCT reference_id) FROM literature_fulltext_sources WHERE status='no_oa'").fetchone()[0]
    print(f"  DB: downloaded={dled}, failed={failed}, no_oa={no_oa}")

    con.close()


if __name__ == "__main__":
    main()
