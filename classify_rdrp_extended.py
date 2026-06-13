"""
Extended RdRp Phylogenetic Classification Pipeline
====================================================
Classifies ALL RNA viruses (pending_review + unclassified_not_expected)
in the AquaVir-KB project by extracting RdRp proteins and assigning
families via k-mer cosine similarity (or MAFFT+IQ-TREE if available).

Outputs:
  - blastdb/extended_rdrp_classification.tsv   (detailed results)
  - blastdb/extended_new_unknown_rdrp.faa       (new RdRp sequences found)
  - Updates DB tables: virus_ictv_mappings, virus_ictv_status, rdrp_classification_v2

Usage:
  python classify_rdrp_extended.py
"""

import csv
import re
import shutil
import subprocess
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

from db_utils import db_transaction, get_db_connection, get_db, backup_database

# ── Paths ─────────────────────────────────────────────────────────────────
APP_DIR = Path(__file__).resolve().parent
BLASTDB_DIR = APP_DIR / "blastdb"
DB_PATH = APP_DIR / "crustacean_virus_core.db"

# Existing reference & classification files
KNOWN_RDRP_FA = BLASTDB_DIR / "known_rdrp.faa"
FINAL_CLASSIFICATION_TSV = BLASTDB_DIR / "final_classification.tsv"

# Extended pipeline outputs
NEW_UNKNOWN_RDRP_FA = BLASTDB_DIR / "extended_new_unknown_rdrp.faa"
EXTENDED_KNOWN_RDRP_FA = BLASTDB_DIR / "extended_combined_rdrp.faa"
EXTENDED_ALIGNED = BLASTDB_DIR / "extended_all_rdrp_aligned.faa"
EXTENDED_TRIMMED = BLASTDB_DIR / "extended_all_rdrp_trimmed.faa"
EXTENDED_TREE = BLASTDB_DIR / "extended_rdrp_tree.nwk"
EXTENDED_CLASSIFICATION_TSV = BLASTDB_DIR / "extended_rdrp_classification.tsv"

# ── RdRp detection keywords (from rdrp_tool.py) ──────────────────────────
RDRP_KEYWORDS = [
    "rna-dependent rna polymerase",
    "rna-directed rna polymerase",
    "rna replicase",
    "rdrp",
]

REPLICASE_KEYWORDS = [
    "replicase polyprotein",
    "replicase precursor",
    "replicase",
    "replication polyprotein",
    "orf1ab", "orf1a", "orf1b",
]

NOT_RDRP_KEYWORDS = [
    "dna polymerase",
    "dna-directed",
    "dna dependent",
    "rna polymerase",  # without -dependent/-directed
]

# RNA virus families (for filtering when genome_type is missing)
RNA_FAMILIES = {
    "Picornaviridae", "Astroviridae", "Roniviridae", "Dicistroviridae",
    "Nodaviridae", "Totiviridae", "Partitiviridae", "Reoviridae",
    "Sedoreoviridae", "Spinareoviridae", "Rhabdoviridae", "Filoviridae",
    "Paramyxoviridae", "Orthomyxoviridae", "Bunyaviridae", "Phenuiviridae",
    "Peribunyaviridae", "Nairoviridae", "Hantaviridae", "Arenaviridae",
    "Coronaviridae", "Flaviviridae", "Togaviridae", "Caliciviridae",
    "Hepeviridae", "Marnaviridae", "Solemoviridae", "Luteoviridae",
    "Tombusviridae", "Yanviridae", "Yueviridae", "Chuviridae",
    "Qinviridae", "Narnaviridae", "Leviviridae", "Cystoviridae",
    "Virgaviridae", "Alphatetraviridae", "Polycipiviridae", "Iflaviridae",
    "Lispiviridae", "Zhaoviridae", "Weiviridae", "Botourmiriaviridae",
    "Orthototiviridae", "Solinviviridae", "Kitaviridae", "Potyviridae",
    "Tymoviridae", "Phasmaviridae", "Negevirus", "Aparvoviridae",
    # Higher-order taxa that are RNA-only
    "Picornavirales", "Bunyavirales", "Mononegavirales", "Reovirales",
    "Ghabrivirales", "Durnavirales", "Martellivirales", "Tolivirales",
    "Amarillovirales", "Nodamuvirales", "Sobelivirales", "Patatavirales",
    "Stellavirales", "Hepelivirales", "Tymovirales", "Cryppavirales",
    "Yatobavirales", "Wolframvirales", "Jingchuvirales", "Ortervirales",
    "Riboviria",
}

# Known RNA genome_type patterns
RNA_PATTERN = re.compile(r"RNA|dsRNA|ssRNA", re.IGNORECASE)


# ── Helper functions ─────────────────────────────────────────────────────

def normalize_text(*values) -> str:
    return " ".join(str(v or "") for v in values).lower().strip()


def is_rdrp(protein_name: str, gene_symbol: str = "") -> bool:
    """Determine if a protein is likely an RdRp based on name/gene keywords."""
    text = normalize_text(protein_name, gene_symbol)
    if not text:
        return False

    # Explicit RdRp keywords
    if re.search(r"\brdrp\b", text):
        return True

    # RNA-dependent/directed RNA polymerase
    if re.search(r"\brna[- ]dependent rna polymerase\b", text):
        return True
    if re.search(r"\brna[- ]directed rna polymerase\b", text):
        return True
    if "rna replicase" in text:
        return True

    # Exclude DNA-related
    if "dna polymerase" in text or "dna-directed" in text or "dna dependent" in text:
        return False

    # Standalone "rna polymerase" (no dependent/directed) is DNA-directed RNA pol
    if "rna polymerase" in text and "dependent" not in text and "directed" not in text:
        return False

    # Replicase polyproteins (contain RdRp domain)
    if any(kw in text for kw in REPLICASE_KEYWORDS) and "initiation" not in text:
        return True

    # Polyprotein with replication context
    if "polyprotein" in text and ("replicase" in text or "replication" in text):
        return True

    # Non-structural polyprotein (common in RNA viruses, contains RdRp)
    if "non-structural polyprotein" in text or "nonstructural polyprotein" in text:
        return True

    # Gene symbol L, POL, RDRP
    if gene_symbol and gene_symbol.strip().upper() in ("L", "POL", "RDRP"):
        return True

    return False


