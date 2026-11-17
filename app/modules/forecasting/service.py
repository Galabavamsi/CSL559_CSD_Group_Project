"""Forecasting Service (HLD service 7): predict demand and set reorder points from it.

Daily sales come from the stock ledger. Three models share one shape, model(history, target_day) -> units, so
they can be swapped and compared by backtest (WAPE); config.FORECAST_MODEL picks the one `run` uses. The reorder
point then follows HLD 6.2 (in days instead of hours):

    reorder point = daily_demand * lead_time + z * daily_std * sqrt(lead_time)
    target stock  = reorder point + daily_demand * cover_days
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


# Every model reads `history`, {date: units sold} for one SKU, and returns the forecast for `target_day` from the
# days before it. A day after the SKU's first recorded sale with no sales counts as 0; days before that first sale
# are unknown, not zero, and are left out, so a SKU with a short history still gets a fair forecast. With no day
# left to look at, the forecast is 0.0.

SMOOTHING_DAYS = 28        # exp_smoothing looks back four weeks; an older day would weigh under 0.01%


def _known_days(history: dict[date, int], days: list[date]) -> list[date]:
    """`days` without the ones before the SKU's first recorded sale (all of them when there is no sale at all)."""
    if not history:
        return []
    first_sale = min(history)
    return [day for day in days if day >= first_sale]


def _mean(history: dict[date, int], days: list[date]) -> float:
    return sum(history.get(day, 0) for day in days) / len(days) if days else 0.0


def moving_average(history: dict[date, int], target_day: date, window: int = config.FORECAST_WINDOW_DAYS) -> float:
    """The mean of the `window` days before `target_day`."""
    return _mean(history, _known_days(history, [target_day - timedelta(days=n) for n in range(1, window + 1)]))


def weekday_average(history: dict[date, int], target_day: date, weeks: int = 4) -> float:
    """The mean of the same weekday in the last `weeks` weeks: a Saturday is forecast from Saturdays."""
    return _mean(history, _known_days(history, [target_day - timedelta(weeks=n) for n in range(1, weeks + 1)]))


def exp_smoothing(history: dict[date, int], target_day: date, alpha: float = 0.3) -> float:
    """A weighted mean of the last SMOOTHING_DAYS days in which recent days count more: yesterday weighs 1 and each
    earlier day (1 - alpha) times as much as the day after it."""
    days = _known_days(history, [target_day - timedelta(days=n) for n in range(1, SMOOTHING_DAYS + 1)])
    weights = [(1 - alpha) ** n for n in range(len(days))]          # days run newest first
    return sum(w * history.get(day, 0) for w, day in zip(weights, days)) / sum(weights) if days else 0.0


MODELS = {"moving_average": moving_average, "weekday_average": weekday_average, "exp_smoothing": exp_smoothing}
HISTORY_DAYS = max(4 * 7, SMOOTHING_DAYS, config.FORECAST_WINDOW_DAYS)   # the most days any model looks back

if config.FORECAST_MODEL not in MODELS:        # fail at start-up, not on the first forecast or KPI request
    raise RuntimeError(f"FORECAST_MODEL is {config.FORECAST_MODEL!r}; use one of: {', '.join(MODELS)}")


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
