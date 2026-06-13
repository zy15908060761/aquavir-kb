# CrustaVirus DB — Manuscript Outline v2

**Date:** 2026-05-12
**Status:** Draft for review
**Target:** NAR Database Issue (primary), Database journal (backup)
**Based on:** R1 comprehensive audit, R2 red-team review, database queries from crustacean_virus_core.db (v1, 2026-05-08)

---

## 1. Title Candidates

### Recommended (short, honest, scoped):
**CrustaVirus DB: a multi-dimensional knowledge graph of crustacean-associated viruses integrating sequence, taxonomy, host ecology, and geographic distribution**

### Alternative 1 (more conservative):
**CrustaVirus DB: an integrated resource for crustacean virus genomics, host associations, and geographic occurrence**

### Alternative 2 (function-focused, for backup journal):
**CrustaVirus DB: a curated database of crustacean viruses with multi-source protein annotations and ecological context**

### REJECTED (per R2 audit guidance):
- Any title implying "predictive modeling" or "virulence/temperature" — the evidence layer is empty (0 reviewed records)
- Any title claiming "comprehensive" or "complete" — 505/526 virus species have zero evidence records
- Any title mentioning "AI/ML" — `model_performance_metrics` table is empty

---

## 2. Abstract (~250 words)

> CrustaVirus DB is a multi-dimensional knowledge graph that integrates genomic, taxonomic, ecological, and geographic data for viruses associated with crustacean hosts. The database catalogs 526 virus species across 3,783 isolates, of which 2,197 are classified as strict-target (crustacean-associated) isolates, linked to 104 crustacean host species via 3,107 infection records. Genomic data are integrated from NCBI GenBank, with protein annotations mapped from UniProt, InterPro, KEGG, and AlphaFold/ESMFold structural predictions. Host ecological traits (habitat, aquaculture status, IUCN status) are compiled from WoRMS, FishBase, and SeaLifeBase, while geographic occurrence data span 35 countries with coordinate-level precision for 63.7% of curated profiles. The database distinguishes three data tiers: core (175 manually reviewed isolates), extended (1,416 quality-filtered records), and unverified (612 candidate records requiring curation). Fifty-six outbreak events are documented with mortality estimates and literature provenance. The underlying schema (121 tables, 27 views) implements a multi-layer knowledge graph design that separates raw sequence metadata from curated evidence, enabling traceable data quality assessment. A FastAPI web interface provides RESTful access, keyword search, and interactive visualization. CrustaVirus DB is freely available at [URL] under CC BY 4.0, with all source code at https://github.com/zy15908060761/CDB. We anticipate that this resource will accelerate research in crustacean virology, aquaculture disease management, and host-virus evolutionary biology.

**Note:** The abstract avoids overclaiming. The 175 "core" records are manually reviewed; the remainder are auto-imported with quality filters.

---

## 3. Introduction Structure

### 3.1 The crustacean virology problem
- **Claim:** Crustaceans (shrimp, crabs, crayfish, lobsters) underpin a ~$70B global aquaculture industry, yet viral disease remains the single largest production constraint.
- **Evidence from DB:** 56 outbreak events with mortality rates up to 100%; top hosts are commercial penaeid shrimp (L. vannamei, P. monodon).
- **Citation strategy:** FAO aquaculture reports, NACA disease reports, published WSSV/YHV/IHHNV epidemiology reviews.

### 3.2 Fragmented data landscape
- **Problem:** GenBank entries for crustacean viruses are scattered across 30+ families, inconsistently annotated (many isolates lack host metadata or collection coordinates).
- **Evidence from DB:** 
  - 505/526 virus species have zero evidence_records linked
  - 52 ref_literatures have no PMID or DOI (traceless)
  - Only 53.9% of curated profiles have collection_year recorded
- **Existing resources gap:** ICTV VMR provides taxonomy only; ViralZone is family-level; NCBI Virus has crustacean filter but no curated host-virus links, ecological annotations, or outbreak data.
- **What's missing:** No single resource integrates *all* of: viral sequence + host taxonomy + host ecology + geographic occurrence + outbreak epidemiology + protein functional annotation.

