"""Cancel after payment (Member 2 guide, task 2.3): a paid order can be cancelled until it is packed.

Nothing leaves on-hand stock before packing, so a cancel only gives holds back. Every test ends with the stock audit."""
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.db import SessionLocal
from app.errors import DomainError
from app.models import PickTask
from app.modules.fulfilment import service as fulfilment
from app.modules.pickpack import service as pickpack

from .conftest import assert_stock_is_consistent, atp, place_paid_order
from .test_order_flow import next_job, scan_all

REASON = "Customer changed their mind"


def job_of(client, order_id: str, store_id: int = 1) -> dict:
    return next(j for j in client.get("/v1/fulfilment-jobs", params={"store_id": store_id}).json()
                if j["order_id"] == order_id)


def cancel(client, job_id: int, reason: str = REASON):
    return client.post(f"/v1/fulfilment-jobs/{job_id}/cancel", json={"reason": reason})


def stock(client, sku_id: int, store_id: int = 1) -> tuple[int, int]:
    row = client.get(f"/v1/stores/{store_id}/availability", params={"skus": str(sku_id)}).json()[0]
    return row["on_hand"], row["reserved"]


def events_of(client, event_type: str) -> list[dict]:
    return [e for e in client.get("/v1/events", params={"limit": 200}).json() if e["type"] == event_type]


def test_cancel_before_a_picker_claims_it_gives_the_stock_back(client, sku):
    rice, tea = sku("Basmati rice"), sku("Tea")
    before = atp(client, 1, rice), atp(client, 1, tea)
    paid = place_paid_order(client, "c-1", 1, [(rice, 2), (tea, 1)])
    job = job_of(client, "c-1")
    assert job["state"] == "created"

    res = cancel(client, job["job_id"])

    assert res.status_code == 200, res.text
    assert res.json()["state"] == "cancelled"
    assert {t["status"] for t in res.json()["tasks"]} == {"cancelled"}
    assert (atp(client, 1, rice), atp(client, 1, tea)) == before
    assert client.get(f"/v1/reservations/{paid['reservation_id']}").json()["status"] == "cancelled"
    [event] = events_of(client, "order.cancelled")
    assert event["payload"] == {"order_id": "c-1", "job_id": job["job_id"], "reason": REASON,
                                "refund_amount": 2 * 140 + 130}                 # rice Rs 140, tea Rs 130
    assert {"job_id": job["job_id"], "order_id": "c-1", "state": "cancelled"} in [
        e["payload"] for e in events_of(client, "fulfilment.state_changed")]
    # Paying again cannot bring the order back, and releasing the hold again is safe and changes nothing.
    assert client.post(f"/v1/reservations/{paid['reservation_id']}/confirm").status_code == 409
    again = client.delete(f"/v1/reservations/{paid['reservation_id']}")
    assert again.status_code == 200 and again.json()["status"] == "cancelled"
    assert (atp(client, 1, rice), atp(client, 1, tea)) == before
    assert next_job(client) is None
    assert_stock_is_consistent()


def test_cancel_mid_pick_gives_back_the_scanned_line_and_the_pending_one(client, sku):
    rice, tea = sku("Basmati rice"), sku("Tea")
    before = atp(client, 1, rice), atp(client, 1, tea)
    on_hand_before = stock(client, rice)[0], stock(client, tea)[0]
    place_paid_order(client, "c-2", 1, [(rice, 2), (tea, 1)])
    job = next_job(client)
    scanned, pending = job["tasks"]
    assert client.post(f"/v1/pick-tasks/{scanned['task_id']}/scans",
                       json={"barcode": scanned["barcode"], "qty": scanned["qty"]}).json()["match"] is True

    assert cancel(client, job["job_id"]).status_code == 200

    assert (atp(client, 1, rice), atp(client, 1, tea)) == before
    assert (stock(client, rice)[0], stock(client, tea)[0]) == on_hand_before    # the tote goes back on the shelf
    # The picker's handheld finds out on its next call; the station explains it.
    late_scan = client.post(f"/v1/pick-tasks/{pending['task_id']}/scans",
                            json={"barcode": pending["barcode"], "qty": pending["qty"]})
    assert late_scan.status_code == 409 and late_scan.json()["error"]["code"] == "job_not_picking"
    late_pack = client.post(f"/v1/fulfilment-jobs/{job['job_id']}/packed", json={"crate_slot": "S-01"})
    assert late_pack.status_code == 409 and late_pack.json()["error"]["code"] == "job_not_picking"
    assert client.post(f"/v1/pick-tasks/{pending['task_id']}/short").status_code == 409
    assert_stock_is_consistent()


