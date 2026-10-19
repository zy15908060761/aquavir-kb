from __future__ import annotations

import argparse
import os
import re
import sqlite3
import zipfile
from datetime import datetime
from pathlib import Path

import pandas as pd
from build_public_download_metadata import main as build_public_download_metadata


# Fixed timestamp for deterministic (reproducible) release artifacts.
# Freeze date; overridable via SOURCE_DATE_EPOCH for reproducible builds.
_EPOCH = os.environ.get("SOURCE_DATE_EPOCH")
FIXED_DT = datetime.fromtimestamp(int(_EPOCH)) if _EPOCH else datetime(2026, 10, 5, 0, 0, 0)

# Matches W3CDTF timestamps inside docProps/core.xml (created/modified).
_W3CDTF_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")

# ── Withdrawn host-association batch (2026-10-14) ──────────────────────
# Mirrors _WITHDRAWN_HOST_IDS / _WITHDRAWN_RECORD_IDS in backend.py: the
# 3,750 synthetic placeholder rows (host_id 37 + PALMDB_u* accession), the
# 523 host-mapping 'flag_pending' record_ids from
# HOST_FIX_CHANGESET_v3_20261013.csv, and host 37 (Acanthaster planci)
# in full -- an echinoderm mislabelled target_mollusk whose remaining rows
# are host-genome / cross-species contamination.  These builders read the
# frozen DB directly, so the connection-local TEMP VIEWs the web app relies
# on do not reach them; the predicate is repeated here instead.
_WITHDRAWN_HOST_IDS = (37,)
_WITHDRAWN_RECORD_IDS = (294, 296, 297, 298, 299, 300, 301, 303, 304, 305, 306, 307, 308, 309, 310, 311, 312, 313, 314, 315, 318, 319, 322, 323, 324, 325, 326, 327, 328, 329, 330, 331, 332, 333, 334, 335, 336, 337, 338, 339, 340, 341, 342, 343, 345, 346, 347, 349, 350, 351, 352, 353, 354, 355, 356, 357, 358, 359, 360, 361, 362, 363, 364, 365, 366, 367, 368, 369, 370, 371, 372, 373, 374, 375, 376, 377, 378, 379, 380, 381, 382, 383, 384, 385, 386, 387, 388, 389, 390, 391, 392, 393, 394, 395, 396, 397, 398, 399, 400, 401, 402, 403, 404, 405, 406, 407, 408, 409, 410, 411, 412, 413, 414, 415, 432, 433, 434, 435, 436, 437, 438, 439, 440, 502, 503, 504, 505, 506, 507, 509, 510, 511, 512, 513, 514, 515, 516, 518, 519, 521, 770, 772, 773, 820, 1389, 1398, 1399, 1457, 1458, 1823, 1865, 2058, 2059, 2060, 2082, 2085, 2086, 2205, 2268, 2269, 2270, 2271, 2272, 2519, 3101, 3106, 3322, 3323, 3324, 3325, 3326, 3327, 3329, 3330, 3331, 3335, 3336, 3337, 3338, 3339, 3341, 3342, 3343, 3344, 3345, 3354, 3366, 3631, 3698, 3709, 3781, 3788, 3790, 3791, 3792, 3794, 3795, 3796, 3797, 3798, 3799, 3800, 3922, 3987, 3993, 4020, 4021, 4022, 4023, 4024, 4034, 4035, 4036, 4053, 4811, 4812, 4813, 4814, 4815, 4816, 4817, 4818, 4819, 4820, 4821, 4822, 4823, 4824, 4825, 4826, 4827, 4828, 4829, 4830, 4831, 4832, 4833, 4834, 4835, 4836, 4837, 4838, 4839, 4840, 4841, 4842, 4843, 4844, 4845, 4846, 4847, 4848, 4849, 4850, 4851, 4852, 4853, 4854, 4855, 4856, 4857, 4858, 4859, 4860, 4861, 4862, 4863, 4864, 4865, 4866, 4867, 4868, 4869, 4870, 4871, 4872, 4873, 4874, 4875, 4876, 4877, 4881, 5274, 5276, 5282, 5284, 5287, 5308, 5311, 5313, 5315, 5324, 5332, 5337, 5342, 5349, 5363, 5365, 5370, 5373, 5374, 5375, 5377, 5384, 5391, 5392, 5393, 5394, 5395, 5399, 5400, 5402, 5403, 5406, 5409, 5410, 5412, 5413, 5423, 5424, 5425, 5426, 5427, 5429, 5430, 5431, 5433, 5436, 5438, 5440, 5441, 5442, 5448, 5449, 5450, 5456, 5457, 5461, 5462, 5464, 5465, 5467, 5470, 5475, 5478, 5479, 5481, 5482, 5487, 5493, 5494, 5497, 5498, 5502, 5504, 5506, 5508, 5510, 5512, 5513, 5514, 5520, 5527, 5535, 5538, 5539, 5541, 5542, 5546, 5549, 5561, 5563, 5566, 5571, 5574, 5576, 5578, 5580, 5582, 5585, 5586, 5594, 5596, 5599, 5600, 5602, 5603, 5604, 5607, 5609, 5613, 5614, 5621, 5622, 5623, 5624, 5626, 5628, 5630, 5632, 5633, 5637, 5639, 5640, 5642, 5643, 5647, 5655, 5656, 5666, 5668, 5669, 5670, 5671, 5672, 5675, 5676, 5677, 5678, 5681, 5682, 5683, 5685, 5687, 5689, 5692, 5695, 5700, 5701, 5702, 5704, 5707, 5708, 5710, 5712, 5715, 5717, 5718, 5719, 5720, 5724, 9230, 9231, 9233, 9235, 9236, 9238, 9243, 9244, 9245, 9246, 9247, 9248, 9249, 9250, 9251, 9252, 9253, 9254, 9255, 9256, 9257, 9258, 9261, 9262, 9263, 9264, 9265, 9267, 9269, 9270, 9271, 9272, 9273, 9306, 9317, 9318, 9319, 9320, 9321, 9322, 9323, 9324, 9411, 9490, 9491, 9492, 9493, 9502, 9504, 9505, 9506, 9507, 9531, 9534, 9535, 9575, 9589, 9590, 9593, 9594, 9724, 9725, 9726, 9727, 9728, 9729, 9730, 9731, 9732, 9736, 9737, 9738, 9739, 9740, 9761, 9762, 9763, 9774, 9776, 9786, 9793, 10166)


