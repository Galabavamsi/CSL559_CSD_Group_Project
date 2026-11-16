"""Generate a reproducible sales history for the demo stores (Member 3 guide, task 3.1).

The demo data has one week of sales for four SKUs, which is too little to build or judge a forecast on.
This script draws `days` days of sales for every SKU a store carries: a Poisson draw around a base demand
per category, busier at weekends and on two festival days, sold mostly in the evening peak.

The history goes straight into the stock ledger, as app/seed.py does, because it is demo history and not a
stock movement. Each SKU gets one `sale` row per day it sold, plus one `receipt` row for the same total,
dated a day before its first sale, all tagged reference="history". Those rows sum to zero, so stock on hand
and the ledger keep agreeing, and a re-run can delete them and draw again.

Run it from the repository root (it uses the app's database, DARKSTORE_DB, by default ./darkstore.db):

    python scripts/generate_sales.py [--store N] [--days 60] [--seed 42]
"""
import argparse
import math
import random
import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path

if __package__ in (None, ""):          # run as a file: make `import app` work
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import delete, func, select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.db import SessionLocal, init_db  # noqa: E402
from app.errors import DomainError  # noqa: E402
from app.models import SKU, StockLedger, StockLevel, Store, utcnow  # noqa: E402
from app.modules.inventory import service as inventory  # noqa: E402
from app.seed import seed_if_empty  # noqa: E402

# Units sold on an ordinary weekday, by category (guide task 3.1, step 2). Other categories sell DEFAULT_DEMAND.
BASE_DEMAND = {"Dairy": 20, "Bakery": 12, "Staples": 4, "Frozen": 2}
DEFAULT_DEMAND = 3
WEEKEND_FACTOR = 1.35                         # Saturday and Sunday are busier
FESTIVAL_FACTOR = 2.0                         # demand doubles on a festival day
FESTIVAL_DAYS_AGO = (14, 42)                  # two festivals inside the default 60-day window
# Store hours 07:00-23:59 local time; 19:00-20:59 is the evening peak (HLD 2.2), four times as busy.
HOUR_WEIGHTS = {h: 4 if h in (19, 20) else 1 for h in range(7, 24)}
UTC_OFFSET = timedelta(hours=5, minutes=30)   # the stores run on IST; the ledger stores naive UTC


def _poisson(rng: random.Random, mean: float) -> int:
    """One Poisson draw, by Knuth's multiplication method (fine for the small means used here)."""
    limit, units, product = math.exp(-mean), 0, rng.random()
    while product > limit:
        units += 1
        product *= rng.random()
    return units


def draw_history(skus: list[tuple[int, str]], days: int, seed: int,
                 today: date) -> list[tuple[int, datetime, int]]:
    """Draw units sold per SKU per day for the `days` days before `today` (today itself is left out).

    `skus` holds (sku_id, category) pairs. Returns one (sku_id, naive UTC timestamp, units) row for each SKU
    and day that sold at least one unit. The same arguments always give the same rows.
    """
    rng = random.Random(seed)
    festivals = {today - timedelta(days=n) for n in FESTIVAL_DAYS_AGO}
    hours, weights = list(HOUR_WEIGHTS), list(HOUR_WEIGHTS.values())
    rows = []
    for days_ago in range(days, 0, -1):
        day = today - timedelta(days=days_ago)
        factor = WEEKEND_FACTOR if day.weekday() >= 5 else 1.0
        if day in festivals:
            factor *= FESTIVAL_FACTOR
        for sku_id, category in skus:
            units = _poisson(rng, BASE_DEMAND.get(category, DEFAULT_DEMAND) * factor)
            if units:
                local = datetime.combine(day, time(rng.choices(hours, weights)[0], rng.randrange(60)))
                rows.append((sku_id, local - UTC_OFFSET, units))
    return rows


