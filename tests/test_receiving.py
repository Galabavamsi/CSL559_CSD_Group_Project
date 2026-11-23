"""Two-step receiving (guide task 3.5): open a receipt, scan the truck onto the dock, put each line away, close."""
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

from sqlalchemy import func, select, update

from app import clock
from app.db import SessionLocal
from app.errors import DomainError
from app.models import SKU, Bin, StockItem, StockLedger, TransferOrder
from app.modules.inbound import service as inbound
from app.modules.inventory import service as inventory
from app.modules.replenishment import service as replenishment
from app.modules.slotting import service as slotting

from .conftest import assert_stock_is_consistent, atp


def in_days(n: int) -> str:
    return (clock.today() + timedelta(days=n)).isoformat()


def open_truck(client, store_id: int = 1) -> tuple[dict, dict]:
    """Order what the store needs (store 1 on the seed: bread 40, ice cream 42), dispatch it and open its receipt."""
    order = client.post("/v1/replenishment/run", params={"store_id": store_id}).json()["transfer_order"]
    client.post(f"/v1/transfer-orders/{order['transfer_order_id']}/dispatch")
    opened = client.post("/v1/goods-receipts/open",
                         json={"store_id": store_id, "transfer_order_id": order["transfer_order_id"]})
    assert opened.status_code == 201, opened.text
    return order, opened.json()


def scan(client, db, receipt: dict, sku_id: int, qty: int, **details):
    """Scan units of batch LOT1 with a full shelf life, unless `details` say otherwise."""
    sku = db.get(SKU, sku_id)
    return client.post(f"/v1/goods-receipts/{receipt['receipt_id']}/scans",
                       json={"barcode": sku.barcode, "qty": qty, "batch_no": "LOT1",
                             "expiry_date": in_days(sku.shelf_life_days), **details})


def put_away(client, receipt: dict, sku_id: int, batch_no: str, bin_code: str, qty: int):
    return client.post(f"/v1/goods-receipts/{receipt['receipt_id']}/putaway",
                       json={"sku_id": sku_id, "batch_no": batch_no, "bin_code": bin_code, "qty": qty})


def tasks_for(client, receipt: dict, sku_id: int) -> list[dict]:
    tasks = client.get(f"/v1/goods-receipts/{receipt['receipt_id']}/putaway-tasks").json()
    return [task for task in tasks if task["sku_id"] == sku_id]


def line_of(body: dict, sku_id: int, batch_no: str | None = None) -> dict:
    return next(line for line in body["lines"]
                if line["sku_id"] == sku_id and batch_no in (None, line["batch_no"]))


def test_scanned_units_wait_on_the_dock(client, db, sku):
    bread, ice_cream = sku("White bread"), sku("Vanilla ice cream")
    before = (atp(client, 1, bread), atp(client, 1, ice_cream))
    _, receipt = open_truck(client)
    assert scan(client, db, receipt, bread, 40).json()["scan"]["outcome"] == "on_dock"
    body = scan(client, db, receipt, ice_cream, 42).json()
    assert (atp(client, 1, bread), atp(client, 1, ice_cream)) == before          # nothing is sellable yet
    assert {line["sku_id"]: line["on_dock"] for line in body["lines"]} == {bread: 40, ice_cream: 42}
    assert_stock_is_consistent()


def test_damaged_units_are_recorded_off_the_dock(client, db, sku):
    bread = sku("White bread")
    _, receipt = open_truck(client)
    scan(client, db, receipt, bread, 35)
    body = scan(client, db, receipt, bread, 5, damaged=True).json()
    assert body["scan"]["outcome"] == "damaged"
    line = line_of(body, bread)
    assert (line["scanned"], line["damaged"], line["on_dock"]) == (35, 5, 35)


def test_a_batch_expiring_tomorrow_is_refused(client, db, sku):
    milk = sku("Toned milk")                                     # shelf life 3 days
    _, receipt = open_truck(client)
    body = scan(client, db, receipt, milk, 12, batch_no="M-SHORT", expiry_date=in_days(1)).json()
    assert body["scan"]["outcome"] == "rejected" and "shelf life" in body["scan"]["reason"]
    line = line_of(body, milk)
    assert (line["rejected"], line["scanned"], line["on_dock"]) == (12, 0, 0)


def test_exactly_half_its_shelf_life_left_is_accepted(client, db, sku):
    bread = sku("White bread")                                   # shelf life 4 days
    _, receipt = open_truck(client)
    half = scan(client, db, receipt, bread, 10, batch_no="B-HALF", expiry_date=in_days(2)).json()
    less = scan(client, db, receipt, bread, 10, batch_no="B-LESS", expiry_date=in_days(1)).json()
    assert (half["scan"]["outcome"], less["scan"]["outcome"]) == ("on_dock", "rejected")


