"""Stock-in side: replenishment, inbound receiving, slotting, forecasting (HLD 6.2 and 6.3)."""
from datetime import date, timedelta

from .conftest import assert_stock_is_consistent, atp


def test_low_stock_is_reordered_once(client, sku):
    bread = sku("White bread")                                       # 4 left, reorder point 10, target 40
    order = client.post("/v1/replenishment/run", params={"store_id": 1}).json()["transfer_order"]
    by_sku = {line["sku_id"]: line["qty_ordered"] for line in order["lines"]}
    assert by_sku[bread] == 40                                       # 36 needed, ordered in whole cases of 10
    # Stock already on its way counts, so running again orders nothing.
    assert client.post("/v1/replenishment/run", params={"store_id": 1}).json()["transfer_order"] is None


def test_receiving_a_truck_puts_stock_on_sale_and_flags_shortfalls(client, sku):
    bread = sku("White bread")
    order = client.post("/v1/replenishment/run", params={"store_id": 1}).json()["transfer_order"]
    client.post(f"/v1/transfer-orders/{order['transfer_order_id']}/dispatch")

    lines = [{"sku_id": line["sku_id"], "qty": line["qty_ordered"]} for line in order["lines"]]
    next(line for line in lines if line["sku_id"] == bread)["qty"] = 34      # hub sent 6 fewer than ordered
    receipt = client.post("/v1/goods-receipts", json={
        "store_id": 1, "transfer_order_id": order["transfer_order_id"], "lines": lines})
    assert receipt.status_code == 201
    body = receipt.json()
    assert {"sku_id": bread, "sku": "White bread 400 g", "ordered": 40, "received": 34} in body["discrepancies"]
    assert atp(client, 1, bread) == 38                               # sellable immediately
    orders = client.get("/v1/transfer-orders", params={"store_id": 1}).json()
    assert orders[0]["status"] == "received"
    again = client.post("/v1/goods-receipts", json={
        "store_id": 1, "transfer_order_id": order["transfer_order_id"], "lines": lines})
    assert again.status_code == 409
    assert_stock_is_consistent()


def test_chilled_goods_cannot_go_in_an_ambient_bin(client, sku):
    milk = sku("Toned milk")
    ambient_bin = next(b for b in client.get("/v1/stores/1/bins").json() if b["zone"] == "ambient")
    res = client.post("/v1/goods-receipts", json={
        "store_id": 1, "lines": [{"sku_id": milk, "qty": 5, "bin_id": ambient_bin["bin_id"]}]})
    assert res.status_code == 422 and res.json()["error"]["code"] == "wrong_zone"
    assert atp(client, 1, milk) == 28                                  # unchanged: 30 on hand less the seeded buffer of 2


def test_slotting_keeps_a_sku_together_and_respects_zones(client, sku):
    milk = sku("Toned milk")
    suggestion = client.get("/v1/slotting/suggest", params={"store_id": 1, "sku_id": milk}).json()
    assert suggestion["zone"] == "chilled" and suggestion["code"] == "C-01-01"


def test_new_batch_gets_its_own_expiry(client, sku):
    milk = sku("Toned milk")
    expiry = (date.today() + timedelta(days=5)).isoformat()
    client.post("/v1/goods-receipts", json={
        "store_id": 1, "lines": [{"sku_id": milk, "qty": 10, "batch_no": "M-FRESH", "expiry_date": expiry}]})
    batches = {row["batch_no"]: row for row in client.get("/v1/stores/1/stock").json() if row["sku_id"] == milk}
    assert batches["M-FRESH"]["qty"] == 10 and batches["M-FRESH"]["expiry_date"] == expiry


def test_forecast_sets_reorder_point_from_sales_history(client, sku):
    milk, rice = sku("Toned milk"), sku("Basmati rice")
    results = {row["sku_id"]: row for row in client.post("/v1/forecasting/run", params={"store_id": 1}).json()}
    assert results[milk]["daily_demand"] > 15                        # the seed data sells ~20 milk a day
    assert results[milk]["reorder_point"] > 10
    assert results[milk]["target_stock"] > results[milk]["reorder_point"]
    assert results[rice]["reorder_point"] == 10                      # no sales history -> left alone
