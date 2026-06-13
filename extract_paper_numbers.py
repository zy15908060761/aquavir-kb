"""Extract all paper numbers from the database into a JSON report."""
import sys, sqlite3, json, os
sys.stdout.reconfigure(encoding='utf-8')
db = sqlite3.connect(os.path.join(os.path.dirname(__file__), 'crustacean_virus_core.db'))
db.row_factory = sqlite3.Row

ACTIVE = ("vm.is_crustacean_virus=1 AND vm.entry_type NOT IN "
          "('non_target','ictv_non_target','duplicate_ictv_vmr_placeholder',"
          "'duplicate_alias_placeholder','host_genome')")

paper = {}

# CORE COUNTS
paper['active_viruses_broad'] = db.execute(
    f"SELECT COUNT(*) FROM virus_master vm WHERE {ACTIVE}").fetchone()[0]
paper['active_viruses_public'] = db.execute(
    f"SELECT COUNT(*) FROM virus_master vm WHERE {ACTIVE} AND public_visibility='public'").fetchone()[0]
paper['active_viruses_limited'] = db.execute(
    f"SELECT COUNT(*) FROM virus_master vm WHERE {ACTIVE} AND public_visibility='limited'").fetchone()[0]
paper['total_virus_master'] = db.execute("SELECT COUNT(*) FROM virus_master").fetchone()[0]
paper['non_target_count'] = db.execute(
    "SELECT COUNT(*) FROM virus_master WHERE entry_type IN ('non_target','ictv_non_target')").fetchone()[0]
paper['evidence_total'] = db.execute("SELECT COUNT(*) FROM evidence_records").fetchone()[0]
paper['evidence_rejected'] = db.execute(
    "SELECT COUNT(*) FROM evidence_records WHERE curation_status='rejected'").fetchone()[0]
paper['evidence_effective'] = paper['evidence_total'] - paper['evidence_rejected']
paper['refs_total'] = db.execute("SELECT COUNT(*) FROM ref_literatures").fetchone()[0]
paper['refs_with_pmid'] = db.execute(
    "SELECT COUNT(*) FROM ref_literatures WHERE pmid IS NOT NULL AND pmid != ''").fetchone()[0]
paper['refs_with_doi'] = db.execute(
    "SELECT COUNT(*) FROM ref_literatures WHERE doi IS NOT NULL AND doi != ''").fetchone()[0]
paper['viral_proteins'] = db.execute("SELECT COUNT(*) FROM viral_proteins").fetchone()[0]
paper['protein_domains'] = db.execute("SELECT COUNT(*) FROM protein_domains").fetchone()[0]
paper['viral_isolates_total'] = db.execute("SELECT COUNT(*) FROM viral_isolates").fetchone()[0]
paper['ati_raw'] = db.execute("SELECT COUNT(*) FROM analysis_target_isolates").fetchone()[0]
paper['ati_strict'] = db.execute("SELECT COUNT(*) FROM analysis_strict_target_isolates").fetchone()[0]
paper['ati_with_seq'] = db.execute(
    "SELECT COUNT(*) FROM analysis_target_isolates WHERE has_sequence=1").fetchone()[0]
paper['tables_count'] = db.execute(
    "SELECT COUNT(*) FROM sqlite_master WHERE type='table'").fetchone()[0]
paper['views_count'] = db.execute(
    "SELECT COUNT(*) FROM sqlite_master WHERE type='view'").fetchone()[0]
paper['vmr_mappings'] = db.execute("SELECT COUNT(*) FROM virus_vmr_mappings").fetchone()[0]
paper['ictv_status_total'] = db.execute("SELECT COUNT(*) FROM virus_ictv_status").fetchone()[0]
paper['ictv_mapped'] = db.execute(
    "SELECT COUNT(*) FROM virus_ictv_status WHERE ictv_status='mapped'").fetchone()[0]

