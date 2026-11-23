"""Opening a hub at a site (POST /v1/admin/stores): the hub, its shelves, its delivery zone and its logins arrive
together, and Bhilai, which the demo data leaves without a hub, starts working once it has one."""
from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app import auth, config, seed
from app.main import app
from app.models import Bin, EventLog, Staff, StockLevel, Store, StoreZone, User, utcnow
from app.modules.farms import service as farms
from tests.conftest import assert_stock_is_consistent

CIVIC_CENTRE = (21.1938, 81.3509)        # the centre of Bhilai
SUPELA = (21.207, 81.344)                # 1.6 km from it
RISALI = (21.165, 81.34)                 # 3.4 km from it: outside a 3 km hub
FARM_NEAR_BHILAI = (21.10, 81.45)        # about 15 km south-east of the centre
RAIPUR = (21.2514, 81.6296)              # 30 km east: not Bhilai
TODAY = (utcnow() + farms.LOCAL).date()


def open_hub(client, name="BH-01 Civic Centre", where=CIVIC_CENTRE, **extra):
    return client.post("/v1/admin/stores", json={"name": name, "lat": where[0], "lng": where[1], **extra})


@pytest.fixture()
def farmer(db):
    user = User(email="farmer@example.com", role="farmer", name="Test farmer")
    db.add(user)
    db.commit()
    return TestClient(app, headers={"Authorization": f"Bearer {auth.make_user_token(user.id, 'farmer')}"})


def test_a_hub_opens_with_its_city_radius_shelves_zone_and_logins(client, db):
    res = open_hub(client)

    assert res.status_code == 201, res.text
    hub = res.json()
    assert (hub["city"], hub["radius_km"], hub["status"], hub["bins"]) == ("bhilai", 3.0, "open", 18)
    assert hub["zone_cells"] > 0
    assert hub["logins"] == [f"{role}{hub['store_id']}" for role in ("picker", "packer", "receiver", "manager")]
    zones = {zone for (zone,) in db.execute(select(Bin.zone).where(Bin.store_id == hub["store_id"])).all()}
    assert zones == {"ambient", "chilled", "frozen"}
    assert db.scalar(select(func.count()).select_from(StockLevel).where(StockLevel.store_id == hub["store_id"])) == 0
    event = db.scalar(select(EventLog).where(EventLog.type == "store.opened"))
    assert (event.store_id, event.payload["city"], event.payload["by"]) == (hub["store_id"], "bhilai", "test-admin")
    cities = {c["city"]: c["hubs"] for c in client.get("/v1/cities").json()}
    assert cities == {"bangalore": 2, "bhilai": 1}
    assert_stock_is_consistent()


def test_an_address_in_the_new_zone_is_served_and_one_outside_it_is_not(client):
    before = client.get("/v1/serviceability", params={"lat": SUPELA[0], "lng": SUPELA[1]}).json()
    hub = open_hub(client).json()

    inside = client.get("/v1/serviceability", params={"lat": SUPELA[0], "lng": SUPELA[1]}).json()
    outside = client.get("/v1/serviceability", params={"lat": RISALI[0], "lng": RISALI[1]}).json()

    assert before["serviceable"] is False
    assert (inside["serviceable"], inside["store_id"]) == (True, hub["store_id"])
    assert outside["serviceable"] is False


def test_the_new_hubs_staff_can_log_in_and_work_only_there(client, db):
    hub = open_hub(client).json()

    login = TestClient(app).post("/v1/auth/login", json={"username": hub["logins"][2],        # the receiver
                                                         "password": config.DEMO_PASSWORD})

    assert login.status_code == 200, login.text
    receiver = TestClient(app, headers={"Authorization": f"Bearer {login.json()['access_token']}"})
    assert receiver.get(f"/v1/stores/{hub['store_id']}/expected-drops").json() == []
    assert receiver.get("/v1/stores/1/expected-drops").status_code == 403
    assert db.scalar(select(Staff.role).where(Staff.username == hub["logins"][0])) == "picker"


