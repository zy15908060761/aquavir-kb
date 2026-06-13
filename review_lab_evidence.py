#!/usr/bin/env python
"""
Lab evidence manual review toolkit.
Step 1: Generate a stratified random review sample as CSV.
Step 2: User reviews in Excel/LibreOffice, marks accept/reject/unsure.
Step 3: Ingest reviewed decisions back into curation_logs + update evidence_records.
"""

import sqlite3
import csv
import random
import sys
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "crustacean_virus_core.db")
REVIEW_CSV = os.path.join(os.path.dirname(os.path.abspath(__file__)), "reports", "lab_evidence_review_worklist.csv")
RESULTS_CSV = os.path.join(os.path.dirname(os.path.abspath(__file__)), "reports", "lab_evidence_review_results.csv")

random.seed(20260605)


def generate_sample(sample_size=400):
    """Generate a stratified random sample of lab needs_review evidence for manual review."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # Get distribution by evidence_type and extraction_method for stratification
    cur.execute("""
        SELECT evidence_type, extraction_method, COUNT(*) as cnt
        FROM evidence_records
        WHERE observation_type = 'lab' AND curation_status = 'needs_review'
        GROUP BY evidence_type, extraction_method
        ORDER BY cnt DESC
    """)
    strata = [(r["evidence_type"], r["extraction_method"], r["cnt"]) for r in cur.fetchall()]

    # Stratified sampling: proportional allocation
    total_eligible = sum(s[2] for s in strata)
    sample_ids = set()

    for ev_type, ext_method, cnt in strata:
        stratum_n = max(1, round(sample_size * cnt / total_eligible))

        cur.execute("""
            SELECT evidence_id FROM evidence_records
            WHERE observation_type = 'lab'
              AND curation_status = 'needs_review'
              AND evidence_type = ?
              AND extraction_method = ?
            ORDER BY RANDOM()
            LIMIT ?
        """, (ev_type, ext_method, stratum_n))
        ids = [r["evidence_id"] for r in cur.fetchall()]
        sample_ids.update(ids)

    # If we got fewer than requested (small strata rounding), top up
    if len(sample_ids) < sample_size:
        shortfall = sample_size - len(sample_ids)
        cur.execute("""
            SELECT evidence_id FROM evidence_records
            WHERE observation_type = 'lab'
              AND curation_status = 'needs_review'
              AND evidence_id NOT IN ({})
            ORDER BY RANDOM()
            LIMIT ?
        """.format(",".join("?" * len(sample_ids))),
            list(sample_ids) + [shortfall])
        ids = [r["evidence_id"] for r in cur.fetchall()]
        sample_ids.update(ids)

    # Fetch full records
    cur.execute("""
        SELECT
            er.evidence_id,
            vm.canonical_name,
            vm.virus_family,
            er.evidence_type,
            er.evidence_strength,
            er.extraction_method,
            er.claim,
            er.context,
            rl.pmid,
            rl.doi,
            rl.title AS ref_title,
            rl.journal,
            rl.year
        FROM evidence_records er
        JOIN virus_master vm ON er.virus_master_id = vm.master_id
        LEFT JOIN ref_literatures rl ON er.reference_id = rl.reference_id
        WHERE er.evidence_id IN ({})
        ORDER BY er.evidence_type, vm.canonical_name
    """.format(",".join("?" * len(sample_ids))),
        list(sample_ids))

    rows = cur.fetchall()
    conn.close()

    # Write CSV
    os.makedirs(os.path.dirname(REVIEW_CSV), exist_ok=True)
    with open(REVIEW_CSV, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow([
            "evidence_id", "review_decision", "review_notes",
            "canonical_name", "virus_family", "evidence_type", "evidence_strength",
            "extraction_method", "claim", "context",
            "pmid", "doi", "ref_title", "journal", "year"
        ])
        for r in rows:
            writer.writerow([
                r["evidence_id"],
                "",  # ACCEPT / REJECT / UNSURE — to be filled by reviewer
                "",  # review_notes
                r["canonical_name"],
                r["virus_family"],
                r["evidence_type"],
                r["evidence_strength"],
                r["extraction_method"],
                r["claim"],
                r["context"],
                r["pmid"],
                r["doi"],
                r["ref_title"],
                r["journal"],
                r["year"],
            ])

    sample_n = len(rows)
    print(f"Generated review worklist: {REVIEW_CSV}")
    print(f"  Sample size: {sample_n} (requested: {sample_size})")
    print(f"  Total eligible (lab + needs_review): {total_eligible:,}")
    print(f"  Sampling fraction: {sample_n / total_eligible * 100:.1f}%")
    print()
    print("Strata:")
    for ev_type, ext_method, cnt in strata:
        in_sample = sum(1 for r in rows if r["evidence_type"] == ev_type and r["extraction_method"] == ext_method)
        print(f"  {ev_type:25s} {ext_method:35s} total={cnt:>6,d}  sampled={in_sample:>4,d}")
    print()
    print("REVIEW INSTRUCTIONS:")
    print("  1. Open the CSV in Excel/LibreOffice")
    print("  2. For each row, read the claim text and check:")
    print("     a) Does the claim MENTION the assigned virus (canonical_name)?")
    print("     b) Does the claim SUPPORT the assigned evidence_type?")
    print("     c) Is the claim a complete, meaningful sentence?")
    print("  3. Mark review_decision: ACCEPT, REJECT, or UNSURE")
    print("  4. Add review_notes if you want to explain your decision")
    print("  5. Save the CSV and run: python review_lab_evidence.py --ingest")

    return REVIEW_CSV


def ingest_decisions():
    """Read reviewed CSV and apply decisions to the database."""
    if not os.path.exists(REVIEW_CSV):
        print(f"ERROR: Review worklist not found at {REVIEW_CSV}")
        print("Run with --generate first.")
        sys.exit(1)

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # Backup before modifying
    backup_path = DB_PATH.replace(".db", f"_before_lab_review_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db")
    print(f"Creating backup: {backup_path}")
    import shutil
    shutil.copy2(DB_PATH, backup_path)

    stats = {"accepted": 0, "rejected": 0, "unsure": 0, "skipped": 0}
    results = []

    with open(REVIEW_CSV, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            decision = row.get("review_decision", "").strip().upper()
            notes = row.get("review_notes", "").strip()
            evidence_id = int(row["evidence_id"])

            if decision not in ("ACCEPT", "REJECT", "UNSURE"):
                stats["skipped"] += 1
                continue

            stats[decision.lower()] += 1
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            if decision == "ACCEPT":
                new_status = "manual_checked"
                new_strength = row.get("evidence_strength", "medium")  # keep original
            elif decision == "REJECT":
                new_status = "rejected"
                new_strength = row.get("evidence_strength", "medium")
            else:  # UNSURE
                new_status = "needs_review"
                new_strength = row.get("evidence_strength", "medium")

            # Update evidence_records
            cur.execute("""
                UPDATE evidence_records
                SET curation_status = ?,
                    evidence_strength = ?,
                    notes = CASE
                        WHEN notes IS NULL THEN ?
                        WHEN notes = '' THEN ?
                        ELSE notes || ' | ' || ?
                    END,
                    updated_at = ?
                WHERE evidence_id = ?
            """, (new_status, new_strength, notes, notes, notes, timestamp, evidence_id))

            # Insert curation_log
            cur.execute("""
                INSERT INTO curation_logs
                (entity_type, entity_id, action, old_value, new_value, confidence, curator, created_at, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                "evidence", evidence_id, "manual_review",
                "needs_review", new_status,
                "high" if decision == "ACCEPT" else ("low" if decision == "REJECT" else "medium"),
                f"human_reviewer_{datetime.now().strftime('%Y%m%d')}",
                timestamp,
                f"Manual review decision: {decision}. {notes}"
            ))

            results.append({
                "evidence_id": evidence_id,
                "decision": decision,
                "new_status": new_status,
                "notes": notes
            })

    conn.commit()

    # Write results summary
    os.makedirs(os.path.dirname(RESULTS_CSV), exist_ok=True)
    with open(RESULTS_CSV, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=["evidence_id", "decision", "new_status", "notes"])
        writer.writeheader()
        writer.writerows(results)

    # Print summary
    total_decided = stats["accepted"] + stats["rejected"] + stats["unsure"]
    print(f"\nReview ingested: {REVIEW_CSV} -> {RESULTS_CSV}")
    print(f"  Accepted: {stats['accepted']}")
    print(f"  Rejected: {stats['rejected']}")
    print(f"  Unsure:   {stats['unsure']}")
    print(f"  Skipped:  {stats['skipped']}")
    if total_decided > 0:
        precision = stats["accepted"] / total_decided * 100
        print(f"  Precision (accepted / decided): {precision:.1f}%")
        print(f"  95% CI: {precision - 1.96 * ((precision/100 * (1-precision/100)) / total_decided) ** 0.5 * 100:.1f}% - {precision + 1.96 * ((precision/100 * (1-precision/100)) / total_decided) ** 0.5 * 100:.1f}%")

    # Verify
    cur.execute("PRAGMA foreign_key_check")
    fk = cur.fetchall()
    cur.execute("PRAGMA integrity_check")
    integrity = cur.fetchone()[0]
    print(f"\nPost-review verification:")
    print(f"  FK violations: {len(fk)}")
    print(f"  Integrity: {integrity}")
    print(f"  Backup: {backup_path}")

    conn.close()
    return RESULTS_CSV