def test_receipt_rules_at_open_and_scan(client, db, sku):
    bread = sku("White bread")
    order, receipt = open_truck(client)
    again = client.post("/v1/goods-receipts/open",
                        json={"store_id": 1, "transfer_order_id": order["transfer_order_id"]})
    assert again.status_code == 409 and again.json()["error"]["code"] == "receipt_open"
    elsewhere = client.post("/v1/goods-receipts/open",
                            json={"store_id": 2, "transfer_order_id": order["transfer_order_id"]})
    assert elsewhere.status_code == 404
    unknown = client.post(f"/v1/goods-receipts/{receipt['receipt_id']}/scans",
                          json={"barcode": "0000", "qty": 1, "batch_no": "LOT1", "expiry_date": in_days(4)})
    assert unknown.status_code == 422 and unknown.json()["error"]["code"] == "unknown_barcode"
    scan(client, db, receipt, bread, 5, batch_no="B1", expiry_date=in_days(4))
    clash = scan(client, db, receipt, bread, 5, batch_no="B1", expiry_date=in_days(3))
    assert clash.status_code == 422 and clash.json()["error"]["code"] == "batch_mismatch"


def test_putting_away_one_line_makes_only_that_sku_sellable(client, db, sku):
    bread, ice_cream = sku("White bread"), sku("Vanilla ice cream")
    before = {bread: atp(client, 1, bread), ice_cream: atp(client, 1, ice_cream)}
    _, receipt = open_truck(client)
    scan(client, db, receipt, bread, 40)
    scan(client, db, receipt, ice_cream, 42)
    for task in tasks_for(client, receipt, bread):
        put = put_away(client, receipt, bread, task["batch_no"], task["bin_code"], task["qty"])
        assert put.status_code == 200, put.text
    assert atp(client, 1, bread) == before[bread] + 40            # sellable the moment it is put away
    assert atp(client, 1, ice_cream) == before[ice_cream]         # still waiting on the dock
    assert line_of(put.json(), bread)["on_dock"] == 0 and line_of(put.json(), ice_cream)["on_dock"] == 42
    assert_stock_is_consistent()


def test_putaway_tasks_name_bins_with_room(client, db, sku):
    milk, ice_cream = sku("Toned milk"), sku("Vanilla ice cream")
    _, receipt = open_truck(client)
    db.execute(update(Bin).where(Bin.store_id == 1, Bin.zone == "chilled").values(capacity=40))
    db.execute(update(Bin).where(Bin.store_id == 1, Bin.zone == "frozen").values(capacity=0))
    db.commit()
    scan(client, db, receipt, milk, 36)
    scan(client, db, receipt, ice_cream, 42)
    # Milk's own bins first: C-01-01 holds 6 (34 free), C-01-04 holds 24 (16 free).
    assert [(t["bin_code"], t["qty"]) for t in tasks_for(client, receipt, milk)] == [("C-01-01", 34), ("C-01-04", 2)]
    [frozen] = tasks_for(client, receipt, ice_cream)
    assert frozen["bin_code"] is None and frozen["qty"] == 42 and "room" in frozen["problem"]


def test_putaway_refusals(client, db, sku):
    bread, milk = sku("White bread"), sku("Toned milk")
    _, receipt = open_truck(client)
    scan(client, db, receipt, bread, 40, batch_no="B-1")
    scan(client, db, receipt, milk, 12, batch_no="M-1")
    db.execute(update(Bin).where(Bin.store_id == 1, Bin.code == "A-01-02").values(capacity=0))
    db.commit()
    before = atp(client, 1, bread)
    refusals = [(put_away(client, receipt, bread, "B-1", "A-01-01", 41), 422, "too_many"),
                (put_away(client, receipt, bread, "B-NONE", "A-01-01", 1), 422, "not_scanned"),
                (put_away(client, receipt, milk, "M-1", "A-01-01", 12), 422, "wrong_zone"),
                (put_away(client, receipt, bread, "B-1", "Z-99-99", 1), 422, "bad_bin"),
                (put_away(client, receipt, bread, "B-1", "A-01-02", 1), 409, "bin_full")]
    for response, status, code in refusals:
        assert (response.status_code, response.json()["error"]["code"]) == (status, code)
    assert atp(client, 1, bread) == before
    assert_stock_is_consistent()


def test_two_putaways_never_overfill_a_bin(db, sku, monkeypatch):
    milk = sku("Toned milk")
    first_bin = db.scalar(select(Bin).where(Bin.store_id == 1, Bin.code == "C-01-01"))   # holds the 6 old milk
    first_bin.capacity, bin_id = 10, first_bin.id
    db.commit()
    receipts = []
    for batch in ("B-ONE", "B-TWO"):
        receipt_id = inbound.open_receipt(db, 1)["receipt_id"]
        inbound.scan(db, receipt_id, db.get(SKU, milk).barcode, 4, batch_no=batch)
        receipts.append((receipt_id, batch))
    room = slotting.room_in

    def room_slowly(session, bin_):
        time.sleep(0.3)                    # both putaways check before either writes, unless one checks again after
        return room(session, bin_)

    monkeypatch.setattr(slotting, "room_in", room_slowly)

    def put(receipt):
        with SessionLocal() as session:
            try:
                inbound.put_away(session, receipt[0], milk, receipt[1], "C-01-01", 4)
                return "put"
            except DomainError as error:
                return error.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(put, receipts)) == ["bin_full", "put"]
    assert db.scalar(select(func.sum(StockItem.qty)).where(StockItem.bin_id == bin_id)) == 10
    assert_stock_is_consistent()


