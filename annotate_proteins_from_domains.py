#!/usr/bin/env python3
"""Infer viral_proteins.functional_category from existing domain annotations."""
import sqlite3, re
from collections import Counter

conn = sqlite3.connect('F:/水生无脊椎动物数据库/crustacean_virus_core.db')

DOMAIN_TO_FUNCTION = [
    # Replication / Transcription (ordered: specific -> generic)
    (r'RNA-dependent RNA polymerase|RNA-directed RNA polymerase|RdRp|RDRP|RNA replicase|viral RNA polymerase|RNA-dependent RNA_polymerase', 'RdRP'),
    (r'RNA polymerase|DNA-directed RNA polymerase|transcriptase', 'replication'),
    (r'helicase|Hel|superfamily.*helicase|DEAD.box|DEAH.box|SF1.*helicase|SF2.*helicase|viral.*helicase', 'replication'),
    (r'RNA-dependent DNA polymerase|reverse transcriptase|RT_like|RVT', 'replication'),
    (r'DNA polymerase|DNA_depen.*pol|DNA_pol|viral DNA polymerase|DNA.polymerase', 'replication'),
    (r'DNA primase|primase|DnaG', 'replication'),
    (r'viral.*methyltransferase|2.*O.*methyltransferase|viral.*MT|FtsJ.*methyl|nsp1[346].*MT|NSP1[346].*MT', 'replication'),
    (r'endonuclease|nuclease|exonuclease|ribonuclease|RNase|RNaseIII|RNase_H|Ribonuclease_H|viral.*RNase|Rnc\b', 'replication'),
    (r'peptidase.*C3[0-9]|3C.*protease|3CL.pro|cysteine protease.*viral|chymotrypsin.*viral|serine protease.*viral|viral protease|main protease|leader protease|trypsin.*viral', 'replication'),
    (r'nucleotidyltransferase|guanylyltransferase|guanylate|mRNA.cap|cap.methyl', 'replication'),
    (r'dNTPase|NTPase|viral.*NTPase|P.loop.*NTPase', 'replication'),
    (r'Vmethyltransf|FtsJ|SAM.*methyl|AdoMet.*MTase', 'replication'),
    (r'DNA.binding.*viral|viral.*DNA.binding|single.strand.*binding.*viral|ssDNA.binding|replication.protein.A', 'replication'),
    (r'transcription.factor.*viral|viral.*transcription.factor|immediate.early|IE.*protein.*viral', 'replication'),
    # Additional replication signals from domain names
    (r'\bDnaQ_like_exo\b|\bbeta_clamp\b|\bHMG_box\b|\bPHP\b|\bRPA\b', 'replication'),
    (r'ribonucleotide.reductase|thioredoxin|glutaredoxin|nucleotide.*metab', 'metabolism'),

    # Structural / Capsid
    (r'capsid|coat protein|viral coat|viral.*capsid|major capsid|minor capsid|capsid.protein|p24 capsid', 'structural'),
    (r'nucleocapsid|nucleoprotein|viral.*nucleocapsid|core protein|viral core|N protein|capsid.*internal', 'structural'),
    (r'envelope.*glycoprotein|envelope.*protein|viral.*envelope|spike glycoprotein|spike protein|peplomer|membrane glycoprotein|viral glycoprotein|surface glycoprotein|major envelope|E1.glycoprotein|E2.glycoprotein', 'structural'),
    (r'matrix protein|viral matrix|tegument|viral tegument', 'structural'),
    (r'virion|virion protein|structural protein|structural.polyprotein|viral structural', 'structural'),
    (r'fibre protein|tail fiber|tail fibre|viral tail|baseplate|portal protein|viral portal|connector protein', 'structural'),
    # Additional structural signals
    (r'\bVP\d+\b|viral.protein.\d+|\bWSS_VP\b|\bSP24\b|\bp24\b', 'structural'),
    (r'\brhv_like\b|picornavirus.capsid|jelly.roll|beta.barrel.*capsid|beta.sandwich.*capsid', 'structural'),
    (r'glycoprotein|signal.peptide|transmembrane.*helix|membrane.*protein.*viral', 'structural'),
    (r'collagen.like|collagen.*repeat|gly_rich_SclB|glycine.rich.*structural', 'structural'),
    (r'myosin.*tail|Myosin_tail|tropomyosin|actin.binding', 'structural'),

    # Host interaction / Immune evasion
    (r'apoptosis|apoptotic|Bcl.2|Bcl2|BAX|BAK|caspase.*inhib|death.*domain|viral.*death|viral.*FAS', 'host_interaction'),
    (r'interferon|IFN.*antagonist|IFN.*inhibitor|STAT.*inhibitor|IRF.*inhibitor|innate.*immune.*evasion|immune.evasin|viral.*evasion|immune.evasion', 'host_interaction'),
    (r'ubiquitin|E3.ubiquitin.ligase|ubiquitin.ligase|deubiquitinase|DUB|RING.finger.*viral|HECT.*viral|viral.*ubiquitin|Rcat_RBR|Ubl1_cv_Nsp3', 'host_interaction'),
    (r'SH2|SH3|viral.*signaling|viral.*adaptor|ITAM|ITIM|immunoreceptor|KIR|viral.*MHC|viral.*cytokine|viral.*chemokine|vIL|viral interleukin|viral TNF', 'host_interaction'),
    (r'host.shutoff|host.*shut.off|viral.*shutoff|RNA.degradation.*viral|vhs.*protein', 'host_interaction'),
    (r'ankyrin.repeat.*viral|viral.*ankyrin|ANK.*repeat.*viral|Ank_2\b', 'host_interaction'),
    (r'movement protein|cell.to.cell|plasmodesmat|tubule.*viral', 'host_interaction'),
    (r'RNA.silencing|RNAi suppressor|VSR|viral.*silencing|PTGS|siRNA.*viral|dsRNA.binding.*viral', 'host_interaction'),
    # Additional host interaction signals
    (r'\bRasGAP\b|\bGAP\b|GTPase.activating|G.protein|small.GTPase', 'host_interaction'),
    (r'cytokine.receptor|growth.factor.*receptor|TNFR|TLR|NLR|RLR|PRR', 'host_interaction'),
    (r'phosphatase|kinase.*viral|serine.threonine.kinase|tyrosine.kinase|protein.kinase|PKR', 'host_interaction'),

    # Assembly / Morphogenesis
    (r'assembly|virion.assembly|viral.assembly|scaffold|scaffolding|maturation|viral maturation|procapsid|prohead', 'assembly'),
    (r'packaging|DNA.packaging|RNA.packaging|terminase|portal.protein|packaging.ATPase', 'assembly'),
    (r'holin|lysin|lysis|endolysin|lysozyme.*viral|peptidoglycan.*viral|viral.*lysis', 'assembly'),

    # Metabolism
    (r'thymidine kinase|thymidylate kinase|dUTPase|dUTP.pyrophosphatase|dCMP deaminase|ribonucleotide.reductase|thymidylate synthase|dihydrofolate reductase|viral.*nucleotide.*metab', 'metabolism'),
    (r'ATPase.*viral|viral.*ATPase|AAA.*ATPase.*viral', 'metabolism'),
    # Additional metabolism signals
    (r'\bdut\b|\bATP.cone\b|\bTesB\b|acyl.CoA|thioesterase', 'metabolism'),
    (r'ferritin|superoxide.dismutase|catalase|peroxidase|redoxin|glutathione|thioredoxin', 'metabolism'),
    (r'glycosyltransferase|glycosyl.hydrolase|chitinase|chitin.binding|lectin|carbohydrate.binding', 'metabolism'),
    (r'lipase|esterase|phospholipase|protease|peptidase|metalloprotease', 'metabolism'),
    (r'\bRNR_PFL\b|\bPDI_a_family\b|disulfide.isomerase', 'metabolism'),
    (r'\bRMtype1_S_TRD-CR_like\b|restriction.modification|methylase.*DNA', 'metabolism'),

    # Additional replication signals (round 3)
    (r'\bViral_Rep\b|viral.replication|Rep.protein|replication.initiator|replication.associated', 'replication'),
    (r'\bDSRM_SF\b|dsRNA.binding|double.strand.RNA.binding|dsRBD', 'host_interaction'),
    (r'\bZinc_finger\b|zinc.finger.*viral|zf-|zinc.knuckle|zinc.binding.*viral|\bzf-TAZ\b', 'replication'),

    # Additional structural signals (round 3)
    (r'\bTransmembrane\b|transmembrane.domain|integral.membrane|membrane.protein', 'structural'),
    (r'\bCollagen\b|collagen.repeat', 'structural'),
    (r'\bB2\b|\bMSV199\b|Pab87_oct', 'structural'),
    (r'\bPolyprotein\b|polyprotein', 'structural'),

    # Additional assembly signals
    (r'\bDNA_pack_C\b|\bDNA_pack\b|packaging.*signal', 'assembly'),

    # Additional host interaction signals
    (r'\bPKc_like\b|protein.kinase|tyrosine.kinase.sf|kinase.domain', 'host_interaction'),
    (r'\bbZIP\b|basic.leucine.zipper|transcription.factor.*bZIP', 'host_interaction'),
    (r'\beIF_4EBP\b|eIF4E|translation.initiation|eukaryotic.initiation', 'host_interaction'),
    (r'\bNIF\b|\bHRD1\b|ubiquitin.ligase', 'host_interaction'),

    # Additional broad/fallback for viral proteins
    (r'\bLDLa\b|LDL.receptor|EGF.like|fibronectin|integrin|adhesin', 'structural'),
    (r'\bSHS2_Rpb7-N\b|Rpb7|RNA.polymerase.subunit', 'replication'),
]

