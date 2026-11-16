"""Read-only numbers for the operations dashboard (FR-13)."""
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ...models import EventLog, FulfilmentJob, Reservation, StockLevel, TransferOrder
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
    }


def recent_events(db: Session, store_id: int | None = None, limit: int = 20) -> list[dict]:
    query = select(EventLog)
    if store_id is not None:
        query = query.where(EventLog.store_id == store_id)
    rows = db.scalars(query.order_by(EventLog.id.desc()).limit(limit)).all()
    return [{"id": e.id, "type": e.type, "store_id": e.store_id, "payload": e.payload,
             "ts": e.ts.isoformat() + "Z"} for e in rows]
