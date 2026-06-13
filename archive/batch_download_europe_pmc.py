#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Download OA PDFs via Europe PMC API as fallback for NCBI PMC 502 errors.
Europe PMC endpoints:
  - JSON metadata: https://www.ebi.ac.uk/europepmc/webservices/rest/PMC{id}?format=json
  - PDF download: https://europepmc.org/backend/ptpmcrender.fcgi?accid=PMC{id}&blobtype=pdf
"""

import csv
import json
import os
import time
import urllib.request
import ssl
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Input: list of PMCIDs from various sources
PMC_SOURCES = [
    os.path.join(BASE_DIR, "downloads", "literature_integrated", "literature_merged_master.csv"),
    os.path.join(BASE_DIR, "downloads", "literature_gap_analysis", "external_matched_articles.csv"),
]

OUT_DIR = os.path.join(BASE_DIR, "downloads", "literature_download_report", "europe_pmc_pdfs")
os.makedirs(OUT_DIR, exist_ok=True)

CHECKPOINT_FILE = os.path.join(OUT_DIR, "europe_pmc_checkpoint.json")
REPORT_FILE = os.path.join(OUT_DIR, "europe_pmc_download_report.json")

EUROPE_PMC_JSON = "https://www.ebi.ac.uk/europepmc/webservices/rest/PMC{}?format=json"
EUROPE_PMC_PDF = "https://europepmc.org/backend/ptpmcrender.fcgi?accid=PMC{}&blobtype=pdf"

ssl_context = ssl.create_default_context()
ssl_context.check_hostname = False
ssl_context.verify_mode = ssl.CERT_NONE


def load_existing_pmcids():
    pmcids = set()
    for path in PMC_SOURCES:
        if not os.path.exists(path):
            continue
        with open(path, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                pmc = str(row.get("pmc_id", row.get("pmcid", row.get("PMCID", "")))).strip()
                if pmc and pmc.lower() != "nan":
                    # Normalize: remove PMC prefix if present
                    pmc = pmc.replace("PMC", "").strip()
                    if pmc:
                        pmcids.add(pmc)
    return sorted(list(pmcids))


def load_checkpoint():
    if os.path.exists(CHECKPOINT_FILE):
        with open(CHECKPOINT_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"completed": [], "failed": [], "success": []}


def save_checkpoint(cp):
    with open(CHECKPOINT_FILE, "w", encoding="utf-8") as f:
        json.dump(cp, f, ensure_ascii=False, indent=2)


def check_has_pdf(pmc_id):
    """Check if Europe PMC has PDF for this PMCID."""
    url = EUROPE_PMC_JSON.format(pmc_id)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "aquatic_virus_db"})
        with urllib.request.urlopen(req, timeout=15, context=ssl_context) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        result = data.get("result", {})
        # Europe PMC has hasPDF field
        if isinstance(result, list) and len(result) > 0:
            result = result[0]
        return result.get("hasPDF", "N") == "Y"
    except Exception as e:
        print(f"    [Check error] {e}")
        return False


def download_pdf(pmc_id, out_path):
    """Download PDF from Europe PMC."""
    url = EUROPE_PMC_PDF.format(pmc_id)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "aquatic_virus_db"})
        with urllib.request.urlopen(req, timeout=60, context=ssl_context) as resp:
            data = resp.read()
        if len(data) < 1024:
            return False, f"too_small ({len(data)} bytes)"
        with open(out_path, "wb") as f:
            f.write(data)
        return True, "ok"
    except Exception as e:
        return False, str(e)


def main():
    pmcids = load_existing_pmcids()
    print(f"[{datetime.now()}] Found {len(pmcids)} unique PMCIDs to attempt")
    
    cp = load_checkpoint()
    completed = set(cp.get("completed", []))
    failed = list(cp.get("failed", []))
    success = list(cp.get("success", []))
    
    total = len(pmcids)
    for idx, pmc_id in enumerate(pmcids):
        if pmc_id in completed:
            continue
        
        print(f"[{idx+1}/{total}] PMC{pmc_id}")
        out_path = os.path.join(OUT_DIR, f"PMC{pmc_id}.pdf")
        
        if os.path.exists(out_path) and os.path.getsize(out_path) > 1024:
            print("  -> Already downloaded")
            success.append(pmc_id)
            completed.add(pmc_id)
            continue
        
        # Check availability
        has_pdf = check_has_pdf(pmc_id)
        time.sleep(0.5)
        
        if not has_pdf:
            print("  -> No PDF available in Europe PMC")
            failed.append({"pmc_id": pmc_id, "reason": "no_pdf_available"})
            completed.add(pmc_id)
            continue
        
        # Download
        ok, reason = download_pdf(pmc_id, out_path)
        time.sleep(1.0)
        
        if ok:
            size = os.path.getsize(out_path)
            print(f"  -> Downloaded ({size} bytes)")
            success.append(pmc_id)
        else:
            print(f"  -> Failed: {reason}")
            failed.append({"pmc_id": pmc_id, "reason": reason})
        
        completed.add(pmc_id)
        
        if (idx + 1) % 10 == 0:
            cp["completed"] = sorted(list(completed))
            cp["failed"] = failed
            cp["success"] = success
            save_checkpoint(cp)
            print(f"  [Checkpoint] {len(completed)}/{total} done, {len(success)} success, {len(failed)} failed")
    
    # Final save
    cp["completed"] = sorted(list(completed))
    cp["failed"] = failed
    cp["success"] = success
    save_checkpoint(cp)
    
    report = {
        "total_pmcids": total,
        "attempted": len(completed),
        "success": len(success),
        "failed": len(failed),
        "success_rate_pct": round(len(success) / len(completed) * 100, 2) if completed else 0,
        "output_dir": OUT_DIR,
        "timestamp": datetime.now().isoformat(),
    }
    with open(REPORT_FILE, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    
    print(f"\n[{datetime.now()}] DONE!")
    print(f"  Success: {len(success)}/{len(completed)}")
    print(f"  Failed: {len(failed)}")
    print(f"  Output: {OUT_DIR}")


if __name__ == "__main__":
    main()