### 3.3 The knowledge graph approach
- **Differentiator:** CrustaVirus DB is not a sequence archive. It is a **multi-layer knowledge graph** where the core entity (virus species) is connected via typed edges to hosts, geographic locations, literature references, protein annotations, and evidence records.
- **Data tiering system:** Instead of presenting all data as equally validated, we implement three tiers (core / extended / unverified) with explicit curation status tracking.
- **Novelty argument (honest):** The integration layer itself is novel — the *act of linking* virus isolates to standardized host taxonomy, host ecological traits, standardized geography, and evidence-backed outcome data is not done by any existing resource. The individual data sources are all public; the integration is the contribution.

### 3.4 Scope and roadmap
- Current release: v1 (2026-05-08), 526 species, 2,197 strict-target isolates
- Planned expansion: Track A (SRA virome mining) and Track B (deep protein annotation)
- Sustainability: Zenodo deposition, institutional hosting plan

---

## 4. Results Sections

### Section R1: Database Architecture and Data Model

**Narrative:** Describe the multi-layer schema design. The database comprises 121 tables organized into layers: (1) sequence layer (viral_isolates, viral_proteins), (2) taxonomy layer (virus_master, crustacean_hosts), (3) occurrence layer (sample_collections, isolate_curated_profiles with geography), (4) evidence layer (evidence_records, ref_literatures), (5) annotation layer (protein functional data), (6) curation layer (worklist tables, curation_conflicts, curation_priority_queue).

**Key statistics to present:**
- 121 tables, 27 views, 216 indexes
- Schema version: v1 (2026-05-08), documented via `v_data_dictionary` view
- Data tiering: core (175), extended (1,416), unverified (612)
- Release gate mechanism filters non-crustacean data from public surfaces

**Figures/Tables:**
- **Figure 1:** Entity-relationship diagram showing the six layers and their interconnections. (RED FLAG from R2: Needs to capture enrichment topology, not just generic ER.)
- **Table 1:** Summary of database content by data tier and category.

**Supporting queries:**
```sql
SELECT dataset_tier, COUNT(*) FROM isolate_curated_profiles GROUP BY dataset_tier;
SELECT COUNT(*) FROM virus_master;
SELECT COUNT(*) FROM viral_isolates;
SELECT COUNT(*) FROM viral_proteins;
```

**Data gaps:**
- 30 host_genome_artifact records still in curated_profiles (should be excluded from strict-target)
- 877 sequence_scope_artifact records — what are these? Need audit before publication
- No formal ontology alignment (OWL/RDF/JSON-LD) — FAIR compliance gap

---

### Section R2: The Crustacean Virome Landscape

**Narrative:** Present the taxonomic composition of known crustacean viruses, genome type distribution, completeness profile of available sequences, and host range breadth.

**Key statistics:**
- **Host perspective:** 104 crustacean host species, 8 major host groups
  - Penaeid shrimp: 28 species (major aquaculture)
  - Crabs: 17 species
  - Palaemonid shrimp: 11 species
  - Crayfish: 5, lobster: 3, fairy shrimp: 5, barnacle: 2, krill: 1, isopod: 1, mantis shrimp: 1
  - Plus 22 non-crustacean records (E. coli, etc. — lab artifacts)
- **Virus taxonomy (master level):** 526 species across 30+ families
  - Marnaviridae: 153 (29.1%)
  - Picornaviridae: 140 (26.6%)
  - Yanviridae: 43 (8.2%)
  - Solemoviridae: 40 (7.6%)
  - Unclassified: 24
  - Astroviridae: 19, Weiviridae: 16, Dicistroviridae: 8, Nodaviridae: 5, Potyviridae: 4
- **Genome type distribution:** ssRNA(+) dominates at 91.3% (480/526 master species)
  - dsDNA: 4, ssDNA: 3, dsRNA: 3, ssRNA(-): 8
  - 10 untyped or ambiguous
- **Sequence completeness:** Top isolate-level families by count: Nimaviridae (1,274, includes WSSV strains), Dicistroviridae (453), Roniviridae (216), Marnaviridae (184)

**Figures/Tables:**
- **Figure 2:** Pie/donut chart — Genome type distribution across virus master species
- **Figure 3:** Bar chart — Top 15 virus families by species count
- **Figure 4:** Host group composition bar chart
- **Table 2:** Top 15 crustacean hosts by infection record count (with aquaculture status)

