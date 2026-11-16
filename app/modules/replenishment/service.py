"""Replenishment Service (HLD service 8): decide what to reorder from the mother hub (HLD 6.2).

Stock position = on hand - reserved + already on its way.
When the position drops below the reorder point, order enough to get back to target stock.
"""
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ... import events
from ...errors import DomainError, not_found
from ...models import StockLevel, TransferOrder, TransferOrderLine
from ..inventory import service as inventory

OPEN_STATES = ("created", "dispatched")
LOW_STOCK_CAUSES = {"reserved", "sale", "damage", "expiry", "theft", "count", "not_found"}


@events.subscribe("stock.changed")
def on_stock_changed(db: Session, store_id: int | None, payload: dict) -> None:
    """Raise stock.low when a SKU's ATP falls below its reorder point."""
    if payload.get("cause") not in LOW_STOCK_CAUSES:
        return
    level = inventory.get_level(db, store_id, payload["sku_id"])
    if level is None:
        return
    atp = level.qty_on_hand - level.qty_reserved
    if atp < level.reorder_point:
        events.publish(db, "stock.low", store_id,
                       {"sku_id": level.sku_id, "atp": atp, "reorder_point": level.reorder_point})


def in_transit(db: Session, store_id: int) -> dict[int, int]:
    """Units already ordered from the hub but not yet received, per SKU."""
    rows = db.execute(
        select(TransferOrderLine.sku_id, func.sum(TransferOrderLine.qty_ordered - TransferOrderLine.qty_received))
        .join(TransferOrder, TransferOrder.id == TransferOrderLine.transfer_order_id)
        .where(TransferOrder.store_id == store_id, TransferOrder.status.in_(OPEN_STATES))
        .group_by(TransferOrderLine.sku_id)
    ).all()
    return {sku_id: int(qty) for sku_id, qty in rows}


def run(db: Session, store_id: int) -> TransferOrder | None:
    """Check every SKU in the store and raise one transfer order for everything that is low (FR-8).
    Returns None when nothing needs ordering."""
    inventory.get_store(db, store_id)
    transit = in_transit(db, store_id)
    levels = db.scalars(
        select(StockLevel).where(StockLevel.store_id == store_id).execution_options(populate_existing=True)
    ).all()
    lines = []
    for level in levels:
        position = level.qty_on_hand - level.qty_reserved + transit.get(level.sku_id, 0)
        if position < level.reorder_point:
            qty = level.target_stock - position
            if qty > 0:
                lines.append(TransferOrderLine(sku_id=level.sku_id, qty_ordered=qty))
    if not lines:
        return None
    order = TransferOrder(store_id=store_id, status="created", lines=lines)
    db.add(order)
    db.flush()
    events.publish(db, "transfer_order.created", store_id, {"transfer_order_id": order.id, "lines": len(lines)})
    db.commit()
    return order


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
