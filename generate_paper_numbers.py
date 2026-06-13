"""Generate all numbers needed for the NAR paper from the live database."""
import sqlite3

conn = sqlite3.connect('crustacean_virus_core.db')

ACTIVE_FILTER = """is_crustacean_virus=1 AND entry_type NOT IN ('non_target','ictv_non_target','host_genome','duplicate_ictv_vmr_placeholder','duplicate_alias_placeholder')"""

print("="*60)
print("AQUAVIR-KB PAPER NUMBERS (generated from live DB)")
print("="*60)

# === CORE COUNTS ===
active = conn.execute(f"SELECT COUNT(*) FROM virus_master WHERE {ACTIVE_FILTER}").fetchone()[0]
print(f"\nActive target viruses: {active}")

total_vm = conn.execute("SELECT COUNT(*) FROM virus_master").fetchone()[0]
print(f"Total virus_master entries: {total_vm}")

# === PHYLUM DISTRIBUTION (Table 1) ===
print("\n--- Table 1: Phylum Distribution ---")
for r in conn.execute(f"""SELECT host_phylum, COUNT(*) as cnt FROM virus_master WHERE {ACTIVE_FILTER} GROUP BY host_phylum ORDER BY cnt DESC"""):
    pct = r[1]*100.0/active
    print(f"  {r[0]}: {r[1]} ({pct:.1f}%)")
print(f"  Total: {active}")

# === TIER DISTRIBUTION ===
print("\n--- Tier Distribution ---")
for r in conn.execute(f"""SELECT public_visibility, COUNT(*) FROM virus_master WHERE {ACTIVE_FILTER} GROUP BY public_visibility"""):
    pct = r[1]*100.0/active
    print(f"  {r[0]}: {r[1]} ({pct:.1f}%)")

# === EVIDENCE ===
total_ev = conn.execute("SELECT COUNT(*) FROM evidence_records").fetchone()[0]
effective_ev = conn.execute("SELECT COUNT(*) FROM evidence_records WHERE curation_status != 'rejected'").fetchone()[0]
rejected_ev = conn.execute("SELECT COUNT(*) FROM evidence_records WHERE curation_status = 'rejected'").fetchone()[0]
print(f"\n--- Evidence ---")
print(f"Total: {total_ev:,}")
print(f"Effective: {effective_ev:,}")
print(f"Rejected: {rejected_ev:,} ({rejected_ev*100.0/total_ev:.1f}%)")

# Curation status
print("\nCuration status:")
for r in conn.execute("SELECT curation_status, COUNT(*) FROM evidence_records GROUP BY curation_status ORDER BY COUNT(*) DESC"):
    pct = r[1]*100.0/total_ev
    print(f"  {r[0]}: {r[1]:,} ({pct:.1f}%)")

# Evidence origin
print("\nEvidence origin (effective only):")
for r in conn.execute("SELECT evidence_origin, COUNT(*) FROM evidence_records WHERE curation_status != 'rejected' GROUP BY evidence_origin ORDER BY COUNT(*) DESC"):
    pct = r[1]*100.0/effective_ev
    print(f"  {r[0]}: {r[1]:,} ({pct:.1f}%)")

# Evidence strength (effective only)
print("\nEvidence strength (effective only):")
for r in conn.execute("SELECT evidence_strength, COUNT(*) FROM evidence_records WHERE curation_status != 'rejected' GROUP BY evidence_strength ORDER BY COUNT(*) DESC"):
    pct = r[1]*100.0/effective_ev
    print(f"  {r[0]}: {r[1]:,} ({pct:.1f}%)")

# Evidence type (effective only)
print("\nEvidence type (effective only):")
for r in conn.execute("SELECT evidence_type, COUNT(*) FROM evidence_records WHERE curation_status != 'rejected' GROUP BY evidence_type ORDER BY COUNT(*) DESC"):
    pct = r[1]*100.0/effective_ev
    print(f"  {r[0]}: {r[1]:,} ({pct:.1f}%)")

