"""Smarter replenishment (guide task 3.4): whole cases, free bin space, runs by itself."""
import asyncio
import logging
import time
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import event, func, select, update

from app import background, config, events
from app.db import SessionLocal, engine
from app.errors import DomainError
from app.models import Bin, EventLog, Forecast, StockItem, StockLevel, Store, TransferOrder
from app.modules.inbound import service as inbound
from app.modules.inventory import service as inventory
from app.modules.replenishment import service as replenishment
from app.modules.slotting import service as slotting

from .conftest import assert_stock_is_consistent, atp


def test_orders_are_rounded_up_to_full_cases(client, sku):
    milk = sku("Toned milk")                                   # case of 12; reorder point 10, target 40
    client.post("/v1/stock-adjustments", json={"store_id": 1, "sku_id": milk, "delta": -27, "reason": "damage"})
    order = client.post("/v1/replenishment/run", params={"store_id": 1}).json()["transfer_order"]
    lines = {line["sku_id"]: line["qty_ordered"] for line in order["lines"]}
    assert lines[milk] == 48                                   # 40 - 3 = 37 needed -> 4 cases of 12
    assert lines[sku("White bread")] == 40                     # 36 needed -> 4 cases of 10
    assert_stock_is_consistent()


def squeeze_chilled_zone(client, db, sku):
    """Milk down to 4 (2 sellable after its buffer), curd down to 2, and four chilled bins of 24 units each."""
    milk, curd = sku("Toned milk"), sku("Curd")
    for sku_id, delta in ((milk, -26), (curd, -28)):
        client.post("/v1/stock-adjustments", json={"store_id": 1, "sku_id": sku_id, "delta": delta, "reason": "damage"})
    db.add_all([Forecast(store_id=1, sku_id=milk, daily_demand=20.0), Forecast(store_id=1, sku_id=curd, daily_demand=5.0)])
    db.execute(update(Bin).where(Bin.store_id == 1, Bin.zone == "chilled").values(capacity=24))
    db.commit()
    return milk, curd


def test_a_full_zone_orders_the_most_urgent_items_first(client, db, sku):
    milk, curd = squeeze_chilled_zone(client, db, sku)
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


def test_a_truck_the_system_ordered_can_be_put_away(client, db, sku):
    milk, curd = squeeze_chilled_zone(client, db, sku)
    order = client.post("/v1/replenishment/run", params={"store_id": 1}).json()["transfer_order"]   # milk 36, curd 24
    client.post(f"/v1/transfer-orders/{order['transfer_order_id']}/dispatch")
    receipt = client.post("/v1/goods-receipts", json={
        "store_id": 1, "transfer_order_id": order["transfer_order_id"],
        "lines": [{"sku_id": line["sku_id"], "qty": line["qty_ordered"]} for line in order["lines"]]})
    assert receipt.status_code == 201
    milk_bins = {row["bin"]: row["qty"] for row in receipt.json()["received"] if row["sku_id"] == milk}
    assert sum(milk_bins.values()) == 36 and len(milk_bins) == 2       # no single chilled bin had room for 36
    units = dict(db.execute(
        select(Bin.code, func.sum(StockItem.qty)).join(StockItem, StockItem.bin_id == Bin.id)
        .where(Bin.store_id == 1, Bin.zone == "chilled").group_by(Bin.code)).all())
    assert units["C-01-03"] == 30                                       # paneer's bin was already over: nothing added
    assert all(units[code] <= 24 for code in ("C-01-01", "C-01-02", "C-01-04"))
    assert_stock_is_consistent()


