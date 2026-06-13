"""
GO enrichment analysis for crustacean virus proteins.

Uses Fisher's exact test to find over-represented GO terms
within each functional category (structural, metabolism, replication, host_interaction).

Usage:
    python go_enrichment.py                      # full analysis
    python go_enrichment.py --by-virus           # also analyze per major virus
    python go_enrichment.py --output-dir ./reports
"""

from __future__ import annotations

import json
import os
import sqlite3
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
from scipy.stats import fisher_exact


BASE_DIR = Path(__file__).resolve().parent
DB_PATH = os.environ.get(
    "ENRICH_DB_PATH",
    str(BASE_DIR / "crustacean_virus_core.db"),
)

# GO aspect prefixes
ASPECT_MAP = {
    "F": "分子功能 (Molecular Function)",
    "P": "生物过程 (Biological Process)",
    "C": "细胞组分 (Cellular Component)",
}


def parse_go_terms(go_json: str | None) -> list[dict[str, str]]:
    """Parse GO terms JSON string into list of {go_id, go_term}."""
    if not go_json or not go_json.strip():
        return []
    try:
        return json.loads(go_json)
    except (json.JSONDecodeError, TypeError):
        return []


def get_data(conn: sqlite3.Connection) -> dict[str, Any]:
    """Fetch all UniProt annotations with GO terms and functional categories."""
    rows = conn.execute("""
        SELECT ua.ncbi_protein_acc, ua.uniprot_id, ua.go_terms,
               ua.functional_category, ua.organism
        FROM uniprot_annotations ua
        WHERE ua.go_terms IS NOT NULL AND ua.go_terms != ''
    """).fetchall()

    records = []
    for r in rows:
        terms = parse_go_terms(r[2])
        if terms:
            records.append({
                "acc": r[0],
                "uniprot": r[1],
                "go_terms": terms,
                "category": r[3] or "uncategorized",
                "organism": r[4] or "unknown",
            })

    return {"records": records}


def get_virus_group(organism: str) -> str:
    """Map organism string to a virus group for per-virus analysis."""
    org_lower = organism.lower()
    if "white spot" in org_lower or "wssv" in org_lower:
        return "WSSV (白斑综合征病毒)"
    if "yellow head" in org_lower or "yhv" in org_lower:
        return "YHV (黄头病毒)"
    if "taura" in org_lower:
        return "TSV (桃拉综合征病毒)"
    if "iridescent" in org_lower or "dii" in org_lower:
        return "DIV1 (虹彩病毒)"
    if "beihai" in org_lower:
        return "Beihai virus"
    if "shrimp" in org_lower and "infectious" in org_lower and "myonecrosis" in org_lower:
        return "IMNV"
    if "hypodermal" in org_lower or "ihhnv" in org_lower:
        return "IHHNV"
    if "macrobrachium" in org_lower or "golda" in org_lower:
        return "MrGV"
    if "brine" in org_lower:
        return "Brine shrimp virus"
    if "laem-singh" in org_lower:
        return "LSNV"
    if "eriocheir" in org_lower:
        return "Eriocheir virus"
    if "gill-associated" in org_lower:
        return "GAV"
    if "scylla" in org_lower or "mud crab" in org_lower or "serrata" in org_lower:
        return "Scylla virus"
    if "crayfish" in org_lower or "procambarus" in org_lower or "cherax" in org_lower:
        return "Crayfish virus"
    if "penaeus" in org_lower or "litopenaeus" in org_lower or "fenneropenaeus" in org_lower:
        return "Penaeid shrimp virus"
    # Catch remaining crustacean viruses
    if "crab" in org_lower or "carcinus" in org_lower:
        return "Crab virus"
    if "hermit" in org_lower:
        return "Hermit crab virus"
    return organism[:30]


