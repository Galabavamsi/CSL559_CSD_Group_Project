"""Read-only numbers for the operations dashboard (FR-13), and the live event feed behind it."""
import asyncio
from collections import defaultdict

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ... import events
from ...models import EventLog, FulfilmentJob, Reservation, StockLevel, TransferOrder, utcnow
from ..inventory import service as inventory


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
        "skus_out_of_stock": sum(1 for lv in levels if lv.qty_on_hand - lv.qty_reserved <= 0),
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
