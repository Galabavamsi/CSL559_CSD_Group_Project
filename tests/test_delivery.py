"""Delivery (docs/DESIGN.md, section 4): packed orders leave the hub in trips, an agent checks the bags out, and each
order is handed over against the four digits the customer reads out."""
from datetime import timedelta
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app import auth, background, config, events
from app.main import app
from app.models import AgentProfile, FulfilmentJob, LoginCode, Order, OrderEvent, Trip, TripStop, User, utcnow
from app.modules.delivery import service as delivery
from app.modules.orders import service as orders
from tests.conftest import assert_stock_is_consistent
from tests.test_orders import HEBBAL, MG_ROAD, hold, pick_and_pack, place


@pytest.fixture()
def person(db):
    """person("agent", "Kiran") signs someone in: a client with their token, and `.user_id`."""
    made = []

    def sign_in(role: str, name: str | None = None) -> TestClient:
        user = User(email=f"{role}{len(made) + 1}@example.com", role=role, name=name or f"Test {role}")
        db.add(user)
        db.commit()
        made.append(user)
        client = TestClient(app, headers={"Authorization": f"Bearer {auth.make_user_token(user.id, role)}"})
        client.user_id = user.id
        return client
    return sign_in


@pytest.fixture()
def customer(person):
    return person("customer", "Asha")


@pytest.fixture()
def no_waiting(monkeypatch):
    """A lone order leaves at once: the oldest has always waited long enough."""
    monkeypatch.setattr(config, "POOL_MAX_WAIT_MINUTES", 0)


def on_duty(agent, store_id: int = 1) -> dict:
    assert agent.post("/v1/agent/hub", json={"store_id": store_id}).status_code == 200
    res = agent.post("/v1/agent/duty", json={"on_duty": True})
    assert res.status_code == 200, res.text
    return res.json()


def packed(customer, staff, sku, order_id: str, address: dict = MG_ROAD, store_id: int = 1) -> None:
    """A customer's order, paid, picked and packed at the hub."""
    assert place(customer, hold(customer, order_id, [(sku("Toned milk"), 1)], store_id), address).status_code == 201
    pick_and_pack(staff, store_id)


def status(customer, order_id: str) -> str:
    return customer.get(f"/v1/orders/{order_id}").json()["status"]


def trip(agent) -> dict | None:
    return agent.get("/v1/agent").json()["trip"]


# --------------------------------------------------------------------------- the whole way

def test_an_order_goes_from_packed_to_the_door(customer, person, client, sku, db, no_waiting):
    agent = person("agent", "Kiran")
    on_duty(agent)
    packed(customer, client, sku, "F2H-DOOR")

    # packed with an agent free and no wait asked for: on a trip at once, and the customer has a code
    order = customer.get("/v1/orders/F2H-DOOR").json()
    assert (order["status"], order["agent_name"], order["pooled_with"]) == ("pooled", "Kiran", 0)
    code = order["delivery_code"]
    assert len(code) == 4 and code.isdigit() and code == orders.door_code("F2H-DOOR")
    mine = trip(agent)
    assert (mine["status"], mine["hub"]["name"], len(mine["stops"])) == ("assigned", "DS-01 Central", 1)
    stop = mine["stops"][0]
    assert (stop["order_id"], stop["status"], stop["crate_slot"], stop["units"]) == ("F2H-DOOR", "waiting", "S-01", 1)
    assert (stop["address"]["line"], stop["customer"]["name"], stop["tries_left"]) == ("12 Lake Road", "Asha", 5)
    assert not any("code" in key for key in stop)               # the agent is never sent it

    # the agent checks the bag out of the hub: the trip is out
    out = agent.post("/v1/agent/trip/bags/F2H-DOOR/load").json()
    assert (out["status"], out["stops"][0]["status"]) == ("out", "loaded")
    assert status(customer, "F2H-DOOR") == "out_for_delivery"
    assert db.scalar(select(FulfilmentJob.state).where(FulfilmentJob.order_id == "F2H-DOOR")) == "handed_over"

    # at the door the customer reads the code out
    done = agent.post("/v1/agent/trip/stops/F2H-DOOR/deliver", json={"code": code})
    assert done.status_code == 200, done.text
    assert (done.json()["status"], done.json()["stops"][0]["status"]) == ("done", "delivered")
    order = customer.get("/v1/orders/F2H-DOOR").json()
    assert (order["status"], order["delivery_code"], order["can_cancel"]) == ("delivered", None, False)
    assert [event["status"] for event in order["history"]] == [
        "placed", "confirmed", "packed", "pooled", "out_for_delivery", "delivered"]
    assert trip(agent) is None and agent.get("/v1/agent").json()["on_duty"] is True
    assert_stock_is_consistent()


