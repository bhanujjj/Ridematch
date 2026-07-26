#!/usr/bin/env python3
"""
RideMatch /match latency benchmark.

Measures end-to-end p50/p90/p95/p99 latency of the match API (which includes
Feast->Redis online feature fetch + sklearn inference for 100 candidates).

Usage:
    python scripts/bench_latency.py                      # 500 reqs, 10 concurrent
    python scripts/bench_latency.py -n 2000 -c 50
    python scripts/bench_latency.py --url http://localhost:8000 --top-k 5
"""

import argparse
import asyncio
import json
import random
import statistics
import time
from pathlib import Path

import httpx

# Rough SF bounding box – matches data_sim/generator.py geography closely enough.
LAT_RANGE = (37.70, 37.82)
LON_RANGE = (-122.51, -122.38)


def pct(sorted_vals, p):
    if not sorted_vals:
        return float("nan")
    k = (len(sorted_vals) - 1) * (p / 100.0)
    lo, hi = int(k), min(int(k) + 1, len(sorted_vals) - 1)
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (k - lo)


async def worker(client, url, top_k, n, results, errors, warmup=False):
    for _ in range(n):
        payload = {
            "rider_id": f"rider_{random.randint(0, 9999)}",
            "rider_lat": random.uniform(*LAT_RANGE),
            "rider_lon": random.uniform(*LON_RANGE),
            "top_k": top_k,
        }
        t0 = time.perf_counter()
        try:
            r = await client.post(f"{url}/match", json=payload)
            dt = (time.perf_counter() - t0) * 1000.0
            if r.status_code != 200:
                errors.append(f"HTTP {r.status_code}: {r.text[:200]}")
                continue
            if not warmup:
                results.append(dt)
        except Exception as e:  # noqa: BLE001
            errors.append(f"{type(e).__name__}: {e}")


async def run(args):
    limits = httpx.Limits(max_connections=args.concurrency + 10,
                          max_keepalive_connections=args.concurrency + 10)
    timeout = httpx.Timeout(args.timeout)

    async with httpx.AsyncClient(limits=limits, timeout=timeout) as client:
        # Health probe
        try:
            probe = await client.post(
                f"{args.url}/match",
                json={"rider_id": "probe", "rider_lat": 37.77,
                      "rider_lon": -122.42, "top_k": args.top_k},
            )
        except Exception as e:  # noqa: BLE001
            print(f"Cannot reach {args.url}/match -> {type(e).__name__}: {e}")
            print("Is the API running?  uvicorn src.match_api.main:app --port 8000")
            return 1
        if probe.status_code != 200:
            print(f"Probe failed: HTTP {probe.status_code}\n{probe.text[:500]}")
            return 1
        n_matches = len(probe.json().get("matches", []))
        print(f"API reachable. Probe returned {n_matches} matches.")
        if n_matches == 0:
            print("WARNING: 0 matches returned -> Redis online store is likely empty.")
            print("         Run: cd feature_repo && feast apply && python materialize_features.py")

        # Warmup (excluded from stats)
        print(f"Warming up ({args.warmup} requests)...")
        await asyncio.gather(*[
            worker(client, args.url, args.top_k, max(1, args.warmup // args.concurrency),
                   [], [], warmup=True)
            for _ in range(args.concurrency)
        ])

        results, errors = [], []
        per_worker = max(1, args.requests // args.concurrency)
        total = per_worker * args.concurrency

        print(f"Running {total} requests at concurrency {args.concurrency}...")
        t_start = time.perf_counter()
        await asyncio.gather(*[
            worker(client, args.url, args.top_k, per_worker, results, errors)
            for _ in range(args.concurrency)
        ])
        wall = time.perf_counter() - t_start

    if not results:
        print("No successful requests.")
        for e in errors[:5]:
            print("  ", e)
        return 1

    s = sorted(results)
    summary = {
        "url": args.url,
        "requests_ok": len(results),
        "requests_failed": len(errors),
        "concurrency": args.concurrency,
        "top_k": args.top_k,
        "wall_seconds": round(wall, 3),
        "throughput_rps": round(len(results) / wall, 1),
        "latency_ms": {
            "min": round(s[0], 2),
            "mean": round(statistics.fmean(s), 2),
            "p50": round(pct(s, 50), 2),
            "p90": round(pct(s, 90), 2),
            "p95": round(pct(s, 95), 2),
            "p99": round(pct(s, 99), 2),
            "max": round(s[-1], 2),
        },
    }

    print("\n" + "=" * 46)
    print("  RideMatch /match latency")
    print("=" * 46)
    print(f"  ok / failed     : {summary['requests_ok']} / {summary['requests_failed']}")
    print(f"  concurrency     : {args.concurrency}")
    print(f"  throughput      : {summary['throughput_rps']} req/s")
    print("-" * 46)
    for k, v in summary["latency_ms"].items():
        print(f"  {k:<8}        : {v:>9.2f} ms")
    print("=" * 46)

    if errors:
        print(f"\nFirst errors ({len(errors)} total):")
        for e in errors[:5]:
            print("  ", e)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, indent=2))
    print(f"\nSaved -> {out}")
    return 0


def main():
    p = argparse.ArgumentParser(description="Benchmark RideMatch /match latency")
    p.add_argument("--url", default="http://localhost:8000")
    p.add_argument("-n", "--requests", type=int, default=500)
    p.add_argument("-c", "--concurrency", type=int, default=10)
    p.add_argument("--top-k", type=int, default=5)
    p.add_argument("--warmup", type=int, default=20)
    p.add_argument("--timeout", type=float, default=30.0)
    p.add_argument("--out", default="reports/latency.json")
    args = p.parse_args()
    raise SystemExit(asyncio.run(run(args)))


if __name__ == "__main__":
    main()
