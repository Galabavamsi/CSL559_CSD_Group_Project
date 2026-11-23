"""Orders: a signed-in customer's paid order, as a record (docs/DESIGN.md, section 2).

An order is created at payment, around the hold: the hold and the pick job go on doing the stock work exactly as
before, and the order adds who the customer is, where it goes, what each unit cost and how far along it is. A hold
paid at the hub's demo desk, with no customer signed in, makes no order.

An order's status is written when something happens, not worked out when read. This module listens to the events
the hub already publishes and moves the order in the publisher's transaction, so an order and its pick job cannot
disagree: both change or neither does.
"""
import contextvars
from datetime import datetime

import h3
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ... import config, events
from ...errors import DomainError
from ...models import SKU, FulfilmentJob, Order, OrderEvent, OrderLine, Reservation, Store, StoreZone, utcnow
from ..fulfilment import service as fulfilment
from ..inventory import service as inventory

# Statuses, in the order an order can pass through them. Delivery adds pooled, out_for_delivery, delivered and
# delivery_failed; nothing sets them yet.
OPEN = ("confirmed",)                               # a customer may still cancel
ENDED = ("delivered", "cancelled", "delivery_failed")

# The customer and address of the order being placed in this request, for on_order_paid below. `place` sets it
# around the hold's confirmation; the handler runs inside that confirmation's transaction, on the same thread.
_placing: contextvars.ContextVar[dict | None] = contextvars.ContextVar("order_being_placed", default=None)


def _not_yours(order_id: str) -> DomainError:
    # Someone else's order does not exist, as far as you know.
    return DomainError(404, "not_found", f"Order {order_id} does not exist")


def _stamp(at: datetime) -> str:
    return at.isoformat() + "Z"


def view(db: Session, order: Order) -> dict:
    hub = db.get(Store, order.store_id)
    return {
        "id": order.order_id, "status": order.status, "placed_at": _stamp(order.placed_at),
        "history": [{"status": event.status, "at": _stamp(event.at)} for event in order.events],
        "hub_id": order.store_id, "hub_name": hub.name, "hold_id": order.reservation_id,
        "lines": [{"product_id": line.sku_id, "name": line.name, "unit_label": line.unit_label,
                   "quantity": line.qty, "unit_price": line.unit_price} for line in order.lines],
        "item_total": order.item_total, "savings": order.savings, "delivery_fee": order.delivery_fee,
        "total": order.total, "payment": order.payment,
        "address": {"label": order.address_label, "line": order.address_line, "landmark": order.landmark,
                    "lat": order.lat, "lng": order.lng},
        # Delivery is not built: no code, no pool, no agent, and no promise of a time.
        "delivery_code": None, "pooled_with": None, "eta_minutes": None, "agent_name": None,
        "can_cancel": order.status in OPEN,
    }


def _move(db: Session, order_id: str, to: str, only_from: tuple[str, ...]) -> bool:
    """Move an order to a status if it is in one of `only_from`, and note when. One guarded update, so an event
    that arrives twice, or after the order has ended, changes nothing. Does not commit."""
    moved = db.execute(update(Order).where(Order.order_id == order_id, Order.status.in_(only_from))
                       .values(status=to).returning(Order.id)).scalar()
    if moved is None:
        return False
    db.add(OrderEvent(order_id=moved, status=to, at=utcnow()))
    return True


# --------------------------------------------------------------------------- placing

def place(db: Session, user_id: int, hold_id: str, address: dict) -> dict:
    """Pay for a held cart and make it an order. Commits (through the hold's confirmation).

    The address has to be one the hold's hub delivers to (422 address_outside_zone). Asking again for the same hold
    returns the order made the first time. A hold that ran out is refused as the hold itself refuses it
    (409 hold_expired), and so is one that is no longer held (409 not_held). A hold already paid for with no
    customer cannot be turned into an order afterwards (409 already_paid)."""
    res = inventory.get_reservation(db, hold_id)
    existing = db.scalar(select(Order).where(Order.reservation_id == res.id))
    if existing is not None:
        if existing.user_id != user_id:
            raise DomainError(404, "not_found", f"Reservation {hold_id} does not exist")
        return view(db, existing)
    if res.status in ("confirmed", "fulfilled"):
        raise DomainError(409, "already_paid", "This cart was already paid for, with no order made for it")
    zone = db.get(StoreZone, h3.latlng_to_cell(address["lat"], address["lng"], config.H3_RESOLUTION))
    if zone is None or zone.store_id != res.store_id:
        raise DomainError(422, "address_outside_zone",
                          "The hub holding these items does not deliver to this address. Choose the delivery "
                          "location again and hold the cart from the hub that serves it.",
                          {"store_id": res.store_id, "serving_store_id": zone.store_id if zone else None})
    token = _placing.set({"reservation_id": res.id, "user_id": user_id, "address": address})
    try:
        inventory.confirm(db, res.id)        # publishes order.paid: on_order_paid writes the order with it
    finally:
        _placing.reset(token)
    order = db.scalar(select(Order).where(Order.reservation_id == res.id))
    if order is None:                        # paid by another request between our look and the confirmation
        raise DomainError(409, "already_paid", "This cart was already paid for, with no order made for it")
    return view(db, order)


