"""Farm supply (HLD flow A): a farmer lists produce, a hub is chosen and a drop slot given, and the hub weighs,
grades and packs the lot when it arrives. Farmers deal in kg; stock is whole units."""
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import auth, config, seed
from app.main import app
from app.models import SKU, EventLog, Listing, ProduceItem, QualityCheck, StockItem, Store, User, utcnow
from app.modules.farms import service as farms
from tests.conftest import assert_stock_is_consistent, atp

SOUTH_OF_CENTRAL = (12.80, 77.59)        # 19 km from DS-01 Central (hub 1), 26 km from DS-02 North (hub 2)
NORTH_OF_NORTH = (13.20, 77.60)          # 18 km from DS-02 North (hub 2), 25 km from DS-01 Central
BHILAI = (21.1938, 81.3509)              # 990 km from either
TODAY = (utcnow() + farms.LOCAL).date()  # the date in the cities


@pytest.fixture()
def produce(db):
    """The produce catalogue, and a way to look things up in it by name."""
    seed.add_produce(db)
    db.commit()

    class Catalogue:
        @staticmethod
        def item(name: str) -> int:
            return db.scalar(select(ProduceItem.id).where(ProduceItem.name == name))

        @staticmethod
        def unit(name: str) -> int:
            return db.scalar(select(SKU.id).where(SKU.name == name))
    return Catalogue


@pytest.fixture()
def as_user(db):
    """as_user("farmer") is a client signed in as a new app user with that role."""
    made = []

    def sign_in(role: str, email: str | None = None) -> TestClient:
        user = User(email=email or f"{role}{len(made) + 1}@example.com", role=role, name=f"Test {role}")
        db.add(user)
        db.commit()
        client = TestClient(app, headers={"Authorization": f"Bearer {auth.make_user_token(user.id, role)}"})
        made.append(client)
        return client
    return sign_in


@pytest.fixture()
def farmer(as_user):
    return as_user("farmer")


def a_farm(client, where=SOUTH_OF_CENTRAL, **extra) -> dict:
    res = client.post("/v1/farms", json={"name": "Green Acres", "lat": where[0], "lng": where[1], **extra})
    assert res.status_code == 201, res.text
    return res.json()


def list_it(client, farm, item_id, qty_kg=20, harvest=None, price=18.0, key=None):
    return client.post("/v1/listings", headers={"Idempotency-Key": key} if key else {},
                       json={"farm_id": farm["farm_id"], "item_id": item_id, "qty_kg": qty_kg,
                             "price_per_kg": price, "harvest_date": (harvest or TODAY).isoformat()})


def take_in(client, listing_id, received_kg=20, rejected_kg=0, grade="A", **extra):
    return client.post(f"/v1/listings/{listing_id}/intake",
                       json={"received_kg": received_kg, "rejected_kg": rejected_kg, "grade": grade, **extra})


def put_everything_away(client, receipt_id) -> None:
    for task in client.get(f"/v1/goods-receipts/{receipt_id}/putaway-tasks").json():
        res = client.post(f"/v1/goods-receipts/{receipt_id}/putaway", json={
            "sku_id": task["sku_id"], "batch_no": task["batch_no"], "bin_code": task["bin_code"], "qty": task["qty"]})
        assert res.status_code == 200, res.text
    assert client.post(f"/v1/goods-receipts/{receipt_id}/close").status_code == 200


# --------------------------------------------------------------------------- the catalogue of produce

def test_produce_items_list_the_units_customers_buy_them_in(client, produce):
    items = {item["name"]: item for item in client.get("/v1/produce-items").json()}

    assert len(items) == 12
    tomato = items["Tomato"]
    assert (tomato["family"], tomato["storage_type"], tomato["shelf_life_days"]) == ("vegetables", "chilled", 5)
    assert [(u["unit_label"], u["unit_grams"]) for u in tomato["units"]] == [("500 g", 500), ("1 kg", 1000)]
    assert items["Cauliflower"]["units"][0]["unit_label"] == "1 piece (400-600 g)"


