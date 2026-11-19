"""Inbound Service (HLD service 9): receive a truck and put the stock away (HLD 6.3)."""
from datetime import date, timedelta

from sqlalchemy.orm import Session

from ... import events
from ...errors import DomainError, not_found
from ...models import Bin, TransferOrder, utcnow
from ..inventory import service as inventory
from ..slotting import service as slotting


def receive_goods(db: Session, store_id: int, lines: list[dict], transfer_order_id: int | None = None,
                  actor: str = "receiver") -> dict:
    """Record a goods receipt. Each line: sku_id, qty, and optionally batch_no, expiry_date, bin_id.
    Missing details are filled in: today's batch, shelf-life expiry, and the bin Slotting suggests.
    A line that would overfill its bin is refused with 409 bin_full, and then nothing in the receipt is kept."""
    inventory.get_store(db, store_id)
    order = None
    if transfer_order_id is not None:
        order = db.get(TransferOrder, transfer_order_id)
        if order is None or order.store_id != store_id:
            raise not_found("Transfer order", transfer_order_id)
        if order.status == "received":
            raise DomainError(409, "already_received", f"Transfer order {order.id} was already received")

    reference = f"to:{order.id}" if order else "grn"
    received = []
    for line in lines:
        sku = inventory.get_sku(db, line["sku_id"])
        bin_id = line.get("bin_id") or slotting.suggest_bin(db, store_id, sku.id, line["qty"]).id
        slotting.ensure_room(db, store_id, bin_id, line["qty"])
        batch_no = line.get("batch_no") or f"B{date.today():%y%m%d}"
        expiry = line.get("expiry_date") or date.today() + timedelta(days=sku.shelf_life_days)
        inventory.receive(db, store_id, sku.id, line["qty"], bin_id, batch_no, expiry, reference, actor)
        received.append({"sku_id": sku.id, "sku": sku.name, "qty": line["qty"], "bin": db.get(Bin, bin_id).code,
                         "batch_no": batch_no, "expiry_date": expiry.isoformat()})

    discrepancies = []
    if order is not None:
        got: dict[int, int] = {}
        for line in lines:
            got[line["sku_id"]] = got.get(line["sku_id"], 0) + line["qty"]
        for ol in order.lines:
            ol.qty_received = got.pop(ol.sku_id, 0)
            if ol.qty_received != ol.qty_ordered:
                discrepancies.append({"sku_id": ol.sku_id, "sku": ol.sku.name, "ordered": ol.qty_ordered,
                                      "received": ol.qty_received})
        for sku_id, qty in got.items():            # arrived but never ordered
            discrepancies.append({"sku_id": sku_id, "sku": inventory.get_sku(db, sku_id).name,
                                  "ordered": 0, "received": qty})
        order.status = "received"
        order.received_at = utcnow()

    events.publish(db, "goods.received", store_id,
                   {"transfer_order_id": order.id if order else None, "lines": len(received),
                    "discrepancies": len(discrepancies)})
    db.commit()
    return {"store_id": store_id, "transfer_order_id": order.id if order else None,
            "received": received, "discrepancies": discrepancies}
