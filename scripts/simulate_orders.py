"""Timing run (Member 2 guide, task 2.8): random paid orders picked and packed by scripted pickers through the real
API, then the fulfilment KPIs beside their HLD 12 targets.

All orders are paid before picking starts, as at a peak. Each picker asks for work (next-batch: one order when few
wait, up to BATCH_SIZE at peak; or next-task with --single), walks the route nearest bin first, sleeping --step
seconds per walk_seq step, scans every line on the way, walks back to the desk and packs each order. The app runs
in-process (FastAPI's test client, with real logins) on a throwaway copy of the demo data, so no server is needed and
darkstore.db is never touched. At the end it reads GET /v1/stores/{id}/fulfilment-metrics and checks the stock audit.

    python scripts/simulate_orders.py [--orders 100] [--pickers 1] [--step 0.05] [--single] [--seed 7]

Time is compressed: --step 0.05 makes one walk step 0.05 s, and scanning takes no time at all. See the note printed
at the end before quoting the numbers.
"""
import argparse
import logging
import os
import random
import sys
import tempfile
import time
import warnings
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

if __package__ in (None, ""):          # run as a file: make `import app` work
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# (key, label, HLD 12 target, unit, is the target met?)
KPIS = [
    ("seconds_to_pack_p90", "Order to packed (p90)", "≤ 120 s", "s", lambda v: v <= 120),
    ("seconds_to_pack_p50", "Order to packed (p50)", "", "s", None),
    ("seconds_claim_to_pack_p90", "Claim to packed (p90)", "", "s", None),
    ("fill_rate", "Fill rate", "≥ 99% of units", "%", lambda v: v >= 0.99),
    ("items_per_picker_hour", "Items per picker-hour", "≥ 100", "", lambda v: v >= 100),
]


def place_orders(client, count: int, rng: random.Random, store_id: int = 1) -> int:
    """Pay for `count` random carts of 1-3 different items, 1-2 of each, as a customer would. Returns how many."""
    skus = [row["sku_id"] for row in client.get(f"/v1/stores/{store_id}/availability").json() if row["atp"] > 0]
    placed = 0
    for _attempt in range(count * 20):
        if placed == count:
            break
        lines = [{"sku_id": sku_id, "qty": rng.randint(1, 2)} for sku_id in rng.sample(skus, rng.randint(1, 3))]
        held = client.post("/v1/reservations", json={"order_id": f"sim-{placed + 1}", "store_id": store_id,
                                                     "lines": lines})
        if held.status_code != 201:          # not enough left of something: draw another cart
            continue
        paid = client.post(f"/v1/reservations/{held.json()['reservation_id']}/confirm")
        assert paid.status_code == 200, paid.text
        placed += 1
    return placed


def work(client, picker_id: str, store_id: int, step: float, batch: bool) -> int:
    """One scripted picker: claim, walk, scan, walk back, pack, until nothing waits. Returns the number of walks."""
    walks = 0
    while True:
        if batch:
            jobs = client.get(f"/v1/pickers/{picker_id}/next-batch", params={"store_id": store_id}).json()["jobs"]
        else:
            job = client.get(f"/v1/pickers/{picker_id}/next-task", params={"store_id": store_id}).json()["job"]
            jobs = [job] if job else []
        if not jobs:
            return walks
        walks += 1
        lines = sorted(((job, task) for job in jobs for task in job["tasks"] if task["status"] == "pending"),
                       key=lambda line: (line[1]["walk_seq"], line[0]["tote"] or "", line[1]["seq"]))
        here = 0
        for _job, task in lines:
            time.sleep(step * (task["walk_seq"] - here))           # walk on to the next bin
            here = task["walk_seq"]
            scanned = client.post(f"/v1/pick-tasks/{task['task_id']}/scans",
                                  json={"barcode": task["barcode"], "qty": task["qty"], "picker_id": picker_id})
            assert scanned.status_code == 200 and scanned.json()["match"], scanned.text
        time.sleep(step * here)                                     # back to the packing desk
        for job in jobs:
            packed = client.post(f"/v1/fulfilment-jobs/{job['job_id']}/packed",
                                 json={"crate_slot": f"S-{job['tote'] or 'A'}", "picker_id": picker_id})
            assert packed.status_code == 200, packed.text


