#!/usr/bin/env python3
"""
Smart re-extraction with improved virus name matching:
1. Token-based matching (not just exact substring)
2. Normalize names (remove -like, virus suffixes, handle numbers)
3. Abbreviation expansion
4. Genus-word matching for compound names
"""

import json, re, sqlite3, time
from pathlib import Path
from collections import defaultdict, Counter
from datetime import datetime
from xml.etree import ElementTree as ET

try:
    import fitz
    HAS_PDF = True
except ImportError:
    HAS_PDF = False

DB_PATH = Path(r"F:\甲壳动物数据库\crustacean_virus_core.db")
PMC_XML_DIR = Path(r"F:\甲壳动物数据库\literature_curation_v2\pmc_xml")
FULLTEXT_DIR = Path(r"F:\甲壳动物数据库\literature_curation_v2\fulltext")
EPMC_XML_DIR = Path(r"F:\甲壳动物数据库")

# Signal patterns
DIAG_RE = re.compile(r'\b(PCR|qPCR|RT[ -]?PCR|LAMP|ELISA|immunoassay|hybridization|western blot|metagenomic|NGS|diagnostic|TaqMan|SYBR|RPA|sequencing|phylogenetic|genome|ORF|RdRp)\b', re.I)
PATH_RE = re.compile(r'\b(mortalit|lethal|virulen|pathogenic|challenge|infection rate|survival rate|death|histopatholog|disease sign|symptom|LD50)\b', re.I)
TEMP_RE = re.compile(r'\b(temperatur|thermal|°C|℃|degree|heat shock)\b', re.I)
HOST_RE = re.compile(r'\b(infected|infection|susceptible|host|transmission|isolated from|detected in|tissue tropism|organ|prevalence)\b', re.I)


def build_search_tokens(name, abbreviations):
    """Build all searchable token variants for a virus name."""
    tokens = set()
    name = (name or '').strip()
    if not name:
        return tokens

    # Full name (original)
    tokens.add(name.lower())

    # Remove parenthetical content
    cleaned = re.sub(r'\([^)]*\)', '', name).strip()
    if cleaned and cleaned != name:
        tokens.add(cleaned.lower())

    # Remove -like suffix variants
    no_like = re.sub(r'-like', '', name).strip()
    if no_like != name:
        tokens.add(no_like.lower())

    # Extract key content words (3+ chars, not stopwords)
    stopwords = {'virus', 'viruses', 'the', 'and', 'from', 'with', 'for', 'its', 'associated'}
    words = re.findall(r'[a-zA-Z0-9]+', name)
    key_words = [w for w in words if w.lower() not in stopwords and len(w) >= 4]

    # 2-word combinations (most discriminating)
    for i in range(len(key_words) - 1):
        bigram = f"{key_words[i]} {key_words[i+1]}".lower()
        if len(bigram) >= 8:
            tokens.add(bigram)

    # Individual significant words (5+ chars, unique enough)
    for w in key_words:
        if len(w) >= 5:
            tokens.add(w.lower())

    # Add abbreviations
    if abbreviations:
        for abbr in abbreviations.split(','):
            abbr = abbr.strip()
            if abbr and len(abbr) >= 3:
                tokens.add(abbr.lower())

    return tokens


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
                if tag in ('p', 'article-title', 'abstract', 'title', 'sec-title', 'caption') or tag.endswith('}p'):
                    t = ''.join(el.itertext()).strip()
                    if len(t) > 30:
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
        except:
            pass

    return text[:80000]


def find_virus_matches(text, virus_tokens_map):
    """Find virus matches using token-based matching.
    Returns dict of master_id -> list of matched tokens."""
    text_lower = text.lower()
    matches = defaultdict(list)

    for master_id, token_list in virus_tokens_map.items():
        for token in token_list:
            if token in text_lower:
                matches[master_id].append(token)

    return dict(matches)


def find_evidence_sentences(text, matched_tokens):
    """Find sentences near matched tokens that contain evidence signals."""
    sentences = re.split(r'(?<=[.!?])\s+', text)
    results = []

    for sent in sentences:
        sent_stripped = sent.strip()
        if len(sent_stripped) < 15:
            continue

        # Check if any matched token is near
        sent_lower = sent_stripped.lower()
        has_token = any(t in sent_lower for t in matched_tokens)
        if not has_token:
            continue

        ev_types = []
        if DIAG_RE.search(sent_stripped):
            ev_types.append('diagnosis')
        if PATH_RE.search(sent_stripped):
            ev_types.append('pathogenicity')
        if TEMP_RE.search(sent_stripped):
            ev_types.append('temperature')
        if HOST_RE.search(sent_stripped):
            ev_types.append('host_range')

        for et in ev_types:
            results.append((et, sent_stripped[:250]))

    return results


