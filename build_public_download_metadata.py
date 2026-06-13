from __future__ import annotations

import csv
import hashlib
from datetime import datetime
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
PUBLIC_DIR = BASE_DIR / "public_downloads"
MAIN_PUBLIC_FILES = {
    "all_sequences.fasta",
    "complete_genomes.fasta",
    "crustacean_virus_metadata_standardized.xlsx",
    "host_virus_network.csv",
    "reviewed_evidence_records.xlsx",
    "DATA_USE_AGREEMENT.md",
    "LICENSE.txt",
    "CITATION.cff",
}
PHYLOGENY_PUBLIC_SUFFIXES = {".png", ".svg", ".contree", ".tree", ".nwk", ".newick"}
FORBIDDEN_PUBLIC_SUFFIXES = {".log", ".iqtree", ".mldist", ".splits", ".ckp", ".gz", ".model"}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def is_public_download_file(path: Path) -> bool:
    rel = path.relative_to(PUBLIC_DIR).as_posix()
    if path.name in {"SHA256SUMS.csv", "README.md"}:
        return True
    if "/" not in rel and path.name in MAIN_PUBLIC_FILES:
        return True
    if rel.startswith("phylogeny/"):
        if any(part in {"logs", "intermediate", "tmp"} for part in path.parts):
            return False
        if path.suffix.lower() in PHYLOGENY_PUBLIC_SUFFIXES:
            return True
    return False


def main() -> None:
    PUBLIC_DIR.mkdir(exist_ok=True)

    (PUBLIC_DIR / "README.md").write_text(
        "# CrustaVirus DB Public Downloads\n\n"
        f"Generated: {datetime.now().isoformat(timespec='seconds')}\n\n"
        "Files in this directory are release-filtered public artifacts. Candidate, inferred, and unreviewed evidence is not promoted as validated knowledge here.\n\n"
        "- `crustacean_virus_metadata_standardized.xlsx`: strict target isolate metadata.\n"
        "- `all_sequences.fasta`: FASTA sequences for strict target isolates with local sequence files.\n"
        "- `complete_genomes.fasta`: complete-genome strict target FASTA subset.\n"
        "- `host_virus_network.csv`: strict target host-virus edge table.\n"
        "- `reviewed_evidence_records.xlsx`: manual-checked evidence only; may be empty until curation is complete.\n"
        "- `phylogeny/`: generated phylogeny figures and final tree files used by the local web UI. Logs, alignments, and intermediate FASTA files are not public release files.\n"
        "- `SHA256SUMS.csv`: file size and checksum manifest.\n",
        encoding="utf-8",
    )

    (PUBLIC_DIR / "LICENSE.txt").write_text(
        "CrustaVirus DB public metadata is intended for release under CC BY 4.0 unless a source database imposes stricter terms. "
        "NCBI/UniProt/AlphaFold/GBIF/OBIS/Europe PMC derived records should be reused according to their original source licenses and attribution requirements.\n",
        encoding="utf-8",
    )

    (PUBLIC_DIR / "CITATION.cff").write_text(
        "cff-version: 1.2.0\n"
        "message: \"If you use CrustaVirus DB, please cite the database paper or release.\"\n"
        "title: \"CrustaVirus DB\"\n"
        "version: \"v1.0-rc\"\n"
        "date-released: \"" + datetime.now().date().isoformat() + "\"\n"
        "authors:\n"
        "  - family-names: \"CrustaVirus DB Team\"\n",
        encoding="utf-8",
    )

    files = sorted(
        path
        for path in PUBLIC_DIR.rglob("*")
        if path.is_file() and is_public_download_file(path) and path.name != "SHA256SUMS.csv"
    )

    with (PUBLIC_DIR / "SHA256SUMS.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["path", "bytes", "sha256"])
        writer.writeheader()
        for path in files:
            writer.writerow({
                "path": str(path.relative_to(PUBLIC_DIR)).replace("\\", "/"),
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            })

    print(PUBLIC_DIR)


if __name__ == "__main__":
    main()
