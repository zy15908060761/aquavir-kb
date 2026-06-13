#!/usr/bin/env python3
"""
P1: Extract evidence from downloaded-but-unparsed fulltexts.
Searches multiple directories (old + new project paths) for files.
Supports XML (PMC/EPMC) and PDF (via PyMuPDF).
"""
import json, re, sqlite3, time
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

import fitz  # PyMuPDF

# Paths
DB_PATH = Path(r"F:\水生无脊椎动物数据库\crustacean_virus_core.db")
PROJECT_DIR = Path(r"F:\水生无脊椎动物数据库")
OLD_PROJECT_DIR = Path(r"F:\甲壳动物数据库")

# Where to search for fulltext files
SEARCH_DIRS = [
    PROJECT_DIR / "literature_curation_v2" / "pmc_xml",
    PROJECT_DIR / "literature_curation_v2" / "fulltext",
    PROJECT_DIR / "literature_curation_v2" / "oa_fulltext",
    OLD_PROJECT_DIR / "literature_curation_v2" / "pmc_xml",
    OLD_PROJECT_DIR / "literature_curation_v2" / "fulltext",
    OLD_PROJECT_DIR / "literature_curation_v2" / "oa_fulltext",
    PROJECT_DIR,  # root for DOI_*_EPMC.xml
    OLD_PROJECT_DIR,  # root for DOI_*_EPMC.xml
]

LOG_DIR = PROJECT_DIR / "downloads" / "fulltext_extraction"
CHECKPOINT_PATH = LOG_DIR / "extraction_p1_checkpoint.json"
LOG_DIR.mkdir(parents=True, exist_ok=True)

# Evidence signal keywords
DIAG_SIGNALS = [
    "PCR", "qPCR", "RT-PCR", "RT-qPCR", "LAMP", "ELISA", "immunoassay",
    "in situ hybridization", "ISH", "western blot", "immunohistochemistry",
    "metagenomic", "next-generation sequencing", "NGS", "diagnostic",
    "TaqMan", "SYBR Green", "RPA", "recombinase polymerase",
]

PATHOGEN_SIGNALS = [
    "mortality", "cumulative mortality", "lethal", "LD50",
    "challenge", "experimental infection", "pathogenicity", "virulence",
    "tissue tropism", "histopathology", "disease signs", "symptom",
    "survival rate", "death rate",
]

TEMPERATURE_SIGNALS = [
    "temperature", "thermal", "water temperature",
    "heat shock", "degree", "°C", "℃",
]

HOST_SIGNALS = [
    "host range", "infected", "infection", "natural infection",
    "experimental infection", "susceptible", "carrier", "reservoir",
    "transmission", "host",
    "Penaeus", "Litopenaeus", "Macrobrachium", "Scylla", "Cherax",
    "Procambarus", "Eriocheir", "Portunus", "Callinectes",
    "Crassostrea", "Haliotis", "Chlamys", "Scapharca", "Mytilus",
    "Ostrea", "Pinctada", "Ruditapes", "Cerastoderma",
]

VIRUS_DICT = {}
HOST_DICT = {}


def load_lookup_tables(con):
    global VIRUS_DICT, HOST_DICT
    VIRUS_DICT.clear()
    HOST_DICT.clear()

    for row in con.execute("SELECT master_id, canonical_name, abbreviations FROM virus_master"):
        names = [str(row[1] or "")]
        if row[2]:
            names.extend([a.strip() for a in str(row[2]).split(",")])
        for n in names:
            if n and len(n) >= 8:
                VIRUS_DICT[n.lower()] = row[0]

    cur2 = con.cursor()
    for row in cur2.execute("SELECT host_id, scientific_name, common_name_cn FROM crustacean_hosts"):
        if row[1]:
            HOST_DICT[str(row[1]).lower()] = row[0]
        if row[2]:
            HOST_DICT[str(row[2]).lower()] = row[0]

    print(f"  Loaded {len(VIRUS_DICT)} virus names, {len(HOST_DICT)} host names")