def clear_history(db: Session, store_id: int) -> int:
    """Delete one store's history (ledger rows with reference="history") and return how many rows went.

    Refuses, deleting nothing, when some SKU's history rows do not sum to zero: a database made before the
    seed gave its history a matching receipt. Removing those rows would leave the ledger disagreeing with the
    stock on hand. Does not commit.
    """
    is_history = (StockLedger.store_id == store_id, StockLedger.reference == "history")
    unbalanced = list(db.scalars(
        select(StockLedger.sku_id).where(*is_history)
        .group_by(StockLedger.sku_id).having(func.sum(StockLedger.delta) != 0)
    ))
    if unbalanced:
        raise DomainError(409, "unbalanced_history",
                          f"Store {store_id} has sales history with no matching receipt (SKUs {unbalanced}). "
                          "Reset the demo data with `python -m app.seed`, then run this again.",
                          {"sku_ids": unbalanced})
    return db.execute(delete(StockLedger).where(*is_history)).rowcount


def write_history(db: Session, store_id: int, rows: list[tuple[int, datetime, int]],
                  actor: str = "generator") -> int:
    """Write (sku_id, ts, units) sales as history and return the units written. Does not commit.

    Each row becomes a `sale` ledger row. Each SKU also gets one `receipt` row for its total, dated a day
    before its first sale, so the history sums to zero and stock on hand is unchanged.
    """
    totals: dict[int, int] = {}
    first_sale: dict[int, datetime] = {}
    for sku_id, ts, units in rows:
        db.add(StockLedger(store_id=store_id, sku_id=sku_id, bin_id=None, delta=-units, reason="sale",
                           reference="history", actor=actor, ts=ts))
        totals[sku_id] = totals.get(sku_id, 0) + units
        first_sale[sku_id] = min(ts, first_sale.get(sku_id, ts))
    for sku_id, units in totals.items():
        db.add(StockLedger(store_id=store_id, sku_id=sku_id, bin_id=None, delta=units, reason="receipt",
                           reference="history", actor=actor, ts=first_sale[sku_id] - timedelta(days=1)))
    return sum(totals.values())


def generate(store_id: int, days: int = 60, seed: int = 42, db: Session | None = None) -> dict:
    """Replace one store's sales history with `days` days of seeded sales for every SKU it carries, and commit.

    The same store, days, seed and date always give the same history; the store id is mixed into the seed,
    so two stores never get an identical copy. Without `db` it works on the app's database, creating and
    seeding it first if needed.
    """
    if db is None:
        init_db()
        with SessionLocal() as own:
            seed_if_empty(own)
            return generate(store_id, days, seed, db=own)
    if days < 1:
        raise DomainError(422, "bad_days", "days must be at least 1")
    inventory.get_store(db, store_id)
    skus = [(sku_id, category) for sku_id, category in db.execute(
        select(StockLevel.sku_id, SKU.category).join(SKU, SKU.id == StockLevel.sku_id)
        .where(StockLevel.store_id == store_id).order_by(StockLevel.sku_id)
    )]
    rows = draw_history(skus, days, seed * 1000 + store_id, utcnow().date())
    clear_history(db, store_id)
    units = write_history(db, store_id, rows)
    db.commit()
    return {"store_id": store_id, "days": days, "seed": seed, "skus": len(skus), "sale_rows": len(rows),
            "units": units}


def main(argv: list[str] | None = None) -> int:
    """Command line: write the history for one store, or every store, and print what was written."""
    parser = argparse.ArgumentParser(description="Write a seeded sales history into the demo database.")
    parser.add_argument("--store", type=int, help="store id (default: every store)")
    parser.add_argument("--days", type=int, default=60, help="days of history before today (default: 60)")
    parser.add_argument("--seed", type=int, default=42, help="random seed (default: 42)")
    args = parser.parse_args(argv)
    init_db()
    with SessionLocal() as db:
        seed_if_empty(db)
        store_ids = [args.store] if args.store is not None else list(db.scalars(select(Store.id).order_by(Store.id)))
        try:
            for store_id in store_ids:
                result = generate(store_id, args.days, args.seed, db=db)
                print(f"Store {store_id}: {result['days']} days, {result['skus']} SKUs, {result['units']} units "
                      f"in {result['sale_rows']} sale rows (seed {result['seed']})")
        except DomainError as error:
            print(f"error: {error.message}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