def main():
    con = sqlite3.connect(str(DB_PATH), timeout=60)
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    print("Building virus token index...")
    cur.execute("SELECT master_id, canonical_name, abbreviations FROM virus_master")
    virus_rows = cur.fetchall()

    virus_tokens = {}
    virus_names = {}
    for r in virus_rows:
        tokens = build_search_tokens(r['canonical_name'], r['abbreviations'])
        if tokens:
            virus_tokens[r['master_id']] = list(tokens)
            virus_names[r['master_id']] = r['canonical_name']

    print(f"  {len(virus_tokens)} viruses indexed with {sum(len(v) for v in virus_tokens.values())} tokens")

    # Find all PDFs that need re-extraction (downloaded, not yet matched)
    cur.execute("""
        SELECT DISTINCT lfs.reference_id, lfs.local_path, rl.title, rl.year
        FROM literature_fulltext_sources lfs
        JOIN ref_literatures rl ON lfs.reference_id = rl.reference_id
        WHERE lfs.status = 'downloaded'
        AND lfs.local_path IS NOT NULL AND lfs.local_path != ''
    """)
    all_downloaded = cur.fetchall()

    print(f"\nProcessing {len(all_downloaded)} downloaded refs...")

    new_evidence = 0
    refs_matched = 0
    viruses_matched = Counter()
    evidence_by_type = Counter()
    total_viruses_found = set()

    for i, row in enumerate(all_downloaded):
        ref_id = row['reference_id']
        path_str = row['local_path']
        path = Path(path_str)

        if not path.exists():
            continue

        if i % 100 == 0:
            con.commit()
            print(f"  [{i+1}/{len(all_downloaded)}] matched={refs_matched}, "
                  f"viruses={len(total_viruses_found)}, evidence={new_evidence}")

        text = extract_text(path)
        if not text or len(text) < 100:
            continue

        # Find virus matches
        matches = find_virus_matches(text, virus_tokens)
        if not matches:
            continue

        refs_matched += 1

        for master_id, matched_tokens in matches.items():
            total_viruses_found.add(master_id)

            # Check if this virus+ref already has evidence (avoid duplicates)
            cur.execute("""
                SELECT COUNT(*) FROM evidence_records
                WHERE virus_master_id = ? AND reference_id = ?
            """, (master_id, ref_id))
            existing_count = cur.fetchone()[0]
            if existing_count >= 4:
                continue  # Already well-covered

            # Find evidence sentences
            ev_sentences = find_evidence_sentences(text, matched_tokens[:3])

            for ev_type, claim in ev_sentences:
                # Skip if this exact type already exists
                cur.execute("""
                    SELECT COUNT(*) FROM evidence_records
                    WHERE virus_master_id = ? AND reference_id = ? AND evidence_type = ?
                """, (master_id, ref_id, ev_type))
                if cur.fetchone()[0] > 0:
                    continue

                try:
                    cur.execute("""
                        INSERT INTO evidence_records
                        (evidence_type, virus_master_id, reference_id, claim,
                         evidence_strength, extraction_method, curation_status, observation_type)
                        VALUES (?, ?, ?, ?, 'medium', 'smart_match_re_extract', 'auto_imported', 'review')
                    """, (ev_type, master_id, ref_id, claim))
                    new_evidence += cur.rowcount
                    evidence_by_type[ev_type] += 1
                    viruses_matched[master_id] += 1
                except:
                    pass

    con.commit()

    # Store extraction sections for matched refs
    cur.execute("SELECT COUNT(DISTINCT reference_id) FROM literature_fulltext_sections")
    sections_before = cur.fetchone()[0]

    print(f"\n{'=' * 60}")
    print("SMART MATCH RE-EXTRACTION RESULTS")
    print(f"{'=' * 60}")
    print(f"  Files processed: {len(all_downloaded)}")
    print(f"  Refs with >=1 virus match: {refs_matched}")
    print(f"  Viruses matched: {len(total_viruses_found)}")
    print(f"  New evidence: {new_evidence}")

    print(f"\n  Evidence by type:")
    for t, c in evidence_by_type.most_common():
        print(f"    {t}: {c}")

    print(f"\n  Top 20 matched viruses:")
    top = viruses_matched.most_common(20)
    for master_id, cnt in top:
        name = virus_names.get(master_id, f"ID:{master_id}")[:60]
        print(f"    {name}: {cnt}")

    # Coverage update
    cur.execute("SELECT COUNT(DISTINCT virus_master_id) FROM evidence_records WHERE virus_master_id IS NOT NULL")
    cov = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM virus_master")
    tv = cur.fetchone()[0]
    print(f"\n  Coverage: {cov}/{tv} = {cov/tv*100:.1f}%")

    # Count low-evidence improvement
    cur.execute("""
    SELECT COUNT(*) FROM (
        SELECT vm.master_id, COUNT(er.evidence_id) as cnt
        FROM virus_master vm LEFT JOIN evidence_records er ON vm.master_id = er.virus_master_id
        WHERE vm.host_phylum LIKE '%Arthropod%'
        GROUP BY vm.master_id HAVING cnt BETWEEN 1 AND 5
    )
    """)
    low_after = cur.fetchone()[0]
    print(f"  Low-evidence crustaceans: {low_after} (was 228)")

    con.close()

    # Save log
    log_path = Path(r"F:\甲壳动物数据库\downloads\fulltext_extraction") / f"smart_match_{int(time.time())}.json"
    log_path.write_text(json.dumps({
        "timestamp": datetime.now().isoformat(),
        "files_processed": len(all_downloaded),
        "refs_matched": refs_matched,
        "viruses_matched": len(total_viruses_found),
        "new_evidence": new_evidence,
        "by_type": dict(evidence_by_type),
        "top_viruses": dict(top),
        "coverage": f"{cov}/{tv}={cov/tv*100:.1f}%",
        "low_ev_crustaceans": low_after,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  Log: {log_path}")


if __name__ == "__main__":
    main()
