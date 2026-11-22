"""Replenishment Service (HLD service 8): decide what to reorder from the mother hub (HLD 6.2).

Stock position = on hand - reserved + already on its way.
When the position drops below the reorder point, order enough to get back to target stock, in whole cases,
within the free bin space of each zone; when a zone is short of space the most urgent SKUs go first.
A manager can stop reordering one SKU, e.g. to let it run down before dropping it, or change its reorder point
(update_reorder_settings).
"""
import logging
import math
import threading
from datetime import timedelta

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from ... import config, events
from ...errors import DomainError, not_found
from ...models import (SKU, Bin, EventLog, StockItem, StockLedger, StockLevel, Store, TransferOrder, TransferOrderLine,
                       utcnow)
from ..forecasting import service as forecasting
from ..inventory import service as inventory

OPEN_STATES = ("created", "dispatched")
# One run at a time in this app, so the timer and a manager's button cannot both order the same stock. The lock
# is per process: with several app instances, run the timer in one of them only.
_RUN_LOCK = threading.Lock()
LOW_STOCK_CAUSES = {"reserved", "sale", "damage", "expiry", "theft", "count", "not_found"}
log = logging.getLogger(__name__)


@events.subscribe("stock.changed")
def on_stock_changed(db: Session, store_id: int | None, payload: dict) -> None:
    """Raise stock.low when a SKU's ATP falls below its reorder point, unless a manager stopped reordering it.

    Once per SKU until stock comes in again: each later sale, hold or write-off while it stays low says nothing new,
    and used to publish another stock.low every time. A delivery, or units found by a count, starts over."""
    if payload.get("cause") not in LOW_STOCK_CAUSES:
        return
    level = inventory.get_level(db, store_id, payload["sku_id"])
    if level is None or level.reorder_stopped:      # it is being run down on purpose: no alert
        return
    atp = level.qty_on_hand - level.qty_reserved
    if atp < level.reorder_point and not _low_reported_since_restock(db, store_id, level.sku_id):
        events.publish(db, "stock.low", store_id,
                       {"sku_id": level.sku_id, "atp": atp, "reorder_point": level.reorder_point})


def _low_reported_since_restock(db: Session, store_id: int, sku_id: int) -> bool:
    """True when stock.low was already published for this SKU after units last came in (a receipt, or units found by
    a count; a move between bins brings nothing in). Read-only."""
    restocked = db.scalar(select(func.max(StockLedger.ts)).where(
        StockLedger.store_id == store_id, StockLedger.sku_id == sku_id, StockLedger.delta > 0,
        StockLedger.reason != "move"))
    reported = select(EventLog.id).where(EventLog.type == "stock.low", EventLog.store_id == store_id,
                                         EventLog.payload["sku_id"].as_integer() == sku_id)
    if restocked is not None:
        reported = reported.where(EventLog.ts > restocked)
    return db.scalar(reported.limit(1)) is not None


def in_transit(db: Session, store_id: int) -> dict[int, int]:
    """Units already ordered from the hub but not yet received, per SKU."""
    rows = db.execute(
        select(TransferOrderLine.sku_id, func.sum(TransferOrderLine.qty_ordered - TransferOrderLine.qty_received))
        .join(TransferOrder, TransferOrder.id == TransferOrderLine.transfer_order_id)
        .where(TransferOrder.store_id == store_id, TransferOrder.status.in_(OPEN_STATES))
        .group_by(TransferOrderLine.sku_id)
    ).all()
    return {sku_id: int(qty) for sku_id, qty in rows}


def _whole_cases(qty: int, case_size: int) -> int:
    """`qty` rounded up to whole cases (the hub ships nothing smaller); 0 for nothing needed."""
    case = max(1, case_size)
    return math.ceil(qty / case) * case if qty > 0 else 0


def run(db: Session, store_id: int) -> dict:
    """Check every SKU in the store and raise one transfer order for everything that is low (FR-8), in whole cases
    and within each zone's free bin space (HLD 6.2), and commit.

    Returns {"transfer_order": the order, or None when nothing is ordered, "capped": [{sku_id, sku, zone, wanted,
    ordered}] for each SKU that got less than it needed because its zone was short of space}. Cuts are also
    published as a replenishment.capped event.
    """
    with _RUN_LOCK:
        return _run(db, store_id)