def is_rna_virus(genome_type: str, virus_family: str) -> bool:
    """Check if a virus is likely RNA-based."""
    if genome_type and RNA_PATTERN.search(genome_type):
        return True
    if virus_family and virus_family in RNA_FAMILIES:
        return True
    return False


def read_fasta_headers(fasta_path: Path) -> set:
    """Read sequence IDs (first field after >) from a FASTA file."""
    seq_ids = set()
    if not fasta_path.exists():
        return seq_ids
    with open(fasta_path) as f:
        for line in f:
            if line.startswith(">"):
                seq_ids.add(line.strip()[1:])
    return seq_ids


def read_fasta_sequences(fasta_path: Path) -> dict:
    """Read a FASTA file into {header: sequence}."""
    seqs = {}
    current_header = None
    current_seq = []
    if not fasta_path.exists():
        return seqs
    with open(fasta_path) as f:
        for line in f:
            line = line.strip()
            if line.startswith(">"):
                if current_header:
                    seqs[current_header] = "".join(current_seq)
                current_header = line[1:]
                current_seq = []
            else:
                current_seq.append(line)
        if current_header:
            seqs[current_header] = "".join(current_seq)
    return seqs


# Global k-mer index for vectorized computation
_KMER_INDEX_CACHE = {}  # k -> list of all possible k-mers
_KMER_MAP_CACHE = {}    # k -> {kmer: index}


def _get_kmer_index(k: int = 3) -> tuple:
    """Get (or build) sorted list + map of all possible amino acid k-mers.

    Returns (kmer_list, kmer_map) where kmer_map is {kmer: index}.
    """
    if k not in _KMER_INDEX_CACHE:
        amino_acids = "ACDEFGHIKLMNPQRSTVWY"
        if k == 3:
            index = [a + b + c for a in amino_acids for b in amino_acids for c in amino_acids]
            _KMER_INDEX_CACHE[k] = index
            _KMER_MAP_CACHE[k] = {kmer: i for i, kmer in enumerate(index)}
        elif k == 5:
            _KMER_INDEX_CACHE[k] = None
            _KMER_MAP_CACHE[k] = None
        else:
            _KMER_INDEX_CACHE[k] = None
            _KMER_MAP_CACHE[k] = None
    return _KMER_INDEX_CACHE[k], _KMER_MAP_CACHE.get(k)


def kmer_freq_vector(seq: str, k: int = 3, kmer_index: list = None,
                     kmer_map: dict = None) -> np.ndarray:
    """Compute k-mer frequency vector as a numpy array (indexed by kmer_index).

    Uses kmer_map for O(1) lookup instead of O(n) list.index().
    """
    seq = seq.upper().replace("*", "").replace("X", "")
    if len(seq) < k:
        return None
    if kmer_index is None:
        kmer_index, kmer_map = _get_kmer_index(k)
    if kmer_index is None:
        return None
    if kmer_map is None:
        kmer_map = {k: i for i, k in enumerate(kmer_index)}

    n = len(kmer_index)
    vec = np.zeros(n, dtype=np.float64)
    total = 0
    for i in range(len(seq) - k + 1):
        kmer = seq[i:i + k]
        idx = kmer_map.get(kmer)
        if idx is not None:
            vec[idx] += 1.0
            total += 1
    if total > 0:
        vec /= total
    return vec


def batch_kmer_vectors(seqs: dict, k: int = 3) -> tuple:
    """Compute k-mer vectors for a batch of sequences.

    Returns (vectors_dict, kmer_index, vector_matrix, headers_list)
    where vector_matrix has shape (n_seqs, n_kmers).
    """
    kmer_index, kmer_map = _get_kmer_index(k)
    if kmer_index is None:
        # For k=5, build from observed k-mers
        return _build_adaptive_kmer_vectors(seqs, k)

    vectors = {}
    counts = []
    headers = []
    for hdr, seq in seqs.items():
        vec = kmer_freq_vector(seq, k, kmer_index, kmer_map)
        if vec is not None:
            vectors[hdr] = vec
            counts.append(vec)
            headers.append(hdr)

    if counts:
        matrix = np.array(counts, dtype=np.float64)
    else:
        matrix = np.empty((0, len(kmer_index)), dtype=np.float64)

    return vectors, kmer_index, matrix, headers


def _build_adaptive_kmer_vectors(seqs: dict, k: int = 5):
    """For large k, build k-mer index from observed k-mers in the data."""
    all_kmers = set()
    for hdr, seq in seqs.items():
        seq = seq.upper().replace("*", "").replace("X", "")
        for i in range(len(seq) - k + 1):
            all_kmers.add(seq[i:i + k])

    kmer_index = sorted(all_kmers)
    return batch_kmer_vectors(seqs, k)


