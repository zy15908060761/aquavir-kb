import math
import re
from pathlib import Path

BASE = Path(__file__).resolve().parent
FASTA = BASE / "external_data" / "interproscan" / "nr_protein_representatives.fasta"
OUT = BASE / "external_data" / "interproscan" / "batches"
OUT.mkdir(parents=True, exist_ok=True)

BATCH_SIZE = 1000


def read_fasta(path):
    header = None
    seq = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.rstrip()
            if line.startswith(">"):
                if header:
                    yield header, "".join(seq)
                header = line
                seq = []
            else:
                seq.append(line)
        if header:
            yield header, "".join(seq)


records = [(h, s) for h, s in read_fasta(FASTA) if len(s) >= 10]
for old in OUT.glob("batch_*.fasta"):
    old.unlink()

for i in range(0, len(records), BATCH_SIZE):
    batch = records[i : i + BATCH_SIZE]
    path = OUT / f"batch_{i // BATCH_SIZE + 1:03d}.fasta"
    with path.open("w", encoding="utf-8", newline="\n") as f:
        for h, s in batch:
            f.write(h + "\n")
            for j in range(0, len(s), 60):
                f.write(s[j : j + 60] + "\n")

script = OUT / "run_interproscan_batches_wsl.sh"
script.write_text(
    """#!/usr/bin/env bash
set -euo pipefail

IPRSCAN="${1:-/mnt/f/tools/interproscan/interproscan.sh}"
BATCH_DIR="$(cd "$(dirname "$0")" && pwd)"
OUT_DIR="$BATCH_DIR/results"
mkdir -p "$OUT_DIR"

for fasta in "$BATCH_DIR"/batch_*.fasta; do
  base="$(basename "$fasta" .fasta)"
  out="$OUT_DIR/${base}.tsv"
  if [[ -s "$out" ]]; then
    echo "[skip] $base already done"
    continue
  fi
  echo "[run] $base"
  "$IPRSCAN" -i "$fasta" -f TSV -o "$out" -cpu 4 -goterms -pa
done
""",
    encoding="utf-8",
)

readme = OUT / "README_interproscan_batches.md"
readme.write_text(
    f"""# InterProScan Batch Plan

Input FASTA: `{FASTA}`

Records: {len(records)}

Batch size: {BATCH_SIZE}

Batches: {math.ceil(len(records) / BATCH_SIZE)}

## WSL/Linux run

Install InterProScan, then run:

```bash
cd /mnt/f/甲壳动物数据库/external_data/interproscan/batches
bash run_interproscan_batches_wsl.sh /path/to/interproscan.sh
```

Outputs go to:

`{OUT / "results"}`

After TSV files are generated, import them with a parser into `interpro_annotations` and `interpro_go_terms`.
""",
    encoding="utf-8",
)

print({"records": len(records), "batch_size": BATCH_SIZE, "batches": math.ceil(len(records) / BATCH_SIZE), "out": str(OUT)})