def stock_problems() -> list[str]:
    """The stock audit (as in the tests): on hand = units in bins = sum of the ledger, and 0 <= held <= on hand."""
    from sqlalchemy import func, select

    from app.db import SessionLocal
    from app.models import StockItem, StockLedger, StockLevel

    problems = []
    with SessionLocal() as db:
        for level in db.scalars(select(StockLevel)).all():
            where = (StockItem.store_id == level.store_id, StockItem.sku_id == level.sku_id)
            in_bins = db.scalar(select(func.coalesce(func.sum(StockItem.qty), 0)).where(*where))
            in_ledger = db.scalar(select(func.coalesce(func.sum(StockLedger.delta), 0))
                                  .where(StockLedger.store_id == level.store_id, StockLedger.sku_id == level.sku_id))
            if not (level.qty_on_hand == in_bins == in_ledger and 0 <= level.qty_reserved <= level.qty_on_hand):
                problems.append(f"store {level.store_id} sku {level.sku_id}: on hand {level.qty_on_hand}, bins "
                                f"{in_bins}, ledger {in_ledger}, held {level.qty_reserved}")
    return problems


def simulate(make_client, orders: int = 100, pickers: int = 1, step: float = 0.05, batch: bool = True,
             random_seed: int = 7, store_id: int = 1) -> dict:
    """Place the orders, let `pickers` scripted pickers clear the queue at once, and read the KPIs."""
    from app import auth

    def logged_in(username: str, role: str):
        client = make_client()
        client.headers["Authorization"] = f"Bearer {auth.make_token(username, role, store_id)}"
        return client

    placed = place_orders(make_client(), orders, random.Random(random_seed), store_id)
    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=pickers) as pool:
        walks = sum(pool.map(lambda n: work(logged_in(f"sim-picker-{n}", "picker"), f"sim-{n}", store_id, step, batch),
                             range(1, pickers + 1)))
    seconds = time.monotonic() - started
    metrics = logged_in("sim-manager", "manager").get(f"/v1/stores/{store_id}/fulfilment-metrics").json()
    return {"orders": placed, "pickers": pickers, "step": step, "batch": batch, "walks": walks,
            "seconds": seconds, "metrics": metrics, "stock_problems": stock_problems()}


def report(result: dict) -> str:
    def shown(value, unit):
        if value is None:
            return "n/a"
        return f"{value:.1%}" if unit == "%" else f"{value:,.1f} {unit}".strip()

    m = result["metrics"]
    mode = "batch picking at peak (next-batch)" if result["batch"] else "one order per walk (next-task)"
    lines = [f"{result['orders']} paid orders, {result['pickers']} picker(s), {mode}, "
             f"{result['step']} s per walk step.",
             f"All orders waiting at the start. Took {result['seconds']:.0f} s and {result['walks']} walks; "
             f"{m['orders_packed']} orders packed.", "",
             f"{'KPI':26}{'Simulated':>14}   {'HLD 12 target':16}Met"]
    for key, label, target, unit, met in KPIS:
        value = m.get(key)
        ok = "" if met is None or value is None else ("yes" if met(value) else "NO")
        lines.append(f"{label:26}{shown(value, unit):>14}   {target:16}{ok}")
    audit = result["stock_problems"]
    lines += ["", "Stock audit: clean" if not audit else "Stock audit FAILED:\n  " + "\n  ".join(audit), "",
              "Note: walking is compressed (one step = --step seconds) and scanning, packing and the walk to the",
              "rider take no time, so items per picker-hour is far above a real floor's. Order-to-packed times mostly",
              "measure queueing: every order waits from the start for one of the pickers."]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--orders", type=int, default=100)
    parser.add_argument("--pickers", type=int, default=1)
    parser.add_argument("--step", type=float, default=0.05, help="seconds per walk_seq step (walking speed)")
    parser.add_argument("--single", action="store_true", help="one order per walk (next-task) instead of batches")
    parser.add_argument("--seed", type=int, default=7, help="random seed, so a run can be repeated")
    args = parser.parse_args()
    # Before anything imports app: a throwaway database, no timed jobs, and no rate limit (the script is one client).
    os.environ["DARKSTORE_DB"] = f"sqlite:///{tempfile.mkdtemp()}/simulate_orders.db"
    os.environ["BACKGROUND_JOBS"] = "off"
    os.environ["RATE_LIMIT_PER_SECOND"] = "0"
    warnings.filterwarnings("ignore", message="Using `httpx`")    # from FastAPI's test client, not ours
    from fastapi.testclient import TestClient

    from app import seed
    from app.main import app

    logging.getLogger("app.requests").setLevel(logging.WARNING)    # one log line per call would drown the report
    seed.reset()
    result = simulate(lambda: TestClient(app), args.orders, args.pickers, args.step, not args.single, args.seed)
    print(report(result))
    sys.exit(1 if result["stock_problems"] else 0)


if __name__ == "__main__":
    main()
