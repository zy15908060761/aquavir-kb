"""
backfill_protein_annotations.py

Backfill interpro_annotations, interpro_go_terms, and kegg_annotations
from protein_domains domain names using an extensive built-in domain-to-GO/KEGG
mapping dictionary plus fuzzy name matching.

Target: AquaVir-KB (crustacean_virus_core.db)
"""

import sqlite3
import re
import sys

DB_PATH = "F:/水生无脊椎动物数据库/crustacean_virus_core.db"

# =========================================================================
# 1. DOMAIN-TO-GO MAPPING DICTIONARY
#    Maps domain_name patterns -> list of (go_id, go_name, go_namespace)
# =========================================================================

# Exact domain_name -> GO mappings (for rule_based, protein_name_inference, etc.)
DOMAIN_GO_MAP = {
    # === RdRp / RNA-dependent RNA polymerase ===
    "RdRp": [
        ("GO:0003968", "RNA-directed RNA polymerase activity", "molecular_function"),
        ("GO:0016740", "transferase activity", "molecular_function"),
    ],
    "RdRp_domain": [
        ("GO:0003968", "RNA-directed RNA polymerase activity", "molecular_function"),
    ],
    "RdRp_replication": [
        ("GO:0003968", "RNA-directed RNA polymerase activity", "molecular_function"),
        ("GO:0003723", "RNA binding", "molecular_function"),
    ],
    "Func_RdRP": [
        ("GO:0003968", "RNA-directed RNA polymerase activity", "molecular_function"),
        ("GO:0003723", "RNA binding", "molecular_function"),
    ],
    "ps-ssRNAv_RdRp-like": [
        ("GO:0003968", "RNA-directed RNA polymerase activity", "molecular_function"),
    ],
    "ps-ssRNAv_Nodaviridae_RdRp": [
        ("GO:0003968", "RNA-directed RNA polymerase activity", "molecular_function"),
    ],
    "ps-ssRNAv_CBPV-like_RdRp": [
        ("GO:0003968", "RNA-directed RNA polymerase activity", "molecular_function"),
    ],
    "Viral_RdRp_C": [
        ("GO:0003968", "RNA-directed RNA polymerase activity", "molecular_function"),
    ],
    "RNA_polymerase": [
        ("GO:0003968", "RNA-directed RNA polymerase activity", "molecular_function"),
        ("GO:0003899", "DNA-directed 5'-3' RNA polymerase activity", "molecular_function"),
        ("GO:0006351", "transcription, DNA-templated", "biological_process"),
    ],
    "Polymerase": [
        ("GO:0016779", "nucleotidyltransferase activity", "molecular_function"),
    ],

    # === Helicase ===
    "Helicase": [
        ("GO:0004386", "helicase activity", "molecular_function"),
        ("GO:0005524", "ATP binding", "molecular_function"),
    ],
    "Helicase_domain": [
        ("GO:0004386", "helicase activity", "molecular_function"),
        ("GO:0005524", "ATP binding", "molecular_function"),
    ],
    "Helicase_C": [
        ("GO:0004386", "helicase activity", "molecular_function"),
        ("GO:0005524", "ATP binding", "molecular_function"),
    ],
    "Helicase_C_4": [
        ("GO:0004386", "helicase activity", "molecular_function"),
    ],
    "DEAD-like_helicase_N": [
        ("GO:0004386", "helicase activity", "molecular_function"),
        ("GO:0005524", "ATP binding", "molecular_function"),
    ],
    "RNA_helicase": [
        ("GO:0003724", "RNA helicase activity", "molecular_function"),
        ("GO:0005524", "ATP binding", "molecular_function"),
    ],
    "DEAD": [
        ("GO:0004386", "helicase activity", "molecular_function"),
        ("GO:0005524", "ATP binding", "molecular_function"),
    ],
    "CoV_Nsp13-helicase": [
        ("GO:0004386", "helicase activity", "molecular_function"),
        ("GO:0005524", "ATP binding", "molecular_function"),
    ],
    "DEXDc": [
        ("GO:0004386", "helicase activity", "molecular_function"),
        ("GO:0005524", "ATP binding", "molecular_function"),
    ],
    "ZBD_UPF1_nv_SF1_Hel-like": [
        ("GO:0004386", "helicase activity", "molecular_function"),
        ("GO:0000166", "nucleotide binding", "molecular_function"),
    ],

    # === Protease / Peptidase ===
    "Protease": [
        ("GO:0008233", "peptidase activity", "molecular_function"),
        ("GO:0006508", "proteolysis", "biological_process"),
    ],
    "Protease_domain": [
        ("GO:0008233", "peptidase activity", "molecular_function"),
        ("GO:0006508", "proteolysis", "biological_process"),
    ],
    "Ntn_hydrolase": [
        ("GO:0016787", "hydrolase activity", "molecular_function"),
    ],

    # === Capsid / Coat ===
    "Capsid_domain": [
        ("GO:0019028", "viral capsid", "cellular_component"),
        ("GO:0005198", "structural molecule activity", "molecular_function"),
    ],
    "Capsid_protein": [
        ("GO:0019028", "viral capsid", "cellular_component"),
        ("GO:0005198", "structural molecule activity", "molecular_function"),
    ],
    "Coat_protein": [
        ("GO:0019028", "viral capsid", "cellular_component"),
        ("GO:0005198", "structural molecule activity", "molecular_function"),
    ],
    "CRPV_capsid": [
        ("GO:0019028", "viral capsid", "cellular_component"),
    ],
    "IHHNV_capsid": [
        ("GO:0019028", "viral capsid", "cellular_component"),
    ],
    "rhv_like": [
        ("GO:0019028", "viral capsid", "cellular_component"),
        ("GO:0005198", "structural molecule activity", "molecular_function"),
    ],
    "LA-virus_coat": [
        ("GO:0019028", "viral capsid", "cellular_component"),
        ("GO:0005198", "structural molecule activity", "molecular_function"),
    ],
    "Viral_coat": [
        ("GO:0019028", "viral capsid", "cellular_component"),
        ("GO:0005198", "structural molecule activity", "molecular_function"),
    ],

    # === Envelope ===
    "Envelope": [
        ("GO:0019031", "viral envelope", "cellular_component"),
        ("GO:0005886", "plasma membrane", "cellular_component"),
    ],
    "Envelope_domain": [
        ("GO:0019031", "viral envelope", "cellular_component"),
        ("GO:0005886", "plasma membrane", "cellular_component"),
    ],
    "Glycoprotein": [
        ("GO:0019031", "viral envelope", "cellular_component"),
        ("GO:0005886", "plasma membrane", "cellular_component"),
    ],

    # === DNA polymerase ===
    "DNA_polymerase": [
        ("GO:0003887", "DNA-directed DNA polymerase activity", "molecular_function"),
        ("GO:0003677", "DNA binding", "molecular_function"),
        ("GO:0006260", "DNA replication", "biological_process"),
    ],
    "PolB": [
        ("GO:0003887", "DNA-directed DNA polymerase activity", "molecular_function"),
        ("GO:0006260", "DNA replication", "biological_process"),
    ],
    "DnaQ_like_exo": [
        ("GO:0004527", "exonuclease activity", "molecular_function"),
        ("GO:0003887", "DNA-directed DNA polymerase activity", "molecular_function"),
    ],

    # === Reverse Transcriptase ===
    "RT_domain": [
        ("GO:0003964", "RNA-directed DNA polymerase activity", "molecular_function"),
    ],

    # === Integrase ===
    "Integrase": [
        ("GO:0008907", "integrase activity", "molecular_function"),
    ],
    "Integrase_domain": [
        ("GO:0008907", "integrase activity", "molecular_function"),
    ],
    "Rcat_RBR": [
        ("GO:0008907", "integrase activity", "molecular_function"),
    ],

    # === Nucleoprotein / RNA binding ===
    "Nucleoprotein": [
        ("GO:0003723", "RNA binding", "molecular_function"),
        ("GO:0019029", "viral nucleocapsid", "cellular_component"),
    ],
    "RNA_binding": [
        ("GO:0003723", "RNA binding", "molecular_function"),
    ],
    "dsrm": [
        ("GO:0003725", "double-stranded RNA binding", "molecular_function"),
    ],
    "DSRM_SF": [
        ("GO:0003725", "double-stranded RNA binding", "molecular_function"),
    ],

    # === Kinase ===
    "Kinase": [
        ("GO:0004672", "protein kinase activity", "molecular_function"),
        ("GO:0005524", "ATP binding", "molecular_function"),
    ],
    "PKc_like": [
        ("GO:0004672", "protein kinase activity", "molecular_function"),
        ("GO:0005524", "ATP binding", "molecular_function"),
    ],
    "Thymidine_kinase": [
        ("GO:0004797", "thymidine kinase activity", "molecular_function"),
        ("GO:0005524", "ATP binding", "molecular_function"),
    ],

    # === Methyltransferase ===
    "Methyltransferase_domain": [
        ("GO:0008168", "methyltransferase activity", "molecular_function"),
    ],
    "MTase": [
        ("GO:0008168", "methyltransferase activity", "molecular_function"),
    ],
    "Noda_Vmethyltr": [
        ("GO:0008168", "methyltransferase activity", "molecular_function"),
    ],

    # === ATPase / NTPase / nucleotide binding ===
    "ATPase": [
        ("GO:0016887", "ATP hydrolysis activity", "molecular_function"),
        ("GO:0005524", "ATP binding", "molecular_function"),
    ],
    "P-loop_NTPase": [
        ("GO:0000166", "nucleotide binding", "molecular_function"),
        ("GO:0005524", "ATP binding", "molecular_function"),
    ],
    "AAA_34": [
        ("GO:0000166", "nucleotide binding", "molecular_function"),
        ("GO:0016887", "ATP hydrolysis activity", "molecular_function"),
    ],
    "ATP_binding": [
        ("GO:0005524", "ATP binding", "molecular_function"),
    ],
    "Viral_Rep": [
        ("GO:0000166", "nucleotide binding", "molecular_function"),
        ("GO:0004386", "helicase activity", "molecular_function"),
    ],

    # === Endonuclease / Nuclease / RNase ===
    "Endonuclease": [
        ("GO:0004519", "endonuclease activity", "molecular_function"),
        ("GO:0090305", "nucleic acid phosphodiester bond hydrolysis", "biological_process"),
    ],
    "Endonuclease_NS": [
        ("GO:0004519", "endonuclease activity", "molecular_function"),
    ],
    "Nuclease": [
        ("GO:0004518", "nuclease activity", "molecular_function"),
    ],
    "RNase": [
        ("GO:0004540", "ribonuclease activity", "molecular_function"),
    ],
    "GIY-YIG_SF": [
        ("GO:0004519", "endonuclease activity", "molecular_function"),
    ],

    # === Exonuclease ===
    "Exonuclease": [
        ("GO:0004527", "exonuclease activity", "molecular_function"),
    ],

    # === dUTPase ===
    "dUTPase_domain": [
        ("GO:0004170", "dUTP diphosphatase activity", "molecular_function"),
        ("GO:0046080", "dUTP catabolic process", "biological_process"),
    ],
    "dUTPase": [
        ("GO:0004170", "dUTP diphosphatase activity", "molecular_function"),
    ],
    "dut": [
        ("GO:0004170", "dUTP diphosphatase activity", "molecular_function"),
    ],
    "trimeric_dUTPase": [
        ("GO:0004170", "dUTP diphosphatase activity", "molecular_function"),
    ],

    # === Zinc finger / RING ===
    "RING_domain": [
        ("GO:0008270", "zinc ion binding", "molecular_function"),
        ("GO:0061630", "ubiquitin protein ligase activity", "molecular_function"),
    ],
    "RING_finger": [
        ("GO:0008270", "zinc ion binding", "molecular_function"),
    ],
    "RING-H2": [
        ("GO:0008270", "zinc ion binding", "molecular_function"),
    ],
    "RING_Ubox": [
        ("GO:0008270", "zinc ion binding", "molecular_function"),
    ],
    "zf-RING_2": [
        ("GO:0008270", "zinc ion binding", "molecular_function"),
    ],
    "zf-TAZ": [
        ("GO:0008270", "zinc ion binding", "molecular_function"),
    ],
    "Zinc_finger": [
        ("GO:0008270", "zinc ion binding", "molecular_function"),
    ],
    "RING-HC": [
        ("GO:0008270", "zinc ion binding", "molecular_function"),
    ],
    "bZIP": [
        ("GO:0046983", "protein dimerization activity", "molecular_function"),
        ("GO:0003700", "DNA-binding transcription factor activity", "molecular_function"),
    ],

    # === DNA binding ===
    "DNA_binding": [
        ("GO:0003677", "DNA binding", "molecular_function"),
    ],
    "HMG_box": [
        ("GO:0003677", "DNA binding", "molecular_function"),
    ],
    "HMG-box_SF": [
        ("GO:0003677", "DNA binding", "molecular_function"),
    ],
    "HMG-box_HMGB_rpt1": [
        ("GO:0003677", "DNA binding", "molecular_function"),
    ],

    # === Ligase ===
    "Ligase": [
        ("GO:0016874", "ligase activity", "molecular_function"),
    ],

    # === Phosphatase ===
    "Phosphatase": [
        ("GO:0016791", "phosphatase activity", "molecular_function"),
    ],

    # === Helicase C-terminal ===
    "RMtype1_S_TRD-CR_like": [
        ("GO:0003677", "DNA binding", "molecular_function"),
        ("GO:0005524", "ATP binding", "molecular_function"),
    ],

    # === Transposase ===
    "Transposase": [
        ("GO:0004803", "transposase activity", "molecular_function"),
        ("GO:0006313", "transposition, DNA-mediated", "biological_process"),
    ],
    "transpos_IS4_2": [
        ("GO:0004803", "transposase activity", "molecular_function"),
    ],

    # === Ribonucleotide reductase ===
    "RNR": [
        ("GO:0004748", "ribonucleoside-diphosphate reductase activity", "molecular_function"),
        ("GO:0006260", "DNA replication", "biological_process"),
    ],
    "RNR_PFL": [
        ("GO:0004748", "ribonucleoside-diphosphate reductase activity", "molecular_function"),
    ],
    "Ribonuc_red_lgC": [
        ("GO:0004748", "ribonucleoside-diphosphate reductase activity", "molecular_function"),
    ],

    # === Polyprotein ===
    "Polyprotein": [
        ("GO:0005198", "structural molecule activity", "molecular_function"),
        ("GO:0006508", "proteolysis", "biological_process"),
    ],
    "Structural_polyprotein": [
        ("GO:0005198", "structural molecule activity", "molecular_function"),
    ],

    # === Functional categories ===
    "Func_structural": [
        ("GO:0005198", "structural molecule activity", "molecular_function"),
    ],
    "Func_replication": [
        ("GO:0006260", "DNA replication", "biological_process"),
        ("GO:0006351", "transcription, DNA-templated", "biological_process"),
    ],
    "Func_metabolism": [
        ("GO:0008152", "metabolic process", "biological_process"),
    ],
    "Func_host_interaction": [
        ("GO:0051701", "interaction with host", "biological_process"),
    ],
    "Nonstructural": [
        ("GO:0003723", "RNA binding", "molecular_function"),
    ],

    # === Membrane / Transmembrane ===
    "Transmembrane": [
        ("GO:0016021", "integral component of membrane", "cellular_component"),
        ("GO:0005886", "plasma membrane", "cellular_component"),
    ],
    "Membrane_protein": [
        ("GO:0016020", "membrane", "cellular_component"),
    ],

    # === Replicase ===
    "Replicase": [
        ("GO:0003968", "RNA-directed RNA polymerase activity", "molecular_function"),
        ("GO:0003723", "RNA binding", "molecular_function"),
    ],

    # === Structural proteins ===
    "VP1": [
        ("GO:0019028", "viral capsid", "cellular_component"),
        ("GO:0005198", "structural molecule activity", "molecular_function"),
    ],
    "VP2": [
        ("GO:0019028", "viral capsid", "cellular_component"),
        ("GO:0005198", "structural molecule activity", "molecular_function"),
    ],
    "VP3": [
        ("GO:0019028", "viral capsid", "cellular_component"),
    ],
    "VP4": [
        ("GO:0019028", "viral capsid", "cellular_component"),
    ],
    "VP9": [
        ("GO:0019028", "viral capsid", "cellular_component"),
    ],
    "MSV199": [
        ("GO:0016020", "membrane", "cellular_component"),
    ],
    "WSS_VP": [
        ("GO:0019028", "viral capsid", "cellular_component"),
    ],
    "Dicistro_VP4": [
        ("GO:0019028", "viral capsid", "cellular_component"),
    ],

    # === Host interaction / immune evasion ===
    "IE": [
        ("GO:0051701", "interaction with host", "biological_process"),
    ],
    "B2": [
        ("GO:0003725", "double-stranded RNA binding", "molecular_function"),
        ("GO:0046794", "suppression by virus of host RNAi", "biological_process"),
    ],
    "IAP": [
        ("GO:0002020", "protease binding", "molecular_function"),
        ("GO:0043154", "negative regulation of cysteine-type endopeptidase activity", "biological_process"),
    ],

    # === Macro domain / ADP-ribose binding ===
    "Macro_SF": [
        ("GO:1990405", "protein ADP-ribosylase activity", "molecular_function"),
    ],

    # === Ankyrin ===
    "ANKYR": [
        ("GO:0005515", "protein binding", "molecular_function"),
    ],

    # === Ferritin-like ===
    "Ferritin_like": [
        ("GO:0008199", "ferric iron binding", "molecular_function"),
        ("GO:0006879", "intracellular iron ion homeostasis", "biological_process"),
    ],

    # === Collagen ===
    "Collagen": [
        ("GO:0005581", "collagen trimer", "cellular_component"),
    ],

    # === Matrix ===
    "Matrix": [
        ("GO:0016020", "membrane", "cellular_component"),
    ],

    # === Ubiquitin ===
    "Ubiquitin": [
        ("GO:0005515", "protein binding", "molecular_function"),
        ("GO:0016567", "protein ubiquitination", "biological_process"),
    ],

    # === WD40 ===
    "WD40": [
        ("GO:0005515", "protein binding", "molecular_function"),
    ],

    # === DNA packaging ===
    "DNA_pack_C": [
        ("GO:0003677", "DNA binding", "molecular_function"),
        ("GO:0019069", "viral genome packaging", "biological_process"),
    ],

    # === Topoisomerase ===
    "Topoisomer_IB_N": [
        ("GO:0003917", "DNA topoisomerase type I (single strand cut, ATP-independent) activity", "molecular_function"),
        ("GO:0006265", "DNA topological change", "biological_process"),
    ],

    # === Endonuclease/reverse transcriptase ===
    "RT_domain": [
        ("GO:0003964", "RNA-directed DNA polymerase activity", "molecular_function"),
    ],

    # === NTP transferase / NTase ===
    "NTase": [
        ("GO:0016779", "nucleotidyltransferase activity", "molecular_function"),
    ],

    # === Signal peptide ===
    "Signal_peptide": [
        ("GO:0005048", "signal sequence binding", "molecular_function"),
    ],

    # === NADAR ===
    "NADAR": [
        ("GO:0016740", "transferase activity", "molecular_function"),
    ],

    # === Hsp70 / Chaperone ===
    "HSP70": [
        ("GO:0005524", "ATP binding", "molecular_function"),
        ("GO:0051082", "unfolded protein binding", "molecular_function"),
    ],

    # === SMC protein ===
    "Smc": [
        ("GO:0005524", "ATP binding", "molecular_function"),
        ("GO:0007059", "chromosome segregation", "biological_process"),
    ],

    # === ATP cone domain ===
    "ATP-cone": [
        ("GO:0005524", "ATP binding", "molecular_function"),
    ],

    # === Thioredoxin ===
    "TRX_family": [
        ("GO:0015035", "protein-disulfide reductase activity", "molecular_function"),
    ],

    # === PDI (protein disulfide isomerase) ===
    "PDI_a_family": [
        ("GO:0003756", "protein disulfide isomerase activity", "molecular_function"),
    ],

    # === Translation-related ===
    "eIF_4EBP": [
        ("GO:0003743", "translation initiation factor activity", "molecular_function"),
    ],

    # === HRD1 (ubiquitin ligase) ===
    "HRD1": [
        ("GO:0061630", "ubiquitin protein ligase activity", "molecular_function"),
        ("GO:0008270", "zinc ion binding", "molecular_function"),
    ],

    # === Endonuclease/reverse transcriptase ===
    "BIR": [
        ("GO:0005515", "protein binding", "molecular_function"),
        ("GO:0043027", "cysteine-type endopeptidase inhibitor activity", "molecular_function"),
    ],

    # === Apolipoprotein ===
    "Apolipoprotein": [
        ("GO:0034364", "high-density lipoprotein particle", "cellular_component"),
    ],

    # === Thymidylate synthase ===
    "Thymidylat_synt": [
        ("GO:0004799", "thymidylate synthase activity", "molecular_function"),
    ],
    "TS": [
        ("GO:0004799", "thymidylate synthase activity", "molecular_function"),
    ],

    # === NUDIX hydrolase ===
    "NUDIX_Hydrolase": [
        ("GO:0016787", "hydrolase activity", "molecular_function"),
    ],

    # === DUF (domain unknown function) / uncharacterized ===
    "DUF1335": [
        ("GO:0003674", "molecular_function", "molecular_function"),
    ],
    "DUF5757": [],
    "DUF5767": [],
    "DUF5770": [],
    "DUF5832": [],
    "DUF5850": [],
    "Func_unknown": [],

    # === Uncharacterized / generic ===
    "Func_unknown": [],
    "DUF1335": [],
    "DUF382": [],
    "DUF5757": [],
    "DUF5767": [],
    "DUF5770": [],
    "DUF5832": [],
    "DUF5850": [],

    # === Viral structural components ===
    "PspA_IM30": [
        ("GO:0005886", "plasma membrane", "cellular_component"),
    ],
    "gly_rich_SclB": [
        ("GO:0005198", "structural molecule activity", "molecular_function"),
    ],

    # === Chroparvo / Parvovirus ===
    "Chropara_Vmeth": [
        ("GO:0008168", "methyltransferase activity", "molecular_function"),
    ],
    "DiSB-ORF2_chro": [
        ("GO:0003677", "DNA binding", "molecular_function"),
    ],

    # === Miscellaneous conserved domains ===
    "COG3177": [
        ("GO:0016787", "hydrolase activity", "molecular_function"),
    ],
    "PRK10787": [],
    "PRK12438": [],
    "PRK12323": [],
    "PRK00449": [],
    "COG2433": [],
    "COG4372": [],
    "PHA03126": [],
    "PHA00430": [],
}

