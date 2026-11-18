"""Stuck-order recovery (Member 2 guide, task 2.5): a dead handheld must not hold an order forever.

An order being picked with no claim, scan or shelf report for PICK_STALL_MINUTES is stalled. With nothing in its tote it
goes back to the queue; with units in a tote it is only flagged, because a person has to fetch them."""
import asyncio
from datetime import datetime, timedelta

from sqlalchemy import select

from app import background, config
from app.db import SessionLocal
from app.models import FulfilmentJob, utcnow
from app.modules.fulfilment import service as fulfilment

from .conftest import assert_stock_is_consistent, place_paid_order

IDLE = config.PICK_STALL_MINUTES + 1


def claim(client, picker: str, store_id: int = 1) -> dict | None:
    return client.get(f"/v1/pickers/{picker}/next-task", params={"store_id": store_id}).json()["job"]


def scan(client, task: dict, qty: int = 1, barcode: str | None = None, picker_id: str = "picker-a"):
    """Scan as picker-a's handheld does: it says whose handheld it is."""
    return client.post(f"/v1/pick-tasks/{task['task_id']}/scans",
                       json={"barcode": barcode or task["barcode"], "qty": qty, "picker_id": picker_id})


def back_date(db, order_id: str, minutes: float = IDLE) -> None:
    """Pretend the picker claimed this order and has done nothing on it for `minutes`."""
    job = db.scalar(select(FulfilmentJob).where(FulfilmentJob.order_id == order_id))
    job.picking_at = job.last_activity_at = utcnow() - timedelta(minutes=minutes)
    db.commit()


def recover(client) -> dict:
    res = client.post("/v1/admin/recover-stalled")
    assert res.status_code == 200, res.text
    return res.json()


def job_of(client, order_id: str) -> dict:
    return next(j for j in client.get("/v1/fulfilment-jobs", params={"store_id": 1}).json()
                if j["order_id"] == order_id)


def when(stamp: str) -> datetime:
    return datetime.fromisoformat(stamp.removesuffix("Z"))


def test_an_idle_order_with_nothing_in_the_tote_goes_to_another_picker(client, db, sku):
    place_paid_order(client, "idle-1", 1, [(sku("Basmati rice"), 2)])
    first = claim(client, "picker-a")
    back_date(db, "idle-1")

    result = recover(client)

    assert [r["order_id"] for r in result["released"]] == ["idle-1"] and result["needs_attention"] == []
    released = job_of(client, "idle-1")
    assert (released["state"], released["picker_id"]) == ("created", None)
    # The first picker's handheld comes back to life: before and after someone else claims the order,
    # it is told the order is no longer theirs, and its scans change nothing.
    before = scan(client, first["tasks"][0], qty=2)
    assert before.status_code == 409 and before.json()["error"]["code"] == "job_not_picking"
    assert claim(client, "picker-b")["order_id"] == "idle-1"
    after = scan(client, first["tasks"][0], qty=2)
    assert after.status_code == 409 and after.json()["error"]["code"] == "not_your_order"
    after_short = client.post(f"/v1/pick-tasks/{first['tasks'][0]['task_id']}/short", json={"picker_id": "picker-a"})
    assert after_short.status_code == 409 and after_short.json()["error"]["code"] == "not_your_order"
    assert scan(client, first["tasks"][0], qty=2, picker_id="picker-b").json()["message"] == "Picked."
    changes = [e["payload"] for e in client.get("/v1/events", params={"limit": 50}).json()
               if e["type"] == "fulfilment.state_changed"]
    assert {"job_id": first["job_id"], "order_id": "idle-1", "state": "created", "reason": "stalled",
            "picker_id": "picker-a"} in changes
    assert_stock_is_consistent()


def test_an_idle_order_with_a_picked_line_is_flagged_not_released(client, db, sku):
    place_paid_order(client, "idle-2", 1, [(sku("Basmati rice"), 1), (sku("Sugar"), 1)])
    job = claim(client, "picker-a")
    assert scan(client, job["tasks"][0]).json()["message"] == "Picked."
    back_date(db, "idle-2")

    result = recover(client)

    assert result["released"] == []
    [flagged] = result["needs_attention"]
    assert (flagged["order_id"], flagged["picker_id"], flagged["units_in_tote"]) == ("idle-2", "picker-a", 1)
    assert flagged["minutes_idle"] >= IDLE
    assert job_of(client, "idle-2")["state"] == "picking"
    assert claim(client, "picker-b") is None                   # nobody else is handed it
    assert_stock_is_consistent()


def test_a_half_scanned_line_counts_as_items_in_the_tote(client, db, sku):
    place_paid_order(client, "idle-3", 1, [(sku("Basmati rice"), 6)])
    job = claim(client, "picker-a")
    scan(client, job["tasks"][0], qty=2)
    back_date(db, "idle-3")

    result = recover(client)

    assert result["released"] == [] and result["needs_attention"][0]["units_in_tote"] == 2


