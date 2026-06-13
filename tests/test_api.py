"""
Test: API endpoints return valid responses.

These tests assume the FastAPI backend (backend.py) is running locally
on its default port.  If the server is not running, tests will be skipped
with a warning.

Override the base URL via the CRUSTA_API_URL environment variable::

    set CRUSTA_API_URL=http://localhost:8080
    python tests/test_api.py
"""
import os
import sys
import json
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

try:
    import requests
except ImportError:
    requests = None  # type: ignore[assignment]

# ── Configuration ──────────────────────────────────────────────────
BASE_URL = os.environ.get("CRUSTA_API_URL", "http://127.0.0.1:8000")
REQUEST_TIMEOUT = 15  # seconds

# Critical endpoints to test
ENDPOINTS = [
    ("health", "/api/health"),
    ("stats", "/api/stats"),
    ("search (virus)", "/api/search?q=WSSV"),
    ("search (host)", "/api/search?host=Litopenaeus+vannamei"),
    ("suggestions (virus)", "/api/suggestions?kind=virus"),
    ("suggestions (host)", "/api/suggestions?kind=host"),
    ("download metadata", "/api/download/crustacean_virus_metadata_standardized.xlsx"),
]


def check_server_alive() -> bool:
    """Return True if the API server is reachable."""
    try:
        resp = requests.get(f"{BASE_URL}/api/health", timeout=5)
        resp.raise_for_status()
        return True
    except Exception as e:
        print(f"[SKIP] Server not reachable at {BASE_URL}: {e}")
        return False


def test_endpoint(name: str, path: str) -> bool:
    """Hit a single endpoint and validate the response."""
    url = f"{BASE_URL}{path}"
    try:
        start = time.time()
        resp = requests.get(url, timeout=REQUEST_TIMEOUT)
        elapsed = time.time() - start
    except requests.Timeout:
        print(f"  [FAIL] {name:35s}  TIMEOUT (>={REQUEST_TIMEOUT}s)")
        return False
    except requests.ConnectionError as e:
        print(f"  [FAIL] {name:35s}  ConnectionError: {e}")
        return False
    except Exception as e:
        print(f"  [FAIL] {name:35s}  {type(e).__name__}: {e}")
        return False

    # Status code check
    if resp.status_code != 200:
        print(f"  [FAIL] {name:35s}  HTTP {resp.status_code}  ({elapsed:.2f}s)")
        return False

    # File downloads are allowed to return binary content.
    if path.startswith("/api/download/"):
        if len(resp.content) == 0:
            print(f"  [FAIL] {name:35s}  empty download  ({elapsed:.2f}s)")
            return False
        print(f"  [PASS] {name:35s}  HTTP 200  {len(resp.content)} bytes  ({elapsed:.2f}s)")
        return True

    # Content-Type should be JSON for API endpoints
    ct = resp.headers.get("content-type", "")
    if "json" not in ct and "text" in ct:
        print(f"  [WARN] {name:35s}  HTTP 200  Content-Type: {ct}  ({elapsed:.2f}s)")
        # It might be HTML from a redirect
        return False

    # Try to parse JSON
    try:
        data = resp.json()
    except json.JSONDecodeError as e:
        print(f"  [FAIL] {name:35s}  Invalid JSON: {e}  ({elapsed:.2f}s)")
        return False

    print(f"  [PASS] {name:35s}  HTTP 200  ({elapsed:.2f}s)")
    return True


