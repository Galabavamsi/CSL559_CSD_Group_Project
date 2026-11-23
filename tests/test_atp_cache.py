"""ATP cache (HLD 9.2, task 1.6): whole-store availability is served from a short-lived cache that every stock change
clears, and holds never trust it."""
from datetime import timedelta

from sqlalchemy import select

from app import cache, clock, seed
from app.cache import TTLCache, atp_cache
from app.db import SessionLocal
from app.models import StockItem
from app.modules.inventory import service as inventory

from .conftest import assert_stock_is_consistent, place_paid_order
from .test_order_flow import next_job, scan_all


def store_list(client, store_id=1) -> dict[int, dict]:
    """The whole-store availability list (the cached one), by SKU."""
    return {row["sku_id"]: row for row in client.get(f"/v1/stores/{store_id}/availability").json()}


def primed(client, store_id=1) -> None:
    store_list(client, store_id)
    assert atp_cache.get(store_id) is not None


def hold(client, order_id, sku_id, qty, store_id=1):
    return client.post("/v1/reservations", json={"order_id": order_id, "store_id": store_id,
                                                  "lines": [{"sku_id": sku_id, "qty": qty}]})


def test_a_hold_shows_at_once(client, sku):
    rice = sku("Basmati rice")
    assert store_list(client)[rice]["atp"] == 30                         # now cached
    hold(client, "order-1", rice, 5)
    assert store_list(client)[rice]["atp"] == 25                         # the hold cleared the cache


def test_a_stale_cache_cannot_cause_an_oversell(client, sku):
    """Pretend the cache is badly out of date: it shows 1,000 rice. The hold still checks the database."""
    rice = sku("Basmati rice")
    rows = [dict(row, atp=1000, on_hand=1000) if row["sku_id"] == rice else row
            for row in client.get("/v1/stores/1/availability").json()]
    atp_cache.set(1, rows)
    assert store_list(client)[rice]["atp"] == 1000                       # the customer is shown the wrong number...
    refused = hold(client, "order-1", rice, 31)
    assert refused.status_code == 409                                    # ...but cannot hold more than really exists
    assert refused.json()["error"]["details"]["lines"][0]["available"] == 30
    assert_stock_is_consistent()


def expire_a_batch(db):
    db.scalar(select(StockItem).where(StockItem.store_id == 1, StockItem.batch_no == "M-OLD")).expiry_date =         clock.today() - timedelta(days=1)
    db.commit()
    assert inventory.expire_stock(db, 1) == 6


def test_every_kind_of_stock_change_clears_the_store(client, db, sku):
    rice, tea = sku("Basmati rice"), sku("Tea")
    bin_id = next(r["bin_id"] for r in client.get("/v1/stores/1/stock").json() if r["sku_id"] == rice)
    changes = {
        "hold": lambda: hold(client, "order-1", rice, 2),
        "release": lambda: client.delete(f"/v1/reservations/{hold(client, 'order-2', rice, 1).json()['reservation_id']}"),
        "adjustment": lambda: client.post("/v1/stock-adjustments", json={
            "store_id": 1, "sku_id": rice, "delta": -1, "reason": "damage"}),
        "goods receipt": lambda: client.post("/v1/goods-receipts", json={
            "store_id": 1, "lines": [{"sku_id": rice, "qty": 3, "bin_id": bin_id}]}),
        "safety buffer": lambda: client.put(f"/v1/stores/1/stock-settings/{rice}", json={"safety_buffer": 1}),
        "expiry write-off": lambda: expire_a_batch(db),
    }
    for name, change in changes.items():
        primed(client)
        change()
        assert atp_cache.get(1) is None, f"{name} left the cached list in place"

    primed(client)
    place_paid_order(client, "order-3", 1, [(tea, 1)])
    scan_all(client, next_job(client))
    primed(client)
    client.post("/v1/fulfilment-jobs/1/packed", json={"crate_slot": "S-01"})   # the sale leaves on-hand stock
    assert atp_cache.get(1) is None
    assert_stock_is_consistent()


def test_another_module_adding_or_dropping_a_sku_clears_the_store(client, sku):
    """Assortment writes StockLevel rows itself (db.add and a bulk delete); the cache notices both."""
    bananas = sku("Bananas")                                             # store 2 has none on hand
    primed(client, 2)
    assert client.delete(f"/v1/stores/2/assortment/{bananas}").status_code == 200
    assert atp_cache.get(2) is None and bananas not in store_list(client, 2)
    assert client.post("/v1/stores/2/assortment", json={"sku_id": bananas}).status_code in (200, 201)
    assert bananas in store_list(client, 2)


def test_a_change_in_one_store_leaves_the_other_cached(client, sku):
    primed(client, 1)
    primed(client, 2)
    hold(client, "order-1", sku("Basmati rice"), 1, store_id=1)
    assert atp_cache.get(1) is None and atp_cache.get(2) is not None


def test_an_old_copy_cached_before_the_commit_is_dropped_after_it(client, sku):
    """The gap the guide warns about: a write is not committed yet, another request reads the old numbers and caches
    them. The drop after the commit removes that copy."""
    rice = sku("Basmati rice")
    with SessionLocal() as writer:
        inventory.unreserve(writer, 1, rice, -5)                         # hold 5 more, not committed yet
        with SessionLocal() as reader:
            assert inventory.availability(reader, 1)[0] is not None      # caches the old, committed numbers
        assert atp_cache.get(1) is not None
        writer.commit()
    assert atp_cache.get(1) is None
    assert store_list(client)[rice]["atp"] == 25


def test_a_rolled_back_write_changes_nothing(client, sku):
    rice = sku("Basmati rice")
    with SessionLocal() as writer:
        inventory.unreserve(writer, 1, rice, -5)
        writer.rollback()
    assert store_list(client)[rice]["atp"] == 30


def test_reset_demo_data_clears_the_cache(client, sku):
    rice = sku("Basmati rice")
    hold(client, "order-1", rice, 5)
    assert store_list(client)[rice]["atp"] == 25
    seed.reset()
    assert store_list(client)[rice]["atp"] == 30


def test_entries_expire(monkeypatch):
    now = [100.0]
    monkeypatch.setattr(cache.time, "monotonic", lambda: now[0])
    short = TTLCache(ttl_seconds=2)
    short.set("k", "v")
    now[0] += 1.9
    assert short.get("k") == "v"
    now[0] += 0.2
    assert short.get("k") is None


def test_zero_seconds_turns_the_cache_off():
    off = TTLCache(ttl_seconds=0)
    off.set("k", "v")
    assert off.get("k") is None