def test_adding_produce_twice_adds_it_once_and_leaves_the_old_catalogue_alone(db, produce):
    assert seed.add_produce(db) == 0
    assert db.scalar(select(SKU.id).where(SKU.name == "Toned milk 500 ml", SKU.item_id.is_(None))) is not None


# --------------------------------------------------------------------------- farms

def test_a_farmer_registers_a_farm_and_is_told_the_nearest_hub(farmer, produce):
    farm = a_farm(farmer, area_acres=3.5)

    assert farm["nearest_hub"]["name"] == "DS-01 Central" and 18 < farm["nearest_hub"]["distance_km"] < 20
    assert farm["rejection_rate_30d"] is None                      # nothing delivered yet
    assert [f["farm_id"] for f in farmer.get("/v1/farms").json()] == [farm["farm_id"]]


def test_a_farm_far_from_every_hub_is_registered_with_no_hub_in_reach(farmer, produce):
    assert a_farm(farmer, BHILAI)["nearest_hub"] is None


def test_a_gps_fix_rougher_than_50_m_is_not_kept_but_a_hand_placed_pin_is(farmer):
    rough = farmer.post("/v1/farms", json={"name": "F", "lat": 12.8, "lng": 77.59, "accuracy_m": 80})

    assert rough.status_code == 422 and rough.json()["error"]["code"] == "location_too_rough"
    assert a_farm(farmer, accuracy_m=30)["farm_id"]
    assert a_farm(farmer)["farm_id"]                               # no accuracy sent: a pin placed by hand


def test_farmers_see_only_their_own_farms_and_only_farmers_have_farms(farmer, as_user, client):
    a_farm(farmer)
    other = as_user("farmer")

    assert other.get("/v1/farms").json() == []
    assert as_user("customer").post("/v1/farms", json={"name": "F", "lat": 12.8, "lng": 77.59}).status_code == 403
    assert client.get("/v1/farms").status_code == 403              # hub staff are not farmers


# --------------------------------------------------------------------------- listing: the hub and the slot

def test_a_listing_goes_to_the_nearest_hub_and_gets_the_next_morning_slot(farmer, produce, db):
    farm = a_farm(farmer, NORTH_OF_NORTH)

    res = list_it(farmer, farm, produce.item("Tomato"), qty_kg=20)

    assert res.status_code == 201, res.text
    listing = res.json()
    assert (listing["hub"], listing["status"], listing["qty_kg"]) == ("DS-02 North", "listed", 20.0)
    assert 17 < listing["hub_distance_km"] < 19 and listing["quality_check"] is None
    start = datetime.fromisoformat(listing["drop_from"].rstrip("Z")) + farms.LOCAL
    assert start.hour == config.INTAKE_START_HOUR and start > utcnow() + farms.LOCAL       # a morning still to come
    assert listing["drop_until"] > listing["drop_from"]
    event = db.scalar(select(EventLog).where(EventLog.type == "listing.created"))
    assert event.store_id == listing["store_id"] and event.payload["listing_id"] == listing["listing_id"]


def test_the_drop_slot_is_this_morning_before_it_opens_tomorrow_after_and_never_before_the_harvest():
    early = datetime(2026, 11, 23, 0, 0) - farms.LOCAL + timedelta(hours=5)        # 05:00 in the cities, as UTC
    midday = datetime(2026, 11, 23, 0, 0) - farms.LOCAL + timedelta(hours=12)

    def local_start(now, harvest):
        return farms.next_drop_slot(now, harvest)[0] + farms.LOCAL

    assert local_start(early, date(2026, 11, 22)) == datetime(2026, 11, 23, 6)
    assert local_start(midday, date(2026, 11, 22)) == datetime(2026, 11, 24, 6)
    assert local_start(midday, date(2026, 11, 26)) == datetime(2026, 11, 26, 6)      # harvested later: dropped then
    start, end = farms.next_drop_slot(midday, date(2026, 11, 22))
    assert end - start == timedelta(hours=config.INTAKE_HOURS)


