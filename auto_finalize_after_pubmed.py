#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Auto-finalize script: waits for PubMed search checkpoint to reach target,
then re-runs integration and generates final report.
"""

import os
import sys
import time
import json
import subprocess

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CHECKPOINT_FILE = os.path.join(BASE_DIR, "downloads", "literature_all_viruses_search", "search_checkpoint.json")
TARGET_VIRUSES = 834
INTEGRATION_SCRIPT = os.path.join(BASE_DIR, "integrate_all_literature_for_import.py")


def get_checkpoint_progress():
    if not os.path.exists(CHECKPOINT_FILE):
        return 0
    try:
        with open(CHECKPOINT_FILE, "r", encoding="utf-8") as f:
            cp = json.load(f)
        return len(cp.get("completed", []))
    except:
        return 0


def main():
    print("[Auto-Finalize] Monitoring PubMed search progress...")
    last_progress = 0
    
    while True:
        progress = get_checkpoint_progress()
        if progress != last_progress:
            print(f"  Progress: {progress}/{TARGET_VIRUSES} viruses completed")
            last_progress = progress
        
        if progress >= TARGET_VIRUSES:
            print(f"\n[Auto-Finalize] PubMed search complete! Running final integration...")
            result = subprocess.run(
                [sys.executable, INTEGRATION_SCRIPT],
                cwd=BASE_DIR,
                capture_output=True,
                text=True,
            )
            print(result.stdout)
            if result.returncode != 0:
                print("ERROR:", result.stderr)
                sys.exit(1)
            
            # Generate summary
            report_path = os.path.join(BASE_DIR, "downloads", "literature_all_viruses_search", "final_coverage_report.json")
            if os.path.exists(report_path):
                with open(report_path, "r", encoding="utf-8") as f:
                    report = json.load(f)
                print("\n" + "="*60)
                print("FINAL LITERATURE CURATION SUMMARY")
                print("="*60)
                print(f"Total viruses: {report['total_viruses']}")
                print(f"Covered: {report['covered_viruses']} ({report['coverage_pct']}%)")
                print(f"Direct-only: {report['direct_only']}")
                print(f"Indirect-only: {report['indirect_only']}")
                print(f"PubMed-enhanced: {report['pubmed_enhanced']}")
                print(f"Total unique articles: {report['total_unique_articles']}")
                print("="*60)
            
            print("\n[Auto-Finalize] All done!")
            break
        
        time.sleep(60)  # Check every minute


if __name__ == "__main__":
    main()
