"""Supply KPIs (guide task 3.8, HLD 12): stock-outs, days of cover, wastage, on-time trucks, forecast error."""
from datetime import timedelta

from fastapi.testclient import TestClient

from app import config
from app.main import app
from app.models import TransferOrder

from .conftest import assert_stock_is_consistent, plant_sales

URL = "/v1/stores/{}/supply-kpis"
EVERY_DAY = range(1, 43)


def kpis(client, store_id=1):
    return client.get(URL.format(store_id)).json()


def test_stock_out_rate_counts_skus_with_nothing_to_sell(client, sku):
    out = kpis(client, 2)["stock_out_rate"]                    # the seed leaves store 2 without bananas
    assert (out["value"], out["met"], out["carried"]) == (0.0625, False, 16)
    assert out["out_of_stock"] == [{"sku_id": sku("Bananas"), "sku": "Bananas (6 pcs)"}]
    store_1 = kpis(client, 1)["stock_out_rate"]
    assert (store_1["value"], store_1["met"]) == (0.0, True)


def test_writing_off_stock_raises_the_wastage_rate(client, sku):
    before = kpis(client)["wastage_rate"]
    # The seed week sold 148 milk x Rs 28, 87 bread x 45, 51 eggs x 60 and 36 chips x 30 = Rs 12,199.
    assert (before["value"], before["sold_value"], before["days"]) == (0.0, 12199.0, 30)
    expired = client.post("/v1/stock-adjustments", json={
        "store_id": 1, "sku_id": sku("Toned milk"), "delta": -5, "reason": "expiry"})
    stolen = client.post("/v1/stock-adjustments", json={
        "store_id": 1, "sku_id": sku("Tea"), "delta": -2, "reason": "theft"})
    assert expired.status_code == stolen.status_code == 200
    after = kpis(client)["wastage_rate"]
    assert after["written_off_value"] == 140.0                 # 5 x Rs 28; theft is not wastage
    assert (after["value"], after["met"]) == (round(140 / 12199, 4), False)
    assert_stock_is_consistent()


def test_on_time_compares_each_receipt_with_the_lead_time(client, db):
    assert kpis(client)["replenishment_on_time"]["value"] is None          # no truck received yet
    order = client.post("/v1/replenishment/run", params={"store_id": 1}).json()["transfer_order"]
    client.post(f"/v1/transfer-orders/{order['transfer_order_id']}/dispatch")
    received = client.post("/v1/goods-receipts", json={
        "store_id": 1, "transfer_order_id": order["transfer_order_id"],
        "lines": [{"sku_id": line["sku_id"], "qty": line["qty_ordered"]} for line in order["lines"]]})
    assert received.status_code == 201
    on_time = kpis(client)["replenishment_on_time"]
    assert (on_time["value"], on_time["on_time"], on_time["received"], on_time["met"]) == (1.0, 1, 1, True)
    row = db.get(TransferOrder, order["transfer_order_id"])
    row.created_at = row.received_at - timedelta(days=2)       # ordered two days before it arrived; lead time is 1 day
    db.commit()
    late = kpis(client)["replenishment_on_time"]
    assert (late["value"], late["on_time"], late["met"]) == (0.0, 0, False)
    assert_stock_is_consistent()


def test_days_of_cover_compares_stock_with_the_forecast(client, db, sku):
    plant_sales(db, {sku("Toned milk"): dict.fromkeys(EVERY_DAY, 10), sku("White bread"): dict.fromkeys(EVERY_DAY, 4),
                     sku("Potato chips"): dict.fromkeys(EVERY_DAY, 10), sku("Eggs"): dict.fromkeys(EVERY_DAY, 1),
                     sku("Vanilla ice cream"): dict.fromkeys(EVERY_DAY, 2)})
    client.post("/v1/forecasting/run", params={"store_id": 1})
    cover = kpis(client)["days_of_cover"]
    by_sku = {row["sku_id"]: row for row in cover["per_sku"]}
    milk = by_sku[sku("Toned milk")]
    assert (milk["days"], milk["fresh"], milk["met"]) == (3.0, True, False)   # 30 / 10; fresh target is 1-2 days
    assert by_sku[sku("White bread")]["met"] is True           # 4 / 4 = 1 day, fresh
    assert by_sku[sku("Potato chips")]["met"] is True          # 30 / 10 = 3 days: target 3-5 days
    assert by_sku[sku("Basmati rice")]["days"] is None         # no forecast demand: not measured
    assert (cover["measured"], cover["within_target"], cover["under_1_day"], cover["over_14_days"]) == (5, 2, 1, 1)
    assert (cover["value"], cover["met"]) == (0.4, False)
    assert cover["per_sku"][0]["sku_id"] == sku("Vanilla ice cream")       # 1 / 2 = 0.5 days: most urgent first


def test_forecast_wape_kpi_is_the_backtest_of_the_model_in_use(client, db, sku):
    plant_sales(db, {sku("Toned milk"): dict.fromkeys(EVERY_DAY, 10)})
    wape = kpis(client)["forecast_wape"]
    assert (wape["value"], wape["met"], wape["model"], wape["test_days"]) == (0.0, True, config.FORECAST_MODEL, 14)


def test_a_store_with_nothing_to_measure_reports_not_available(client):
    body = kpis(client, 2)                                     # store 2: no sales, no forecasts, no trucks
    for name in ("days_of_cover", "wastage_rate", "replenishment_on_time", "forecast_wape"):
        assert (body[name]["value"], body[name]["met"]) == (None, None), name


def test_supply_kpis_are_for_staff_of_that_store(client_as):
    with TestClient(app) as anonymous:
        assert anonymous.get(URL.format(1)).status_code == 401
    picker = client_as("picker", 1)
    body = picker.get(URL.format(1)).json()
    assert set(body) == {"store_id", "stock_out_rate", "days_of_cover", "wastage_rate", "replenishment_on_time",
                         "forecast_wape"}
    assert all({"value", "target", "met"} <= set(body[name]) for name in body if name != "store_id")
    assert picker.get(URL.format(2)).status_code == 403
    assert client_as("ops").get(URL.format(2)).status_code == 200
    assert client_as("admin").get(URL.format(99)).status_code == 404
