"""A batch that expires while one of its lines is being picked (found in the review of #28).

Before the fix, the empty-shelf write-off also took the units already in the picker's tote, and packing failed with
409 stock_mismatch. Now the write-off leaves tote units alone, and a scan of the expired batch is refused, so the
picker reports the rest Not on shelf and it is picked from a fresh batch.
Store 1 has 6 milk in batch M-OLD (expires tomorrow) and 24 in M-NEW."""
from datetime import timedelta

from sqlalchemy import select

from app import clock
from app.models import StockItem, StockLedger
from app.modules.inventory import service as inventory

from .conftest import assert_stock_is_consistent, place_paid_order
from .test_order_flow import next_job, scan_all


def expire_m_old(db) -> int:
    """M-OLD expired at midnight and the hourly write-off has run. Returns the units it wrote off."""
    db.scalar(select(StockItem).where(StockItem.batch_no == "M-OLD")).expiry_date = clock.today() - timedelta(days=1)
    db.commit()
    return inventory.expire_stock(db)


def milk_level(client) -> tuple[int, int]:
    row = client.get("/v1/stores/1/availability", params={"skus": "1"}).json()[0]
    return row["on_hand"], row["reserved"]


def half_scanned_old_milk(client, sku) -> tuple[dict, dict]:
    """A paid order of 6 milk, all from M-OLD, with 3 already scanned into the tote."""
    assert sku("Toned milk") == 1
    place_paid_order(client, "x-1", 1, [(1, 6)])
    job = next_job(client)
    [line] = job["tasks"]
    assert (line["batch_no"], line["qty"]) == ("M-OLD", 6)
    client.post(f"/v1/pick-tasks/{line['task_id']}/scans", json={"barcode": line["barcode"], "qty": 3})
    return job, line


def test_after_an_expiry_write_off_the_order_is_still_packed(client, db, sku):
    job, line = half_scanned_old_milk(client, sku)
    assert expire_m_old(db) == 3                                    # only the 3 still on the shelf

    short = client.post(f"/v1/pick-tasks/{line['task_id']}/short").json()   # the 3 scanned were found

    assert (short["picked"], short["reallocated"], short["dropped"]) == (3, 3, 0)
    assert not db.scalars(select(StockLedger).where(StockLedger.reason == "not_found")).all()   # nothing more taken
    scan_all(client, short["job"])
    packed = client.post(f"/v1/fulfilment-jobs/{job['job_id']}/packed", json={"crate_slot": "S-01"})
    assert packed.status_code == 200, packed.text
    assert milk_level(client) == (21, 0)                            # 30 - 3 expired - 6 sold
    assert_stock_is_consistent()


def test_the_rest_of_an_expired_batch_cannot_be_scanned(client, db, sku):
    job, line = half_scanned_old_milk(client, sku)
    expire_m_old(db)

    res = client.post(f"/v1/pick-tasks/{line['task_id']}/scans", json={"barcode": line["barcode"], "qty": 3}).json()

    assert res["match"] is False and "expired" in res["message"] and "Not on shelf" in res["message"]
    now = client.get(f"/v1/fulfilment-jobs/{job['job_id']}").json()["tasks"][0]
    assert (now["scanned_qty"], now["status"]) == (3, "pending")
    assert_stock_is_consistent()


def test_an_expired_batch_the_hourly_job_has_not_reached_is_refused_too(client, db, sku):
    """Expired at midnight, written off at the next hourly run: in between it is still in the books."""
    place_paid_order(client, "x-2", 1, [(sku("Toned milk"), 2)])
    job = next_job(client)
    [line] = job["tasks"]
    db.scalar(select(StockItem).where(StockItem.batch_no == "M-OLD")).expiry_date = clock.today() - timedelta(days=1)
    db.commit()

    scan = client.post(f"/v1/pick-tasks/{line['task_id']}/scans", json={"barcode": line["barcode"], "qty": 2}).json()
    short = client.post(f"/v1/pick-tasks/{line['task_id']}/short").json()

    assert scan["match"] is False
    assert (short["reallocated"], short["dropped"]) == (2, 0)              # moved to the fresh batch
    scan_all(client, short["job"])
    assert client.post(f"/v1/fulfilment-jobs/{job['job_id']}/packed",
                       json={"crate_slot": "S-01"}).json()["state"] == "packed"
    assert_stock_is_consistent()
