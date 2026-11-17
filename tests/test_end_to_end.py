"""End to end (task 4.8): the demo script through the API with real logins, from order to a final stock audit."""
from fastapi.testclient import TestClient

from app import config
from app.main import app

from .conftest import assert_stock_is_consistent, atp

DS01_HOME = {"lat": 12.975, "lng": 77.60}


def login(api: TestClient, username: str) -> dict:
    res = api.post("/v1/auth/login", json={"username": username, "password": config.DEMO_PASSWORD})
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def ok(res, status: int = 200):
    assert res.status_code == status, res.text
    return res.json()


def test_demo_script_from_order_to_stock_audit(fresh_data, sku):
    milk, rice, bread = sku("Toned milk"), sku("Basmati rice"), sku("White bread")
    with TestClient(app) as api:
        picker, manager, receiver = (login(api, name) for name in ("picker1", "manager1", "receiver1"))

        # 1. Customer (no login): a store serves the address; hold 8 milk and 2 rice, then pay.
        store = ok(api.get("/v1/serviceability", params=DS01_HOME))["store_id"]
        assert store == 1
        hold = ok(api.post("/v1/reservations", json={"order_id": "demo-1", "store_id": store, "lines": [
            {"sku_id": milk, "qty": 8}, {"sku_id": rice, "qty": 2}]}), 201)
        ok(api.post(f"/v1/reservations/{hold['reservation_id']}/confirm"))

        # 2. Picker: claim the order, scan one wrong item, find one shelf empty, pick the rest.
        job = ok(api.get("/v1/pickers/picker1/next-task", params={"store_id": store}, headers=picker))["job"]
        rice_line = next(t for t in job["tasks"] if t["sku_id"] == rice)
        wrong = ok(api.post(f"/v1/pick-tasks/{rice_line['task_id']}/scans",
                            json={"barcode": "0000000000000", "qty": rice_line["qty"]}, headers=picker))
        assert wrong["match"] is False
        old_milk = next(t for t in job["tasks"] if t["sku_id"] == milk and t["batch_no"] == "M-OLD")
        short = ok(api.post(f"/v1/pick-tasks/{old_milk['task_id']}/short", headers=picker))
        assert (short["reallocated"], short["dropped"]) == (old_milk["qty"], 0)      # found in another bin
        for task in short["job"]["tasks"]:
            if task["status"] == "pending":
                scan = api.post(f"/v1/pick-tasks/{task['task_id']}/scans",
                                json={"barcode": task["barcode"], "qty": task["qty"]}, headers=picker)
                assert ok(scan)["match"] is True

        # 3. Pack, then hand the bag to the rider.
        packed = ok(api.post(f"/v1/fulfilment-jobs/{job['job_id']}/packed", json={"crate_slot": "S-01"},
                             headers=picker))
        assert packed["state"] == "packed"
        assert ok(api.post(f"/v1/fulfilment-jobs/{job['job_id']}/handover", headers=picker))["state"] == "handed_over"

        # 4. Manager reorders once; the hub dispatches; the receiver puts the truck away.
        order = ok(api.post("/v1/replenishment/run", params={"store_id": store}, headers=manager))["transfer_order"]
        assert bread in [line["sku_id"] for line in order["lines"]]
        assert ok(api.post("/v1/replenishment/run", params={"store_id": store}, headers=manager))["transfer_order"] is None
        ok(api.post(f"/v1/transfer-orders/{order['transfer_order_id']}/dispatch", headers=manager))
        bread_before = atp(api, store, bread)
        lines = [{"sku_id": line["sku_id"], "qty": line["qty_ordered"]} for line in order["lines"]]
        ok(api.post("/v1/goods-receipts", json={"store_id": store, "transfer_order_id": order["transfer_order_id"],
                                                "lines": lines}, headers=receiver), 201)
        assert atp(api, store, bread) > bread_before

        # 5. Forecasts and reorder points are recalculated.
        ok(api.post("/v1/forecasting/run", params={"store_id": store}, headers=manager))

        # 6. A picker from store 1 cannot act in store 2.
        assert api.get("/v1/pickers/picker1/next-task", params={"store_id": 2}, headers=picker).status_code == 403

        events = {e["type"] for e in ok(api.get("/v1/events", params={"store_id": store, "limit": 100},
                                                headers=manager))}
        assert {"order.paid", "order.ready_for_pickup"} <= events

    # 7. Final audit: stock level, units in bins and the ledger all agree.
    assert_stock_is_consistent()
