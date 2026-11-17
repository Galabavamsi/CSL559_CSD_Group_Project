"""Sales history (guide task 3.1)."""
from datetime import date, time, timedelta

import pytest
from sqlalchemy import delete, func, select

from app import seed
from app.errors import DomainError
from app.models import StockLedger
from app.modules.inventory import service as inventory
from scripts.generate_sales import FESTIVAL_DAYS_AGO, UTC_OFFSET, draw_history, generate, main

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


def history_rows(db, store_id=1):
    return db.scalar(select(func.count()).select_from(StockLedger)
                     .where(StockLedger.store_id == store_id, StockLedger.reference == "history"))


def test_generated_history_keeps_stock_consistent(db, sku):
    summary = generate(1, db=db)
    generate(2, db=db)                     # store 2 carries bananas with no stock and no bin
    assert summary["skus"] == 16 and summary["units"] > 0
    assert inventory.get_level(db, 1, sku("Toned milk")).qty_on_hand == 30
    assert_stock_is_consistent()


def test_generating_again_replaces_the_history(db):
    first = generate(1, db=db)
    rows = history_rows(db)
    assert generate(1, db=db) == first and history_rows(db) == rows
    assert db.scalar(select(func.count()).select_from(StockLedger)
                     .where(StockLedger.actor == "seed", StockLedger.reference == "history")) == 0
    assert_stock_is_consistent()


def test_generator_refuses_history_that_does_not_balance(db, sku):
    db.add(StockLedger(store_id=1, sku_id=sku("Tea"), delta=-5, reason="sale", reference="history"))
    db.commit()                            # looks like a darkstore.db from before Task 1
    rows = history_rows(db)
    with pytest.raises(DomainError) as refused:
        generate(1, db=db)
    assert refused.value.code == "unbalanced_history" and "python -m app.seed" in refused.value.message
    assert history_rows(db) == rows


def test_generator_rejects_unknown_store_and_bad_days(db):
    with pytest.raises(DomainError) as unknown:
        generate(99, db=db)
    with pytest.raises(DomainError) as bad:
        generate(1, days=0, db=db)
    assert unknown.value.status == 404 and bad.value.status == 422


def test_command_line_writes_every_store_and_reports_errors(capsys):
    assert main([]) == 0
    out = capsys.readouterr().out
    assert out.startswith("Store 1: 60 days, 16 SKUs") and "Store 2: 60 days, 16 SKUs" in out
    assert main(["--store", "99"]) == 1
    assert "Store 99 does not exist" in capsys.readouterr().err
    assert_stock_is_consistent()


def test_each_store_gets_its_own_history(db):
    assert generate(1, db=db)["units"] != generate(2, db=db)["units"]
    assert_stock_is_consistent()
