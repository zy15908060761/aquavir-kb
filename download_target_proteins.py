"""
Download missing protein sequences from NCBI for 512 viruses needing ICTV classification.

For each virus in pending_review / unclassified_not_expected that has NO protein
sequences in viral_proteins, we download FASTA from NCBI and insert into the
viral_proteins table so that downstream phylogeny (RdRp) or BLAST (DNA viruses)
can classify them.

Usage: python download_target_proteins.py
"""

from __future__ import annotations

import re
import subprocess
import sys
import time
import textwrap
from pathlib import Path

from db_utils import db_connection, db_transaction

# ── Paths ─────────────────────────────────────────────────────────────────────
PROJECT_DIR = Path(__file__).resolve().parent
BLASTDB_DIR = PROJECT_DIR / "blastdb"
OUTPUT_FASTA = BLASTDB_DIR / "target_new_proteins.faa"

# NCBI efetch
EFETCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
NCBI_KEY = None  # set via env var NCBI_API_KEY for higher rate limits

BATCH_SIZE = 50           # accessions per NCBI request (smaller to avoid URL length issues)
REQUEST_DELAY = 0.4       # seconds between requests
MAX_RETRIES = 3
CURL_TIMEOUT = 120
USER_AGENT = "Mozilla/5.0 AquaVir-KB/3.0"


# ── Step 1: Identify accessions ──────────────────────────────────────────────

def get_target_accessions() -> list[dict]:
    """Return rows of accession, isolate_id, master_id, canonical_name, genome_type
    for isolates belonging to target viruses that have zero proteins."""
    with db_connection(read_only=True) as conn:
        cur = conn.execute("""
            SELECT DISTINCT vi.accession, vi.isolate_id,
                   vm.master_id, vm.canonical_name, vm.genome_type
            FROM virus_ictv_status vs
            JOIN virus_master vm ON vs.master_id = vm.master_id
            JOIN viral_isolates vi ON vm.master_id = vi.master_id
            LEFT JOIN viral_proteins vp ON vi.isolate_id = vp.isolate_id
            WHERE vs.ictv_status IN ('pending_review', 'unclassified_not_expected')
              AND vm.entry_type NOT IN ('non_target', 'host_genome',
                                        'duplicate_alias_placeholder',
                                        'duplicate_ictv_vmr_placeholder')
              AND vp.protein_id IS NULL
              AND vi.accession IS NOT NULL
              AND vi.accession != ''
            ORDER BY vi.accession
        """)
        rows = [dict(r) for r in cur.fetchall()]
    return rows


# ── Step 2: NCBI download ────────────────────────────────────────────────────

def curl_fetch(url: str, timeout: int = CURL_TIMEOUT) -> tuple[int, str | None]:
    """Fetch a URL using curl subprocess (avoids Windows TCP issues with requests).

    Uses --ssl-no-revoke to work around Windows Schannel CRL revocation
    failures when the machine cannot reach CRL/OCSP servers.
    """
    cmd = [
        "curl", "-sL", "--max-time", str(timeout),
        "--ssl-no-revoke",
        "-w", "%{http_code}",
        "-o", "-",
        "-H", f"User-Agent: {USER_AGENT}",
        url,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, timeout=timeout + 15)
        raw = result.stdout
        if len(raw) >= 3:
            code = int(raw[-3:].decode().strip())
            body = raw[:-3]
            return code, body.decode("utf-8") if body else None
        return 0, None
    except subprocess.TimeoutExpired:
        return 0, None
    except Exception:
        return 0, None