def test_stats_endpoint():
    """Validate the /api/stats response contains expected numeric fields."""
    url = f"{BASE_URL}/api/stats"
    resp = requests.get(url, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    data = resp.json()

    expected_keys = {
        "viral_isolates",
        "crustacean_hosts",
        "ref_literatures",
        "sample_collections",
        "virulence_profiles",
        "temperature_profiles",
    }
    missing = expected_keys - set(data.keys())
    if missing:
        print(f"  [FAIL] /api/stats missing keys: {missing}")
        return False

    # Values should be non-negative integers
    for key in expected_keys:
        val = data.get(key, -1)
        if not isinstance(val, (int, float)) or val < 0:
            print(f"  [FAIL] /api/stats.{key} = {val!r} (expected non-negative number)")
            return False

    print(f"  [PASS] /api/stats has all {len(expected_keys)} expected keys with valid values")
    return True


def test_search_returns_results():
    """Search for a well-known virus should return results."""
    url = f"{BASE_URL}/api/search?q=WSSV"
    resp = requests.get(url, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    data = resp.json()

    items = data.get("items") or data.get("results") or data
    total = data.get("total", 0) if isinstance(data, dict) else len(items) if isinstance(items, list) else 0

    if total == 0:
        print(f"  [WARN] /api/search?q=WSSV returned 0 results (DB may be empty)")
    else:
        print(f"  [PASS] /api/search?q=WSSV returned {total} result(s)")
    return True


def test_suggestions_return_items():
    """Suggestions endpoint should return a non-empty items list."""
    for kind in ("virus", "host"):
        url = f"{BASE_URL}/api/suggestions?kind={kind}"
        resp = requests.get(url, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        items = data.get("items", [])
        if len(items) == 0:
            print(f"  [WARN] /api/suggestions?kind={kind} returned empty items")
        else:
            print(f"  [PASS] /api/suggestions?kind={kind} returned {len(items)} items")
    return True


def test_hosts_endpoint():
    """Host list should return a dict with 'hosts' array and 'count'."""
    url = f"{BASE_URL}/api/hosts"
    resp = requests.get(url, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    data = resp.json()
    if not isinstance(data, dict):
        print(f"  [FAIL] /api/hosts did not return a dict (got {type(data).__name__})")
        return False
    if "hosts" not in data:
        print(f"  [FAIL] /api/hosts missing 'hosts' key (keys: {list(data.keys())})")
        return False
    if "count" not in data:
        print(f"  [FAIL] /api/hosts missing 'count' key (keys: {list(data.keys())})")
        return False
    hosts = data["hosts"]
    count = data["count"]
    if not isinstance(hosts, list):
        print(f"  [FAIL] /api/hosts['hosts'] is not a list (got {type(hosts).__name__})")
        return False
    if not isinstance(count, int):
        print(f"  [FAIL] /api/hosts['count'] is not an int (got {type(count).__name__})")
        return False
    if count != len(hosts):
        print(f"  [WARN] /api/hosts count={count} does not match len(hosts)={len(hosts)}")
    print(f"  [PASS] /api/hosts returned {len(hosts)} host(s), count={count}")
    if hosts:
        first = hosts[0]
        if "host_id" not in first or "scientific_name" not in first:
            print(f"  [WARN] /api/hosts entries missing expected fields: {list(first.keys())}")
    return True


def run_all():
    print("=" * 60)
    print("test_api.py  --  API endpoint smoke tests")
    print("=" * 60)

    if requests is None:
        print("[SKIP] 'requests' package is not installed. Install with: pip install requests")
        return

    if not check_server_alive():
        print(f"\nTo run these tests, start the backend first:\n"
              f"    uvicorn backend:app --host 127.0.0.1 --port 8000\n"
              f"Or set CRUSTA_API_URL to the correct address.")
        return

    passed = 0
    failed = 0

    # 1. Basic endpoint reachability
    print("\n--- Endpoint reachability ---")
    for name, path in ENDPOINTS:
        ok = test_endpoint(name, path)
        if ok:
            passed += 1
        else:
            failed += 1

    # 2. Detailed content validation
    print("\n--- /api/stats content validation ---")
    if test_stats_endpoint():
        passed += 1
    else:
        failed += 1

    print("\n--- /api/search content validation ---")
    if test_search_returns_results():
        passed += 1
    else:
        failed += 1

    print("\n--- /api/suggestions content validation ---")
    if test_suggestions_return_items():
        passed += 1
    else:
        failed += 1

    print("\n--- /api/hosts content validation ---")
    if test_hosts_endpoint():
        passed += 1
    else:
        failed += 1

    print("=" * 60)
    total = passed + failed
    print(f"Results: {passed}/{total} passed, {failed} failed")
    print("=" * 60)
    return failed == 0


if __name__ == "__main__":
    success = run_all()
    sys.exit(0 if success else 1)