# EVIDENCE QUALITY
for level in ['high','medium','low']:
    paper[f'evidence_{level}'] = db.execute(
        "SELECT COUNT(*) FROM evidence_records WHERE evidence_strength=?", (level,)).fetchone()[0]
    paper[f'evidence_{level}_pct'] = round(
        paper[f'evidence_{level}'] / paper['evidence_total'] * 100, 1)

for status in ['auto_imported','manual_checked','needs_review','rejected']:
    paper[f'curation_{status}'] = db.execute(
        "SELECT COUNT(*) FROM evidence_records WHERE curation_status=?", (status,)).fetchone()[0]

# HOST PHYLUM
paper['host_phyla'] = []
for r in db.execute(
    f"SELECT host_phylum, COUNT(*) cnt FROM virus_master vm WHERE {ACTIVE} "
    "GROUP BY host_phylum ORDER BY cnt DESC").fetchall():
    paper['host_phyla'].append({'phylum': r['host_phylum'] or 'NULL', 'count': r['cnt']})

# GENOME TYPE
paper['genome_types'] = []
for r in db.execute(
    f"SELECT genome_type, COUNT(*) cnt FROM virus_master vm WHERE {ACTIVE} "
    "AND genome_type IS NOT NULL AND genome_type != '' "
    "GROUP BY genome_type ORDER BY cnt DESC").fetchall():
    paper['genome_types'].append({'genome_type': r['genome_type'], 'count': r['cnt']})

paper['missing_genome_type'] = db.execute(
    f"SELECT COUNT(*) FROM virus_master vm WHERE {ACTIVE} "
    "AND (genome_type IS NULL OR genome_type='')").fetchone()[0]

# DISCOVERY CONTEXT
paper['discovery_contexts'] = []
for r in db.execute(
    f"SELECT discovery_context, COUNT(*) cnt FROM virus_master vm WHERE {ACTIVE} "
    "GROUP BY discovery_context ORDER BY cnt DESC").fetchall():
    paper['discovery_contexts'].append(
        {'context': r['discovery_context'] or 'NULL', 'count': r['cnt']})

# PROTEIN ANNOTATION
paper['protein_annotated'] = db.execute(
    "SELECT COUNT(*) FROM viral_proteins WHERE functional_annotation_status='domain_inferred'"
).fetchone()[0]
paper['protein_unannotated'] = db.execute(
    "SELECT COUNT(*) FROM viral_proteins WHERE functional_annotation_status='unannotated'"
).fetchone()[0]
paper['protein_rule_suggested'] = db.execute(
    "SELECT COUNT(*) FROM viral_proteins WHERE functional_annotation_status='rule_suggested_unreviewed'"
).fetchone()[0]
paper['protein_annotated_pct'] = round(
    paper['protein_annotated'] / paper['viral_proteins'] * 100, 1)

paper['functional_categories'] = []
for r in db.execute(
    "SELECT functional_category, COUNT(*) cnt FROM viral_proteins "
    "GROUP BY functional_category ORDER BY cnt DESC").fetchall():
    paper['functional_categories'].append(
        {'category': r['functional_category'] or 'NULL', 'count': r['cnt']})

# GEOGRAPHY
paper['geo_profiles'] = db.execute("SELECT COUNT(*) FROM isolate_curated_profiles").fetchone()[0]
paper['geo_with_country'] = db.execute(
    "SELECT COUNT(*) FROM isolate_curated_profiles WHERE country IS NOT NULL AND country != ''"
).fetchone()[0]
paper['geo_pct'] = round(paper['geo_with_country'] / paper['geo_profiles'] * 100, 1)
paper['country_count'] = db.execute(
    "SELECT COUNT(DISTINCT country) FROM isolate_curated_profiles "
    "WHERE country IS NOT NULL AND country != ''").fetchone()[0]

# ICTV STATUS
paper['ictv_statuses'] = []
for r in db.execute(
    "SELECT ictv_status, COUNT(*) cnt FROM virus_ictv_status "
    "GROUP BY ictv_status ORDER BY cnt DESC").fetchall():
    paper['ictv_statuses'].append({'status': r['ictv_status'] or 'NULL', 'count': r['cnt']})

