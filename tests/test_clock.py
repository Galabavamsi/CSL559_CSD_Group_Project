"""The calendar is India's (app/clock.py): the server's clock is UTC, and a use-by date ends at midnight where the
food is, not five and a half hours later."""
from datetime import datetime, time

from sqlalchemy import select

from app import clock
from app.models import StockItem
from app.modules.inventory import service as inventory
from tests.conftest import place_paid_order


def at(monkeypatch, moment: datetime) -> None:
    """Make it `moment` (UTC) for everything that asks the calendar."""
    monkeypatch.setattr(clock, "utcnow", lambda: moment)


def test_the_date_changes_at_midnight_in_india_not_in_utc(monkeypatch):
    at(monkeypatch, datetime(2026, 11, 23, 18, 29))             # 23:59 on the 23rd in India
    assert clock.today().isoformat() == "2026-11-23"
    at(monkeypatch, datetime(2026, 11, 23, 18, 30))             # midnight in India; still the 23rd in UTC
    assert clock.today().isoformat() == "2026-11-24"
    at(monkeypatch, datetime(2026, 11, 24, 0, 0))               # UTC catches up five and a half hours later
    assert clock.today().isoformat() == "2026-11-24"


def test_a_pack_is_not_sold_after_midnight_in_india_on_its_use_by_date(client, db, sku, monkeypatch):
    milk = sku("Toned milk")
    use_by = db.scalar(select(StockItem.expiry_date).where(StockItem.sku_id == milk, StockItem.batch_no == "M-OLD"))

    def shop_row() -> dict:
        return next(row for row in client.get("/v1/stores/1/shop").json() if row["sku_id"] == milk)

    at(monkeypatch, datetime.combine(use_by, time(18, 0)))      # 23:30 in India on the use-by date: its last hour
    last_hour = shop_row()
    at(monkeypatch, datetime.combine(use_by, time(19, 0)))      # 00:30 the next day in India; UTC says the same date
    next_day = shop_row()

    assert (last_hour["batch"]["batch_no"], last_hour["rescue"]) == ("M-OLD", {"price": 20.0, "units": 6})
    assert (next_day["batch"]["batch_no"], next_day["rescue"]) == ("M-NEW", None)


def test_an_order_after_midnight_in_india_is_not_picked_from_yesterdays_batch(client, db, sku, monkeypatch):
    milk = sku("Toned milk")
    use_by = db.scalar(select(StockItem.expiry_date).where(StockItem.sku_id == milk, StockItem.batch_no == "M-OLD"))
    at(monkeypatch, datetime.combine(use_by, time(19, 0)))      # 00:30 the next day in India

    place_paid_order(client, "desk-1", 1, [(milk, 2)])

    job = client.get("/v1/pickers/picker1/next-task", params={"store_id": 1}).json()["job"]
    assert [task["batch_no"] for task in job["tasks"]] == ["M-NEW"]


def test_the_hourly_write_off_follows_indias_date_too(db, sku, monkeypatch):
    milk = sku("Toned milk")
    use_by = db.scalar(select(StockItem.expiry_date).where(StockItem.sku_id == milk, StockItem.batch_no == "M-OLD"))

    at(monkeypatch, datetime.combine(use_by, time(18, 0)))      # still the use-by date in India
    assert inventory.expire_stock(db, 1) == 0
    at(monkeypatch, datetime.combine(use_by, time(19, 0)))      # the day after, in India
    assert inventory.expire_stock(db, 1) == 6