def infer_function(domain_name, description):
    text = str(domain_name or '') + ' ' + str(description or '')
    for pattern, category in DOMAIN_TO_FUNCTION:
        if re.search(pattern, text, re.IGNORECASE):
            return category
    # Broader fallbacks
    tl = text.lower()
    if re.search(r'structural|virion|capsid|coat|envelope|spike|fiber|nucleocapsid', tl):
        return 'structural'
    if re.search(r'polymerase|replicase|helicase|protease|nuclease|methyltransferase|transcriptase', tl):
        return 'replication'
    return None

unknown_proteins = conn.execute("""
SELECT protein_id, protein_name, gene_symbol
FROM viral_proteins
WHERE functional_category = 'unknown' OR functional_category IS NULL
""").fetchall()
total_unknown = len(unknown_proteins)
print(f"Proteins with unknown function: {total_unknown}")

updated = 0
domain_sources = []
for prot_id, prot_name, gene_sym in unknown_proteins:
    domains = conn.execute("""
    SELECT domain_name, domain_description, domain_source
    FROM protein_domains
    WHERE protein_id = ?
    ORDER BY confidence_score DESC
    """, (prot_id,)).fetchall()

    inferred = None
    for dname, ddesc, dsrc in domains:
        inferred = infer_function(dname, ddesc)
        if inferred:
            domain_sources.append(dsrc or 'unknown_source')
            break

    # Name-based fallback
    if not inferred:
        text = str(prot_name or '') + ' ' + str(gene_sym or '')
        tl = text.lower()
        non_struct = bool(re.search(r'non.structural|nonstructural', tl))
        if re.search(r'structural|capsid|coat|virion|envelope|spike|nucleocapsid|nucleoprotein|matrix|tegument', tl) and not non_struct:
            inferred = 'structural'
        elif re.search(r'RNA.dependent.RNA.polymerase|RdRp|RNA.polymerase|replicase|RNA.replicase', tl):
            inferred = 'RdRP'
        elif re.search(r'polymerase|helicase|protease|nuclease|methyltransferase|replication|transcriptase', tl) and not re.search(r'RNA.polymerase|RdRp', tl):
            inferred = 'replication'
        elif re.search(r'ubiquitin|apoptosis|immune|Bcl|interferon|host.*shut', tl):
            inferred = 'host_interaction'
        elif re.search(r'kinase|ATPase|dUTPase|nucleotide|thymidine|metabol|synthase|reductase', tl):
            inferred = 'metabolism'
        elif re.search(r'assembly|scaffold|packaging|terminase|holin|lysin|lysis', tl):
            inferred = 'assembly'

    if inferred:
        conn.execute("""
        UPDATE viral_proteins SET functional_category = ?, functional_category_source = 'domain_inference'
        WHERE protein_id = ?
        """, (inferred, prot_id))
        updated += 1

    if updated % 5000 == 0 and updated > 0:
        conn.commit()
        print(f"  Updated {updated}...")

conn.commit()
remaining = conn.execute("SELECT COUNT(*) FROM viral_proteins WHERE functional_category='unknown' OR functional_category IS NULL").fetchone()[0]
print(f"\nUpdated: {updated} proteins ({100*updated/total_unknown:.1f}% of previously unknown)")
print(f"Remaining unknown: {remaining} ({100*remaining/26894:.1f}% of all proteins)")
print()

print("New functional_category distribution:")
for r in conn.execute("SELECT functional_category, COUNT(*) FROM viral_proteins GROUP BY functional_category ORDER BY COUNT(*) DESC").fetchall():
    pct = 100 * r[1] / 26894
    print(f"  {r[0]:<25} {r[1]:>7,}  ({pct:.1f}%)")

dc = Counter(domain_sources)
if dc:
    print(f"\nDomain sources used for inference:")
    for src, cnt in dc.most_common(5):
        print(f"  {src}: {cnt}")

conn.close()
