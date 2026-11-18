"""Batch picking at peak (Member 2 guide, task 2.6, HLD 13.1): one order at a time off-peak, up to BATCH_SIZE orders in
one walk when at least BATCH_PICK_BACKLOG wait. Store 1's bins are walked in walk_seq order: 1-12 ambient, 13-16
chilled, 17-18 frozen."""
from datetime import timedelta

from sqlalchemy import select

from app import config
from app.models import FulfilmentJob, utcnow
from app.modules.fulfilment import service as fulfilment
from scripts.compare_picking import compare

from .conftest import assert_stock_is_consistent, place_paid_order

CARTS = [[("Basmati rice", 1), ("Vanilla ice cream", 1)],   # ambient and the far frozen bin
         [("Toned milk", 2), ("Sugar", 1)],
         [("Tea", 1), ("Frozen green peas", 1)],
         [("Paneer", 1)],
         [("Potato chips", 2)]]


def pay_for(client, sku, how_many: int) -> list[str]:
    order_ids = []
    for n, cart in enumerate(CARTS[:how_many], start=1):
        place_paid_order(client, f"b-{n}", 1, [(sku(name), qty) for name, qty in cart])
        order_ids.append(f"b-{n}")
    return order_ids


def next_batch(client, picker: str = "picker-a", store_id: int = 1) -> dict:
    res = client.get(f"/v1/pickers/{picker}/next-batch", params={"store_id": store_id})
    assert res.status_code == 200, res.text
    return res.json()


def pick_and_pack(client, batch: dict, tote: str) -> dict:
    """Scan every line of one tote's order, then pack it."""
    for line in batch["route"]:
        if line["tote"] == tote:
            client.post(f"/v1/pick-tasks/{line['task_id']}/scans",
                        json={"barcode": line["barcode"], "qty": line["qty"]})
    job_id = next(j["job_id"] for j in batch["jobs"] if j["tote"] == tote)
    return client.post(f"/v1/fulfilment-jobs/{job_id}/packed", json={"crate_slot": f"S-{tote}"}).json()


def test_at_peak_a_picker_gets_the_three_oldest_orders_in_three_totes(client, sku):
    pay_for(client, sku, 5)                                   # 5 waiting: at least BATCH_PICK_BACKLOG (4)

    batch = next_batch(client)

    assert batch["totes"] == {"A": "b-1", "B": "b-2", "C": "b-3"}
    assert [(j["tote"], j["state"], j["picker_id"]) for j in batch["jobs"]] == [
        ("A", "picking", "picker-a"), ("B", "picking", "picker-a"), ("C", "picking", "picker-a")]
    assert next_batch(client) == batch                         # asking again returns the same batch
    assert next_batch(client, "picker-b")["totes"] == {"A": "b-4"}   # 2 left: one at a time


def test_off_peak_a_picker_gets_one_order(client, sku):
    pay_for(client, sku, 2)

    batch = next_batch(client)

    assert batch["totes"] == {"A": "b-1"} and len(batch["jobs"]) == 1


def test_with_nothing_waiting_the_batch_is_empty(client):
    assert next_batch(client) == {"totes": {}, "route": [], "jobs": []}


def test_the_route_is_one_walk_through_the_store_for_all_three_orders(client, sku):
    pay_for(client, sku, 4)

    batch = next_batch(client)

    walk = [line["walk_seq"] for line in batch["route"]]
    assert walk == sorted(walk)                               # never walks back
    assert {line["tote"] for line in batch["route"]} == {"A", "B", "C"}
    pending = {t["task_id"] for j in batch["jobs"] for t in j["tasks"] if t["status"] == "pending"}
    assert {line["task_id"] for line in batch["route"]} == pending
    assert all(line["order_id"] == batch["totes"][line["tote"]] for line in batch["route"])


def test_each_order_in_a_batch_is_packed_on_its_own_and_keeps_its_tote(client, sku):
    pay_for(client, sku, 4)
    batch = next_batch(client)

    packed = pick_and_pack(client, batch, "B")

    assert (packed["state"], packed["crate_slot"]) == ("packed", "S-B")
    left = next_batch(client)
    assert left["totes"] == {"A": "b-1", "C": "b-3"}          # A and C keep their totes
    pick_and_pack(client, left, "A")
    pick_and_pack(client, next_batch(client), "C")
    assert next_batch(client)["totes"] == {"A": "b-4"}        # all three done: the next walk starts
    assert_stock_is_consistent()