def extract_text_from_xml(filepath):
    import xml.etree.ElementTree as ET
    try:
        with open(filepath, 'r', encoding='utf-8-sig', errors='ignore') as f:
            content = f.read()
        if 'does not allow downloading of the full text' in content:
            return ""
        root = ET.fromstring(content)
        texts = []
        for el in root.iter():
            tag = el.tag.split('}')[-1] if '}' in el.tag else el.tag
            if tag == 'article-title':
                t = ''.join(el.itertext()).strip()
                if t:
                    texts.append(t)
            elif tag in ('abstract',) or tag.endswith('}abstract'):
                t = ''.join(el.itertext()).strip()
                if t and len(t) > 20:
                    texts.append(t)
            elif tag in ('p',) or tag.endswith('}p'):
                t = ''.join(el.itertext()).strip()
                if len(t) > 80:
                    texts.append(t)
            elif tag in ('title', 'sec-title', 'caption') or tag.endswith('}title'):
                t = ''.join(el.itertext()).strip()
                if t and len(t) > 10:
                    texts.append(t)
        return ' '.join(texts)
    except Exception:
        return ""


def extract_text_from_pdf(filepath):
    try:
        doc = fitz.open(str(filepath))
        texts = []
        for page in doc:
            t = page.get_text()
            if t:
                texts.append(t)
        doc.close()
        full = ' '.join(texts)
        return full[:50000]
    except Exception:
        return ""


def find_file_for_ref(ref_id, pmid, doi, local_paths):
    """Search multiple directories for the best file."""
    # 1. Try known local_paths from DB
    for lp in local_paths:
        if lp:
            p = Path(lp)
            if p.exists():
                return p

    # 2. Search all SEARCH_DIRS by PMID and DOI patterns
    search_terms = []
    if pmid:
        search_terms.append(pmid)
    if doi:
        clean = doi.replace("/", "_").replace(".", "_")[:80]
        search_terms.append(clean)

    for sdir in SEARCH_DIRS:
        if not sdir.exists():
            continue
        for st in search_terms:
            # Direct pattern match
            for pat in [f"*{st}*", f"*PMC*{st}*", f"DOI_{st}_*"]:
                for f in sdir.glob(pat):
                    if f.is_file():
                        return f

    # 3. Fallback: search by ref_id
    for sdir in SEARCH_DIRS:
        if not sdir.exists():
            continue
        for f in sdir.iterdir():
            if f.is_file() and str(ref_id) in f.name:
                return f

    return None


def find_viruses_in_text(text):
    text_lower = text.lower()
    found = set()
    for vname, master_id in VIRUS_DICT.items():
        if len(vname) < 8:
            continue
        if vname in text_lower:
            found.add(master_id)
    return found


def find_signal_matches(text):
    text_lower = text.lower()
    return {
        'diagnostic': [sig for sig in DIAG_SIGNALS if sig.lower() in text_lower],
        'pathogenicity': [sig for sig in PATHOGEN_SIGNALS if sig.lower() in text_lower],
        'temperature': [sig for sig in TEMPERATURE_SIGNALS if sig.lower() in text_lower],
        'host_range': [sig for sig in HOST_SIGNALS if sig.lower() in text_lower],
    }


def load_checkpoint():
    if CHECKPOINT_PATH.exists():
        return set(json.loads(CHECKPOINT_PATH.read_text(encoding="utf-8")))
    return set()


def save_checkpoint(completed_ref_ids):
    CHECKPOINT_PATH.write_text(
        json.dumps(list(completed_ref_ids), ensure_ascii=False), encoding="utf-8")


