"""
Supplementary normalization with safer matching rules for unresolved names.
"""

import sqlite3

DB_PATH = r"F:\甲壳动物数据库\crustacean_virus_core.db"

SUPPLEMENTARY_RULES = [
    {
        "canonical_name": "White spot syndrome virus",
        "match_type": "contains",
        "patterns": ["white spot syndrome virus", "shrimp white spot syndrome virus", "wssv"],
        "is_crustacean": 1,
        "entry_type": "gene_fragment",
    },
    {
        "canonical_name": "Crab associated circular virus",
        "match_type": "contains",
        "patterns": ["associated circular virus"],
        "is_crustacean": 1,
        "entry_type": "complete_genome",
    },
    {
        "canonical_name": "Shrimp glass disease virus",
        "match_type": "exact",
        "patterns": ["shrimp glass disease virus"],
        "is_crustacean": 1,
        "entry_type": "complete_genome",
    },
    {
        "canonical_name": "Non-crustacean virus",
        "match_type": "exact",
        "patterns": [
            "african swine fever virus",
            "ambystoma tigrinum virus",
            "bean yellow mosaic virus",
            "bovine papular stomatitis virus",
            "ectromelia virus",
            "emiliania huxleyi virus",
            "frog virus 3",
            "human immunodeficiency virus",
            "infectious spleen and kidney necrosis virus",
            "lumpy skin disease virus",
            "lymphocystis disease virus",
            "molluscum contagiosum virus",
            "mumps virus",
            "newcastle disease virus",
            "orf virus",
            "peanut mottle virus",
            "peanut stunt virus",
            "pseudorabies virus",
            "rabbit hemorrhagic disease virus",
            "sars-cov-2",
            "severe acute respiratory syndrome coronavirus 2",
            "sheeppox virus",
            "simian immunodeficiency virus",
            "soybean mosaic virus",
            "taro bacilliform virus",
            "tomato black ring virus",
        ],
        "is_crustacean": 0,
        "entry_type": "non_target",
    },
]


def matches_rule(raw_name, rule):
    lower = raw_name.lower().strip()
    if rule["match_type"] == "exact":
        return lower in rule["patterns"]
    if rule["match_type"] == "contains":
        return any(pattern in lower for pattern in rule["patterns"])
    return False


def upsert_master(c, canonical_name, is_crustacean, entry_type):
    c.execute("SELECT master_id FROM virus_master WHERE canonical_name = ?", (canonical_name,))
    row = c.fetchone()
    if row:
        c.execute(
            """
            UPDATE virus_master
            SET is_crustacean_virus = ?, entry_type = ?
            WHERE canonical_name = ?
            """,
            (is_crustacean, entry_type, canonical_name),
        )
        return row[0]

    c.execute(
        """
        INSERT INTO virus_master (canonical_name, entry_type, is_crustacean_virus)
        VALUES (?, ?, ?)
        """,
        (canonical_name, entry_type, is_crustacean),
    )
    return c.lastrowid


def apply(incremental=True):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute(
        "SELECT master_id FROM virus_master WHERE canonical_name = ?",
        ("Unknown/Unclassified",),
    )
    result = c.fetchone()
    if not result:
        conn.close()
        print("Unknown/Unclassified master record not found. Run normalize_virus_names.py first.")
        return
    unknown_id = result[0]

    if incremental:
        c.execute(
            """
            SELECT DISTINCT virus_name
            FROM viral_isolates
            WHERE master_id = ?
            """,
            (unknown_id,),
        )
        unmapped = [r[0] for r in c.fetchall() if r[0]]
    else:
        c.execute("SELECT DISTINCT virus_name FROM viral_isolates WHERE virus_name IS NOT NULL")
        unmapped = [r[0] for r in c.fetchall()]

    print(f"Processing {len(unmapped)} names...")

    processed = 0
    for raw_name in unmapped:
        for rule in SUPPLEMENTARY_RULES:
            if not matches_rule(raw_name, rule):
                continue

            master_id = upsert_master(
                c,
                rule["canonical_name"],
                rule["is_crustacean"],
                rule["entry_type"],
            )
            c.execute(
                "UPDATE viral_isolates SET master_id = ? WHERE virus_name = ?",
                (master_id, raw_name),
            )
            processed += c.rowcount
            break

    conn.commit()
    print(f"Updated {processed} records")
    conn.close()


if __name__ == "__main__":
    apply()