def _run(db: Session, store_id: int) -> dict:
    inventory.get_store(db, store_id)
    transit = in_transit(db, store_id)
    levels = db.scalars(
        select(StockLevel).where(StockLevel.store_id == store_id).execution_options(populate_existing=True)
    ).all()
    wanted = []
    for level in levels:
        if level.reorder_stopped:                   # a manager is letting it run down
            continue
        position = level.qty_on_hand - level.qty_reserved + transit.get(level.sku_id, 0)
        if position < level.reorder_point:
            qty = _whole_cases(level.target_stock - position, level.sku.case_size)
            if qty > 0:
                wanted.append((level, qty))
    lines, capped = _fit_free_space(db, store_id, wanted, levels, transit)
    if capped:                      # on the live feed, so a manager sees cuts made by the timer too
        events.publish(db, "replenishment.capped", store_id, {"capped": capped})
    if not lines:
        if capped:
            db.commit()
        return {"transfer_order": None, "capped": capped}
    order = TransferOrder(store_id=store_id, status="created", lines=lines)
    db.add(order)
    db.flush()
    events.publish(db, "transfer_order.created", store_id,
                   {"transfer_order_id": order.id, "lines": len(lines), "capped": len(capped)})
    db.commit()
    return {"transfer_order": order, "capped": capped}


def run_all(db: Session) -> list[dict]:
    """Run replenishment for every store that is not closed (the timer in app/background.py calls this), each
    store committed on its own. Returns per store: store_id, transfer_order_id (None when nothing was ordered),
    lines and capped. A store whose run fails is rolled back and logged, its row says why in "error", and the
    stores after it still run."""
    results = []
    for store_id in list(db.scalars(select(Store.id).where(Store.status != "closed").order_by(Store.id))):
        try:
            result = run(db, store_id)
        except Exception as error:                  # one broken store must not stop the others' reorders
            db.rollback()
            log.exception("Replenishment failed for store %s", store_id)
            results.append({"store_id": store_id, "transfer_order_id": None, "lines": 0, "capped": [],
                            "error": f"{type(error).__name__}: {error}"})
            continue
        order = result["transfer_order"]
        results.append({"store_id": store_id, "transfer_order_id": order.id if order else None,
                        "lines": len(order.lines) if order else 0, "capped": result["capped"]})
    return results


def update_reorder_settings(db: Session, store_id: int, sku_id: int, *, reorder_stopped: bool | None = None,
                            reorder_point: int | None = None) -> dict:
    """Change the reorder settings of one SKU in one store, and commit; a setting left as None keeps its value.

    reorder_stopped: a manager stops reordering to let the SKU run down, for example before dropping it: run() then
    skips it and no stock.low is raised. Units already on their way still arrive.
    reorder_point: must stay below the target stock, as when the SKU is added (issue #63), since a reorder refills up
    to the target. A forecast run sets it again for a SKU that sells.

    404 not_carried when the store does not carry the SKU; 422 bad_reorder_point when the reorder point is not below
    the target. Either way nothing changes."""
    inventory.get_store(db, store_id)
    sku = inventory.get_sku(db, sku_id)
    query = update(StockLevel).where(StockLevel.store_id == store_id, StockLevel.sku_id == sku_id)
    changes = {}
    if reorder_stopped is not None:
        changes["reorder_stopped"] = reorder_stopped
    if reorder_point is not None:
        changes["reorder_point"] = reorder_point
        # Checked in the same statement that saves it, so a forecast run that lowers the target meanwhile cannot slip
        # in between the check and the save.
        query = query.where(StockLevel.target_stock > reorder_point)
    changed = db.execute(query.values(**changes).execution_options(synchronize_session=False)).rowcount
    level = inventory.get_level(db, store_id, sku_id)
    if level is None:
        raise DomainError(404, "not_carried", f"Store {store_id} does not carry {sku.name}")
    if not changed:                                 # the row is there, so the target check stopped it
        raise DomainError(422, "bad_reorder_point", f"The reorder point of {sku.name} must be below its target stock "
                          f"of {level.target_stock}, as a reorder refills up to the target",
                          {"target_stock": level.target_stock})
    saved = {"reorder_stopped": level.reorder_stopped, "reorder_point": level.reorder_point}
    events.publish(db, "reordering.changed", store_id, {"sku_id": sku_id, **saved})
    db.commit()
    return {"store_id": store_id, "sku_id": sku_id, "sku": sku.name, **saved}


def free_space(db: Session, store_id: int, levels: list[StockLevel], transit: dict[int, int]) -> dict[str, int]:
    """Units each zone can still take: its bins' capacity - units stored in them - units on their way. Read-only."""
    capacity = dict(db.execute(
        select(Bin.zone, func.sum(Bin.capacity)).where(Bin.store_id == store_id).group_by(Bin.zone)).all())
    stored = dict(db.execute(
        select(Bin.zone, func.sum(StockItem.qty)).join(StockItem, StockItem.bin_id == Bin.id)
        .where(Bin.store_id == store_id).group_by(Bin.zone)).all())
    coming: dict[str, int] = {}
    for level in levels:
        coming[level.sku.storage_type] = coming.get(level.sku.storage_type, 0) + transit.get(level.sku_id, 0)
    return {zone: max(0, int(capacity.get(zone) or 0) - int(stored.get(zone) or 0) - coming.get(zone, 0))
            for zone in set(capacity) | set(stored) | set(coming)}


