#!/usr/bin/env python3
"""
Expand evidence depth: extract diagnostic, pathology, and challenge experiment
evidence from fulltext sections.

Scans literature_fulltext_sections for paragraphs matching diagnostic methods
(PCR, qPCR, ELISA, microscopy) and pathogenicity signals (mortality, challenge,
histopathology), then creates new evidence_records linked through the
reference -> isolate -> virus chain.

Idempotent: uses SHA-256 claim hashing to skip duplicates.
Safe: --dry-run mode, WAL-safe backup before writes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

# ── Paths ────────────────────────────────────────────────────────
APP_DIR = Path(__file__).resolve().parent
DB_PATH = APP_DIR / "crustacean_virus_core.db"
REPORTS_DIR = APP_DIR / "reports"
BACKUPS_DIR = APP_DIR / "backups"


def stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def connect(db_path: Path = DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path), timeout=120)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 120000")
    return conn


def backup(db_path: Path, label: str) -> Path:
    """WAL-safe backup before writes."""
    BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
    ts = stamp()
    safe_label = label.replace(" ", "_").replace("/", "_").replace("\\", "_")
    backup_base = BACKUPS_DIR / f"crustacean_virus_core_{safe_label}_{ts}"

    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        conn.close()

    import shutil
    shutil.copy2(str(db_path), str(backup_base.with_suffix(".db")))
    for suffix in (".db-wal", ".db-shm"):
        src = Path(str(db_path) + suffix)
        if src.exists():
            dst = Path(str(backup_base.with_suffix("")) + suffix)
            shutil.copy2(str(src), str(dst))
    print(f"[backup] WAL-safe backup -> {backup_base.with_suffix('.db').name}")
    return backup_base.with_suffix(".db")


# ── Keyword rules ─────────────────────────────────────────────────

DIAGNOSTIC_TERMS = [
    # PCR methods (checked case-insensitively with word boundaries)
    r"\bpcr\b", r"\bqpcr\b", r"\brt-pcr\b", r"\breal-time pcr\b",
    r"\bnested pcr\b", r"\blamp\b", r"\bloop-mediated\b",
    # Serology
    r"\belisa\b", r"\bwestern blot\b", r"\bimmunohistochemistry\b",
    r"\bimmunofluorescence\b", r"\bimmunoassay\b",
    # Microscopy
    r"\btem\b", r"\bsem\b", r"\belectron microscop", r"\btransmission electron\b",
    r"\bscanning electron\b",
    # Molecular detection
    r"\bin situ hybridization\b", r"\bish\b", r"\bngs\b", r"\bmetagenom",
    r"\bdetected by\b", r"\bdiagnostic\b", r"\bdetection\b",
    r"\bvirus isolation\b", r"\bcell culture\b", r"\btissue culture\b",
]

PATHOGENICITY_TERMS = [
    r"\bmortality\b", r"\blethal\b", r"\bld50\b", r"\bld 50\b",
    r"\bchallenge\b", r"\bchallenged\b", r"\binoculated\b", r"\binjected\b",
    r"\bexperimental infection\b", r"\bpathogenicity\b", r"\bvirulence\b",
    r"\bhistopatholog", r"\btissue tropism\b", r"\bdisease signs\b",
    r"\bclinical signs\b", r"\bmoribund\b", r"\bcumulative mortality\b",
    r"\bsurvival\b", r"\bdpi\b", r"\bdays post\b",
    r"\bdark spots\b", r"\bwhite spot\b", r"\bred body\b",
    r"\bnecropsy\b", r"\blesion\b",
]

# Excluded sections
EXCLUDED_SECTIONS = {
    "references", "acknowledgements", "acknowledgments",
    "funding", "author contributions", "competing interests",
    "data availability", "supplementary material", "supplementary information",
    "conflict of interest", "ethical statement", "ethics",
}

# ── Helper functions ──────────────────────────────────────────────


def clean_space(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").replace("\xa0", " ")).strip()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def split_sentences(text: str) -> list[str]:
    """Split text into sentences of reasonable length."""
    text = clean_space(text)
    if not text or len(text) < 60:
        return []
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9])", text)
    sentences = []
    for part in parts:
        part = clean_space(part)
        if 40 <= len(part) <= 800:
            sentences.append(part)
    return sentences


def section_allowed(section_type: str | None, section_title: str | None) -> bool:
    combined = f"{(section_type or '').lower()} {(section_title or '').lower()}"
    return not any(token in combined for token in EXCLUDED_SECTIONS)


def match_patterns(text: str, patterns: list[str]) -> list[str]:
    """Return list of matched pattern strings (first match group or pattern)."""
    lower = text.lower()
    matched = []
    for pat in patterns:
        if re.search(pat, lower):
            matched.append(pat)
    return matched


def extract_mortality_values(text: str) -> dict[str, Any]:
    """Extract mortality %, LD50, DPI values from text."""
    values: dict[str, Any] = {}

    # Mortality percentage with context
    m = re.findall(
        r"(?:mortality|mortalities|death|lethal|survival)[^.!?\n]{0,80}?"
        r"(\d{1,3}(?:\.\d+)?)\s*%",
        text, re.IGNORECASE
    )
    if m:
        nums = [float(x) for x in m if 0 <= float(x) <= 100]
        if nums:
            values["mortality_pct_min"] = min(nums)
            values["mortality_pct_max"] = max(nums)

    # LD50
    ld = re.findall(r"(?:ld50|ld 50|lethal dose)\s*(?::|=|of)?\s*(\d+(?:\.\d+)?)", text, re.IGNORECASE)
    if ld:
        values["ld50"] = float(ld[0])

    # DPI
    dpi = re.findall(r"(\d+)\s*dpi", text, re.IGNORECASE)
    if dpi:
        values["dpi"] = [int(x) for x in dpi]

    return values


# ── Main logic ────────────────────────────────────────────────────


def load_virus_name_map(conn: sqlite3.Connection) -> dict[str, int]:
    """Build case-insensitive name -> master_id map."""
    name_map: dict[str, int] = {}

    for row in conn.execute(
        "SELECT master_id, canonical_name, abbreviations FROM virus_master "
        "WHERE coalesce(is_crustacean_virus, 1) = 1 "
        "AND coalesce(entry_type, '') NOT IN ('host_genome', 'non_target')"
    ):
        names = [row["canonical_name"]]
        if row["abbreviations"]:
            names.extend(x.strip() for x in str(row["abbreviations"]).split(","))
        for n in names:
            n = clean_space(str(n))
            if len(n) >= 4:
                name_map[n.lower()] = row["master_id"]

    # Also load aliases
    for row in conn.execute(
        "SELECT va.master_id, va.alias FROM virus_aliases va "
        "JOIN virus_master vm ON vm.master_id = va.master_id "
        "WHERE coalesce(vm.is_crustacean_virus, 1) = 1 "
        "AND coalesce(vm.entry_type, '') NOT IN ('host_genome', 'non_target')"
    ):
        n = clean_space(str(row["alias"]))
        if len(n) >= 4:
            name_map[n.lower()] = row["master_id"]

    return name_map


def load_host_name_map(conn: sqlite3.Connection) -> dict[str, int]:
    """Build case-insensitive name -> host_id map."""
    name_map: dict[str, int] = {}

    for row in conn.execute(
        "SELECT host_id, scientific_name, common_name_cn FROM crustacean_hosts "
        "WHERE coalesce(host_scope_status, '') NOT IN "
        "('excluded_environmental', 'excluded_technical', 'non_target')"
    ):
        names = [str(row["scientific_name"] or ""), str(row["common_name_cn"] or "")]
        for n in names:
            n = clean_space(n)
            if len(n) >= 4:
                name_map[n.lower()] = row["host_id"]

    # Common_terms
    common_hosts = [
        "Penaeus", "Litopenaeus", "Fenneropenaeus", "Marsupenaeus",
        "Macrobrachium", "Procambarus", "Cherax", "Eriocheir",
        "Scylla", "Portunus", "Callinectes", "Crassostrea", "Ostrea",
        "Haliotis", "Mytilus", "Chlamys", "Argopecten", "Ruditapes",
        "Scapharca", "shrimp", "prawn", "crab", "crayfish", "oyster",
        "abalone", "mussel", "scallop", "clam", "lobster", "krill",
        "copepod", "barnacle", "water flea", "daphnia", "artemia",
    ]
    for h in common_hosts:
        name_map[h.lower()] = -1  # placeholder ID

    return name_map


def find_viruses_in_text(text: str, name_map: dict[str, int]) -> list[int]:
    """Find virus master_ids referenced in text."""
    lower = text.lower()
    found: dict[int, str] = {}
    for name_lower, mid in sorted(name_map.items(), key=lambda x: len(x[0]), reverse=True):
        if re.search(rf"(?<![A-Za-z0-9]){re.escape(name_lower)}(?![A-Za-z0-9])", lower):
            if mid not in found:
                found[mid] = name_lower
    return list(found.keys())


def find_hosts_in_text(text: str, name_map: dict[str, int]) -> list[int]:
    """Find host_ids referenced in text."""
    lower = text.lower()
    found: dict[int, str] = {}
    for name_lower, hid in sorted(name_map.items(), key=lambda x: len(x[0]), reverse=True):
        if hid == -1:
            continue  # skip common terms for exact host matching
        if re.search(rf"(?<![A-Za-z0-9]){re.escape(name_lower)}(?![A-Za-z0-9])", lower):
            if hid not in found:
                found[hid] = name_lower
    return list(found.keys())


def observation_type_for(text: str) -> str:
    """Determine lab vs field observation."""
    lower = text.lower()
    lab_terms = ["challenge", "experimental infection", "injected", "inoculated",
                 "immersion", "oral", "intramuscular", "injection",
                 "laboratory", "experiment", "in vitro", "in vivo"]
    field_terms = ["field", "natural infection", "naturally infected", "farm",
                   "pond", "outbreak", "survey", "collected from"]
    lab = sum(1 for t in lab_terms if t in lower)
    field = sum(1 for t in field_terms if t in lower)
    if lab > field:
        return "lab"
    if field > lab:
        return "field"
    return "lab"  # default


def generate_claim(sentence: str, evidence_type: str, matched_terms: list[str],
                   virus_names: list[str], host_names: list[str]) -> str:
    """Generate a concise claim text for the evidence record."""
    prefix = {
        "diagnosis": "Diagnostic detection via",
        "pathogenicity": "Pathogenicity observed:",
        "mortality": "Mortality reported:",
    }.get(evidence_type, f"{evidence_type.capitalize()} evidence:")
    terms_str = ", ".join(sorted(set(matched_terms)))
    virus_str = f" in {', '.join(virus_names[:3])}" if virus_names else ""
    host_str = f" ({', '.join(host_names[:2])})" if host_names else ""
    claim = f"{prefix} {terms_str}{virus_str}{host_str}. [{sentence[:300]}]"
    return claim[:500]


def evidence_strength_for(section_type: str, sentence: str) -> str:
    """Determine evidence strength: medium or low."""
    # From fulltext sections, default to medium
    section_type = (section_type or "").lower()
    if section_type in {"results", "methods", "materials"}:
        return "medium"
    if section_type in {"discussion", "body", "background", "introduction"}:
        return "medium"
    return "medium"  # conservative but fulltext


def main():
    parser = argparse.ArgumentParser(
        description="Expand evidence depth from fulltext sections"
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview changes without writing")
    parser.add_argument("--db", type=str, default=str(DB_PATH),
                        help="Path to database file")
    parser.add_argument("--limit", type=int, default=None,
                        help="Optional section limit for testing")
    parser.add_argument("--no-backup", action="store_true",
                        help="Skip backup on real run")
    args = parser.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"ERROR: Database not found: {db_path}")
        sys.exit(1)

    conn = connect(db_path)

    # ── Backup ────────────────────────────────────────────────────
    if not args.dry_run and not args.no_backup:
        backup(db_path, "pre_expand_evidence_depth")

    try:
        # ── Load name maps ────────────────────────────────────────
        print("Loading virus/host name maps...")
        virus_name_map = load_virus_name_map(conn)
        host_name_map = load_host_name_map(conn)
        print(f"  Virus names: {len(virus_name_map):,}")
        print(f"  Host names: {len(host_name_map):,}")

        # ── Load fulltext sections ────────────────────────────────
        print("\nLoading fulltext sections...")
        sql = """
            SELECT lfs.section_id, lfs.fulltext_id, lfs.reference_id,
                   lfs.section_type, lfs.section_title, lfs.text,
                   lfsr.pmid, lfsr.doi, lfsr.title AS ref_title
            FROM literature_fulltext_sections lfs
            LEFT JOIN ref_literatures lfsr ON lfsr.reference_id = lfs.reference_id
            WHERE lfs.text IS NOT NULL AND length(trim(lfs.text)) > 80
            ORDER BY lfs.reference_id, lfs.section_id
        """
        if args.limit:
            sql = f"""
                SELECT lfs.section_id, lfs.fulltext_id, lfs.reference_id,
                       lfs.section_type, lfs.section_title, lfs.text,
                       lfsr.pmid, lfsr.doi, lfsr.title AS ref_title
                FROM literature_fulltext_sections lfs
                LEFT JOIN ref_literatures lfsr ON lfsr.reference_id = lfs.reference_id
                WHERE lfs.text IS NOT NULL AND length(trim(lfs.text)) > 80
                ORDER BY lfs.reference_id, lfs.section_id
                LIMIT ?
            """
        sections = conn.execute(sql, (args.limit,) if args.limit else ()).fetchall()
        print(f"  Loaded {len(sections):,} sections")

        # ── Load existing evidence claims to avoid duplicates ────
        print("\nLoading existing evidence claims for dedup...")
        existing_claims = set()
        for row in conn.execute(
            "SELECT evidence_id, claim FROM evidence_records WHERE claim IS NOT NULL"
        ):
            existing_claims.add(sha256_text(clean_space(str(row["claim"] or ""))))
        print(f"  Existing evidence claims: {len(existing_claims):,}")

        # ── Pre-compute which viruses have which refs ────────────
        print("\nBuilding reference-to-virus mapping...")
        ref_virus_map: dict[int, set[int]] = defaultdict(set)
        for row in conn.execute(
            """SELECT DISTINCT er.reference_id, er.virus_master_id
               FROM evidence_records er
               WHERE er.reference_id IS NOT NULL AND er.virus_master_id IS NOT NULL
               UNION
               SELECT DISTINCT ir.reference_id, vm.master_id
               FROM infection_records ir
               JOIN viral_isolates vi ON vi.isolate_id = ir.isolate_id
               JOIN virus_master vm ON vm.master_id = vi.master_id
               WHERE ir.reference_id IS NOT NULL"""
        ):
            ref_virus_map[row["reference_id"]].add(row["virus_master_id"])
        print(f"  References with virus links: {len(ref_virus_map):,}")

        # ── Compile detection patterns ───────────────────────────
        diag_patterns = DIAGNOSTIC_TERMS
        path_patterns = PATHOGENICITY_TERMS

        # ── Process sections ──────────────────────────────────────
        print("\nProcessing sections for evidence extraction...")
        new_evidence: list[dict[str, Any]] = []
        seen_claim_hashes: set[str] = set()
        section_counts: Counter[str] = Counter()
        type_counts: Counter[str] = Counter()
        refs_covered: set[int] = set()

        for section in sections:
            section_type = section["section_type"] or ""
            section_title = section["section_title"] or ""
            if not section_allowed(section_type, section_title):
                continue

            text = clean_space(section["text"])
            if len(text) < 80:
                continue

            ref_id = section["reference_id"]
            linked_viruses = ref_virus_map.get(ref_id, set())
            mention_viruses = find_viruses_in_text(text, virus_name_map)
            mention_hosts = find_hosts_in_text(text, host_name_map)

            # Combine: prefer linked viruses, else fallback to mentioned
            candidate_viruses = linked_viruses or mention_viruses

            if not candidate_viruses:
                continue  # skip sections with no virus association

            # Split into sentences
            sentences = split_sentences(text)
            for sentence in sentences:
                if len(sentence) < 60:
                    continue

                # Check for diagnostic terms
                diag_matched = match_patterns(sentence, diag_patterns)
                # Check for pathogenicity terms
                path_matched = match_patterns(sentence, path_patterns)

                if not diag_matched and not path_matched:
                    continue

                # Generate evidence records per virus per type
                evidence_types: list[str] = []
                if diag_matched:
                    evidence_types.append("diagnosis")
                if path_matched:
                    evidence_types.append("pathogenicity")
                    # If the sentence also has mortality numbers, add mortality subtype
                    mortality_vals = extract_mortality_values(sentence)
                    if mortality_vals:
                        evidence_types.append("mortality")

                for vid in candidate_viruses:
                    for etype in evidence_types:
                        # Build claim text
                        matched_terms = []
                        if etype in ("diagnosis",):
                            matched_terms = diag_matched
                        elif etype in ("pathogenicity", "mortality"):
                            matched_terms = path_matched

                        # Simplify matched terms for display
                        display_terms = []
                        for t in matched_terms:
                            # Extract readable term from regex
                            readable = t.replace(r"\b", "").replace(r"\b", "")
                            readable = readable.strip()
                            if readable not in display_terms:
                                display_terms.append(readable)

                        virus_names_for_claim = [
                            name_lower for name_lower, mid in virus_name_map.items()
                            if mid == vid
                        ][:1] if vid in set(virus_name_map.values()) else []

                        claim = generate_claim(sentence, etype, display_terms,
                                               [], [])
                        claim_hash = sha256_text(clean_space(claim))

                        # Dedup: check existing + newly generated
                        if claim_hash in existing_claims or claim_hash in seen_claim_hashes:
                            continue
                        seen_claim_hashes.add(claim_hash)

                        obs_type = observation_type_for(sentence)
                        strength = evidence_strength_for(section_type, sentence)

                        new_evidence.append({
                            "virus_master_id": vid,
                            "reference_id": ref_id,
                            "fulltext_section_id": section["section_id"],
                            "evidence_type": etype,
                            "evidence_strength": strength,
                            "claim": claim,
                            "claim_hash": claim_hash,
                            "extraction_method": "fulltext_deep_extraction",
                            "observation_type": obs_type,
                            "source_detail": f"section_id={section['section_id']}",
                            "matched_diagnostic_terms": "|".join(diag_matched),
                            "matched_pathogenicity_terms": "|".join(path_matched),
                            "host_ids": "|".join(str(h) for h in mention_hosts),
                            "extracted_values": json.dumps(
                                extract_mortality_values(sentence),
                                ensure_ascii=False,
                            ),
                            "section_sentence": sentence[:500],
                        })
                        type_counts[etype] += 1

                refs_covered.add(ref_id)
                section_counts[section_type or "unknown"] += 1

        # ── Report ────────────────────────────────────────────────
        print(f"\n{'='*60}")
        print(f"EXPAND EVIDENCE DEPTH{' (DRY-RUN)' if args.dry_run else ''}")
        print(f"{'='*60}")
        print(f"\nSections processed: {len(sections):,}")
        print(f"Sentences matched: {len(new_evidence):,}")
        print(f"References covered: {len(refs_covered):,}")
        print(f"Unique viruses touched: {len(set(e['virus_master_id'] for e in new_evidence)):,}")

        print("\nNew evidence by type:")
        for etype, cnt in type_counts.most_common():
            print(f"  {etype}: {cnt:,}")

        print("\nNew evidence by section type:")
        for stype, cnt in section_counts.most_common():
            print(f"  {stype}: {cnt:,}")

        # Sample some evidence
        if new_evidence:
            print(f"\nSample evidence (first 5):")
            for e in new_evidence[:5]:
                print(f"  [{e['evidence_type']}] vm_id={e['virus_master_id']} "
                      f"ref_id={e['reference_id']} "
                      f"strength={e['evidence_strength']} "
                      f"obs={e['observation_type']}")
                print(f"    Claim: {e['claim'][:150]}...")

        # ── Write to database ─────────────────────────────────────
        if not args.dry_run and new_evidence:
            conn.execute("BEGIN IMMEDIATE")
            try:
                inserted = 0
                for ev in new_evidence:
                    try:
                        conn.execute(
                            """INSERT INTO evidence_records
                               (virus_master_id, reference_id, fulltext_section_id,
                                evidence_type, evidence_strength, claim,
                                claim_hash, extraction_method, observation_type,
                                source_detail, created_at)
                               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                            (
                                ev["virus_master_id"],
                                ev["reference_id"],
                                ev["fulltext_section_id"],
                                ev["evidence_type"],
                                ev["evidence_strength"],
                                ev["claim"],
                                ev["claim_hash"],
                                ev["extraction_method"],
                                ev["observation_type"],
                                ev["source_detail"],
                                datetime.now().isoformat(timespec="seconds"),
                            ),
                        )
                        inserted += 1
                    except sqlite3.IntegrityError:
                        pass  # duplicate on constraint
                    except sqlite3.InterfaceError as e:
                        print(f"  WARN: InterfaceError on insert: {e}")
                        continue
                conn.commit()
                print(f"\nInserted {inserted:,} new evidence records")
            except BaseException:
                conn.rollback()
                raise

        # ── Summary & report ──────────────────────────────────────
        total_new = len(new_evidence)
        summary = {
            "script": "expand_evidence_depth.py",
            "timestamp": stamp(),
            "dry_run": args.dry_run,
            "sections_loaded": len(sections),
            "sentences_matched": total_new,
            "references_covered": len(refs_covered),
            "new_by_type": dict(type_counts.most_common()),
            "new_by_section_type": dict(section_counts.most_common()),
            "viruses_affected": len(set(e["virus_master_id"] for e in new_evidence)),
        }
        if not args.dry_run:
            summary["inserted"] = inserted
            summary["integrity"] = conn.execute("PRAGMA integrity_check").fetchone()[0]
            fk = conn.execute("PRAGMA foreign_key_check").fetchall()
            summary["fk_violations"] = len(fk)

        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        report_path = REPORTS_DIR / f"expand_evidence_depth_{stamp()}.json"
        report_path.write_text(
            json.dumps(summary, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        print(f"\n[report] -> {report_path}")
        print(json.dumps(summary, indent=2, ensure_ascii=False))

    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()

    print("\nDone.")


if __name__ == "__main__":
    main()
