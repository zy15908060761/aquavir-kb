-- AquaVir-KB Database Schema (generated from SQLite)
-- Target: PostgreSQL 16
-- Generated: 2026-06-05

CREATE TABLE abstract_mention_fulltext_worklist (
            worklist_id SERIAL PRIMARY KEY,
            reference_id INTEGER NOT NULL UNIQUE,
            evidence_count INTEGER NOT NULL,
            high_risk_evidence_count INTEGER NOT NULL,
            host_range_count INTEGER NOT NULL,
            pmid TEXT,
            doi TEXT,
            title TEXT,
            year TEXT,
            existing_fulltext_status TEXT,
            priority TEXT NOT NULL,
            recommended_action TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'open',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(reference_id) REFERENCES ref_literatures(reference_id)
        );

CREATE TABLE accession_duplicate_review_queue (
            queue_id SERIAL PRIMARY KEY,
            run_ts TEXT NOT NULL,
            dedupe_key TEXT NOT NULL,
            isolate_ids TEXT NOT NULL,
            accession_values TEXT NOT NULL,
            virus_names TEXT,
            master_ids TEXT,
            priority TEXT NOT NULL DEFAULT 'P0',
            status TEXT NOT NULL DEFAULT 'open',
            recommended_action TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(dedupe_key, isolate_ids)
        );