# === ISOLATES ===
total_iso = conn.execute("SELECT COUNT(*) FROM viral_isolates").fetchone()[0]
target_iso = conn.execute("SELECT COUNT(*) FROM analysis_target_isolates").fetchone()[0]
strict_iso = conn.execute("SELECT COUNT(*) FROM analysis_strict_target_isolates").fetchone()[0]
iso_with_seq = conn.execute("SELECT COUNT(*) FROM viral_isolates WHERE has_sequence=1").fetchone()[0]
print(f"\n--- Isolates ---")
print(f"Total: {total_iso:,}")
print(f"Target (analysis_target_isolates): {target_iso:,}")
print(f"Strict (analysis_strict_target_isolates): {strict_iso:,}")
print(f"With sequence data: {iso_with_seq:,}")

# === PROTEINS ===
total_prot = conn.execute("SELECT COUNT(*) FROM viral_proteins").fetchone()[0]
annotated = conn.execute("SELECT COUNT(*) FROM viral_proteins WHERE functional_annotation_status != 'unannotated' AND functional_annotation_status IS NOT NULL").fetchone()[0]
unannotated = conn.execute("SELECT COUNT(*) FROM viral_proteins WHERE functional_annotation_status = 'unannotated' OR functional_annotation_status IS NULL").fetchone()[0]
print(f"\n--- Proteins ---")
print(f"Total: {total_prot:,}")
print(f"Annotated: {annotated:,} ({annotated*100.0/total_prot:.1f}%)")
print(f"Unannotated: {unannotated:,} ({unannotated*100.0/total_prot:.1f}%)")

# Functional categories
print("\nFunctional categories:")
for r in conn.execute("SELECT functional_category, COUNT(*) FROM viral_proteins GROUP BY functional_category ORDER BY COUNT(*) DESC"):
    pct = r[1]*100.0/total_prot
    print(f"  {r[0] or 'NULL'}: {r[1]:,} ({pct:.1f}%)")

# === REFERENCES ===
total_ref = conn.execute("SELECT COUNT(*) FROM ref_literatures").fetchone()[0]
with_pmid = conn.execute("SELECT COUNT(*) FROM ref_literatures WHERE pmid IS NOT NULL AND pmid != ''").fetchone()[0]
with_doi = conn.execute("SELECT COUNT(*) FROM ref_literatures WHERE doi IS NOT NULL AND doi != ''").fetchone()[0]
no_pmid_doi = conn.execute("SELECT COUNT(*) FROM ref_literatures WHERE (pmid IS NULL OR pmid='') AND (doi IS NULL OR doi='')").fetchone()[0]
print(f"\n--- References ---")
print(f"Total: {total_ref:,}")
print(f"PMID coverage: {with_pmid:,} ({with_pmid*100.0/total_ref:.1f}%)")
print(f"DOI coverage: {with_doi:,} ({with_doi*100.0/total_ref:.1f}%)")
print(f"No PMID or DOI: {no_pmid_doi}")

# === GENOME TYPE (Table 3) ===
print(f"\n--- Table 3: Genome Type Distribution (active={active}) ---")
for r in conn.execute(f"""SELECT COALESCE(genome_type,'Missing'), COUNT(*) as cnt FROM virus_master WHERE {ACTIVE_FILTER} GROUP BY genome_type ORDER BY cnt DESC"""):
    pct = r[1]*100.0/active
    print(f"  {r[0]}: {r[1]} ({pct:.1f}%)")

# === DISCOVERY CONTEXT ===
print(f"\n--- Discovery Context ---")
for r in conn.execute(f"""SELECT discovery_context, COUNT(*) FROM virus_master WHERE {ACTIVE_FILTER} GROUP BY discovery_context ORDER BY COUNT(*) DESC"""):
    pct = r[1]*100.0/active
    print(f"  {r[0]}: {r[1]} ({pct:.1f}%)")

# === FAMILY DISTRIBUTION (Table 2, top 20) ===
print(f"\n--- Top 20 Families ---")
for r in conn.execute(f"""SELECT virus_family, COUNT(*) as cnt FROM virus_master WHERE {ACTIVE_FILTER} AND virus_family IS NOT NULL AND virus_family != '' GROUP BY virus_family ORDER BY cnt DESC LIMIT 20"""):
    pct = r[1]*100.0/active
    print(f"  {r[0]}: {r[1]} ({pct:.1f}%)")

