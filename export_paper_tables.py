"""Export paper tables from DB — Table 2, Table 5, S1, S2."""
import sys, sqlite3, json, os
sys.stdout.reconfigure(encoding='utf-8')
DB = os.path.join(os.path.dirname(__file__), 'crustacean_virus_core.db')
conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row

ACTIVE = ("vm.is_crustacean_virus=1 AND vm.entry_type NOT IN "
          "('non_target','ictv_non_target','duplicate_ictv_vmr_placeholder',"
          "'duplicate_alias_placeholder','host_genome')")

outdir = os.path.join(os.path.dirname(__file__), 'reports')
os.makedirs(outdir, exist_ok=True)

# ═══════════════════════════════════════════════
# TABLE 2: Top 20 viral families
# ═══════════════════════════════════════════════
print("=" * 70)
print("TABLE 2: Top 20 Viral Families in AquaVir-KB by Species Count")
print("=" * 70)

families = conn.execute(f"""
    SELECT vm.virus_family, COUNT(*) cnt,
           GROUP_CONCAT(DISTINCT vm.host_phylum) phyla,
           GROUP_CONCAT(DISTINCT vm.genome_type) genome_types
    FROM virus_master vm WHERE {ACTIVE}
    AND vm.virus_family IS NOT NULL AND vm.virus_family != ''
    AND vm.virus_family != 'Unclassified'
    GROUP BY vm.virus_family ORDER BY cnt DESC LIMIT 20
""").fetchall()

print(f"{'Rank':<5} {'Family':<35} {'Count':>6} {'%':>6} {'Primary Host Phyla'}")
print("-" * 70)
for i, r in enumerate(families, 1):
    pct = r['cnt'] / 1704 * 100
    phyla_short = ', '.join(sorted(set(r['phyla'].split(',')))[:3])
    print(f"{i:<5} {r['virus_family']:<35} {r['cnt']:>6} {pct:>5.1f}% {phyla_short}")

unclassified = conn.execute(f"SELECT COUNT(*) FROM virus_master vm WHERE {ACTIVE} AND (virus_family IS NULL OR virus_family='' OR virus_family='Unclassified')").fetchone()[0]
print(f"\n  Unclassified/missing family: {unclassified} ({unclassified/1704*100:.1f}%)")

# ═══════════════════════════════════════════════
# TABLE 5: Model virus-host system evidence quality
# ═══════════════════════════════════════════════
print("\n" + "=" * 70)
print("TABLE 5: Evidence Strength for Model Virus-Host Systems")
print("=" * 70)

# Define model viruses by name patterns
model_viruses = [
    ("White spot syndrome virus", "WSSV", "Nimaviridae"),
    ("Ostreid herpesvirus 1", "OsHV-1", "Malacoherpesviridae"),
    ("Infectious hypodermal", "IHHNV", "Parvoviridae"),
    ("Macrobrachium rosenbergii nodavirus", "MrNV", "Nodaviridae"),
    ("Hepatopancreatic parvovirus", "HPV", "Parvoviridae"),
    ("Taura syndrome virus", "TSV", "Dicistroviridae"),
    ("Yellow head virus", "YHV", "Roniviridae"),
    ("Infectious myonecrosis virus", "IMNV", "Totiviridae"),
    ("Haliotid herpesvirus 1", "HaHV-1", "Malacoherpesviridae"),
]

print(f"{'Virus':<22} {'Family':<20} {'Total':>8} {'High':>8} {'Medium':>8} {'Low':>8} {'Rejected':>8}")
print("-" * 82)

for name_pat, abbr, family in model_viruses:
    # Find master_ids matching
    masters = conn.execute(
        f"SELECT master_id, canonical_name FROM virus_master "
        f"WHERE canonical_name LIKE ? AND {ACTIVE}",
        (f'%{name_pat}%',)
    ).fetchall()

    if not masters:
        print(f"{abbr:<22} {'(not found)':<20}")
        continue

    # Sum evidence across all matching masters
    total = high = medium = low = rejected = 0
    for m in masters:
        for row in conn.execute(
            "SELECT evidence_strength, curation_status, COUNT(*) cnt FROM evidence_records "
            "WHERE virus_master_id=? GROUP BY evidence_strength, curation_status",
            (m['master_id'],)
        ).fetchall():
            n = row['cnt']
            total += n
            if row['curation_status'] == 'rejected':
                rejected += n
            elif row['evidence_strength'] == 'high':
                high += n
            elif row['evidence_strength'] == 'medium':
                medium += n
            elif row['evidence_strength'] == 'low':
                low += n

    if total > 0:
        print(f"{abbr:<22} {family:<20} {total:>8,} {high:>8,} {medium:>8,} {low:>8,} {rejected:>8,}")
    else:
        print(f"{abbr:<22} {family:<20} {'(no evidence)':<8}")