def test_a_full_hub_is_passed_over_for_the_next_nearest(farmer, produce, db):
    farm = a_farm(farmer, NORTH_OF_NORTH)
    db.get(Store, 2).capacity_kg = 10
    db.commit()

    listing = list_it(farmer, farm, produce.item("Tomato"), qty_kg=20).json()

    assert listing["hub"] == "DS-01 Central" and 24 < listing["hub_distance_km"] < 26


def test_lots_on_their_way_count_against_a_hubs_room(farmer, produce, db):
    farm = a_farm(farmer)
    db.get(Store, 1).capacity_kg = 30
    db.commit()

    first = list_it(farmer, farm, produce.item("Onion"), qty_kg=20).json()
    second = list_it(farmer, farm, produce.item("Onion"), qty_kg=20).json()

    assert (first["hub"], second["hub"]) == ("DS-01 Central", "DS-02 North")       # 20 + 20 does not fit in 30


def test_when_no_hub_can_take_the_lot_the_farmer_is_told_why(farmer, produce, db):
    farm = a_farm(farmer)
    for store_id in (1, 2):
        db.get(Store, store_id).capacity_kg = 5
    db.commit()

    res = list_it(farmer, farm, produce.item("Tomato"), qty_kg=20)

    assert res.status_code == 409 and res.json()["error"]["code"] == "no_hub_with_room"
    assert [hub["store"] for hub in res.json()["error"]["details"]["hubs"]] == ["DS-01 Central", "DS-02 North"]
    assert all("room for 5.0 kg only" in hub["reason"] for hub in res.json()["error"]["details"]["hubs"])


def test_a_farm_with_no_hub_within_reach_cannot_list(farmer, produce):
    res = list_it(farmer, a_farm(farmer, BHILAI), produce.item("Tomato"))

    assert res.status_code == 409 and res.json()["error"]["details"]["hubs"] == []


def test_a_closed_hub_takes_no_listings(farmer, produce, db):
    db.get(Store, 1).status = "closed"
    db.commit()

    assert list_it(farmer, a_farm(farmer), produce.item("Tomato")).json()["hub"] == "DS-02 North"


def test_produce_that_would_arrive_too_old_cannot_be_listed(farmer, produce):
    farm = a_farm(farmer)

    stale = list_it(farmer, farm, produce.item("Spinach"), harvest=TODAY - timedelta(days=2))   # keeps 2 days
    fresh = list_it(farmer, farm, produce.item("Spinach"), harvest=TODAY)

    assert stale.status_code == 422 and stale.json()["error"]["code"] == "too_old"
    assert fresh.status_code == 201


def test_a_harvest_too_far_ahead_cannot_be_listed_and_a_near_one_is_dropped_on_its_day(farmer, produce):
    farm = a_farm(farmer)

    far = list_it(farmer, farm, produce.item("Onion"), harvest=TODAY + timedelta(days=8))
    soon = list_it(farmer, farm, produce.item("Onion"), harvest=TODAY + timedelta(days=3))

    assert far.status_code == 422 and far.json()["error"]["code"] == "too_far_ahead"
    start = datetime.fromisoformat(soon.json()["drop_from"].rstrip("Z")) + farms.LOCAL
    assert start.date() == TODAY + timedelta(days=3)


def test_a_retried_listing_is_made_once(farmer, produce, db):
    farm = a_farm(farmer)

    first = list_it(farmer, farm, produce.item("Tomato"), key="list-1")
    again = list_it(farmer, farm, produce.item("Tomato"), key="list-1")

    assert again.json() == first.json()
    assert len(db.scalars(select(Listing)).all()) == 1
    assert list_it(farmer, farm, produce.item("Onion"), key="list-1").json()["error"]["code"] == "idempotency_key_reused"


