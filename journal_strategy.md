# Journal Strategy for CrustaVirus DB

**Date:** 2026-05-12
**Purpose:** Compare target journals, assess honest fit, recommend primary + backup

---

## 1. NAR (Nucleic Acids Research) Database Issue

### Acceptance criteria (from NAR guidelines + R1/R2 audit):
- **Pre-query required:** Email by July 1 to nardatabase@gmail.com with working URL
- **Database must be publicly accessible** with no mandatory registration
- **Bulk download** in standard formats (FASTA, TSV, CSV, XLSX)
- **REST API** with documentation
- **Novelty:** Resource must offer something clearly beyond existing databases
- **Scale:** Accepted databases typically have >10,000 records (or novel primary data)
- **Sustainability:** 5-year plan with institutional commitment and funding
- **FAIR compliance:** Expected (PID, standard formats, license)
- **Manuscript:** 4-5 journal pages (~4,000-5,000 words, 200-word abstract)
- **Community adoption:** Explicitly favored
- **Referee suggestions:** 6 needed

### Our honest fit:

| Criterion | Status | Verdict |
|-----------|--------|---------|
| Public URL | ✗ Not deployed | FAIL |
| Pre-query email | ✗ Not sent | FAIL |
| Database scale (526 species) | Far below NAR norm (>10,000) | FAIL |
| Novelty (integration claim) | Defensible but thin | WEAK PASS |
| Bulk download | ✓ Available | PASS |
| API | ✓ Exists (not deployed) | WEAK PASS |
| Sustainability plan | ○ Placeholder-filled | FAIL |
| FAIR compliance | ✗ No PID, no public URL | FAIL |
| Community adoption | ✗ None | FAIL |
| Curation quality | ○ 1,544 unreviewed records | WEAK FAIL |
| Production architecture | ✗ SQLite | FAIL |
| Reproducible build | ✗ No Docker/CI | FAIL |

**Assessment: NOT READY for NAR. Risk of desk rejection: HIGH (90%+).**

### Timeline:
- If we deploy, expand to 2,000+ species (Track A), populate annotations (Track B), migrate to PostgreSQL, and fix FAIR gaps: **submission possible by late 2026 or early 2027**
- **July 1, 2026 deadline is not feasible** — we lack a public URL and scale

### Recommendation:
- **Do NOT submit pre-query email on July 1.** Sending a weak pre-query will burn the NAR opportunity permanently. Wait until we have:
  - Public URL with HTTPS
  - 2,000+ virus species (Track A)
  - Protein annotation pipeline running (Track B)
  - PostgreSQL (or at minimum, a defensible architecture statement)
  - Real Zenodo DOI
  - Curation backlog reduced to <200 records
- **New timeline:** Pre-query by January 2027, submit by March 2027 for January 2028 issue

---

## 2. Scientific Data (Nature Portfolio)

### Acceptance criteria:
- **Primary data contribution:** Paper must describe a dataset, not a database tool
- **Data descriptor format:** Title, Background & Summary, Methods, Technical Validation, Usage Notes, Data Records
- **Dataset must be deposited** in a recognized public repository with persistent identifier
- **FAIR compliance required**
- **Technical validation section:** Rigorous quality assessment of the data
- **Word limit:** ~3,000 words (shorter than NAR)
- **Open access:** CC BY 4.0 (already aligned)
- **Review focus:** Data quality and reuse potential, not novelty of analysis

### Our honest fit:

| Criterion | Status | Verdict |
|-----------|--------|---------|
| Primary data description | ○ Partially (aggregated, not original) | WEAK |
| Data repository deposition | ✗ Not yet (Zenodo DOI pending) | FAIL |
| FAIR compliance | ✗ | FAIL |
| Technical validation | ○ Release gate + auto-checks exist | WEAK PASS |
| Data reuse potential | ○ Crustacean virology community | MODERATE |
| Open access | ✓ CC BY 4.0 | PASS |

