"""Slotting Service (HLD service 6): decide which bin a SKU should live in.

The prototype rule is simple: keep a SKU together, otherwise use the emptiest bin in the right
temperature zone, nearest to the packing desk, and never fill a bin past its capacity. Member 3's guide
covers the real rule (fast movers nearest, items bought together close to each other).
"""
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ...errors import DomainError
from ...models import Bin, StockItem
from ..inventory import service as inventory


def _load(db: Session, store_id: int) -> dict[int, int]:
    """Units stored per bin in one store."""
    return {bin_id: int(units) for bin_id, units in db.execute(
        select(StockItem.bin_id, func.sum(StockItem.qty)).where(StockItem.store_id == store_id)
        .group_by(StockItem.bin_id)).all()}


def room_in(db: Session, bin_: Bin) -> int:
    """Units `bin_` can still take: its capacity less what it holds (negative if it is already over). Read-only."""
    stored = db.scalar(select(func.coalesce(func.sum(StockItem.qty), 0)).where(StockItem.bin_id == bin_.id))
    return bin_.capacity - int(stored)


def suggest_bin(db: Session, store_id: int, sku_id: int, qty: int = 0) -> Bin:
    """The bin for `qty` more units of a SKU: a bin already holding it, if one has room, otherwise the emptiest bin
    with room in the right temperature zone, nearest the packing desk. Read-only.

    409 no_bin when the store has no bin of that zone, 409 bin_full when none has room for `qty`.
    """
    sku = inventory.get_sku(db, sku_id)
    load = _load(db, store_id)
    same_sku = db.scalars(
        select(Bin).join(StockItem, StockItem.bin_id == Bin.id)
        .where(StockItem.store_id == store_id, StockItem.sku_id == sku_id, StockItem.qty > 0)
        .distinct().order_by(Bin.walk_seq)
    ).all()
    for bin_ in same_sku:
        if bin_.capacity - load.get(bin_.id, 0) >= qty:
            return bin_
    bins = db.scalars(
        select(Bin).where(Bin.store_id == store_id, Bin.zone == sku.storage_type).order_by(Bin.walk_seq)
    ).all()
    if not bins:
        raise DomainError(409, "no_bin", f"Store {store_id} has no {sku.storage_type} bin for {sku.name}")
    with_room = [b for b in bins if b.capacity - load.get(b.id, 0) >= qty]
    if not with_room:
        raise DomainError(409, "bin_full", f"No {sku.storage_type} bin in store {store_id} has room for {qty} more "
                                           f"{sku.name}", {"zone": sku.storage_type, "qty": qty})
    return min(with_room, key=lambda b: (load.get(b.id, 0), b.walk_seq))


def ensure_room(db: Session, store_id: int, bin_id: int, qty: int) -> None:
    """409 bin_full when `qty` more units would overfill the bin. A bin that is not in the store is left for
    inventory.receive to refuse. Read-only."""
    bin_ = db.get(Bin, bin_id)
    if bin_ is None or bin_.store_id != store_id:
        return
    room = room_in(db, bin_)
    if qty > room:
        raise DomainError(409, "bin_full", f"Bin {bin_.code} has room for {max(room, 0)} more units, not {qty}",
                          {"bin": bin_.code, "capacity": bin_.capacity, "room": max(room, 0)})


def list_bins(db: Session, store_id: int) -> list[dict]:
    inventory.get_store(db, store_id)
    bins = db.scalars(select(Bin).where(Bin.store_id == store_id).order_by(Bin.walk_seq)).all()
    return [{"bin_id": b.id, "code": b.code, "zone": b.zone, "walk_seq": b.walk_seq} for b in bins]
