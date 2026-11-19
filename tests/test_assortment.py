"""Assortment recommendations (guide task 3.7): what to add, what to drop, and how much shelf room is left."""
from .conftest import assert_stock_is_consistent, plant_sales

URL = "/v1/stores/{}/assortment/recommendations"


def test_a_sku_selling_elsewhere_is_recommended_where_it_is_missing(client, db, sku):
    bananas = sku("Bananas")
    plant_sales(db, {bananas: dict.fromkeys(range(1, 31), 3)})                  # store 1 sells 3 a day
    assert client.delete(f"/v1/stores/2/assortment/{bananas}").status_code == 200   # store 2: none on hand, held or coming
    assert client.delete(f"/v1/stores/2/assortment/{bananas}").status_code == 404   # no longer carried
    add = client.get(URL.format(2)).json()["add"]
    assert add == [{"sku_id": bananas, "sku": "Bananas (6 pcs)", "zone": "ambient", "daily_demand": 3.0,
                    "stores_selling": 1, "fits": True}]
    assert_stock_is_consistent()


def test_a_sku_with_stock_cannot_be_dropped(client, sku):
    refused = client.delete(f"/v1/stores/1/assortment/{sku('Toned milk')}")
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "still_stocked"
    assert "30 on hand" in refused.json()["error"]["message"]
    client.post("/v1/replenishment/run", params={"store_id": 2})                 # bananas are now on their way
    coming = client.delete(f"/v1/stores/2/assortment/{sku('Bananas')}")
    assert coming.status_code == 409 and "on their way" in coming.json()["error"]["message"]
    assert len(client.get("/v1/stores/2/assortment").json()) == 16


def test_dead_stock_and_shelf_room(client):
    body = client.get(URL.format(1)).json()
    drop = {row["sku"] for row in body["drop"]}
    assert "Basmati rice 1 kg" in drop and "Toned milk 500 ml" not in drop      # rice has stock but no sale in the seed week
    assert body["space"] == [{"zone": "ambient", "bins": 12, "skus": 11, "room_for": 1},
                             {"zone": "chilled", "bins": 4, "skus": 3, "room_for": 1},
                             {"zone": "frozen", "bins": 2, "skus": 2, "room_for": 0}]


def test_recommendations_are_for_staff_and_dropping_is_for_managers(client_as, sku):
    tea = sku("Tea")
    assert client_as("picker", 1).get(URL.format(1)).status_code == 200
    assert client_as("picker", 1).get(URL.format(2)).status_code == 403
    assert client_as("picker", 1).delete(f"/v1/stores/1/assortment/{tea}").status_code == 403
    assert client_as("manager", 2).delete(f"/v1/stores/1/assortment/{tea}").status_code == 403
    assert client_as("manager", 1).delete(f"/v1/stores/1/assortment/{tea}").status_code == 409   # 30 on hand
