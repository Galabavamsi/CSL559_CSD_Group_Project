"""Inbound Service (HLD service 9): receive a truck and put the stock away (HLD 6.3).

A receipt goes through five steps. Open it; scan each item off the truck onto the dock (nothing is sellable yet, and
damaged units or batches with too little shelf life left are recorded but never stocked); get putaway tasks; put each
line away, which makes it sellable at once; close it, which marks the transfer order received and reports shortfalls.
`receive_goods` is the older one-call receipt.

Every write step takes `commit`: the router passes False and lets run_once commit, so a request retried with the same
Idempotency-Key gets its saved answer instead of being done twice.
"""
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ... import config, events
from ...errors import DomainError, not_found
from ...models import SKU, Bin, GoodsReceipt, GoodsReceiptLine, TransferOrder, utcnow
from ..inventory import service as inventory
from ..slotting import service as slotting


def get_receipt(db: Session, receipt_id: int) -> GoodsReceipt:
    receipt = db.get(GoodsReceipt, receipt_id)
    if receipt is None:
        raise not_found("Goods receipt", receipt_id)
    return receipt


def receipt_view(receipt: GoodsReceipt) -> dict:
    """The receipt and its lines, JSON-ready (run_once saves it as the answer to a retried request)."""
    return {"receipt_id": receipt.id, "store_id": receipt.store_id, "transfer_order_id": receipt.transfer_order_id,
            "status": receipt.status, "created_at": receipt.created_at.isoformat(),
            "closed_at": receipt.closed_at.isoformat() if receipt.closed_at else None,
            "lines": [{"sku_id": line.sku_id, "sku": line.sku.name, "batch_no": line.batch_no,
                       "expiry_date": line.expiry_date.isoformat(), "scanned": line.qty_scanned,
                       "damaged": line.qty_damaged, "rejected": line.qty_rejected, "put_away": line.qty_put_away,
                       "on_dock": line.qty_scanned - line.qty_put_away} for line in receipt.lines]}


def _changeable(db: Session, receipt_id: int) -> GoodsReceipt:
    receipt = get_receipt(db, receipt_id)
    if receipt.status != "open":
        raise DomainError(409, "receipt_closed", f"Goods receipt {receipt.id} is closed")
    return receipt


def open_receipt(db: Session, store_id: int, transfer_order_id: int | None = None, commit: bool = True) -> dict:
    """Start receiving a truck (HLD 6.3, step 1). Changes no stock. 404 for a transfer order of another store,
    409 already_received for one received before, 409 receipt_open while another receipt of it is open."""
    inventory.get_store(db, store_id)
    if transfer_order_id is not None:
        order = db.get(TransferOrder, transfer_order_id)
        if order is None or order.store_id != store_id:
            raise not_found("Transfer order", transfer_order_id)
        if order.status == "received":
            raise DomainError(409, "already_received", f"Transfer order {order.id} was already received")
        still_open = db.scalar(select(GoodsReceipt.id).where(GoodsReceipt.transfer_order_id == order.id,
                                                             GoodsReceipt.status == "open"))
        if still_open is not None:
            raise DomainError(409, "receipt_open", f"Goods receipt {still_open} of transfer order {order.id} is "
                                                   f"still open", {"receipt_id": still_open})
    receipt = GoodsReceipt(store_id=store_id, transfer_order_id=transfer_order_id, status="open")
    db.add(receipt)
    db.flush()
    view = receipt_view(receipt)
    if commit:
        db.commit()
    return view


def scan(db: Session, receipt_id: int, barcode: str, qty: int, batch_no: str | None = None,
         expiry_date: date | None = None, damaged: bool = False, commit: bool = True) -> dict:
    """Scan units off the truck (HLD 6.3, step 2). Changes no stock: good units wait on the dock until they are put
    away. Damaged units, and a batch with less than MIN_REMAINING_SHELF_LIFE of its shelf life left, are recorded on
    the receipt and never stocked. Missing details get the one-call defaults: today's batch, full shelf life.
    422 unknown_barcode; 422 batch_mismatch for a batch already scanned with another expiry; 409 receipt_closed."""
    receipt = _changeable(db, receipt_id)
    if qty <= 0:
        raise DomainError(422, "bad_quantity", "Scanned quantity must be at least 1")
    sku = db.scalar(select(SKU).where(SKU.barcode == barcode))
    if sku is None:
        raise DomainError(422, "unknown_barcode", f"No product has barcode {barcode}")
    batch_no = batch_no or f"B{date.today():%y%m%d}"
    expiry = expiry_date or date.today() + timedelta(days=sku.shelf_life_days)
    line = next((ln for ln in receipt.lines if ln.sku_id == sku.id and ln.batch_no == batch_no), None)
    if line is None:
        line = GoodsReceiptLine(sku_id=sku.id, sku=sku, batch_no=batch_no, expiry_date=expiry, qty_scanned=0,
                                qty_damaged=0, qty_rejected=0, qty_put_away=0)
        receipt.lines.append(line)
    elif line.expiry_date != expiry:
        raise DomainError(422, "batch_mismatch", f"Batch {batch_no} of {sku.name} was scanned with expiry "
                                                 f"{line.expiry_date}, not {expiry}")
    days_left = (expiry - date.today()).days
    if damaged:
        line.qty_damaged += qty
        outcome, reason = "damaged", "Damaged on arrival: recorded, never stocked"
    elif days_left < config.MIN_REMAINING_SHELF_LIFE * sku.shelf_life_days:
        line.qty_rejected += qty
        outcome, reason = "rejected", (f"Refused: {days_left} of {sku.shelf_life_days} days of shelf life left, "
                                       f"at least {config.MIN_REMAINING_SHELF_LIFE:.0%} is needed")
    else:
        line.qty_scanned += qty
        outcome, reason = "on_dock", None
    db.flush()
    view = receipt_view(receipt)
    view["scan"] = {"sku_id": sku.id, "sku": sku.name, "batch_no": batch_no, "qty": qty, "outcome": outcome,
                    "reason": reason}
    if commit:
        db.commit()
    return view


def receive_goods(db: Session, store_id: int, lines: list[dict], transfer_order_id: int | None = None,
                  actor: str = "receiver") -> dict:
    """Record a goods receipt. Each line: sku_id, qty, and optionally batch_no, expiry_date, bin_id.
    Missing details are filled in: today's batch, shelf-life expiry, and the bin Slotting suggests.
    A line without a bin is spread over the bins Slotting picks, never past a bin's capacity. A line that does not
    fit is refused with 409 bin_full, and then nothing in the receipt is kept."""
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
        batch_no = line.get("batch_no") or f"B{date.today():%y%m%d}"
        expiry = line.get("expiry_date") or date.today() + timedelta(days=sku.shelf_life_days)
        if line.get("bin_id"):
            slotting.ensure_room(db, store_id, line["bin_id"], line["qty"])
            portions = [(line["bin_id"], line["qty"])]
        else:                       # as many bins as it takes, never over capacity
            portions = [(bin_.id, qty) for bin_, qty in slotting.place(db, store_id, sku.id, line["qty"])]
        for bin_id, qty in portions:
            inventory.receive(db, store_id, sku.id, qty, bin_id, batch_no, expiry, reference, actor)
            slotting.ensure_not_overfilled(db, bin_id)
            received.append({"sku_id": sku.id, "sku": sku.name, "qty": qty, "bin": db.get(Bin, bin_id).code,
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