def close(client, receipt: dict):
    return client.post(f"/v1/goods-receipts/{receipt['receipt_id']}/close")


def put_all(client, receipt: dict, sku_id: int) -> None:
    for task in tasks_for(client, receipt, sku_id):
        assert put_away(client, receipt, sku_id, task["batch_no"], task["bin_code"], task["qty"]).status_code == 200


def test_closing_reports_ordered_versus_received_for_every_line(client, db, sku):
    bread, ice_cream = sku("White bread"), sku("Vanilla ice cream")
    order, receipt = open_truck(client)
    scan(client, db, receipt, bread, 34)                        # the hub sent 6 bread short, and no ice cream
    put_all(client, receipt, bread)
    body = close(client, receipt).json()
    assert body["status"] == "closed"
    assert {row["sku_id"]: row for row in body["report"]} == {
        bread: {"sku_id": bread, "sku": "White bread 400 g", "ordered": 40, "received": 34, "damaged": 0,
                "rejected": 0, "sent_back": 0},
        ice_cream: {"sku_id": ice_cream, "sku": "Vanilla ice cream 500 ml", "ordered": 42, "received": 0,
                    "damaged": 0, "rejected": 0, "sent_back": 0}}
    assert sorted(row["sku_id"] for row in body["shortfalls"]) == sorted([bread, ice_cream])
    orders = {o["transfer_order_id"]: o for o in client.get("/v1/transfer-orders", params={"store_id": 1}).json()}
    assert orders[order["transfer_order_id"]]["status"] == "received"
    newest = client.get("/v1/events", params={"store_id": 1}).json()[0]
    assert newest["type"] == "goods.received" and newest["payload"]["receipt_id"] == receipt["receipt_id"]
    assert_stock_is_consistent()


def test_damaged_units_appear_in_the_shortfall_list(client, db, sku):
    bread = sku("White bread")
    before = atp(client, 1, bread)
    _, receipt = open_truck(client)
    scan(client, db, receipt, bread, 35)
    scan(client, db, receipt, bread, 5, damaged=True)
    put_all(client, receipt, bread)
    [short] = [row for row in close(client, receipt).json()["shortfalls"] if row["sku_id"] == bread]
    assert (short["ordered"], short["received"], short["damaged"]) == (40, 35, 5)
    assert atp(client, 1, bread) == before + 35                 # the 5 damaged never entered stock
    assert_stock_is_consistent()


def test_a_receipt_closes_only_once_and_never_with_units_on_the_dock(client, db, sku):
    bread = sku("White bread")
    _, receipt = open_truck(client)
    scan(client, db, receipt, bread, 40, batch_no="B1")
    waiting = close(client, receipt)
    assert waiting.status_code == 409 and waiting.json()["error"]["code"] == "still_on_dock"
    put_all(client, receipt, bread)
    assert close(client, receipt).status_code == 200
    for late in (scan(client, db, receipt, bread, 1), put_away(client, receipt, bread, "B1", "A-01-01", 1),
                 close(client, receipt)):
        assert (late.status_code, late.json()["error"]["code"]) == (409, "receipt_closed")


def test_a_receipt_with_nothing_scanned_cannot_close(client, db, sku):
    """Member 4's review of PR 54: it closed, marking the truck received at 0 units, so the real truck was refused."""
    order, receipt = open_truck(client)
    for send_back in ("false", "true"):
        refused = client.post(f"/v1/goods-receipts/{receipt['receipt_id']}/close", params={"send_back": send_back})
        assert (refused.status_code, refused.json()["error"]["code"]) == (409, "nothing_scanned")
    assert db.get(TransferOrder, order["transfer_order_id"], populate_existing=True).status == "dispatched"


def test_a_truck_that_arrived_all_damaged_still_closes(client, db, sku):
    """Recorded units count as scanned: the closed receipt is the record that the truck came and nothing was usable."""
    bread, ice_cream = sku("White bread"), sku("Vanilla ice cream")
    _, receipt = open_truck(client)
    scan(client, db, receipt, bread, 40, damaged=True)
    scan(client, db, receipt, ice_cream, 42, damaged=True)
    closed = close(client, receipt)
    assert closed.status_code == 200, closed.text
    assert {row["sku_id"]: (row["received"], row["damaged"]) for row in closed.json()["report"]} == {
        bread: (0, 40), ice_cream: (0, 42)}


def test_an_empty_receipt_can_be_cancelled_and_the_truck_received_later(client, db, sku):
    order, receipt = open_truck(client)
    url = f"/v1/goods-receipts/{receipt['receipt_id']}/cancel"
    cancelled = client.post(url, headers={"Idempotency-Key": "cancel-1"})
    assert cancelled.status_code == 200 and cancelled.json()["status"] == "cancelled"
    assert client.post(url, headers={"Idempotency-Key": "cancel-1"}).json() == cancelled.json()     # a retry
    bread = sku("White bread")
    for late in (scan(client, db, receipt, bread, 1), put_away(client, receipt, bread, "LOT1", "A-01-01", 1),
                 close(client, receipt)):
        assert (late.status_code, late.json()["error"]["code"]) == (409, "receipt_closed")
        assert "cancelled" in late.json()["error"]["message"]
    assert db.get(TransferOrder, order["transfer_order_id"], populate_existing=True).status == "dispatched"
    again = client.post("/v1/goods-receipts/open",
                        json={"store_id": 1, "transfer_order_id": order["transfer_order_id"]})
    assert again.status_code == 201, again.text                     # Receive truck works again