**Data gaps:**
- **BLOCKER:** Many virus species come from metagenomic studies (e.g., Changjiang virus, Beihai virus) — these may represent environmental RNA sequences rather than true crustacean viruses. The "host association" is often inferred from water/sediment sampling location, not infection. Need to distinguish "detected in crustacean samples" from "infects crustaceans."
- **BLOCKER:** 22 non-crustacean hosts in the host table (E. coli, yeast, etc.) — these are cloning hosts, not biological hosts. Must be flagged or excluded from host-virus claims.
- **MAJOR:** The 1,274 Nimaviridae count is inflated by WSSV strain sequencing projects — most are nearly identical genomes. Need to clarify "isolates vs. unique sequences."
- **MINOR:** 10 virus_master records have empty genome_type.

---

### Section R3: Protein Functional Annotation (placeholder for Track B results)

**Narrative:** Describe the protein annotation pipeline integrating UniProt, InterPro, KEGG, and structural predictions. This section will be substantially expanded after Track B execution.

**Current state (pre-Track B):**
- 22,823 viral protein sequences (all with translations)
- 6 virus master species have NO associated proteins (need investigation)
- Annotation coverage is extremely low:
  - GO terms: 0.4% (need exact count from viral_proteins_annotation or go_annotation tables)
  - KEGG orthologs: <0.1%
  - InterPro domains: 16.4% (estimate from R1 audit)
  - UniProt matches: 49.7% (estimate)
  - PDB/AlphaFold structures: 0.1%
- **Honest assessment:** The current annotation coverage is too sparse to support a standalone protein section. This section will depend entirely on Track B output.

**Planned after Track B:**
- ESMFold structure predictions for all proteins
- InterProScan domain annotation pipeline
- KEGG pathway mapping via GhostKOALA or similar
- STRING interaction network mapping
- Then present: % coverage by annotation type, most common domains, structural novelty

**Figures/Tables (contingent on Track B):**
- **Figure 5:** Annotation coverage bar chart (before/after Track B)
- **Table 3:** Top 20 InterPro domains identified
- **Figure 6:** Example ESMFold predicted structures with pLDDT confidence

**Data gaps:**
- **CRITICAL blocker:** If Track B does not substantially improve coverage, this section must be reduced to a brief Methods paragraph. Do NOT publish with <5% annotation coverage as a "Results" section.
- **MAJOR:** 186 proteins contain non-standard amino acids (X, B, Z, J) — these may fail structural prediction tools.
- **MAJOR:** `functional_annotation_status` defaults to "unannotated" — we need to verify actual annotation pipeline results.
- **MINOR:** `ec_number` field is nearly empty.

---

### Section R4: Host-Virus Ecology and Geographic Distribution

**Narrative:** Present the geographic distribution of crustacean virus isolates, host ecological traits, and the integration of virus occurrence with host distribution data from GBIF/OBIS.

**Key statistics:**
- **Geographic coverage:** 35 countries represented in sample_collections and isolate_curated_profiles
  - Top countries: China (602), Mexico (355), India (129), Thailand (128), Bangladesh (119)
  - 63.7% of curated profiles have country-level data
  - 53.9% have collection year (range 1991-2025)
  - 63.7% have coordinate-level precision
- **Host ecology:** 
  - 28 commercial aquaculture host species
  - 16 major aquaculture species (by production volume)
  - Habitats: marine (48.7%), marine/aquaculture (25.6%), freshwater (28.2%), salt lake (7.7%)
- **Outbreak events:** 56 documented, with mortality rates (WSSV: 90-100%, YHV: 80-100%, TSV: 40-95%)
  - BUT: Only 3/56 are manually reviewed; 53 remain `needs_review`

**Figures/Tables:**
- **Figure 7:** World map of virus isolate collection locations (from isolate_curated_profiles with coordinates)
- **Figure 8:** Host habitat vs. virus family heatmap
- **Figure 9:** Temporal trend of isolate collection years (1991-2025)
- **Table 4:** Top-10 countries with isolate counts and predominant virus families
- **Supplementary Figure S1:** GBIF/OBIS host distribution overlays with virus occurrence points

