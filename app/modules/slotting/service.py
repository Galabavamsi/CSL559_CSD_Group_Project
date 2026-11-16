"""Slotting Service (HLD service 6): decide which bin a SKU should live in.

The prototype rule is simple: keep a SKU together, otherwise use the emptiest bin in the right
temperature zone, nearest to the packing desk. Member 3's guide covers the real rule
(fast movers nearest, items bought together close to each other).
"""
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ...errors import DomainError
from ...models import Bin, StockItem
from ..inventory import service as inventory


def suggest_bin(db: Session, store_id: int, sku_id: int) -> Bin:
    sku = inventory.get_sku(db, sku_id)
    same_sku = db.scalar(
        select(Bin).join(StockItem, StockItem.bin_id == Bin.id)
        .where(StockItem.store_id == store_id, StockItem.sku_id == sku_id, StockItem.qty > 0)
        .order_by(Bin.walk_seq)
    )
    if same_sku is not None:
        return same_sku
    bins = db.scalars(
        select(Bin).where(Bin.store_id == store_id, Bin.zone == sku.storage_type).order_by(Bin.walk_seq)
    ).all()
    if not bins:
        raise DomainError(409, "no_bin", f"Store {store_id} has no {sku.storage_type} bin for {sku.name}")
    load = dict(
        db.execute(
            select(StockItem.bin_id, func.sum(StockItem.qty))
            .where(StockItem.store_id == store_id).group_by(StockItem.bin_id)
        ).all()
    )
    return min(bins, key=lambda b: (load.get(b.id, 0), b.walk_seq))


def list_bins(db: Session, store_id: int) -> list[dict]:
    inventory.get_store(db, store_id)
    bins = db.scalars(select(Bin).where(Bin.store_id == store_id).order_by(Bin.walk_seq)).all()
    return [{"bin_id": b.id, "code": b.code, "zone": b.zone, "walk_seq": b.walk_seq} for b in bins]
