"""
Pipeline runner for the crustacean virus database build process.

Executes build/migration steps in order:
  1. Checks pre-conditions before each step
  2. Logs output to stdout and optionally to a file
  3. Aborts on the first failure
  4. Records applied steps in the schema_version table

Usage
-----
    # Run the full pipeline
    python run_pipeline.py

    # Run only specific steps (by index from the PIPELINE list)
    python run_pipeline.py --steps 0 1 3

    # Dry-run: print what would run without executing
    python run_pipeline.py --dry-run

    # Force re-run a step even if already recorded
    python run_pipeline.py --force 2

    # Run tests after building
    python run_pipeline.py --run-tests
"""
import hashlib
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

from schema_version import SchemaTracker

# ── Pipeline definition ────────────────────────────────────────────
# Each step is a dict:
#   name        - short label (used as script_name in schema_version)
#   script      - Python script to run (relative to PROJECT_ROOT)
#   description - human-readable purpose
#   pre_check   - optional callable returning (ok: bool, msg: str)
#   post_check  - optional callable returning (ok: bool, msg: str)
#   required    - if True, pipeline aborts on failure (default True)
#   depends_on  - list of step names that must have run first

PIPELINE = [
    {
        "name": "build_core_db",
        "script": "build_sqlite_core_db_v2.py",
        "description": "Build core database tables from Excel metadata",
        "required": True,
        "depends_on": [],
    },
    {
        "name": "fix_uniprot_mapping",
        "script": "fix_uniprot_protein_mapping.py",
        "description": "Link UniProt annotations to viral proteins",
        "required": True,
        "depends_on": ["build_core_db"],
    },
]

# ── Logging ────────────────────────────────────────────────────────

LOG_FILE = PROJECT_ROOT / "pipeline_run.log"


def log(msg: str):
    """Print with timestamp and append to log file."""
    ts = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError:
        pass  # best-effort


# ── Checksum helpers ───────────────────────────────────────────────

def file_checksum(path: Path) -> str:
    """Return SHA-256 hex digest of file content."""
    h = hashlib.sha256()
    try:
        h.update(path.read_bytes())
    except OSError:
        return ""
    return h.hexdigest()[:16]


# ── Pre-checks ─────────────────────────────────────────────────────

def check_db_writable() -> tuple:
    """Verify the database file directory is writable."""
    db_path = PROJECT_ROOT / "crustacean_virus_core.db"
    try:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        test_file = db_path.parent / ".write_test"
        test_file.write_text("")
        test_file.unlink()
        return True, ""
    except OSError as e:
        return False, f"Cannot write to database directory: {e}"


def check_excel_inputs() -> tuple:
    """Verify input Excel files exist."""
    meta = PROJECT_ROOT / "ncbi_metadata" / "crustacean_virus_metadata.xlsx"
    lit = PROJECT_ROOT / "ncbi_metadata" / "pubmed_supplements.xlsx"
    missing = []
    if not meta.exists():
        missing.append(str(meta))
    if not lit.exists():
        missing.append(str(lit))
    if missing:
        return False, f"Missing input files: {', '.join(missing)}"
    return True, ""


def check_script_exists(script_name: str) -> tuple:
    """Verify a script file exists."""
    script_path = PROJECT_ROOT / script_name
    if not script_path.exists():
        return False, f"Script not found: {script_path}"
    return True, ""


# ── Step execution ─────────────────────────────────────────────────

def run_step(step: dict, tracker: SchemaTracker, force: bool = False) -> bool:
    """Execute a single pipeline step.

    Parameters
    ----------
    step : dict
        Pipeline step definition.
    tracker : SchemaTracker
        Schema version tracker instance.
    force : bool
        If True, re-run even if already recorded.

    Returns
    -------
    bool
        True on success, False on failure.
    """
    name = step["name"]
    script = step["script"]
    description = step.get("description", "")

    # Check if already applied
    if not force and tracker.is_applied(name):
        log(f"  [SKIP] '{name}' already applied (use --force to re-run)")
        return True

    # Pre-checks
    for check_fn in step.get("pre_checks", []):
        ok, msg = check_fn()
        if not ok:
            log(f"  [ABORT] Pre-check failed for '{name}': {msg}")
            return False
        if msg:
            log(f"  [CHECK] {msg}")

    # Dependencies
    for dep in step.get("depends_on", []):
        if not tracker.is_applied(dep):
            log(f"  [ABORT] '{name}' depends on '{dep}' which has not been applied")
            return False

    # Run the script
    log(f"  [RUN] {name}: {description}")
    log(f"  [CMD] python {script}")
    start = time.time()

    script_path = PROJECT_ROOT / script
    checksum = file_checksum(script_path)

    try:
        result = subprocess.run(
            [sys.executable, str(script_path)],
            cwd=str(PROJECT_ROOT),
            capture_output=False,
            text=True,
            timeout=600,  # 10 minutes
        )
        elapsed = time.time() - start
        exit_code = result.returncode

        if exit_code == 0:
            log(f"  [PASS] '{name}' completed in {elapsed:.1f}s (exit={exit_code})")
            tracker.record(name, checksum=checksum, exit_code=exit_code, notes=description)
            return True
        else:
            log(f"  [FAIL] '{name}' failed in {elapsed:.1f}s (exit={exit_code})")
            log(f"  [FAIL] stdout/stderr above")
            tracker.record(name, checksum=checksum, exit_code=exit_code,
                           notes=f"FAILED: {description}")
            return False

    except subprocess.TimeoutExpired:
        elapsed = time.time() - start
        log(f"  [FAIL] '{name}' timed out after {elapsed:.1f}s")
        tracker.record(name, checksum=checksum, exit_code=-1,
                       notes="TIMEOUT")
        return False
    except FileNotFoundError:
        log(f"  [FAIL] '{name}' script not found: {script_path}")
        return False
    except Exception as e:
        log(f"  [FAIL] '{name}' unexpected error: {e}")
        return False


