"""Insert BLAST classification mapping details into virus_ictv_mappings."""
import sqlite3, time
from collections import defaultdict, Counter

DB_PATH = r"F:\水生无脊椎动物数据库\crustacean_virus_core.db"
OUT_TAB = r"F:\水生无脊椎动物数据库\blastdb\blast_results.tsv"

conn = sqlite3.connect(DB_PATH)
c = conn.cursor()

start = time.time()
hit_families = defaultdict(list)
with open(OUT_TAB) as f:
    for line in f:
        parts = line.strip().split('\t')
        if len(parts) < 5:
            continue
        qseqid, sseqid, pident, length, qcovhsp = parts[0], parts[1], float(parts[2]), int(parts[3]), float(parts[4])
        qparts = qseqid.split('|')
        sparts = sseqid.split('|')
        if len(qparts) >= 3 and len(sparts) >= 3:
            mid = qparts[2]
            ref_family = sparts[2]
            if not ref_family or ref_family == 'Unclassified':
                continue
            hit_families[mid].append({
                'pid': qparts[1], 'family': ref_family,
                'pident': pident, 'qcov': qcovhsp
            })

print(f"Parsed {len(hit_families)} viruses")

updates_m = []
for mid, hits in hit_families.items():
    if not hits:
        continue
    best_by_protein = {}
    for h in hits:
        if h['pid'] not in best_by_protein or h['pident'] > best_by_protein[h['pid']]['pident']:
            best_by_protein[h['pid']] = h
    family_votes = Counter(h['family'] for h in best_by_protein.values())
    top_family, top_count = family_votes.most_common(1)[0]
    consensus = top_count / len(best_by_protein)
    best = max(best_by_protein.values(), key=lambda h: h['pident'])

    if best['pident'] >= 70 and best['qcov'] >= 80:
        conf = 'high'
    elif best['pident'] >= 50:
        conf = 'medium'
    elif best['pident'] >= 30 and best['qcov'] >= 40:
        conf = 'low'
    else:
        continue

    updates_m.append((mid, top_family, conf, best['pident'], best['qcov'], consensus, len(best_by_protein)))

n = 0
skipped = []
for mid, fam, conf, pident, qcov, consensus, nprot in updates_m:
    c.execute("SELECT ictv_id FROM ictv_taxonomy WHERE LOWER(family) = LOWER(?) LIMIT 1", (fam,))
    row = c.fetchone()
    if not row:
        # Try genus-level lookup for non-family taxa like Riboviria (realm)
        c.execute("SELECT ictv_id FROM ictv_taxonomy WHERE LOWER(genus) = LOWER(?) LIMIT 1", (fam,))
        row = c.fetchone()
    if row:
        c.execute(
            "INSERT OR IGNORE INTO virus_ictv_mappings (master_id, ictv_id, match_status, confidence, match_type, matched_value, notes, created_at) VALUES (?, ?, 'auto_matched', ?, 'normalized_exact', ?, 'BLASTP_local_ref', datetime('now'))",
            (mid, row[0], conf, fam)
        )
        n += 1
    else:
        if fam not in skipped:
            skipped.append(fam)
            print(f"  Warning: no ICTV taxonomy entry for '{fam}' - skipping")

conn.commit()

c.execute("SELECT COUNT(*) FROM virus_ictv_mappings WHERE notes = 'BLASTP_local_ref'")
print(f"Inserted {n} mapping rows. Total in DB: {c.fetchone()[0]}")

# Final audit
c.execute("SELECT ictv_status, COUNT(*) FROM virus_ictv_status GROUP BY ictv_status")
print("\nFinal ICTV Status:")
for r in c.fetchall():
    print(f"  {r[0]}: {r[1]}")

conn.close()
print(f"Done in {time.time()-start:.0f}s")
