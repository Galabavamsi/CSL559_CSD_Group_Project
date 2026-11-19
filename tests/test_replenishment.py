"""Smarter replenishment (guide task 3.4): whole cases, free bin space, runs by itself."""
from .conftest import assert_stock_is_consistent


def test_orders_are_rounded_up_to_full_cases(client, sku):
    milk = sku("Toned milk")                                   # case of 12; reorder point 10, target 40
    client.post("/v1/stock-adjustments", json={"store_id": 1, "sku_id": milk, "delta": -27, "reason": "damage"})
    order = client.post("/v1/replenishment/run", params={"store_id": 1}).json()["transfer_order"]
    lines = {line["sku_id"]: line["qty_ordered"] for line in order["lines"]}
    assert lines[milk] == 48                                   # 40 - 3 = 37 needed -> 4 cases of 12
    assert lines[sku("White bread")] == 40                     # 36 needed -> 4 cases of 10
    assert_stock_is_consistent()