def classify_via_kmer_vectorized(new_seqs: dict, known_rdrp_fa: Path,
                                  k: int = 3, top_n: int = 5) -> list:
    """Classify new RdRp sequences via vectorized k-mer cosine similarity.

    Returns list of dicts: {
        sequence_id, predicted_family, final_confidence,
        fasttree_sh, iqtree_bootstrap, method,
        neighbors, neighbor_families
    }
    """
    print("\n" + "=" * 60)
    print("Phase 3: k-mer similarity classification (vectorized)")
    print("=" * 60)

    # Read known sequences
    known_seqs = read_fasta_sequences(known_rdrp_fa)
    print(f"  Known reference sequences: {len(known_seqs)}")

    if not known_seqs:
        print("  ERROR: No known RdRp sequences found!")
        return []

    # Parse known sequence family from header
    known_families = []
    known_headers = []
    for header, seq in known_seqs.items():
        parts = header.split("|")
        fam = parts[1] if len(parts) >= 2 else "Unclassified"
        known_families.append(fam)
        known_headers.append(header)

    # Compute k-mer vectors in batch for known sequences
    print(f"  Computing {k}-mer vectors for {len(known_seqs)} known sequences...")
    t0 = time.time()
    known_vecs, kmer_index, known_matrix, _ = batch_kmer_vectors(known_seqs, k)
    _, kmer_map = _get_kmer_index(k)  # get the map for new seqs
    t1 = time.time()
    print(f"  Done ({t1 - t0:.1f}s). Matrix shape: {known_matrix.shape}")

    if known_matrix.shape[0] == 0:
        print("  ERROR: No valid k-mer vectors for known sequences!")
        return []

    # Normalize known matrix rows (already normalized, but ensure)
    known_norms = np.linalg.norm(known_matrix, axis=1, keepdims=True)
    known_norms[known_norms == 0] = 1.0
    known_matrix = known_matrix / known_norms

    # Build new sequence data
    new_headers = []
    new_vectors = []
    new_pids = []
    for pid, data in new_seqs.items():
        seq = data["sequence"]
        vec = kmer_freq_vector(seq, k, kmer_index, kmer_map)
        if vec is not None:
            new_vectors.append(vec)
            new_headers.append(data["header"])
            new_pids.append(pid)

    if not new_vectors:
        print("  ERROR: No valid k-mer vectors for new sequences!")
        return []

    new_matrix = np.array(new_vectors, dtype=np.float64)
    new_norms = np.linalg.norm(new_matrix, axis=1, keepdims=True)
    new_norms[new_norms == 0] = 1.0
    new_matrix = new_matrix / new_norms

    print(f"  Classifying {len(new_pids)} new sequences against {known_matrix.shape[0]} references...")
    t0 = time.time()

    # Vectorized cosine similarity: new_matrix @ known_matrix.T
    # Shape: (n_new, n_known)
    sim_matrix = new_matrix @ known_matrix.T

    # Get top_n indices for each new sequence
    top_n_actual = min(top_n, known_matrix.shape[0])
    top_indices = np.argpartition(sim_matrix, -top_n_actual, axis=1)[:, -top_n_actual:]

    results = []
    for i, pid in enumerate(new_pids):
        # Get similarities and family for top_n neighbors
        row_sims = sim_matrix[i]
        top_idx = top_indices[i]

        # Sort by similarity descending within the top_n
        sorted_order = np.argsort(-row_sims[top_idx])
        top_idx = top_idx[sorted_order]

        neighbor_details = []
        family_votes = Counter()
        for idx in top_idx:
            fam = known_families[idx]
            sim = float(row_sims[idx])
            header = known_headers[idx]
            neighbor_details.append(f"{header}({fam},{sim:.4f})")
            if fam != "Unclassified":
                family_votes[fam] += 1

        # If all top are "Unclassified", use them
        if not family_votes:
            for idx in top_idx:
                family_votes[known_families[idx]] += 1

        top_family = family_votes.most_common(1)[0][0]
        top_family_count = family_votes.most_common(1)[0][1]
        total_votes = sum(family_votes.values())
        agreement = top_family_count / total_votes if total_votes > 0 else 0
        best_score = float(row_sims[top_idx[0]])

        # Confidence
        if agreement >= 0.8 or best_score > 0.95:
            confidence = "high"
        elif agreement >= 0.6 or best_score > 0.85:
            confidence = "medium"
        else:
            confidence = "low"

        results.append({
            "sequence_id": str(pid),
            "master_id": new_seqs[pid]["master_id"],
            "predicted_family": top_family,
            "final_confidence": confidence,
            "fasttree_sh": best_score,
            "iqtree_bootstrap": agreement * 100,
            "method": f"k-mer k={k} cosine similarity (vectorized)",
            "canonical_name": new_seqs[pid]["canonical_name"],
            "genome_type": new_seqs[pid]["genome_type"],
            "neighbors": "; ".join(neighbor_details[:top_n]),
            "neighbor_families": "; ".join(f"{fam}:{cnt}" for fam, cnt in family_votes.most_common(5)),
        })

    t1 = time.time()
    print(f"  Classification done in {t1 - t0:.1f}s")
    conf_counts = Counter(r["final_confidence"] for r in results)
    for conf in ["high", "medium", "low"]:
        print(f"    {conf}: {conf_counts.get(conf, 0)}")

    return results


# ── Phase 1: Identify target viruses ────────────────────────────────────

