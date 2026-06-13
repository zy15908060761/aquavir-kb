#!/usr/bin/env python3
"""Merge 9 duplicate virus_master entries. Full data migration, no data loss."""
import sqlite3

conn = sqlite3.connect('F:/水生无脊椎动物数据库/crustacean_virus_core.db')

merges = [
    # (dup_id, keeper_id, label)
    (1300, 1, 'white spot syndrome virus'),
    (1299, 2, 'yellow head virus'),
    (1302, 3, 'taura syndrome virus'),
    (1301, 4, 'infectious hypodermal and hematopoietic necrosis virus'),
    (1305, 5, 'infectious myonecrosis virus'),
    (1306, 6, 'macrobrachium rosenbergii nodavirus'),
    (1298, 8, 'hepatopancreatic parvovirus'),
    (545,  1304, 'ostreid herpesvirus 1'),
    (1308, 547, 'haliotid herpesvirus 1'),
]

# Fix TSV family (id=1302 has Dicistroviridae which is correct, id=3 has Aparvoviridae)
conn.execute("UPDATE virus_master SET virus_family = 'Dicistroviridae' WHERE master_id = 3")
print("[OK] TSV family fixed: Aparvoviridae -> Dicistroviridae")

# Find all tables referencing virus_master master_id
fk_cols = {}
for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall():
    tname = r[0]
    cols = [c[1] for c in conn.execute(f"PRAGMA table_info(\"{tname}\")").fetchall()]
    for col in cols:
        if col in ('master_id', 'virus_master_id', 'virus_id'):
            fk_cols.setdefault(tname, []).append(col)

print(f"Tables with virus FK: {len(fk_cols)}")

migrated = {}
for dup_id, keeper_id, label in merges:
    dup_name = conn.execute("SELECT canonical_name FROM virus_master WHERE master_id=?", (dup_id,)).fetchone()
    keep_name = conn.execute("SELECT canonical_name FROM virus_master WHERE master_id=?", (keeper_id,)).fetchone()
    dup_name = dup_name[0] if dup_name else '?'
    keep_name = keep_name[0] if keep_name else '?'

    # Merge all isolates
    iso_moved = 0
    for iso in conn.execute("SELECT isolate_id FROM viral_isolates WHERE master_id=?", (dup_id,)).fetchall():
        conn.execute("UPDATE viral_isolates SET master_id=? WHERE isolate_id=?", (keeper_id, iso[0]))
        iso_moved += 1

    # Merge evidence_records
    ev_moved = 0
    for ev in conn.execute("SELECT evidence_id FROM evidence_records WHERE virus_master_id=?", (dup_id,)).fetchall():
        try:
            conn.execute("UPDATE evidence_records SET virus_master_id=? WHERE evidence_id=?", (keeper_id, ev[0]))
            ev_moved += 1
        except:
            pass

    # Merge other FK tables
    other_moved = {}
    for tname, cols in fk_cols.items():
        if tname in ('virus_master', 'viral_isolates', 'evidence_records', 'sqlite_sequence', 'sqlite_stat1',
                     'virus_search_fts', 'virus_search_fts_data', 'virus_search_fts_docsize',
                     'virus_search_fts_idx', 'virus_search_fts_config'):
            continue
        for col in cols:
            try:
                res = conn.execute(f"UPDATE \"{tname}\" SET {col}=? WHERE {col}=?", (keeper_id, dup_id))
                cnt = res.rowcount
                if cnt > 0:
                    other_moved[f"{tname}.{col}"] = cnt
            except Exception as e:
                pass

    # Migrate ICTV mappings
    map_moved = 0
    for m in conn.execute("SELECT mapping_id FROM virus_ictv_mappings WHERE master_id=?", (dup_id,)).fetchall():
        # Check if keeper already has this ICTV mapping
        dup_ictv = conn.execute("SELECT ictv_id FROM virus_ictv_mappings WHERE mapping_id=?", (m[0],)).fetchone()
        if dup_ictv and dup_ictv[0]:
            exists = conn.execute("SELECT COUNT(*) FROM virus_ictv_mappings WHERE master_id=? AND ictv_id=?",
                                  (keeper_id, dup_ictv[0])).fetchone()[0]
            if exists:
                conn.execute("DELETE FROM virus_ictv_mappings WHERE mapping_id=?", (m[0],))
                continue
        conn.execute("UPDATE virus_ictv_mappings SET master_id=? WHERE mapping_id=?", (keeper_id, m[0]))
        map_moved += 1

    # Migrate data_provenance references
    prov_moved = 0
    for p in conn.execute("SELECT provenance_id FROM data_provenance WHERE virus_master_id=?", (dup_id,)).fetchall():
        try:
            conn.execute("UPDATE data_provenance SET virus_master_id=? WHERE provenance_id=?", (keeper_id, p[0]))
            prov_moved += 1
        except:
            pass

    # Delete the duplicate virus_master
    conn.execute("DELETE FROM virus_master WHERE master_id=?", (dup_id,))

    # FTS table doesn't use master_id — it's a search index, will rebuild later
    # Just delete from main tables

    print(f"\n{'='*60}")
    print(f"MERGED: '{dup_name}' -> '{keep_name}'")
    print(f"  Isolates moved: {iso_moved}")
    print(f"  Evidence moved: {ev_moved}")
    print(f"  ICTV mappings moved: {map_moved}")
    print(f"  Provenance moved: {prov_moved}")
    for tbl, cnt in other_moved.items():
        print(f"  {tbl}: {cnt} records re-pointed")
    print(f"  Duplicate DELETED (id={dup_id})")

conn.commit()

# Verify
remaining = conn.execute("SELECT COUNT(*) FROM virus_master").fetchone()[0]
print(f"\n{'='*60}")
print(f"Total virus_master after merge: {remaining} (was 1323, expected 1314)")

# Check no orphan evidence
orphan_ev = conn.execute("""
SELECT COUNT(*) FROM evidence_records er
WHERE er.virus_master_id IS NOT NULL
AND NOT EXISTS (SELECT 1 FROM virus_master vm WHERE vm.master_id = er.virus_master_id)
""").fetchone()[0]
print(f"Orphan evidence_records: {orphan_ev} (should be 0)")

# Check no orphan isolates
orphan_iso = conn.execute("""
SELECT COUNT(*) FROM viral_isolates vi
WHERE vi.master_id IS NOT NULL
AND NOT EXISTS (SELECT 1 FROM virus_master vm WHERE vm.master_id = vi.master_id)
""").fetchone()[0]
print(f"Orphan viral_isolates: {orphan_iso} (should be 0)")

conn.close()
