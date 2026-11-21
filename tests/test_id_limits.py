"""Limits on the ids sent to Inventory (found in the review of #50, which capped the quantities).

An id of 10**20 used to reach the database and come back as a 500 (an integer overflow on SQLite). Ids are 32-bit
integers from 1, so anything else is now a 422 that never reaches a query, while an id that is merely unknown is still
a 404."""
import pytest
from fastapi.testclient import TestClient

from app.main import app

from .conftest import assert_stock_is_consistent
from .test_cycle_counts import start, submit

HUGE = 10**20
BAD_IDS = (HUGE, -HUGE, 2**31, 0)


@pytest.fixture()
def api(client):
    """The admin client, answering with the 500 a real caller would get where the plain one raises the error."""
    with TestClient(app, raise_server_exceptions=False, headers=dict(client.headers)) as quiet:
        yield quiet


def hold(api, store_id: int, sku_id: int):
    return api.post("/v1/reservations", json={"order_id": "ids", "store_id": store_id,
                                              "lines": [{"sku_id": sku_id, "qty": 1}]})


@pytest.mark.parametrize("bad", BAD_IDS)
def test_an_impossible_id_in_a_request_body_is_refused(api, sku, bad):
    rice = sku("Basmati rice")
    adjustment = {"store_id": 1, "sku_id": rice, "delta": -1, "reason": "damage"}

    assert hold(api, 1, bad).status_code == 422
    assert hold(api, bad, rice).status_code == 422
    assert api.post("/v1/stock-adjustments", json={**adjustment, "sku_id": bad}).status_code == 422
    assert api.post("/v1/stock-adjustments", json={**adjustment, "store_id": bad}).status_code == 422
    assert api.post("/v1/stock-adjustments", json={**adjustment, "bin_id": bad}).status_code == 422
    assert api.post("/v1/cycle-counts", json={"store_id": 1, "bin_id": bad}).status_code == 422
    assert api.post("/v1/cycle-counts", json={"store_id": bad, "bin_id": 1}).status_code == 422
    assert_stock_is_consistent()


@pytest.mark.parametrize("bad", BAD_IDS)
def test_an_impossible_id_in_the_address_is_refused(api, bad):
    for path in ("/v1/stores/{}/availability", "/v1/stores/{}/stock", "/v1/stores/{}/ledger",
                 "/v1/stores/{}/near-expiry", "/v1/stores/{}/cycle-counts", "/v1/stores/{}/inventory-accuracy",
                 "/v1/cycle-counts/{}"):
        assert api.get(path.format(bad)).status_code == 422, path
    assert api.get("/v1/admin/stock-audit", params={"store_id": bad}).status_code == 422
    assert api.post("/v1/admin/expire-stock", params={"store_id": bad}).status_code == 422
    assert api.put(f"/v1/stores/1/stock-settings/{bad}", json={"safety_buffer": 1}).status_code == 422
    assert api.post(f"/v1/cycle-counts/{bad}/approve").status_code == 422


def test_a_counted_line_takes_only_a_possible_sku_id(api, sku):
    rice = sku("Basmati rice")
    count = start(api, rice)

    assert submit(api, count, {HUGE: 1}).status_code == 422
    assert submit(api, count, {rice: 30}).status_code == 200


def test_the_sku_list_of_availability_takes_only_ids(api, sku):
    rice, sugar = sku("Basmati rice"), sku("Sugar")

    assert api.get("/v1/stores/1/availability", params={"skus": f"{rice},{HUGE}"}).status_code == 422
    assert api.get("/v1/stores/1/availability", params={"skus": "rice"}).status_code == 422
    assert api.get("/v1/stores/1/availability", params={"skus": f"{rice},0"}).status_code == 422
    spaced = api.get("/v1/stores/1/availability", params={"skus": f"{rice}, {sugar},"})
    assert [row["sku_id"] for row in spaced.json()] == sorted([rice, sugar])


def test_the_ledger_returns_at_most_500_rows_per_request(api):
    assert api.get("/v1/stores/1/ledger", params={"limit": HUGE}).status_code == 422
    assert api.get("/v1/stores/1/ledger", params={"limit": 0}).status_code == 422
    assert api.get("/v1/stores/1/ledger", params={"limit": 500}).status_code == 200


def test_an_id_that_is_possible_but_unknown_is_still_not_found(api, sku):
    assert hold(api, 99, sku("Basmati rice")).status_code == 404
    assert api.get("/v1/admin/stock-audit", params={"store_id": 99}).status_code == 404
    assert api.get(f"/v1/cycle-counts/{2**31 - 1}").status_code == 404