def test_the_code_is_worked_out_and_never_stored(customer, person, client, sku, db, no_waiting):
    on_duty(person("agent"))
    packed(customer, client, sku, "F2H-CODE")
    code = customer.get("/v1/orders/F2H-CODE").json()["delivery_code"]

    assert orders.door_code("F2H-CODE") == code and orders.door_code("F2H-OTHER") != code
    for table in (Order, TripStop, Trip, OrderEvent):
        columns = [column.name for column in table.__table__.columns]
        assert not any("code" in name and name != "code_tries" for name in columns), table.__name__


# --------------------------------------------------------------------------- when a trip leaves

def test_one_order_waits_for_company_until_it_has_waited_long_enough(customer, person, client, sku, db):
    agent = person("agent")
    on_duty(agent)
    packed(customer, client, sku, "F2H-ALONE")

    assert status(customer, "F2H-ALONE") == "packed" and trip(agent) is None
    assert customer.get("/v1/orders/F2H-ALONE").json()["delivery_code"] is None
    assert background.delivery_once() is None                   # the timer finds nothing due yet

    # ten minutes pass
    event = db.scalar(select(OrderEvent).join(Order, Order.id == OrderEvent.order_id)
                      .where(Order.order_id == "F2H-ALONE", OrderEvent.status == "packed"))
    event.at = utcnow() - timedelta(minutes=config.POOL_MAX_WAIT_MINUTES, seconds=1)
    db.commit()

    assert background.delivery_once() == 1
    assert status(customer, "F2H-ALONE") == "pooled" and len(trip(agent)["stops"]) == 1


def test_the_fourth_order_makes_a_trip_leave_without_waiting(customer, person, client, sku):
    agent = person("agent")
    on_duty(agent)
    for n in range(1, 4):
        packed(customer, client, sku, f"F2H-P{n}")
    assert trip(agent) is None

    packed(customer, client, sku, "F2H-P4")

    mine = trip(agent)
    assert sorted(stop["order_id"] for stop in mine["stops"]) == ["F2H-P1", "F2H-P2", "F2H-P3", "F2H-P4"]
    assert [stop["seq"] for stop in mine["stops"]] == [1, 2, 3, 4]
    assert customer.get("/v1/orders/F2H-P2").json()["pooled_with"] == 3


def test_orders_wait_packed_until_an_agent_comes_on_duty(customer, person, client, sku, no_waiting):
    packed(customer, client, sku, "F2H-EARLY")
    assert status(customer, "F2H-EARLY") == "packed"

    agent = person("agent")
    mine = on_duty(agent)["trip"]

    assert [stop["order_id"] for stop in mine["stops"]] == ["F2H-EARLY"]
    assert status(customer, "F2H-EARLY") == "pooled"


def test_the_agent_free_longest_takes_the_trip_and_a_busy_one_takes_none(customer, person, client, sku, db, no_waiting):
    first, second = person("agent", "First"), person("agent", "Second")
    on_duty(second)
    on_duty(first)
    db.get(AgentProfile, first.user_id).free_since = utcnow() - timedelta(minutes=30)       # free for half an hour
    db.commit()

    packed(customer, client, sku, "F2H-A")
    packed(customer, client, sku, "F2H-B")
    packed(customer, client, sku, "F2H-C")

    assert [stop["order_id"] for stop in trip(first)["stops"]] == ["F2H-A"]
    assert [stop["order_id"] for stop in trip(second)["stops"]] == ["F2H-B"]
    assert status(customer, "F2H-C") == "packed"                # both agents are out: it waits
    assert db.scalar(select(func.count()).select_from(Trip)) == 2


