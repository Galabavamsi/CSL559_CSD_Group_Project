"""Login and roles (HLD 10): who may call what, and only for their own store."""
from fastapi.testclient import TestClient

from app import auth, config
from app.main import app

from .conftest import place_paid_order


def bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_password_hash_round_trip():
    stored = auth.hash_password("s3cret")

    assert "s3cret" not in stored
    assert auth.check_password("s3cret", stored) is True
    assert auth.check_password("wrong", stored) is False
    assert auth.check_password("s3cret", "not-a-hash") is False


def test_login_returns_a_token_that_works(fresh_data):
    with TestClient(app) as anonymous:
        res = anonymous.post("/v1/auth/login", json={"username": "picker1", "password": config.DEMO_PASSWORD})

        assert res.status_code == 200, res.text
        body = res.json()
        assert body["role"] == "picker" and body["store_id"] == 1
        jobs = anonymous.get("/v1/pickers/picker1/next-task", params={"store_id": 1},
                             headers=bearer(body["access_token"]))
        assert jobs.status_code == 200


def test_login_rejects_wrong_password_and_unknown_user(fresh_data):
    with TestClient(app) as anonymous:
        wrong = anonymous.post("/v1/auth/login", json={"username": "picker1", "password": "nope"})
        unknown = anonymous.post("/v1/auth/login", json={"username": "nobody", "password": config.DEMO_PASSWORD})

    assert wrong.status_code == 401 and wrong.json()["error"]["code"] == "bad_credentials"
    assert unknown.status_code == 401 and unknown.json() == wrong.json()   # no hint about which usernames exist


def test_no_token_on_protected_endpoint_is_401(fresh_data):
    with TestClient(app) as anonymous:
        assert anonymous.get("/v1/stores/1/dashboard").status_code == 401
        assert anonymous.post("/v1/admin/reset").status_code == 401
        assert anonymous.post("/v1/stock-adjustments", json={
            "store_id": 1, "sku_id": 1, "delta": -1, "reason": "damage"}).status_code == 401


def test_customer_endpoints_stay_open(fresh_data, sku):
    with TestClient(app) as anonymous:
        assert anonymous.get("/v1/serviceability", params={"lat": 12.975, "lng": 77.60}).status_code == 200
        assert anonymous.get("/v1/stores/1/availability").status_code == 200
        held = anonymous.post("/v1/reservations", json={
            "order_id": "open-1", "store_id": 1, "lines": [{"sku_id": sku("Tea"), "qty": 1}]})
        assert held.status_code == 201
        assert anonymous.post(f"/v1/reservations/{held.json()['reservation_id']}/confirm").status_code == 200


def test_expired_or_forged_token_is_401(fresh_data):
    expired = auth.make_token("picker1", "picker", 1, minutes=-1)
    with TestClient(app) as anonymous:
        assert anonymous.get("/v1/stores/1/dashboard", headers=bearer(expired)).status_code == 401
        assert anonymous.get("/v1/stores/1/dashboard", headers=bearer("not-a-token")).status_code == 401


def test_picker_cannot_take_another_stores_task(client_as):
    picker = client_as("picker", 1)

    assert picker.get("/v1/pickers/p/next-task", params={"store_id": 1}).status_code == 200
    other = picker.get("/v1/pickers/p/next-task", params={"store_id": 2})
    assert other.status_code == 403 and other.json()["error"]["code"] == "wrong_store"


def test_picker_cannot_scan_or_pack_another_stores_order(client, client_as, sku):
    place_paid_order(client, "order-s2", 2, [(sku("Tea"), 1)])
    job = client_as("picker", 2).get("/v1/pickers/p2/next-task", params={"store_id": 2}).json()["job"]
    task = job["tasks"][0]
    outsider = client_as("picker", 1)

    assert outsider.post(f"/v1/pick-tasks/{task['task_id']}/scans",
                         json={"barcode": task["barcode"], "qty": 1}).status_code == 403
    assert outsider.post(f"/v1/pick-tasks/{task['task_id']}/short").status_code == 403
    assert outsider.post(f"/v1/fulfilment-jobs/{job['job_id']}/packed", json={"crate_slot": "S-1"}).status_code == 403
    assert outsider.post(f"/v1/fulfilment-jobs/{job['job_id']}/handover",
                         json={"rider_id": "R-11", "scanned_order_id": job["order_id"]}).status_code == 403


def test_receiver_cannot_adjust_stock_but_manager_can(client_as, sku):
    body = {"store_id": 1, "sku_id": sku("Tea"), "delta": -1, "reason": "damage"}

    assert client_as("receiver", 1).post("/v1/stock-adjustments", json=body).status_code == 403
    assert client_as("manager", 2).post("/v1/stock-adjustments", json=body).status_code == 403
    assert client_as("manager", 1).post("/v1/stock-adjustments", json=body).status_code == 200


def test_goods_receipt_needs_receiver_or_manager_of_that_store(client_as, sku):
    body = {"store_id": 1, "lines": [{"sku_id": sku("Tea"), "qty": 2}]}

    assert client_as("picker", 1).post("/v1/goods-receipts", json=body).status_code == 403
    assert client_as("receiver", 2).post("/v1/goods-receipts", json=body).status_code == 403
    assert client_as("receiver", 1).post("/v1/goods-receipts", json=body).status_code == 201


def test_manager_runs_supply_jobs_only_for_own_store(client_as):
    manager, picker = client_as("manager", 1), client_as("picker", 1)

    assert manager.post("/v1/replenishment/run", params={"store_id": 1}).status_code == 200
    assert manager.post("/v1/forecasting/run", params={"store_id": 1}).status_code == 200
    assert manager.post("/v1/replenishment/run", params={"store_id": 2}).status_code == 403
    assert picker.post("/v1/forecasting/run", params={"store_id": 1}).status_code == 403


def test_transfer_order_dispatch_checks_the_orders_store(client_as):
    order = client_as("manager", 1).post("/v1/replenishment/run", params={"store_id": 1}).json()["transfer_order"]
    url = f"/v1/transfer-orders/{order['transfer_order_id']}/dispatch"

    assert client_as("manager", 2).post(url).status_code == 403
    assert client_as("manager", 1).post(url).status_code == 200


def test_dashboard_and_events_are_per_store_except_for_ops(client_as):
    picker, ops = client_as("picker", 1), client_as("ops")

    assert picker.get("/v1/stores/1/dashboard").status_code == 200
    assert picker.get("/v1/stores/2/dashboard").status_code == 403
    assert picker.get("/v1/events", params={"store_id": 1}).status_code == 200
    assert picker.get("/v1/events").status_code == 403            # all stores at once is city-wide
    assert ops.get("/v1/stores/2/dashboard").status_code == 200
    assert ops.get("/v1/events").status_code == 200


def test_admin_endpoints_need_admin(client, client_as):
    assert client_as("manager", 1).post("/v1/admin/sweep-reservations").status_code == 403
    assert client_as("ops").post("/v1/admin/reset").status_code == 403
    assert client.post("/v1/admin/sweep-reservations").status_code == 200
