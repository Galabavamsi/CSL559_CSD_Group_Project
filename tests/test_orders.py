"""Orders (docs/DESIGN.md, section 2): a signed-in customer's paid order as a record, made around the hold, and moved
along by what the hub does."""
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app import auth, events, seed
from app.main import app
from app.models import FulfilmentJob, Order, Reservation, User, utcnow
from app.modules.farms import service as farms
from app.modules.orders import service as orders
from tests.conftest import assert_stock_is_consistent, atp

MG_ROAD = {"label": "MG Road, Bangalore", "line": "12 Lake Road", "landmark": "Opposite the park",
           "lat": 12.9756, "lng": 77.605}                        # in hub 1's zone
HEBBAL = {"label": "Hebbal, Bangalore", "line": "4 Tank Road", "lat": 13.0358, "lng": 77.597}       # in hub 2's zone
NOWHERE = {"label": "Kumhari", "line": "1 Main Road", "lat": 21.266, "lng": 81.519}                 # in nobody's


@pytest.fixture()
def as_user(db):
    made = []

    def sign_in(role: str) -> TestClient:
        user = User(email=f"{role}{len(made) + 1}@example.com", role=role, name=f"Test {role}")
        db.add(user)
        db.commit()
        made.append(user)
        return TestClient(app, headers={"Authorization": f"Bearer {auth.make_user_token(user.id, role)}"})
    return sign_in


@pytest.fixture()
def customer(as_user):
    return as_user("customer")


def hold(client, order_id: str, lines: list[tuple[int, int]], store_id: int = 1) -> str:
    res = client.post("/v1/reservations", json={"order_id": order_id, "store_id": store_id,
                                                "lines": [{"sku_id": s, "qty": q} for s, q in lines]})
    assert res.status_code == 201, res.text
    return res.json()["reservation_id"]


def place(client, hold_id: str, address: dict = MG_ROAD):
    return client.post("/v1/orders", json={"hold_id": hold_id, "address": address})


def pick_and_pack(client, store_id: int = 1, empty_shelf: bool = False) -> dict:
    """As the hub: claim the next order, scan every line (or report the first one's shelf empty), and pack."""
    job = client.get("/v1/pickers/picker1/next-task", params={"store_id": store_id}).json()["job"]
    for n, task in enumerate(job["tasks"]):
        if empty_shelf and n == 0:
            assert client.post(f"/v1/pick-tasks/{task['task_id']}/short").status_code == 200
        else:
            scan = client.post(f"/v1/pick-tasks/{task['task_id']}/scans",
                               json={"barcode": task["barcode"], "qty": task["qty"]})
            assert scan.status_code == 200, scan.text
    packed = client.post(f"/v1/fulfilment-jobs/{job['job_id']}/packed", json={"crate_slot": "S-01"})
    assert packed.status_code == 200, packed.text
    return packed.json()


def test_placing_an_order_pays_the_hold_and_records_who_where_and_at_what_price(customer, client, sku, db):
    milk, rice = sku("Toned milk"), sku("Basmati rice")
    hold_id = hold(customer, "F2H-ORDER001", [(milk, 2), (rice, 1)])

    res = place(customer, hold_id)

    assert res.status_code == 201, res.text
    order = res.json()
    assert (order["id"], order["status"], order["hub_id"], order["hub_name"]) == ("F2H-ORDER001", "confirmed", 1,
                                                                                  "DS-01 Central")
    # The two packs of milk come from the batch that expires tomorrow (it is picked first), at the rescue price.
    assert order["lines"] == [
        {"product_id": milk, "name": "Toned milk 500 ml", "unit_label": None, "quantity": 2, "unit_price": 20.0,
         "list_price": 28.0},
        {"product_id": rice, "name": "Basmati rice 1 kg", "unit_label": None, "quantity": 1, "unit_price": 140.0,
         "list_price": 140.0}]
    assert (order["item_total"], order["savings"], order["delivery_fee"], order["total"]) == (196.0, 16.0, 0, 180.0)
    assert order["address"] == MG_ROAD
    assert [event["status"] for event in order["history"]] == ["placed", "confirmed"]
    assert (order["payment"], order["can_cancel"], order["delivery_code"]) == ("stand_in", True, None)
    assert db.get(Reservation, hold_id).status == "confirmed"
    assert db.scalar(select(func.count()).select_from(FulfilmentJob).where(FulfilmentJob.order_id == "F2H-ORDER001")) == 1
    assert_stock_is_consistent()