def test_two_receipts_at_once_never_overfill_a_bin(db, sku, monkeypatch):
    milk = sku("Toned milk")
    first_bin = db.scalar(select(Bin).where(Bin.store_id == 1, Bin.code == "C-01-01"))   # holds the 6 old milk
    first_bin.capacity, bin_id = 10, first_bin.id
    db.commit()
    room = slotting.room_in

    def room_slowly(session, bin_):
        time.sleep(0.3)                    # both receipts check before either writes, unless one checks again after
        return room(session, bin_)

    monkeypatch.setattr(slotting, "room_in", room_slowly)

    def receive(batch):
        with SessionLocal() as session:
            try:
                inbound.receive_goods(session, 1, [{"sku_id": milk, "qty": 4, "bin_id": bin_id, "batch_no": batch}])
                return "received"
            except DomainError as error:
                return error.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(receive, ["B-ONE", "B-TWO"])) == ["bin_full", "received"]
    assert db.scalar(select(func.sum(StockItem.qty)).where(StockItem.bin_id == bin_id)) == 10
    assert_stock_is_consistent()


def test_when_nothing_fits_the_run_says_so(client, db):
    db.execute(update(Bin).where(Bin.store_id == 1).values(capacity=0))
    db.commit()
    body = client.post("/v1/replenishment/run", params={"store_id": 1}).json()
    assert body["transfer_order"] is None
    assert {row["sku"] for row in body["capped"]} == {"White bread 400 g", "Vanilla ice cream 500 ml"}
    newest = client.get("/v1/events", params={"store_id": 1}).json()[0]    # a manager sees it on the live feed
    assert (newest["type"], newest["payload"]) == ("replenishment.capped", {"capped": body["capped"]})


def test_receiving_nothing_is_still_refused(db, sku):
    try:
        inbound.receive_goods(db, 1, [{"sku_id": sku("Toned milk"), "qty": 0}])
    except DomainError as error:
        assert error.code == "bad_quantity"
    else:
        raise AssertionError("a line of 0 units was accepted")


def test_a_zone_with_no_bins_gets_nothing_ordered(client, db, sku):
    ice_cream = sku("Vanilla ice cream")                        # 1 left: below its reorder point
    db.execute(update(Bin).where(Bin.store_id == 1, Bin.zone == "frozen").values(zone="ambient"))
    db.commit()                                                 # as if store 1 had no freezer at all
    body = client.post("/v1/replenishment/run", params={"store_id": 1}).json()
    assert ice_cream not in {line["sku_id"] for line in body["transfer_order"]["lines"]}
    assert {"sku_id": ice_cream, "sku": "Vanilla ice cream 500 ml", "zone": "frozen", "wanted": 42,
            "ordered": 0} in body["capped"]


def test_one_failing_store_does_not_stop_the_others(db, monkeypatch, caplog):
    monkeypatch.setattr(logging.getLogger("app"), "propagate", True)     # so caplog sees the app's log lines
    publish = events.publish

    def break_store_1(session, event_type, store_id, payload):
        if event_type == "transfer_order.created" and store_id == 1:
            raise RuntimeError("store 1 is broken")             # its order is written but not committed yet
        publish(session, event_type, store_id, payload)

    monkeypatch.setattr(events, "publish", break_store_1)
    rows = {row["store_id"]: row for row in replenishment.run_all(db)}
    assert rows[1]["transfer_order_id"] is None and "store 1 is broken" in rows[1]["error"]
    assert rows[2]["transfer_order_id"] is not None             # store 2's bananas are still ordered
    assert not db.scalars(select(TransferOrder).where(TransferOrder.store_id == 1)).all()   # half-order rolled back
    assert "Replenishment failed for store 1" in caplog.text


def test_items_sold_out_together_go_to_the_faster_seller_first(client, db, sku):
    milk, curd = sku("Toned milk"), sku("Curd")
    for sku_id, delta in ((milk, -28), (curd, -30)):            # milk 2 (both hidden by its buffer), curd 0
        client.post("/v1/stock-adjustments", json={"store_id": 1, "sku_id": sku_id, "delta": delta, "reason": "damage"})
    db.add_all([Forecast(store_id=1, sku_id=milk, daily_demand=20.0), Forecast(store_id=1, sku_id=curd, daily_demand=5.0)])
    db.execute(update(Bin).where(Bin.store_id == 1, Bin.zone == "chilled").values(capacity=20))
    db.commit()
    # Customers can buy neither, so both have 0 days of cover. The chilled zone holds 4 x 20 = 80 units and 32 are
    # stored (milk 2, paneer 30): 48 free, room for one of the two 48-unit orders. Milk sells 4 times as fast.
    body = client.post("/v1/replenishment/run", params={"store_id": 1}).json()
    lines = {line["sku_id"]: line["qty_ordered"] for line in body["transfer_order"]["lines"]}
    assert lines.get(milk) == 48 and curd not in lines


