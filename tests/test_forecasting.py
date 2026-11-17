"""Forecasting (guide tasks 3.2 and 3.3): daily sales, the three models, backtest, WAPE."""
import importlib
from datetime import date, datetime, time, timedelta

import pytest
from fastapi.testclient import TestClient

from app import config
from app.errors import DomainError
from app.main import app
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


def test_forecast_uses_the_seven_days_ending_yesterday(client, sku, monkeypatch):
    monkeypatch.setattr(config, "FORECAST_MODEL", "moving_average")
    rows = {r["sku_id"]: r for r in client.post("/v1/forecasting/run", params={"store_id": 1}).json()}
    assert rows[sku("Toned milk")]["daily_demand"] == 21.14     # seed week sums to 148; 148 / 7


def test_forecast_sizes_safety_stock_from_forecast_errors(client, db, sku, monkeypatch):
    monkeypatch.setattr(config, "FORECAST_MODEL", "weekday_average")
    milk = sku("Toned milk")
    plant(db, milk, {n: 20 if n == 1 else 10 for n in range(1, 43)})
    row = next(r for r in client.post("/v1/forecasting/run", params={"store_id": 1}).json() if r["sku_id"] == milk)
    # Every replayed day was forecast at 10, so the only error is yesterday's +10: pstdev([0] * 13 + [10]) = 2.5754.
    # Reorder point = ceil(10 x 1 + 1.65 x 2.5754) = 15; target = 15 + 10 x 3 = 45.
    assert (row["model"], row["daily_demand"], row["daily_std"]) == ("weekday_average", 10.0, 2.58)
    assert (row["reorder_point"], row["target_stock"]) == (15, 45)


def test_forecasts_show_the_model_that_made_them(client):
    client.post("/v1/forecasting/run", params={"store_id": 1})
    rows = client.get("/v1/forecasts", params={"store_id": 1}).json()
    assert len(rows) == 16 and {row["model"] for row in rows} == {config.FORECAST_MODEL}


TUESDAY = date(2026, 11, 10)


def sold(day, units_by_days_ago):
    return {day - timedelta(days=n): units for n, units in units_by_days_ago.items()}


def test_moving_average_is_the_mean_of_the_days_before():
    history = sold(TUESDAY, {1: 20, 2: 10, 3: 99}) | {TUESDAY: 500}
    assert forecasting.moving_average(history, TUESDAY, window=2) == 15.0
    # After the first sale a day without sales counts as 0; days before it are unknown and left out.
    assert forecasting.moving_average(sold(TUESDAY, {3: 6, 1: 3}), TUESDAY, window=5) == 3.0
    assert forecasting.moving_average({}, TUESDAY) == 0.0


def test_weekday_average_is_the_mean_of_the_same_weekdays():
    history = sold(TUESDAY, {7: 10, 14: 20, 21: 30, 28: 40, 35: 999, 1: 500, 2: 500})
    assert forecasting.weekday_average(history, TUESDAY) == 25.0              # (10 + 20 + 30 + 40) / 4
    assert forecasting.weekday_average(history, TUESDAY, weeks=2) == 15.0
    assert forecasting.weekday_average(sold(TUESDAY, {7: 12, 3: 5}), TUESDAY) == 12.0   # one Tuesday known
    assert forecasting.weekday_average(sold(TUESDAY, {3: 5}), TUESDAY) == 0.0           # no Tuesday known yet


def test_exp_smoothing_weighs_recent_days_more():
    assert forecasting.exp_smoothing(sold(TUESDAY, {1: 10, 2: 20}), TUESDAY, alpha=0.5) == pytest.approx(20 / 1.5)
    assert forecasting.exp_smoothing(sold(TUESDAY, {n: 8 for n in range(1, 60)}), TUESDAY) == pytest.approx(8.0)
    assert forecasting.exp_smoothing({}, TUESDAY) == 0.0


def test_every_model_has_the_same_shape():
    assert set(forecasting.MODELS) == {"moving_average", "weekday_average", "exp_smoothing"}
    assert config.FORECAST_MODEL in forecasting.MODELS
    steady = sold(TUESDAY, {n: 5 for n in range(1, 43)})
    assert {name: model(steady, TUESDAY) for name, model in forecasting.MODELS.items()} == pytest.approx(
        {name: 5.0 for name in forecasting.MODELS})


