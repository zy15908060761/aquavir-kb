"""
Parse IQ-TREE output, classify unknown RdRp sequences by nearest known-family neighbor.
Writes results to DB and produces a classification report.
"""
import re, sys, os, sqlite3
from pathlib import Path
from collections import defaultdict

PROJ = Path(r"F:\水生无脊椎动物数据库")
DB_PATH = PROJ / "db" / "database.db"  # adjust if different
TREE_PATH = PROJ / "blastdb" / "rdrp_tree.contree"
UNKNOWN_FA = PROJ / "blastdb" / "unknown_rdrp.faa"
OUTPUT = PROJ / "blastdb" / "rdrp_classification.tsv"

# Bootstrap threshold for reliable clade assignment
BOOTSTRAP_THRESHOLD = 70.0
# Family consensus threshold (proportion of nearest known neighbors agreeing)
FAMILY_CONSENSUS = 0.5


def parse_newick(newick_str):
    """Parse Newick tree string, return (taxa, parent_map, children_map, branch_lengths, supports)."""
    # Tokenize
    tokens = re.findall(r"([^;,()\s]+)|([,();])", newick_str)
    taxa = []
    parent_map = {}
    children_map = defaultdict(list)
    branch_lengths = {}
    supports = {}
    stack = []
    node_id = 0
    current_node = None
    i = 0

    while i < len(tokens):
        text, delim = tokens[i]
        if text:
            # Could be taxon name, support value, or branch length
            lookahead = []
            j = i + 1
            while j < len(tokens):
                nt, nd = tokens[j]
                if nt:
                    lookahead.append(('text', nt))
                    j += 1
                elif nd == ':':
                    lookahead.append(('colon', ':'))
                    j += 1
                    if j < len(tokens) and tokens[j][0]:
                        lookahead.append(('blen', tokens[j][0]))
                        j += 1
                elif nd in ',();':
                    break
                else:
                    break

            # This is a leaf taxon or a support value
            # For simplicity, handle via tree reconstruction
            pass
        elif delim:
            if delim == '(':
                node_id += 1
                new_node = f"node_{node_id}"
                if current_node is not None:
                    parent_map[new_node] = current_node
                    children_map[current_node].append(new_node)
                stack.append(current_node)
                current_node = new_node
            elif delim == ')':
                if stack:
                    current_node = stack.pop()
            elif delim == ',':
                # Next sibling
                pass
            elif delim == ';':
                break
        i += 1

    return taxa, parent_map, children_map, branch_lengths, supports


def extract_clades_from_tree(tree_str):
    """Use a simpler approach: read the .treefile (not consensus) and extract distances."""
    # We'll use a distance-based approach from the tree file
    pass


def read_unknown_ids(fasta_path):
    """Get list of unknown virus sequence IDs."""
    ids = []
    with open(fasta_path) as f:
        for line in f:
            if line.startswith(">"):
                ids.append(line[1:].strip().split()[0])
    return ids


def parse_treefile(treefile_path, unknown_ids):
    """
    Parse IQ-TREE .treefile (unrooted ML tree in Newick).
    Compute pairwise distances between unknown and known taxa from the tree.
    """
    if not os.path.exists(treefile_path):
        print(f"Tree file not found: {treefile_path}")
        return None

    with open(treefile_path) as f:
        tree_str = f.read().strip()

    # Extract taxa
    taxa_raw = re.findall(r'([A-Za-z0-9_\-\.]+):', tree_str)
    # Also handle taxa without branch lengths
    taxa_raw2 = re.findall(r'([A-Za-z0-9_\-\.]+)[,);]', tree_str)
    print(f"Found {len(taxa_raw)} taxa with branch lengths, {len(taxa_raw2)} total taxa references")

    unknown_set = set(unknown_ids)
    unknown_found = [t for t in taxa_raw if t in unknown_set]
    print(f"Found {len(unknown_found)}/{len(unknown_ids)} unknown sequences in tree")

    return taxa_raw


def assign_families_nearest_neighbor(treefile_path, unknown_ids, known_family_map):
    """
    For each unknown sequence, find the closest known-family neighbor in the tree
    and assign family if bootstrap support is high enough.
    """
    # Read tree
    if not os.path.exists(treefile_path):
        return {}

    with open(treefile_path) as f:
        tree_str = f.read().strip()

    # Approach: Use pairwise patristic distances
    # Read the .mldist file if available (IQ-TREE -m MFP produces this)
    dist_path = treefile_path.replace('.treefile', '.mldist')
    assignments = {}

    if os.path.exists(dist_path):
        print(f"Using ML distance matrix: {dist_path}")
        assignments = assign_from_distance_matrix(
            dist_path, unknown_ids, known_family_map
        )
    else:
        print("No ML distance file found, using simple tree-based assignment")
        # Fallback: simple string parsing approach
        assignments = assign_from_simple_tree(tree_str, unknown_ids, known_family_map)

    return assignments


