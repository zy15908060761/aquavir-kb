"""
Test: data quality / sanity checks.

Verifies the database content is free of common contamination patterns:
  - No host chromosomes in viral sequences (e.g. "chromosome" in host names)
  - No primer/adapter artifacts in virus names
  - No unexpected NULLs in critical columns
  - Virus names look like real virus names
"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from db_pg import get_query_connection as get_db
from nar_readiness_check import validate_public_https_url
from validate_database import STANDARD_COUNTRIES

# Patterns that should NEVER appear in a virus_name field
INVALID_VIRUS_PATTERNS = [
    "chromosome",
    "primer",
    "adapter",
    "vector",
    "plasmid",
    "synthetic construct",
    "cloning vector",
]

# Fields that MUST NOT be NULL
NOT_NULL_FIELDS = {
    "viral_isolates": ["accession", "virus_name"],
    "crustacean_hosts": ["scientific_name"],
    "infection_records": ["isolate_id"],
}

# Tables that should have at least MIN_ROWS rows
MIN_ROWS = {
    "ref_literatures": 10,
    "viral_isolates": 50,
    "crustacean_hosts": 5,
    "sample_collections": 5,
    "infection_records": 20,
}


def test_core_tables_have_minimum_rows():
    """Each core table must meet a minimum row count."""
    conn = get_db()
    failures = 0
    try:
        for table, minimum in MIN_ROWS.items():
            row = conn.execute(f"SELECT COUNT(*) AS cnt FROM {table}").fetchone()
            cnt = row["cnt"]
            if cnt < minimum:
                print(f"  [FAIL] {table:25s}: {cnt:>6d} rows (minimum {minimum})")
                failures += 1
            else:
                print(f"  [PASS] {table:25s}: {cnt:>6d} rows")
    finally:
        conn.close()

    if failures:
        print(f"\n  FAILED: {failures} table(s) below minimum row count")
    return failures == 0


def test_no_host_chromosomes_in_host_names():
    """Host names should not contain 'chromosome' or assembly artifacts."""
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT host_id, scientific_name FROM crustacean_hosts "
            "WHERE scientific_name LIKE '%chromosome%' "
            "   OR scientific_name LIKE '%chromosome%' "
            "   OR scientific_name LIKE '%scaffold%' "
            "   OR scientific_name LIKE '%contig%'"
        ).fetchall()
    finally:
        conn.close()

    if rows:
        print(f"  [FAIL] {len(rows)} host name(s) contain chromosome/assembly artifacts:")
        for r in rows[:10]:
            print(f"         host_id={r['host_id']}: {r['scientific_name']}")
        return False
    else:
        print("  [PASS] No chromosome/assembly artifacts in host names")
        return True


def test_no_primer_artifacts_in_virus_names():
    """Virus names should not contain primer/adapter/vector artifacts."""
    conn = get_db()
    problems = []
    try:
        for pattern in INVALID_VIRUS_PATTERNS:
            like = f"%{pattern}%"
            rows = conn.execute(
                "SELECT isolate_id, accession, virus_name FROM viral_isolates "
                "WHERE virus_name LIKE ?",
                (like,),
            ).fetchall()
            for r in rows:
                problems.append((r["isolate_id"], r["accession"], r["virus_name"], pattern))
    finally:
        conn.close()

    if problems:
        print(f"  [FAIL] {len(problems)} virus name(s) with invalid patterns:")
        for pid, acc, name, pat in problems[:10]:
            print(f"         isolate_id={pid}, accession={acc}: '{name}' (matched '{pat}')")
        return False
    else:
        print("  [PASS] No primer/adapter/vector artifacts in virus names")
        return True


def test_no_null_in_critical_fields():
    """Critical fields must not be NULL."""
    conn = get_db()
    failures = 0
    try:
        for table, fields in NOT_NULL_FIELDS.items():
            for field in fields:
                row = conn.execute(
                    f"SELECT COUNT(*) AS cnt FROM {table} WHERE {field} IS NULL"
                ).fetchone()
                cnt = row["cnt"]
                if cnt > 0:
                    print(f"  [FAIL] {table}.{field}: {cnt} NULL values")
                    failures += 1
    finally:
        conn.close()

    if failures == 0:
        print("  [PASS] No NULLs in critical fields")
    return failures == 0


def test_vaccination_status_consistency():
    """If a diagnostic table 'analysis_diagnostics_controls' exists, check consistency."""
    conn = get_db()
    try:
        cur = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name='analysis_diagnostics_controls'"
        )
        if not cur.fetchone():
            print("  [SKIP] analysis_diagnostics_controls table not present")
            return True

        rows = conn.execute(
            "SELECT COUNT(*) AS cnt FROM analysis_diagnostics_controls "
            "WHERE vaccinated_status IS NOT NULL "
            "AND vaccinated_status NOT IN ('vaccinated','unvaccinated','unknown')"
        ).fetchall()
        if rows and rows[0]["cnt"] > 0:
            print(f"  [FAIL] {rows[0]['cnt']} rows with invalid vaccinated_status")
            return False
        else:
            print("  [PASS] Vaccination status values are valid")
            return True
    finally:
        conn.close()


def test_doi_or_pmid_present():
    """References should have at least a DOI or PMID."""
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT COUNT(*) AS cnt FROM ref_literatures "
            "WHERE (doi IS NULL OR doi = '') "
            "AND (pmid IS NULL OR pmid = '')"
        ).fetchone()
        cnt = row["cnt"]
    finally:
        conn.close()

    if cnt > 0:
        print(f"  [WARN] {cnt} reference(s) have neither DOI nor PMID")
    else:
        print("  [PASS] All references have DOI or PMID")
    return True


def test_foreign_key_integrity():
    """Run PRAGMA foreign_key_check to detect orphaned references."""
    conn = get_db()
    try:
        violations = conn.execute("PRAGMA foreign_key_check").fetchall()
    finally:
        conn.close()

    if violations:
        print(f"  [FAIL] {len(violations)} foreign key violation(s):")
        for v in violations[:10]:
            print(f"         table={v['table']}, rowid={v['rowid']}, parent={v['parent']}")
        # Group by table
        from collections import Counter
        table_counts = Counter(v["table"] for v in violations)
        for table, cnt in table_counts.items():
            print(f"         {table}: {cnt} violation(s)")
        return False
    else:
        print("  [PASS] No foreign key violations")
        return True


def test_marine_dependent_territories_are_recognized():
    """Marine collection geography can legitimately use ISO territory names."""
    expected = {"Aruba", "Faroe Islands", "French Polynesia", "New Caledonia"}
    missing = expected - STANDARD_COUNTRIES
    if missing:
        print(f"  [FAIL] ISO territory names missing from country whitelist: {sorted(missing)}")
        return False
    print("  [PASS] Marine ISO territory names are accepted")
    return True


def test_nar_public_url_rejects_local_or_insecure_urls():
    """NAR readiness must not accept localhost or non-HTTPS placeholders."""
    import tempfile
    from pathlib import Path

    cases = {
        "http://example.org": "invalid",
        "https://localhost:8000": "invalid",
        "https://127.0.0.1": "invalid",
        "https://192.168.1.10": "invalid",
        "https://crustavirus.example.org": "ok",
    }
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "PUBLIC_URL.txt"
        for raw, expected in cases.items():
            path.write_text(raw, encoding="utf-8")
            status, detail = validate_public_https_url(path)
            if status != expected:
                print(f"  [FAIL] {raw!r}: got {status!r} ({detail}), expected {expected!r}")
                return False
    print("  [PASS] NAR public URL validator rejects local/insecure placeholders")
    return True


def run_all():
    print("=" * 60)
    print("test_data_quality.py  --  Data sanity & contamination checks")
    print("=" * 60)

    checks = [
        ("Minimum row counts", test_core_tables_have_minimum_rows),
        ("No NULLs in critical fields", test_no_null_in_critical_fields),
        ("No host chromosomes in names", test_no_host_chromosomes_in_host_names),
        ("No primer artifacts in virus names", test_no_primer_artifacts_in_virus_names),
        ("DOI or PMID present", test_doi_or_pmid_present),
        ("Vaccination status consistency", test_vaccination_status_consistency),
        ("Foreign key integrity", test_foreign_key_integrity),
        ("Marine territory whitelist", test_marine_dependent_territories_are_recognized),
        ("NAR public URL validator", test_nar_public_url_rejects_local_or_insecure_urls),
    ]

    passed = 0
    failed = 0
    for label, func in checks:
        print(f"\n--- {label} ---")
        try:
            ok = func()
            if ok:
                passed += 1
            else:
                failed += 1
        except Exception as e:
            print(f"  [ERROR] {e}")
            failed += 1

    print("=" * 60)
    print(f"Results: {passed} passed, {failed} failed")
    if failed:
        print("WARNING: Some data quality checks failed!")
    print("=" * 60)
    return failed == 0


if __name__ == "__main__":
    success = run_all()
    sys.exit(0 if success else 1)
