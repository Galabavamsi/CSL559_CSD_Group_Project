"""Batch picking (Member 2 guide, task 2.6): how far does a picker walk for the same orders, one at a time versus in
batches?

HLD 13.1 chose "single-order off-peak, batch picking at peak" because batching should raise throughput at peak. This
measures the walking. The distance model is the guide's: a walk from the packing desk out to the shelves and back costs
twice the highest walk_seq it visits (bin 1 is next to the desk).

The script places the same random paid orders in store 1 twice, on a fresh copy of the demo data each time, and has
one picker clear the queue: first with next-task (one order per walk), then with next-batch (up to BATCH_SIZE orders
per walk while at least BATCH_PICK_BACKLOG wait, then one at a time). Every order is waiting when picking starts, as
at peak. Each walk is picked and packed for real, so the stock audit still holds afterwards.

    python scripts/compare_picking.py [--orders 30] [--batch 3] [--seed 7]

It never touches darkstore.db: it works on a temporary database.
"""
import argparse
import os
import random
import sys
import tempfile
from pathlib import Path

if __package__ in (None, ""):          # run as a file: make `import app` work
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

PICKER = "walker"


def walk_distance(jobs) -> int:
    """Out to the furthest bin any of these orders still needs, and back."""
    return 2 * max((task.bin.walk_seq for job in jobs for task in job.tasks
                    if task.status == "pending" and task.bin is not None), default=0)


def place_orders(db, count: int, rng: random.Random, store_id: int = 1) -> int:
    """Pay for `count` random carts of 1-3 different items, 1-2 of each. Returns how many were placed."""
    from app.errors import DomainError
    from app.modules.inventory import service as inventory

    skus = [row["sku_id"] for row in inventory.availability(db, store_id) if row["atp"] > 0]
    placed = 0
    for attempt in range(count * 20):
        if placed == count:
            break
        lines = [(sku_id, rng.randint(1, 2)) for sku_id in rng.sample(skus, rng.randint(1, 3))]
        try:
            held = inventory.reserve(db, f"cmp-{placed + 1}", store_id, lines)
        except DomainError:            # not enough left of something: draw another cart
            db.rollback()
            continue
        inventory.confirm(db, held.id)
        placed += 1
    return placed


def pick_all(db, claim) -> tuple[int, int]:
    """Claim with `claim` until nothing waits; each claim is one walk: scan every line, then pack each order.
    Returns (walks, distance)."""
    from app.modules.pickpack import service as pickpack

    walks = distance = 0
    while jobs := claim():
        walks += 1
        distance += walk_distance(jobs)
        for job in jobs:
            for task in [t for t in job.tasks if t.status == "pending"]:
                pickpack.scan(db, task.id, task.sku.barcode, task.qty)
            pickpack.pack(db, job.id, crate_slot=f"S-{job.tote or 'A'}", actor=PICKER)
    return walks, distance


def compare(orders: int = 30, batch_size: int = 3, random_seed: int = 7, store_id: int = 1) -> dict:
    """Walks and distance for the same orders picked one at a time and in batches, and the saving."""
    from app import config, seed
    from app.db import SessionLocal
    from app.modules.pickpack import service as pickpack

    def one_at_a_time(db):
        job = pickpack.next_job(db, PICKER, store_id)
        return [job] if job else []

    def in_batches(db):
        return pickpack.next_batch(db, PICKER, store_id)

    result = {"orders": orders, "batch_size": batch_size}
    saved_size = config.BATCH_SIZE
    config.BATCH_SIZE = batch_size
    try:
        for name, claim in (("one_at_a_time", one_at_a_time), ("batched", in_batches)):
            seed.reset()
            with SessionLocal() as db:
                result["orders"] = place_orders(db, orders, random.Random(random_seed), store_id)
                walks, distance = pick_all(db, lambda: claim(db))
            result[name] = {"walks": walks, "distance": distance}
    finally:
        config.BATCH_SIZE = saved_size
    single, batched = result["one_at_a_time"]["distance"], result["batched"]["distance"]
    result["saving"] = 1 - batched / single if single else 0.0
    return result


def report(result: dict) -> str:
    n = result["orders"]
    rows = [("One order per walk", result["one_at_a_time"]),
            (f"Batches of up to {result['batch_size']}", result["batched"])]
    lines = [f"{n} paid orders in store 1, all waiting when picking starts (peak).",
             "Distance: 2 x the furthest walk_seq visited per walk, in bin steps.", "",
             f"{'':28}{'walks':>7}{'distance':>10}{'per order':>11}"]
    lines += [f"{label:28}{row['walks']:>7}{row['distance']:>10}{row['distance'] / n:>11.1f}" for label, row in rows]
    lines += ["", f"Batching saves {result['saving']:.0%} of the walking."]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--orders", type=int, default=30)
    parser.add_argument("--batch", type=int, default=3, help="orders per walk at peak (BATCH_SIZE)")
    parser.add_argument("--seed", type=int, default=7, help="random seed, so a run can be repeated")
    args = parser.parse_args()
    # Before anything imports app: a throwaway database, and no timed jobs.
    os.environ["DARKSTORE_DB"] = f"sqlite:///{tempfile.mkdtemp()}/compare_picking.db"
    os.environ["BACKGROUND_JOBS"] = "off"
    print(report(compare(args.orders, args.batch, args.seed)))


if __name__ == "__main__":
    main()
