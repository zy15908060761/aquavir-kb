# Honest Novelty Matrix — CrustaVirus DB vs. Existing Resources

**Date:** 2026-05-12
**Note:** This supersedes the earlier NOVELTY_COMPARISON.md, which the R2 audit correctly identified as overly favorable. This version uses:
- **✓** = fully implemented and verified
- **○** = partially implemented (exists but limited)
- **✗** = not implemented

---

## Feature Comparison Matrix

| Feature | CrustaVirus DB | NCBI Virus | ICTV VMR | ViralZone | Virus-Host DB | Crustacean-specific resources |
|---------|:--------------:|:----------:|:--------:|:---------:|:-------------:|:-----------------------------:|
| **Sequence data** | ✓ | ✓ | ✗ | ✗ | ✗ | ○ |
| **Host-virus links** | ○ | ○ | ✗ | ○ | ✓ | ✗ |
| **Manual curation** | ○ | ○ | ✓ | ✓ | ○ | ✗ |
| **Taxonomy (ICTV aligned)** | ○ | ✓ | ✓ | ✓ | ✓ | ✗ |
| **Geographic occurrence** | ○ | ○ | ✗ | ✗ | ✗ | ✗ |
| **Host ecology traits** | ○ | ✗ | ✗ | ✗ | ✗ | ✗ |
| **Coordinate-level precision** | ○ | ○ | ✗ | ✗ | ✗ | ✗ |
| **Outbreak events** | ○ | ✗ | ✗ | ✗ | ✗ | ✗ |
| **Mortality/economic data** | ○ | ✗ | ✗ | ✗ | ✗ | ✗ |
| **Protein function annotation** | ○ | ○ | ✗ | ○ | ✗ | ✗ |
| **Protein 3D structures** | ○ | ✗ | ✗ | ✗ | ✗ | ✗ |
| **InterPro domains** | ○ | ○ | ✗ | ○ | ✗ | ✗ |
| **KEGG pathways** | ○ | ✗ | ✗ | ✗ | ✗ | ✗ |
| **GO terms** | ○ | ○ | ✗ | ✗ | ✗ | ✗ |
| **Literature integration** | ○ | ✓ | ○ | ○ | ○ | ✗ |
| **Multi-source literature** | ○ | ✓ | ✗ | ✗ | ✗ | ✗ |
| **Data tiering (core/extended/unverified)** | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ |
| **Provenance tracking** | ○ | ✗ | ✗ | ✗ | ✗ | ✗ |
| **API access** | ○ | ✓ | ✗ | ✗ | ✗ | ✗ |
| **Bulk download** | ✓ | ✓ | ✓ | ✗ | ✓ | ✗ |
| **FAIR compliance** | ✗ | ✓ | ○ | ○ | ✗ | ✗ |
| **OWL/RDF export** | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ |
| **Persistent identifier (DOI)** | ✗ | ✓ | ✓ | ✗ | ✗ | ✗ |
| **Public URL** | ✗ | ✓ | ✓ | ✓ | ✓ | ✗ |
| **Sustainability plan** | ○ | ✓ | ✓ | ✓ | ✗ | ✗ |
| **Reproducible build** | ✗ | ✓ | ✓ | ✗ | ✗ | ✗ |
| **CI/CD pipeline** | ✗ | ✓ | ✗ | ✗ | ✗ | ✗ |
| **Community adoption evidence** | ✗ | ✓ | ✓ | ✓ | ✓ | ✗ |
| **Scale (# of virus records)** | 526 species | >10,000 species | >14,000 species | All families | >8,000 species | ~50-100 species |

---

## Detailed Assessment

### Sequence Data (CrustaVirus DB: ✓)
- 3,783 isolates, 22,823 proteins, all with GenBank accessions
- FASTA bulk download available (2,195 strict-target, 111 complete-genome)
- Comparable to NCBI Virus for crustacean subset

### Host-Virus Links (CrustaVirus DB: ○)
- **Partial:** 3,107 infection_records linking viruses to hosts
- **Problem:** Many links are inferred from environmental co-occurrence, not confirmed infection
- **Problem:** 22/104 hosts are non-crustacean (lab strains)
- Virus-Host DB does this better with >8,000 curated host-virus associations across all viruses

### Manual Curation (CrustaVirus DB: ○)
- **Partial:** 175 "core" isolates manually reviewed
- **Problem:** 1,544 records still need review; 89.6% of data is auto-imported
- ICTV VMR and ViralZone are fully expert-curated

### Taxonomy Alignment (CrustaVirus DB: ○)
- **Partial:** virus_master table maps to ICTV VMR via alias resolution
- **Problem:** Many species-level assignments are inferred from sequence similarity, not ICTV ratification
- NCBI Taxonomy and ICTV VMR are the authorities

### Geographic Occurrence (CrustaVirus DB: ○)
- **Partial:** 35 countries, 1,981 curated profiles with country data, 1,263 with coordinates
- **Claimable:** "The only resource that systematically geolocates crustacean virus isolates"
- **Problem:** 36.3% of profiles lack country data; coordinate precision varies
- NCBI BioSample has similar data but not extracted/indexed for crustacean viruses specifically

### Host Ecology Traits (CrustaVirus DB: ○)
- **Partial:** Habitat, aquaculture_status, IUCN status for 82 crustacean host species
- **Claimable:** "The only resource linking crustacean virus data to standardized host ecological traits"
- **Problem:** Integration depth is shallow (mostly binary classifications)

### Protein Function Annotation (CrustaVirus DB: ○)
- GO: **✗** (0.4% coverage is effectively nothing)
- KEGG: **✗** (<0.1%)
- InterPro: **○** (~16.4%)
- 3D structures: **○** (52 downloaded, but most are AlphaFold predictions from public DB)
- UniProt: **○** (~49.7%, but many are existence-level matches)

### Literature Integration (CrustaVirus DB: ○)
- 317 ref_literatures, 185 linked to evidence_records
- 52 (16.4%) lack PMID/DOI — unverifiable
- Multi-source (PubMed, CNKI, Wanfang, bioRxiv) is unique among crustacean resources
- NCBI Virus > PubMed linking is more comprehensive

### API Access (CrustaVirus DB: ○)
- FastAPI endpoints exist but not publicly deployed
- No HTTPS, no authentication (planned)
- Rate limiting is in-memory
- NCBI E-utilities are production-grade

---

## What We ACTUALLY Do Better

### 1. Integration depth for crustacean viruses
**This is our only defensible novelty claim.** No existing resource brings together all of the following for crustacean viruses:
- Sequence metadata (from GenBank)
- Host taxonomy with ecological traits (habitat, aquaculture importance, conservation status)
- Geographic occurrence with coordinate-level precision
- Outbreak event documentation with mortality estimates
- Literature evidence with multi-source coverage (PubMed + CNKI + bioRxiv)
- Protein annotation indexes (even if sparse)

Each individual data type exists elsewhere. The integration is the contribution.

### 2. Data tiering and provenance transparency
**This is a methodological contribution.** Our three-tier system (core / extended / unverified) with explicit curation status per record is uncommon among virus databases. Most resources present all data as equally valid. We provide:
- `curation_status` column on curated entities (not just reviewed/unreviewed, but specific status)
- `dataset_tier` column distinguishing manual from automated records
- Provenance tracking from source through enrichment

### 3. Crustacean-specific focus
**This is a scope contribution.**
- NCBI Virus: crustacean filter exists but is just a host taxon query — no curated host links, no ecological data, no outbreak data
- Virus-Host DB: all-virus scope with broader host coverage but no crustacean-specific integration
- All crustacean-specific resources: limited to single pathogens (WSSV, YHV), not comprehensive
- Our scope: 82 true crustacean host species, 30+ virus families, global coverage

### 4. Geographic and ecological data
**Weak but defensible.** We are the first resource to:
- Map crustacean virus isolates to standardized geographic coordinates
- Link virus occurrence to host ecological traits (habitat, aquaculture status)
- Document outbreak events with structured mortality and location data

### 5. Multi-source literature coverage
**A pragmatic differentiator.** We integrate Chinese-language literature (CNKI, Wanfang) that is invisible to PubMed-centric resources. Given that China is the world's largest aquaculture producer and has 602 curated isolate profiles (the most of any country), this coverage is relevant.

---

## Honest Summary

If NAR (or any journal) asks "What does CrustaVirus DB provide that NCBI Virus + a Python script cannot?", our answer must be:

> *"Approximately 2-3 weeks of a bioinformatician's time, saved as a reusable resource with structured metadata, provenance tracking, and a web interface. Additionally, the host ecological traits, Chinese literature coverage, outbreak documentation, and data tiering system are not available through any combination of existing resources, and they cannot be replicated from NCBI alone."*

This is not a killer app. It is a solid, well-designed infrastructure paper. That is sufficient for Database journal or Scientific Data. It is likely insufficient for NAR Database Issue without substantial scale expansion (Track A) and annotation depth improvement (Track B).

---

## Comparison with Crustacean-Specific Resources

| Feature | CrustaVirus DB | WSSV-only resources | ShrimpVirusDB (if exists) | General crustacean virology reviews |
|---------|:--------------:|:-------------------:|:-------------------------:|:----------------------------------:|
| Multi-virus coverage | ✓ 526 species | ✗ WSSV only | ○ (hypothetical) | ○ (literature list) |
| Sequence data | ✓ 3,783 isolates | ✓ | ~ | ✗ |
| Interactive search | ✓ (FastAPI) | ✗ | ~ | ✗ |
| Bulk download | ✓ | ✓ | ~ | ✗ |
| Curated host links | ○ | ✓ | ~ | ✗ |
| Geographic map | ○ | ✗ | ~ | ✗ |
| Protein domains | ○ | ✓ (published) | ~ | ✗ |
| Updated regularly | Planned | ✗ (static) | ~ | ✗ |

**Note:** We did not find an existing multi-species crustacean virus database to compare against. This supports the scope novelty claim but is also a weak argument — the absence of competitors may indicate low demand rather than an unfilled niche.

---

## What We Do NOT Do Better (honest admission)

1. **Sequence quantity:** NCBI Virus has more crustacean virus sequences than we do (they have the raw GenBank data; we have a filtered subset)
2. **Curation quality:** ICTV VMR and ViralZone have expert validation; most of our data is auto-imported
3. **FAIR compliance:** None of the FAIR principles are fully met (no PID, no public URL, no ontology export, no standardized format)
4. **Community adoption:** Zero — no citations, no preprints, no conference presentations
5. **Technical architecture:** SQLite is not appropriate for production; API is not publicly deployed
6. **Reproducibility:** Cannot reproduce data from primary sources; pipeline has undocumented steps
7. **Predictive modeling:** model_performance_metrics table is empty; no ML results exist
8. **Protein annotation depth:** Coverage is too sparse to support biological discovery
