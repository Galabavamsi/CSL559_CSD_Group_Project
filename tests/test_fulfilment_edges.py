"""Edge cases and races in fulfilment and pick & pack that the feature tests do not reach.

Each test names the promise it checks: events delivered twice change nothing, retries are safe, and a request that
read an order just before someone else changed it never acts on the stale copy."""
import threading
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import select

from app import events
from app.db import SessionLocal
from app.models import FulfilmentJob, RiderAssignment, Store
from app.modules.fulfilment import riders
from app.modules.fulfilment import service as fulfilment
from app.modules.pickpack import service as pickpack

from .conftest import assert_stock_is_consistent, place_paid_order
from .test_order_flow import next_job, scan_all


def stock(client, sku_id: int) -> tuple[int, int]:
    row = client.get("/v1/stores/1/availability", params={"skus": str(sku_id)}).json()[0]
    return row["on_hand"], row["reserved"]


def picked_and_packed(client, sku, order_id: str = "e-1") -> dict:
    place_paid_order(client, order_id, 1, [(sku("Basmati rice"), 1)])
    job = next_job(client)
    scan_all(client, job)
    return client.post(f"/v1/fulfilment-jobs/{job['job_id']}/packed", json={"crate_slot": "S-01"}).json()


# --------------------------------------------------------------------------- events delivered more than once

def test_order_paid_delivered_twice_still_makes_one_job(client, db, sku):
    """The outbox delivers at least once: a second order.paid must not create a second job."""
    paid = place_paid_order(client, "e-1", 1, [(sku("Tea"), 1)])

    events.publish(db, "order.paid", 1, {"order_id": "e-1", "reservation_id": paid["reservation_id"]})
    events.publish(db, "order.paid", 1, {"order_id": "ghost", "reservation_id": "no-such-reservation"})   # ignored
    db.commit()

    jobs = client.get("/v1/fulfilment-jobs", params={"store_id": 1}).json()
    assert [j["order_id"] for j in jobs] == ["e-1"]
    assert_stock_is_consistent()


def test_ready_for_pickup_delivered_twice_keeps_one_rider(client, db, sku):
    packed = picked_and_packed(client, sku)
    payload = {"job_id": packed["job_id"], "order_id": "e-1", "crate_slot": "S-01"}

    events.publish(db, "order.ready_for_pickup", 1, payload)
    events.publish(db, "order.ready_for_pickup", 1, {**payload, "job_id": 999_999})                 # no such job
    db.commit()

    assigned = db.scalars(select(RiderAssignment).where(RiderAssignment.job_id == packed["job_id"])).all()
    assert [a.rider_id for a in assigned] == [packed["rider"]["rider_id"]]


# --------------------------------------------------------------------------- retries and stale reads

def test_packing_twice_sells_once(client, sku):
    rice = sku("Basmati rice")
    place_paid_order(client, "e-2", 1, [(rice, 2)])
    job = next_job(client)
    scan_all(client, job)

    first = client.post(f"/v1/fulfilment-jobs/{job['job_id']}/packed", json={"crate_slot": "S-01"})
    again = client.post(f"/v1/fulfilment-jobs/{job['job_id']}/packed", json={"crate_slot": "S-01"})

    assert (first.status_code, again.status_code) == (200, 200)
    assert again.json()["state"] == "packed"
    assert stock(client, rice) == (28, 0)
    assert_stock_is_consistent()


def test_a_pack_that_read_the_order_before_another_pack_sells_once(client, sku):
    rice = sku("Basmati rice")
    place_paid_order(client, "e-3", 1, [(rice, 2)])
    job = next_job(client)
    scan_all(client, job)
    with SessionLocal() as late_packer:
        stale = fulfilment.get_job(late_packer, job["job_id"])             # kept: the session keeps this copy
        assert stale.state == "picking"

        client.post(f"/v1/fulfilment-jobs/{job['job_id']}/packed", json={"crate_slot": "S-01"})
        again = pickpack.pack(late_packer, job["job_id"], "S-02")

        assert (again.state, again.crate_slot) == ("packed", "S-01")
    assert stock(client, rice) == (28, 0)
    assert_stock_is_consistent()


def test_a_handover_that_read_the_order_before_another_handover_is_safe(client, sku):
    packed = picked_and_packed(client, sku)
    rider = packed["rider"]["rider_id"]
    with SessionLocal() as desk:
        stale = fulfilment.get_job(desk, packed["job_id"])
        assert (stale.state, stale.rider.status) == ("packed", "assigned")

        client.post(f"/v1/fulfilment-jobs/{packed['job_id']}/handover",
                    json={"rider_id": rider, "scanned_order_id": "e-1"})
        again = riders.handover(desk, packed["job_id"], rider, "e-1")

        assert again.state == "handed_over"
    changes = [e["payload"] for e in client.get("/v1/events", params={"limit": 50}).json()
               if e["type"] == "fulfilment.state_changed" and e["payload"]["state"] == "handed_over"]
    assert len(changes) == 1                                                  # handed over once


