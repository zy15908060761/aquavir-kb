import json
import sqlite3
from pathlib import Path

db = Path(__file__).resolve().parent / "crustacean_virus_core.db"
con = sqlite3.connect(db)
con.row_factory = sqlite3.Row
cur = con.cursor()

pre_cols = [r["name"] for r in cur.execute("PRAGMA table_info(epmc_preprints)")]
lit_cols = [r["name"] for r in cur.execute("PRAGMA table_info(epmc_literature)")]

fk = cur.execute("PRAGMA foreign_key_list(epmc_preprints)").fetchone()
if not fk:
    raise SystemExit("epmc_preprints has no foreign key")
from_col = fk["from"]
to_col = fk["to"]

missing = cur.execute(
    f"""
    SELECT DISTINCT p."{from_col}" AS parent_id
    FROM epmc_preprints p
    LEFT JOIN epmc_literature l ON l."{to_col}" = p."{from_col}"
    WHERE p."{from_col}" IS NOT NULL AND l."{to_col}" IS NULL
    """
).fetchall()

inserted = 0
for row in missing:
    parent_id = row["parent_id"]
    sample = cur.execute(
        f'SELECT * FROM epmc_preprints WHERE "{from_col}"=? LIMIT 1', (parent_id,)
    ).fetchone()
    data = {to_col: parent_id}
    for col in lit_cols:
        if col in data:
            continue
        if col in pre_cols and sample[col] is not None:
            data[col] = sample[col]
    for col in ["source", "record_source", "curation_status", "notes"]:
        if col in lit_cols and col not in data:
            if col == "curation_status":
                data[col] = "preprint_parent_stub"
            elif col in {"source", "record_source"}:
                data[col] = "Europe PMC preprint"
            else:
                data[col] = "Auto-created parent row to satisfy epmc_preprints foreign key; review before final citation use."

    required_missing = []
    for c in cur.execute("PRAGMA table_info(epmc_literature)"):
        name = c["name"]
        notnull = c["notnull"]
        default = c["dflt_value"]
        pk = c["pk"]
        if notnull and default is None and not pk and name not in data:
            required_missing.append(name)
    if required_missing:
        # Conservative generic placeholders only for schema-required text fields.
        for name in required_missing:
            data[name] = f"preprint_stub_{parent_id}"

    cur.execute(
        f'INSERT OR IGNORE INTO epmc_literature ({",".join(data.keys())}) VALUES ({",".join(["?"] * len(data))})',
        list(data.values()),
    )
    inserted += cur.rowcount

cur.execute(
    """
    INSERT INTO database_maintenance_log (action, details_json, created_at)
    VALUES (?, ?, CURRENT_TIMESTAMP)
    """,
    (
        "foreign_key_fix",
        json.dumps(
            {
                "table": "epmc_preprints",
                "parent_table": "epmc_literature",
                "from_col": from_col,
                "to_col": to_col,
                "missing_parent_ids": len(missing),
                "inserted_parent_rows": inserted,
            },
            ensure_ascii=False,
        ),
    ),
)
con.commit()
print({"missing_parent_ids": len(missing), "inserted_parent_rows": inserted})