def test_a_listing_is_only_for_ones_own_farm_and_a_known_item(farmer, as_user, produce):
    farm = a_farm(farmer)

    assert list_it(as_user("farmer"), farm, produce.item("Tomato")).status_code == 404
    assert list_it(farmer, farm, 9999).status_code == 404
    assert list_it(farmer, farm, produce.item("Tomato"), qty_kg=0).status_code == 422
    assert list_it(farmer, farm, produce.item("Tomato"), qty_kg=config.LISTING_MAX_KG + 1).status_code == 422


def test_a_farmer_withdraws_a_listing_and_the_hub_gets_its_room_back(farmer, as_user, produce, db):
    farm = a_farm(farmer)
    listing = list_it(farmer, farm, produce.item("Tomato"), qty_kg=20).json()

    assert as_user("farmer").post(f"/v1/listings/{listing['listing_id']}/cancel").status_code == 404
    cancelled = farmer.post(f"/v1/listings/{listing['listing_id']}/cancel")

    assert cancelled.json()["status"] == "cancelled" and farms.used_capacity_g(db, 1) == 0
    assert farmer.post(f"/v1/listings/{listing['listing_id']}/cancel").json()["status"] == "cancelled"   # again: no error
    assert [row["status"] for row in farmer.get("/v1/listings").json()] == ["cancelled"]


# --------------------------------------------------------------------------- at the hub: weigh, grade, pack

@pytest.fixture()
def tomatoes(farmer, produce):
    """20 kg of tomatoes listed for hub 1, harvested today."""
    return list_it(farmer, a_farm(farmer), produce.item("Tomato"), qty_kg=20).json()


def test_the_hub_sees_the_lots_on_their_way_and_only_its_own(tomatoes, client_as):
    with client_as("receiver", 1) as receiver, client_as("receiver", 2) as elsewhere:
        mine = receiver.get("/v1/stores/1/expected-drops")

        assert [(d["item"], d["qty_kg"], d["farmer"]) for d in mine.json()] == [("Tomato", 20.0, "Test farmer")]
        assert elsewhere.get("/v1/stores/1/expected-drops").status_code == 403
        assert elsewhere.get("/v1/stores/2/expected-drops").json() == []


def test_accepted_kilograms_become_whole_units_on_the_dock_and_sellable_once_put_away(tomatoes, farmer, client, produce,
                                                                                    db):
    unit = produce.unit("Tomato, 500 g")

    res = take_in(client, tomatoes["listing_id"], received_kg=19.5, rejected_kg=1.5, grade="A", remarks="firm, clean")

    assert res.status_code == 200, res.text
    intake = res.json()
    check = intake["quality_check"]
    assert (check["grade"], check["received_kg"], check["accepted_kg"], check["rejected_kg"], check["trim_kg"]) == \
        ("A", 19.5, 18.0, 1.5, 0.0)
    assert (intake["status"], intake["shortfall_kg"]) == ("received", 0.5)          # 20 kg listed, 19.5 arrived
    assert intake["packed"] == [{"sku_id": unit, "sku": "Tomato, 500 g", "units": 36}]
    (line,) = intake["receipt"]["lines"]
    assert (line["on_dock"], line["batch_no"]) == (36, f"L{tomatoes['listing_id']}")
    assert line["expiry_date"] == (TODAY + timedelta(days=5)).isoformat()            # harvest date + shelf life
    on_sale = client.get("/v1/stores/1/availability", params={"skus": str(unit)}).json()
    assert on_sale == []                                                             # on the dock is not on sale

    put_everything_away(client, intake["receipt"]["receipt_id"])

    assert atp(client, 1, unit) == 36
    assert db.scalar(select(StockItem.batch_no).where(StockItem.sku_id == unit)) == f"L{tomatoes['listing_id']}"
    assert farms.used_capacity_g(db, 1) == 18_000                                    # the lot is now stock, not "coming"
    assert_stock_is_consistent()
    mine = farmer.get("/v1/listings").json()[0]["quality_check"]                     # the farmer sees the result
    assert (mine["accepted_kg"], mine["rejected_kg"], mine["remarks"]) == (18.0, 1.5, "firm, clean")
    assert farmer.get("/v1/farms").json()[0]["rejection_rate_30d"] == round(1.5 / 19.5, 3)


