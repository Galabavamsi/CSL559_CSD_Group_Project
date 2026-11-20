"""Benchmark the ATP cache (Member 1 guide, task 1.6): time whole-store availability reads with the cache off and on.

HLD 3 expects reads to outnumber stock writes about 13 to 1, so by default every 13th call is a checkout hold
(released straight away). Each hold clears the store's cached list, so this measures a realistic hit rate rather than
a cache that never changes. Only the availability reads are timed.

    python scripts/bench_availability.py                 # in-process, on a throw-away copy of the demo data
    python scripts/bench_availability.py --requests 5000 --write-every 0     # reads only

In-process means no network and no web server, so the numbers show the database work the cache saves, not what a
customer's phone would see. A laptop is not the HLD's cluster: compare the two runs with each other, not with HLD 12.
"""
import argparse
import os
import statistics
import sys
import tempfile
import time
import uuid
from pathlib import Path

os.environ.setdefault("DARKSTORE_DB", f"sqlite:///{tempfile.mkdtemp()}/bench.db")   # never touch the real data
os.environ["BACKGROUND_JOBS"] = "off"
os.environ["RATE_LIMIT_PER_SECOND"] = "0"          # one client sending thousands of calls would be throttled
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402

from app import config, seed  # noqa: E402
from app.cache import atp_cache  # noqa: E402
from app.main import app  # noqa: E402
from app.metrics import ATP_CACHE  # noqa: E402

STORE = 1


def _count(result: str) -> float:
    return ATP_CACHE.labels(result)._value.get()


def run(client: TestClient, requests: int, write_every: int, cache_seconds: float) -> dict:
    seed.reset()
    atp_cache.ttl = cache_seconds
    atp_cache.clear()
    rice = next(row["sku_id"] for row in client.get(f"/v1/stores/{STORE}/availability").json()
                if row["name"].startswith("Basmati rice"))
    hits, misses = _count("hit"), _count("miss")
    times = []
    for n in range(1, requests + 1):
        if write_every and n % write_every == 0:
            held = client.post("/v1/reservations", json={"order_id": f"bench-{uuid.uuid4()}", "store_id": STORE,
                                                         "lines": [{"sku_id": rice, "qty": 1}]}).json()
            client.delete(f"/v1/reservations/{held['reservation_id']}")
        start = time.perf_counter()
        res = client.get(f"/v1/stores/{STORE}/availability")
        times.append((time.perf_counter() - start) * 1000)
        assert res.status_code == 200, res.text
    times.sort()
    looked_up = (_count("hit") - hits) + (_count("miss") - misses)
    return {"median_ms": statistics.median(times), "p99_ms": times[int(0.99 * (len(times) - 1))],
            "hit_rate": (_count("hit") - hits) / looked_up if looked_up else 0.0}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--requests", type=int, default=2000)
    parser.add_argument("--write-every", type=int, default=13, help="a hold every N reads; 0 for reads only")
    args = parser.parse_args()
    with TestClient(app) as client:
        print(f"{args.requests} whole-store availability reads, store {STORE}, "
              + (f"a hold every {args.write_every} reads" if args.write_every else "no writes"))
        print(f"{'cache':<14}{'median ms':>10}{'p99 ms':>10}{'hit rate':>10}")
        for label, seconds in (("off", 0), (f"on ({config.ATP_CACHE_SECONDS:g} s)", config.ATP_CACHE_SECONDS)):
            r = run(client, args.requests, args.write_every, seconds)
            print(f"{label:<14}{r['median_ms']:>10.2f}{r['p99_ms']:>10.2f}{r['hit_rate']:>10.0%}")


if __name__ == "__main__":
    main()
