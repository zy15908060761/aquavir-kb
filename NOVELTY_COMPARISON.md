# Novelty Comparison - CrustaVirus DB vs. Existing Resources

This document is a pre-submission comparison for the current local release
candidate. It must not be read as a claim that all records are manually
reviewed. The current release separates release-filtered sequence metadata from
candidate evidence worklists.

## 1. Comparison Matrix

| Feature | CrustaVirus DB current release candidate | NCBI Virus | ViralZone | ICTV | Virus-Host DB |
|---------|------------------------------------------|------------|-----------|------|---------------|
| Taxonomic scope | Crustacean-associated viral records after release filtering | All viruses | All viruses | All viruses | All viruses |
| Host specificity | Strict target host links in the release-filtered set; unresolved records remain outside primary claims | Variable; not host-centric | Family-level only | N/A | Broad; not crustacean-focused |
| Isolate-level metadata | Release-filtered isolate metadata with explicit target/raw scopes | GenBank entries | No | VMR only | Limited |
| Geospatial data | Source-derived collection geography and host occurrence overlays, marked by provenance | Limited | No | No | No |
| Ecological traits | Source-derived host ecology indexes for contextual use | No | No | No | No |
| Protein annotations | Source-derived UniProt, InterPro, KEGG, STRING and structure indexes with QC flags | Conserved Domain and linked resources | Family summaries | No | No |
| Literature evidence | Traceable literature table plus manual review worklists | PubMed links | Selected reviews | VMR references | Limited |
| Diagnostic methods | 7 manual-checked records; 18 records remain in review | No | No | No | No |
| Disease outbreaks | 3 manual-checked records; non-reviewed outbreak records are not primary claims | No | No | No | No |
| Virulence/temperature evidence | Manual-reviewed public evidence layer currently has 0 records; candidate profiles are internal worklists | No | No | No | No |
| Proteomics/transcriptomics links | Source-derived PRIDE, SRA and GEO cross-reference indexes | Source links only | No | No | No |
| Release gate and QC | Automated release gate blocks obvious contaminants and prevents candidate evidence from public reviewed surfaces | Standard GenBank QC | Expert review | Expert review | Automated import |
| API and web UI | FastAPI and server-rendered HTML, with public endpoints intended to expose release-filtered data | NCBI web and E-utilities | Web pages | Static pages | Web search only |

## 2. What Is Actually Novel

### 2.1 Crustacean-Specific Release Filtering

CrustaVirus DB is not intended to mirror a general viral database. Its useful
contribution is the crustacean-specific integration layer: host links,
collection geography, taxonomy, sequence availability, and source provenance are
assembled into one release-filtered view. This is different from claiming that
every row is manually reviewed; most strict-target isolate records are
release-filtered rather than manually checked.

### 2.2 Host-Virus-Environment Integration

The database combines three data axes:

- Virus side: GenBank-derived isolate metadata, ICTV mappings, protein records,
  and source-derived annotation indexes.
- Host side: crustacean host taxonomy and source-derived ecological context.
- Environment side: collection geography, host occurrence overlays, and
  outbreak/evidence worklists.

The defensible novelty claim is integration and filtering, not completion of a
fully curated epidemiology knowledge base.

### 2.3 Evidence Layer Status

The evidence layer is not yet ready for strong biological claims. The reviewed
public evidence view currently contains 0 records. Virulence, temperature, host
range, environmental, and outbreak evidence backlogs must be manually verified
before they can support manuscript claims.

Current policy:

- Public virulence and temperature APIs expose only manual-reviewed evidence.
- Candidate evidence and inferred profiles are kept out of primary claims.
- Worklists are useful for future curation but are not presented as validated
  knowledge.

### 2.4 Protein-Centric Functional Indexes

Protein annotations currently provide a source-derived index over viral protein
records. UniProt, InterPro, KEGG, STRING, PRIDE and structure tables are useful
for navigation and hypothesis generation, but they should be described as
annotation indexes unless a specific subset has been manually verified and
quality-filtered for a primary claim.

### 2.5 Multi-Source Literature Coverage

The literature layer integrates English and Chinese source discovery pipelines,
including PubMed, Europe PMC, bioRxiv, CNKI and Wanfang helper workflows. The
publishable claim is traceable source aggregation and review prioritization.
Any biological conclusion extracted from these sources still requires manual
curation before submission.

## 3. Relationship to Existing Resources

| Existing Resource | How CrustaVirus DB Uses It | Value Added |
|-------------------|---------------------------|-------------|
| NCBI / GenBank | Primary sequence and accession source | Crustacean-specific release filtering and host/geography joins |
| ICTV | Taxonomic authority | Alias resolution and local mapping status |
| ViralZone | Family-level knowledge | Contextual links to isolate-level records |
| Virus-Host DB | Cross-reference validation | Crustacean-focused host integration |
| UniProt / InterPro / KEGG / STRING | Protein annotation sources | Navigable protein annotation indexes with release-scope flags |
| GBIF / OBIS | Host occurrence sources | Host distribution context, not direct virus occurrence evidence |
| Europe PMC / PubMed | Literature indexing | Evidence worklists and traceable review queues |

## 4. Submission-Risk Position

This database can support a NAR strategy only if the manuscript is framed around
the release-filtered crustacean virus metadata and integration workflow. It
cannot yet support claims of a fully manually curated virulence, temperature,
outbreak, or diagnostic knowledge base. Those claims require additional manual
review and a non-empty reviewed evidence layer.
