"""
Fill IUCN Red List status and standardize host entries for crustacean virus database.

Approach:
1. Manual mapping for well-known species (avoids IUCN API token requirement)
2. Mark non-crustacean hosts
3. Mark non-species-level entries
4. Generate a report of gaps for future manual curation.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

DB_PATH = Path(r"F:\甲壳动物数据库\crustacean_virus_core.db")

# Manual IUCN mapping for known crustacean hosts
# Sources: IUCN Red List assessments, FAO, general biodiversity knowledge
IUCN_MAPPING: dict[str, str] = {
    # --- Penaeid shrimp ---
    "Litopenaeus vannamei": "Not Evaluated",
    "Penaeus vannamei": "Not Evaluated",
    "L.vannamei": "Not Evaluated",
    "Penaeus (Litopenaeus) vannamei": "Not Evaluated",
    "Litopenaeus stylirostris": "Not Evaluated",
    "Penaeus stylirostris": "Not Evaluated",
    "Penaeus monodon": "Not Evaluated",
    "Penaeus monodon (black tiger shrimp)": "Not Evaluated",
    "Penaeus monodon (shrimp)": "Not Evaluated",
    "Penaeus monodon (tiger shrimp)": "Not Evaluated",
    "black tiger shrimp": "Not Evaluated",
    "tiger shrimp": "Not Evaluated",
    "Fenneropenaeus chinensis": "Data Deficient",
    "Penaeus chinensis": "Data Deficient",
    "Marsupenaeus japonicus": "Not Evaluated",
    "Penaeus japonicus": "Not Evaluated",
    "Penaeus (Marsupenaeus) japonicus Bate": "Not Evaluated",
    "Penaeus indicus": "Not Evaluated",
    "Fenneropenaeus indicus": "Not Evaluated",
    "penaeus indicus (shrimp)": "Not Evaluated",
    "fenneropenaeus indicus": "Not Evaluated",
    "Penaeus merguiensis": "Not Evaluated",
    "Penaeus semisulcatus": "Not Evaluated",
    "Penaeus setiferus": "Not Evaluated",
    "Farfantepenaeus duorarum": "Not Evaluated",
    "Farfantepenaeus californiensis": "Not Evaluated",
    "Metapenaeus ensis": "Not Evaluated",
    "Metapenaeus affinis": "Not Evaluated",
    "Metapenaeus monoceros": "Not Evaluated",
    "Trachypenaeus curvirostris": "Not Evaluated",
    "Trachysalambria curvirostris": "Not Evaluated",
    "Metapenaeopsis lamellata": "Not Evaluated",
    "Acetes chinensis": "Not Evaluated",
    # --- Prawns / other decapods ---
    "Macrobrachium rosenbergii": "Not Evaluated",
    "Macrobrachium rosenbergii (giant freshwater prawn)": "Not Evaluated",
    "Macrobrachium rosenbergii de Man": "Not Evaluated",
    "Macrobracium rosenbergii": "Not Evaluated",
    "Macrobrachium nipponense": "Not Evaluated",
    "Exopalaemon orientis": "Not Evaluated",
    "Palaemon gravieri": "Not Evaluated",
    "Palaemonetes intermedius": "Not Evaluated",
    "Palaemonetes kadiakensis": "Not Evaluated",
    "Alpheus distinguendus": "Not Evaluated",
    "Octolasmis neptuni": "Not Evaluated",
    # --- Crabs ---
    "Eriocheir sinensis": "Least Concern",
    "Erocheir sinensis": "Least Concern",
    "Procambarus clarkii": "Least Concern",
    "Procambarus alleni": "Not Evaluated",
    "Carcinus maenas": "Least Concern",
    "Scylla serrata": "Least Concern",
    "Callinectes sapidus": "Least Concern",
    "Callinectes arcuatus": "Not Evaluated",
    "Callinectes ornatus": "Not Evaluated",
    "Charybdis japonica": "Not Evaluated",
    "Chasmagnathus granulata": "Not Evaluated",
    "Orisarma dehaani": "Not Evaluated",
    "Goniopsis cruentata": "Not Evaluated",
    "Petrochirus diogenes": "Not Evaluated",
    # --- Lobsters / Crayfish ---
    "Homarus americanus": "Least Concern",
    "Cherax quadricarinatus": "Not Evaluated",
    "signal crayfish": "Not Evaluated",  # Pacifastacus leniusculus
    # --- Spiny lobsters ---
    "Panulirus homarus": "Not Evaluated",
    "Panulirus homarus (spiny lobster)": "Not Evaluated",
    "Panulirus ornatus": "Not Evaluated",
    "Panulirus echinatus": "Not Evaluated",
    # --- Artemia / brine shrimp ---
    "Artemia salina": "Least Concern",
    "Artemia sinica": "Not Evaluated",
    "Artemia tibetiana": "Not Evaluated",
    "Artemia parthenogenetic lineage": "Not Evaluated",
    # --- Other crustaceans ---
    "Euphausia superba": "Least Concern",
    "Capitulum mitella": "Not Evaluated",
    "Crangon sp.": "Not Evaluated",
    # --- Non-crustacean (but in DB) ---
    "Acanthaster planci": "Not Evaluated",  # Crown-of-thorns starfish (echinoderm)
    "Margaritifera falcata": "Least Concern",  # Freshwater mussel
}

# Hosts that are explicitly NOT crustaceans (contamination/broad sampling)
NON_CRUSTACEAN: set[str] = {
    "E. coli",
    "E.coli DH5 alpha",
    "E.coli SOLR strain",
    "DH10B E.coli",
    "DH10B cells",
    "GH K12",
    "Gallus gallus",
    "Oreochromis sp.",
    "Gerres cinereus",
    "Lile stolifera",
    "Bivalva",
    "Bellamya sp.",
    "insects",
    "small fish",
    "tadpole",
    "water boatman",
    "water strider",
    "plankton",
    "horseshoe crab",
}

# Entries that are not species-level (genera, higher taxa, common names without sci name)
NOT_SPECIES_LEVEL: set[str] = {
    "Crustacea",
    "Astacidea",
    "Brachyura",
    "Penaeus spp.",
    "Penaeid shrimp",
    "Litopenaeus sp.",
    "Macrobrachium sp.",
    "Palaemonetes sp.",
    "Artemia sp.",
    "Scylla sp.",
    "Scylla sp. (crab)",
    "Charybdis crab",
    "Mantis shrimp",
    "freshwater atyid shrimp",
    "fiddler Crab",
    "fiddler crab",
    "hermit crab",
    "hermit crab mix Beihai",
    "blue swimmer crab",
    "shrimp",
    "shrimps",
    "penaeid shrimp",
    "crayfish",
    "crab",
    "crustacean",
    "crustaceans",
    "crustacean mix",
}

# Aquaculture status mapping for major species
AQUACULTURE_STATUS: dict[str, str] = {
    "Litopenaeus vannamei": "major_aquaculture",
    "Penaeus vannamei": "major_aquaculture",
    "L.vannamei": "major_aquaculture",
    "Penaeus (Litopenaeus) vannamei": "major_aquaculture",
    "Penaeus monodon": "major_aquaculture",
    "Penaeus monodon (black tiger shrimp)": "major_aquaculture",
    "Penaeus monodon (shrimp)": "major_aquaculture",
    "Penaeus monodon (tiger shrimp)": "major_aquaculture",
    "black tiger shrimp": "major_aquaculture",
    "tiger shrimp": "major_aquaculture",
    "Fenneropenaeus chinensis": "major_aquaculture",
    "Penaeus chinensis": "major_aquaculture",
    "Marsupenaeus japonicus": "major_aquaculture",
    "Penaeus japonicus": "major_aquaculture",
    "Penaeus (Marsupenaeus) japonicus Bate": "major_aquaculture",
    "Litopenaeus stylirostris": "minor_aquaculture",
    "Penaeus stylirostris": "minor_aquaculture",
    "Macrobrachium rosenbergii": "major_aquaculture",
    "Macrobrachium rosenbergii (giant freshwater prawn)": "major_aquaculture",
    "Macrobrachium rosenbergii de Man": "major_aquaculture",
    "Macrobracium rosenbergii": "major_aquaculture",
    "Macrobrachium nipponense": "minor_aquaculture",
    "Eriocheir sinensis": "major_aquaculture",
    "Erocheir sinensis": "major_aquaculture",
    "Procambarus clarkii": "major_aquaculture",
    "Scylla serrata": "major_aquaculture",
    "Callinectes sapidus": "wild_fishery",
    "Homarus americanus": "wild_fishery",
    "Cherax quadricarinatus": "minor_aquaculture",
    "Panulirus ornatus": "wild_fishery",
    "Panulirus homarus": "wild_fishery",
    "Artemia salina": "hatchery_feed",
    "Artemia sp.": "hatchery_feed",
    "Acetes chinensis": "wild_fishery",
    "Euphausia superba": "wild_fishery",
}


def add_host_columns(conn: sqlite3.Connection) -> None:
    c = conn.cursor()
    c.execute("PRAGMA table_info(crustacean_hosts)")
    cols = [row[1] for row in c.fetchall()]

    if "host_type" not in cols:
        c.execute("ALTER TABLE crustacean_hosts ADD COLUMN host_type VARCHAR(30)")
        conn.commit()
        print("[DB] Added column: crustacean_hosts.host_type")

    if "iucn_assessment_year" not in cols:
        c.execute("ALTER TABLE crustacean_hosts ADD COLUMN iucn_assessment_year VARCHAR(10)")
        conn.commit()
        print("[DB] Added column: crustacean_hosts.iucn_assessment_year")


def enhance_hosts() -> None:
    print("=" * 60)
    print("Enhancing Host Data (IUCN + aquaculture status + host_type)")
    print("=" * 60)

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    add_host_columns(conn)

    c.execute("SELECT host_id, scientific_name FROM crustacean_hosts ORDER BY scientific_name")
    hosts = c.fetchall()

    updated_iucn = 0
    updated_aqua = 0
    updated_type = 0
    unknowns: list[tuple[int, str]] = []

    for row in hosts:
        hid = row["host_id"]
        name = row["scientific_name"]
        name_norm = name.strip()

        # Determine host_type
        host_type = None
        if name_norm in NON_CRUSTACEAN:
            host_type = "non_crustacean"
        elif name_norm in NOT_SPECIES_LEVEL:
            host_type = "not_species_level"
        else:
            host_type = "crustacean"

        # IUCN status
        iucn = IUCN_MAPPING.get(name_norm)
        if not iucn and host_type == "not_species_level":
            iucn = "Not Applicable"
        if not iucn and host_type == "non_crustacean":
            iucn = "Not Applicable"

        # Aquaculture status
        aqua = AQUACULTURE_STATUS.get(name_norm)

        # Build update
        updates = []
        params = []
        if iucn:
            updates.append("iucn_status = ?")
            params.append(iucn)
        if aqua:
            updates.append("aquaculture_status = ?")
            params.append(aqua)
        if host_type:
            updates.append("host_type = ?")
            params.append(host_type)

        if updates:
            sql = f"UPDATE crustacean_hosts SET {', '.join(updates)} WHERE host_id = ?"
            params.append(hid)
            c.execute(sql, params)

        if iucn:
            updated_iucn += 1
        if aqua:
            updated_aqua += 1
        if host_type:
            updated_type += 1

        if not iucn and host_type == "crustacean":
            unknowns.append((hid, name_norm))

    conn.commit()

    print(f"\n[Results]")
    print(f"  Total hosts: {len(hosts)}")
    print(f"  IUCN status filled: {updated_iucn}")
    print(f"  Aquaculture status filled: {updated_aqua}")
    print(f"  Host type filled: {updated_type}")
    print(f"  Unknown crustacean species (need manual curation): {len(unknowns)}")

    if unknowns:
        print(f"\n  Hosts needing IUCN lookup:")
        for hid, name in unknowns:
            print(f"    - {name}")

    # Verification
    print(f"\n[Verification]")
    c.execute("SELECT host_type, COUNT(*) FROM crustacean_hosts GROUP BY host_type")
    for r in c.fetchall():
        print(f"  {r[0] or 'NULL':20s}: {r[1]:3d}")

    c.execute(
        "SELECT iucn_status, COUNT(*) FROM crustacean_hosts WHERE iucn_status IS NOT NULL GROUP BY iucn_status"
    )
    print(f"\n  IUCN status distribution:")
    for r in c.fetchall():
        print(f"    {r[0] or 'NULL':20s}: {r[1]:3d}")

    conn.close()
    print("\n" + "=" * 60)
    print("Done! Host enhancement complete.")
    print("=" * 60)


if __name__ == "__main__":
    enhance_hosts()
