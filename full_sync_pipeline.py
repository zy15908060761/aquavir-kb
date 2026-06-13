"""
一键全链路同步流水线
运行方式: python full_sync_pipeline.py
"""

import sys
import time
import shutil
import sqlite3
import socket
import os
from pathlib import Path
from datetime import datetime

# Add script directory to path
SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))

from sync_runtime import append_history, now_iso, save_status
from db_utils import backup_database as wal_safe_backup

DB_PATH = Path(r'F:\甲壳动物数据库\crustacean_virus_core.db')
BACKUP_DIR = Path(r'F:\甲壳动物数据库\backups')
REPORT_FILE = Path(r'F:\甲壳动物数据库\sync_report.txt')


def log(msg):
    print(f"  [{datetime.now().strftime('%H:%M:%S')}] {msg}")


def backup_database():
    """Step 0: Backup existing database (WAL-safe)"""
    backup_path = wal_safe_backup(DB_PATH, BACKUP_DIR, label="sync")
    log(f"Database backed up to: {backup_path.name}")
    return backup_path


def step1_ncbi_sync():
    """Step 1: Download new records from NCBI"""
    print("\n[Step 1/8] NCBI Sync - Downloading new records...")
    print("  (This may take 1-5 minutes depending on network and new record count)")
    try:
        import ncbi_sync
        ncbi_sync.sync()
        return True
    except Exception as e:
        log(f"ERROR: {e}")
        print("  NCBI sync failed or timed out. Pipeline will continue with local data.")
        return False


def step2_incremental_import():
    """Step 2: Import new records into database"""
    print("\n[Step 2/8] Incremental Import - Adding new records to database...")
    try:
        import incremental_import
        count = incremental_import.import_new_records()
        log(f"Imported {count} new records")
        return True, count
    except Exception as e:
        log(f"ERROR: {e}")
        return False, 0


def step3_extract_sequences():
    """Step 3: Extract FASTA sequences"""
    print("\n[Step 3/8] Extract Sequences - Generating FASTA files...")
    try:
        import extract_sequences
        total = extract_sequences.extract_and_save()
        return total > 0
    except Exception as e:
        log(f"ERROR: {e}")
        return False


def step4_classify_sequences():
    """Step 4: Classify sequence completeness"""
    print("\n[Step 4/8] Classify Sequences - Labeling completeness...")
    try:
        import classify_sequences
        classify_sequences.main()
        return True
    except Exception as e:
        log(f"ERROR: {e}")
        return False


def step5_normalize_names():
    """Step 5: Normalize virus names"""
    print("\n[Step 5/8] Normalize Names - Mapping to canonical names...")
    try:
        import normalize_virus_names
        import normalize_virus_names_v2
        normalize_virus_names.apply_normalization(incremental=True)
        normalize_virus_names_v2.apply(incremental=True)
        return True
    except Exception as e:
        log(f"ERROR: {e}")
        return False


def step6_fill_geo():
    """Step 6: Backfill host and geographic metadata"""
    print("\n[Step 6/8] Fill Geography - Backfilling host/location metadata...")
    try:
        import extract_geo_from_gb
        import fill_country_centroids
        extract_geo_from_gb.main()
        fill_country_centroids.main()
        return True
    except Exception as e:
        log(f"ERROR: {e}")
        return False


def step7_build_phylogeny():
    """Step 7: Rebuild phylogenetic tree"""
    print("\n[Step 7/8] Build Phylogeny - Updating phylogenetic tree...")
    try:
        import build_phylogeny
        return bool(build_phylogeny.main())
    except Exception as e:
        log(f"ERROR: {e}")
        return False


def step8_build_downloads():
    """Step 8: Regenerate download files"""
    print("\n[Step 8/8] Build Downloads - Regenerating download files...")
    try:
        import build_downloads
        import export_release_tsvs
        build_downloads.build_complete_genomes_fasta()
        build_downloads.build_all_sequences_fasta()
        build_downloads.build_network_csv()
        build_downloads.build_reviewed_evidence_excel()
        build_downloads.build_metadata_standardized()
        export_release_tsvs.main([])
        return True
    except Exception as e:
        log(f"ERROR: {e}")
        return False


