#!/usr/bin/env python3
"""
Evidence Quality Upgrade v2: Strategies 1-4 with tuned parameters.
S1: Triangulation — ≥3 independent refs + similar claim → high
S2: Weighted multi-factor scoring (0-9 pts, ≥7 → high)
S3: Quantitative value extraction from claim text
S4: Low quality cleanup
"""
import sqlite3, re, shutil, argparse, hashlib
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent
DB = BASE / "crustacean_virus_core.db"

def stamp(): return datetime.now().strftime("%Y%m%d_%H%M%S")

def backup():
    bp = BASE / "backups" / f"db_pre_quality_v2_{stamp()}.db"
    bp.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(str(DB))
    c.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    c.close()
    shutil.copy2(str(DB), str(bp))
    print(f"[backup] {bp.name}")

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--skip", type=str, default="")
    args = p.parse_args()
    skip = set(f"S{s}" for s in args.skip.split(",")) if args.skip else set()

    conn = sqlite3.connect(str(DB))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=120000")

    total = conn.execute("SELECT COUNT(*) FROM evidence_records").fetchone()[0]
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    upgrades = {"S1_triangulation": 0, "S2_multifactor": 0, "S3_quantitative": 0, "S4_low_cleanup": 0}
    cur = conn.cursor()

    if not args.dry_run:
        backup()

    # ═══════════════════════════════════════════════════════════
    # STRATEGY 2: Weighted multi-factor scoring
    # ═══════════════════════════════════════════════════════════
    if "S2" not in skip:
        print("\n" + "="*60)
        print("STRATEGY 2: Weighted multi-factor scoring (≥7 pts → high)")
        print("="*60)

        # Score weights
        score_parts = [
            ("CASE WHEN r.doi IS NOT NULL AND r.doi != '' THEN 1 ELSE 0 END", "DOI"),
            ("CASE WHEN lfs.reference_id IS NOT NULL THEN 2 ELSE 0 END", "fulltext"),
            ("CASE WHEN e.isolate_id IS NOT NULL THEN 2 ELSE 0 END", "isolate_linked"),
            (f"""CASE WHEN (e.claim LIKE '%PCR%' OR e.claim LIKE '%qPCR%' OR e.claim LIKE '%challenge%'
                   OR e.claim LIKE '%TEM%' OR e.claim LIKE '%mortality%'
                   OR e.claim LIKE '%histopath%' OR e.claim LIKE '%ELISA%'
                   OR e.claim LIKE '%virus isolat%' OR e.claim LIKE '%sequencing%')
                  THEN 2 ELSE 0 END""", "experimental"),
            ("CASE WHEN e.extraction_method IN ('fulltext_deep_extraction','fulltext_parsed','fulltext_parsed_p1','genbank_efetch_extracted') THEN 1 ELSE 0 END", "fulltext_extracted"),
            ("CASE WHEN e.curation_status = 'manual_checked' THEN 1 ELSE 0 END", "manual_checked"),
        ]

        score_expr = " + ".join(s[0] for s in score_parts)

        # Count by score tiers
        print("  Score distribution:")
        for threshold in [3, 4, 5, 6, 7, 8, 9]:
            cnt = conn.execute(f"""
                SELECT COUNT(*) FROM evidence_records e
                LEFT JOIN ref_literatures r ON e.reference_id = r.reference_id
                LEFT JOIN literature_fulltext_sources lfs ON e.reference_id = lfs.reference_id
                WHERE e.evidence_strength = 'medium'
                  AND ({score_expr}) >= ?
            """, (threshold,)).fetchone()[0]
            pct = cnt * 100.0 / total
            print(f"    ≥{threshold}: {cnt:>10,} ({pct:.1f}%)")

        if not args.dry_run:
            # Upgrade: score ≥ 6
            n = cur.execute(f"""
                UPDATE evidence_records
                SET evidence_strength = 'high', updated_at = ?
                WHERE evidence_id IN (
                    SELECT e.evidence_id FROM evidence_records e
                    LEFT JOIN ref_literatures r ON e.reference_id = r.reference_id
                    LEFT JOIN literature_fulltext_sources lfs ON e.reference_id = lfs.reference_id
                    WHERE e.evidence_strength = 'medium'
                      AND ({score_expr}) >= 7
                )
            """, (ts,)).rowcount
            conn.commit()
            upgrades["S2_multifactor"] = n
            print(f"  Upgraded (≥7): {n:,}")
        else:
            cnt6 = conn.execute(f"""
                SELECT COUNT(*) FROM evidence_records e
                LEFT JOIN ref_literatures r ON e.reference_id = r.reference_id
                LEFT JOIN literature_fulltext_sources lfs ON e.reference_id = lfs.reference_id
                WHERE e.evidence_strength = 'medium' AND ({score_expr}) >= 7
            """).fetchone()[0]
            print(f"  [DRY RUN] Would upgrade ≥7: {cnt6:,}")

    # ═══════════════════════════════════════════════════════════
    # STRATEGY 3: Quantitative value extraction
    # ═══════════════════════════════════════════════════════════
    if "S3" not in skip:
        print("\n" + "="*60)
        print("STRATEGY 3: Quantitative value extraction")
        print("="*60)

        patterns = [
            (r'(?i)mortality\s*(?:rate|was|of|reached|up\s*to)?\s*(\d+[\.\d]*)%', '%', 'mortality_rate'),
            (r'(?i)(\d+[\.\d]*)%\s*(?:cumulative\s*)?mortality', '%', 'mortality_rate'),
            (r'(?i)LD50\s*(?:value\s*)?[=:\s]+(\d+[\.\d]+)', 'dose', 'LD50'),
            (r'(?i)survival\s*(?:rate|of)\s*(\d+[\.\d]*)%', '%', 'survival_rate'),
            (r'(?i)prevalence\s*(?:rate|of)\s*(\d+[\.\d]*)%', '%', 'prevalence'),
            (r'(?i)(\d+[\.\d]*)\s*°C', '°C', 'temperature'),
        ]

        if not args.dry_run:
            extracted = 0
            for pattern, unit, etype in patterns:
                # Find matching claims
                rows = conn.execute("""
                    SELECT evidence_id, claim FROM evidence_records
                    WHERE evidence_strength IN ('medium', 'high')
                      AND (value_numeric_min IS NULL AND value_numeric_max IS NULL)
                      AND claim IS NOT NULL AND claim != ''
                """).fetchall()

                batch = []
                for r in rows:
                    m = re.search(pattern, r['claim'])
                    if m:
                        try:
                            val = float(m.group(1))
                            batch.append((val, unit, ts, r['evidence_id']))
                        except ValueError:
                            continue

                if batch:
                    cur.executemany("""
                        UPDATE evidence_records
                        SET value_numeric_min = ?, unit = ?, updated_at = ?
                        WHERE evidence_id = ?
                    """, batch)
                    extracted += len(batch)
                    conn.commit()
                    print(f"  {etype}: {len(batch):,} values extracted")

            # Upgrade to high for evidence that now has quantitative data
            n = cur.execute("""
                UPDATE evidence_records
                SET evidence_strength = 'high', updated_at = ?
                WHERE evidence_strength = 'medium'
                  AND value_numeric_min IS NOT NULL
            """, (ts,)).rowcount
            conn.commit()
            upgrades["S3_quantitative"] = n
            print(f"  Total S3: {extracted:,} extracted, {n:,} upgraded to high")
        else:
            # Quick estimate
            est = conn.execute("""
                SELECT COUNT(*) FROM evidence_records
                WHERE evidence_strength IN ('medium', 'high')
                  AND (value_numeric_min IS NULL AND value_numeric_max IS NULL)
                  AND claim IS NOT NULL
                  AND (claim LIKE '%mortality%' OR claim LIKE '%LD50%' OR claim LIKE '%survival%')
            """).fetchone()[0]
            print(f"  [DRY RUN] Potential quantitative candidates: ~{est:,}")

    # ═══════════════════════════════════════════════════════════
    # STRATEGY 1: Triangulation (tightened)
    # ═══════════════════════════════════════════════════════════
    if "S1" not in skip:
        print("\n" + "="*60)
        print("STRATEGY 1: Triangulation — ≥3 refs, same virus+type, similar claim")
        print("="*60)

        # Group by virus+type+claim_prefix (first 100 chars)
        triang = conn.execute("""
            SELECT virus_master_id, evidence_type,
                   SUBSTR(claim, 1, 100) as claim_prefix,
                   COUNT(DISTINCT reference_id) as ref_count,
                   COUNT(*) as ev_count
            FROM evidence_records
            WHERE evidence_strength = 'medium'
              AND reference_id IS NOT NULL
              AND virus_master_id IS NOT NULL
              AND claim IS NOT NULL AND claim != ''
            GROUP BY virus_master_id, evidence_type, SUBSTR(claim, 1, 100)
            HAVING COUNT(DISTINCT reference_id) >= 3
        """).fetchall()

        print(f"  Similar-claim groups with ≥3 refs: {len(triang)}")
        triang_count = sum(r['ev_count'] for r in triang)
        print(f"  Evidence in triangulated groups: {triang_count:,}")

        if not args.dry_run:
            upgraded = 0
            for r in triang:
                n = cur.execute("""
                    UPDATE evidence_records
                    SET evidence_strength = 'high', updated_at = ?
                    WHERE virus_master_id = ? AND evidence_type = ?
                      AND SUBSTR(claim, 1, 100) = ?
                      AND evidence_strength = 'medium'
                      AND reference_id IS NOT NULL
                """, (ts, r['virus_master_id'], r['evidence_type'],
                      r['claim_prefix'])).rowcount
                upgraded += n

            conn.commit()
            upgrades["S1_triangulation"] = upgraded
            print(f"  Upgraded: {upgraded:,}")
        else:
            print(f"  [DRY RUN] Would upgrade: {triang_count:,}")

    # ═══════════════════════════════════════════════════════════
    # STRATEGY 4: Low quality cleanup
    # ═══════════════════════════════════════════════════════════
    if "S4" not in skip:
        print("\n" + "="*60)
        print("STRATEGY 4: Low quality cleanup")
        print("="*60)

        low_total = conn.execute(
            "SELECT COUNT(*) FROM evidence_records WHERE evidence_strength = 'low'"
        ).fetchone()[0]
        print(f"  Current low: {low_total:,}")

        if not args.dry_run:
            # Upgrade low → medium if has DOI
            n1 = cur.execute("""
                UPDATE evidence_records SET evidence_strength = 'medium', updated_at = ?
                WHERE evidence_strength = 'low'
                  AND reference_id IN (SELECT reference_id FROM ref_literatures WHERE doi IS NOT NULL AND doi != '')
            """, (ts,)).rowcount
            print(f"  Low+DOI → medium: {n1:,}")

            # Upgrade low → medium if has fulltext
            n2 = cur.execute("""
                UPDATE evidence_records SET evidence_strength = 'medium', updated_at = ?
                WHERE evidence_strength = 'low'
                  AND reference_id IN (SELECT reference_id FROM literature_fulltext_sources)
                  AND evidence_strength = 'low'
            """, (ts,)).rowcount
            print(f"  Low+fulltext → medium: {n2:,}")

            # Reject: non-traceable low evidence
            n3 = cur.execute("""
                UPDATE evidence_records SET curation_status = 'rejected', updated_at = ?
                WHERE evidence_strength = 'low'
                  AND reference_id NOT IN (SELECT reference_id FROM ref_literatures WHERE doi IS NOT NULL AND doi != '')
                  AND reference_id NOT IN (SELECT reference_id FROM literature_fulltext_sources)
            """, (ts,)).rowcount
            print(f"  Rejected (non-traceable): {n3:,}")

            conn.commit()
            upgrades["S4_low_cleanup"] = n1 + n2
        else:
            n_doi = conn.execute("""
                SELECT COUNT(*) FROM evidence_records WHERE evidence_strength = 'low'
                AND reference_id IN (SELECT reference_id FROM ref_literatures WHERE doi IS NOT NULL AND doi != '')
            """).fetchone()[0]
            print(f"  [DRY RUN] Upgrade low+DOI: {n_doi:,}")

    # ═══════════════════════════════════════════════════════════
    # FINAL
    # ═══════════════════════════════════════════════════════════
    print("\n" + "="*60)
    print("FINAL QUALITY DISTRIBUTION")
    print("="*60)

    if args.dry_run:
        print("\n[DRY RUN complete — no changes]")
    else:
        total_up = sum(upgrades.values())
        print(f"\n  Total upgrades: {total_up:,}")
        for s, n in upgrades.items():
            print(f"    {s}: {n:,}")

    for row in conn.execute("""
        SELECT evidence_strength, COUNT(*) as n FROM evidence_records
        GROUP BY evidence_strength ORDER BY n DESC
    """):
        pct = row['n']*100.0/total
        print(f"  {row['evidence_strength']:8s}: {row['n']:>10,} ({pct:.1f}%)")

    conn.close()
    print("\nDone.")

if __name__ == "__main__":
    main()
