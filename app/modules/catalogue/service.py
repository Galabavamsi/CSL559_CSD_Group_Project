"""Catalogue: what a customer is told about a pack (docs/DESIGN.md, section 3).

The shop's list is the hub's availability, plus the facts of the batch that would be picked first for each item:
its use-by date and, for a farm lot, its grade, harvest date and farm. A batch in its last day is offered at a
rescue price, for that batch's units only. Stock is promised per hub and item and picked oldest batch first, so
"the batch you would get next" is the honest thing to show; a customer cannot choose a batch.

Nothing is stored here. A farm lot's batch is `L<listing id>`, which leads to the listing, its farm and the hub's
quality check.
"""
import re
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ... import config
from ...models import SKU, Bin, Farm, FulfilmentJob, Listing, PickTask, ProduceItem, QualityCheck, StockItem
from ..inventory import service as inventory

FARM_LOT = re.compile(r"^L(\d+)$")


def in_rescue(expiry: date, today: date) -> bool:
    """A batch in its last day (or however many RESCUE_WITHIN_DAYS says) is sold at the rescue price."""
    return (expiry - today).days <= config.RESCUE_WITHIN_DAYS


def rescue_price(price: float) -> float:
    """The full price less RESCUE_DISCOUNT, in whole rupees and never under one."""
    return float(max(1, round(price * (1 - config.RESCUE_DISCOUNT))))


def shop(db: Session, store_id: int) -> list[dict]:
    """Everything the hub stocks, as a customer should see it. Read-only.

    `batch` describes the batch the next order would be picked from: the earliest use-by date that still has units
    no other order is waiting for. `rescue` is there when units in their last day can be bought, with the lower
    price and how many units it applies to; an order for more pays the full price for the rest."""
    rows = inventory.availability(db, store_id)
    today = date.today()
    promised = dict(db.execute(
        select(PickTask.stock_item_id, func.sum(PickTask.qty))
        .join(FulfilmentJob, FulfilmentJob.id == PickTask.job_id)
        .where(FulfilmentJob.store_id == store_id, FulfilmentJob.state.in_(("created", "picking")),
               PickTask.status.in_(inventory.TOTE_STATUSES), PickTask.stock_item_id.is_not(None))
        .group_by(PickTask.stock_item_id)).all())
    items = db.execute(
        select(StockItem.id, StockItem.sku_id, StockItem.batch_no, StockItem.expiry_date, StockItem.qty)
        .join(Bin, Bin.id == StockItem.bin_id)
        .where(StockItem.store_id == store_id, StockItem.qty > 0, StockItem.expiry_date >= today)
        .order_by(StockItem.sku_id, StockItem.expiry_date, Bin.walk_seq)).all()       # the order they are picked in

    first: dict[int, dict] = {}                 # sku -> the batch picked first, and its free units
    rescue_units: dict[int, int] = {}           # sku -> free units in their last day
    for item_id, sku_id, batch_no, expiry, qty in items:
        free = qty - promised.get(item_id, 0)
        if free <= 0:
            continue
        batch = first.setdefault(sku_id, {"batch_no": batch_no, "use_by": expiry, "units": 0})
        if (batch["batch_no"], batch["use_by"]) == (batch_no, expiry):
            batch["units"] += free
        if in_rescue(expiry, today):
            rescue_units[sku_id] = rescue_units.get(sku_id, 0) + free

    lot_ids = {int(match.group(1)) for batch in first.values() if (match := FARM_LOT.match(batch["batch_no"]))}
    lots = {listing_id: (farm, harvest, grade) for listing_id, farm, harvest, grade in db.execute(
        select(Listing.id, Farm.name, Listing.harvest_date, QualityCheck.grade)
        .join(Farm, Farm.id == Listing.farm_id)
        .join(QualityCheck, QualityCheck.listing_id == Listing.id)
        .where(Listing.id.in_(lot_ids))).all()} if lot_ids else {}
    units = {sku_id: (label, item, family) for sku_id, label, item, family in db.execute(
        select(SKU.id, SKU.unit_label, ProduceItem.name, ProduceItem.family)
        .outerjoin(ProduceItem, ProduceItem.id == SKU.item_id)
        .where(SKU.id.in_([row["sku_id"] for row in rows]))).all()} if rows else {}

    out = []
    for row in rows:
        label, item, family = units[row["sku_id"]]
        batch = first.get(row["sku_id"])
        facts = None
        if batch is not None:
            lot = FARM_LOT.match(batch["batch_no"])
            farm, harvest, grade = lots.get(int(lot.group(1)), (None, None, None)) if lot else (None, None, None)
            facts = {"batch_no": batch["batch_no"], "use_by": batch["use_by"].isoformat(), "units": batch["units"],
                     "harvest_date": harvest.isoformat() if harvest else None, "grade": grade, "farm": farm}
        on_offer = min(rescue_units.get(row["sku_id"], 0), row["atp"])
        out.append({
            "sku_id": row["sku_id"],
            # A produce unit is stored as "Tomato, 500 g": the shop says "Tomato" and "500 g".
            "name": item or row["name"], "unit_label": label, "family": family, "category": row["category"],
            "price": row["price"], "atp": row["atp"], "batch": facts,
            "rescue": {"price": rescue_price(row["price"]), "units": on_offer} if on_offer > 0 else None,
        })
    return out