def test_an_agent_who_finishes_is_given_what_waited_meanwhile(customer, person, client, sku, no_waiting):
    agent = person("agent")
    on_duty(agent)
    packed(customer, client, sku, "F2H-ONE")
    packed(customer, client, sku, "F2H-TWO")
    agent.post("/v1/agent/trip/bags/F2H-ONE/load")

    after = agent.post("/v1/agent/trip/stops/F2H-ONE/deliver", json={"code": orders.door_code("F2H-ONE")}).json()

    assert after["status"] == "done"
    assert [stop["order_id"] for stop in trip(agent)["stops"]] == ["F2H-TWO"]


def test_a_hub_only_gives_its_own_orders_to_its_own_agents(customer, person, client, sku, no_waiting):
    north = person("agent", "North")
    on_duty(north, store_id=2)

    packed(customer, client, sku, "F2H-CENTRAL")                # packed at hub 1

    assert trip(north) is None and status(customer, "F2H-CENTRAL") == "packed"
    packed(customer, client, sku, "F2H-NORTH", HEBBAL, store_id=2)
    assert [stop["order_id"] for stop in trip(north)["stops"]] == ["F2H-NORTH"]


# --------------------------------------------------------------------------- which orders, in what order

def at(lat: float, lng: float, ident: int = 0) -> SimpleNamespace:
    return SimpleNamespace(lat=lat, lng=lng, id=ident)


def test_the_stops_are_made_in_the_shortest_round():
    hub = at(0.0, 0.0)
    east_near, east_far, north = at(0.0, 0.01, 1), at(0.0, 0.03, 2), at(0.02, 0.0, 3)

    stops, km = delivery.route(hub, [east_far, north, east_near])

    # out along the east road and back by the north, or the other way round: never east, north, east again
    assert [stop.id for stop in stops] in ([1, 2, 3], [3, 2, 1])
    straight = sum(delivery.serviceability.distance_km(a.lat, a.lng, b.lat, b.lng)
                   for a, b in zip([hub, *stops], [*stops, hub]))
    assert km == round(straight * config.ROAD_FACTOR, 2)
    assert 9.4 < straight < 9.7                                 # 1.1 + 2.2 + 4.0 + 2.2 km of straight lines


def test_a_round_is_the_same_every_time_it_is_worked_out():
    hub = at(0.0, 0.0)
    load = [at(0.01, 0.01, n) for n in range(1, 4)]             # three orders for one building

    assert [stop.id for stop in delivery.route(hub, load)[0]] == [1, 2, 3]


def test_when_more_wait_than_a_trip_takes_neighbours_by_direction_go_together(monkeypatch):
    monkeypatch.setattr(config, "TRIP_MAX_ORDERS", 3)
    hub = at(0.0, 0.0)
    north = [at(0.02, -0.002, 1), at(0.02, 0.0, 2), at(0.02, 0.002, 3)]
    south = [at(-0.02, -0.002, 4), at(-0.02, 0.0, 5), at(-0.02, 0.002, 6)]

    oldest_is_south = delivery.one_load(hub, [south[1], north[0], south[0], north[1], south[2], north[2]])
    oldest_is_north = delivery.one_load(hub, [north[2], south[0], north[0]] + south[1:] + [north[1]])

    assert sorted(order.id for order in oldest_is_south) == [4, 5, 6]
    assert sorted(order.id for order in oldest_is_north) == [1, 2, 3]
    assert delivery.bearing(hub, north[1]) == pytest.approx(0, abs=0.01)
    assert delivery.bearing(hub, at(0.0, 0.02)) == pytest.approx(90, abs=0.01)


