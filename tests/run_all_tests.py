"""
Run all tests in the tests/ directory and report results.
"""
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

TEST_DIR = Path(__file__).resolve().parent


def run_test(module_name: str) -> bool:
    """Import and run run_all() from a test module."""
    print(f"\n{'=' * 60}")
    print(f"Running: {module_name}")
    print(f"{'=' * 60}")
    start = time.time()
    try:
        # Dynamic import
        import importlib
        mod = importlib.import_module(module_name)
        if hasattr(mod, "run_all"):
            result = mod.run_all()
        else:
            print(f"[ERROR] {module_name} has no run_all() function")
            return False
        elapsed = time.time() - start
        status = "PASSED" if result else "FAILED"
        print(f"\n[{status}] {module_name}  ({elapsed:.2f}s)")
        return bool(result)
    except Exception as e:
        elapsed = time.time() - start
        print(f"\n[ERROR] {module_name} raised {type(e).__name__}: {e}  ({elapsed:.2f}s)")
        import traceback
        traceback.print_exc()
        return False


def main():
    # Test modules in order (DB tests first, then quality, then API)
    test_modules = [
        "tests.test_db_connection",
        "tests.test_data_quality",
        "tests.test_api",
    ]

    results = {}
    for mod_name in test_modules:
        results[mod_name] = run_test(mod_name)

    print(f"\n\n{'=' * 60}")
    print("TEST SUMMARY")
    print(f"{'=' * 60}")
    passed = 0
    failed = 0
    for mod_name, ok in results.items():
        status = "PASS" if ok else "FAIL"
        print(f"  [{status}] {mod_name}")
        if ok:
            passed += 1
        else:
            failed += 1

    total = passed + failed
    print(f"\n{passed}/{total} test suites passed, {failed} failed")

    if failed:
        print("\nWARNING: Some test suites failed.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
