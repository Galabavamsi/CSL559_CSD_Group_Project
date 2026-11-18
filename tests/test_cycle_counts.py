"""Cycle counts with manager approval (FR-11, HLD 10) and inventory accuracy (HLD 12), task 1.5.

Rice costs Rs 140 and store 1 has 30 in one bin. COUNT_AUTO_APPROVE_VALUE is Rs 500, so a difference of up to
3 rice is applied at once and a bigger one waits for a manager."""
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import auth
from app.main import app
from app.models import StockLedger

from .conftest import assert_stock_is_consistent, atp, place_paid_order
from .test_order_flow import next_job, scan_all


def bin_of(client, sku_id, store_id=1, batch_no=None):
    rows = [r for r in client.get(f"/v1/stores/{store_id}/stock").json()
            if r["sku_id"] == sku_id and (batch_no is None or r["batch_no"] == batch_no)]
    return rows[0]["bin_id"]


def start(client, sku_id, store_id=1):
    res = client.post("/v1/cycle-counts", json={"store_id": store_id, "bin_id": bin_of(client, sku_id, store_id)})
    assert res.status_code == 201, res.text
    return res.json()


def submit(client, count, counted: dict):
    return client.post(f"/v1/cycle-counts/{count['count_id']}/submit",
                       json={"lines": [{"sku_id": s, "counted_qty": q} for s, q in counted.items()]})


def as_manager(name: str, store_id: int = 1) -> TestClient:
    return TestClient(app, headers={"Authorization": f"Bearer {auth.make_token(name, 'manager', store_id)}"})


def test_the_counter_is_not_told_how_many_to_expect(client, sku):
    rice = sku("Basmati rice")
    count = start(client, rice)
    assert count["status"] == "open"
    assert [line["sku_id"] for line in count["lines"]] == [rice]
    shown = repr(count) + repr(client.get(f"/v1/cycle-counts/{count['count_id']}").json())
    assert "qty" not in shown and "30" not in shown


def test_a_small_difference_is_applied_at_once(client, db, sku):
    rice = sku("Basmati rice")
    count = start(client, rice)
    done = submit(client, count, {rice: 28}).json()                     # 2 x Rs 140 = Rs 280
    assert (done["status"], done["decided_by"], done["difference_value"]) == ("approved", "auto", 280.0)
    assert done["lines"] == [{"sku_id": rice, "sku": "Basmati rice 1 kg", "system_qty": 30, "counted_qty": 28,
                              "difference": -2}]
    assert atp(client, 1, rice) == 28
    row = db.scalar(select(StockLedger).where(StockLedger.reason == "count"))
    assert (row.delta, row.reference) == (-2, f"count:{count['count_id']}")
    assert_stock_is_consistent()


def test_a_big_difference_waits_for_a_manager(client, sku):
    rice = sku("Basmati rice")
    count = start(client, rice)
    waiting = submit(client, count, {rice: 10}).json()                  # 20 x Rs 140 = Rs 2,800
    assert (waiting["status"], waiting["difference_value"]) == ("submitted", 2800.0)
    assert atp(client, 1, rice) == 30                                    # nothing changes yet
    queue = client.get("/v1/stores/1/cycle-counts", params={"status": "submitted"}).json()
    assert [c["count_id"] for c in queue] == [count["count_id"]]

    approved = client.post(f"/v1/cycle-counts/{count['count_id']}/approve").json()
    assert approved["status"] == "approved"
    assert atp(client, 1, rice) == 10
    again = client.post(f"/v1/cycle-counts/{count['count_id']}/approve")
    assert again.status_code == 409                                      # applied once only
    assert atp(client, 1, rice) == 10
    assert_stock_is_consistent()


def test_a_rejected_count_changes_nothing(client, sku):
    rice = sku("Basmati rice")
    count = start(client, rice)
    submit(client, count, {rice: 10})
    assert client.post(f"/v1/cycle-counts/{count['count_id']}/reject").json()["status"] == "rejected"
    assert atp(client, 1, rice) == 30
    assert start(client, rice)["count_id"] != count["count_id"]          # the bin can be counted again


def test_a_manager_cannot_approve_their_own_count(client, sku):
    rice = sku("Basmati rice")
    with as_manager("asha") as asha, as_manager("ravi") as ravi:
        count = start(asha, rice)
        submit(asha, count, {rice: 10})
        own = asha.post(f"/v1/cycle-counts/{count['count_id']}/approve")
        assert own.status_code == 403 and own.json()["error"]["code"] == "own_count"
        assert ravi.post(f"/v1/cycle-counts/{count['count_id']}/approve").json()["decided_by"] == "ravi"
    assert atp(client, 1, rice) == 10


