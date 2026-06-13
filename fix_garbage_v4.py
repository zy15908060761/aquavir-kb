"""Additional garbage rejection based on spot-check findings."""
import sqlite3

conn = sqlite3.connect('crustacean_virus_core.db')

patterns = [
    ('%children with%', 'Human pediatric study'),
    ('%patients with%', 'Human clinical study'),
    ('%clinical trial%', 'Human clinical trial'),
    ('%SARS-CoV-2%', 'Human SARS-CoV-2'),
    ('%COVID-19 pandemic%', 'COVID-19 socioeconomic'),
    ('%coronavirus disease 2019%', 'COVID-19 generic'),
    ('%sea lion%', 'Marine mammal study'),
    ('%California sea lion%', 'Marine mammal study'),
    ('%goodness-of-fit%', 'Statistical modeling, not evidence'),
    ('%Weibull%', 'Statistical modeling'),
    ('%log-logistic%', 'Statistical modeling'),
    ('%Akaike information criterion%', 'Statistical modeling'),
    ('%SPAdes%', 'Bioinformatics tool description'),
    ('%MEGAHIT%', 'Bioinformatics tool description'),
    ('%HTLV-1%', 'Human retrovirus study'),
    ('%T-cell line%', 'Human cell line study'),
    ('%food safety%', 'Human food safety'),
    ('%raw or undercooked%', 'Human food consumption'),
]
# Escape % for SQL LIKE
all_ids = set()
for pat, reason in patterns:
    rows = conn.execute('''
        SELECT evidence_id FROM evidence_records
        WHERE curation_status = 'auto_imported'
        AND (LOWER(COALESCE(claim,'')) LIKE ? OR LOWER(COALESCE(value_text,'')) LIKE ?)
    ''', (pat.lower(), pat.lower())).fetchall()
    ids = set(r[0] for r in rows)
    all_ids.update(ids)
    if ids:
        print(f'  {reason}: {len(ids):,}')

print(f'\nTotal to reject: {len(all_ids):,}')

id_list = list(all_ids)
for i in range(0, len(id_list), 500):
    batch = id_list[i:i+500]
    ph = ','.join(['?']*len(batch))
    conn.execute(f'''
        UPDATE evidence_records SET curation_status='rejected',
        notes=COALESCE(notes,'') || ' [Audit v4: off-topic human virus/mammal/statistical/bioinformatics]'
        WHERE evidence_id IN ({ph})
    ''', batch)

conn.commit()

rej = conn.execute("SELECT COUNT(*) FROM evidence_records WHERE curation_status='rejected'").fetchone()[0]
eff = conn.execute("SELECT COUNT(*) FROM evidence_records WHERE curation_status!='rejected'").fetchone()[0]
ai = conn.execute("SELECT COUNT(*) FROM evidence_records WHERE curation_status='auto_imported'").fetchone()[0]
mc = conn.execute("SELECT COUNT(*) FROM evidence_records WHERE curation_status='manual_checked'").fetchone()[0]
nr = conn.execute("SELECT COUNT(*) FROM evidence_records WHERE curation_status='needs_review'").fetchone()[0]
print(f'Rejected: {rej:,}  Effective: {eff:,}')
print(f'Auto_imported: {ai:,}  Manual_checked: {mc:,}  Needs_review: {nr:,}')

conn.close()
print('Done.')
