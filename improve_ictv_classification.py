#!/usr/bin/env python3
"""
Improve ICTV classification for AquaVir-KB (P0-4 + P1-1 + P1-2).

Phase A: Create virus_ictv_status rows for 875 unmapped target masters.
Phase B: Match viruses to ictv_vmr by species name and accession.
Phase C: Fill missing genome_type (144) and family (87) from VMR + inference.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from db_utils import DB_PATH, backup_database, db_connection, db_transaction

BASE_DIR = Path(__file__).resolve().parent
REPORTS_DIR = BASE_DIR / "reports"

# ── Discovery pattern rules (adapted from refine_ictv_status.py) ──

DISCOVERY_PREFIXES = (
    "qianjiang ", "beihai ", "wenzhou ", "changjiang ", "hubei ",
    "shahe ", "wenling ", "sanxia ",
)

LIKE_PATTERNS = (
    "-like virus", " like virus", "marna-like", "picorna-like",
    "astro-like", "sobemo-like", "solemo-like", "yanvirus-like",
    "zhaovirus-like", "botourmia-like", "noda-like", "toti-like",
    "reo-like", "bunya-like", "levi-like", "tobamo-like",
    "tombus-like", "dicistro-like", "alphatetra-like", "kita-like",
)

DISCOVERY_FAMILIES = {
    "Astroviridae", "Botourmiaviridae", "Chuviridae", "Dicistroviridae",
    "Marnaviridae", "Picornaviridae", "Sobemoviridae", "Totiviridae",
    "Weiviridae", "Yanviridae", "Zhaoviridae",
}

# ── Family → genome_type inference table ──

FAMILY_GENOME_MAP: dict[str, str] = {
    "Malacoherpesviridae": "dsDNA",
    "Nimaviridae": "dsDNA",
    "Iridoviridae": "dsDNA",
    "Autographiviridae": "dsDNA",
    "Myoviridae": "dsDNA",
    "Podoviridae": "dsDNA",
    "Siphoviridae": "dsDNA",
    "Demerecviridae": "dsDNA",
    "Bacilladnaviridae": "ssDNA",
    "Parvoviridae": "ssDNA",
    "Circoviridae": "ssDNA",
    "Genomoviridae": "ssDNA",
    "Microviridae": "ssDNA",
    "Cruciviridae": "ssDNA",
    "Reoviridae": "dsRNA",
    "Sedoreoviridae": "dsRNA",
    "Spinareoviridae": "dsRNA",
    "Totiviridae": "dsRNA",
    "Birnaviridae": "dsRNA",
    "Chuviridae": "ssRNA(-)",
    "Artoviridae": "ssRNA(-)",
    "Rhabdoviridae": "ssRNA(-)",
    "Peribunyaviridae": "ssRNA(-)",
    "Phenuiviridae": "ssRNA(-)",
    "Nodaviridae": "ssRNA(+)",
    "Dicistroviridae": "ssRNA(+)",
    "Flaviviridae": "ssRNA(+)",
    "Picornaviridae": "ssRNA(+)",
    "Marnaviridae": "ssRNA(+)",
    "Sobemoviridae": "ssRNA(+)",
    "Botourmiaviridae": "ssRNA(+)",
    "Alphaflexiviridae": "ssRNA(+)",
    "Tombusviridae": "ssRNA(+)",
    "Togaviridae": "ssRNA(+)",
    "Hepeviridae": "ssRNA(+)",
    "Astroviridae": "ssRNA(+)",
    "Caliciviridae": "ssRNA(+)",
    "Closteroviridae": "ssRNA(+)",
    "Natareviridae": "ssRNA(+)",
    "Yanviridae": "ssRNA(+)",
    "Zhaoviridae": "ssRNA(+)",
    "Weiviridae": "ssRNA(+)",
    "Riboviria": "RNA",
    "Endornaviridae": "dsRNA",
    "Partitiviridae": "dsRNA",
    "Chrysoviridae": "dsRNA",
    "Fusariviridae": "ssRNA(+)",
    "Hytrosaviridae": "dsDNA",
    "Phasmaviridae": "ssRNA(-)",
    "Qinviridae": "ssRNA(-)",
}

# ICTV genome_composition → genome_type
GENOME_COMPOSITION_MAP: dict[str, str] = {
    "dsDNA": "dsDNA",
    "ssDNA": "ssDNA",
    "ssDNA(+/-)": "ssDNA",
    "dsRNA": "dsRNA",
    "ssRNA(+)": "ssRNA(+)",
    "ssRNA(-)": "ssRNA(-)",
    "ssRNA(+/-)": "ssRNA",
    "ssRNA": "ssRNA",
}


def stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


# ── Phase A helpers ──

def masters_without_ictv_status(conn) -> list[dict[str, Any]]:
    """Target virus_master entries missing a virus_ictv_status row."""
    return [
        dict(r)
        for r in conn.execute(
            """
            SELECT vm.master_id, vm.canonical_name, vm.virus_family, vm.virus_genus,
                   vm.genome_type, vm.entry_type, vm.host_phylum, vm.discovery_context,
                   vm.abbreviations,
                   (SELECT COUNT(*) FROM viral_isolates vi WHERE vi.master_id=vm.master_id) as isolate_count
            FROM virus_master vm
            WHERE vm.is_crustacean_virus = 1
              AND vm.entry_type NOT IN ('non_target', 'ictv_non_target')
              AND vm.master_id NOT IN (SELECT master_id FROM virus_ictv_status)
            ORDER BY vm.host_phylum, vm.canonical_name
            """
        ).fetchall()
    ]


def classify_unclassified_not_expected(name: str, family: str, entry_type: str,
                                        isolate_count: int, abbr: str) -> str | None:
    """Return reason if entry should be auto-classified as unclassified_not_expected."""
    name_l = name.lower()
    if "unclassified" in name_l:
        return "Name explicitly states unclassified status"
    if " sp." in name_l or name_l.endswith(" sp"):
        return "Rank-level or placeholder 'sp.' discovery name"
    if any(p in name_l for p in LIKE_PATTERNS):
        return "Contains '-like' discovery naming pattern"
    if entry_type == "unclassified_rna_virus":
        return "Entry type is unclassified_rna_virus"
    if (any(name_l.startswith(p) for p in DISCOVERY_PREFIXES)
            and family in DISCOVERY_FAMILIES and isolate_count <= 3):
        return "Low-replicate geographic discovery-series entry"
    if re.search(r"\bvirus\s+\d+[a-z]?$", name_l) and isolate_count <= 2 and family in DISCOVERY_FAMILIES:
        return "Numbered discovery-series with low replicate count"
    return None


# ── Phase B helpers ──

def match_vmr_species(conn, master_id: int, canonical_name: str) -> dict | None:
    """Try to find an exact species match in ictv_vmr."""
    row = conn.execute(
        "SELECT * FROM ictv_vmr WHERE LOWER(species) = LOWER(?) LIMIT 1",
        (canonical_name,),
    ).fetchone()
    return dict(row) if row else None


def match_vmr_accession(conn, master_id: int) -> dict | None:
    """Try to match a virus to ictv_vmr via isolate accession."""
    row = conn.execute(
        """
        SELECT iv.* FROM ictv_vmr iv
        JOIN viral_isolates vi ON iv.genbank_accession LIKE '%' || vi.accession || '%'
           OR vi.accession LIKE '%' || iv.genbank_accession || '%'
        WHERE vi.master_id = ? AND iv.genbank_accession IS NOT NULL AND iv.genbank_accession != ''
        LIMIT 1
        """,
        (master_id,),
    ).fetchone()
    return dict(row) if row else None


# ── Phase C helpers ──

def fill_genome_type_from_vmr(conn) -> int:
    """Fill missing genome_type from ictv_vmr.genome_composition for mapped viruses."""
    count = 0
    for mapping in ["ssRNA(+/-)", "dsDNA", "ssDNA", "ssDNA(+/-)", "dsRNA",
                     "ssRNA(+)", "ssRNA(-)", "ssRNA"]:
        result = conn.execute(
            """
            UPDATE virus_master
            SET genome_type = ?
            WHERE master_id IN (
                SELECT vvm.master_id FROM virus_vmr_mappings vvm
                JOIN ictv_vmr iv ON vvm.vmr_id = iv.vmr_id
                WHERE iv.genome_composition = ?
            )
            AND (genome_type IS NULL OR genome_type = '')
            AND is_crustacean_virus = 1
            AND entry_type NOT IN ('non_target', 'ictv_non_target')
            """,
            (GENOME_COMPOSITION_MAP.get(mapping, mapping), mapping),
        )
        count += result.rowcount
    return count


def fill_genome_type_from_family(conn) -> int:
    """Fill missing genome_type from FAMILY_GENOME_MAP inference."""
    count = 0
    for family, gtype in FAMILY_GENOME_MAP.items():
        result = conn.execute(
            """
            UPDATE virus_master
            SET genome_type = ?,
                notes = COALESCE(notes || '; ', '') || ?
            WHERE virus_family = ?
              AND (genome_type IS NULL OR genome_type = '')
              AND is_crustacean_virus = 1
              AND entry_type NOT IN ('non_target', 'ictv_non_target')
            """,
            (gtype, f"genome_type_inferred_from_family:{family}", family),
        )
        count += result.rowcount
    return count


def fill_family_from_vmr(conn) -> int:
    """Fill missing virus_family from ictv_vmr.family for mapped viruses."""
    result = conn.execute(
        """
        UPDATE virus_master
        SET virus_family = (
            SELECT iv.family FROM virus_vmr_mappings vvm
            JOIN ictv_vmr iv ON vvm.vmr_id = iv.vmr_id
            WHERE vvm.master_id = virus_master.master_id
            AND iv.family IS NOT NULL AND iv.family != ''
            LIMIT 1
        ),
        notes = COALESCE(notes || '; ', '') || 'family_inferred_from_vmr'
        WHERE (virus_family IS NULL OR virus_family = '')
          AND is_crustacean_virus = 1
          AND entry_type NOT IN ('non_target', 'ictv_non_target')
          AND master_id IN (SELECT master_id FROM virus_vmr_mappings)
        """
    )
    return result.rowcount


def fill_family_from_isolates(conn) -> int:
    """Fill missing virus_family from isolate taxonomy for viruses with a single family."""
    result = conn.execute(
        """
        UPDATE virus_master
        SET virus_family = (
            SELECT vi.taxon_family FROM viral_isolates vi
            WHERE vi.master_id = virus_master.master_id
              AND vi.taxon_family IS NOT NULL AND vi.taxon_family != ''
            GROUP BY vi.taxon_family ORDER BY COUNT(*) DESC LIMIT 1
        ),
        notes = COALESCE(notes || '; ', '') || 'family_inferred_from_isolate_taxonomy'
        WHERE (virus_family IS NULL OR virus_family = '')
          AND is_crustacean_virus = 1
          AND entry_type NOT IN ('non_target', 'ictv_non_target')
          AND EXISTS (
              SELECT 1 FROM viral_isolates vi
              WHERE vi.master_id = virus_master.master_id
                AND vi.taxon_family IS NOT NULL AND vi.taxon_family != ''
          )
        """
    )
    return result.rowcount


# ── Main ──

def main() -> None:
    p = argparse.ArgumentParser(description="Improve ICTV classification (P0-4+P1-1+P1-2)")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--skip-vmr-match", action="store_true", help="Skip VMR species/accession matching")
    args = p.parse_args()

    ts = stamp()
    REPORTS_DIR.mkdir(exist_ok=True)
    summary: dict[str, Any] = {"timestamp": ts, "dry_run": args.dry_run}

    # ── Read phase: gather state ──
    with db_connection(read_only=True) as conn:
        unmapped = masters_without_ictv_status(conn)
        summary["masters_without_ictv_status"] = len(unmapped)

        # Already mapped count
        mapped_before = conn.execute(
            "SELECT COUNT(*) FROM virus_ictv_status WHERE ictv_status = 'mapped'"
        ).fetchone()[0]
        summary["ictv_mapped_before"] = mapped_before

        # genome_type missing
        missing_gt = conn.execute(
            """
            SELECT COUNT(*) FROM virus_master
            WHERE is_crustacean_virus = 1 AND entry_type NOT IN ('non_target','ictv_non_target')
              AND (genome_type IS NULL OR genome_type = '')
            """
        ).fetchone()[0]
        summary["missing_genome_type_before"] = missing_gt

        # family missing
        missing_fam = conn.execute(
            """
            SELECT COUNT(*) FROM virus_master
            WHERE is_crustacean_virus = 1 AND entry_type NOT IN ('non_target','ictv_non_target')
              AND (virus_family IS NULL OR virus_family = '')
            """
        ).fetchone()[0]
        summary["missing_family_before"] = missing_fam

        # Count VMR species matches
        vmr_species_matches = 0
        vmr_accession_matches = 0
        if not args.skip_vmr_match:
            for m in unmapped:
                if match_vmr_species(conn, m["master_id"], m["canonical_name"]):
                    vmr_species_matches += 1
                elif match_vmr_accession(conn, m["master_id"]):
                    vmr_accession_matches += 1
        summary["vmr_species_matches_available"] = vmr_species_matches
        summary["vmr_accession_matches_available"] = vmr_accession_matches

    if args.dry_run:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return

    # ── Write phase ──
    backup_path = backup_database(label="before_improve_ictv")

    with db_transaction() as conn:
        # Phase A: Create virus_ictv_status rows
        auto_unclassified = 0
        auto_mapped = 0
        auto_pending = 0
        for m in unmapped:
            name = m["canonical_name"] or ""
            family = m["virus_family"] or ""
            entry_type = m["entry_type"] or ""
            iso_count = m["isolate_count"] or 0
            abbr = m["abbreviations"] or ""

            # Check if already has virus_ictv_mappings
            existing_map = conn.execute(
                "SELECT COUNT(*) FROM virus_ictv_mappings WHERE master_id = ?",
                (m["master_id"],),
            ).fetchone()[0]

            if existing_map > 0:
                status = "mapped"
                reason = "Existing virus_ictv_mappings entry found"
                auto_mapped += 1
            elif not args.skip_vmr_match and match_vmr_species(conn, m["master_id"], name):
                status = "mapped"
                reason = "Species matched to ICTV VMR"
                # Create vmr_mapping
                vmr = match_vmr_species(conn, m["master_id"], name)
                if vmr:
                    conn.execute(
                        """
                        INSERT OR IGNORE INTO virus_vmr_mappings (
                            master_id, vmr_id, match_type, matched_value,
                            match_status, confidence, created_at
                        ) VALUES (?, ?, 'species_exact', ?, 'auto_mapped', 'high', ?)
                        """,
                        (m["master_id"], vmr["vmr_id"], name, ts),
                    )
                    # Update master taxonomy from VMR
                    if vmr.get("family") and not m["virus_family"]:
                        conn.execute(
                            "UPDATE virus_master SET virus_family=? WHERE master_id=?",
                            (vmr["family"], m["master_id"]),
                        )
                    if vmr.get("genus") and not m["virus_genus"]:
                        conn.execute(
                            "UPDATE virus_master SET virus_genus=? WHERE master_id=?",
                            (vmr["genus"], m["master_id"]),
                        )
                auto_mapped += 1
            else:
                # Try auto-classification
                reason = classify_unclassified_not_expected(name, family, entry_type, iso_count, abbr)
                if reason:
                    status = "unclassified_not_expected"
                    auto_unclassified += 1
                else:
                    status = "pending_review"
                    reason = "Needs manual taxonomic review"
                    auto_pending += 1

            conn.execute(
                """
                INSERT OR IGNORE INTO virus_ictv_status (
                    master_id, ictv_status, mapping_count, best_confidence, reason, updated_at
                ) VALUES (?, ?, 0, NULL, ?, ?)
                """,
                (m["master_id"], status, reason, ts),
            )

        summary["phase_a"] = {
            "total_processed": len(unmapped),
            "auto_mapped": auto_mapped,
            "auto_unclassified_not_expected": auto_unclassified,
            "auto_pending_review": auto_pending,
        }

        # Phase C: Fill genome_type and family
        gt_from_vmr = fill_genome_type_from_vmr(conn)
        gt_from_family = fill_genome_type_from_family(conn)
        fam_from_vmr = fill_family_from_vmr(conn)
        fam_from_isolates = fill_family_from_isolates(conn)
        summary["phase_c"] = {
            "genome_type_filled_from_vmr": gt_from_vmr,
            "genome_type_filled_from_family": gt_from_family,
            "family_filled_from_vmr": fam_from_vmr,
            "family_filled_from_isolates": fam_from_isolates,
        }

    # ── Verification ──
    with db_connection(read_only=True) as conn:
        mapped_after = conn.execute(
            "SELECT COUNT(*) FROM virus_ictv_status WHERE ictv_status = 'mapped'"
        ).fetchone()[0]
        summary["ictv_mapped_after"] = mapped_after

        missing_gt_after = conn.execute(
            """
            SELECT COUNT(*) FROM virus_master
            WHERE is_crustacean_virus = 1 AND entry_type NOT IN ('non_target','ictv_non_target')
              AND (genome_type IS NULL OR genome_type = '')
            """
        ).fetchone()[0]
        summary["missing_genome_type_after"] = missing_gt_after

        missing_fam_after = conn.execute(
            """
            SELECT COUNT(*) FROM virus_master
            WHERE is_crustacean_virus = 1 AND entry_type NOT IN ('non_target','ictv_non_target')
              AND (virus_family IS NULL OR virus_family = '')
            """
        ).fetchone()[0]
        summary["missing_family_after"] = missing_fam_after

        # VMR mappings total
        vmr_total = conn.execute("SELECT COUNT(*) FROM virus_vmr_mappings").fetchone()[0]
        summary["vmr_mappings_total"] = vmr_total

        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        fk_count = len(conn.execute("PRAGMA foreign_key_check").fetchall())
        summary["integrity_check"] = integrity
        summary["foreign_key_violations"] = fk_count

    summary["backup_path"] = str(backup_path)
    report_path = REPORTS_DIR / f"ictv_classification_improvement_{ts}.json"
    report_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