def test_an_item_with_reordering_stopped_is_left_alone(client, sku):
    milk = sku("Toned milk")
    stopped = client.put(f"/v1/stores/1/reorder-settings/{milk}", json={"reorder_stopped": True})
    assert stopped.status_code == 200 and stopped.json()["reorder_stopped"] is True
    client.post("/v1/stock-adjustments", json={"store_id": 1, "sku_id": milk, "delta": -27, "reason": "damage"})
    order = client.post("/v1/replenishment/run", params={"store_id": 1}).json()["transfer_order"]
    assert milk not in {line["sku_id"] for line in order["lines"]}          # bread and ice cream still are
    feed = client.get("/v1/events", params={"store_id": 1, "limit": 100}).json()
    assert not [e for e in feed if e["type"] == "stock.low" and e["payload"]["sku_id"] == milk]   # no alert either
    client.put(f"/v1/stores/1/reorder-settings/{milk}", json={"reorder_stopped": False})
    order = client.post("/v1/replenishment/run", params={"store_id": 1}).json()["transfer_order"]
    assert {line["sku_id"]: line["qty_ordered"] for line in order["lines"]}.get(milk) == 48


def test_stopping_reordering_lets_a_manager_drop_an_item(client, sku):
    tea = sku("Tea")                                            # 30 on hand in store 1
    client.put(f"/v1/stores/1/reorder-settings/{tea}", json={"reorder_stopped": True})
    client.post("/v1/stock-adjustments", json={"store_id": 1, "sku_id": tea, "delta": -30, "reason": "damage"})
    client.post("/v1/replenishment/run", params={"store_id": 1})          # the timer or the button runs meanwhile
    assert client.delete(f"/v1/stores/1/assortment/{tea}").status_code == 200   # no truck on its way to wait for
    assert_stock_is_consistent()


def test_only_a_manager_of_the_store_can_stop_reordering(client, client_as, sku):
    milk, bananas = sku("Toned milk"), sku("Bananas")
    url = f"/v1/stores/1/reorder-settings/{milk}"
    assert client_as("picker", 1).put(url, json={"reorder_stopped": True}).status_code == 403
    assert client_as("manager", 2).put(url, json={"reorder_stopped": True}).status_code == 403
    assert client_as("manager", 1).put(url, json={"reorder_stopped": True}).status_code == 200
    client.delete(f"/v1/stores/2/assortment/{bananas}")                    # store 2 stops carrying bananas
    missing = client.put(f"/v1/stores/2/reorder-settings/{bananas}", json={"reorder_stopped": True})
    assert missing.status_code == 404 and missing.json()["error"]["code"] == "not_carried"


def saved_settings(db, sku_id: int) -> tuple[int, bool]:
    """(reorder point, reorder stopped) of the SKU in store 1, read straight from the database."""
    level = db.get(StockLevel, (1, sku_id), populate_existing=True)
    return level.reorder_point, level.reorder_stopped


def set_reorder_point(db, sku_id: int, reorder_point: int) -> None:
    """Save a reorder point in store 1 without the API, as a forecast run or an older version of the app did."""
    db.execute(update(StockLevel).where(StockLevel.store_id == 1, StockLevel.sku_id == sku_id)
               .values(reorder_point=reorder_point))
    db.commit()