def test_two_pickers_never_share_an_order_and_the_batch_rule_is_checked_each_time(client, sku):
    pay_for(client, sku, 5)
    place_paid_order(client, "b-6", 1, [(sku("Sugar"), 1)])

    first, second = next_batch(client, "picker-a"), next_batch(client, "picker-b")

    assert set(first["totes"].values()).isdisjoint(second["totes"].values())
    assert (len(first["totes"]), len(second["totes"])) == (3, 1)   # 6 waiting: a batch; then 3 waiting: one order


def test_an_order_claimed_one_at_a_time_is_given_a_tote(client, sku):
    pay_for(client, sku, 1)
    client.get("/v1/pickers/picker-a/next-task", params={"store_id": 1})

    assert next_batch(client)["totes"] == {"A": "b-1"}


def test_scanning_one_order_of_a_batch_keeps_the_others_from_looking_idle(client, db, sku):
    """Order C's lines may be at the far end of the walk: while the picker scans A, C must not be handed back."""
    pay_for(client, sku, 4)
    batch = next_batch(client)
    stale = utcnow() - timedelta(minutes=config.PICK_STALL_MINUTES + 1)
    for job in db.scalars(select(FulfilmentJob).where(FulfilmentJob.state == "picking")):
        job.picking_at = job.last_activity_at = stale
    db.commit()

    first_line = next(line for line in batch["route"] if line["tote"] == "A")
    client.post(f"/v1/pick-tasks/{first_line['task_id']}/scans", json={"barcode": first_line["barcode"]})

    assert client.post("/v1/admin/recover-stalled").json() == {"released": [], "needs_attention": []}
    assert next_batch(client)["totes"] == {"A": "b-1", "B": "b-2", "C": "b-3"}


def test_a_batch_released_for_being_idle_gives_up_its_totes(client, db, sku):
    pay_for(client, sku, 4)
    next_batch(client)
    stale = utcnow() - timedelta(minutes=config.PICK_STALL_MINUTES + 1)
    for job in db.scalars(select(FulfilmentJob).where(FulfilmentJob.state == "picking")):
        job.picking_at = job.last_activity_at = stale
    db.commit()

    assert len(client.post("/v1/admin/recover-stalled").json()["released"]) == 3

    assert next_batch(client, "picker-b")["totes"] == {"A": "b-1", "B": "b-2", "C": "b-3"}


def test_productivity_counts_a_batch_walk_once(client, db, sku):
    """Three orders picked in one 2-minute walk are 2 minutes of picking, not 4.5 (60 + 90 + 120 seconds)."""
    pay_for(client, sku, 4)
    batch = next_batch(client)
    for tote in "ABC":
        pick_and_pack(client, batch, tote)
    start = utcnow() - timedelta(minutes=10)
    for seconds, job in zip((60, 90, 120), db.scalars(select(FulfilmentJob).where(FulfilmentJob.state == "packed")
                                                      .order_by(FulfilmentJob.tote))):
        job.picking_at, job.packed_at = start, start + timedelta(seconds=seconds)
    db.commit()

    units = sum(qty for cart in CARTS[:3] for _name, qty in cart)            # 2 + 3 + 2 = 7 units
    assert fulfilment.metrics(db, 1)["items_per_picker_hour"] == round(units / (120 / 3600), 1)


def test_next_batch_is_for_the_stores_own_staff(client_as):
    assert client_as("picker", 2).get("/v1/pickers/p/next-batch", params={"store_id": 1}).status_code == 403
    assert client_as("manager", 1).get("/v1/pickers/p/next-batch", params={"store_id": 1}).status_code == 403


def test_batching_walks_less_than_one_order_at_a_time(fresh_data):
    result = compare(orders=10, batch_size=3, random_seed=3)

    assert result["orders"] == 10
    assert result["one_at_a_time"]["walks"] == 10
    assert result["batched"]["walks"] == 4                    # 10 -> 7 -> 4 -> 1 waiting: three batches of 3, then 1
    assert result["batched"]["distance"] < result["one_at_a_time"]["distance"]
    assert 0 < result["saving"] < 1
    assert_stock_is_consistent()


def test_a_batch_size_with_no_tote_letters_stops_the_app_at_startup():
    """0 would claim nothing while orders wait, and past 26 there are no tote letters left."""
    import os
    import subprocess
    import sys

    def start_with(size: str) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, "-c", "import app.config"], capture_output=True, text=True,
                              env={**os.environ, "BATCH_SIZE": size})

    for bad in ("0", "27"):
        failed = start_with(bad)
        assert failed.returncode != 0 and "BATCH_SIZE must be 1 to 26" in failed.stderr
    assert start_with("26").returncode == 0