# === EVIDENCE PER VIRUS ===
print("\n--- Evidence per virus ---")
single_ev = conn.execute("SELECT COUNT(*) FROM (SELECT virus_master_id, COUNT(*) as cnt FROM evidence_records WHERE curation_status != 'rejected' GROUP BY virus_master_id HAVING cnt=1)").fetchone()[0]
le5 = conn.execute("SELECT COUNT(*) FROM (SELECT virus_master_id, COUNT(*) as cnt FROM evidence_records WHERE curation_status != 'rejected' GROUP BY virus_master_id HAVING cnt<=5)").fetchone()[0]
print(f"Viruses with 1 evidence: {single_ev}")
print(f"Viruses with <=5 evidence: {le5}")

# === MODEL VIRUSES (Table 5) ===
print("\n--- Model Virus Evidence (Table 5) ---")
for name in ['White spot syndrome virus', 'Yellow head virus', 'Taura syndrome virus',
             'Infectious hypodermal and hematopoietic necrosis virus',
             'Infectious myonecrosis virus', 'Macrobrachium rosenbergii nodavirus',
             'Ostreid herpesvirus 1', 'Haliotid herpesvirus 1', 'Abalone viral necrosis virus']:
    row = conn.execute("""SELECT master_id FROM virus_master WHERE canonical_name=? AND is_crustacean_virus=1""", (name,)).fetchone()
    if row:
        mid = row[0]
        total = conn.execute("SELECT COUNT(*) FROM evidence_records WHERE virus_master_id=? AND curation_status != 'rejected'", (mid,)).fetchone()[0]
        high = conn.execute("SELECT COUNT(*) FROM evidence_records WHERE virus_master_id=? AND curation_status != 'rejected' AND evidence_strength='high'", (mid,)).fetchone()[0]
        medium = conn.execute("SELECT COUNT(*) FROM evidence_records WHERE virus_master_id=? AND curation_status != 'rejected' AND evidence_strength='medium'", (mid,)).fetchone()[0]
        low = conn.execute("SELECT COUNT(*) FROM evidence_records WHERE virus_master_id=? AND curation_status != 'rejected' AND evidence_strength='low'", (mid,)).fetchone()[0]
        print(f"  {name[:50]}: total={total}, high={high}, medium={medium}, low={low}")
    else:
        print(f"  {name[:50]}: NOT FOUND in active set")

# === TABLES AND VIEWS ===
tables = conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'").fetchone()[0]
views = conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='view'").fetchone()[0]
print(f"\n--- Database Structure ---")
print(f"Tables: {tables}")
print(f"Views: {views}")

# === OTHER KEY NUMBERS ===
print(f"\n--- Other ---")
# Distinct families
families = conn.execute(f"SELECT COUNT(DISTINCT virus_family) FROM virus_master WHERE {ACTIVE_FILTER} AND virus_family IS NOT NULL AND virus_family != ''").fetchone()[0]
print(f"Distinct viral families: {families}")
# Missing family
missing_fam = conn.execute(f"SELECT COUNT(*) FROM virus_master WHERE {ACTIVE_FILTER} AND (virus_family IS NULL OR virus_family = '')").fetchone()[0]
print(f"Missing family: {missing_fam}")
# Missing genome_type
missing_gt = conn.execute(f"SELECT COUNT(*) FROM virus_master WHERE {ACTIVE_FILTER} AND (genome_type IS NULL OR genome_type = '')").fetchone()[0]
print(f"Missing genome_type: {missing_gt}")
# Data provenance
prov = conn.execute("SELECT COUNT(*) FROM data_provenance").fetchone()[0]
print(f"Data provenance records: {prov:,}")
# Curation logs
clogs = conn.execute("SELECT COUNT(*) FROM curation_logs").fetchone()[0]
print(f"Curation logs: {clogs:,}")
# Curation conflicts
cc = conn.execute("SELECT COUNT(*) FROM curation_conflicts").fetchone()[0]
print(f"Curation conflicts: {cc:,}")

conn.close()
print("\nDone.")
