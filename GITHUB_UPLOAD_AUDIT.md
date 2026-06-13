# GitHub Upload Audit

Generated for the local workspace before creating a public/private GitHub repo.

## Hard Rule

Do not upload the whole `F:\甲壳动物数据库` directory. It contains databases, backups,
raw sequence files, release bundles, local reports, generated downloads, and
temporary audit scripts.

## Upload These Now

Core application:

- `backend.py`
- `api_models.py`
- `db_utils.py`
- `schema_version.py`
- `genbank_metadata_utils.py`
- `requirements.txt`
- `environment.yml`
- `templates/`
- `tests/`
- `vendor/` if it contains only small source files needed at runtime

Release and validation scripts:

- `release_gate.py`
- `nar_readiness_check.py`
- `validate_database.py`
- `build_downloads.py`
- `export_release_tsvs.py`
- `build_release_bundle.py`
- `build_sqlite_core_db_v2.py`
- `build_public_download_metadata.py`
- `publication_hardening.py`
- `submission_blocker_fixes.py`
- `full_sync_pipeline.py`
- `maintain_analysis_views.py`
- `seed_core_provenance.py`

Important curation/rebuild scripts, if you want reproducibility:

- `import_ictv_msl.py`
- `import_ictv_vmr.py`
- `match_ictv.py`
- `import_virushostdb.py`
- `import_viralzone.py`
- `import_gbif.py`
- `import_obis_fishbase.py`
- `import_geo_sra.py`
- `import_pride.py`
- `enrich_*.py`
- `fetch_*.py`
- `fix_*.py`
- `batch*.py`

Small static assets:

- `world.json`
- `china.json`
- `public_assets/`
- `schema_dump.sql`

Documentation:

- `README.md`
- `LICENSE.txt`
- `CITATION.cff` (but keep in mind it still has placeholder DOI/authors)
- `DATA_AVAILABILITY.md` (draft only, not NAR-ready)
- `DATA_USE_AGREEMENT.md`
- `SUSTAINABILITY.md` (draft only, not NAR-ready)
- `NOVELTY_COMPARISON.md`
- `THIRD_PARTY_LICENSES.md`
- `AUTO_SYNC_README.md`
- `MANUAL_REVIEW_CHECKLIST.md`
- `GITHUB_UPLOAD_AUDIT.md`

Config examples:

- `notification_config.example.json`

## Do Not Upload

Large or generated data:

- `crustacean_virus_core.db`
- `crustacean_virus_core*.db`
- `*.db`, `*.db-wal`, `*.db-shm`, `*.bak`
- `backups/`
- `releases/`
- `downloads/exports/`
- `public_downloads/`
- `sequences/`
- `ncbi_metadata/`
- `external_data/`
- `blastdb/`
- `tools/`
- `cdhit-4.8.1/`
- `cdhit-4.8.1.zip`
- `test_dl.zip`
- `graphviz_installer.exe`

Secrets/local runtime:

- `notification_config.json`
- `.env`
- any `*.pem`, `*.key`, `*.p12`, `*.crt`
- server passwords, API keys, SMTP passwords, webhook URLs

Generated local reports and scratch:

- `reports/`
- `maintenance_archive/`
- `literature_curation_v2/`
- `tmp_*.py`, `tmp_*.json`, `tmp_*.txt`
- `_tmp_*.py`, `_tmp_*.json`
- `*_audit*.py`, `*_check*.py`, `*_probe*.py`
- `*.log`
- `__pycache__/`

Generated office/binary files:

- `*.docx`
- `*.pptx`
- `*.xlsx`
- `*.zip`

## Files Needing Manual Review Before Public Repo

- `download_crustacean_virus_metadata_requests.py`: contains placeholder email
  text. Replace with environment variable or documented placeholder before
  public release.
- `CITATION.cff`: still has placeholder DOI/authors/affiliation.
- `DATA_AVAILABILITY.md`: still has placeholder repository URL.
- `SUSTAINABILITY.md`: still has TBD institution/contact/funding fields.
- Any script that accepts tokens via command line is okay, but never commit real
  token values or command logs.

## Where To Put The Database

Do not put the 235 MB SQLite database in the normal GitHub repo.

Recommended:

- Put release bundles in Zenodo/Figshare and cite the DOI.
- Put the production database on the cloud server.
- Optionally attach release assets to GitHub Releases later, after confirming
  file size and repository policy.

## Suggested First Commit

Use GitHub Desktop or command line, but do not run `git add .` blindly.

Command-line starter:

```powershell
git init
git add .gitignore README.md LICENSE.txt CITATION.cff DATA_AVAILABILITY.md DATA_USE_AGREEMENT.md SUSTAINABILITY.md NOVELTY_COMPARISON.md THIRD_PARTY_LICENSES.md GITHUB_UPLOAD_AUDIT.md
git add backend.py api_models.py db_utils.py schema_version.py genbank_metadata_utils.py requirements.txt environment.yml
git add templates tests public_assets
git add release_gate.py nar_readiness_check.py validate_database.py build_downloads.py export_release_tsvs.py build_release_bundle.py build_sqlite_core_db_v2.py publication_hardening.py submission_blocker_fixes.py full_sync_pipeline.py
git status
```

Before commit, inspect `git status` carefully. If any `.db`, `.xlsx`, `.fasta`,
`reports/`, `downloads/`, `backups/`, `sequences/`, or `notification_config.json`
appears, stop and fix `.gitignore` or unstage it.
