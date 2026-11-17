"""Read-only numbers for the operations dashboard (FR-13), and the live event feed behind it."""
import asyncio
import importlib
import logging
from collections import Counter, defaultdict
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ... import events
from ...models import EventLog, FulfilmentJob, Reservation, StockLevel, TransferOrder, utcnow
from ..inventory import service as inventory
from ..serviceability import service as serviceability

log = logging.getLogger(__name__)


def store_dashboard(db: Session, store_id: int) -> dict:
    store = inventory.get_store(db, store_id)
    by_state = dict(
        db.execute(
            select(FulfilmentJob.state, func.count()).where(FulfilmentJob.store_id == store_id)
            .group_by(FulfilmentJob.state)
        ).all()
    )
    packed = db.scalars(
        select(FulfilmentJob).where(FulfilmentJob.store_id == store_id, FulfilmentJob.packed_at.is_not(None),
                                    FulfilmentJob.state.in_(("packed", "handed_over")))
    ).all()
    pack_times = [(j.packed_at - j.created_at).total_seconds() for j in packed]
    levels = db.scalars(
        select(StockLevel).where(StockLevel.store_id == store_id).execution_options(populate_existing=True)
    ).all()
    low = [lv for lv in levels if lv.qty_on_hand - lv.qty_reserved < lv.reorder_point]
    return {
        "store_id": store.id,
        "store": store.name,
        "status": store.status,
        "orders": {state: by_state.get(state, 0)
                   for state in ("created", "picking", "packed", "handed_over", "cancelled")},
        "avg_seconds_to_pack": round(sum(pack_times) / len(pack_times), 1) if pack_times else None,
        "active_holds": db.scalar(
            select(func.count()).select_from(Reservation)
            .where(Reservation.store_id == store_id, Reservation.status == "held")),
        "skus_stocked": len(levels),
        # What customers see, so the safety buffer counts; "below reorder point" above uses physical stock, like
        # replenishment does.
        "skus_out_of_stock": sum(1 for lv in levels if inventory.atp_of(lv) <= 0),
        "skus_below_reorder_point": len(low),
        "open_transfer_orders": db.scalar(
            select(func.count()).select_from(TransferOrder)
            .where(TransferOrder.store_id == store_id, TransferOrder.status.in_(("created", "dispatched")))),
        "outbox_lag_seconds": outbox_lag_seconds(db),
    }


def outbox_lag_seconds(db: Session) -> float:
    """Age of the oldest event the relay has not sent yet; 0 when it is up to date.
    HLD 12 alerts when Kafka consumer lag passes 30 s; this is the prototype's equivalent."""
    oldest = db.scalar(select(func.min(EventLog.ts)).where(EventLog.published_at.is_(None)))
    return round((utcnow() - oldest).total_seconds(), 1) if oldest else 0


def recent_events(db: Session, store_id: int | None = None, limit: int = 20) -> list[dict]:
    query = select(EventLog)
    if store_id is not None:
        query = query.where(EventLog.store_id == store_id)
    rows = db.scalars(query.order_by(EventLog.id.desc()).limit(limit)).all()
    return [events.event_view(e) for e in rows]


# --------------------------------------------------------------------------- live feed (task 4.5)

LIVE_QUEUE_SIZE = 100
_listeners: dict[int, set[asyncio.Queue]] = defaultdict(set)     # store id -> one queue per open WebSocket


def listen(store_id: int) -> asyncio.Queue:
    """Start receiving one store's events. Call stop_listening when the viewer leaves."""
    queue: asyncio.Queue = asyncio.Queue(maxsize=LIVE_QUEUE_SIZE)
    _listeners[store_id].add(queue)
    return queue


def stop_listening(store_id: int, queue: asyncio.Queue) -> None:
    _listeners[store_id].discard(queue)


@events.add_sink
def push_to_listeners(event: dict) -> None:
    """Relay sink: give the event to everyone watching its store."""
    for queue in list(_listeners.get(event["store_id"], ())):
        if not queue.full():   # a viewer this far behind skips events; it reloads everything on the next one
            queue.put_nowait(event)


