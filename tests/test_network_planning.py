"""Network planning from order data (task 4.4, FR-12): demand by H3 cell, and where the next store should go."""
import h3
from sqlalchemy import select

from app import config
from app.models import Reservation, ServiceabilityMiss, Store, StoreZone
from app.modules.network_planning import service as planning
from app.modules.serviceability.service import distance_km
from scripts.generate_demand import look_up

CENTRAL = (12.975, 77.600)       # inside DS-01 Central's zone
OUTSIDE = (12.800, 77.400)       # outside every zone
GAP = {"name": "gap", "lat": 12.905, "lng": 77.650, "spread_km": 0.5, "lookups": 40}         # ~9 km from DS-01
SMALL_GAP = {"name": "small gap", "lat": 12.960, "lng": 77.500, "spread_km": 0.5, "lookups": 10}
SERVED = {"name": "served", "lat": 12.975, "lng": 77.600, "spread_km": 0.5, "lookups": 30}


def cell(lat: float, lng: float, resolution: int = config.H3_RESOLUTION) -> str:
    return h3.latlng_to_cell(lat, lng, resolution)


def hold(client, order_id: str, sku_id: int, h3_cell: str | None):
    body = {"order_id": order_id, "store_id": 1, "h3_cell": h3_cell, "lines": [{"sku_id": sku_id, "qty": 1}]}
    return client.post("/v1/reservations", json=body)


def test_lookup_outside_every_zone_is_recorded_by_cell_and_a_served_one_is_not(client, db):
    inside = client.get("/v1/serviceability", params={"lat": CENTRAL[0], "lng": CENTRAL[1]}).json()
    outside = client.get("/v1/serviceability", params={"lat": OUTSIDE[0], "lng": OUTSIDE[1]}).json()

    assert inside["h3_cell"] == cell(*CENTRAL) and outside["h3_cell"] == cell(*OUTSIDE)
    assert [m.h3_cell for m in db.scalars(select(ServiceabilityMiss))] == [cell(*OUTSIDE)]


def test_order_keeps_the_cell_of_its_address_and_refuses_a_bad_one(client, db, sku):
    assert hold(client, "geo-1", sku("Tea"), cell(*CENTRAL)).status_code == 201
    assert hold(client, "geo-2", sku("Tea"), "not-a-cell").status_code == 422
    assert hold(client, "geo-3", sku("Tea"), cell(*CENTRAL, resolution=7)).status_code == 422   # wrong cell size
    assert hold(client, "geo-4", sku("Tea"), None).status_code == 201                        # the cell is optional

    assert db.scalar(select(Reservation.h3_cell).where(Reservation.order_id == "geo-1")) == cell(*CENTRAL)


def test_order_cell_is_stored_in_one_spelling(client, db, sku):
    assert hold(client, "geo-upper", sku("Tea"), cell(*CENTRAL).upper()).status_code == 201

    assert db.scalar(select(Reservation.h3_cell).where(Reservation.order_id == "geo-upper")) == cell(*CENTRAL)


def test_heatmap_counts_paid_orders_and_misses_per_cell(client, sku):
    home = cell(*CENTRAL)
    for n in range(2):
        held = hold(client, f"heat-{n}", sku("Tea"), home).json()
        assert client.post(f"/v1/reservations/{held['reservation_id']}/confirm").status_code == 200
    hold(client, "heat-unpaid", sku("Tea"), home)                  # held but never paid: not an order
    for _ in range(3):
        client.get("/v1/serviceability", params={"lat": OUTSIDE[0], "lng": OUTSIDE[1]})

    rows = {row["h3_cell"]: row for row in client.get("/v1/network-planning/heatmap").json()}

    assert (rows[home]["orders"], rows[home]["misses"]) == (2, 0)
    assert (rows[cell(*OUTSIDE)]["orders"], rows[cell(*OUTSIDE)]["misses"]) == (0, 3)
    assert len(rows[home]["boundary"]) == 6                        # a hexagon the map can draw


def test_first_suggestion_lies_inside_a_cluster_of_misses_outside_every_zone(db):
    assert look_up(db, [GAP, SMALL_GAP, SERVED], seed=1) == {"lookups": 80, "misses": 50}

    first, second = planning.suggest_sites(db, k=3)               # two gaps, so no third site

    assert distance_km(first["lat"], first["lng"], GAP["lat"], GAP["lng"]) < 1.5
    assert first["demand_gained"] == 40
    assert distance_km(second["lat"], second["lng"], SMALL_GAP["lat"], SMALL_GAP["lng"]) < 1.5
    assert second["demand_gained"] == 10


def test_a_no_go_cell_is_never_suggested(db, monkeypatch):
    look_up(db, [GAP], seed=1)
    best = planning.suggest_sites(db, k=1)[0]["h3_cell"]

    monkeypatch.setattr(config, "NO_GO_CELLS", [best])
    suggestions = planning.suggest_sites(db, k=3)

    assert best not in [site["h3_cell"] for site in suggestions]
    assert suggestions[0]["demand_gained"] == 40                   # a neighbouring cell still covers the cluster


def test_no_site_is_suggested_inside_an_existing_zone(db):
    # A busy store serves only the inner 70% of its zone, so customers in the outer ring are turned away.
    store = db.get(Store, 1)
    store.status = "busy"
    db.commit()
    ring = {"name": "outer ring", "lat": store.lat + 2.6 / 111.32, "lng": store.lng, "spread_km": 0.1, "lookups": 10}

    assert look_up(db, [ring], seed=1)["misses"] > 0
    zoned = set(db.scalars(select(StoreZone.h3_cell)))
    assert all(site["h3_cell"] not in zoned for site in planning.suggest_sites(db, k=3))


def test_planning_endpoints_are_for_ops(client_as, db):
    look_up(db, [GAP], seed=1)
    picker, ops = client_as("picker", 1), client_as("ops")

    for path in ("/v1/network-planning/heatmap", "/v1/network-planning/suggestions"):
        assert picker.get(path).status_code == 403
        assert ops.get(path).status_code == 200
    assert len(ops.get("/v1/network-planning/suggestions", params={"k": 1}).json()) == 1
    assert ops.get("/v1/network-planning/suggestions", params={"k": 0}).status_code == 422
