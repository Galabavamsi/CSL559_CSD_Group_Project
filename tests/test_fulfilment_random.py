"""Random mixes of everything a store does to orders, checked after every step (Member 2's fulfilment and pick & pack).

The feature tests each follow one story. Here a seeded random sequence of claims, unit scans, empty-shelf reports
(with random "found" counts), cancels, packs and handovers runs over a dozen paid orders, so the steps meet in orders
no one wrote down. After every step the stock audit must hold (on hand = bins = ledger, 0 <= held <= on hand). At the
end every order is packed, handed over or cancelled, nothing is held any more, and no order was refunded more than
it cost. The seeds are fixed, so a failure can be replayed."""
import random

import pytest

from .conftest import assert_stock_is_consistent

PICKERS = ("picker-a", "picker-b")


def place_orders(client, rng: random.Random, count: int) -> dict[str, float]:
    """Pay for `count` random carts; returns each order's total price."""
    rows = [r for r in client.get("/v1/stores/1/availability").json() if r["atp"] > 0]
    totals = {}
    for n in range(count * 10):
        if len(totals) == count:
            break
        picks = rng.sample(rows, rng.randint(1, 3))
        lines = [{"sku_id": r["sku_id"], "qty": rng.randint(1, 3)} for r in picks]
        order_id = f"rnd-{len(totals)}"
        held = client.post("/v1/reservations", json={"order_id": order_id, "store_id": 1, "lines": lines})
        if held.status_code != 201:
            continue                                              # not enough of something: draw another cart
        assert client.post(f"/v1/reservations/{held.json()['reservation_id']}/confirm").status_code == 200
        price = {r["sku_id"]: r["price"] for r in picks}
        totals[order_id] = sum(line["qty"] * price[line["sku_id"]] for line in lines)
    return totals


def jobs(client) -> list[dict]:
    return client.get("/v1/fulfilment-jobs", params={"store_id": 1}).json()


def ok(res) -> dict:
    assert res.status_code == 200, res.text
    return res.json()


def step(client, rng: random.Random) -> str:
    """Do one random thing that is allowed right now; returns what it did."""
    now = jobs(client)
    picking = [j for j in now if j["state"] == "picking"]
    pending = [(j, t) for j in picking for t in j["tasks"] if t["status"] == "pending"]
    ready = [j for j in picking if not any(t["status"] == "pending" for t in j["tasks"])]
    choices = ["claim"] * any(j["state"] == "created" for j in now)
    choices += ["scan"] * 4 * bool(pending) + ["short"] * bool(pending)
    choices += ["cancel"] * any(j["state"] in ("created", "picking") for j in now)
    choices += ["pack"] * 2 * bool(ready) + ["handover"] * any(j["state"] == "packed" for j in now)
    if not choices:
        return "done"
    action = rng.choice(choices)
    if action == "claim":
        ok(client.get(f"/v1/pickers/{rng.choice(PICKERS)}/next-batch", params={"store_id": 1}))
    elif action == "scan":
        job, task = rng.choice(pending)
        left = task["qty"] - task["scanned_qty"]
        assert ok(client.post(f"/v1/pick-tasks/{task['task_id']}/scans",
                              json={"barcode": task["barcode"], "qty": rng.randint(1, left)}))["match"]
    elif action == "short":
        job, task = rng.choice(pending)
        found = rng.choice([None, *range(task["scanned_qty"], task["qty"])])
        ok(client.post(f"/v1/pick-tasks/{task['task_id']}/short", json={"found": found} if found is not None else None))
    elif action == "cancel":
        job = rng.choice([j for j in now if j["state"] in ("created", "picking")])
        ok(client.post(f"/v1/fulfilment-jobs/{job['job_id']}/cancel", json={"reason": "random"}))
    elif action == "pack":
        ok(client.post(f"/v1/fulfilment-jobs/{rng.choice(ready)['job_id']}/packed", json={"crate_slot": "S-01"}))
    else:
        job = rng.choice([j for j in now if j["state"] == "packed"])
        ok(client.post(f"/v1/fulfilment-jobs/{job['job_id']}/handover",
                       json={"rider_id": job["rider"]["rider_id"], "scanned_order_id": job["order_id"]}))
    return action


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_any_mix_of_store_actions_keeps_the_stock_right_and_finishes_every_order(client, seed):
    rng = random.Random(seed)
    totals = place_orders(client, rng, 12)
    done = []

    for _ in range(400):
        action = step(client, rng)
        assert_stock_is_consistent()
        if action == "done":
            break
        done.append(action)

    assert action == "done", f"still going after 400 steps: {done[-10:]}"
    assert {j["state"] for j in jobs(client)} <= {"packed", "handed_over", "cancelled"}
    assert all(r["reserved"] == 0 for r in client.get("/v1/stores/1/availability").json())   # nothing left held
    log = client.get("/v1/events", params={"limit": 500}).json()
    refunded = {order: 0.0 for order in totals}
    for event in log:
        if event["type"] in ("order.line_dropped", "order.cancelled"):
            refunded[event["payload"]["order_id"]] += event["payload"]["refund_amount"]
    assert all(refunded[order] <= totals[order] + 1e-6 for order in totals), refunded
    assert {"claim", "scan", "pack"} <= set(done)                                 # the mix really mixed