def test_weight_that_does_not_fill_a_last_unit_is_trim(tomatoes, client):
    intake = take_in(client, tomatoes["listing_id"], received_kg=10.3).json()

    assert intake["packed"][0]["units"] == 20 and intake["quality_check"]["trim_kg"] == 0.3


def test_the_receiver_can_choose_how_to_pack_the_lot(tomatoes, client, produce):
    half, whole = produce.unit("Tomato, 500 g"), produce.unit("Tomato, 1 kg")

    intake = take_in(client, tomatoes["listing_id"], received_kg=10.3,
                     packs=[{"sku_id": half, "units": 10}, {"sku_id": whole, "units": 5}]).json()

    assert {(p["sku"], p["units"]) for p in intake["packed"]} == {("Tomato, 500 g", 10), ("Tomato, 1 kg", 5)}
    assert intake["quality_check"]["trim_kg"] == 0.3
    assert sorted(line["on_dock"] for line in intake["receipt"]["lines"]) == [5, 10]


def test_packs_cannot_weigh_more_than_was_accepted_or_be_units_of_something_else(tomatoes, client, produce, db):
    half = produce.unit("Tomato, 500 g")

    heavy = take_in(client, tomatoes["listing_id"], received_kg=10, packs=[{"sku_id": half, "units": 21}])
    wrong = take_in(client, tomatoes["listing_id"], received_kg=10,
                    packs=[{"sku_id": produce.unit("Onion, 1 kg"), "units": 1}])

    assert heavy.status_code == 422 and heavy.json()["error"]["code"] == "packs_exceed_weight"
    assert wrong.status_code == 422 and wrong.json()["error"]["code"] == "wrong_unit"
    assert db.get(Listing, tomatoes["listing_id"]).status == "listed"                # a refused intake changes nothing
    assert db.scalars(select(QualityCheck)).all() == []


def test_a_rejected_lot_is_recorded_and_stocks_nothing(tomatoes, farmer, client):
    intake = take_in(client, tomatoes["listing_id"], received_kg=20, grade="reject", remarks="rot").json()

    check = intake["quality_check"]
    assert (check["grade"], check["accepted_kg"], check["rejected_kg"], check["receipt_id"]) == ("reject", 0.0, 20.0, None)
    assert intake["receipt"] is None and intake["packed"] == []
    assert farmer.get("/v1/farms").json()[0]["rejection_rate_30d"] == 1.0


def test_the_weights_have_to_add_up(tomatoes, client):
    over = take_in(client, tomatoes["listing_id"], received_kg=22.5)                 # 20 kg listed; 10% over is fine
    more_rejected = take_in(client, tomatoes["listing_id"], received_kg=10, rejected_kg=11)
    nothing_left = take_in(client, tomatoes["listing_id"], received_kg=10, rejected_kg=10, grade="B")

    assert over.json()["error"]["code"] == "more_than_listed"
    assert more_rejected.json()["error"]["code"] == nothing_left.json()["error"]["code"] == "bad_weights"
    assert take_in(client, tomatoes["listing_id"], received_kg=21.9).status_code == 200


def test_a_lot_is_taken_in_once_even_by_two_receivers_at_the_same_moment(tomatoes, client, db):
    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = sorted(res.status_code for res in pool.map(lambda _: take_in(client, tomatoes["listing_id"]),
                                                              range(2)))

    assert statuses == [200, 409]
    assert len(db.scalars(select(QualityCheck)).all()) == 1
    assert take_in(client, tomatoes["listing_id"]).json()["error"]["code"] == "not_listed"


