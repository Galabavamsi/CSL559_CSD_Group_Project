"""Forecasting Service (HLD service 7): predict demand and set reorder points from it.

The prototype model is a moving average of the last N days of sales taken from the stock ledger.
It then applies the reorder-point formula from HLD 6.2 (in days instead of hours):

    reorder point = mean_daily_demand * lead_time + z * std_daily_demand * sqrt(lead_time)
    target stock  = reorder point + mean_daily_demand * cover_days

Member 3's guide covers replacing the moving average with a better model.
"""
import math
from datetime import timedelta
from statistics import pstdev

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ... import config, events
from ...models import Forecast, StockLedger, StockLevel, utcnow
from ..inventory import service as inventory


def daily_sales(db: Session, store_id: int, window_days: int) -> dict[int, list[int]]:
    """Units sold per day for each SKU over the window, with zero-sale days included."""
    today = utcnow().date()
    days = [(today - timedelta(days=n)).isoformat() for n in range(window_days)]
    since = utcnow() - timedelta(days=window_days)
    rows = db.execute(
        select(StockLedger.sku_id, func.date(StockLedger.ts), func.sum(-StockLedger.delta))
        .where(StockLedger.store_id == store_id, StockLedger.reason == "sale", StockLedger.ts >= since)
        .group_by(StockLedger.sku_id, func.date(StockLedger.ts))
    ).all()
    by_sku: dict[int, dict[str, int]] = {}
    for sku_id, day, units in rows:
        by_sku.setdefault(sku_id, {})[str(day)] = int(units)
    return {sku_id: [per_day.get(d, 0) for d in days] for sku_id, per_day in by_sku.items()}


def run(db: Session, store_id: int, window_days: int | None = None) -> list[dict]:
    """Recalculate forecasts for one store and update reorder points for SKUs that have sales (FR-7)."""
    inventory.get_store(db, store_id)
    window = window_days or config.FORECAST_WINDOW_DAYS
    sales = daily_sales(db, store_id, window)
    lead = config.LEAD_TIME_DAYS
    results = []
    levels = db.scalars(
        select(StockLevel).where(StockLevel.store_id == store_id).execution_options(populate_existing=True)
    ).all()
    for level in levels:
        series = sales.get(level.sku_id, [0] * window)
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


def list_forecasts(db: Session, store_id: int) -> list[dict]:
    rows = db.scalars(select(Forecast).where(Forecast.store_id == store_id)).all()
    return [{"sku_id": f.sku_id, "daily_demand": round(f.daily_demand, 2), "daily_std": round(f.daily_std, 2),
             "model": f.model, "updated_at": f.updated_at.isoformat() + "Z"} for f in rows]
