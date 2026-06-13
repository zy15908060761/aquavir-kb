#!/usr/bin/env python3
"""
Sci-Hub batch download for paywalled literature.
Attempts multiple mirrors, handles CAPTCHAs gracefully.
Targets the 6,086 no_oa + failed refs with DOIs.
"""
import json, sqlite3, time, urllib.request, urllib.error, re, os
from pathlib import Path
from datetime import datetime
from collections import Counter

DB_PATH = Path(r"F:\水生无脊椎动物数据库\crustacean_virus_core.db")
PROJECT_DIR = Path(r"F:\水生无脊椎动物数据库")
OA_DIR = PROJECT_DIR / "literature_curation_v2" / "oa_fulltext"
LOG_DIR = PROJECT_DIR / "downloads" / "scihub_logs"

for d in [OA_DIR, LOG_DIR]:
    d.mkdir(parents=True, exist_ok=True)

CHECKPOINT = LOG_DIR / "scihub_checkpoint.json"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
TIMEOUT = 60
SLEEP = 1.0  # Sci-Hub needs polite delays


def load_cp():
    if CHECKPOINT.exists():
        return json.loads(CHECKPOINT.read_text(encoding="utf-8"))
    return {"done": [], "unavailable": []}


def save_cp(cp):
    CHECKPOINT.write_text(json.dumps(cp, ensure_ascii=False, indent=2), encoding="utf-8")


def get_target_refs():
    cp = load_cp()
    already = set(cp.get("done", [])) | set(cp.get("unavailable", []))
    con = sqlite3.connect(str(DB_PATH), timeout=60)
    con.row_factory = sqlite3.Row
    cur = con.execute("""
        SELECT DISTINCT lfs.reference_id, lfs.doi, lfs.pmid,
               rl.title, rl.journal, rl.year
        FROM literature_fulltext_sources lfs
        JOIN ref_literatures rl ON lfs.reference_id = rl.reference_id
        WHERE lfs.status IN ('no_oa', 'failed')
          AND lfs.doi IS NOT NULL AND lfs.doi != ''
        ORDER BY rl.year DESC
    """)
    refs = [dict(r) for r in cur.fetchall() if r["reference_id"] not in already]
    con.close()
    return refs