def _withdrawal_sql(alias: str) -> str:
    """SQL predicate excluding the withdrawn host-association rows (alias.ir)."""
    return "IFNULL(%s.host_id, 0) NOT IN (%s) AND %s.record_id NOT IN (%s)" % (
        alias, ",".join(str(i) for i in _WITHDRAWN_HOST_IDS),
        alias, ",".join(str(i) for i in _WITHDRAWN_RECORD_IDS),
    )


def _canonicalize_xlsx(path: Path, dt: datetime) -> None:
    """Make the xlsx byte-stable: fixed per-entry mtime + fixed core.xml timestamps.

    openpyxl rewrites dcterms:modified at save time, so pinning workbook properties
    is not sufficient; we rewrite core.xml content directly here.
    """
    tt = (dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second)
    iso = dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    tmp = str(path) + ".canon"
    with zipfile.ZipFile(path) as zin, zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
        for name in zin.namelist():
            data = zin.read(name)
            if name == "docProps/core.xml":
                data = _W3CDTF_RE.sub(iso, data.decode("utf-8")).encode("utf-8")
            zi = zipfile.ZipInfo(name, date_time=tt)
            zi.compress_type = zipfile.ZIP_DEFLATED
            zout.writestr(zi, data)
    os.replace(tmp, path)


def _write_xlsx_deterministic(df: pd.DataFrame, out_file: Path, sheet_name: str) -> None:
    """Write df to xlsx with fixed core properties + canonical zip headers."""
    with pd.ExcelWriter(out_file, engine="openpyxl") as xw:
        df.to_excel(xw, index=False, sheet_name=sheet_name)
        xw.book.properties.created = FIXED_DT
        xw.book.properties.modified = FIXED_DT
    _canonicalize_xlsx(out_file, FIXED_DT)


_ILLEGAL_CHARS_RE = re.compile(r"[\000-\010]|[\013-\014]|[\016-\037]")


def _sanitize_excel(df: pd.DataFrame) -> pd.DataFrame:
    """Strip control characters that openpyxl rejects in worksheet cells."""
    def _clean(v):
        if isinstance(v, str):
            return _ILLEGAL_CHARS_RE.sub("", v)
        return v
    return df.map(_clean)


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "deploy" / "data"
DB_PATH = DATA_DIR / "crustacean_virus_core.db"
SEQ_DIR = DATA_DIR / "sequences"
OUT_DIR = DATA_DIR / "public_downloads"
INTERNAL_OUT_DIR = DATA_DIR / "maintenance_archive" / "internal_candidate_exports"
OUT_DIR.mkdir(exist_ok=True)
INTERNAL_OUT_DIR.mkdir(parents=True, exist_ok=True)


def read_sql(sql: str) -> pd.DataFrame:
    with sqlite3.connect(DB_PATH) as conn:
        df = pd.read_sql_query(sql, conn)
    return _sanitize_excel(df)