**Data gaps:**
- **BLOCKER:** Only 53.9% of curated profiles have collection_year — the temporal trend figure will be misleading if we don't note that recent years are overrepresented due to better metadata practices.
- **BLOCKER:** Outbreak data quality is poor — 53/56 events are `needs_review`. Cannot claim validated outbreak patterns. Must present as "documented but unvalidated."
- **MAJOR:** Coordinate precision varies wildly — some points are country-centroid level, others are precise GPS. Must clearly flag precision tiers.
- **MAJOR:** The GBIF/OBIS integration needs verification — we need to check whether the imported occurrence data is actually linked to virus data or just co-located.
- **MINOR:** 36.3% of curated profiles lack country data entirely — these are mostly older GenBank records without geographic metadata.

---

### Section R5: Predictive Applications (honest, scoped-down version)

**Narrative:** Rather than claiming predictive power (which the R2 audit rightly criticized as overreach), this section should discuss the *infrastructure for prediction* — the data layers that *enable* future predictive modeling.

**What we actually have:**
- 125 virulence evidence records, 18 temperature tolerance records, 72 mortality records
- Evidence layer design separates raw from reviewed (current reviewed count: 0)
- Literature-backed host range data (90 host_range evidence_records)
- 56 outbreak events with structured severity metadata
- Host ecological trait matrix (habitat, aquaculture status, IUCN status)
- `model_performance_metrics` table exists but is EMPTY (0 rows)

**Honest framing:**
> "The database schema includes tables designed to support predictive modeling of virulence determinants, thermal tolerance profiles, and outbreak risk. However, the current release contains zero manually reviewed evidence records in the public evidence layer, and the model_performance_metrics table has not yet been populated. We present the data schema and worklist infrastructure as a foundation for future machine learning applications, which we anticipate will become feasible after completion of the ongoing curation effort (Track B) and the SRA virome expansion (Track A)."

**Figures/Tables:**
- **Table 5:** Evidence record types and counts (with curation status breakdown)
- **Brief mention only** — no dedicated figure unless Track B produces results

**Data gaps:**
- **BLOCKER:** model_performance_metrics table is empty — cannot claim any predictive modeling
- **BLOCKER:** 0 reviewed evidence records — cannot claim validated virulence/temperature associations
- **MAJOR:** Even raw evidence records only cover 21/526 virus species — vast data sparsity

---

### Section R6: Web Interface and Data Access

**Narrative:** Describe the FastAPI-based web interface, RESTful API endpoints, bulk download options, and data visualization features.

**What exists:**
- FastAPI backend with Jinja2 server-rendered HTML pages
- REST API endpoints for: isolates, hosts, proteins, geography, statistics
- Bulk downloads: FASTA (2,195 strict-target sequences, 111 complete genomes), TSV exports (~189,850 rows), XLSX
- Host-virus network visualization (93 edges)
- Interactive map component (Leaflet-based)
- CORS support
- API key authentication mechanism

**What is NOT ready:**
- **No public URL deployed** (pre-query cannot proceed without this)
- **No HTTPS** (will fail modern browser security)
- **In-memory rate limiting** (not production-safe)
- **No CI/CD pipeline**
- **Screenshots in paper will need to be from production deployment, not mockup** (previous mockup was misleading — 327 isolates ≠ 3,783 in DB)

**Figures/Tables:**
- **Figure 10:** Screenshot of real (not mockup) web interface — search results page
- **Figure 11:** Screenshot of interactive map showing isolate geographic distribution
- **Table 6:** API endpoint summary

**Data gaps:**
- **CRITICAL:** No public URL — must deploy before any submission
- **MAJOR:** Previous homepage mockup contains fabricated numbers — must create new screenshots from actual deployment
- **MAJOR:** Backup/test the FastAPI templates — some may use hardcoded example data

---

## 5. Methods Sections

### M1: Data Sources and Integration
- NCBI GenBank: primary sequence and metadata source (3783 isolates)
- ICTV MSL/VMR: taxonomic authority (via ictv_mappings, species_resolution tables)
- UniProt/Swiss-Prot: protein function annotation
- InterPro: domain annotation
- KEGG: pathway mapping
- AlphaFold DB / ESMFold: structural predictions
- STRING: protein-protein interaction data
- GBIF/OBIS: host geographic occurrence data
- WoRMS/FishBase/SeaLifeBase: host ecological traits
- Literature: PubMed, Europe PMC, bioRxiv, CNKI, Wanfang
- **Citation:** Must provide version numbers/download dates for each source