def run_enrichment(
    records: list[dict],
    group_key: str,
    group_name: str | None = None,
    min_occurrence: int = 2,
) -> list[dict]:
    """
    Run GO enrichment for a specific group vs background.

    Args:
        records: All records with GO terms
        group_key: Key to filter group (e.g., 'category' or 'virus_group')
        group_name: Value of group_key to test (if None, auto-detect each)
        min_occurrence: Minimum GO term occurrences in foreground group

    Returns:
        List of enrichment results sorted by p-value
    """
    # Collect all unique GO terms
    all_go_ids: set[str] = set()
    for rec in records:
        for t in rec["go_terms"]:
            all_go_ids.add(t["go_id"])

    results = []

    for gid in all_go_ids:
        # Count occurrences
        a = sum(1 for rec in records if rec.get(group_key) == group_name and any(t["go_id"] == gid for t in rec["go_terms"]))
        b = sum(1 for rec in records if rec.get(group_key) != group_name and any(t["go_id"] == gid for t in rec["go_terms"]))
        c = sum(1 for rec in records if rec.get(group_key) == group_name and not any(t["go_id"] == gid for t in rec["go_terms"]))
        d = sum(1 for rec in records if rec.get(group_key) != group_name and not any(t["go_id"] == gid for t in rec["go_terms"]))

        if a < min_occurrence:
            continue

        # Fisher's exact test (one-sided: enrichment)
        try:
            odds_ratio, p_value = fisher_exact([[a, b], [c, d]], alternative="greater")
        except (ValueError, ZeroDivisionError):
            continue

        # Find the GO term text
        go_term_text = ""
        go_aspect = ""
        for rec in records:
            for t in rec["go_terms"]:
                if t["go_id"] == gid:
                    go_term_text = t.get("go_term", "")
                    if go_term_text and ":" in go_term_text:
                        go_aspect = go_term_text[0]
                    break
            if go_term_text:
                break

        total_in_group = a + c
        total_with_go = a + b

        results.append({
            "go_id": gid,
            "go_term": go_term_text,
            "aspect": ASPECT_MAP.get(go_aspect, "Unknown"),
            "foreground_count": a,
            "foreground_total": total_in_group,
            "background_count": b,
            "foreground_ratio": f"{a}/{total_in_group}",
            "background_ratio": f"{b}/{total_with_go}",
            "enrichment": f"{a/total_in_group:.1%}" if total_in_group > 0 else "0%",
            "odds_ratio": round(odds_ratio, 2) if odds_ratio != float("inf") else float("inf"),
            "p_value": p_value,
        })

    # Sort by p-value
    results.sort(key=lambda x: x["p_value"])

    # Apply Bonferroni correction
    n_tests = len(results)
    if n_tests > 0:
        for r in results:
            r["p_adjusted"] = min(r["p_value"] * n_tests, 1.0)
        # Filter significant
        sig = [r for r in results if r["p_adjusted"] < 0.05]
    else:
        sig = []

    return sig


def analyze_by_category(records: list[dict]) -> dict[str, Any]:
    """Run enrichment for each functional category."""
    categories = set(r["category"] for r in records)
    results = {}

    for cat in sorted(categories):
        if cat == "uncategorized":
            continue
        cat_name = cat.replace("_", " ").title()
        sig = run_enrichment(records, "category", cat)
        results[cat] = {
            "name": cat_name,
            "total_proteins": sum(1 for r in records if r["category"] == cat),
            "significant_terms": sig[:30] if sig else [],
            "n_sig": len(sig),
        }

    return results


def analyze_by_virus(records: list[dict]) -> dict[str, Any]:
    """Run enrichment for each major virus group."""
    # Assign virus groups
    for rec in records:
        rec["virus_group"] = get_virus_group(rec["organism"])

    virus_groups = defaultdict(int)
    for rec in records:
        virus_groups[rec["virus_group"]] += 1

    results = {}
    for vg, cnt in sorted(virus_groups.items(), key=lambda x: -x[1]):
        if cnt < 5:  # skip groups with too few GO-annotated proteins
            continue
        sig = run_enrichment(records, "virus_group", vg)
        results[vg] = {
            "total_proteins": cnt,
            "significant_terms": sig[:30] if sig else [],
            "n_sig": len(sig),
        }

    return results