# EVIDENCE TYPES
paper['evidence_types'] = []
for r in db.execute(
    "SELECT evidence_type, COUNT(*) cnt FROM evidence_records "
    "GROUP BY evidence_type ORDER BY cnt DESC").fetchall():
    paper['evidence_types'].append({'type': r['evidence_type'], 'count': r['cnt']})

# TOP 20 FAMILIES
paper['top_families'] = []
for r in db.execute(
    f"SELECT virus_family, COUNT(*) cnt FROM virus_master vm WHERE {ACTIVE} "
    "AND virus_family IS NOT NULL AND virus_family != '' "
    "GROUP BY virus_family ORDER BY cnt DESC LIMIT 20").fetchall():
    phyla = db.execute(
        f"SELECT GROUP_CONCAT(DISTINCT host_phylum) FROM virus_master vm "
        f"WHERE {ACTIVE} AND virus_family=?", (r['virus_family'],)).fetchone()[0]
    paper['top_families'].append(
        {'family': r['virus_family'], 'count': r['cnt'], 'phyla': phyla})

paper['missing_family'] = db.execute(
    f"SELECT COUNT(*) FROM virus_master vm WHERE {ACTIVE} "
    "AND (virus_family IS NULL OR virus_family='')").fetchone()[0]
paper['classified_pct'] = round(
    (paper['active_viruses_broad'] - paper['missing_family']) / paper['active_viruses_broad'] * 100, 1)

# PROTEIN LENGTH
for r in db.execute(
    "SELECT AVG(aa_length), MIN(aa_length), MAX(aa_length) FROM viral_proteins WHERE aa_length > 0"
).fetchall():
    paper['protein_length_avg'] = round(r[0], 0) if r[0] else 0
    paper['protein_length_min'] = r[1]
    paper['protein_length_max'] = r[2]

# RDRP
paper['rdrp_count'] = db.execute(
    "SELECT COUNT(*) FROM viral_proteins WHERE is_rdrp=1").fetchone()[0]
rdrp_avg = db.execute(
    "SELECT AVG(aa_length) FROM viral_proteins WHERE is_rdrp=1 AND aa_length > 0"
).fetchone()[0]
paper['rdrp_avg_len'] = round(rdrp_avg, 0) if rdrp_avg else 0

# DATA PROVENANCE
paper['data_provenance'] = db.execute("SELECT COUNT(*) FROM data_provenance").fetchone()[0]
paper['curation_logs'] = db.execute("SELECT COUNT(*) FROM curation_logs").fetchone()[0]

# DB SIZE
db_path = os.path.join(os.path.dirname(__file__), 'crustacean_virus_core.db')
paper['db_size_mb'] = round(os.path.getsize(db_path) / 1024 / 1024, 1)

# ISOLATES PER VIRUS
paper['active_with_isolates'] = db.execute(
    f"SELECT COUNT(DISTINCT vm.master_id) FROM virus_master vm "
    f"JOIN analysis_target_isolates ati ON vm.master_id=ati.master_id WHERE {ACTIVE}"
).fetchone()[0]
paper['active_zero_isolates'] = paper['active_viruses_broad'] - paper['active_with_isolates']

# NULL-REF EVIDENCE
paper['null_ref_evidence'] = db.execute(
    "SELECT COUNT(*) FROM evidence_records WHERE reference_id IS NULL").fetchone()[0]
paper['null_ref_active_viruses'] = db.execute(
    f"SELECT COUNT(DISTINCT vm.master_id) FROM virus_master vm "
    f"JOIN evidence_records er ON vm.master_id=er.virus_master_id "
    f"WHERE {ACTIVE} AND er.reference_id IS NULL").fetchone()[0]

# OBSERVATION TYPE
paper['observation_types'] = []
for r in db.execute(
    "SELECT observation_type, COUNT(*) cnt FROM evidence_records "
    "GROUP BY observation_type ORDER BY cnt DESC").fetchall():
    paper['observation_types'].append(
        {'type': r['observation_type'] or 'NULL', 'count': r['cnt']})

