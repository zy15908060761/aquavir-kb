# AquaVir-KB: A comprehensive knowledge base for viruses infecting aquatic invertebrates

## Abstract

Aquatic invertebrates underpin global aquaculture and marine ecosystem health, yet viral diseases remain poorly characterized at the knowledge-base level. We present AquaVir-KB (https://aquavirdb.com), a literature-mined knowledge base integrating 1,595 virus species, 13,891 target isolates, 27,096 viral proteins, and 353,160 structured evidence records from 9,065 publications (92.0% PMID-traceable) spanning 1950–2026. The database covers eight aquatic invertebrate phyla (Arthropoda, Mollusca, Cnidaria, Echinodermata, Porifera, Annelida, Platyhelminthes, Rotifera) across 63 countries. Built on a 140-table relational architecture with ICTV-aligned taxonomy (928 mapped species, 476 VMR mappings), AquaVir-KB provides explicit multi-dimensional evidence stratification (origin: primary/secondary/database; strength: high/medium/low; curation status: manual_checked/auto_imported/needs_review/rejected) for every virus–host association. Protein functional annotation covers 87.9% of 27,096 proteins through domain inference, and 792 RdRP sequences provide phylogenetic context across 18 viral families. The database is freely accessible via a REST API with full-text search and programmatic access, with bulk data downloads in FASTA and TSV formats under CC-BY 4.0. AquaVir-KB fills a critical gap by providing the first systematically curated, evidence-graded resource for aquatic invertebrate virology, transparently distinguishing experimentally confirmed associations from computationally inferred ones.

## Introduction

**The economic and ecological significance of aquatic invertebrate viruses.** Aquatic invertebrates dominate global aquaculture production, contributing over 28 million tonnes annually valued at approximately USD 100 billion. Viral pathogens cause the largest economic losses in this sector: white spot syndrome virus (WSSV; Nimaviridae) alone has caused cumulative losses exceeding USD 15 billion since emergence in the 1990s, while ostreid herpesvirus 1 (OsHV-1; Malacoherpesviridae) has driven mass mortality events in Pacific oyster populations across Europe, Australia, and New Zealand. Beyond aquaculture, marine invertebrates harbor vast viral diversity—metagenomic surveys have revealed thousands of novel RNA and DNA viruses from coral holobionts, sponge microbiomes, and echinoderm populations, many representing previously undescribed viral lineages with unknown ecological functions.

**Limitations of existing resources.** Several publicly available databases serve adjacent functions. NCBI Virus provides the broadest sequence coverage (>10 million accessions) but lacks structured evidence grading, curated host verification, or per-record literature traceability. The ICTV Virus Metadata Resource (VMR) provides authoritative taxonomy (11,273 recognized species) but host metadata are limited to coarse categorical annotations without species-level specificity or literature provenance. Virus-Host DB computationally infers >40,000 host associations from NCBI Taxonomy fields, yet these computationally derived links lack primary literature verification and evidence quality stratification. IMG/VR v3 catalogs 2.3 million uncultivated viral genomes from metagenomes but provides no curated host metadata. Crucially, none of these resources distinguish between a virus experimentally confirmed via Koch's postulates, one detected by PCR in clinical disease, and one identified solely as a sequence in a metatranscriptomic survey—a distinction that is critical for biosecurity and aquaculture disease management.

**The present work.** To address this gap, we developed AquaVir-KB, a comprehensive knowledge base for viruses infecting aquatic invertebrates. The database systematically integrates ICTV taxonomy, NCBI sequence metadata, Europe PMC literature, protein annotations (InterPro, Pfam, KEGG, UniProt), geographic occurrence data (GBIF, OBIS), and SRA metagenomic metadata within a single relational framework. Its central methodological contribution is an explicit multi-dimensional evidence stratification system that transparently communicates the provenance, strength, and curation status of every virus–host association. Here we describe the database architecture, data integration methodology, content statistics, and utility for the aquatic invertebrate virology community.

## Database construction and content

### Data sources and integration

AquaVir-KB integrates six primary data source types through a multi-stage ETL pipeline:

**Taxonomy.** The complete ICTV Master Species List (MSL41, 2025) was imported into dedicated `ictv_taxonomy` (17,554 records) and `ictv_vmr` (19,271 records) tables, providing the taxonomic backbone. Virus-to-taxonomy mappings were established through systematic species name matching and accession-based linking, yielding 476 VMR mappings and 928 ICTV-mapped status records.

**Sequence and isolate metadata.** Viral nucleotide accessions were retrieved from NCBI via Entrez E-utilities using targeted queries across eight aquatic invertebrate phyla. The database integrates 17,867 raw viral isolates (13,891 target isolates via release-filtered view, 3,052 with nucleotide sequence data), drawn from complete genome (389), partial genome (709), ICTV VMR catalogue (336), and literature/meta-genomic survey (156) sources.

**Literature mining.** Systematic literature searches were executed against Europe PMC and PubMed using 16 query strategies covering all target phyla. After deduplication, 9,065 unique references were retained (92.0% PMID coverage, 90.4% DOI coverage, spanning 1950–2026). A multi-stage text mining pipeline applied automated keyword and regular expression matching against titles, abstracts, and full-text XML (4,371 articles parsed), extracting virus–host associations, detection methods, and numerical measurements into structured evidence records.

**Protein annotation.** Viral proteins (27,096 total) were annotated through NCBI CDD batch search for conserved domain identification (87.9% coverage), supplemented by InterPro (427 annotations), KEGG pathway mapping (2,814 annotations), UniProt cross-referencing (11,351 annotations), and AlphaFold/ESMFold structure predictions (6,255 predicted structures).

**Geographic and ecological data.** Host occurrence data were integrated from GBIF (4,039 records) and OBIS (2,885 records), standardized to coordinate-level precision. Of 10,302 curated isolate profiles, 4,326 (42.0%) carry country-level geographic annotation spanning 63 countries.

**Metagenomic metadata.** 16,880 SRA runs from aquatic invertebrate metagenomic studies are indexed, with 400 runs confirmed to contain detectable viral sequences through NCBI Taxonomy analysis.

### Database architecture

AquaVir-KB is built on a 140-table, 45-view relational schema implemented in SQLite for local curation and PostgreSQL for production deployment. The architecture separates concerns across seven conceptual layers:

1. **Core entity layer** — `virus_master`, `viral_isolates`, `crustacean_hosts`
2. **Taxonomy layer** — `ictv_taxonomy`, `ictv_vmr`, `virus_ictv_mappings`, `virus_vmr_mappings`
3. **Evidence layer** — `evidence_records` (353,160 records), `infection_records` (9,519 records)
4. **Annotation layer** — `viral_proteins`, `core_genes`, domain annotations
5. **Enrichment layer** — KEGG, InterPro, STRING, UniProt, ViralZone integration tables
6. **Geographic layer** — GBIF, OBIS, sample collection metadata
7. **Provenance layer** — `data_provenance` (100,599 records tracking source-to-record lineage)

All records carry explicit provenance annotations, and all schema modifications are tracked through `database_maintenance_log` (34 entries). The database enforces referential integrity through foreign key constraints (verified zero violations) and passes `PRAGMA integrity_check`.

### Evidence stratification system

The key methodological contribution of AquaVir-KB is its three-dimensional evidence stratification:

**Evidence origin** distinguishes:
- **Primary evidence** (n = 13,121, 3.7%): derived from laboratory experiments and field studies
- **Secondary evidence** (n = 336,512, 95.3%): derived from automated literature mining of published reports
- **Database annotations** (n = 3,527, 1.0%): computationally inferred from external databases

**Evidence strength** (assigned by automated keyword-based decision tree):
- **High** (n = 46,033, 13.1%): records mentioning experimental infection, virus isolation, or pathology visualization
- **Medium** (n = 305,771, 86.5%): records with molecular detection or genomic characterization context
- **Low** (n = 1,356, 0.4%): records from metagenomic co-occurrence without host confirmation

**Curation status** tracks manual verification:
- **Manual-checked** (n = 93,180, 26.4%)
- **Auto-imported** (n = 145,705, 41.3%)
- **Needs review** (n = 7,681, 2.2%)
- **Rejected** (n = 106,594, 30.2%)

### Public access and API

The production database is deployed via Docker Compose with PostgreSQL 16, PgBouncer connection pooling, and nginx reverse proxy with HTTPS (Let's Encrypt). The REST API (FastAPI, OpenAPI 3.0) provides 50+ endpoints covering virus search, host lookup, family browsing, geographic queries, protein annotation retrieval, phylogenetic data access, and structured data downloads. Bulk data exports are available in FASTA format (2,507 target sequences, 113 complete genomes) and TSV format (26 tables, 323,619 rows, 102 MB). All data are released under CC-BY 4.0.

## Results and discussion

### Content overview

AquaVir-KB version 1.0 contains 1,595 active target viruses spanning eight aquatic invertebrate phyla. The taxonomic and genomic scope is summarized in Table 1.

**Taxonomic coverage.** Arthropoda (609 viruses, 38.2%) and Mollusca (396, 24.8%) dominate, reflecting the historical research focus on economically important crustaceans (shrimp, crab, lobster) and mollusks (oyster, abalone, mussel, clam). The database also covers Echinodermata (50), Porifera (42), Cnidaria (38), Platyhelminthes (30), Annelida (26), and Rotifera (2). Cross-phylum viruses recognized by ICTV account for 336 entries.

**Entry type distribution.** Complete genome records (389, 24.4%) represent fully characterized viruses with comprehensive sequence coverage. Partial genome records (709, 44.5%) include viruses with incomplete genomic data, typically from metagenomic surveys. ICTV VMR catalogue entries (336, 21.1%) are taxonomically recognized species awaiting additional sequence characterization. Literature candidate and metagenomic discovery records (156, 9.8%) represent recently identified viruses from published surveys.

**Evidence depth.** The 353,160 evidence records provide 93,180 manually verified association statements linking viruses to hosts, geographic locations, disease outcomes, and molecular characteristics. High-strength evidence (46,033 records) supports the most confident virus–host associations. The evidence coverage distribution is skewed: 1,018 viruses (63.8%) have five or fewer evidence records, while the best-studied viruses (WSSV, TSV, YHV, IHHNV, OsHV-1) account for a disproportionate share.

**Comparison with existing resources.** AquaVir-KB occupies a previously unfilled niche. NCBI Virus provides broader sequence coverage but no structured evidence grading. ICTV VMR offers authoritative taxonomy but no per-record literature traceability. Virus-Host DB achieves higher computational throughput but without manual curation or geographic detail. AquaVir-KB's unique value is the combination of (i) phylum-specific scope for aquatic invertebrates, (ii) transparent evidence stratification, (iii) per-record literature provenance, (iv) multi-dimensional data integration (taxonomy, genomics, proteomics, geography, ecology), and (v) systematic geographic indexing with coordinate-level precision.

### Use cases

AquaVir-KB enables several application scenarios relevant to the aquatic virology community:

**Disease emergence monitoring.** Biosecurity agencies can use the evidence-strength filter to distinguish experimentally confirmed pathogens from metagenomic detections when assessing emerging disease risks in aquaculture operations.

**Host range analysis.** The infection_records table (9,519 records) with multi-level host taxonomy enables systematic host range analysis across crustacean, mollusk, and echinoderm taxa.

**Geographic surveillance.** The 4,326 profiles with country-level geographic annotation enable spatial analysis of virus distribution patterns, with particular strength in Asia (602 curated profiles in China alone).

**Phylogenetic context.** The 792 RdRP sequences with phylogenetic placement provide immediate taxonomic context for novel virus discovery efforts, enabling rapid classification of newly sequenced isolates.

### Limitations and transparency

Several limitations warrant transparent acknowledgment. First, 95.3% of evidence records derive from automated literature mining rather than manual expert curation; users should interpret these as literature-derived signals requiring independent verification. Second, evidence coverage is highly skewed toward well-studied pathogens (WSSV, OsHV-1), with 63.8% of viruses having five or fewer evidence records. Third, 607 ICTV status entries remain under pending review, reflecting ongoing taxonomic reconciliation. Fourth, geographic coverage (42.0% of profiles) is incomplete, with strong bias toward Asia and North America. Fifth, protein functional annotations (87.9%) are domain-inferred rather than experimentally validated.

### Future directions

Development priorities for the next release cycle include: (i) SRA-based virus discovery using RdRP HMM profiling against the 16,880 indexed SRA runs, targeting an estimated 500–1,500 additional virus species; (ii) Chinese literature integration via CNKI-indexed journals; (iii) phylogenetic resolution of the 19 unclassified RNA virus entries; (iv) transition to a real-time update model with weekly ingestion of new NCBI and Europe PMC records; and (v) community curation interface enabling domain expert contributions.

## Data availability

AquaVir-KB is freely accessible at https://aquavirdb.com with no registration required. The REST API is documented via Swagger UI (/docs) and ReDoc (/redoc). Bulk data downloads are available at /downloads/ under CC-BY 4.0. Source code and deployment scripts are at https://github.com/zy15908060761/CDB. A versioned data archive is deposited at Zenodo (DOI pending). The database is designed for FAIR compliance and will be registered with FAIRsharing upon publication.

## Acknowledgements

To be completed.

## Conflict of interest

None declared.

## Funding

To be completed.