def test_a_reorder_point_sent_to_reorder_settings_is_saved_and_used(client, db, sku):
    """Review of PR #69: a reorder_point sent here was ignored with a 200, so a reorder point saved before the limits
    of issue #63 could only be corrected by dropping the SKU and adding it again. 0 here: stock is never below it."""
    milk = sku("Toned milk")                                   # case of 12; target 40
    set_reorder_point(db, milk, 0)
    client.post("/v1/stock-adjustments", json={"store_id": 1, "sku_id": milk, "delta": -30, "reason": "damage"})
    order = client.post("/v1/replenishment/run", params={"store_id": 1}).json()["transfer_order"]
    assert milk not in {line["sku_id"] for line in order["lines"]}          # sold out, and still not reordered
    saved = client.put(f"/v1/stores/1/reorder-settings/{milk}", json={"reorder_point": 10})
    assert saved.status_code == 200, saved.text
    assert saved.json() == {"store_id": 1, "sku_id": milk, "sku": "Toned milk 500 ml", "reorder_stopped": False,
                            "reorder_point": 10}
    feed = client.get("/v1/events", params={"store_id": 1, "limit": 100}).json()
    assert {"sku_id": milk, "reorder_stopped": False, "reorder_point": 10} in [
        e["payload"] for e in feed if e["type"] == "reordering.changed"]   # the live feed shows the change
    order = client.post("/v1/replenishment/run", params={"store_id": 1}).json()["transfer_order"]
    assert {line["sku_id"]: line["qty_ordered"] for line in order["lines"]}.get(milk) == 48   # 40 -> 4 cases of 12


def test_a_reorder_point_that_cannot_work_is_refused_as_when_adding(client, db, sku):
    """The limits of adding a SKU (issue #63): at least 1, at most what a bin holds, and below the target stock, as a
    reorder refills up to the target. A refused body changes nothing, not even the reorder_stopped sent with it."""
    milk = sku("Toned milk")                                   # reorder point 10, target 40
    url = f"/v1/stores/1/reorder-settings/{milk}"
    for bad in (-5, 0, 100_001):
        refused = client.put(url, json={"reorder_stopped": True, "reorder_point": bad})
        assert refused.status_code == 422, bad
    for bad in (40, 41):                                       # not below the target
        refused = client.put(url, json={"reorder_stopped": True, "reorder_point": bad})
        assert refused.status_code == 422, bad
        assert refused.json()["error"]["code"] == "bad_reorder_point"
        assert refused.json()["error"]["details"] == {"target_stock": 40}
    assert saved_settings(db, milk) == (10, False)
    for works in (1, 39):                                      # the lowest and the highest that work
        assert client.put(url, json={"reorder_point": works}).status_code == 200, works
    assert saved_settings(db, milk) == (39, False)


def test_reorder_settings_with_only_reorder_stopped_work_as_before(client, db, sku):
    """The body every caller sent before reorder_point could be changed here: it still only stops or restarts
    reordering, and the reorder point stays as it was."""
    milk = sku("Toned milk")
    set_reorder_point(db, milk, 25)
    url = f"/v1/stores/1/reorder-settings/{milk}"
    stopped = client.put(url, json={"reorder_stopped": True})
    assert stopped.status_code == 200 and stopped.json()["reorder_stopped"] is True
    assert saved_settings(db, milk) == (25, True)
    restarted = client.put(url, json={"reorder_stopped": False})
    assert restarted.status_code == 200 and restarted.json()["reorder_stopped"] is False
    assert saved_settings(db, milk) == (25, False)


def test_reorder_settings_with_only_a_reorder_point_keep_reordering_stopped(client, db, sku):
    milk = sku("Toned milk")
    url = f"/v1/stores/1/reorder-settings/{milk}"
    client.put(url, json={"reorder_stopped": True})
    changed = client.put(url, json={"reorder_point": 20})
    assert changed.status_code == 200, changed.text
    assert saved_settings(db, milk) == (20, True)               # still being run down