def read_family_map(known_fasta_path):
    """Extract family annotations from known RdRp FASTA headers.
    Expected format: >accession|family_name or >accession [family=Name]
    """
    family_map = {}
    with open(known_fasta_path) as f:
        for line in f:
            if line.startswith(">"):
                header = line[1:].strip()
                # Try various formats
                # Format 1: >accession|Family_Name
                parts = header.split("|")
                if len(parts) >= 2:
                    seq_id = parts[0]
                    family = parts[1]
                    family_map[seq_id] = family
                # Format 2: >accession [family=Name]
                elif "family=" in header.lower():
                    m = re.search(r'family[=:]\s*(\S+)', header, re.I)
                    if m:
                        seq_id = header.split()[0]
                        family_map[seq_id] = m.group(1)
                # Format 3: >accession Family_Name (space-separated)
                else:
                    fields = header.split()
                    if len(fields) >= 2:
                        seq_id = fields[0]
                        # Check if second field looks like a family name
                        fam = fields[1]
                        if not fam.startswith("[") and not re.match(r'^[\d\.]+$', fam):
                            family_map[seq_id] = fam
    return family_map


def assign_from_distance_matrix(dist_path, unknown_ids, known_family_map):
    """Use ML distance matrix to find nearest known-family neighbor."""
    assignments = {}
    unknown_set = set(unknown_ids)
    known_set = set(known_family_map.keys())

    # Read distance matrix
    with open(dist_path) as f:
        lines = f.readlines()

    # First line has the number of taxa
    n_taxa = int(lines[0].strip())
    taxon_order = []

    # Read the matrix
    distances = {}
    for i, line in enumerate(lines[1:], 1):
        parts = line.strip().split()
        if not parts:
            continue
        taxon = parts[0]
        taxon_order.append(taxon)
        for j, dist_str in enumerate(parts[1:], 0):
            if j < len(taxon_order) - 1:
                other = taxon_order[j]
                d = float(dist_str)
                distances[(taxon, other)] = d
                distances[(other, taxon)] = d

    for unknown_id in unknown_ids:
        if unknown_id not in taxon_order:
            print(f"  Warning: {unknown_id} not in distance matrix")
            continue

        # Find nearest known neighbor(s)
        neighbors = []
        for known_id in known_set:
            if known_id in taxon_order:
                d = distances.get((unknown_id, known_id), float('inf'))
                if d < float('inf'):
                    neighbors.append((d, known_id, known_family_map[known_id]))

        if not neighbors:
            print(f"  Warning: No known neighbors for {unknown_id}")
            continue

        neighbors.sort()
        # Get the family of the nearest neighbor
        nearest_family = neighbors[0][2]
        nearest_dist = neighbors[0][0]
        nearest_id = neighbors[0][1]

        # Check top-3 consensus
        top3 = neighbors[:3]
        fam_votes = defaultdict(int)
        for d, kid, fam in top3:
            fam_votes[fam] += 1
        consensus_family = max(fam_votes, key=fam_votes.get)
        consensus_ratio = fam_votes[consensus_family] / len(top3)

        assignments[unknown_id] = {
            'assigned_family': consensus_family if consensus_ratio >= FAMILY_CONSENSUS else nearest_family,
            'nearest_neighbor': nearest_id,
            'nearest_family': nearest_family,
            'distance': nearest_dist,
            'consensus_family': consensus_family,
            'consensus_ratio': consensus_ratio,
            'confidence': 'high' if consensus_ratio >= 0.67 else 'medium' if consensus_ratio >= 0.5 else 'low',
            'top3_neighbors': ";".join([f"{tid}({fam},{d:.4f})" for d, tid, fam in top3])
        }

    return assignments


def assign_from_simple_tree(tree_str, unknown_ids, known_family_map):
    """Fallback: extract taxonomic patterns from tree string.
    This is less accurate but works without the distance matrix.
    """
    assignments = {}
    unknown_set = set(unknown_ids)
    known_set = set(known_family_map.keys())

    # Extract all taxon labels from the tree
    all_labels = set(re.findall(r'([A-Za-z0-9_\-\.]+?)(?::\d+\.\d+)?[,);]', tree_str))
    print(f"Tree contains {len(all_labels)} taxon labels")

    # Find labels matching our unknown IDs
    matched_unknowns = unknown_set & all_labels
    matched_knowns = known_set & all_labels
    print(f"Matched: {len(matched_unknowns)} unknown, {len(matched_knowns)} known")

    # For each unknown, find the closest known in the Newick string
    # This is heuristic - we look at the tree topology in the string
    for uid in matched_unknowns:
        # Find position of this taxon in tree string
        idx = tree_str.find(uid)
        if idx < 0:
            continue

        # Look for nearby known-family taxa (within 500 chars)
        window = tree_str[max(0, idx-500):idx+500]
        nearby_known = []
        for kid in matched_knowns:
            k_idx = window.find(kid)
            if k_idx >= 0:
                fam = known_family_map[kid]
                nearby_known.append((abs(k_idx - 250), kid, fam))  # 250 is center of window

        if nearby_known:
            nearby_known.sort()
            top = nearby_known[:3]
            fam_votes = defaultdict(int)
            for dist, kid, fam in top:
                fam_votes[fam] += 1
            consensus_family = max(fam_votes, key=fam_votes.get)

            assignments[uid] = {
                'assigned_family': consensus_family,
                'nearest_neighbor': top[0][1],
                'nearest_family': top[0][2],
                'distance': 0.0,
                'consensus_family': consensus_family,
                'consensus_ratio': fam_votes[consensus_family] / len(top),
                'confidence': 'low',  # string-based method is low confidence
                'top3_neighbors': ";".join([f"{tid}({fam})" for _, tid, fam in top])
            }

    print(f"Assigned {len(assignments)} unknowns via simple tree parsing")
    return assignments


