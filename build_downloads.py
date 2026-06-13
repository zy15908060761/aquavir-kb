from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

import pandas as pd
from build_public_download_metadata import main as build_public_download_metadata


BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "crustacean_virus_core.db"
SEQ_DIR = BASE_DIR / "sequences"
OUT_DIR = BASE_DIR / "public_downloads"
INTERNAL_OUT_DIR = BASE_DIR / "maintenance_archive" / "internal_candidate_exports"
OUT_DIR.mkdir(exist_ok=True)
INTERNAL_OUT_DIR.mkdir(parents=True, exist_ok=True)


def read_sql(sql: str) -> pd.DataFrame:
    with sqlite3.connect(DB_PATH) as conn:
        return pd.read_sql_query(sql, conn)


def build_complete_genomes_fasta() -> Path:
    """Export only strict target complete genomes with plausible length."""
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute(
            """
            SELECT accession
            FROM analysis_strict_target_isolates
            WHERE completeness = 'complete_genome'
              AND COALESCE(sequence_length, genome_length, 0) >= 1000
            ORDER BY accession
            """
        ).fetchall()
    accessions = [r[0] for r in rows]

    out_file = OUT_DIR / "complete_genomes.fasta"
    written = 0
    with out_file.open("w", encoding="utf-8") as fout:
        for acc in accessions:
            fa_file = SEQ_DIR / f"{acc}.fasta"
            if fa_file.exists():
                text = fa_file.read_text(encoding="utf-8", errors="replace")
                fout.write(text)
                if text and not text.endswith("\n"):
                    fout.write("\n")
                written += 1

    print(f"complete_genomes.fasta: {written}/{len(accessions)} sequences")
    return out_file


def build_all_sequences_fasta() -> Path:
    """Export only strict target sequences."""
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute(
            """
            SELECT accession
            FROM analysis_strict_target_isolates
            WHERE has_sequence = 1
            ORDER BY accession
            """
        ).fetchall()
    accessions = [r[0] for r in rows]

    out_file = OUT_DIR / "all_sequences.fasta"
    written = 0
    with out_file.open("w", encoding="utf-8") as fout:
        for acc in accessions:
            fa_file = SEQ_DIR / f"{acc}.fasta"
            if fa_file.exists():
                text = fa_file.read_text(encoding="utf-8", errors="replace")
                fout.write(text)
                if text and not text.endswith("\n"):
                    fout.write("\n")
                written += 1

    print(f"all_sequences.fasta: {written}/{len(accessions)} sequences")
    return out_file


def build_candidate_virulence_excel() -> Path:
    df = read_sql("SELECT * FROM virulence_profiles ORDER BY virus_name")
    df.insert(0, "curation_scope", "candidate_unreviewed")
    out_file = INTERNAL_OUT_DIR / "candidate_virulence_profiles.xlsx"
    df.to_excel(out_file, index=False)
    print(f"internal candidate_virulence_profiles.xlsx: {len(df)} records")
    return out_file


def build_candidate_temperature_excel() -> Path:
    df = read_sql("SELECT * FROM temperature_profiles ORDER BY virus_name")
    df.insert(0, "curation_scope", "candidate_unreviewed")
    out_file = INTERNAL_OUT_DIR / "candidate_temperature_profiles.xlsx"
    df.to_excel(out_file, index=False)
    print(f"internal candidate_temperature_profiles.xlsx: {len(df)} records")
    return out_file


def build_reviewed_evidence_excel() -> Path:
    df = read_sql(
        """
        SELECT er.*
        FROM evidence_records er
        LEFT JOIN ref_literatures rl ON rl.reference_id = er.reference_id
        WHERE er.curation_status = 'manual_checked'
          AND er.evidence_type IN (
            'virulence', 'pathogenicity', 'mortality',
            'temperature', 'thermal_tolerance', 'host_range', 'diagnosis'
          )
          AND (
              NULLIF(TRIM(COALESCE(er.source_pmid, '')), '') IS NOT NULL
           OR NULLIF(TRIM(COALESCE(er.source_doi, '')), '') IS NOT NULL
           OR NULLIF(TRIM(COALESCE(rl.pmid, '')), '') IS NOT NULL
           OR NULLIF(TRIM(COALESCE(rl.doi, '')), '') IS NOT NULL
          )
        ORDER BY er.evidence_type, er.evidence_id
        """
    )
    out_file = OUT_DIR / "reviewed_evidence_records.xlsx"
    df.to_excel(out_file, index=False)
    print(f"reviewed_evidence_records.xlsx: {len(df)} records")
    return out_file


def build_network_csv() -> Path:
    df = read_sql(
        """
        SELECT vm.canonical_name AS virus_name,
               h.scientific_name AS host_name,
               h.common_name_cn AS host_cn,
               COUNT(*) AS record_count
        FROM analysis_strict_target_isolates v
        JOIN virus_master vm ON v.master_id = vm.master_id
        JOIN infection_records ir ON v.isolate_id = ir.isolate_id
        JOIN crustacean_hosts h ON ir.host_id = h.host_id
        GROUP BY vm.canonical_name, h.scientific_name, h.common_name_cn
        ORDER BY record_count DESC
        """
    )
    out_file = OUT_DIR / "host_virus_network.csv"
    df.to_csv(out_file, index=False, encoding="utf-8-sig")
    print(f"host_virus_network.csv: {len(df)} edges")
    return out_file


def build_metadata_standardized() -> Path:
    df = read_sql(
        """
        SELECT
            v.accession, vm.canonical_name, vm.chinese_name, vm.abbreviations,
            vm.entry_type, v.completeness, v.molecule_type, v.sequence_length,
            v.genome_length, v.taxon_family, v.taxon_genus, v.taxon_species,
            h.scientific_name AS host_name, h.common_name_cn AS host_cn,
            s.country, s.collection_year, s.collection_date,
            l.title AS ref_title, l.pmid, l.doi,
            icp.dataset_tier, icp.curation_status, icp.confidence
        FROM analysis_strict_target_isolates v
        LEFT JOIN virus_master vm ON v.master_id = vm.master_id
        LEFT JOIN infection_records ir ON v.isolate_id = ir.isolate_id
        LEFT JOIN crustacean_hosts h ON ir.host_id = h.host_id
        LEFT JOIN sample_collections s ON ir.collection_id = s.collection_id
        LEFT JOIN ref_literatures l ON v.reference_id = l.reference_id
        LEFT JOIN isolate_curated_profiles icp ON icp.isolate_id = v.isolate_id
        ORDER BY v.accession
        """
    )
    out_file = OUT_DIR / "crustacean_virus_metadata_standardized.xlsx"
    df.to_excel(out_file, index=False)
    print(f"metadata_standardized.xlsx: {len(df)} records")
    return out_file


def main() -> None:
    parser = argparse.ArgumentParser(description="Build release-safe public download files.")
    parser.add_argument(
        "--internal-candidates",
        action="store_true",
        help="Also export unreviewed internal candidate workbooks to maintenance_archive.",
    )
    args = parser.parse_args()

    print("Building release-safe public download files...")
    build_all_sequences_fasta()
    build_complete_genomes_fasta()
    if args.internal_candidates:
        build_candidate_virulence_excel()
        build_candidate_temperature_excel()
    build_reviewed_evidence_excel()
    build_network_csv()
    build_metadata_standardized()
    build_public_download_metadata()
    print(f"\nPublic files built in: {OUT_DIR}")


if __name__ == "__main__":
    main()
