"""Assortment Service (HLD service 2): which SKUs does each store carry?

In the prototype a store "carries" a SKU when it has a StockLevel row for it. Adding a SKU to the
assortment just creates that row with zero stock, so replenishment starts ordering it.
Member 3's guide covers choosing the assortment from local demand.
"""
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...errors import DomainError
from ...models import SKU, StockLevel
from ..inventory import service as inventory


def list_assortment(db: Session, store_id: int) -> list[dict]:
    inventory.get_store(db, store_id)
    rows = db.scalars(select(StockLevel).where(StockLevel.store_id == store_id)).all()
    return sorted(
        ({"sku_id": r.sku_id, "name": r.sku.name, "category": r.sku.category,
          "storage_type": r.sku.storage_type} for r in rows),
        key=lambda row: row["name"],
    )


def add_sku(db: Session, store_id: int, sku_id: int, reorder_point: int = 10, target_stock: int = 40) -> dict:
    inventory.get_store(db, store_id)
    sku = inventory.get_sku(db, sku_id)
    if db.get(StockLevel, (store_id, sku_id)) is not None:
        raise DomainError(409, "already_stocked", f"Store {store_id} already carries {sku.name}")
    db.add(StockLevel(store_id=store_id, sku_id=sku_id, reorder_point=reorder_point, target_stock=target_stock))
    db.commit()
    return {"store_id": store_id, "sku_id": sku_id, "name": sku.name}


def catalogue(db: Session) -> list[dict]:
    return [{"sku_id": s.id, "name": s.name, "category": s.category, "barcode": s.barcode,
             "storage_type": s.storage_type, "shelf_life_days": s.shelf_life_days, "price": s.price}
            for s in db.scalars(select(SKU).order_by(SKU.name)).all()]
