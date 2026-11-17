"""Inventory Service: holds, releases, expiry, and the no-overselling rule (HLD 9.1)."""
import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

from app import background, config
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


# --------------------------------------------------------------------------- safety buffer (task 1.1, HLD 7.1)


def test_safety_buffer_hides_units_from_customers(client, sku):
    """The seed gives milk in store 1 a buffer of 2: 30 on hand shows as 28 available."""
    milk = sku("Toned milk")
    row = client.get("/v1/stores/1/availability", params={"skus": str(milk)}).json()[0]
    assert (row["on_hand"], row["reserved"], row["safety_buffer"], row["atp"]) == (30, 0, 2, 28)

    too_many = hold(client, "order-29", [(milk, 29)])
    assert too_many.status_code == 409
    assert too_many.json()["error"]["details"]["lines"] == [{"sku_id": milk, "requested": 29, "available": 28}]
    assert hold(client, "order-28", [(milk, 28)]).status_code == 201
    assert atp(client, 1, milk) == 0
    assert_stock_is_consistent()


def test_set_safety_buffer(client, sku):
    rice = sku("Basmati rice")
    res = client.put(f"/v1/stores/1/stock-settings/{rice}", json={"safety_buffer": 5})
    assert res.status_code == 200, res.text
    assert (res.json()["safety_buffer"], res.json()["atp"]) == (5, 25)
    assert atp(client, 1, rice) == 25
    assert atp(client, 2, rice) == 30                                   # only that store changed

    client.put(f"/v1/stores/1/stock-settings/{rice}", json={"safety_buffer": 50})
    assert atp(client, 1, rice) == 0                                    # never below zero
    assert hold(client, "order-1", [(rice, 1)]).status_code == 409


def test_buffer_does_not_touch_existing_holds(client, sku):
    rice = sku("Basmati rice")
    held = hold(client, "order-1", [(rice, 28)]).json()
    client.put(f"/v1/stores/1/stock-settings/{rice}", json={"safety_buffer": 5})
    assert atp(client, 1, rice) == 0
    paid = client.post(f"/v1/reservations/{held['reservation_id']}/confirm")
    assert paid.status_code == 200 and paid.json()["status"] == "confirmed"
    assert_stock_is_consistent()


def test_stock_settings_rejects_bad_input(client, sku):
    rice = sku("Basmati rice")
    assert client.put(f"/v1/stores/1/stock-settings/{rice}", json={"safety_buffer": -1}).status_code == 422
    assert client.put("/v1/stores/1/stock-settings/99999", json={"safety_buffer": 1}).status_code == 404
    assert client.put(f"/v1/stores/999/stock-settings/{rice}", json={"safety_buffer": 1}).status_code == 404


def test_only_the_stores_manager_sets_the_buffer(client_as, sku):
    rice = sku("Basmati rice")
    url, body = f"/v1/stores/1/stock-settings/{rice}", {"safety_buffer": 3}
    with client_as("picker", 1) as picker:
        assert picker.put(url, json=body).status_code == 403
    with client_as("manager", 2) as other_manager:
        assert other_manager.put(url, json=body).status_code == 403
    with client_as("manager", 1) as manager:
        assert manager.put(url, json=body).status_code == 200


def test_dashboard_counts_buffered_skus_as_out_of_stock(client, sku):
    before = client.get("/v1/stores/1/dashboard").json()["skus_out_of_stock"]
    rice = sku("Basmati rice")
    client.put(f"/v1/stores/1/stock-settings/{rice}", json={"safety_buffer": 30})
    assert client.get("/v1/stores/1/dashboard").json()["skus_out_of_stock"] == before + 1


# --------------------------------------------------------------------------- automatic sweeper (task 1.2, HLD 9.1)


def _back_date(db, reservation_id: str) -> None:
    db.get(Reservation, reservation_id).expires_at = utcnow() - timedelta(minutes=1)
    db.commit()


