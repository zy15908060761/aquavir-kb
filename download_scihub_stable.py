#!/usr/bin/env python3
"""
Sci-Hub stable batch downloader.
Design: reliability > speed. Saves after every paper. Never loses progress.

Usage:
  python download_scihub_stable.py          # full run
  python download_scihub_stable.py --test   # test reachability first
"""
import json, sqlite3, time, urllib.request, urllib.error, re, sys, hashlib
from pathlib import Path
from collections import Counter

# === CONFIG ===
DB_PATH = Path(r"F:\水生无脊椎动物数据库\crustacean_virus_core.db")
PROJECT_DIR = Path(r"F:\水生无脊椎动物数据库")
OA_DIR = PROJECT_DIR / "literature_curation_v2" / "oa_fulltext"
LOG_DIR = PROJECT_DIR / "downloads" / "scihub_logs"
for d in [OA_DIR, LOG_DIR]: d.mkdir(parents=True, exist_ok=True)

CHECKPOINT = LOG_DIR / "scihub_stable_checkpoint.json"
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
TIMEOUT = 45
SLEEP_MIN = 2.0       # minimum sleep between papers
SLEEP_ON_ERROR = 10.0  # sleep after any error
SLEEP_ON_CAPTCHA = 30.0  # sleep when CAPTCHA detected

# All known Sci-Hub domains — will test which ones work
ALL_MIRRORS = [
    "https://sci-hub.se",
    "https://sci-hub.ru",
    "https://sci-hub.st",
    "https://sci-hub.ee",
]


def load_cp():
    if CHECKPOINT.exists():
        with open(CHECKPOINT, encoding="utf-8") as f:
            return json.load(f)
    return {"done": {}, "unavailable": [], "errors": {}, "mirror_stats": {}}


