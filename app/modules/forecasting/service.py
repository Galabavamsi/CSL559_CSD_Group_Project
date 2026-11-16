"""Forecasting Service (HLD service 7): predict demand and set reorder points from it.

The prototype model is a moving average of the last N days of sales taken from the stock ledger.
It then applies the reorder-point formula from HLD 6.2 (in days instead of hours):

    reorder point = mean_daily_demand * lead_time + z * std_daily_demand * sqrt(lead_time)
    target stock  = reorder point + mean_daily_demand * cover_days

Member 3's guide covers replacing the moving average with a better model.
"""
import math
from datetime import date, datetime, time, timedelta
from statistics import pstdev

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ... import config, events
from ...models import Forecast, StockLedger, StockLevel, utcnow
from ..inventory import service as inventory


def daily_sales(db: Session, store_id: int, days_back: int) -> dict[int, dict[date, int]]:
    """Units sold per SKU per day over the `days_back` whole days ending yesterday. Read-only.

    Today is left out because it is only partly over. Days without sales are absent from the result.
    """
    today = utcnow().date()
    rows = db.execute(
        select(StockLedger.sku_id, func.date(StockLedger.ts), func.sum(-StockLedger.delta))
        .where(StockLedger.store_id == store_id, StockLedger.reason == "sale",
               StockLedger.ts >= datetime.combine(today - timedelta(days=days_back), time.min),
               StockLedger.ts < datetime.combine(today, time.min))
        .group_by(StockLedger.sku_id, func.date(StockLedger.ts))
    ).all()
    sales: dict[int, dict[date, int]] = {}
    for sku_id, day, units in rows:
        # SQLite returns the day as text and PostgreSQL as a date; going through str() handles both.
        sales.setdefault(sku_id, {})[date.fromisoformat(str(day))] = int(units)
    return sales


def run(db: Session, store_id: int, window_days: int | None = None) -> list[dict]:
    """Recalculate forecasts for one store from the `window_days` days ending yesterday, and update reorder
    points for SKUs that have sales (FR-7)."""
    inventory.get_store(db, store_id)
    window = window_days or config.FORECAST_WINDOW_DAYS
    sales = daily_sales(db, store_id, window)
    today = utcnow().date()
    window_dates = [today - timedelta(days=n) for n in range(window, 0, -1)]
    lead = config.LEAD_TIME_DAYS
    results = []
    levels = db.scalars(
        select(StockLevel).where(StockLevel.store_id == store_id).execution_options(populate_existing=True)
    ).all()
    for level in levels:
        history = sales.get(level.sku_id, {})
        series = [history.get(d, 0) for d in window_dates]
        mean = sum(series) / window
        std = pstdev(series)
        forecast = db.get(Forecast, (store_id, level.sku_id))
        if forecast is None:
            forecast = Forecast(store_id=store_id, sku_id=level.sku_id)
            db.add(forecast)
        forecast.daily_demand, forecast.daily_std, forecast.updated_at = mean, std, utcnow()
        if mean > 0:        # no sales history -> keep the manually set reorder point
            level.reorder_point = math.ceil(mean * lead + config.SERVICE_LEVEL_Z * std * math.sqrt(lead))
            level.target_stock = level.reorder_point + max(1, math.ceil(mean * config.COVER_DAYS))
        results.append({"sku_id": level.sku_id, "sku": level.sku.name, "daily_demand": round(mean, 2),
                        "daily_std": round(std, 2), "reorder_point": level.reorder_point,
                        "target_stock": level.target_stock})
    events.publish(db, "forecast.updated", store_id, {"skus": len(results), "window_days": window})
    db.commit()
    return sorted(results, key=lambda r: r["sku"])


def moving_average(history: dict[date, int], target_day: date, window: int = 7) -> float:
    """Forecast for `target_day`: the mean of the `window` days before it. Days missing from `history` sold 0."""
    return sum(history.get(target_day - timedelta(days=n), 0) for n in range(1, window + 1)) / window


def _wape(abs_error: float, actual: int) -> float | None:
    return round(abs_error / actual, 4) if actual else None


def backtest(db: Session, store_id: int, test_days: int = 14, window: int = 7) -> dict:
    """How wrong would the moving average have been over the `test_days` days ending yesterday? Read-only.

    For each of those days and each SKU the store carries, the forecast is the moving average of the `window`
    days before it, and the actual is what sold. WAPE = sum of |actual - forecast| / sum of actual (HLD 12
    target: 30% or lower); weighting by volume stops slow sellers swamping the score. WAPE is None when
    nothing sold.
    """
    inventory.get_store(db, store_id)
    sales = daily_sales(db, store_id, test_days + window)
    today = utcnow().date()
    test_dates = [today - timedelta(days=n) for n in range(test_days, 0, -1)]
    per_sku, total_error, total_actual = [], 0.0, 0
    for level in db.scalars(select(StockLevel).where(StockLevel.store_id == store_id)).all():
        history = sales.get(level.sku_id, {})
        actual = sum(history.get(d, 0) for d in test_dates)
        error = sum(abs(history.get(d, 0) - moving_average(history, d, window)) for d in test_dates)
        total_error += error
        total_actual += actual
        per_sku.append({"sku_id": level.sku_id, "sku": level.sku.name, "actual_units": actual,
                        "abs_error": round(error, 2), "wape": _wape(error, actual)})
    return {"store_id": store_id, "model": "moving_average", "window": window, "test_days": test_days,
            "wape": _wape(total_error, total_actual), "per_sku": sorted(per_sku, key=lambda row: row["sku"])}


def list_forecasts(db: Session, store_id: int) -> list[dict]:
    rows = db.scalars(select(Forecast).where(Forecast.store_id == store_id)).all()
    return [{"sku_id": f.sku_id, "daily_demand": round(f.daily_demand, 2), "daily_std": round(f.daily_std, 2),
             "model": f.model, "updated_at": f.updated_at.isoformat() + "Z"} for f in rows]