def test_ten_releases_of_one_hold_give_the_stock_back_once(client, sku):
    """The sweeper, a cancel and another instance's sweeper can all see the same hold as "held" at once.
    Every thread reads the hold first and only then releases it, so all ten really do race."""
    rice = sku("Basmati rice")
    rid = hold(client, "order-1", [(rice, 5)]).json()["reservation_id"]
    everyone_has_read = threading.Barrier(10)

    def release_it(_n: int) -> bool:
        with SessionLocal() as session:
            res = inventory.get_reservation(session, rid)
            assert res.status == "held"
            everyone_has_read.wait()
            gave_back = inventory._release(session, res, "released")
            session.commit()
            return gave_back

    with ThreadPoolExecutor(max_workers=10) as pool:
        results = list(pool.map(release_it, range(10)))
    assert results.count(True) == 1
    assert atp(client, 1, rice) == 30
    assert_stock_is_consistent()


def test_release_through_the_api_ten_times_at_once(client, sku):
    rice = sku("Basmati rice")
    rid = hold(client, "order-1", [(rice, 5)]).json()["reservation_id"]

    def release_it(_n: int) -> str:
        with SessionLocal() as session:
            return inventory.release(session, rid).status

    with ThreadPoolExecutor(max_workers=10) as pool:
        assert set(pool.map(release_it, range(10))) == {"released"}
    assert atp(client, 1, rice) == 30
    assert_stock_is_consistent()


def test_sweep_once_releases_a_back_dated_hold(client, db, sku):
    rice = sku("Basmati rice")
    old = hold(client, "order-1", [(rice, 5)]).json()["reservation_id"]
    hold(client, "order-2", [(rice, 3)])                                     # still within its 10 minutes
    _back_date(db, old)
    assert background.sweep_once() == 1
    assert atp(client, 1, rice) == 27
    assert background.sweep_once() == 0                                     # nothing left to release
    assert client.get(f"/v1/reservations/{old}").json()["status"] == "expired"
    assert_stock_is_consistent()


def test_sweep_loop_runs_on_its_own(client, db, sku, monkeypatch):
    rice = sku("Basmati rice")
    rid = hold(client, "order-1", [(rice, 5)]).json()["reservation_id"]
    _back_date(db, rid)
    monkeypatch.setattr(config, "SWEEP_INTERVAL_SECONDS", 0.05)

    async def run_briefly():
        loop = asyncio.create_task(background.sweep_loop())
        for _ in range(100):
            await asyncio.sleep(0.05)
            if atp(client, 1, rice) == 30:
                break
        loop.cancel()

    asyncio.run(run_briefly())
    assert atp(client, 1, rice) == 30
    assert_stock_is_consistent()


def test_payment_and_expiry_at_the_same_instant(client, sku):
    """Confirm and release both read "held"; exactly one of them changes it, and the stock agrees with the winner."""
    rice = sku("Basmati rice")
    rid = hold(client, "order-1", [(rice, 5)]).json()["reservation_id"]
    both_have_read = threading.Barrier(2)

    def pay():
        with SessionLocal() as session:
            res = inventory.get_reservation(session, rid)
            both_have_read.wait()
            try:
                return inventory._change_status(session, res, "held", "confirmed")
            finally:
                session.commit()

    def expire():
        with SessionLocal() as session:
            res = inventory.get_reservation(session, rid)
            both_have_read.wait()
            gave_back = inventory._release(session, res, "expired")
            session.commit()
            return gave_back

    with ThreadPoolExecutor(max_workers=2) as pool:
        paid, expired = pool.submit(pay), pool.submit(expire)
        assert paid.result() != expired.result()                       # one winner, never both
    final = client.get(f"/v1/reservations/{rid}").json()["status"]
    assert atp(client, 1, rice) == (25 if final == "confirmed" else 30)
    assert_stock_is_consistent()


def test_confirm_after_the_sweeper_won_says_expired(client, db, sku):
    rice = sku("Basmati rice")
    rid = hold(client, "order-1", [(rice, 5)]).json()["reservation_id"]
    _back_date(db, rid)
    background.sweep_once()
    paid = client.post(f"/v1/reservations/{rid}/confirm")
    assert paid.status_code == 409 and paid.json()["error"]["code"] == "not_held"
    assert atp(client, 1, rice) == 30
