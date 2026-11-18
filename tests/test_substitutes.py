"""Substitutes for dropped lines, first half (Member 2 guide, task 2.4): the offer and the refund event.

Accepting an offer (POST /v1/fulfilment-jobs/{id}/substitutions) needs Member 1's inventory.swap_line and comes next.
Store 1 has one vanilla ice cream (Rs 120, Frozen) and 30 frozen green peas (Rs 95, Frozen); Staples are rice (Rs 140),
oil (Rs 155), sugar (Rs 48) and atta (Rs 245), 30 of each, each in one bin."""
from datetime import date, timedelta

from sqlalchemy import select

from app.models import StockItem
from app.modules.pickpack import service as pickpack

from .conftest import assert_stock_is_consistent, atp, place_paid_order
from .test_order_flow import next_job


def events_of(client, event_type: str) -> list[dict]:
    return [e["payload"] for e in client.get("/v1/events", params={"limit": 200}).json() if e["type"] == event_type]


def hold(client, order_id: str, sku_id: int, qty: int) -> None:
    """Another customer's unpaid hold, to take stock out of what customers can buy."""
    res = client.post("/v1/reservations", json={"order_id": order_id, "store_id": 1,
                                                "lines": [{"sku_id": sku_id, "qty": qty}]})
    assert res.status_code == 201, res.text


def report_empty(client, sku_id: int, order_qty: int = 1, found: int | None = None, order_id: str = "s-1") -> dict:
    """Pay for `order_qty` of one item, claim it, and report its first line short."""
    place_paid_order(client, order_id, 1, [(sku_id, order_qty)])
    line = next_job(client)["tasks"][0]
    res = client.post(f"/v1/pick-tasks/{line['task_id']}/short", json={"found": found} if found is not None else None)
    assert res.status_code == 200, res.text
    return res.json()


def test_the_last_ice_cream_is_missing_so_peas_are_offered_and_the_line_refunded(client, sku):
    ice_cream, peas = sku("Vanilla ice cream"), sku("Frozen green peas")
    peas_before = atp(client, 1, peas)

    result = report_empty(client, ice_cream)

    assert result["dropped"] == 1
    assert result["substitute_offer"] == {"sku_id": peas, "name": "Frozen green peas 500 g", "price": 95}
    assert result["message"].endswith("Possible substitute: Frozen green peas 500 g (Rs 95).")
    job_id = result["job"]["job_id"]
    assert events_of(client, "order.line_dropped") == [
        {"order_id": "s-1", "job_id": job_id, "sku_id": ice_cream, "qty": 1, "refund_amount": 120}]
    assert atp(client, 1, peas) == peas_before              # an offer holds nothing
    assert_stock_is_consistent()


def test_with_nothing_left_in_the_category_the_offer_is_null_but_the_refund_is_still_published(client, sku):
    ice_cream, peas = sku("Vanilla ice cream"), sku("Frozen green peas")
    hold(client, "all-the-peas", peas, atp(client, 1, peas))

    result = report_empty(client, ice_cream)

    assert result["dropped"] == 1 and result["substitute_offer"] is None
    assert "substitute" not in result["message"]
    assert [e["sku_id"] for e in events_of(client, "order.line_dropped")] == [ice_cream]
    assert_stock_is_consistent()


def test_the_nearest_price_wins_among_items_customers_can_still_buy(client, sku):
    rice, oil, sugar = sku("Basmati rice"), sku("Sunflower oil"), sku("Sugar")

    first = report_empty(client, rice, order_qty=6, found=4, order_id="s-1")   # 2 rice dropped, Rs 140 each
    assert first["substitute_offer"]["sku_id"] == oil                          # Rs 155: 15 away
    assert events_of(client, "order.line_dropped")[0]["refund_amount"] == 280

    hold(client, "most-of-the-oil", oil, atp(client, 1, oil) - 1)              # 1 oil left; 2 are needed
    client.post(f"/v1/fulfilment-jobs/{first['job']['job_id']}/packed", json={"crate_slot": "S-01"})
    second = report_empty(client, rice, order_qty=3, found=1, order_id="s-2")
    assert second["substitute_offer"]["sku_id"] == sugar                       # Rs 48: 92 away, atta is 105
    assert_stock_is_consistent()


def test_a_line_moved_to_another_bin_is_not_refunded_and_gets_no_offer(client, sku):
    result = report_empty(client, sku("Toned milk"), order_qty=4)   # M-OLD empty; M-NEW has plenty

    assert (result["reallocated"], result["dropped"], result["substitute_offer"]) == (4, 0, None)
    assert events_of(client, "order.line_dropped") == []
    assert_stock_is_consistent()


def test_units_that_cannot_be_found_when_the_order_is_paid_are_refunded_too(client, db, sku):
    """Batch M-OLD expired after the hold was placed but before the hourly write-off: only 24 milk can be picked."""
    milk = sku("Toned milk")
    hold_id = client.post("/v1/reservations", json={"order_id": "s-9", "store_id": 1,
                                                    "lines": [{"sku_id": milk, "qty": 26}]}).json()["reservation_id"]
    db.scalar(select(StockItem).where(StockItem.batch_no == "M-OLD")).expiry_date = date.today() - timedelta(days=1)
    db.commit()

    assert client.post(f"/v1/reservations/{hold_id}/confirm").status_code == 200

    tasks = next_job(client)["tasks"]
    assert sorted((t["status"], t["qty"]) for t in tasks) == [("pending", 24), ("short", 2)]
    [dropped] = events_of(client, "order.line_dropped")
    assert (dropped["order_id"], dropped["sku_id"], dropped["qty"], dropped["refund_amount"]) == ("s-9", milk, 2, 56)
    assert_stock_is_consistent()


def test_find_substitute_looks_only_in_the_same_category(db, sku):
    assert pickpack.find_substitute(db, 1, sku("White bread"), 1) is None       # the only Bakery item
    assert pickpack.find_substitute(db, 1, sku("Tea"), 1) is None               # the only Beverage
    assert pickpack.find_substitute(db, 1, sku("Frozen green peas"), 1)["sku_id"] == sku("Vanilla ice cream")
    assert pickpack.find_substitute(db, 1, sku("Frozen green peas"), 2) is None  # only 1 ice cream
