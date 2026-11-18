"""Audit log (Member 4 guide, section 7): who called which protected endpoint, and what they got back."""
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from app import monitoring
from app.main import app


def audit(client, **params) -> list[dict]:
    res = client.get("/v1/audit", params=params)
    assert res.status_code == 200, res.text
    return res.json()


def test_a_staff_call_is_recorded_with_who_what_and_the_answer(client, client_as):
    res = client_as("manager", 1).get("/v1/stores/1/dashboard")
    assert res.status_code == 200

    [entry] = audit(client, username="test-manager")

    assert (entry["username"], entry["role"], entry["store_id"]) == ("test-manager", "manager", 1)
    assert (entry["method"], entry["route"], entry["status"]) == ("GET", "/v1/stores/{store_id}/dashboard", 200)
    assert entry["path"] == "/v1/stores/1/dashboard"
    assert entry["request_id"] == res.headers["X-Request-ID"]


def test_a_refused_call_is_recorded_with_its_403(client, client_as):
    res = client_as("picker", 1).get("/v1/pickers/test-picker/next-task", params={"store_id": 2})
    assert res.status_code == 403

    [entry] = audit(client, username="test-picker")

    assert entry["status"] == 403
    assert entry["path"] == "/v1/pickers/test-picker/next-task?store_id=2"


def test_an_error_answer_is_recorded_with_its_real_status(client):
    assert client.get("/v1/stores/999/dashboard").status_code == 404

    [entry] = audit(client, username="test-admin")

    assert (entry["path"], entry["status"]) == ("/v1/stores/999/dashboard", 404)


def test_calls_that_need_no_login_are_not_recorded(client):
    with TestClient(app) as customer:
        assert customer.get("/v1/stores/1/availability").status_code == 200
        assert customer.get("/v1/stores/1/dashboard").status_code == 401   # no token: nobody to name

    assert audit(client) == []


def test_entries_come_newest_first_and_limit_caps_them(client, client_as):
    manager = client_as("manager", 1)
    manager.get("/v1/stores/1/dashboard")
    manager.get("/v1/transfer-orders", params={"store_id": 1})

    entries = audit(client, username="test-manager", limit=1)

    assert [e["route"] for e in entries] == ["/v1/transfer-orders"]


def test_only_admin_may_read_the_audit_log(client_as):
    assert client_as("ops").get("/v1/audit").status_code == 403
    assert client_as("manager", 1).get("/v1/audit").status_code == 403


def test_a_failed_audit_write_does_not_fail_the_call(client_as, monkeypatch):
    def broken_session():
        raise OperationalError("INSERT INTO audit_entries", {}, Exception("database is locked"))
    monkeypatch.setattr(monitoring, "SessionLocal", broken_session)

    assert client_as("manager", 1).get("/v1/stores/1/dashboard").status_code == 200