def run_tests():
    """Run all test suites after pipeline completes."""
    log("\n" + "=" * 60)
    log("Running post-build tests...")
    log("=" * 60)
    test_runner = PROJECT_ROOT / "tests" / "run_all_tests.py"
    if not test_runner.exists():
        log("[SKIP] Test runner not found")
        return True

    result = subprocess.run(
        [sys.executable, str(test_runner)],
        cwd=str(PROJECT_ROOT),
        capture_output=False,
        timeout=120,
    )
    if result.returncode == 0:
        log("[PASS] All tests passed")
        return True
    else:
        log("[FAIL] Some tests failed")
        return False


# ── Main ───────────────────────────────────────────────────────────

def parse_args():
    """Parse command-line arguments."""
    args = {
        "steps": [],
        "dry_run": False,
        "force": [],
        "run_tests": False,
    }
    argv = sys.argv[1:]
    i = 0
    while i < len(argv):
        if argv[i] == "--steps":
            i += 1
            while i < len(argv) and not argv[i].startswith("--"):
                args["steps"].append(int(argv[i]))
                i += 1
            continue
        elif argv[i] == "--dry-run":
            args["dry_run"] = True
        elif argv[i] == "--force":
            i += 1
            if i < len(argv) and not argv[i].startswith("--"):
                args["force"].append(argv[i])
            else:
                args["force"].append("*")  # force all
            continue
        elif argv[i] == "--run-tests":
            args["run_tests"] = True
        else:
            print(f"Unknown argument: {argv[i]}")
            print_usage()
            sys.exit(1)
        i += 1
    return args


def print_usage():
    print(__doc__)


def main():
    args = parse_args()
    tracker = SchemaTracker()
    tracker.ensure_table()

    # Determine which steps to run
    if args["steps"]:
        selected = [PIPELINE[i] for i in args["steps"] if 0 <= i < len(PIPELINE)]
        if not selected:
            log("[ABORT] No valid step indices matched")
            sys.exit(1)
    else:
        selected = PIPELINE

    # Handle --force
    force_all = False
    force_names = args["force"]
    if "*" in force_names:
        force_all = True
        log("[INFO] --force applied to all steps")
    else:
        force_names_lower = [n.lower() for n in force_names]

    log("=" * 60)
    log("Pipeline runner started")
    log(f"Steps to execute: {', '.join(s['name'] for s in selected)}")
    log("=" * 60)

    if args["dry_run"]:
        log("\n[Dry Run] Would execute:")
        for step in selected:
            applied = tracker.is_applied(step["name"])
            forced = force_all or step["name"].lower() in force_names_lower
            status = "re-run" if (applied and forced) else ("skip (applied)" if applied else "run")
            log(f"  {step['name']:30s}  [{status}]  {step['description']}")
        log("\n[Dry Run] Complete.")
        return

    # Execute steps
    success = True
    for step in selected:
        name = step["name"]
        step_force = force_all or name.lower() in force_names_lower

        ok = run_step(step, tracker, force=step_force)
        if not ok:
            if step.get("required", True):
                log(f"\n[ABORT] Pipeline aborted at step '{name}'")
                success = False
                break
            else:
                log(f"[WARN] Non-required step '{name}' failed, continuing")

    # Optionally run tests
    if success and args["run_tests"]:
        test_ok = run_tests()
        if not test_ok:
            log("[WARN] Build succeeded but tests failed")

    # Summary
    log("\n" + "=" * 60)
    if success:
        log("Pipeline finished successfully")
    else:
        log("Pipeline FAILED")
    log(tracker.summary())
    log("=" * 60)

    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
