"""Velocity-based slotting (guide task 3.6): fast movers live in the bins nearest the packing desk.

Store 1 of the demo data, by walk_seq (1 is next to the desk): ambient A-01-01 bread, A-01-02 eggs, A-01-03 bananas,
A-01-04 rice, A-02-01 atta, A-02-02 sugar, A-02-03 tea, A-02-04 noodles, A-03-01 chips, A-03-02 oil, A-03-03 soap,
A-03-04 empty; chilled C-01-01 milk (batch M-OLD), C-01-02 curd, C-01-03 paneer, C-01-04 milk (M-NEW); frozen F-01-01
ice cream, F-01-02 peas."""
from datetime import date, timedelta

from sqlalchemy import func, select, update

from app.models import SKU, Bin, StockItem, StockLedger
from app.modules.assortment import service as assortment
from app.modules.inventory import service as inventory
from app.modules.slotting import service as slotting

from .conftest import assert_stock_is_consistent, place_paid_order, plant_sales
from .test_order_flow import next_job

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


def reslot(client, key: str | None = None):
    return client.post("/v1/slotting/apply", params={"store_id": 1}, headers={"Idempotency-Key": key} if key else {})


def bins_holding(db, sku_id: int) -> set[str]:
    return set(db.scalars(select(Bin.code).join(StockItem, StockItem.bin_id == Bin.id)
                          .where(StockItem.store_id == 1, StockItem.sku_id == sku_id, StockItem.qty > 0)))


def test_after_apply_the_fastest_ambient_sku_is_in_the_nearest_ambient_bin(client, db, sku):
    chips, bread = sku("Potato chips"), sku("White bread")
    plant_sales(db, {chips: every_day(9), bread: every_day(3)})
    applied = reslot(client)
    assert applied.status_code == 200, applied.text
    nearest = db.scalar(select(Bin.code).where(Bin.store_id == 1, Bin.zone == "ambient").order_by(Bin.walk_seq))
    assert bins_holding(db, chips) == {nearest}
    assert_stock_is_consistent()


def test_chilled_skus_never_leave_chilled_bins(client, db, sku):
    chilled = (sku("Toned milk"), sku("Curd"), sku("Paneer"))
    plant_sales(db, {chilled[2]: every_day(8), chilled[1]: every_day(5), chilled[0]: every_day(1),
                     sku("Potato chips"): every_day(9)})
    assert reslot(client).status_code == 200
    zones = {zone for sku_id in chilled for zone in db.scalars(
        select(Bin.zone).join(StockItem, StockItem.bin_id == Bin.id)
        .where(StockItem.store_id == 1, StockItem.sku_id == sku_id, StockItem.qty > 0))}
    assert zones == {"chilled"}
    assert bins_holding(db, chilled[0]) == {"C-01-03"}                     # both milk batches, together
    assert_stock_is_consistent()


def test_apply_does_the_plan_and_a_second_apply_has_nothing_to_move(client, db, sku):
    plant_sales(db, {sku("Potato chips"): every_day(9), sku("White bread"): every_day(3)})
    planned = client.get("/v1/slotting/plan", params={"store_id": 1}).json()
    applied = reslot(client).json()

    def by_batch(moves: list[dict]) -> list[dict]:
        return sorted(moves, key=lambda move: move["stock_item_id"])

    assert (by_batch(applied["moved"]), applied["skipped"]) == (by_batch(planned["moves"]), [])
    assert client.get("/v1/slotting/plan", params={"store_id": 1}).json()["moves"] == []
    again = reslot(client).json()
    assert (again["moved"], again["skipped"]) == ([], [])
    assert_stock_is_consistent()


def test_a_batch_a_picker_was_sent_for_is_skipped(client, db, sku):
    chips = sku("Potato chips")
    plant_sales(db, {chips: every_day(9)})
    place_paid_order(client, "reslot-1", 1, [(chips, 2)])
    next_job(client)                                            # a picker is on the way to A-03-01 for 2 chips
    applied = reslot(client).json()
    [skipped] = [move for move in applied["skipped"] if move["sku_id"] == chips]
    assert (skipped["from_bin"], skipped["to_bin"], skipped["code"]) == ("A-03-01", "A-01-01", "promised_to_picker")
    assert bins_holding(db, chips) == {"A-03-01"}               # nothing of that batch moved
    assert_stock_is_consistent()


def test_apply_never_overfills_a_bin(client, db, sku):
    """Two full bins that must swap: neither batch fits until the other has left, so both are skipped, not forced."""
    eggs, bread = sku("Eggs"), sku("White bread")
    plant_sales(db, {eggs: every_day(9), bread: every_day(3)})            # eggs to A-01-01, bread to A-01-02
    db.execute(update(Bin).where(Bin.store_id == 1, Bin.code.in_(("A-01-01", "A-01-02"))).values(capacity=30))
    db.commit()                                                           # A-01-01: 4 bread, A-01-02: 30 eggs
    applied = reslot(client).json()
    assert applied["moved"] == []
    assert sorted((move["sku_id"], move["code"]) for move in applied["skipped"]) == sorted(
        [(eggs, "no_room"), (bread, "no_room")])
    assert (bins_holding(db, eggs), bins_holding(db, bread)) == ({"A-01-02"}, {"A-01-01"})
    assert_stock_is_consistent()


def test_a_retried_apply_moves_once(client, db, sku):
    plant_sales(db, {sku("Potato chips"): every_day(9)})
    first, again = reslot(client, key="reslot-key"), reslot(client, key="reslot-key")
    assert first.json()["moved"] and first.json() == again.json()
    assert db.scalar(select(func.count(StockLedger.id)).where(StockLedger.reason == "move")) == \
        2 * len(first.json()["moved"])
    assert_stock_is_consistent()


def test_the_ledger_names_the_manager_who_reslotted(client_as, db, sku):
    plant_sales(db, {sku("Potato chips"): every_day(9)})
    assert reslot(client_as("manager", 1)).status_code == 200
    rows = db.execute(select(StockLedger.actor, StockLedger.reference).where(StockLedger.reason == "move")).all()
    assert rows and set(rows) == {("test-manager", "reslot")}


def test_staff_see_the_plan_and_only_managers_of_the_store_apply_it(client_as):
    url, store = "/v1/slotting/plan", {"store_id": 1}
    assert client_as("picker", 1).get(url, params=store).status_code == 200
    assert client_as("picker", 2).get(url, params=store).status_code == 403
    assert reslot(client_as("picker", 1)).status_code == 403
    assert reslot(client_as("manager", 2)).status_code == 403
    assert reslot(client_as("manager", 1)).status_code == 200