def test_a_receipt_scanned_by_mistake_can_still_be_cancelled(client, db, sku):
    """The review of the first fix: one case scanned on the wrong truck left only close with send_back, which marks
    the truck received at 0 units, so the real one would be refused. The lines stay as the record."""
    bread = sku("White bread")
    order, receipt = open_truck(client)
    scan(client, db, receipt, bread, 6)
    scan(client, db, receipt, bread, 2, damaged=True)
    cancelled = client.post(f"/v1/goods-receipts/{receipt['receipt_id']}/cancel")
    assert cancelled.status_code == 200, cancelled.text
    line = line_of(cancelled.json(), bread)
    assert (line["scanned"], line["damaged"], line["on_dock"], line["sent_back"]) == (6, 2, 0, 6)
    assert client.get(f"/v1/goods-receipts/{receipt['receipt_id']}/putaway-tasks").json() == []
    assert db.get(TransferOrder, order["transfer_order_id"], populate_existing=True).status == "dispatched"
    again = client.post("/v1/goods-receipts/open",
                        json={"store_id": 1, "transfer_order_id": order["transfer_order_id"]})
    assert again.status_code == 201, again.text


def test_a_receipt_with_units_put_away_cannot_be_cancelled(client, db, sku):
    bread = sku("White bread")
    _, receipt = open_truck(client)
    scan(client, db, receipt, bread, 40)
    put_away(client, receipt, bread, "LOT1", "A-01-01", 1)                 # one unit is sellable now
    refused = client.post(f"/v1/goods-receipts/{receipt['receipt_id']}/cancel")
    assert (refused.status_code, refused.json()["error"]["code"]) == (409, "already_put_away")


def test_a_cancel_waits_for_a_putaway_in_flight(client, db, sku, monkeypatch):
    """A cancel must not decide "nothing put away" while a putaway that holds the receipt is still running: its units
    would be sellable on a cancelled receipt and still counted as on their way."""
    bread = sku("White bread")
    before = atp(client, 1, bread)
    _, receipt = open_truck(client)
    scan(client, db, receipt, bread, 40)
    room, putting = slotting.room_in, threading.Event()

    def room_slowly(session, bin_):
        putting.set()                                   # the putaway holds the receipt by now
        time.sleep(0.3)
        return room(session, bin_)

    monkeypatch.setattr(slotting, "room_in", room_slowly)

    def put() -> str:
        with SessionLocal() as session:
            inbound.put_away(session, receipt["receipt_id"], bread, "LOT1", "A-01-01", 40)
            return "put"

    def cancel() -> str:
        assert putting.wait(5)
        with SessionLocal() as session:
            try:
                inbound.cancel_receipt(session, receipt["receipt_id"])
                return "cancelled"
            except DomainError as error:
                return error.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = [pool.submit(put), pool.submit(cancel)]
        assert [outcome.result() for outcome in outcomes] == ["put", "already_put_away"]
    assert atp(client, 1, bread) == before + 40
    assert_stock_is_consistent()


def test_a_one_call_receipt_is_saved_as_a_closed_receipt(client, sku):
    bread = sku("White bread")
    body = client.post("/v1/goods-receipts",
                       json={"store_id": 1, "lines": [{"sku_id": bread, "qty": 10, "batch_no": "B-SAVED"}]}).json()
    saved = client.get(f"/v1/goods-receipts/{body['receipt_id']}").json()
    assert (saved["status"], saved["transfer_order_id"]) == ("closed", None)
    assert [(line["sku_id"], line["batch_no"], line["scanned"], line["put_away"]) for line in saved["lines"]] == \
        [(bread, "B-SAVED", 10, 10)]


def test_a_short_dated_line_does_not_sink_a_one_call_receipt(client, sku):
    bread, ice_cream = sku("White bread"), sku("Vanilla ice cream")
    order = client.post("/v1/replenishment/run", params={"store_id": 1}).json()["transfer_order"]
    response = client.post("/v1/goods-receipts", json={
        "store_id": 1, "transfer_order_id": order["transfer_order_id"],
        "lines": [{"sku_id": bread, "qty": 40, "batch_no": "B-OLD", "expiry_date": in_days(1)},
                  {"sku_id": ice_cream, "qty": 42}]})
    assert response.status_code == 201, response.text
    body = response.json()
    assert {row["sku_id"] for row in body["received"]} == {ice_cream}
    assert [(row["sku_id"], row["qty"]) for row in body["rejected"]] == [(bread, 40)]
    assert {"sku_id": bread, "sku": "White bread 400 g", "ordered": 40, "received": 0} in body["discrepancies"]
    assert_stock_is_consistent()