def test_cancel_after_lines_were_moved_or_dropped_gives_back_only_what_is_still_held(client, sku):
    """A `reallocated` line was replaced by new lines and a `short` line already gave its hold back:
    giving those back again would release someone else's hold."""
    milk, ice_cream = sku("Toned milk"), sku("Vanilla ice cream")
    place_paid_order(client, "c-3", 1, [(milk, 8), (ice_cream, 1)])
    job = next_job(client)
    old_milk = next(t for t in job["tasks"] if t["batch_no"] == "M-OLD")
    ice = next(t for t in job["tasks"] if t["sku_id"] == ice_cream)
    assert client.post(f"/v1/pick-tasks/{old_milk['task_id']}/short").json()["reallocated"] == 6
    assert client.post(f"/v1/pick-tasks/{ice['task_id']}/short").json()["dropped"] == 1

    statuses = [t["status"] for t in cancel(client, job["job_id"]).json()["tasks"]]

    assert sorted(statuses) == ["cancelled", "cancelled", "reallocated", "short"]
    assert stock(client, milk) == (24, 0)                  # 30 - 6 written off; nothing held any more
    assert stock(client, ice_cream) == (0, 0)              # not -1
    assert_stock_is_consistent()


@pytest.mark.parametrize("handed_over", [False, True])
def test_a_packed_order_cannot_be_cancelled(client, sku, handed_over):
    rice = sku("Basmati rice")
    place_paid_order(client, "c-4", 1, [(rice, 2)])
    job = next_job(client)
    scan_all(client, job)
    packed = client.post(f"/v1/fulfilment-jobs/{job['job_id']}/packed", json={"crate_slot": "S-01"}).json()
    if handed_over:
        client.post(f"/v1/fulfilment-jobs/{job['job_id']}/handover",
                    json={"rider_id": packed["rider"]["rider_id"], "scanned_order_id": "c-4"})

    res = cancel(client, job["job_id"])

    assert res.status_code == 409 and res.json()["error"]["code"] == "too_late"
    assert "return" in res.json()["error"]["message"]
    assert client.get(f"/v1/fulfilment-jobs/{job['job_id']}").json()["state"] == (
        "handed_over" if handed_over else "packed")
    assert stock(client, rice) == (28, 0)
    assert events_of(client, "order.cancelled") == []
    assert_stock_is_consistent()


def test_cancelling_twice_is_safe(client, sku):
    rice = sku("Basmati rice")
    place_paid_order(client, "c-5", 1, [(rice, 2)])
    job_id = job_of(client, "c-5")["job_id"]

    first, again = cancel(client, job_id), cancel(client, job_id)

    assert (first.status_code, again.status_code) == (200, 200)
    assert again.json()["state"] == "cancelled"
    assert stock(client, rice) == (30, 0)
    assert len(events_of(client, "order.cancelled")) == 1
    assert_stock_is_consistent()


def test_five_cancels_at_once_give_the_holds_back_once(client, sku):
    """Every thread reads the order as `created` first and only then cancels, so they really race.
    Another customer's unpaid hold on the same item must survive: giving back twice would eat into it."""
    rice = sku("Basmati rice")
    other = client.post("/v1/reservations", json={"order_id": "someone-else", "store_id": 1,
                                                   "lines": [{"sku_id": rice, "qty": 3}]})
    assert other.status_code == 201
    place_paid_order(client, "c-6", 1, [(rice, 2)])
    job_id = job_of(client, "c-6")["job_id"]
    everyone_has_read = threading.Barrier(5)

    def cancel_it(_n: int) -> str:
        with SessionLocal() as session:
            assert fulfilment.get_job(session, job_id).state == "created"
            everyone_has_read.wait()
            return fulfilment.cancel(session, job_id, REASON).state

    with ThreadPoolExecutor(max_workers=5) as pool:
        assert set(pool.map(cancel_it, range(5))) == {"cancelled"}
    assert stock(client, rice) == (30, 3)                  # only the other customer's hold is left
    assert len(events_of(client, "order.cancelled")) == 1
    assert_stock_is_consistent()