def _fit_free_space(db: Session, store_id: int, wanted: list[tuple[StockLevel, int]], levels: list[StockLevel],
                    transit: dict[int, int]) -> tuple[list[TransferOrderLine], list[dict]]:
    """Fill each zone's free space most urgent first: lowest days of cover (what customers can buy / forecast
    daily demand), and on equal cover (say, several SKUs sold out) the faster seller; a SKU with no forecast comes
    last. A line that does not fit is cut to the whole cases that do."""
    demand = {row["sku_id"]: row["daily_demand"] for row in forecasting.list_forecasts(db, store_id)}

    def urgency(item: tuple[StockLevel, int]) -> tuple:
        level, daily = item[0], demand.get(item[0].sku_id, 0)
        return (inventory.atp_of(level) / daily if daily > 0 else math.inf, -daily, level.sku.name)

    room = free_space(db, store_id, levels, transit)
    lines, capped = [], []
    for level, qty in sorted(wanted, key=urgency):
        zone, case = level.sku.storage_type, max(1, level.sku.case_size)
        ordered = qty if qty <= room.get(zone, 0) else room.get(zone, 0) // case * case
        room[zone] = room.get(zone, 0) - ordered
        if ordered:
            lines.append(TransferOrderLine(sku_id=level.sku_id, qty_ordered=ordered))
        if ordered < qty:
            capped.append({"sku_id": level.sku_id, "sku": level.sku.name, "zone": zone, "wanted": qty,
                           "ordered": ordered})
    return lines, capped


def get_order(db: Session, transfer_order_id: int) -> TransferOrder:
    """Look up one transfer order or raise 404. Read-only."""
    order = db.get(TransferOrder, transfer_order_id)
    if order is None:
        raise not_found("Transfer order", transfer_order_id)
    return order


def dispatch(db: Session, transfer_order_id: int) -> TransferOrder:
    """Stand-in for the mother hub WMS saying 'the truck has left'."""
    order = get_order(db, transfer_order_id)
    if order.status != "created":
        raise DomainError(409, "bad_state", f"Transfer order is {order.status}; only a new one can be dispatched")
    order.status = "dispatched"
    events.publish(db, "transfer_order.dispatched", order.store_id, {"transfer_order_id": order.id})
    db.commit()
    return order


def list_orders(db: Session, store_id: int) -> list[TransferOrder]:
    return list(db.scalars(
        select(TransferOrder).where(TransferOrder.store_id == store_id).order_by(TransferOrder.id.desc()).limit(30)
    ).all())


def order_view(order: TransferOrder) -> dict:
    return {
        "transfer_order_id": order.id,
        "store_id": order.store_id,
        "status": order.status,
        "created_at": order.created_at.isoformat() + "Z",
        "lines": [{"sku_id": l.sku_id, "sku": l.sku.name, "qty_ordered": l.qty_ordered,
                   "qty_received": l.qty_received} for l in order.lines],
    }


# --------------------------------------------------------------------------- supply KPIs (HLD 12)

# HLD 12 targets for the five supply KPIs.
STOCK_OUT_TARGET = 0.02            # at most 2% of carried SKUs with nothing to sell
COVER_DAYS_FRESH = (1, 2)          # days of cover for a fresh SKU: enough for tomorrow's truck, not enough to expire
COVER_DAYS_OTHER = (3, 5)          # days of cover for everything else
WASTAGE_TARGET = 0.01              # write-offs worth at most 1% of sales
ON_TIME_TARGET = 0.95              # at least 95% of transfer orders arrive within the lead time
WAPE_TARGET = 0.30                 # forecast error at most 30%


def _kpi(value: float | None, target: str, met: bool | None, **details) -> dict:
    """One KPI as the dashboard shows it. value is a fraction; value and met are None when there is nothing to
    measure yet."""
    return {"value": None if value is None else round(value, 4), "target": target, "met": met, **details}


def _ratio(part: float, whole: float) -> float | None:
    return part / whole if whole else None


def kpis(db: Session, store_id: int) -> dict:
    """The five supply KPIs of HLD 12 for one store, each with its value, its HLD target and whether it is met.
    Read-only.

    Stock-outs and days of cover are measured now; wastage and on-time deliveries over the last
    config.KPI_WINDOW_DAYS days; forecast error by backtesting the model in use.
    """
    inventory.get_store(db, store_id)
    levels = db.scalars(
        select(StockLevel).where(StockLevel.store_id == store_id).execution_options(populate_existing=True)
    ).all()
    since = utcnow() - timedelta(days=config.KPI_WINDOW_DAYS)
    return {
        "store_id": store_id,
        "stock_out_rate": _stock_out_rate(levels),
        "days_of_cover": _days_of_cover(db, store_id, levels),
        "wastage_rate": _wastage_rate(db, store_id, since),
        "replenishment_on_time": _on_time(db, store_id, since),
        "forecast_wape": _forecast_wape(db, store_id),
    }