def test_asking_again_for_the_same_hold_returns_the_same_order(customer, sku, db):
    hold_id = hold(customer, "F2H-ORDER002", [(sku("Toned milk"), 1)])

    first, again = place(customer, hold_id), place(customer, hold_id)

    assert (first.status_code, again.status_code) == (201, 201)
    assert again.json() == first.json()
    assert db.scalar(select(func.count()).select_from(Order)) == 1
    assert db.scalar(select(func.count()).select_from(FulfilmentJob)) == 1


def test_an_address_the_holds_hub_does_not_serve_is_refused_and_the_hold_stays_held(customer, sku, db):
    hold_id = hold(customer, "F2H-ORDER003", [(sku("Toned milk"), 1)])

    other_hub, no_hub = place(customer, hold_id, HEBBAL), place(customer, hold_id, NOWHERE)

    assert (other_hub.status_code, other_hub.json()["error"]["code"]) == (422, "address_outside_zone")
    assert other_hub.json()["error"]["details"] == {"store_id": 1, "serving_store_id": 2}
    assert (no_hub.status_code, no_hub.json()["error"]["details"]["serving_store_id"]) == (422, None)
    assert db.get(Reservation, hold_id).status == "held"
    assert db.scalar(select(func.count()).select_from(Order)) == 0


def test_a_hold_that_ran_out_cannot_become_an_order(customer, sku, db):
    milk = sku("Toned milk")
    before = atp(customer, 1, milk)
    hold_id = hold(customer, "F2H-ORDER004", [(milk, 3)])
    db.get(Reservation, hold_id).expires_at = utcnow() - timedelta(seconds=1)
    db.commit()

    res = place(customer, hold_id)

    assert (res.status_code, res.json()["error"]["code"]) == (409, "hold_expired")
    assert db.scalar(select(func.count()).select_from(Order)) == 0
    assert atp(customer, 1, milk) == before                 # the items went back on sale
    assert_stock_is_consistent()


def test_a_hold_paid_at_the_hubs_desk_makes_no_order_and_cannot_become_one(customer, client, sku, db):
    hold_id = hold(client, "DESK-1", [(sku("Toned milk"), 1)])
    assert client.post(f"/v1/reservations/{hold_id}/confirm").status_code == 200

    late = place(customer, hold_id)

    assert db.scalar(select(func.count()).select_from(Order)) == 0
    assert (late.status_code, late.json()["error"]["code"]) == (409, "already_paid")


def test_an_unknown_hold_and_a_cancelled_one_are_refused(customer, client, sku):
    hold_id = hold(customer, "F2H-ORDER005", [(sku("Toned milk"), 1)])
    assert client.delete(f"/v1/reservations/{hold_id}").status_code == 200

    assert place(customer, "no-such-hold").status_code == 404
    released = place(customer, hold_id)
    assert (released.status_code, released.json()["error"]["code"]) == (409, "not_held")


def test_the_order_follows_the_hub_to_packed(customer, client, sku):
    hold_id = hold(customer, "F2H-ORDER006", [(sku("Toned milk"), 2)])
    place(customer, hold_id)

    pick_and_pack(client)

    order = customer.get("/v1/orders/F2H-ORDER006").json()
    assert (order["status"], order["can_cancel"]) == ("packed", False)
    assert [event["status"] for event in order["history"]] == ["placed", "confirmed", "packed"]
    assert_stock_is_consistent()


def test_a_customer_cancels_before_packing_and_the_items_go_back_on_sale(customer, sku):
    milk = sku("Toned milk")
    before = atp(customer, 1, milk)
    place(customer, hold(customer, "F2H-ORDER007", [(milk, 2)]))
    assert atp(customer, 1, milk) == before - 2

    cancelled = customer.post("/v1/orders/F2H-ORDER007/cancel")
    again = customer.post("/v1/orders/F2H-ORDER007/cancel")

    assert (cancelled.status_code, again.status_code) == (200, 200)
    assert (cancelled.json()["status"], cancelled.json()["can_cancel"]) == ("cancelled", False)
    assert [event["status"] for event in again.json()["history"]] == ["placed", "confirmed", "cancelled"]
    assert atp(customer, 1, milk) == before
    assert_stock_is_consistent()


