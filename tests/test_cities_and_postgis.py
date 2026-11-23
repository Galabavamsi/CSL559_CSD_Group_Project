"""Cities, and distance questions answered by PostGIS on the hub locations (HLD 8: nearest hub, hubs within radius)."""
from sqlalchemy import select, text

from app.models import City, Store
from app.modules.serviceability import service as serviceability

CENTRAL = (12.9716, 77.5946)     # DS-01 Central, as seeded
NORTH = (13.0350, 77.5970)       # DS-02 North, about 7 km north of it
BHILAI = (21.1938, 81.3509)


def test_the_seed_has_a_tier_1_and_a_tier_2_city_and_every_hub_is_in_one(client, db):
    cities = {c["city"]: c for c in client.get("/v1/cities").json()}

    assert (cities["bangalore"]["tier"], cities["bangalore"]["hubs"]) == (1, 2)
    assert (cities["bhilai"]["tier"], cities["bhilai"]["hubs"]) == (2, 0)
    assert cities["bangalore"]["hub_radius_km"] < cities["bhilai"]["hub_radius_km"]     # denser city, smaller radius
    assert db.scalars(select(Store).where(Store.city_id.is_(None))).all() == []


def test_hubs_can_be_listed_for_one_city(client):
    assert [s["city"] for s in client.get("/v1/stores").json()] == ["bangalore", "bangalore"]
    assert len(client.get("/v1/stores", params={"city": "bangalore"}).json()) == 2
    assert client.get("/v1/stores", params={"city": "bhilai"}).json() == []
    assert client.get("/v1/stores", params={"city": "nowhere"}).json() == []


def test_the_database_keeps_each_location_point_in_step_with_lat_and_lng(db):
    store = db.get(Store, 1)
    store.lat, store.lng = 13.0, 77.6
    db.commit()

    lng, lat = db.execute(text("SELECT ST_X(location::geometry), ST_Y(location::geometry) "
                               "FROM stores WHERE id = 1")).one()

    assert (round(lat, 6), round(lng, 6)) == (13.0, 77.6)


def test_nearest_hub_is_found_with_its_distance(db):
    store, km = serviceability.nearest_store(db, 13.03, 77.597)       # 0.55 km south of DS-02
    assert store.name == "DS-02 North" and 0.5 < km < 0.6

    store, km = serviceability.nearest_store(db, *CENTRAL)
    assert store.name == "DS-01 Central" and km < 0.001


def test_nearest_hub_skips_closed_hubs_unless_asked_and_can_be_kept_to_one_city(db):
    db.get(Store, 2).status = "closed"
    db.commit()
    bhilai = db.scalar(select(City.id).where(City.slug == "bhilai"))

    assert serviceability.nearest_store(db, *NORTH)[0].name == "DS-01 Central"
    assert serviceability.nearest_store(db, *NORTH, include_closed=True)[0].name == "DS-02 North"
    assert serviceability.nearest_store(db, *BHILAI, city_id=bhilai) is None      # no hub there yet
    assert serviceability.nearest_store(db, *BHILAI)[1] > 900                     # the nearest one is in Bangalore


def test_hubs_covering_a_point_are_those_whose_own_radius_reaches_it(db):
    midway = (13.0033, 77.5958)          # about 3.5 km from each hub: outside both 3 km radii
    assert serviceability.stores_covering(db, *midway) == []

    db.get(Store, 2).radius_km = 4.0
    db.commit()
    assert [s.name for s, _ in serviceability.stores_covering(db, *midway)] == ["DS-02 North"]

    db.get(Store, 1).radius_km = 4.0
    db.commit()
    covering = serviceability.stores_covering(db, *midway)
    assert {s.name for s, _ in covering} == {"DS-01 Central", "DS-02 North"}
    assert covering[0][1] <= covering[1][1]                                       # nearest first

    db.get(Store, 1).status = "closed"
    db.commit()
    assert [s.name for s, _ in serviceability.stores_covering(db, *midway)] == ["DS-02 North"]


def test_a_point_just_inside_the_radius_is_covered_and_just_outside_is_not(db):
    store = db.get(Store, 1)
    lat, lng = db.execute(text(
        "SELECT ST_Y(p::geometry), ST_X(p::geometry) FROM "
        "(SELECT ST_Project(location, 3000, radians(90)) AS p FROM stores WHERE id = 1) AS t")).one()
    km = db.scalar(text("SELECT ST_Distance(location, ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography, false) "
                        "/ 1000 FROM stores WHERE id = 1"), {"lat": lat, "lng": lng})

    store.radius_km = km + 0.001
    db.commit()
    assert [s.id for s, _ in serviceability.stores_covering(db, lat, lng)] == [1]

    store.radius_km = km - 0.001
    db.commit()
    assert serviceability.stores_covering(db, lat, lng) == []


def test_a_customer_outside_every_zone_is_told_the_nearest_hub_by_postgis(client):
    res = client.get("/v1/serviceability", params={"lat": BHILAI[0], "lng": BHILAI[1]}).json()

    assert res["serviceable"] is False
    assert res["nearest_store"] in ("DS-01 Central", "DS-02 North") and res["nearest_distance_km"] > 900