### M2: Data Processing Pipeline
- ETL scripts (Python) for each data source
- Host association inference: from sample metadata, not from experimental infection
- Taxonomy reconciliation: GenBank names matched to ICTV VMR via alias resolution
- Geographic standardization: country/continent mapping, coordinate quality classification
- Protein annotation pipeline (placeholder for Track B details)
- Release gate: multi-stage quality filter (excludes non-crustacean, host-genome artifacts)
- **Honest:** Acknowledge that most records are auto-imported, not manually curated

### M3: Curation Framework
- Three-tier curation model (core / extended / unverified)
- `core`: manually reviewed by domain experts (175 isolates)
- `extended`: auto-imported with quality filters (1,416 records)
- `unverified`: candidate records awaiting review (612)
- Evidence layer: typed evidence records (virulence, host_range, temperature, mortality, diagnosis)
- Manual review checklist documented in `MANUAL_REVIEW_CHECKLIST.md`
- **Honest:** 1,544 records still require human review; 52 references lack PMID/DOI

### M4: Web Application Architecture
- Backend: FastAPI (Python 3.12)
- Database: SQLite 3.x (note: this is a pre-production choice; PostgreSQL migration planned)
- Frontend: Jinja2 templates + Leaflet.js for maps
- API: RESTful JSON endpoints with optional API key authentication
- Rate limiting: in-memory (pre-production)
- Deployment: planned for public URL with HTTPS before submission
- **Honest:** Acknowledge SQLite is not suitable for production web deployment; position as "current development phase, production migration in progress."

### M5: Reproducibility
- Schema dump: `schema_dump.sql`
- Rebuild script: `build_sqlite_core_db_v2.py`
- Docker Compose file (to be created)
- Release gate: `release_gate.py`
- Data validation: `validate_database.py`
- **Honest:** The full data processing pipeline cannot be reproduced from primary sources without access to rate-limited APIs, cached responses, and undocumented manual steps.

---

## 6. Discussion

### 6.1 Summary of contributions
- First dedicated resource integrating crustacean virus data across genomic, taxonomic, ecological, and geographic dimensions
- Multi-layer knowledge graph design with explicit data tiering and provenance tracking
- 526 virus species linked to 104 host species with 3,107 infection records
- Geographic coverage spanning 35 countries with 34-year temporal range (1991-2025)
- Open data under CC BY 4.0 with REST API and bulk download

### 6.2 Comparison with existing resources (honest)
- **vs. NCBI Virus:** Larger crustacean-specific scope (NCBI Virus has crustacean filter but no curated host links or ecological data). However, NCBI has orders of magnitude more sequences.
- **vs. ICTV VMR:** VMR has 14+ crustacean virus species in MSL39; we have 526 species. But ICTV species are expertly reviewed; ours are mostly auto-imported.
- **vs. ViralZone:** Complementary — ViralZone provides family-level biology; we provide isolate-level occurrence data.
- **vs. Virus-Host DB:** Virus-Host DB has broader taxonomic scope (all viruses) but no crustacean-specific focus or geographic/ecological data.

### 6.3 Limitations (HONEST — must be a separate subsection)

> **Limitations**