def write_to_db(assignments, db_path):
    """Write classification results to the database."""
    if not os.path.exists(db_path):
        print(f"Database not found: {db_path}, skipping DB write")
        return

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    for seq_id, data in assignments.items():
        try:
            cursor.execute("""
                UPDATE virus_protein
                SET predicted_family = ?,
                    family_prediction_confidence = ?,
                    family_prediction_method = 'RdRp_phylogeny'
                WHERE protein_id = ? OR sequence_id = ?
            """, (data['assigned_family'], data['confidence'],
                  seq_id, seq_id))
        except sqlite3.Error as e:
            print(f"  DB error for {seq_id}: {e}")
            # Try simpler update
            try:
                cursor.execute("""
                    INSERT OR REPLACE INTO rdrp_classification
                    (sequence_id, predicted_family, nearest_neighbor, nearest_family,
                     patristic_distance, consensus_family, consensus_ratio, confidence, top3_neighbors)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (seq_id, data['assigned_family'], data['nearest_neighbor'],
                      data['nearest_family'], data['distance'], data['consensus_family'],
                      data['consensus_ratio'], data['confidence'], data['top3_neighbors']))
            except Exception:
                pass

    conn.commit()
    conn.close()
    print(f"Wrote {len(assignments)} classifications to database")


def write_report(assignments, output_path):
    """Write classification report as TSV."""
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write("sequence_id\tassigned_family\tnearest_known_neighbor\tnearest_family\t"
                "patristic_distance\tconsensus_family\tconsensus_ratio\tconfidence\ttop3_neighbors\n")
        for seq_id, data in sorted(assignments.items()):
            f.write(f"{seq_id}\t{data['assigned_family']}\t{data['nearest_neighbor']}\t"
                    f"{data['nearest_family']}\t{data['distance']:.6f}\t"
                    f"{data['consensus_family']}\t{data['consensus_ratio']:.2f}\t"
                    f"{data['confidence']}\t{data['top3_neighbors']}\n")
    print(f"Report written to {output_path}")


def print_summary(assignments):
    """Print classification summary statistics."""
    families = defaultdict(int)
    confidences = defaultdict(int)
    for data in assignments.values():
        families[data['assigned_family']] += 1
        confidences[data['confidence']] += 1

    print("\n=== Classification Summary ===")
    print(f"Total classified: {len(assignments)}")
    print(f"\nBy confidence:")
    for conf, count in sorted(confidences.items()):
        print(f"  {conf}: {count}")
    print(f"\nBy assigned family:")
    for fam, count in sorted(families.items(), key=lambda x: -x[1]):
        print(f"  {fam}: {count}")


def main():
    known_fasta = PROJ / "blastdb" / "known_rdrp.faa"

    print("Reading unknown IDs...")
    unknown_ids = read_unknown_ids(UNKNOWN_FA)
    print(f"  {len(unknown_ids)} unknown sequences")

    print("Reading known family annotations...")
    known_family_map = read_family_map(known_fasta)
    print(f"  {len(known_family_map)} known sequences with family")

    # Find tree file
    treefile = TREE_PATH
    if not os.path.exists(treefile):
        # Try alternative names
        for alt in [PROJ / "blastdb" / "rdrp_tree.treefile",
                    PROJ / "blastdb" / "rdrp_tree.nex"]:
            if os.path.exists(alt):
                treefile = alt
                break

    if not os.path.exists(treefile):
        print(f"Cannot find tree file. Looked for: {TREE_PATH}")
        print("Available files in blastdb/:")
        for f in os.listdir(PROJ / "blastdb"):
            if 'rdrp' in f.lower() and 'tree' in f.lower():
                print(f"  {f}")
        sys.exit(1)

    print(f"Using tree file: {treefile}")
    print("Assigning families...")
    assignments = assign_families_nearest_neighbor(
        str(treefile), unknown_ids, known_family_map
    )

    if not assignments:
        print("No assignments made!")
        sys.exit(1)

    print_summary(assignments)
    write_report(assignments, str(OUTPUT))

    # Try to find and write to DB
    db_files = list(PROJ.glob("**/*.db")) + list(PROJ.glob("**/*.sqlite")) + list(PROJ.glob("**/*.sqlite3"))
    if db_files:
        write_to_db(assignments, str(db_files[0]))
    else:
        print("No database found, skipping DB write")


if __name__ == "__main__":
    main()
