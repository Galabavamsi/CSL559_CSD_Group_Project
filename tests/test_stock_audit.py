"""Stock audit (Member 1 guide, task 1.8): the three records of stock are compared, and each disagreement is named.

The tests break the records on purpose with direct writes, which only a test may do."""
from sqlalchemy import update

from app.models import StockItem, StockLedger, StockLevel
from app.modules.inventory import service as inventory

from .conftest import place_paid_order


def test_the_demo_data_and_a_full_order_leave_nothing_to_report(client, sku):
    rice = sku("Basmati rice")
    job = place_paid_order(client, "audit-1", 1, [(rice, 2)])
    client.post("/v1/stock-adjustments", json={"store_id": 1, "sku_id": rice, "delta": -3, "reason": "damage"})

    assert job["status"] == "confirmed"
    assert client.get("/v1/admin/stock-audit").json() == {"consistent": True, "mismatches": []}


def test_a_level_that_disagrees_with_its_bins_and_ledger_is_reported_with_the_values(client, db, sku):
    rice = sku("Basmati rice")
    db.execute(update(StockLevel).where(StockLevel.store_id == 1, StockLevel.sku_id == rice).values(qty_on_hand=33))
    db.commit()

    report = client.get("/v1/admin/stock-audit").json()

    assert report["consistent"] is False
    assert report["mismatches"] == [{"store_id": 1, "sku_id": rice, "on_hand": 33, "in_bins": 30, "in_ledger": 30,
                                     "reserved": 0, "problems": ["on_hand_vs_bins", "on_hand_vs_ledger"]}]


def test_units_taken_from_a_bin_without_a_ledger_row_are_reported(db, sku):
    rice = sku("Basmati rice")
    db.execute(update(StockItem).where(StockItem.store_id == 1, StockItem.sku_id == rice)
               .values(qty=StockItem.qty - 1))
    db.execute(update(StockLevel).where(StockLevel.store_id == 1, StockLevel.sku_id == rice)
               .values(qty_on_hand=StockLevel.qty_on_hand - 1))
    db.commit()

    assert [(row["sku_id"], row["problems"]) for row in inventory.audit(db)] == [(rice, ["on_hand_vs_ledger"])]


def test_holds_below_zero_or_above_the_stock_are_reported(db, sku):
    rice, sugar = sku("Basmati rice"), sku("Sugar")
    db.execute(update(StockLevel).where(StockLevel.store_id == 1, StockLevel.sku_id == rice).values(qty_reserved=-1))
    db.execute(update(StockLevel).where(StockLevel.store_id == 1, StockLevel.sku_id == sugar).values(qty_reserved=31))
    db.commit()

    assert {row["sku_id"]: row["problems"] for row in inventory.audit(db)} == {
        rice: ["negative_reserved"], sugar: ["reserved_over_on_hand"]}


def test_a_ledger_row_for_a_sku_the_store_does_not_stock_is_reported(db):
    db.add(StockLedger(store_id=1, sku_id=999, bin_id=None, delta=5, reason="receipt", actor="test"))
    db.commit()

    assert inventory.audit(db) == [{"store_id": 1, "sku_id": 999, "on_hand": 0, "in_bins": 0, "in_ledger": 5,
                                    "reserved": 0, "problems": ["on_hand_vs_ledger"]}]


def test_one_store_can_be_audited_alone_and_only_an_admin_may_ask(client, client_as, db, sku):
    rice = sku("Basmati rice")
    db.execute(update(StockLevel).where(StockLevel.store_id == 2, StockLevel.sku_id == rice).values(qty_on_hand=1))
    db.commit()

    assert client.get("/v1/admin/stock-audit", params={"store_id": 1}).json()["consistent"] is True
    assert client.get("/v1/admin/stock-audit", params={"store_id": 2}).json()["consistent"] is False
    assert client.get("/v1/admin/stock-audit", params={"store_id": 99}).status_code == 404
    assert client_as("manager", 1).get("/v1/admin/stock-audit").status_code == 403