def test_a_batch_without_a_number_is_named_after_its_expiry_date(client, db, sku):
    """Issue #56: it was named after the day it arrived, so a second delivery that day with another expiry date joined
    the first batch and took its date. Two dates of one SKU in one receipt were a 422 batch_mismatch for the same
    reason."""
    sugar = sku("Sugar")
    early, late = clock.today() + timedelta(days=200), clock.today() + timedelta(days=300)

    def stocked() -> dict[date, tuple[set, int]]:
        """Batch names and units of sugar per expiry date."""
        found: dict[date, tuple[set, int]] = {}
        for item in db.scalars(select(StockItem).where(StockItem.store_id == 1, StockItem.sku_id == sugar,
                                                       StockItem.expiry_date.in_((early, late)))
                               .execution_options(populate_existing=True)):
            names, units = found.get(item.expiry_date, (set(), 0))
            found[item.expiry_date] = (names | {item.batch_no}, units + item.qty)
        return found

    for expiry in (early, late):                                        # two deliveries on the same day
        delivered = client.post("/v1/goods-receipts", json={"store_id": 1, "lines": [
            {"sku_id": sugar, "qty": 5, "expiry_date": expiry.isoformat()}]})
        assert delivered.status_code == 201, delivered.text
    assert stocked() == {early: ({f"B{early:%y%m%d}"}, 5), late: ({f"B{late:%y%m%d}"}, 5)}
    both = client.post("/v1/goods-receipts", json={"store_id": 1, "lines": [
        {"sku_id": sugar, "qty": 2, "expiry_date": early.isoformat()},
        {"sku_id": sugar, "qty": 3, "expiry_date": late.isoformat()}]})
    assert both.status_code == 201, both.text                           # one receipt, two dates
    assert stocked() == {early: ({f"B{early:%y%m%d}"}, 7), late: ({f"B{late:%y%m%d}"}, 8)}
    assert_stock_is_consistent()


def test_two_putaways_of_one_line_never_stock_more_than_was_scanned(client, db, sku, monkeypatch):
    bread = sku("White bread")
    before = atp(client, 1, bread)
    _, receipt = open_truck(client)
    scan(client, db, receipt, bread, 40, batch_no="B-RACE")
    room = slotting.room_in

    def room_slowly(session, bin_):
        time.sleep(0.3)                    # both look at the dock before either writes, unless they take turns
        return room(session, bin_)

    monkeypatch.setattr(slotting, "room_in", room_slowly)

    def put(_):
        with SessionLocal() as session:
            try:
                inbound.put_away(session, receipt["receipt_id"], bread, "B-RACE", "A-01-01", 40)
                return "put"
            except DomainError as error:
                return error.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(put, range(2))) == ["put", "too_many"]
    assert atp(client, 1, bread) == before + 40
    assert_stock_is_consistent()


def test_the_ledger_names_who_received_the_stock(client_as, db, sku):
    bread = sku("White bread")
    receiver = client_as("receiver", 1)
    receipt = receiver.post("/v1/goods-receipts/open", json={"store_id": 1}).json()
    receiver.post(f"/v1/goods-receipts/{receipt['receipt_id']}/scans",
                  json={"barcode": db.get(SKU, bread).barcode, "qty": 4, "batch_no": "B-WHO",
                        "expiry_date": in_days(4)})
    receiver.post(f"/v1/goods-receipts/{receipt['receipt_id']}/putaway",
                  json={"sku_id": bread, "batch_no": "B-WHO", "bin_code": "A-01-01", "qty": 4, "actor": "someone"})
    receiver.post("/v1/goods-receipts",
                  json={"store_id": 1, "actor": "someone", "lines": [{"sku_id": bread, "qty": 2, "batch_no": "B-1"}]})
    actors = db.scalars(select(StockLedger.actor).where(StockLedger.store_id == 1, StockLedger.sku_id == bread,
                                                         StockLedger.reference.like("grn:%"))).all()
    assert actors == ["test-receiver", "test-receiver"]       # from the login, not from the request body


def test_a_retried_scan_counts_once(client, db, sku):
    bread = sku("White bread")
    _, receipt = open_truck(client)
    url = f"/v1/goods-receipts/{receipt['receipt_id']}/scans"
    body = {"barcode": db.get(SKU, bread).barcode, "qty": 40, "batch_no": "B-KEY", "expiry_date": in_days(4)}
    first = client.post(url, json=body, headers={"Idempotency-Key": "scan-1"})
    again = client.post(url, json=body, headers={"Idempotency-Key": "scan-1"})
    assert first.json() == again.json()
    assert line_of(client.get(f"/v1/goods-receipts/{receipt['receipt_id']}").json(), bread)["scanned"] == 40
    reused = client.post(url, json={**body, "qty": 1}, headers={"Idempotency-Key": "scan-1"})
    assert reused.status_code == 422 and reused.json()["error"]["code"] == "idempotency_key_reused"


def test_a_retried_one_call_receipt_receives_once(client, sku):
    bread = sku("White bread")
    before = atp(client, 1, bread)
    body = {"store_id": 1, "lines": [{"sku_id": bread, "qty": 10}]}
    first = client.post("/v1/goods-receipts", json=body, headers={"Idempotency-Key": "grn-1"})
    again = client.post("/v1/goods-receipts", json=body, headers={"Idempotency-Key": "grn-1"})
    assert (first.status_code, again.status_code) == (201, 201) and first.json() == again.json()
    assert atp(client, 1, bread) == before + 10
    assert_stock_is_consistent()


