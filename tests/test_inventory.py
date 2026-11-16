"""Inventory Service: holds, releases, expiry, and the no-overselling rule (HLD 9.1)."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

from app.db import SessionLocal
from app.errors import DomainError
from app.models import Reservation, utcnow
from app.modules.inventory import service as inventory

from .conftest import assert_stock_is_consistent, atp


def hold(client, order_id, lines, store_id=1):
    return client.post("/v1/reservations", json={
        "order_id": order_id, "store_id": store_id,
        "lines": [{"sku_id": s, "qty": q} for s, q in lines]})


def test_hold_lowers_atp_but_not_on_hand(client, sku):
    rice = sku("Basmati rice")
    assert atp(client, 1, rice) == 30
    res = hold(client, "order-1", [(rice, 5)])
    assert res.status_code == 201 and res.json()["status"] == "held"
    row = client.get("/v1/stores/1/availability", params={"skus": str(rice)}).json()[0]
    assert (row["on_hand"], row["reserved"], row["atp"]) == (30, 5, 25)
    assert_stock_is_consistent()


def test_cart_is_held_whole_or_not_at_all(client, sku):
    rice, ice_cream = sku("Basmati rice"), sku("Vanilla ice cream")
    res = hold(client, "order-1", [(rice, 5), (ice_cream, 2)])       # only 1 ice cream exists
    assert res.status_code == 409
    error = res.json()["error"]
    assert error["code"] == "insufficient_stock"
    assert error["details"]["lines"] == [{"sku_id": ice_cream, "requested": 2, "available": 1}]
    assert atp(client, 1, rice) == 30                                 # the rice was not held either


def test_release_gives_stock_back(client, sku):
    rice = sku("Basmati rice")
    rid = hold(client, "order-1", [(rice, 5)]).json()["reservation_id"]
    assert client.delete(f"/v1/reservations/{rid}").json()["status"] == "released"
    assert atp(client, 1, rice) == 30
    assert client.delete(f"/v1/reservations/{rid}").status_code == 200   # releasing twice is harmless
    assert atp(client, 1, rice) == 30


def test_same_order_id_never_holds_twice(client, sku):
    rice = sku("Basmati rice")
    first = hold(client, "order-1", [(rice, 5)]).json()
    again = hold(client, "order-1", [(rice, 5)]).json()
    assert first["reservation_id"] == again["reservation_id"]
    assert atp(client, 1, rice) == 25


def test_expired_hold_is_swept_and_cannot_be_paid(client, db, sku):
    rice = sku("Basmati rice")
    rid = hold(client, "order-1", [(rice, 5)]).json()["reservation_id"]
    reservation = db.get(Reservation, rid)
    reservation.expires_at = utcnow() - timedelta(minutes=1)          # pretend 10 minutes have passed
    db.commit()

    paid = client.post(f"/v1/reservations/{rid}/confirm")
    assert paid.status_code == 409 and paid.json()["error"]["code"] == "hold_expired"
    assert atp(client, 1, rice) == 30

    rid2 = hold(client, "order-2", [(rice, 3)]).json()["reservation_id"]
    reservation2 = db.get(Reservation, rid2)
    reservation2.expires_at = utcnow() - timedelta(minutes=1)
    db.commit()
    assert client.post("/v1/admin/sweep-reservations").json() == {"released": 1}
    assert atp(client, 1, rice) == 30
    assert_stock_is_consistent()


def test_last_unit_goes_to_exactly_one_of_twenty_buyers(sku):
    """Twenty customers press checkout on the last ice cream at the same moment."""
    ice_cream = sku("Vanilla ice cream")

    def try_to_buy(n: int) -> bool:
        with SessionLocal() as session:
            try:
                inventory.reserve(session, f"race-{n}", 1, [(ice_cream, 1)])
                return True
            except DomainError:
                return False

    with ThreadPoolExecutor(max_workers=20) as pool:
        results = list(pool.map(try_to_buy, range(20)))

    assert results.count(True) == 1
    with SessionLocal() as session:
        level = inventory.get_level(session, 1, ice_cream)
        assert (level.qty_on_hand, level.qty_reserved) == (1, 1)


def test_damage_adjustment_updates_stock_and_ledger(client, sku):
    rice = sku("Basmati rice")
    res = client.post("/v1/stock-adjustments",
                      json={"store_id": 1, "sku_id": rice, "delta": -4, "reason": "damage"})
    assert res.status_code == 200 and res.json()["on_hand"] == 26
    newest = client.get("/v1/stores/1/ledger", params={"limit": 1}).json()[0]
    assert (newest["delta"], newest["reason"]) == (-4, "damage")
    too_many = client.post("/v1/stock-adjustments",
                           json={"store_id": 1, "sku_id": rice, "delta": -500, "reason": "damage"})
    assert too_many.status_code == 409
    assert_stock_is_consistent()