@events.subscribe("order.paid", first=True)
def on_order_paid(db: Session, store_id: int, payload: dict) -> None:
    """The hold was confirmed. If a signed-in customer is placing it, write the order: in the same transaction, so
    there is never a paid hold of theirs without an order, or an order without a paid hold. It runs before the
    hub's own handler, which creates the pick job and may at once drop a line it cannot find stock for: the order
    has to be there for that drop to be taken off it."""
    placing = _placing.get()
    if placing is None or placing["reservation_id"] != payload["reservation_id"]:
        return
    res = db.get(Reservation, payload["reservation_id"])
    address, now = placing["address"], utcnow()
    lines = []
    for held in res.lines:
        sku = db.get(SKU, held.sku_id)
        # A produce unit is stored as "Tomato, 500 g" in the category "Tomato": the line says "Tomato" and "500 g".
        lines.append(OrderLine(sku_id=sku.id, name=sku.category if sku.item_id else sku.name,
                               unit_label=sku.unit_label, qty=held.qty, unit_price=sku.price))
    item_total = round(sum(line.qty * line.unit_price for line in lines), 2)
    order = Order(order_id=res.order_id, user_id=placing["user_id"], store_id=res.store_id, reservation_id=res.id,
                  status="confirmed", address_label=address["label"], address_line=address["line"],
                  landmark=address.get("landmark"), lat=address["lat"], lng=address["lng"],
                  item_total=item_total, savings=0, delivery_fee=0, total=item_total, placed_at=now, lines=lines,
                  # Payment is a stand-in, so an order is placed and confirmed in the same moment.
                  events=[OrderEvent(status="placed", at=now), OrderEvent(status="confirmed", at=now)])
    db.add(order)
    db.flush()


# --------------------------------------------------------------------------- following the hub

@events.subscribe("fulfilment.state_changed")
def on_job_state(db: Session, store_id: int, payload: dict) -> None:
    if payload["state"] == "packed":
        _move(db, payload["order_id"], "packed", only_from=("confirmed",))
    elif payload["state"] == "cancelled":
        _move(db, payload["order_id"], "cancelled", only_from=("confirmed",))


def _order_for(db: Session, order_id: str) -> Order | None:
    return db.scalar(select(Order).where(Order.order_id == order_id))


def _retotal(order: Order) -> None:
    order.item_total = round(sum(line.qty * line.unit_price for line in order.lines), 2)
    order.total = round(order.item_total - order.savings + order.delivery_fee, 2)


@events.subscribe("order.line_dropped")
def on_line_dropped(db: Session, store_id: int, payload: dict) -> None:
    """Units the hub could not find leave the order and its bill."""
    order = _order_for(db, payload["order_id"])
    if order is None:
        return
    left = payload["qty"]
    for line in [line for line in order.lines if line.sku_id == payload["sku_id"]]:
        gone = min(left, line.qty)
        line.qty -= gone
        left -= gone
        if line.qty == 0:
            order.lines.remove(line)
    _retotal(order)
    db.flush()


@events.subscribe("order.line_substituted")
def on_line_substituted(db: Session, store_id: int, payload: dict) -> None:
    """The customer took another item in place of a missing one: it joins the order at what it was charged."""
    order = _order_for(db, payload["order_id"])
    if order is None or not payload["qty"]:
        return
    sku = db.get(SKU, payload["substitute_sku_id"])
    order.lines.append(OrderLine(sku_id=sku.id, name=sku.category if sku.item_id else sku.name,
                                 unit_label=sku.unit_label, qty=payload["qty"],
                                 unit_price=round(payload["charge_amount"] / payload["qty"], 2)))
    _retotal(order)
    db.flush()


# --------------------------------------------------------------------------- the customer's side

def mine(db: Session, user_id: int) -> list[dict]:
    """The customer's orders, newest first."""
    orders = db.scalars(select(Order).where(Order.user_id == user_id).order_by(Order.placed_at.desc(), Order.id.desc()))
    return [view(db, order) for order in orders.all()]


def get(db: Session, user_id: int, order_id: str) -> Order:
    order = _order_for(db, order_id)
    if order is None or order.user_id != user_id:
        raise _not_yours(order_id)
    return order


def cancel(db: Session, user_id: int, order_id: str) -> dict:
    """Cancel an order the hub has not packed yet: its items go back on sale. Commits (through the pick job's own
    cancel, whose event moves the order). Cancelling a cancelled order again is safe. 409 too_late once packed."""
    order = get(db, user_id, order_id)
    if order.status == "cancelled":
        return view(db, order)
    if order.status not in OPEN:
        raise DomainError(409, "too_late", f"This order is already {order.status.replace('_', ' ')}, so it cannot be "
                                           "cancelled here")
    job = db.scalar(select(FulfilmentJob).where(FulfilmentJob.order_id == order.order_id))
    fulfilment.cancel(db, job.id, "customer")        # 409 too_late if the hub packed it a moment ago
    db.refresh(order)
    return view(db, order)
