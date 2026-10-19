# Evidence extraction: software stack and rules

## Summary

Evidence statements were extracted with **custom Python scripts** (Python 3.12.7) using **regular expressions, token matching and rule-based scoring**, backed by SQLite. **No NLP library (spaCy, scispaCy or similar) and no large language model was used.** PDF text was parsed with **PyMuPDF 1.27.2.2**; all other processing used the Python standard library (`re`, `json`, `sqlite3`, `xml.etree`).

## Scripts

| Script | Role |
|---|---|
| `evidence_extraction/extract_smart_match.py` | Main production extractor; token index of virus names/abbreviations and sentence-level evidence signals |
| `evidence_extraction/text_mine_literature_abstracts.py` | Abstract-level text mining |
| `evidence_extraction/extract_evidence_v2.py` | Fuzzy-match extraction pass |
| `evidence_extraction/deep_fulltext_extraction.py` | Deep extraction from retrieved full texts |

## Rule families in `extract_smart_match.py`

```python
DIAG_RE = re.compile(r'\b(PCR|qPCR|RT[ -]?PCR|LAMP|ELISA|immunoassay|hybridization|western blot|metagenomic|NGS|diagnostic|TaqMan|SYBR|RPA|sequencing|phylogenetic|genome|ORF|RdRp)\b', re.I)
PATH_RE = re.compile(r'\b(mortalit|lethal|virulen|pathogenic|challenge|infection rate|survival rate|death|histopatholog|disease sign|symptom|LD50)\b', re.I)
TEMP_RE = re.compile(r'\b(temperatur|thermal|°C|℃|degree|heat shock)\b', re.I)
HOST_RE = re.compile(r'\b(infected|infection|susceptible|host|transmission|isolated from|detected in|tissue tropism|organ|prevalence)\b', re.I)
```

These four expression families correspond to the evidence categories **diagnosis**, **pathogenicity**, **temperature** and **host range**. A sentence is retained when a virus-name token and a category signal co-occur; the surrounding sentence is stored as the evidence claim.

## Extraction-method distribution (353,160 raw records)

Counts are from the `extraction_method` field of `evidence_records` in the frozen snapshot:

| Method | Records |
|---|---:|
| `smart_match_re_extract` | 287,930 (81.5%) |
| `literature_text_mine` | 17,862 |
| `evidence_v2_fuzzy_match` | 12,500 |
| `fulltext_parsed` | 9,349 |
| `fulltext_deep_extraction` | 8,001 |
| `fulltext_deep_extraction_v2` | 5,108 |
| `fulltext_parsed_p1` | 4,740 |
| `auto_extracted_epmc_abstract` | 2,442 |
| other named methods | 5,228 |
| **Total** | **353,160** |

The dominant route (`smart_match_re_extract`) accounts for 81.5% of raw records; full-text parsing methods together account for 27,198 records.

## What the pipeline does and does not do

- It records **where a statement pattern occurs** and stores the sentence; it does not infer structured facts such as titres, LD50 values or temperatures unless those values are present in the sentence.
- It does not assign evidence confidence; confidence/curation status is assigned downstream.
- It is deterministic for a fixed input corpus and database snapshot.

## Reproducibility caveats

- The scripts are the production versions but were not tagged with a semantic version; this package records their SHA-256 in `SHA256SUMS.txt`.
- The scripts expect the frozen database and cached full texts, which are distributed separately.
- Absolute paths at the top of each script must be adjusted before running.
