"""
Parse FastTree Newick output, classify unknown RdRp sequences.
Uses closest phylogenetic neighbor approach with SH-like support values.
"""
import re, sys, os
from pathlib import Path
from collections import defaultdict

PROJ = Path(r"F:\水生无脊椎动物数据库")
KNOWN_FA = PROJ / "blastdb" / "known_rdrp.faa"
UNKNOWN_FA = PROJ / "blastdb" / "unknown_rdrp.faa"
TREE_NWK = PROJ / "blastdb" / "rdrp_fasttree.nwk"
OUTPUT_TSV = PROJ / "blastdb" / "rdrp_classification.tsv"

# SH-like support thresholds
SUPPORT_HIGH = 0.70   # High confidence - direct assignment
SUPPORT_MEDIUM = 0.50 # Medium - needs IQ-TREE verification
# Below 0.50 = Low - manual review


def read_family_map(fasta_path):
    """Extract family from known RdRp headers: >accession|Family"""
    fam = {}
    with open(fasta_path) as f:
        for line in f:
            if line.startswith(">"):
                parts = line[1:].strip().split("|")
                if len(parts) >= 2:
                    fam[parts[0]] = parts[1]
    return fam


def read_unknown_ids(fasta_path):
    ids = []
    with open(fasta_path) as f:
        for line in f:
            if line.startswith(">"):
                ids.append(line[1:].strip().split("|")[0])
    return ids


def parse_fasttree_newick(tree_str):
    """
    Parse FastTree Newick tree into an adjacency structure.
    FastTree format: (A:0.1,(B:0.2,C:0.3)0.95:0.5);
    Internal nodes have optional support value before ':'.

    Returns:
      leaves: set of leaf names
      parent: dict child->parent node id
      children: dict parent->[children]
      support: dict node->SH support value
      branch_length: dict (child,parent)->length
    """
    # First, simplify the tree string for parsing
    # Replace all leaf names with unique tokens
    tree_str = tree_str.strip().rstrip(';')

    # Extract leaf names and support values
    # Pattern: (name):length or )support:length
    leaves = set()
    # Find all leaf names
    for m in re.finditer(r'([A-Za-z0-9_\-\.\|]+):(\d+\.?\d*(?:e[+-]?\d+)?)', tree_str):
        leaves.add(m.group(1))

    return leaves


class TreeNode:
    def __init__(self, name=None):
        self.name = name
        self.children = []
        self.support = None
        self.length = 0.0
        self.parent = None
        self.is_leaf = False
        self._descendants = set()


def _parse_newick_recursive(s, idx):
    """Recursive descent parser for Newick format. Returns (node, new_idx)."""
    s = s.strip()
    node = TreeNode()

    if idx >= len(s):
        return node, idx

    if s[idx] == '(':
        # Internal node
        idx += 1
        while True:
            child, idx = _parse_newick_recursive(s, idx)
            child.parent = node
            node.children.append(child)
            if idx >= len(s):
                break
            if s[idx] == ',':
                idx += 1
                continue
            elif s[idx] == ')':
                idx += 1
                break

        # Optional support value after ')'
        m = re.match(r'(\d+\.?\d*(?:e[+-]?\d+)?)', s[idx:])
        if m:
            node.support = float(m.group(1))
            idx += len(m.group(1))

        # Optional branch length
        if idx < len(s) and s[idx] == ':':
            idx += 1
            m = re.match(r'(\d+\.?\d*(?:e[+-]?\d+)?)', s[idx:])
            if m:
                node.length = float(m.group(1))
                idx += len(m.group(1))
    else:
        # Leaf node
        node.is_leaf = True
        m = re.match(r'([^,:;()]+)', s[idx:])
        if m:
            node.name = m.group(1).strip()
            idx += len(m.group(1))

        # Optional branch length
        if idx < len(s) and s[idx] == ':':
            idx += 1
            m = re.match(r'(\d+\.?\d*(?:e[+-]?\d+)?)', s[idx:])
            if m:
                node.length = float(m.group(1))
                idx += len(m.group(1))

    return node, idx


