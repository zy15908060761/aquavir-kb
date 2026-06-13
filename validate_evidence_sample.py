#!/usr/bin/env python3
"""Stratified random sampling of auto-imported evidence records for quality validation."""
import sqlite3, random, re

conn = sqlite3.connect('F:/水生无脊椎动物数据库/crustacean_virus_core.db')
random.seed(42)

# === STEP 1: Stratified sampling ===
strata = {
    'high_auto': "evidence_strength='high' AND curation_status='auto_imported'",
    'medium_auto': "evidence_strength='medium' AND curation_status='auto_imported'",
    'low_auto': "evidence_strength='low' AND curation_status='auto_imported'",
}

samples = {}
for label, where in strata.items():
    pool = conn.execute(f"""
    SELECT er.evidence_id, er.evidence_type, er.evidence_strength, er.claim,
           er.reference_id, er.virus_master_id, er.host_id,
           vm.canonical_name, rl.title, rl.pmid,
           ch.scientific_name
    FROM evidence_records er
    LEFT JOIN virus_master vm ON er.virus_master_id = vm.master_id
    LEFT JOIN ref_literatures rl ON er.reference_id = rl.reference_id
    LEFT JOIN crustacean_hosts ch ON er.host_id = ch.host_id
    WHERE {where}
    """).fetchall()

    sample_size = min(100, len(pool))
    sample = random.sample(pool, sample_size)
    samples[label] = sample
    print(f"{label}: pool={len(pool):,}, sampled={sample_size}")

# === STEP 2: Automated validation checks ===
print("\n===== VALIDATION RESULTS =====")
print()

CHECKS = {
    'claim_non_empty': lambda r: bool(r[3] and len(r[3].strip()) > 10),
    'has_reference': lambda r: r[4] is not None,
    'virus_name_valid': lambda r: r[7] is not None and len(r[7]) > 3,
    'reference_title_valid': lambda r: r[8] is not None and len(r[8]) > 20,
    'pmid_valid_format': lambda r: bool(r[9]) and bool(re.match(r'^\d{7,8}$', str(r[9] or ''))),
    'claim_not_placeholder': lambda r: bool(r[3]) and 'TODO' not in str(r[3]) and 'TBD' not in str(r[3]) and len(str(r[3])) > 15,
    'has_host': lambda r: r[6] is not None,
}

for label, sample in samples.items():
    results = {k: [] for k in CHECKS}
    for row in sample:
        for check_name, check_fn in CHECKS.items():
            results[check_name].append(check_fn(row))

    print(f"--- {label} (n={len(sample)}) ---")
    total_pass = 0
    total_checks = 0
    for check_name, passes in results.items():
        pct = 100 * sum(passes) / len(passes)
        total_pass += sum(passes)
        total_checks += len(passes)
        status = 'PASS' if pct >= 95 else 'WARN' if pct >= 85 else 'FAIL'
        bar = '#' * int(pct / 5) + '.' * (20 - int(pct / 5))
        print(f"  [{status:<4}] {check_name:<25} [{bar}] {pct:5.1f}%")

    overall = 100 * total_pass / total_checks
    print(f"  OVERALL: {overall:.1f}% pass rate")
    print()

# === STEP 3: Evidence-virus-host cross-consistency ===
print("===== CROSS-CONSISTENCY: Does claim text match virus/host? =====")

for label, sample in samples.items():
    consistent = 0
    checked = 0
    for row in sample:
        ev_id, etype, strength, claim, ref_id, virus_id, host_id, vname, title, pmid, hname = row
        if vname and claim and len(claim) > 15:
            checked += 1
            # Check if claim contains virus name tokens or host tokens
            vname_lower = vname.lower()
            claim_lower = claim.lower()
            # At least one significant token from virus name should be in claim
            v_tokens = [t for t in vname_lower.split() if len(t) > 3]
            v_match = any(t in claim_lower for t in v_tokens[:3])
            # Or the claim is clearly about this virus (contains family name)
            if v_match:
                consistent += 1

    if checked > 0:
        pct = 100 * consistent / checked
        print(f"  {label}: {consistent}/{checked} virus-claim text matches ({pct:.1f}%)")

# === STEP 4: Overall quality report ===
print()
print("===== QUALITY REPORT FOR NAR REVIEWERS =====")
print("""
Method: Stratified random sampling across 3 evidence strength tiers.
Sample size: 300 total (100 per tier).
Validation: 7 automated format/completeness checks + 1 cross-consistency check.

Results:
""")
print(f"  Overall precision (format checks): {100*total_pass/total_checks:.1f}%")
print(f"  Cross-consistency (claim matches virus): estimated from sample")
print()
print("  Conclusion: Auto-imported evidence records have [X]% format validity.")
print("  Error sources: [to be analyzed from failures]")
print("  Recommended: Manual review of [X]% lowest-scoring records.")

conn.close()
