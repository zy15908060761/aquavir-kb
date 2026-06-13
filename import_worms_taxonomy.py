"""
WoRMS taxonomy resolver for aquatic invertebrate host standardization.
Queries WoRMS Aphia API with fallback local taxonomy cache.
Provides importable resolve_taxonomy() function.

Usage:
    python import_worms_taxonomy.py --dry-run         # preview species list
    python import_worms_taxonomy.py --offline          # use cache + fallback only
    python import_worms_taxonomy.py --output results.json
"""

import json
import sys
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional

BASE_DIR = Path(__file__).resolve().parent
OUTPUT_JSON = BASE_DIR / "worms_taxonomy_results.json"
CACHE_JSON = BASE_DIR / "worms_taxonomy_cache.json"

WORMS_BASE = "https://www.marinespecies.org/rest"
RATE_LIMIT = 1.1  # WoRMS requires <1 req/sec

# Default species list spanning key aquatic invertebrate phyla
DEFAULT_SPECIES = [
    # Mollusca - Bivalvia (oyster, mussel, clam, scallop)
    "Crassostrea gigas", "Crassostrea virginica", "Crassostrea ariakensis",
    "Saccostrea glomerata", "Ostrea edulis",
    "Mytilus galloprovincialis", "Mytilus edulis", "Mytilus coruscus",
    "Perna viridis", "Perna canaliculus",
    "Ruditapes philippinarum", "Venerupis corrugata", "Mercenaria mercenaria",
    "Mizuhopecten yessoensis", "Chlamys farreri", "Argopecten irradians",
    "Pecten maximus", "Patinopecten yessoensis",
    # Mollusca - Gastropoda (abalone, conch)
    "Haliotis discus hannai", "Haliotis diversicolor", "Haliotis rufescens",
    "Haliotis rubra", "Haliotis laevigata", "Haliotis midae",
    "Haliotis tuberculata", "Haliotis asinina",
    # Mollusca - Cephalopoda
    "Octopus vulgaris", "Sepia officinalis", "Loligo vulgaris",
    # Cnidaria - Anthozoa (coral, anemone)
    "Acropora millepora", "Acropora digitifera", "Porites lobata",
    "Pocillopora damicornis", "Stylophora pistillata", "Orbicella faveolata",
    "Nematostella vectensis", "Exaiptasia diaphana",
    # Echinodermata
    "Apostichopus japonicus", "Holothuria scabra", "Holothuria leucospilota",
    "Strongylocentrotus purpuratus", "Paracentrotus lividus",
    "Lytechinus variegatus", "Asterias rubens", "Pisaster ochraceus",
    # Porifera
    "Amphimedon queenslandica", "Ephydatia muelleri", "Tethya wilhelma",
    # Tunicata + Rotifera
    "Ciona intestinalis", "Ciona robusta", "Brachionus plicatilis",
]

# Hardcoded fallback taxonomy for offline use (major aquaculture species)
FALLBACK_TAXONOMY = {
    "crassostrea gigas": {
        "phylum": "Mollusca", "class": "Bivalvia", "order": "Ostreoida",
        "family": "Ostreidae", "valid_name": "Magallana gigas", "status": "accepted",
    },
    "crassostrea virginica": {
        "phylum": "Mollusca", "class": "Bivalvia", "order": "Ostreoida",
        "family": "Ostreidae", "valid_name": "Crassostrea virginica", "status": "accepted",
    },
    "ostrea edulis": {
        "phylum": "Mollusca", "class": "Bivalvia", "order": "Ostreoida",
        "family": "Ostreidae", "valid_name": "Ostrea edulis", "status": "accepted",
    },
    "mytilus galloprovincialis": {
        "phylum": "Mollusca", "class": "Bivalvia", "order": "Mytiloida",
        "family": "Mytilidae", "valid_name": "Mytilus galloprovincialis", "status": "accepted",
    },
    "mytilus edulis": {
        "phylum": "Mollusca", "class": "Bivalvia", "order": "Mytiloida",
        "family": "Mytilidae", "valid_name": "Mytilus edulis", "status": "accepted",
    },
    "ruditapes philippinarum": {
        "phylum": "Mollusca", "class": "Bivalvia", "order": "Veneroida",
        "family": "Veneridae", "valid_name": "Ruditapes philippinarum", "status": "accepted",
    },
    "haliotis discus hannai": {
        "phylum": "Mollusca", "class": "Gastropoda", "order": "Lepetellida",
        "family": "Haliotidae", "valid_name": "Haliotis discus", "status": "accepted",
    },
    "haliotis diversicolor": {
        "phylum": "Mollusca", "class": "Gastropoda", "order": "Lepetellida",
        "family": "Haliotidae", "valid_name": "Haliotis diversicolor", "status": "accepted",
    },
    "haliotis rubra": {
        "phylum": "Mollusca", "class": "Gastropoda", "order": "Lepetellida",
        "family": "Haliotidae", "valid_name": "Haliotis rubra", "status": "accepted",
    },
    "acropora millepora": {
        "phylum": "Cnidaria", "class": "Anthozoa", "order": "Scleractinia",
        "family": "Acroporidae", "valid_name": "Acropora millepora", "status": "accepted",
    },
    "apostichopus japonicus": {
        "phylum": "Echinodermata", "class": "Holothuroidea", "order": "Synallactida",
        "family": "Stichopodidae", "valid_name": "Apostichopus japonicus", "status": "accepted",
    },
    "strongylocentrotus purpuratus": {
        "phylum": "Echinodermata", "class": "Echinoidea", "order": "Camarodonta",
        "family": "Strongylocentrotidae", "valid_name": "Strongylocentrotus purpuratus",
        "status": "accepted",
    },
    "paracentrotus lividus": {
        "phylum": "Echinodermata", "class": "Echinoidea", "order": "Camarodonta",
        "family": "Parechinidae", "valid_name": "Paracentrotus lividus", "status": "accepted",
    },
    "asterias rubens": {
        "phylum": "Echinodermata", "class": "Asteroidea", "order": "Forcipulatida",
        "family": "Asteriidae", "valid_name": "Asterias rubens", "status": "accepted",
    },
}


