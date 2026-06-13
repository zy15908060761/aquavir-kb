# NAR Database Issue — Review Report
## Dimension: Schema Design & Technical Architecture
### Verdict: **REJECT** (Production-unready infrastructure)

---

## FATAL FLAWS

### F1. SQLite as production database — architecturally indefensible
The entire web-accessible database runs on a single **700+ MB SQLite file**. This is fundamentally unsuitable for any database claiming NAR-level production readiness:
- **File-level locking:** SQLite serializes all writes. Under concurrent web access, readers will be blocked by writers, causing timeouts and failures.
- **No connection pooling:** SQLite is not designed for client-server architectures. Each web request opens a new connection to the file.
- **No role-based access control:** No user permissions model. The API key "authentication" has no granular authorization.
- **No replication, no failover, no backup strategy:** A single SQLite file on a single server.
- **The authors admit this:** *"A reviewer from the database community would reject this on architectural grounds alone."* (narrative_gaps.md, Gap 12)

**NAR publishes databases that serve thousands of concurrent users.** SQLite cannot do this. Period.

### F2. No public deployment exists
The manuscript abstract claims *"freely available at [URL]"* but:
- **No public URL is deployed** (a BLOCKER per the authors' own checklist)
- **No HTTPS** — would fail browser security requirements
- The "web interface" section describes screenshots that **cannot be taken** because the system is not deployed
- Previous mockup screenshots contained fabricated data (see Review 1, F4)

A NAR Database Issue submission without a functioning public website is **not a submission** — it is a proposal.

### F3. 119-table schema is bloated, not designed
119 tables for a database of 526 core entities is **excessive** by any standard. The schema shows signs of organic/agile accretion rather than deliberate design:
- Many tables appear to be **ETL intermediate tables** (`ncbi_*`, `import_*`) that should not be part of the public schema
- The `crustacean_hosts` table name persists despite 5-phylum expansion — consistent with unplanned scope creep
- No clear separation between operational/ETL tables and public-facing data tables
- The "view" layer (27 views per abstract) suggests the underlying schema is too complex for direct querying

### F4. No graph database for a "knowledge graph"
The paper's central claim is being a **"multi-layer knowledge graph"** but:
- The implementation is **purely relational** (SQL tables + foreign keys)
- No RDF triples, no OWL ontology, no SPARQL endpoint
- No Neo4j or any graph database backend
- No OBO Foundry alignment
- A relational schema with foreign keys ≠ knowledge graph
- This is **category confusion** — calling a relational database a "knowledge graph" is misleading to reviewers familiar with semantic web technologies

---

## MAJOR CONCERNS

### M1. No CI/CD, no Docker, no reproducible build
- **196 Python scripts** with no unified workflow, no Makefile, no dependency management file
- **No Docker Compose** — means every environment is unique and unreproducible
- **No GitHub Actions** or any CI pipeline
- Reproducibility is described as *"circular: dump → rebuild → export"* — this is not reproducibility
- Tests directory contains only **5 files** for a codebase of 196+ scripts

### M2. Production infrastructure is aspirational, not actual
The paper's Methods M4 describes:
- "In-memory rate limiting" — trivial to bypass by spawning new connections
- Jinja2 server-rendered HTML — not a modern interactive web application
- No load balancer, no reverse proxy, no monitoring
- The planned migration to PostgreSQL is described as "3-5 days of work" — suggesting the authors underestimate production database migration complexity by an order of magnitude

### M3. Three-tier curation is a narrative construct, not a schema-enforced system
The "core/extended/unverified" tiering is:
- Documented in the manuscript text, but **not enforced by schema constraints, triggers, or automated checks**
- No automated flagging of records that violate tier boundaries
- No database-level gate preventing unverified records from being presented as validated
- Practically: this is a **labeling convention**, not a curation system

### M4. No ontology or controlled vocabulary integration
- Host traits from WoRMS/FishBase are stored as free-text, not linked to ontology terms
- No EnvO (Environment Ontology) for habitat types
- No PATO (Phenotype And Trait Ontology) for virulence characteristics
- No OBI (Ontology for Biomedical Investigations) for assay methods
- For a "knowledge base" targeting NAR, this lack of semantic interoperability is a significant gap

---

## MINOR ISSUES

- `crustacean_hosts` table scope mismatch: name says crustacean, content spans 5 phyla. Rename to `aquatic_invertebrate_hosts`.
- No API versioning strategy (`/api/v1/` convention missing)
- No documented database migration system (Alembic or similar) for schema evolution
- The `backend.py` file is 210 KB — a monolithic design suggesting poor code organization
- No Swagger/OpenAPI documentation for the REST API (despite using FastAPI which auto-generates it — was it disabled?)

---

## SUMMARY ASSESSMENT

The technical architecture is at the **proof-of-concept stage**, not production-ready. The combination of SQLite as a web backend, zero public deployment, no CI/CD, and no Docker reproducibility makes this database unsuitable for publication in a venue that expects community-facing, production-grade resources.

The "knowledge graph" framing is particularly damaging — it sets expectations the implementation cannot meet, inviting rejection from any reviewer familiar with semantic web or graph database technologies.

**Recommendation: REJECT**

A minimum viable NAR submission requires: PostgreSQL migration completed, public HTTPS deployment, Docker Compose reproducibility, CI/CD pipeline, and a genuine graph/RDF layer **or** an honest renaming from "knowledge graph" to "relational database."

**Suitable venue after infrastructure maturation:** *Database* (Oxford), which has lower infrastructure requirements than NAR Database Issue.
