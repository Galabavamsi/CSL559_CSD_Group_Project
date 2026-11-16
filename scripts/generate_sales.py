"""Generate a reproducible sales history for the demo stores (Member 3 guide, task 3.1).

The demo data has one week of sales for four SKUs, which is too little to build or judge a forecast on.
This script draws `days` days of sales for every SKU a store carries: a Poisson draw around a base demand
per category, busier at weekends and on two festival days, sold mostly in the evening peak.
"""
import math
import random
from datetime import date, datetime, time, timedelta

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