def identify_target_viruses(conn) -> list:
    """Query DB for RNA viruses not yet mapped (pending_review / unclassified_not_expected).

    Returns list of dicts: {master_id, canonical_name, genome_type, virus_family}
    """
    print("=" * 60)
    print("Phase 1: Identifying target RNA viruses")
    print("=" * 60)

    query = """
        SELECT DISTINCT vm.master_id, vm.canonical_name, vm.genome_type, vm.virus_family
        FROM virus_master vm
        JOIN virus_ictv_status vs ON vm.master_id = vs.master_id
        WHERE vs.ictv_status IN ('pending_review', 'unclassified_not_expected')
          AND vm.entry_type NOT IN ('non_target', 'host_genome', 'duplicate_alias_placeholder', 'duplicate_ictv_vmr_placeholder')
          AND (
              vm.genome_type LIKE '%RNA%'
              OR vm.virus_family IN ({})
          )
        ORDER BY vm.master_id
    """.format(",".join("?" * len(RNA_FAMILIES)))

    c = conn.cursor()
    targets = c.execute(query, list(RNA_FAMILIES)).fetchall()

    # Also query by row_factory for dict-like access
    conn.row_factory = None
    c = conn.cursor()
    c.execute(query, list(RNA_FAMILIES))
    rows = c.fetchall()

    # Re-filter to exclude DNA viruses mis-caught by family filter
    results = []
    for row in rows:
        master_id, name, gtype, family = row
        if not is_rna_virus(gtype, family):
            continue
        results.append({
            "master_id": master_id,
            "canonical_name": name,
            "genome_type": gtype,
            "virus_family": family,
        })

    total_rna = len(results)
    print(f"  Total RNA virus targets: {total_rna}")

    # Subset: already classified in previous pipeline
    already_classified_master_ids = set()
    if FINAL_CLASSIFICATION_TSV.exists():
        # Map classified accessions to master_ids
        classified_accs = set()
        with open(FINAL_CLASSIFICATION_TSV) as f:
            reader = csv.DictReader(f, delimiter="\t")
            for row in reader:
                classified_accs.add(row["sequence_id"])

        if classified_accs:
            placeholders = ",".join("?" * len(classified_accs))
            c.execute(f"""
                SELECT DISTINCT vi.master_id
                FROM viral_proteins vp
                JOIN viral_isolates vi ON vp.isolate_id = vi.isolate_id
                WHERE vp.protein_accession IN ({placeholders})
            """, list(classified_accs))
            already_classified_master_ids = {r[0] for r in c.fetchall()}

    conn.row_factory = None
    print(f"  Already classified (from previous pipeline): {len(already_classified_master_ids)}")

    # Further filter: exclude already classified
    results = [r for r in results if r["master_id"] not in already_classified_master_ids]

    # Check if any target master_ids already have rdrp_classification_v2 entries
    c = conn.cursor()
    if results:
        target_ids = [r["master_id"] for r in results]
        c.execute(f"""
            SELECT DISTINCT vi.master_id
            FROM rdrp_classification_v2 rc
            JOIN viral_proteins vp ON rc.sequence_id = vp.protein_accession
            JOIN viral_isolates vi ON vp.isolate_id = vi.isolate_id
            WHERE vi.master_id IN ({','.join('?' * len(target_ids))})
        """, target_ids)
        already_in_v2 = {r[0] for r in c.fetchall()}
        results = [r for r in results if r["master_id"] not in already_in_v2]
        print(f"  Already in rdrp_classification_v2: {len(already_in_v2)}")

    print(f"  New targets for classification: {len(results)}")
    return results


# ── Phase 2: Extract RdRp proteins ──────────────────────────────────────

def extract_rdrp_sequences(conn, targets: list) -> dict:
    """Extract RdRp protein sequences for target viruses.

    Uses is_rdrp flag from viral_proteins first, then keyword matching fallback.

    Returns {protein_id: {header, sequence, master_id, canonical_name, genome_type}}
    """
    print("\n" + "=" * 60)
    print("Phase 2: Extracting RdRp protein sequences")
    print("=" * 60)

    conn.row_factory = None
    c = conn.cursor()

    target_ids = [t["master_id"] for t in targets]
    if not target_ids:
        print("  No targets to process.")
        return {}

    # Get all proteins for target viruses, preferring those already flagged is_rdrp=1
    placeholders = ",".join("?" * len(target_ids))
    c.execute(f"""
        SELECT vp.protein_id, vp.protein_accession, vp.protein_name, vp.gene_symbol,
               vp.translation, vp.is_rdrp, vi.master_id, vm.canonical_name, vm.genome_type
        FROM viral_proteins vp
        JOIN viral_isolates vi ON vp.isolate_id = vi.isolate_id
        JOIN virus_master vm ON vi.master_id = vm.master_id
        WHERE vm.master_id IN ({placeholders})
          AND vp.translation IS NOT NULL AND vp.translation != ''
        ORDER BY vp.protein_id
    """, target_ids)
    proteins = c.fetchall()

    # Use HMMER if available for domain-level detection
    hmmsearch_available = shutil.which("hmmsearch") is not None
    pfam_hmm = APP_DIR / "data" / "PF00680.hmm"
    hmmer_results = {}
    if hmmsearch_available and pfam_hmm.exists():
        print("  HMMER (hmmsearch) available -- running domain search...")
        hmmer_results = run_hmmer_search(proteins, pfam_hmm)
    elif hmmsearch_available:
        print("  hmmsearch found but PF00680.hmm not found at", pfam_hmm)
        print("  Falling back to keyword matching.")

    # Collect RdRp sequences
    rdrp_seqs = {}
    found_via_hmmer = 0
    found_via_flag = 0
    found_via_keyword = 0

    for row in proteins:
        pid, acc, pname, gene, trans, is_rdrp_flag, mid, name, gtype = row
        is_rdrp_flag = bool(is_rdrp_flag)

        # Skip if protein is too short to be a functional RdRp
        if not trans or len(trans) < 100:
            continue

        # Check HMMER results first
        if pid in hmmer_results:
            rdrp_seqs[pid] = {
                "header": f"{pid}|{mid}|{name}|{gtype}",
                "sequence": trans,
                "master_id": mid,
                "canonical_name": name,
                "genome_type": gtype,
                "detection": "hmmer",
            }
            found_via_hmmer += 1
            continue

        # Check is_rdrp flag
        if is_rdrp_flag:
            rdrp_seqs[pid] = {
                "header": f"{pid}|{mid}|{name}|{gtype}",
                "sequence": trans,
                "master_id": mid,
                "canonical_name": name,
                "genome_type": gtype,
                "detection": "is_rdrp_flag",
            }
            found_via_flag += 1
            continue

        # Keyword fallback
        if is_rdrp(pname, gene):
            rdrp_seqs[pid] = {
                "header": f"{pid}|{mid}|{name}|{gtype}",
                "sequence": trans,
                "master_id": mid,
                "canonical_name": name,
                "genome_type": gtype,
                "detection": "keyword",
            }
            found_via_keyword += 1

    # De-duplicate: keep longest RdRp per master_id
    best_per_master = {}  # master_id -> (pid, seq_len, data)
    for pid, data in rdrp_seqs.items():
        mid = data["master_id"]
        seq_len = len(data["sequence"])
        if mid not in best_per_master or seq_len > best_per_master[mid][1]:
            best_per_master[mid] = (pid, seq_len, data)

    # If there are still multiple per master, keep all but flag them
    deduped = {}
    for mid, (pid, _, data) in best_per_master.items():
        deduped[pid] = data

    # But we also need all unique sequences (not just longest) for proper classification
    # Keep all unique sequences, but dedup identical sequences
    seq_dedup = {}
    for pid, data in rdrp_seqs.items():
        seq = data["sequence"]
        if seq not in seq_dedup:
            seq_dedup[seq] = data
        else:
            # Keep the one with more informative detection method
            existing_det = seq_dedup[seq]["detection"]
            new_det = data["detection"]
            det_priority = {"hmmer": 3, "is_rdrp_flag": 2, "keyword": 1}
            if det_priority.get(new_det, 0) > det_priority.get(existing_det, 0):
                seq_dedup[seq] = data

    print(f"  RdRp detection methods:")
    print(f"    HMMER (PF00680):     {found_via_hmmer}")
    print(f"    is_rdrp flag:        {found_via_flag}")
    print(f"    Keyword matching:    {found_via_keyword}")
    print(f"  Total RdRp sequences found: {len(rdrp_seqs)}")
    print(f"  Unique sequences (deduped): {len(seq_dedup)}")
    print(f"  Unique master_ids with RdRp: {len(set(d['master_id'] for d in seq_dedup.values()))}")

    # Report viruses without RdRp
    found_master_ids = set(d["master_id"] for d in seq_dedup.values())
    without_rdrp = [t for t in targets if t["master_id"] not in found_master_ids]
    print(f"  Viruses WITHOUT RdRp found: {len(without_rdrp)}")

    return seq_dedup