CREATE TABLE biorxiv_preprints (
            preprint_id SERIAL PRIMARY KEY,
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

CREATE TABLE biosample_links (
            link_id SERIAL PRIMARY KEY,
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

CREATE TABLE conservative_cleanup_runs (
            run_id SERIAL PRIMARY KEY,
            run_at TEXT NOT NULL,
            script_name TEXT NOT NULL,
            notes TEXT
        );

CREATE TABLE conservative_fk_quarantine (
            quarantine_id SERIAL PRIMARY KEY,
            run_id INTEGER NOT NULL,
            table_name TEXT NOT NULL,
            rowid_value INTEGER NOT NULL,
            parent_table TEXT NOT NULL,
            fk_id INTEGER,
            action TEXT NOT NULL,
            row_json TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

CREATE TABLE control_management_methods (
            control_id SERIAL PRIMARY KEY,
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

CREATE TABLE core_genes (
        gene_id SERIAL PRIMARY KEY,
        virus_species VARCHAR(200) NOT NULL,
        gene_symbol VARCHAR(100),
        protein_name VARCHAR(500),
        functional_category VARCHAR(50),
        conservation_rate DOUBLE PRECISION,
        total_isolates INTEGER,
        present_isolates INTEGER,
        avg_identity DOUBLE PRECISION,
        function_summary TEXT, taxonomic_level TEXT DEFAULT 'species', taxonomic_group TEXT, min_coverage_pct DOUBLE PRECISION, core_status TEXT, core_threshold_note TEXT,
        UNIQUE(virus_species, gene_symbol)
    );

CREATE TABLE crustacean_hosts (
        host_id SERIAL PRIMARY KEY,
        scientific_name VARCHAR(100) NOT NULL UNIQUE,
        common_name_cn VARCHAR(100),
        taxon_order VARCHAR(100),
        taxon_family VARCHAR(100),
        host_group VARCHAR(50),
        habitat VARCHAR(100),
        aquaculture_status VARCHAR(50),
        iucn_status VARCHAR(50)
    , host_type VARCHAR(30), iucn_assessment_year VARCHAR(10), phylum VARCHAR(50), class VARCHAR(50), host_scope_status VARCHAR(30)
            DEFAULT 'needs_review', public_visibility TEXT DEFAULT 'public');

CREATE TABLE curation_conflicts (
            conflict_id SERIAL PRIMARY KEY,
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

CREATE TABLE curation_logs (
            log_id SERIAL PRIMARY KEY,
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

CREATE TABLE curation_priority_queue (
            queue_id SERIAL PRIMARY KEY,
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

CREATE TABLE curation_vocab_terms (
            vocab_id SERIAL PRIMARY KEY,
            category TEXT NOT NULL,
            term TEXT NOT NULL,
            description TEXT,
            active INTEGER DEFAULT 1 CHECK (active IN (0, 1)),
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(category, term)
        );

CREATE TABLE data_provenance (
            provenance_id SERIAL PRIMARY KEY,
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

CREATE TABLE database_maintenance_log (
            log_id SERIAL PRIMARY KEY,
            action TEXT NOT NULL,
            details_json TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

CREATE TABLE diagnostic_method_review_queue (
            review_id SERIAL PRIMARY KEY,
            method_id INTEGER NOT NULL UNIQUE,
            issue_type TEXT NOT NULL,
            recommended_action TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            status TEXT DEFAULT 'open' CHECK (status IN ('open', 'resolved', 'ignored')),
            FOREIGN KEY(method_id) REFERENCES diagnostic_methods(method_id)
        );

CREATE TABLE diagnostic_methods (
            method_id SERIAL PRIMARY KEY,
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

CREATE TABLE entity_quality_scores (
            score_id SERIAL PRIMARY KEY,
            run_id INTEGER NOT NULL,
            entity_type TEXT NOT NULL,
            entity_id INTEGER NOT NULL,
            virus_master_id INTEGER,
            host_id INTEGER,
            isolate_id INTEGER,
            reference_id INTEGER,
            completeness_score INTEGER NOT NULL,
            traceability_score INTEGER NOT NULL,
            consistency_score INTEGER NOT NULL,
            evidence_score INTEGER NOT NULL,
            artifact_penalty INTEGER NOT NULL,
            blocking_issue_count INTEGER NOT NULL,
            quality_grade TEXT NOT NULL,
            reasons TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (run_id) REFERENCES qaqc_runs(run_id)
        );

CREATE TABLE environmental_evidence (
            environmental_id SERIAL PRIMARY KEY,
            virus_master_id INTEGER NOT NULL,
            evidence_type TEXT NOT NULL CHECK (
                evidence_type IN ('optimal_temperature', 'survival_range', 'thermal_inactivation', 'cold_storage', 'climate_impact', 'salinity', 'ph', 'other')
            ),
            value_min DOUBLE PRECISION,
            value_max DOUBLE PRECISION,
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

CREATE TABLE epmc_literature (
            epmc_id SERIAL PRIMARY KEY,
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
            relative_citation_ratio DOUBLE PRECISION,
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

CREATE TABLE epmc_preprints (
            preprint_id SERIAL PRIMARY KEY,
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

CREATE TABLE evidence_dedup_quarantine (
            quarantine_id SERIAL PRIMARY KEY,
            run_id        INTEGER NOT NULL REFERENCES evidence_dedup_runs(run_id),
            evidence_id   INTEGER NOT NULL,
            full_record   TEXT NOT NULL,
            reason        TEXT NOT NULL,
            created_at    TEXT NOT NULL
        );

CREATE TABLE evidence_dedup_runs (
            run_id        SERIAL PRIMARY KEY,
            run_ts        TEXT NOT NULL,
            phase         TEXT NOT NULL,
            dry_run       INTEGER NOT NULL DEFAULT 0,
            removed_count INTEGER,
            notes         TEXT
        );

CREATE TABLE evidence_duplicate_suppression_log (
            log_id SERIAL PRIMARY KEY,
            run_ts TEXT NOT NULL,
            duplicate_key TEXT NOT NULL,
            canonical_evidence_id INTEGER NOT NULL,
            suppressed_evidence_id INTEGER NOT NULL,
            original_status TEXT,
            original_strength TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP, status TEXT NOT NULL DEFAULT 'active',
            UNIQUE(run_ts, suppressed_evidence_id),
            FOREIGN KEY(canonical_evidence_id) REFERENCES evidence_records(evidence_id),
            FOREIGN KEY(suppressed_evidence_id) REFERENCES evidence_records(evidence_id)
        );

CREATE TABLE evidence_isolate_links (
            link_id       SERIAL PRIMARY KEY,
            evidence_id   INTEGER NOT NULL REFERENCES evidence_records(evidence_id),
            isolate_id    INTEGER NOT NULL REFERENCES viral_isolates(isolate_id),
            link_source   TEXT NOT NULL DEFAULT 'dedup_consolidation',
            created_at    TEXT NOT NULL,
            UNIQUE(evidence_id, isolate_id)
        );

CREATE TABLE "evidence_records" (
            evidence_id SERIAL PRIMARY KEY,
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
            value_numeric_min DOUBLE PRECISION,
            value_numeric_max DOUBLE PRECISION,
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
            notes TEXT, source_url TEXT, evidence_origin TEXT DEFAULT "secondary",
            FOREIGN KEY (virus_master_id) REFERENCES virus_master(master_id),
            FOREIGN KEY (host_id) REFERENCES crustacean_hosts(host_id),
            FOREIGN KEY (isolate_id) REFERENCES viral_isolates(isolate_id),
            FOREIGN KEY (reference_id) REFERENCES ref_literatures(reference_id),
            FOREIGN KEY (source_id) REFERENCES external_sources(source_id)
        );

CREATE TABLE evidence_review_priority_queue (
                    queue_id SERIAL PRIMARY KEY,
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

CREATE TABLE external_sources (
            source_id SERIAL PRIMARY KEY,
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

CREATE TABLE external_xrefs (
            xref_id SERIAL PRIMARY KEY,
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

CREATE TABLE fulltext_evidence_rescue_candidates (
            candidate_id SERIAL PRIMARY KEY,
            run_id INTEGER NOT NULL,
            source_evidence_id INTEGER NOT NULL,
            source_evidence_type TEXT NOT NULL,
            reference_id INTEGER NOT NULL,
            fulltext_id INTEGER,
            section_id INTEGER,
            section_type TEXT,
            section_title TEXT,
            sentence TEXT NOT NULL,
            sentence_hash TEXT NOT NULL,
            virus_master_id INTEGER,
            host_id INTEGER,
            matched_virus_names TEXT,
            matched_host_names TEXT,
            matched_terms TEXT NOT NULL,
            confidence_score INTEGER NOT NULL,
            confidence_label TEXT NOT NULL,
            rescue_action TEXT NOT NULL DEFAULT 'manual_review',
            promotion_status TEXT NOT NULL DEFAULT 'candidate',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(run_id) REFERENCES fulltext_evidence_rescue_runs(run_id),
            FOREIGN KEY(source_evidence_id) REFERENCES evidence_records(evidence_id),
            FOREIGN KEY(reference_id) REFERENCES ref_literatures(reference_id),
            FOREIGN KEY(section_id) REFERENCES literature_fulltext_sections(section_id),
            UNIQUE(run_id, source_evidence_id, section_id, sentence_hash)
        );

CREATE TABLE "fulltext_evidence_rescue_candidates_legacy_20260528_104551" (
            candidate_id SERIAL PRIMARY KEY,
            run_id INTEGER NOT NULL,
            source_evidence_id INTEGER NOT NULL,
            source_evidence_type TEXT NOT NULL,
            reference_id INTEGER NOT NULL,
            fulltext_id INTEGER,
            section_id INTEGER,
            section_type TEXT,
            section_title TEXT,
            sentence TEXT NOT NULL,
            sentence_hash TEXT NOT NULL,
            virus_master_id INTEGER,
            host_id INTEGER,
            matched_virus_names TEXT,
            matched_host_names TEXT,
            matched_terms TEXT NOT NULL,
            confidence_score INTEGER NOT NULL,
            confidence_label TEXT NOT NULL,
            rescue_action TEXT NOT NULL DEFAULT 'manual_review',
            promotion_status TEXT NOT NULL DEFAULT 'candidate',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(run_id) REFERENCES fulltext_evidence_rescue_runs(run_id),
            FOREIGN KEY(source_evidence_id) REFERENCES evidence_records(evidence_id),
            FOREIGN KEY(reference_id) REFERENCES ref_literatures(reference_id),
            FOREIGN KEY(section_id) REFERENCES literature_fulltext_sections(section_id),
            UNIQUE(source_evidence_id, section_id, sentence_hash)
        );

CREATE TABLE fulltext_evidence_rescue_review_queue (
            review_id SERIAL PRIMARY KEY,
            source_run_id INTEGER NOT NULL,
            source_evidence_type TEXT NOT NULL,
            reference_id INTEGER NOT NULL,
            sentence_hash TEXT NOT NULL,
            representative_candidate_id INTEGER NOT NULL,
            source_evidence_ids TEXT NOT NULL,
            source_evidence_count INTEGER NOT NULL,
            max_confidence_score INTEGER NOT NULL,
            confidence_label TEXT NOT NULL,
            priority TEXT NOT NULL,
            section_type TEXT,
            section_title TEXT,
            virus_master_ids TEXT,
            host_ids TEXT,
            matched_terms TEXT,
            sentence TEXT NOT NULL,
            review_status TEXT NOT NULL DEFAULT 'open',
            recommended_action TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(source_run_id, source_evidence_type, reference_id, sentence_hash)
        );

CREATE TABLE fulltext_evidence_rescue_runs (
            run_id SERIAL PRIMARY KEY,
            run_ts TEXT NOT NULL,
            target_rule TEXT NOT NULL,
            target_evidence_count INTEGER NOT NULL,
            target_reference_count INTEGER NOT NULL,
            references_with_sections INTEGER NOT NULL,
            candidate_count INTEGER NOT NULL DEFAULT 0,
            script_name TEXT NOT NULL,
            notes TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

CREATE TABLE fulltext_evidence_rescue_targets (
            run_id INTEGER NOT NULL,
            source_evidence_id INTEGER NOT NULL,
            source_evidence_type TEXT NOT NULL,
            reference_id INTEGER NOT NULL,
            virus_master_id INTEGER,
            host_id INTEGER,
            polluted_claim TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY(run_id, source_evidence_id),
            FOREIGN KEY(run_id) REFERENCES fulltext_evidence_rescue_runs(run_id),
            FOREIGN KEY(source_evidence_id) REFERENCES evidence_records(evidence_id),
            FOREIGN KEY(reference_id) REFERENCES ref_literatures(reference_id)
        );

CREATE TABLE gbif_occurrences (
            occurrence_id SERIAL PRIMARY KEY,
            host_id INTEGER,
            scientific_name TEXT NOT NULL,
            gbif_taxon_key INTEGER,
            country TEXT,
            continent TEXT,
            decimal_latitude DOUBLE PRECISION,
            decimal_longitude DOUBLE PRECISION,
            locality TEXT,
            year INTEGER,
            basis_of_record TEXT,
            dataset_name TEXT,
            occurrence_count INTEGER DEFAULT 1,
            fetched_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (host_id) REFERENCES crustacean_hosts(host_id)
        );

CREATE TABLE gbif_species_summary (
            summary_id SERIAL PRIMARY KEY,
            host_id INTEGER,
            scientific_name TEXT NOT NULL,
            gbif_taxon_key INTEGER,
            total_occurrences INTEGER,
            num_countries INTEGER,
            min_lat DOUBLE PRECISION,
            max_lat DOUBLE PRECISION,
            min_lon DOUBLE PRECISION,
            max_lon DOUBLE PRECISION,
            countries_json TEXT,
            first_record_year INTEGER,
            last_record_year INTEGER,
            fetched_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (host_id) REFERENCES crustacean_hosts(host_id)
        );

CREATE TABLE genbank_recovery_candidates (
            candidate_id SERIAL PRIMARY KEY,
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

CREATE TABLE genome_pairwise_identity (
        identity_id SERIAL PRIMARY KEY,
        accession_a VARCHAR(50) NOT NULL,
        accession_b VARCHAR(50) NOT NULL,
        virus_species VARCHAR(200),
        identity_percent DOUBLE PRECISION,
        shared_kmers INTEGER,
        total_unique_kmers INTEGER,
        method TEXT DEFAULT 'kmer_jaccard_k11',
        UNIQUE(accession_a, accession_b)
    );

CREATE TABLE genome_synteny_blocks (
        block_id SERIAL PRIMARY KEY,
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

CREATE TABLE geo_datasets (
            geo_id SERIAL PRIMARY KEY,
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

CREATE TABLE geo_virus_links (
            link_id SERIAL PRIMARY KEY,
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

CREATE TABLE geography_quality_profiles (
            geo_profile_id SERIAL PRIMARY KEY,
            isolate_id INTEGER NOT NULL UNIQUE,
            collection_id INTEGER,
            raw_country TEXT,
            standardized_country TEXT,
            continent TEXT,
            province_state TEXT,
            city TEXT,
            specific_site TEXT,
            latitude DOUBLE PRECISION,
            longitude DOUBLE PRECISION,
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

CREATE TABLE host_aliases (
            alias_id SERIAL PRIMARY KEY,
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

CREATE TABLE host_association_assessment (
            record_id INTEGER PRIMARY KEY,
            isolate_id INTEGER,
            master_id INTEGER,
            host_id INTEGER,
            host_association_method TEXT,
            association_tier TEXT NOT NULL,
            association_reason TEXT NOT NULL,
            display_recommendation TEXT NOT NULL,
            run_id INTEGER NOT NULL,
            assessed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

CREATE TABLE host_biology_profiles (
            profile_id SERIAL PRIMARY KEY,
            host_id INTEGER UNIQUE,
            scientific_name TEXT NOT NULL,
            habitat_type TEXT,
            depth_range_min DOUBLE PRECISION,
            depth_range_max DOUBLE PRECISION,
            temperature_tolerance_min DOUBLE PRECISION,
            temperature_tolerance_max DOUBLE PRECISION,
            salinity_tolerance TEXT,
            max_body_length_cm DOUBLE PRECISION,
            trophic_level DOUBLE PRECISION,
            feeding_type TEXT,
            generation_time_days INTEGER,
            longevity_days INTEGER,
            fecundity_min INTEGER,
            fecundity_max INTEGER,
            aquaculture_production_tonnes DOUBLE PRECISION,
            commercial_importance TEXT,
            data_sources_json TEXT,
            fetched_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (host_id) REFERENCES crustacean_hosts(host_id)
        );

CREATE TABLE host_ecological_traits (
            trait_id SERIAL PRIMARY KEY,
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

CREATE TABLE host_genome_artifacts(
  isolate_id INT,
  accession TEXT,
  virus_name TEXT,
  taxon_family TEXT,
  taxon_genus TEXT,
  taxon_species TEXT,
  genome_accession TEXT,
  genome_length INT,
  gc_content DOUBLE PRECISION,
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

CREATE TABLE host_range_evidence (
            host_range_id SERIAL PRIMARY KEY,
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

CREATE TABLE host_review_candidates (
            candidate_id SERIAL PRIMARY KEY,
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

CREATE TABLE host_taxonomy_profiles (
            profile_id SERIAL PRIMARY KEY,
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

CREATE TABLE ictv_taxonomy (
            ictv_id SERIAL PRIMARY KEY,
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

CREATE TABLE ictv_vmr (
            vmr_id SERIAL PRIMARY KEY,
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

CREATE TABLE infection_records (
        record_id SERIAL PRIMARY KEY,
        isolate_id INTEGER NOT NULL,
        host_id INTEGER,
        collection_id INTEGER,
        detection_method VARCHAR(100),
        disease_symptom TEXT,
        mortality_rate VARCHAR(50),
        isolation_source VARCHAR(100),
        reference_id INTEGER, time_consistency_flag TEXT, orphan_flag TEXT, host_association_method VARCHAR(50)
            DEFAULT 'co_occurrence_metagenomic',
        FOREIGN KEY (isolate_id) REFERENCES viral_isolates(isolate_id),
        FOREIGN KEY (host_id) REFERENCES crustacean_hosts(host_id),
        FOREIGN KEY (collection_id) REFERENCES sample_collections(collection_id),
        FOREIGN KEY (reference_id) REFERENCES ref_literatures(reference_id)
    );

CREATE TABLE interpro_annotations (
            interpro_anno_id SERIAL PRIMARY KEY,
            uniprot_id TEXT NOT NULL,
            interpro_id TEXT NOT NULL,
            interpro_name TEXT,
            interpro_type TEXT,
            source_database TEXT,
            start_pos INTEGER,
            end_pos INTEGER,
            score DOUBLE PRECISION,
            go_terms TEXT,
            pathways TEXT,
            protein_id INTEGER,
            fetched_at TEXT DEFAULT CURRENT_TIMESTAMP, "position_status" TEXT, "publication_use" TEXT,
            FOREIGN KEY (protein_id) REFERENCES viral_proteins(protein_id)
        );

CREATE TABLE interpro_go_terms (
        id SERIAL PRIMARY KEY,
        protein_id INTEGER,
        interpro_id TEXT,
        go_id TEXT,
        go_name TEXT,
        go_namespace TEXT,
        evidence_source TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(protein_id, interpro_id, go_id)
    );

CREATE TABLE isolate_curated_profiles (
            profile_id SERIAL PRIMARY KEY,
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
            gc_content DOUBLE PRECISION,
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
            latitude DOUBLE PRECISION,
            longitude DOUBLE PRECISION,
            elevation_m DOUBLE PRECISION,
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

CREATE TABLE isolate_reference_links (
            link_id SERIAL PRIMARY KEY,
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

CREATE TABLE kegg_annotations (
            kegg_id SERIAL PRIMARY KEY,
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

CREATE TABLE kegg_pathways (
            pathway_id SERIAL PRIMARY KEY,
            kegg_pathway_id TEXT NOT NULL,
            pathway_name TEXT,
            pathway_description TEXT,
            category TEXT,
            ko_count INTEGER,
            fetched_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

CREATE TABLE kegg_protein_pathways (
            link_id SERIAL PRIMARY KEY,
            ko_id TEXT NOT NULL,
            kegg_pathway_id TEXT NOT NULL,
            protein_id INTEGER,
            ncbi_protein_acc TEXT,
            UNIQUE(ko_id, kegg_pathway_id, ncbi_protein_acc),
            FOREIGN KEY (protein_id) REFERENCES viral_proteins(protein_id)
        );

CREATE TABLE literature_backfill_candidates (
            staging_id SERIAL PRIMARY KEY,
            run_id INTEGER NOT NULL,
            source_candidate_id INTEGER,
            reference_id INTEGER,
            pmid TEXT,
            doi TEXT,
            title TEXT,
            source_type TEXT NOT NULL,
            source_path TEXT,
            section TEXT,
            signal TEXT NOT NULL,
            target_tables TEXT,
            matched_terms TEXT,
            virus_master_ids TEXT,
            virus_names TEXT,
            host_ids TEXT,
            host_names TEXT,
            extracted_values_json TEXT,
            confidence TEXT NOT NULL CHECK (confidence IN ('high','medium','low','unknown')),
            strict_score INTEGER DEFAULT 0,
            strict_reason TEXT,
            evidence_text TEXT NOT NULL,
            curation_status TEXT NOT NULL DEFAULT 'needs_review'
                CHECK (curation_status IN ('needs_review','approved','rejected','promoted','superseded')),
            reviewer TEXT,
            review_notes TEXT,
            promoted_table TEXT,
            promoted_record_id INTEGER,
            evidence_hash TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP, dedupe_key TEXT,
            FOREIGN KEY (run_id) REFERENCES literature_backfill_runs(run_id),
            FOREIGN KEY (reference_id) REFERENCES ref_literatures(reference_id),
            UNIQUE(reference_id, signal, virus_master_ids, host_ids, evidence_hash)
        );

CREATE TABLE literature_backfill_runs (
            run_id SERIAL PRIMARY KEY,
            run_ts TEXT NOT NULL,
            source_file TEXT NOT NULL,
            source_file_sha256 TEXT NOT NULL,
            candidate_count INTEGER NOT NULL,
            strict_policy TEXT NOT NULL,
            notes TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

CREATE TABLE literature_evidence_candidates (
            candidate_id SERIAL PRIMARY KEY,
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
            relevance_score DOUBLE PRECISION DEFAULT 0,
            abstract TEXT,
            raw_json TEXT,
            curation_status TEXT DEFAULT 'needs_review',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (source_id) REFERENCES external_sources(source_id),
            FOREIGN KEY (master_id) REFERENCES virus_master(master_id),
            FOREIGN KEY (reference_id) REFERENCES ref_literatures(reference_id)
        );

CREATE TABLE literature_fulltext_quality (
            quality_id SERIAL PRIMARY KEY,
            reference_id INTEGER NOT NULL UNIQUE,
            best_fulltext_id INTEGER,
            file_exists INTEGER,
            file_type TEXT,
            file_size INTEGER,
            extractable_text_chars INTEGER,
            has_sections INTEGER,
            quality_label TEXT,
            needs_action TEXT,
            priority_score INTEGER,
            title TEXT,
            year TEXT,
            pmid TEXT,
            doi TEXT,
            pmcid TEXT,
            local_path TEXT,
            notes TEXT,
            audited_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(reference_id) REFERENCES ref_literatures(reference_id)
        );

CREATE TABLE literature_fulltext_sections (
            section_id SERIAL PRIMARY KEY,
            fulltext_id INTEGER NOT NULL,
            reference_id INTEGER NOT NULL,
            section_title TEXT,
            section_type TEXT,
            text TEXT NOT NULL,
            char_count INTEGER,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(fulltext_id) REFERENCES literature_fulltext_sources(fulltext_id),
            FOREIGN KEY(reference_id) REFERENCES ref_literatures(reference_id),
            UNIQUE(fulltext_id, section_title, section_type)
        );

CREATE TABLE literature_fulltext_sources (
            fulltext_id SERIAL PRIMARY KEY,
            reference_id INTEGER NOT NULL,
            pmid TEXT,
            doi TEXT,
            pmcid TEXT,
            source TEXT NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('local','downloaded','no_oa','failed','skipped')),
            oa_status TEXT,
            fulltext_url TEXT,
            pdf_url TEXT,
            xml_url TEXT,
            local_path TEXT,
            content_type TEXT,
            license TEXT,
            error TEXT,
            checked_at TEXT DEFAULT CURRENT_TIMESTAMP,
            raw_json TEXT,
            dedupe_key TEXT NOT NULL UNIQUE,
            FOREIGN KEY(reference_id) REFERENCES ref_literatures(reference_id)
        );

CREATE TABLE manual_ictv_bridges (
            bridge_id SERIAL PRIMARY KEY,
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

CREATE TABLE manual_review_priority_queue (
            review_id SERIAL PRIMARY KEY,
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

CREATE TABLE nr_protein_clusters (
        cluster_id SERIAL PRIMARY KEY,
        representative_seq_hash VARCHAR(64) UNIQUE,
        representative_aa_seq TEXT,
        representative_dna_seq TEXT,
        cluster_size INTEGER DEFAULT 1,
        cluster_method TEXT DEFAULT 'exact_match',
        cd_hit_threshold DOUBLE PRECISION,
        avg_length DOUBLE PRECISION,
        functional_category VARCHAR(50),
        source_count INTEGER DEFAULT 0,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    , cdhit50_cluster_id INTEGER, cdhit50_is_rep INTEGER DEFAULT 0);

CREATE TABLE nucleotide_records (
            record_id SERIAL PRIMARY KEY,
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

CREATE TABLE obis_occurrences (
            obis_id SERIAL PRIMARY KEY,
            host_id INTEGER,
            scientific_name TEXT NOT NULL,
            aphia_id INTEGER,
            decimal_latitude DOUBLE PRECISION,
            decimal_longitude DOUBLE PRECISION,
            depth_min DOUBLE PRECISION,
            depth_max DOUBLE PRECISION,
            temperature DOUBLE PRECISION,
            salinity DOUBLE PRECISION,
            country TEXT,
            locality TEXT,
            year_collected INTEGER,
            dataset_name TEXT,
            record_count INTEGER DEFAULT 1,
            fetched_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (host_id) REFERENCES crustacean_hosts(host_id)
        );

CREATE TABLE optimize_quality_quarantine (
            quarantine_id SERIAL PRIMARY KEY,
            run_id        INTEGER NOT NULL REFERENCES optimize_quality_runs(run_id),
            fix_name      TEXT NOT NULL,
            table_name    TEXT NOT NULL,
            row_pk        INTEGER NOT NULL,
            original_json TEXT,
            action        TEXT NOT NULL,
            created_at    TEXT NOT NULL
        );

CREATE TABLE optimize_quality_runs (
            run_id        SERIAL PRIMARY KEY,
            run_ts        TEXT NOT NULL,
            script_name   TEXT NOT NULL,
            dry_run       INTEGER NOT NULL DEFAULT 0,
            fixes_applied TEXT,
            notes         TEXT
        );

CREATE TABLE outbreak_events (
            outbreak_id SERIAL PRIMARY KEY,
            virus_master_id INTEGER NOT NULL,
            host_id INTEGER,
            country TEXT,
            province_state TEXT,
            start_year TEXT,
            end_year TEXT,
            event_summary TEXT NOT NULL,
            economic_impact TEXT,
            mortality_rate_min DOUBLE PRECISION,
            mortality_rate_max DOUBLE PRECISION,
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

CREATE TABLE pathogenicity_assessment (
            assessment_id SERIAL PRIMARY KEY,
            source_table TEXT NOT NULL,
            source_id INTEGER NOT NULL,
            virus_master_id INTEGER,
            pathogenicity_tier TEXT NOT NULL,
            pathogenicity_reason TEXT NOT NULL,
            claim_recommendation TEXT NOT NULL,
            run_id INTEGER NOT NULL,
            assessed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(source_table, source_id)
        );

CREATE TABLE pathogenicity_evidence (
            pathogenicity_id SERIAL PRIMARY KEY,
            virus_master_id INTEGER NOT NULL,
            host_id INTEGER,
            isolate_id INTEGER,
            reference_id INTEGER,
            virulence_level TEXT,
            virulence_label INTEGER,
            mortality_rate_min DOUBLE PRECISION,
            mortality_rate_max DOUBLE PRECISION,
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

CREATE TABLE phi_base_hits (
            hit_id SERIAL PRIMARY KEY,
            cluster_id INTEGER NOT NULL,
            phi_accession TEXT NOT NULL,
            phi_id TEXT,
            phi_gene TEXT,
            phi_organism TEXT,
            phi_phenotype TEXT,
            identity DOUBLE PRECISION,
            alignment_length INTEGER,
            evalue DOUBLE PRECISION,
            bit_score DOUBLE PRECISION,
            query_coverage DOUBLE PRECISION,
            FOREIGN KEY (cluster_id) REFERENCES nr_protein_clusters(cluster_id)
        );

CREATE TABLE pride_datasets (
            pride_id SERIAL PRIMARY KEY,
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

CREATE TABLE pride_virus_links (
            link_id SERIAL PRIMARY KEY,
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

CREATE TABLE protein_annotation_bridge (
            bridge_id SERIAL PRIMARY KEY,
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
            best_structure_confidence DOUBLE PRECISION,
            match_method TEXT,
            needs_review INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(protein_id, uniprot_id)
        );

CREATE TABLE protein_domains (
        domain_id SERIAL PRIMARY KEY,
        cluster_id INTEGER,
        protein_id INTEGER,
        reanno_id INTEGER,
        domain_source TEXT DEFAULT 'rule_based',
        domain_name TEXT,
        domain_description TEXT,
        start_pos INTEGER,
        end_pos INTEGER,
        confidence_score DOUBLE PRECISION,
        domain_model TEXT,
        interpro_id TEXT,
        pfam_id TEXT,
        cdd_id TEXT,
        FOREIGN KEY (cluster_id) REFERENCES nr_protein_clusters(cluster_id),
        FOREIGN KEY (protein_id) REFERENCES viral_proteins(protein_id),
        FOREIGN KEY (reanno_id) REFERENCES reannotated_orfs(reanno_id)
    );

CREATE TABLE protein_function_suggestions (
            suggestion_id SERIAL PRIMARY KEY,
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

CREATE TABLE protein_structures (
        structure_id SERIAL PRIMARY KEY,
        cluster_id INTEGER,
        protein_id INTEGER,
        reanno_id INTEGER,
        prediction_method TEXT DEFAULT 'esmfold',
        model_version TEXT,
        pdb_file_path TEXT,
        plddt_score DOUBLE PRECISION,
        sequence_length INTEGER,
        prediction_date TEXT DEFAULT CURRENT_TIMESTAMP,
        api_source TEXT DEFAULT 'https://api.esmatlas.com', "plddt_raw" DOUBLE PRECISION, "plddt_scale" TEXT, "plddt_normalized_100" DOUBLE PRECISION, "confidence_tier" TEXT, "publication_use" TEXT, "quality_notes" TEXT,
        FOREIGN KEY (cluster_id) REFERENCES nr_protein_clusters(cluster_id),
        FOREIGN KEY (protein_id) REFERENCES viral_proteins(protein_id),
        FOREIGN KEY (reanno_id) REFERENCES reannotated_orfs(reanno_id),
        UNIQUE(cluster_id, prediction_method)
    );

CREATE TABLE qaqc_conflicts (
            conflict_id SERIAL PRIMARY KEY,
            run_id INTEGER NOT NULL,
            conflict_type TEXT NOT NULL,
            entity_type TEXT NOT NULL,
            entity_id INTEGER,
            field_name TEXT NOT NULL,
            value_a TEXT,
            source_a TEXT,
            value_b TEXT,
            source_b TEXT,
            resolution_status TEXT NOT NULL DEFAULT 'open',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (run_id) REFERENCES qaqc_runs(run_id)
        );

CREATE TABLE qaqc_duplicates (
            duplicate_id SERIAL PRIMARY KEY,
            run_id INTEGER NOT NULL,
            duplicate_type TEXT NOT NULL,
            dedupe_key TEXT NOT NULL,
            table_name TEXT NOT NULL,
            record_ids TEXT NOT NULL,
            canonical_candidate_id INTEGER,
            conflict_fields TEXT,
            duplicate_count INTEGER NOT NULL,
            severity TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (run_id) REFERENCES qaqc_runs(run_id)
        );

CREATE TABLE qaqc_issues (
            issue_id SERIAL PRIMARY KEY,
            run_id INTEGER NOT NULL,
            rule_id TEXT NOT NULL,
            severity TEXT NOT NULL,
            table_name TEXT NOT NULL,
            primary_key TEXT,
            entity_type TEXT,
            entity_id INTEGER,
            field_name TEXT,
            observed_value TEXT,
            expected_rule TEXT,
            linked_virus_master_id INTEGER,
            linked_host_id INTEGER,
            linked_isolate_id INTEGER,
            linked_reference_id INTEGER,
            evidence_id INTEGER,
            action_hint TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (run_id) REFERENCES qaqc_runs(run_id)
        );

CREATE TABLE qaqc_runs (
            run_id SERIAL PRIMARY KEY,
            run_ts TEXT NOT NULL,
            db_path TEXT NOT NULL,
            script_name TEXT NOT NULL,
            notes TEXT
        );

CREATE TABLE qaqc_summary (
            summary_id SERIAL PRIMARY KEY,
            run_id INTEGER NOT NULL,
            rule_group TEXT NOT NULL,
            rule_id TEXT NOT NULL,
            severity TEXT NOT NULL,
            table_name TEXT NOT NULL,
            issue_count INTEGER NOT NULL,
            affected_entity_count INTEGER NOT NULL,
            pass_rate DOUBLE PRECISION,
            recommendation TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (run_id) REFERENCES qaqc_runs(run_id)
        );

CREATE TABLE quality_hardening_log (
            log_id SERIAL PRIMARY KEY,
            run_ts TEXT NOT NULL,
            script_name TEXT NOT NULL,
            action TEXT NOT NULL,
            affected_count INTEGER NOT NULL,
            details_json TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

CREATE TABLE rdrp_classification (
            sequence_id TEXT PRIMARY KEY,
            predicted_family TEXT,
            sh_support DOUBLE PRECISION,
            consensus_ratio DOUBLE PRECISION,
            num_known_in_clade INTEGER,
            clade_size INTEGER,
            confidence TEXT,
            family_distribution TEXT,
            method TEXT DEFAULT 'FastTree_phylogeny',
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

CREATE TABLE rdrp_classification_v2 (
        sequence_id TEXT PRIMARY KEY,
        predicted_family TEXT,
        final_confidence TEXT,
        fasttree_sh DOUBLE PRECISION,
        iqtree_bootstrap DOUBLE PRECISION,
        method TEXT,
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

CREATE TABLE reannotated_orfs (
        reanno_id SERIAL PRIMARY KEY,
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

CREATE TABLE reannotation_stats (
        isolate_id INTEGER PRIMARY KEY,
        original_orf_count INTEGER,
        reannotated_orf_count INTEGER,
        original_coverage_percent DOUBLE PRECISION,
        reannotated_coverage_percent DOUBLE PRECISION,
        avg_orf_length DOUBLE PRECISION,
        FOREIGN KEY (isolate_id) REFERENCES viral_isolates(isolate_id)
    );

CREATE TABLE ref_citation_metadata (
                reference_id INTEGER PRIMARY KEY,
                citation_count INTEGER,
                journal_impact TEXT,
                publication_type TEXT,
                mesh_terms TEXT,
                enriched_at TEXT,
                FOREIGN KEY (reference_id) REFERENCES ref_literatures(reference_id)
            );

CREATE TABLE ref_literatures (
        reference_id SERIAL PRIMARY KEY,
        pmid VARCHAR(20) UNIQUE,
        title TEXT,
        authors TEXT,
        journal TEXT,
        year VARCHAR(10),
        doi VARCHAR(100),
        abstract TEXT,
        keywords TEXT
    , notes TEXT);

CREATE TABLE release_manifest (
            manifest_id SERIAL PRIMARY KEY,
            release_name TEXT NOT NULL,
            generated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            table_name TEXT NOT NULL,
            row_count INTEGER,
            export_path TEXT,
            notes TEXT
        );

CREATE TABLE sample_collections (
        collection_id SERIAL PRIMARY KEY,
        country VARCHAR(100),
        province VARCHAR(100),
        city VARCHAR(100),
        site_name VARCHAR(200),
        latitude DOUBLE PRECISION,
        longitude DOUBLE PRECISION,
        collection_year VARCHAR(10),
        collection_date VARCHAR(20),
        source_type VARCHAR(50),
        note TEXT
    , continent VARCHAR(50), coordinate_precision TEXT DEFAULT 'country', coordinate_quality TEXT);

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

CREATE TABLE schema_deprecated_columns (
            deprecated_id SERIAL PRIMARY KEY,
            table_name TEXT NOT NULL,
            column_name TEXT NOT NULL,
            reason TEXT NOT NULL,
            recommended_action TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(table_name, column_name)
        );

CREATE TABLE schema_version (
            version_id    SERIAL PRIMARY KEY,
            applied_at    TEXT NOT NULL DEFAULT (datetime('now')),
            script_name   TEXT NOT NULL,
            description   TEXT
        );

CREATE TABLE sequence_curation_flags (
            flag_id SERIAL PRIMARY KEY,
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

CREATE TABLE sra_runs (
            sra_id SERIAL PRIMARY KEY,
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

CREATE TABLE string_interactions (
            interaction_id SERIAL PRIMARY KEY,
            protein_a TEXT NOT NULL,
            protein_b TEXT NOT NULL,
            protein_a_name TEXT,
            protein_b_name TEXT,
            combined_score DOUBLE PRECISION,
            neighborhood_score DOUBLE PRECISION,
            fusion_score DOUBLE PRECISION,
            cooccurrence_score DOUBLE PRECISION,
            coexpression_score DOUBLE PRECISION,
            experimental_score DOUBLE PRECISION,
            database_score DOUBLE PRECISION,
            textmining_score DOUBLE PRECISION,
            species_taxid INTEGER,
            source_uniprot_id TEXT,
            local_protein_id INTEGER,
            interaction_type TEXT DEFAULT 'functional',
            fetched_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (local_protein_id) REFERENCES viral_proteins(protein_id)
        );

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

CREATE TABLE temperature_profiles (
        profile_id SERIAL PRIMARY KEY,
        virus_name VARCHAR(200) NOT NULL UNIQUE,
        optimal_temp_min DOUBLE PRECISION,               -- Optimal temperature range min (°C)
        optimal_temp_max DOUBLE PRECISION,               -- Optimal temperature range max (°C)
        temp_range_min DOUBLE PRECISION,                 -- Survival temperature minimum (°C)
        temp_range_max DOUBLE PRECISION,                 -- Survival temperature maximum (°C)
        thermal_inactivation_temp DOUBLE PRECISION,      -- Temperature for thermal inactivation (°C)
        thermal_inactivation_time DOUBLE PRECISION,      -- Time for thermal inactivation (min)
        cold_storage_temp DOUBLE PRECISION,              -- Recommended cold storage temp (°C)
        cold_storage_viability VARCHAR(200), -- Viability under cold storage
        temp_sensitivity_notes TEXT,         -- Notes on temperature sensitivity
        climate_change_impact TEXT,          -- Projected impact of climate change
        data_source VARCHAR(500),            -- Literature source
        confidence VARCHAR(20),              -- 'High', 'Medium', 'Low'
        curation_date DATE,
        notes TEXT
    , "data_origin" TEXT, "data_source_type" TEXT, "publication_use" TEXT);

CREATE TABLE uniprot_annotations (
            annotation_id SERIAL PRIMARY KEY,
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

CREATE TABLE uniprot_protein_links (
        link_id SERIAL PRIMARY KEY,
        uniprot_id TEXT NOT NULL,
        ncbi_protein_acc TEXT,
        protein_id INTEGER,
        match_type TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(uniprot_id, ncbi_protein_acc, protein_id),
        FOREIGN KEY (protein_id) REFERENCES viral_proteins(protein_id)
    );

CREATE TABLE uniprot_structures (
            struct_id SERIAL PRIMARY KEY,
            uniprot_id TEXT NOT NULL,
            source TEXT NOT NULL CHECK (source IN ('alphafold', 'pdb')),
            entry_id TEXT NOT NULL,
            confidence DOUBLE PRECISION,
            sequence_length INTEGER,
            pdb_url TEXT,
            gene TEXT,
            protein_description TEXT,
            organism TEXT,
            fetched_at TEXT
        , protein_id INTEGER REFERENCES viral_proteins(protein_id), local_pdb_path TEXT);

CREATE TABLE viral_isolates (
        isolate_id SERIAL PRIMARY KEY,
        accession VARCHAR(50) UNIQUE NOT NULL,
        virus_name VARCHAR(200),
        taxon_family VARCHAR(100),
        taxon_genus VARCHAR(100),
        taxon_species VARCHAR(100),
        genome_accession VARCHAR(50),
        genome_length INTEGER,
        gc_content DOUBLE PRECISION,
        genome_type VARCHAR(50),
        keywords TEXT,
        reference_id INTEGER, sequence_length INTEGER, molecule_type VARCHAR(20), has_sequence INTEGER DEFAULT 0, master_id INTEGER, completeness VARCHAR(50), "raw_record_name" TEXT, "raw_completeness" TEXT, "sequence_scope_status" TEXT, "sequence_scope_note" TEXT, inference_source TEXT, genome_length_estimated INTEGER DEFAULT 0,
        FOREIGN KEY (reference_id) REFERENCES ref_literatures(reference_id)
    );

CREATE TABLE viral_proteins (
        protein_id SERIAL PRIMARY KEY,
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
        functional_category VARCHAR(50) DEFAULT 'unknown', is_rdrp INTEGER DEFAULT 0, "functional_annotation_status" TEXT DEFAULT 'unannotated', "functional_category_source" TEXT, sequence_quality TEXT,
        FOREIGN KEY (isolate_id) REFERENCES viral_isolates(isolate_id)
    );

CREATE TABLE viral_proteins_nr (
        mapping_id SERIAL PRIMARY KEY,
        protein_id INTEGER,
        reanno_id INTEGER,
        cluster_id INTEGER NOT NULL,
        identity_to_rep DOUBLE PRECISION DEFAULT 100.0,
        alignment_length INTEGER,
        FOREIGN KEY (protein_id) REFERENCES viral_proteins(protein_id),
        FOREIGN KEY (reanno_id) REFERENCES reannotated_orfs(reanno_id),
        FOREIGN KEY (cluster_id) REFERENCES nr_protein_clusters(cluster_id)
    );

CREATE TABLE viralzone_families (
            family_id SERIAL PRIMARY KEY,
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

CREATE TABLE viralzone_gene_tables (
            gene_entry_id SERIAL PRIMARY KEY,
            family_id INTEGER NOT NULL,
            gene_name TEXT,
            protein_name TEXT,
            function_description TEXT,
            position TEXT,
            notes TEXT,
            FOREIGN KEY (family_id) REFERENCES viralzone_families(family_id)
        );

CREATE TABLE virulence_profiles (
        profile_id SERIAL PRIMARY KEY,
        virus_name VARCHAR(200) NOT NULL UNIQUE,
        virulence_level VARCHAR(50),        -- 'High', 'Moderate', 'Low', 'Non-pathogenic'
        virulence_label INTEGER,             -- 1=High pathogenic, 0=Low/Non-pathogenic (guide convention)
        mortality_rate_min DOUBLE PRECISION,             -- Minimum mortality rate (%)
        mortality_rate_max DOUBLE PRECISION,             -- Maximum mortality rate (%)
        ld50_value VARCHAR(100),             -- LD50 value with unit
        pathogenic_mechanism TEXT,           -- Brief description of pathogenic mechanism
        outbreak_record TEXT,                -- Major outbreak records
        host_age_susceptibility VARCHAR(200),-- Which life stages are most susceptible
        data_source VARCHAR(500),            -- Literature or expert curation source
        confidence VARCHAR(20),              -- 'High', 'Medium', 'Low'
        curation_date DATE,
        notes TEXT
    , "data_origin" TEXT, "data_source_type" TEXT, "publication_use" TEXT, "mortality_rate_min_raw" DOUBLE PRECISION, "mortality_rate_max_raw" DOUBLE PRECISION, "mortality_rate_unit" TEXT, "mortality_normalization_note" TEXT);

CREATE TABLE virus_aliases (
            alias_id SERIAL PRIMARY KEY,
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

CREATE TABLE virus_evidence_quality_score (
        master_id INTEGER PRIMARY KEY,
        canonical_name TEXT,
        virus_family TEXT,
        host_phylum TEXT,
        total_evidence INTEGER,
        high_count INTEGER,
        medium_experimental_count INTEGER,
        quantitative_count INTEGER,
        doi_count INTEGER,
        fulltext_count INTEGER,
        reviewed_count INTEGER,
        triangulated_count INTEGER,
        isolate_linked_count INTEGER,
        quality_score DOUBLE PRECISION,
        quality_tier TEXT,
        computed_at TEXT,
        FOREIGN KEY (master_id) REFERENCES virus_master(master_id)
    );

CREATE TABLE virus_ictv_mappings (
            mapping_id SERIAL PRIMARY KEY,
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

CREATE TABLE virus_master (
            master_id SERIAL PRIMARY KEY,
            canonical_name VARCHAR(200) NOT NULL UNIQUE,
            abbreviations TEXT,
            chinese_name VARCHAR(200),
            virus_family VARCHAR(100),
            virus_genus VARCHAR(100),
            genome_type VARCHAR(50),
            is_crustacean_virus INTEGER DEFAULT 1,
            entry_type VARCHAR(50) DEFAULT 'complete_genome',
            notes TEXT
        , discovery_context VARCHAR(50)
            DEFAULT 'metagenomic_environmental', host_phylum VARCHAR(50), public_visibility TEXT DEFAULT 'public');

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

CREATE TABLE virus_name_scope_review (
            review_id SERIAL PRIMARY KEY,
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

CREATE TABLE virus_scope_assessment (
            master_id INTEGER PRIMARY KEY,
            scope_class TEXT NOT NULL,
            scope_reason TEXT NOT NULL,
            evidence_tier TEXT NOT NULL,
            host_phylum TEXT,
            entry_type TEXT,
            discovery_context TEXT,
            has_isolate INTEGER NOT NULL DEFAULT 0,
            has_host_record INTEGER NOT NULL DEFAULT 0,
            has_reference INTEGER NOT NULL DEFAULT 0,
            has_protein INTEGER NOT NULL DEFAULT 0,
            has_country INTEGER NOT NULL DEFAULT 0,
            needs_manual_review INTEGER NOT NULL DEFAULT 0,
            run_id INTEGER NOT NULL,
            assessed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

-- PostgreSQL full-text search (replaces SQLite FTS5 virtual table)
-- Adds a tsvector column to virus_master and a GIN index for fast text search.

ALTER TABLE virus_master ADD COLUMN IF NOT EXISTS search_vector tsvector;

CREATE INDEX IF NOT EXISTS idx_virus_master_search
    ON virus_master USING GIN (search_vector);

-- Trigger to keep search_vector in sync on INSERT or UPDATE
CREATE OR REPLACE FUNCTION virus_master_search_update() RETURNS trigger AS $$
BEGIN
    NEW.search_vector :=
        to_tsvector('english', COALESCE(NEW.canonical_name, '')) ||
        to_tsvector('english', COALESCE(NEW.abbreviations, '')) ||
        to_tsvector('english', COALESCE(NEW.chinese_name, ''));
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_virus_master_search ON virus_master;
CREATE TRIGGER trg_virus_master_search
    BEFORE INSERT OR UPDATE ON virus_master
    FOR EACH ROW EXECUTE FUNCTION virus_master_search_update();

-- Backfill search_vector for existing rows (run AFTER data migration):
-- UPDATE virus_master SET search_vector =
--     to_tsvector('english', COALESCE(canonical_name, '')) ||
--     to_tsvector('english', COALESCE(abbreviations, '')) ||
--     to_tsvector('english', COALESCE(chinese_name, ''));
-- ;

CREATE TABLE virus_vmr_mappings (
            mapping_id SERIAL PRIMARY KEY,
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

CREATE TABLE weak_evidence_isolation_log (
            log_id SERIAL PRIMARY KEY,
            run_ts TEXT NOT NULL,
            evidence_id INTEGER NOT NULL,
            original_status TEXT,
            reason TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP, status TEXT NOT NULL DEFAULT 'active',
            UNIQUE(run_ts, evidence_id),
            FOREIGN KEY(evidence_id) REFERENCES evidence_records(evidence_id)
        );

-- Indexes

CREATE INDEX "idx_auto_biosample_links_isolate" ON "biosample_links" ("isolate_id");
CREATE INDEX "idx_auto_control_reference" ON "control_management_methods" ("reference_id");
CREATE INDEX "idx_auto_diagnostic_reference" ON "diagnostic_methods" ("reference_id");
CREATE INDEX "idx_auto_icp_accession" ON "isolate_curated_profiles" ("accession");
CREATE INDEX "idx_auto_icp_host_name" ON "isolate_curated_profiles" ("host_scientific_name");
CREATE INDEX "idx_auto_kegg_protein_pathways_protein" ON "kegg_protein_pathways" ("protein_id");
CREATE INDEX "idx_auto_outbreak_host" ON "outbreak_events" ("host_id");
CREATE INDEX "idx_auto_outbreak_reference" ON "outbreak_events" ("reference_id");
CREATE INDEX "idx_auto_pathogenicity_isolate" ON "pathogenicity_evidence" ("isolate_id");
CREATE INDEX "idx_auto_pathogenicity_reference" ON "pathogenicity_evidence" ("reference_id");
CREATE INDEX "idx_auto_protein_domains_protein" ON "protein_domains" ("protein_id");
CREATE INDEX "idx_auto_protein_domains_reanno" ON "protein_domains" ("reanno_id");
CREATE INDEX "idx_auto_protein_structures_reanno" ON "protein_structures" ("reanno_id");
CREATE INDEX "idx_auto_reannotation_stats_isolate" ON "reannotation_stats" ("isolate_id");
CREATE INDEX "idx_auto_sample_metadata_accession" ON "sample_metadata" ("accession");
CREATE INDEX "idx_auto_sample_metadata_collection_date" ON "sample_metadata" ("collection_date");
CREATE INDEX "idx_auto_sample_metadata_geo_loc" ON "sample_metadata" ("geo_loc_name");
CREATE INDEX "idx_auto_sample_metadata_isolate" ON "sample_metadata" ("isolate_id");
CREATE INDEX "idx_auto_viral_proteins_is_rdrp" ON "viral_proteins" ("is_rdrp");
CREATE INDEX idx_bio_host ON host_biology_profiles(host_id);
CREATE INDEX idx_biorxiv_date ON biorxiv_preprints(date_posted);
CREATE INDEX idx_biorxiv_doi ON biorxiv_preprints(doi);
CREATE INDEX idx_biorxiv_server ON biorxiv_preprints(server);
CREATE INDEX idx_bridge_accession ON protein_annotation_bridge(protein_accession);
CREATE INDEX idx_bridge_protein ON protein_annotation_bridge(protein_id);
CREATE INDEX idx_bridge_sources ON protein_annotation_bridge(has_uniprot, has_interpro, has_kegg, has_structure);
CREATE INDEX idx_bridge_uniprot ON protein_annotation_bridge(uniprot_id);
CREATE INDEX idx_cg_species ON core_genes(virus_species);
CREATE INDEX idx_ch_scientific_name ON crustacean_hosts(scientific_name);
CREATE INDEX idx_conflicts_status ON curation_conflicts(status);
CREATE INDEX idx_environment_virus ON environmental_evidence(virus_master_id);
CREATE INDEX idx_epmc_doi ON epmc_literature(doi);
CREATE INDEX idx_epmc_pmid ON epmc_literature(pmid);
CREATE INDEX idx_epmc_ref ON epmc_literature(local_reference_id);
CREATE INDEX idx_ev_curation ON evidence_records(curation_status);
CREATE INDEX idx_ev_strength ON evidence_records(evidence_strength);
CREATE INDEX idx_evidence_host
            ON evidence_records(host_id);
CREATE INDEX idx_evidence_reference
            ON evidence_records(reference_id);
CREATE INDEX idx_evidence_type
            ON evidence_records(evidence_type);
CREATE INDEX idx_evidence_virus
            ON evidence_records(virus_master_id);
CREATE INDEX idx_fulltext_quality_action
            ON literature_fulltext_quality(needs_action, priority_score);
CREATE INDEX idx_fulltext_sources_ref
            ON literature_fulltext_sources(reference_id);
CREATE INDEX idx_fulltext_sources_status
            ON literature_fulltext_sources(status, source);
CREATE INDEX idx_gbif_host ON gbif_occurrences(host_id);
CREATE INDEX idx_gbif_latlon ON gbif_occurrences(decimal_latitude, decimal_longitude);
CREATE INDEX idx_gbif_name ON gbif_occurrences(scientific_name);
CREATE INDEX idx_genbank_recovery_accession
            ON genbank_recovery_candidates(accession);
CREATE INDEX idx_genbank_recovery_field
            ON genbank_recovery_candidates(field_name);
CREATE INDEX idx_genbank_recovery_status
            ON genbank_recovery_candidates(match_status);
CREATE INDEX idx_geo_gse ON geo_datasets(gse_accession);
CREATE INDEX idx_geo_quality_continent
            ON geography_quality_profiles(continent);
CREATE INDEX idx_geo_quality_country
            ON geography_quality_profiles(standardized_country);
CREATE INDEX idx_geo_quality_needs_geocoding
            ON geography_quality_profiles(needs_geocoding);
CREATE INDEX idx_geo_quality_precision
            ON geography_quality_profiles(location_precision);
CREATE INDEX idx_geo_virus_name ON geo_virus_links(virus_name);
CREATE INDEX idx_gpi_species ON genome_pairwise_identity(virus_species);
CREATE INDEX idx_host_aliases_host
            ON host_aliases(host_id);
CREATE INDEX idx_host_range_host ON host_range_evidence(host_id);
CREATE INDEX idx_host_range_virus ON host_range_evidence(virus_master_id);
CREATE INDEX idx_host_review_candidates_host
            ON host_review_candidates(host_id);
CREATE INDEX idx_host_review_candidates_issue
            ON host_review_candidates(issue_type);
CREATE INDEX idx_host_taxonomy_profiles_host
            ON host_taxonomy_profiles(host_id);
CREATE INDEX idx_host_taxonomy_profiles_taxid
            ON host_taxonomy_profiles(ncbi_taxid);
CREATE INDEX idx_hosts_class ON crustacean_hosts(class);
CREATE INDEX idx_hosts_phylum_class ON crustacean_hosts(phylum, class);
CREATE INDEX idx_icp_country ON isolate_curated_profiles(country);
CREATE INDEX idx_icp_host ON isolate_curated_profiles(host_id);
CREATE INDEX idx_icp_master ON isolate_curated_profiles(master_id);
CREATE INDEX idx_icp_status ON isolate_curated_profiles(curation_status);
CREATE INDEX idx_icp_year ON isolate_curated_profiles(collection_year);
CREATE INDEX idx_ictv_family ON ictv_taxonomy(family);
CREATE INDEX idx_ictv_genus ON ictv_taxonomy(genus);
CREATE INDEX idx_ictv_species ON ictv_taxonomy(species);
CREATE INDEX idx_ictv_vmr_genbank ON ictv_vmr(genbank_accession);
CREATE INDEX idx_ictv_vmr_refseq ON ictv_vmr(refseq_accession);
CREATE INDEX idx_ictv_vmr_species ON ictv_vmr(species);
CREATE INDEX idx_ictv_vmr_virus_name ON ictv_vmr(virus_name);
CREATE INDEX idx_infection_assoc_method ON infection_records(host_association_method);
CREATE INDEX idx_ip_interpro ON interpro_annotations(interpro_id);
CREATE INDEX idx_ip_protein ON interpro_annotations(protein_id);
CREATE INDEX idx_ip_uniprot ON interpro_annotations(uniprot_id);
CREATE INDEX idx_ipgo_go ON interpro_go_terms(go_id);
CREATE INDEX idx_ipgo_protein ON interpro_go_terms(protein_id);
CREATE INDEX idx_ir_collection_id ON infection_records(collection_id);
CREATE INDEX idx_ir_host_id ON infection_records(host_id);
CREATE INDEX idx_ir_isolate_id ON infection_records(isolate_id);
CREATE INDEX idx_irl_isolate_reference
        ON isolate_reference_links(isolate_id, reference_id)
        ;
CREATE INDEX idx_irl_reference ON isolate_reference_links(reference_id);
CREATE INDEX idx_kegg_ec ON kegg_annotations(ec_number);
CREATE INDEX idx_kegg_ko ON kegg_annotations(ko_id);
CREATE INDEX idx_kegg_pathway_ko ON kegg_protein_pathways(ko_id);
CREATE INDEX idx_kegg_protein ON kegg_annotations(protein_id);
CREATE INDEX idx_lit_backfill_ref
            ON literature_backfill_candidates(reference_id);
CREATE INDEX idx_lit_backfill_run
            ON literature_backfill_candidates(run_id);
CREATE INDEX idx_lit_backfill_signal
            ON literature_backfill_candidates(signal);
CREATE INDEX idx_lit_backfill_status
            ON literature_backfill_candidates(curation_status, confidence, signal);
CREATE INDEX idx_lit_candidates_identifier
        ON literature_evidence_candidates(pmid, doi)
        ;
CREATE INDEX idx_lit_candidates_source
        ON literature_evidence_candidates(source_key)
        ;
CREATE INDEX idx_lit_candidates_virus
        ON literature_evidence_candidates(master_id, target_virus)
        ;
CREATE INDEX idx_manual_ictv_bridges_ictv
            ON manual_ictv_bridges(ictv_id);
CREATE INDEX idx_manual_ictv_bridges_master
            ON manual_ictv_bridges(master_id);
CREATE INDEX idx_manual_review_priority
            ON manual_review_priority_queue(priority, score DESC, category);
CREATE INDEX idx_nr_acc ON nucleotide_records(accession);
CREATE INDEX idx_obis_host ON obis_occurrences(host_id);
CREATE INDEX idx_obis_latlon ON obis_occurrences(decimal_latitude, decimal_longitude);
CREATE INDEX idx_outbreak_virus ON outbreak_events(virus_master_id);
CREATE INDEX idx_pathogenicity_virus ON pathogenicity_evidence(virus_master_id);
CREATE INDEX idx_pd_cluster ON protein_domains(cluster_id);
CREATE INDEX idx_pd_name ON protein_domains(domain_name);
CREATE INDEX idx_phi_cluster ON phi_base_hits(cluster_id);
CREATE INDEX idx_phi_phenotype ON phi_base_hits(phi_phenotype);
CREATE INDEX idx_pride_acc ON pride_datasets(pride_accession);
CREATE INDEX idx_pride_pmid ON pride_datasets(publication_pmid);
CREATE INDEX idx_prov_confidence
            ON data_provenance(confidence_level)
    ;
CREATE INDEX idx_prov_source
            ON data_provenance(data_source)
    ;
CREATE INDEX idx_prov_table_record
            ON data_provenance(table_name, record_id)
    ;
CREATE INDEX idx_ps_cluster ON protein_structures(cluster_id);
CREATE INDEX idx_ps_protein ON protein_structures(protein_id);
CREATE INDEX "idx_pub_fk_control_management_methods_host_id"
            ON "control_management_methods"("host_id")
            ;
CREATE INDEX "idx_pub_fk_curation_logs_source_id"
            ON "curation_logs"("source_id")
            ;
CREATE INDEX "idx_pub_fk_curation_priority_queue_isolate_id"
            ON "curation_priority_queue"("isolate_id")
            ;
CREATE INDEX "idx_pub_fk_data_provenance_virus_master_id"
            ON "data_provenance"("virus_master_id")
            ;
CREATE INDEX "idx_pub_fk_environmental_evidence_reference_id"
            ON "environmental_evidence"("reference_id")
            ;
CREATE INDEX "idx_pub_fk_epmc_preprints_epmc_id"
            ON "epmc_preprints"("epmc_id")
            ;
CREATE INDEX "idx_pub_fk_evidence_records_isolate_id"
            ON "evidence_records"("isolate_id")
            ;
CREATE INDEX "idx_pub_fk_evidence_records_source_id"
            ON "evidence_records"("source_id")
            ;
CREATE INDEX "idx_pub_fk_evidence_review_priority_queue_virus_master_id"
            ON "evidence_review_priority_queue"("virus_master_id")
            ;
CREATE INDEX "idx_pub_fk_gbif_species_summary_host_id"
            ON "gbif_species_summary"("host_id")
            ;
CREATE INDEX "idx_pub_fk_geo_virus_links_geo_dataset_id"
            ON "geo_virus_links"("geo_dataset_id")
            ;
CREATE INDEX "idx_pub_fk_geo_virus_links_local_isolate_id"
            ON "geo_virus_links"("local_isolate_id")
            ;
CREATE INDEX "idx_pub_fk_geo_virus_links_sra_run_id"
            ON "geo_virus_links"("sra_run_id")
            ;
CREATE INDEX "idx_pub_fk_geography_quality_profiles_collection_id"
            ON "geography_quality_profiles"("collection_id")
            ;
CREATE INDEX "idx_pub_fk_host_aliases_source_id"
            ON "host_aliases"("source_id")
            ;
CREATE INDEX "idx_pub_fk_host_range_evidence_reference_id"
            ON "host_range_evidence"("reference_id")
            ;
CREATE INDEX "idx_pub_fk_host_range_evidence_representative_isolate_id"
            ON "host_range_evidence"("representative_isolate_id")
            ;
CREATE INDEX "idx_pub_fk_host_scope_overrides_host_id"
            ON "host_scope_overrides"("host_id")
            ;
CREATE INDEX "idx_pub_fk_host_taxonomy_profiles_source_id"
            ON "host_taxonomy_profiles"("source_id")
            ;
CREATE INDEX "idx_pub_fk_ictv_review_priority_queue_master_id"
            ON "ictv_review_priority_queue"("master_id")
            ;
CREATE INDEX "idx_pub_fk_infection_records_reference_id"
            ON "infection_records"("reference_id")
            ;
CREATE INDEX "idx_pub_fk_isolate_curated_profiles_collection_id"
            ON "isolate_curated_profiles"("collection_id")
            ;
CREATE INDEX "idx_pub_fk_isolate_curated_profiles_discovery_reference_id"
            ON "isolate_curated_profiles"("discovery_reference_id")
            ;
CREATE INDEX "idx_pub_fk_isolate_curated_profiles_genome_reference_id"
            ON "isolate_curated_profiles"("genome_reference_id")
            ;
CREATE INDEX "idx_pub_fk_isolate_curated_profiles_primary_reference_id"
            ON "isolate_curated_profiles"("primary_reference_id")
            ;
CREATE INDEX "idx_pub_fk_literature_evidence_candidates_reference_id"
            ON "literature_evidence_candidates"("reference_id")
            ;
CREATE INDEX "idx_pub_fk_literature_evidence_candidates_source_id"
            ON "literature_evidence_candidates"("source_id")
            ;
CREATE INDEX "idx_pub_fk_pride_virus_links_local_isolate_id"
            ON "pride_virus_links"("local_isolate_id")
            ;
CREATE INDEX "idx_pub_fk_pride_virus_links_local_protein_id"
            ON "pride_virus_links"("local_protein_id")
            ;
CREATE INDEX "idx_pub_fk_pride_virus_links_pride_dataset_id"
            ON "pride_virus_links"("pride_dataset_id")
            ;
CREATE INDEX "idx_pub_fk_string_interactions_local_protein_id"
            ON "string_interactions"("local_protein_id")
            ;
CREATE INDEX "idx_pub_fk_uniprot_protein_links_protein_id"
            ON "uniprot_protein_links"("protein_id")
            ;
CREATE INDEX "idx_pub_fk_uniprot_structures_protein_id"
            ON "uniprot_structures"("protein_id")
            ;
CREATE INDEX "idx_pub_fk_virus_aliases_source_id"
            ON "virus_aliases"("source_id")
            ;
CREATE INDEX "idx_pub_fk_virus_ictv_mappings_source_id"
            ON "virus_ictv_mappings"("source_id")
            ;
CREATE INDEX "idx_pub_fk_virus_ictv_status_master_id"
            ON "virus_ictv_status"("master_id")
            ;
CREATE INDEX "idx_pub_fk_virus_master_review_queue_master_id"
            ON "virus_master_review_queue"("master_id")
            ;
CREATE INDEX "idx_pub_fk_virus_vmr_mappings_source_id"
            ON "virus_vmr_mappings"("source_id")
            ;
CREATE INDEX idx_qaqc_issues_run_rule ON qaqc_issues(run_id, rule_id);
CREATE INDEX idx_qaqc_issues_severity ON qaqc_issues(run_id, severity);
CREATE INDEX idx_qaqc_scores_run_grade ON entity_quality_scores(run_id, entity_type, quality_grade);
CREATE INDEX idx_queue_band
            ON curation_priority_queue(priority_band);
CREATE INDEX idx_queue_field
            ON curation_priority_queue(field_name);
CREATE INDEX idx_queue_score
            ON curation_priority_queue(priority_score);
CREATE INDEX idx_reanno_isolate ON reannotated_orfs(isolate_id);
CREATE INDEX idx_reanno_pos ON reannotated_orfs(start_pos, end_pos);
CREATE INDEX idx_rescue_candidates_reference
            ON "fulltext_evidence_rescue_candidates_legacy_20260528_104551"(reference_id);
CREATE INDEX idx_rescue_candidates_run
            ON "fulltext_evidence_rescue_candidates_legacy_20260528_104551"(run_id, confidence_score DESC);
CREATE INDEX idx_rescue_candidates_source
            ON "fulltext_evidence_rescue_candidates_legacy_20260528_104551"(source_evidence_id);
CREATE INDEX idx_rl_pmid ON ref_literatures(pmid);
CREATE INDEX idx_sc_country ON sample_collections(country);
CREATE INDEX idx_sc_province ON sample_collections(province);
CREATE INDEX idx_sc_year ON sample_collections(collection_year);
CREATE INDEX idx_sra_acc ON sra_runs(sra_accession);
CREATE INDEX idx_string_prot ON string_interactions(protein_a);
CREATE INDEX idx_string_score ON string_interactions(combined_score);
CREATE INDEX idx_string_uniprot ON string_interactions(source_uniprot_id);
CREATE INDEX idx_submission_geo_precision_class ON submission_target_geography_precision(map_precision_class, isolate_id);
CREATE INDEX idx_submission_manual_tasks_type ON submission_manual_intervention_tasks(task_type, entity_id);
CREATE INDEX idx_submission_protein_structure_status ON submission_protein_annotation_coverage(structure_consistency_status, protein_id);
CREATE INDEX idx_synteny_species ON genome_synteny_blocks(virus_species);
CREATE INDEX idx_traits_host ON host_ecological_traits(host_id);
CREATE INDEX idx_us_source ON uniprot_structures(source);
CREATE INDEX idx_us_uniprot ON uniprot_structures(uniprot_id);
CREATE INDEX idx_vi_accession ON viral_isolates(accession);
CREATE INDEX idx_vi_completeness ON viral_isolates(completeness);
CREATE INDEX idx_vi_master_id ON viral_isolates(master_id);
CREATE INDEX idx_vi_reference_id ON viral_isolates(reference_id);
CREATE INDEX idx_vi_virus_name ON viral_isolates(virus_name);
CREATE INDEX idx_vim_ictv ON virus_ictv_mappings(ictv_id);
CREATE INDEX idx_vim_master ON virus_ictv_mappings(master_id);
CREATE INDEX idx_virus_aliases_master
            ON virus_aliases(master_id);
CREATE INDEX idx_virus_discovery_ctx ON virus_master(discovery_context);
CREATE INDEX idx_virus_host_phylum ON virus_master(host_phylum);
CREATE INDEX idx_vm_canonical ON virus_master(canonical_name);
CREATE INDEX idx_vp_accession ON viral_proteins(protein_accession);
CREATE INDEX idx_vp_category ON viral_proteins(functional_category);
CREATE INDEX idx_vp_gene ON viral_proteins(gene_symbol);
CREATE INDEX idx_vp_isolate_id ON viral_proteins(isolate_id);
CREATE INDEX idx_vpnr_cluster ON viral_proteins_nr(cluster_id);
CREATE INDEX idx_vpnr_protein ON viral_proteins_nr(protein_id);
CREATE INDEX idx_vpnr_reanno ON viral_proteins_nr(reanno_id);
CREATE INDEX idx_vvm_ictv ON virus_vmr_mappings(ictv_id);
CREATE INDEX idx_vvm_master ON virus_vmr_mappings(master_id);
CREATE INDEX idx_vvm_vmr ON virus_vmr_mappings(vmr_id);
CREATE INDEX idx_vz_family ON viralzone_families(family_name);
CREATE INDEX idx_vz_gene_family ON viralzone_gene_tables(family_id);
CREATE INDEX idx_xrefs_entity
            ON external_xrefs(entity_type, entity_id);
CREATE INDEX idx_xrefs_source_external
            ON external_xrefs(source_id, external_id);

-- Views (created after data import)

-- View: analysis_clean_viral_isolates
-- CREATE VIEW analysis_clean_viral_isolates AS
        SELECT *
        FROM viral_isolates
        WHERE NOT (
            COALESCE(genome_length, sequence_length, 0) > 10000000
            OR LOWER(COALESCE(virus_name, '')) = 'host genome artifact'
            OR COALESCE(sequence_scope_status, '') = 'host_genome_artifact'
        );

-- View: analysis_curated_diagnostic_methods
-- CREATE VIEW analysis_curated_diagnostic_methods AS
        SELECT *
        FROM diagnostic_methods
        WHERE data_quality = 'curated'
          AND curation_status = 'manual_checked'
          AND virus_master_id IS NOT NULL
          AND reference_id IS NOT NULL
          AND target_gene_or_region IS NOT NULL AND TRIM(target_gene_or_region) <> ''
          AND detection_limit IS NOT NULL AND TRIM(detection_limit) <> ''
          AND validation_context IS NOT NULL AND TRIM(validation_context) <> '';

-- View: analysis_isolate_completeness
-- CREATE VIEW analysis_isolate_completeness AS
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

-- View: analysis_protein_annotation_completeness
-- CREATE VIEW analysis_protein_annotation_completeness AS
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

-- View: analysis_reviewed_evidence_records
-- CREATE VIEW analysis_reviewed_evidence_records AS
        SELECT *
        FROM evidence_records
        WHERE curation_status = 'manual_checked'
          AND reference_id IS NOT NULL;

-- View: analysis_strict_target_isolates
-- CREATE VIEW analysis_strict_target_isolates AS
    SELECT *
    FROM analysis_target_isolates
    WHERE isolate_id IN (
        SELECT isolate_id
        FROM isolate_curated_profiles
        WHERE COALESCE(curation_status, 'auto_seeded') <> 'conflict_open'
    );

-- View: analysis_target_isolates
-- CREATE VIEW analysis_target_isolates AS
    SELECT vi.*
    FROM viral_isolates vi
    LEFT JOIN isolate_curated_profiles icp ON vi.isolate_id = icp.isolate_id
    JOIN virus_master vm ON COALESCE(icp.master_id, vi.master_id) = vm.master_id
    WHERE vm.is_crustacean_virus = 1
      AND vm.entry_type NOT IN (
          'non_target',
          'ictv_non_target',
          'host_genome',
          'duplicate_ictv_vmr_placeholder',
          'duplicate_alias_placeholder'
      );

-- View: predicted_temperature_profiles
-- CREATE VIEW predicted_temperature_profiles AS
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

-- View: predicted_virulence_profiles
-- CREATE VIEW predicted_virulence_profiles AS
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

-- View: public_crustacean_hosts
-- CREATE VIEW public_crustacean_hosts AS
SELECT * FROM crustacean_hosts WHERE public_visibility = 'public';

-- View: public_evidence_records
-- CREATE VIEW public_evidence_records AS
SELECT er.* FROM evidence_records er
LEFT JOIN virus_master vm ON er.virus_master_id = vm.master_id
WHERE vm.public_visibility = 'public' OR er.virus_master_id IS NULL;

-- View: public_ref_literatures
-- CREATE VIEW public_ref_literatures AS
SELECT * FROM ref_literatures;

-- View: public_viral_isolates
-- CREATE VIEW public_viral_isolates AS
SELECT vi.* FROM viral_isolates vi
JOIN virus_master vm ON vi.master_id = vm.master_id
WHERE vm.public_visibility = 'public';

-- View: public_virus_master
-- CREATE VIEW public_virus_master AS
SELECT * FROM virus_master WHERE public_visibility = 'public';

-- View: submission_excluded_isolates_with_reasons
-- CREATE VIEW submission_excluded_isolates_with_reasons AS
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

-- View: v_core_target_viruses
-- CREATE VIEW v_core_target_viruses AS
        SELECT vm.*, vsa.scope_class, vsa.evidence_tier, vsa.scope_reason,
               vsa.has_isolate, vsa.has_host_record, vsa.has_reference,
               vsa.has_protein, vsa.has_country
        FROM virus_master vm
        JOIN virus_scope_assessment vsa ON vm.master_id = vsa.master_id
        WHERE vsa.scope_class IN ('core_target_high_confidence', 'core_target_supported');

-- View: v_data_dictionary
-- CREATE VIEW v_data_dictionary AS
    SELECT
        m.name AS table_name,
        p.cid,
        p.name AS column_name,
        p.type AS data_type,
        CASE WHEN p."notnull" THEN 1 ELSE 0 END AS not_null,
        COALESCE(p.dflt_value, '') AS default_value,
        CASE WHEN p.pk THEN 1 ELSE 0 END AS is_primary_key
    FROM sqlite_schema AS m
    JOIN pragma_table_info(m.name) AS p
    WHERE m.type IN ('table', 'view')
      AND m.name NOT LIKE 'sqlite_%'
    ORDER BY m.name, p.cid;

-- View: v_data_provenance_summary
-- CREATE VIEW v_data_provenance_summary AS
                SELECT
                    data_source,
                    confidence_level,
                    COUNT(*) as record_count,
                    GROUP_CONCAT(DISTINCT table_name) as source_tables
                FROM data_provenance
                GROUP BY data_source, confidence_level
                ORDER BY record_count DESC;

-- View: v_evidence_clean
-- CREATE VIEW v_evidence_clean AS
        SELECT er.*
        FROM evidence_records er
        WHERE COALESCE(er.curation_status, '') <> 'rejected'
          AND er.evidence_id NOT IN (
              SELECT suppressed_evidence_id
              FROM evidence_duplicate_suppression_log
              WHERE status = 'active'
          )
          AND er.evidence_id NOT IN (
              SELECT evidence_id
              FROM weak_evidence_isolation_log
              WHERE status = 'active'
          )
          AND er.virus_master_id IS NOT NULL
          AND er.reference_id IS NOT NULL;

-- View: v_evidence_excluded_from_analysis
-- CREATE VIEW v_evidence_excluded_from_analysis AS
        SELECT er.*,
               CASE
                   WHEN er.curation_status = 'rejected' THEN 'rejected'
                   WHEN er.evidence_id IN (
                       SELECT suppressed_evidence_id
                       FROM evidence_duplicate_suppression_log
                       WHERE status = 'active'
                   ) THEN 'duplicate_suppressed'
                   WHEN er.evidence_id IN (
                       SELECT evidence_id
                       FROM weak_evidence_isolation_log
                       WHERE status = 'active'
                   ) THEN 'weak_abstract_mention'
                   WHEN er.virus_master_id IS NULL THEN 'missing_virus'
                   WHEN er.reference_id IS NULL THEN 'missing_reference'
                   WHEN er.evidence_type = 'host_range' AND er.host_id IS NULL THEN 'host_range_missing_host'
                   ELSE 'other_exclusion'
               END AS exclusion_reason
        FROM evidence_records er
        WHERE er.evidence_id NOT IN (SELECT evidence_id FROM v_evidence_public_analysis);

-- View: v_evidence_public_analysis
-- CREATE VIEW v_evidence_public_analysis AS
        SELECT er.*
        FROM v_evidence_clean er
        WHERE COALESCE(er.evidence_strength, '') IN ('high', 'medium')
          AND COALESCE(er.curation_status, '') IN ('manual_checked', 'auto_imported', 'needs_review')
          AND NOT (er.evidence_type = 'host_range' AND er.host_id IS NULL);

-- View: v_expansion_readiness
-- CREATE VIEW v_expansion_readiness AS
    SELECT 'schema_version' as metric, 'v2.0-aquatic-expansion' as value, 'ready' as status
    UNION ALL
    SELECT 'phylum_coverage',
           GROUP_CONCAT(DISTINCT phylum),
           CASE WHEN COUNT(DISTINCT phylum) >= 3 THEN 'multi_phylum' ELSE 'in_progress' END
    FROM crustacean_hosts WHERE host_scope_status LIKE 'target_%'
    UNION ALL
    SELECT 'target_host_count', CAST(COUNT(*) AS TEXT),
           CASE WHEN COUNT(*) >= 70 THEN 'growing' ELSE 'baseline' END
    FROM crustacean_hosts WHERE host_scope_status LIKE 'target_%'
    UNION ALL
    SELECT 'host_association_method', COUNT(DISTINCT host_association_method) || ' tiers', 'active'
    FROM infection_records
    UNION ALL
    SELECT 'discovery_context', COUNT(DISTINCT discovery_context) || ' tiers', 'active'
    FROM virus_master
    UNION ALL
    SELECT 'phase1_mollusk_ready', 'yes', 'ready';

-- View: v_host_association_for_display
-- CREATE VIEW v_host_association_for_display AS
        SELECT ir.*, haa.association_tier, haa.association_reason, haa.display_recommendation
        FROM infection_records ir
        JOIN host_association_assessment haa ON ir.record_id = haa.record_id;

-- View: v_host_composition_by_phylum
-- CREATE VIEW v_host_composition_by_phylum AS
    SELECT phylum, class, COUNT(*) as host_count,
           GROUP_CONCAT(DISTINCT host_group) as host_groups
    FROM crustacean_hosts
    WHERE host_scope_status IN ('target_crustacean', 'target_mollusk', 'target_other_aquatic_invert')
    GROUP BY phylum, class
    ORDER BY host_count DESC;

-- View: v_host_scope_audit
-- CREATE VIEW v_host_scope_audit AS
        SELECT
            h.host_id,
            h.scientific_name,
            h.taxon_order,
            h.host_group,
            h.host_type,
            h.phylum,
            h.class,
            h.host_scope_status,
            COUNT(ir.record_id) as infection_record_count
        FROM crustacean_hosts h
        LEFT JOIN infection_records ir ON h.host_id = ir.host_id
        GROUP BY h.host_id
        ORDER BY h.host_scope_status, h.phylum, h.scientific_name;

-- View: v_imprecise_coordinates
-- CREATE VIEW v_imprecise_coordinates AS
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

-- View: v_infection_quality
-- CREATE VIEW v_infection_quality AS
        SELECT
            host_association_method,
            COUNT(*) as record_count,
            COUNT(DISTINCT host_id) as unique_hosts,
            COUNT(DISTINCT isolate_id) as unique_isolates
        FROM infection_records
        GROUP BY host_association_method
        ORDER BY
            CASE host_association_method
                WHEN 'confirmed_infection' THEN 1
                WHEN 'disease_outbreak' THEN 2
                WHEN 'pathology_observation' THEN 3
                WHEN 'co_occurrence_metagenomic' THEN 4
                WHEN 'environmental_sample' THEN 5
                ELSE 6
            END;

-- View: v_infection_records_missing_host
-- CREATE VIEW v_infection_records_missing_host AS
            SELECT ir.*, vi.accession, vm.canonical_name
            FROM infection_records ir
            LEFT JOIN viral_isolates vi ON vi.isolate_id = ir.isolate_id
            LEFT JOIN virus_master vm ON vm.master_id = vi.master_id
            WHERE ir.host_id IS NULL;

-- View: v_inferred_temperature
-- CREATE VIEW v_inferred_temperature AS
                    SELECT *, 'temperature_profiles' as source_table
                    FROM temperature_profiles
                    WHERE (data_origin = 'FAMILY_INFERRED') OR ((notes LIKE '%FAMILY_INFERRED%' OR notes LIKE '%family_inferred%'))
                    ORDER BY virus_name;

-- View: v_inferred_virulence
-- CREATE VIEW v_inferred_virulence AS
                    SELECT *, 'virulence_profiles' as source_table
                    FROM virulence_profiles
                    WHERE (data_origin = 'FAMILY_INFERRED') OR ((notes LIKE '%FAMILY_INFERRED%' OR notes LIKE '%family_inferred%'))
                    ORDER BY virus_name;

-- View: v_interpro_annotations_positioned
-- CREATE VIEW v_interpro_annotations_positioned AS
            SELECT *
            FROM interpro_annotations
            WHERE start_pos IS NOT NULL AND end_pos IS NOT NULL;

-- View: v_interpro_missing_positions
-- CREATE VIEW v_interpro_missing_positions AS
            SELECT *
            FROM interpro_annotations
            WHERE start_pos IS NULL OR end_pos IS NULL;

-- View: v_isolate_reference_unique
-- CREATE VIEW v_isolate_reference_unique AS
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

-- View: v_isolates_without_infection_records
-- CREATE VIEW v_isolates_without_infection_records AS
            SELECT vi.isolate_id, vi.accession, vm.canonical_name, vi.virus_name,
                   vi.reference_id, vi.completeness
            FROM viral_isolates vi
            LEFT JOIN virus_master vm ON vm.master_id = vi.master_id
            WHERE NOT EXISTS (
                SELECT 1 FROM infection_records ir WHERE ir.isolate_id = vi.isolate_id
            );

-- View: v_isolates_without_proteins
-- CREATE VIEW v_isolates_without_proteins AS
            SELECT vi.isolate_id, vi.accession, vm.canonical_name, vi.virus_name,
                   vi.completeness, vi.sequence_length, vi.genome_length
            FROM viral_isolates vi
            LEFT JOIN virus_master vm ON vm.master_id = vi.master_id
            WHERE NOT EXISTS (
                SELECT 1 FROM viral_proteins vp WHERE vp.isolate_id = vi.isolate_id
            );

-- View: v_low_confidence_structures
-- CREATE VIEW v_low_confidence_structures AS
            SELECT ps.*, vp.protein_accession, vp.protein_name, vi.accession AS isolate_accession,
                   vm.canonical_name
            FROM protein_structures ps
            LEFT JOIN viral_proteins vp ON vp.protein_id = ps.protein_id
            LEFT JOIN viral_isolates vi ON vi.isolate_id = vp.isolate_id
            LEFT JOIN virus_master vm ON vm.master_id = vi.master_id
            WHERE COALESCE(ps.plddt_normalized_100,
                           CASE WHEN ps.plddt_score <= 1.0 THEN ps.plddt_score * 100.0 ELSE ps.plddt_score END) < 50
               OR ps.publication_use = 'do_not_use_for_primary_claims';

-- View: v_nar_database_summary
-- CREATE VIEW v_nar_database_summary AS
    SELECT 'Total virus species' as metric, CAST(COUNT(*) AS TEXT) as value FROM virus_master
    UNION ALL SELECT 'Total viral isolates', CAST(COUNT(*) AS TEXT) FROM viral_isolates
    UNION ALL SELECT 'Total proteins', CAST(COUNT(*) AS TEXT) FROM viral_proteins
    UNION ALL SELECT 'Target aquatic invertebrate hosts',
        CAST(COUNT(*) AS TEXT) FROM crustacean_hosts
        WHERE host_scope_status IN ('target_crustacean', 'target_mollusk', 'target_other_aquatic_invert')
    UNION ALL SELECT 'Aquatic invertebrate phyla covered',
        CAST(COUNT(DISTINCT phylum) AS TEXT) FROM crustacean_hosts
        WHERE host_scope_status IN ('target_crustacean', 'target_mollusk', 'target_other_aquatic_invert')
    UNION ALL SELECT 'Confirmed virus-host associations (infection/disease)',
        CAST(COUNT(*) AS TEXT) FROM infection_records
        WHERE host_association_method IN ('disease_outbreak', 'confirmed_infection', 'pathology_observation')
    UNION ALL SELECT 'Geographic countries', CAST(COUNT(DISTINCT country) AS TEXT)
        FROM isolate_curated_profiles WHERE country IS NOT NULL
    UNION ALL SELECT 'Literature references', CAST(COUNT(*) AS TEXT) FROM ref_literatures
    UNION ALL SELECT 'Virus species with evidence records',
        CAST(COUNT(DISTINCT vm.master_id) AS TEXT)
        FROM virus_master vm JOIN evidence_records er ON vm.master_id = er.virus_master_id;

-- View: v_non_target_or_uncertain_viruses
-- CREATE VIEW v_non_target_or_uncertain_viruses AS
        SELECT vm.*, vsa.scope_class, vsa.evidence_tier, vsa.scope_reason
        FROM virus_master vm
        JOIN virus_scope_assessment vsa ON vm.master_id = vsa.master_id
        WHERE vsa.scope_class NOT IN ('core_target_high_confidence', 'core_target_supported');

-- View: v_pathogenicity_claim_safety
-- CREATE VIEW v_pathogenicity_claim_safety AS
        SELECT pa.*, vm.canonical_name
        FROM pathogenicity_assessment pa
        LEFT JOIN virus_master vm ON pa.virus_master_id = vm.master_id;

-- View: v_publication_profile_status
-- CREATE VIEW v_publication_profile_status AS
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

-- View: v_references_missing_identifiers
-- CREATE VIEW v_references_missing_identifiers AS
            SELECT reference_id, title, authors, journal, year, pmid, doi
            FROM ref_literatures
            WHERE TRIM(COALESCE(pmid, '')) = ''
              AND TRIM(COALESCE(doi, '')) = '';

-- View: v_unverified_literature
-- CREATE VIEW v_unverified_literature AS
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

-- View: v_viral_isolate_name_reconciled
-- CREATE VIEW v_viral_isolate_name_reconciled AS
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

-- View: v_viral_isolate_taxonomy_reconciled
-- CREATE VIEW v_viral_isolate_taxonomy_reconciled AS
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

-- View: v_virus_discovery_summary
-- CREATE VIEW v_virus_discovery_summary AS
        SELECT
            discovery_context,
            host_phylum,
            COUNT(*) as species_count
        FROM virus_master
        GROUP BY discovery_context, host_phylum
        ORDER BY species_count DESC;

