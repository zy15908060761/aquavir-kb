# Data Availability - AquaVir-KB

This is the final NAR Data Availability statement for AquaVir-KB v1.0.

## Current Status

- Source-code repository: https://github.com/zy15908060761/CDB
- Database release status: released v1.0
- Public web URL: https://aquavirdb.com
- Data archive DOI: 10.5281/zenodo.pending (pending deposition)

Large data files are intentionally excluded from the GitHub repository. The
production SQLite database, FASTA files, public download workbooks, and release
bundles must be distributed through the production server and a DOI-backed
archive, not through the normal source-code repository.

## Release-Filtered Local Artifacts

The current local release-filtered artifacts are generated from the live
database by `build_downloads.py` and `export_release_tsvs.py`. The strict
release gate fails while unreviewed evidence worklists remain open; the
compatibility flag `--allow-curation-warnings` is for local UI/source checks
only and is not acceptable for NAR readiness.

| Artifact | Current local count | Scope |
|---|---:|---|
| Strict-target isolate metadata | 2,197 records | release-filtered target isolates |
| All strict-target FASTA | 2,195 sequences | release-filtered target isolates with sequence files |
| Complete-genome FASTA | 111 sequences | complete-genome subset with plausible length |
| Host-virus network | 93 edges | strict-target host-virus links |
| Reviewed evidence workbook | 0 records | manual-checked evidence only |
| Release TSV exports | 189,850 rows | filtered/public export policy in `tsv_manifest.json` |

The reviewed evidence workbook is intentionally empty until manual evidence
curation is completed. Candidate virulence, temperature, host-range,
environmental, pathogenicity, and outbreak records must not be described as
manual-reviewed knowledge.

## Primary Public Sources

CrustaVirus DB integrates records derived from public sources including NCBI
Nucleotide/GenBank, NCBI Taxonomy, ICTV MSL/VMR, UniProt, InterPro, KEGG,
STRING, AlphaFold DB, PRIDE, SRA, GEO, GBIF, OBIS, Europe PMC, PubMed,
bioRxiv/medRxiv, ViralZone, Virus-Host DB, WoRMS, FishBase/SeaLifeBase, EOL,
OpenAlex, Semantic Scholar, Crossref, FAO, NACA, CNKI, and Wanfang.

Third-party source records retain their original licenses and terms. The local
curated metadata and documentation are intended for CC BY 4.0 release unless a
source-specific restriction applies.

## Reproducibility Files

- Schema dump: `schema_dump.sql`
- Rebuild utility: `build_sqlite_core_db_v2.py`
- Public download builder: `build_downloads.py`
- TSV export builder: `export_release_tsvs.py`
- Release gate: `release_gate.py`
- NAR readiness check: `nar_readiness_check.py`
