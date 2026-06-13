"""Classify viruses from BLAST results and update DB."""
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
        # qry|protein_id|master_id|name|genome_type|family
        qparts = qseqid.split('|')
        # ref|protein_id|family|genus|name|accession
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

print(f"Parsed {len(hit_families)} viruses with BLAST hits (non-Unclassified families)")

classified_high, classified_med, classified_low, failed = 0, 0, 0, 0
updates_s, updates_m = [], []

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
        conf = 'high'; classified_high += 1
    elif best['pident'] >= 50:
        conf = 'medium'; classified_med += 1
    elif best['pident'] >= 30 and best['qcov'] >= 40:
        conf = 'low'; classified_low += 1
    else:
        failed += 1; continue

    updates_s.append((conf, mid))
    updates_m.append((mid, top_family, conf, best['pident'], best['qcov'], consensus, len(best_by_protein)))

total = len(hit_families)
classified = classified_high + classified_med + classified_low
print(f"\nResults: {classified}/{total} viruses classified ({100*classified/max(total,1):.1f}%)")
print(f"  High: {classified_high}, Medium: {classified_med}, Low: {classified_low}, Failed: {failed}")

family_counts = Counter(f[1] for f in updates_m)
print("\nTop families assigned:")
for fam, cnt in family_counts.most_common(15):
    print(f"  {fam}: {cnt}")

# Update database
if updates_s:
    c.executemany(
        "UPDATE virus_ictv_status SET ictv_status='mapped', best_confidence=?, updated_at=datetime('now') WHERE master_id=?",
        updates_s
    )
    print(f"  Updated {len(updates_s)} virus_ictv_status rows to 'mapped'")

for mid, fam, conf, pident, qcov, consensus, nprot in updates_m:
    c.execute("SELECT ictv_id FROM ictv_taxonomy WHERE LOWER(family) = LOWER(?) LIMIT 1", (fam,))
    row = c.fetchone()
    if row:
        c.execute(
            "INSERT OR IGNORE INTO virus_ictv_mappings (master_id, ictv_id, match_status, confidence, match_type, matched_value, notes, created_at) VALUES (?, ?, 'auto_matched', ?, 'family', ?, 'BLASTP_local_ref', datetime('now'))",
            (mid, row[0], conf, fam)
        )

conn.commit()

# Verify
c.execute("SELECT ictv_status, COUNT(*) FROM virus_ictv_status GROUP BY ictv_status")
print("\nUpdated ICTV status distribution:")
for r in c.fetchall():
    print(f"  {r[0]}: {r[1]}")

c.execute("SELECT COUNT(DISTINCT master_id) FROM virus_ictv_mappings WHERE notes = 'BLASTP_local_ref'")
print(f"  Total BLASTP_local_ref mappings: {c.fetchone()[0]}")

conn.close()
print(f"\nDone in {time.time()-start:.0f}s")
