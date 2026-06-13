"""
Sequential runner for all external data source enrichments.

Runs each import/enrichment script one at a time to avoid SQLite lock conflicts.
Uses --limit flags for heavy scripts to keep runtime manageable.
"""
import subprocess
import sys
from pathlib import Path
from datetime import datetime

BASE_DIR = Path(__file__).resolve().parent
SCRIPTS = [
    # Tier 1
    ("ViralZone", "import_viralzone.py", []),
    ("KEGG", "enrich_kegg.py", ["--fetch-pathways"]),
    # Tier 2
    ("InterPro API", "enrich_interpro_api.py", ["--limit", "200"]),
    ("GEO/SRA", "import_geo_sra.py", ["--limit", "50"]),
    ("GBIF", "import_gbif.py", ["--limit", "15", "--max-occurrences", "100"]),
    ("Europe PMC (enrich)", "enrich_europe_pmc.py", ["--enrich-existing", "--limit", "100"]),
    ("Europe PMC (new)", "enrich_europe_pmc.py", ["--search-new"]),
    # Tier 3
    ("PRIDE", "import_pride.py", ["--limit", "20"]),
    ("AlphaFold (existing)", "enrich_structures.py", ["--limit", "200"]),
    ("STRING", "enrich_string.py", ["--limit", "200"]),
    ("bioRxiv", "import_biorxiv.py", ["--max-per-term", "20"]),
    ("OBIS/FishBase", "import_obis_fishbase.py", ["--limit", "15"]),
]


def main():
    print("=" * 60)
    print("Crustacean Virus DB - External Data Enrichment Runner")
    print(f"Start: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Scripts to run: {len(SCRIPTS)}")
    print("=" * 60)

    results = {}
    for i, (name, script, args) in enumerate(SCRIPTS, 1):
        script_path = BASE_DIR / script
        if not script_path.exists():
            print(f"\n[{i}/{len(SCRIPTS)}] {name} - SKIPPED (script not found: {script})")
            results[name] = "skipped"
            continue

        cmd = [sys.executable, str(script_path)] + args
        print(f"\n{'=' * 60}")
        print(f"[{i}/{len(SCRIPTS)}] {name}")
        print(f"  Command: {' '.join(cmd)}")
        print(f"  Time: {datetime.now().strftime('%H:%M:%S')}")
        print(f"{'=' * 60}")

        try:
            result = subprocess.run(cmd, capture_output=False, text=True, timeout=1800)
            if result.returncode == 0:
                print(f"  [OK] {name} completed successfully")
                results[name] = "ok"
            else:
                print(f"  [WARN] {name} exited with code {result.returncode}")
                results[name] = f"exit={result.returncode}"
        except subprocess.TimeoutExpired:
            print(f"  [TIMEOUT] {name} exceeded 30 min limit")
            results[name] = "timeout"
        except Exception as e:
            print(f"  [ERROR] {name}: {e}")
            results[name] = f"error: {e}"

    # Final summary
    print("\n" + "=" * 60)
    print("Enrichment Runner - Summary")
    print(f"End: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)
    for name, status in results.items():
        icon = "[OK]" if status == "ok" else f"[{status.upper()}]"
        print(f"  {icon} {name}")


if __name__ == "__main__":
    main()