def test_claim_and_scans_record_activity_so_a_slow_picker_is_not_stalled(client, db, sku):
    """The old check counted from the claim, so a slow but working picker looked stalled."""
    place_paid_order(client, "slow-1", 1, [(sku("Basmati rice"), 6)])
    job = claim(client, "picker-a")
    assert job["last_activity_at"] is not None
    back_date(db, "slow-1", minutes=IDLE + 30)                   # claimed long ago...

    scan(client, job["tasks"][0])                                # ...but scanning right now

    assert when(job_of(client, "slow-1")["last_activity_at"]) > utcnow() - timedelta(minutes=1)
    assert fulfilment.attention(db, 1)["stalled"] == []
    assert recover(client) == {"released": [], "needs_attention": []}


def test_a_wrong_scan_still_shows_the_handheld_is_alive(client, db, sku):
    place_paid_order(client, "alive-1", 1, [(sku("Basmati rice"), 1)])
    job = claim(client, "picker-a")
    back_date(db, "alive-1")

    assert scan(client, job["tasks"][0], barcode="0000000000000").json()["match"] is False

    assert recover(client)["released"] == []
    assert job_of(client, "alive-1")["tasks"][0]["scanned_qty"] == 0   # the wrong item still changed nothing else


def test_a_scan_between_the_check_and_the_release_keeps_the_order(client, db, sku, monkeypatch):
    """recover_stalled reads the idle jobs, then releases them with a conditional UPDATE. A scan landing in between
    makes the order active again, so the UPDATE must not match."""
    place_paid_order(client, "race-1", 1, [(sku("Basmati rice"), 1)])
    task = claim(client, "picker-a")["tasks"][0]
    back_date(db, "race-1")
    real_units_in_tote = fulfilment.units_in_tote

    def picker_scans_meanwhile(job):
        assert scan(client, task, barcode="0000000000000").status_code == 200   # the handheld wakes up
        return real_units_in_tote(job)

    monkeypatch.setattr(fulfilment, "units_in_tote", picker_scans_meanwhile)
    with SessionLocal() as session:
        result = fulfilment.recover_stalled(session)

    assert result["released"] == []
    assert job_of(client, "race-1")["picker_id"] == "picker-a"


def test_attention_lists_stalled_orders_and_bags_waiting_too_long_for_a_rider(client, db, sku):
    rice = sku("Basmati rice")
    for order_id in ("bag-old", "bag-new", "stuck"):
        place_paid_order(client, order_id, 1, [(rice, 1)])
    for slot in ("S-01", "S-02"):                                # bag-old, then bag-new
        job = claim(client, "picker-a")
        scan(client, job["tasks"][0])
        client.post(f"/v1/fulfilment-jobs/{job['job_id']}/packed", json={"crate_slot": slot})
    claim(client, "picker-a")                                    # "stuck" is claimed, then left
    back_date(db, "stuck")
    old_bag = db.scalar(select(FulfilmentJob).where(FulfilmentJob.order_id == "bag-old"))
    old_bag.packed_at = utcnow() - timedelta(minutes=config.RIDER_WAIT_MINUTES + 2)
    db.commit()

    seen = client.get("/v1/stores/1/attention").json()

    assert [s["order_id"] for s in seen["stalled"]] == ["stuck"]
    [late_bag] = seen["waiting_for_rider"]
    assert (late_bag["order_id"], late_bag["crate_slot"]) == ("bag-old", "S-01")
    assert late_bag["minutes_waiting"] > config.RIDER_WAIT_MINUTES


def test_who_may_see_and_recover(client_as):
    assert client_as("picker", 1).get("/v1/stores/1/attention").status_code == 200
    assert client_as("manager", 2).get("/v1/stores/1/attention").status_code == 403
    assert client_as("manager", 1).post("/v1/admin/recover-stalled").status_code == 403
    assert client_as("admin").post("/v1/admin/recover-stalled").status_code == 200


def test_the_background_loop_recovers_on_its_own(client, db, sku, monkeypatch):
    place_paid_order(client, "loop-1", 1, [(sku("Basmati rice"), 1)])
    claim(client, "picker-a")
    back_date(db, "loop-1")
    monkeypatch.setattr(config, "STALL_CHECK_SECONDS", 0.05)

    async def run_briefly():
        loop = asyncio.create_task(background.stall_loop())
        for _ in range(100):
            await asyncio.sleep(0.05)
            if job_of(client, "loop-1")["state"] == "created":
                break
        loop.cancel()

    asyncio.run(run_briefly())
    assert job_of(client, "loop-1")["state"] == "created"