def test_a_retried_intake_is_done_once(tomatoes, client, db):
    body = {"received_kg": 20, "rejected_kg": 0, "grade": "A"}
    url = f"/v1/listings/{tomatoes['listing_id']}/intake"

    first = client.post(url, json=body, headers={"Idempotency-Key": "intake-1"})
    again = client.post(url, json=body, headers={"Idempotency-Key": "intake-1"})

    assert first.status_code == 200 and again.json() == first.json()
    assert len(db.scalars(select(QualityCheck)).all()) == 1


def test_a_lot_dropped_late_is_packed_but_refused_at_the_dock_for_its_shelf_life(tomatoes, client, db):
    listing = db.get(Listing, tomatoes["listing_id"])
    listing.harvest_date = TODAY - timedelta(days=4)             # as if it came days after its slot: 1 of 5 days left
    db.commit()

    (line,) = take_in(client, listing.id, received_kg=20).json()["receipt"]["lines"]

    assert (line["on_dock"], line["rejected"]) == (0, 40)        # the receiving rule: at least half the shelf life


def test_a_cancelled_or_received_listing_cannot_be_taken_in_or_cancelled(tomatoes, farmer, client):
    take_in(client, tomatoes["listing_id"])

    late = farmer.post(f"/v1/listings/{tomatoes['listing_id']}/cancel")

    assert late.status_code == 409 and late.json()["error"]["code"] == "not_cancellable"


def test_only_this_hubs_receivers_and_managers_take_in_a_lot(tomatoes, farmer, client_as):
    url, body = f"/v1/listings/{tomatoes['listing_id']}/intake", {"received_kg": 20, "grade": "A"}

    assert farmer.post(url, json=body).status_code == 403                         # a farmer does not grade
    with client_as("picker", 1) as picker, client_as("receiver", 2) as elsewhere, client_as("receiver", 1) as receiver:
        assert picker.post(url, json=body).status_code == 403
        assert elsewhere.post(url, json=body).status_code == 403
        assert receiver.post(url, json=body).status_code == 200
    assert TestClient(app).post(url, json=body).status_code == 401
    assert TestClient(app).post("/v1/listings/9999/intake", headers=receiver.headers, json=body).status_code == 404


def test_a_weighed_lot_stays_on_the_dock_list_until_its_receipt_is_closed(tomatoes, client_as):
    with client_as("receiver", 1) as receiver:
        before = receiver.get("/v1/stores/1/lots-on-dock").json()
        receipt = take_in(receiver, tomatoes["listing_id"], received_kg=20).json()["receipt"]["receipt_id"]
        waiting = receiver.get("/v1/stores/1/lots-on-dock").json()
        for task in receiver.get(f"/v1/goods-receipts/{receipt}/putaway-tasks").json():
            receiver.post(f"/v1/goods-receipts/{receipt}/putaway", json={
                "sku_id": task["sku_id"], "batch_no": task["batch_no"], "bin_code": task["bin_code"], "qty": task["qty"]})
        put_away = receiver.get("/v1/stores/1/lots-on-dock").json()
        receiver.post(f"/v1/goods-receipts/{receipt}/close")
        after = receiver.get("/v1/stores/1/lots-on-dock").json()

    assert before == []
    assert [(lot["item"], lot["quality_check"]["receipt_id"]) for lot in waiting] == [("Tomato", receipt)]
    assert len(put_away) == 1          # everything is in its bin, but the receipt is not closed yet
    assert after == []


def test_a_rejected_lot_never_waits_on_the_dock_and_the_list_is_for_ones_own_hub(tomatoes, client_as):
    with client_as("receiver", 1) as receiver, client_as("receiver", 2) as elsewhere:
        take_in(receiver, tomatoes["listing_id"], received_kg=20, grade="reject")

        assert receiver.get("/v1/stores/1/lots-on-dock").json() == []
        assert elsewhere.get("/v1/stores/1/lots-on-dock").status_code == 403
        assert elsewhere.get("/v1/stores/2/lots-on-dock").json() == []
