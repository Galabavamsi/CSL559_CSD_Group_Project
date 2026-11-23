"""Expiry handling (FR-10, task 1.3): never pick or sell an expired batch, write it off, flag what is about to expire.

Store 1 has 6 milk in batch M-OLD (expires tomorrow) and 24 in batch M-NEW (expires later)."""
from datetime import date, timedelta

from sqlalchemy import select

from app import background, clock
from app.models import EventLog, StockItem, StockLedger
from app.modules.inventory import service as inventory

from .conftest import assert_stock_is_consistent, atp, place_paid_order
from .test_order_flow import next_job, scan_all


def _set_expiry(db, batch_no: str, expiry: date) -> StockItem:
    item = db.scalar(select(StockItem).where(StockItem.store_id == 1, StockItem.batch_no == batch_no))
    item.expiry_date = expiry
    db.commit()
    return item


def yesterday() -> date:
    return clock.today() - timedelta(days=1)


def test_expired_batch_is_never_picked(client, db, sku):
    _set_expiry(db, "M-OLD", yesterday())                       # the hourly write-off has not run yet
    place_paid_order(client, "order-1", 1, [(sku("Toned milk"), 8)])
    tasks = next_job(client)["tasks"]
    assert [(t["batch_no"], t["qty"]) for t in tasks] == [("M-NEW", 8)]


def test_expire_stock_writes_off_the_expired_batch(client, db, sku):
    milk = sku("Toned milk")
    old = _set_expiry(db, "M-OLD", yesterday())
    assert client.post("/v1/admin/expire-stock").json() == {"units_written_off": 6}

    rows = db.scalars(select(StockLedger).where(StockLedger.sku_id == milk, StockLedger.reason == "expiry")).all()
    assert [(r.delta, r.bin_id, r.reference) for r in rows] == [(-6, old.bin_id, "batch:M-OLD")]
    assert atp(client, 1, milk) == 22                                    # 24 left, less the seeded buffer of 2
    assert client.post("/v1/admin/expire-stock").json() == {"units_written_off": 0}   # nothing left the second time
    causes = [e.payload["cause"] for e in db.scalars(select(EventLog).where(EventLog.type == "stock.changed"))]
    assert causes == ["expiry"]
    assert_stock_is_consistent()


def test_expire_stock_for_one_store_only(client, db, sku):
    _set_expiry(db, "M-OLD", yesterday())
    assert client.post("/v1/admin/expire-stock", params={"store_id": 2}).json() == {"units_written_off": 0}
    assert client.post("/v1/admin/expire-stock", params={"store_id": 1}).json() == {"units_written_off": 6}


def test_units_already_in_a_tote_are_not_written_off(client, db, sku):
    """The picker scanned the 6 M-OLD units into a tote before midnight; the order is packed after."""
    milk = sku("Toned milk")
    place_paid_order(client, "order-1", 1, [(milk, 8)])
    job = next_job(client)
    scan_all(client, job)
    _set_expiry(db, "M-OLD", yesterday())
    assert inventory.expire_stock(db) == 0
    packed = client.post(f"/v1/fulfilment-jobs/{job['job_id']}/packed", json={"crate_slot": "S-01"})
    assert packed.status_code == 200, packed.text
    assert atp(client, 1, milk) == 20                                    # 22 left, less the seeded buffer of 2
    assert_stock_is_consistent()


def test_expired_units_held_by_a_paid_order_are_settled_by_the_picker(client, db, sku):
    """The trade-off: the write-off does not cancel orders. For a moment the order holds more than is on hand;
    when the picker reports the M-OLD line empty, the line is cut to what is left and the extra hold is freed."""
    milk = sku("Toned milk")
    place_paid_order(client, "order-1", 1, [(milk, 28)])
    job = next_job(client)
    _set_expiry(db, "M-OLD", yesterday())
    assert inventory.expire_stock(db) == 6
    row = client.get("/v1/stores/1/availability", params={"skus": str(milk)}).json()[0]
    assert (row["on_hand"], row["reserved"]) == (24, 28)
    assert_stock_is_consistent(holds_may_exceed_stock=True)

    old_line = next(t for t in job["tasks"] if t["batch_no"] == "M-OLD")
    result = client.post(f"/v1/pick-tasks/{old_line['task_id']}/short").json()
    assert (result["reallocated"], result["dropped"]) == (2, 4)            # M-NEW had only 2 units not promised
    scan_all(client, result["job"])
    client.post(f"/v1/fulfilment-jobs/{job['job_id']}/packed", json={"crate_slot": "S-01"})
    row = client.get("/v1/stores/1/availability", params={"skus": str(milk)}).json()[0]
    assert (row["on_hand"], row["reserved"]) == (0, 0)                     # 24 sold, nothing held
    assert_stock_is_consistent()


def test_near_expiry_report(client, sku):
    rows = client.get("/v1/stores/1/near-expiry", params={"days": 2}).json()
    old = next(r for r in rows if r["batch_no"] == "M-OLD")
    assert (old["sku_id"], old["qty"], old["days_left"], old["bin"]) == (sku("Toned milk"), 6, 1, "C-01-01")
    assert [r["days_left"] for r in rows] == sorted(r["days_left"] for r in rows)
    assert all(r["batch_no"] != "M-OLD" for r in client.get("/v1/stores/1/near-expiry", params={"days": 0}).json())


def test_near_expiry_is_flagged_once_per_batch_per_day(client, db):
    first = inventory.flag_near_expiry(db, days=2)
    assert first >= 1
    assert inventory.flag_near_expiry(db, days=2) == 0
    flagged = [e.payload["batch_no"] for e in db.scalars(select(EventLog).where(EventLog.type == "item.near_expiry"))]
    assert "M-OLD" in flagged and len(flagged) == first


def test_hourly_job_does_both(client, db, sku):
    _set_expiry(db, "M-OLD", yesterday())
    result = background.expiry_once()
    assert result["units_written_off"] == 6
    assert background.expiry_once()["units_written_off"] == 0
    assert_stock_is_consistent()


def test_expiry_endpoints_need_the_right_staff(client_as):
    with client_as("manager", 1) as manager:
        assert manager.post("/v1/admin/expire-stock").status_code == 403
        assert manager.get("/v1/stores/1/near-expiry").status_code == 200
    with client_as("picker", 2) as other_store:
        assert other_store.get("/v1/stores/1/near-expiry").status_code == 403