def test_a_trip_takes_no_more_than_its_most(customer, person, client, sku, monkeypatch):
    monkeypatch.setattr(config, "TRIP_MAX_ORDERS", 2)
    monkeypatch.setattr(config, "POOL_MIN_ORDERS", 2)
    for n in range(1, 4):
        packed(customer, client, sku, f"F2H-M{n}")

    agent = person("agent")
    mine = on_duty(agent)["trip"]

    assert len(mine["stops"]) == 2 and "F2H-M1" in [stop["order_id"] for stop in mine["stops"]]
    assert agent.get("/v1/agent").json()["waiting_at_hub"] == 1


# --------------------------------------------------------------------------- at the hub and at the door

def test_the_trip_is_out_only_when_every_bag_is_checked_out(customer, person, client, sku, monkeypatch):
    monkeypatch.setattr(config, "POOL_MIN_ORDERS", 2)
    agent = person("agent")
    on_duty(agent)
    packed(customer, client, sku, "F2H-BAG1")
    packed(customer, client, sku, "F2H-BAG2")

    early = agent.post("/v1/agent/trip/stops/F2H-BAG1/deliver", json={"code": orders.door_code("F2H-BAG1")})
    one = agent.post("/v1/agent/trip/bags/F2H-BAG1/load").json()
    again = agent.post("/v1/agent/trip/bags/F2H-BAG1/load").json()

    assert (early.status_code, early.json()["error"]["code"]) == (409, "not_left")
    assert one["status"] == again["status"] == "assigned"
    assert status(customer, "F2H-BAG1") == "pooled"             # nobody is told "out" while a bag is still at the hub
    assert agent.post("/v1/agent/trip/bags/F2H-BAG2/load").json()["status"] == "out"
    assert status(customer, "F2H-BAG1") == status(customer, "F2H-BAG2") == "out_for_delivery"


def test_a_wrong_code_is_counted_and_five_lock_the_hand_over(customer, person, client, sku, db, no_waiting):
    agent = person("agent")
    on_duty(agent)
    packed(customer, client, sku, "F2H-LOCK")
    agent.post("/v1/agent/trip/bags/F2H-LOCK/load")
    right = orders.door_code("F2H-LOCK")
    wrong = "0000" if right != "0000" else "1111"

    tries = [agent.post("/v1/agent/trip/stops/F2H-LOCK/deliver", json={"code": wrong}) for _ in range(5)]
    locked = agent.post("/v1/agent/trip/stops/F2H-LOCK/deliver", json={"code": right})

    assert [t.status_code for t in tries] == [422] * 5
    assert [t.json()["error"]["details"]["tries_left"] for t in tries] == [4, 3, 2, 1, 0]
    assert (locked.status_code, locked.json()["error"]["code"]) == (409, "code_locked")     # even the right one, now
    assert status(customer, "F2H-LOCK") == "out_for_delivery"
    assert trip(agent)["stops"][0]["tries_left"] == 0

    failed = agent.post("/v1/agent/trip/stops/F2H-LOCK/fail", json={"reason": "refused"}).json()
    assert (failed["status"], failed["stops"][0]["status"], failed["stops"][0]["failed_reason"]) == (
        "done", "failed", "refused")
    assert status(customer, "F2H-LOCK") == "delivery_failed"


def test_a_right_code_after_a_wrong_one_delivers(customer, person, client, sku, no_waiting):
    agent = person("agent")
    on_duty(agent)
    packed(customer, client, sku, "F2H-SLIP")
    agent.post("/v1/agent/trip/bags/F2H-SLIP/load")
    right = orders.door_code("F2H-SLIP")

    assert agent.post("/v1/agent/trip/stops/F2H-SLIP/deliver",
                      json={"code": "0000" if right != "0000" else "1111"}).status_code == 422
    done = agent.post("/v1/agent/trip/stops/F2H-SLIP/deliver", json={"code": right})
    repeat = agent.post("/v1/agent/trip/stops/F2H-SLIP/deliver", json={"code": right})

    assert (done.status_code, status(customer, "F2H-SLIP")) == (200, "delivered")
    assert repeat.status_code == 409 and repeat.json()["error"]["code"] == "no_trip"       # the trip is over