def test_a_pack_that_read_the_order_before_it_was_cancelled_sells_nothing(client, sku):
    """The packer's screen shows every line picked; the customer cancels; then the packer presses Pack.
    Selling the units and giving their hold back must never both happen."""
    rice = sku("Basmati rice")
    place_paid_order(client, "c-7", 1, [(rice, 2)])
    job = next_job(client)
    scan_all(client, job)
    with SessionLocal() as packer:
        stale = fulfilment.get_job(packer, job["job_id"])
        assert [t.status for t in stale.tasks] == ["picked"]

        assert cancel(client, job["job_id"]).status_code == 200

        with pytest.raises(DomainError) as refused:
            pickpack.pack(packer, job["job_id"], "S-01")
        assert refused.value.code == "job_not_picking"
    assert stock(client, rice) == (30, 0)
    assert_stock_is_consistent()


def test_an_empty_shelf_report_that_read_the_order_before_it_was_cancelled_changes_nothing(client, sku):
    ice_cream = sku("Vanilla ice cream")
    place_paid_order(client, "c-8", 1, [(ice_cream, 1)])
    job = next_job(client)
    with SessionLocal() as handheld:
        task = handheld.get(PickTask, job["tasks"][0]["task_id"])
        stale = fulfilment.get_job(handheld, job["job_id"])    # kept, so the session keeps this copy of the order
        assert (task.status, stale.state) == ("pending", "picking")

        assert cancel(client, job["job_id"]).status_code == 200

        with pytest.raises(DomainError) as refused:
            pickpack.report_short(handheld, task.id)
        assert refused.value.code == "job_not_picking"
    assert stock(client, ice_cream) == (1, 0)              # no write-off, and the hold was given back once
    assert_stock_is_consistent()


def test_cancelling_brings_a_busy_store_back_to_open(client, sku):
    rice = sku("Basmati rice")
    home = {"lat": 12.975, "lng": 77.60}
    for n in range(6):                                     # threshold is 5 waiting orders
        place_paid_order(client, f"busy-{n}", 1, [(rice, 1)])
    assert client.get("/v1/serviceability", params=home).json()["status"] == "busy"

    cancel(client, job_of(client, "busy-0")["job_id"])

    assert client.get("/v1/serviceability", params=home).json()["status"] == "open"
    assert_stock_is_consistent()


def test_only_the_stores_manager_may_cancel(client, client_as, sku):
    place_paid_order(client, "c-9", 1, [(sku("Basmati rice"), 1)])
    job_id = job_of(client, "c-9")["job_id"]

    assert cancel(client_as("picker", 1), job_id).status_code == 403
    assert cancel(client_as("manager", 2), job_id).status_code == 403
    assert cancel(client_as("manager", 1), job_id, reason="").status_code == 422
    assert cancel(client_as("manager", 1), job_id).status_code == 200
    assert cancel(client_as("manager", 1), 999_999).status_code == 404
    assert_stock_is_consistent()


def test_a_scan_and_a_cancel_at_the_same_moment_leave_the_stock_right(client, sku):
    """Both read the order as being picked first, then act at once. Whichever wins, the hold is given back once
    and nothing is sold."""
    rice = sku("Basmati rice")
    place_paid_order(client, "c-10", 1, [(rice, 2)])
    job = next_job(client)
    task = job["tasks"][0]
    both_have_read = threading.Barrier(2)

    def scan_it():
        with SessionLocal() as session:
            assert session.get(PickTask, task["task_id"]).status == "pending"
            both_have_read.wait()
            try:
                return pickpack.scan(session, task["task_id"], task["barcode"], 2)["match"]
            except DomainError as refused:
                return refused.code

    def cancel_it():
        with SessionLocal() as session:
            assert fulfilment.get_job(session, job["job_id"]).state == "picking"
            both_have_read.wait()
            return fulfilment.cancel(session, job["job_id"], REASON).state

    with ThreadPoolExecutor(max_workers=2) as pool:
        scanned, cancelled = pool.submit(scan_it), pool.submit(cancel_it)
        assert scanned.result() in (True, "job_not_picking")      # before the cancel, or refused after it
        assert cancelled.result() == "cancelled"
    assert stock(client, rice) == (30, 0)
    assert_stock_is_consistent()