# =========================================================================
# 2. FUZZY NAME MATCHING RULES
#    Applied when exact domain_name is not found
# =========================================================================

FUZZY_RULES = [
    # (pattern, GO list, name_tag)
    (r"RdRp|RNA_dep.*RNA_pol|RNA_polymerase|RNA-directed|Replicase", [
        ("GO:0003968", "RNA-directed RNA polymerase activity", "molecular_function"),
        ("GO:0003723", "RNA binding", "molecular_function"),
    ]),
    (r"DNA_polymerase|DNA_dep.*DNA_pol|DNA-directed_DNA", [
        ("GO:0003887", "DNA-directed DNA polymerase activity", "molecular_function"),
        ("GO:0003677", "DNA binding", "molecular_function"),
        ("GO:0006260", "DNA replication", "biological_process"),
    ]),
    (r"Reverse_transcri|RT_domain|RNA_dep.*DNA", [
        ("GO:0003964", "RNA-directed DNA polymerase activity", "molecular_function"),
    ]),
    (r"helicase|HELICASE|DEAD|DEAH|DEXD|Helic", [
        ("GO:0004386", "helicase activity", "molecular_function"),
        ("GO:0005524", "ATP binding", "molecular_function"),
    ]),
    (r"protease|peptidase|PROTEASE|PEPTIDASE|Ntn_hydro", [
        ("GO:0008233", "peptidase activity", "molecular_function"),
        ("GO:0006508", "proteolysis", "biological_process"),
    ]),
    (r"capsid|CAPSID|coat_protein|COAT|Viral_coat", [
        ("GO:0019028", "viral capsid", "cellular_component"),
        ("GO:0005198", "structural molecule activity", "molecular_function"),
    ]),
    (r"envelope|ENVELOPE|glycoprotein|GLYCOPROTEIN", [
        ("GO:0019031", "viral envelope", "cellular_component"),
        ("GO:0005886", "plasma membrane", "cellular_component"),
    ]),
    (r"kinase|KINASE|PKc_like", [
        ("GO:0004672", "protein kinase activity", "molecular_function"),
        ("GO:0005524", "ATP binding", "molecular_function"),
    ]),
    (r"methyltransfer|MTase|methylase|Methyltr", [
        ("GO:0008168", "methyltransferase activity", "molecular_function"),
    ]),
    (r"endonuclease|ENDONUCLEASE|GIY-YIG|Nuclease", [
        ("GO:0004519", "endonuclease activity", "molecular_function"),
        ("GO:0090305", "nucleic acid phosphodiester bond hydrolysis", "biological_process"),
    ]),
    (r"exonuclease|EXONUCLEASE", [
        ("GO:0004527", "exonuclease activity", "molecular_function"),
    ]),
    (r"integrase|INTEGRASE", [
        ("GO:0008907", "integrase activity", "molecular_function"),
    ]),
    (r"ribonuclease|RNase|RNase", [
        ("GO:0004540", "ribonuclease activity", "molecular_function"),
    ]),
    (r"ATPase|ATPase|ATP_binding|ATP-binding", [
        ("GO:0005524", "ATP binding", "molecular_function"),
        ("GO:0016887", "ATP hydrolysis activity", "molecular_function"),
    ]),
    (r"ligase|LIGASE|Ligase", [
        ("GO:0016874", "ligase activity", "molecular_function"),
    ]),
    (r"phosphatase|PHOSPHATASE", [
        ("GO:0016791", "phosphatase activity", "molecular_function"),
    ]),
    (r"transposase|TRANSPOSASE|transpos", [
        ("GO:0004803", "transposase activity", "molecular_function"),
        ("GO:0006313", "transposition, DNA-mediated", "biological_process"),
    ]),
    (r"nucleoprotein|NUCLEOPROTEIN|nucleocapsid", [
        ("GO:0003723", "RNA binding", "molecular_function"),
        ("GO:0019029", "viral nucleocapsid", "cellular_component"),
    ]),
    (r"RING|zinc_finger|Zinc_finger|zf-", [
        ("GO:0008270", "zinc ion binding", "molecular_function"),
    ]),
    (r"transmembrane|TRANSMEMBRANE|membrane|MEMBRANE", [
        ("GO:0016021", "integral component of membrane", "cellular_component"),
    ]),
    (r"dUTPase|dUTP", [
        ("GO:0004170", "dUTP diphosphatase activity", "molecular_function"),
        ("GO:0046080", "dUTP catabolic process", "biological_process"),
    ]),
    (r"thymidine_kinase|Thymidine_kinase|thymidylat|thymidylate_synth", [
        ("GO:0004797", "thymidine kinase activity", "molecular_function"),
        ("GO:0005524", "ATP binding", "molecular_function"),
    ]),
    (r"DNA_binding|DNA-binding|HMG.box", [
        ("GO:0003677", "DNA binding", "molecular_function"),
    ]),
    (r"RNA_binding|RNA-binding|dsrm|DSRM", [
        ("GO:0003723", "RNA binding", "molecular_function"),
    ]),
    (r"P-loop_NTPase|nucleotide_binding|NTPase", [
        ("GO:0000166", "nucleotide binding", "molecular_function"),
        ("GO:0005524", "ATP binding", "molecular_function"),
    ]),
    (r"ribonucleotide_reductase|RNR|Ribonuc_red", [
        ("GO:0004748", "ribonucleoside-diphosphate reductase activity", "molecular_function"),
    ]),
    (r"polyprotein|POLYPROTEIN|Polyprotein", [
        ("GO:0005198", "structural molecule activity", "molecular_function"),
        ("GO:0006508", "proteolysis", "biological_process"),
    ]),
    (r"VP[0-9]|capsid_protein|Capsid_protein", [
        ("GO:0019028", "viral capsid", "cellular_component"),
        ("GO:0005198", "structural molecule activity", "molecular_function"),
    ]),
    (r"ubiquitin|UBIQUITIN|Ubl", [
        ("GO:0005515", "protein binding", "molecular_function"),
        ("GO:0016567", "protein ubiquitination", "biological_process"),
    ]),
    (r"kinase|KINASE|kinase", [
        ("GO:0004672", "protein kinase activity", "molecular_function"),
        ("GO:0005524", "ATP binding", "molecular_function"),
    ]),
    (r"topoisomer|TOPOISOMER|Topoisomer", [
        ("GO:0003916", "DNA topoisomerase activity", "molecular_function"),
    ]),
    (r"helicase|HELICASE|Helicase", [
        ("GO:0004386", "helicase activity", "molecular_function"),
        ("GO:0005524", "ATP binding", "molecular_function"),
    ]),
]

