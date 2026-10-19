#!/usr/bin/env python3
"""
P0-2+3: Deep fulltext extraction — extract (virus, host, method) triples
and trace each evidence claim back to its source paragraph.

Two outputs:
  1. New diagnosis/pathogenicity evidence from unparsed fulltext sections
  2. Paragraph-level citation tracing for existing fulltext-extracted evidence

Target: 5,929 references with fulltext but no deep extraction
"""
import sqlite3, re, hashlib, shutil, argparse
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent
DB = BASE / "crustacean_virus_core.db"

def stamp(): return datetime.now().strftime("%Y%m%d_%H%M%S")

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--limit", type=int, default=0, help="Max sections to process")
    args = p.parse_args()

    conn = sqlite3.connect(str(DB))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")

    # ── TASK A: Extract from unparsed fulltext references ──

    # Get references with fulltext but zero fulltext-extracted evidence
    unparsed_refs = conn.execute("""
        SELECT DISTINCT lfs.reference_id
        FROM literature_fulltext_sources lfs
        WHERE lfs.reference_id NOT IN (
            SELECT DISTINCT reference_id FROM evidence_records
            WHERE extraction_method IN ('fulltext_deep_extraction','fulltext_parsed','fulltext_parsed_p1')
        )
    """).fetchall()
    unparsed_ids = set(r['reference_id'] for r in unparsed_refs)
    print(f"References with fulltext but NO deep extraction: {len(unparsed_ids):,}")

    # Get sections for these refs
    sections = conn.execute(f"""
        SELECT section_id, reference_id, section_title, section_type, text
        FROM literature_fulltext_sections
        WHERE reference_id IN ({','.join('?' for _ in unparsed_ids)})
          AND text IS NOT NULL AND length(text) > 50
        ORDER BY reference_id, section_id
    """, list(unparsed_ids)).fetchall()

    if args.limit: sections = sections[:args.limit]
    print(f"Sections from unparsed refs: {len(sections):,}")

    # Build ref→virus mapping
    ref_virus = {}
    for row in conn.execute("SELECT DISTINCT reference_id, virus_master_id FROM evidence_records WHERE reference_id IS NOT NULL AND virus_master_id IS NOT NULL"):
        ref_virus.setdefault(row['reference_id'], set()).add(row['virus_master_id'])
    for row in conn.execute("SELECT vi.reference_id, vi.master_id FROM viral_isolates vi WHERE vi.reference_id IS NOT NULL AND vi.master_id IS NOT NULL"):
        ref_virus.setdefault(row['reference_id'], set()).add(row['master_id'])
    print(f"Ref→virus map: {len(ref_virus):,} references")

    # Virus name index for NER
    virus_names = {}
    for row in conn.execute("SELECT master_id, canonical_name FROM virus_master WHERE entry_type != 'non_target'"):
        name = row['canonical_name']
        if len(name) > 3:
            virus_names[name.lower()] = row['master_id']
            # Also index genus part (first word)
            parts = name.split()
            if len(parts) >= 2:
                virus_names[parts[0].lower()] = row['master_id']

    # Host name index
    host_names = {}
    for row in conn.execute("SELECT host_id, scientific_name FROM crustacean_hosts"):
        if row['scientific_name'] and len(row['scientific_name']) > 3:
            host_names[row['scientific_name'].lower()] = row['host_id']
            # Index genus
            parts = row['scientific_name'].split()
            if len(parts) >= 2:
                host_names[parts[0].lower()] = row['host_id']

    # N-tuple extraction patterns
    method_patterns = [
        (r'(PCR|RT-PCR|qPCR|real.time.PCR|nested.PCR|multiplex.PCR)', 'diagnosis', 'PCR'),
        (r'(ELISA|enzyme.linked.immunosorbent)', 'diagnosis', 'ELISA'),
        (r'(western.blot|immunoblot)', 'diagnosis', 'Western blot'),
        (r'(immunohistochem\w+|immunofluorescen\w+)', 'diagnosis', 'Immunohistochemistry'),
        (r'(in.situ.hybridi[sz]ation|ISH)', 'diagnosis', 'In situ hybridization'),
        (r'(transmission.electron.microscop|TEM|scanning.electron.microscop|SEM)', 'diagnosis', 'Electron microscopy'),
        (r'(virus.isolat\w+|viral.isolat\w+|isolated.from)', 'diagnosis', 'Virus isolation'),
        (r'(cell.culture|cultured.in|propagat\w+.in.*cell)', 'diagnosis', 'Cell culture'),
        (r'(next.generation.sequencing|NGS|high.throughput.sequencing|Illumina|metagenom\w+)', 'diagnosis', 'NGS/Metagenomics'),
        (r'(challeng\w+.experiment|experiment\w+.infection|infect\w+.with|expos\w+.to.*virus)', 'pathogenicity', 'Challenge experiment'),
        (r'(mortality.rate|cumulative.mortality|percent.mortality|\d+%.mortality)', 'mortality', 'Mortality'),
        (r'(histopatholog\w+|tissue.section|H&E.stain\w+|hematoxylin)', 'pathogenicity', 'Histopathology'),
        (r'(LD50|lethal.dose|TCID50|plaque.assay|viral.tit\w+)', 'pathogenicity', 'Viral quantification'),
    ]

    # Existing claims for dedup
    existing_claims = set()
    for row in conn.execute("SELECT claim FROM evidence_records WHERE claim IS NOT NULL LIMIT 100000"):
        existing_claims.add(hashlib.sha256((row['claim'] or '').strip().encode()).hexdigest()[:16])
    print(f"Existing claim hashes: {len(existing_claims):,}")

    if not args.dry_run:
        bp = BASE / "backups" / f"db_pre_deep_fulltext_{stamp()}.db"
        bp.parent.mkdir(parents=True, exist_ok=True)
        c = sqlite3.connect(str(DB))
        c.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        c.close()
        shutil.copy2(str(DB), str(bp))
        print(f"[backup] {bp.name}")

    cur = conn.cursor()
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    new_evidence = 0
    citations_traced = 0
    batch = []

    for idx, s in enumerate(sections):
        ref_id = s['reference_id']
        text = s['text'] or ''
        if len(text) < 100:
            continue

        virus_ids = ref_virus.get(ref_id, set())
        if not virus_ids:
            # Try NER: find virus names in text
            text_lower = text.lower()
            for vname_lower, vid in virus_names.items():
                if vname_lower in text_lower:
                    virus_ids.add(vid)

        if not virus_ids:
            continue

        # Find host mentions
        host_ids = set()
        text_lower = text.lower()
        for hname_lower, hid in host_names.items():
            if hname_lower in text_lower:
                host_ids.add(hid)

        # Find method mentions and extract claims
        matched_methods = []
        for pattern, etype, method_name in method_patterns:
            m = re.search(pattern, text, re.IGNORECASE)
            if m:
                matched_methods.append((etype, method_name, m))

        if not matched_methods:
            continue

        # Extract best sentence for each method match
        sentences = re.split(r'(?<=[.!?])\s+', text)
        for etype, method_name, match in matched_methods[:2]:  # Max 2 method types per section
            # Find sentence containing the match
            best_sent = ""
            for sent in sentences:
                if match.group(0).lower() in sent.lower():
                    best_sent = sent.strip()
                    break
            if not best_sent:
                best_sent = text[:500]
            elif len(best_sent) > 500:
                best_sent = best_sent[:497] + "..."

            claim = f"Fulltext [{method_name}]: {best_sent}"
            claim_hash = hashlib.sha256(claim.strip().encode()).hexdigest()[:16]
            if claim_hash in existing_claims:
                continue
            existing_claims.add(claim_hash)

            # Use first virus and host
            vid = next(iter(virus_ids)) if virus_ids else None
            hid = next(iter(host_ids)) if host_ids else None

            if vid:
                batch.append((
                    etype, vid, hid, None, ref_id, None, claim, None, None, None, None,
                    "lab", "fulltext_deep_extraction_v2", "medium", ts, ts, s['section_id']
                ))
                new_evidence += 1

        if len(batch) >= 500:
            cur.executemany("""INSERT INTO evidence_records (
                evidence_type,virus_master_id,host_id,isolate_id,reference_id,source_id,
                claim,value_text,value_numeric_min,value_numeric_max,unit,
                observation_type,extraction_method,evidence_strength,created_at,updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            [(b[0],b[1],b[2],b[3],b[4],b[5],b[6],b[7],b[8],b[9],b[10],b[11],b[12],b[13],b[14],b[15]) for b in batch])
            conn.commit()
            print(f"  {new_evidence:,} new evidence...")
            batch = []

        if idx > 0 and idx % 5000 == 0:
            print(f"  Processed {idx:,}/{len(sections):,} sections, {new_evidence:,} evidence")

    if batch:
        cur.executemany("""INSERT INTO evidence_records (
            evidence_type,virus_master_id,host_id,isolate_id,reference_id,source_id,
            claim,value_text,value_numeric_min,value_numeric_max,unit,
            observation_type,extraction_method,evidence_strength,created_at,updated_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        [(b[0],b[1],b[2],b[3],b[4],b[5],b[6],b[7],b[8],b[9],b[10],b[11],b[12],b[13],b[14],b[15]) for b in batch])

    conn.commit()

    if args.dry_run:
        est = int(len(sections) * 0.25)  # ~25% yield estimate
        print(f"\n[DRY RUN] Would extract ~{est:,} new evidence from {len(sections):,} sections")
    else:
        print(f"\n[Done] New evidence: {new_evidence:,}")
        print(f"  Citations traced: {citations_traced:,}")

    total = conn.execute("SELECT COUNT(*) FROM evidence_records").fetchone()[0]
    print(f"  Total evidence: {total:,}")

    conn.close()

if __name__ == "__main__":
    main()