def test_a_lot_listed_near_bhilai_goes_to_its_hub_once_it_has_one(client, db, farmer):
    seed.add_produce(db)
    db.commit()
    onion = next(i["item_id"] for i in client.get("/v1/produce-items").json() if i["name"] == "Onion")
    farm = farmer.post("/v1/farms", json={"name": "Sahu Farm", "lat": FARM_NEAR_BHILAI[0],
                                          "lng": FARM_NEAR_BHILAI[1]}).json()
    listing = {"farm_id": farm["farm_id"], "item_id": onion, "qty_kg": 30, "price_per_kg": 22,
               "harvest_date": TODAY.isoformat()}
    refused = farmer.post("/v1/listings", json=listing)

    hub = open_hub(client).json()
    accepted = farmer.post("/v1/listings", json=listing)

    assert (refused.status_code, refused.json()["error"]["code"]) == (409, "no_hub_with_room")
    assert accepted.status_code == 201, accepted.text
    assert (accepted.json()["store_id"], accepted.json()["hub"]) == (hub["store_id"], "BH-01 Civic Centre")


def test_a_lot_taken_in_at_the_new_hub_is_on_sale_there(client, db, farmer):
    seed.add_produce(db)
    db.commit()
    hub = open_hub(client).json()
    onion = next(i["item_id"] for i in client.get("/v1/produce-items").json() if i["name"] == "Onion")
    farm = farmer.post("/v1/farms", json={"name": "Sahu Farm", "lat": FARM_NEAR_BHILAI[0],
                                          "lng": FARM_NEAR_BHILAI[1]}).json()
    listing = farmer.post("/v1/listings", json={"farm_id": farm["farm_id"], "item_id": onion, "qty_kg": 30,
                                                "price_per_kg": 22, "harvest_date": TODAY.isoformat()}).json()

    intake = client.post(f"/v1/listings/{listing['listing_id']}/intake",
                         json={"received_kg": 30, "rejected_kg": 0, "grade": "A"}).json()
    receipt = intake["receipt"]["receipt_id"]
    for task in client.get(f"/v1/goods-receipts/{receipt}/putaway-tasks").json():
        put = client.post(f"/v1/goods-receipts/{receipt}/putaway", json={
            "sku_id": task["sku_id"], "batch_no": task["batch_no"], "bin_code": task["bin_code"], "qty": task["qty"]})
        assert put.status_code == 200, put.text

    shop = client.get(f"/v1/stores/{hub['store_id']}/availability").json()
    assert [(line["name"], line["atp"]) for line in shop] == [("Onion, 1 kg", 30)]
    assert_stock_is_consistent()


def test_the_city_can_be_named_and_the_radius_and_capacity_set(client, db):
    hub = open_hub(client, city="bhilai", radius_km=1.5, capacity_kg=800).json()

    assert (hub["city"], hub["radius_km"], hub["capacity_kg"]) == ("bhilai", 1.5, 800)
    supela = client.get("/v1/serviceability", params={"lat": SUPELA[0], "lng": SUPELA[1]}).json()
    assert supela["serviceable"] is False               # 1.6 km away, outside a 1.5 km radius


def test_a_site_outside_every_city_is_refused(client, db):
    res = open_hub(client, name="Raipur Hub", where=RAIPUR)

    assert (res.status_code, res.json()["error"]["code"]) == (422, "outside_city")
    assert res.json()["error"]["details"]["city"] == "bhilai"
    assert db.scalar(select(func.count()).select_from(Store)) == 2


def test_a_site_outside_the_city_named_is_refused_and_so_is_an_unknown_city(client):
    wrong_city = open_hub(client, city="bangalore")
    no_city = open_hub(client, city="atlantis")

    assert (wrong_city.status_code, wrong_city.json()["error"]["code"]) == (422, "outside_city")
    assert (no_city.status_code, no_city.json()["error"]["code"]) == (422, "unknown_city")


def test_the_same_site_twice_is_refused_and_so_is_a_name_already_used(client, db):
    open_hub(client)

    same_site = open_hub(client, name="BH-01 again", where=(CIVIC_CENTRE[0] + 0.001, CIVIC_CENTRE[1]))    # 110 m away
    same_name = open_hub(client, name="bh-01  civic centre", where=SUPELA)

    assert (same_site.status_code, same_site.json()["error"]["code"]) == (409, "hub_too_close")
    assert same_site.json()["error"]["details"]["name"] == "BH-01 Civic Centre"
    assert (same_name.status_code, same_name.json()["error"]["code"]) == (409, "name_taken")
    assert db.scalar(select(func.count()).select_from(Store)) == 3


