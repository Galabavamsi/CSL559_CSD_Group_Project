"""Assortment recommendations (guide task 3.7): what to add, what to drop, and how much shelf room is left."""
from datetime import timedelta

from sqlalchemy import select

from app.db import SessionLocal
from app.models import StockLedger, StockLevel, TransferOrder, TransferOrderLine
from app.modules.replenishment import service as replenishment

from .conftest import assert_stock_is_consistent, place_paid_order, plant_sales

URL = "/v1/stores/{}/assortment/recommendations"


def test_a_sku_selling_elsewhere_is_recommended_where_it_is_missing(client, db, sku):
    bananas = sku("Bananas")
    plant_sales(db, {bananas: dict.fromkeys(range(1, 31), 3)})                  # store 1 sells 3 a day
    assert client.delete(f"/v1/stores/2/assortment/{bananas}").status_code == 200   # store 2: none on hand, held or coming
    assert client.delete(f"/v1/stores/2/assortment/{bananas}").status_code == 404   # no longer carried
    add = client.get(URL.format(2)).json()["add"]
    assert add == [{"sku_id": bananas, "sku": "Bananas (6 pcs)", "zone": "ambient", "daily_demand": 3.0,
                    "stores_selling": 1, "fits": True}]
    assert_stock_is_consistent()


def test_a_sku_with_stock_cannot_be_dropped(client, sku):
    refused = client.delete(f"/v1/stores/1/assortment/{sku('Toned milk')}")
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "still_stocked"
    assert "30 on hand" in refused.json()["error"]["message"]
    client.post("/v1/replenishment/run", params={"store_id": 2})                 # bananas are now on their way
    coming = client.delete(f"/v1/stores/2/assortment/{sku('Bananas')}")
    assert coming.status_code == 409 and "on their way" in coming.json()["error"]["message"]
    assert len(client.get("/v1/stores/2/assortment").json()) == 16


def drop_list(client, store_id: int = 1) -> set[str]:
    return {row["sku"] for row in client.get(URL.format(store_id)).json()["drop"]}


def age_stock(db, sku_id: int, days: int) -> None:
    """Move every ledger row of one SKU in store 1 `days` days back in time."""
    for row in db.scalars(select(StockLedger).where(StockLedger.store_id == 1, StockLedger.sku_id == sku_id)):
        row.ts -= timedelta(days=days)
    db.commit()


def test_shelf_room_per_zone_and_nothing_judged_too_soon(client):
    body = client.get(URL.format(1)).json()
    assert body["drop"] == []                        # every item arrived 8 days ago: too soon to call it dead stock
    assert body["space"] == [{"zone": "ambient", "bins": 12, "skus": 11, "room_for": 1},
                             {"zone": "chilled", "bins": 4, "skus": 3, "room_for": 1},
                             {"zone": "frozen", "bins": 2, "skus": 2, "room_for": 0}]


def test_recommendations_are_for_staff_and_dropping_is_for_managers(client_as, sku):
    tea = sku("Tea")
    assert client_as("picker", 1).get(URL.format(1)).status_code == 200
    assert client_as("picker", 1).get(URL.format(2)).status_code == 403
    assert client_as("picker", 1).delete(f"/v1/stores/1/assortment/{tea}").status_code == 403
    assert client_as("manager", 2).delete(f"/v1/stores/1/assortment/{tea}").status_code == 403
    assert client_as("manager", 1).delete(f"/v1/stores/1/assortment/{tea}").status_code == 409   # 30 on hand


def test_dead_stock_sat_on_the_shelf_all_month_without_a_sale(client, db, sku):
    age_stock(db, sku("Basmati rice"), 30)                     # as if the rice had arrived 38 days ago
    assert drop_list(client) == {"Basmati rice 1 kg"}         # on the shelf all month and not one sold


def test_an_item_back_in_stock_after_running_out_is_not_judged_yet(client, db, sku):
    rice = sku("Basmati rice")
    on_hand = db.get(StockLevel, (1, rice)).qty_on_hand
    client.post("/v1/stock-adjustments", json={"store_id": 1, "sku_id": rice, "delta": -on_hand, "reason": "expiry"})
    age_stock(db, rice, 35)                                    # arrived 43 days ago, all written off 35 days ago
    client.post("/v1/goods-receipts", json={"store_id": 1, "lines": [{"sku_id": rice, "qty": 10}]})   # back today
    assert drop_list(client) == set()                          # it had nothing to sell for most of the month
    assert_stock_is_consistent()


def test_units_held_for_customers_are_named_when_a_drop_is_refused(client, sku):
    milk = sku("Toned milk")
    place_paid_order(client, "ORD-HELD", 1, [(milk, 2)])
    refused = client.delete(f"/v1/stores/1/assortment/{milk}")
    assert refused.status_code == 409 and "2 held for customers" in refused.json()["error"]["message"]


def test_a_truck_ordered_while_dropping_stops_the_drop(client, sku, monkeypatch):
    bananas = sku("Bananas")                                   # store 2: none on hand, held or coming
    read_transit, calls = replenishment.in_transit, []

    def order_right_after_the_check(db, store_id):
        seen = read_transit(db, store_id)
        calls.append(store_id)
        if len(calls) == 1:                                    # the timer orders bananas in that split second
            with SessionLocal() as other:
                other.add(TransferOrder(store_id=2, status="created",
                                        lines=[TransferOrderLine(sku_id=bananas, qty_ordered=6)]))
                other.commit()
        return seen

    monkeypatch.setattr(replenishment, "in_transit", order_right_after_the_check)
    refused = client.delete(f"/v1/stores/2/assortment/{bananas}")
    assert refused.status_code == 409 and "6 on their way" in refused.json()["error"]["message"]
    assert len(client.get("/v1/stores/2/assortment").json()) == 16             # bananas are still carried