def fetch_fasta_batch(accessions: list[str], db: str = "nucleotide") -> dict[str, str] | None:
    """Fetch FASTA for a batch of accessions from NCBI efetch using curl.

    Most accessions in this database are GenBank nucleotide accessions, so
    ``db='nucleotide'`` is the typical database.  Will also try ``db='protein'``
    only when the URL returns a clear error and the accessions look protein-like
    (e.g., start with NP_, YP_, XP_, WP_).

    Returns dict mapping base accession -> raw FASTA text (single or multi-FASTA).
    Returns None on total failure (after retries). Returns {} if valid response but empty.
    """
    ids = ",".join(accessions)
    url = (f"{EFETCH_URL}?db={db}&id={ids}&rettype=fasta&retmode=text")
    if NCBI_KEY:
        url += f"&api_key={NCBI_KEY}"

    for attempt in range(1, MAX_RETRIES + 1):
        code, body = curl_fetch(url)

        if code == 0 or body is None:
            print(f"    [Retry {attempt}/{MAX_RETRIES}] Curl failed (code={code}) for batch of {len(accessions)}")
            time.sleep(2 ** attempt)
            continue

        if code != 200:
            print(f"    [Retry {attempt}/{MAX_RETRIES}] HTTP {code} for batch of {len(accessions)}")
            time.sleep(2 ** attempt)
            continue

        if not body.strip() or body.startswith("ERROR") or "error occurred" in body.lower():
            print(f"    [Retry {attempt}/{MAX_RETRIES}] Empty/error response from {db}")
            time.sleep(2 ** attempt)
            continue

        # Parse multi-FASTA
        sequences: dict[str, str] = {}
        current_acc: str | None = None
        current_lines: list[str] = []

        for line in body.splitlines():
            line = line.rstrip("\n\r")
            if line.startswith(">"):
                if current_acc and current_lines:
                    sequences[current_acc] = "\n".join(current_lines)
                # Extract base accession from header
                raw_acc = line[1:].split()[0]
                current_acc = raw_acc.split(".")[0]
                current_lines = [line]
            else:
                if current_acc is not None:
                    current_lines.append(line)

        if current_acc and current_lines:
            sequences[current_acc] = "\n".join(current_lines)

        if sequences:
            return sequences

        # Valid response but no sequences parsed
        return {}

    return None  # All retries exhausted


def _looks_like_protein_accession(acc: str) -> bool:
    """Heuristic: protein accessions often start with NP_, YP_, XP_, WP_, etc."""
    base = acc.split(".")[0]
    return bool(re.match(r'^[NXWY][NP]_', base))


def fetch_protein_or_nucleotide(accessions: list[str]) -> dict[str, str]:
    """Fetch FASTA, trying the most likely database first.

    Most accessions in this project are nucleotide GenBank accessions
    (e.g., AB287465.1).  We check the first accession to decide which db
    to try first, rather than wasting 3 retries on 400 errors.
    """
    # Heuristic: if ANY accession in the batch looks like a protein accession
    # (NP_, YP_, XP_, WP_), try protein first; otherwise go straight to nucleotide
    has_protein_like = any(_looks_like_protein_accession(a) for a in accessions)

    if has_protein_like:
        result = fetch_fasta_batch(accessions, db="protein")
        if result:
            # Mark for tracking
            for acc in list(result.keys()):
                if ">" in result[acc][:50]:
                    result[acc] = result[acc].replace(">", "> [protein_db] ", 1)
            return result
        # Fall through to nucleotide
        print(f"    Protein DB failed, trying nucleotide DB...")
        result = fetch_fasta_batch(accessions, db="nucleotide")
        if result:
            for acc in list(result.keys()):
                if ">" in result[acc][:50]:
                    result[acc] = result[acc].replace(">", "> [nucleotide_db] ", 1)
        return result if result else {}

    # Go straight to nucleotide — saves 3+ seconds per batch
    result = fetch_fasta_batch(accessions, db="nucleotide")
    if result:
        for acc in list(result.keys()):
            if ">" in result[acc][:50]:
                result[acc] = result[acc].replace(">", "> [nucleotide_db] ", 1)
        return result

    # Try protein as last resort
    print(f"    Nucleotide DB failed, trying protein DB...")
    alt = fetch_fasta_batch(accessions, db="protein")
    if alt:
        for acc in list(alt.keys()):
            if ">" in alt[acc][:50]:
                alt[acc] = alt[acc].replace(">", "> [protein_db] ", 1)
    return alt if alt else {}

