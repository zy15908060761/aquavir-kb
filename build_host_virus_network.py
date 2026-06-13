#!/usr/bin/env python3
"""P3-8: Host-virus cross-phylum network analysis (read-only)."""
import sqlite3, csv
from collections import defaultdict
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent
DB = BASE / "crustacean_virus_core.db"
OUT = BASE / "reports"

def main():
    conn = sqlite3.connect(str(DB))
    conn.row_factory = sqlite3.Row
    OUT.mkdir(parents=True, exist_ok=True)

    # 1. Cross-phylum matrix
    print("[1/4] Building cross-phylum matrix...")
    rows = conn.execute("""
        SELECT v.virus_family, v.host_phylum, COUNT(DISTINCT v.master_id) as cnt
        FROM virus_master v
        WHERE v.entry_type != 'non_target'
          AND v.virus_family IS NOT NULL AND v.virus_family != ''
          AND v.host_phylum IS NOT NULL AND v.host_phylum != ''
        GROUP BY v.virus_family, v.host_phylum
        ORDER BY cnt DESC
    """).fetchall()

    # Build matrix
    phyla = sorted(set(r['host_phylum'] for r in rows))
    families = sorted(set(r['virus_family'] for r in rows))
    matrix = defaultdict(lambda: defaultdict(int))
    family_totals = defaultdict(int)
    for r in rows:
        matrix[r['virus_family']][r['host_phylum']] = r['cnt']
        family_totals[r['virus_family']] += r['cnt']

    # Write matrix CSV
    with open(OUT / "host_virus_matrix.csv", 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(['virus_family', 'total_viruses'] + phyla)
        for fam in sorted(families, key=lambda x: -family_totals[x]):
            row_data = [fam, family_totals[fam]]
            for ph in phyla:
                row_data.append(matrix[fam].get(ph, 0))
            w.writerow(row_data)
    print(f"  Matrix: {len(families)} families x {len(phyla)} phyla")
    print(f"  Saved: host_virus_matrix.csv")

    # 2. Cross-phylum jumpers
    print("[2/4] Detecting host-jump candidates...")
    cross_phylum = []
    for fam in families:
        phyla_infected = [ph for ph in phyla if matrix[fam].get(ph, 0) > 0]
        if len(phyla_infected) >= 2:
            total = family_totals[fam]
            cross_phylum.append((fam, len(phyla_infected), phyla_infected, total))

    cross_phylum.sort(key=lambda x: -x[1])

    with open(OUT / "host_jump_candidates.csv", 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(['virus_family', 'phyla_count', 'phyla', 'total_viruses'])
        for fam, n_phyla, phyla_list, total in cross_phylum:
            w.writerow([fam, n_phyla, '; '.join(phyla_list), total])

    print(f"  Cross-phylum families: {len(cross_phylum)}")
    for fam, n, phyla_list, total in cross_phylum[:10]:
        print(f"    {fam}: {n} phyla ({', '.join(phyla_list[:3])}) — {total} viruses")

    # 3. Hub analysis
    print("[3/4] Network topology...")
    # Specialist vs generalist
    host_count_per_virus = conn.execute("""
        SELECT v.master_id, COUNT(DISTINCT h.host_id) as host_count
        FROM virus_master v
        LEFT JOIN evidence_records e ON v.master_id = e.virus_master_id
        LEFT JOIN crustacean_hosts h ON e.host_id = h.host_id
        WHERE v.entry_type != 'non_target' AND h.host_id IS NOT NULL
        GROUP BY v.master_id
    """).fetchall()

    specialists = sum(1 for r in host_count_per_virus if r['host_count'] == 1)
    generalists = sum(1 for r in host_count_per_virus if r['host_count'] > 1)
    print(f"  Specialists (1 host): {specialists}")
    print(f"  Generalists (>1 host): {generalists}")

    # 4. Report
    print("[4/4] Generating report...")
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    with open(OUT / f"network_analysis_{ts}.md", 'w', encoding='utf-8') as f:
        f.write("# Host-Virus Network Analysis\n\n")
        f.write(f"Generated: {datetime.now()}\n\n")
        f.write(f"## Summary\n\n")
        f.write(f"- **Families analyzed**: {len(families)}\n")
        f.write(f"- **Host phyla analyzed**: {len(phyla)}\n")
        f.write(f"- **Cross-phylum families**: {len(cross_phylum)}\n")
        f.write(f"- **Specialists (1 host)**: {specialists}\n")
        f.write(f"- **Generalists (>1 host)**: {generalists}\n\n")
        f.write(f"## Top Cross-Phylum Families\n\n")
        f.write(f"| Family | Phyla | Viruses |\n")
        f.write(f"|--------|-------|--------|\n")
        for fam, n, phyla_list, total in cross_phylum[:15]:
            f.write(f"| {fam} | {n} | {total} |\n")
        f.write(f"\n## Host Phyla Distribution\n\n")
        for ph in phyla:
            total = sum(matrix[fam].get(ph, 0) for fam in families)
            f.write(f"- **{ph}**: {total} viruses\n")

    print(f"  Report saved: network_analysis_{ts}.md")
    print("\nDone.")
    conn.close()

if __name__ == "__main__":
    main()