def test_a_packed_order_cannot_be_cancelled(customer, client, sku):
    place(customer, hold(customer, "F2H-ORDER008", [(sku("Toned milk"), 1)]))
    pick_and_pack(client)

    res = customer.post("/v1/orders/F2H-ORDER008/cancel")

    assert (res.status_code, res.json()["error"]["code"]) == (409, "too_late")
    assert customer.get("/v1/orders/F2H-ORDER008").json()["status"] == "packed"


def test_units_the_hub_cannot_find_leave_the_order_and_its_bill(customer, client, sku):
    bread, rice = sku("White bread"), sku("Basmati rice")          # bread: 4 left, all in one bin
    place(customer, hold(customer, "F2H-ORDER009", [(bread, 2), (rice, 1)]))

    pick_and_pack(client, empty_shelf=True)                        # the bread's shelf is empty

    order = customer.get("/v1/orders/F2H-ORDER009").json()
    assert order["status"] == "packed"
    assert [(line["product_id"], line["quantity"]) for line in order["lines"]] == [(rice, 1)]
    assert (order["item_total"], order["total"]) == (140.0, 140.0)
    assert_stock_is_consistent()


def test_an_order_with_nothing_left_to_pack_is_cancelled(customer, client, sku):
    place(customer, hold(customer, "F2H-ORDER010", [(sku("White bread"), 2)]))

    pick_and_pack(client, empty_shelf=True)

    order = customer.get("/v1/orders/F2H-ORDER010").json()
    assert (order["status"], order["lines"], order["total"]) == ("cancelled", [], 0)


def test_orders_are_listed_newest_first_and_only_to_their_owner(customer, as_user, sku):
    milk = sku("Toned milk")
    place(customer, hold(customer, "F2H-FIRST", [(milk, 1)]))
    place(customer, hold(customer, "F2H-SECOND", [(milk, 1)]))
    stranger = as_user("customer")
    place(stranger, hold(stranger, "F2H-THEIRS", [(milk, 1)]))

    assert [order["id"] for order in customer.get("/v1/orders").json()] == ["F2H-SECOND", "F2H-FIRST"]
    assert [order["id"] for order in stranger.get("/v1/orders").json()] == ["F2H-THEIRS"]
    assert customer.get("/v1/orders/F2H-THEIRS").status_code == 404
    assert customer.post("/v1/orders/F2H-THEIRS/cancel").status_code == 404
    assert stranger.get("/v1/orders/F2H-THEIRS").json()["status"] == "confirmed"


def test_someone_elses_hold_that_is_already_an_order_looks_unknown(customer, as_user, sku):
    hold_id = hold(customer, "F2H-ORDER011", [(sku("Toned milk"), 1)])
    place(customer, hold_id)

    assert place(as_user("customer"), hold_id).status_code == 404


def test_only_signed_in_customers_have_orders(customer, as_user, client, sku):
    hold_id = hold(customer, "F2H-ORDER012", [(sku("Toned milk"), 1)])
    body = {"hold_id": hold_id, "address": MG_ROAD}

    assert as_user("farmer").post("/v1/orders", json=body).status_code == 403
    assert as_user("agent").get("/v1/orders").status_code == 403
    assert client.post("/v1/orders", json=body).status_code == 403            # a staff token is not a customer's
    assert TestClient(app).post("/v1/orders", json=body).status_code == 401
    assert TestClient(app).get("/v1/orders").status_code == 401


@pytest.mark.parametrize("change", [{"line": "ab"}, {"line": "    "}, {"label": ""}, {"lat": 91}, {"lng": None}])
def test_a_malformed_address_is_refused(customer, sku, change):
    hold_id = hold(customer, "F2H-ORDER013", [(sku("Toned milk"), 1)])

    assert place(customer, hold_id, {**MG_ROAD, **change}).status_code == 422


