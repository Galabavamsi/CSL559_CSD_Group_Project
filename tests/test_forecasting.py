"""Forecasting (guide task 3.2): daily sales, backtest, WAPE."""
from datetime import datetime, time, timedelta

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
