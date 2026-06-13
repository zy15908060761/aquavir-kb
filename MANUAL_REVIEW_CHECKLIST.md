# Manual Review Checklist - NAR Submission Readiness

This checklist lists work that cannot be honestly automated. Do not present any
unchecked item here as completed in the manuscript, README, data availability
statement, cover letter, or public website.

## Critical Before Any NAR Pre-Query

### 1. Author Identity and ORCID

- [ ] Replace placeholder authors in `CITATION.cff` with real names.
- [ ] Obtain ORCID iDs for all authors.
- [ ] Decide corresponding author and use an institutional email.
- [ ] Confirm all authors can approve the database scope and data-use terms.

### 2. Public URL and Hosting

- [ ] Register and activate a real domain or institutional subdomain.
- [ ] Deploy the database on a stable public server with HTTPS.
- [ ] Confirm the site is free to access and does not require registration.
- [ ] Test all public API endpoints from outside the local network.
- [ ] Define who maintains the URL for at least five years after publication.

### 3. Persistent Archive and DOI

- [ ] Create a frozen release in a public archive such as Zenodo.
- [ ] Mint a DOI for the exact v1.0 code/data release.
- [ ] Update `CITATION.cff`, README, and the manuscript data availability
      statement with the real DOI.
- [ ] Verify the archived release matches the public website download manifest.

### 4. Copyright and Compliance Cleanup

- [ ] Verify no Sci-Hub or copyright-circumvention URLs, files, or code remain.
- [ ] Verify any full-text PDFs have legal provenance or are excluded.
- [ ] Search the final public repository for `sci-hub`, `scihub`, and `sci_hub`.
- [ ] Document third-party data licenses and attribution requirements.

## Critical Before Full Manuscript Submission

### 5. Manual Evidence Backlog

Current public reviewed evidence count is 0. This blocks any manuscript claim
that CrustaVirus DB contains a curated virulence, temperature, host-range,
outbreak, or diagnostic knowledge base.

| Category | Current status | Required decision |
|----------|----------------|-------------------|
| Evidence records | Needs manual literature verification | Verify with PMID/DOI/source text or exclude from primary claims |
| Diagnostic methods | 7 manual-checked, 18 still in review | Verify method citations and validation contexts |
| ICTV mappings | Pending-review rows remain | Resolve or mark as non-primary |
| Host-range evidence | Unreviewed backlog | Batch-review with documented curator and batch ID or exclude |
| Pathogenicity evidence | Unreviewed backlog | Batch-review with documented curator and batch ID or exclude |
| Environmental evidence | Largest unreviewed backlog | Keep out of primary claims unless manually verified |
| Outbreak events | 3 manual-checked; most remain unreviewed | Verify against original outbreak reports |
| Virulence/temperature profiles | Candidate worklists only | Do not use as biological conclusions until reviewed |

Minimum acceptable review record for promoted evidence:

- source PMID, DOI, accession, or stable URL;
- curator name or initials;
- review date;
- exact curation decision;
- short note explaining the evidence;
- reproducible link to the database row.

### 6. Traceability of Core Records

- [ ] For strict-release isolates without host links, either fill host evidence
      or exclude them from host-centered primary statistics.
- [ ] For strict-release isolates without PMID/DOI, document accession-derived
      provenance or exclude them from literature-supported claims.
- [ ] Freeze one release ID and generate every manuscript count from that
      release manifest.

### 7. Public Downloads

- [ ] Rebuild public downloads in one command.
- [ ] Regenerate checksums immediately after file generation.
- [ ] Verify no public download contains local absolute paths, logs, raw
      intermediate files, or unreviewed phylogeny FASTA/alignment artifacts.
- [ ] Ensure every public file is listed in `SHA256SUMS.csv`.

### 8. API Scope

- [ ] Public endpoints must use release-filtered views or be clearly labeled as
      source-derived indexes.
- [ ] Internal queues, sync logs, curation priority records, and raw candidate
      tables must not be publicly exposed without authentication.
- [ ] Any endpoint returning source-derived enrichment records must return a
      scope/status field such as `source_status` or `publication_use`.

### 9. Manuscript and Cover Letter

- [ ] Title starts with the database name.
- [ ] Abstract includes the public URL.
- [ ] Main text uses one frozen release ID and exact counts.
- [ ] Novelty is framed as crustacean-specific integration and release
      filtering, not as a fully curated evidence knowledge base.
- [ ] AI/tool-use disclosure is included where required.
- [ ] Six qualified referee suggestions are prepared.

## Current NAR Position

Ignoring the external hosting blocker, the database is not submission-ready.
It can support internal hardening and possibly a cautious pre-query only after
the public URL exists. It cannot yet support claims of a manually curated
virulence, temperature, host-range, outbreak, or diagnostic evidence resource.

Generated: 2026-05-11