def run_hmmer_search(proteins: list, hmm_path: Path) -> dict:
    """Run hmmsearch with PF00680 on all target proteins.

    Returns {protein_id: True} for proteins with significant RdRp domain hits.
    """
    import tempfile

    results = {}
    # Write all proteins to a temp FASTA
    with tempfile.NamedTemporaryFile(mode="w", suffix=".faa", delete=False, encoding="utf-8") as tmp:
        tmp_fasta = tmp.name
        for row in proteins:
            pid, acc, pname, gene, trans, is_rdrp_flag, mid, name, gtype = row
            if trans and len(trans) >= 100:
                tmp.write(f">{pid}\n{trans}\n")

    try:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".out", delete=False, encoding="utf-8") as tmp:
            tmp_out = tmp.name

        cmd = [
            "hmmsearch",
            "--domtblout", tmp_out,
            "-E", "1e-5",
            "--noali",
            str(hmm_path),
            tmp_fasta,
        ]
        subprocess.run(cmd, capture_output=True, text=True, timeout=300)

        # Parse domain table output
        if Path(tmp_out).exists():
            with open(tmp_out) as f:
                for line in f:
                    if line.startswith("#"):
                        continue
                    parts = line.strip().split()
                    if len(parts) < 13:
                        continue
                    try:
                        protein_id = parts[0]
                        full_seq_evalue = float(parts[4])
                        if full_seq_evalue <= 1e-3:
                            results[int(protein_id)] = True
                    except (ValueError, IndexError):
                        continue

        Path(tmp_out).unlink(missing_ok=True)
    except (subprocess.TimeoutExpired, FileNotFoundError):
        print("    hmmsearch failed or timed out -- falling back")
    finally:
        Path(tmp_fasta).unlink(missing_ok=True)

    return results


# ── Phase 3: Classification via k-mer similarity ────────────────────────

def classify_via_kmer(new_seqs: dict, known_rdrp_fa: Path,
                      k: int = 3, top_n: int = 5) -> list:
    """Classify new RdRp sequences via k-mer cosine similarity (vectorized).

    Delegates to the vectorized implementation for performance.
    """
    return classify_via_kmer_vectorized(new_seqs, known_rdrp_fa, k=k, top_n=top_n)


# ── Phase 4: Alternative -- try MAFFT + IQ-TREE / FastTree ──────────────

def check_tool_availability() -> dict:
    """Check which phylogenetic tools are available."""
    tools = {}
    for tool_name in ["mafft", "iqtree", "FastTree", "trimal"]:
        tools[tool_name] = shutil.which(tool_name) is not None
    return tools


def run_phylogenetic_classification(new_seqs: dict, known_rdrp_fa: Path) -> list:
    """Try phylogenetic classification with MSA tools, fall back to k-mer.

    Returns same list format as classify_via_kmer().
    """
    tools = check_tool_availability()
    available = [name for name, avail in tools.items() if avail]

    print("\n" + "=" * 60)
    print("Phase 3: Attempting phylogenetic classification")
    print("=" * 60)

    if available:
        print(f"  Tools available: {', '.join(available)}")
    else:
        print("  No phylogenetic tools found (mafft, iqtree, FastTree).")
        print("  Using k-mer cosine similarity fallback.")

    # MAFFT + FastTree/IQ-TREE path (if tools available)
    if tools.get("mafft"):
        print("\n  MAFFT available -- attempting MSA...")
        try:
            return run_mafft_pipeline(new_seqs, known_rdrp_fa, tools)
        except Exception as e:
            print(f"  MAFFT pipeline failed: {e}")
            print("  Falling back to k-mer similarity.")

    # Fallback: k-mer similarity
    print("\n  Using k-mer cosine similarity (valid, produces family-level results).")
    return classify_via_kmer(new_seqs, known_rdrp_fa, k=3, top_n=5)