def quick_stats():
    """Show current lab evidence stats for planning."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("""
        SELECT curation_status, COUNT(*) FROM evidence_records
        WHERE observation_type = 'lab'
        GROUP BY curation_status
    """)
    print("=== Lab evidence by curation_status ===")
    for r in cur.fetchall(): print(f"  {r[0]:20s}: {r[1]:>8,d}")

    cur.execute("""
        SELECT evidence_type, COUNT(*) FROM evidence_records
        WHERE observation_type = 'lab' AND curation_status = 'needs_review'
        GROUP BY evidence_type ORDER BY COUNT(*) DESC
    """)
    print("\n=== Lab needs_review by evidence_type ===")
    for r in cur.fetchall(): print(f"  {r[0]:25s}: {r[1]:>8,d}")

    cur.execute("""
        SELECT COUNT(DISTINCT virus_master_id) FROM evidence_records
        WHERE observation_type = 'lab' AND curation_status = 'needs_review'
    """)
    print(f"\n  Unique viruses: {cur.fetchone()[0]}")

    cur.execute("""
        SELECT COUNT(DISTINCT reference_id) FROM evidence_records
        WHERE observation_type = 'lab' AND curation_status = 'needs_review'
    """)
    print(f"  Unique references: {cur.fetchone()[0]}")

    cur.execute("""
        SELECT extraction_method, COUNT(*) FROM evidence_records
        WHERE observation_type = 'lab' AND curation_status = 'needs_review'
        GROUP BY extraction_method ORDER BY COUNT(*) DESC
    """)
    print("\n=== Lab needs_review by extraction_method ===")
    for r in cur.fetchall(): print(f"  {r[0]:35s}: {r[1]:>8,d}")

    conn.close()


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] == "--stats":
        quick_stats()
    elif sys.argv[1] == "--generate":
        sample_size = int(sys.argv[2]) if len(sys.argv) > 2 else 400
        generate_sample(sample_size)
    elif sys.argv[1] == "--ingest":
        ingest_decisions()
    else:
        print("Usage:")
        print("  python review_lab_evidence.py --stats       Show current lab evidence stats")
        print("  python review_lab_evidence.py --generate [N] Generate review worklist (default 400 records)")
        print("  python review_lab_evidence.py --ingest       Ingest reviewed decisions from CSV")