def test_a_produce_line_is_named_by_its_item_and_its_unit(customer, client, as_user, db):
    """A farm lot taken in at hub 1, then bought: the line says Tomato and 500 g, at the unit's price."""
    seed.add_produce(db)
    db.commit()
    tomato = next(i for i in client.get("/v1/produce-items").json() if i["name"] == "Tomato")
    farmer = as_user("farmer")
    farm = farmer.post("/v1/farms", json={"name": "Green Acres", "lat": 12.80, "lng": 77.59}).json()
    today = (utcnow() + farms.LOCAL).date().isoformat()
    lot = farmer.post("/v1/listings", json={"farm_id": farm["farm_id"], "item_id": tomato["item_id"], "qty_kg": 10,
                                            "price_per_kg": 18, "harvest_date": today}).json()
    receipt = client.post(f"/v1/listings/{lot['listing_id']}/intake",
                          json={"received_kg": 10, "grade": "A"}).json()["receipt"]["receipt_id"]
    for task in client.get(f"/v1/goods-receipts/{receipt}/putaway-tasks").json():
        client.post(f"/v1/goods-receipts/{receipt}/putaway", json={
            "sku_id": task["sku_id"], "batch_no": task["batch_no"], "bin_code": task["bin_code"], "qty": task["qty"]})
    pack = tomato["units"][0]["sku_id"]

    order = place(customer, hold(customer, "F2H-ORDER014", [(pack, 2)])).json()

    assert order["lines"] == [{"product_id": pack, "name": "Tomato", "unit_label": "500 g", "quantity": 2,
                               "unit_price": 24.0, "list_price": 24.0}]
    assert order["total"] == 48.0


def test_units_in_their_last_day_cost_the_rescue_price_and_the_rest_the_full_price(customer, sku):
    """Six packs of milk expire tomorrow and are picked first; the seventh and eighth come from the fresh batch."""
    milk = sku("Toned milk")

    order = place(customer, hold(customer, "F2H-ORDER015", [(milk, 8)])).json()

    assert [(line["quantity"], line["unit_price"], line["list_price"]) for line in order["lines"]] == [
        (6, 20.0, 28.0), (2, 28.0, 28.0)]
    assert (order["item_total"], order["savings"], order["total"]) == (224.0, 48.0, 176.0)
    assert_stock_is_consistent()


def test_a_unit_that_is_dropped_comes_off_the_dearer_line_first(customer, sku, db):
    milk = sku("Toned milk")
    place(customer, hold(customer, "F2H-ORDER016", [(milk, 8)]))

    orders.on_line_dropped(db, 1, {"order_id": "F2H-ORDER016", "sku_id": milk, "qty": 3})
    db.commit()

    order = customer.get("/v1/orders/F2H-ORDER016").json()
    assert [(line["quantity"], line["unit_price"]) for line in order["lines"]] == [(5, 20.0)]
    assert (order["item_total"], order["savings"], order["total"]) == (140.0, 40.0, 100.0)


def test_a_job_sent_back_to_the_queue_does_not_reprice_the_order(customer, client, sku, db):
    milk = sku("Toned milk")
    place(customer, hold(customer, "F2H-ORDER017", [(milk, 2)]))
    job = client.get("/v1/pickers/picker1/next-task", params={"store_id": 1}).json()["job"]
    task = job["tasks"][0]
    client.post(f"/v1/pick-tasks/{task['task_id']}/scans", json={"barcode": task["barcode"], "qty": 2})

    # what the hub publishes when a stalled order goes back to the queue, with its lines already in a tote
    orders.on_job_state(db, 1, {"job_id": job["job_id"], "order_id": "F2H-ORDER017", "state": "created",
                                "reason": "stalled", "picker_id": "picker1"})
    db.commit()

    order = customer.get("/v1/orders/F2H-ORDER017").json()
    assert [(line["quantity"], line["unit_price"]) for line in order["lines"]] == [(2, 20.0)]


def test_the_order_is_written_before_the_hub_starts_on_it():
    """The hub's handler creates the pick job and may drop a line at once; the order has to exist by then."""
    assert events._handlers["order.paid"][0] is orders.on_order_paid