def step9_enrich_kegg():
    """Step 9: Enrich KEGG annotations"""
    print("\n[Step 9/16] KEGG Enrichment - Mapping proteins to KEGG pathways...")
    try:
        import enrich_kegg
        enrich_kegg.enrich_kegg(
            sqlite3.connect(str(DB_PATH)),
            dry_run=False,
            limit=None,
            fetch_pathways=True,
        )
        return True
    except Exception as e:
        log(f"ERROR: {e}")
        return False


def step10_import_viralzone():
    """Step 10: Import ViralZone data"""
    print("\n[Step 10/16] ViralZone Import - Fetching virus family factsheets...")
    try:
        import import_viralzone
        conn = sqlite3.connect(str(DB_PATH))
        import_viralzone.create_tables(conn)
        import_viralzone.register_source(conn)
        import_viralzone.import_viralzone(conn, dry_run=False, rebuild_cache=False)
        conn.close()
        return True
    except Exception as e:
        log(f"ERROR: {e}")
        return False


def step11_enrich_interpro():
    """Step 11: Enrich InterPro domain annotations via API"""
    print("\n[Step 11/16] InterPro Enrichment - Fetching domain annotations...")
    print("  (This may take 5-15 minutes for all proteins)")
    try:
        import enrich_interpro_api
        enrich_interpro_api.enrich_interpro(
            sqlite3.connect(str(DB_PATH)),
            dry_run=False,
            limit=None,
        )
        return True
    except Exception as e:
        log(f"ERROR: {e}")
        return False


def step12_import_geo_sra():
    """Step 12: Import GEO/SRA transcriptomics metadata"""
    print("\n[Step 12/16] GEO/SRA Import - Fetching transcriptomics datasets...")
    try:
        import import_geo_sra
        conn = sqlite3.connect(str(DB_PATH))
        import_geo_sra.create_tables(conn)
        import_geo_sra.register_source(conn)
        import_geo_sra.search_and_import_geo(conn, dry_run=False)
        import_geo_sra.search_and_import_sra(conn, dry_run=False)
        conn.close()
        return True
    except Exception as e:
        log(f"ERROR: {e}")
        return False


def step13_import_gbif():
    """Step 13: Import GBIF species occurrence data"""
    print("\n[Step 13/16] GBIF Import - Fetching host species distributions...")
    print("  (This may take 5-10 minutes)")
    try:
        import import_gbif
        conn = sqlite3.connect(str(DB_PATH))
        import_gbif.create_tables(conn)
        import_gbif.register_source(conn)
        import_gbif.import_gbif(conn, dry_run=False, limit=None, max_occurrences_per_species=200)
        conn.close()
        return True
    except Exception as e:
        log(f"ERROR: {e}")
        return False


def step14_enrich_europe_pmc():
    """Step 14: Enrich from Europe PMC"""
    print("\n[Step 14/16] Europe PMC Enrichment - Enriching literature metadata...")
    try:
        import enrich_europe_pmc
        conn = sqlite3.connect(str(DB_PATH))
        enrich_europe_pmc.create_tables(conn)
        enrich_europe_pmc.register_source(conn)
        enrich_europe_pmc.enrich_existing_references(conn, dry_run=False, limit=200)
        conn.close()
        return True
    except Exception as e:
        log(f"ERROR: {e}")
        return False


def step15_enrich_alphafold():
    """Step 15: Enrich AlphaFold DB structures"""
    print("\n[Step 15/16] AlphaFold Enrichment - Fetching protein structures...")
    print("  (This may take 10-30 minutes for all proteins)")
    try:
        import enrich_structures
        conn = sqlite3.connect(str(DB_PATH))
        enrich_structures.download_schema(conn)
        enrich_structures.run_alphafold(conn, dry_run=False, limit=None)
        conn.close()
        return True
    except Exception as e:
        log(f"ERROR: {e}")
        return False


