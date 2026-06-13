#!/usr/bin/env python3
"""TTFB / Performance benchmark for AquaVir-KB (Phase 6)

Usage (inside container or from host with network access to the container):

    python3 benchmark_ttfb.py --url https://aquavir-kb.org --runs 20

Targets:
    - /           (homepage, SSR)
    - /api/dashboard  (aggregated JSON, cached)
    - /search?q=shrimp  (search results, SSR)
    - /virus/NC_001526  (detail page, SSR)

Expectations on 2C/4GB cloud:
    - TTFB < 200 ms for cached endpoints
    - TTFB < 800 ms for SSR pages (cold)
    - 95th percentile < 1200 ms
"""
import argparse
import statistics
import sys
import time
from urllib.request import Request, urlopen


def measure_ttfb(url: str, headers: dict = None, timeout: int = 30) -> float:
    """Return TTFB in milliseconds."""
    req = Request(url, headers=headers or {})
    t0 = time.perf_counter()
    with urlopen(req, timeout=timeout) as resp:
        _ = resp.read(1)  # trigger first byte
    t1 = time.perf_counter()
    return (t1 - t0) * 1000


def benchmark(url_base: str, runs: int = 10):
    endpoints = {
        "homepage": "/",
        "dashboard": "/api/dashboard",
        "search": "/search?q=shrimp",
        "virus_detail": "/virus/NC_001526",
    }

    print(f"Benchmarking {url_base} — {runs} runs each")
    print("=" * 60)

    for name, path in endpoints.items():
        url = url_base.rstrip("/") + path
        times = []
        for i in range(runs):
            try:
                ms = measure_ttfb(url)
                times.append(ms)
            except Exception as e:
                print(f"  [{name}] run {i+1} failed: {e}")
                continue

        if not times:
            print(f"  {name:20s} — all runs failed")
            continue

        avg = statistics.mean(times)
        med = statistics.median(times)
        p95 = sorted(times)[int(len(times) * 0.95)] if len(times) > 1 else times[0]
        mini, maxi = min(times), max(times)

        status = "✅" if avg < 500 else "⚠️" if avg < 1200 else "❌"
        print(
            f"  {status} {name:18s}  avg={avg:6.1f}ms  med={med:6.1f}ms  "
            f"p95={p95:6.1f}ms  min={mini:6.1f}ms  max={maxi:6.1f}ms"
        )

    print("=" * 60)


def main():
    parser = argparse.ArgumentParser(description="AquaVir-KB TTFB benchmark")
    parser.add_argument("--url", default="http://localhost", help="Base URL")
    parser.add_argument("--runs", type=int, default=10, help="Number of runs per endpoint")
    args = parser.parse_args()
    benchmark(args.url, args.runs)


if __name__ == "__main__":
    main()