def main():
    print("=" * 70)
    print("P1: Extracting Evidence from Unparsed Downloaded Fulltexts")
    print("=" * 70)

    con = sqlite3.connect(str(DB_PATH), timeout=60)
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    load_lookup_tables(con)

    # Get refs with downloaded fulltext that have NOT been parsed into sections
    cur.execute("""
        SELECT lfs.reference_id, lfs.pmid, lfs.doi, lfs.local_path,
               rl.title, rl.abstract
        FROM literature_fulltext_sources lfs
        JOIN ref_literatures rl ON lfs.reference_id = rl.reference_id
        WHERE (lfs.status = 'downloaded' OR lfs.status = 'local')
          AND lfs.local_path IS NOT NULL
          AND lfs.local_path != ''
          AND lfs.reference_id NOT IN (
              SELECT DISTINCT reference_id FROM literature_fulltext_sections
          )
        ORDER BY rl.year DESC
    """)
    to_process = cur.fetchall()

    # Group by reference_id to collect all local_paths
    ref_groups = defaultdict(list)
    for row in to_process:
        ref_groups[row["reference_id"]].append(row)

    print(f"Refs with unparsed fulltext: {len(ref_groups)}")

    completed = load_checkpoint()
    remaining = {rid: rows for rid, rows in ref_groups.items() if str(rid) not in completed}
    print(f"After checkpoint filter: {len(remaining)}")

    stats = {
        "processed": 0,
        "xml_parsed": 0,
        "pdf_parsed": 0,
        "no_text_found": 0,
        "no_file_found": 0,
        "new_evidence": 0,
        "viruses_found": Counter(),
        "signals_found": defaultdict(int),
    }

    t0 = time.time()
    for ref_id, rows in remaining.items():
        pmid = rows[0]["pmid"] or ""
        doi = rows[0]["doi"] or ""
        title = rows[0]["title"] or ""
        abstract = rows[0]["abstract"] or ""
        local_paths = [r["local_path"] for r in rows if r["local_path"]]

        file_path = find_file_for_ref(ref_id, pmid, doi, local_paths)

        full_text = ""
        source_type = "unknown"

        if file_path and file_path.exists():
            suffix = file_path.suffix.lower()
            if suffix in ('.xml', '.nxml'):
                full_text = extract_text_from_xml(file_path)
                if full_text:
                    source_type = "xml"
                    stats["xml_parsed"] += 1
            elif suffix == '.pdf':
                full_text = extract_text_from_pdf(file_path)
                if full_text:
                    source_type = "pdf"
                    stats["pdf_parsed"] += 1
            elif suffix in ('.gz', '.tar', '.tgz'):
                pass
        else:
            stats["no_file_found"] += 1

        # Fallback: title + abstract
        if not full_text:
            full_text = (title or "") + " " + (abstract or "")
            if len(full_text.strip()) < 50:
                stats["no_text_found"] += 1
                completed.add(str(ref_id))
                continue
            source_type = "abstract_only"

        # Find viruses mentioned in text
        virus_ids = find_viruses_in_text(full_text)
        if not virus_ids:
            virus_ids = find_viruses_in_text((title or ""))

        if not virus_ids:
            stats["no_text_found"] += 1
            completed.add(str(ref_id))
            continue

        signals = find_signal_matches(full_text)

        for master_id in virus_ids:
            stats["viruses_found"][master_id] += 1

            evidence_types = []
            if signals['host_range']:
                evidence_types.append(("host_range", f"Fulltext: {', '.join(signals['host_range'][:5])}"))
            if signals['diagnostic']:
                evidence_types.append(("diagnosis", f"Fulltext: {', '.join(signals['diagnostic'][:5])}"))
            if signals['pathogenicity']:
                evidence_types.append(("pathogenicity", f"Fulltext: {', '.join(signals['pathogenicity'][:5])}"))
            if signals['temperature']:
                evidence_types.append(("temperature", f"Fulltext: {', '.join(signals['temperature'][:5])}"))

            for etype, claim in evidence_types:
                try:
                    cur.execute("""
                        INSERT OR IGNORE INTO evidence_records
                        (evidence_type, virus_master_id, reference_id, claim,
                         evidence_strength, source_pmid, source_doi,
                         extraction_method, curation_status, observation_type)
                        VALUES (?, ?, ?, ?, 'low', ?, ?, 'fulltext_parsed_p1', 'auto_imported', 'review')
                    """, (etype, master_id, ref_id, claim, pmid, doi))
                    if cur.rowcount > 0:
                        stats["new_evidence"] += 1
                        stats["signals_found"][etype] += 1
                except Exception:
                    pass

            # Store extracted text sections
            try:
                text_preview = full_text[:2000] if len(full_text) > 2000 else full_text
                cur.execute("""
                    INSERT OR IGNORE INTO literature_fulltext_sections
                    (reference_id, section_type, text, char_count)
                    VALUES (?, 'body', ?, ?)
                """, (ref_id, text_preview, len(full_text)))
            except Exception:
                pass

        stats["processed"] += 1
        completed.add(str(ref_id))

        if stats["processed"] % 50 == 0:
            con.commit()
            save_checkpoint(completed)
            elapsed = time.time() - t0
            rate = stats["processed"] / elapsed if elapsed > 0 else 0
            print(f"  [{stats['processed']}/{len(remaining)}] "
                  f"rate={rate:.1f}/s | evid={stats['new_evidence']} | "
                  f"xml={stats['xml_parsed']} pdf={stats['pdf_parsed']} "
                  f"noTxt={stats['no_text_found']} noFile={stats['no_file_found']}")

    con.commit()
    save_checkpoint(completed)

    elapsed = time.time() - t0
    print(f"\n{'=' * 70}")
    print("P1 EXTRACTION COMPLETE")
    print(f"{'=' * 70}")
    print(f"  Time: {elapsed:.1f}s ({elapsed/60:.1f} min)")
    print(f"  Processed: {stats['processed']}")
    print(f"  XML parsed: {stats['xml_parsed']}")
    print(f"  PDF parsed: {stats['pdf_parsed']}")
    print(f"  No text found: {stats['no_text_found']}")
    print(f"  No file found: {stats['no_file_found']}")
    print(f"  New evidence records: {stats['new_evidence']}")

    print(f"\n  Evidence by type:")
    for sig, cnt in sorted(stats["signals_found"].items(), key=lambda x: -x[1]):
        print(f"    {sig}: {cnt}")

    print(f"\n  Top viruses found:")
    for mid, cnt in stats["viruses_found"].most_common(20):
        vname = cur.execute("SELECT canonical_name FROM virus_master WHERE master_id = ?", (mid,)).fetchone()
        name = vname[0] if vname else f"ID={mid}"
        print(f"    {name[:60]}: {cnt}")

    # Coverage update
    total_v = cur.execute("SELECT COUNT(*) FROM virus_master").fetchone()[0]
    with_evidence = cur.execute(
        "SELECT COUNT(DISTINCT virus_master_id) FROM evidence_records WHERE virus_master_id IS NOT NULL"
    ).fetchone()[0]
    print(f"\n  Evidence coverage: {with_evidence}/{total_v} = {with_evidence/total_v*100:.1f}%")

    # Zero-evidence update
    zero = cur.execute("""SELECT COUNT(*) FROM virus_master v
        WHERE v.master_id NOT IN (SELECT DISTINCT virus_master_id FROM evidence_records WHERE virus_master_id IS NOT NULL)
        AND v.host_phylum NOT IN ('non_target (algae)','non_target (vertebrate)','non_target (fungus)','non_target (plant)','non_target','non_aquatic')"""
    ).fetchone()[0]
    print(f"  Zero-evidence target viruses: {zero}")

    con.close()

    # Save log
    log_data = {
        "timestamp": datetime.now().isoformat(),
        "elapsed_s": elapsed,
        **{k: v for k, v in stats.items() if k not in ("viruses_found", "signals_found")},
        "signals_found": dict(stats["signals_found"]),
        "top_viruses": dict(stats["viruses_found"].most_common(100)),
    }
    log_path = LOG_DIR / f"extraction_p1_{int(time.time())}.json"
    log_path.write_text(json.dumps(log_data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n  Log: {log_path}")


if __name__ == "__main__":
    main()