def test_a_refused_site_leaves_the_zones_as_they_were(client, db):
    cells = db.scalar(select(func.count()).select_from(StoreZone))

    open_hub(client, name="Raipur Hub", where=RAIPUR)

    assert db.scalar(select(func.count()).select_from(StoreZone)) == cells


def test_a_new_hub_takes_only_the_cells_it_is_nearest_to(client, db):
    first = open_hub(client).json()
    alone = db.scalar(select(func.count()).select_from(StoreZone).where(StoreZone.store_id == first["store_id"]))

    second = open_hub(client, name="BH-02 Supela", where=SUPELA).json()

    shared = db.scalar(select(func.count()).select_from(StoreZone).where(StoreZone.store_id == first["store_id"]))
    assert 0 < shared < alone                                  # the newcomer took the cells nearer to it
    assert second["zone_cells"] > 0
    bangalore = db.scalar(select(func.count()).select_from(StoreZone).where(StoreZone.store_id.in_([1, 2])))
    assert bangalore > 0                                       # and the other city's zones are untouched


def test_a_retry_with_the_same_key_opens_one_hub(client, db):
    body = {"name": "BH-01 Civic Centre", "lat": CIVIC_CENTRE[0], "lng": CIVIC_CENTRE[1]}
    first = client.post("/v1/admin/stores", json=body, headers={"Idempotency-Key": "open-bh-01"})
    again = client.post("/v1/admin/stores", json=body, headers={"Idempotency-Key": "open-bh-01"})

    assert (first.status_code, again.status_code) == (201, 201)
    assert again.json() == first.json()
    assert db.scalar(select(func.count()).select_from(Store)) == 3


def test_only_an_admin_opens_a_hub(client_as):
    body = {"name": "BH-01 Civic Centre", "lat": CIVIC_CENTRE[0], "lng": CIVIC_CENTRE[1]}

    assert client_as("ops").post("/v1/admin/stores", json=body).status_code == 403
    assert client_as("manager", 1).post("/v1/admin/stores", json=body).status_code == 403
    assert TestClient(app).post("/v1/admin/stores", json=body).status_code == 401


@pytest.mark.parametrize("change", [{"name": "ab"}, {"name": "   "}, {"lat": 91}, {"radius_km": 0.1},
                                    {"radius_km": 50}, {"capacity_kg": 0}])
def test_a_malformed_request_is_refused(client, change):
    body = {"name": "BH-01 Civic Centre", "lat": CIVIC_CENTRE[0], "lng": CIVIC_CENTRE[1], **change}

    assert client.post("/v1/admin/stores", json=body).status_code == 422


def test_the_demo_setting_opens_bhilais_hubs_once(client, db, monkeypatch):
    monkeypatch.setattr(config, "DEMO_HUBS", True)

    opened = seed.add_demo_hubs(db)
    db.commit()
    again = seed.add_demo_hubs(db)

    assert (opened, again) == (3, 0)
    names = [s["name"] for s in client.get("/v1/stores", params={"city": "bhilai"}).json()]
    assert names == ["BH-01 Civic Centre", "BH-02 Nehru Nagar", "BH-03 Durg"]
    served = {area: client.get("/v1/serviceability", params={"lat": lat, "lng": lng}).json()["serviceable"]
              for area, (lat, lng) in {"Civic Centre": CIVIC_CENTRE, "Supela": SUPELA, "Nehru Nagar": (21.209, 81.326),
                                       "Smriti Nagar": (21.219, 81.318), "Durg Station Road": (21.1904, 81.2849),
                                       "Risali": RISALI, "Kumhari": (21.266, 81.519)}.items()}
    assert served == {"Civic Centre": True, "Supela": True, "Nehru Nagar": True, "Smriti Nagar": True,
                      "Durg Station Road": True, "Risali": False, "Kumhari": False}
    assert db.scalar(select(func.count()).select_from(Staff).where(Staff.username == "receiver3")) == 1


def test_a_database_seeded_before_bhilai_had_hubs_gets_them_at_the_next_start(db, monkeypatch):
    monkeypatch.setattr(config, "DEMO_HUBS", True)

    seeded = seed.seed_if_empty(db)

    assert seeded is False
    assert db.scalar(select(func.count()).select_from(Store)) == 5
    assert isinstance(db.scalar(select(EventLog.ts).where(EventLog.type == "store.opened").limit(1)), datetime)
