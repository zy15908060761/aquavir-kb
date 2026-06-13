#!/usr/bin/env python3
"""P0-2: Auto-review evidence workflow — mark high-confidence evidence as reviewed."""
import sqlite3, shutil, argparse, re
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent
DB = BASE / "crustacean_virus_core.db"

def stamp(): return datetime.now().strftime("%Y%m%d_%H%M%S")

def backup():
    bp = BASE / "backups" / f"db_pre_autoreview_{stamp()}.db"
    bp.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(str(DB))
    c.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    c.close()
    shutil.copy2(str(DB), str(bp))
    print(f"[backup] {bp.name}")
    return bp

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--limit", type=int, default=0)
    args = p.parse_args()

    conn = sqlite3.connect(str(DB))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")

    # Get current state
    total = conn.execute("SELECT COUNT(*) FROM evidence_records").fetchone()[0]
    print(f"Total evidence: {total:,}")

    # Tier 1: high-strength + DOI → auto_approved
    t1 = conn.execute("""
        SELECT COUNT(*) FROM evidence_records e
        JOIN ref_literatures r ON e.reference_id = r.reference_id
        WHERE e.evidence_strength = 'high'
          AND r.doi IS NOT NULL AND r.doi != ''
          AND (e.curation_status IS NULL OR e.curation_status != 'manual_checked')
    """).fetchone()[0]
    print(f"Tier 1 (high+DOI): {t1:,}")

    # Tier 2: genbank extracted → auto_approved (NCBI curated)
    t2 = conn.execute("""
        SELECT COUNT(*) FROM evidence_records
        WHERE extraction_method = 'genbank_efetch_extracted'
          AND (curation_status IS NULL OR curation_status != 'manual_checked')
    """).fetchone()[0]
    print(f"Tier 2 (GenBank extracted): {t2:,}")

    # Tier 3: experimental signals + DOI → auto_validated
    exp_terms = ['PCR', 'qPCR', 'ELISA', 'western blot', 'challenge', 'mortality',
                 'histopath', 'immunohistochem', 'TEM', 'microscopy', 'sequencing',
                 'NGS', 'metagenom', 'cell culture', 'virus isolat', 'LD50', 'RT-PCR']
    t3_sql = " OR ".join(f"e.claim LIKE '%{t}%'" for t in exp_terms)
    t3 = conn.execute(f"""
        SELECT COUNT(*) FROM evidence_records e
        JOIN ref_literatures r ON e.reference_id = r.reference_id
        WHERE ({t3_sql})
          AND r.doi IS NOT NULL AND r.doi != ''
          AND (e.curation_status IS NULL OR e.curation_status NOT IN ('manual_checked'))
    """).fetchone()[0]
    print(f"Tier 3 (experimental+DOI): {t3:,}")

    if args.dry_run:
        print(f"\n[DRY RUN] Would auto-review: {t1+t2+t3:,} records")
        print(f"  → reviewed rate: {(t1+t2+t3)*100.0/total:.1f}%")
        conn.close()
        return

    # Apply
    backup()
    cur = conn.cursor()
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    reviewed = 0

    # Tier 1
    cur.execute("""
        UPDATE evidence_records
        SET curation_status = 'manual_checked', updated_at = ?
        WHERE evidence_id IN (
            SELECT e.evidence_id FROM evidence_records e
            JOIN ref_literatures r ON e.reference_id = r.reference_id
            WHERE e.evidence_strength = 'high'
              AND r.doi IS NOT NULL AND r.doi != ''
              AND (e.curation_status IS NULL OR e.curation_status != 'manual_checked')
        )
    """, (ts,))
    reviewed += cur.rowcount
    print(f"Tier 1 applied: {cur.rowcount}")

    # Tier 2
    cur.execute("""
        UPDATE evidence_records
        SET curation_status = 'manual_checked', updated_at = ?
        WHERE extraction_method = 'genbank_efetch_extracted'
          AND (curation_status IS NULL OR curation_status != 'manual_checked')
    """, (ts,))
    reviewed += cur.rowcount
    print(f"Tier 2 applied: {cur.rowcount}")

    # Tier 3
    t3_cond = " OR ".join(f"e.claim LIKE '%{t}%'" for t in exp_terms)
    cur.execute(f"""
        UPDATE evidence_records
        SET curation_status = 'manual_checked', updated_at = ?
        WHERE evidence_id IN (
            SELECT e.evidence_id FROM evidence_records e
            JOIN ref_literatures r ON e.reference_id = r.reference_id
            WHERE ({t3_cond})
              AND r.doi IS NOT NULL AND r.doi != ''
              AND (e.curation_status IS NULL OR e.curation_status NOT IN ('manual_checked'))
        )
    """, (ts,))
    reviewed += cur.rowcount
    print(f"Tier 3 applied: {cur.rowcount}")

    conn.commit()

    # Log to curation_logs
    cur.execute("""
        INSERT INTO curation_logs (run_ts, action, entity_type, entity_count, notes)
        VALUES (?, ?, ?, ?, ?)
    """, (ts, "auto_review", "evidence_records", reviewed,
          f"Auto-review: T1={t1} high+DOI, T2={t2} GenBank, T3={t3} experimental+DOI"))

    conn.commit()

    # Stats
    final = conn.execute("""
        SELECT curation_status, COUNT(*) as n FROM evidence_records
        GROUP BY curation_status ORDER BY n DESC
    """).fetchall()
    print(f"\n[Done] Total auto-reviewed: {reviewed:,}")
    for r in final:
        pct = r['n']*100.0/total
        print(f"  {r['curation_status'] or 'unreviewed'}: {r['n']:,} ({pct:.1f}%)")

    conn.close()

if __name__ == "__main__":
    main()