def test_only_receivers_and_managers_of_the_store_can_receive(client, client_as, db, sku):
    _, receipt = open_truck(client)
    url = f"/v1/goods-receipts/{receipt['receipt_id']}"
    assert client_as("picker", 1).post("/v1/goods-receipts/open", json={"store_id": 1}).status_code == 403
    assert client_as("receiver", 2).post("/v1/goods-receipts/open", json={"store_id": 1}).status_code == 403
    assert client_as("receiver", 1).post("/v1/goods-receipts/open", json={"store_id": 1}).status_code == 201
    one_bread = {"barcode": db.get(SKU, sku("White bread")).barcode, "qty": 1, "batch_no": "LOT1",
                 "expiry_date": in_days(4)}
    assert client_as("receiver", 2).post(f"{url}/scans", json=one_bread).status_code == 403
    assert client_as("picker", 1).post(f"{url}/cancel").status_code == 403
    assert client_as("receiver", 2).post(f"{url}/cancel").status_code == 403
    assert client_as("manager", 1).post(f"{url}/scans", json=one_bread).status_code == 200
    assert client_as("picker", 2).get(url).status_code == 403
    assert client_as("picker", 1).get(url).status_code == 200


def test_receiving_one_truck_twice_at_once_stocks_it_once(client, db, sku, monkeypatch):
    bread = sku("White bread")
    before = atp(client, 1, bread)
    order = client.post("/v1/replenishment/run", params={"store_id": 1}).json()["transfer_order"]
    lines = [{"sku_id": line["sku_id"], "qty": line["qty_ordered"]} for line in order["lines"]]
    room = slotting.room_in

    def room_slowly(session, bin_):
        time.sleep(0.2)                    # the first receipt is still at work when the second click lands
        return room(session, bin_)

    monkeypatch.setattr(slotting, "room_in", room_slowly)

    def receive(delay):
        time.sleep(delay)
        with SessionLocal() as session:
            try:
                inbound.receive_goods(session, 1, lines, order["transfer_order_id"])
                return "received"
            except DomainError as error:
                return error.code

    with ThreadPoolExecutor(max_workers=2) as pool:      # a double-click on "Receive truck"
        assert sorted(pool.map(receive, [0, 0.1])) == ["already_received", "received"]
    assert atp(client, 1, bread) == before + 40
    assert_stock_is_consistent()


def test_put_away_units_no_longer_count_as_on_their_way(client, db, sku):
    bread, ice_cream = sku("White bread"), sku("Vanilla ice cream")
    _, receipt = open_truck(client)
    scan(client, db, receipt, bread, 40)
    put_all(client, receipt, bread)
    transit = replenishment.in_transit(db, 1)
    assert (transit.get(bread, 0), transit.get(ice_cream, 0)) == (0, 42)    # the bread is on the shelf already


def test_units_left_on_the_dock_can_be_sent_back(client, db, sku):
    bread = sku("White bread")
    before = atp(client, 1, bread)
    _, receipt = open_truck(client)
    scan(client, db, receipt, bread, 400)                       # 400 typed instead of 40
    put_away(client, receipt, bread, "LOT1", "A-01-01", 40)
    assert close(client, receipt).status_code == 409
    body = client.post(f"/v1/goods-receipts/{receipt['receipt_id']}/close", params={"send_back": True}).json()
    [row] = [row for row in body["report"] if row["sku_id"] == bread]
    assert (row["received"], row["sent_back"]) == (40, 360)
    assert (line_of(body, bread)["on_dock"], line_of(body, bread)["sent_back"]) == (0, 360)
    assert client.get(f"/v1/goods-receipts/{receipt['receipt_id']}/putaway-tasks").json() == []   # nothing to do
    assert atp(client, 1, bread) == before + 40                 # the 360 never entered stock
    assert_stock_is_consistent()


def test_a_scan_must_name_its_batch_and_expiry(client, db, sku):
    _, receipt = open_truck(client)
    url = f"/v1/goods-receipts/{receipt['receipt_id']}/scans"
    barcode = db.get(SKU, sku("White bread")).barcode
    assert client.post(url, json={"barcode": barcode, "qty": 5, "batch_no": "LOT1"}).status_code == 422
    assert client.post(url, json={"barcode": barcode, "qty": 5, "expiry_date": in_days(4)}).status_code == 422


def test_an_impossible_quantity_is_refused_and_changes_nothing(client, db, sku):
    """Capped like Inventory's quantities (PR 50). 10**20 does not even fit a database integer: it was a 500."""
    bread = sku("White bread")
    _, receipt = open_truck(client)
    scan(client, db, receipt, bread, 40)
    for qty in (100_001, 10**20):
        assert scan(client, db, receipt, bread, qty).status_code == 422
        assert put_away(client, receipt, bread, "LOT1", "A-01-01", qty).status_code == 422
        one_call = client.post("/v1/goods-receipts", json={"store_id": 1, "lines": [{"sku_id": bread, "qty": qty}]})
        assert one_call.status_code == 422
    line = line_of(client.get(f"/v1/goods-receipts/{receipt['receipt_id']}").json(), bread)
    assert (line["scanned"], line["put_away"]) == (40, 0)
    assert_stock_is_consistent()