def test_the_app_refuses_to_start_with_an_unknown_model(monkeypatch):
    monkeypatch.setattr(config, "FORECAST_MODEL", "crystal_ball")
    with pytest.raises(RuntimeError, match="crystal_ball"):
        importlib.reload(forecasting)


def test_backtest_is_exact_for_constant_sales(db, sku):
    milk = sku("Toned milk")
    plant(db, milk, {n: 10 for n in range(1, 43)})
    for model in forecasting.MODELS:
        result = forecasting.backtest(db, 1, test_days=14, model=model)
        by_sku = {row["sku_id"]: row for row in result["per_sku"]}
        assert (result["model"], result["wape"], by_sku[milk]["wape"]) == (model, 0.0, 0.0)
        assert by_sku[sku("Basmati rice")]["wape"] is None           # nothing sold: no ratio, no crash


def test_backtest_matches_hand_arithmetic(db, sku):
    milk = sku("Toned milk")
    plant(db, milk, {4: 10, 3: 20, 2: 30, 1: 40})
    # Moving average of the known days before each day (the first sale was 4 days ago):
    # day -2: (10 + 20) / 2 = 15, sold 30 -> 15 off; day -1: (10 + 20 + 30) / 3 = 20, sold 40 -> 20 off
    result = forecasting.backtest(db, 1, test_days=2, model="moving_average")
    row = next(r for r in result["per_sku"] if r["sku_id"] == milk)
    assert (row["actual_units"], row["abs_error"]) == (70, 35.0)
    assert result["wape"] == row["wape"] == 0.5                   # 35 / 70


def test_weekday_average_beats_moving_average_on_a_weekend_pattern(db, sku):
    today = utcnow().date()
    plant(db, sku("Toned milk"), {n: 30 if (today - timedelta(days=n)).weekday() >= 5 else 10 for n in range(1, 43)})
    result = forecasting.compare_models(db, 1)
    assert result["wape"]["weekday_average"] == 0.0
    assert result["wape"]["moving_average"] > 0.3                # forecasts ~15.7 every day
    assert (result["best"], result["in_use"], result["test_days"]) == ("weekday_average", config.FORECAST_MODEL, 14)


def test_backtest_rejects_an_unknown_model_or_no_days(db):
    with pytest.raises(DomainError) as unknown:
        forecasting.backtest(db, 1, model="crystal_ball")
    with pytest.raises(DomainError) as no_days:
        forecasting.backtest(db, 1, test_days=0)
    assert (unknown.value.status, unknown.value.code) == (422, "unknown_model")
    assert (no_days.value.status, no_days.value.code) == (422, "bad_test_days")


def test_backtest_with_no_sales_has_no_wape(db):
    clear_history(db, 1)
    db.commit()
    assert forecasting.backtest(db, 1)["wape"] is None


URL = "/v1/forecasting/backtest"


def test_backtest_endpoint_is_for_staff_of_that_store(client_as):
    with TestClient(app) as anonymous:
        assert anonymous.get(URL, params={"store_id": 1}).status_code == 401
    picker = client_as("picker", 1)
    assert picker.get(URL, params={"store_id": 1}).status_code == 200
    assert picker.get(URL, params={"store_id": 2}).status_code == 403
    assert client_as("ops").get(URL, params={"store_id": 2}).status_code == 200


def test_backtest_endpoint_checks_its_parameters(client):
    assert client.get(URL, params={"store_id": 1, "test_days": 0}).status_code == 422
    assert client.get(URL, params={"store_id": 1, "model": "crystal_ball"}).status_code == 422
    assert client.get(URL, params={"store_id": 99}).status_code == 404
    body = client.get(URL, params={"store_id": 1}).json()
    assert (body["model"], body["test_days"]) == (config.FORECAST_MODEL, 14)
    assert client.get(URL, params={"store_id": 1, "model": "exp_smoothing"}).json()["model"] == "exp_smoothing"


def test_compare_endpoint_is_for_staff_of_that_store(client_as):
    compare = "/v1/forecasting/compare"
    with TestClient(app) as anonymous:
        assert anonymous.get(compare, params={"store_id": 1}).status_code == 401
    picker = client_as("picker", 1)
    body = picker.get(compare, params={"store_id": 1}).json()
    assert set(body["wape"]) == set(forecasting.MODELS) and body["test_days"] == 14
    assert picker.get(compare, params={"store_id": 2}).status_code == 403