# --------------------------------------------------------------------------- ops page (task 4.6)
#
# The page shows every HLD 12 KPI the team builds. Teammates' numbers come from their functions, looked up by
# name when the page loads, so the page works before they exist and a bug in one never breaks the rest:
#
#   Member 2  app.modules.fulfilment.service.metrics(db, store_id)       -> {"seconds_to_pack_p90", "fill_rate",
#                                                                            "items_per_picker_hour"}   (task 2.1)
#   Member 2  app.modules.fulfilment.service.attention(db, store_id)     -> {"stalled": [{"order_id"}, ...]} (2.5)
#   Member 1  app.modules.inventory.counts.inventory_accuracy(db, sid)   -> {"value": fraction or None}  (task 1.5)
#   Member 3  app.modules.replenishment.service.kpis(db, store_id)       -> one {"value", "met"} per KPI (task 3.8)

# (key, name, owner, unit, HLD 12 target), in the order the page shows them.
KPIS = [
    ("seconds_to_pack_p90", "Order to packed (p90)", "fulfilment", "seconds", "≤ 120 s"),
    ("fill_rate", "Fill rate", "fulfilment", "fraction", "≥ 99% of units ordered"),
    ("items_per_picker_hour", "Picker productivity", "fulfilment", "per_hour", "≥ 100 items per picker-hour"),
    ("inventory_accuracy", "Inventory accuracy", "inventory", "fraction", "≥ 99.5% of counted lines"),
    ("stock_out_rate", "Stock-out rate", "supply", "fraction", "≤ 2% of carried SKUs"),
    ("days_of_cover", "SKUs with the right days of cover", "supply", "fraction",
     "100% of SKUs within 3–5 days of cover (fresh: 1–2 days)"),
    ("wastage_rate", "Wastage", "supply", "fraction", "≤ 1% of sales value"),
    ("replenishment_on_time", "Transfers on time", "supply", "fraction", "≥ 95% within the lead time"),
    ("forecast_wape", "Forecast error (WAPE)", "supply", "fraction", "≤ 30%"),
    ("outbox_lag_seconds", "Event relay lag", "platform", "seconds", "≤ 30 s"),
]
SUPPLY_KPIS = ("stock_out_rate", "days_of_cover", "wastage_rate", "replenishment_on_time", "forecast_wape")
CHART_HOURS = 12


class NotBuiltYet(Exception):
    """A teammate's function the page asks for does not exist yet."""


def _teammate(module: str, name: str):
    """A teammate's function, or NotBuiltYet. A module that exists but breaks on import raises its own error."""
    try:
        found = importlib.import_module(module)
    except ModuleNotFoundError as error:
        if error.name != module:        # the module is there, but something it imports is missing
            raise
        raise NotBuiltYet(module) from None
    function = getattr(found, name, None)
    if function is None:
        raise NotBuiltYet(f"{module}.{name}")
    return function


def _judged(value: float | None, meets) -> tuple:
    return value, None if value is None else meets(value)


def _fulfilment_kpis(db: Session, store_id: int) -> dict:
    m = _teammate("app.modules.fulfilment.service", "metrics")(db, store_id)
    return {"seconds_to_pack_p90": _judged(m["seconds_to_pack_p90"], lambda v: v <= 120),
            "fill_rate": _judged(m["fill_rate"], lambda v: v >= 0.99),
            "items_per_picker_hour": _judged(m["items_per_picker_hour"], lambda v: v >= 100)}


def _inventory_kpis(db: Session, store_id: int) -> dict:
    accuracy = _teammate("app.modules.inventory.counts", "inventory_accuracy")(db, store_id)
    return {"inventory_accuracy": _judged(accuracy["value"], lambda v: v >= 0.995)}


def _supply_kpis(db: Session, store_id: int) -> dict:
    kpis = _teammate("app.modules.replenishment.service", "kpis")(db, store_id)
    return {key: (kpis[key]["value"], kpis[key]["met"]) for key in SUPPLY_KPIS}


def _platform_kpis(db: Session, store_id: int) -> dict:
    return {"outbox_lag_seconds": _judged(outbox_lag_seconds(db), lambda v: v <= 30)}