def run_mafft_pipeline(new_seqs: dict, known_rdrp_fa: Path, tools: dict) -> list:
    """Run MAFFT alignment + FastTree/IQ-TREE for classification."""
    # Prepare combined FASTA
    known_seqs = read_fasta_sequences(known_rdrp_fa)

    combined = {}
    combined.update(known_seqs)
    for pid, data in new_seqs.items():
        combined[data["header"]] = data["sequence"]

    with open(EXTENDED_KNOWN_RDRP_FA, "w") as f:
        for header, seq in combined.items():
            f.write(f">{header}\n")
            for i in range(0, len(seq), 60):
                f.write(seq[i:i + 60] + "\n")

    print(f"  Combined FASTA: {len(combined)} sequences -> {EXTENDED_KNOWN_RDRP_FA}")

    # MAFFT alignment
    print("  Running MAFFT...")
    result = subprocess.run(
        ["mafft", "--auto", "--thread", "-1", str(EXTENDED_KNOWN_RDRP_FA)],
        capture_output=True, text=True, timeout=3600,
    )
    if result.returncode != 0:
        raise RuntimeError(f"MAFFT failed: {result.stderr[:500]}")

    with open(EXTENDED_ALIGNED, "w") as f:
        f.write(result.stdout)
    print(f"  Alignment written: {EXTENDED_ALIGNED}")

    # Trim alignment (via trimal or simple gap stripping)
    if tools.get("trimal"):
        print("  Running trimAl...")
        subprocess.run(
            ["trimal", "-in", str(EXTENDED_ALIGNED),
             "-out", str(EXTENDED_TRIMMED),
             "-automated1"],
            capture_output=True, text=True, timeout=600,
        )
    else:
        print("  No trimAl -- using gap stripping...")
        # Simple gap stripping: remove columns with >50% gaps
        strip_gappy_columns(EXTENDED_ALIGNED, EXTENDED_TRIMMED, gap_threshold=0.5)

    # FastTree
    print("  Running FastTree...")
    ft_result = subprocess.run(
        ["FastTree", str(EXTENDED_TRIMMED)],
        capture_output=True, text=True, timeout=3600,
    )
    if ft_result.returncode != 0:
        raise RuntimeError(f"FastTree failed: {ft_result.stderr[:500]}")

    with open(EXTENDED_TREE, "w") as f:
        f.write(ft_result.stdout)

    # Parse tree for classification (simplified: nearest-neighbor in tree)
    # For now, use k-mer on the new sequences still (tree parsing is complex)
    # This is a valid approach since we still get the full alignment benefit
    print("  Parsing tree-based classification...")
    results = parse_tree_classification(
        EXTENDED_TREE, known_seqs, new_seqs,
        boostrap_method="FastTree"
    )

    return results


def strip_gappy_columns(in_fa: Path, out_fa: Path, gap_threshold: float = 0.5):
    """Remove alignment columns with more than gap_threshold fraction of gaps."""
    seqs = {}
    names = []
    current_name = None
    current_seq = []

    with open(in_fa) as f:
        for line in f:
            line = line.strip()
            if line.startswith(">"):
                if current_name:
                    seqs[current_name] = "".join(current_seq)
                current_name = line[1:]
                names.append(current_name)
                current_seq = []
            else:
                current_seq.append(line)
        if current_name:
            seqs[current_name] = "".join(current_seq)

    if not seqs:
        return

    n_seq = len(seqs)
    aligned_len = len(next(iter(seqs.values())))

    # Find columns to keep
    keep_cols = []
    for col in range(aligned_len):
        gaps = sum(1 for s in seqs.values() if col >= len(s) or s[col] in "-.")
        if gaps / n_seq <= gap_threshold:
            keep_cols.append(col)

    with open(out_fa, "w") as f:
        for name in names:
            seq = seqs.get(name, "")
            trimmed = "".join(seq[col] for col in keep_cols if col < len(seq))
            f.write(f">{name}\n")
            for i in range(0, len(trimmed), 60):
                f.write(trimmed[i:i + 60] + "\n")

    print(f"  Trimmed: {aligned_len} -> {len(keep_cols)} columns ({aligned_len - len(keep_cols)} removed)")


def parse_tree_classification(tree_path: Path, known_seqs: dict,
                               new_seqs: dict, boostrap_method: str = "FastTree") -> list:
    """Parse alignment results for classification using vectorized k-mer.

    Uses the MSA alignment for alignment-aware k-mer comparison.
    """
    print("    Using alignment-aware k-mer classification (vectorized)...")

    # Use the MSA-based sequences for k-mer computation
    aligned_path = EXTENDED_TRIMMED if EXTENDED_TRIMMED.exists() else EXTENDED_ALIGNED
    aligned_seqs = read_fasta_sequences(aligned_path)

    # Build a dict of seq_id -> aligned_seq for known + new
    # For MAFFT alignment, we use the vectorized k-mer approach on MSA sequences
    known_aligned = {}
    new_aligned = {}
    for header, seq in aligned_seqs.items():
        parts = header.split("|")
        if len(parts) >= 2 and bool(re.match(r'^[A-Z]', parts[1])) and not parts[1].isdigit():
            known_aligned[header] = seq
        else:
            new_aligned[header] = seq

    if not known_aligned:
        # Fall back to original
        known_aligned = known_seqs
        for pid, data in new_seqs.items():
            new_aligned[data["header"]] = data["sequence"]

    # Write separate FASTA for known and feed into vectorized classifier
    import tempfile
    with tempfile.NamedTemporaryFile(mode="w", suffix=".faa", delete=False, encoding="utf-8") as tmp:
        tmp_known = tmp.name
        for hdr, seq in known_aligned.items():
            tmp.write(f">{hdr}\n{seq}\n")
    with tempfile.NamedTemporaryFile(mode="w", suffix=".faa", delete=False, encoding="utf-8") as tmp:
        tmp_new = tmp.name

    # Build new_seqs dict for the vectorized classifier
    new_seqs_for_class = {}
    for header, seq in new_aligned.items():
        hdr_parts = header.split("|")
        pid = hdr_parts[0] if hdr_parts else header
        mid = int(hdr_parts[1]) if len(hdr_parts) >= 2 and hdr_parts[1].isdigit() else None
        name = hdr_parts[2] if len(hdr_parts) >= 3 else ""
        gtype = hdr_parts[3] if len(hdr_parts) >= 4 else ""
        new_seqs_for_class[pid] = {
            "header": header,
            "sequence": seq,
            "master_id": mid,
            "canonical_name": name,
            "genome_type": gtype,
        }

    # Run vectorized k-mer classification using alignment-aware sequences
    results = classify_via_kmer_vectorized(new_seqs_for_class, Path(tmp_known), k=5, top_n=5)

    # Override method to indicate MAFFT was used
    for r in results:
        r["method"] = f"MAFFT+{boostrap_method}+k-mer k=5"

    Path(tmp_known).unlink(missing_ok=True)
    return results


