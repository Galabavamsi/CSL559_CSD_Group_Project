"""Forecasting (guide task 3.2): daily sales, backtest, WAPE."""
from datetime import date, datetime, time, timedelta

from app.models import utcnow
from app.modules.forecasting import service as forecasting
from scripts.generate_sales import clear_history, write_history


def plant(db, sku_id, units_by_days_ago, store_id=1):
    """Replace the store's history with {days_ago: units} sales of one SKU, each at noon UTC."""
    today = utcnow().date()
    clear_history(db, store_id)
    write_history(db, store_id, [(sku_id, datetime.combine(today - timedelta(days=n), time(12)), units)
                                 for n, units in units_by_days_ago.items()])
    db.commit()
    return today


def test_daily_sales_counts_whole_days_ending_yesterday(db, sku):
    milk = sku("Toned milk")
    today = plant(db, milk, {0: 5, 1: 7, 7: 9, 8: 11})
    assert forecasting.daily_sales(db, 1, 7) == {
        milk: {today - timedelta(days=1): 7, today - timedelta(days=7): 9}}


def test_forecast_uses_the_seven_days_ending_yesterday(client, sku):
    rows = {r["sku_id"]: r for r in client.post("/v1/forecasting/run", params={"store_id": 1}).json()}
    assert rows[sku("Toned milk")]["daily_demand"] == 21.14     # seed week sums to 148; 148 / 7


def test_moving_average_is_the_mean_of_the_days_before():
    day = date(2026, 11, 10)
    history = {day - timedelta(days=1): 20, day - timedelta(days=2): 10, day - timedelta(days=3): 99, day: 500}
    assert forecasting.moving_average(history, day, window=2) == 15.0
    assert forecasting.moving_average({day - timedelta(days=1): 6}, day, window=3) == 2.0


def test_backtest_is_exact_for_constant_sales(db, sku):
    milk = sku("Toned milk")
    plant(db, milk, {n: 10 for n in range(1, 22)})
    result = forecasting.backtest(db, 1, test_days=14, window=7)
    by_sku = {row["sku_id"]: row for row in result["per_sku"]}
    assert result["wape"] == 0.0 and by_sku[milk]["wape"] == 0.0
    assert by_sku[sku("Basmati rice")]["wape"] is None           # nothing sold: no ratio, no crash


def test_backtest_matches_hand_arithmetic(db, sku):
    milk = sku("Toned milk")
    plant(db, milk, {4: 10, 3: 20, 2: 30, 1: 40})
    # day -2: forecast (10+20)/2 = 15, sold 30 -> 15 off; day -1: forecast 25, sold 40 -> 15 off
    result = forecasting.backtest(db, 1, test_days=2, window=2)
    row = next(r for r in result["per_sku"] if r["sku_id"] == milk)
    assert (row["actual_units"], row["abs_error"]) == (70, 30.0)
    assert result["wape"] == row["wape"] == 0.4286                # 30 / 70


def test_backtest_with_no_sales_has_no_wape(db):
    clear_history(db, 1)
    db.commit()
    assert forecasting.backtest(db, 1)["wape"] is None