def test_nobody_home_ends_the_stop_and_the_trip_goes_on(customer, person, client, sku, monkeypatch):
    monkeypatch.setattr(config, "POOL_MIN_ORDERS", 2)
    agent = person("agent")
    on_duty(agent)
    packed(customer, client, sku, "F2H-HOME")
    packed(customer, client, sku, "F2H-AWAY")
    for order_id in ("F2H-HOME", "F2H-AWAY"):
        agent.post(f"/v1/agent/trip/bags/{order_id}/load")

    away = agent.post("/v1/agent/trip/stops/F2H-AWAY/fail", json={"reason": "nobody_home"}).json()

    assert away["status"] == "out"                              # one stop left
    assert (status(customer, "F2H-AWAY"), status(customer, "F2H-HOME")) == ("delivery_failed", "out_for_delivery")
    assert agent.post("/v1/agent/duty", json={"on_duty": False}).json()["error"]["code"] == "on_a_trip"
    done = agent.post("/v1/agent/trip/stops/F2H-HOME/deliver", json={"code": orders.door_code("F2H-HOME")}).json()
    assert done["status"] == "done"
    assert agent.post("/v1/agent/duty", json={"on_duty": False}).json()["on_duty"] is False


# --------------------------------------------------------------------------- who may do what

def test_an_agent_has_only_their_own_trip(customer, person, client, sku, no_waiting):
    mine, stranger = person("agent"), person("agent")
    on_duty(mine)
    packed(customer, client, sku, "F2H-MINE")
    on_duty(stranger)                                           # on duty, with nothing waiting: no trip

    code = {"code": orders.door_code("F2H-MINE")}
    assert stranger.post("/v1/agent/trip/bags/F2H-MINE/load").json()["error"]["code"] == "no_trip"
    assert stranger.post("/v1/agent/trip/stops/F2H-MINE/deliver", json=code).json()["error"]["code"] == "no_trip"
    assert mine.post("/v1/agent/trip/bags/F2H-NOT-ON-IT/load").status_code == 404


def test_only_agents_use_the_agents_calls_and_a_code_is_four_digits(customer, person, client, sku, no_waiting):
    agent = person("agent")
    on_duty(agent)
    packed(customer, client, sku, "F2H-WHO")
    agent.post("/v1/agent/trip/bags/F2H-WHO/load")

    assert customer.get("/v1/agent").status_code == 403
    assert customer.post("/v1/agent/duty", json={"on_duty": True}).status_code == 403
    assert client.get("/v1/agent").status_code == 403           # a staff token is not an agent's
    assert TestClient(app).get("/v1/agent").status_code == 401
    assert agent.get("/v1/orders").status_code == 403           # and an agent has no orders of their own
    for bad in ("123", "12345", "12a4", ""):
        assert agent.post("/v1/agent/trip/stops/F2H-WHO/deliver", json={"code": bad}).status_code == 422
    assert agent.post("/v1/agent/trip/stops/F2H-WHO/fail", json={"reason": "bored"}).status_code == 422
    assert trip(agent)["stops"][0]["tries_left"] == 5           # a malformed code is not a try


def test_duty_needs_a_hub_and_a_hub_cannot_be_changed_on_duty(person):
    agent = person("agent")

    assert agent.get("/v1/agent").json() == {"user_id": agent.user_id, "name": "Test agent", "hub": None,
                                             "on_duty": False, "trip": None, "waiting_at_hub": 0}
    assert agent.post("/v1/agent/duty", json={"on_duty": True}).json()["error"]["code"] == "no_hub"
    assert agent.post("/v1/agent/hub", json={"store_id": 999}).status_code == 404
    assert on_duty(agent)["hub"]["name"] == "DS-01 Central"
    assert agent.post("/v1/agent/hub", json={"store_id": 2}).json()["error"]["code"] == "on_duty"
    agent.post("/v1/agent/duty", json={"on_duty": False})
    assert agent.post("/v1/agent/hub", json={"store_id": 2}).json()["hub"]["name"] == "DS-02 North"