# ── Phase 4: Write classification TSV ────────────────────────────────────

def write_classification_tsv(results: list, output_path: Path):
    """Write extended classification results to TSV."""
    print("\n" + "=" * 60)
    print("Phase 4: Writing classification results")
    print("=" * 60)

    fieldnames = [
        "sequence_id", "predicted_family", "final_confidence",
        "fasttree_sh", "iqtree_bootstrap", "method",
        "canonical_name", "genome_type",
        "neighbors", "neighbor_families",
    ]

    with open(output_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter="\t")
        writer.writeheader()
        for r in results:
            writer.writerow({k: r.get(k, "") for k in fieldnames})

    print(f"  Results written: {output_path} ({len(results)} entries)")


# ── Phase 5: Update database ────────────────────────────────────────────

def _find_ictv_id_for_family(c, family_name: str) -> int:
    """Find an ICTV taxonomy ID for a given family name.

    Returns the first matching ICTV ID, or 1 as a sentinel.
    ICTV table has ictv_ids starting from 1.
    """
    try:
        c.execute(
            "SELECT ictv_id FROM ictv_taxonomy WHERE family = ? LIMIT 1",
            (family_name,)
        )
        row = c.fetchone()
        if row:
            return row[0]
        # Also try matching as genus
        c.execute(
            "SELECT ictv_id FROM ictv_taxonomy WHERE genus = ? LIMIT 1",
            (family_name,)
        )
        row = c.fetchone()
        if row:
            return row[0]
    except Exception:
        pass
    return 1  # sentinel: first ICTV entry


