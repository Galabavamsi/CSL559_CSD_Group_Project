"""Two-step receiving (guide task 3.5): open a receipt, scan the truck onto the dock, put each line away, close."""
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

from sqlalchemy import func, select, update

from app.db import SessionLocal
from app.errors import DomainError
from app.models import SKU, Bin, StockItem
from app.modules.inbound import service as inbound
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
    return client.post(f"/v1/goods-receipts/{receipt['receipt_id']}/scans",
                       json={"barcode": db.get(SKU, sku_id).barcode, "qty": qty, **details})


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
    again = client.post("/v1/goods-receipts/open", json={"store_id": 1, "transfer_order_id": order["transfer_order_id"]})
    assert again.status_code == 409 and again.json()["error"]["code"] == "receipt_open"
    elsewhere = client.post("/v1/goods-receipts/open",
                            json={"store_id": 2, "transfer_order_id": order["transfer_order_id"]})
    assert elsewhere.status_code == 404
    unknown = client.post(f"/v1/goods-receipts/{receipt['receipt_id']}/scans", json={"barcode": "0000", "qty": 1})
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
