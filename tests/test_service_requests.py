"""Asking for delivery where no hub serves yet (POST /v1/service-requests): the request is kept as an H3 cell, and
planning counts it as demand for a new hub."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app import auth, config
from app.main import app
from app.models import ServiceabilityMiss, ServiceRequest, User

KUMHARI = {"lat": 21.266, "lng": 81.519, "label": "Kumhari, Bhilai"}       # no hub serves it
MG_ROAD = {"lat": 12.9756, "lng": 77.605, "label": "MG Road, Bangalore"}   # hub 1 does


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


def ask(client, place: dict = KUMHARI):
    return client.post("/v1/service-requests", json=place)


def test_a_customer_asks_for_delivery_where_nobody_serves(as_user, db):
    res = ask(as_user("customer"))

    assert res.status_code == 201, res.text
    answer = res.json()
    assert (answer["requested"], answer["new"], answer["others_nearby"]) == (True, True, 0)
    assert {"nearest_store", "nearest_distance_km"} <= answer.keys()
    saved = db.scalars(select(ServiceRequest)).all()
    assert [(r.h3_cell, r.label) for r in saved] == [(answer["h3_cell"], "Kumhari, Bhilai")]
    assert not hasattr(saved[0], "lat")                         # the cell is kept, never the exact point
    assert db.scalar(select(func.count()).select_from(ServiceabilityMiss)) == 0     # a request is not a lookup


def test_asking_again_from_the_same_place_is_the_same_request(as_user, db):
    customer = as_user("customer")
    ask(customer)

    again = ask(customer, {**KUMHARI, "lat": KUMHARI["lat"] + 0.0001})      # a few metres away: the same cell

    assert (again.status_code, again.json()["new"]) == (201, False)
    assert db.scalar(select(func.count()).select_from(ServiceRequest)) == 1


def test_the_answer_says_how_many_others_nearby_have_asked(as_user):
    ask(as_user("customer"))
    ask(as_user("customer"), {**KUMHARI, "lat": KUMHARI["lat"] + 0.004})    # about 450 m north
    ask(as_user("customer"), {"lat": 21.165, "lng": 81.34, "label": "Risali"})      # 20 km away

    third = ask(as_user("customer"))

    assert (third.json()["new"], third.json()["others_nearby"]) == (True, 2)


def test_a_place_a_hub_serves_has_nothing_to_ask_for(as_user, db):
    res = ask(as_user("customer"), MG_ROAD)

    assert (res.status_code, res.json()["error"]["code"]) == (409, "already_served")
    assert res.json()["error"]["details"] == {"store_id": 1, "store": "DS-01 Central"}
    assert db.scalar(select(func.count()).select_from(ServiceRequest)) == 0


def test_only_signed_in_customers_ask(as_user, client):
    assert ask(as_user("farmer")).status_code == 403
    assert ask(client).status_code == 403                       # a staff token is not a customer's
    assert ask(TestClient(app)).status_code == 401


@pytest.mark.parametrize("change", [{"lat": 91}, {"lng": None}, {"label": "x" * 121}])
def test_a_malformed_request_is_refused(as_user, change):
    assert ask(as_user("customer"), {**KUMHARI, **change}).status_code == 422


def test_requests_show_on_the_planning_map_and_weigh_more_than_lookups(as_user, client):
    """Three lookups turned away at Risali, one customer who asked at Kumhari: the next hub goes to Kumhari."""
    for _ in range(3):
        client.get("/v1/serviceability", params={"lat": 21.165, "lng": 81.34})
    asked = ask(as_user("customer")).json()

    cells = {cell["h3_cell"]: cell for cell in client.get("/v1/network-planning/heatmap").json()}
    first = client.get("/v1/network-planning/suggestions", params={"k": 1}).json()[0]

    assert (cells[asked["h3_cell"]]["requests"], cells[asked["h3_cell"]]["misses"]) == (1, 0)
    assert sum(cell["requests"] for cell in cells.values()) == 1 and sum(c["misses"] for c in cells.values()) == 3
    assert (first["h3_cell"], first["demand_gained"]) == (asked["h3_cell"], config.SERVICE_REQUEST_WEIGHT)