def test_reorder_settings_refuse_an_empty_body_and_fields_they_cannot_change(client, db, sku):
    """Nothing is ignored in silence. A body with nothing to change is a 422, as it was when reorder_stopped was
    required; so is a field this route does not change (target_stock) or a misspelt one, even next to a good one."""
    milk = sku("Toned milk")
    url = f"/v1/stores/1/reorder-settings/{milk}"
    for body in ({}, {"target_stock": 60}, {"reorder_stopped": True, "target_stock": 60},
                 {"reorder_stopped": True, "reorderpoint": 20}):
        assert client.put(url, json=body).status_code == 422, body
    assert saved_settings(db, milk) == (10, False)


def test_a_target_lowered_meanwhile_still_refuses_the_reorder_point(client, db, sku):
    """The check is in the update itself, like every contested change in this app: a forecast run that lowers the
    target just before the save cannot let through a reorder point at or above the new target."""
    milk = sku("Toned milk")                                   # reorder point 10, target 40
    forecast_ran = []

    def forecast_runs_first(conn, cursor, statement, parameters, context, executemany):
        """Runs just before the save's UPDATE is sent to the database."""
        if not forecast_ran and statement.startswith("UPDATE stock_levels"):
            forecast_ran.append(True)
            with SessionLocal() as other:
                other.execute(update(StockLevel).where(StockLevel.store_id == 1, StockLevel.sku_id == milk)
                              .values(reorder_point=20, target_stock=25))
                other.commit()

    event.listen(engine, "before_cursor_execute", forecast_runs_first)
    try:
        refused = client.put(f"/v1/stores/1/reorder-settings/{milk}", json={"reorder_point": 30})
    finally:
        event.remove(engine, "before_cursor_execute", forecast_runs_first)
    assert forecast_ran == [True]
    assert refused.status_code == 422, refused.text
    assert refused.json()["error"]["details"] == {"target_stock": 25}
    assert saved_settings(db, milk) == (20, False)              # what the forecast run saved


def _low_alerts(db, sku_id: int) -> list[dict]:
    """The stock.low events store 1 published for one SKU, oldest first."""
    return [event.payload for event in db.scalars(select(EventLog).where(EventLog.type == "stock.low",
                                                                         EventLog.store_id == 1)
                                                  .order_by(EventLog.id)) if event.payload["sku_id"] == sku_id]


def _damage(client, sku_id: int, units: int) -> None:
    written_off = client.post("/v1/stock-adjustments",
                              json={"store_id": 1, "sku_id": sku_id, "delta": -units, "reason": "damage"})
    assert written_off.status_code == 200, written_off.text


def _units_over_reorder_point(db, sku_id: int) -> int:
    level = inventory.get_level(db, 1, sku_id)
    return level.qty_on_hand - level.qty_reserved - level.reorder_point


def test_an_item_that_stays_low_is_reported_once_not_on_every_change(client, db, sku):
    """stock.low marks the moment an item drops below its reorder point. Each later sale, hold or write-off while it
    stays low used to publish another one (five holds, five alerts)."""
    milk = sku("Toned milk")
    _damage(client, milk, _units_over_reorder_point(db, milk) + 1)          # one unit under the reorder point
    for _ in range(3):
        _damage(client, milk, 1)
    alerts = _low_alerts(db, milk)
    assert len(alerts) == 1, alerts
    assert alerts[0]["atp"] == alerts[0]["reorder_point"] - 1


def test_after_a_delivery_an_item_that_drops_low_again_is_reported_again(client, db, sku):
    milk = sku("Toned milk")
    _damage(client, milk, _units_over_reorder_point(db, milk) + 1)          # under the reorder point: reported
    delivered = client.post("/v1/goods-receipts", json={"store_id": 1, "lines": [{"sku_id": milk, "qty": 1}]})
    assert delivered.status_code == 201, delivered.text                       # back at the reorder point
    _damage(client, milk, 1)                                                  # under it again, after a delivery
    assert len(_low_alerts(db, milk)) == 2