KPI_SOURCES = {"fulfilment": _fulfilment_kpis, "inventory": _inventory_kpis, "supply": _supply_kpis,
               "platform": _platform_kpis}


def _guarded(db: Session, what: str, read):
    """Run `read()`; on a missing or failing teammate function return (None, why) instead of raising."""
    try:
        return read(), None
    except NotBuiltYet:
        return None, "not built yet"
    except Exception:              # one teammate's bug must not take the whole page down
        log.exception("Dashboard could not read %s", what)
        db.rollback()
        return None, "failed; see the server log"


def kpi_board(db: Session, store_id: int) -> dict:
    """Everything the ops page shows for one store: what needs action now, every HLD 12 KPI beside its target,
    and paid orders per hour. A KPI whose source is missing or fails is listed as not available."""
    inventory.get_store(db, store_id)
    measured, notes = {}, {}
    for owner, source in KPI_SOURCES.items():
        values, notes[owner] = _guarded(db, f"{owner} KPIs", lambda: source(db, store_id))
        measured.update(values or {})
    kpis = []
    for key, name, owner, unit, target in KPIS:
        value, met = measured.get(key, (None, None))
        kpis.append({"key": key, "name": name, "owner": owner, "unit": unit, "target": target,
                     "available": key in measured, "value": value, "met": met, "note": notes[owner]})
    return {"store_id": store_id, "needs_action": needs_action(db, store_id), "kpis": kpis,
            "orders_per_hour": orders_per_hour(db, store_id)}


def needs_action(db: Session, store_id: int) -> dict:
    """Problems first: stalled orders (None until Member 2 builds them), bags waiting for a rider, stock-outs."""
    stalled, why = _guarded(db, "stalled orders", lambda: [
        job["order_id"] for job in _teammate("app.modules.fulfilment.service", "attention")(db, store_id)["stalled"]])
    packed = db.scalars(select(FulfilmentJob)
                        .where(FulfilmentJob.store_id == store_id, FulfilmentJob.state == "packed",
                               FulfilmentJob.packed_at.is_not(None))
                        .order_by(FulfilmentJob.packed_at)).all()           # longest wait first
    now = utcnow()
    return {
        "stalled_orders": stalled,
        "stalled_note": why,
        "waiting_for_rider": [{"order_id": job.order_id,
                               "minutes_waiting": max(0, int((now - job.packed_at).total_seconds() // 60))}
                              for job in packed],
        "out_of_stock": [row["name"] for row in inventory.availability(db, store_id) if row["atp"] <= 0],
    }


def orders_per_hour(db: Session, store_id: int) -> list[dict]:
    """Paid orders (one fulfilment job each) per hour over the last CHART_HOURS hours, oldest first. Times are UTC."""
    this_hour = utcnow().replace(minute=0, second=0, microsecond=0)
    start = this_hour - timedelta(hours=CHART_HOURS - 1)
    created = db.scalars(select(FulfilmentJob.created_at)
                         .where(FulfilmentJob.store_id == store_id, FulfilmentJob.created_at >= start)).all()
    per_hour = Counter(ts.replace(minute=0, second=0, microsecond=0) for ts in created)
    hours = [start + timedelta(hours=n) for n in range(CHART_HOURS)]
    return [{"hour": hour.isoformat() + "Z", "orders": per_hour[hour]} for hour in hours]


def city_overview(db: Session) -> list[dict]:
    """One row per store for city-wide staff: status, orders waiting to be picked, bags waiting, low stock."""
    # shortcut: runs store_dashboard's queries once per store; fine for a handful of stores, switch to grouped
    # COUNT queries across all stores before the city has dozens.
    rows = []
    for store in serviceability.list_stores(db):
        d = store_dashboard(db, store["store_id"])
        rows.append({"store_id": d["store_id"], "store": d["store"], "status": d["status"],
                     "waiting_orders": d["orders"]["created"] + d["orders"]["picking"],
                     "waiting_for_rider": d["orders"]["packed"],
                     "low_stock": d["skus_below_reorder_point"], "out_of_stock": d["skus_out_of_stock"]})
    return rows