# ── Step 3: Database insertion ──────────────────────────────────────────────

def parse_fasta(fasta_text: str) -> list[dict]:
    """Parse a FASTA string into list of {header, accession, description, sequence}.

    Handles our tagged headers like ``> [nucleotide_db] ACCESSION.DESC``
    by stripping the ``[tag]`` prefix before extracting the accession.
    """
    records = []
    current = None

    for line in fasta_text.splitlines():
        line = line.rstrip("\n\r")
        if line.startswith(">"):
            if current and current["sequence"]:
                records.append(current)
            # Strip leading tag like [nucleotide_db] or [protein_db]
            header = line[1:].lstrip()  # strip > and any leading space
            tag_match = re.match(r'^\[([^\]]+)\]\s+', header)
            if tag_match:
                header = header[tag_match.end():]
            parts = header.split(None, 1)
            raw_acc = parts[0] if parts else "unknown"
            desc = parts[1] if len(parts) > 1 else ""
            current = {
                "header": line,
                "accession": raw_acc.split(".")[0],  # base accession
                "full_accession": raw_acc,
                "description": desc[:500],
                "sequence": "",
            }
        else:
            if current is not None:
                current["sequence"] += line.strip().replace(" ", "")

    if current and current["sequence"]:
        records.append(current)

    return records


def translate_sequence(seq: str) -> str | None:
    """Translate a nucleotide sequence to protein in all 6 frames,
    return the longest ORF that starts with M and is at least 30 AA.

    Uses Bio.SeqIO for the translation logic.
    """
    try:
        from Bio.Seq import Seq
    except ImportError:
        print("    [WARN] BioPython not available, storing nucleotide as-is")
        return None

    seq = seq.upper().replace("U", "T")
    seq_obj = Seq(seq)

    longest_orf = ""
    # Forward frames 0,1,2 and reverse frames 0,1,2
    for strand in [1, -1]:
        for frame in range(3):
            if strand == 1:
                coding = seq_obj[frame:]
            else:
                coding = seq_obj.reverse_complement()[frame:]

            # Make length a multiple of 3
            trim = len(coding) % 3
            if trim:
                coding = coding[:-trim]

            if len(coding) < 30:
                continue

            try:
                prot = coding.translate(to_stop=False)
                prot_str = str(prot)

                # Find longest ORF starting with M
                for match in re.finditer(r"M[^*]*", prot_str):
                    orf = match.group()
                    if len(orf) > len(longest_orf) and len(orf) >= 30:
                        longest_orf = orf
            except Exception:
                continue

    return longest_orf if len(longest_orf) >= 30 else None