> 1. **Curation depth:** The vast majority of records (89.6%) are auto-imported with automated quality filters rather than manually curated by domain experts. Only 175 isolates (3.3% of tier system's "core") have undergone expert review. Users should verify critical data points against primary literature.

> 2. **Host association uncertainty:** Many virus-host associations in this database are inferred from co-occurrence in environmental samples (e.g., water, sediment) rather than confirmed infection. This is particularly true for metagenomic virus discoveries from the Changjiang River, Beihai, and similar surveys. These are flagged in the database but users should exercise caution in interpreting host-virus links.

> 3. **Annotation sparsity:** Protein functional annotation coverage is extremely limited (<1% for GO terms, KEGG pathways, and 3D structures; ~16% for InterPro domains). The database currently serves as a sequence repository with annotation indexes rather than a deeply annotated protein resource.

> 4. **Evidence layer emptiness:** The reviewed evidence layer contains zero approved records. All virulence, temperature, host range, and outbreak associations remain unvalidated and should not be cited as confirmed biological knowledge.

> 5. **Geographic data incompleteness:** 36.3% of curated isolate profiles lack country-level geographic data, and 46.1% lack collection year. Coordinate precision varies from precise GPS coordinates to country-level centroids.

> 6. **Production architecture:** The current backend uses SQLite, which is not suitable for concurrent production workloads. A PostgreSQL migration is planned but not yet complete. The web interface is not yet deployed at a public URL with HTTPS.

> 7. **Missing reproducibility:** The full data processing pipeline cannot be reproduced from primary sources due to API rate limits, cached intermediate data, and undocumented manual curation steps. We provide schema and build scripts, but end-to-end reproducibility is not yet achieved.

> 8. **Community adoption:** The resource has not yet been published or presented at conferences. Community feedback and adoption metrics are not yet available.

### 6.4 Future directions
- Track A: SRA virome expansion (target: 2,000+ additional virus species)
- Track B: Deep protein annotation pipeline (InterProScan, ESMFold, KEGG for all 22,823 proteins)
- PostgreSQL migration for production deployment
- FAIR compliance: OWL/RDF export, FAIRsharing registration
- Community curation tools: allow domain experts to submit curated records
- Regular release cycle (quarterly updates)

### 6.5 Conclusion
CrustaVirus DB provides a novel integration layer for crustacean virus data that is not available from any existing resource. Despite its limitations — which we have transparently documented — it represents a significant step toward a comprehensive knowledge base for crustacean virology. We invite the community to contribute to its continued development.

---

## Figure and Table Summary

| # | Type | Title | Data Source | Status |
|---|------|-------|-------------|--------|
| 1 | Figure | Database schema: six-layer knowledge graph architecture | Schema dump | Draft ready |
| 2 | Figure | Genome type distribution | virus_master + viral_isolates | Ready |
| 3 | Figure | Top virus families (by species count) | virus_master | Ready |
| 4 | Figure | Host group composition | crustacean_hosts | Ready |
| 5 | Figure | Protein annotation coverage | viral_proteins + annotation tables | Awaits Track B |
| 6 | Figure | Example ESMFold predicted structures | Awaits Track B | Awaits Track B |
| 7 | Figure | World map of isolate collection locations | isolate_curated_profiles | Ready (needs visual refinement) |
| 8 | Figure | Host habitat vs. virus family heatmap | crustacean_hosts + virus_master | Ready |
| 9 | Figure | Temporal distribution of isolate collection years | isolate_curated_profiles | Ready |
| 10 | Figure | Web interface screenshot | FastAPI/Jinja2 | Awaits deployment |
| 11 | Figure | Interactive map screenshot | Leaflet component | Awaits deployment |
| 1 | Table | Database content summary | Multi-table | Ready |
| 2 | Table | Top crustacean hosts by infection count | infection_records | Ready |
| 3 | Table | Top InterPro domains in viral proteome | Awaits Track B | Awaits Track B |
| 4 | Table | Geographic distribution by country | isolate_curated_profiles | Ready |
| 5 | Table | Evidence record types and curation status | evidence_records | Ready |
| 6 | Table | API endpoint summary | backend.py | Ready |

---

## Manuscript length estimate

| Section | Estimated words | Notes |
|---------|----------------|-------|
| Abstract | 250 | NAR limit: 200 words; this draft is slightly over |
| Introduction | 800-1,000 | 3-4 paragraphs |
| Results (R1-R6) | 2,500-3,000 | 6 subsections, ~500 words each |
| Methods (M1-M5) | 1,500-2,000 | Combined |
| Discussion | 1,200-1,500 | Including 300-400 word limitations |
| **Total** | **6,250-7,750** | NAR DB issue: ~4-5 journal pages (~4,000-5,000 words) -> this is too long. Need to trim or combine sections. |

**Trim plan:** Merge R2+R4 (virome landscape + ecology), reduce R5 to 1 paragraph in Discussion, shorten Methods by referring to Supplementary.

---

## AI Disclosure

*This manuscript was prepared with the assistance of AI language models for text composition and data analysis. The scientific content, database design, and data curation were performed by human authors. AI tools were used in accordance with NAR AI disclosure policies.*