def _stock_out_rate(levels: list[StockLevel]) -> dict:
    """Carried SKUs customers cannot buy / carried SKUs. Uses inventory.atp_of, so units hidden by the safety
    buffer do not count as stock, as on the dashboard."""
    out = sorted((lv for lv in levels if inventory.atp_of(lv) <= 0), key=lambda lv: lv.sku.name)
    value = _ratio(len(out), len(levels))
    return _kpi(value, "≤ 2% of carried SKUs", None if value is None else value <= STOCK_OUT_TARGET,
                carried=len(levels), out_of_stock=[{"sku_id": lv.sku_id, "sku": lv.sku.name} for lv in out])


def _days_of_cover(db: Session, store_id: int, levels: list[StockLevel]) -> dict:
    """Per SKU: ATP (what customers can buy, inventory.atp_of) / forecast daily demand. The value is the share of
    SKUs with a forecast whose cover is within target: 1-2 days for a fresh SKU (shelf life up to
    config.FRESH_SHELF_LIFE_DAYS), 3-5 days for the rest; met when every one of them is. SKUs without forecast
    demand are not measured."""
    demand = {row["sku_id"]: row["daily_demand"] for row in forecasting.list_forecasts(db, store_id)}
    rows = []
    for level in levels:
        daily = demand.get(level.sku_id, 0)
        atp = inventory.atp_of(level)
        fresh = level.sku.shelf_life_days <= config.FRESH_SHELF_LIFE_DAYS
        days = atp / daily if daily > 0 else None
        low, high = COVER_DAYS_FRESH if fresh else COVER_DAYS_OTHER
        rows.append({"sku_id": level.sku_id, "sku": level.sku.name, "fresh": fresh, "atp": atp,
                     "daily_demand": daily, "days": None if days is None else round(days, 2),
                     "met": None if days is None else low <= days <= high})
    measured = [row for row in rows if row["days"] is not None]
    within = sum(1 for row in measured if row["met"])
    value = _ratio(within, len(measured))
    rows.sort(key=lambda row: (row["days"] is None, row["days"] or 0, row["sku"]))
    return _kpi(value, "100% of SKUs within 3–5 days of cover (fresh: 1–2 days)",
                None if value is None else within == len(measured),
                measured=len(measured), within_target=within,
                under_1_day=sum(1 for row in measured if row["days"] < 1),
                over_14_days=sum(1 for row in measured if row["days"] > 14), per_sku=rows)


def _value_removed(db: Session, store_id: int, since, reasons: tuple[str, ...]) -> float:
    """Rupee value of the units the ledger took out for `reasons` since `since`."""
    return float(db.scalar(
        select(func.coalesce(func.sum(-StockLedger.delta * SKU.price), 0))
        .select_from(StockLedger).join(SKU, SKU.id == StockLedger.sku_id)
        .where(StockLedger.store_id == store_id, StockLedger.ts >= since, StockLedger.delta < 0,
               StockLedger.reason.in_(reasons))
    ))


def _wastage_rate(db: Session, store_id: int, since) -> dict:
    """Value written off as expired or damaged / value sold."""
    written_off = _value_removed(db, store_id, since, ("expiry", "damage"))
    sold = _value_removed(db, store_id, since, ("sale",))
    value = _ratio(written_off, sold)
    return _kpi(value, "≤ 1% of sales value", None if value is None else value <= WASTAGE_TARGET,
                written_off_value=round(written_off, 2), sold_value=round(sold, 2), days=config.KPI_WINDOW_DAYS)


def _on_time(db: Session, store_id: int, since) -> dict:
    """Transfer orders received within the lead time of being raised / transfer orders received."""
    orders = db.scalars(select(TransferOrder).where(TransferOrder.store_id == store_id,
                                                    TransferOrder.received_at >= since)).all()
    lead = timedelta(days=config.LEAD_TIME_DAYS)
    on_time = sum(1 for order in orders if order.received_at - order.created_at <= lead)
    value = _ratio(on_time, len(orders))
    return _kpi(value, "≥ 95% within the lead time", None if value is None else value >= ON_TIME_TARGET,
                on_time=on_time, received=len(orders), lead_time_days=config.LEAD_TIME_DAYS)


def _forecast_wape(db: Session, store_id: int) -> dict:
    """WAPE of the model in use over the recent days (forecasting.backtest)."""
    result = forecasting.backtest(db, store_id)
    value = result["wape"]
    return _kpi(value, "≤ 30%", None if value is None else value <= WAPE_TARGET,
                model=result["model"], test_days=result["test_days"])
