"""Rider handoff (Member 2 guide, task 2.7, HLD service 11): the right bag goes to the right rider.

Packing an order makes the stand-in rider system assign a rider; the rider checks in for a crate slot; the desk scans
the bag and only this order's bag goes to this order's rider."""
from datetime import timedelta

from sqlalchemy import select

from app.models import FulfilmentJob
from app.modules.fulfilment import service as fulfilment
from app.modules.fulfilment.riders import RIDERS

from .conftest import assert_stock_is_consistent, place_paid_order
from .test_order_flow import next_job, scan_all


def packed_order(client, sku, order_id: str = "r-1", slot: str = "S-04") -> dict:
    place_paid_order(client, order_id, 1, [(sku("Basmati rice"), 1)])
    job = next_job(client)
    scan_all(client, job)
    packed = client.post(f"/v1/fulfilment-jobs/{job['job_id']}/packed", json={"crate_slot": slot})
    assert packed.status_code == 200, packed.text
    return packed.json()


def handover(client, job: dict, rider_id: str, scanned_order_id: str):
    return client.post(f"/v1/fulfilment-jobs/{job['job_id']}/handover",
                       json={"rider_id": rider_id, "scanned_order_id": scanned_order_id})


def test_packing_an_order_gets_it_a_rider(client, sku):
    job = packed_order(client, sku)

    assert job["rider"]["rider_id"] in RIDERS and job["rider"]["status"] == "assigned"
    assigned = [e["payload"] for e in client.get("/v1/events", params={"limit": 50}).json()
                if e["type"] == "rider.assigned"]
    assert assigned == [{"job_id": job["job_id"], "order_id": "r-1", "rider_id": job["rider"]["rider_id"]}]


def test_the_rider_checks_in_and_is_told_the_crate_slot(client, sku):
    job = packed_order(client, sku, slot="S-04")
    rider = job["rider"]["rider_id"]

    res = client.post(f"/v1/riders/{rider}/arrive", json={"order_id": "r-1"})

    assert res.status_code == 200
    assert res.json() == {"order_id": "r-1", "rider_id": rider, "crate_slot": "S-04", "status": "arrived"}
    assert client.get(f"/v1/fulfilment-jobs/{job['job_id']}").json()["rider"]["arrived_at"] is not None


def test_a_wrong_bag_is_refused_and_the_order_stays_packed(client, sku):
    mine = packed_order(client, sku, "r-1", "S-01")
    other = packed_order(client, sku, "r-2", "S-02")
    rider = mine["rider"]["rider_id"]

    res = handover(client, mine, rider, scanned_order_id="r-2")          # the desk picked up the other bag

    assert res.status_code == 409 and res.json()["error"]["code"] == "wrong_bag"
    assert "S-01" in res.json()["error"]["message"]                       # tells the desk where the right bag is
    for job in (mine, other):
        now = client.get(f"/v1/fulfilment-jobs/{job['job_id']}").json()
        assert (now["state"], now["rider"]["status"]) == ("packed", "assigned")
    assert_stock_is_consistent()


def test_the_right_bag_goes_to_the_rider(client, sku):
    job = packed_order(client, sku)
    rider = job["rider"]["rider_id"]
    client.post(f"/v1/riders/{rider}/arrive", json={"order_id": "r-1"})

    res = handover(client, job, rider, scanned_order_id="r-1")

    assert res.status_code == 200
    handed = res.json()
    assert handed["state"] == "handed_over"
    assert (handed["rider"]["status"], handed["rider"]["rider_id"]) == ("collected", rider)
    assert handed["rider"]["collected_at"] is not None
    assert handover(client, job, rider, scanned_order_id="r-1").status_code == 200   # a retry is safe
    assert_stock_is_consistent()


def test_another_rider_cannot_check_in_or_take_the_bag(client, sku):
    job = packed_order(client, sku)
    stranger = next(r for r in RIDERS if r != job["rider"]["rider_id"])

    arrive = client.post(f"/v1/riders/{stranger}/arrive", json={"order_id": "r-1"})
    take = handover(client, job, stranger, scanned_order_id="r-1")

    assert arrive.status_code == take.status_code == 409
    assert arrive.json()["error"]["code"] == take.json()["error"]["code"] == "wrong_rider"
    assert client.get(f"/v1/fulfilment-jobs/{job['job_id']}").json()["state"] == "packed"