def test_a_handover_before_packing_is_refused(client, sku):
    place_paid_order(client, "e-4", 1, [(sku("Basmati rice"), 1)])
    job = next_job(client)

    res = client.post(f"/v1/fulfilment-jobs/{job['job_id']}/handover",
                      json={"rider_id": "R-11", "scanned_order_id": "e-4"})

    assert res.status_code == 409 and res.json()["error"]["code"] == "not_packed"


def test_a_picker_who_loses_the_race_for_an_order_gets_the_next_one(client, sku, monkeypatch):
    """next_job reads the oldest waiting order, then claims it. If another picker claims it in between, the claim
    changes nothing and next_job moves on to the next oldest."""
    rice = sku("Basmati rice")
    place_paid_order(client, "first", 1, [(rice, 1)])
    place_paid_order(client, "second", 1, [(rice, 1)])
    real_claim = pickpack._claim
    raced = []

    def claim_after_someone_else(db, job, picker_id, tote=None):
        if not raced:
            raced.append(job.order_id)                                       # picker-b gets there first
            assert next_job(client, "picker-b")["order_id"] == job.order_id
        return real_claim(db, job, picker_id, tote)

    monkeypatch.setattr(pickpack, "_claim", claim_after_someone_else)
    with SessionLocal() as session:
        mine = pickpack.next_job(session, "picker-a", 1)

        assert (raced, mine.order_id, mine.picker_id) == (["first"], "second", "picker-a")


def test_pickers_asking_for_batches_at_the_same_moment_never_share_an_order(client, sku):
    rice = sku("Basmati rice")
    for n in range(9):
        place_paid_order(client, f"rush-{n}", 1, [(rice, 1)])
    everyone_ready = threading.Barrier(3)

    def ask(picker: str) -> list[tuple[str, str]]:
        with SessionLocal() as session:
            everyone_ready.wait()
            return [(job.order_id, job.tote) for job in pickpack.next_batch(session, picker, 1)]

    with ThreadPoolExecutor(max_workers=3) as pool:
        batches = list(pool.map(ask, ["p-1", "p-2", "p-3"]))

    orders = [order for batch in batches for order, _tote in batch]
    assert len(orders) == len(set(orders))                                   # nobody shares an order
    assert all(1 <= len(batch) <= 3 for batch in batches)
    assert all(len({tote for _order, tote in batch}) == len(batch) for batch in batches)   # one tote per order
    assert_stock_is_consistent()


# --------------------------------------------------------------------------- small branches

def test_unknown_pick_tasks_are_404(client):
    assert client.post("/v1/pick-tasks/999999/scans", json={"barcode": "x"}).status_code == 404
    assert client.post("/v1/pick-tasks/999999/short").status_code == 404
    assert client.get("/v1/fulfilment-jobs/999999").status_code == 404


def test_a_closed_store_stays_closed_however_many_orders_wait(client, db, sku):
    db.get(Store, 1).status = "closed"
    db.commit()

    for n in range(7):                                                       # more than the busy threshold
        place_paid_order(client, f"c-{n}", 1, [(sku("Sugar"), 1)])

    with SessionLocal() as fresh:
        assert fresh.get(Store, 1).status == "closed"


def test_the_job_list_can_be_filtered_by_state(client, sku):
    picked_and_packed(client, sku, "packed-one")
    place_paid_order(client, "waiting-one", 1, [(sku("Sugar"), 1)])

    def orders(state: str) -> list[str]:
        return [j["order_id"] for j in client.get("/v1/fulfilment-jobs", params={"store_id": 1, "state": state}).json()]

    assert (orders("packed"), orders("created")) == (["packed-one"], ["waiting-one"])
    assert orders("picking") == []


def test_a_finished_job_is_never_stalled_or_released(client, db, sku):
    from datetime import timedelta

    from app import config
    from app.models import utcnow

    packed = picked_and_packed(client, sku)
    row = db.get(FulfilmentJob, packed["job_id"])
    row.last_activity_at = row.picking_at = utcnow() - timedelta(minutes=config.PICK_STALL_MINUTES + 10)
    db.commit()

    assert fulfilment.attention(db, 1)["stalled"] == []
    assert client.post("/v1/admin/recover-stalled").json() == {"released": [], "needs_attention": []}


def test_a_rider_checking_in_twice_keeps_the_first_arrival_time(client, sku):
    packed = picked_and_packed(client, sku)
    rider = packed["rider"]["rider_id"]

    first = client.post(f"/v1/riders/{rider}/arrive", json={"order_id": "e-1"}).json()
    arrived_at = client.get(f"/v1/fulfilment-jobs/{packed['job_id']}").json()["rider"]["arrived_at"]
    again = client.post(f"/v1/riders/{rider}/arrive", json={"order_id": "e-1"}).json()

    assert first == again == {"order_id": "e-1", "rider_id": rider, "crate_slot": "S-01", "status": "arrived"}
    assert client.get(f"/v1/fulfilment-jobs/{packed['job_id']}").json()["rider"]["arrived_at"] == arrived_at
