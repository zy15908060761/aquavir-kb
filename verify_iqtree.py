"""
Extract subsets from full MAFFT alignment, trim gap-only columns,
run IQ-TREE bootstrap, compare with FastTree SH values.
"""
import subprocess, sys, os, re, csv
from pathlib import Path
from collections import defaultdict

PROJ = Path(r"F:\水生无脊椎动物数据库")
ALIGNMENT = PROJ / "blastdb" / "all_rdrp_aligned.faa"
CLASS_TSV = PROJ / "blastdb" / "rdrp_classification.tsv"
KNOWN_FA = PROJ / "blastdb" / "known_rdrp.faa"
IQTREE = r"F:\iqtree\iqtree-2.4.0-Windows\bin\iqtree2.exe"
OUTDIR = PROJ / "blastdb" / "iqtree_verify"


def read_alignment():
    """Read MAFFT alignment -> {short_id: sequence}"""
    seqs = {}
    order = []
    cur_id = None
    cur_seq = []
    with open(ALIGNMENT) as f:
        for line in f:
            line = line.strip()
            if line.startswith('>'):
                if cur_id:
                    seqs[cur_id] = ''.join(cur_seq)
                    order.append(cur_id)
                cur_id = line[1:].split('|')[0]
                cur_seq = []
            elif cur_id:
                cur_seq.append(line)
        if cur_id:
            seqs[cur_id] = ''.join(cur_seq)
            order.append(cur_id)
    return seqs, order


def read_known_families():
    fam = {}
    with open(KNOWN_FA) as f:
        for line in f:
            if line.startswith('>'):
                p = line[1:].strip().split('|')
                if len(p) >= 2:
                    fam[p[0]] = p[1]
    return fam


def read_classifications():
    results = {}
    with open(CLASS_TSV, encoding='utf-8') as f:
        for row in csv.DictReader(f, delimiter='\t'):
            results[row['sequence_id']] = row
    return results


def extract_subset_alignment(seqs, target_ids, known_fam, max_neighbors=15):
    """
    Build subset: targets + known sequences from same families + diverse other families.
    Returns (written_file_path, list_of_ids) or (None, None).
    """
    subset = set(target_ids)

    # Get target families
    cls = read_classifications()
    target_fams = set()
    for tid in target_ids:
        if tid in cls:
            target_fams.add(cls[tid]['assigned_family'])

    print(f"  Target families: {target_fams}")

    # Add known sequences from same families
    for fid, fam in known_fam.items():
        if fam in target_fams and fid not in subset and fid in seqs:
            subset.add(fid)

    # For Unclassified or small groups, add diverse known families as outgroups
    if 'Unclassified' in target_fams or len(subset) < 20:
        added_fams = set(target_fams)
        for fid, fam in known_fam.items():
            if fam not in added_fams and fid not in subset and fid in seqs:
                subset.add(fid)
                added_fams.add(fam)
                if len(added_fams) >= len(target_fams) + 5:
                    break

    # Get alignment order
    ids_in_order = [sid for sid in seqs if sid in subset]
    if len(ids_in_order) < 4:
        print(f"  Too few sequences: {len(ids_in_order)}")
        return None, None

    # Find non-gap columns
    aln_len = len(seqs[ids_in_order[0]])
    keep = []
    for j in range(aln_len):
        if any(seqs[sid][j] != '-' for sid in ids_in_order):
            keep.append(j)

    print(f"  {len(ids_in_order)} seqs, {len(keep)}/{aln_len} cols ({100*len(keep)//aln_len}%)")

    # Write
    out = OUTDIR / f"subset_{len(subset)}.faa"
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, 'w') as f:
        for sid in ids_in_order:
            trimmed = ''.join(seqs[sid][j] for j in keep)
            f.write(f'>{sid}\n{trimmed}\n')

    return str(out), ids_in_order


def parse_iqtree_bootstrap(treefile):
    """
    Parse IQ-TREE .treefile Newick, extract bootstrap values.
    Returns {short_id: {'bootstrap': float, 'clade_size': int}}
    """
    if not treefile or not os.path.exists(treefile):
        return {}

    with open(treefile) as f:
        s = f.read().strip()

    # Find all bootstrap values: )<number>:
    # And map them to the taxa they contain

    # Simpler approach: find each taxon, trace to nearest supported ancestor
    bootstrap = {}

    # For each taxon, find the nearest enclosing )<num>: or )<num>,
    for m in re.finditer(r'\)(\d+\.?\d*)(?::\d+\.\d+)?[,)]', s):
        pass  # We need a tree parser for proper mapping

    # Use simple recursive parser
    class Node:
        __slots__ = ('children', 'name', 'is_leaf', 'support', 'length', 'parent', '_descendants')
        def __init__(self):
            self.children = []
            self.name = None
            self.is_leaf = False
            self.support = None
            self.length = 0.0
            self.parent = None
            self._descendants = set()

    def parse(s, idx):
        node = Node()
        if idx >= len(s):
            return node, idx
        if s[idx] == '(':
            idx += 1
            while True:
                child, idx = parse(s, idx)
                child.parent = node
                node.children.append(child)
                if idx >= len(s): break
                if s[idx] == ',':
                    idx += 1; continue
                elif s[idx] == ')':
                    idx += 1; break
            # Support value
            m = re.match(r'(\d+\.?\d*(?:e[+-]?\d+)?)', s[idx:])
            if m:
                # IQ-TREE ultrafast bootstrap: values 0-100
                val = float(m.group(1))
                if val > 1:  # percentage
                    val = val / 100.0
                node.support = val
                idx += len(m.group(1))
            # Branch length
            if idx < len(s) and s[idx] == ':':
                idx += 1
                m = re.match(r'(\d+\.?\d*(?:e[+-]?\d+)?)', s[idx:])
                if m:
                    node.length = float(m.group(1))
                    idx += len(m.group(1))
        else:
            node.is_leaf = True
            m = re.match(r'([^,:;()]+)', s[idx:])
            if m:
                node.name = m.group(1).strip()
                idx += len(m.group(1))
            if idx < len(s) and s[idx] == ':':
                idx += 1
                m = re.match(r'(\d+\.?\d*(?:e[+-]?\d+)?)', s[idx:])
                if m:
                    node.length = float(m.group(1))
                    idx += len(m.group(1))
        return node, idx

    def annotate(node):
        if node.is_leaf:
            node._descendants = {node.name.split('|')[0]}
        else:
            node._descendants = set()
            for c in node.children:
                annotate(c)
                node._descendants |= c._descendants

    root, _ = parse(s, 0)
    annotate(root)

    # For each leaf, find first ancestor with support
    def collect(node, results):
        if node.is_leaf:
            short = node.name.split('|')[0]
            n = node.parent
            while n:
                if n.support is not None:
                    results[short] = {
                        'bootstrap': n.support,
                        'clade_size': len(n._descendants)
                    }
                    break
                n = n.parent
        for c in node.children:
            collect(c, results)

    results = {}
    collect(root, results)
    return results


