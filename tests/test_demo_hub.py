"""The demo hub (app/demo_hub.py): an order no picker has started is picked and packed by the app itself, the way a
picker would, so a demo run from phones alone reaches delivery."""
from datetime import timedelta

from sqlalchemy import select

from app import background, config, demo_hub
from app.models import FulfilmentJob, PickTask, StockItem, utcnow
from app.modules.orders import service as orders
from tests.conftest import assert_stock_is_consistent, atp, place_paid_order
from tests.test_delivery import customer, on_duty, person, status, trip  # noqa: F401  (fixtures and helpers)
from tests.test_orders import hold, place


def waited(db, order_id: str, seconds: float) -> None:
    """Make it look as if this order was paid `seconds` ago."""
    job = db.scalar(select(FulfilmentJob).where(FulfilmentJob.order_id == order_id))
    job.created_at = utcnow() - timedelta(seconds=seconds)
    db.commit()


def test_an_order_nobody_starts_is_picked_and_packed_like_a_pickers(customer, client, sku, db):
    milk, rice = sku("Toned milk"), sku("Basmati rice")
    before = atp(client, 1, milk)
    assert place(customer, hold(customer, "F2H-AUTO", [(milk, 8), (rice, 1)])).status_code == 201

    too_soon = demo_hub.pack_waiting(db)
    waited(db, "F2H-AUTO", config.DEMO_AUTOPACK_SECONDS + 1)
    packed = demo_hub.pack_waiting(db)

    assert (too_soon, packed) == ([], ["F2H-AUTO"])
    job = db.scalar(select(FulfilmentJob).where(FulfilmentJob.order_id == "F2H-AUTO"))
    db.refresh(job)
    assert (job.state, job.picker_id, job.crate_slot) == ("packed", demo_hub.PICKER, "S-01")
    assert {task.status for task in job.tasks} == {"picked"}
    order = customer.get("/v1/orders/F2H-AUTO").json()
    assert (order["status"], order["total"]) == ("packed", 316.0)       # six at the rescue price, as a picker's
    # oldest batch first: the six that expire tomorrow all went
    assert db.scalar(select(StockItem.qty).where(StockItem.sku_id == milk, StockItem.batch_no == "M-OLD")) == 0
    assert atp(client, 1, milk) == before - 8
    assert_stock_is_consistent()


def test_an_order_a_person_has_started_is_left_to_them(customer, client, sku, db):
    assert place(customer, hold(customer, "F2H-THEIRS", [(sku("Toned milk"), 1)])).status_code == 201
    waited(db, "F2H-THEIRS", 600)
    claimed = client.get("/v1/pickers/picker1/next-task", params={"store_id": 1}).json()["job"]

    assert demo_hub.pack_waiting(db) == []
    job = db.get(FulfilmentJob, claimed["job_id"])
    db.refresh(job)
    assert (job.state, job.picker_id) == ("picking", "picker1")


def test_each_packed_bag_gets_a_crate_slot_of_its_own(client, sku, db):
    for n in (1, 2, 3):
        place_paid_order(client, f"desk-{n}", 1, [(sku("Toned milk"), 1)])
        waited(db, f"desk-{n}", 600)

    assert demo_hub.pack_waiting(db) == ["desk-1", "desk-2", "desk-3"]
    slots = db.scalars(select(FulfilmentJob.crate_slot).order_by(FulfilmentJob.id)).all()
    assert slots == ["S-01", "S-02", "S-03"]


def test_a_batch_that_expired_after_payment_is_not_packed(customer, client, sku, db):
    """The demo hub presses Not on shelf where a picker would: the line moves to a batch that can be sold."""
    milk = sku("Toned milk")
    assert place(customer, hold(customer, "F2H-OLD", [(milk, 2)])).status_code == 201
    waited(db, "F2H-OLD", 600)
    old = db.scalar(select(StockItem).where(StockItem.sku_id == milk, StockItem.batch_no == "M-OLD"))
    old.expiry_date = old.expiry_date - timedelta(days=5)
    db.commit()

    assert demo_hub.pack_waiting(db) == ["F2H-OLD"]
    picked = db.scalars(select(PickTask).join(FulfilmentJob, FulfilmentJob.id == PickTask.job_id)
                        .where(FulfilmentJob.order_id == "F2H-OLD", PickTask.status == "picked")).all()
    assert [(task.stock_item.batch_no, task.qty) for task in picked] == [("M-NEW", 2)]
    assert_stock_is_consistent()


def test_work_it_had_claimed_and_not_finished_is_finished(client, sku, db):
    place_paid_order(client, "desk-1", 1, [(sku("Toned milk"), 1)])
    job = db.scalar(select(FulfilmentJob).where(FulfilmentJob.order_id == "desk-1"))
    job.state, job.picker_id = "picking", demo_hub.PICKER               # the app stopped between claim and pack
    db.commit()

    assert demo_hub.pack_waiting(db) == ["desk-1"]


def test_with_an_agent_on_duty_an_order_goes_from_paid_to_the_door_with_nobody_at_the_hub(
        customer, person, sku, db, monkeypatch):
    monkeypatch.setattr(config, "POOL_MAX_WAIT_MINUTES", 0)
    agent = person("agent", "Kiran")
    on_duty(agent)
    assert place(customer, hold(customer, "F2H-PHONES", [(sku("Toned milk"), 1)])).status_code == 201
    waited(db, "F2H-PHONES", 600)

    assert background.demo_hub_once() == ["F2H-PHONES"]

    assert status(customer, "F2H-PHONES") == "pooled"
    assert agent.post("/v1/agent/trip/bags/F2H-PHONES/load").json()["status"] == "out"
    done = agent.post("/v1/agent/trip/stops/F2H-PHONES/deliver", json={"code": orders.door_code("F2H-PHONES")})
    assert (done.status_code, status(customer, "F2H-PHONES")) == (200, "delivered")
    assert trip(agent) is None


def test_the_timed_job_runs_only_when_the_setting_is_on(monkeypatch):
    monkeypatch.setattr(config, "DEMO_AUTOPACK", False)
    assert background.demo_hub_loop not in background.loops()
    monkeypatch.setattr(config, "DEMO_AUTOPACK", True)
    assert background.demo_hub_loop in background.loops()
