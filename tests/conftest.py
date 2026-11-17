"""Shared test setup: every test runs against a fresh copy of the demo data in a temporary database."""
import os
import tempfile
from datetime import date, datetime, time, timedelta

# Must be set before anything from `app` is imported, because the engine is created at import time.
os.environ["DARKSTORE_DB"] = f"sqlite:///{tempfile.mkdtemp()}/test.db"
os.environ["BACKGROUND_JOBS"] = "off"                     # no timed jobs: tests release holds themselves

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import func, select  # noqa: E402

from app import auth, seed  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models import SKU, StockItem, StockLedger, StockLevel, utcnow  # noqa: E402
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
def sku(db):
    """Look up a SKU id by the start of its name, e.g. sku('Toned milk')."""
    def find(name_starts_with: str) -> int:
        return db.scalar(select(SKU.id).where(SKU.name.startswith(name_starts_with)))
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


def assert_stock_is_consistent():
    """The three records of stock must always agree:
    StockLevel.on_hand == units in bins == sum of the ledger, and holds never exceed stock."""
    with SessionLocal() as session:
        for level in session.scalars(select(StockLevel)).all():
            in_bins = session.scalar(
                select(func.coalesce(func.sum(StockItem.qty), 0))
                .where(StockItem.store_id == level.store_id, StockItem.sku_id == level.sku_id))
            in_ledger = session.scalar(
                select(func.coalesce(func.sum(StockLedger.delta), 0))
                .where(StockLedger.store_id == level.store_id, StockLedger.sku_id == level.sku_id))
            where = f"store {level.store_id} sku {level.sku_id}"
            assert level.qty_on_hand == in_bins, f"{where}: on_hand {level.qty_on_hand} != bins {in_bins}"
            assert level.qty_on_hand == in_ledger, f"{where}: on_hand {level.qty_on_hand} != ledger {in_ledger}"
            assert 0 <= level.qty_reserved <= level.qty_on_hand, f"{where}: reserved {level.qty_reserved}"


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