def test_an_impossible_id_is_refused_before_any_query(client, db, sku):
    """app/ids.py, as in Inventory (PR 52): a receipt id of 10**20 does not fit a database integer and was a 500."""
    huge = 10**20
    scan_body = {"barcode": db.get(SKU, sku("White bread")).barcode, "qty": 1, "batch_no": "LOT1",
                 "expiry_date": in_days(4)}
    put_body = {"sku_id": 1, "batch_no": "LOT1", "bin_code": "A-01-01", "qty": 1}
    for receipt_id in (0, huge):
        url = f"/v1/goods-receipts/{receipt_id}"
        for method, path, body in (("GET", "", None), ("GET", "/putaway-tasks", None), ("POST", "/scans", scan_body),
                                   ("POST", "/putaway", put_body), ("POST", "/close", None),
                                   ("POST", "/cancel", None)):
            assert client.request(method, url + path, json=body).status_code == 422, (method, url + path)
    for body in ({"store_id": huge}, {"store_id": 1, "transfer_order_id": huge}):
        assert client.post("/v1/goods-receipts/open", json=body).status_code == 422, body
    for body in ({"store_id": huge, "lines": [{"sku_id": 1, "qty": 1}]},
                 {"store_id": 1, "transfer_order_id": huge, "lines": [{"sku_id": 1, "qty": 1}]},
                 {"store_id": 1, "lines": [{"sku_id": huge, "qty": 1}]},
                 {"store_id": 1, "lines": [{"sku_id": 1, "qty": 1, "bin_id": huge}]}):
        assert client.post("/v1/goods-receipts", json=body).status_code == 422, body
    _, receipt = open_truck(client)
    assert put_away(client, receipt, huge, "LOT1", "A-01-01", 1).status_code == 422


def test_two_putaways_of_different_items_never_overfill_a_bin(db, sku, monkeypatch):
    milk, curd = sku("Toned milk"), sku("Curd")
    first_bin = db.scalar(select(Bin).where(Bin.store_id == 1, Bin.code == "C-01-01"))   # holds the 6 old milk
    first_bin.capacity, bin_id = 10, first_bin.id
    db.commit()
    receipts = []
    for item in (milk, curd):
        receipt_id = inbound.open_receipt(db, 1)["receipt_id"]
        inbound.scan(db, receipt_id, db.get(SKU, item).barcode, 4, batch_no="B-BOTH")
        receipts.append((receipt_id, item))
    room = slotting.room_in

    def room_slowly(session, bin_):
        time.sleep(0.3)
        return room(session, bin_)

    monkeypatch.setattr(slotting, "room_in", room_slowly)

    def put(receipt):
        with SessionLocal() as session:
            try:
                inbound.put_away(session, receipt[0], receipt[1], "B-BOTH", "C-01-01", 4)
                return "put"
            except DomainError as error:
                return error.code

    with ThreadPoolExecutor(max_workers=2) as pool:      # on PostgreSQL neither check would see the other's units
        assert sorted(pool.map(put, receipts)) == ["bin_full", "put"]
    assert db.scalar(select(func.sum(StockItem.qty)).where(StockItem.bin_id == bin_id)) == 10
    assert_stock_is_consistent()


def test_an_idempotency_key_belongs_to_whoever_sent_it(client, client_as, db, sku):
    _, receipt = open_truck(client)
    url = f"/v1/goods-receipts/{receipt['receipt_id']}/scans"
    body = {"barcode": db.get(SKU, sku("White bread")).barcode, "qty": 4, "batch_no": "LOT1", "expiry_date": in_days(4)}
    first = client_as("receiver", 1).post(url, json=body, headers={"Idempotency-Key": "k-1"})
    other = client_as("manager", 1).post(url, json=body, headers={"Idempotency-Key": "k-1"})
    assert first.status_code == 200
    assert other.status_code == 422 and other.json()["error"]["code"] == "idempotency_key_reused"


# --------------------------------------------------------------------------- one batch number, one date (review of #71)


def receive_now(client, sku_id: int, qty: int, batch_no: str, expires_in: int):
    """Put a batch on the shelf in store 1 with the one-call receipt."""
    return client.post("/v1/goods-receipts", json={"store_id": 1, "lines": [
        {"sku_id": sku_id, "qty": qty, "batch_no": batch_no, "expiry_date": in_days(expires_in)}]})


def open_receipt(client) -> dict:
    """A receipt in store 1 without a transfer order."""
    opened = client.post("/v1/goods-receipts/open", json={"store_id": 1})
    assert opened.status_code == 201, opened.text
    return opened.json()


