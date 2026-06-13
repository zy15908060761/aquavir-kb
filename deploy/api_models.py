"""
Pydantic response models for the AquaVir-KB API.

These models provide structured schemas that appear in the auto-generated
OpenAPI / Swagger documentation, making the API self-documenting for
consumers (frontend, external tools, notebooks).
"""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


# ── 1. Protein search result ─────────────────────────────────────

class ProteinResponse(BaseModel):
    """Single protein annotation as returned by the protein search endpoint."""
    protein_id: int = Field(..., description="Internal primary key of the protein record")
    protein_accession: str = Field("", description="Cross-database protein accession (e.g. GenBank protein ID)")
    protein_name: str = Field("", description="Descriptive name of the protein product")
    gene_symbol: str = Field("", description="Gene symbol / locus abbreviation")
    locus_tag: Optional[str] = Field(None, description="Locus tag assigned during annotation")
    aa_length: Optional[int] = Field(None, description="Length of the amino-acid sequence")
    functional_category: Optional[str] = Field(None, description="Functional classification (e.g. structural, replication, host_modulation)")
    functional_annotation_status: Optional[str] = Field(None, description="Curation/status label for the functional annotation")
    accession: str = Field("", description="NCBI / INSDC nucleotide accession of the parent isolate")
    virus_name: str = Field("", description="Canonical virus species name")
    has_structure: bool = Field(False, alias="_has_structure", description="Whether at least one 3D structure (AlphaFold / ESMFold / PDB) is associated with this protein")
    model_config = ConfigDict(populate_by_name=True)


class PaginatedProteinResponse(BaseModel):
    """Wrapper for the paginated protein search endpoint response."""
    total: int = Field(..., description="Total number of matching proteins across all pages")
    page: int = Field(..., description="Current page number (1-indexed)")
    page_size: int = Field(..., description="Number of results per page")
    results: List[ProteinResponse] = Field(default_factory=list, description="List of protein records for the current page")


# ── 2. Structure record ──────────────────────────────────────────

class StructureResponse(BaseModel):
    """A single 3D structure record (AlphaFold, PDB, or ESMFold prediction)."""
    structure_id: Optional[int] = Field(None, description="Internal ID for locally predicted structures")
    uniprot_id: Optional[str] = Field(None, description="UniProt accession linked to this structure")
    source: str = Field(..., description="Origin of the structure (alphafold, pdb, esmfold)")
    entry_id: Optional[str] = Field(None, description="PDB entry ID or AlphaFold DB identifier")
    plddt_score: Optional[float] = Field(None, description="Predicted local distance difference test (pLDDT) confidence score", ge=0, le=100)
    sequence_length: Optional[int] = Field(None, description="Length of the protein sequence used for prediction")
    pdb_url: Optional[str] = Field(None, description="URL to download the PDB file")
    protein_id: Optional[int] = Field(None, description="Foreign key to the viral_proteins table")
    prediction_method: Optional[str] = Field(None, description="Method used for prediction (esmfold, etc.)")
    confidence: Optional[float] = Field(None, description="Normalized confidence score (alternative to pLDDT)")


# ── 3. Expansion statistics (v2.0) ─────────────────────────────────

class HostPhylumStats(BaseModel):
    """Aggregated virus/host statistics grouped by host phylum."""
    phylum: str = Field(..., description="Host taxonomic phylum")
    virus_species_count: int = Field(..., description="Distinct virus species count")
    isolate_count: int = Field(..., description="Distinct viral isolate count")
    host_species_count: int = Field(..., description="Distinct host species count")


class ExpansionStats(BaseModel):
    """Expansion progress tracking for the aquatic invertebrate expansion (v2.0)."""
    total_virus_species: int = Field(..., description="Total virus species in database")
    phyla_covered: int = Field(..., description="Distinct host phyla covered")
    target_hosts_by_phylum: Dict[str, int] = Field(..., description="Target host count by phylum")
    evidence_coverage_pct: float = Field(..., description="Percentage of infection records with confirmed association method")
    species_with_structures: int = Field(..., description="Virus species with at least one 3D structure")