**Assessment: BORDERLINE.** Scientific Data accepts aggregated databases as data descriptors. The key issues are:
- We need a deposited dataset with PID (Zenodo DOI)
- FAIR compliance is expected
- The "dataset" framing works better for our actual contribution (integrated data) than the "database" framing

### Timeline:
- Prepare data descriptor by September 2026
- Requires: Zenodo DOI, public URL (optional but recommended), cleaned curation backlog, FAIR documentation
- **More achievable than NAR within 2026** because Scientific Data doesn't require production-grade infrastructure

### Recommendation:
- Strong backup option
- Better fit for the honest integration-angle than NAR
- Submit after Track A + Track B (August-September 2026)

---

## 3. Database (Oxford Journals)

### Acceptance criteria:
- **Database description** (not just data description)
- **Focus on database design** and implementation
- **Accepting of smaller, specialized databases** — no strict size threshold
- **Technical rigor** expected (schema, API, sustainability)
- **Comparison with existing resources required**
- **Open access** (CC BY, author-pays model)
- **No pre-query required** — submit manuscript directly
- **Reviewer focus:** Design quality, novelty of approach, utility to target community

### Our honest fit:

| Criterion | Status | Verdict |
|-----------|--------|---------|
| Database design description | ✓ Schema documented, tiered system | PASS |
| Web/API implementation | ○ FastAPI exists, not deployed | WEAK PASS |
| Comparison with resources | ✓ NOVELTY_COMPARISON.md exists | PASS |
| Specialized focus | ✓ Crustacean virology niche | PASS |
| Technical rigor | ○ SQLite concern, no CI | WEAK |
| Sustainability plan | ○ Placeholder-filled | WEAK |
| Scale (size-independent) | ✓ No minimum threshold | PASS |

**Assessment: BEST FIT for current state.** Database journal:
- Accepts specialized databases with modest scale
- Focuses on design and implementation, not comprehensive coverage
- No pre-query requirement (submit directly)
- Reviewers are database specialists who will recognize good schema design
- Our multi-layer knowledge graph approach and data tiering system are publishable contributions
- The niche (crustacean virology) is small enough that 526 species is reasonable

### Timeline:
- Prepare manuscript: June-July 2026
- Submit: August 2026
- Decision: October-November 2026
- Requires minimal prerequisites:
  - Public URL (strongly recommended but not strict requirement)
  - Zenodo DOI (recommended)
  - Curation backlog reduced
  - Docker Compose (nice-to-have)

