"""Two requests at the same moment (issues #81 and #82, found and first tested by Member 3).

Each test lets both requests get past the same check before either writes, which is what a double-click, a network
retry or two people at once do. Store 1: bin A-01-01 holds 4 white bread and has a capacity of 200."""
import threading

from sqlalchemy import func, inspect, select

from app import db as app_db
from app.db import SessionLocal
from app.errors import DomainError
from app.models import Bin, CycleCount, StockItem, StockLedger
from app.modules.inventory import counts
from app.modules.inventory import service as inventory
from app.modules.slotting import service as slotting

from .conftest import assert_stock_is_consistent


def run_paused(monkeypatch, module, name: str, *calls) -> list[str]:
    """Run each call (given its own session) in its own thread. Every thread waits just after `module.name` returns
    until all of them got there, so they are all past that check before any of them writes. Returns the error code of
    each call that was refused."""
    barrier, original = threading.Barrier(len(calls), timeout=3), getattr(module, name)
    refused: list[str] = []

    def paused(*args, **kwargs):
        result = original(*args, **kwargs)
        try:
            barrier.wait()
        except threading.BrokenBarrierError:          # once fixed, the other request may never get here
            pass
        return result

    monkeypatch.setattr(module, name, paused)

    def run(call):
        with SessionLocal() as session:
            try:
                call(session)
            except DomainError as error:
                refused.append(error.code)

    threads = [threading.Thread(target=run, args=(call,)) for call in calls]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(30)
    return refused


def one_sku_bin(db) -> tuple[int, int]:
    """A bin of store 1 that holds one SKU, so a count of it has one line: (bin id, SKU id)."""
    return db.execute(
        select(StockItem.bin_id, func.min(StockItem.sku_id)).where(StockItem.store_id == 1, StockItem.qty > 0)
        .group_by(StockItem.bin_id).having(func.count(func.distinct(StockItem.sku_id)) == 1)
        .order_by(StockItem.bin_id)).first()


# --------------------------------------------------------------------------- #81 cycle counts


def test_two_submits_of_one_count_change_stock_once(monkeypatch):
    with SessionLocal() as db:
        bin_id, sku_id = one_sku_bin(db)
        count_id = counts.start(db, 1, bin_id, created_by="manager1").id
        before = counts._on_the_shelf(db, bin_id, sku_id)
    counted = {sku_id: before + 1}                                   # one unit more than the records

    refused = run_paused(monkeypatch, counts, "_on_the_shelf",
                         lambda s: counts.submit(s, count_id, counted, "counter-a"),
                         lambda s: counts.submit(s, count_id, counted, "counter-b"))

    with SessionLocal() as db:
        applied = db.scalars(select(StockLedger).where(StockLedger.reference == f"count:{count_id}")).all()
        assert [row.delta for row in applied] == [1]
        assert counts._on_the_shelf(db, bin_id, sku_id) == before + 1
    assert refused == ["count_closed"]
    assert_stock_is_consistent()


def test_a_second_submit_after_the_first_is_refused_too():
    with SessionLocal() as db:
        bin_id, sku_id = one_sku_bin(db)
        count_id = counts.start(db, 1, bin_id, created_by="manager1").id
        counted = {sku_id: counts._on_the_shelf(db, bin_id, sku_id)}
        counts.submit(db, count_id, counted, "counter-a")

    with SessionLocal() as db:
        try:
            counts.submit(db, count_id, counted, "counter-a")
            code = None
        except DomainError as error:
            code = error.code
    assert code == "count_closed"


def test_two_starts_at_once_give_the_bin_one_open_count(monkeypatch):
    with SessionLocal() as db:
        bin_id, _ = one_sku_bin(db)

    run_paused(monkeypatch, counts, "_open_count_for",
               lambda s: counts.start(s, 1, bin_id, created_by="system"),
               lambda s: counts.start(s, 1, bin_id, created_by="manager1"))

    with SessionLocal() as db:
        open_counts = db.scalars(select(CycleCount).where(CycleCount.bin_id == bin_id,
                                                          CycleCount.status.in_(counts.OPEN_STATES))).all()
    assert len(open_counts) == 1


# --------------------------------------------------------------------------- #82 found units


def test_two_found_unit_adjustments_at_once_cannot_overfill_a_bin(monkeypatch):
    with SessionLocal() as db:
        bin_ = db.scalar(select(Bin).where(Bin.store_id == 1, Bin.code == "A-01-01"))
        bin_id = bin_.id
        sku_id = db.scalar(select(StockItem.sku_id).where(StockItem.bin_id == bin_id, StockItem.qty > 0))
        room = slotting.room_in(db, bin_)                            # 196 of 200 in the demo data

    def found(session):                                             # as POST /v1/stock-adjustments calls it
        inventory.adjust(session, 1, sku_id, room, "damage", bin_id=bin_id, actor="manager1", shelf_rules=True)

    refused = run_paused(monkeypatch, slotting, "ensure_room", found, found)

    with SessionLocal() as db:
        assert slotting.room_in(db, db.get(Bin, bin_id)) == 0        # exactly one of the two was kept
    assert refused == ["bin_full"]
    assert_stock_is_consistent()


# --------------------------------------------------------------------------- #84 the index


def test_a_bins_stock_is_found_through_an_index():
    indexed = {tuple(index["column_names"]) for index in inspect(app_db.engine).get_indexes("stock_items")}

    assert ("bin_id",) in indexed
