"""Shared test setup: every test runs against a fresh copy of the demo data.

The database is a temporary SQLite file, unless DARKSTORE_TEST_DB names another one (task 1.7), for example
    DARKSTORE_TEST_DB=postgresql://darkstore:darkstore@localhost:5432/darkstore python -m pytest -q
Every table in that database is dropped and rebuilt before each test: never point it at data you want to keep."""
import os
import tempfile
from datetime import date, datetime, time, timedelta

# Must be set before anything from `app` is imported, because the engine is created at import time.
os.environ["DARKSTORE_DB"] = os.environ.get("DARKSTORE_TEST_DB") or f"sqlite:///{tempfile.mkdtemp()}/test.db"
os.environ["BACKGROUND_JOBS"] = "off"                     # no timed jobs: tests release holds themselves
os.environ["RATE_LIMIT_PER_SECOND"] = "0"                 # tests make many calls at once; test_rate_limit turns it on

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app import auth, seed  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models import SKU, utcnow  # noqa: E402
from app.modules.inventory import service as inventory  # noqa: E402
from scripts.generate_sales import clear_history, write_history  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_data():
    seed.reset()


def _logged_in(role: str, store_id: int | None = None) -> TestClient:
    token = auth.make_token(f"test-{role}", role, store_id)
    return TestClient(app, headers={"Authorization": f"Bearer {token}"})


@pytest.fixture()
def client(fresh_data):
    """Logged in as admin, so tests of business rules are not about permissions."""
    with _logged_in("admin") as c:
        yield c


@pytest.fixture()
def client_as(fresh_data):
    """For permission tests: client_as("picker", 1) is a client logged in with that role at that store.
    Leave store_id out for city-wide roles such as ops."""
    return _logged_in


@pytest.fixture()
def db(fresh_data):
    with SessionLocal() as session:
        yield session


@pytest.fixture()
def sku(fresh_data):
    """Look up a SKU id by the start of its name, e.g. sku('Toned milk'). Each lookup uses its own short session, so
    it leaves no transaction open (on PostgreSQL an open one would block a reset of the demo data)."""
    def find(name_starts_with: str) -> int:
        with SessionLocal() as session:
            return session.scalar(select(SKU.id).where(SKU.name.startswith(name_starts_with)))
    return find


def atp(client, store_id: int, sku_id: int) -> int:
    return client.get(f"/v1/stores/{store_id}/availability", params={"skus": str(sku_id)}).json()[0]["atp"]


def place_paid_order(client, order_id: str, store_id: int, lines: list[tuple[int, int]]) -> dict:
    """Checkout + pay. Returns the reservation."""
    body = {"order_id": order_id, "store_id": store_id,
            "lines": [{"sku_id": s, "qty": q} for s, q in lines]}
    res = client.post("/v1/reservations", json=body)
    assert res.status_code == 201, res.text
    paid = client.post(f"/v1/reservations/{res.json()['reservation_id']}/confirm")
    assert paid.status_code == 200, paid.text
    return paid.json()


def assert_stock_is_consistent(holds_may_exceed_stock: bool = False):
    """The three records of stock must always agree:
    StockLevel.on_hand == units in bins == sum of the ledger, and holds never exceed stock.
    The checks themselves are inventory.audit, the same ones GET /v1/admin/stock-audit runs.

    `holds_may_exceed_stock=True` is only for the moment after an expiry write-off took units a paid order was
    holding (see inventory.expire_stock); the empty-shelf path settles it when the picker reaches the line."""
    with SessionLocal() as session:
        mismatches = inventory.audit(session)
    if holds_may_exceed_stock:
        for row in mismatches:
            row["problems"] = [p for p in row["problems"] if p != "reserved_over_on_hand"]
        mismatches = [row for row in mismatches if row["problems"]]
    assert mismatches == [], f"stock records disagree: {mismatches}"


def plant_sales(db, sales: dict[int, dict[int, int]], store_id: int = 1) -> date:
    """Replace one store's sales history with {sku_id: {days_ago: units}}, each sale at noon UTC, and return today.
    Zero-unit days are left out, as the generator does."""
    today = utcnow().date()
    clear_history(db, store_id)
    write_history(db, store_id, [(sku_id, datetime.combine(today - timedelta(days=n), time(12)), units)
                                 for sku_id, by_day in sales.items() for n, units in by_day.items() if units])
    db.commit()
    assert_stock_is_consistent()
    return today