# ═══════════════════════════════════════════════
# SUPPLEMENTARY TABLE S1: Database comparison
# ═══════════════════════════════════════════════
print("\n" + "=" * 70)
print("TABLE S1: Feature Comparison with Existing Virus Databases")
print("=" * 70)

features = [
    ("Aquatic invertebrate specialization", "Yes", "No", "No", "No", "No", "No"),
    ("Virus species (curated)", "1,704", ">10M accessions", "11,273", ">10K", "Clustered", ">15M"),
    ("Curated host species", "140 profiles", "N/A", "Coarse categories", "Inferred", "None", "Environmental"),
    ("Evidence grading (H/M/L)", "Yes (13.0/85.9/1.1%)", "No", "No", "No", "No", "No"),
    ("Curation status tracking", "Yes (4-tier)", "No", "No", "No", "No", "No"),
    ("PMID coverage", "92.1%", "Partial", "N/A", "PMID only", "N/A", "Minimal"),
    ("DOI coverage", "90.4%", "Partial", "N/A", "N/A", "N/A", "Minimal"),
    ("Protein functional annotation", "87.2% domain-inferred", "No", "No", "No", "No", "No"),
    ("Phylogenetic classification", "Yes (RdRP, 1,260 seqs)", "No", "No", "No", "No", "ViCTree"),
    ("SRA metagenomic index", "16,880 runs", "No", "No", "No", "No", "Yes"),
    ("Public visibility tiering", "Yes (3-tier)", "No", "No", "No", "No", "No"),
    ("Curation audit trail", "1,311 logs", "No", "No", "No", "No", "No"),
    ("Data provenance records", "100,599", "No", "No", "No", "No", "No"),
    ("REST API", "Yes (FastAPI)", "Yes", "No", "Yes", "No", "Yes"),
    ("Bulk download", "Yes (CC-BY 4.0)", "Yes", "Yes", "Yes", "Yes", "Yes"),
    ("Docker deployment", "Yes", "No", "No", "No", "No", "No"),
]

header = f"{'Feature':<42} {'AquaVir-KB':<25} {'NCBI Virus':<18} {'ICTV VMR':<15} {'Virus-Host DB':<15} {'RVDB':<12} {'IMG/VR':<12}"
print(header)
print("-" * len(header))
for row in features:
    print(f"{row[0]:<42} {row[1]:<25} {row[2]:<18} {row[3]:<15} {row[4]:<15} {row[5]:<12} {row[6]:<12}")

# ═══════════════════════════════════════════════
# ADDITIONAL: Evidence type breakdown table
# ═══════════════════════════════════════════════
print("\n" + "=" * 70)
print("Evidence Type Distribution (350,716 effective)")
print("=" * 70)
for r in conn.execute("""
    SELECT evidence_type, COUNT(*) cnt FROM evidence_records
    WHERE curation_status != 'rejected'
    GROUP BY evidence_type ORDER BY cnt DESC
""").fetchall():
    pct = r['cnt'] / 350716 * 100
    print(f"  {r['evidence_type']:<25s} {r['cnt']:>10,}  ({pct:.1f}%)")

# ═══════════════════════════════════════════════
# ADDITIONAL: ICTV status breakdown
# ═══════════════════════════════════════════════
print("\n" + "=" * 70)
print("ICTV Status Distribution")
print("=" * 70)
for r in conn.execute("SELECT ictv_status, COUNT(*) cnt FROM virus_ictv_status GROUP BY ictv_status ORDER BY cnt DESC").fetchall():
    print(f"  {r['ictv_status']:<30s} {r['cnt']:>6}")

# ═══════════════════════════════════════════════
# ADDITIONAL: Discovery context breakdown
# ═══════════════════════════════════════════════
print("\n" + "=" * 70)
print("Discovery Context Distribution (1,704 active)")
print("=" * 70)
for r in conn.execute(f"""
    SELECT discovery_context, COUNT(*) cnt FROM virus_master vm
    WHERE {ACTIVE} GROUP BY discovery_context ORDER BY cnt DESC
""").fetchall():
    pct = r['cnt'] / 1704 * 100
    print(f"  {r['discovery_context'] or 'NULL':<40s} {r['cnt']:>6}  ({pct:.1f}%)")

print("\nDone. Copy these tables into the manuscript.")
conn.close()
