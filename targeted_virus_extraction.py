#!/usr/bin/env python3
"""
Targeted extraction for low-evidence viruses:
For each virus with 1-5 evidence records, find its linked references that are ALREADY downloaded,
search fulltext for that specific virus name, and create new evidence records with better specificity.
"""

import json
import re
import sqlite3
from pathlib import Path
from xml.etree import ElementTree as ET
from collections import defaultdict, Counter
from datetime import datetime

try:
    import fitz
    HAS_PDF = True
except ImportError:
    HAS_PDF = False

DB_PATH = Path(r"F:\甲壳动物数据库\crustacean_virus_core.db")
PMC_XML_DIR = Path(r"F:\甲壳动物数据库\literature_curation_v2\pmc_xml")
FULLTEXT_DIR = Path(r"F:\甲壳动物数据库\literature_curation_v2\fulltext")
EPMC_XML_DIR = Path(r"F:\甲壳动物数据库")
OA_DIR = Path(r"F:\甲壳动物数据库\literature_curation_v2\oa_fulltext")


def get_low_evidence_viruses(cur):
    """Get crustacean viruses with 1-5 evidence."""
    cur.execute("""
        SELECT vm.master_id, vm.canonical_name, vm.abbreviations,
               COUNT(er.evidence_id) as ev_count,
               GROUP_CONCAT(DISTINCT er.reference_id) as ref_ids,
               GROUP_CONCAT(DISTINCT er.evidence_type) as ev_types
        FROM virus_master vm
        LEFT JOIN evidence_records er ON vm.master_id = er.virus_master_id
        WHERE (vm.host_phylum LIKE '%Arthropod%'
               OR vm.discovery_context LIKE '%crustacean%'
               OR vm.discovery_context LIKE '%shrimp%'
               OR vm.discovery_context LIKE '%crab%'
               OR vm.discovery_context LIKE '%cray%'
               OR vm.canonical_name LIKE '%shrimp%'
               OR vm.canonical_name LIKE '%crab%'
               OR vm.canonical_name LIKE '%crayfish%')
        GROUP BY vm.master_id
        HAVING ev_count BETWEEN 1 AND 5
    """)
    rows = cur.fetchall()
    results = []
    for r in rows:
        ref_ids = [int(x) for x in (r['ref_ids'] or '').split(',') if x.strip().isdigit()]
        ev_types = [t.strip() for t in (r['ev_types'] or '').split(',') if t.strip()]
        results.append({
            'master_id': r['master_id'],
            'canonical_name': r['canonical_name'],
            'abbreviations': r['abbreviations'],
            'ev_count': r['ev_count'],
            'ref_ids': ref_ids,
            'ev_types': ev_types,
            'names': get_search_names(r['canonical_name'], r['abbreviations']),
        })
    return results


def get_search_names(canonical_name, abbreviations):
    """Generate search name variants for a virus."""
    names = []
    if canonical_name:
        names.append(canonical_name)
        # Also try without special characters
        clean = re.sub(r'[^a-zA-Z0-9\s]', '', canonical_name)
        if clean != canonical_name:
            names.append(clean)
        # Try first 2 words
        words = canonical_name.split()
        if len(words) >= 2:
            names.append(' '.join(words[:2]))
    if abbreviations:
        for abbr in abbreviations.split(','):
            abbr = abbr.strip()
            if abbr and len(abbr) >= 3:
                names.append(abbr)
    return names


def find_file_for_ref(cur, ref_id):
    """Find downloaded file for a reference."""
    cur.execute("""
        SELECT local_path FROM literature_fulltext_sources
        WHERE reference_id = ? AND status = 'downloaded' AND local_path IS NOT NULL AND local_path != ''
        LIMIT 5
    """, (ref_id,))
    for row in cur.fetchall():
        path = Path(row[0])
        if path.exists():
            return path
    return None


def extract_text(filepath):
    """Extract text from XML or PDF."""
    suffix = filepath.suffix.lower()
    text = ""

    if suffix in ('.xml', '.nxml'):
        try:
            with open(filepath, 'r', encoding='utf-8-sig', errors='ignore') as f:
                content = f.read()
            if 'does not allow downloading of the full text' in content:
                return ""
            root = ET.fromstring(content)
            texts = []
            for el in root.iter():
                tag = el.tag.split('}')[-1] if '}' in el.tag else el.tag
                if tag in ('p', 'article-title', 'abstract') or tag.endswith('}p'):
                    t = ''.join(el.itertext()).strip()
                    if len(t) > 40:
                        texts.append(t)
            text = ' '.join(texts)
        except:
            pass
    elif suffix == '.pdf' and HAS_PDF:
        try:
            doc = fitz.open(str(filepath))
            texts = [page.get_text() for page in doc]
            doc.close()
            text = ' '.join(t for t in texts if t)
            text = text[:50000]
        except:
            pass
    elif suffix in ('.gz', '.tar', '.tgz'):
        pass  # Skip archives for now

    return text


def find_virus_in_text(text, search_names):
    """Search for specific virus name in text and return context."""
    text_lower = text.lower()
    for name in search_names:
        name_lower = name.lower()
        if len(name_lower) < 5:
            continue
        # Find position
        idx = text_lower.find(name_lower)
        if idx >= 0:
            # Extract surrounding context (200 chars around the match)
            start = max(0, idx - 100)
            end = min(len(text), idx + len(name) + 200)
            context = text[start:end].strip()
            return name, context
    return None, None


