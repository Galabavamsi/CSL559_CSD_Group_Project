"""The shop's list (docs/DESIGN.md, section 3): availability, plus what a customer is told about the batch the next
order would be picked from, and a rescue price for units in their last day."""
from datetime import date, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select

from app import auth, seed
from app.main import app
from app.models import StockItem, User, utcnow
from app.modules.catalogue import service as catalogue
from app.modules.farms import service as farms
from tests.conftest import place_paid_order

TODAY = date.today()


def row(client, store_id: int, sku_id: int) -> dict:
    return next(r for r in client.get(f"/v1/stores/{store_id}/shop").json() if r["sku_id"] == sku_id)


def a_lot_on_the_shelf(client, db, kg: float = 10) -> int:
    """A farmer's tomatoes taken in and put away at hub 1. Returns the id of the 500 g pack."""
    seed.add_produce(db)
    db.commit()
    tomato = next(i for i in client.get("/v1/produce-items").json() if i["name"] == "Tomato")
    user = User(email="farmer@example.com", role="farmer", name="Test farmer")
    db.add(user)
    db.commit()
    farmer = TestClient(app, headers={"Authorization": f"Bearer {auth.make_user_token(user.id, 'farmer')}"})
    farm = farmer.post("/v1/farms", json={"name": "Green Acres", "lat": 12.80, "lng": 77.59}).json()
    today = (utcnow() + farms.LOCAL).date().isoformat()
    lot = farmer.post("/v1/listings", json={"farm_id": farm["farm_id"], "item_id": tomato["item_id"], "qty_kg": kg,
                                            "price_per_kg": 18, "harvest_date": today}).json()
    receipt = client.post(f"/v1/listings/{lot['listing_id']}/intake",
                          json={"received_kg": kg, "grade": "A"}).json()["receipt"]["receipt_id"]
    for task in client.get(f"/v1/goods-receipts/{receipt}/putaway-tasks").json():
        client.post(f"/v1/goods-receipts/{receipt}/putaway", json={
            "sku_id": task["sku_id"], "batch_no": task["batch_no"], "bin_code": task["bin_code"], "qty": task["qty"]})
    return tomato["units"][0]["sku_id"]


def test_the_shop_describes_the_batch_picked_first_and_offers_its_last_day_units_cheaper(client, sku):
    milk = row(client, 1, sku("Toned milk"))        # 6 packs expire tomorrow, 24 are fresh, 2 are a safety buffer
    rice = row(client, 1, sku("Basmati rice"))

    assert (milk["price"], milk["atp"]) == (28.0, 28)
    assert milk["batch"] == {"batch_no": "M-OLD", "use_by": (TODAY + timedelta(days=1)).isoformat(), "units": 6,
                             "harvest_date": None, "grade": None, "farm": None}
    assert milk["rescue"] == {"price": 20.0, "units": 6}
    assert (rice["batch"]["batch_no"], rice["rescue"]) == ("B-OPEN", None)
    assert (rice["name"], rice["unit_label"], rice["family"]) == ("Basmati rice 1 kg", None, None)


def test_the_shop_is_open_to_anyone_like_availability(sku):
    assert TestClient(app).get("/v1/stores/1/shop").status_code == 200


def test_units_another_order_is_waiting_for_are_not_offered_again(client, sku):
    milk = sku("Toned milk")
    place_paid_order(client, "desk-1", 1, [(milk, 6)])          # takes all six packs of the old batch

    after = row(client, 1, milk)

    assert (after["batch"]["batch_no"], after["batch"]["units"], after["rescue"]) == ("M-NEW", 24, None)


def test_some_of_the_last_day_units_taken_leaves_the_rest_on_offer(client, sku):
    milk = sku("Toned milk")
    place_paid_order(client, "desk-1", 1, [(milk, 4)])

    after = row(client, 1, milk)

    assert (after["batch"]["batch_no"], after["batch"]["units"]) == ("M-OLD", 2)
    assert after["rescue"] == {"price": 20.0, "units": 2}


def test_a_farm_lot_shows_its_grade_its_harvest_date_and_its_farm(client, db):
    pack = a_lot_on_the_shelf(client, db)

    tomato = row(client, 1, pack)

    harvest = (utcnow() + farms.LOCAL).date()
    assert (tomato["name"], tomato["unit_label"], tomato["family"], tomato["price"], tomato["atp"]) == (
        "Tomato", "500 g", "vegetables", 24.0, 20)
    assert tomato["batch"] == {"batch_no": "L1", "use_by": (harvest + timedelta(days=5)).isoformat(), "units": 20,
                               "harvest_date": harvest.isoformat(), "grade": "A", "farm": "Green Acres"}
    assert tomato["rescue"] is None


def test_a_farm_lot_in_its_last_day_is_offered_at_the_rescue_price(client, db):
    pack = a_lot_on_the_shelf(client, db)
    for item in db.scalars(select(StockItem).where(StockItem.sku_id == pack)).all():
        item.expiry_date = TODAY + timedelta(days=1)                # four days have passed on the shelf
    db.commit()

    tomato = row(client, 1, pack)

    assert tomato["rescue"] == {"price": 17.0, "units": 20}         # 24 less 30%, in whole rupees


def test_a_batch_past_its_date_is_never_described(client, db, sku):
    milk = sku("Toned milk")
    old = db.scalar(select(StockItem).where(StockItem.sku_id == milk, StockItem.batch_no == "M-OLD"))
    old.expiry_date = TODAY - timedelta(days=1)
    db.commit()

    after = row(client, 1, milk)

    assert (after["batch"]["batch_no"], after["rescue"]) == ("M-NEW", None)


def test_an_item_with_nothing_on_the_shelf_has_no_batch(client, sku):
    bananas = row(client, 2, sku("Bananas"))                       # out of stock at hub 2

    assert (bananas["atp"], bananas["batch"], bananas["rescue"]) == (0, None, None)


def test_an_unknown_hub_is_not_found_and_a_new_hub_lists_nothing(client):
    hub = client.post("/v1/admin/stores", json={"name": "BH-01 Civic Centre", "lat": 21.1938, "lng": 81.3509}).json()

    assert client.get("/v1/stores/999/shop").status_code == 404
    assert client.get(f"/v1/stores/{hub['store_id']}/shop").json() == []


def test_the_rescue_price_is_a_whole_number_of_rupees_and_never_under_one():
    assert [catalogue.rescue_price(price) for price in (28, 24, 140, 1, 0.5)] == [20.0, 17.0, 98.0, 1.0, 1.0]
    assert catalogue.in_rescue(TODAY + timedelta(days=1), TODAY) and catalogue.in_rescue(TODAY, TODAY)
    assert not catalogue.in_rescue(TODAY + timedelta(days=2), TODAY)