# REFERENCE YEAR RANGE
paper['ref_year_min'] = db.execute(
    "SELECT MIN(CAST(year AS INTEGER)) FROM ref_literatures WHERE year IS NOT NULL AND year != ''"
).fetchone()[0]
paper['ref_year_max'] = db.execute(
    "SELECT MAX(CAST(year AS INTEGER)) FROM ref_literatures WHERE year IS NOT NULL AND year != ''"
).fetchone()[0]

# Write
outdir = os.path.join(os.path.dirname(__file__), 'reports')
os.makedirs(outdir, exist_ok=True)
outpath = os.path.join(outdir, 'paper_numbers_20260602.json')
with open(outpath, 'w', encoding='utf-8') as f:
    json.dump(paper, f, indent=2, ensure_ascii=False)

# Print summary
print("=== PAPER NUMBERS EXPORTED ===\n")
print(f"VIRUSES: broad={paper['active_viruses_broad']}, public={paper['active_viruses_public']}, "
      f"limited={paper['active_viruses_limited']}, non_target={paper['non_target_count']}")
print(f"EVIDENCE: total={paper['evidence_total']:,}, effective={paper['evidence_effective']:,}, "
      f"rejected={paper['evidence_rejected']:,}")
print(f"  high={paper['evidence_high']:,} ({paper['evidence_high_pct']}%), "
      f"medium={paper['evidence_medium']:,} ({paper['evidence_medium_pct']}%), "
      f"low={paper['evidence_low']:,} ({paper['evidence_low_pct']}%)")
print(f"CURATION: auto={paper['curation_auto_imported']:,}, manual={paper['curation_manual_checked']:,}, "
      f"review={paper['curation_needs_review']:,}, rejected={paper['curation_rejected']:,}")
print(f"REFS: {paper['refs_total']:,} (PMID={paper['refs_with_pmid']:,}, DOI={paper['refs_with_doi']:,}) "
      f"[{paper['ref_year_min']}-{paper['ref_year_max']}]")
print(f"PROTEINS: {paper['viral_proteins']:,} ({paper['protein_annotated_pct']}% domain_inferred), "
      f"domains={paper['protein_domains']:,}, RdRP={paper['rdrp_count']} (avg {paper['rdrp_avg_len']}aa)")
print(f"ISOLATES: total={paper['viral_isolates_total']:,}, ATI={paper['ati_raw']:,}, "
      f"strict={paper['ati_strict']:,}, seq={paper['ati_with_seq']:,}")
print(f"GEOGRAPHY: {paper['geo_with_country']:,}/{paper['geo_profiles']:,} ({paper['geo_pct']}%), "
      f"{paper['country_count']} countries")
print(f"ICTV: mapped={paper['ictv_mapped']}, VMR={paper['vmr_mappings']}")
print(f"STRUCTURE: {paper['tables_count']} tables, {paper['views_count']} views, "
      f"provenance={paper['data_provenance']:,}, curation_logs={paper['curation_logs']:,}")
print(f"DB: {paper['db_size_mb']} MB")
print(f"GAPS: missing_family={paper['missing_family']} ({100-paper['classified_pct']}%), "
      f"missing_genome_type={paper['missing_genome_type']}, zero_isolates={paper['active_zero_isolates']}")
print(f"\nHost phyla: {[(p['phylum'],p['count']) for p in paper['host_phyla']]}")
print(f"Genome types: {[(g['genome_type'],g['count']) for g in paper['genome_types']]}")
print(f"Top 10 families:")
for f in paper['top_families'][:10]:
    print(f"  {f['family']}: {f['count']} ({f['phyla']})")
print(f"\nEvidence types:")
for e in paper['evidence_types']:
    print(f"  {e['type']}: {e['count']:,}")
print(f"\nObservation types:")
for o in paper['observation_types']:
    print(f"  {o['type']}: {o['count']:,}")
print(f"\nFunctional categories:")
for fc in paper['functional_categories']:
    print(f"  {fc['category']}: {fc['count']:,}")
print(f"\nSaved to: {outpath}")
db.close()
