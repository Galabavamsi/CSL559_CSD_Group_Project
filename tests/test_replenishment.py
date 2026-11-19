"""Smarter replenishment (guide task 3.4): whole cases, free bin space, runs by itself."""
import asyncio
import time
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import select, update

from app import background, config
from app.db import SessionLocal
from app.models import Bin, Forecast, Store
from app.modules.replenishment import service as replenishment

from .conftest import assert_stock_is_consistent, atp


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


def test_putaway_never_overfills_a_bin(client, db, sku):
    milk = sku("Toned milk")
    first_bin = db.scalar(select(Bin).where(Bin.store_id == 1, Bin.code == "C-01-01"))   # holds the 6 old milk
    first_bin.capacity = 6
    db.commit()
    full = client.post("/v1/goods-receipts", json={
        "store_id": 1, "lines": [{"sku_id": milk, "qty": 5, "bin_id": first_bin.id}]})
    assert full.status_code == 409 and full.json()["error"]["code"] == "bin_full"
    assert atp(client, 1, milk) == 28                           # nothing received (30 less the buffer of 2)
    placed = client.post("/v1/goods-receipts", json={"store_id": 1, "lines": [{"sku_id": milk, "qty": 5}]})
    assert placed.status_code == 201 and placed.json()["received"][0]["bin"] == "C-01-04"   # milk's other bin has room
    assert_stock_is_consistent()


def test_run_all_orders_for_every_open_store_once(db):
    first = {row["store_id"]: row["transfer_order_id"] for row in replenishment.run_all(db)}
    assert first[1] is not None and first[2] is not None        # bread in store 1, bananas in store 2
    assert all(row["transfer_order_id"] is None for row in replenishment.run_all(db))   # all on their way


def test_run_all_skips_a_closed_store(db):
    db.get(Store, 2).status = "closed"
    db.commit()
    assert [row["store_id"] for row in replenishment.run_all(db)] == [1]


def test_replenishment_runs_on_its_own(client, monkeypatch):
    monkeypatch.setattr(config, "REPLENISHMENT_INTERVAL_MINUTES", 0.001)          # every 0.06 s

    async def run_briefly():
        loop = asyncio.create_task(background.replenish_loop())
        for _ in range(100):
            await asyncio.sleep(0.05)
            if client.get("/v1/transfer-orders", params={"store_id": 1}).json():
                break
        loop.cancel()

    asyncio.run(run_briefly())
    assert client.get("/v1/transfer-orders", params={"store_id": 1}).json()[0]["status"] == "created"


def test_the_timer_can_be_switched_off(monkeypatch):
    monkeypatch.setattr(config, "REPLENISHMENT_INTERVAL_MINUTES", 0)
    assert background.replenish_loop not in background.loops()


def test_the_timer_and_the_button_never_order_twice(monkeypatch):
    read_transit = replenishment.in_transit

    def read_slowly(db, store_id):
        time.sleep(0.2)                                         # both runs read before either writes, unless they take turns
        return read_transit(db, store_id)

    monkeypatch.setattr(replenishment, "in_transit", read_slowly)

    def run_in_own_session(_):
        with SessionLocal() as session:
            return replenishment.run(session, 1)["transfer_order"] is not None

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(run_in_own_session, range(2))) == [False, True]
