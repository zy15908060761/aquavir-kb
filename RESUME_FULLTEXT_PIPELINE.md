# Fulltext OA Pipeline Resume Checkpoint

Last saved: 2026-05-13 19:?? local time

## Current Goal

Use the 7,482 references in `ref_literatures` to legally discover/openly fetch full text where available, extract useful information, fill safe database fields, and export a manual checklist for references without open full text.

## Important Boundary

Use only legal/open channels:

- local cache
- PubMed Central / Europe PMC fullTextXML
- Europe PMC open PDF links
- Unpaywall open PDF links
- publisher/open landing pages only when openly available

Do not bypass paywalls. References without open full text go to the manual checklist.

## Database

Working directory:

`F:\甲壳动物数据库`

Main DB:

`F:\甲壳动物数据库\crustacean_virus_core.db`

Most recent full pipeline backup before fulltext work:

`F:\甲壳动物数据库\backups\crustacean_virus_core_before_fulltext_pipeline_20260513_191601.db`

## Resume State File

Latest machine-readable progress:

`F:\甲壳动物数据库\reports\fulltext_oa_pipeline\resume_state_latest.json`

At save time:

- `ref_literatures`: 7,482
- distinct references with fulltext-source status: 2,027
- `literature_fulltext_sources`: 2,491
- `literature_fulltext_sections`: 8,000
- downloaded/open local sources:
  - Europe PMC XML: 374
  - Europe PMC PDF: 201
  - Unpaywall PDF: 33
  - local cache: 2
- no open access / landing only:
  - OA discovery no_oa: 560
  - Unpaywall landing only: 142
- failed attempts: 1,179

## Scripts Added/Modified

Core fulltext pipeline:

`run_fulltext_oa_pipeline.py`

It is resumable. It skips references already represented in `literature_fulltext_sources` unless run with `--no-resume`.

Useful command to continue:

```powershell
python run_fulltext_oa_pipeline.py --sleep 0.1
```

If sandbox blocks network, rerun with escalated permissions for the same command. It needs access to NCBI, Europe PMC, and Unpaywall.

## Database Tables Added

- `literature_fulltext_sources`
- `literature_fulltext_sections`

Existing staging tables used:

- `literature_backfill_candidates`
- `literature_backfill_candidate_promotions`
- `literature_backfill_runs`

## Diagnostic Backfill Status

Already completed before fulltext crawl:

- `diagnostic_methods`: 402 total
- literature-driven diagnostic promotions: 300
- auto-kept literature diagnostics: 259
- downgraded to needs_review: 41

Main reports:

- `reports\literature_backfill_candidates\promoted_diagnostic_methods_all_refined.csv`
- `reports\literature_backfill_candidates\diagnostic_pilot_refinement_actions.csv`

## Optimization Cycles Already Done

1. Fixed diagnostic one-to-many promotion tracking in script.
2. Cleared misleading direct `promoted_record_id` for promoted diagnostic staging rows; bridge table is authoritative.
3. Added stable `dedupe_key` to `literature_backfill_candidates` and updated staging import script.
4. Protected triage script from overwriting already reviewed/promoted rows.
5. Lowered automatic diagnostic promotion evidence strength to `low` until manual review.
6. Tightened entity matching and blocked document-level entity fallback from strict candidate promotion in extraction script.

## Next Steps After Resume

1. Continue fulltext OA crawl:

```powershell
python run_fulltext_oa_pipeline.py --sleep 0.1
```

2. Periodically inspect progress:

```powershell
python -c "import sqlite3; con=sqlite3.connect(r'F:\甲壳动物数据库\crustacean_virus_core.db'); print(con.execute('select count(distinct reference_id) from literature_fulltext_sources').fetchone()); print(con.execute('select count(*) from literature_fulltext_sections').fetchone())"
```

3. After all 7,482 references have a source status, rerun candidate extraction using local cache/fulltext sections. The current extraction script may need an update to read `literature_fulltext_sections` directly.

4. Promote only safe candidates:

- diagnostics: already partly done; can continue after QA
- pathogenicity: first pilot should be very conservative, about 196 candidates max, based on subagent guidance
- references without open full text: export `manual_fulltext_checklist.csv`

## Important Warnings

- Do not rerun old triage in a way that overwrites human/promoted statuses.
- Do not promote all approved pathogenicity candidates. Many are noisy.
- Use `literature_backfill_candidate_promotions` as authoritative traceability for one-to-many production records.
- Keep automatic evidence strength low until manual review.
