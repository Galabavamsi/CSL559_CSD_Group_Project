"""Two-step receiving (guide task 3.5): open a receipt, scan the truck onto the dock, put each line away, close."""
from datetime import date, timedelta

from app.models import SKU

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