class InfectionRecordResponse(BaseModel):
    """A single virus-host infection/association record."""
    infection_id: int = Field(..., description="Primary key of infection record")
    virus_name: str = Field(..., description="Virus name (canonical or original)")
    host_name: str = Field(..., description="Host scientific name")
    host_phylum: str = Field(..., description="Host taxonomic phylum")
    host_class: str = Field(..., description="Host taxonomic class")
    association_method: str = Field(..., description="Host association method")
    detection_method: Optional[str] = Field(None, description="Detection/diagnostic method used")
    evidence_strength: Optional[str] = Field(None, description="Evidence strength rating")


class HostDetailResponse(BaseModel):
    """Detailed information for a single host species."""
    host_id: int = Field(..., description="Internal primary key")
    scientific_name: str = Field(..., description="Host scientific name")
    phylum: str = Field(..., description="Taxonomic phylum")
    class_name: str = Field("", alias="class", description="Taxonomic class")
    host_scope_status: str = Field(..., description="Host scope classification")
    virus_count: int = Field(..., description="Distinct virus species associated with this host")
    aquaculture_status: Optional[str] = Field(None, description="Aquaculture relevance status")

    model_config = ConfigDict(populate_by_name=True)


# ── 4. Database statistics ───────────────────────────────────────

class StatsResponse(BaseModel):
    """Aggregated statistics for the database home page.

    Key fields carry a ``scope_note`` explaining the data source.  Three scopes
    are tracked:

    * **target_isolates** / **target_hosts** / **target_species** --
      counts scoped to the ``analysis_target_isolates`` view
      (broad target set, excludes serious conflicts).
    * **strict_target_isolates** / **strict_target_hosts** / **strict_target_species** --
      counts scoped to the ``analysis_strict_target_isolates`` view
      (release-filtered set; not necessarily manual-reviewed).
    * **total_isolates** / **total_hosts** / **total_species** --
      counts from the raw database tables (full database).
    """
    # ── Scope documentation ────────────────────────────────────────
    scope_note: str = Field(
        default=(
            "'target_*' counts use analysis_target_isolates (broad target set); "
            "'strict_target_*' uses analysis_strict_target_isolates (release-filtered, not necessarily manual-reviewed); "
            "'total_*' counts use the raw database tables (full database)."
        ),
        description="Explains the three counting scopes returned by this endpoint",
    )

    # ── Main display numbers (total database scope) ──────────────────
    viral_isolates: int = Field(
        ...,
        description="Total viral isolates in the database across all phyla",
    )
    virus_species: int = Field(
        ...,
        description="Total distinct virus species in the database",
    )
    aquatic_invertebrate_hosts: int = Field(
        ...,
        description="Total aquatic invertebrate host species",
    )

    # ── Explicit target scopes ─────────────────────────────────────
    strict_target_isolates: int = Field(
        ..., description="Isolate count from analysis_strict_target_isolates (conflict_open excluded)"
    )
    strict_target_species: int = Field(
        ..., description="Virus species count from analysis_strict_target_isolates"
    )
    strict_target_hosts: int = Field(
        ..., description="Host species count from analysis_strict_target_isolates"
    )

    target_isolates: int = Field(
        ..., description="Isolate count from analysis_target_isolates view (publication-ready set)"
    )
    target_species: int = Field(
        ..., description="Virus species count from analysis_target_isolates view"
    )
    target_hosts: int = Field(
        ..., description="Host species count from analysis_target_isolates view"
    )

    # ── Full-database totals ───────────────────────────────────────
    total_isolates: int = Field(
        ..., description="Total isolate count from the raw viral_isolates table (full database)"
    )
    total_species: int = Field(
        ..., description="Total distinct virus species from the raw virus_master table"
    )
    total_hosts: int = Field(
        ..., description="Total distinct crustacean host species from the raw crustacean_hosts table"
    )

    # ── Remaining fields (unchanged) ───────────────────────────────
    viral_proteins: int = Field(..., description="Total number of annotated viral proteins / CDS")
    proteins_with_structure: int = Field(..., description="Number of viral proteins that have at least one 3D structure (AlphaFold / PDB / ESMFold)")
    core_genes: int = Field(0, description="Number of core / conserved gene entries")
    ref_literatures: int = Field(0, description="Number of reference publications linked to isolates")
    sample_collections: int = Field(0, description="Number of sample collection events recorded")
    virulence_covered: int = Field(0, description="Number of isolates / species with virulence evidence")
    temperature_covered: int = Field(0, description="Number of isolates / species with temperature-related evidence")
    rdrp_count: int = Field(0, description="Number of RNA-dependent RNA polymerase (RDRP) annotations")
    rdrp_species: int = Field(0, description="Number of virus species with at least one RDRP annotation")

    # ── Expansion fields (v2.0) ─────────────────────────────────────
    hosts_by_phylum: Dict[str, int] = Field(
        default_factory=dict, description="Host species count per phylum, e.g. {'Arthropoda':63, 'Mollusca':10}")
    phyla_covered: int = Field(0, description="Number of distinct host phyla in the database")
    evidence_coverage_pct: float = Field(0.0, description="Percentage of infection records with confirmed association method")