def build_complete_genomes_fasta() -> Path:
    """Export strict-target complete genomes, dropping short gene-fragment records.

    For large viruses (per-species max length >= 10kb), keep only sequences
    >= 2kb so that short fragments (e.g. WSSV ORF75 gene, 1064bp) are excluded.
    Small/segmented viruses (per-species max < 10kb) are exported whole so that
    their genuine <2kb segments are not dropped.
    """
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute(
            """
            WITH cg AS (
                SELECT isolate_id, accession, master_id,
                       COALESCE(sequence_length, genome_length, 0) AS seq_len
                FROM analysis_strict_target_isolates
                WHERE completeness = 'complete_genome'
                  AND master_id NOT IN (
                      SELECT master_id FROM virus_master
                      WHERE entry_type IN ('host_genome','duplicate_alias_placeholder',
                                           'duplicate_ictv_vmr_placeholder','aggregation_bucket',
                                           'merged_duplicate'))
            ),
            maxlen AS (
                SELECT master_id, MAX(seq_len) AS max_len
                FROM cg GROUP BY master_id
            )
            SELECT cg.accession
            FROM cg JOIN maxlen ON cg.master_id = maxlen.master_id
            WHERE cg.seq_len >= 2000 OR maxlen.max_len < 10000
            ORDER BY cg.accession
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
              AND master_id NOT IN (
                  SELECT master_id FROM virus_master
                  WHERE entry_type IN ('host_genome','duplicate_alias_placeholder',
                                       'duplicate_ictv_vmr_placeholder','aggregation_bucket',
                                       'merged_duplicate'))
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
    _write_xlsx_deterministic(df, out_file, "evidence")
    print(f"reviewed_evidence_records.xlsx: {len(df)} records")
    return out_file


def build_network_csv() -> Path:
    df = read_sql(
        """
        SELECT vm.canonical_name AS virus_name,
               h.scientific_name AS host_name,
               COUNT(*) AS record_count
        FROM analysis_strict_target_isolates v
        JOIN virus_master vm ON v.master_id = vm.master_id
        JOIN infection_records ir ON v.isolate_id = ir.isolate_id
             AND {withdrawal}
        JOIN crustacean_hosts h ON ir.host_id = h.host_id
        WHERE v.master_id NOT IN (
            SELECT master_id FROM virus_master
            WHERE entry_type IN ('host_genome','duplicate_alias_placeholder',
                                 'duplicate_ictv_vmr_placeholder','aggregation_bucket',
                                 'merged_duplicate'))
        GROUP BY vm.canonical_name, h.scientific_name
        ORDER BY record_count DESC
        """.format(withdrawal=_withdrawal_sql("ir"))
    )
    out_file = OUT_DIR / "host_virus_network.csv"
    df.to_csv(out_file, index=False, encoding="utf-8-sig")
    print(f"host_virus_network.csv: {len(df)} edges")
    return out_file


def build_metadata_standardized() -> Path:
    df = read_sql(
        """
        SELECT
            v.accession, vm.canonical_name, vm.abbreviations,
            vm.entry_type, v.completeness, v.molecule_type, v.sequence_length,
            v.genome_length, v.taxon_family, v.taxon_genus, v.taxon_species,
            h.scientific_name AS host_name,
            s.country, s.collection_year, s.collection_date,
            l.title AS ref_title, l.pmid, l.doi,
            icp.dataset_tier, icp.curation_status, icp.confidence
        FROM analysis_strict_target_isolates v
        LEFT JOIN virus_master vm ON v.master_id = vm.master_id
        LEFT JOIN infection_records ir ON v.isolate_id = ir.isolate_id
             AND {withdrawal}
        LEFT JOIN crustacean_hosts h ON ir.host_id = h.host_id
        LEFT JOIN sample_collections s ON ir.collection_id = s.collection_id
        LEFT JOIN ref_literatures l ON v.reference_id = l.reference_id
        LEFT JOIN isolate_curated_profiles icp ON icp.isolate_id = v.isolate_id
        WHERE v.master_id NOT IN (
            SELECT master_id FROM virus_master
            WHERE entry_type IN ('host_genome','duplicate_alias_placeholder',
                                 'duplicate_ictv_vmr_placeholder','aggregation_bucket',
                                 'merged_duplicate'))
        ORDER BY v.accession
        """.format(withdrawal=_withdrawal_sql("ir"))
    )
    out_file = OUT_DIR / "crustacean_virus_metadata_standardized.xlsx"
    _write_xlsx_deterministic(df, out_file, "virus_metadata")
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
