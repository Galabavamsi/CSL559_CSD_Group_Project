"""Smarter replenishment (guide task 3.4): whole cases, free bin space, runs by itself."""
from sqlalchemy import update

from app.models import Bin, Forecast

from .conftest import assert_stock_is_consistent


def test_orders_are_rounded_up_to_full_cases(client, sku):
    milk = sku("Toned milk")                                   # case of 12; reorder point 10, target 40
    client.post("/v1/stock-adjustments", json={"store_id": 1, "sku_id": milk, "delta": -27, "reason": "damage"})
    order = client.post("/v1/replenishment/run", params={"store_id": 1}).json()["transfer_order"]
    lines = {line["sku_id"]: line["qty_ordered"] for line in order["lines"]}
    assert lines[milk] == 48                                   # 40 - 3 = 37 needed -> 4 cases of 12
    assert lines[sku("White bread")] == 40                     # 36 needed -> 4 cases of 10
    assert_stock_is_consistent()


def test_a_full_zone_orders_the_most_urgent_items_first(client, db, sku):
    milk, curd = sku("Toned milk"), sku("Curd")
    for sku_id, delta in ((milk, -26), (curd, -28)):            # milk 4 left (2 sellable after its buffer), curd 2
        client.post("/v1/stock-adjustments", json={"store_id": 1, "sku_id": sku_id, "delta": delta, "reason": "damage"})
    db.add_all([Forecast(store_id=1, sku_id=milk, daily_demand=20.0), Forecast(store_id=1, sku_id=curd, daily_demand=5.0)])
    db.execute(update(Bin).where(Bin.store_id == 1, Bin.zone == "chilled").values(capacity=24))
    db.commit()
    # The chilled zone holds 4 x 24 = 96 units; 36 are stored (milk 4, curd 2, paneer 30), so 60 are free.
    # Milk covers 2 / 20 = 0.1 days, curd 2 / 5 = 0.4: milk goes first and gets its 3 cases (36);
    # curd wants 4 cases (48) but only 2 fit (24).
    body = client.post("/v1/replenishment/run", params={"store_id": 1}).json()
    lines = {line["sku_id"]: line["qty_ordered"] for line in body["transfer_order"]["lines"]}
    assert (lines[milk], lines[curd]) == (36, 24)
    assert body["capped"] == [{"sku_id": curd, "sku": "Curd 400 g", "zone": "chilled", "wanted": 48, "ordered": 24}]
    assert_stock_is_consistent()


def test_a_zone_with_no_room_orders_nothing_for_it(client, db, sku):
    ice_cream = sku("Vanilla ice cream")                        # 1 left: below its reorder point
    db.execute(update(Bin).where(Bin.store_id == 1, Bin.zone == "frozen").values(capacity=0))
    db.commit()
    body = client.post("/v1/replenishment/run", params={"store_id": 1}).json()
    assert ice_cream not in {line["sku_id"] for line in body["transfer_order"]["lines"]}
    # 40 - 1 = 39 wanted -> 7 cases of 6 = 42, and none fits.
    assert {"sku_id": ice_cream, "sku": "Vanilla ice cream 500 ml", "zone": "frozen", "wanted": 42,
            "ordered": 0} in body["capped"]
