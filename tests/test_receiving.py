"""Two-step receiving (guide task 3.5): open a receipt, scan the truck onto the dock, put each line away, close."""
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

from sqlalchemy import func, select, update

from app.db import SessionLocal
from app.errors import DomainError
from app.models import SKU, Bin, StockItem, StockLedger
from app.modules.inbound import service as inbound
from app.modules.replenishment import service as replenishment
from app.modules.slotting import service as slotting

from .conftest import assert_stock_is_consistent, atp


def in_days(n: int) -> str:
    return (date.today() + timedelta(days=n)).isoformat()


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
    assert atp(client, 1, bread) == before + 40                 # the 360 never entered stock
    assert_stock_is_consistent()


def test_a_scan_must_name_its_batch_and_expiry(client, db, sku):
    _, receipt = open_truck(client)
    url = f"/v1/goods-receipts/{receipt['receipt_id']}/scans"
    barcode = db.get(SKU, sku("White bread")).barcode
    assert client.post(url, json={"barcode": barcode, "qty": 5, "batch_no": "LOT1"}).status_code == 422
    assert client.post(url, json={"barcode": barcode, "qty": 5, "expiry_date": in_days(4)}).status_code == 422


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