def print_category_results(results: dict[str, Any]) -> None:
    """Print functional category enrichment results."""
    print("\n" + "=" * 70)
    print("功能分类 GO 富集分析结果")
    print("=" * 70)

    for cat, data in sorted(results.items()):
        n = data["n_sig"]
        total = data["total_proteins"]
        print(f"\n==> {data['name']} ({total} 个蛋白, {n} 个显著富集 GO 项)")

        if not data["significant_terms"]:
            print("  无显著富集的 GO 项")
            continue

        # Group by aspect
        by_aspect: dict[str, list] = defaultdict(list)
        for term in data["significant_terms"]:
            by_aspect[term["aspect"]].append(term)

        for aspect_name, terms in by_aspect.items():
            print(f"\n  [{aspect_name}]")
            for i, t in enumerate(terms[:10], 1):
                term_label = t["go_term"].split(":", 1)[-1].strip() if ":" in t["go_term"] else t["go_term"]
                p = f"{t['p_value']:.2e}"
                padj = f"{t['p_adjusted']:.2e}" if t['p_adjusted'] < 0.001 else f"{t['p_adjusted']:.4f}"
                print(f"    {i:2d}. {t['go_id']:15s} {term_label[:50]:50s}")
                print(f"        富集={t['enrichment']:>6s}  比率={t['foreground_ratio']:>8s}  OR={t['odds_ratio']:<8}  p={p}  adj.p={padj}")


def print_virus_results(results: dict[str, Any]) -> None:
    """Print per-virus enrichment results."""
    print("\n" + "=" * 70)
    print("按病毒分类 GO 富集分析结果")
    print("=" * 70)

    for vg, data in sorted(results.items(), key=lambda x: -x[1]["total_proteins"]):
        n = data["n_sig"]
        total = data["total_proteins"]
        print(f"\n==> {vg} ({total} 个蛋白, {n} 个显著富集 GO 项)")

        if not data["significant_terms"]:
            print("  无显著富集的 GO 项")
            continue

        for i, t in enumerate(data["significant_terms"][:10], 1):
            term_label = t["go_term"].split(":", 1)[-1].strip() if ":" in t["go_term"] else t["go_term"]
            print(f"    {i:2d}. [{t['aspect'][:4]}] {term_label[:55]:55s}")
            print(f"        富集={t['enrichment']:>6s}  p={t['p_value']:.2e}  adj.p={t['p_adjusted']:.4f}")


def export_json(cat_results: dict, virus_results: dict | None, output_dir: Path) -> Path:
    """Export all results to JSON."""
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = output_dir / f"go_enrichment_{stamp}.json"

    def serialize(obj: Any) -> Any:
        if isinstance(obj, float):
            if np.isinf(obj):
                return "inf"
            if np.isnan(obj):
                return None
            return round(obj, 6)
        if isinstance(obj, dict):
            return {k: serialize(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [serialize(v) for v in obj]
        return obj

    data = {
        "script": "go_enrichment.py",
        "category_enrichment": serialize(cat_results),
        "virus_enrichment": serialize(virus_results) if virus_results else None,
        "completed_at": datetime.now().isoformat(timespec="seconds"),
    }
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="GO enrichment analysis")
    parser.add_argument("--by-virus", action="store_true", help="Also analyze per virus group")
    parser.add_argument("--output-dir", type=str, default=str(BASE_DIR / "reports"))
    args = parser.parse_args()

    output_dir = Path(args.output_dir)

    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")

    print("读取 UniProt GO 注释数据...")
    data = get_data(conn)
    conn.close()

    records = data["records"]
    print(f"  有 GO 注释的蛋白: {len(records)}")
    print(f"  功能分类: {set(r['category'] for r in records)}")

    # --- Category enrichment ---
    cat_results = analyze_by_category(records)
    print_category_results(cat_results)

    # --- Summary table ---
    print("\n\n" + "=" * 70)
    print("富集分析汇总")
    print("=" * 70)
    print(f"  {'功能分类':25s} {'蛋白数':>6s} {'显著GO项':>8s}")
    print(f"  {'-'*25} {'-'*6} {'-'*8}")
    for cat, data in sorted(cat_results.items()):
        print(f"  {data['name']:25s} {data['total_proteins']:6d} {data['n_sig']:8d}")

    all_go_ids = set()
    for cat, data in cat_results.items():
        for t in data.get("significant_terms", []):
            all_go_ids.add(t["go_id"])
    print(f"\n  总计显著富集的独特 GO 项: {len(all_go_ids)}")

    # --- Per-virus analysis ---
    virus_results = None
    if args.by_virus:
        virus_results = analyze_by_virus(records)
        print_virus_results(virus_results)

    # --- Export ---
    export_path = export_json(cat_results, virus_results, output_dir)
    print(f"\n[导出] 结果已保存至 {export_path}")


if __name__ == "__main__":
    main()
