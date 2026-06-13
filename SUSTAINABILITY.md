# Sustainability Plan - AquaVir-KB

This is a production sustainability plan. It represents a completed NAR five-year maintenance commitment until the hosting institution,
responsible PI, long-term contact address, production server, and archive DOI
are finalized.

## Current Status

| Item | Current state |
|---|---|
| Public source repository | https://github.com/zy15908060761/CDB |
| Production web server | pending |
| Stable public URL | pending |
| Versioned data archive DOI | pending |
| Named hosting institution | pending confirmation |
| Named responsible PI | pending confirmation |
| Long-term contact email | pending confirmation |

## Planned Maintenance Model

| Data layer | Planned update cycle | Mechanism |
|---|---|---|
| NCBI GenBank sequences | quarterly | `incremental_import.py` plus release gate |
| ICTV taxonomy | annually | `import_ictv_msl.py`, `import_ictv_vmr.py` |
| UniProt / InterPro / KEGG / STRING | twice yearly | enrichment scripts with source-specific rate limits |
| GBIF / OBIS occurrences | twice yearly | `fetch_gbif.py`, `fetch_obis.py` |
| Literature metadata | monthly | PubMed, Europe PMC, and related literature scripts |
| Manual curation worklists | continuous | `publication_hardening.py` and manual review exports |
| Quality audit | every release | `release_gate.py`, `validate_database.py`, `nar_readiness_check.py` |

## Archiving Plan

The production release should include:

- SQLite database snapshot
- release-filtered public downloads
- TSV exports with row filters and SHA256 checksums
- schema dump
- release gate and validation reports
- source-code tag corresponding to the release
- DOI-backed archive on Zenodo, Figshare, or an institutional repository

## Five-Year Commitment Fields To Complete

Before NAR submission, fill in:

- hosting institution
- responsible PI
- technical maintainer
- data curator
- long-term institutional email
- funding or institutional support source
- domain owner
- production server owner
- fallback archive plan if active funding ends

Until those fields are completed with real names and real institutional
responsibility, this document is a plan, not a valid NAR sustainability claim.
