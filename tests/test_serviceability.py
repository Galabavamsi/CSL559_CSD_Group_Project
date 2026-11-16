"""Serviceability and network planning."""


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
