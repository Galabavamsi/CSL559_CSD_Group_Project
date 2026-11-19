"""Assortment Service (HLD service 2): which SKUs does each store carry?

In the prototype a store "carries" a SKU when it has a StockLevel row for it. Adding a SKU to the
assortment just creates that row with zero stock, so replenishment starts ordering it; dropping one deletes
the row once nothing is on the shelf, held for a customer or on its way. `recommendations` suggests what to
add and drop from local demand and shelf space.
"""
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from ...errors import DomainError
from ...models import SKU, Bin, StockLevel, Store
from ..forecasting import service as forecasting
from ..inventory import service as inventory
from ..replenishment import service as replenishment

SALES_DAYS = 30                          # recommendations look at the last 30 whole days of sales
ZONES = ("ambient", "chilled", "frozen")


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


def recommendations(db: Session, store_id: int) -> dict:
    """What one store could add, what it could drop, and how much shelf room each zone has (HLD service 2).
    Read-only.

    add: SKUs it does not carry that sold in another store in the last SALES_DAYS whole days, highest daily demand
    first (units a day, averaged over the stores selling it), and whether their zone has a bin to spare.
    drop: SKUs it carries with stock on hand and no sale in those days: dead stock taking space.
    space: per zone, bins against SKUs carried; room_for below 1 means a new SKU there gets no bin of its own.
    """
    inventory.get_store(db, store_id)
    carried = {level.sku_id: level for level in db.scalars(select(StockLevel).where(StockLevel.store_id == store_id))}
    space = _space(db, store_id, carried.values())
    room = {row["zone"]: row["room_for"] for row in space}
    selling: dict[int, list[float]] = {}
    for other in list(db.scalars(select(Store.id).where(Store.id != store_id).order_by(Store.id))):
        for sku_id, by_day in forecasting.daily_sales(db, other, SALES_DAYS).items():
            if sku_id not in carried and sum(by_day.values()) > 0:
                selling.setdefault(sku_id, []).append(sum(by_day.values()) / SALES_DAYS)
    add = []
    for sku_id, per_store in selling.items():
        sku = inventory.get_sku(db, sku_id)
        add.append({"sku_id": sku_id, "sku": sku.name, "zone": sku.storage_type,
                    "daily_demand": round(sum(per_store) / len(per_store), 2), "stores_selling": len(per_store),
                    "fits": room.get(sku.storage_type, 0) > 0})
    add.sort(key=lambda row: (-row["daily_demand"], row["sku"]))
    sold_here = forecasting.daily_sales(db, store_id, SALES_DAYS)
    drop = sorted(({"sku_id": level.sku_id, "sku": level.sku.name, "on_hand": level.qty_on_hand}
                   for level in carried.values()
                   if level.qty_on_hand > 0 and not sum(sold_here.get(level.sku_id, {}).values())),
                  key=lambda row: row["sku"])
    return {"store_id": store_id, "days": SALES_DAYS, "add": add, "drop": drop, "space": space}


def _space(db: Session, store_id: int, levels) -> list[dict]:
    bins = {zone: count for zone, count in db.execute(
        select(Bin.zone, func.count()).where(Bin.store_id == store_id).group_by(Bin.zone)).all()}
    skus: dict[str, int] = {}
    for level in levels:
        skus[level.sku.storage_type] = skus.get(level.sku.storage_type, 0) + 1
    return [{"zone": zone, "bins": bins.get(zone, 0), "skus": skus.get(zone, 0),
             "room_for": bins.get(zone, 0) - skus.get(zone, 0)}
            for zone in ZONES if zone in bins or zone in skus]


def drop_sku(db: Session, store_id: int, sku_id: int) -> dict:
    """Stop carrying a SKU in one store, and commit. Only when nothing is on the shelf, held for a customer or on
    its way from the hub; otherwise 409 still_stocked naming each reason. 404 not_carried when it is not carried."""
    inventory.get_store(db, store_id)
    sku = inventory.get_sku(db, sku_id)
    level = db.get(StockLevel, (store_id, sku_id), populate_existing=True)
    if level is None:
        raise DomainError(404, "not_carried", f"Store {store_id} does not carry {sku.name}")
    coming = replenishment.in_transit(db, store_id).get(sku_id, 0)
    reasons = [f"{count} {what}" for count, what in ((level.qty_on_hand, "on hand"),
                                                     (level.qty_reserved, "held for customers"),
                                                     (coming, "on their way")) if count]
    if reasons:
        raise DomainError(409, "still_stocked", f"Store {store_id} still has {sku.name}: {', '.join(reasons)}",
                          {"on_hand": level.qty_on_hand, "reserved": level.qty_reserved, "in_transit": coming})
    # Conditional, so units received or held between the check above and here are never orphaned.
    gone = db.execute(delete(StockLevel).where(StockLevel.store_id == store_id, StockLevel.sku_id == sku_id,
                                               StockLevel.qty_on_hand == 0, StockLevel.qty_reserved == 0)).rowcount
    if not gone:
        db.rollback()
        raise DomainError(409, "still_stocked", f"Store {store_id} just received or held {sku.name}; try again")
    db.commit()
    return {"store_id": store_id, "sku_id": sku_id, "name": sku.name, "carried": False}
