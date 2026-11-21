"""Upper limits on quantities sent to Inventory (found in the review of #28 and #30).

A huge number (10**20) used to reach the database and come back as a 500 (an integer overflow). Now each field has a
limit and the answer is a 422 naming the field: a cart line up to 1,000 units, a counted quantity and one stock
adjustment up to 100,000 (what a bin can hold)."""
from .conftest import assert_stock_is_consistent
from .test_cycle_counts import start, submit

HUGE = 10**20


def hold(client, qty: int, sku_id: int):
    return client.post("/v1/reservations", json={"order_id": f"q-{qty}", "store_id": 1,
                                                 "lines": [{"sku_id": sku_id, "qty": qty}]})


def test_a_cart_line_is_at_most_1000_units(client, sku):
    tea = sku("Tea")

    assert hold(client, HUGE, tea).status_code == 422
    assert hold(client, 1001, tea).status_code == 422
    allowed = hold(client, 1000, tea)                              # a valid size, just more than the store has
    assert allowed.status_code == 409 and allowed.json()["error"]["code"] == "insufficient_stock"
    assert_stock_is_consistent()


def test_a_counted_quantity_is_at_most_100000(client, sku):
    rice = sku("Basmati rice")
    count = start(client, rice)

    assert submit(client, count, {rice: HUGE}).status_code == 422
    assert submit(client, count, {rice: 30}).status_code == 200    # the count is still open and takes a real number


def test_a_stock_adjustment_is_at_most_100000_either_way(client, sku):
    body = {"store_id": 1, "sku_id": sku("Sugar"), "reason": "damage"}

    assert client.post("/v1/stock-adjustments", json={**body, "delta": -HUGE}).status_code == 422
    assert client.post("/v1/stock-adjustments", json={**body, "delta": HUGE}).status_code == 422
    assert client.post("/v1/stock-adjustments", json={**body, "delta": -1}).status_code == 200
    assert_stock_is_consistent()
