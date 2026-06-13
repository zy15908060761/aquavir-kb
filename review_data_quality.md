# NAR Database Issue — Review Report
## Dimension: Data Quality & Completeness
### Verdict: **REJECT** (Fatal data deficiencies)

---

## FATAL FLAWS

### F1. Grossly inadequate scale for NAR standards
The database catalogs **1,283 virus species** (902 aquatic invertebrate targets), compared to NAR norms of >10,000 entries. Even the paper admits *"a competent bioinformatician could replicate 90% with a week of Python scripts"* (narrative_gaps.md, Gap 1). The 526 targeted crustacean species is roughly **5% of the scale expected** for a NAR Database Issue publication. For context: recent NAR Database Issue acceptances include resources like UniProt (>200M proteins), Pfam (>19,000 families), and InterPro (>40,000 entries). A database of 526 entries does not meet the bar.

### F2. The "knowledge graph" is a single-layer for 96% of entries
Of the 526 virus species:
- **505 (96.0%) have ZERO evidence records** linked
- Only **21 species** (4.0%) have any evidence at all
- The evidence layer — claimed as the *core competitive advantage* vs NCBI Virus — is virtually empty
- The "multi-layer" claim in the title and abstract is **materially misleading**

### F3. Protein annotation is functionally absent
- GO terms: **~0.4%** of proteins annotated
- KEGG pathways: **<0.1%**
- PDB structures: **~0.1%**
- InterPro domains: **~16.4%** (the only non-trivial number)
- The paper acknowledges: *"The protein section becomes: We provide 22,823 protein sequences from NCBI. Annotations are pending."* (narrative_gaps.md, Gap 3)
- A Results section on protein annotations with <1% coverage is unpublishable.

### F4. Homepage mockup contained fabricated data
The prototype screenshot (`crustacean_db_homepage_prototype.png`) displayed fabricated numbers:
- Mockup: 327 isolates → Actual: **3,783 isolates**
- Mockup: 156 host species → Actual: **104 hosts**
- Mockup: 892 infections → Actual: **3,107 infections**
- **None** of the mockup numbers matched the actual database.
- This is a **research integrity concern**. Submitting fabricated screenshots is misconduct.

### F5. ML/predictive modeling claims are entirely unsupported
- `model_performance_metrics` table: **0 rows** (empty)
- The paper's abstract mentions "predictive modeling infrastructure"
- No model has been trained, validated, or tested
- This is not an "in-progress" feature — it is **vaporware in a manuscript**

---

## MAJOR CONCERNS

### M1. Host attribution is systematically unreliable (71.5% uncertainty)
- 376/526 virus species (71.5%) were discovered via **metagenomic surveys of environmental samples** (water, sediment, plankton tows)
- These are listed as "crustacean viruses" because sampling locations *contained* crustaceans, NOT because infection was confirmed
- Marnaviridae (known diatom/algal viruses) are misclassified as crustacean viruses
- The `host_association_method` defaults to `co_occurrence_metagenomic` — the **weakest** evidence tier

### M2. Outbreak data is unvalidated
- 56 outbreak events documented → **only 3 manually reviewed**
- 53/56 are `needs_review` or `auto_seeded`
- Mortality figures (WSSV 90-100%, YHV 80-100%) are **unverified against original sources**
- Cannot claim validated epidemiological data

### M3. Critical metadata missing
- Only **63.7%** of curated profiles have geographic coordinates
- Only **53.9%** have `collection_year` recorded
- These are basic metadata fields — their absence undermines geographic distribution claims

### M4. 52 references unverifiable
- 52/317 references lack both PMID and DOI
- Cannot be verified by reviewers
- *"Suggests improper citation practices or scraped metadata without validation"* (the authors' own words)
- For a resource claiming "evidence-driven" design, this is self-defeating

### M5. "Three-tier curation" is window dressing
- Core tier: **175 isolates** (1.5% of 11,353)
- Extended tier: 1,416 auto-imported with filters
- Unverified tier: 612 candidates
- Calling a database with 1.5% manual review "curated" is misleading
- The vast majority of the database is an **NCBI dump with renaming**

---

## MINOR ISSUES

- The `crustacean_hosts` table name is misleading when it now covers 5 phyla (Arthropoda, Mollusca, Echinodermata, Cnidaria, Porifera)
- No automated quality gate preventing non-crustacean host entries
- `discovery_context` field distributions not reported — can't assess how many viruses were traditionally characterized vs. metagenomic survey artifacts

---

## SUMMARY ASSESSMENT

This database is at the **prototype stage**, not the publication stage. The authors' own internal documents identify **6 BLOCKER-level gaps** and **8+ MAJOR gaps**. A manuscript that acknowledges this many fatal deficiencies cannot pass peer review at NAR.

**Recommendation: REJECT**

The resource may have future potential after (a) expanding to 2,000+ species, (b) populating evidence records for >50% of entries, and (c) completing protein annotation coverage. In its current state, it is a curated NCBI export with an ambitious schema that remains largely empty.

**Suitable venue after maturation:** *Database* (Oxford) or *Scientific Data* (Nature), not NAR Database Issue.