### Recommendation:
- **PRIMARY TARGET for current state** given Track A+B completing in June-July
- Most realistic path to publication in 2026
- Better reviewer fit (specialized DB experts vs. NAR's big-biology referees)

---

## 4. BMC Genomics (Database/Resource section)

### Acceptance criteria:
- **Resource description** — open to database and bioinformatics tool papers
- **Less strict on database scale** than NAR
- **Focus on biological utility** of the resource
- **Bioinformatics methods allowed**
- **Open access** (author-pays)
- **No word limit** (flexible formatting)
- **Reviewer focus:** Does the resource enable new biology?

### Our honest fit:

| Criterion | Status | Verdict |
|-----------|--------|---------|
| Biological utility | ○ Potential, not demonstrated | WEAK |
| Resource description | ✓ Comprehensive | PASS |
| Scale requirement | ○ Minimal threshold | PASS |
| Methods description | ✓ Detailed ETL pipeline | PASS |
| Community evidence | ✗ None | WEAK |

**Assessment: MODERATE FIT.** BMC Genomics would publish this but:
- They expect demonstrated biological insight — we need to show the database enables discovery
- Without community adoption or a use case analysis, the paper is just a "here is our schema" report
- Higher threshold for biological insight than Database journal

### Timeline:
- Similar to Database journal (August 2026)
- But needs a "biological use case" section — e.g., "Using CrustaVirus DB to identify WSSV host range patterns across habitats"
- Requires preparatory analysis work (1-2 weeks additional)

### Recommendation:
- Tertiary option (if Database rejects)
- Must add biological use case analysis

---

## Comparison Summary

| Journal | Prestige | Fit for current state | Likelihood of acceptance | Timeline | Cost | Overall recommendation |
|---------|:--------:|:---------------------:|:------------------------:|:--------:|:----:|:----------------------:|
| **NAR Database Issue** | Very high | Poor | <10% (current) | Jul 2026 (not feasible) | Free (waiver) | **Defer to 2027** |
| **Scientific Data** | High | Moderate | 40% (if FAIR fixed) | Sep 2026 | OA fee (~$2,500) | **Backup #1** |
| **Database (Oxford)** | Moderate | **Good** | **70%** | **Aug 2026** | OA fee (~$1,500) | **PRIMARY** |
| **BMC Genomics** | Moderate | Moderate | 50% | Aug 2026 | OA fee (~$2,900) | Backup #2 |

---

## Recommended Strategy

### Phase 1: Track A + Track B completion (May-June 2026)
- Track A: SRA mining to expand virus species count to 2,000+ (critical for all venues)
- Track B: Deep protein annotation (rescue Results R3)
- Parallel: Deploy public URL, obtain Zenodo DOI, create Docker Compose, add CI

### Phase 2: Pre-submission (July 2026)
- Clean curation backlog (1,544 → <200)
- Fix 52 traceless references
- Add ORCID iDs
- Generate real screenshots from deployed instance
- Write and test the manuscript against Database journal format

### Phase 3: Primary submission (August 2026)
- **Submit to Database (Oxford)** — best fit for current state
- Manuscript framing: "multi-layer knowledge graph for crustacean-associated viruses"
- Honest limitations section
- AI disclosure statement

### Phase 4: Contingency (September-November 2026)
- If Database rejects: revise for Scientific Data (data descriptor format)
- If Scientific Data rejects: revise for BMC Genomics (add use case analysis)
- Continue infrastructure improvements for NAR resubmission in 2027

### Phase 5: NAR upgrade (2027)
- Use Database journal publication as community adoption evidence
- Expand Track A results to 5,000+ species
- Migrate to PostgreSQL
- Full FAIR compliance (OWL/RDF, FAIRsharing)
- Submit pre-query to NAR by January 2027
- Submit full manuscript by March 2027 for January 2028 issue

---

## Timeline Feasibility

| Milestone | Optimistic | Realistic | Pessimistic |
|-----------|:----------:|:---------:|:-----------:|
| Track A complete (2,000+ species) | Jun 1 | Jun 15 | Jul 1 |
| Track B complete (protein annotation) | Jun 1 | Jun 15 | Jul 1 |
| Public URL deployed | Jun 15 | Jun 30 | Jul 15 |
| Zenodo DOI obtained | Jun 15 | Jul 1 | Jul 30 |
| Curation backlog < 200 | Jul 1 | Jul 15 | Aug 1 |
| Manuscript ready | Jul 15 | Aug 1 | Aug 15 |
| **Database journal submission** | **Jul 15** | **Aug 1** | **Aug 15** |
| Decision received | Oct 1 | Nov 1 | Dec 1 |
| Publication | Dec 2026 | Feb 2027 | Apr 2027 |

---

## Final Recommendation

**Submit to Database (Oxford) in August 2026** after Track A+B complete. This is the most realistic path to publication. The journal's reviewer pool includes database design specialists who will recognize the value of the multi-layer knowledge graph approach and data tiering system, even at moderate scale. Use the Database publication as a stepping stone to NAR in 2027-2028.

**Do NOT submit the pre-query to NAR on July 1, 2026.** It would be rejected and would burn the opportunity. Wait until the database has adequate scale, infrastructure, and community adoption.
