"""Rate limit on the open customer endpoints (Member 4 guide, task 4.7 step 8): HLD 5's last gateway duty."""
import pytest
from fastapi.testclient import TestClient

from app import auth, config, rate_limit
from app.main import app


@pytest.fixture(autouse=True)
def fresh_buckets(monkeypatch):
    monkeypatch.setattr(rate_limit, "_buckets", {})


@pytest.fixture()
def customer(monkeypatch):
    """The limit switched on (the rest of the suite runs with it off): a burst of 3 and almost no refill,
    so a client's 4th call is refused."""
    monkeypatch.setattr(config, "RATE_LIMIT_PER_SECOND", 0.001)
    monkeypatch.setattr(config, "RATE_LIMIT_BURST", 3)
    with TestClient(app) as client:
        yield client


def test_a_client_gets_its_burst_then_429_with_retry_after(customer):
    answers = [customer.get("/v1/stores/1/availability").status_code for _ in range(3)]
    refused = customer.get("/v1/serviceability", params={"lat": 12.975, "lng": 77.6})

    assert answers == [200, 200, 200]
    assert refused.status_code == 429
    assert refused.json()["error"]["code"] == "rate_limited"
    assert int(refused.headers["Retry-After"]) >= 1
    assert refused.headers["X-Request-ID"]          # still logged and timed like any other call


def test_checkout_login_and_the_catalogue_count_too(customer):
    for _ in range(3):
        customer.get("/v1/skus")

    assert customer.get("/v1/stores").status_code == 429
    assert customer.post("/v1/reservations", json={"order_id": "x", "store_id": 1, "lines": []}).status_code == 429
    assert customer.post("/v1/reservations/r1/confirm").status_code == 429
    assert customer.delete("/v1/reservations/r1").status_code == 429
    assert customer.post("/v1/auth/login", json={"username": "admin", "password": "guess"}).status_code == 429


def test_staff_endpoints_pages_and_health_are_not_limited(customer):
    for _ in range(4):
        customer.get("/v1/stores")
    staff = TestClient(app, headers={"Authorization": f"Bearer {auth.make_token('m', 'manager', 1)}"})

    assert staff.get("/v1/stores/1/dashboard").status_code == 200
    assert customer.get("/health").status_code == 200
    assert customer.get("/").status_code == 200       # the demo page itself


def test_the_bucket_refills_at_the_rate_and_each_client_has_its_own(monkeypatch):
    monkeypatch.setattr(config, "RATE_LIMIT_PER_SECOND", 20)
    monkeypatch.setattr(config, "RATE_LIMIT_BURST", 40)

    assert all(rate_limit.wait_for("a", now=0.0) == 0 for _ in range(40))
    assert rate_limit.wait_for("a", now=0.0) == pytest.approx(0.05)     # one token comes back every 1/20 s
    assert rate_limit.wait_for("a", now=0.06) == 0
    assert rate_limit.wait_for("a", now=0.06) > 0
    assert rate_limit.wait_for("b", now=0.06) == 0                      # another client is not affected


def test_memory_stays_bounded_by_forgetting_the_client_seen_longest_ago(monkeypatch):
    monkeypatch.setattr(config, "RATE_LIMIT_PER_SECOND", 20)
    monkeypatch.setattr(config, "RATE_LIMIT_BURST", 40)
    monkeypatch.setattr(rate_limit, "MAX_CLIENTS", 3)
    for n in range(3):
        rate_limit.wait_for(f"client-{n}", now=0.0)
    rate_limit.wait_for("client-0", now=0.5)         # seen again: now the most recent

    rate_limit.wait_for("late", now=1.0)

    assert list(rate_limit._buckets) == ["client-2", "client-0", "late"]


def test_zero_turns_the_limit_off(monkeypatch):
    monkeypatch.setattr(config, "RATE_LIMIT_PER_SECOND", 0)
    monkeypatch.setattr(config, "RATE_LIMIT_BURST", 1)

    with TestClient(app) as client:
        assert all(client.get("/v1/skus").status_code == 200 for _ in range(10))