def scihub_download(doi, try_count=0):
    """
    Try to download a paper from Sci-Hub.
    Returns (local_path, source_info) or (None, None).
    """
    if try_count > 3:
        return None, None

    # Mirrors to try (ordered by recent reliability)
    mirrors = [
        "https://sci-hub.se",
        "https://sci-hub.ru",
        "https://sci-hub.st",
    ]

    mirror = mirrors[try_count % len(mirrors)]

    try:
        # Step 1: Access Sci-Hub page for this DOI
        scihub_url = f"{mirror}/{doi}"
        req = urllib.request.Request(scihub_url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            html = resp.read().decode("utf-8", errors="ignore")

        # Check for CAPTCHA
        if "captcha" in html.lower() or "verify you are human" in html.lower():
            time.sleep(3)
            return scihub_download(doi, try_count + 1)  # retry with different mirror

        # Check if paper not found
        if "not found" in html.lower() or "not available" in html.lower():
            return None, "not_available"

        # Step 2: Look for PDF URL in the page
        # Sci-Hub embeds the PDF as an <iframe> or <embed> with src=...
        pdf_url = None

        # Pattern 1: <embed> or <iframe> with src to PDF
        embed_match = re.search(r'(?:embed|iframe)\s[^>]*src\s*=\s*["\']([^"\']+\.pdf)["\']', html, re.I)
        if embed_match:
            pdf_url = embed_match.group(1)
            if pdf_url.startswith("//"):
                pdf_url = "https:" + pdf_url
            elif pdf_url.startswith("/"):
                pdf_url = mirror + pdf_url

        # Pattern 2: Direct PDF link in button/onclick
        if not pdf_url:
            btn_match = re.search(r'(?:href|onclick).*?["\']/(?:downloads|stream)/[^"\']+', html, re.I)
            if btn_match:
                path = btn_match.group(0).split('"')[0].split("'")[0]
                pdf_url = mirror + path if path.startswith("/") else path

        # Pattern 3: Any absolute PDF URL
        if not pdf_url:
            pdf_match = re.search(r'https?://[^"\'\s]+\.pdf[^"\'\s]*', html)
            if pdf_match:
                pdf_url = pdf_match.group(0).split("'")[0].split('"')[0]

        if not pdf_url:
            # Maybe the page has a direct view via #pdf
            for hash_url in [f"{mirror}/{doi}#pdf", f"{mirror}/{doi}#view"]:
                try:
                    req2 = urllib.request.Request(hash_url, headers={"User-Agent": UA, "Referer": scihub_url})
                    with urllib.request.urlopen(req2, timeout=TIMEOUT) as resp2:
                        html2 = resp2.read().decode("utf-8", errors="ignore")
                    embed = re.search(r'(?:embed|iframe).*?src\s*=\s*["\']([^"\']+\.pdf)["\']', html2, re.I)
                    if embed:
                        pdf_url = embed.group(1)
                        if pdf_url.startswith("//"):
                            pdf_url = "https:" + pdf_url
                        break
                except Exception:
                    continue

        if not pdf_url:
            return None, "no_pdf_url_found"

        # Step 3: Download the PDF
        req3 = urllib.request.Request(pdf_url, headers={
            "User-Agent": UA,
            "Referer": scihub_url,
        })
        with urllib.request.urlopen(req3, timeout=TIMEOUT) as resp3:
            content = resp3.read()

        # Validate: is it actually a PDF?
        if len(content) < 5000:
            return None, "too_small"
        if not content.startswith(b"%PDF") and b"PDF" not in content[:100]:
            return None, "not_a_pdf"

        # Save
        clean = doi.replace("/", "_").replace(".", "_")[:80]
        path = OA_DIR / f"{clean}_scihub.pdf"
        path.write_bytes(content)

        return str(path), mirror

    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None, "not_found"
        if e.code == 429:
            time.sleep(5)
            return scihub_download(doi, try_count + 1)
        return None, f"HTTP_{e.code}"
    except urllib.error.URLError as e:
        if "SSL" in str(e) or "EOF" in str(e):
            return scihub_download(doi, try_count + 1)  # retry other mirror
        return None, f"network_error"
    except Exception as e:
        return None, str(e)[:80]


def update_db(con, ref_id, source, local_path=None):
    if local_path:
        con.execute("""UPDATE literature_fulltext_sources
            SET status='downloaded', source=?, local_path=?, content_type='application/pdf'
            WHERE reference_id=? AND status IN ('no_oa','failed')""",
            (source, local_path, ref_id))


def print_ascii_bar(label, count, total, width=40):
    pct = count / max(1, total)
    filled = int(width * pct)
    bar = "█" * filled + "░" * (width - filled)
    return f"{label}: {bar} {count}/{total} ({pct*100:.0f}%)"


def main():
    print("=" * 70)
    print("Sci-Hub BATCH DOWNLOAD")
    print("=" * 70)
    print()

    con = sqlite3.connect(str(DB_PATH), timeout=60)
    con.row_factory = sqlite3.Row

    refs = get_target_refs()
    print(f"Target refs: {len(refs):,}")
    no_oa = sum(1 for r in refs if r["status"] == "no_oa")
    failed = sum(1 for r in refs if r["status"] == "failed")
    print(f"  no_oa: {no_oa:,}  |  failed: {failed:,}")
    print()

    cp = load_cp()
    stats = Counter()
    t0 = time.time()
    batch_t0 = time.time()

    for i, ref in enumerate(refs):
        ref_id = ref["reference_id"]
        doi = ref["doi"] or ""

        if not doi:
            stats["no_doi"] += 1
            cp.setdefault("unavailable", []).append(ref_id)
            continue

        print(f"\r[{i+1}/{len(refs)}] {doi[:60]}...", end="", flush=True)

        pdf_path, info = scihub_download(doi)

        if pdf_path:
            source = f"scihub_{Path(info).stem}" if info and "/" in str(info) else "scihub"
            update_db(con, ref_id, source, pdf_path)
            cp.setdefault("done", []).append(ref_id)
            stats["success"] += 1
            stats[f"mirror_{info}"] += 1 if info and info.startswith("http") else 0
        else:
            # Could try next time
            if info == "not_available" or info == "not_found":
                cp.setdefault("unavailable", []).append(ref_id)
                stats["unavailable"] += 1
            else:
                stats["error"] += 1
                if "error_detail" not in cp:
                    cp["error_detail"] = {}
                cp["error_detail"][str(ref_id)] = str(info)

        stats["total"] += 1

        # Periodic commit
        if stats["total"] % 50 == 0:
            con.commit()
            save_cp(cp)
            elapsed = time.time() - batch_t0
            rate = 50 / elapsed if elapsed > 0 else 0
            batch_t0 = time.time()
            total_elapsed = time.time() - t0
            print(f"\r  [{stats['total']}/{len(refs)}] "
                  f"OK={stats['success']} unavail={stats['unavailable']} "
                  f"err={stats['error']} | "
                  f"{rate:.1f}/s | "
                  f"total {total_elapsed/60:.0f}min"
                  f"     ")

        time.sleep(SLEEP)

    con.commit()
    save_cp(cp)
    con.close()

    total_time = time.time() - t0
    print(f"\n{'=' * 70}")
    print("Sci-HUB DOWNLOAD COMPLETE")
    print(f"{'=' * 70}")
    print(f"  Time: {total_time/60:.1f} min")
    print(f"  Total attempted: {stats['total']:,}")
    print(f"  Downloaded: {stats['success']:,} ({stats['success']/max(1,stats['total'])*100:.1f}%)")
    print(f"  Unavailable: {stats['unavailable']:,}")
    print(f"  Errors: {stats['error']:,}")
    print(f"\n  Files saved to: {OA_DIR}")

    # Final DB state
    con = sqlite3.connect(str(DB_PATH), timeout=60)
    cur = con.cursor()
    for row in cur.execute("SELECT status, COUNT(DISTINCT reference_id) FROM literature_fulltext_sources GROUP BY status"):
        print(f"  DB {row[0]}: {row[1]:,}")
    con.close()


if __name__ == "__main__":
    main()
