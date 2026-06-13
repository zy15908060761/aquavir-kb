-- Full schema dump from crustacean_virus_core.db
-- Exported: 2026-05-09 12:18:36
-- Tables: 119
-- Views:  27
-- Indexes: 216
-- Triggers: 0

BEGIN TRANSACTION;

-- table: auto_annotation_gap_worklist
CREATE TABLE auto_annotation_gap_worklist (
            worklist_id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_ts TEXT NOT NULL,
            priority TEXT NOT NULL,
            protein_id INTEGER,
            isolate_id INTEGER,
            accession TEXT,
            protein_accession TEXT,
            protein_name TEXT,
            gap_type TEXT NOT NULL,
            suggested_action TEXT,
            status TEXT NOT NULL DEFAULT 'open',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

-- table: auto_completeness_fills
CREATE TABLE auto_completeness_fills (
            fill_id INTEGER PRIMARY KEY AUTOINCREMENT,
            entity_type TEXT NOT NULL,
            entity_id INTEGER NOT NULL,
            field_name TEXT NOT NULL,
            old_value TEXT,
            new_value TEXT NOT NULL,
            method TEXT NOT NULL,
            confidence TEXT NOT NULL,
            source_table TEXT,
            source_id TEXT,
            needs_manual_review INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(entity_type, entity_id, field_name, method, new_value)
        );

-- table: auto_completeness_worklist
CREATE TABLE auto_completeness_worklist (
            worklist_id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_ts TEXT NOT NULL,
            priority TEXT NOT NULL,
            entity_type TEXT NOT NULL,
            entity_id TEXT,
            accession TEXT,
            virus_master_id INTEGER,
            virus_name TEXT,
            issue_type TEXT NOT NULL,
            suggested_source TEXT,
            suggested_action TEXT,
            current_value TEXT,
            status TEXT NOT NULL DEFAULT 'open',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

-- table: auto_host_scope_worklist
CREATE TABLE auto_host_scope_worklist (
            worklist_id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_ts TEXT NOT NULL,
            host_id INTEGER,
            scientific_name TEXT,
            host_type TEXT,
            host_group TEXT,
            taxon_order TEXT,
            issue_type TEXT NOT NULL,
            suggested_scope_status TEXT,
            suggested_exclude_from_target_stats INTEGER,
            evidence TEXT,
            status TEXT NOT NULL DEFAULT 'open',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(host_id) REFERENCES crustacean_hosts(host_id)
        );

-- table: auto_quality_metrics
CREATE TABLE auto_quality_metrics (
            metric_id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_ts TEXT NOT NULL,
            category TEXT NOT NULL,
            metric TEXT NOT NULL,
            numerator INTEGER,
            denominator INTEGER,
            pct REAL,
            notes TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

-- table: biorxiv_preprints
CREATE TABLE biorxiv_preprints (
            preprint_id INTEGER PRIMARY KEY AUTOINCREMENT,
            doi TEXT NOT NULL UNIQUE,
            title TEXT,
            authors TEXT,
            author_corresponding TEXT,
            author_corresponding_institution TEXT,
            abstract TEXT,
            date_posted TEXT,
            date_revised TEXT,
            server TEXT,
            category TEXT,
            collection TEXT,
            version INTEGER,
            published_doi TEXT,
            published_journal TEXT,
            match_status TEXT DEFAULT 'pending_review',
            local_virus_names TEXT,
            local_host_names TEXT,
            relevant INTEGER DEFAULT 1,
            raw_json TEXT,
            fetched_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

-- table: biosample_links
CREATE TABLE biosample_links (
            link_id INTEGER PRIMARY KEY AUTOINCREMENT,
            isolate_id INTEGER,
            accession TEXT,
            biosample_accession TEXT,
            bioproject_accession TEXT,
            source_text TEXT,
            match_confidence TEXT,
            curation_status TEXT DEFAULT 'needs_remote_lookup',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (isolate_id) REFERENCES viral_isolates(isolate_id)
        );

-- table: completeness_optimization_log
CREATE TABLE completeness_optimization_log (
            log_id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_ts TEXT NOT NULL,
            priority INTEGER NOT NULL,
            target_table TEXT NOT NULL,
            target_id TEXT,
            field_name TEXT NOT NULL,
            old_value TEXT,
            new_value TEXT,
            source TEXT NOT NULL,
            confidence TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

-- table: compliance_quarantine_log
CREATE TABLE compliance_quarantine_log (
            log_id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_path TEXT NOT NULL,
            quarantined_path TEXT,
            reason TEXT NOT NULL,
            action_taken TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(file_path, reason)
        );

-- table: control_management_methods
CREATE TABLE control_management_methods (
            control_id INTEGER PRIMARY KEY AUTOINCREMENT,
            virus_master_id INTEGER,
            host_id INTEGER,
            method_category TEXT NOT NULL CHECK (
                method_category IN ('vaccine', 'immunostimulant', 'thermal_management', 'biosecurity', 'selective_breeding', 'pond_management', 'disinfection', 'other')
            ),
            method_name TEXT NOT NULL,
            effect_summary TEXT,
            validation_context TEXT,
            reference_id INTEGER,
            evidence_strength TEXT DEFAULT 'medium' CHECK (
                evidence_strength IN ('high', 'medium', 'low', 'unknown')
            ),
            curation_status TEXT DEFAULT 'needs_review' CHECK (
                curation_status IN ('auto_seeded', 'needs_review', 'manual_checked', 'rejected')
            ),
            notes TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP, vaccine_type TEXT,
            FOREIGN KEY (virus_master_id) REFERENCES virus_master(master_id),
            FOREIGN KEY (host_id) REFERENCES crustacean_hosts(host_id),
            FOREIGN KEY (reference_id) REFERENCES ref_literatures(reference_id)
        );

-- table: core_genes
CREATE TABLE core_genes (
        gene_id INTEGER PRIMARY KEY AUTOINCREMENT,
        virus_species VARCHAR(200) NOT NULL,
        gene_symbol VARCHAR(100),
        protein_name VARCHAR(500),
        functional_category VARCHAR(50),
        conservation_rate REAL,
        total_isolates INTEGER,
        present_isolates INTEGER,
        avg_identity REAL,
        function_summary TEXT, taxonomic_level TEXT DEFAULT 'species', taxonomic_group TEXT, min_coverage_pct REAL,
        UNIQUE(virus_species, gene_symbol)
    );

-- table: crustacean_hosts
CREATE TABLE crustacean_hosts (
        host_id INTEGER PRIMARY KEY AUTOINCREMENT,
        scientific_name VARCHAR(100) NOT NULL UNIQUE,
        common_name_cn VARCHAR(100),
        taxon_order VARCHAR(100),
        taxon_family VARCHAR(100),
        host_group VARCHAR(50),
        habitat VARCHAR(100),
        aquaculture_status VARCHAR(50),
        iucn_status VARCHAR(50)
    , host_type VARCHAR(30), iucn_assessment_year VARCHAR(10));

-- table: curation_conflicts
CREATE TABLE curation_conflicts (
            conflict_id INTEGER PRIMARY KEY AUTOINCREMENT,
            entity_type TEXT NOT NULL CHECK (
                entity_type IN ('isolate', 'virus', 'host', 'collection', 'reference')
            ),
            entity_id INTEGER NOT NULL,
            isolate_id INTEGER,
            field_name TEXT NOT NULL,
            value_a TEXT,
            source_a TEXT,
            value_b TEXT,
            source_b TEXT,
            conflict_type TEXT NOT NULL CHECK (
                conflict_type IN (
                    'missing_in_profile',
                    'value_mismatch',
                    'taxonomy_mismatch',
                    'reference_mismatch',
                    'non_target_or_noise',
                    'ambiguous_mapping'
                )
            ),
            severity TEXT DEFAULT 'medium' CHECK (
                severity IN ('high', 'medium', 'low')
            ),
            status TEXT DEFAULT 'open' CHECK (
                status IN ('open', 'resolved', 'accepted_a', 'accepted_b', 'ignored')
            ),
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            resolved_at TEXT,
            notes TEXT,
            FOREIGN KEY (isolate_id) REFERENCES viral_isolates(isolate_id)
        );

-- table: curation_logs
CREATE TABLE curation_logs (
            log_id INTEGER PRIMARY KEY AUTOINCREMENT,
            entity_type TEXT NOT NULL,
            entity_id INTEGER,
            action TEXT NOT NULL,
            source_id INTEGER,
            old_value TEXT,
            new_value TEXT,
            confidence TEXT DEFAULT 'unknown' CHECK (
                confidence IN ('high', 'medium', 'low', 'unknown')
            ),
            curator TEXT DEFAULT 'script',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            notes TEXT,
            FOREIGN KEY (source_id) REFERENCES external_sources(source_id)
        );

-- table: curation_priority_queue
CREATE TABLE curation_priority_queue (
            queue_id INTEGER PRIMARY KEY AUTOINCREMENT,
            conflict_id INTEGER NOT NULL UNIQUE,
            isolate_id INTEGER,
            accession TEXT,
            canonical_virus_name TEXT,
            field_name TEXT NOT NULL,
            conflict_type TEXT NOT NULL,
            severity TEXT NOT NULL,
            priority_score INTEGER NOT NULL,
            priority_band TEXT NOT NULL CHECK (
                priority_band IN ('P0', 'P1', 'P2', 'P3', 'ignore_candidate')
            ),
            recommended_action TEXT NOT NULL,
            queue_status TEXT NOT NULL DEFAULT 'open' CHECK (
                queue_status IN ('open', 'in_progress', 'resolved', 'ignored')
            ),
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            notes TEXT,
            FOREIGN KEY (conflict_id) REFERENCES curation_conflicts(conflict_id),
            FOREIGN KEY (isolate_id) REFERENCES viral_isolates(isolate_id)
        );

-- table: curation_standardization_log
CREATE TABLE curation_standardization_log (
            log_id INTEGER PRIMARY KEY AUTOINCREMENT,
            action TEXT NOT NULL,
            details_json TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

-- table: curation_vocab_terms
CREATE TABLE curation_vocab_terms (
            vocab_id INTEGER PRIMARY KEY AUTOINCREMENT,
            category TEXT NOT NULL,
            term TEXT NOT NULL,
            description TEXT,
            active INTEGER DEFAULT 1 CHECK (active IN (0, 1)),
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(category, term)
        );

-- table: data_gap_queue
CREATE TABLE data_gap_queue (
            queue_id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_ts TEXT NOT NULL,
            priority INTEGER NOT NULL,
            entity_type TEXT NOT NULL,
            entity_id TEXT,
            accession TEXT,
            gap_type TEXT NOT NULL,
            suggested_source TEXT,
            status TEXT DEFAULT 'open',
            notes TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

-- table: data_provenance
CREATE TABLE data_provenance (
            provenance_id INTEGER PRIMARY KEY AUTOINCREMENT,
            table_name TEXT NOT NULL,
            record_id INTEGER,
            virus_master_id INTEGER,
            virus_name TEXT,
            data_source TEXT NOT NULL,
            confidence_level TEXT NOT NULL
                CHECK (confidence_level IN ('verified', 'inferred', 'predicted', 'unverified')),
            verification_method TEXT,
            curator_notes TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (virus_master_id) REFERENCES virus_master(master_id)
        );

-- table: database_maintenance_log
CREATE TABLE database_maintenance_log (
            log_id INTEGER PRIMARY KEY AUTOINCREMENT,
            action TEXT NOT NULL,
            details_json TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

-- table: diagnostic_evidence_promotion_log
CREATE TABLE diagnostic_evidence_promotion_log (
            log_id INTEGER PRIMARY KEY AUTOINCREMENT,
            action TEXT NOT NULL,
            details_json TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

-- table: diagnostic_method_review_queue
CREATE TABLE diagnostic_method_review_queue (
            review_id INTEGER PRIMARY KEY AUTOINCREMENT,
            method_id INTEGER NOT NULL UNIQUE,
            issue_type TEXT NOT NULL,
            recommended_action TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            status TEXT DEFAULT 'open' CHECK (status IN ('open', 'resolved', 'ignored')),
            FOREIGN KEY(method_id) REFERENCES diagnostic_methods(method_id)
        );

-- table: diagnostic_methods
CREATE TABLE diagnostic_methods (
            method_id INTEGER PRIMARY KEY AUTOINCREMENT,
            virus_master_id INTEGER,
            method_category TEXT NOT NULL,
            method_subcategory TEXT,
            method_name TEXT NOT NULL,
            target_gene_or_region TEXT,
            sample_type TEXT,
            field_deployable INTEGER CHECK (field_deployable IN (0, 1)),
            visual_readout INTEGER CHECK (visual_readout IN (0, 1)),
            detection_limit TEXT,
            validation_context TEXT,
            reference_id INTEGER,
            evidence_strength TEXT DEFAULT 'medium' CHECK (
                evidence_strength IN ('high', 'medium', 'low', 'unknown')
            ),
            curation_status TEXT DEFAULT 'needs_review' CHECK (
                curation_status IN ('auto_seeded', 'needs_review', 'manual_checked', 'rejected')
            ),
            notes TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            data_quality TEXT DEFAULT 'placeholder',
            FOREIGN KEY (virus_master_id) REFERENCES virus_master(master_id),
            FOREIGN KEY (reference_id) REFERENCES ref_literatures(reference_id)
        );

-- table: environmental_evidence
CREATE TABLE environmental_evidence (
            environmental_id INTEGER PRIMARY KEY AUTOINCREMENT,
            virus_master_id INTEGER NOT NULL,
            evidence_type TEXT NOT NULL CHECK (
                evidence_type IN ('optimal_temperature', 'survival_range', 'thermal_inactivation', 'cold_storage', 'climate_impact', 'salinity', 'ph', 'other')
            ),
            value_min REAL,
            value_max REAL,
            unit TEXT,
            value_text TEXT,
            context TEXT,
            reference_id INTEGER,
            evidence_strength TEXT DEFAULT 'medium' CHECK (
                evidence_strength IN ('high', 'medium', 'low', 'unknown')
            ),
            curation_status TEXT DEFAULT 'needs_review' CHECK (
                curation_status IN ('auto_seeded', 'needs_review', 'manual_checked', 'rejected')
            ),
            notes TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (virus_master_id) REFERENCES virus_master(master_id),
            FOREIGN KEY (reference_id) REFERENCES ref_literatures(reference_id)
        );

-- table: epmc_literature
CREATE TABLE epmc_literature (
            epmc_id INTEGER PRIMARY KEY AUTOINCREMENT,
            pmid TEXT,
            pmcid TEXT,
            doi TEXT,
            title TEXT,
            authors TEXT,
            author_orcids TEXT,
            journal TEXT,
            year TEXT,
            abstract TEXT,
            source TEXT,
            publication_type TEXT,
            citation_count INTEGER,
            relative_citation_ratio REAL,
            is_open_access INTEGER DEFAULT 0,
            has_full_text INTEGER DEFAULT 0,
            grants_json TEXT,
            data_links_json TEXT,
            mesh_terms TEXT,
            keywords TEXT,
            local_reference_id INTEGER,
            match_status TEXT DEFAULT 'new',
            raw_json TEXT,
            fetched_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (local_reference_id) REFERENCES ref_literatures(reference_id)
        );

-- table: epmc_preprints
CREATE TABLE epmc_preprints (
            preprint_id INTEGER PRIMARY KEY AUTOINCREMENT,
            epmc_id INTEGER,
            title TEXT,
            authors TEXT,
            source TEXT,
            doi TEXT,
            posted_date TEXT,
            abstract TEXT,
            server TEXT,
            pmid TEXT,
            local_virus_names TEXT,
            raw_json TEXT,
            fetched_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (epmc_id) REFERENCES epmc_literature(epmc_id)
        );

-- table: evidence_records
CREATE TABLE "evidence_records" (
            evidence_id INTEGER PRIMARY KEY AUTOINCREMENT,
            evidence_type TEXT NOT NULL CHECK (
                evidence_type IN (
                    'host_range',
                    'natural_infection',
                    'experimental_infection',
                    'outbreak',
                    'mortality',
                    'symptom',
                    'temperature',
                    'diagnosis',
                    'transmission',
                    'virulence',
                    'pathogenicity',
                    'other'
                )
            ),
            virus_master_id INTEGER,
            host_id INTEGER,
            isolate_id INTEGER,
            reference_id INTEGER,
            source_id INTEGER,
            claim TEXT NOT NULL,
            value_text TEXT,
            value_numeric_min REAL,
            value_numeric_max REAL,
            unit TEXT,
            context TEXT,
            observation_type TEXT CHECK (
                observation_type IS NULL OR observation_type IN (
                    'field',
                    'lab',
                    'database_annotation',
                    'review',
                    'expert_curation',
                    'unknown'
                )
            ),
            evidence_strength TEXT DEFAULT 'medium' CHECK (
                evidence_strength IN ('high', 'medium', 'low', 'unknown')
            ),
            source_pmid TEXT,
            source_doi TEXT,
            extraction_method TEXT DEFAULT 'manual_or_seeded',
            curation_status TEXT DEFAULT 'needs_review' CHECK (
                curation_status IN ('needs_review', 'auto_imported', 'manual_checked', 'rejected')
            ),
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            notes TEXT,
            FOREIGN KEY (virus_master_id) REFERENCES virus_master(master_id),
            FOREIGN KEY (host_id) REFERENCES crustacean_hosts(host_id),
            FOREIGN KEY (isolate_id) REFERENCES viral_isolates(isolate_id),
            FOREIGN KEY (reference_id) REFERENCES ref_literatures(reference_id),
            FOREIGN KEY (source_id) REFERENCES external_sources(source_id)
        );

-- table: evidence_review_priority_queue
CREATE TABLE evidence_review_priority_queue (
                    queue_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    evidence_id INTEGER NOT NULL UNIQUE,
                    evidence_type TEXT NOT NULL,
                    virus_master_id INTEGER,
                    canonical_name TEXT,
                    priority TEXT NOT NULL,
                    priority_score INTEGER NOT NULL,
                    reason TEXT NOT NULL,
                    queue_status TEXT NOT NULL DEFAULT 'open',
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (evidence_id) REFERENCES evidence_records(evidence_id),
                    FOREIGN KEY (virus_master_id) REFERENCES virus_master(master_id)
                );

-- table: external_curation_queries
CREATE TABLE external_curation_queries (
            query_id INTEGER PRIMARY KEY AUTOINCREMENT,
            isolate_id INTEGER NOT NULL,
            accession TEXT NOT NULL,
            priority_band TEXT NOT NULL,
            priority_score INTEGER NOT NULL,
            canonical_virus_name TEXT,
            field_name TEXT NOT NULL,
            query_target TEXT NOT NULL CHECK (
                query_target IN ('pubmed', 'crossref', 'scholar', 'genbank', 'literature_manual')
            ),
            query_text TEXT NOT NULL,
            genbank_title TEXT,
            genbank_journal TEXT,
            genbank_authors TEXT,
            query_status TEXT NOT NULL DEFAULT 'open' CHECK (
                query_status IN ('open', 'searched_no_hit', 'candidate_found', 'resolved', 'ignored')
            ),
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            notes TEXT,
            FOREIGN KEY (isolate_id) REFERENCES viral_isolates(isolate_id)
        );

-- table: external_sources
CREATE TABLE external_sources (
            source_id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_key TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            category TEXT NOT NULL,
            base_url TEXT,
            description TEXT,
            update_policy TEXT,
            priority INTEGER DEFAULT 100,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

-- table: external_xrefs
CREATE TABLE external_xrefs (
            xref_id INTEGER PRIMARY KEY AUTOINCREMENT,
            entity_type TEXT NOT NULL CHECK (
                entity_type IN (
                    'virus_master',
                    'viral_isolate',
                    'host',
                    'reference',
                    'protein',
                    'evidence'
                )
            ),
            entity_id INTEGER NOT NULL,
            source_id INTEGER NOT NULL,
            external_id TEXT NOT NULL,
            external_url TEXT,
            match_status TEXT NOT NULL DEFAULT 'unverified' CHECK (
                match_status IN ('exact', 'fuzzy', 'inferred', 'manual_checked', 'unverified', 'rejected')
            ),
            confidence TEXT DEFAULT 'medium' CHECK (
                confidence IN ('high', 'medium', 'low', 'unknown')
            ),
            matched_by TEXT DEFAULT 'script',
            matched_at TEXT DEFAULT CURRENT_TIMESTAMP,
            notes TEXT,
            FOREIGN KEY (source_id) REFERENCES external_sources(source_id),
            UNIQUE (entity_type, entity_id, source_id, external_id)
        );

-- table: field_completeness_snapshots
CREATE TABLE field_completeness_snapshots (
            snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_ts TEXT,
            metric TEXT,
            numerator INTEGER,
            denominator INTEGER,
            pct REAL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

-- table: gbif_occurrences
CREATE TABLE gbif_occurrences (
            occurrence_id INTEGER PRIMARY KEY AUTOINCREMENT,
            host_id INTEGER,
            scientific_name TEXT NOT NULL,
            gbif_taxon_key INTEGER,
            country TEXT,
            continent TEXT,
            decimal_latitude REAL,
            decimal_longitude REAL,
            locality TEXT,
            year INTEGER,
            basis_of_record TEXT,
            dataset_name TEXT,
            occurrence_count INTEGER DEFAULT 1,
            fetched_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (host_id) REFERENCES crustacean_hosts(host_id)
        );

-- table: gbif_species_summary
CREATE TABLE gbif_species_summary (
            summary_id INTEGER PRIMARY KEY AUTOINCREMENT,
            host_id INTEGER,
            scientific_name TEXT NOT NULL,
            gbif_taxon_key INTEGER,
            total_occurrences INTEGER,
            num_countries INTEGER,
            min_lat REAL,
            max_lat REAL,
            min_lon REAL,
            max_lon REAL,
            countries_json TEXT,
            first_record_year INTEGER,
            last_record_year INTEGER,
            fetched_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (host_id) REFERENCES crustacean_hosts(host_id)
        );

-- table: genbank_recovery_candidates
CREATE TABLE genbank_recovery_candidates (
            candidate_id INTEGER PRIMARY KEY AUTOINCREMENT,
            isolate_id INTEGER NOT NULL,
            accession TEXT NOT NULL,
            priority_band TEXT,
            canonical_virus_name TEXT,
            field_name TEXT NOT NULL,
            candidate_value TEXT NOT NULL,
            source TEXT NOT NULL DEFAULT 'genbank_raw',
            matched_entity_type TEXT,
            matched_entity_id INTEGER,
            match_status TEXT NOT NULL CHECK (
                match_status IN (
                    'exact',
                    'alias_exact',
                    'multiple_reference_pmids',
                    'no_local_reference',
                    'unresolved',
                    'ambiguous',
                    'applied',
                    'not_applicable'
                )
            ),
            confidence TEXT NOT NULL CHECK (
                confidence IN ('high', 'medium', 'low', 'unknown')
            ),
            applied INTEGER NOT NULL DEFAULT 0 CHECK (applied IN (0, 1)),
            raw_context TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            notes TEXT,
            FOREIGN KEY (isolate_id) REFERENCES viral_isolates(isolate_id)
        );

-- table: genome_pairwise_identity
CREATE TABLE genome_pairwise_identity (
        identity_id INTEGER PRIMARY KEY AUTOINCREMENT,
        accession_a VARCHAR(50) NOT NULL,
        accession_b VARCHAR(50) NOT NULL,
        virus_species VARCHAR(200),
        identity_percent REAL,
        shared_kmers INTEGER,
        total_unique_kmers INTEGER,
        method TEXT DEFAULT 'kmer_jaccard_k11',
        UNIQUE(accession_a, accession_b)
    );

-- table: genome_synteny_blocks
CREATE TABLE genome_synteny_blocks (
        block_id INTEGER PRIMARY KEY AUTOINCREMENT,
        accession_a VARCHAR(50) NOT NULL,
        accession_b VARCHAR(50) NOT NULL,
        virus_species VARCHAR(200),
        start_a INTEGER,
        end_a INTEGER,
        start_b INTEGER,
        end_b INTEGER,
        strand INTEGER DEFAULT 1,
        block_length INTEGER,
        anchor_kmers INTEGER,
        method TEXT DEFAULT 'kmer_anchor_k15',
        UNIQUE(accession_a, accession_b, start_a, start_b)
    );

-- table: geo_datasets
CREATE TABLE geo_datasets (
            geo_id INTEGER PRIMARY KEY AUTOINCREMENT,
            gse_accession TEXT NOT NULL UNIQUE,
            title TEXT,
            summary TEXT,
            organism TEXT,
            experiment_type TEXT,
            platform TEXT,
            sample_count INTEGER,
            pubmed_ids TEXT,
            submission_date TEXT,
            gds_type TEXT,
            virus_species_matched TEXT,
            host_species_matched TEXT,
            raw_json TEXT,
            fetched_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

-- table: geo_virus_links
CREATE TABLE geo_virus_links (
            link_id INTEGER PRIMARY KEY AUTOINCREMENT,
            geo_dataset_id INTEGER,
            sra_run_id INTEGER,
            local_isolate_id INTEGER,
            virus_name TEXT,
            match_type TEXT DEFAULT 'name_fuzzy',
            match_confidence TEXT DEFAULT 'medium',
            notes TEXT,
            FOREIGN KEY (geo_dataset_id) REFERENCES geo_datasets(geo_id),
            FOREIGN KEY (sra_run_id) REFERENCES sra_runs(sra_id),
            FOREIGN KEY (local_isolate_id) REFERENCES viral_isolates(isolate_id)
        );

-- table: geography_quality_profiles
CREATE TABLE geography_quality_profiles (
            geo_profile_id INTEGER PRIMARY KEY AUTOINCREMENT,
            isolate_id INTEGER NOT NULL UNIQUE,
            collection_id INTEGER,
            raw_country TEXT,
            standardized_country TEXT,
            continent TEXT,
            province_state TEXT,
            city TEXT,
            specific_site TEXT,
            latitude REAL,
            longitude REAL,
            location_precision TEXT,
            coordinate_quality TEXT NOT NULL CHECK (
                coordinate_quality IN ('exact_or_reported', 'centroid_or_inferred', 'missing', 'invalid')
            ),
            location_completeness_score INTEGER NOT NULL,
            missing_components TEXT,
            needs_geocoding INTEGER NOT NULL CHECK (needs_geocoding IN (0, 1)),
            curation_status TEXT NOT NULL DEFAULT 'auto_seeded' CHECK (
                curation_status IN ('auto_seeded', 'needs_review', 'manual_checked', 'rejected')
            ),
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            notes TEXT,
            FOREIGN KEY (isolate_id) REFERENCES viral_isolates(isolate_id),
            FOREIGN KEY (collection_id) REFERENCES sample_collections(collection_id)
        );

-- table: host_aliases
CREATE TABLE host_aliases (
            alias_id INTEGER PRIMARY KEY AUTOINCREMENT,
            host_id INTEGER NOT NULL,
            alias TEXT NOT NULL,
            alias_type TEXT NOT NULL DEFAULT 'synonym' CHECK (
                alias_type IN ('scientific_name', 'common_name_cn', 'synonym', 'historical_name', 'raw_name', 'manual_alias')
            ),
            source_id INTEGER,
            external_id TEXT,
            match_status TEXT NOT NULL DEFAULT 'unverified' CHECK (
                match_status IN ('exact', 'fuzzy', 'inferred', 'manual_checked', 'unverified', 'rejected')
            ),
            confidence TEXT DEFAULT 'medium' CHECK (
                confidence IN ('high', 'medium', 'low', 'unknown')
            ),
            is_preferred INTEGER DEFAULT 0 CHECK (is_preferred IN (0, 1)),
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            notes TEXT,
            FOREIGN KEY (host_id) REFERENCES crustacean_hosts(host_id),
            FOREIGN KEY (source_id) REFERENCES external_sources(source_id),
            UNIQUE (host_id, alias)
        );

-- table: host_biology_profiles
CREATE TABLE host_biology_profiles (
            profile_id INTEGER PRIMARY KEY AUTOINCREMENT,
            host_id INTEGER UNIQUE,
            scientific_name TEXT NOT NULL,
            habitat_type TEXT,
            depth_range_min REAL,
            depth_range_max REAL,
            temperature_tolerance_min REAL,
            temperature_tolerance_max REAL,
            salinity_tolerance TEXT,
            max_body_length_cm REAL,
            trophic_level REAL,
            feeding_type TEXT,
            generation_time_days INTEGER,
            longevity_days INTEGER,
            fecundity_min INTEGER,
            fecundity_max INTEGER,
            aquaculture_production_tonnes REAL,
            commercial_importance TEXT,
            data_sources_json TEXT,
            fetched_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (host_id) REFERENCES crustacean_hosts(host_id)
        );

-- table: host_ecological_traits
CREATE TABLE host_ecological_traits (
            trait_id INTEGER PRIMARY KEY AUTOINCREMENT,
            host_id INTEGER,
            scientific_name TEXT NOT NULL,
            source TEXT DEFAULT 'EOL',
            trait_name TEXT,
            trait_value TEXT,
            units TEXT,
            measurement_method TEXT,
            confidence TEXT DEFAULT 'medium',
            fetched_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (host_id) REFERENCES crustacean_hosts(host_id)
        );

-- table: host_genome_artifacts
CREATE TABLE host_genome_artifacts(
  isolate_id INT,
  accession TEXT,
  virus_name TEXT,
  taxon_family TEXT,
  taxon_genus TEXT,
  taxon_species TEXT,
  genome_accession TEXT,
  genome_length INT,
  gc_content REAL,
  genome_type TEXT,
  keywords TEXT,
  reference_id INT,
  sequence_length INT,
  molecule_type TEXT,
  has_sequence INT,
  master_id INT,
  completeness TEXT,
  raw_record_name TEXT,
  raw_completeness TEXT,
  sequence_scope_status TEXT,
  sequence_scope_note TEXT
);

-- table: host_range_evidence
CREATE TABLE host_range_evidence (
            host_range_id INTEGER PRIMARY KEY AUTOINCREMENT,
            virus_master_id INTEGER NOT NULL,
            host_id INTEGER NOT NULL,
            evidence_category TEXT NOT NULL CHECK (
                evidence_category IN (
                    'observed_isolate',
                    'natural_infection',
                    'experimental_infection',
                    'database_annotation',
                    'literature_review',
                    'expert_curation'
                )
            ),
            isolate_count INTEGER DEFAULT 0,
            representative_isolate_id INTEGER,
            reference_id INTEGER,
            host_life_stage TEXT,
            tissue_or_sample TEXT,
            geography_summary TEXT,
            first_observed_year TEXT,
            last_observed_year TEXT,
            evidence_strength TEXT DEFAULT 'medium' CHECK (
                evidence_strength IN ('high', 'medium', 'low', 'unknown')
            ),
            curation_status TEXT DEFAULT 'auto_seeded' CHECK (
                curation_status IN ('auto_seeded', 'needs_review', 'manual_checked', 'rejected')
            ),
            notes TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (virus_master_id) REFERENCES virus_master(master_id),
            FOREIGN KEY (host_id) REFERENCES crustacean_hosts(host_id),
            FOREIGN KEY (representative_isolate_id) REFERENCES viral_isolates(isolate_id),
            FOREIGN KEY (reference_id) REFERENCES ref_literatures(reference_id),
            UNIQUE (virus_master_id, host_id, evidence_category)
        );

-- table: host_review_candidates
CREATE TABLE host_review_candidates (
            candidate_id INTEGER PRIMARY KEY AUTOINCREMENT,
            host_id INTEGER NOT NULL,
            issue_type TEXT NOT NULL CHECK (
                issue_type IN (
                    'missing_taxonomy',
                    'non_target_host',
                    'likely_duplicate',
                    'accepted_name_differs',
                    'ambiguous_group',
                    'not_found_in_cache'
                )
            ),
            suggested_host_id INTEGER,
            suggested_name TEXT,
            evidence TEXT,
            confidence TEXT NOT NULL DEFAULT 'medium' CHECK (
                confidence IN ('high', 'medium', 'low', 'unknown')
            ),
            status TEXT NOT NULL DEFAULT 'open' CHECK (
                status IN ('open', 'accepted', 'rejected', 'manual_checked')
            ),
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            notes TEXT,
            FOREIGN KEY (host_id) REFERENCES crustacean_hosts(host_id),
            FOREIGN KEY (suggested_host_id) REFERENCES crustacean_hosts(host_id)
        );

-- table: host_scope_overrides
CREATE TABLE host_scope_overrides (
            host_id INTEGER PRIMARY KEY,
            scope_status TEXT NOT NULL CHECK (
                scope_status IN ('target', 'non_target', 'technical_host', 'not_species_level', 'unknown')
            ),
            exclude_from_target_stats INTEGER NOT NULL DEFAULT 0 CHECK (exclude_from_target_stats IN (0, 1)),
            reason TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(host_id) REFERENCES crustacean_hosts(host_id)
        );

-- table: host_taxonomy_profiles
CREATE TABLE host_taxonomy_profiles (
            profile_id INTEGER PRIMARY KEY AUTOINCREMENT,
            host_id INTEGER NOT NULL UNIQUE,
            ncbi_taxid TEXT,
            accepted_name TEXT,
            lineage TEXT,
            lineage_superkingdom TEXT,
            lineage_kingdom TEXT,
            lineage_phylum TEXT,
            lineage_class TEXT,
            lineage_order TEXT,
            lineage_family TEXT,
            lineage_genus TEXT,
            is_crustacean INTEGER CHECK (is_crustacean IN (0, 1)),
            is_target_host INTEGER CHECK (is_target_host IN (0, 1)),
            match_status TEXT NOT NULL DEFAULT 'from_cache' CHECK (
                match_status IN ('from_cache', 'manual_checked', 'needs_review', 'not_found')
            ),
            confidence TEXT NOT NULL DEFAULT 'medium' CHECK (
                confidence IN ('high', 'medium', 'low', 'unknown')
            ),
            source_id INTEGER,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            notes TEXT,
            FOREIGN KEY (host_id) REFERENCES crustacean_hosts(host_id),
            FOREIGN KEY (source_id) REFERENCES external_sources(source_id)
        );

-- table: ictv_review_priority_queue
CREATE TABLE ictv_review_priority_queue (
            master_id INTEGER PRIMARY KEY,
            canonical_name TEXT NOT NULL,
            abbreviations TEXT,
            virus_family TEXT,
            virus_genus TEXT,
            isolate_count INTEGER DEFAULT 0,
            priority TEXT NOT NULL,
            reason TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (master_id) REFERENCES virus_master(master_id)
        );

-- table: ictv_taxonomy
CREATE TABLE ictv_taxonomy (
            ictv_id INTEGER PRIMARY KEY AUTOINCREMENT,
            msl_version TEXT NOT NULL,
            release_year TEXT NOT NULL,
            realm TEXT,
            subrealm TEXT,
            kingdom TEXT,
            subkingdom TEXT,
            phylum TEXT,
            subphylum TEXT,
            class TEXT,
            subclass TEXT,
            order_name TEXT,
            suborder TEXT,
            family TEXT,
            subfamily TEXT,
            genus TEXT,
            subgenus TEXT,
            species TEXT NOT NULL,
            virus_names TEXT,
            virus_abbreviations TEXT,
            genome_composition TEXT,
            row_hash TEXT NOT NULL,
            source_file TEXT,
            imported_at TEXT DEFAULT CURRENT_TIMESTAMP, official_ictv_id TEXT,
            UNIQUE (msl_version, row_hash)
        );

-- table: ictv_vmr
CREATE TABLE ictv_vmr (
            vmr_id INTEGER PRIMARY KEY AUTOINCREMENT,
            vmr_version TEXT NOT NULL,
            official_ictv_id TEXT,
            realm TEXT,
            subrealm TEXT,
            kingdom TEXT,
            subkingdom TEXT,
            phylum TEXT,
            subphylum TEXT,
            class TEXT,
            subclass TEXT,
            order_name TEXT,
            suborder TEXT,
            family TEXT,
            subfamily TEXT,
            genus TEXT,
            subgenus TEXT,
            species TEXT,
            exemplar_type TEXT,
            virus_name TEXT,
            virus_abbreviation TEXT,
            virus_isolate TEXT,
            genbank_accession TEXT,
            refseq_accession TEXT,
            genome_composition TEXT,
            host_source TEXT,
            raw_json TEXT,
            row_hash TEXT NOT NULL,
            source_file TEXT,
            imported_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (vmr_version, row_hash)
        );

-- table: infection_records
CREATE TABLE infection_records (
        record_id INTEGER PRIMARY KEY AUTOINCREMENT,
        isolate_id INTEGER NOT NULL,
        host_id INTEGER,
        collection_id INTEGER,
        detection_method VARCHAR(100),
        disease_symptom TEXT,
        mortality_rate VARCHAR(50),
        isolation_source VARCHAR(100),
        reference_id INTEGER,
        FOREIGN KEY (isolate_id) REFERENCES viral_isolates(isolate_id),
        FOREIGN KEY (host_id) REFERENCES crustacean_hosts(host_id),
        FOREIGN KEY (collection_id) REFERENCES sample_collections(collection_id),
        FOREIGN KEY (reference_id) REFERENCES ref_literatures(reference_id)
    );

-- table: interpro_annotations
CREATE TABLE interpro_annotations (
            interpro_anno_id INTEGER PRIMARY KEY AUTOINCREMENT,
            uniprot_id TEXT NOT NULL,
            interpro_id TEXT NOT NULL,
            interpro_name TEXT,
            interpro_type TEXT,
            source_database TEXT,
            start_pos INTEGER,
            end_pos INTEGER,
            score REAL,
            go_terms TEXT,
            pathways TEXT,
            protein_id INTEGER,
            fetched_at TEXT DEFAULT CURRENT_TIMESTAMP, "position_status" TEXT, "publication_use" TEXT,
            FOREIGN KEY (protein_id) REFERENCES viral_proteins(protein_id)
        );

-- table: interpro_api_query_log
CREATE TABLE interpro_api_query_log (
            query_id INTEGER PRIMARY KEY AUTOINCREMENT,
            uniprot_id TEXT NOT NULL,
            protein_id INTEGER,
            status TEXT NOT NULL,
            interpro_count INTEGER DEFAULT 0,
            go_count INTEGER DEFAULT 0,
            message TEXT,
            queried_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(uniprot_id)
        );

-- table: interpro_go_backfill_queue
CREATE TABLE interpro_go_backfill_queue (
            queue_id INTEGER PRIMARY KEY AUTOINCREMENT,
            protein_id INTEGER,
            ncbi_protein_acc TEXT,
            uniprot_id TEXT,
            reason TEXT,
            status TEXT DEFAULT 'pending',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

-- table: interpro_go_terms
CREATE TABLE interpro_go_terms (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        protein_id INTEGER,
        interpro_id TEXT,
        go_id TEXT,
        go_name TEXT,
        go_namespace TEXT,
        evidence_source TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(protein_id, interpro_id, go_id)
    );

-- table: isolate_curated_profiles
CREATE TABLE isolate_curated_profiles (
            profile_id INTEGER PRIMARY KEY AUTOINCREMENT,
            isolate_id INTEGER NOT NULL UNIQUE,
            accession TEXT NOT NULL UNIQUE,
            master_id INTEGER,
            canonical_virus_name TEXT,
            raw_virus_name TEXT,
            isolate_designation TEXT,
            ictv_species TEXT,
            ictv_id TEXT,
            virus_family TEXT,
            virus_genus TEXT,
            genome_type TEXT,
            completeness TEXT,
            sequence_length INTEGER,
            genome_length INTEGER,
            gc_content REAL,
            host_id INTEGER,
            host_scientific_name TEXT,
            host_common_name_cn TEXT,
            host_taxid TEXT,
            host_is_target INTEGER CHECK (host_is_target IN (0, 1)),
            sample_source TEXT,
            collection_id INTEGER,
            specific_site TEXT,
            city TEXT,
            province_state TEXT,
            country TEXT,
            continent TEXT,
            latitude REAL,
            longitude REAL,
            elevation_m REAL,
            collection_year TEXT,
            collection_date TEXT,
            location_precision TEXT CHECK (
                location_precision IS NULL OR location_precision IN (
                    'exact_coordinates',
                    'site',
                    'city',
                    'province_state',
                    'country',
                    'unknown'
                )
            ),
            coordinates_source TEXT,
            primary_reference_id INTEGER,
            genome_reference_id INTEGER,
            discovery_reference_id INTEGER,
            metadata_source_priority TEXT DEFAULT 'genbank_until_literature_checked' CHECK (
                metadata_source_priority IN (
                    'original_reference',
                    'genbank_until_literature_checked',
                    'manual_curated',
                    'mixed_with_conflicts'
                )
            ),
            curation_status TEXT DEFAULT 'needs_review' CHECK (
                curation_status IN ('needs_review', 'auto_seeded', 'manual_checked', 'conflict_open')
            ),
            confidence TEXT DEFAULT 'medium' CHECK (
                confidence IN ('high', 'medium', 'low', 'unknown')
            ),
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            notes TEXT, dataset_tier TEXT DEFAULT 'extended',
            FOREIGN KEY (isolate_id) REFERENCES viral_isolates(isolate_id),
            FOREIGN KEY (master_id) REFERENCES virus_master(master_id),
            FOREIGN KEY (host_id) REFERENCES crustacean_hosts(host_id),
            FOREIGN KEY (collection_id) REFERENCES sample_collections(collection_id),
            FOREIGN KEY (primary_reference_id) REFERENCES ref_literatures(reference_id),
            FOREIGN KEY (genome_reference_id) REFERENCES ref_literatures(reference_id),
            FOREIGN KEY (discovery_reference_id) REFERENCES ref_literatures(reference_id)
        );

-- table: isolate_reference_links
CREATE TABLE isolate_reference_links (
            link_id INTEGER PRIMARY KEY AUTOINCREMENT,
            isolate_id INTEGER NOT NULL,
            reference_id INTEGER NOT NULL,
            link_type TEXT NOT NULL CHECK (
                link_type IN (
                    'genbank_reference',
                    'infection_record_reference',
                    'genome_sequencing',
                    'initial_discovery',
                    'collection_or_isolation',
                    'curation_evidence',
                    'other'
                )
            ),
            source_table TEXT,
            source_field TEXT,
            priority INTEGER DEFAULT 100,
            evidence_status TEXT DEFAULT 'auto_seeded' CHECK (
                evidence_status IN ('auto_seeded', 'manual_checked', 'rejected')
            ),
            notes TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (isolate_id) REFERENCES viral_isolates(isolate_id),
            FOREIGN KEY (reference_id) REFERENCES ref_literatures(reference_id),
            UNIQUE (isolate_id, reference_id, link_type)
        );

-- table: kegg_annotations
CREATE TABLE kegg_annotations (
            kegg_id INTEGER PRIMARY KEY AUTOINCREMENT,
            ncbi_protein_acc TEXT,
            uniprot_id TEXT,
            ec_number TEXT,
            ko_id TEXT,
            ko_name TEXT,
            ko_definition TEXT,
            protein_id INTEGER,
            fetched_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (protein_id) REFERENCES viral_proteins(protein_id)
        );

-- table: kegg_pathways
CREATE TABLE kegg_pathways (
            pathway_id INTEGER PRIMARY KEY AUTOINCREMENT,
            kegg_pathway_id TEXT NOT NULL,
            pathway_name TEXT,
            pathway_description TEXT,
            category TEXT,
            ko_count INTEGER,
            fetched_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

-- table: kegg_protein_pathways
CREATE TABLE kegg_protein_pathways (
            link_id INTEGER PRIMARY KEY AUTOINCREMENT,
            ko_id TEXT NOT NULL,
            kegg_pathway_id TEXT NOT NULL,
            protein_id INTEGER,
            ncbi_protein_acc TEXT,
            UNIQUE(ko_id, kegg_pathway_id, ncbi_protein_acc),
            FOREIGN KEY (protein_id) REFERENCES viral_proteins(protein_id)
        );

-- table: literature_evidence_candidates
CREATE TABLE literature_evidence_candidates (
            candidate_id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_id INTEGER,
            source_key TEXT NOT NULL,
            target_virus TEXT NOT NULL,
            master_id INTEGER,
            reference_id INTEGER,
            title TEXT NOT NULL,
            authors TEXT,
            journal TEXT,
            year TEXT,
            doi TEXT,
            pmid TEXT,
            url TEXT,
            evidence_scope TEXT DEFAULT 'other',
            claim_hint TEXT,
            relevance_score REAL DEFAULT 0,
            abstract TEXT,
            raw_json TEXT,
            curation_status TEXT DEFAULT 'needs_review',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (source_id) REFERENCES external_sources(source_id),
            FOREIGN KEY (master_id) REFERENCES virus_master(master_id),
            FOREIGN KEY (reference_id) REFERENCES ref_literatures(reference_id)
        );

-- table: literature_evidence_import_log
CREATE TABLE literature_evidence_import_log (
            log_id INTEGER PRIMARY KEY AUTOINCREMENT,
            action TEXT NOT NULL,
            details_json TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

-- table: literature_evidence_promotion_log
CREATE TABLE literature_evidence_promotion_log (
            promotion_id INTEGER PRIMARY KEY AUTOINCREMENT,
            target_table TEXT NOT NULL,
            target_id INTEGER NOT NULL,
            reference_id INTEGER NOT NULL,
            score INTEGER NOT NULL,
            reasons_json TEXT NOT NULL,
            previous_reference_id INTEGER,
            applied INTEGER NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

-- table: literature_search_log
CREATE TABLE literature_search_log (
            log_id INTEGER PRIMARY KEY AUTOINCREMENT,
            search_source TEXT NOT NULL,
            search_query TEXT NOT NULL,
            hit_count INTEGER DEFAULT 0,
            top_doi TEXT,
            searched_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

-- table: manual_ictv_bridges
CREATE TABLE manual_ictv_bridges (
            bridge_id INTEGER PRIMARY KEY AUTOINCREMENT,
            master_id INTEGER NOT NULL,
            ictv_id INTEGER NOT NULL,
            canonical_name TEXT NOT NULL,
            ictv_species TEXT NOT NULL,
            reason TEXT NOT NULL,
            curator TEXT DEFAULT 'add_manual_ictv_bridges.py',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (master_id) REFERENCES virus_master(master_id),
            FOREIGN KEY (ictv_id) REFERENCES ictv_taxonomy(ictv_id),
            UNIQUE (master_id, ictv_id)
        );

-- table: manual_review_priority_queue
CREATE TABLE manual_review_priority_queue (
            review_id INTEGER PRIMARY KEY AUTOINCREMENT,
            category TEXT NOT NULL,
            entity_id INTEGER NOT NULL,
            priority TEXT NOT NULL,
            score INTEGER NOT NULL,
            title TEXT,
            current_status TEXT,
            suggested_action TEXT,
            review_reason TEXT,
            source_reference_id INTEGER,
            related_master_id INTEGER,
            related_isolate_id INTEGER,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(category, entity_id)
        );

-- table: model_performance_metrics
CREATE TABLE model_performance_metrics (
    metric_id INTEGER PRIMARY KEY AUTOINCREMENT,
    model_name TEXT NOT NULL,
    target_column TEXT NOT NULL,
    metric_name TEXT NOT NULL CHECK (
        metric_name IN (
            'accuracy', 'precision', 'recall', 'f1', 'auc_roc',
            'mcc', 'r2', 'mae', 'rmse', 'cross_val_mean', 'cross_val_std',
            'balanced_accuracy', 'sensitivity', 'specificity'
        )
    ),
    metric_value REAL NOT NULL,
    cv_folds INTEGER,
    test_set_size INTEGER,
    train_set_size INTEGER,
    feature_count INTEGER,
    hyperparameters TEXT,
    evaluation_timestamp TEXT,
    notes TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- table: nr_protein_clusters
CREATE TABLE nr_protein_clusters (
        cluster_id INTEGER PRIMARY KEY AUTOINCREMENT,
        representative_seq_hash VARCHAR(64) UNIQUE,
        representative_aa_seq TEXT,
        representative_dna_seq TEXT,
        cluster_size INTEGER DEFAULT 1,
        cluster_method TEXT DEFAULT 'exact_match',
        cd_hit_threshold REAL,
        avg_length REAL,
        functional_category VARCHAR(50),
        source_count INTEGER DEFAULT 0,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    , cdhit50_cluster_id INTEGER, cdhit50_is_rep INTEGER DEFAULT 0);

-- table: nucleotide_records
CREATE TABLE nucleotide_records (
            record_id INTEGER PRIMARY KEY AUTOINCREMENT,
            isolate_id INTEGER NOT NULL,
            accession TEXT NOT NULL,
            definition TEXT,
            organism TEXT,
            taxonomy_lineage TEXT,
            genome_length INTEGER,
            topology TEXT,
            molecule_type TEXT,
            strand TEXT,
            cds_count INTEGER DEFAULT 0,
            gene_count INTEGER DEFAULT 0,
            feature_count INTEGER DEFAULT 0,
            taxid INTEGER,
            create_date TEXT,
            update_date TEXT,
            fetched_at TEXT,
            FOREIGN KEY (isolate_id) REFERENCES viral_isolates(isolate_id),
            UNIQUE(isolate_id, accession)
        );

-- table: obis_occurrences
CREATE TABLE obis_occurrences (
            obis_id INTEGER PRIMARY KEY AUTOINCREMENT,
            host_id INTEGER,
            scientific_name TEXT NOT NULL,
            aphia_id INTEGER,
            decimal_latitude REAL,
            decimal_longitude REAL,
            depth_min REAL,
            depth_max REAL,
            temperature REAL,
            salinity REAL,
            country TEXT,
            locality TEXT,
            year_collected INTEGER,
            dataset_name TEXT,
            record_count INTEGER DEFAULT 1,
            fetched_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (host_id) REFERENCES crustacean_hosts(host_id)
        );

-- table: outbreak_events
CREATE TABLE outbreak_events (
            outbreak_id INTEGER PRIMARY KEY AUTOINCREMENT,
            virus_master_id INTEGER NOT NULL,
            host_id INTEGER,
            country TEXT,
            province_state TEXT,
            start_year TEXT,
            end_year TEXT,
            event_summary TEXT NOT NULL,
            economic_impact TEXT,
            mortality_rate_min REAL,
            mortality_rate_max REAL,
            reference_id INTEGER,
            evidence_strength TEXT DEFAULT 'medium' CHECK (
                evidence_strength IN ('high', 'medium', 'low', 'unknown')
            ),
            curation_status TEXT DEFAULT 'needs_review' CHECK (
                curation_status IN ('auto_seeded', 'needs_review', 'manual_checked', 'rejected')
            ),
            notes TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (virus_master_id) REFERENCES virus_master(master_id),
            FOREIGN KEY (host_id) REFERENCES crustacean_hosts(host_id),
            FOREIGN KEY (reference_id) REFERENCES ref_literatures(reference_id)
        );

-- table: pathogenicity_evidence
CREATE TABLE pathogenicity_evidence (
            pathogenicity_id INTEGER PRIMARY KEY AUTOINCREMENT,
            virus_master_id INTEGER NOT NULL,
            host_id INTEGER,
            isolate_id INTEGER,
            reference_id INTEGER,
            virulence_level TEXT,
            virulence_label INTEGER,
            mortality_rate_min REAL,
            mortality_rate_max REAL,
            ld50_value TEXT,
            disease_symptoms TEXT,
            tissue_tropism TEXT,
            pathogenic_mechanism TEXT,
            host_age_susceptibility TEXT,
            observation_type TEXT CHECK (
                observation_type IS NULL OR observation_type IN ('field', 'lab', 'review', 'expert_curation', 'database_annotation')
            ),
            evidence_strength TEXT DEFAULT 'medium' CHECK (
                evidence_strength IN ('high', 'medium', 'low', 'unknown')
            ),
            source_text TEXT,
            curation_status TEXT DEFAULT 'needs_review' CHECK (
                curation_status IN ('auto_seeded', 'needs_review', 'manual_checked', 'rejected')
            ),
            notes TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (virus_master_id) REFERENCES virus_master(master_id),
            FOREIGN KEY (host_id) REFERENCES crustacean_hosts(host_id),
            FOREIGN KEY (isolate_id) REFERENCES viral_isolates(isolate_id),
            FOREIGN KEY (reference_id) REFERENCES ref_literatures(reference_id)
        );

-- table: phi_base_hits
CREATE TABLE phi_base_hits (
            hit_id INTEGER PRIMARY KEY AUTOINCREMENT,
            cluster_id INTEGER NOT NULL,
            phi_accession TEXT NOT NULL,
            phi_id TEXT,
            phi_gene TEXT,
            phi_organism TEXT,
            phi_phenotype TEXT,
            identity REAL,
            alignment_length INTEGER,
            evalue REAL,
            bit_score REAL,
            query_coverage REAL,
            FOREIGN KEY (cluster_id) REFERENCES nr_protein_clusters(cluster_id)
        );

-- table: pride_datasets
CREATE TABLE pride_datasets (
            pride_id INTEGER PRIMARY KEY AUTOINCREMENT,
            pride_accession TEXT NOT NULL UNIQUE,
            px_accession TEXT,
            title TEXT,
            description TEXT,
            organism TEXT,
            instrument TEXT,
            modification TEXT,
            num_proteins INTEGER,
            num_peptides INTEGER,
            num_psms INTEGER,
            publication_pmid TEXT,
            publication_doi TEXT,
            submission_date TEXT,
            data_protocol TEXT,
            sample_protocol TEXT,
            virus_species_matched TEXT,
            host_species_matched TEXT,
            source_repository TEXT DEFAULT 'PRIDE',
            raw_json TEXT,
            fetched_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

-- table: pride_virus_links
CREATE TABLE pride_virus_links (
            link_id INTEGER PRIMARY KEY AUTOINCREMENT,
            pride_dataset_id INTEGER,
            local_protein_id INTEGER,
            local_isolate_id INTEGER,
            virus_name TEXT,
            protein_description TEXT,
            match_type TEXT DEFAULT 'organism_match',
            match_confidence TEXT DEFAULT 'medium',
            FOREIGN KEY (pride_dataset_id) REFERENCES pride_datasets(pride_id),
            FOREIGN KEY (local_protein_id) REFERENCES viral_proteins(protein_id),
            FOREIGN KEY (local_isolate_id) REFERENCES viral_isolates(isolate_id)
        );

-- table: protein_annotation_bridge
CREATE TABLE protein_annotation_bridge (
            bridge_id INTEGER PRIMARY KEY AUTOINCREMENT,
            protein_id INTEGER,
            isolate_id INTEGER,
            protein_accession TEXT,
            accession_root TEXT,
            uniprot_id TEXT,
            annotation_sources TEXT,
            has_uniprot INTEGER DEFAULT 0,
            has_interpro INTEGER DEFAULT 0,
            has_interpro_go INTEGER DEFAULT 0,
            has_kegg INTEGER DEFAULT 0,
            has_structure INTEGER DEFAULT 0,
            has_alphafold INTEGER DEFAULT 0,
            has_pdb INTEGER DEFAULT 0,
            interpro_count INTEGER DEFAULT 0,
            go_count INTEGER DEFAULT 0,
            kegg_ko_count INTEGER DEFAULT 0,
            structure_count INTEGER DEFAULT 0,
            best_structure_confidence REAL,
            match_method TEXT,
            needs_review INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(protein_id, uniprot_id)
        );

-- table: protein_domains
CREATE TABLE protein_domains (
        domain_id INTEGER PRIMARY KEY AUTOINCREMENT,
        cluster_id INTEGER,
        protein_id INTEGER,
        reanno_id INTEGER,
        domain_source TEXT DEFAULT 'rule_based',
        domain_name TEXT,
        domain_description TEXT,
        start_pos INTEGER,
        end_pos INTEGER,
        confidence_score REAL,
        domain_model TEXT,
        interpro_id TEXT,
        pfam_id TEXT,
        cdd_id TEXT,
        FOREIGN KEY (cluster_id) REFERENCES nr_protein_clusters(cluster_id),
        FOREIGN KEY (protein_id) REFERENCES viral_proteins(protein_id),
        FOREIGN KEY (reanno_id) REFERENCES reannotated_orfs(reanno_id)
    );

-- table: protein_function_suggestions
CREATE TABLE protein_function_suggestions (
            suggestion_id INTEGER PRIMARY KEY AUTOINCREMENT,
            protein_id INTEGER NOT NULL,
            suggested_category TEXT NOT NULL,
            suggestion_source TEXT NOT NULL,
            rule_id TEXT NOT NULL,
            evidence_text TEXT,
            confidence_level TEXT NOT NULL DEFAULT 'medium',
            needs_manual_review INTEGER NOT NULL DEFAULT 1,
            curator_decision TEXT,
            curator_notes TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(protein_id, suggested_category, rule_id)
        );

-- table: protein_structures
CREATE TABLE protein_structures (
        structure_id INTEGER PRIMARY KEY AUTOINCREMENT,
        cluster_id INTEGER,
        protein_id INTEGER,
        reanno_id INTEGER,
        prediction_method TEXT DEFAULT 'esmfold',
        model_version TEXT,
        pdb_file_path TEXT,
        plddt_score REAL,
        sequence_length INTEGER,
        prediction_date TEXT DEFAULT CURRENT_TIMESTAMP,
        api_source TEXT DEFAULT 'https://api.esmatlas.com', "plddt_raw" REAL, "plddt_scale" TEXT, "plddt_normalized_100" REAL, "confidence_tier" TEXT, "publication_use" TEXT, "quality_notes" TEXT,
        FOREIGN KEY (cluster_id) REFERENCES nr_protein_clusters(cluster_id),
        FOREIGN KEY (protein_id) REFERENCES viral_proteins(protein_id),
        FOREIGN KEY (reanno_id) REFERENCES reannotated_orfs(reanno_id),
        UNIQUE(cluster_id, prediction_method)
    );

-- table: reannotated_orfs
CREATE TABLE reannotated_orfs (
        reanno_id INTEGER PRIMARY KEY AUTOINCREMENT,
        isolate_id INTEGER NOT NULL,
        orf_number INTEGER NOT NULL,
        locus_tag VARCHAR(20),
        start_pos INTEGER NOT NULL,
        end_pos INTEGER NOT NULL,
        strand INTEGER NOT NULL,
        frame INTEGER NOT NULL,
        aa_length INTEGER NOT NULL,
        dna_sequence TEXT,
        aa_sequence TEXT,
        is_incomplete INTEGER DEFAULT 0,
        note TEXT,
        FOREIGN KEY (isolate_id) REFERENCES viral_isolates(isolate_id)
    );

-- table: reannotation_stats
CREATE TABLE reannotation_stats (
        isolate_id INTEGER PRIMARY KEY,
        original_orf_count INTEGER,
        reannotated_orf_count INTEGER,
        original_coverage_percent REAL,
        reannotated_coverage_percent REAL,
        avg_orf_length REAL,
        FOREIGN KEY (isolate_id) REFERENCES viral_isolates(isolate_id)
    );

-- table: ref_literatures
CREATE TABLE ref_literatures (
        reference_id INTEGER PRIMARY KEY AUTOINCREMENT,
        pmid VARCHAR(20) UNIQUE,
        title TEXT,
        authors TEXT,
        journal TEXT,
        year VARCHAR(10),
        doi VARCHAR(100),
        abstract TEXT,
        keywords TEXT
    );

-- table: release_manifest
CREATE TABLE release_manifest (
            manifest_id INTEGER PRIMARY KEY AUTOINCREMENT,
            release_name TEXT NOT NULL,
            generated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            table_name TEXT NOT NULL,
            row_count INTEGER,
            export_path TEXT,
            notes TEXT
        );

-- table: sample_collections
CREATE TABLE sample_collections (
        collection_id INTEGER PRIMARY KEY AUTOINCREMENT,
        country VARCHAR(100),
        province VARCHAR(100),
        city VARCHAR(100),
        site_name VARCHAR(200),
        latitude REAL,
        longitude REAL,
        collection_year VARCHAR(10),
        collection_date VARCHAR(20),
        source_type VARCHAR(50),
        note TEXT
    , continent VARCHAR(50), coordinate_precision TEXT DEFAULT 'country');

-- table: sample_metadata
CREATE TABLE sample_metadata (
            isolate_id INTEGER PRIMARY KEY,
            accession TEXT NOT NULL,
            host_name TEXT,
            collection_date TEXT,
            isolation_source TEXT,
            geo_loc_name TEXT,
            lat_lon TEXT,
            isolate_name TEXT,
            strain TEXT,
            organism TEXT,
            mol_type TEXT,
            ncbi_taxid INTEGER,
            raw_notes TEXT,
            fetched_at TEXT,
            FOREIGN KEY (isolate_id) REFERENCES viral_isolates(isolate_id)
        );

-- table: schema_deprecated_columns
CREATE TABLE schema_deprecated_columns (
            deprecated_id INTEGER PRIMARY KEY AUTOINCREMENT,
            table_name TEXT NOT NULL,
            column_name TEXT NOT NULL,
            reason TEXT NOT NULL,
            recommended_action TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(table_name, column_name)
        );

-- table: schema_version
CREATE TABLE schema_version (
            version_id    INTEGER PRIMARY KEY AUTOINCREMENT,
            applied_at    TEXT NOT NULL DEFAULT (datetime('now')),
            script_name   TEXT NOT NULL,
            description   TEXT
        );

-- table: sequence_curation_flags
CREATE TABLE sequence_curation_flags (
            flag_id INTEGER PRIMARY KEY AUTOINCREMENT,
            isolate_id INTEGER NOT NULL,
            accession TEXT,
            flag_type TEXT NOT NULL,
            severity TEXT NOT NULL,
            reason TEXT NOT NULL,
            previous_completeness TEXT,
            new_completeness TEXT,
            action_taken TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(isolate_id, flag_type, reason),
            FOREIGN KEY(isolate_id) REFERENCES viral_isolates(isolate_id)
        );

-- table: sra_runs
CREATE TABLE sra_runs (
            sra_id INTEGER PRIMARY KEY AUTOINCREMENT,
            sra_accession TEXT NOT NULL UNIQUE,
            bioproject TEXT,
            biosample TEXT,
            title TEXT,
            organism TEXT,
            library_strategy TEXT,
            library_source TEXT,
            library_layout TEXT,
            platform TEXT,
            total_bases TEXT,
            total_spots TEXT,
            run_date TEXT,
            geo_linked TEXT,
            virus_species_matched TEXT,
            raw_json TEXT,
            fetched_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

-- table: string_interactions
CREATE TABLE string_interactions (
            interaction_id INTEGER PRIMARY KEY AUTOINCREMENT,
            protein_a TEXT NOT NULL,
            protein_b TEXT NOT NULL,
            protein_a_name TEXT,
            protein_b_name TEXT,
            combined_score REAL,
            neighborhood_score REAL,
            fusion_score REAL,
            cooccurrence_score REAL,
            coexpression_score REAL,
            experimental_score REAL,
            database_score REAL,
            textmining_score REAL,
            species_taxid INTEGER,
            source_uniprot_id TEXT,
            local_protein_id INTEGER,
            interaction_type TEXT DEFAULT 'functional',
            fetched_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (local_protein_id) REFERENCES viral_proteins(protein_id)
        );

-- table: submission_manual_intervention_tasks
CREATE TABLE submission_manual_intervention_tasks(
  task_type,
  entity_id INT,
  subtype TEXT,
  priority_hint TEXT,
  summary TEXT,
  reference_id INT,
  virus_master_id INT,
  isolate_id INT
);

-- table: submission_p0_release_blockers
CREATE TABLE submission_p0_release_blockers(
  blocker_type,
  entity_id INT,
  summary
);

-- table: submission_protein_annotation_coverage
CREATE TABLE submission_protein_annotation_coverage(
  protein_id INT,
  isolate_id INT,
  protein_accession TEXT,
  protein_name TEXT,
  functional_category TEXT,
  has_uniprot,
  has_interpro,
  has_go,
  has_kegg,
  has_bridge_structure,
  has_protein_structures_row,
  has_uniprot_structures_row,
  structure_consistency_status
);

-- table: submission_target_geography_precision
CREATE TABLE submission_target_geography_precision(
  isolate_id INT,
  accession TEXT,
  virus_name TEXT,
  master_id INT,
  canonical_name TEXT,
  host_scientific_name,
  country,
  latitude,
  longitude,
  raw_precision,
  map_precision_class,
  default_map_eligible
);

-- table: temperature_profiles
CREATE TABLE temperature_profiles (
        profile_id INTEGER PRIMARY KEY AUTOINCREMENT,
        virus_name VARCHAR(200) NOT NULL UNIQUE,
        optimal_temp_min REAL,               -- Optimal temperature range min (°C)
        optimal_temp_max REAL,               -- Optimal temperature range max (°C)
        temp_range_min REAL,                 -- Survival temperature minimum (°C)
        temp_range_max REAL,                 -- Survival temperature maximum (°C)
        thermal_inactivation_temp REAL,      -- Temperature for thermal inactivation (°C)
        thermal_inactivation_time REAL,      -- Time for thermal inactivation (min)
        cold_storage_temp REAL,              -- Recommended cold storage temp (°C)
        cold_storage_viability VARCHAR(200), -- Viability under cold storage
        temp_sensitivity_notes TEXT,         -- Notes on temperature sensitivity
        climate_change_impact TEXT,          -- Projected impact of climate change
        data_source VARCHAR(500),            -- Literature source
        confidence VARCHAR(20),              -- 'High', 'Medium', 'Low'
        curation_date DATE,
        notes TEXT
    , "data_origin" TEXT, "data_source_type" TEXT, "publication_use" TEXT);

-- table: uniprot_annotations
CREATE TABLE uniprot_annotations (
            annotation_id INTEGER PRIMARY KEY AUTOINCREMENT,
            ncbi_protein_acc TEXT NOT NULL,
            uniprot_id TEXT,
            protein_name TEXT,
            gene_name TEXT,
            ec_numbers TEXT,
            go_terms TEXT,
            keywords TEXT,
            organism TEXT,
            protein_length INTEGER,
            functional_category TEXT,
            fetched_at TEXT,
            UNIQUE(ncbi_protein_acc)
        );

-- table: uniprot_protein_links
CREATE TABLE uniprot_protein_links (
        link_id INTEGER PRIMARY KEY AUTOINCREMENT,
        uniprot_id TEXT NOT NULL,
        ncbi_protein_acc TEXT,
        protein_id INTEGER,
        match_type TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(uniprot_id, ncbi_protein_acc, protein_id),
        FOREIGN KEY (protein_id) REFERENCES viral_proteins(protein_id)
    );

-- table: uniprot_structures
CREATE TABLE uniprot_structures (
            struct_id INTEGER PRIMARY KEY AUTOINCREMENT,
            uniprot_id TEXT NOT NULL,
            source TEXT NOT NULL CHECK (source IN ('alphafold', 'pdb')),
            entry_id TEXT NOT NULL,
            confidence REAL,
            sequence_length INTEGER,
            pdb_url TEXT,
            gene TEXT,
            protein_description TEXT,
            organism TEXT,
            fetched_at TEXT
        , protein_id INTEGER REFERENCES viral_proteins(protein_id), local_pdb_path TEXT);

-- table: viral_isolates
CREATE TABLE viral_isolates (
        isolate_id INTEGER PRIMARY KEY AUTOINCREMENT,
        accession VARCHAR(50) UNIQUE NOT NULL,
        virus_name VARCHAR(200),
        taxon_family VARCHAR(100),
        taxon_genus VARCHAR(100),
        taxon_species VARCHAR(100),
        genome_accession VARCHAR(50),
        genome_length INTEGER,
        gc_content REAL,
        genome_type VARCHAR(50),
        keywords TEXT,
        reference_id INTEGER, sequence_length INTEGER, molecule_type VARCHAR(20), has_sequence INTEGER DEFAULT 0, master_id INTEGER, completeness VARCHAR(50), "raw_record_name" TEXT, "raw_completeness" TEXT, "sequence_scope_status" TEXT, "sequence_scope_note" TEXT,
        FOREIGN KEY (reference_id) REFERENCES ref_literatures(reference_id)
    );

-- table: viral_proteins
CREATE TABLE viral_proteins (
        protein_id INTEGER PRIMARY KEY AUTOINCREMENT,
        isolate_id INTEGER NOT NULL,
        protein_accession VARCHAR(50),
        protein_name VARCHAR(500),
        gene_symbol VARCHAR(100),
        locus_tag VARCHAR(100),
        aa_length INTEGER,
        genome_start INTEGER,
        genome_end INTEGER,
        translation TEXT,
        ec_number VARCHAR(50),
        note TEXT,
        functional_category VARCHAR(50) DEFAULT 'unknown', is_rdrp INTEGER DEFAULT 0, "functional_annotation_status" TEXT DEFAULT 'unannotated', "functional_category_source" TEXT,
        FOREIGN KEY (isolate_id) REFERENCES viral_isolates(isolate_id)
    );

-- table: viral_proteins_nr
CREATE TABLE viral_proteins_nr (
        mapping_id INTEGER PRIMARY KEY AUTOINCREMENT,
        protein_id INTEGER,
        reanno_id INTEGER,
        cluster_id INTEGER NOT NULL,
        identity_to_rep REAL DEFAULT 100.0,
        alignment_length INTEGER,
        FOREIGN KEY (protein_id) REFERENCES viral_proteins(protein_id),
        FOREIGN KEY (reanno_id) REFERENCES reannotated_orfs(reanno_id),
        FOREIGN KEY (cluster_id) REFERENCES nr_protein_clusters(cluster_id)
    );

-- table: viralzone_families
CREATE TABLE viralzone_families (
            family_id INTEGER PRIMARY KEY AUTOINCREMENT,
            family_name TEXT NOT NULL UNIQUE,
            virion_description TEXT,
            genome_description TEXT,
            genome_type TEXT,
            genome_size_range TEXT,
            replication_cycle TEXT,
            host_range TEXT,
            transmission TEXT,
            taxonomy_lineage TEXT,
            genera_list TEXT,
            reference_strains TEXT,
            viralzone_url TEXT,
            raw_json TEXT,
            fetched_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

-- table: viralzone_gene_tables
CREATE TABLE viralzone_gene_tables (
            gene_entry_id INTEGER PRIMARY KEY AUTOINCREMENT,
            family_id INTEGER NOT NULL,
            gene_name TEXT,
            protein_name TEXT,
            function_description TEXT,
            position TEXT,
            notes TEXT,
            FOREIGN KEY (family_id) REFERENCES viralzone_families(family_id)
        );

-- table: virulence_profiles
CREATE TABLE virulence_profiles (
        profile_id INTEGER PRIMARY KEY AUTOINCREMENT,
        virus_name VARCHAR(200) NOT NULL UNIQUE,
        virulence_level VARCHAR(50),        -- 'High', 'Moderate', 'Low', 'Non-pathogenic'
        virulence_label INTEGER,             -- 1=High pathogenic, 0=Low/Non-pathogenic (guide convention)
        mortality_rate_min REAL,             -- Minimum mortality rate (%)
        mortality_rate_max REAL,             -- Maximum mortality rate (%)
        ld50_value VARCHAR(100),             -- LD50 value with unit
        pathogenic_mechanism TEXT,           -- Brief description of pathogenic mechanism
        outbreak_record TEXT,                -- Major outbreak records
        host_age_susceptibility VARCHAR(200),-- Which life stages are most susceptible
        data_source VARCHAR(500),            -- Literature or expert curation source
        confidence VARCHAR(20),              -- 'High', 'Medium', 'Low'
        curation_date DATE,
        notes TEXT
    , "data_origin" TEXT, "data_source_type" TEXT, "publication_use" TEXT, "mortality_rate_min_raw" REAL, "mortality_rate_max_raw" REAL, "mortality_rate_unit" TEXT, "mortality_normalization_note" TEXT);

-- table: virus_aliases
CREATE TABLE virus_aliases (
            alias_id INTEGER PRIMARY KEY AUTOINCREMENT,
            master_id INTEGER NOT NULL,
            alias TEXT NOT NULL,
            alias_type TEXT NOT NULL DEFAULT 'synonym' CHECK (
                alias_type IN ('canonical', 'abbreviation', 'synonym', 'historical_name', 'raw_name', 'manual_alias')
            ),
            source_id INTEGER,
            external_id TEXT,
            match_status TEXT NOT NULL DEFAULT 'unverified' CHECK (
                match_status IN ('exact', 'fuzzy', 'inferred', 'manual_checked', 'unverified', 'rejected')
            ),
            confidence TEXT DEFAULT 'medium' CHECK (
                confidence IN ('high', 'medium', 'low', 'unknown')
            ),
            is_preferred INTEGER DEFAULT 0 CHECK (is_preferred IN (0, 1)),
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            notes TEXT,
            FOREIGN KEY (master_id) REFERENCES virus_master(master_id),
            FOREIGN KEY (source_id) REFERENCES external_sources(source_id),
            UNIQUE (master_id, alias)
        );

-- table: virus_ictv_mappings
CREATE TABLE virus_ictv_mappings (
            mapping_id INTEGER PRIMARY KEY AUTOINCREMENT,
            master_id INTEGER NOT NULL,
            ictv_id INTEGER NOT NULL,
            match_type TEXT NOT NULL CHECK (
                match_type IN ('species_exact', 'virus_name_exact', 'abbreviation_exact', 'raw_name_exact', 'normalized_exact')
            ),
            matched_value TEXT NOT NULL,
            match_status TEXT NOT NULL DEFAULT 'auto_matched' CHECK (
                match_status IN ('auto_matched', 'manual_checked', 'rejected')
            ),
            confidence TEXT NOT NULL DEFAULT 'high' CHECK (
                confidence IN ('high', 'medium', 'low', 'unknown')
            ),
            source_id INTEGER,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            notes TEXT,
            FOREIGN KEY (master_id) REFERENCES virus_master(master_id),
            FOREIGN KEY (ictv_id) REFERENCES ictv_taxonomy(ictv_id),
            FOREIGN KEY (source_id) REFERENCES external_sources(source_id),
            UNIQUE (master_id, ictv_id, match_type, matched_value)
        );

-- table: virus_ictv_status
CREATE TABLE virus_ictv_status (
            master_id INTEGER PRIMARY KEY,
            ictv_status TEXT NOT NULL CHECK (
                ictv_status IN ('mapped', 'rejected', 'non_target', 'unclassified_not_expected', 'pending_review')
            ),
            mapping_count INTEGER DEFAULT 0,
            best_confidence TEXT,
            reason TEXT,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(master_id) REFERENCES virus_master(master_id)
        );

-- table: virus_master
CREATE TABLE virus_master (
            master_id INTEGER PRIMARY KEY AUTOINCREMENT,
            canonical_name VARCHAR(200) NOT NULL UNIQUE,
            abbreviations TEXT,
            chinese_name VARCHAR(200),
            virus_family VARCHAR(100),
            virus_genus VARCHAR(100),
            genome_type VARCHAR(50),
            is_crustacean_virus INTEGER DEFAULT 1,
            entry_type VARCHAR(50) DEFAULT 'complete_genome',
            notes TEXT
        );

-- table: virus_master_review_queue
CREATE TABLE virus_master_review_queue (
            master_id INTEGER PRIMARY KEY,
            canonical_name TEXT NOT NULL,
            issue_type TEXT NOT NULL,
            severity TEXT NOT NULL,
            reason TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (master_id) REFERENCES virus_master(master_id)
        );

-- table: virus_name_scope_review
CREATE TABLE virus_name_scope_review (
            review_id INTEGER PRIMARY KEY AUTOINCREMENT,
            isolate_id INTEGER NOT NULL UNIQUE,
            accession TEXT,
            reported_virus_name TEXT,
            linked_master_id INTEGER,
            linked_canonical_name TEXT,
            master_entry_type TEXT,
            master_is_crustacean_virus INTEGER,
            review_reason TEXT NOT NULL,
            suggested_action TEXT NOT NULL,
            curator_decision TEXT,
            curator_notes TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

-- table: virus_search_fts
CREATE VIRTUAL TABLE virus_search_fts USING fts5(
            accession,
            virus_name,
            canonical_name,
            abbreviations,
            chinese_name,
            taxon_family,
            taxon_genus,
            host_name,
            host_cn,
            country,
            tokenize = 'unicode61'
        );

-- table: virus_search_fts_config
CREATE TABLE 'virus_search_fts_config'(k PRIMARY KEY, v) WITHOUT ROWID;

-- table: virus_search_fts_content
CREATE TABLE 'virus_search_fts_content'(id INTEGER PRIMARY KEY, c0, c1, c2, c3, c4, c5, c6, c7, c8, c9);

-- table: virus_search_fts_data
CREATE TABLE 'virus_search_fts_data'(id INTEGER PRIMARY KEY, block BLOB);

-- table: virus_search_fts_docsize
CREATE TABLE 'virus_search_fts_docsize'(id INTEGER PRIMARY KEY, sz BLOB);

-- table: virus_search_fts_idx
CREATE TABLE 'virus_search_fts_idx'(segid, term, pgno, PRIMARY KEY(segid, term)) WITHOUT ROWID;

-- table: virus_vmr_mappings
CREATE TABLE virus_vmr_mappings (
            mapping_id INTEGER PRIMARY KEY AUTOINCREMENT,
            master_id INTEGER NOT NULL,
            vmr_id INTEGER NOT NULL,
            ictv_id INTEGER,
            match_type TEXT NOT NULL CHECK (
                match_type IN (
                    'accession_exact',
                    'accession_base_exact',
                    'virus_name_exact',
                    'abbreviation_exact',
                    'species_exact',
                    'manual_alias'
                )
            ),
            matched_value TEXT NOT NULL,
            match_status TEXT NOT NULL DEFAULT 'auto_matched' CHECK (
                match_status IN ('auto_matched', 'manual_checked', 'rejected')
            ),
            confidence TEXT NOT NULL DEFAULT 'high' CHECK (
                confidence IN ('high', 'medium', 'low', 'unknown')
            ),
            source_id INTEGER,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            notes TEXT,
            FOREIGN KEY (master_id) REFERENCES virus_master(master_id),
            FOREIGN KEY (vmr_id) REFERENCES ictv_vmr(vmr_id),
            FOREIGN KEY (ictv_id) REFERENCES ictv_taxonomy(ictv_id),
            FOREIGN KEY (source_id) REFERENCES external_sources(source_id),
            UNIQUE (master_id, vmr_id, match_type, matched_value)
        );

-- table: worms_search_log
CREATE TABLE worms_search_log (
            log_id INTEGER PRIMARY KEY AUTOINCREMENT,
            host_id INTEGER NOT NULL,
            search_name TEXT NOT NULL,
            aphia_id INTEGER,
            match_type TEXT,
            found_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

-- index: idx_auto_biosample_links_isolate
CREATE INDEX "idx_auto_biosample_links_isolate" ON "biosample_links" ("isolate_id");

-- index: idx_auto_control_reference
CREATE INDEX "idx_auto_control_reference" ON "control_management_methods" ("reference_id");

-- index: idx_auto_diagnostic_reference
CREATE INDEX "idx_auto_diagnostic_reference" ON "diagnostic_methods" ("reference_id");

-- index: idx_auto_fills_entity
CREATE INDEX idx_auto_fills_entity
            ON auto_completeness_fills(entity_type, entity_id);

-- index: idx_auto_fills_field
CREATE INDEX idx_auto_fills_field
            ON auto_completeness_fills(field_name, confidence);

-- index: idx_auto_icp_accession
CREATE INDEX "idx_auto_icp_accession" ON "isolate_curated_profiles" ("accession");

-- index: idx_auto_icp_host_name
CREATE INDEX "idx_auto_icp_host_name" ON "isolate_curated_profiles" ("host_scientific_name");

-- index: idx_auto_kegg_protein_pathways_protein
CREATE INDEX "idx_auto_kegg_protein_pathways_protein" ON "kegg_protein_pathways" ("protein_id");

-- index: idx_auto_outbreak_host
CREATE INDEX "idx_auto_outbreak_host" ON "outbreak_events" ("host_id");

-- index: idx_auto_outbreak_reference
CREATE INDEX "idx_auto_outbreak_reference" ON "outbreak_events" ("reference_id");

-- index: idx_auto_pathogenicity_host
CREATE INDEX "idx_auto_pathogenicity_host" ON "pathogenicity_evidence" ("host_id");

-- index: idx_auto_pathogenicity_isolate
CREATE INDEX "idx_auto_pathogenicity_isolate" ON "pathogenicity_evidence" ("isolate_id");

-- index: idx_auto_pathogenicity_reference
CREATE INDEX "idx_auto_pathogenicity_reference" ON "pathogenicity_evidence" ("reference_id");

-- index: idx_auto_protein_domains_cluster
CREATE INDEX "idx_auto_protein_domains_cluster" ON "protein_domains" ("cluster_id");

-- index: idx_auto_protein_domains_protein
CREATE INDEX "idx_auto_protein_domains_protein" ON "protein_domains" ("protein_id");

-- index: idx_auto_protein_domains_reanno
CREATE INDEX "idx_auto_protein_domains_reanno" ON "protein_domains" ("reanno_id");

-- index: idx_auto_protein_structures_protein
CREATE INDEX "idx_auto_protein_structures_protein" ON "protein_structures" ("protein_id");

-- index: idx_auto_protein_structures_reanno
CREATE INDEX "idx_auto_protein_structures_reanno" ON "protein_structures" ("reanno_id");

-- index: idx_auto_reannotation_stats_isolate
CREATE INDEX "idx_auto_reannotation_stats_isolate" ON "reannotation_stats" ("isolate_id");

-- index: idx_auto_sample_metadata_accession
CREATE INDEX "idx_auto_sample_metadata_accession" ON "sample_metadata" ("accession");

-- index: idx_auto_sample_metadata_collection_date
CREATE INDEX "idx_auto_sample_metadata_collection_date" ON "sample_metadata" ("collection_date");

-- index: idx_auto_sample_metadata_geo_loc
CREATE INDEX "idx_auto_sample_metadata_geo_loc" ON "sample_metadata" ("geo_loc_name");

-- index: idx_auto_sample_metadata_isolate
CREATE INDEX "idx_auto_sample_metadata_isolate" ON "sample_metadata" ("isolate_id");

-- index: idx_auto_viral_proteins_accession
CREATE INDEX "idx_auto_viral_proteins_accession" ON "viral_proteins" ("protein_accession");

-- index: idx_auto_viral_proteins_is_rdrp
CREATE INDEX "idx_auto_viral_proteins_is_rdrp" ON "viral_proteins" ("is_rdrp");

-- index: idx_bio_host
CREATE INDEX idx_bio_host ON host_biology_profiles(host_id);

-- index: idx_biorxiv_date
CREATE INDEX idx_biorxiv_date ON biorxiv_preprints(date_posted);

-- index: idx_biorxiv_doi
CREATE INDEX idx_biorxiv_doi ON biorxiv_preprints(doi);

-- index: idx_biorxiv_server
CREATE INDEX idx_biorxiv_server ON biorxiv_preprints(server);

-- index: idx_bridge_accession
CREATE INDEX idx_bridge_accession ON protein_annotation_bridge(protein_accession);

-- index: idx_bridge_protein
CREATE INDEX idx_bridge_protein ON protein_annotation_bridge(protein_id);

-- index: idx_bridge_sources
CREATE INDEX idx_bridge_sources ON protein_annotation_bridge(has_uniprot, has_interpro, has_kegg, has_structure);

-- index: idx_bridge_uniprot
CREATE INDEX idx_bridge_uniprot ON protein_annotation_bridge(uniprot_id);

-- index: idx_cg_species
CREATE INDEX idx_cg_species ON core_genes(virus_species);

-- index: idx_ch_scientific_name
CREATE INDEX idx_ch_scientific_name ON crustacean_hosts(scientific_name);

-- index: idx_ch_scientific_name_nocase_unique
CREATE UNIQUE INDEX idx_ch_scientific_name_nocase_unique
            ON crustacean_hosts(scientific_name COLLATE NOCASE);

-- index: idx_conflicts_isolate
CREATE INDEX idx_conflicts_isolate ON curation_conflicts(isolate_id);

-- index: idx_conflicts_status
CREATE INDEX idx_conflicts_status ON curation_conflicts(status);

-- index: idx_conflicts_unique_open_seed
CREATE UNIQUE INDEX idx_conflicts_unique_open_seed
            ON curation_conflicts(
                entity_type,
                entity_id,
                COALESCE(isolate_id, -1),
                field_name,
                conflict_type,
                COALESCE(value_a, ''),
                COALESCE(value_b, '')
            );

-- index: idx_control_unique
CREATE UNIQUE INDEX idx_control_unique
            ON control_management_methods(
                COALESCE(virus_master_id, -1),
                COALESCE(host_id, -1),
                method_category,
                method_name,
                COALESCE(reference_id, -1)
            );

-- index: idx_control_virus
CREATE INDEX idx_control_virus ON control_management_methods(virus_master_id);

-- index: idx_diagnostic_unique
CREATE UNIQUE INDEX idx_diagnostic_unique
        ON diagnostic_methods(
            COALESCE(virus_master_id, -1),
            method_category,
            method_name,
            COALESCE(reference_id, -1)
        );

-- index: idx_diagnostic_virus
CREATE INDEX idx_diagnostic_virus ON diagnostic_methods(virus_master_id);

-- index: idx_environment_unique
CREATE UNIQUE INDEX idx_environment_unique
            ON environmental_evidence(
                virus_master_id,
                evidence_type,
                COALESCE(value_min, -999999),
                COALESCE(value_max, -999999),
                COALESCE(value_text, '')
            );

-- index: idx_environment_virus
CREATE INDEX idx_environment_virus ON environmental_evidence(virus_master_id);

-- index: idx_epmc_doi
CREATE INDEX idx_epmc_doi ON epmc_literature(doi);

-- index: idx_epmc_pmid
CREATE INDEX idx_epmc_pmid ON epmc_literature(pmid);

-- index: idx_epmc_ref
CREATE INDEX idx_epmc_ref ON epmc_literature(local_reference_id);

-- index: idx_evidence_host
CREATE INDEX idx_evidence_host
            ON evidence_records(host_id);

-- index: idx_evidence_reference
CREATE INDEX idx_evidence_reference
            ON evidence_records(reference_id);

-- index: idx_evidence_type
CREATE INDEX idx_evidence_type
            ON evidence_records(evidence_type);

-- index: idx_evidence_virus
CREATE INDEX idx_evidence_virus
            ON evidence_records(virus_master_id);

-- index: idx_external_curation_queries_band
CREATE INDEX idx_external_curation_queries_band
            ON external_curation_queries(priority_band);

-- index: idx_external_curation_queries_field
CREATE INDEX idx_external_curation_queries_field
            ON external_curation_queries(field_name);

-- index: idx_external_curation_queries_status
CREATE INDEX idx_external_curation_queries_status
            ON external_curation_queries(query_status);

-- index: idx_external_curation_queries_unique
CREATE UNIQUE INDEX idx_external_curation_queries_unique
            ON external_curation_queries(isolate_id, field_name, query_target, query_text);

-- index: idx_gbif_host
CREATE INDEX idx_gbif_host ON gbif_occurrences(host_id);

-- index: idx_gbif_latlon
CREATE INDEX idx_gbif_latlon ON gbif_occurrences(decimal_latitude, decimal_longitude);

-- index: idx_gbif_name
CREATE INDEX idx_gbif_name ON gbif_occurrences(scientific_name);

-- index: idx_genbank_recovery_accession
CREATE INDEX idx_genbank_recovery_accession
            ON genbank_recovery_candidates(accession);

-- index: idx_genbank_recovery_candidate_unique
CREATE UNIQUE INDEX idx_genbank_recovery_candidate_unique
            ON genbank_recovery_candidates(isolate_id, field_name, candidate_value, matched_entity_type, matched_entity_id);

-- index: idx_genbank_recovery_field
CREATE INDEX idx_genbank_recovery_field
            ON genbank_recovery_candidates(field_name);

-- index: idx_genbank_recovery_status
CREATE INDEX idx_genbank_recovery_status
            ON genbank_recovery_candidates(match_status);

-- index: idx_geo_gse
CREATE INDEX idx_geo_gse ON geo_datasets(gse_accession);

-- index: idx_geo_quality_continent
CREATE INDEX idx_geo_quality_continent
            ON geography_quality_profiles(continent);

-- index: idx_geo_quality_country
CREATE INDEX idx_geo_quality_country
            ON geography_quality_profiles(standardized_country);

-- index: idx_geo_quality_needs_geocoding
CREATE INDEX idx_geo_quality_needs_geocoding
            ON geography_quality_profiles(needs_geocoding);

-- index: idx_geo_quality_precision
CREATE INDEX idx_geo_quality_precision
            ON geography_quality_profiles(location_precision);

-- index: idx_geo_virus_name
CREATE INDEX idx_geo_virus_name ON geo_virus_links(virus_name);

-- index: idx_gpi_species
CREATE INDEX idx_gpi_species ON genome_pairwise_identity(virus_species);

-- index: idx_host_aliases_alias
CREATE INDEX idx_host_aliases_alias
            ON host_aliases(alias);

-- index: idx_host_aliases_host
CREATE INDEX idx_host_aliases_host
            ON host_aliases(host_id);

-- index: idx_host_range_host
CREATE INDEX idx_host_range_host ON host_range_evidence(host_id);

-- index: idx_host_range_virus
CREATE INDEX idx_host_range_virus ON host_range_evidence(virus_master_id);

-- index: idx_host_review_candidates_host
CREATE INDEX idx_host_review_candidates_host
            ON host_review_candidates(host_id);

-- index: idx_host_review_candidates_issue
CREATE INDEX idx_host_review_candidates_issue
            ON host_review_candidates(issue_type);

-- index: idx_host_review_candidates_unique
CREATE UNIQUE INDEX idx_host_review_candidates_unique
            ON host_review_candidates(
                host_id,
                issue_type,
                COALESCE(suggested_host_id, -1),
                COALESCE(suggested_name, '')
            );

-- index: idx_host_taxonomy_profiles_host
CREATE INDEX idx_host_taxonomy_profiles_host
            ON host_taxonomy_profiles(host_id);

-- index: idx_host_taxonomy_profiles_taxid
CREATE INDEX idx_host_taxonomy_profiles_taxid
            ON host_taxonomy_profiles(ncbi_taxid);

-- index: idx_icp_country
CREATE INDEX idx_icp_country ON isolate_curated_profiles(country);

-- index: idx_icp_host
CREATE INDEX idx_icp_host ON isolate_curated_profiles(host_id);

-- index: idx_icp_master
CREATE INDEX idx_icp_master ON isolate_curated_profiles(master_id);

-- index: idx_icp_status
CREATE INDEX idx_icp_status ON isolate_curated_profiles(curation_status);

-- index: idx_icp_year
CREATE INDEX idx_icp_year ON isolate_curated_profiles(collection_year);

-- index: idx_ictv_family
CREATE INDEX idx_ictv_family ON ictv_taxonomy(family);

-- index: idx_ictv_genus
CREATE INDEX idx_ictv_genus ON ictv_taxonomy(genus);

-- index: idx_ictv_species
CREATE INDEX idx_ictv_species ON ictv_taxonomy(species);

-- index: idx_ictv_vmr_genbank
CREATE INDEX idx_ictv_vmr_genbank ON ictv_vmr(genbank_accession);

-- index: idx_ictv_vmr_refseq
CREATE INDEX idx_ictv_vmr_refseq ON ictv_vmr(refseq_accession);

-- index: idx_ictv_vmr_species
CREATE INDEX idx_ictv_vmr_species ON ictv_vmr(species);

-- index: idx_ictv_vmr_virus_name
CREATE INDEX idx_ictv_vmr_virus_name ON ictv_vmr(virus_name);

-- index: idx_ip_interpro
CREATE INDEX idx_ip_interpro ON interpro_annotations(interpro_id);

-- index: idx_ip_protein
CREATE INDEX idx_ip_protein ON interpro_annotations(protein_id);

-- index: idx_ip_uniprot
CREATE INDEX idx_ip_uniprot ON interpro_annotations(uniprot_id);

-- index: idx_ipgo_go
CREATE INDEX idx_ipgo_go ON interpro_go_terms(go_id);

-- index: idx_ipgo_protein
CREATE INDEX idx_ipgo_protein ON interpro_go_terms(protein_id);

-- index: idx_ir_collection_id
CREATE INDEX idx_ir_collection_id ON infection_records(collection_id);

-- index: idx_ir_host_id
CREATE INDEX idx_ir_host_id ON infection_records(host_id);

-- index: idx_ir_isolate_id
CREATE INDEX idx_ir_isolate_id ON infection_records(isolate_id);

-- index: idx_irl_isolate
CREATE INDEX idx_irl_isolate ON isolate_reference_links(isolate_id);

-- index: idx_irl_isolate_reference
CREATE INDEX idx_irl_isolate_reference
        ON isolate_reference_links(isolate_id, reference_id);

-- index: idx_irl_reference
CREATE INDEX idx_irl_reference ON isolate_reference_links(reference_id);

-- index: idx_irl_unique_isolate_reference_type
CREATE UNIQUE INDEX idx_irl_unique_isolate_reference_type
        ON isolate_reference_links(isolate_id, reference_id, link_type);

-- index: idx_kegg_ec
CREATE INDEX idx_kegg_ec ON kegg_annotations(ec_number);

-- index: idx_kegg_ko
CREATE INDEX idx_kegg_ko ON kegg_annotations(ko_id);

-- index: idx_kegg_pathway_ko
CREATE INDEX idx_kegg_pathway_ko ON kegg_protein_pathways(ko_id);

-- index: idx_kegg_protein
CREATE INDEX idx_kegg_protein ON kegg_annotations(protein_id);

-- index: idx_lit_candidates_identifier
CREATE INDEX idx_lit_candidates_identifier
        ON literature_evidence_candidates(pmid, doi);

-- index: idx_lit_candidates_source
CREATE INDEX idx_lit_candidates_source
        ON literature_evidence_candidates(source_key);

-- index: idx_lit_candidates_virus
CREATE INDEX idx_lit_candidates_virus
        ON literature_evidence_candidates(master_id, target_virus);

-- index: idx_manual_ictv_bridges_ictv
CREATE INDEX idx_manual_ictv_bridges_ictv
            ON manual_ictv_bridges(ictv_id);

-- index: idx_manual_ictv_bridges_master
CREATE INDEX idx_manual_ictv_bridges_master
            ON manual_ictv_bridges(master_id);

-- index: idx_manual_review_priority
CREATE INDEX idx_manual_review_priority
            ON manual_review_priority_queue(priority, score DESC, category);

-- index: idx_nr_acc
CREATE INDEX idx_nr_acc ON nucleotide_records(accession);

-- index: idx_obis_host
CREATE INDEX idx_obis_host ON obis_occurrences(host_id);

-- index: idx_obis_latlon
CREATE INDEX idx_obis_latlon ON obis_occurrences(decimal_latitude, decimal_longitude);

-- index: idx_outbreak_unique
CREATE UNIQUE INDEX idx_outbreak_unique
            ON outbreak_events(
                virus_master_id,
                COALESCE(country, ''),
                COALESCE(start_year, ''),
                event_summary
            );

-- index: idx_outbreak_virus
CREATE INDEX idx_outbreak_virus ON outbreak_events(virus_master_id);

-- index: idx_pathogenicity_unique
CREATE UNIQUE INDEX idx_pathogenicity_unique
            ON pathogenicity_evidence(
                virus_master_id,
                COALESCE(host_id, -1),
                COALESCE(isolate_id, -1),
                COALESCE(reference_id, -1),
                COALESCE(source_text, '')
            );

-- index: idx_pathogenicity_virus
CREATE INDEX idx_pathogenicity_virus ON pathogenicity_evidence(virus_master_id);

-- index: idx_pd_cluster
CREATE INDEX idx_pd_cluster ON protein_domains(cluster_id);

-- index: idx_pd_name
CREATE INDEX idx_pd_name ON protein_domains(domain_name);

-- index: idx_phi_cluster
CREATE INDEX idx_phi_cluster ON phi_base_hits(cluster_id);

-- index: idx_phi_phenotype
CREATE INDEX idx_phi_phenotype ON phi_base_hits(phi_phenotype);

-- index: idx_pride_acc
CREATE INDEX idx_pride_acc ON pride_datasets(pride_accession);

-- index: idx_pride_pmid
CREATE INDEX idx_pride_pmid ON pride_datasets(publication_pmid);

-- index: idx_prov_confidence
CREATE INDEX idx_prov_confidence
            ON data_provenance(confidence_level);

-- index: idx_prov_source
CREATE INDEX idx_prov_source
            ON data_provenance(data_source);

-- index: idx_prov_table_record
CREATE INDEX idx_prov_table_record
            ON data_provenance(table_name, record_id);

-- index: idx_ps_cluster
CREATE INDEX idx_ps_cluster ON protein_structures(cluster_id);

-- index: idx_ps_protein
CREATE INDEX idx_ps_protein ON protein_structures(protein_id);

-- index: idx_pub_fk_auto_host_scope_worklist_host_id
CREATE INDEX "idx_pub_fk_auto_host_scope_worklist_host_id"
            ON "auto_host_scope_worklist"("host_id");

-- index: idx_pub_fk_control_management_methods_host_id
CREATE INDEX "idx_pub_fk_control_management_methods_host_id"
            ON "control_management_methods"("host_id");

-- index: idx_pub_fk_curation_logs_source_id
CREATE INDEX "idx_pub_fk_curation_logs_source_id"
            ON "curation_logs"("source_id");

-- index: idx_pub_fk_curation_priority_queue_isolate_id
CREATE INDEX "idx_pub_fk_curation_priority_queue_isolate_id"
            ON "curation_priority_queue"("isolate_id");

-- index: idx_pub_fk_data_provenance_virus_master_id
CREATE INDEX "idx_pub_fk_data_provenance_virus_master_id"
            ON "data_provenance"("virus_master_id");

-- index: idx_pub_fk_environmental_evidence_reference_id
CREATE INDEX "idx_pub_fk_environmental_evidence_reference_id"
            ON "environmental_evidence"("reference_id");

-- index: idx_pub_fk_epmc_preprints_epmc_id
CREATE INDEX "idx_pub_fk_epmc_preprints_epmc_id"
            ON "epmc_preprints"("epmc_id");

-- index: idx_pub_fk_evidence_records_isolate_id
CREATE INDEX "idx_pub_fk_evidence_records_isolate_id"
            ON "evidence_records"("isolate_id");

-- index: idx_pub_fk_evidence_records_source_id
CREATE INDEX "idx_pub_fk_evidence_records_source_id"
            ON "evidence_records"("source_id");

-- index: idx_pub_fk_evidence_review_priority_queue_virus_master_id
CREATE INDEX "idx_pub_fk_evidence_review_priority_queue_virus_master_id"
            ON "evidence_review_priority_queue"("virus_master_id");

-- index: idx_pub_fk_gbif_species_summary_host_id
CREATE INDEX "idx_pub_fk_gbif_species_summary_host_id"
            ON "gbif_species_summary"("host_id");

-- index: idx_pub_fk_geo_virus_links_geo_dataset_id
CREATE INDEX "idx_pub_fk_geo_virus_links_geo_dataset_id"
            ON "geo_virus_links"("geo_dataset_id");

-- index: idx_pub_fk_geo_virus_links_local_isolate_id
CREATE INDEX "idx_pub_fk_geo_virus_links_local_isolate_id"
            ON "geo_virus_links"("local_isolate_id");

-- index: idx_pub_fk_geo_virus_links_sra_run_id
CREATE INDEX "idx_pub_fk_geo_virus_links_sra_run_id"
            ON "geo_virus_links"("sra_run_id");

-- index: idx_pub_fk_geography_quality_profiles_collection_id
CREATE INDEX "idx_pub_fk_geography_quality_profiles_collection_id"
            ON "geography_quality_profiles"("collection_id");

-- index: idx_pub_fk_host_aliases_source_id
CREATE INDEX "idx_pub_fk_host_aliases_source_id"
            ON "host_aliases"("source_id");

-- index: idx_pub_fk_host_range_evidence_reference_id
CREATE INDEX "idx_pub_fk_host_range_evidence_reference_id"
            ON "host_range_evidence"("reference_id");

-- index: idx_pub_fk_host_range_evidence_representative_isolate_id
CREATE INDEX "idx_pub_fk_host_range_evidence_representative_isolate_id"
            ON "host_range_evidence"("representative_isolate_id");

-- index: idx_pub_fk_host_review_candidates_suggested_host_id
CREATE INDEX "idx_pub_fk_host_review_candidates_suggested_host_id"
            ON "host_review_candidates"("suggested_host_id");

-- index: idx_pub_fk_host_scope_overrides_host_id
CREATE INDEX "idx_pub_fk_host_scope_overrides_host_id"
            ON "host_scope_overrides"("host_id");

-- index: idx_pub_fk_host_taxonomy_profiles_source_id
CREATE INDEX "idx_pub_fk_host_taxonomy_profiles_source_id"
            ON "host_taxonomy_profiles"("source_id");

-- index: idx_pub_fk_ictv_review_priority_queue_master_id
CREATE INDEX "idx_pub_fk_ictv_review_priority_queue_master_id"
            ON "ictv_review_priority_queue"("master_id");

-- index: idx_pub_fk_infection_records_reference_id
CREATE INDEX "idx_pub_fk_infection_records_reference_id"
            ON "infection_records"("reference_id");

-- index: idx_pub_fk_isolate_curated_profiles_collection_id
CREATE INDEX "idx_pub_fk_isolate_curated_profiles_collection_id"
            ON "isolate_curated_profiles"("collection_id");

-- index: idx_pub_fk_isolate_curated_profiles_discovery_reference_id
CREATE INDEX "idx_pub_fk_isolate_curated_profiles_discovery_reference_id"
            ON "isolate_curated_profiles"("discovery_reference_id");

-- index: idx_pub_fk_isolate_curated_profiles_genome_reference_id
CREATE INDEX "idx_pub_fk_isolate_curated_profiles_genome_reference_id"
            ON "isolate_curated_profiles"("genome_reference_id");

-- index: idx_pub_fk_isolate_curated_profiles_primary_reference_id
CREATE INDEX "idx_pub_fk_isolate_curated_profiles_primary_reference_id"
            ON "isolate_curated_profiles"("primary_reference_id");

-- index: idx_pub_fk_literature_evidence_candidates_reference_id
CREATE INDEX "idx_pub_fk_literature_evidence_candidates_reference_id"
            ON "literature_evidence_candidates"("reference_id");

-- index: idx_pub_fk_literature_evidence_candidates_source_id
CREATE INDEX "idx_pub_fk_literature_evidence_candidates_source_id"
            ON "literature_evidence_candidates"("source_id");

-- index: idx_pub_fk_pride_virus_links_local_isolate_id
CREATE INDEX "idx_pub_fk_pride_virus_links_local_isolate_id"
            ON "pride_virus_links"("local_isolate_id");

-- index: idx_pub_fk_pride_virus_links_local_protein_id
CREATE INDEX "idx_pub_fk_pride_virus_links_local_protein_id"
            ON "pride_virus_links"("local_protein_id");

-- index: idx_pub_fk_pride_virus_links_pride_dataset_id
CREATE INDEX "idx_pub_fk_pride_virus_links_pride_dataset_id"
            ON "pride_virus_links"("pride_dataset_id");

-- index: idx_pub_fk_string_interactions_local_protein_id
CREATE INDEX "idx_pub_fk_string_interactions_local_protein_id"
            ON "string_interactions"("local_protein_id");

-- index: idx_pub_fk_uniprot_protein_links_protein_id
CREATE INDEX "idx_pub_fk_uniprot_protein_links_protein_id"
            ON "uniprot_protein_links"("protein_id");

-- index: idx_pub_fk_uniprot_structures_protein_id
CREATE INDEX "idx_pub_fk_uniprot_structures_protein_id"
            ON "uniprot_structures"("protein_id");

-- index: idx_pub_fk_virus_aliases_source_id
CREATE INDEX "idx_pub_fk_virus_aliases_source_id"
            ON "virus_aliases"("source_id");

-- index: idx_pub_fk_virus_ictv_mappings_source_id
CREATE INDEX "idx_pub_fk_virus_ictv_mappings_source_id"
            ON "virus_ictv_mappings"("source_id");

-- index: idx_pub_fk_virus_ictv_status_master_id
CREATE INDEX "idx_pub_fk_virus_ictv_status_master_id"
            ON "virus_ictv_status"("master_id");

-- index: idx_pub_fk_virus_master_review_queue_master_id
CREATE INDEX "idx_pub_fk_virus_master_review_queue_master_id"
            ON "virus_master_review_queue"("master_id");

-- index: idx_pub_fk_virus_vmr_mappings_source_id
CREATE INDEX "idx_pub_fk_virus_vmr_mappings_source_id"
            ON "virus_vmr_mappings"("source_id");

-- index: idx_queue_band
CREATE INDEX idx_queue_band
            ON curation_priority_queue(priority_band);

-- index: idx_queue_field
CREATE INDEX idx_queue_field
            ON curation_priority_queue(field_name);

-- index: idx_queue_score
CREATE INDEX idx_queue_score
            ON curation_priority_queue(priority_score);

-- index: idx_reanno_isolate
CREATE INDEX idx_reanno_isolate ON reannotated_orfs(isolate_id);

-- index: idx_reanno_pos
CREATE INDEX idx_reanno_pos ON reannotated_orfs(start_pos, end_pos);

-- index: idx_rl_pmid
CREATE INDEX idx_rl_pmid ON ref_literatures(pmid);

-- index: idx_sc_country
CREATE INDEX idx_sc_country ON sample_collections(country);

-- index: idx_sc_province
CREATE INDEX idx_sc_province ON sample_collections(province);

-- index: idx_sc_year
CREATE INDEX idx_sc_year ON sample_collections(collection_year);

-- index: idx_sra_acc
CREATE INDEX idx_sra_acc ON sra_runs(sra_accession);

-- index: idx_string_prot
CREATE INDEX idx_string_prot ON string_interactions(protein_a);

-- index: idx_string_score
CREATE INDEX idx_string_score ON string_interactions(combined_score);

-- index: idx_string_uniprot
CREATE INDEX idx_string_uniprot ON string_interactions(source_uniprot_id);

-- index: idx_submission_geo_precision_class
CREATE INDEX idx_submission_geo_precision_class ON submission_target_geography_precision(map_precision_class, isolate_id);

-- index: idx_submission_manual_tasks_type
CREATE INDEX idx_submission_manual_tasks_type ON submission_manual_intervention_tasks(task_type, entity_id);

-- index: idx_submission_p0_blockers_type
CREATE INDEX idx_submission_p0_blockers_type ON submission_p0_release_blockers(blocker_type, entity_id);

-- index: idx_submission_protein_structure_status
CREATE INDEX idx_submission_protein_structure_status ON submission_protein_annotation_coverage(structure_consistency_status, protein_id);

-- index: idx_synteny_species
CREATE INDEX idx_synteny_species ON genome_synteny_blocks(virus_species);

-- index: idx_traits_host
CREATE INDEX idx_traits_host ON host_ecological_traits(host_id);

-- index: idx_us_source
CREATE INDEX idx_us_source ON uniprot_structures(source);

-- index: idx_us_uniprot
CREATE INDEX idx_us_uniprot ON uniprot_structures(uniprot_id);

-- index: idx_vi_accession
CREATE INDEX idx_vi_accession ON viral_isolates(accession);

-- index: idx_vi_completeness
CREATE INDEX idx_vi_completeness ON viral_isolates(completeness);

-- index: idx_vi_master_id
CREATE INDEX idx_vi_master_id ON viral_isolates(master_id);

-- index: idx_vi_reference_id
CREATE INDEX idx_vi_reference_id ON viral_isolates(reference_id);

-- index: idx_vi_virus_name
CREATE INDEX idx_vi_virus_name ON viral_isolates(virus_name);

-- index: idx_vim_ictv
CREATE INDEX idx_vim_ictv ON virus_ictv_mappings(ictv_id);

-- index: idx_vim_master
CREATE INDEX idx_vim_master ON virus_ictv_mappings(master_id);

-- index: idx_virus_aliases_alias
CREATE INDEX idx_virus_aliases_alias
            ON virus_aliases(alias);

-- index: idx_virus_aliases_master
CREATE INDEX idx_virus_aliases_master
            ON virus_aliases(master_id);

-- index: idx_vm_canonical
CREATE INDEX idx_vm_canonical ON virus_master(canonical_name);

-- index: idx_vp_accession
CREATE INDEX idx_vp_accession ON viral_proteins(protein_accession);

-- index: idx_vp_category
CREATE INDEX idx_vp_category ON viral_proteins(functional_category);

-- index: idx_vp_gene
CREATE INDEX idx_vp_gene ON viral_proteins(gene_symbol);

-- index: idx_vp_isolate_id
CREATE INDEX idx_vp_isolate_id ON viral_proteins(isolate_id);

-- index: idx_vpnr_cluster
CREATE INDEX idx_vpnr_cluster ON viral_proteins_nr(cluster_id);

-- index: idx_vpnr_protein
CREATE INDEX idx_vpnr_protein ON viral_proteins_nr(protein_id);

-- index: idx_vpnr_reanno
CREATE INDEX idx_vpnr_reanno ON viral_proteins_nr(reanno_id);

-- index: idx_vvm_ictv
CREATE INDEX idx_vvm_ictv ON virus_vmr_mappings(ictv_id);

-- index: idx_vvm_master
CREATE INDEX idx_vvm_master ON virus_vmr_mappings(master_id);

-- index: idx_vvm_vmr
CREATE INDEX idx_vvm_vmr ON virus_vmr_mappings(vmr_id);

-- index: idx_vz_family
CREATE INDEX idx_vz_family ON viralzone_families(family_name);

-- index: idx_vz_gene_family
CREATE INDEX idx_vz_gene_family ON viralzone_gene_tables(family_id);

-- index: idx_xrefs_entity
CREATE INDEX idx_xrefs_entity
            ON external_xrefs(entity_type, entity_id);

-- index: idx_xrefs_source_external
CREATE INDEX idx_xrefs_source_external
            ON external_xrefs(source_id, external_id);

-- view: analysis_clean_viral_isolates
CREATE VIEW analysis_clean_viral_isolates AS
        SELECT *
        FROM viral_isolates
        WHERE NOT (
            COALESCE(genome_length, sequence_length, 0) > 10000000
            OR LOWER(COALESCE(virus_name, '')) = 'host genome artifact'
            OR COALESCE(sequence_scope_status, '') = 'host_genome_artifact'
        );

-- view: analysis_curated_diagnostic_methods
CREATE VIEW analysis_curated_diagnostic_methods AS
        SELECT *
        FROM diagnostic_methods
        WHERE data_quality = 'curated'
          AND curation_status = 'manual_checked'
          AND virus_master_id IS NOT NULL
          AND reference_id IS NOT NULL
          AND target_gene_or_region IS NOT NULL AND TRIM(target_gene_or_region) <> ''
          AND detection_limit IS NOT NULL AND TRIM(detection_limit) <> ''
          AND validation_context IS NOT NULL AND TRIM(validation_context) <> '';

-- view: analysis_isolate_completeness
CREATE VIEW analysis_isolate_completeness AS
        SELECT
            vi.isolate_id,
            vi.accession,
            vi.master_id,
            vm.canonical_name,
            vi.virus_name,
            COALESCE(icp.host_id, mh.host_id) AS host_id,
            COALESCE(NULLIF(icp.host_scientific_name, ''), mh.scientific_name, sm.host_name) AS host_scientific_name,
            COALESCE(NULLIF(sc.country, ''), NULLIF(icp.country, ''), NULLIF(substr(sm.geo_loc_name, 1, instr(sm.geo_loc_name || ':', ':') - 1), '')) AS country,
            COALESCE(sc.latitude, icp.latitude) AS latitude,
            COALESCE(sc.longitude, icp.longitude) AS longitude,
            COALESCE(NULLIF(sc.collection_year, ''), NULLIF(icp.collection_year, ''), NULLIF(sm.collection_date, '')) AS collection_year,
            COALESCE(NULLIF(ir.isolation_source, ''), NULLIF(icp.sample_source, ''), NULLIF(sm.isolation_source, '')) AS isolation_source,
            vi.genome_type,
            vi.genome_length,
            vi.gc_content,
            CASE WHEN vi.reference_id IS NOT NULL OR EXISTS (
                SELECT 1 FROM isolate_reference_links irl WHERE irl.isolate_id = vi.isolate_id
            ) THEN 1 ELSE 0 END AS has_reference,
            CASE WHEN COALESCE(icp.host_id, mh.host_id) IS NOT NULL THEN 1 ELSE 0 END AS has_host,
            CASE WHEN COALESCE(NULLIF(sc.country, ''), NULLIF(icp.country, ''), NULLIF(substr(sm.geo_loc_name, 1, instr(sm.geo_loc_name || ':', ':') - 1), '')) IS NOT NULL THEN 1 ELSE 0 END AS has_country,
            CASE WHEN COALESCE(sc.latitude, icp.latitude) IS NOT NULL
                   AND COALESCE(sc.longitude, icp.longitude) IS NOT NULL THEN 1 ELSE 0 END AS has_coordinates,
            CASE WHEN COALESCE(NULLIF(sc.collection_year, ''), NULLIF(icp.collection_year, ''), NULLIF(sm.collection_date, '')) IS NOT NULL THEN 1 ELSE 0 END AS has_collection_year,
            CASE WHEN COALESCE(NULLIF(ir.isolation_source, ''), NULLIF(icp.sample_source, ''), NULLIF(sm.isolation_source, '')) IS NOT NULL THEN 1 ELSE 0 END AS has_isolation_source,
            CASE WHEN vi.genome_type IS NOT NULL AND TRIM(vi.genome_type) <> '' THEN 1 ELSE 0 END AS has_genome_type
        FROM viral_isolates vi
        JOIN virus_master vm ON vm.master_id = vi.master_id
        LEFT JOIN isolate_curated_profiles icp ON icp.isolate_id = vi.isolate_id
        LEFT JOIN sample_metadata sm ON sm.isolate_id = vi.isolate_id
        LEFT JOIN crustacean_hosts mh
          ON LOWER(mh.scientific_name) = LOWER(COALESCE(NULLIF(icp.host_scientific_name, ''), NULLIF(sm.host_name, '')))
        LEFT JOIN infection_records ir ON ir.isolate_id = vi.isolate_id
        LEFT JOIN sample_collections sc ON sc.collection_id = ir.collection_id;

-- view: analysis_protein_annotation_completeness
CREATE VIEW analysis_protein_annotation_completeness AS
        SELECT
            vp.protein_id,
            vp.isolate_id,
            vi.accession,
            vp.protein_accession,
            vp.protein_name,
            vp.aa_length,
            CASE WHEN upl.link_id IS NOT NULL THEN 1 ELSE 0 END AS has_uniprot_link,
            CASE WHEN pd.domain_id IS NOT NULL THEN 1 ELSE 0 END AS has_domain,
            CASE WHEN ig.id IS NOT NULL THEN 1 ELSE 0 END AS has_go_term,
            CASE WHEN kpp.link_id IS NOT NULL THEN 1 ELSE 0 END AS has_kegg_pathway,
            CASE WHEN ps.structure_id IS NOT NULL THEN 1 ELSE 0 END AS has_structure
        FROM viral_proteins vp
        JOIN viral_isolates vi ON vi.isolate_id = vp.isolate_id
        LEFT JOIN uniprot_protein_links upl ON upl.protein_id = vp.protein_id
        LEFT JOIN protein_domains pd ON pd.protein_id = vp.protein_id
        LEFT JOIN interpro_go_terms ig ON ig.protein_id = vp.protein_id
        LEFT JOIN kegg_protein_pathways kpp ON kpp.protein_id = vp.protein_id
        LEFT JOIN protein_structures ps ON ps.protein_id = vp.protein_id
        GROUP BY vp.protein_id;

-- view: analysis_reviewed_evidence_records
CREATE VIEW analysis_reviewed_evidence_records AS
        SELECT *
        FROM evidence_records
        WHERE curation_status = 'manual_checked'
          AND reference_id IS NOT NULL;

-- view: analysis_strict_target_isolates
CREATE VIEW analysis_strict_target_isolates AS
        SELECT v.*
        FROM analysis_target_isolates v
        LEFT JOIN isolate_curated_profiles icp ON icp.isolate_id = v.isolate_id
        WHERE COALESCE(icp.curation_status, 'auto_seeded') <> 'conflict_open'
          AND COALESCE(icp.dataset_tier, '') <> 'unverified';

-- view: analysis_target_isolates
CREATE VIEW analysis_target_isolates AS
        SELECT v.*
        FROM viral_isolates v
        JOIN virus_master vm ON vm.master_id = v.master_id
        LEFT JOIN isolate_curated_profiles icp ON icp.isolate_id = v.isolate_id
        LEFT JOIN host_scope_overrides hso ON hso.host_id = icp.host_id
        LEFT JOIN nucleotide_records nr ON nr.isolate_id = v.isolate_id
        LEFT JOIN sample_metadata sm ON sm.isolate_id = v.isolate_id
        WHERE vm.is_crustacean_virus = 1
          AND vm.entry_type NOT IN ('non_target', 'host_genome', 'catalog_only', 'reference_only')
          AND COALESCE(icp.host_is_target, 1) = 1
          AND COALESCE(hso.exclude_from_target_stats, 0) = 0
        AND COALESCE(icp.dataset_tier, '') NOT IN (
              'sequence_scope_artifact', 'host_genome_artifact'
          )
          AND COALESCE(v.sequence_scope_status, '') NOT IN (
              'short_fragment_not_complete_genome', 'host_genome_artifact'
          )
          AND v.accession NOT LIKE 'RDRP\_%' ESCAPE '\'
          AND NOT (
              COALESCE(v.genome_length, v.sequence_length, 0) > 10000000
              OR LOWER(COALESCE(v.virus_name, '')) = 'host genome artifact'
          )
          AND 
    LOWER(
        COALESCE(v.virus_name, '') || ' ' ||
        COALESCE(v.molecule_type, '') || ' ' ||
        COALESCE(v.completeness, '') || ' ' ||
        COALESCE(nr.definition, '') || ' ' ||
        COALESCE(nr.organism, '') || ' ' ||
        COALESCE(nr.molecule_type, '') || ' ' ||
        COALESCE(nr.taxonomy_lineage, '') || ' ' ||
        COALESCE(sm.mol_type, '') || ' ' ||
        COALESCE(sm.raw_notes, '') || ' ' ||
        COALESCE(sm.organism, '')
    )
     NOT LIKE '% mrna%'
          AND 
    LOWER(
        COALESCE(v.virus_name, '') || ' ' ||
        COALESCE(v.molecule_type, '') || ' ' ||
        COALESCE(v.completeness, '') || ' ' ||
        COALESCE(nr.definition, '') || ' ' ||
        COALESCE(nr.organism, '') || ' ' ||
        COALESCE(nr.molecule_type, '') || ' ' ||
        COALESCE(nr.taxonomy_lineage, '') || ' ' ||
        COALESCE(sm.mol_type, '') || ' ' ||
        COALESCE(sm.raw_notes, '') || ' ' ||
        COALESCE(sm.organism, '')
    )
     NOT LIKE '% cdna%'
          AND 
    LOWER(
        COALESCE(v.virus_name, '') || ' ' ||
        COALESCE(v.molecule_type, '') || ' ' ||
        COALESCE(v.completeness, '') || ' ' ||
        COALESCE(nr.definition, '') || ' ' ||
        COALESCE(nr.organism, '') || ' ' ||
        COALESCE(nr.molecule_type, '') || ' ' ||
        COALESCE(nr.taxonomy_lineage, '') || ' ' ||
        COALESCE(sm.mol_type, '') || ' ' ||
        COALESCE(sm.raw_notes, '') || ' ' ||
        COALESCE(sm.organism, '')
    )
     NOT LIKE '% est%'
          AND NOT (
              v.completeness = 'complete_genome'
              AND COALESCE(v.sequence_length, v.genome_length, 0) < 1000
          );

-- view: predicted_temperature_profiles
CREATE VIEW predicted_temperature_profiles AS
            SELECT profile_id,
                   virus_name,
                   optimal_temp_min,
                   optimal_temp_max,
                   temp_range_min,
                   temp_range_max,
                   thermal_inactivation_temp,
                   thermal_inactivation_time,
                   cold_storage_temp,
                   cold_storage_viability,
                   temp_sensitivity_notes,
                   climate_change_impact,
                   data_source,
                   data_origin,
                   data_source_type,
                   confidence,
                   publication_use,
                   curation_date,
                   notes
            FROM temperature_profiles;

-- view: predicted_virulence_profiles
CREATE VIEW predicted_virulence_profiles AS
            SELECT profile_id,
                   virus_name,
                   virulence_level,
                   virulence_label,
                   mortality_rate_min,
                   mortality_rate_max,
                   ld50_value,
                   pathogenic_mechanism,
                   outbreak_record,
                   host_age_susceptibility,
                   data_source,
                   data_origin,
                   data_source_type,
                   confidence,
                   publication_use,
                   curation_date,
                   notes
            FROM virulence_profiles;

-- view: submission_excluded_isolates_with_reasons
CREATE VIEW submission_excluded_isolates_with_reasons AS
        SELECT
            vi.isolate_id,
            vi.accession,
            vi.virus_name,
            vi.master_id,
            vm.canonical_name,
            vm.entry_type,
            vm.is_crustacean_virus,
            icp.host_id,
            icp.host_scientific_name,
            icp.host_is_target,
            hso.scope_status,
            hso.exclude_from_target_stats,
            CASE
                WHEN vm.is_crustacean_virus <> 1 THEN 'virus_master_not_marked_crustacean'
                WHEN vm.entry_type IN ('non_target', 'host_genome') THEN 'virus_master_entry_type_excluded'
                WHEN COALESCE(icp.host_is_target, 1) <> 1 THEN 'curated_host_not_target'
                WHEN COALESCE(hso.exclude_from_target_stats, 0) <> 0 THEN 'host_scope_override_excluded'
                WHEN COALESCE(hso.scope_status, 'target') IN ('technical_host', 'non_target') THEN 'strict_scope_status_excluded'
                ELSE 'not_excluded_by_current_target_rule'
            END AS exclusion_reason,
            CASE
                WHEN vi.isolate_id IN (SELECT isolate_id FROM analysis_target_isolates) THEN 1 ELSE 0
            END AS in_analysis_target,
            CASE
                WHEN vi.isolate_id IN (SELECT isolate_id FROM analysis_strict_target_isolates) THEN 1 ELSE 0
            END AS in_strict_target
        FROM viral_isolates vi
        JOIN virus_master vm ON vm.master_id = vi.master_id
        LEFT JOIN isolate_curated_profiles icp ON icp.isolate_id = vi.isolate_id
        LEFT JOIN host_scope_overrides hso ON hso.host_id = icp.host_id
        WHERE vi.isolate_id NOT IN (SELECT isolate_id FROM analysis_strict_target_isolates);

-- view: v_data_dictionary
CREATE VIEW v_data_dictionary AS

        SELECT
            'auto_annotation_gap_worklist' AS table_name,
            cid,
            name AS column_name,
            type AS data_type,
            CASE WHEN "notnull" THEN 1 ELSE 0 END AS not_null,
            COALESCE(dflt_value, '') AS default_value,
            CASE WHEN pk THEN 1 ELSE 0 END AS is_primary_key
        FROM pragma_table_info('auto_annotation_gap_worklist')
        
UNION ALL

        SELECT
            'auto_completeness_fills' AS table_name,
            cid,
            name AS column_name,
            type AS data_type,
            CASE WHEN "notnull" THEN 1 ELSE 0 END AS not_null,
            COALESCE(dflt_value, '') AS default_value,
            CASE WHEN pk THEN 1 ELSE 0 END AS is_primary_key
        FROM pragma_table_info('auto_completeness_fills')
        
UNION ALL

        SELECT
            'auto_completeness_worklist' AS table_name,
            cid,
            name AS column_name,
            type AS data_type,
            CASE WHEN "notnull" THEN 1 ELSE 0 END AS not_null,
            COALESCE(dflt_value, '') AS default_value,
            CASE WHEN pk THEN 1 ELSE 0 END AS is_primary_key
        FROM pragma_table_info('auto_completeness_worklist')
        
UNION ALL

        SELECT
            'auto_host_scope_worklist' AS table_name,
            cid,
            name AS column_name,
            type AS data_type,
            CASE WHEN "notnull" THEN 1 ELSE 0 END AS not_null,
            COALESCE(dflt_value, '') AS default_value,
            CASE WHEN pk THEN 1 ELSE 0 END AS is_primary_key
        FROM pragma_table_info('auto_host_scope_worklist')
        
UNION ALL

        SELECT
            'auto_quality_metrics' AS table_name,
            cid,
            name AS column_name,
            type AS data_type,
            CASE WHEN "notnull" THEN 1 ELSE 0 END AS not_null,
            COALESCE(dflt_value, '') AS default_value,
            CASE WHEN pk THEN 1 ELSE 0 END AS is_primary_key
        FROM pragma_table_info('auto_quality_metrics')
        
UNION ALL

        SELECT
            'biorxiv_preprints' AS table_name,
            cid,
            name AS column_name,
            type AS data_type,
            CASE WHEN "notnull" THEN 1 ELSE 0 END AS not_null,
            COALESCE(dflt_value, '') AS default_value,
            CASE WHEN pk THEN 1 ELSE 0 END AS is_primary_key
        FROM pragma_table_info('biorxiv_preprints')
        
UNION ALL

        SELECT
            'biosample_links' AS table_name,
            cid,
            name AS column_name,
            type AS data_type,
            CASE WHEN "notnull" THEN 1 ELSE 0 END AS not_null,
            COALESCE(dflt_value, '') AS default_value,
            CASE WHEN pk THEN 1 ELSE 0 END AS is_primary_key
        FROM pragma_table_info('biosample_links')
        
UNION ALL

        SELECT
            'completeness_optimization_log' AS table_name,
            cid,
            name AS column_name,
            type AS data_type,
            CASE WHEN "notnull" THEN 1 ELSE 0 END AS not_null,
            COALESCE(dflt_value, '') AS default_value,
            CASE WHEN pk THEN 1 ELSE 0 END AS is_primary_key
        FROM pragma_table_info('completeness_optimization_log')
        
UNION ALL

        SELECT
            'compliance_quarantine_log' AS table_name,
            cid,
            name AS column_name,
            type AS data_type,
            CASE WHEN "notnull" THEN 1 ELSE 0 END AS not_null,
            COALESCE(dflt_value, '') AS default_value,
            CASE WHEN pk THEN 1 ELSE 0 END AS is_primary_key
        FROM pragma_table_info('compliance_quarantine_log')
        
UNION ALL

        SELECT
            'control_management_methods' AS table_name,
            cid,
            name AS column_name,
            type AS data_type,
            CASE WHEN "notnull" THEN 1 ELSE 0 END AS not_null,
            COALESCE(dflt_value, '') AS default_value,
            CASE WHEN pk THEN 1 ELSE 0 END AS is_primary_key
        FROM pragma_table_info('control_management_methods')
        
UNION ALL

        SELECT
            'core_genes' AS table_name,
            cid,
            name AS column_name,
            type AS data_type,
            CASE WHEN "notnull" THEN 1 ELSE 0 END AS not_null,
            COALESCE(dflt_value, '') AS default_value,
            CASE WHEN pk THEN 1 ELSE 0 END AS is_primary_key
        FROM pragma_table_info('core_genes')
        
UNION ALL

        SELECT
            'crustacean_hosts' AS table_name,
            cid,
            name AS column_name,
            type AS data_type,
            CASE WHEN "notnull" THEN 1 ELSE 0 END AS not_null,
            COALESCE(dflt_value, '') AS default_value,
            CASE WHEN pk THEN 1 ELSE 0 END AS is_primary_key
        FROM pragma_table_info('crustacean_hosts')
        
UNION ALL

        SELECT
            'curation_conflicts' AS table_name,
            cid,
            name AS column_name,
            type AS data_type,
            CASE WHEN "notnull" THEN 1 ELSE 0 END AS not_null,
            COALESCE(dflt_value, '') AS default_value,
            CASE WHEN pk THEN 1 ELSE 0 END AS is_primary_key
        FROM pragma_table_info('curation_conflicts')
        
UNION ALL

        SELECT
            'curation_logs' AS table_name,
            cid,
            name AS column_name,
            type AS data_type,
            CASE WHEN "notnull" THEN 1 ELSE 0 END AS not_null,
            COALESCE(dflt_value, '') AS default_value,
            CASE WHEN pk THEN 1 ELSE 0 END AS is_primary_key
        FROM pragma_table_info('curation_logs')
        
UNION ALL

        SELECT
            'curation_priority_queue' AS table_name,
            cid,
            name AS column_name,
            type AS data_type,
            CASE WHEN "notnull" THEN 1 ELSE 0 END AS not_null,
            COALESCE(dflt_value, '') AS default_value,
            CASE WHEN pk THEN 1 ELSE 0 END AS is_primary_key
        FROM pragma_table_info('curation_priority_queue')
        
UNION ALL

        SELECT
            'curation_standardization_log' AS table_name,
            cid,
            name AS column_name,
            type AS data_type,
            CASE WHEN "notnull" THEN 1 ELSE 0 END AS not_null,
            COALESCE(dflt_value, '') AS default_value,
            CASE WHEN pk THEN 1 ELSE 0 END AS is_primary_key
        FROM pragma_table_info('curation_standardization_log')
        
UNION ALL

        SELECT
            'curation_vocab_terms' AS table_name,
            cid,
            name AS column_name,
            type AS data_type,
            CASE WHEN "notnull" THEN 1 ELSE 0 END AS not_null,
            COALESCE(dflt_value, '') AS default_value,
            CASE WHEN pk THEN 1 ELSE 0 END AS is_primary_key
        FROM pragma_table_info('curation_vocab_terms')
        
UNION ALL

        SELECT
            'data_gap_queue' AS table_name,
            cid,
            name AS column_name,
            type AS data_type,
            CASE WHEN "notnull" THEN 1 ELSE 0 END AS not_null,
            COALESCE(dflt_value, '') AS default_value,
            CASE WHEN pk THEN 1 ELSE 0 END AS is_primary_key
        FROM pragma_table_info('data_gap_queue')
        
UNION ALL

        SELECT
            'database_maintenance_log' AS table_name,
            cid,
            name AS column_name,
            type AS data_type,
            CASE WHEN "notnull" THEN 1 ELSE 0 END AS not_null,
            COALESCE(dflt_value, '') AS default_value,
            CASE WHEN pk THEN 1 ELSE 0 END AS is_primary_key
        FROM pragma_table_info('database_maintenance_log')
        
UNION ALL

        SELECT
            'diagnostic_evidence_promotion_log' AS table_name,
            cid,
            name AS column_name,
            type AS data_type,
            CASE WHEN "notnull" THEN 1 ELSE 0 END AS not_null,
            COALESCE(dflt_value, '') AS default_value,
            CASE WHEN pk THEN 1 ELSE 0 END AS is_primary_key
        FROM pragma_table_info('diagnostic_evidence_promotion_log')
        
UNION ALL

        SELECT
            'diagnostic_method_review_queue' AS table_name,
            cid,
            name AS column_name,
            type AS data_type,
            CASE WHEN "notnull" THEN 1 ELSE 0 END AS not_null,
            COALESCE(dflt_value, '') AS default_value,
            CASE WHEN pk THEN 1 ELSE 0 END AS is_primary_key
        FROM pragma_table_info('diagnostic_method_review_queue')
        
UNION ALL

        SELECT
            'diagnostic_methods' AS table_name,
            cid,
            name AS column_name,
            type AS data_type,
            CASE WHEN "notnull" THEN 1 ELSE 0 END AS not_null,
            COALESCE(dflt_value, '') AS default_value,
            CASE WHEN pk THEN 1 ELSE 0 END AS is_primary_key
        FROM pragma_table_info('diagnostic_methods')
        
UNION ALL

        SELECT
            'environmental_evidence' AS table_name,
            cid,
            name AS column_name,
            type AS data_type,
            CASE WHEN "notnull" THEN 1 ELSE 0 END AS not_null,
            COALESCE(dflt_value, '') AS default_value,
            CASE WHEN pk THEN 1 ELSE 0 END AS is_primary_key
        FROM pragma_table_info('environmental_evidence')
        
UNION ALL

        SELECT
            'epmc_literature' AS table_name,
            cid,
            name AS column_name,
            type AS data_type,
            CASE WHEN "notnull" THEN 1 ELSE 0 END AS not_null,
            COALESCE(dflt_value, '') AS default_value,
            CASE WHEN pk THEN 1 ELSE 0 END AS is_primary_key
        FROM pragma_table_info('epmc_literature')
        
UNION ALL

        SELECT
            'epmc_preprints' AS table_name,
            cid,
            name AS column_name,
            type AS data_type,
            CASE WHEN "notnull" THEN 1 ELSE 0 END AS not_null,
            COALESCE(dflt_value, '') AS default_value,
            CASE WHEN pk THEN 1 ELSE 0 END AS is_primary_key
        FROM pragma_table_info('epmc_preprints')
        
UNION ALL

        SELECT
            'evidence_records' AS table_name,
            cid,
            name AS column_name,
            type AS data_type,
            CASE WHEN "notnull" THEN 1 ELSE 0 END AS not_null,
            COALESCE(dflt_value, '') AS default_value,
            CASE WHEN pk THEN 1 ELSE 0 END AS is_primary_key
        FROM pragma_table_info('evidence_records')
        
UNION ALL

        SELECT
            'evidence_review_priority_queue' AS table_name,
            cid,
            name AS column_name,
            type AS data_type,
            CASE WHEN "notnull" THEN 1 ELSE 0 END AS not_null,
            COALESCE(dflt_value, '') AS default_value,
            CASE WHEN pk THEN 1 ELSE 0 END AS is_primary_key
        FROM pragma_table_info('evidence_review_priority_queue')
        
UNION ALL

        SELECT
            'external_curation_queries' AS table_name,
            cid,
            name AS column_name,
            type AS data_type,
            CASE WHEN "notnull" THEN 1 ELSE 0 END AS not_null,
            COALESCE(dflt_value, '') AS default_value,
            CASE WHEN pk THEN 1 ELSE 0 END AS is_primary_key
        FROM pragma_table_info('external_curation_queries')
        
UNION ALL

        SELECT
            'external_sources' AS table_name,
            cid,
            name AS column_name,
            type AS data_type,
            CASE WHEN "notnull" THEN 1 ELSE 0 END AS not_null,
            COALESCE(dflt_value, '') AS default_value,
            CASE WHEN pk THEN 1 ELSE 0 END AS is_primary_key
        FROM pragma_table_info('external_sources')
        
UNION ALL

        SELECT
            'external_xrefs' AS table_name,
            cid,
            name AS column_name,
            type AS data_type,
            CASE WHEN "notnull" THEN 1 ELSE 0 END AS not_null,
            COALESCE(dflt_value, '') AS default_value,
            CASE WHEN pk THEN 1 ELSE 0 END AS is_primary_key
        FROM pragma_table_info('external_xrefs')
        
UNION ALL

        SELECT
            'field_completeness_snapshots' AS table_name,
            cid,
            name AS column_name,
            type AS data_type,
            CASE WHEN "notnull" THEN 1 ELSE 0 END AS not_null,
            COALESCE(dflt_value, '') AS default_value,
            CASE WHEN pk THEN 1 ELSE 0 END AS is_primary_key
        FROM pragma_table_info('field_completeness_snapshots')
        
UNION ALL

        SELECT
            'gbif_occurrences' AS table_name,
            cid,
            name AS column_name,
            type AS data_type,
            CASE WHEN "notnull" THEN 1 ELSE 0 END AS not_null,
            COALESCE(dflt_value, '') AS default_value,
            CASE WHEN pk THEN 1 ELSE 0 END AS is_primary_key
        FROM pragma_table_info('gbif_occurrences')
        
UNION ALL

        SELECT
            'gbif_species_summary' AS table_name,
            cid,
            name AS column_name,
            type AS data_type,
            CASE WHEN "notnull" THEN 1 ELSE 0 END AS not_null,
            COALESCE(dflt_value, '') AS default_value,
            CASE WHEN pk THEN 1 ELSE 0 END AS is_primary_key
        FROM pragma_table_info('gbif_species_summary')
        
UNION ALL

        SELECT
            'genbank_recovery_candidates' AS table_name,
            cid,
            name AS column_name,
            type AS data_type,
            CASE WHEN "notnull" THEN 1 ELSE 0 END AS not_null,
            COALESCE(dflt_value, '') AS default_value,
            CASE WHEN pk THEN 1 ELSE 0 END AS is_primary_key
        FROM pragma_table_info('genbank_recovery_candidates')
        
UNION ALL

        SELECT
            'genome_pairwise_identity' AS table_name,
            cid,
            name AS column_name,
            type AS data_type,
            CASE WHEN "notnull" THEN 1 ELSE 0 END AS not_null,
            COALESCE(dflt_value, '') AS default_value,
            CASE WHEN pk THEN 1 ELSE 0 END AS is_primary_key
        FROM pragma_table_info('genome_pairwise_identity')
        
UNION ALL

        SELECT
            'genome_synteny_blocks' AS table_name,
            cid,
            name AS column_name,
            type AS data_type,
            CASE WHEN "notnull" THEN 1 ELSE 0 END AS not_null,
            COALESCE(dflt_value, '') AS default_value,
            CASE WHEN pk THEN 1 ELSE 0 END AS is_primary_key
        FROM pragma_table_info('genome_synteny_blocks')
        
UNION ALL

        SELECT
            'geo_datasets' AS table_name,
            cid,
            name AS column_name,
            type AS data_type,
            CASE WHEN "notnull" THEN 1 ELSE 0 END AS not_null,
            COALESCE(dflt_value, '') AS default_value,
            CASE WHEN pk THEN 1 ELSE 0 END AS is_primary_key
        FROM pragma_table_info('geo_datasets')
        
UNION ALL

        SELECT
            'geo_virus_links' AS table_name,
            cid,
            name AS column_name,
            type AS data_type,
            CASE WHEN "notnull" THEN 1 ELSE 0 END AS not_null,
            COALESCE(dflt_value, '') AS default_value,
            CASE WHEN pk THEN 1 ELSE 0 END AS is_primary_key
        FROM pragma_table_info('geo_virus_links')
        
UNION ALL

        SELECT
            'geography_quality_profiles' AS table_name,
            cid,
            name AS column_name,
            type AS data_type,
            CASE WHEN "notnull" THEN 1 ELSE 0 END AS not_null,
            COALESCE(dflt_value, '') AS default_value,
            CASE WHEN pk THEN 1 ELSE 0 END AS is_primary_key
        FROM pragma_table_info('geography_quality_profiles')
        
UNION ALL

        SELECT
            'host_aliases' AS table_name,
            cid,
            name AS column_name,
            type AS data_type,
            CASE WHEN "notnull" THEN 1 ELSE 0 END AS not_null,
            COALESCE(dflt_value, '') AS default_value,
            CASE WHEN pk THEN 1 ELSE 0 END AS is_primary_key
        FROM pragma_table_info('host_aliases')
        
UNION ALL

        SELECT
            'host_biology_profiles' AS table_name,
            cid,
            name AS column_name,
            type AS data_type,
            CASE WHEN "notnull" THEN 1 ELSE 0 END AS not_null,
            COALESCE(dflt_value, '') AS default_value,
            CASE WHEN pk THEN 1 ELSE 0 END AS is_primary_key
        FROM pragma_table_info('host_biology_profiles')
        
UNION ALL

        SELECT
            'host_ecological_traits' AS table_name,
            cid,
            name AS column_name,
            type AS data_type,
            CASE WHEN "notnull" THEN 1 ELSE 0 END AS not_null,
            COALESCE(dflt_value, '') AS default_value,
            CASE WHEN pk THEN 1 ELSE 0 END AS is_primary_key
        FROM pragma_table_info('host_ecological_traits')
        
UNION ALL

        SELECT
            'host_range_evidence' AS table_name,
            cid,
            name AS column_name,
            type AS data_type,
            CASE WHEN "notnull" THEN 1 ELSE 0 END AS not_null,
            COALESCE(dflt_value, '') AS default_value,
            CASE WHEN pk THEN 1 ELSE 0 END AS is_primary_key
        FROM pragma_table_info('host_range_evidence')
        
UNION ALL

        SELECT
            'host_review_candidates' AS table_name,
            cid,
            name AS column_name,
            type AS data_type,
            CASE WHEN "notnull" THEN 1 ELSE 0 END AS not_null,
            COALESCE(dflt_value, '') AS default_value,
            CASE WHEN pk THEN 1 ELSE 0 END AS is_primary_key
        FROM pragma_table_info('host_review_candidates')
        
UNION ALL

        SELECT
            'host_scope_overrides' AS table_name,
            cid,
            name AS column_name,
            type AS data_type,
            CASE WHEN "notnull" THEN 1 ELSE 0 END AS not_null,
            COALESCE(dflt_value, '') AS default_value,
            CASE WHEN pk THEN 1 ELSE 0 END AS is_primary_key
        FROM pragma_table_info('host_scope_overrides')
        
UNION ALL

        SELECT
            'host_taxonomy_profiles' AS table_name,
            cid,
            name AS column_name,
            type AS data_type,
            CASE WHEN "notnull" THEN 1 ELSE 0 END AS not_null,
            COALESCE(dflt_value, '') AS default_value,
            CASE WHEN pk THEN 1 ELSE 0 END AS is_primary_key
        FROM pragma_table_info('host_taxonomy_profiles')
        
UNION ALL

        SELECT
            'ictv_review_priority_queue' AS table_name,
            cid,
            name AS column_name,
            type AS data_type,
            CASE WHEN "notnull" THEN 1 ELSE 0 END AS not_null,
            COALESCE(dflt_value, '') AS default_value,
            CASE WHEN pk THEN 1 ELSE 0 END AS is_primary_key
        FROM pragma_table_info('ictv_review_priority_queue')
        
UNION ALL

        SELECT
            'ictv_taxonomy' AS table_name,
            cid,
            name AS column_name,
            type AS data_type,
            CASE WHEN "notnull" THEN 1 ELSE 0 END AS not_null,
            COALESCE(dflt_value, '') AS default_value,
            CASE WHEN pk THEN 1 ELSE 0 END AS is_primary_key
        FROM pragma_table_info('ictv_taxonomy')
        
UNION ALL

        SELECT
            'ictv_vmr' AS table_name,
            cid,
            name AS column_name,
            type AS data_type,
            CASE WHEN "notnull" THEN 1 ELSE 0 END AS not_null,
            COALESCE(dflt_value, '') AS default_value,
            CASE WHEN pk THEN 1 ELSE 0 END AS is_primary_key
        FROM pragma_table_info('ictv_vmr')
        
UNION ALL

        SELECT
            'infection_records' AS table_name,
            cid,
            name AS column_name,
            type AS data_type,
            CASE WHEN "notnull" THEN 1 ELSE 0 END AS not_null,
            COALESCE(dflt_value, '') AS default_value,
            CASE WHEN pk THEN 1 ELSE 0 END AS is_primary_key
        FROM pragma_table_info('infection_records')
        
UNION ALL

        SELECT
            'interpro_annotations' AS table_name,
            cid,
            name AS column_name,
            type AS data_type,
            CASE WHEN "notnull" THEN 1 ELSE 0 END AS not_null,
            COALESCE(dflt_value, '') AS default_value,
            CASE WHEN pk THEN 1 ELSE 0 END AS is_primary_key
        FROM pragma_table_info('interpro_annotations')
        
UNION ALL

        SELECT
            'interpro_api_query_log' AS table_name,
            cid,
            name AS column_name,
            type AS data_type,
            CASE WHEN "notnull" THEN 1 ELSE 0 END AS not_null,
            COALESCE(dflt_value, '') AS default_value,
            CASE WHEN pk THEN 1 ELSE 0 END AS is_primary_key
        FROM pragma_table_info('interpro_api_query_log')
        
UNION ALL

        SELECT
            'interpro_go_backfill_queue' AS table_name,
            cid,
            name AS column_name,
            type AS data_type,
            CASE WHEN "notnull" THEN 1 ELSE 0 END AS not_null,
            COALESCE(dflt_value, '') AS default_value,
            CASE WHEN pk THEN 1 ELSE 0 END AS is_primary_key
        FROM pragma_table_info('interpro_go_backfill_queue')
        
UNION ALL

        SELECT
            'interpro_go_terms' AS table_name,
            cid,
            name AS column_name,
            type AS data_type,
            CASE WHEN "notnull" THEN 1 ELSE 0 END AS not_null,
            COALESCE(dflt_value, '') AS default_value,
            CASE WHEN pk THEN 1 ELSE 0 END AS is_primary_key
        FROM pragma_table_info('interpro_go_terms')
        
UNION ALL

        SELECT
            'isolate_curated_profiles' AS table_name,
            cid,
            name AS column_name,
            type AS data_type,
            CASE WHEN "notnull" THEN 1 ELSE 0 END AS not_null,
            COALESCE(dflt_value, '') AS default_value,
            CASE WHEN pk THEN 1 ELSE 0 END AS is_primary_key
        FROM pragma_table_info('isolate_curated_profiles')
        
UNION ALL

        SELECT
            'isolate_reference_links' AS table_name,
            cid,
            name AS column_name,
            type AS data_type,
            CASE WHEN "notnull" THEN 1 ELSE 0 END AS not_null,
            COALESCE(dflt_value, '') AS default_value,
            CASE WHEN pk THEN 1 ELSE 0 END AS is_primary_key
        FROM pragma_table_info('isolate_reference_links')
        
UNION ALL

        SELECT
            'kegg_annotations' AS table_name,
            cid,
            name AS column_name,
            type AS data_type,
            CASE WHEN "notnull" THEN 1 ELSE 0 END AS not_null,
            COALESCE(dflt_value, '') AS default_value,
            CASE WHEN pk THEN 1 ELSE 0 END AS is_primary_key
        FROM pragma_table_info('kegg_annotations')
        
UNION ALL

        SELECT
            'kegg_pathways' AS table_name,
            cid,
            name AS column_name,
            type AS data_type,
            CASE WHEN "notnull" THEN 1 ELSE 0 END AS not_null,
            COALESCE(dflt_value, '') AS default_value,
            CASE WHEN pk THEN 1 ELSE 0 END AS is_primary_key
        FROM pragma_table_info('kegg_pathways')
        
UNION ALL

        SELECT
            'kegg_protein_pathways' AS table_name,
            cid,
            name AS column_name,
            type AS data_type,
            CASE WHEN "notnull" THEN 1 ELSE 0 END AS not_null,
            COALESCE(dflt_value, '') AS default_value,
            CASE WHEN pk THEN 1 ELSE 0 END AS is_primary_key
        FROM pragma_table_info('kegg_protein_pathways')
        
UNION ALL

        SELECT
            'literature_evidence_candidates' AS table_name,
            cid,
            name AS column_name,
            type AS data_type,
            CASE WHEN "notnull" THEN 1 ELSE 0 END AS not_null,
            COALESCE(dflt_value, '') AS default_value,
            CASE WHEN pk THEN 1 ELSE 0 END AS is_primary_key
        FROM pragma_table_info('literature_evidence_candidates')
        
UNION ALL

        SELECT
            'literature_evidence_import_log' AS table_name,
            cid,
            name AS column_name,
            type AS data_type,
            CASE WHEN "notnull" THEN 1 ELSE 0 END AS not_null,
            COALESCE(dflt_value, '') AS default_value,
            CASE WHEN pk THEN 1 ELSE 0 END AS is_primary_key
        FROM pragma_table_info('literature_evidence_import_log')
        
UNION ALL

        SELECT
            'literature_evidence_promotion_log' AS table_name,
            cid,
            name AS column_name,
            type AS data_type,
            CASE WHEN "notnull" THEN 1 ELSE 0 END AS not_null,
            COALESCE(dflt_value, '') AS default_value,
            CASE WHEN pk THEN 1 ELSE 0 END AS is_primary_key
        FROM pragma_table_info('literature_evidence_promotion_log')
        
UNION ALL

        SELECT
            'literature_search_log' AS table_name,
            cid,
            name AS column_name,
            type AS data_type,
            CASE WHEN "notnull" THEN 1 ELSE 0 END AS not_null,
            COALESCE(dflt_value, '') AS default_value,
            CASE WHEN pk THEN 1 ELSE 0 END AS is_primary_key
        FROM pragma_table_info('literature_search_log')
        
UNION ALL

        SELECT
            'manual_ictv_bridges' AS table_name,
            cid,
            name AS column_name,
            type AS data_type,
            CASE WHEN "notnull" THEN 1 ELSE 0 END AS not_null,
            COALESCE(dflt_value, '') AS default_value,
            CASE WHEN pk THEN 1 ELSE 0 END AS is_primary_key
        FROM pragma_table_info('manual_ictv_bridges')
        
UNION ALL

        SELECT
            'manual_review_priority_queue' AS table_name,
            cid,
            name AS column_name,
            type AS data_type,
            CASE WHEN "notnull" THEN 1 ELSE 0 END AS not_null,
            COALESCE(dflt_value, '') AS default_value,
            CASE WHEN pk THEN 1 ELSE 0 END AS is_primary_key
        FROM pragma_table_info('manual_review_priority_queue')
        
UNION ALL

        SELECT
            'nr_protein_clusters' AS table_name,
            cid,
            name AS column_name,
            type AS data_type,
            CASE WHEN "notnull" THEN 1 ELSE 0 END AS not_null,
            COALESCE(dflt_value, '') AS default_value,
            CASE WHEN pk THEN 1 ELSE 0 END AS is_primary_key
        FROM pragma_table_info('nr_protein_clusters')
        
UNION ALL

        SELECT
            'nucleotide_records' AS table_name,
            cid,
            name AS column_name,
            type AS data_type,
            CASE WHEN "notnull" THEN 1 ELSE 0 END AS not_null,
            COALESCE(dflt_value, '') AS default_value,
            CASE WHEN pk THEN 1 ELSE 0 END AS is_primary_key
        FROM pragma_table_info('nucleotide_records')
        
UNION ALL

        SELECT
            'obis_occurrences' AS table_name,
            cid,
            name AS column_name,
            type AS data_type,
            CASE WHEN "notnull" THEN 1 ELSE 0 END AS not_null,
            COALESCE(dflt_value, '') AS default_value,
            CASE WHEN pk THEN 1 ELSE 0 END AS is_primary_key
        FROM pragma_table_info('obis_occurrences')
        
UNION ALL

        SELECT
            'outbreak_events' AS table_name,
            cid,
            name AS column_name,
            type AS data_type,
            CASE WHEN "notnull" THEN 1 ELSE 0 END AS not_null,
            COALESCE(dflt_value, '') AS default_value,
            CASE WHEN pk THEN 1 ELSE 0 END AS is_primary_key
        FROM pragma_table_info('outbreak_events')
        
UNION ALL

        SELECT
            'pathogenicity_evidence' AS table_name,
            cid,
            name AS column_name,
            type AS data_type,
            CASE WHEN "notnull" THEN 1 ELSE 0 END AS not_null,
            COALESCE(dflt_value, '') AS default_value,
            CASE WHEN pk THEN 1 ELSE 0 END AS is_primary_key
        FROM pragma_table_info('pathogenicity_evidence')
        
UNION ALL

        SELECT
            'phi_base_hits' AS table_name,
            cid,
            name AS column_name,
            type AS data_type,
            CASE WHEN "notnull" THEN 1 ELSE 0 END AS not_null,
            COALESCE(dflt_value, '') AS default_value,
            CASE WHEN pk THEN 1 ELSE 0 END AS is_primary_key
        FROM pragma_table_info('phi_base_hits')
        
UNION ALL

        SELECT
            'predicted_temperature_profiles' AS table_name,
            cid,
            name AS column_name,
            type AS data_type,
            CASE WHEN "notnull" THEN 1 ELSE 0 END AS not_null,
            COALESCE(dflt_value, '') AS default_value,
            CASE WHEN pk THEN 1 ELSE 0 END AS is_primary_key
        FROM pragma_table_info('predicted_temperature_profiles')
        
UNION ALL

        SELECT
            'predicted_virulence_profiles' AS table_name,
            cid,
            name AS column_name,
            type AS data_type,
            CASE WHEN "notnull" THEN 1 ELSE 0 END AS not_null,
            COALESCE(dflt_value, '') AS default_value,
            CASE WHEN pk THEN 1 ELSE 0 END AS is_primary_key
        FROM pragma_table_info('predicted_virulence_profiles')
        
UNION ALL

        SELECT
            'pride_datasets' AS table_name,
            cid,
            name AS column_name,
            type AS data_type,
            CASE WHEN "notnull" THEN 1 ELSE 0 END AS not_null,
            COALESCE(dflt_value, '') AS default_value,
            CASE WHEN pk THEN 1 ELSE 0 END AS is_primary_key
        FROM pragma_table_info('pride_datasets')
        
UNION ALL

        SELECT
            'pride_virus_links' AS table_name,
            cid,
            name AS column_name,
            type AS data_type,
            CASE WHEN "notnull" THEN 1 ELSE 0 END AS not_null,
            COALESCE(dflt_value, '') AS default_value,
            CASE WHEN pk THEN 1 ELSE 0 END AS is_primary_key
        FROM pragma_table_info('pride_virus_links')
        
UNION ALL

        SELECT
            'protein_annotation_bridge' AS table_name,
            cid,
            name AS column_name,
            type AS data_type,
            CASE WHEN "notnull" THEN 1 ELSE 0 END AS not_null,
            COALESCE(dflt_value, '') AS default_value,
            CASE WHEN pk THEN 1 ELSE 0 END AS is_primary_key
        FROM pragma_table_info('protein_annotation_bridge')
        
UNION ALL

        SELECT
            'protein_domains' AS table_name,
            cid,
            name AS column_name,
            type AS data_type,
            CASE WHEN "notnull" THEN 1 ELSE 0 END AS not_null,
            COALESCE(dflt_value, '') AS default_value,
            CASE WHEN pk THEN 1 ELSE 0 END AS is_primary_key
        FROM pragma_table_info('protein_domains')
        
UNION ALL

        SELECT
            'protein_structures' AS table_name,
            cid,
            name AS column_name,
            type AS data_type,
            CASE WHEN "notnull" THEN 1 ELSE 0 END AS not_null,
            COALESCE(dflt_value, '') AS default_value,
            CASE WHEN pk THEN 1 ELSE 0 END AS is_primary_key
        FROM pragma_table_info('protein_structures')
        
UNION ALL

        SELECT
            'reannotated_orfs' AS table_name,
            cid,
            name AS column_name,
            type AS data_type,
            CASE WHEN "notnull" THEN 1 ELSE 0 END AS not_null,
            COALESCE(dflt_value, '') AS default_value,
            CASE WHEN pk THEN 1 ELSE 0 END AS is_primary_key
        FROM pragma_table_info('reannotated_orfs')
        
UNION ALL

        SELECT
            'reannotation_stats' AS table_name,
            cid,
            name AS column_name,
            type AS data_type,
            CASE WHEN "notnull" THEN 1 ELSE 0 END AS not_null,
            COALESCE(dflt_value, '') AS default_value,
            CASE WHEN pk THEN 1 ELSE 0 END AS is_primary_key
        FROM pragma_table_info('reannotation_stats')
        
UNION ALL

        SELECT
            'ref_literatures' AS table_name,
            cid,
            name AS column_name,
            type AS data_type,
            CASE WHEN "notnull" THEN 1 ELSE 0 END AS not_null,
            COALESCE(dflt_value, '') AS default_value,
            CASE WHEN pk THEN 1 ELSE 0 END AS is_primary_key
        FROM pragma_table_info('ref_literatures')
        
UNION ALL

        SELECT
            'release_manifest' AS table_name,
            cid,
            name AS column_name,
            type AS data_type,
            CASE WHEN "notnull" THEN 1 ELSE 0 END AS not_null,
            COALESCE(dflt_value, '') AS default_value,
            CASE WHEN pk THEN 1 ELSE 0 END AS is_primary_key
        FROM pragma_table_info('release_manifest')
        
UNION ALL

        SELECT
            'sample_collections' AS table_name,
            cid,
            name AS column_name,
            type AS data_type,
            CASE WHEN "notnull" THEN 1 ELSE 0 END AS not_null,
            COALESCE(dflt_value, '') AS default_value,
            CASE WHEN pk THEN 1 ELSE 0 END AS is_primary_key
        FROM pragma_table_info('sample_collections')
        
UNION ALL

        SELECT
            'sample_metadata' AS table_name,
            cid,
            name AS column_name,
            type AS data_type,
            CASE WHEN "notnull" THEN 1 ELSE 0 END AS not_null,
            COALESCE(dflt_value, '') AS default_value,
            CASE WHEN pk THEN 1 ELSE 0 END AS is_primary_key
        FROM pragma_table_info('sample_metadata')
        
UNION ALL

        SELECT
            'schema_version' AS table_name,
            cid,
            name AS column_name,
            type AS data_type,
            CASE WHEN "notnull" THEN 1 ELSE 0 END AS not_null,
            COALESCE(dflt_value, '') AS default_value,
            CASE WHEN pk THEN 1 ELSE 0 END AS is_primary_key
        FROM pragma_table_info('schema_version')
        
UNION ALL

        SELECT
            'sequence_curation_flags' AS table_name,
            cid,
            name AS column_name,
            type AS data_type,
            CASE WHEN "notnull" THEN 1 ELSE 0 END AS not_null,
            COALESCE(dflt_value, '') AS default_value,
            CASE WHEN pk THEN 1 ELSE 0 END AS is_primary_key
        FROM pragma_table_info('sequence_curation_flags')
        
UNION ALL

        SELECT
            'sra_runs' AS table_name,
            cid,
            name AS column_name,
            type AS data_type,
            CASE WHEN "notnull" THEN 1 ELSE 0 END AS not_null,
            COALESCE(dflt_value, '') AS default_value,
            CASE WHEN pk THEN 1 ELSE 0 END AS is_primary_key
        FROM pragma_table_info('sra_runs')
        
UNION ALL

        SELECT
            'string_interactions' AS table_name,
            cid,
            name AS column_name,
            type AS data_type,
            CASE WHEN "notnull" THEN 1 ELSE 0 END AS not_null,
            COALESCE(dflt_value, '') AS default_value,
            CASE WHEN pk THEN 1 ELSE 0 END AS is_primary_key
        FROM pragma_table_info('string_interactions')
        
UNION ALL

        SELECT
            'submission_manual_intervention_tasks' AS table_name,
            cid,
            name AS column_name,
            type AS data_type,
            CASE WHEN "notnull" THEN 1 ELSE 0 END AS not_null,
            COALESCE(dflt_value, '') AS default_value,
            CASE WHEN pk THEN 1 ELSE 0 END AS is_primary_key
        FROM pragma_table_info('submission_manual_intervention_tasks')
        
UNION ALL

        SELECT
            'submission_p0_release_blockers' AS table_name,
            cid,
            name AS column_name,
            type AS data_type,
            CASE WHEN "notnull" THEN 1 ELSE 0 END AS not_null,
            COALESCE(dflt_value, '') AS default_value,
            CASE WHEN pk THEN 1 ELSE 0 END AS is_primary_key
        FROM pragma_table_info('submission_p0_release_blockers')
        
UNION ALL

        SELECT
            'submission_protein_annotation_coverage' AS table_name,
            cid,
            name AS column_name,
            type AS data_type,
            CASE WHEN "notnull" THEN 1 ELSE 0 END AS not_null,
            COALESCE(dflt_value, '') AS default_value,
            CASE WHEN pk THEN 1 ELSE 0 END AS is_primary_key
        FROM pragma_table_info('submission_protein_annotation_coverage')
        
UNION ALL

        SELECT
            'submission_target_geography_precision' AS table_name,
            cid,
            name AS column_name,
            type AS data_type,
            CASE WHEN "notnull" THEN 1 ELSE 0 END AS not_null,
            COALESCE(dflt_value, '') AS default_value,
            CASE WHEN pk THEN 1 ELSE 0 END AS is_primary_key
        FROM pragma_table_info('submission_target_geography_precision')
        
UNION ALL

        SELECT
            'temperature_profiles' AS table_name,
            cid,
            name AS column_name,
            type AS data_type,
            CASE WHEN "notnull" THEN 1 ELSE 0 END AS not_null,
            COALESCE(dflt_value, '') AS default_value,
            CASE WHEN pk THEN 1 ELSE 0 END AS is_primary_key
        FROM pragma_table_info('temperature_profiles')
        
UNION ALL

        SELECT
            'uniprot_annotations' AS table_name,
            cid,
            name AS column_name,
            type AS data_type,
            CASE WHEN "notnull" THEN 1 ELSE 0 END AS not_null,
            COALESCE(dflt_value, '') AS default_value,
            CASE WHEN pk THEN 1 ELSE 0 END AS is_primary_key
        FROM pragma_table_info('uniprot_annotations')
        
UNION ALL

        SELECT
            'uniprot_protein_links' AS table_name,
            cid,
            name AS column_name,
            type AS data_type,
            CASE WHEN "notnull" THEN 1 ELSE 0 END AS not_null,
            COALESCE(dflt_value, '') AS default_value,
            CASE WHEN pk THEN 1 ELSE 0 END AS is_primary_key
        FROM pragma_table_info('uniprot_protein_links')
        
UNION ALL

        SELECT
            'uniprot_structures' AS table_name,
            cid,
            name AS column_name,
            type AS data_type,
            CASE WHEN "notnull" THEN 1 ELSE 0 END AS not_null,
            COALESCE(dflt_value, '') AS default_value,
            CASE WHEN pk THEN 1 ELSE 0 END AS is_primary_key
        FROM pragma_table_info('uniprot_structures')
        
UNION ALL

        SELECT
            'viral_isolates' AS table_name,
            cid,
            name AS column_name,
            type AS data_type,
            CASE WHEN "notnull" THEN 1 ELSE 0 END AS not_null,
            COALESCE(dflt_value, '') AS default_value,
            CASE WHEN pk THEN 1 ELSE 0 END AS is_primary_key
        FROM pragma_table_info('viral_isolates')
        
UNION ALL

        SELECT
            'viral_proteins' AS table_name,
            cid,
            name AS column_name,
            type AS data_type,
            CASE WHEN "notnull" THEN 1 ELSE 0 END AS not_null,
            COALESCE(dflt_value, '') AS default_value,
            CASE WHEN pk THEN 1 ELSE 0 END AS is_primary_key
        FROM pragma_table_info('viral_proteins')
        
UNION ALL

        SELECT
            'viral_proteins_nr' AS table_name,
            cid,
            name AS column_name,
            type AS data_type,
            CASE WHEN "notnull" THEN 1 ELSE 0 END AS not_null,
            COALESCE(dflt_value, '') AS default_value,
            CASE WHEN pk THEN 1 ELSE 0 END AS is_primary_key
        FROM pragma_table_info('viral_proteins_nr')
        
UNION ALL

        SELECT
            'viralzone_families' AS table_name,
            cid,
            name AS column_name,
            type AS data_type,
            CASE WHEN "notnull" THEN 1 ELSE 0 END AS not_null,
            COALESCE(dflt_value, '') AS default_value,
            CASE WHEN pk THEN 1 ELSE 0 END AS is_primary_key
        FROM pragma_table_info('viralzone_families')
        
UNION ALL

        SELECT
            'viralzone_gene_tables' AS table_name,
            cid,
            name AS column_name,
            type AS data_type,
            CASE WHEN "notnull" THEN 1 ELSE 0 END AS not_null,
            COALESCE(dflt_value, '') AS default_value,
            CASE WHEN pk THEN 1 ELSE 0 END AS is_primary_key
        FROM pragma_table_info('viralzone_gene_tables')
        
UNION ALL

        SELECT
            'virulence_profiles' AS table_name,
            cid,
            name AS column_name,
            type AS data_type,
            CASE WHEN "notnull" THEN 1 ELSE 0 END AS not_null,
            COALESCE(dflt_value, '') AS default_value,
            CASE WHEN pk THEN 1 ELSE 0 END AS is_primary_key
        FROM pragma_table_info('virulence_profiles')
        
UNION ALL

        SELECT
            'virus_aliases' AS table_name,
            cid,
            name AS column_name,
            type AS data_type,
            CASE WHEN "notnull" THEN 1 ELSE 0 END AS not_null,
            COALESCE(dflt_value, '') AS default_value,
            CASE WHEN pk THEN 1 ELSE 0 END AS is_primary_key
        FROM pragma_table_info('virus_aliases')
        
UNION ALL

        SELECT
            'virus_ictv_mappings' AS table_name,
            cid,
            name AS column_name,
            type AS data_type,
            CASE WHEN "notnull" THEN 1 ELSE 0 END AS not_null,
            COALESCE(dflt_value, '') AS default_value,
            CASE WHEN pk THEN 1 ELSE 0 END AS is_primary_key
        FROM pragma_table_info('virus_ictv_mappings')
        
UNION ALL

        SELECT
            'virus_ictv_status' AS table_name,
            cid,
            name AS column_name,
            type AS data_type,
            CASE WHEN "notnull" THEN 1 ELSE 0 END AS not_null,
            COALESCE(dflt_value, '') AS default_value,
            CASE WHEN pk THEN 1 ELSE 0 END AS is_primary_key
        FROM pragma_table_info('virus_ictv_status')
        
UNION ALL

        SELECT
            'virus_master' AS table_name,
            cid,
            name AS column_name,
            type AS data_type,
            CASE WHEN "notnull" THEN 1 ELSE 0 END AS not_null,
            COALESCE(dflt_value, '') AS default_value,
            CASE WHEN pk THEN 1 ELSE 0 END AS is_primary_key
        FROM pragma_table_info('virus_master')
        
UNION ALL

        SELECT
            'virus_master_review_queue' AS table_name,
            cid,
            name AS column_name,
            type AS data_type,
            CASE WHEN "notnull" THEN 1 ELSE 0 END AS not_null,
            COALESCE(dflt_value, '') AS default_value,
            CASE WHEN pk THEN 1 ELSE 0 END AS is_primary_key
        FROM pragma_table_info('virus_master_review_queue')
        
UNION ALL

        SELECT
            'virus_search_fts' AS table_name,
            cid,
            name AS column_name,
            type AS data_type,
            CASE WHEN "notnull" THEN 1 ELSE 0 END AS not_null,
            COALESCE(dflt_value, '') AS default_value,
            CASE WHEN pk THEN 1 ELSE 0 END AS is_primary_key
        FROM pragma_table_info('virus_search_fts')
        
UNION ALL

        SELECT
            'virus_search_fts_config' AS table_name,
            cid,
            name AS column_name,
            type AS data_type,
            CASE WHEN "notnull" THEN 1 ELSE 0 END AS not_null,
            COALESCE(dflt_value, '') AS default_value,
            CASE WHEN pk THEN 1 ELSE 0 END AS is_primary_key
        FROM pragma_table_info('virus_search_fts_config')
        
UNION ALL

        SELECT
            'virus_search_fts_content' AS table_name,
            cid,
            name AS column_name,
            type AS data_type,
            CASE WHEN "notnull" THEN 1 ELSE 0 END AS not_null,
            COALESCE(dflt_value, '') AS default_value,
            CASE WHEN pk THEN 1 ELSE 0 END AS is_primary_key
        FROM pragma_table_info('virus_search_fts_content')
        
UNION ALL

        SELECT
            'virus_search_fts_data' AS table_name,
            cid,
            name AS column_name,
            type AS data_type,
            CASE WHEN "notnull" THEN 1 ELSE 0 END AS not_null,
            COALESCE(dflt_value, '') AS default_value,
            CASE WHEN pk THEN 1 ELSE 0 END AS is_primary_key
        FROM pragma_table_info('virus_search_fts_data')
        
UNION ALL

        SELECT
            'virus_search_fts_docsize' AS table_name,
            cid,
            name AS column_name,
            type AS data_type,
            CASE WHEN "notnull" THEN 1 ELSE 0 END AS not_null,
            COALESCE(dflt_value, '') AS default_value,
            CASE WHEN pk THEN 1 ELSE 0 END AS is_primary_key
        FROM pragma_table_info('virus_search_fts_docsize')
        
UNION ALL

        SELECT
            'virus_search_fts_idx' AS table_name,
            cid,
            name AS column_name,
            type AS data_type,
            CASE WHEN "notnull" THEN 1 ELSE 0 END AS not_null,
            COALESCE(dflt_value, '') AS default_value,
            CASE WHEN pk THEN 1 ELSE 0 END AS is_primary_key
        FROM pragma_table_info('virus_search_fts_idx')
        
UNION ALL

        SELECT
            'virus_vmr_mappings' AS table_name,
            cid,
            name AS column_name,
            type AS data_type,
            CASE WHEN "notnull" THEN 1 ELSE 0 END AS not_null,
            COALESCE(dflt_value, '') AS default_value,
            CASE WHEN pk THEN 1 ELSE 0 END AS is_primary_key
        FROM pragma_table_info('virus_vmr_mappings')
        
UNION ALL

        SELECT
            'worms_search_log' AS table_name,
            cid,
            name AS column_name,
            type AS data_type,
            CASE WHEN "notnull" THEN 1 ELSE 0 END AS not_null,
            COALESCE(dflt_value, '') AS default_value,
            CASE WHEN pk THEN 1 ELSE 0 END AS is_primary_key
        FROM pragma_table_info('worms_search_log')
        
ORDER BY table_name, cid;

-- view: v_data_provenance_summary
CREATE VIEW v_data_provenance_summary AS
                SELECT
                    data_source,
                    confidence_level,
                    COUNT(*) as record_count,
                    GROUP_CONCAT(DISTINCT table_name) as source_tables
                FROM data_provenance
                GROUP BY data_source, confidence_level
                ORDER BY record_count DESC;

-- view: v_imprecise_coordinates
CREATE VIEW v_imprecise_coordinates AS
                    SELECT
                        collection_id,
                        country,
                        province,
                        city,
                        site_name,
                        latitude,
                        longitude,
                        coordinate_precision,
                        collection_year,
                        'Coordinates are centroid/imprecise' as quality_note
                    FROM sample_collections
                    WHERE coordinate_precision IS NOT NULL
                      AND coordinate_precision != 'precise'
                      AND coordinate_precision != 'exact_or_reported'
                    ORDER BY country, province;

-- view: v_infection_records_missing_host
CREATE VIEW v_infection_records_missing_host AS
            SELECT ir.*, vi.accession, vm.canonical_name
            FROM infection_records ir
            LEFT JOIN viral_isolates vi ON vi.isolate_id = ir.isolate_id
            LEFT JOIN virus_master vm ON vm.master_id = vi.master_id
            WHERE ir.host_id IS NULL;

-- view: v_inferred_temperature
CREATE VIEW v_inferred_temperature AS
                    SELECT *, 'temperature_profiles' as source_table
                    FROM temperature_profiles
                    WHERE ((notes LIKE '%FAMILY_INFERRED%' OR notes LIKE '%family_inferred%'))
                    ORDER BY virus_name;

-- view: v_inferred_virulence
CREATE VIEW v_inferred_virulence AS
                    SELECT *, 'virulence_profiles' as source_table
                    FROM virulence_profiles
                    WHERE ((notes LIKE '%FAMILY_INFERRED%' OR notes LIKE '%family_inferred%'))
                    ORDER BY virus_name;

-- view: v_interpro_annotations_positioned
CREATE VIEW v_interpro_annotations_positioned AS
            SELECT *
            FROM interpro_annotations
            WHERE start_pos IS NOT NULL AND end_pos IS NOT NULL;

-- view: v_interpro_missing_positions
CREATE VIEW v_interpro_missing_positions AS
            SELECT *
            FROM interpro_annotations
            WHERE start_pos IS NULL OR end_pos IS NULL;

-- view: v_isolate_reference_unique
CREATE VIEW v_isolate_reference_unique AS
            SELECT l.isolate_id,
                   l.reference_id,
                   MIN(l.link_id) AS representative_link_id,
                   GROUP_CONCAT(DISTINCT l.link_type) AS link_types,
                   CASE
                       WHEN EXISTS (
                           SELECT 1 FROM infection_records ir
                           WHERE ir.isolate_id = l.isolate_id
                             AND ir.reference_id = l.reference_id
                       )
                       THEN 1 ELSE 0
                   END AS also_in_infection_records,
                   MIN(l.priority) AS best_priority
            FROM isolate_reference_links l
            GROUP BY l.isolate_id, l.reference_id;

-- view: v_isolates_without_infection_records
CREATE VIEW v_isolates_without_infection_records AS
            SELECT vi.isolate_id, vi.accession, vm.canonical_name, vi.virus_name,
                   vi.reference_id, vi.completeness
            FROM viral_isolates vi
            LEFT JOIN virus_master vm ON vm.master_id = vi.master_id
            WHERE NOT EXISTS (
                SELECT 1 FROM infection_records ir WHERE ir.isolate_id = vi.isolate_id
            );

-- view: v_isolates_without_proteins
CREATE VIEW v_isolates_without_proteins AS
            SELECT vi.isolate_id, vi.accession, vm.canonical_name, vi.virus_name,
                   vi.completeness, vi.sequence_length, vi.genome_length
            FROM viral_isolates vi
            LEFT JOIN virus_master vm ON vm.master_id = vi.master_id
            WHERE NOT EXISTS (
                SELECT 1 FROM viral_proteins vp WHERE vp.isolate_id = vi.isolate_id
            );

-- view: v_low_confidence_structures
CREATE VIEW v_low_confidence_structures AS
            SELECT ps.*, vp.protein_accession, vp.protein_name, vi.accession AS isolate_accession,
                   vm.canonical_name
            FROM protein_structures ps
            LEFT JOIN viral_proteins vp ON vp.protein_id = ps.protein_id
            LEFT JOIN viral_isolates vi ON vi.isolate_id = vp.isolate_id
            LEFT JOIN virus_master vm ON vm.master_id = vi.master_id
            WHERE COALESCE(ps.plddt_normalized_100,
                           CASE WHEN ps.plddt_score <= 1.0 THEN ps.plddt_score * 100.0 ELSE ps.plddt_score END) < 50
               OR ps.publication_use = 'do_not_use_for_primary_claims';

-- view: v_publication_profile_status
CREATE VIEW v_publication_profile_status AS
            SELECT 'virulence_profiles' AS table_name,
                   profile_id AS record_id,
                   virus_name,
                   data_origin,
                   data_source_type,
                   confidence,
                   publication_use
            FROM virulence_profiles
            UNION ALL
            SELECT 'temperature_profiles' AS table_name,
                   profile_id AS record_id,
                   virus_name,
                   data_origin,
                   data_source_type,
                   confidence,
                   publication_use
            FROM temperature_profiles;

-- view: v_references_missing_identifiers
CREATE VIEW v_references_missing_identifiers AS
            SELECT reference_id, title, authors, journal, year, pmid, doi
            FROM ref_literatures
            WHERE TRIM(COALESCE(pmid, '')) = ''
              AND TRIM(COALESCE(doi, '')) = '';

-- view: v_unverified_literature
CREATE VIEW v_unverified_literature AS
                SELECT
                    reference_id,
                    pmid,
                    title,
                    authors,
                    journal,
                    year,
                    doi,
                    CASE
                        WHEN (pmid IS NULL OR pmid = '') AND (doi IS NULL OR doi = '') THEN 'NO_ID'
                        WHEN pmid IS NULL OR pmid = '' THEN 'NO_PMID'
                        WHEN doi IS NULL OR doi = '' THEN 'NO_DOI'
                        ELSE 'HAS_BOTH'
                    END as id_status
                FROM ref_literatures
                WHERE (pmid IS NULL OR pmid = '')
                   OR (doi IS NULL OR doi = '')
                ORDER BY year DESC;

-- view: v_viral_isolate_name_reconciled
CREATE VIEW v_viral_isolate_name_reconciled AS
            SELECT vi.isolate_id,
                   vi.accession,
                   vi.virus_name AS isolate_reported_virus_name,
                   vm.canonical_name AS canonical_virus_name,
                   CASE
                       WHEN TRIM(COALESCE(vi.virus_name, '')) = ''
                            OR TRIM(COALESCE(vm.canonical_name, '')) = ''
                       THEN 'missing_name'
                       WHEN LOWER(TRIM(vi.virus_name)) = LOWER(TRIM(vm.canonical_name))
                       THEN 'match'
                       ELSE 'alias_or_conflict_requires_review'
                   END AS name_reconciliation_status,
                   vm.master_id
            FROM viral_isolates vi
            LEFT JOIN virus_master vm ON vm.master_id = vi.master_id;

-- view: v_viral_isolate_taxonomy_reconciled
CREATE VIEW v_viral_isolate_taxonomy_reconciled AS
            SELECT vi.isolate_id,
                   vi.accession,
                   vi.taxon_family AS isolate_raw_family,
                   vm.virus_family AS canonical_family,
                   vi.taxon_genus AS isolate_raw_genus,
                   vm.virus_genus AS canonical_genus,
                   CASE
                       WHEN TRIM(COALESCE(vi.taxon_family, '')) = ''
                            OR TRIM(COALESCE(vm.virus_family, '')) = ''
                       THEN 'missing_family'
                       WHEN LOWER(TRIM(vi.taxon_family)) = LOWER(TRIM(vm.virus_family))
                       THEN 'match'
                       ELSE 'conflict_requires_taxonomy_review'
                   END AS family_reconciliation_status,
                   vm.master_id
            FROM viral_isolates vi
            LEFT JOIN virus_master vm ON vm.master_id = vi.master_id;

COMMIT;