def test_a_batch_number_on_the_shelf_with_another_date_is_refused_at_the_scan(client, db, sku):
    """Since #71, putaway refuses a batch number the store already has with another date. The scan accepted it, so the
    line was stuck on the dock and the receipt could close only by sending good units back. Now the scan refuses it,
    while the receiver can still give the case its own number."""
    bread = sku("White bread")                                          # shelf life 4 days
    assert receive_now(client, bread, 5, "LOT1", expires_in=3).status_code == 201
    receipt = open_receipt(client)
    refused = scan(client, db, receipt, bread, 4)                       # LOT1 again, expiring in 4 days
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "batch_expiry_mismatch"
    assert refused.json()["error"]["details"] == {"batch_no": "LOT1", "expiry_date": in_days(3)}
    assert client.get(f"/v1/goods-receipts/{receipt['receipt_id']}").json()["lines"] == []    # nothing recorded
    same_date = scan(client, db, receipt, bread, 2, expiry_date=in_days(3))     # the shelf's date: a normal top-up
    own_number = scan(client, db, receipt, bread, 4, batch_no="LOT2")
    assert (same_date.status_code, own_number.status_code) == (200, 200)
    put_all(client, receipt, bread)
    assert close(client, receipt).status_code == 200
    assert_stock_is_consistent()


def test_damaged_units_are_recorded_whatever_their_batch_number(client, db, sku):
    """Units that never reach the shelf cannot clash with it."""
    bread = sku("White bread")
    assert receive_now(client, bread, 5, "LOT1", expires_in=3).status_code == 201
    body = scan(client, db, open_receipt(client), bread, 2, damaged=True)      # LOT1, expiring in 4 days
    assert body.status_code == 200 and body.json()["scan"]["outcome"] == "damaged"


def test_a_batch_number_on_another_open_receipts_dock_with_another_date_is_refused(client, db, sku):
    """Two receipts open at once: the second line put away would be refused, so its scan is refused instead. Only an
    open receipt's dock counts."""
    bread = sku("White bread")
    first, second = open_receipt(client), open_receipt(client)
    assert scan(client, db, first, bread, 5, expiry_date=in_days(3)).status_code == 200
    refused = scan(client, db, second, bread, 4)                        # LOT1, expiring in 4 days
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "batch_expiry_mismatch"
    assert refused.json()["error"]["details"] == {"batch_no": "LOT1", "expiry_date": in_days(3),
                                                  "receipt_id": first["receipt_id"]}
    assert client.post(f"/v1/goods-receipts/{first['receipt_id']}/cancel").status_code == 200
    assert scan(client, db, second, bread, 4).status_code == 200        # nothing waits on the first dock now


def test_a_line_whose_batch_number_reached_the_shelf_with_another_date_gets_no_bin(client, db, sku):
    """If the shelf gets the number with another date after the scan (two receipts scanning it at the same moment),
    putaway would refuse the line. Its task says so instead of naming a bin, and the line can still be sent back."""
    bread = sku("White bread")
    receipt = open_receipt(client)
    assert scan(client, db, receipt, bread, 4).status_code == 200       # LOT1, expiring in 4 days
    inventory.receive(db, 1, bread, 5, slotting.suggest_bin(db, 1, bread).id, "LOT1",
                      clock.today() + timedelta(days=3))
    db.commit()
    [task] = tasks_for(client, receipt, bread)
    assert (task["bin_code"], task["qty"]) == (None, 4) and "send_back" in task["problem"]
    sent = client.post(f"/v1/goods-receipts/{receipt['receipt_id']}/close", params={"send_back": True})
    assert sent.status_code == 200 and line_of(sent.json(), bread)["sent_back"] == 4
    assert_stock_is_consistent()


def test_a_one_call_receipt_with_a_clashing_batch_number_keeps_nothing(client, sku):
    bread = sku("White bread")
    assert receive_now(client, bread, 5, "LOT1", expires_in=3).status_code == 201
    before = atp(client, 1, bread)
    refused = receive_now(client, bread, 4, "LOT1", expires_in=4)
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "batch_expiry_mismatch"
    assert atp(client, 1, bread) == before
    assert_stock_is_consistent()


def _count_sales_reads(monkeypatch) -> list:
    """Record each time slotting works out sales speeds (two weeks of the ledger) to choose home bins."""
    reads, velocity = [], slotting.velocity
    monkeypatch.setattr(slotting, "velocity", lambda *args, **kwargs: reads.append(args) or velocity(*args, **kwargs))
    return reads


def test_putaway_tasks_read_the_sales_once_for_the_whole_truck(client, db, sku, monkeypatch):
    """The home bins come from the last two weeks of sales. They are worked out once per request, not again for
    every line on the dock (a 15-line truck read the same sales 15 times)."""
    lines = [sku("White bread"), sku("Toned milk"), sku("Vanilla ice cream")]
    opened = client.post("/v1/goods-receipts/open", json={"store_id": 1}).json()
    for sku_id in lines:
        assert scan(client, db, opened, sku_id, 2).status_code == 200
    reads = _count_sales_reads(monkeypatch)
    tasks = client.get(f"/v1/goods-receipts/{opened['receipt_id']}/putaway-tasks").json()
    assert {task["sku_id"] for task in tasks} == set(lines) and all(task["bin_code"] for task in tasks)
    assert len(reads) == 1


def test_a_one_call_receipt_reads_the_sales_once(client, sku, monkeypatch):
    reads = _count_sales_reads(monkeypatch)
    received = client.post("/v1/goods-receipts", json={"store_id": 1, "lines": [
        {"sku_id": sku(name), "qty": 2} for name in ("White bread", "Toned milk", "Vanilla ice cream")]})
    assert received.status_code == 201, received.text
    assert len(received.json()["received"]) >= 3
    assert len(reads) == 1