def test_the_platform_team_makes_an_agents_account_and_signing_up_as_one_is_a_setting(client, client_as, db,
                                                                                    monkeypatch):
    made = client.post("/v1/admin/agents", json={"email": "Kiran@Example.com", "name": "Kiran", "store_id": 1})

    assert made.status_code == 201, made.text
    assert (made.json()["email"], made.json()["store_id"]) == ("kiran@example.com", 1)
    assert db.get(AgentProfile, made.json()["user_id"]).store_id == 1
    assert client.post("/v1/admin/agents", json={"email": "kiran@example.com", "name": "K", "store_id": 1}
                       ).json()["error"]["code"] == "email_taken"
    assert client_as("manager", 1).post("/v1/admin/agents", json={"email": "x@example.com", "name": "X",
                                                                  "store_id": 1}).status_code == 403

    def code_made_for(email: str) -> bool:
        TestClient(app).post("/v1/auth/otp/request", json={"email": email, "role": "agent"})
        return db.scalar(select(LoginCode.used_at).where(LoginCode.email == email)
                         .order_by(LoginCode.id.desc())) is None        # a usable code is one not already spent

    assert code_made_for("kiran@example.com") is True           # an account the team made may sign in
    assert code_made_for("stranger@example.com") is False       # nobody else may become an agent
    monkeypatch.setattr(config, "AGENT_SELF_SIGNUP", True)
    assert code_made_for("demo.agent@example.com") is True      # unless the demo setting says so


def test_the_hub_sees_bags_waiting_trips_and_agents(customer, person, client, client_as, sku, monkeypatch):
    monkeypatch.setattr(config, "POOL_MIN_ORDERS", 2)
    agent = person("agent", "Kiran")
    on_duty(agent)
    packed(customer, client, sku, "F2H-D1")

    before = client.get("/v1/stores/1/dispatch").json()
    packed(customer, client, sku, "F2H-D2")
    after = client_as("manager", 1).get("/v1/stores/1/dispatch").json()

    assert [bag["order_id"] for bag in before["waiting"]] == ["F2H-D1"] and before["trips"] == []
    assert before["agents"][0]["name"] == "Kiran" and before["agents"][0]["trip_id"] is None
    assert before["rule"] == {"min_orders": 2, "max_wait_minutes": config.POOL_MAX_WAIT_MINUTES, "max_orders": 6}
    assert after["waiting"] == [] and [t["agent"] for t in after["trips"]] == ["Kiran"]
    assert sorted(stop["order_id"] for stop in after["trips"][0]["stops"]) == ["F2H-D1", "F2H-D2"]
    assert after["agents"][0]["trip_id"] == after["trips"][0]["trip_id"]
    assert client_as("manager", 2).get("/v1/stores/1/dispatch").status_code == 403
    assert client_as("picker", 1).get("/v1/stores/1/dispatch").status_code == 403


def test_an_order_paid_at_the_hubs_desk_is_no_business_of_delivery(person, client, sku, db, no_waiting):
    """A hold confirmed with no customer signed in has no order, so it joins no trip: the desk hands it over."""
    agent = person("agent")
    on_duty(agent)
    hold_id = hold(client, "DESK-9", [(sku("Toned milk"), 1)])
    assert client.post(f"/v1/reservations/{hold_id}/confirm").status_code == 200

    pick_and_pack(client)

    assert trip(agent) is None and db.scalar(select(func.count()).select_from(Trip)) == 0


def test_delivery_hears_of_a_packed_order_after_orders_has_marked_it(monkeypatch):
    """Both listen to the hub's state changes. Delivery looks for orders marked packed, so orders must go first."""
    handlers = events._handlers["fulfilment.state_changed"]

    assert handlers.index(orders.on_job_state) < handlers.index(delivery.on_job_state)


def test_the_timed_job_is_one_of_the_jobs():
    assert background.delivery_loop in background.loops()