# =========================================================================
# 3. DOMAIN-TO-KEGG MAPPING
# =========================================================================

DOMAIN_KEGG_MAP = {
    "RdRp": ("K00979", "RNA-directed RNA polymerase", "EC:2.7.7.48"),
    "RdRp_domain": ("K00979", "RNA-directed RNA polymerase", "EC:2.7.7.48"),
    "RdRp_replication": ("K00979", "RNA-directed RNA polymerase", "EC:2.7.7.48"),
    "Func_RdRP": ("K00979", "RNA-directed RNA polymerase", "EC:2.7.7.48"),
    "ps-ssRNAv_RdRp-like": ("K00979", "RNA-directed RNA polymerase", "EC:2.7.7.48"),
    "RNA_polymerase": ("K00979", "RNA-directed RNA polymerase", "EC:2.7.7.48"),
    "Replicase": ("K00979", "RNA-directed RNA polymerase", "EC:2.7.7.48"),
    "DNA_polymerase": ("K02335", "DNA-directed DNA polymerase", "EC:2.7.7.7"),
    "PolB": ("K02335", "DNA-directed DNA polymerase", "EC:2.7.7.7"),
    "Helicase": ("K10734", "ATP-dependent DNA helicase", "EC:3.6.4.12"),
    "Helicase_domain": ("K10734", "ATP-dependent DNA helicase", "EC:3.6.4.12"),
    "RNA_helicase": ("K10734", "ATP-dependent RNA helicase", "EC:3.6.4.13"),
    "Protease": ("K01362", "peptidase", "EC:3.4.-.-"),
    "Protease_domain": ("K01362", "peptidase", "EC:3.4.-.-"),
    "Thymidine_kinase": ("K00857", "thymidine kinase", "EC:2.7.1.21"),
    "Kinase": ("K00873", "protein kinase", "EC:2.7.11.1"),
    "PKc_like": ("K00873", "protein kinase", "EC:2.7.11.1"),
    "RT_domain": ("K00981", "reverse transcriptase", "EC:2.7.7.49"),
    "Integrase": ("K03793", "integrase", "EC:2.7.7.-"),
    "Integrase_domain": ("K03793", "integrase", "EC:2.7.7.-"),
    "dUTPase": ("K01520", "dUTP diphosphatase", "EC:3.6.1.23"),
    "dUTPase_domain": ("K01520", "dUTP diphosphatase", "EC:3.6.1.23"),
    "dut": ("K01520", "dUTP diphosphatase", "EC:3.6.1.23"),
    "trimeric_dUTPase": ("K01520", "dUTP diphosphatase", "EC:3.6.1.23"),
    "Endonuclease": ("K01151", "endonuclease", "EC:3.1.-.-"),
    "Endonuclease_NS": ("K01151", "endonuclease", "EC:3.1.-.-"),
    "RNase": ("K01351", "ribonuclease", "EC:3.1.-.-"),
    "Exonuclease": ("K01358", "exonuclease", "EC:3.1.-.-"),
    "Methyltransferase_domain": ("K00558", "methyltransferase", "EC:2.1.1.-"),
    "MTase": ("K00558", "methyltransferase", "EC:2.1.1.-"),
    "Noda_Vmethyltr": ("K00558", "methyltransferase", "EC:2.1.1.-"),
    "ATPase": ("K01525", "ATPase", "EC:3.6.3.-"),
    "Thymidylat_synt": ("K00560", "thymidylate synthase", "EC:2.1.1.45"),
    "TS": ("K00560", "thymidylate synthase", "EC:2.1.1.45"),
    "Ribonuc_red_lgC": ("K00525", "ribonucleoside-diphosphate reductase", "EC:1.17.4.1"),
    "RNR": ("K00525", "ribonucleoside-diphosphate reductase", "EC:1.17.4.1"),
    "RNR_PFL": ("K00525", "ribonucleoside-diphosphate reductase", "EC:1.17.4.1"),
    "Topoisomer_IB_N": ("K03164", "DNA topoisomerase I", "EC:5.99.1.2"),
    "Ligase": ("K01897", "ligase", "EC:6.-.-.-"),
    "Phosphatase": ("K01077", "phosphatase", "EC:3.1.3.-"),
    "Transposase": ("K07496", "transposase", ""),
    "transpos_IS4_2": ("K07496", "transposase", ""),
}


