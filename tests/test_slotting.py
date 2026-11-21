"""Velocity-based slotting (guide task 3.6): fast movers live in the bins nearest the packing desk.

Store 1 of the demo data, by walk_seq (1 is next to the desk): ambient A-01-01 bread, A-01-02 eggs, A-01-03 bananas,
A-01-04 rice, A-02-01 atta, A-02-02 sugar, A-02-03 tea, A-02-04 noodles, A-03-01 chips, A-03-02 oil, A-03-03 soap,
A-03-04 empty; chilled C-01-01 milk (batch M-OLD), C-01-02 curd, C-01-03 paneer, C-01-04 milk (M-NEW); frozen F-01-01
ice cream, F-01-02 peas."""
from datetime import date, timedelta

from sqlalchemy import func, select

from app.models import SKU, Bin, StockItem, StockLedger
from app.modules.assortment import service as assortment
from app.modules.inventory import service as inventory
from app.modules.slotting import service as slotting

from .conftest import assert_stock_is_consistent, plant_sales

FORTNIGHT = range(1, 15)                                    # the 14 whole days before today


def every_day(units: int) -> dict[int, int]:
    return dict.fromkeys(FORTNIGHT, units)


def moves_of(plan: dict) -> dict[int, list[tuple[str, str]]]:
    """{sku_id: [(from_bin, to_bin), ...]} in the plan's order."""
    found: dict[int, list[tuple[str, str]]] = {}
    for move in plan["moves"]:
        found.setdefault(move["sku_id"], []).append((move["from_bin"], move["to_bin"]))
    return found


def test_velocity_is_units_sold_a_day_over_whole_days(db, sku):
    chips, milk = sku("Potato chips"), sku("Toned milk")
    plant_sales(db, {chips: every_day(2), milk: {0: 50, 20: 30}})          # today is only partly over
    assert slotting.velocity(db, 1) == {chips: 2.0}
    assert slotting.velocity(db, 1, days=7) == {chips: 2.0}


def test_the_plan_puts_the_fastest_sku_in_the_nearest_bin(db, sku):
    chips, bread = sku("Potato chips"), sku("White bread")
    plant_sales(db, {chips: every_day(9), bread: every_day(3)})
    plan = slotting.plan(db, 1)
    homes = {home["sku_id"]: home["bin"] for home in plan["homes"]}
    assert (homes[chips], homes[bread]) == ("A-01-01", "A-01-02")
    moves = moves_of(plan)
    assert (moves[chips], moves[bread]) == ([("A-03-01", "A-01-01")], [("A-01-01", "A-01-02")])


def test_skus_that_do_not_sell_stay_unless_a_seller_needs_their_bin(db, sku):
    chips, bread, eggs = sku("Potato chips"), sku("White bread"), sku("Eggs")
    plant_sales(db, {chips: every_day(9), bread: every_day(3)})
    moves = moves_of(slotting.plan(db, 1))
    assert moves[eggs] == [("A-01-02", "A-03-04")]          # bread needs its bin: to the furthest free one
    assert set(moves) == {chips, bread, eggs}                # milk, split over two bins, is left as it is too


def test_chilled_skus_are_planned_into_chilled_bins_only(db, sku):
    milk, curd, paneer = sku("Toned milk"), sku("Curd"), sku("Paneer")
    plant_sales(db, {paneer: every_day(8), curd: every_day(5), milk: every_day(1)})
    plan = slotting.plan(db, 1)
    assert {home["sku_id"]: home["bin"] for home in plan["homes"]} == {paneer: "C-01-01", curd: "C-01-02",
                                                                      milk: "C-01-03"}
    assert moves_of(plan) == {paneer: [("C-01-03", "C-01-01")],
                              milk: [("C-01-01", "C-01-03"), ("C-01-04", "C-01-03")]}   # both milk batches


def test_with_more_sellers_than_bins_the_slowest_keeps_its_place(db, sku):
    ice_cream, peas = sku("Vanilla ice cream"), sku("Frozen green peas")
    new_sku = SKU(name="Kulfi", category="Frozen", barcode="8909999999999", storage_type="frozen",
                  shelf_life_days=180, price=60, case_size=1)
    db.add(new_sku)
    db.commit()
    kulfi = new_sku.id
    assortment.add_sku(db, 1, kulfi)
    first = db.scalar(select(Bin).where(Bin.store_id == 1, Bin.code == "F-01-01"))
    inventory.receive(db, 1, kulfi, 5, first.id, "K1", date.today() + timedelta(days=90), "test", "test")
    db.commit()
    plant_sales(db, {kulfi: every_day(9), ice_cream: every_day(4), peas: every_day(1)})
    plan = slotting.plan(db, 1)
    assert {home["sku_id"]: home["bin"] for home in plan["homes"]} == {kulfi: "F-01-01", ice_cream: "F-01-02"}
    assert moves_of(plan) == {ice_cream: [("F-01-01", "F-01-02")]}         # peas: no bin of its own, no bin free
    assert_stock_is_consistent()


def test_no_sales_in_the_last_whole_days_means_nothing_moves(db, sku):
    plant_sales(db, {sku("Potato chips"): {0: 50, 15: 40}})               # today, and before the 14 days
    assert slotting.plan(db, 1) == {"store_id": 1, "days": 14, "homes": [], "moves": []}


def test_planning_changes_nothing(db, sku):
    plant_sales(db, {sku("Potato chips"): every_day(9), sku("Toned milk"): every_day(4)})

    def snapshot():
        return (sorted(db.execute(select(StockItem.id, StockItem.bin_id, StockItem.qty)).all()),
                db.scalar(select(func.count(StockLedger.id))))

    before = snapshot()
    assert slotting.plan(db, 1)["moves"]
    assert snapshot() == before
