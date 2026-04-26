"""
Burst load test: 100 concurrent POST /predict requests.

Usage:
    # Start the API first (baseline mode, no pickle needed):
    MODEL_VARIANT=baseline uvicorn app.main:app --host 0.0.0.0 --port 8000

    # Then run:
    python tests/load_test.py [--url http://localhost:8000] [--n 100]

Exit code 1 if p95 latency exceeds the 800ms SLO.
"""
from __future__ import annotations

import argparse
import asyncio
import statistics
import sys
import time

import httpx

PAYLOAD = {"rows": [{"ret_mean": 0.05, "ret_std": 0.01, "n": 50}]}
SLO_P95_MS = 800.0


async def _single_request(
    client: httpx.AsyncClient,
    url: str,
) -> tuple[float, int]:
    start = time.perf_counter()
    r = await client.post(url, json=PAYLOAD)
    elapsed_ms = (time.perf_counter() - start) * 1000
    return elapsed_ms, r.status_code


async def burst(base_url: str, n: int) -> None:
    predict_url = f"{base_url}/predict"
    print(f"Sending {n} concurrent requests to {predict_url}...")

    async with httpx.AsyncClient(timeout=10.0) as client:
        tasks = [_single_request(client, predict_url) for _ in range(n)]
        results = await asyncio.gather(*tasks, return_exceptions=True)

    latencies: list[float] = []
    errors: list[str] = []

    for r in results:
        if isinstance(r, Exception):
            errors.append(str(r))
        elif r[1] != 200:
            errors.append(f"HTTP {r[1]}")
        else:
            latencies.append(r[0])

    if not latencies:
        print("ERROR: All requests failed.")
        sys.exit(1)

    latencies.sort()
    total = len(latencies)

    def pct(p: float) -> float:
        idx = min(int(total * p / 100), total - 1)
        return latencies[idx]

    p50 = pct(50)
    p95 = pct(95)
    p99 = pct(99)

    print(f"\n{'─'*40}")
    print(f"  Requests:  {total} ok, {len(errors)} errors")
    print(f"  Min:       {min(latencies):.1f} ms")
    print(f"  p50:       {p50:.1f} ms")
    print(f"  p95:       {p95:.1f} ms  (SLO: {SLO_P95_MS:.0f} ms)")
    print(f"  p99:       {p99:.1f} ms")
    print(f"  Max:       {max(latencies):.1f} ms")
    print(f"  StdDev:    {statistics.stdev(latencies):.1f} ms")
    print(f"{'─'*40}")

    if errors:
        print(f"\nErrors: {errors[:5]}")

    if p95 > SLO_P95_MS:
        print(f"\nSLO BREACH: p95 {p95:.1f}ms > {SLO_P95_MS:.0f}ms")
        sys.exit(1)

    print("\nSLO OK")


def main() -> None:
    parser = argparse.ArgumentParser(description="Burst load test for /predict")
    parser.add_argument("--url", default="http://localhost:8000", help="Base URL of the API")
    parser.add_argument("--n", type=int, default=100, help="Number of concurrent requests")
    args = parser.parse_args()

    asyncio.run(burst(args.url, args.n))


if __name__ == "__main__":
    main()
