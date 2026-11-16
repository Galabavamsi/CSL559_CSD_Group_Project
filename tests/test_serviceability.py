"""Serviceability and network planning."""
import random

import h3
from sqlalchemy import func, select

from app import config, seed
from app.models import Store, StoreZone
from app.modules.serviceability import service

CELL_WIDTH_KM = 2 * h3.average_hexagon_edge_length(config.H3_RESOLUTION, unit="km")


def test_address_inside_a_delivery_zone(client):
    res = client.get("/v1/serviceability", params={"lat": 12.975, "lng": 77.60}).json()
    assert res["serviceable"] is True and res["store"] == "DS-01 Central"
    assert res["distance_km"] < 3 and res["eta_minutes"] <= 10


def test_address_between_stores_goes_to_the_nearest(client):
    res = client.get("/v1/serviceability", params={"lat": 13.03, "lng": 77.596}).json()
    assert res["store"] == "DS-02 North"


def test_address_outside_every_zone(client):
    res = client.get("/v1/serviceability", params={"lat": 12.80, "lng": 77.40}).json()
    assert res["serviceable"] is False and res["nearest_distance_km"] > 3


def test_coverage_report_suggests_a_site_for_uncovered_demand(client):
    body = {"points": [
        {"lat": 12.972, "lng": 77.595, "orders": 100},     # covered by DS-01
        {"lat": 12.900, "lng": 77.650, "orders": 60},      # uncovered
        {"lat": 12.904, "lng": 77.654, "orders": 20},      # uncovered
    ]}
    report = client.post("/v1/network-planning/coverage", json=body).json()
    assert report["covered_order_share"] == round(100 / 180, 3)
    site = report["suggested_site"]
    assert site["orders_gained"] == 80 and 12.900 <= site["lat"] <= 12.904


# --------------------------------------------------------------------------- H3 delivery zones (task 4.3)


def check(client, lat, lng):
    return client.get("/v1/serviceability", params={"lat": lat, "lng": lng}).json()


def test_seed_builds_one_zone_row_per_cell(db):
    cells = db.scalar(select(func.count()).select_from(StoreZone))
    stores_with_zones = db.scalar(select(func.count(func.distinct(StoreZone.store_id))))

    assert cells > 100 and stores_with_zones == 2


def test_point_in_the_overlap_of_two_stores_goes_to_the_nearer_one(client, db):
    # Arrange: the seeded stores are about 7 km apart; a 5 km radius makes their zones overlap.
    for store in db.scalars(select(Store)).all():
        store.radius_km = 5.0
    db.commit()
    assert client.post("/v1/admin/rebuild-zones").status_code == 200
    central, north = db.scalars(select(Store).order_by(Store.id)).all()

    # Act + assert: walk north from one store to the other, skipping points too close to the midline to call.
    for step in range(1, 40):
        lat = central.lat + (north.lat - central.lat) * step / 40
        to_central = service.distance_km(lat, central.lng, central.lat, central.lng)
        to_north = service.distance_km(lat, central.lng, north.lat, north.lng)
        if abs(to_central - to_north) < CELL_WIDTH_KM:
            continue
        result = check(client, lat, central.lng)
        assert result["serviceable"] is True
        assert result["store_id"] == (central.id if to_central < to_north else north.id)


def test_point_near_the_edge_is_served_when_open_and_refused_when_busy(client, db):
    store = db.get(Store, 1)
    lat = store.lat + 2.5 / 111.2          # 2.5 km north: inside the 3 km radius, outside 70% of it

    assert check(client, lat, store.lng)["store_id"] == 1

    store.status = "busy"
    db.commit()
    refused = check(client, lat, store.lng)
    near = check(client, store.lat + 1.0 / 111.2, store.lng)

    assert refused["serviceable"] is False and refused["nearest_store"] == store.name
    assert near["store_id"] == 1 and near["status"] == "busy"      # close-in customers are still served


def test_rebuild_zones_needs_admin(client_as):
    assert client_as("manager", 1).post("/v1/admin/rebuild-zones").status_code == 403


def test_cell_lookup_agrees_with_distance_method_away_from_zone_borders(db):
    """1,000 random points checked both ways. A cell is in or out as a whole, so the two methods
    may only disagree within one cell-width of a zone border."""
    stores = db.scalars(select(Store)).all()
    rng = random.Random(4)
    differ = 0

    for _ in range(1000):
        lat, lng = rng.uniform(12.93, 13.08), rng.uniform(77.55, 77.64)
        distances = {s.id: service.distance_km(lat, lng, s.lat, s.lng) for s in stores}
        by_distance = min((km, sid) for sid, km in distances.items())
        expected = by_distance[1] if by_distance[0] <= 3.0 else None
        actual = service.check(db, lat, lng)["store_id"]
        if actual != expected:
            differ += 1
            assert any(abs(km - 3.0) < CELL_WIDTH_KM for km in distances.values()), (lat, lng, distances)

    assert differ / 1000 < 0.05, f"{differ / 10:.1f}% of points differ"


def test_start_up_rebuilds_zones_made_at_another_resolution(db, monkeypatch):
    monkeypatch.setattr(config, "H3_RESOLUTION", 8)

    seed.seed_if_empty(db)

    cell = db.scalar(select(StoreZone.h3_cell).limit(1))
    assert h3.get_resolution(cell) == 8
    assert service.check(db, 12.975, 77.60)["store_id"] == 1