def parse_newick_robust(tree_str):
    """Parse Newick tree string, returns root TreeNode."""
    tree_str = tree_str.strip().rstrip(';')
    root, _ = _parse_newick_recursive(tree_str, 0)
    # Root has one child - the actual tree
    if root.children and not root.is_leaf:
        return root
    return root


def compute_node_annotations(root):
    """
    Post-order traversal: annotate each node with its leaf descendants.
    """
    def _traverse(node):
        if node.is_leaf:
            node._descendants = {node.name}
        else:
            node._descendants = set()
            for child in node.children:
                _traverse(child)
                node._descendants |= child._descendants
    _traverse(root)


def compute_unknown_to_nearest_known(root, known_families, unknown_ids):
    """
    For each unknown leaf, find the nearest ancestral clade that contains known-family sequences.
    Classify based on the family distribution in that clade.
    """
    compute_node_annotations(root)
    unknown_set = set(unknown_ids)

    # First pass: find all leaves in the tree
    all_leaves = []
    def _collect_leaves(node):
        if node.is_leaf:
            all_leaves.append(node.name)
        for child in node.children:
            _collect_leaves(child)
    _collect_leaves(root)

    # Map leaf name to tree node (by short accession ID)
    leaf_nodes = {}
    def _map_leaves(node):
        if node.is_leaf:
            short_name = node.name.split('|')[0]
            leaf_nodes[short_name] = node
            leaf_nodes[node.name] = node  # also by full name
        for child in node.children:
            _map_leaves(child)
    _map_leaves(root)

    print(f"Tree has {len(all_leaves)} leaves, {len(leaf_nodes)} mapped")

    assignments = {}

    for uid in unknown_ids:
        if uid not in leaf_nodes:
            # Try to find partial match
            matched = [n for n in leaf_nodes if uid in n or n in uid]
            if matched:
                print(f"  Partial match for {uid}: {matched[:3]}")
                leaf = leaf_nodes[matched[0]]
            else:
                print(f"  Unknown {uid} not found in tree")
                continue
        else:
            leaf = leaf_nodes[uid]

        # Walk up from leaf to find the first ancestor with known clade
        node = leaf.parent
        best_result = None

        while node is not None:
            # Check which known families are under this node
            # Match by short ID (accession) against known_families
            known_descendents = []
            for desc_name in node._descendants:
                short = desc_name.split('|')[0]
                if short in known_families:
                    known_descendents.append(short)
                elif desc_name in known_families:
                    known_descendents.append(desc_name)

            if known_descendents:
                # Found an ancestral clade with known-family sequences
                # Count families
                fam_counts = defaultdict(int)
                for kd in known_descendents:
                    fam = known_families[kd]
                    fam_counts[fam] += 1

                # Majority family
                total = sum(fam_counts.values())
                sorted_fams = sorted(fam_counts.items(), key=lambda x: -x[1])
                top_fam = sorted_fams[0][0]
                top_ratio = sorted_fams[0][1] / total if total > 0 else 0
                support = node.support if node.support is not None else 0.0

                if top_ratio >= 0.5:  # Family consensus in this clade
                    confidence = 'high' if support >= SUPPORT_HIGH else \
                                 'medium' if support >= SUPPORT_MEDIUM else 'low'
                    best_result = {
                        'assigned_family': top_fam,
                        'support': support,
                        'consensus_ratio': top_ratio,
                        'num_known_in_clade': total,
                        'family_distribution': dict(sorted_fams),
                        'confidence': confidence,
                        'clade_size': len(node._descendants)
                    }
                    break  # Stop at first ancestral clade with known-family members

            node = node.parent

        if best_result:
            assignments[uid] = best_result
        else:
            print(f"  No known-family clade found for {uid}")

    return assignments


