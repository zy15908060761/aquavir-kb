# Narrative Gaps Analysis — CrustaVirus DB

**Date:** 2026-05-12
**Purpose:** Identify which manuscript claims cannot currently be supported, which statistics are embarrassing, and what Track A/B must fix.

---

## Gap Classification
- **BLOCKER** = Cannot include this claim/section without fixing; will cause rejection
- **MAJOR** = Weakens the claim significantly; should be addressed before submission
- **MINOR** = Could include with caveats; fix if time permits

---

## Gap 1: Database size — "526 virus species" is indefensible against NAR norms

**Severity: BLOCKER**
**Affects:** Abstract, Introduction, Results R2, Discussion

**The problem:**
- 526 virus species is far below NAR Database Issue norms (>10,000)
- R2 reviewer quote: *"A competent bioinformatician could replicate 90% with a week of Python scripts"*
- The 526 figure counts each ICTV species once — but many "species" are single-sequence entries from metagenomic surveys (Changjiang virus, Beihai virus, etc.), not well-characterized viruses
- Broken down honestly: only ~19 families have >4 species; the rest are singletons from environmental RNA surveys

**What Track A must deliver:**
- Minimum target: 2,000+ virus species (Track A's SRA mining)
- Ideally 5,000+ to approach credibility
- Even 2,000 is weak by NAR standards but at least defensible as "the largest crustacean-specific collection"

**Fallback strategy:**
- Reframe the title to emphasize *integration* over *scale*
- Use "526 virus species" as a Release 1.0 number with "rapidly expanding" framing
- Submit to Database journal instead of NAR

---

## Gap 2: 505/526 virus species have ZERO evidence records

**Severity: BLOCKER**
**Affects:** Results R5 (predictive applications), Discussion claims about "knowledge graph"

**The problem:**
- Only 21 virus species have any evidence_records linked to them
- 505 species exist as sequence entries with virus_master names but no literature evidence, no host range evidence, no virulence data
- This means the "multi-layer knowledge graph" is mostly a single-layer (sequence layer) for 96% of entries
- The evidence layer is the key differentiator vs. NCBI Virus — if it's empty, the differentiation collapses

**What Track A/B must deliver:**
- Track A: Each new SRA-derived species should be linked to at least one evidence record
- Curatorial: Batch-populate evidence records from existing literature (even auto-extracted) to cover more species
- Minimum acceptable: evidence_records for >50% of species

**Fallback:**
- Move the evidence layer discussion entirely to Methods/Future Work
- Frame "knowledge graph" as a design claim, not a data claim

---

## Gap 3: Protein annotation coverage is embarrassingly low

**Severity: BLOCKER** (if Track B fails to deliver)
**Affects:** Results R3 (Protein section)

**Current state (pre-Track B):**
- GO terms: ~0.4% of proteins
- KEGG: <0.1%
- PDB structures: ~0.1%
- InterPro domains: ~16.4%
- UniProt matches: ~49.7% (but many are just existence matches at low identity)

**What is acceptable:**
- InterPro > 50% of proteins
- At least one annotation type covering >50%
- ESMFold structures with pLDDT confidence scores for >80% of proteins
- A functional category distribution (e.g., "25% replication, 15% capsid, 10% movement...")

**What happens if Track B fails:**
- Results R3 must be reduced to one paragraph in Methods
- The protein "section" becomes: "We provide 22,823 protein sequences from NCBI. Annotations are pending."
- This is not publishable as a standalone Results section

---

## Gap 4: Outbreak data is mostly unvalidated

**Severity: MAJOR**
**Affects:** Results R4 (geography/ecology)

**The problem:**
- 56 outbreak events documented
- Only 3 are manually reviewed (curation_status = 'manual_checked')
- The remaining 53 are `needs_review` or `auto_seeded`
- Cannot claim validated outbreak epidemiology
- Mortality rates (WSSV 90-100%, YHV 80-100%) may be accurate but haven't been verified against original sources

**Fix:**
- Curate at least the top 10 outbreak events (WSSV, YHV, TSV, IHHNV, etc.)
- Label outbreak figure as "preliminary, based on auto-extracted literature data"
- In Results, present outbreak infrastructure, not outbreak conclusions

---

## Gap 5: Host association uncertainty for metagenomic viruses

**Severity: MAJOR**
**Affects:** Results R2 (virome landscape), entire host-virus narrative

**The problem:**
- Many virus species (Marnaviridae, Picornaviridae, Yanviridae, Solemoviridae — 376/526 species, 71.5%) were discovered in metagenomic surveys of environmental samples (water, sediment, plankton tows)
- These are listed as "crustacean viruses" because the sampling location contained crustaceans, NOT because infection was confirmed
- Marnaviridae are known to infect marine algae/diatoms — they are likely contaminants in crustacean samples, not crustacean viruses
- This fundamentally undermines the "comprehensive crustacean virus knowledge base" framing

**Fix:**
- Track A should explicitly annotate host_association_method for each species
- Clearly separate "confirmed infection" from "detected in crustacean-associated sample"
- Lower the prominence of Marnaviridae/Picornaviridae in host-virus claims
- Consider excluding Marnaviridae from "crustacean virus" counts (would reduce 526 to 373 species)

---

## Gap 6: Geographic data incomplete for meaningful claims

**Severity: MAJOR**
**Affects:** Results R4 (geography), Figure 7 (world map)

**Current stats:**
- 63.7% of curated profiles have country data (1,981/3,110)
- 53.9% have collection year (1,676/3,110)
- 63.7% have coordinates (but precision varies from GPS to country-centroid)
- 36.3% are missing country entirely — these are mostly older GenBank records
- Temporal range 1991-2025 looks impressive, but pre-2000 records are sparse

**Impact on figures:**
- World map will show clusters around China, Mexico, Thailand — this reflects *reporting bias*, not actual virus distribution
- Temporal trend line will show exponential increase — also reporting bias (more sequencing, not more viruses)
- Cannot claim comprehensive geographic coverage

**Fix:**
- Add explicit caveats about reporting bias to map figure legends
- Normalize temporal trends by sequencing effort if possible
- Flag coordinate precision tiers on the map (precise GPS vs. country centroid)
- Add "data quality" supplementary table showing completeness by country

---

## Gap 7: No public URL means no NAR pre-query

**Severity: BLOCKER (submission-level)**
**Affects:** NAR submission feasibility, Abstract URL, all access claims

**Current status:**
- No public URL deployed
- No HTTPS
- No domain configuration
- FastAPI only running locally (127.0.0.1:8000)

**Impact:**
- July 1 pre-query email to NAR cannot be sent without a working URL
- Abstract cannot claim "available at [URL]"
- NAR checklist requirement: "Publicly accessible database" — FAIL
- Without pre-query, the NAR editor will not assess suitability, and the submission timeline slips

**Fix:**
- Deploy to a cloud provider (AWS EC2, DigitalOcean droplet, or Chinese equivalent)
- Cost: ~$10-20/month for a basic VPS
- Time: 2-3 days for setup
- Must be done before June 25 at the latest

---

## Gap 8: Non-crustacean hosts in the host table

**Severity: MAJOR**
**Affects:** Results R2, host-virus statistics

**The problem:**
- 22/104 host species (21.2%) are non-crustacean: E. coli strains, yeast, human cell lines, etc.
- These are cloning/expression hosts, not natural virus hosts
- Including them inflates "104 crustacean hosts" claim
- `infection_records` table links these to viruses — some of those infection records are lab artifacts

**Fix:**
- Exclude non-crustacean hosts from all primary claims
- Add `host_type` filter: crustacean_hosts.host_type to separate biological from lab hosts
- Recalculate: 104 → 82 true crustacean hosts
- Update Abstract and Results accordingly

---

## Gap 9: model_performance_metrics table is empty

**Severity: MAJOR**
**Affects:** Results R5 (predictive applications), Discussion

**The problem:**
- The table exists (created in schema) but has 0 rows
- Any claim about "predictive modeling" or "ML readiness" is unsupported
- The R2 audit specifically flagged this

**Fix:**
- Either populate this table with at least baseline models (e.g., host prediction, virulence prediction)
- Or remove the predictive framing entirely
- The "predictive applications" Results section must be replaced with "Evidence layer design and curation workflow"

---

## Gap 10: 52 references lack PMID/DOI (unverifiable citations)

**Severity: MAJOR**
**Affects:** Manuscript credibility, reviewer trust

**The problem:**
- 52/317 ref_literatures have neither PMID nor DOI
- These cannot be verified by reviewers
- R1 audit flagged this as H9 (HIGH)
- Suggests improper citation practices or scraped metadata without validation

**Fix:**
- Manually look up each reference and add PMID/DOI
- If unresolvable, mark as `unverified` and exclude from manuscript claims
- Estimated effort: 2-4 hours for a curator

---

## Gap 11: No community adoption or preprint

**Severity: HIGH**
**Affects:** NAR acceptance (they favor demonstrated utility)

**The problem:**
- No bioRxiv preprint
- No GitHub stars (private repo)
- No conference presentations
- No beta testers
- No citations (obviously — not published)
- R2 review: "NAR explicitly favors resources with demonstrated utility"

**Fix (partial):**
- Submit a bioRxiv preprint immediately (announcement paper, 2-3 pages)
- Share GitHub repository on relevant mailing lists (shrimp aquaculture, crustacean virology)
- Present at an upcoming conference if possible
- But realistically: this gap cannot be fully closed before submission

---

## Gap 12: SQLite as production database

**Severity: BLOCKER** (for NAR or any journal with a database referee)
**Affects:** Methods M4, technical credibility

**The problem:**
- 235 MB SQLite file serving as web backend
- File-level locking prevents concurrent writes
- No connection pooling
- No role-based access control
- R2 reviewer: *"A reviewer from the database community would reject this on architectural grounds alone."*

**Fix:**
- PostgreSQL migration (3-5 days of work)
- Add PgBouncer for connection pooling
- Set up automated backups
- Document architecture in Methods with specifics

---

## Gap 13: No Docker/CI/reproducible build

**Severity: MAJOR**
**Affects:** Methods M5, FAIR compliance

**Current state:**
- 196 Python scripts, no unified workflow
- No Docker Compose
- No Makefile
- No CI/CD
- Reproducibility is circular: dump → rebuild → export

**Fix:**
- Create Docker Compose with: SQLite (or PostgreSQL), FastAPI, Nginx reverse proxy
- Add GitHub Actions: schema validation, test suite, export verification
- Estimated: 2-3 days

---

## Gap 14: Homepage mockup used fabricated numbers

**Severity: HIGH** (ethics/reputation)
**Affects:** All figures/screenshots in manuscript

**The problem:**
- Previous `crustacean_db_homepage_prototype.png` showed: 327 isolates, 156 host species, 892 infections
- Actual DB: 3,783 isolates, 104 hosts (or 82 true crustacean), 3,107 infections
- None of the mockup numbers match the database
- If this were submitted, it constitutes misleading figures

**Fix:**
- Completely new screenshots from the actual deployed FastAPI interface
- Delete all old prototype images from the repository
- Document screenshot capture date and DB version in figure legends

---

## Summary: What must be fixed before submission

### Critical path (must fix, in priority order):
1. **Deploy public URL + HTTPS** (June 25 deadline for July 1 pre-query)
2. **Track A: Expand to 2,000+ virus species** (can fold into v1.1 release)
3. **Track B: Protein annotation pipeline** (rescue Results R3)
4. **Clean non-crustacean hosts** from all primary claims (1-day fix)
5. **Replace mockup with real screenshots** (post-deployment)
6. **Fix 52 traceless references** (2-4 hour manual effort)

### Strongly recommended (before Aug 15):
7. **Obtain Zenodo DOI** for v1 release
8. **Create Docker Compose + CI** for reproducibility
9. **Curate top 10 outbreak events** manually
10. **Populate evidence_records for >50% of virus species**
11. **Publish bioRxiv preprint** (announcement paper)
12. **Add explicit host_association_method annotation** for metagenomic vs. confirmed infections

### Nice-to-have (before submission):
13. PostgreSQL migration (can be deferred if SQLite is explained as pre-production)
14. Community outreach / beta testers
15. OWL/RDF ontology stub for FAIR compliance
16. ORCID iDs for all authors

### Can be deferred (after publication):
17. model_performance_metrics population
18. Full reproducibility pipeline
19. OBO Foundry alignment
20. Conference presentations