def insert_protein(conn, isolate_id: int, fasta_rec: dict, is_nucleotide: bool) -> bool:
    """Insert a parsed FASTA record into viral_proteins.

    Returns True if inserted, False if skipped (duplicate or error).
    """
    seq = fasta_rec["sequence"]
    if not seq:
        return False

    protein_accession = fasta_rec["full_accession"]
    protein_name = fasta_rec["description"]
    aa_length: int | None = None
    translation: str | None = None
    note = None

    if is_nucleotide:
        note = "nucleotide_derived"
        translated = translate_sequence(seq)
        if translated:
            translation = translated
            aa_length = len(translated)
        else:
            # Store nucleotide sequence as translation with note
            translation = seq
            aa_length = len(seq)
            note = "nucleotide_sequence_no_orf"
    else:
        # Already protein
        translation = seq
        aa_length = len(seq)

    try:
        conn.execute(
            """INSERT INTO viral_proteins
               (isolate_id, protein_accession, protein_name, aa_length, translation, note)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (isolate_id, protein_accession, protein_name[:500], aa_length, translation, note),
        )
        return True
    except Exception as e:
        print(f"    [DB] Insert failed for {protein_accession}: {e}")
        return False


# ── Orchestrator ─────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("Target Protein Downloader")
    print("Downloads missing protein sequences from NCBI")
    print("for viruses needing ICTV classification")
    print("=" * 60)
    print()

    # ── Step 1: Identify ──────────────────────────────────────────────────
    print("[1/5] Identifying target accessions...")
    targets = get_target_accessions()
    print(f"  Found {len(targets):,} isolate accessions to download")
    print(f"  Unique accessions: {len(set(t['accession'] for t in targets)):,}")

    # Group by master_id for reporting (save original counts before filtering)
    original_master_count = len(set(t["master_id"] for t in targets))
    print(f"  Unique master_ids (viruses): {original_master_count}")

    if not targets:
        print("  No targets found. Exiting.")
        return

    # ── Step 2: Filter for real NCBI accessions ──────────────────────────
    # Many accessions in the database are local metagenomic contig names
    # (e.g., BH1-k141_*, os1-k141_*, ZH_*, HS_*) that will never be found
    # in NCBI.  Filter to only real NCBI nucleotide/protein accessions.
    NCBI_ACC_RE = re.compile(r'^[A-Z]{1,4}\d{5,}(\.\d+)?$')

    ncbi_targets = [t for t in targets if NCBI_ACC_RE.match(t["accession"])]
    skipped_local = len(targets) - len(ncbi_targets)

    print(f"\n  Real NCBI accessions: {len(ncbi_targets):,}")
    print(f"  Skipped (local contig names): {skipped_local:,}")

    if not ncbi_targets:
        print("  No NCBI accessions to download. Skipping download step.")

    # Replace full target list with NCBI-only list
    targets = ncbi_targets

    print()
    print(f"[2/5] Downloading from NCBI (batch={BATCH_SIZE}, delay={REQUEST_DELAY}s)...")

    # Ensure blastdb dir exists
    BLASTDB_DIR.mkdir(parents=True, exist_ok=True)
    accessions_list = [t["accession"] for t in targets]
    total = len(accessions_list)

    # Write all downloaded FASTA here
    all_fasta_lines: list[str] = []
    downloaded_count = 0
    failed_count = 0
    failed_accessions: list[str] = []
    nucleotide_fallbacks = 0

    t0 = time.time()
    last_progress_time = t0

    # Accumulators
    all_fasta_lines: list[str] = []
    downloaded_count = 0
    failed_count = 0
    failed_accessions: list[str] = []
    nucleotide_fallbacks = 0
    elapsed_total = 0.0

    if total > 0:
        # Normal download flow
        for batch_start in range(0, total, BATCH_SIZE):
            batch_accs = accessions_list[batch_start:batch_start + BATCH_SIZE]
            batch_num = batch_start // BATCH_SIZE + 1
            total_batches = (total + BATCH_SIZE - 1) // BATCH_SIZE

            print(f"\r  Batch {batch_num}/{total_batches} "
                  f"({batch_start + 1}–{min(batch_start + BATCH_SIZE, total)}/{total})...",
                  end="", flush=True)

            # Fetch
            sequences = fetch_protein_or_nucleotide(batch_accs)

            if sequences is None:
                failed_count += len(batch_accs)
                failed_accessions.extend(batch_accs)
                print(f" [FAILED - no response]")
                time.sleep(REQUEST_DELAY)
                continue

            # Determine if these are nucleotide
            is_nt = False
            if sequences:
                first_val = next(iter(sequences.values()))
                if "[nucleotide_db]" in first_val:
                    is_nt = True
                    nucleotide_fallbacks += 1

            # Write to FASTA
            for acc, fasta_text in sequences.items():
                all_fasta_lines.append(fasta_text)
                all_fasta_lines.append("")

            # Track how many we got
            batch_ok = sum(1 for acc in batch_accs if acc in sequences)
            batch_fail = len(batch_accs) - batch_ok
            downloaded_count += batch_ok
            failed_count += batch_fail

            if batch_fail > 0:
                for acc in batch_accs:
                    if acc not in sequences:
                        failed_accessions.append(acc)

            # Progress report every 10 batches
            elapsed = time.time() - t0
            now = time.time()
            if batch_num % 10 == 0:
                rate = downloaded_count / max(1, elapsed) * 60
                mins = int(elapsed // 60)
                secs = int(elapsed % 60)
                print(f"\r  Progress: {downloaded_count}/{total} downloaded "
                      f"({downloaded_count/total*100:.1f}%). "
                      f"{failed_count} failed. "
                      f"{mins}:{secs:02d} min elapsed. "
                      f"[{rate:.0f} acc/min]            ")

            time.sleep(REQUEST_DELAY)

        # Write combined FASTA file
        OUTPUT_FASTA.write_text("\n".join(all_fasta_lines), encoding="utf-8")
        print(f"\r  FASTA written to {OUTPUT_FASTA}                            ")

        elapsed_total = time.time() - t0
        print(f"\n  Download complete in {elapsed_total/60:.1f} min")
        print(f"  Successfully downloaded: {downloaded_count:,}/{total:,} "
              f"({downloaded_count/total*100:.1f}%)")
        print(f"  Nucleotide fallbacks: {nucleotide_fallbacks}")
        print(f"  Failed: {failed_count:,}")

    # ── Step 3: Insert into database ──────────────────────────────────────
    print()
    print("[3/5] Inserting proteins into database...")

    # Build lookup: accession -> isolate_id
    acc_to_isolate: dict[str, int] = {}
    for t in targets:
        acc = t["accession"]
        if acc not in acc_to_isolate:
            acc_to_isolate[acc] = t["isolate_id"]

    proteins_inserted = 0
    isolates_covered_set: set[int] = set()
    skip_no_match = 0
    skip_duplicate = 0

    if OUTPUT_FASTA.exists():
        fasta_text_all = OUTPUT_FASTA.read_text(encoding="utf-8")
        all_records = parse_fasta(fasta_text_all)
        print(f"  Parsed {len(all_records)} FASTA records from file")

        with db_transaction() as conn:
            for rec in all_records:
                acc = rec["accession"]
                if acc not in acc_to_isolate:
                    # Try matching against original query accession
                    found = False
                    for t in targets:
                        if t["accession"].split(".")[0] == acc or t["accession"] == rec["full_accession"]:
                            acc_to_isolate[acc] = t["isolate_id"]
                            found = True
                            break
                    if not found:
                        skip_no_match += 1
                        continue

                isolate_id = acc_to_isolate[acc]

                # Check for existing protein for this isolate+accession to avoid duplicates
                existing = conn.execute(
                    "SELECT 1 FROM viral_proteins WHERE isolate_id = ? AND protein_accession = ?",
                    (isolate_id, rec["full_accession"]),
                ).fetchone()
                if existing:
                    skip_duplicate += 1
                    continue

                is_nt = "[nucleotide_db]" in rec["header"] or "[nucleotide_derived]" in rec["header"]
                ok = insert_protein(conn, isolate_id, rec, is_nt)
                if ok:
                    proteins_inserted += 1
                    isolates_covered_set.add(isolate_id)

        print(f"  Proteins inserted: {proteins_inserted:,}")
        print(f"  Isolates covered: {len(isolates_covered_set):,}")
        print(f"  Skipped (no isolate match): {skip_no_match}")
        print(f"  Skipped (duplicate): {skip_duplicate}")
    else:
        print(f"  No FASTA file found at {OUTPUT_FASTA}")
        print(f"  Nothing to insert.")

    # ── Step 4: Audit ─────────────────────────────────────────────────────
    print()
    print("[4/5] Post-download audit...")

    with db_connection(read_only=True) as conn:
        # pending_review with proteins
        pr_with = conn.execute("""
            SELECT COUNT(DISTINCT vs.master_id)
            FROM virus_ictv_status vs
            JOIN virus_master vm ON vs.master_id = vm.master_id
            JOIN viral_isolates vi ON vm.master_id = vi.master_id
            JOIN viral_proteins vp ON vi.isolate_id = vp.isolate_id
            WHERE vs.ictv_status = 'pending_review'
              AND vm.entry_type NOT IN ('non_target', 'host_genome',
                                        'duplicate_alias_placeholder',
                                        'duplicate_ictv_vmr_placeholder')
        """).fetchone()[0]

        pr_total = conn.execute("""
            SELECT COUNT(DISTINCT vs.master_id)
            FROM virus_ictv_status vs
            JOIN virus_master vm ON vs.master_id = vm.master_id
            WHERE vs.ictv_status = 'pending_review'
              AND vm.entry_type NOT IN ('non_target', 'host_genome',
                                        'duplicate_alias_placeholder',
                                        'duplicate_ictv_vmr_placeholder')
        """).fetchone()[0]

        # unclassified_not_expected with proteins
        une_with = conn.execute("""
            SELECT COUNT(DISTINCT vs.master_id)
            FROM virus_ictv_status vs
            JOIN virus_master vm ON vs.master_id = vm.master_id
            JOIN viral_isolates vi ON vm.master_id = vi.master_id
            JOIN viral_proteins vp ON vi.isolate_id = vp.isolate_id
            WHERE vs.ictv_status = 'unclassified_not_expected'
              AND vm.entry_type NOT IN ('non_target', 'host_genome',
                                        'duplicate_alias_placeholder',
                                        'duplicate_ictv_vmr_placeholder')
        """).fetchone()[0]

        une_total = conn.execute("""
            SELECT COUNT(DISTINCT vs.master_id)
            FROM virus_ictv_status vs
            JOIN virus_master vm ON vs.master_id = vm.master_id
            WHERE vs.ictv_status = 'unclassified_not_expected'
              AND vm.entry_type NOT IN ('non_target', 'host_genome',
                                        'duplicate_alias_placeholder',
                                        'duplicate_ictv_vmr_placeholder')
        """).fetchone()[0]

        total_proteins_added = conn.execute(
            "SELECT COUNT(*) FROM viral_proteins"
        ).fetchone()[0]

        # How many of our target viruses now have at least one protein
        target_now_covered = conn.execute("""
            SELECT COUNT(DISTINCT vm.master_id)
            FROM virus_ictv_status vs
            JOIN virus_master vm ON vs.master_id = vm.master_id
            JOIN viral_isolates vi ON vm.master_id = vi.master_id
            JOIN viral_proteins vp ON vi.isolate_id = vp.isolate_id
            WHERE vs.ictv_status IN ('pending_review', 'unclassified_not_expected')
              AND vm.entry_type NOT IN ('non_target', 'host_genome',
                                        'duplicate_alias_placeholder',
                                        'duplicate_ictv_vmr_placeholder')
        """).fetchone()[0]

    print(f"  pending_review viruses with proteins: {pr_with}/{pr_total}")
    print(f"  unclassified_not_expected viruses with proteins: {une_with}/{une_total}")
    print(f"  Total target viruses now covered: {target_now_covered}/512")
    print(f"  Total proteins in database: {total_proteins_added:,}")

    # ── Step 5: Final report ──────────────────────────────────────────────
    print()
    print("[5/5] Final Report")
    print("=" * 60)
    print("Target Protein Download Report")
    print("=" * 60)
    print(f"  Accessions to download:     {total:,}")
    print(f"  Successfully downloaded:    {downloaded_count:,} "
          f"({downloaded_count/total*100:.1f}%)" if total else "  N/A")
    print(f"  Proteins inserted:          {proteins_inserted:,}")
    print(f"  Viruses (master_ids) covered: {original_master_count} → {target_now_covered}")
    print(f"  Failed:                    {failed_count:,}")
    print(f"  Time:                      {elapsed_total/60:.1f} min")
    print("=" * 60)


if __name__ == "__main__":
    main()