def get_go_terms_for_domain(domain_name, domain_description):
    """Get GO annotations for a domain name using exact + fuzzy matching."""
    if not domain_name:
        return []

    # 1. Try exact match
    if domain_name in DOMAIN_GO_MAP:
        return DOMAIN_GO_MAP[domain_name]

    # 2. Try fuzzy match on domain_name
    for pattern, go_list in FUZZY_RULES:
        if re.search(pattern, domain_name, re.IGNORECASE):
            return go_list

    # 3. Try fuzzy match on domain_description if available
    if domain_description:
        for pattern, go_list in FUZZY_RULES:
            if re.search(pattern, domain_description, re.IGNORECASE):
                return go_list

    return []


def get_kegg_for_domain(domain_name):
    """Get KEGG annotation for a domain."""
    if not domain_name:
        return None
    if domain_name in DOMAIN_KEGG_MAP:
        return DOMAIN_KEGG_MAP[domain_name]
    # Fuzzy match
    if re.search(r"helicase|HELICASE", domain_name):
        return DOMAIN_KEGG_MAP.get("Helicase")
    if re.search(r"RdRp|RNA_polymerase|RNA-directed|Replicase", domain_name):
        return DOMAIN_KEGG_MAP.get("RdRp")
    if re.search(r"DNA_polymerase|PolB", domain_name):
        return DOMAIN_KEGG_MAP.get("DNA_polymerase")
    if re.search(r"protease|peptidase", domain_name, re.IGNORECASE):
        return DOMAIN_KEGG_MAP.get("Protease")
    if re.search(r"kinase|KINASE|PKc", domain_name):
        return DOMAIN_KEGG_MAP.get("Kinase")
    if re.search(r"endonuclease|nuclease|Endonuclease", domain_name, re.IGNORECASE):
        return DOMAIN_KEGG_MAP.get("Endonuclease")
    if re.search(r"dUTP|dut", domain_name, re.IGNORECASE):
        return DOMAIN_KEGG_MAP.get("dUTPase")
    if re.search(r"methyltransferase|MTase|Methyltr", domain_name, re.IGNORECASE):
        return DOMAIN_KEGG_MAP.get("MTase")
    return None