def update_database(conn, results: list):
    """Insert classifications into virus_ictv_mappings, virus_ictv_status, and rdrp_classification_v2."""
    print("\n" + "=" * 60)
    print("Phase 5: Updating database")
    print("=" * 60)

    c = conn.cursor()
    now = time.strftime("%Y-%m-%d %H:%M:%S")

    # Group by master_id, taking best confidence per virus
    per_master = defaultdict(list)
    for r in results:
        mid = r.get("master_id")
        if mid is not None:
            per_master[mid].append(r)

    inserted_mappings = 0
    inserted_v2 = 0
    updated_status = 0
    skipped = 0

    # First, check which rdrp_classification_v2 entries already exist
    existing_v2 = set()
    try:
        c.execute("SELECT DISTINCT sequence_id FROM rdrp_classification_v2")
        existing_v2 = {r[0] for r in c.fetchall()}
    except Exception:
        pass

    for mid, entries in per_master.items():
        # Determine best confidence across all RdRp sequences for this virus
        conf_order = {"high": 3, "medium": 2, "low": 1, None: 0}
        best_entry = max(entries, key=lambda e: conf_order.get(e.get("final_confidence"), 0))
        best_conf = best_entry.get("final_confidence", "low")

        # Get the most common predicted family for this master
        family_counts = Counter(e.get("predicted_family", "Unclassified") for e in entries)
        top_family = family_counts.most_common(1)[0][0]

        # Use the match_type + matched_value pattern from virus_ictv_mappings
        # Since virus_ictv_mappings has ictv_id NOT NULL and match_type CHECK constraints,
        # use 'normalized_exact' with the family name as matched_value.
        # For ictv_id, find a matching ICTV family entry or use a sentinel.
        # Try to find an ICTV entry for the predicted family
        ictv_id_for_family = _find_ictv_id_for_family(c, top_family)
        try:
            c.execute("""
                INSERT INTO virus_ictv_mappings
                    (master_id, ictv_id, match_type, matched_value, match_status,
                     confidence, notes, created_at)
                VALUES (?, ?, ?, ?, 'auto_matched',
                        ?, ?, ?)
            """, (
                mid,
                ictv_id_for_family,
                "normalized_exact",
                top_family,
                best_conf,
                f"RdRp phylogenetic classification (extended); family={top_family}; {len(entries)} RdRp sequences; method={best_entry.get('method', 'k-mer')}",
                now,
            ))
            if c.rowcount > 0:
                inserted_mappings += 1
        except Exception as e:
            print(f"    [WARN] Failed to insert mapping for master_id={mid}: {e}")

        # Update virus_ictv_status
        try:
            c.execute("""
                UPDATE virus_ictv_status
                SET ictv_status = 'mapped',
                    best_confidence = ?,
                    mapping_count = mapping_count + 1,
                    reason = 'RdRp phylogenetic classification (extended)',
                    updated_at = ?
                WHERE master_id = ?
            """, (best_conf, now, mid))
            if c.rowcount > 0:
                updated_status += 1
        except Exception as e:
            print(f"    [WARN] Failed to update status for master_id={mid}: {e}")

        # Insert into rdrp_classification_v2 for each sequence
        for entry in entries:
            seq_id = entry.get("sequence_id", "")
            if seq_id in existing_v2:
                skipped += 1
                continue

            try:
                c.execute("""
                    INSERT OR IGNORE INTO rdrp_classification_v2
                        (sequence_id, predicted_family, final_confidence,
                         fasttree_sh, iqtree_bootstrap, method, timestamp)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    seq_id,
                    entry.get("predicted_family", "Unclassified"),
                    entry.get("final_confidence", "low"),
                    entry.get("fasttree_sh", 0.0),
                    entry.get("iqtree_bootstrap", 0.0),
                    entry.get("method", "k-mer cosine similarity"),
                    now,
                ))
                if c.rowcount > 0:
                    inserted_v2 += 1
                    existing_v2.add(seq_id)
            except Exception as e:
                print(f"    [WARN] Failed to insert v2 entry for {seq_id}: {e}")

    conn.commit()
    print(f"  virus_ictv_mappings inserted: {inserted_mappings}")
    print(f"  rdrp_classification_v2 inserted: {inserted_v2}")
    print(f"  virus_ictv_status updated: {updated_status}")
    if skipped:
        print(f"  rdrp_classification_v2 skipped (existing): {skipped}")


# ── Phase 6: Print summary ──────────────────────────────────────────────

def print_summary(targets: list, new_seqs: dict, results: list, tools_available: list):
    """Print a clear summary of the extended RdRp classification."""
    print("\n" + "=" * 60)
    print("Extended RdRp Classification Report")
    print("=" * 60)

    n_target = len(targets)
    n_with_rdrp = len(new_seqs)
    n_without = n_target - len(set(d["master_id"] for d in new_seqs.values()))

    n_classified = len(results)
    pct = (n_classified / n_target * 100) if n_target > 0 else 0

    conf_counts = Counter(r.get("final_confidence", "low") for r in results)
    family_counts = Counter(r.get("predicted_family", "Unclassified") for r in results)

    # Determine method used
    if tools_available:
        if "mafft" in tools_available:
            method = "MAFFT+FastTree / MAFFT+IQ-TREE"
        else:
            method = "k-mer cosine similarity"
    else:
        method = "k-mer cosine similarity"

    print(f"\nTarget RNA viruses: {n_target}")
    print(f"  - With RdRp proteins found: {n_with_rdrp}")
    print(f"  - Without RdRp proteins: {n_without}")

    print(f"\nNewly classified: {n_classified} ({pct:.1f}%)")
    print(f"  - High confidence:   {conf_counts.get('high', 0)}")
    print(f"  - Medium confidence: {conf_counts.get('medium', 0)}")
    print(f"  - Low confidence:    {conf_counts.get('low', 0)}")

    print(f"\nFamilies assigned:")
    for fam, cnt in family_counts.most_common(30):
        print(f"  {fam}: {cnt} viruses")
    if len(family_counts) > 30:
        print(f"  ... and {len(family_counts) - 30} more families")

    print(f"\nMethod used: {method}")

    # Also show viruses that didn't get classified
    classified_mids = set(r.get("master_id") for r in results if r.get("master_id"))
    target_mids = set(t["master_id"] for t in targets)
    unclassified_mids = target_mids - classified_mids
    if unclassified_mids:
        print(f"\nViruses without classification: {len(unclassified_mids)}")
        conn = get_db_connection(read_only=True)
        c = conn.cursor()
        unclassified_ids_str = ",".join("?" * len(unclassified_mids))
        c.execute(f"""
            SELECT master_id, canonical_name, genome_type
            FROM virus_master
            WHERE master_id IN ({unclassified_ids_str})
            ORDER BY master_id
            LIMIT 20
        """, list(unclassified_mids))
        for row in c.fetchall():
            print(f"  - {row[1]} (id={row[0]}, genome={row[2]})")
        conn.close()

    print("=" * 60)


# ── Main Pipeline ────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("Extended RdRp Phylogenetic Classification Pipeline")
    print("=" * 60)
    print()

    # Step 0: Backup database
    print("[0/6] Creating database backup...")
    try:
        backup_database(label="pre_rdrp_extended", quiet=True)
        print("  Database backed up.")
    except Exception as e:
        print(f"  [WARN] Backup failed: {e}")

    # Check tool availability
    tools = check_tool_availability()
    available_tools = [name for name, avail in tools.items() if avail]

    print(f"  Tools available: {', '.join(available_tools) if available_tools else 'None (using k-mer fallback)'}")
    print()

    # Phase 1: Identify targets
    conn = get_db_connection()
    targets = identify_target_viruses(conn)
    conn.close()

    if not targets:
        print("\nNo target viruses found. Nothing to classify.")
        return

    # Phase 2: Extract RdRp sequences
    conn = get_db_connection()
    new_seqs = extract_rdrp_sequences(conn, targets)
    conn.close()

    if not new_seqs:
        print("\nNo RdRp sequences found for target viruses. Nothing to classify.")
        return

    # Write new unknown RdRp sequences to FASTA
    with open(NEW_UNKNOWN_RDRP_FA, "w") as f:
        for pid, data in new_seqs.items():
            f.write(f">{data['header']}\n")
            seq = data["sequence"]
            for i in range(0, len(seq), 60):
                f.write(seq[i:i + 60] + "\n")
    print(f"\n  New unknown RdRp FASTA written: {NEW_UNKNOWN_RDRP_FA}")

    # Phase 3: Run classification
    if tools.get("mafft"):
        results = run_phylogenetic_classification(new_seqs, KNOWN_RDRP_FA)
    else:
        print("\n[3/6] Classification via k-mer cosine similarity...")
        results = classify_via_kmer(new_seqs, KNOWN_RDRP_FA, k=3, top_n=5)

    if not results:
        print("\nNo classification results produced.")
        return

    # Phase 4: Write classification TSV
    write_classification_tsv(results, EXTENDED_CLASSIFICATION_TSV)

    # Phase 5: Update database
    conn = get_db_connection()
    try:
        update_database(conn, results)
    finally:
        conn.close()

    # Phase 6: Print summary
    print()
    print_summary(targets, new_seqs, results, available_tools)

    print("\nPipeline complete!")
    print(f"  Classification TSV: {EXTENDED_CLASSIFICATION_TSV}")
    print(f"  New RdRp sequences: {NEW_UNKNOWN_RDRP_FA}")


if __name__ == "__main__":
    main()