def test_found_more_than_the_records_say(client, sku):
    rice = sku("Basmati rice")
    done = submit(client, start(client, rice), {rice: 31}).json()
    assert done["status"] == "approved" and atp(client, 1, rice) == 31
    assert_stock_is_consistent()


def test_every_listed_sku_needs_a_number(client, sku):
    rice, tea = sku("Basmati rice"), sku("Tea")
    count = start(client, rice)
    missing = submit(client, count, {tea: 3})
    assert missing.status_code == 422 and missing.json()["error"]["details"] == {"sku_ids": [rice]}
    assert submit(client, count, {rice: -1}).status_code == 422
    duplicate = client.post(f"/v1/cycle-counts/{count['count_id']}/submit",
                            json={"lines": [{"sku_id": rice, "counted_qty": 1}, {"sku_id": rice, "counted_qty": 2}]})
    assert duplicate.status_code == 422
    assert client.get(f"/v1/cycle-counts/{count['count_id']}").json()["status"] == "open"


def test_units_for_a_pending_pick_are_counted_but_units_in_a_tote_are_not(client, sku):
    """Watch-out from the guide: units promised to a pending pick task are still in the bin."""
    rice = sku("Basmati rice")
    place_paid_order(client, "order-1", 1, [(rice, 5)])
    job = next_job(client)
    pending = submit(client, start(client, rice), {rice: 30}).json()
    assert pending["lines"][0]["system_qty"] == 30 and pending["status"] == "approved"

    scan_all(client, job)                                                # 5 rice now in the picker's tote
    in_tote = submit(client, start(client, rice), {rice: 25}).json()
    assert in_tote["lines"][0]["difference"] == 0
    assert client.post(f"/v1/fulfilment-jobs/{job['job_id']}/packed", json={"crate_slot": "S-01"}).status_code == 200
    assert_stock_is_consistent()


def test_an_empty_shelf_opens_a_count_of_that_bin(client, sku):
    milk = sku("Toned milk")
    place_paid_order(client, "order-1", 1, [(milk, 4)])
    task = next_job(client)["tasks"][0]
    client.post(f"/v1/pick-tasks/{task['task_id']}/short")

    opened = client.get("/v1/stores/1/cycle-counts", params={"status": "open"}).json()
    assert [(c["bin"], c["reason"], c["created_by"]) for c in opened] == [(task["bin"], "not_found", "system")]
    assert milk in [line["sku_id"] for line in opened[0]["lines"]]


def test_inventory_accuracy(client, sku):
    rice, tea = sku("Basmati rice"), sku("Tea")
    assert client.get("/v1/stores/1/inventory-accuracy").json()["value"] is None   # nothing counted yet
    submit(client, start(client, rice), {rice: 30})                      # matches
    submit(client, start(client, tea), {tea: 29})                        # one off
    rejected = start(client, rice)
    submit(client, rejected, {rice: 1})
    client.post(f"/v1/cycle-counts/{rejected['count_id']}/reject")       # a rejected count is not counted
    accuracy = client.get("/v1/stores/1/inventory-accuracy").json()
    assert (accuracy["value"], accuracy["lines_counted"], accuracy["lines_matching"]) == (0.5, 2, 1)

    kpi = next(k for k in client.get("/v1/stores/1/kpis").json()["kpis"] if k["key"] == "inventory_accuracy")
    assert (kpi["available"], kpi["value"], kpi["met"]) == (True, 0.5, False)


def test_who_may_do_what(client_as, sku):
    rice = sku("Basmati rice")
    with client_as("picker", 1) as picker:
        count = start(picker, rice)                                      # pickers count
        submit(picker, count, {rice: 10})
        assert picker.post(f"/v1/cycle-counts/{count['count_id']}/approve").status_code == 403
        assert picker.get("/v1/stores/1/cycle-counts").status_code == 403
    with client_as("picker", 2) as other_store:
        assert other_store.get(f"/v1/cycle-counts/{count['count_id']}").status_code == 403
    with client_as("manager", 2) as other_manager:
        assert other_manager.post(f"/v1/cycle-counts/{count['count_id']}/approve").status_code == 403
