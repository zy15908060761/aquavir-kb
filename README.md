# AquaVir-KB

AquaVir-KB is a production knowledge base for a crustacean-associated virus database and FastAPI web application.

This repository contains application code, validation scripts, templates, and documentation drafts. It does not contain the production SQLite database, sequence files, backups, generated downloads, or private configuration files.



## Data Availability

The production database and release bundles will be archived separately through Zenodo, Figshare, or an equivalent long-term repository after version freeze. Large data files are intentionally excluded from this GitHub repository.

## Do Not Commit

- `*.db`
- `backups/`
- `public_downloads/`
- `downloads/`
- `sequences/`
- `reports/`
- `external_data/`
- `notification_config.json`
- `.env`

## Local Checks

```bash
python release_gate.py
python nar_readiness_check.py
python validate_database.py --check --report
```

`release_gate.py` fails by default when manual curation worklists remain open.
`python release_gate.py --allow-curation-warnings` is only for local UI/source
checks and must not be used as evidence of NAR readiness.

API smoke tests require a running backend:

```bash
uvicorn backend:app --host 127.0.0.1 --port 8000
python tests/run_all_tests.py
```

## Main Components

- `backend.py`: FastAPI application and server-rendered pages.
- `templates/`: web templates.
- `public_assets/`: small public map assets.
- `release_gate.py`: local release-safety gate.
- `nar_readiness_check.py`: NAR readiness checks that include non-code blockers.
- `build_downloads.py`: release-filtered public download builder.
- `export_release_tsvs.py`: release-filtered TSV export builder.
- `validate_database.py`: data-quality validation.
- `tests/`: local smoke tests.

## License

Code and local curated metadata are prepared for open release, but the final
license and DOI-backed data citation must be confirmed before public NAR
submission. Third-party source records retain their original terms.