def save_cp(cp):
    tmp = CHECKPOINT.with_suffix(".tmp")
    tmp.write_text(json.dumps(cp, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(CHECKPOINT)


def test_mirrors():
    """Test which Sci-Hub mirrors are reachable. Return working ones."""
    working = []
    print("Testing Sci-Hub mirrors...")
    for m in ALL_MIRRORS:
        try:
            req = urllib.request.Request(m, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=15) as resp:
                if resp.getcode() == 200:
                    print(f"  {m} — OK")
                    working.append(m)
                else:
                    print(f"  {m} — HTTP {resp.getcode()}")
        except Exception as e:
            print(f"  {m} — {str(e)[:60]}")
    if not working:
        print("\n  *** ALL MIRRORS UNREACHABLE. Check your network. ***")
    else:
        print(f"\n  {len(working)}/{len(ALL_MIRRORS)} mirrors working.")
    return working


def get_target_refs():
    cp = load_cp()
    already = set(cp.get("done", {}).keys()) | set(cp.get("unavailable", []))
    con = sqlite3.connect(str(DB_PATH), timeout=60)
    con.row_factory = sqlite3.Row
    cur = con.execute("""
        SELECT DISTINCT lfs.reference_id, lfs.doi, lfs.pmid, rl.title, rl.journal, rl.year
        FROM literature_fulltext_sources lfs
        JOIN ref_literatures rl ON lfs.reference_id = rl.reference_id
        WHERE lfs.status IN ('no_oa', 'failed')
          AND lfs.doi IS NOT NULL AND lfs.doi != ''
        ORDER BY rl.year DESC
    """)
    refs = [dict(r) for r in cur.fetchall() if r["reference_id"] not in already]
    con.close()
    return refs


def scihub_fetch(doi, mirrors):
    """
    Try to download DOI from Sci-Hub.
    Returns (pdf_bytes, source_label) or (None, error_reason).
    Tries each mirror once, then rotates.
    """
    for attempt in range(len(mirrors) * 2):
        mirror = mirrors[attempt % len(mirrors)]
        sci_url = f"{mirror}/{doi}"

        try:
            # Fetch Sci-Hub page
            req = urllib.request.Request(sci_url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                html = resp.read().decode("utf-8", errors="ignore")

            # Catch CAPTCHA
            if "captcha" in html.lower() or "verify" in html.lower() and "human" in html.lower():
                return None, f"captcha_{mirror}"

            # Catch "not found"
            if "article not found" in html.lower() or "doi not found" in html.lower():
                return None, "not_on_scihub"

            # --- Extract PDF URL ---
            pdf_url = None

            # Method 1: <embed> or <iframe> with PDF src
            for tag in ["embed", "iframe"]:
                m = re.search(
                    r'<' + tag + r'\b[^>]*?\bsrc\s*=\s*["\']([^"\']*?\.pdf[^"\']*?)["\']',
                    html, re.IGNORECASE
                )
                if m:
                    raw = m.group(1)
                    if raw.startswith("//"):
                        pdf_url = "https:" + raw
                    elif raw.startswith("/"):
                        pdf_url = mirror + raw
                    else:
                        pdf_url = raw
                    break
            if pdf_url:
                pass  # found

            # Method 2: button/link with onclick containing PDF URL
            if not pdf_url:
                m = re.search(r"location\.href\s*=\s*['\"]([^'\"]+\.pdf[^'\"]*)['\"]", html, re.I)
                if m:
                    pdf_url = m.group(1)
                    if pdf_url.startswith("//"):
                        pdf_url = "https:" + pdf_url

            # Method 3: Any absolute PDF link on the page
            if not pdf_url:
                for m in re.finditer(r'https?://[^"\'<>\s]+\.pdf', html, re.I):
                    candidate = m.group(0).rstrip("')\"").split("?")[0]
                    # Skip known ad/tracker domains
                    if not any(bad in candidate.lower() for bad in ["doubleclick", "google", "facebook", "twitter"]):
                        pdf_url = candidate
                        break

            # Method 4: Try the #pdf anchor approach
            if not pdf_url:
                try:
                    alt_url = f"{mirror}/{doi}#pdf"
                    req2 = urllib.request.Request(alt_url, headers={"User-Agent": UA})
                    with urllib.request.urlopen(req2, timeout=TIMEOUT) as resp2:
                        html2 = resp2.read().decode("utf-8", errors="ignore")
                    m = re.search(r'(?:embed|iframe)[^>]*src\s*=\s*["\']([^"\']+\.pdf[^"\']*)["\']', html2, re.I)
                    if m:
                        pdf_url = m.group(1)
                        if pdf_url.startswith("//"):
                            pdf_url = "https:" + pdf_url
                        elif pdf_url.startswith("/"):
                            pdf_url = mirror + pdf_url
                except Exception:
                    pass

            if not pdf_url:
                return None, "pdf_url_not_found"

            # --- Download PDF ---
            pdf_req = urllib.request.Request(pdf_url, headers={
                "User-Agent": UA,
                "Referer": sci_url,
                "Accept": "application/pdf,*/*",
            })
            with urllib.request.urlopen(pdf_req, timeout=TIMEOUT) as pdf_resp:
                content = pdf_resp.read()

            # Validate
            if len(content) < 5000:
                return None, f"pdf_too_small_{len(content)}"
            if not (content.startswith(b"%PDF") or b"%PDF-" in content[:200]):
                # Maybe it's HTML (error page)? Check
                if b"<!DOCTYPE" in content[:100] or b"<html" in content[:100]:
                    return None, "got_html_not_pdf"

            # Success!
            return content, mirror

        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None, "http_404"
            if e.code == 429:
                time.sleep(SLEEP_ON_ERROR)
                continue
            if e.code >= 500:
                time.sleep(SLEEP_ON_ERROR)
                continue
            return None, f"http_{e.code}"
        except urllib.error.URLError as e:
            reason = str(e.reason) if e.reason else str(e)
            return None, f"url_error_{reason[:40]}"
        except Exception as e:
            return None, f"exception_{str(e)[:50]}"

    return None, "all_mirrors_exhausted"


def update_db_downloaded(con, ref_id, source, local_path):
    con.execute("""UPDATE literature_fulltext_sources
        SET status='downloaded', source=?, local_path=?, content_type='application/pdf'
        WHERE reference_id=? AND status IN ('no_oa','failed')""",
        (source, local_path, ref_id))


def save_pdf(doi, content):
    """Save PDF bytes to file with DOI-based filename."""
    clean = doi.replace("/", "_").replace(".", "_")[:80]
    # Add content hash suffix to avoid name collisions
    h = hashlib.md5(content[:1024]).hexdigest()[:6]
    path = OA_DIR / f"{clean}_{h}_scihub.pdf"
    path.write_bytes(content)
    return str(path)


def main():
    test_only = "--test" in sys.argv

    print("=" * 70)
    print("Sci-Hub STABLE DOWNLOADER")
    print("=" * 70)

    # Test mirrors
    working_mirrors = test_mirrors()
    if not working_mirrors:
        print("\nCannot reach any Sci-Hub mirror. Exiting.")
        return
    if test_only:
        return

    # Get target refs
    con = sqlite3.connect(str(DB_PATH), timeout=60)
    con.row_factory = sqlite3.Row

    refs = get_target_refs()
    no_oa_n = sum(1 for r in refs if r["status"] == "no_oa")
    failed_n = sum(1 for r in refs if r["status"] == "failed")
    print(f"\nTargets: {len(refs):,} (no_oa={no_oa_n:,} failed={failed_n:,})")

    cp = load_cp()
    done_from_cp = len(cp.get("done", {}))
    unavailable_from_cp = len(cp.get("unavailable", []))
    if done_from_cp:
        print(f"Resume: {done_from_cp} already done, {unavailable_from_cp} unavailable")

    stats = Counter()
    errors_since_last_success = 0
    t0 = time.time()

    print()
    for i, ref in enumerate(refs):
        ref_id = ref["reference_id"]
        doi = (ref["doi"] or "").strip()
        title = (ref["title"] or "")[:100]

        if not doi:
            cp.setdefault("unavailable", []).append(ref_id)
            save_cp(cp)
            continue

        # Show progress line
        elapsed_total = time.time() - t0
        pct = (done_from_cp + stats["success"]) / max(1, done_from_cp + stats["total"])
        print(f"\r  [{stats['total']+1}/{len(refs)}] "
              f"{doi[:55]:<55} "
              f"OK={stats['success']} "
              f"err={stats['error']} "
              f"unavail={stats['unavailable']} "
              f"| {elapsed_total/60:.0f}m",
              end="", flush=True)

        # Download
        pdf_content, source_info = scihub_fetch(doi, working_mirrors)

        if pdf_content:
            # Save PDF
            try:
                local_path = save_pdf(doi, pdf_content)
            except Exception as e:
                stats["error"] += 1
                errors_since_last_success += 1
                time.sleep(SLEEP_ON_ERROR)
                continue

            # Update DB
            source_label = f"scihub_{Path(source_info).name}" if source_info and "/" in source_info else "scihub"
            try:
                update_db_downloaded(con, ref_id, source_label, local_path)
                con.commit()
            except Exception as e:
                # DB might be locked; retry
                time.sleep(2)
                try:
                    update_db_downloaded(con, ref_id, source_label, local_path)
                    con.commit()
                except Exception:
                    pass

            # Update checkpoint
            cp.setdefault("done", {})[str(ref_id)] = {"doi": doi, "title": title[:60], "source": source_label, "path": local_path}
            cp.setdefault("mirror_stats", {}).setdefault(source_info, 0)
            cp["mirror_stats"][source_info] += 1
            save_cp(cp)
            stats["success"] += 1
            errors_since_last_success = 0

            # Sleep (longer between successes to be polite)
            sleep_time = SLEEP_MIN + (stats["success"] % 50 == 0) * 2.0
            time.sleep(sleep_time)

        elif source_info in ("not_on_scihub",):
            # Definitely not available — don't retry
            cp.setdefault("unavailable", []).append(ref_id)
            save_cp(cp)
            stats["unavailable"] += 1
            errors_since_last_success = 0
            time.sleep(SLEEP_MIN)

        else:
            # Transient error — retry later
            stats["error"] += 1
            errors_since_last_success += 1
            cp.setdefault("errors", {})[str(ref_id)] = source_info
            # Don't save checkpoint on every error to avoid IO overhead
            if errors_since_last_success % 10 == 0:
                save_cp(cp)
            # Sleep longer after errors
            time.sleep(SLEEP_ON_ERROR if errors_since_last_success > 3 else SLEEP_MIN * 2)

        stats["total"] += 1

        # Health check: if too many consecutive errors, maybe mirrors are down
        if errors_since_last_success > 20:
            print(f"\n  *** Too many consecutive errors ({errors_since_last_success}). "
                  f"Pausing 60s before retry...")
            time.sleep(60)
            # Re-test mirrors
            working_mirrors = test_mirrors()
            if not working_mirrors:
                print("  All mirrors down. Saving progress and exiting.")
                save_cp(cp)
                break
            errors_since_last_success = 0

    # Cleanup
    con.commit()
    save_cp(cp)
    con.close()

    total_time = time.time() - t0
    print(f"\n\n{'=' * 70}")
    print("COMPLETE")
    print(f"{'=' * 70}")
    print(f"  Duration: {total_time/60:.0f} min ({total_time/3600:.1f}h)")
    print(f"  Downloaded: {stats['success']:,}")
    print(f"  Unavailable: {stats['unavailable']:,}")
    print(f"  Errors: {stats['error']:,}")
    print(f"  Total done (incl. previous): {done_from_cp + stats['success']:,}")

    # Final DB state
    con = sqlite3.connect(str(DB_PATH), timeout=60)
    cur = con.cursor()
    print(f"\n  === DB Fulltext Status ===")
    for row in cur.execute("SELECT status, COUNT(DISTINCT reference_id) FROM literature_fulltext_sources GROUP BY status ORDER BY COUNT(*) DESC"):
        print(f"    {row[0]}: {row[1]:,}")
    con.close()


if __name__ == "__main__":
    main()
