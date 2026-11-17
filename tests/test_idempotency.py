"""Idempotency keys (HLD 8, task 1.4): a retried write never moves stock twice."""
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import func, select

from app.models import IdempotencyRecord, StockLedger

from .conftest import _logged_in, assert_stock_is_consistent

URL = "/v1/stock-adjustments"


def write_off(client, rice, key=None, qty=4):
    headers = {"Idempotency-Key": key} if key else {}
    return client.post(URL, headers=headers, json={"store_id": 1, "sku_id": rice, "delta": -qty, "reason": "damage"})


def damage_rows(db, sku_id):
    return db.scalar(select(func.count()).select_from(StockLedger)
                     .where(StockLedger.sku_id == sku_id, StockLedger.reason == "damage"))


def test_same_key_twice_changes_stock_once(client, db, sku):
    """A manager double-clicks "write off 4 damaged"."""
    rice = sku("Basmati rice")
    first = write_off(client, rice, key="click-1")
    again = write_off(client, rice, key="click-1")
    assert first.status_code == again.status_code == 200
    assert first.json() == again.json() == {"sku_id": rice, "on_hand": 26, "reserved": 0, "atp": 26}
    assert damage_rows(db, rice) == 1
    assert_stock_is_consistent()


def test_two_keys_are_two_write_offs(client, db, sku):
    rice = sku("Basmati rice")
    write_off(client, rice, key="click-1")
    assert write_off(client, rice, key="click-2").json()["on_hand"] == 22
    assert damage_rows(db, rice) == 2


def test_without_a_key_nothing_changes(client, sku):
    rice = sku("Basmati rice")
    write_off(client, rice)
    assert write_off(client, rice).json()["on_hand"] == 22             # no key, no protection: old behaviour


def test_a_key_reused_for_another_request_is_refused(client, db, sku):
    rice = sku("Basmati rice")
    write_off(client, rice, key="click-1", qty=4)
    reused = write_off(client, rice, key="click-1", qty=5)
    assert reused.status_code == 422 and reused.json()["error"]["code"] == "idempotency_key_reused"
    assert damage_rows(db, rice) == 1


def test_a_failed_write_is_not_remembered(client, db, sku):
    """Nothing is saved when the write is refused, so the same key can be retried once the problem is fixed."""
    rice = sku("Basmati rice")
    too_many = write_off(client, rice, key="click-1", qty=31)
    assert too_many.status_code == 409
    assert db.scalar(select(func.count()).select_from(IdempotencyRecord)) == 0
    assert write_off(client, rice, key="click-2", qty=4).status_code == 200


def test_ten_copies_at_once_write_off_once(client, db, sku):
    """A flaky network: the same request arrives ten times at the same moment."""
    rice = sku("Basmati rice")

    def send(_n: int):
        with _logged_in("admin") as c:
            return write_off(c, rice, key="retry-storm")

    with ThreadPoolExecutor(max_workers=10) as pool:
        answers = list(pool.map(send, range(10)))
    assert {a.status_code for a in answers} == {200}
    assert {a.json()["on_hand"] for a in answers} == {26}
    assert damage_rows(db, rice) == 1
    assert_stock_is_consistent()


def test_keys_are_per_endpoint(client, db, sku):
    """The same key on another endpoint is a different request; only stock adjustments use keys today."""
    rice = sku("Basmati rice")
    write_off(client, rice, key="shared")
    assert db.get(IdempotencyRecord, ("stock-adjustment", "shared")) is not None
    assert db.get(IdempotencyRecord, ("goods-receipt", "shared")) is None