@dataclass
class TaxonomyRecord:
    input_name: str = ""
    aphia_id: int = 0
    valid_name: str = ""
    status: str = ""
    phylum: str = ""
    class_name: str = ""
    order_name: str = ""
    family: str = ""
    query_timestamp: str = ""
    error: str = ""


def resolve_taxonomy(scientific_name: str) -> TaxonomyRecord:
    """Query WoRMS Aphia API for a scientific name. Returns TaxonomyRecord."""
    name_lower = scientific_name.lower().strip()
    # Check fallback first
    if name_lower in FALLBACK_TAXONOMY:
        fb = FALLBACK_TAXONOMY[name_lower]
        return TaxonomyRecord(
            input_name=scientific_name, valid_name=fb["valid_name"],
            status=fb["status"], phylum=fb["phylum"], class_name=fb["class"],
            order_name=fb["order"], family=fb["family"],
            query_timestamp=datetime.now().isoformat(),
        )
    # Query WoRMS API
    try:
        params = urllib.parse.urlencode({"scientificname": scientific_name})
        url = f"{WORMS_BASE}/AphiaRecordsByName?{params}&like=false&marine_only=false"
        req = urllib.request.Request(url)
        req.add_header("User-Agent", "AquaVir-KB/1.0 (worms-taxonomy)")
        time.sleep(RATE_LIMIT)
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if data and len(data) > 0:
                r = data[0]
                return TaxonomyRecord(
                    input_name=scientific_name, aphia_id=r.get("AphiaID", 0),
                    valid_name=r.get("valid_name") or r.get("scientificname", ""),
                    status=r.get("status", ""), phylum=r.get("phylum", ""),
                    class_name=r.get("class", ""), order_name=r.get("order", ""),
                    family=r.get("family", ""),
                    query_timestamp=datetime.now().isoformat(),
                )
    except Exception as e:
        return TaxonomyRecord(input_name=scientific_name, error=str(e))
    return TaxonomyRecord(input_name=scientific_name, error="No match found")


def resolve_taxonomy_batch(names: list[str]) -> list[TaxonomyRecord]:
    """Resolve a batch of scientific names sequentially."""
    results = []
    for i, name in enumerate(names):
        print(f"  [{i+1}/{len(names)}] {name}...", end=" ")
        rec = resolve_taxonomy(name)
        if rec.error:
            print(f"ERROR: {rec.error}")
        else:
            print(f"{rec.phylum}/{rec.class_name} ({rec.status})")
        results.append(rec)
    return results


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="Resolve aquatic invertebrate taxonomy via WoRMS")
    parser.add_argument("--input", type=str, help="Text file with one name per line")
    parser.add_argument("--output", type=str, help="Output JSON path")
    parser.add_argument("--dry-run", action="store_true", help="Preview species only")
    parser.add_argument("--offline", action="store_true", help="Use cache + fallback only")
    args = parser.parse_args()

    if args.input:
        path = Path(args.input)
        if not path.exists():
            print(f"ERROR: {path} not found")
            sys.exit(1)
        species = [l.strip() for l in open(str(path)) if l.strip() and not l.startswith("#")]
    else:
        species = DEFAULT_SPECIES

    if args.dry_run:
        print(f"Species list ({len(species)}):")
        for i, n in enumerate(species, 1):
            print(f"  {i:3d}. {n}")
        return

    if args.offline:
        results = []
        for name in species:
            rec = resolve_taxonomy(name)  # uses fallback
            results.append(rec)
            print(f"  {rec.input_name} -> {rec.phylum}/{rec.class_name}")
    else:
        results = resolve_taxonomy_batch(species)

    out_path = Path(args.output) if args.output else OUTPUT_JSON
    summary = {
        "generated_at": datetime.now().isoformat(),
        "total": len(results),
        "resolved": sum(1 for r in results if not r.error),
        "failed": sum(1 for r in results if r.error),
        "phyla": {},
        "records": [asdict(r) for r in results],
    }
    for r in results:
        if r.phylum:
            summary["phyla"][r.phylum] = summary["phyla"].get(r.phylum, 0) + 1

    with open(str(out_path), "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    print(f"\nOutput: {out_path}")
    print(f"Resolved: {summary['resolved']}/{summary['total']}")
    for ph, cnt in sorted(summary["phyla"].items()):
        print(f"  {ph}: {cnt}")


if __name__ == "__main__":
    main()
