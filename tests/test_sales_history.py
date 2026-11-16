"""Sales history (guide task 3.1)."""
from datetime import date, time, timedelta

from sqlalchemy import delete

from app import seed
from app.models import StockLedger
from scripts.generate_sales import FESTIVAL_DAYS_AGO, UTC_OFFSET, draw_history

from .conftest import assert_stock_is_consistent

TODAY = date(2026, 11, 17)
SKUS = [(n, category) for n, (_name, category, *_rest) in enumerate(seed.SKUS, start=1)]


def units_by_day(rows):
    totals = {}
    for _sku, ts, units in rows:
        totals[ts.date()] = totals.get(ts.date(), 0) + units
    return totals


def test_seed_history_rows_balance_on_their_own(db):
    db.execute(delete(StockLedger).where(StockLedger.reference == "history"))
    db.commit()
    assert_stock_is_consistent()


def test_same_seed_draws_the_same_history():
    first = draw_history(SKUS, days=60, seed=42, today=TODAY)
    assert first == draw_history(SKUS, days=60, seed=42, today=TODAY)
    assert first != draw_history(SKUS, days=60, seed=43, today=TODAY)


def test_history_covers_the_last_days_but_not_today():
    days = units_by_day(draw_history(SKUS, days=60, seed=42, today=TODAY))
    assert min(days) == TODAY - timedelta(days=60)
    assert max(days) == TODAY - timedelta(days=1)


def test_sales_happen_in_store_hours_and_peak_in_the_evening():
    rows = draw_history(SKUS, days=60, seed=42, today=TODAY)
    assert all(time(1, 30) <= ts.time() < time(18, 30) for _, ts, _ in rows)    # 07:00-23:59 IST
    by_hour = {}
    for _, ts, units in rows:
        by_hour[(ts + UTC_OFFSET).hour] = by_hour.get((ts + UTC_OFFSET).hour, 0) + units
    assert set(sorted(by_hour, key=by_hour.get)[-2:]) == {19, 20}


def test_weekends_and_festivals_sell_more():
    days = units_by_day(draw_history(SKUS, days=60, seed=42, today=TODAY))
    festivals = {TODAY - timedelta(days=n) for n in FESTIVAL_DAYS_AGO}
    normal = {d: u for d, u in days.items() if d not in festivals}
    weekend = [u for d, u in normal.items() if d.weekday() >= 5]
    weekday = [u for d, u in normal.items() if d.weekday() < 5]
    assert sum(weekend) / len(weekend) > 1.2 * sum(weekday) / len(weekday)
    average = sum(normal.values()) / len(normal)
    assert all(days[d] > 1.5 * average for d in festivals)
