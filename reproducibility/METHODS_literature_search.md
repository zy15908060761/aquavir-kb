# Literature search: sources, query strings and dates

## Sources

- **Primary: PubMed**, via NCBI E-utilities (`esearch` / `efetch`).
- **Supplementary: Europe PMC**, via its REST API (`https://www.ebi.ac.uk/europepmc/webservices/rest/search`).

The manuscript Methods should therefore describe the corpus as retrieved from **PubMed (primary) with supplementary Europe PMC searches**, not from Europe PMC alone.

## Query layers

All queries used `[Title/Abstract]` fields and were run without a lower publication-year bound unless stated otherwise.

### 1. Per-virus search (`batch_search_all_viruses.py`, run 2026-05-16)

For each virus in `virus_master`, up to three queries were issued:

```text
{canonical_name}[Title/Abstract]
{abbreviation}[Title/Abstract]                      # only if len(abbreviation) > 2 and != name
{virus_family}[Title/Abstract] AND {host_phylum}[Title/Abstract]
```

Run statistics (from `search_summary.json`):

- viruses searched: **834**
- viruses with at least one PMID: **208**
- unique PMIDs: **16,672**
- retrieval timestamp: **2026-05-16T17:31:08**
- coverage report (2026-05-17): **17,965 articles**

### 2. Phylum-level search (`batch_search_phylum_level.py`, run 2026-05-16)

Host-term queries were used to broaden coverage beyond virus names. Examples:

```text
(abalone[Title/Abstract] OR oyster[Title/Abstract] OR mussel[Title/Abstract]
 OR clam[Title/Abstract] OR scallop[Title/Abstract] OR mollus*[Title/Abstract]
 OR haliotis[Title/Abstract] OR crassostrea[Title/Abstract] OR mytilus[Title/Abstract]
 OR pinctada[Title/Abstract])
AND (virus[Title/Abstract] OR herpesvirus[Title/Abstract] OR pathogen[Title/Abstract])

Malacoherpesviridae[Title/Abstract]
osHV[Title/Abstract] OR “ohv[Title/Abstract] OR ‘ohv[Title/Abstract]
```

Equivalent query sets were used for Cnidaria (coral, jellyfish, sea anemone, *Nematostella*, *Hydra*), Echinodermata (sea urchin, starfish, echinoderm, asteroid) and Porifera (sponge, poriferan, marine sponge), with virus/virome/viral terms.

### 3. Broad / emerging-virus search (`batch_search_broad_queries.py`, run 2026-05-16)

Targeted queries for viruses that are poorly covered by name-based search, including Wenzhou/Yueviridae, Beihai, Qianjiang marna-like and picorna-like viruses, Laem-Singh virus, covert mortality nodavirus (CMNV), *Artemia* chuviruses/iflaviruses, and mud-crab reoviruses. Examples:

```text
(Wenzhou[Title/Abstract] OR yuevirus[Title/Abstract] OR Yueviridae[Title/Abstract])
AND (shrimp[Title/Abstract] OR penaeus[Title/Abstract] OR crustacean[Title/Abstract])

(Qianjiang[Title/Abstract])
AND (marna-like[Title/Abstract] OR Marnaviridae[Title/Abstract] OR marnavirus[Title/Abstract])
AND (shrimp[Title/Abstract] OR crab[Title/Abstract] OR crustacean[Title/Abstract])

(covert mortality[Title/Abstract] OR CMNV[Title/Abstract])
AND (shrimp[Title/Abstract] OR penaeus[Title/Abstract] OR crustacean[Title/Abstract])
```

### 4. Phenotype searches (`literature_curation_v2/run_pubmed_search.py`, run 2026-05-08)

Two templates were used for the priority viruses:

```text
# virulence
{name}[Title/Abstract]
AND (shrimp[Title/Abstract] OR crustacean[Title/Abstract] OR prawn[Title/Abstract]
     OR crab[Title/Abstract] OR crayfish[Title/Abstract] OR Macrobrachium[Title/Abstract]
     OR Penaeus[Title/Abstract] OR Scylla[Title/Abstract])
AND (mortality[Title/Abstract] OR pathogenicity[Title/Abstract] OR virulence[Title/Abstract]
     OR LD50[Title/Abstract] OR "cumulative mortality"[Title/Abstract]
     OR "lethal dose"[Title/Abstract])

# thermal
{name}[Title/Abstract]
AND (shrimp[Title/Abstract] OR crustacean[Title/Abstract] OR prawn[Title/Abstract]
     OR crab[Title/Abstract] OR crayfish[Title/Abstract] OR Macrobrachium[Title/Abstract]
     OR Penaeus[Title/Abstract] OR Scylla[Title/Abstract])
AND (temperature[Title/Abstract] OR thermal[Title/Abstract]
     OR "heat inactivation"[Title/Abstract] OR "cold storage"[Title/Abstract]
     OR "optimal temperature"[Title/Abstract] OR "thermal stability"[Title/Abstract]
     OR "thermal inactivation"[Title/Abstract])
```

### 5. Europe PMC supplements

`search_epmc_literature.py` (main fetch 2026-05-05/06) used 14 grouped queries, for example:

```text
(coral AND (virome OR virus OR viral)) AND (PUB_YEAR:[2018 TO 2026])
(oyster AND (virome OR virus OR viral)) AND (PUB_YEAR:[2020 TO 2026])
("aquatic invertebrate" AND (virus OR virome)) AND (PUB_YEAR:[2018 TO 2026])
```

`search_epmc_new_literature.py` (2026-08-14) used per-virus queries:

```text
("{virus name}" AND virus) AND (FIRST_PDATE:[2023-01-01 TO 2026-12-31])
```

## Search period

- The primary PubMed searches had **no lower year bound**; coverage extends to the retrieval date (2026-05-16).
- Europe PMC supplements used lower bounds of 2018 or 2020, and a 2023-01-01 lower bound for the per-virus update.

## Reproducibility caveats

- NCBI E-utilities results change over time as PubMed is updated; exact re-runs will not return identical PMID sets.
- The scripts contain the full query construction logic. The entity lists (virus names, families, host phyla) come from the database snapshot, not from the scripts.
- No single combined query string exists: the corpus is the union of the five query layers above.
