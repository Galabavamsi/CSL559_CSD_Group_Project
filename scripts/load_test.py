"""Load test (Member 4 guide, task 4.8): send a realistic mix of calls for a while, then report p50 and p99.

The mix follows the guide: about 90% reads (availability and serviceability, half each) and 10% checkout
holds. One hold in five is paid (about 2% of all calls); the rest are released straight away, timed as
"release", so the run does not lock up all the stock.

Start the app first with the rate limit off (RATE_LIMIT_PER_SECOND=0 uvicorn app.main:app): this script is one
client, and the limit would refuse most of its calls. Then, from the repository root:

    python scripts/load_test.py [--url http://localhost:8000] [--seconds 60] [--workers 8] [--reset]

--reset wipes and reloads the demo data before the run (it logs in as the demo admin).
A laptop is not a production cluster: these numbers show where time goes, not what the HLD's cluster would do.
"""
import argparse
import random
import sys
import threading
import time
import uuid
from collections import defaultdict
from pathlib import Path

import httpx

if __package__ in (None, ""):          # run as a file: make `import app` work
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import config  # noqa: E402

READ_TARGET_MS = 100                   # HLD: availability and serviceability reads answer in under 100 ms (p99)
READS = ("availability", "serviceability")
HOME = (12.975, 77.600)                # inside DS-01 Central's zone


def percentile(values: list[float], q: float) -> float:
    """The value at index int(q * (n - 1)) of the sorted values: the method the team uses (guide task 2.1)."""
    ordered = sorted(values)
    return ordered[int(q * (len(ordered) - 1))]


def _worker(client: httpx.Client, deadline: float, seed: int, store_id: int, record) -> None:
    rng = random.Random(seed)
    skus = [row["sku_id"] for row in client.get(f"/v1/stores/{store_id}/availability").json() if row["atp"] > 0]

    def timed(label: str, method: str, path: str, **kwargs) -> httpx.Response:
        started = time.perf_counter()
        res = client.request(method, path, **kwargs)
        record(label, res.status_code, time.perf_counter() - started)
        return res

    while time.perf_counter() < deadline:
        roll = rng.random()
        if roll < 0.45:
            timed("availability", "GET", f"/v1/stores/{store_id}/availability")
        elif roll < 0.90:
            point = {"lat": HOME[0] + rng.uniform(-0.01, 0.01), "lng": HOME[1] + rng.uniform(-0.01, 0.01)}
            timed("serviceability", "GET", "/v1/serviceability", params=point)
        else:
            hold = timed("hold", "POST", "/v1/reservations", json={
                "order_id": f"load-{uuid.uuid4().hex}", "store_id": store_id,
                "lines": [{"sku_id": rng.choice(skus), "qty": 1}]})
            if hold.status_code != 201:
                continue
            reservation = hold.json()["reservation_id"]
            if roll >= 0.98:
                timed("payment", "POST", f"/v1/reservations/{reservation}/confirm")
            else:
                timed("release", "DELETE", f"/v1/reservations/{reservation}")


def run(make_client, seconds: float, workers: int, store_id: int = 1) -> dict[str, list[tuple[int, float]]]:
    """Run `workers` threads for `seconds`, each with its own client from `make_client()`.
    Returns (status code, seconds) for every call, grouped by endpoint."""
    results: dict[str, list[tuple[int, float]]] = defaultdict(list)
    lock = threading.Lock()

    def record(label: str, status: int, elapsed: float) -> None:
        with lock:
            results[label].append((status, elapsed))

    deadline = time.perf_counter() + seconds

    def one(n: int) -> None:
        client = make_client()
        try:
            _worker(client, deadline, n, store_id, record)
        finally:
            client.close()

    threads = [threading.Thread(target=one, args=(n,)) for n in range(workers)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    return dict(results)


def summarise(results: dict[str, list[tuple[int, float]]], seconds: float) -> list[dict]:
    rows = []
    for endpoint in ("availability", "serviceability", "hold", "payment", "release"):
        calls = results.get(endpoint, [])
        if not calls:
            continue
        times_ms = [elapsed * 1000 for _, elapsed in calls]
        rows.append({"endpoint": endpoint, "requests": len(calls), "per_second": round(len(calls) / seconds, 1),
                     "out_of_stock": sum(1 for status, _ in calls if status == 409),
                     "limited": sum(1 for status, _ in calls if status == 429),
                     "errors": sum(1 for status, _ in calls if status >= 500),
                     "p50_ms": round(percentile(times_ms, 0.50), 1), "p99_ms": round(percentile(times_ms, 0.99), 1)})
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Load-test a running app and report p50 and p99 per endpoint.")
    parser.add_argument("--url", default="http://localhost:8000", help="base URL of the running app")
    parser.add_argument("--seconds", type=float, default=60, help="how long to run (default: 60)")
    parser.add_argument("--workers", type=int, default=8, help="parallel clients (default: 8)")
    parser.add_argument("--store", type=int, default=1, help="store to order from (default: 1)")
    parser.add_argument("--reset", action="store_true", help="reset the demo data first (logs in as admin)")
    args = parser.parse_args(argv)

    if args.reset:
        with httpx.Client(base_url=args.url, timeout=30) as admin:
            token = admin.post("/v1/auth/login", json={"username": "admin", "password": config.DEMO_PASSWORD})
            token.raise_for_status()
            admin.post("/v1/admin/reset", headers={"Authorization": f"Bearer {token.json()['access_token']}"}
                       ).raise_for_status()

    results = run(lambda: httpx.Client(base_url=args.url, timeout=10), args.seconds, args.workers, args.store)
    rows = summarise(results, args.seconds)
    if not rows:
        print(f"No requests succeeded. Is the app running at {args.url}?", file=sys.stderr)
        return 1

    print(f"{args.workers} workers for {args.seconds:g} s against {args.url}\n")
    print(f"{'endpoint':<15}{'requests':>9}{'per s':>8}{'409':>6}{'429':>6}{'5xx':>6}{'p50 ms':>9}{'p99 ms':>9}")
    for r in rows:
        print(f"{r['endpoint']:<15}{r['requests']:>9}{r['per_second']:>8}{r['out_of_stock']:>6}{r['limited']:>6}"
              f"{r['errors']:>6}{r['p50_ms']:>9}{r['p99_ms']:>9}")
    if any(r["limited"] for r in rows):    # 429s are answered before any work, so the timings say nothing
        print("\nSome calls were refused with 429 by the rate limit, so these timings are not the app's. This script "
              "is one client; start the app with RATE_LIMIT_PER_SECOND=0 for a load test.", file=sys.stderr)
        return 1
    worst = max(r["p99_ms"] for r in rows if r["endpoint"] in READS)
    verdict = "meets" if worst < READ_TARGET_MS else "misses"
    print(f"\nRead p99 {worst} ms {verdict} the HLD target of {READ_TARGET_MS} ms. "
          "This is one laptop and SQLite, not the HLD's cluster.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