def run_iqtree(aln_file, prefix_base):
    """Run IQ-TREE, return path to .treefile or None."""
    prefix = str(OUTDIR / prefix_base)
    cmd = [IQTREE, '-s', aln_file, '-m', 'LG+F+G', '-B', '1000', '-T', '2', '--prefix', prefix]
    print(f"  IQ-TREE: {' '.join(cmd[-6:])}")
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=7200, cwd=str(OUTDIR))
        if r.returncode != 0:
            err = r.stderr[-300:] if r.stderr else ''
            out = r.stdout[-300:] if r.stdout else ''
            print(f"  FAILED: {err}\n  stdout: {out}")
            return None
        tf = prefix + '.treefile'
        if os.path.exists(tf):
            return tf
        # Check for alternative output names
        for alt in [prefix + '.contree', prefix + '.nex']:
            if os.path.exists(alt):
                return alt
        return None
    except subprocess.TimeoutExpired:
        print("  TIMEOUT")
        return None


def main():
    classifications = read_classifications()
    known_fam = read_known_families()
    seqs, order = read_alignment()
    print(f"Alignment: {len(seqs)} seqs, {len(seqs[order[0]])} cols")

    # Identify verification groups
    groups = defaultdict(list)
    for sid, info in classifications.items():
        if info['confidence'] == 'high':
            continue
        groups[info['assigned_family']].append(sid)

    print(f"\nVerification groups: {len(groups)}")
    for fam, ids in sorted(groups.items(), key=lambda x: -len(x[1])):
        print(f"  {fam}: {len(ids)} seqs")

    OUTDIR.mkdir(parents=True, exist_ok=True)

    all_comparisons = {}

    for fam, ids in sorted(groups.items(), key=lambda x: -len(x[1])):
        print(f"\n{'='*50}")
        print(f"Group: {fam} ({len(ids)} targets)")
        print(f"{'='*50}")

        # Prepare subset alignment
        aln_path, sub_ids = extract_subset_alignment(seqs, ids, known_fam)
        if not aln_path:
            continue

        # Run IQ-TREE
        safe = re.sub(r'[^a-zA-Z0-9]', '_', fam)
        treefile = run_iqtree(aln_path, f"verify_{safe}")

        if treefile:
            iq_results = parse_iqtree_bootstrap(treefile)
            print(f"  IQ-TREE results: {len(iq_results)} leaves with bootstrap")

            # Compare
            for uid in ids:
                ft = classifications.get(uid, {})
                ft_sh = ft.get('sh_support', '?')
                iq = iq_results.get(uid, {})
                iq_bs = iq.get('bootstrap', '?')
                if isinstance(iq_bs, float):
                    iq_bs = f"{iq_bs:.3f}"
                print(f"    {uid}: FastTree SH={ft_sh}, IQ-TREE BS={iq_bs}")
                all_comparisons[uid] = {
                    'family': fam,
                    'fasttree_sh': ft_sh,
                    'iqtree_bs': iq_bs,
                    'fasttree_conf': ft.get('confidence', '?')
                }
        else:
            print(f"  IQ-TREE failed for {fam}")

    # Summary
    print(f"\n{'='*60}")
    print(f"VERIFICATION SUMMARY")
    print(f"{'='*60}")
    for uid, comp in sorted(all_comparisons.items()):
        print(f"  {uid}: {comp['family']} FT_SH={comp['fasttree_sh']} IQ_BS={comp['iqtree_bs']}")

    # Save comparison
    comp_file = OUTDIR / "fasttree_vs_iqtree.tsv"
    with open(comp_file, 'w', encoding='utf-8') as f:
        f.write("sequence_id\tfamily\tfasttree_sh\tiqtree_bootstrap\tfasttree_confidence\n")
        for uid, comp in sorted(all_comparisons.items()):
            f.write(f"{uid}\t{comp['family']}\t{comp['fasttree_sh']}\t{comp['iqtree_bs']}\t{comp['fasttree_conf']}\n")
    print(f"\nComparison saved: {comp_file}")


if __name__ == '__main__':
    main()