def main():
    conn = sqlite3.connect(DB_PATH)
    # Ensure we can write - force checkpoint and use DELETE mode
    conn.execute("PRAGMA journal_mode=DELETE")
    conn.execute("PRAGMA synchronous=OFF")
    conn.execute("BEGIN TRANSACTION")
    c = conn.cursor()

    # =====================================================================
    # A. Get all distinct domain assignments (protein_id, domain_name,
    #    domain_description, domain_source, interpro_id, pfam_id, cdd_id)
    # =====================================================================
    c.execute("""
        SELECT DISTINCT pd.protein_id, pd.domain_name,
               pd.domain_description, pd.domain_source,
               pd.interpro_id, pd.pfam_id, pd.cdd_id
        FROM protein_domains pd
        WHERE pd.protein_id IS NOT NULL AND pd.domain_name IS NOT NULL
    """)
    rows = c.fetchall()
    total = len(rows)
    print(f"Loaded {total} distinct domain assignments")

    # Counters
    proteins_with_annotations = set()
    proteins_with_go = set()
    go_assignments = 0
    interpro_assignments = 0
    kegg_assignments = 0
    skipped_no_match = 0
    skipped_exists = 0
    inserted_interpro = 0
    inserted_go = 0
    inserted_kegg = 0

    # Pre-check which proteins already have data
    c.execute("SELECT DISTINCT protein_id FROM interpro_annotations WHERE protein_id IS NOT NULL")
    existing_anno = {row[0] for row in c.fetchall()}
    c.execute("SELECT DISTINCT protein_id FROM interpro_go_terms WHERE protein_id IS NOT NULL")
    existing_go = {row[0] for row in c.fetchall()}
    c.execute("SELECT DISTINCT protein_id FROM kegg_annotations WHERE protein_id IS NOT NULL")
    existing_kegg = {row[0] for row in c.fetchall()}

    # Also track existing (protein_id, go_id) combos to avoid duplicates
    c.execute("SELECT DISTINCT protein_id, go_id FROM interpro_go_terms WHERE protein_id IS NOT NULL")
    existing_go_combos = {(row[0], row[1]) for row in c.fetchall()}

    # Track existing (protein_id, interpro_id) combos
    c.execute("SELECT DISTINCT protein_id, interpro_id FROM interpro_annotations WHERE protein_id IS NOT NULL AND interpro_id IS NOT NULL")
    existing_interpro_combos = {(row[0], row[1]) for row in c.fetchall()}

    # Pre-fetch protein accessions for kegg and uniprot mapping
    c.execute("SELECT protein_id, protein_accession FROM viral_proteins")
    protein_accessions = {row[0]: row[1] for row in c.fetchall()}

    # Build uniprot_id mapping from uniprot_protein_links
    c.execute("""
        SELECT upl.protein_id, upl.uniprot_id
        FROM uniprot_protein_links upl
        WHERE upl.protein_id IS NOT NULL
    """)
    uniprot_map = {}
    for pid, uid in c.fetchall():
        if pid not in uniprot_map:
            uniprot_map[pid] = uid

    # For remaining, use protein_accession as fallback
    for pid, acc in protein_accessions.items():
        if pid not in uniprot_map and acc:
            uniprot_map[pid] = acc

    batch_size = 500
    interpro_batch = []
    go_batch = []
    kegg_batch = []

    for idx, (protein_id, domain_name, domain_description, domain_source,
               interpro_id, pfam_id, cdd_id) in enumerate(rows):

        if (idx + 1) % 10000 == 0:
            print(f"  Processing {idx + 1}/{total}...")

        domain_id_use = interpro_id or pfam_id or cdd_id or domain_name
        uniprot_id = uniprot_map.get(protein_id, f"protein_{protein_id}")

        # --- INTERPRO_ANNOTATIONS ---
        combo = (protein_id, domain_id_use)
        if combo not in existing_interpro_combos:
            interpro_batch.append((
                uniprot_id,
                protein_id,
                domain_id_use,
                domain_name,
                domain_source,
                None, None, None,
                "", "",
            ))
            existing_interpro_combos.add(combo)
            interpro_assignments += 1
            proteins_with_annotations.add(protein_id)
        else:
            skipped_exists += 1

        # --- INTERPRO_GO_TERMS ---
        go_terms = get_go_terms_for_domain(domain_name, domain_description)
        for go_id, go_name, go_namespace in go_terms:
            go_combo = (protein_id, go_id)
            if go_combo not in existing_go_combos:
                go_batch.append((
                    protein_id,
                    domain_id_use,
                    go_id,
                    go_name,
                    go_namespace,
                    "IEA",
                ))
                existing_go_combos.add(go_combo)
                go_assignments += 1
                proteins_with_go.add(protein_id)
            else:
                skipped_exists += 1

        # --- KEGG_ANNOTATIONS ---
        if protein_id not in existing_kegg:
            kegg_info = get_kegg_for_domain(domain_name)
            if kegg_info:
                ko_id, ko_name, ec_number = kegg_info
                protein_acc = protein_accessions.get(protein_id, "")
                kegg_batch.append((
                    protein_acc,
                    None,
                    ec_number,
                    ko_id,
                    ko_name,
                    f"inferred: {ko_name}",
                    protein_id,
                ))
                kegg_assignments += 1

        # Flush batches
        if len(interpro_batch) >= batch_size:
            c.executemany("""
                INSERT INTO interpro_annotations
                    (uniprot_id, protein_id, interpro_id, interpro_name, source_database,
                     start_pos, end_pos, score, go_terms, pathways,
                     position_status, publication_use)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'coordinates_not_available_from_source', 'domain_presence_only_no_visualization')
            """, interpro_batch)
            inserted_interpro += len(interpro_batch)
            interpro_batch = []

        if len(go_batch) >= batch_size:
            c.executemany("""
                INSERT INTO interpro_go_terms
                    (protein_id, interpro_id, go_id, go_name, go_namespace, evidence_source)
                VALUES (?, ?, ?, ?, ?, ?)
            """, go_batch)
            inserted_go += len(go_batch)
            go_batch = []

        if len(kegg_batch) >= batch_size:
            c.executemany("""
                INSERT INTO kegg_annotations
                    (ncbi_protein_acc, uniprot_id, ec_number, ko_id, ko_name, ko_definition, protein_id)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, kegg_batch)
            inserted_kegg += len(kegg_batch)
            kegg_batch = []

    # Final flush
    if interpro_batch:
        c.executemany("""
            INSERT INTO interpro_annotations
                (uniprot_id, protein_id, interpro_id, interpro_name, source_database,
                 start_pos, end_pos, score, go_terms, pathways,
                 position_status, publication_use)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'coordinates_not_available_from_source', 'domain_presence_only_no_visualization')
        """, interpro_batch)
        inserted_interpro += len(interpro_batch)

    if go_batch:
        c.executemany("""
            INSERT INTO interpro_go_terms
                (protein_id, interpro_id, go_id, go_name, go_namespace, evidence_source)
            VALUES (?, ?, ?, ?, ?, ?)
        """, go_batch)
        inserted_go += len(go_batch)

    if kegg_batch:
        c.executemany("""
            INSERT INTO kegg_annotations
                (ncbi_protein_acc, uniprot_id, ec_number, ko_id, ko_name, ko_definition, protein_id)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, kegg_batch)
        inserted_kegg += len(kegg_batch)

    conn.commit()

    # =====================================================================
    # B. Print summary
    # =====================================================================
    print("\n" + "=" * 60)
    print("BACKFILL SUMMARY")
    print("=" * 60)

    print(f"\nTotal domain assignments processed: {total}")
    print(f"  - Interpro annotations inserted: {inserted_interpro}")
    print(f"  - GO terms inserted: {inserted_go}")
    print(f"  - KEGG annotations inserted: {inserted_kegg}")
    print(f"  - Skipped (already exists): {skipped_exists}")

    # Final counts
    c.execute("SELECT COUNT(DISTINCT protein_id) FROM interpro_annotations WHERE protein_id IS NOT NULL")
    final_anno = c.fetchone()[0]
    c.execute("SELECT COUNT(DISTINCT protein_id) FROM interpro_go_terms WHERE protein_id IS NOT NULL")
    final_go = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM interpro_go_terms WHERE protein_id IS NOT NULL")
    final_go_total = c.fetchone()[0]
    c.execute("SELECT COUNT(DISTINCT protein_id) FROM kegg_annotations WHERE protein_id IS NOT NULL")
    final_kegg = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM interpro_annotations WHERE protein_id IS NOT NULL")
    final_ia_total = c.fetchone()[0]

    c.execute("SELECT COUNT(DISTINCT protein_id) FROM protein_domains WHERE protein_id IS NOT NULL")
    total_with_domains = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM viral_proteins")
    total_proteins = c.fetchone()[0]

    print(f"\n=== Coverage: Before vs After ===")
    print(f"{'Metric':<45} {'Before':>8} {'After':>8} {'%':>8}")
    print("-" * 69)
    before_anno = len(existing_anno)
    print(f"{'Proteins with interpro_annotations':<45} {before_anno:>8} {final_anno:>8} {final_anno/total_proteins*100:>7.1f}%")
    before_go = len(existing_go)
    print(f"{'Proteins with interpro_go_terms':<45} {before_go:>8} {final_go:>8} {final_go/total_proteins*100:>7.1f}%")
    before_kegg = len(existing_kegg)
    print(f"{'Proteins with kegg_annotations':<45} {before_kegg:>8} {final_kegg:>8} {final_kegg/total_proteins*100:>7.1f}%" if final_kegg != before_kegg else
          f"{'Proteins with kegg_annotations':<45} {before_kegg:>8} {final_kegg:>8} {final_kegg/total_proteins*100:>7.1f}%")

    print(f"\nTotal interpro_annotations rows: {final_ia_total}")
    print(f"Total GO term assignments: {final_go_total}")
    print(f"Total viral proteins: {total_proteins}")

    # Top 10 GO terms by protein count
    print("\n=== Top 10 GO terms by protein count ===")
    for row in c.execute("""
        SELECT ig.go_id, ig.go_name, ig.go_namespace, COUNT(DISTINCT ig.protein_id) as cnt
        FROM interpro_go_terms ig
        WHERE ig.protein_id IS NOT NULL
        GROUP BY ig.go_id
        ORDER BY cnt DESC
        LIMIT 10
    """):
        print(f"  {row[0]} | {row[1]:<50} | {row[2]:<25} | {row[3]} proteins")

    conn.close()
    print("\nDone!")


if __name__ == "__main__":
    main()