def find_signal_sentences(context, virus_name):
    """Find sentences with evidence signals near the virus mention."""
    if not context:
        return []

    sentences = re.split(r'[.!?]+', context)
    results = []

    diag_pattern = re.compile(r'(PCR|qPCR|RT-PCR|ELISA|immunoassay|hybridization|western blot|metagenomic|sequencing|diagnostic|detection|TaqMan|LAMP)', re.I)
    path_pattern = re.compile(r'(mortality|lethal|virulence|pathogenic|challenge|infection rate|survival|death|histopatholog)', re.I)
    temp_pattern = re.compile(r'(temperature|thermal|°C|℃|degree|heat)', re.I)
    host_pattern = re.compile(r'(infected|infection|susceptible|host|transmission|isolated from|detected in|found in|tissue|organ)', re.I)

    for sent in sentences:
        sent = sent.strip()
        if len(sent) < 20:
            continue
        if virus_name.lower() not in sent.lower():
            continue

        if diag_pattern.search(sent):
            results.append(('diagnosis', sent[:200]))
        if path_pattern.search(sent):
            results.append(('pathogenicity', sent[:200]))
        if temp_pattern.search(sent):
            results.append(('temperature', sent[:200]))
        if host_pattern.search(sent):
            results.append(('host_range', sent[:200]))

    return results


def main():
    con = sqlite3.connect(str(DB_PATH), timeout=60)
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    print("Loading low-evidence viruses...")
    viruses = get_low_evidence_viruses(cur)
    print(f"  Found {len(viruses)} low-evidence crustacean viruses")

    # Group by ref for efficiency — process each unique file once
    ref_files = {}
    for v in viruses:
        for ref_id in v['ref_ids']:
            if ref_id not in ref_files:
                path = find_file_for_ref(cur, ref_id)
                if path:
                    ref_files[ref_id] = path

    print(f"  {len(ref_files)} refs have downloadable files out of {len(set(r for v in viruses for r in v['ref_ids']))} total")

    # Extract text from each unique file
    ref_texts = {}
    for i, (ref_id, path) in enumerate(ref_files.items()):
        if i % 20 == 0:
            print(f"  Extracting file {i+1}/{len(ref_files)}...")
        text = extract_text(path)
        if text:
            ref_texts[ref_id] = text
            # Also record in literature_fulltext_sections if not already
            try:
                cur.execute("""
                    INSERT OR IGNORE INTO literature_fulltext_sections
                    (reference_id, section_type, text, char_count)
                    VALUES (?, 'targeted_extract', ?, ?)
                """, (ref_id, text[:5000], len(text)))
            except:
                pass

    print(f"  Successfully extracted text from {len(ref_texts)} refs")

    # Now search for each virus in its linked references
    new_evidence = 0
    viruses_improved = 0
    stats = Counter()

    for v in viruses:
        found_any = False
        for ref_id in v['ref_ids']:
            if ref_id not in ref_texts:
                continue

            text = ref_texts[ref_id]
            matched_name, context = find_virus_in_text(text, v['names'])

            if not matched_name:
                continue

            found_any = True
            signals = find_signal_sentences(context, matched_name)

            for ev_type, claim_text in signals:
                # Only add if this virus doesn't already have this type from this ref
                cur.execute("""
                    SELECT COUNT(*) FROM evidence_records
                    WHERE virus_master_id = ? AND reference_id = ? AND evidence_type = ?
                """, (v['master_id'], ref_id, ev_type))
                if cur.fetchone()[0] > 0:
                    continue

                try:
                    cur.execute("""
                        INSERT INTO evidence_records
                        (evidence_type, virus_master_id, reference_id, claim,
                         evidence_strength, extraction_method, curation_status, observation_type)
                        VALUES (?, ?, ?, ?, 'medium', 'targeted_fulltext_extract', 'auto_imported', 'review')
                    """, (ev_type, v['master_id'], ref_id, claim_text))
                    new_evidence += cur.rowcount
                    stats[ev_type] += 1
                except:
                    pass

        if found_any:
            viruses_improved += 1

    con.commit()

    print(f"\n=== Targeted Extraction Results ===")
    print(f"  Viruses analyzed: {len(viruses)}")
    print(f"  Viruses with new evidence: {viruses_improved}")
    print(f"  New evidence records: {new_evidence}")
    print(f"  By type:")
    for t, c in stats.most_common():
        print(f"    {t}: {c}")

    # Updated coverage
    cur.execute("""
        SELECT COUNT(DISTINCT virus_master_id) FROM evidence_records WHERE virus_master_id IS NOT NULL
    """)
    cov = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM virus_master")
    total = cur.fetchone()[0]
    print(f"\n  Coverage: {cov}/{total} = {cov/total*100:.1f}%")

    con.close()

    # Save log
    log_path = Path(r"F:\甲壳动物数据库\downloads\fulltext_extraction") / f"targeted_extraction_{int(datetime.now().timestamp())}.json"
    log_path.write_text(json.dumps({
        "timestamp": datetime.now().isoformat(),
        "viruses_analyzed": len(viruses),
        "viruses_improved": viruses_improved,
        "new_evidence": new_evidence,
        "by_type": dict(stats),
        "coverage": f"{cov}/{total}={cov/total*100:.1f}%",
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  Log: {log_path}")


if __name__ == "__main__":
    main()
