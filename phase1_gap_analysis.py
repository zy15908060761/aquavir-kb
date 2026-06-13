"""
Phase 1: Gap analysis for crustacean virus database expansion.
Identifies missing crustacean orders, virus families, and host taxa.
"""
import sqlite3
import json
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "crustacean_virus_core.db"

# All known crustacean orders (from WoRMS / NCBI Taxonomy)
ALL_CRUSTACEAN_ORDERS = {
    "Decapoda", "Isopoda", "Amphipoda", "Copepoda", "Cirripedia",
    "Ostracoda", "Branchiopoda", "Stomatopoda", "Euphausiacea",
    "Mysida", "Lophogastrida", "Tanaidacea", "Cumacea",
    "Leptostraca", "Anaspidacea", "Bathynellacea", "Thermosbaenacea",
    "Mictacea", "Spelaeogriphacea", "Bochusacea", "Mystacocarida",
    "Branchiura", "Pentastomida", "Notostraca", "Anostraca",
    "Cladocera", "Cyclopoida", "Calanoida", "Harpacticoida",
    "Sessilia", "Scalpellomorpha", "Verrucomorpha", "Podocopida",
    "Myodocopida", "Platycopida", "Palaeocopida", "Gymnolaemata",
}

# Major DNA virus families known to infect crustaceans
KNOWN_CRUSTACEAN_DNA_VIRUSES = {
    "Nimaviridae", "Malacoherpesviridae", "Iridoviridae",
    "Parvoviridae", "Circoviridae", "Baculoviridae",
    "Nudiviridae", "Polydnaviridae", "Adenoviridae",
    "Poxviridae", "Marseilleviridae", "Mimiviridae",
}

def main():
    conn = sqlite3.connect(str(DB_PATH))
    c = conn.cursor()

    report = {
        "current_state": {},
        "gaps": {},
        "recommendations": [],
    }

    # 1. Current virus stats
    c.execute("SELECT COUNT(*) FROM virus_master")
    report["current_state"]["virus_master_total"] = c.fetchone()[0]

    c.execute("SELECT COUNT(*) FROM viral_isolates")
    report["current_state"]["viral_isolates_total"] = c.fetchone()[0]

    c.execute("SELECT COUNT(*) FROM crustacean_hosts WHERE host_type = 'crustacean'")
    report["current_state"]["crustacean_hosts"] = c.fetchone()[0]

    # 2. Virus families present
    c.execute("""SELECT DISTINCT virus_family FROM virus_master
                 WHERE virus_family IS NOT NULL AND virus_family != ''""")
    present_families = {row[0] for row in c.fetchall()}
    report["current_state"]["virus_families_present"] = sorted(present_families)
    report["current_state"]["virus_families_count"] = len(present_families)

    # 3. Host orders present
    c.execute("""SELECT DISTINCT taxon_order FROM crustacean_hosts
                 WHERE taxon_order IS NOT NULL AND taxon_order != ''""")
    present_orders = {row[0] for row in c.fetchall()}
    report["current_state"]["host_orders_present"] = sorted(present_orders)
    report["gaps"]["missing_crustacean_orders"] = sorted(
        ALL_CRUSTACEAN_ORDERS - present_orders
    )
    report["gaps"]["missing_orders_count"] = len(
        ALL_CRUSTACEAN_ORDERS - present_orders
    )

    # 4. Missing DNA virus families
    missing_dna = KNOWN_CRUSTACEAN_DNA_VIRUSES - present_families
    report["gaps"]["missing_dna_virus_families"] = sorted(missing_dna)

    # 5. Host breakdown by order
    c.execute("""SELECT taxon_order, COUNT(*) as cnt,
                 GROUP_CONCAT(DISTINCT host_group) as groups
                 FROM crustacean_hosts
                 WHERE taxon_order IS NOT NULL AND taxon_order != ''
                 GROUP BY taxon_order ORDER BY cnt DESC""")
    report["current_state"]["host_order_breakdown"] = [
        {"order": row[0], "count": row[1], "groups": row[2]} for row in c.fetchall()
    ]

    # 6. Virus family with isolate counts
    c.execute("""SELECT vm.virus_family, COUNT(DISTINCT vm.master_id) as masters,
                 COUNT(DISTINCT vi.isolate_id) as isolates
                 FROM virus_master vm
                 LEFT JOIN viral_isolates vi ON vm.master_id = vi.master_id
                 WHERE vm.virus_family IS NOT NULL AND vm.virus_family != ''
                 GROUP BY vm.virus_family ORDER BY isolates DESC""")
    report["current_state"]["family_isolate_counts"] = [
        {"family": row[0], "masters": row[1], "isolates": row[2]}
        for row in c.fetchall()
    ]

    # 7. Existing GenBank accessions (for dedup)
    c.execute("SELECT COUNT(DISTINCT accession) FROM viral_isolates")
    report["current_state"]["unique_accessions"] = c.fetchone()[0]

    c.execute("SELECT accession FROM viral_isolates")
    report["existing_accessions"] = [row[0] for row in c.fetchall()]

    # 8. Recommendations
    report["recommendations"] = [
        {
            "priority": "critical",
            "action": "Search SRA/GenBank for virus sequences from missing orders",
            "targets": list(report["gaps"]["missing_crustacean_orders"])[:10],
            "rationale": f"{report['gaps']['missing_orders_count']} crustacean orders have zero coverage"
        },
        {
            "priority": "high",
            "action": "Search for DNA virus families not yet in database",
            "targets": list(missing_dna),
            "rationale": "Database is heavily biased toward RNA viruses (91% ssRNA+)"
        },
        {
            "priority": "high",
            "action": "Expand beyond Decapoda",
            "targets": ["Copepoda", "Amphipoda", "Ostracoda", "Isopoda", "Euphausiacea"],
            "rationale": "Only Decapoda is well-represented; these 5 orders contain >50,000 species"
        },
        {
            "priority": "medium",
            "action": "Search published virome studies for SRA accessions",
            "targets": ["shrimp virome", "crab virome", "copepod virome", "krill virome"],
            "rationale": "Many published viromes have SRA data but sequences not in GenBank Nucleotide"
        },
    ]

    conn.close()

    # Write report
    out_path = Path(__file__).resolve().parent / "gap_analysis_report.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    # Print summary
    print("=" * 60)
    print("GAP ANALYSIS SUMMARY")
    print("=" * 60)
    print(f"Virus master records:     {report['current_state']['virus_master_total']}")
    print(f"Viral isolates:           {report['current_state']['viral_isolates_total']}")
    print(f"Crustacean host species:  {report['current_state']['crustacean_hosts']}")
    print(f"Virus families present:   {report['current_state']['virus_families_count']}")
    print(f"Host orders present:      {len(present_orders)}")
    print(f"Host orders MISSING:      {report['gaps']['missing_orders_count']}")
    print()
    print("Present host orders:")
    for entry in report["current_state"]["host_order_breakdown"]:
        print(f"  {entry['order']}: {entry['count']} species ({entry['groups']})")
    print()
    print(f"Missing crustacean orders (top 15):")
    for order in report["gaps"]["missing_crustacean_orders"][:15]:
        print(f"  - {order}")
    print()
    print(f"Missing DNA virus families:")
    for fam in missing_dna:
        print(f"  - {fam}")
    print()
    print(f"Unique GenBank accessions already imported: {report['current_state']['unique_accessions']}")
    print(f"\nFull report written to: {out_path}")

if __name__ == "__main__":
    main()