def main():
    print("Reading known family annotations...")
    known_families = read_family_map(KNOWN_FA)
    print(f"  {len(known_families)} known sequences with family labels")

    print("Reading unknown IDs...")
    unknown_ids = read_unknown_ids(UNKNOWN_FA)
    print(f"  {len(unknown_ids)} unknown sequences to classify")

    if not os.path.exists(TREE_NWK):
        print(f"Tree file not found: {TREE_NWK}")
        sys.exit(1)

    with open(TREE_NWK) as f:
        tree_str = f.read().strip()

    print(f"Tree string length: {len(tree_str)}")
    print("Parsing tree...")
    root = parse_newick_robust(tree_str)
    print(f"Tree parsed: root has {len(root.children)} children")

    print("Classifying unknown sequences...")
    assignments = compute_unknown_to_nearest_known(root, known_families, unknown_ids)

    print_summary(assignments)
    write_report(assignments)
    write_db(assignments)


def print_summary(assignments):
    print("\n" + "="*60)
    print(f"Classification Results: {len(assignments)} sequences classified")
    families = defaultdict(int)
    confidences = defaultdict(int)
    for uid, data in assignments.items():
        families[data['assigned_family']] += 1
        confidences[data['confidence']] += 1

    print(f"\nConfidence distribution:")
    for conf in ['high', 'medium', 'low']:
        print(f"  {conf}: {confidences.get(conf, 0)}")

    print(f"\nFamily assignments:")
    for fam, count in sorted(families.items(), key=lambda x: -x[1]):
        print(f"  {fam}: {count}")


def write_report(assignments):
    with open(OUTPUT_TSV, 'w', encoding='utf-8') as f:
        f.write("sequence_id\tassigned_family\tsh_support\tclade_consensus_ratio\t"
                "num_known_in_clade\tclade_size\tconfidence\tfamily_distribution\n")
        for uid, data in sorted(assignments.items()):
            fam_dist = ";".join([f"{fam}:{cnt}" for fam, cnt in data['family_distribution'].items()])
            f.write(f"{uid}\t{data['assigned_family']}\t{data['support']:.4f}\t"
                    f"{data['consensus_ratio']:.3f}\t{data['num_known_in_clade']}\t"
                    f"{data['clade_size']}\t{data['confidence']}\t{fam_dist}\n")
    print(f"\nReport saved to: {OUTPUT_TSV}")


def write_db(assignments):
    """Write to database; create table if needed."""
    import sqlite3
    db_files = list(PROJ.glob("**/*.sqlite3")) + list(PROJ.glob("**/*.db")) + list(PROJ.glob("**/*.sqlite"))
    if not db_files:
        print("No database found, skipping DB write")
        return

    db_path = str(db_files[0])
    print(f"Writing to database: {db_path}")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Ensure table exists
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS rdrp_classification (
            sequence_id TEXT PRIMARY KEY,
            predicted_family TEXT,
            sh_support REAL,
            consensus_ratio REAL,
            num_known_in_clade INTEGER,
            clade_size INTEGER,
            confidence TEXT,
            family_distribution TEXT,
            method TEXT DEFAULT 'FastTree_phylogeny',
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    for uid, data in assignments.items():
        cursor.execute("""
            INSERT OR REPLACE INTO rdrp_classification
            (sequence_id, predicted_family, sh_support, consensus_ratio,
             num_known_in_clade, clade_size, confidence, family_distribution)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (uid, data['assigned_family'], data['support'], data['consensus_ratio'],
              data['num_known_in_clade'], data['clade_size'], data['confidence'],
              ";".join([f"{fam}:{cnt}" for fam, cnt in data['family_distribution'].items()])))

    conn.commit()
    conn.close()
    print(f"  Wrote {len(assignments)} records to rdrp_classification table")


if __name__ == "__main__":
    main()