def step16_enrich_string():
    """Step 16: Enrich STRING protein interactions"""
    print("\n[Step 16/16] STRING Enrichment - Fetching protein interactions...")
    try:
        import enrich_string
        enrich_string.enrich_string(
            sqlite3.connect(str(DB_PATH)),
            dry_run=False,
            limit=500,
        )
        return True
    except Exception as e:
        log(f"ERROR: {e}")
        return False


def generate_report(start_time, results):
    """Generate sync report"""
    elapsed = time.time() - start_time
    
    report = []
    report.append("=" * 60)
    report.append("Crustacean Virus Database - Sync Report")
    report.append(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    report.append(f"Duration: {elapsed:.1f} seconds")
    report.append("=" * 60)
    report.append("")
    
    steps = [
        ("NCBI Download", results['ncbi']),
        ("Incremental Import", results['import']),
        ("Extract Sequences", results['extract']),
        ("Classify Sequences", results['classify']),
        ("Normalize Names", results['normalize']),
        ("Fill Geography", results['geo']),
        ("Build Phylogeny", results['phylo']),
        ("Build Downloads", results['downloads']),
    ]
    enrichment_steps = [
        ("KEGG Enrichment", results.get('kegg', None)),
        ("ViralZone Import", results.get('viralzone', None)),
        ("InterPro Enrichment", results.get('interpro', None)),
        ("GEO/SRA Import", results.get('geo_sra', None)),
        ("GBIF Import", results.get('gbif', None)),
        ("Europe PMC Enrich", results.get('europe_pmc', None)),
        ("AlphaFold Enrich", results.get('alphafold', None)),
        ("STRING Enrichment", results.get('string', None)),
    ]
    # Only show enrichment steps if they were run
    if results.get('run_enrichment'):
        report.append("--- Enrichment Steps ---")
        for name, status in enrichment_steps:
            if status is not None:
                icon = "[OK]" if status else "[FAIL]"
                report.append(f"{icon} {name}")
    
    for name, status in steps:
        icon = "[OK]" if status else "[FAIL]"
        report.append(f"{icon} {name}")
    
    report.append("")
    report.append(f"New records imported: {results.get('new_count', 0)}")
    report.append(f"Backup: {results.get('backup', 'N/A')}")
    report.append("")
    report.append("Next steps:")
    report.append("  1. Restart the backend server")
    report.append("  2. Refresh the browser to see updated data")
    report.append("=" * 60)
    
    report_text = "\n".join(report)
    
    # Save to file
    with open(REPORT_FILE, 'w', encoding='utf-8') as f:
        f.write(report_text)
    
    print("\n" + report_text)
    print(f"\nReport saved to: {REPORT_FILE}")
    return report_text, elapsed


def main(skip_ncbi=False, run_enrichment=False):
    print("=" * 60)
    print("Crustacean Virus Database - Full Sync Pipeline")
    if skip_ncbi:
        print("Mode: LOCAL ONLY (skipping NCBI download)")
    if run_enrichment:
        print("Enrichment: ENABLED (steps 9-16)")
    print("=" * 60)
    
    start_time = time.time()
    started_at = now_iso()
    results = {
        'ncbi': False,
        'import': False,
        'extract': False,
        'classify': False,
        'normalize': False,
        'geo': False,
        'phylo': False,
        'downloads': False,
        'kegg': None,
        'viralzone': None,
        'interpro': None,
        'geo_sra': None,
        'gbif': None,
        'europe_pmc': None,
        'alphafold': None,
        'string': None,
        'new_count': 0,
        'run_enrichment': False,
    }
    step_labels = {
        'ncbi': 'NCBI Download',
        'import': 'Incremental Import',
        'extract': 'Extract Sequences',
        'classify': 'Classify Sequences',
        'normalize': 'Normalize Names',
        'geo': 'Fill Geography',
        'phylo': 'Build Phylogeny',
        'downloads': 'Build Downloads',
        'kegg': 'KEGG Enrichment',
        'viralzone': 'ViralZone Import',
        'interpro': 'InterPro Enrichment',
        'geo_sra': 'GEO/SRA Import',
        'gbif': 'GBIF Import',
        'europe_pmc': 'Europe PMC Enrichment',
        'alphafold': 'AlphaFold Enrichment',
        'string': 'STRING Enrichment',
    }
    save_status({
        "status": "running",
        "message": "Sync pipeline is running.",
        "started_at": started_at,
        "host": socket.gethostname(),
        "pid": os.getpid(),
        "step_results": {step_labels[k]: False for k in step_labels},
    })
    
    # Step 0: Backup
    try:
        backup = backup_database()
        results['backup'] = str(backup.name)
    except Exception as e:
        print(f"Backup failed: {e}")
        print("Aborting sync.")
        finished_at = now_iso()
        summary = {
            "status": "failed",
            "overall_status": "failed",
            "message": f"Backup failed: {e}",
            "started_at": started_at,
            "finished_at": finished_at,
            "duration_seconds": time.time() - start_time,
            "new_count": 0,
            "backup": None,
            "step_results": {step_labels[k]: False for k in step_labels},
        }
        save_status(summary)
        append_history(summary)
        return summary
    
    # Step 1: NCBI Sync
    if skip_ncbi:
        print("\n[Step 1/8] NCBI Sync - SKIPPED (using --skip-ncbi)")
        results['ncbi'] = True
    else:
        results['ncbi'] = step1_ncbi_sync()
    
    # Step 2: Incremental Import
    import_ok, new_count = step2_incremental_import()
    results['import'] = import_ok
    results['new_count'] = new_count
    
    # Step 3-8: Always run (they handle incremental logic internally)
    results['extract'] = step3_extract_sequences()
    results['classify'] = step4_classify_sequences()
    results['normalize'] = step5_normalize_names()
    results['geo'] = step6_fill_geo()
    results['phylo'] = step7_build_phylogeny()
    results['downloads'] = step8_build_downloads()
    core_required = ["extract", "classify", "normalize", "downloads"]
    if any(not results[name] for name in core_required):
        print("\nCore release artifact step failed; stopping before optional enrichment.")
        run_enrichment = False

    # Enrichment steps (optional, controlled by --enrich flag)
    if run_enrichment:
        results['run_enrichment'] = True
        results['kegg'] = step9_enrich_kegg()
        results['viralzone'] = step10_import_viralzone()
        results['interpro'] = step11_enrich_interpro()
        results['geo_sra'] = step12_import_geo_sra()
        results['gbif'] = step13_import_gbif()
        results['europe_pmc'] = step14_enrich_europe_pmc()
        results['alphafold'] = step15_enrich_alphafold()
        results['string'] = step16_enrich_string()

    # Generate report
    report_text, elapsed = generate_report(start_time, results)
    step_results = {step_labels[k]: bool(v) for k, v in results.items() if k in step_labels}
    failed_steps = [name for name, ok in step_results.items() if not ok]
    release_blockers = {"Extract Sequences", "Classify Sequences", "Normalize Names", "Build Downloads"}
    failed_release_steps = sorted(release_blockers.intersection(failed_steps))
    overall_status = "success" if not failed_steps else ("failed" if failed_release_steps else "partial")
    finished_at = now_iso()
    summary = {
        "status": overall_status,
        "overall_status": overall_status,
        "message": "Sync pipeline completed." if overall_status == "success" else "Sync pipeline completed with issues.",
        "started_at": started_at,
        "finished_at": finished_at,
        "duration_seconds": elapsed,
        "new_count": results.get("new_count", 0),
        "backup": results.get("backup"),
        "step_results": step_results,
        "failed_steps": failed_steps,
        "failed_release_steps": failed_release_steps,
        "report_file": str(REPORT_FILE),
        "report_text": report_text,
        "host": socket.gethostname(),
        "skip_ncbi": skip_ncbi,
    }
    save_status(summary)
    append_history(summary)
    
    print("\nPipeline complete!")
    print("Note: Remember to restart the backend server to load updated data.")
    return summary


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description='Full Sync Pipeline for Crustacean Virus DB')
    parser.add_argument('--skip-ncbi', action='store_true', help='Skip NCBI download step (process local data only)')
    parser.add_argument('--enrich', action='store_true', help='Run external data enrichment steps (slow, 30-90 min)')
    args = parser.parse_args()
    main(skip_ncbi=args.skip_ncbi, run_enrichment=args.enrich)
