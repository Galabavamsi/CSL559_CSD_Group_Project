"""Fulfilment KPIs (Member 2 guide, task 2.1) and the stalled-order list (task 2.5) that the ops page shows.
More on stalled orders in test_stuck_orders.py."""
from datetime import timedelta

from app import config
from app.models import FulfilmentJob, utcnow
from app.modules.fulfilment import service as fulfilment

from .conftest import place_paid_order


def pick_and_pack(client, store_id: int = 1, empty_shelf: bool = False) -> dict:
    """Claim the next order as picker1, scan every line (or report the first one's shelf empty), and pack."""
    job = client.get("/v1/pickers/picker1/next-task", params={"store_id": store_id}).json()["job"]
    for n, task in enumerate(job["tasks"]):
        if empty_shelf and n == 0:
            assert client.post(f"/v1/pick-tasks/{task['task_id']}/short").status_code == 200
        else:
            scan = client.post(f"/v1/pick-tasks/{task['task_id']}/scans", json={"barcode": task["barcode"], "qty": task["qty"]})
            assert scan.status_code == 200, scan.text
    packed = client.post(f"/v1/fulfilment-jobs/{job['job_id']}/packed", json={"crate_slot": "S-01"})
    assert packed.status_code == 200, packed.text
    return packed.json()


def test_with_nothing_packed_the_numbers_are_empty_not_an_error(client):
    res = client.get("/v1/stores/1/fulfilment-metrics")

    assert res.status_code == 200
    assert res.json() == {"orders_packed": 0, "seconds_to_pack_p50": None, "seconds_to_pack_p90": None,
                          "seconds_claim_to_pack_p90": None, "seconds_packed_to_handover_p90": None,
                          "fill_rate": None, "items_per_picker_hour": None}


def test_fill_rate_counts_a_dropped_line_against_the_units_ordered(client, db, sku):
    place_paid_order(client, "m-1", 1, [(sku("Basmati rice"), 2)])
    place_paid_order(client, "m-2", 1, [(sku("Sugar"), 3)])
    place_paid_order(client, "m-3", 1, [(sku("Paneer"), 1)])     # one bin only: an empty shelf drops it
    pick_and_pack(client)
    pick_and_pack(client)
    dropped = pick_and_pack(client, empty_shelf=True)

    m = fulfilment.metrics(db, 1)

    assert dropped["state"] == "cancelled"                       # nothing found, nothing to deliver
    assert m["orders_packed"] == 2
    assert m["fill_rate"] == 5 / 6                               # 2 + 3 picked of 2 + 3 + 1 ordered


def test_times_and_productivity_come_from_the_packed_orders(client, db, sku):
    place_paid_order(client, "t-1", 1, [(sku("Basmati rice"), 2)])
    place_paid_order(client, "t-2", 1, [(sku("Sugar"), 1)])
    pick_and_pack(client)
    pick_and_pack(client)

    m = fulfilment.metrics(db, 1)

    assert m["seconds_to_pack_p90"] >= m["seconds_to_pack_p50"] >= 0
    assert m["seconds_claim_to_pack_p90"] >= 0
    assert m["items_per_picker_hour"] > 0                        # 3 units over a very short picking time
    assert m["fill_rate"] == 1


def test_percentile_takes_the_value_at_index_q_times_n_minus_one():
    assert fulfilment.percentile([5, 1, 4, 2, 3], 0.9) == 4      # sorted 1..5, index int(0.9 * 4) = 3
    assert fulfilment.percentile([7], 0.9) == 7


def test_an_order_with_no_picker_activity_for_a_while_is_stalled(client, db, sku):
    place_paid_order(client, "s-1", 1, [(sku("Basmati rice"), 1)])
    place_paid_order(client, "s-2", 1, [(sku("Sugar"), 1)])
    client.get("/v1/pickers/picker1/next-task", params={"store_id": 1})
    client.get("/v1/pickers/picker2/next-task", params={"store_id": 1})
    late = db.query(FulfilmentJob).filter_by(order_id="s-1").one()
    late.picking_at = late.last_activity_at = utcnow() - timedelta(minutes=config.PICK_STALL_MINUTES + 1)
    db.commit()

    stalled = fulfilment.attention(db, 1)["stalled"]

    assert [s["order_id"] for s in stalled] == ["s-1"]          # s-2 was only just claimed
    assert stalled[0]["picker_id"] == "picker1" and stalled[0]["minutes_idle"] > config.PICK_STALL_MINUTES


def test_the_ops_page_now_shows_fulfilment_numbers(client, sku):
    place_paid_order(client, "o-1", 1, [(sku("Basmati rice"), 1)])
    pick_and_pack(client)

    page = client.get("/v1/stores/1/kpis").json()
    board = {k["key"]: k for k in page["kpis"]}

    assert all(board[key]["available"] for key in ("seconds_to_pack_p90", "fill_rate", "items_per_picker_hour"))
    assert board["fill_rate"]["value"] == 1 and board["fill_rate"]["met"] is True
    assert page["needs_action"]["stalled_orders"] == [] and page["needs_action"]["stalled_note"] is None


def test_staff_from_another_store_cannot_read_the_metrics(client_as):
    assert client_as("manager", 2).get("/v1/stores/1/fulfilment-metrics").status_code == 403