def test_a_rider_cannot_check_in_before_the_order_is_packed_or_after_it_is_collected(client, sku):
    job = packed_order(client, sku)
    rider = job["rider"]["rider_id"]
    handover(client, job, rider, "r-1")
    late = client.post(f"/v1/riders/{rider}/arrive", json={"order_id": "r-1"})
    assert late.status_code == 409 and late.json()["error"]["code"] == "already_collected"

    place_paid_order(client, "r-9", 1, [(sku("Sugar"), 1)])             # paid, not packed yet
    early = client.post("/v1/riders/R-11/arrive", json={"order_id": "r-9"})
    assert early.status_code == 409 and early.json()["error"]["code"] == "not_ready"
    assert client.post("/v1/riders/R-11/arrive", json={"order_id": "nope"}).status_code == 404


def test_packed_to_handover_time_is_a_fulfilment_kpi(client, db, sku):
    for n in (1, 2, 3):
        job = packed_order(client, sku, f"k-{n}", f"S-0{n}")
        handover(client, job, job["rider"]["rider_id"], f"k-{n}")
    for n, wait in ((1, 30), (2, 60), (3, 90)):                          # riders took 30, 60 and 90 seconds
        row = db.scalar(select(FulfilmentJob).where(FulfilmentJob.order_id == f"k-{n}"))
        row.handed_at = row.packed_at + timedelta(seconds=wait)
    db.commit()

    assert fulfilment.metrics(db, 1)["seconds_packed_to_handover_p90"] == 60.0   # index int(0.9 * 2) = 1 of 30, 60, 90


def test_the_desk_of_another_store_cannot_check_riders_in(client, client_as, sku):
    job = packed_order(client, sku)

    res = client_as("picker", 2).post(f"/v1/riders/{job['rider']['rider_id']}/arrive", json={"order_id": "r-1"})

    assert res.status_code == 403
    assert client_as("manager", 1).post(f"/v1/riders/{job['rider']['rider_id']}/arrive",
                                        json={"order_id": "r-1"}).status_code == 403


def test_an_order_packed_before_riders_were_assigned_goes_to_the_rider_who_comes(client, db, sku):
    """No dead end: such an order (an old database) has no rider, and cancel refuses packed orders."""
    job = packed_order(client, sku)
    db.delete(db.get(FulfilmentJob, job["job_id"]).rider)            # as if packed before task 2.7
    db.commit()

    arrived = client.post("/v1/riders/R-12/arrive", json={"order_id": "r-1"})

    assert arrived.status_code == 200 and arrived.json()["crate_slot"] == "S-04"
    assert client.get(f"/v1/fulfilment-jobs/{job['job_id']}").json()["rider"]["rider_id"] == "R-12"
    assert handover(client, job, "R-12", "r-1").json()["state"] == "handed_over"


def test_an_old_order_with_a_wrong_bag_is_refused_and_keeps_no_rider(client, db, sku):
    job = packed_order(client, sku)
    db.delete(db.get(FulfilmentJob, job["job_id"]).rider)
    db.commit()

    res = handover(client, job, "R-12", "someone-else")

    assert res.status_code == 409 and res.json()["error"]["code"] == "wrong_bag"
    assert client.get(f"/v1/fulfilment-jobs/{job['job_id']}").json()["rider"] is None


def test_a_rider_handed_the_bag_without_checking_in_is_recorded_as_arrived(client, sku):
    job = packed_order(client, sku)
    rider = job["rider"]["rider_id"]

    handed = handover(client, job, rider, "r-1").json()["rider"]

    assert handed["status"] == "collected"
    assert handed["arrived_at"] == handed["collected_at"] is not None


def test_after_the_bag_is_gone_any_other_handover_says_so(client, sku):
    job = packed_order(client, sku)
    rider = job["rider"]["rider_id"]
    stranger = next(r for r in RIDERS if r != rider)
    handover(client, job, rider, "r-1")

    late, wrong_bag = handover(client, job, stranger, "r-1"), handover(client, job, rider, "r-2")

    for res in (late, wrong_bag):
        assert res.status_code == 409 and res.json()["error"]["code"] == "already_collected"
        assert rider in res.json()["error"]["message"]
