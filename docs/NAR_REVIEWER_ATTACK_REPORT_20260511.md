# NAR Reviewer Attack Report - 2026-05-11

This report records reviewer-style failure modes found in the current
CrustaVirus DB release candidate and the fixes applied during this audit.

## Reviewer Attack Findings

### 1. False pass in release gate

**Attack:** `release_gate.py` reported `passed: true` while core evidence
worklists still contained unreviewed records:

- `evidence_needs_review`: 47
- `diagnostic_methods_need_review`: 18
- `ictv_pending_review`: 20
- `host_range_evidence_unreviewed`: 168
- `pathogenicity_evidence_unreviewed`: 171
- `environmental_evidence_unreviewed`: 711
- `outbreak_events_unreviewed`: 53
- `candidate_profile_records_not_for_public_claims`: 356

**Reviewer objection:** A NAR reviewer could reject this as an internal
inconsistency: the project claims a strict release gate while the gate allows
unreviewed biological evidence to remain as warnings.

**Fix:** `release_gate.py` now treats these worklists as blocking failures by
default. `--allow-curation-warnings` remains available only for local UI/source
checks and is explicitly documented as not acceptable for NAR readiness.

### 2. Weak public URL validation

**Attack:** `nar_readiness_check.py` accepted any non-empty `PUBLIC_URL.txt`.
A localhost, private IP, or HTTP placeholder could satisfy the old check.

**Reviewer objection:** NAR requires a functional, freely accessible database
website for review. A local or insecure placeholder URL is not reviewable.

**Fix:** `nar_readiness_check.py` now validates that the URL is HTTPS, has a
real hostname, and is not localhost, `.local`, loopback, or private RFC1918
address space.

### 3. Geography false positives

**Attack:** `validate_database.py` flagged Aruba, Faroe Islands, and New
Caledonia as non-standard countries even though these are legitimate ISO
territory names in marine collection metadata.

**Reviewer objection:** False positives in quality checks reduce confidence in
the QC system and waste manual review time.

**Fix:** The country whitelist now includes marine-relevant ISO territories:
Aruba, Faroe Islands, French Polynesia, and New Caledonia.

### 4. Documentation ambiguity

**Attack:** README and data-availability text did not clearly separate strict
NAR gating from compatibility checks.

**Reviewer objection:** Authors or reviewers could read a compatibility pass
as evidence of submission readiness.

**Fix:** README and DATA_AVAILABILITY now state that unresolved curation
worklists make the strict gate fail, and that `--allow-curation-warnings` is
not a NAR readiness mode.

## Remaining Submission Blockers

These are not fixed because they require real deployment or real manual
curation, not code edits:

- No public no-login HTTPS URL is configured.
- The public manual-reviewed evidence layer currently has 0 records.
- 161 references are not associated with isolates and need a decision:
  link to records, mark as background/context, or remove from the release.
- Large unreviewed worklists remain open; they cannot support virulence,
  temperature, host-range, environmental, outbreak, or diagnostic claims.

## Verification

Commands run after the fixes:

- `python release_gate.py` now fails under strict mode as intended.
- `python release_gate.py --allow-curation-warnings` passes for local
  source/UI checks.
- `python nar_readiness_check.py` fails because the public URL and reviewed
  evidence layer are genuinely missing.
- `OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python validate_database.py --check --report`
  reports only one LOW issue: 161 orphan references.
- `python tests/test_data_quality.py` passes 9/9 checks.
- `python tests/test_db_connection.py` passes.
- `python -m py_compile release_gate.py nar_readiness_check.py validate_database.py tests/test_data_quality.py`
  passes.
