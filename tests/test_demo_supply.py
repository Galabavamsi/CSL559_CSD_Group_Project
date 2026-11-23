"""Demo farms (app/demo_supply.py): lots that arrive without a farmer, through the hub's ordinary intake, so a
hosted demo's shops are never empty. And the hub that serves IIT Bhilai."""
from datetime import timedelta

import pytest
from sqlalchemy import func, select, text

from app import background, clock, config, demo_supply, seed
from app.db import SessionLocal
from app.models import SKU, Farm, Listing, QualityCheck, Store, User
from tests.conftest import assert_stock_is_consistent, place_paid_order

IIT_BHILAI = (21.2444, 81.3176)
BHILAI_FARMS = {name for name, _lat, _lng in demo_supply.FARMS["bhilai"]}


@pytest.fixture()
def hubs(db):
    """The demo's produce, and Bhilai's hubs. Returns {hub name: id} for Bhilai."""
    seed.add_produce(db)
    seed.add_demo_hubs(db)
    db.commit()
    return dict(db.execute(select(Store.name, Store.id).where(Store.name.like("BH-%"))).all())


def shop(client, store_id: int) -> dict[str, dict]:
    return {row["name"]: row for row in client.get(f"/v1/stores/{store_id}/shop").json()}


def test_iit_bhilai_has_its_own_hub(client, hubs):
    here = client.get("/v1/serviceability", params={"lat": IIT_BHILAI[0], "lng": IIT_BHILAI[1]}).json()

    assert (here["serviceable"], here["store"], here["store_id"]) == (True, "BH-04 IIT Bhilai", hubs["BH-04 IIT Bhilai"])
    assert here["distance_km"] < 1.0
    assert shop(client, here["store_id"]) == {}                 # a hub nobody has delivered to has nothing to sell


def test_every_bhilai_hub_gets_every_item_through_the_ordinary_intake(client, db, hubs):
    arrived = demo_supply.top_up(db)

    today = clock.today()
    for name, store_id in hubs.items():
        listed = shop(client, store_id)
        assert sorted(listed) == sorted(demo_supply.LOTS), name
        assert all(row["atp"] > 0 for row in listed.values()), name
    tomato = shop(client, hubs["BH-04 IIT Bhilai"])["Tomato"]
    assert (tomato["unit_label"], tomato["atp"], tomato["rescue"]) == ("500 g", 23, None)     # 12 kg less 0.5 turned away
    assert tomato["batch"]["farm"] in BHILAI_FARMS
    assert (tomato["batch"]["grade"], tomato["batch"]["harvest_date"], tomato["batch"]["use_by"]) == (
        "A", today.isoformat(), (today + timedelta(days=5)).isoformat())
    assert shop(client, hubs["BH-01 Civic Centre"])["Cauliflower"]["batch"]["grade"] == "B"
    # every lot has a listing and the hub's quality check, like a farmer's
    lots = db.scalar(select(func.count()).select_from(Listing))
    assert lots == len(arrived) >= 4 * len(demo_supply.LOTS)
    assert db.scalar(select(func.count()).select_from(Listing).where(Listing.status != "received")) == 0
    assert db.scalar(select(func.count()).select_from(QualityCheck)) == lots
    assert_stock_is_consistent()


def test_spinach_comes_a_day_old_so_the_shop_always_has_a_rescue_price_to_show(client, db, hubs):
    demo_supply.top_up(db)

    spinach = shop(client, hubs["BH-04 IIT Bhilai"])["Spinach"]

    assert spinach["batch"]["use_by"] == (clock.today() + timedelta(days=1)).isoformat()
    assert spinach["rescue"] == {"price": 15.0, "units": spinach["atp"]}       # 22 less 30%, whole rupees


def test_a_hub_with_enough_is_left_alone_and_one_that_runs_low_gets_one_more_lot(client, db, hubs):
    demo_supply.top_up(db)
    hub = hubs["BH-02 Nehru Nagar"]
    tomato = db.scalar(select(SKU.id).where(SKU.name.like("Tomato%"), SKU.unit_grams == 500))

    assert demo_supply.top_up(db) == []

    place_paid_order(client, "desk-1", hub, [(tomato, 20)])                     # 3 of 23 left: under the minimum
    again = demo_supply.top_up(db)

    assert [(lot["store"], lot["item"], lot["units"]) for lot in again] == [("BH-02 Nehru Nagar", "Tomato", 23)]
    assert shop(client, hub)["Tomato"]["atp"] == 26
    assert_stock_is_consistent()


def test_produce_that_runs_low_is_not_reordered_from_the_warehouse(client, db, hubs):
    """The reorder job raises a truck from the warehouse for anything under its reorder point. Farm produce does
    not come from a warehouse: without this rule every hub would wait for trucks of tomatoes that never arrive."""
    demo_supply.top_up(db)
    hub = hubs["BH-03 Durg"]
    tomato = db.scalar(select(SKU.id).where(SKU.name.like("Tomato%"), SKU.unit_grams == 500))
    place_paid_order(client, "desk-1", hub, [(tomato, 20)])                     # 3 left, far under the reorder point

    res = client.post("/v1/replenishment/run", params={"store_id": hub})

    assert res.status_code == 200, res.text
    assert res.json()["transfer_order"] is None


def test_the_demo_farms_belong_to_an_account_nobody_can_sign_in_to(client, db, hubs):
    demo_supply.top_up(db)

    farmer = db.scalar(select(User).where(User.email == demo_supply.DEMO_FARMER_EMAIL))
    asked = client.post("/v1/auth/otp/request", json={"email": demo_supply.DEMO_FARMER_EMAIL, "role": "farmer"})

    assert farmer.role == "farmer"
    assert db.scalar(select(func.count()).select_from(Farm).where(Farm.farmer_id == farmer.id)) == sum(
        len(farms) for farms in demo_supply.FARMS.values())
    assert (asked.status_code, asked.json()["error"]["code"]) == (422, "bad_email")


def test_only_one_top_up_runs_at_a_time(db, hubs):
    with SessionLocal() as other:
        other.execute(text("select pg_advisory_xact_lock(:key)"), {"key": demo_supply.LOCK})

        assert demo_supply.top_up(db) == []                    # another app instance is at it
        other.rollback()

    assert len(demo_supply.top_up(db)) > 0


def test_an_admin_can_have_the_farms_deliver_now(client, client_as, hubs):
    assert client_as("manager", 1).post("/v1/admin/demo-supply").status_code == 403

    res = client.post("/v1/admin/demo-supply")

    assert res.status_code == 200, res.text
    assert len(res.json()["arrived"]) >= 4 * len(demo_supply.LOTS)
    assert client.post("/v1/admin/demo-supply").json() == {"arrived": []}


def test_the_timed_job_runs_only_when_the_setting_is_on(monkeypatch):
    monkeypatch.setattr(config, "DEMO_SUPPLY", False)
    assert background.demo_supply_loop not in background.loops()
    monkeypatch.setattr(config, "DEMO_SUPPLY", True)
    assert background.demo_supply_loop in background.loops()


def test_with_no_produce_in_the_catalogue_nothing_arrives(db):
    assert demo_supply.top_up(db) == []