# ── 5. Virus detail ──────────────────────────────────────────────

class VirusDetailResponse(BaseModel):
    """Full detail for a single virus isolate record."""
    accession: str = Field(..., description="NCBI / INSDC sequence accession (primary key)")
    virus_name: str = Field("", description="Virus name from the original record")
    canonical_name: Optional[str] = Field(None, description="Standardized canonical virus species name")
    genome_length: Optional[int] = Field(None, description="Length of the genomic sequence (bp / nt)")
    gc_content: Optional[float] = Field(None, description="GC content of the genome as a percentage")
    protein_count: int = Field(0, description="Number of annotated proteins / CDS for this isolate")
    host_name: Optional[str] = Field(None, description="Scientific name of the crustacean host")
    country: Optional[str] = Field(None, description="Country of sample collection")
    collection_year: Optional[int] = Field(None, description="Year the sample was collected")
    has_sequence_file: bool = Field(False, description="Whether a local FASTA file is available for download")
    ncbi_nucleotide_url: str = Field("", description="Direct URL to the NCBI Nucleotide record")


# ── 6. RDRP protein record ───────────────────────────────────────

class RDRPResponse(BaseModel):
    """An RNA-dependent RNA polymerase (RDRP) protein record."""
    protein_id: int = Field(..., description="Internal primary key of the RDRP protein record")
    protein_accession: str = Field("", description="Cross-database protein accession")
    protein_name: str = Field("", description="Name of the RDRP / polymerase protein")
    gene_symbol: str = Field("", description="Gene symbol (e.g. RdRp, L, Pol)")
    virus_species: str = Field("", description="Canonical virus species name")
    accession: str = Field("", description="NCBI nucleotide accession of the parent isolate")
    genome_type: Optional[str] = Field(None, description="Genome type (ssRNA, dsRNA, ssDNA, etc.)")
    aa_length: Optional[int] = Field(None, description="Amino-acid length of the RDRP protein")
    functional_category: Optional[str] = Field(None, description="Functional classification")
    functional_annotation_status: Optional[str] = Field(None, description="Curation/status label for the functional annotation")
    has_structure: bool = Field(False, alias="_has_structure", description="Whether a 3D structure is available for this RDRP")

    class Config:
        populate_by_name = True


class PaginatedRDRPResponse(BaseModel):
    """Wrapper for the paginated RDRP list endpoint response."""
    total: int = Field(..., description="Total number of matching RDRP records across all pages")
    page: int = Field(..., description="Current page number (1-indexed)")
    page_size: int = Field(..., description="Number of results per page")
    results: List[RDRPResponse] = Field(default_factory=list, description="List of RDRP records for the current page")
