"""Demo data: two stores, 16 products, and a week of sales history.

A few situations are planted on purpose so the demo has something to show:
  * Store 1, milk      - two batches with different expiry dates (shows FEFO picking), and a safety buffer
                         of 2, so 30 on hand shows as 28 available
  * Store 1, bread     - only 4 left, below the reorder point (shows replenishment)
  * Store 1, ice cream - exactly 1 left (shows two customers racing for the last unit)
  * Store 2, bananas   - out of stock (shows an item hidden from the customer)
"""
from datetime import date, timedelta
from functools import cache

import h3
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import config
from .auth import hash_password
from .db import Base, SessionLocal, engine
from .models import SKU, Bin, Staff, StockItem, StockLedger, StockLevel, Store, StoreZone, utcnow
from .modules.serviceability import service as serviceability

STORES = [
    ("DS-01 Central", 12.9716, 77.5946),
    ("DS-02 North", 13.0350, 77.5970),
]

# name, category, storage type, shelf life (days), price (INR)
SKUS = [
    ("Toned milk 500 ml", "Dairy", "chilled", 3, 28),
    ("Curd 400 g", "Dairy", "chilled", 7, 35),
    ("Paneer 200 g", "Dairy", "chilled", 10, 90),
    ("White bread 400 g", "Bakery", "ambient", 4, 45),
    ("Eggs (pack of 6)", "Dairy", "ambient", 14, 60),
    ("Bananas (6 pcs)", "Fruits", "ambient", 4, 40),
    ("Basmati rice 1 kg", "Staples", "ambient", 365, 140),
    ("Wheat atta 5 kg", "Staples", "ambient", 120, 245),
    ("Sugar 1 kg", "Staples", "ambient", 365, 48),
    ("Tea 250 g", "Beverages", "ambient", 365, 130),
    ("Instant noodles (pack of 4)", "Snacks", "ambient", 240, 56),
    ("Potato chips 90 g", "Snacks", "ambient", 120, 30),
    ("Sunflower oil 1 L", "Staples", "ambient", 270, 155),
    ("Vanilla ice cream 500 ml", "Frozen", "frozen", 180, 120),
    ("Frozen green peas 500 g", "Frozen", "frozen", 270, 95),
    ("Bath soap (pack of 3)", "Personal care", "ambient", 730, 99),
]

# Units sold per day in store 1 over the past week (oldest first), used by the forecast demo.
SALES_HISTORY = {
    "Toned milk 500 ml": [18, 22, 20, 25, 19, 21, 23],
    "White bread 400 g": [12, 10, 14, 11, 13, 12, 15],
    "Eggs (pack of 6)": [6, 8, 7, 9, 6, 7, 8],
    "Potato chips 90 g": [5, 4, 6, 5, 7, 4, 5],
}

# Units per case from the hub (replenishment orders whole cases). SKUs not listed come one at a time.
CASE_SIZES = {
    "Toned milk 500 ml": 12, "Curd 400 g": 12, "Paneer 200 g": 10, "White bread 400 g": 10,
    "Eggs (pack of 6)": 6, "Bananas (6 pcs)": 6, "Basmati rice 1 kg": 10, "Wheat atta 5 kg": 4,
    "Sugar 1 kg": 10, "Tea 250 g": 12, "Instant noodles (pack of 4)": 12, "Potato chips 90 g": 24,
    "Sunflower oil 1 L": 12, "Vanilla ice cream 500 ml": 6, "Frozen green peas 500 g": 10,
    "Bath soap (pack of 3)": 12,
}

DEFAULT_QTY = 30

STORE_ROLES = ("picker", "packer", "receiver", "manager")   # one login of each per store
CITY_ROLES = ("ops", "admin")                                 # not tied to a store


def _make_bins(db: Session, store_id: int) -> dict[str, list[Bin]]:
    """12 ambient bins (3 racks x 4 shelves), 4 chilled, 2 frozen. walk_seq 1 is nearest the packing desk."""
    layout = [("ambient", f"A-{rack:02d}-{shelf:02d}") for rack in range(1, 4) for shelf in range(1, 5)]
    layout += [("chilled", f"C-01-{shelf:02d}") for shelf in range(1, 5)]
    layout += [("frozen", f"F-01-{shelf:02d}") for shelf in range(1, 3)]
    bins: dict[str, list[Bin]] = {"ambient": [], "chilled": [], "frozen": []}
    for seq, (zone, code) in enumerate(layout, start=1):
        b = Bin(store_id=store_id, code=code, zone=zone, walk_seq=seq)
        db.add(b)
        bins[zone].append(b)
    db.flush()
    return bins


def seed(db: Session) -> None:
    today = date.today()
    skus = []
    for n, (name, category, storage, shelf_life, price) in enumerate(SKUS, start=1):
        sku = SKU(name=name, category=category, barcode=f"890{n:010d}", storage_type=storage,
                  shelf_life_days=shelf_life, price=price, case_size=CASE_SIZES.get(name, 1))
        db.add(sku)
        skus.append(sku)
    db.flush()

    for index, (name, lat, lng) in enumerate(STORES, start=1):
        store = Store(name=name, lat=lat, lng=lng, radius_km=3.0)
        db.add(store)
        db.flush()
        bins = _make_bins(db, store.id)
        next_bin = {"ambient": 0, "chilled": 0, "frozen": 0}

        for sku in skus:
            zone_bins = bins[sku.storage_type]
            home = zone_bins[next_bin[sku.storage_type] % len(zone_bins)]
            next_bin[sku.storage_type] += 1
            fresh = today + timedelta(days=sku.shelf_life_days)

            # (bin, batch, expiry, quantity) for this SKU in this store
            placements = [(home, "B-OPEN", fresh, DEFAULT_QTY)]
            if index == 1 and sku.name == "Toned milk 500 ml":
                placements = [(home, "M-OLD", today + timedelta(days=1), 6),
                              (bins["chilled"][-1], "M-NEW", fresh, 24)]
            elif index == 1 and sku.name == "White bread 400 g":
                placements = [(home, "B-OPEN", fresh, 4)]
            elif index == 1 and sku.name == "Vanilla ice cream 500 ml":
                placements = [(home, "B-OPEN", fresh, 1)]
            elif index == 2 and sku.name == "Bananas (6 pcs)":
                placements = []

            history = SALES_HISTORY.get(sku.name, []) if index == 1 else []
            on_hand = sum(qty for _, _, _, qty in placements)
            buffer = 2 if index == 1 and sku.name == "Toned milk 500 ml" else 0     # shows the ATP safety buffer
            db.add(StockLevel(store_id=store.id, sku_id=sku.id, qty_on_hand=on_hand, qty_reserved=0,
                              safety_buffer=buffer, reorder_point=10, target_stock=40))
            for bin_, batch, expiry, qty in placements:
                db.add(StockItem(store_id=store.id, sku_id=sku.id, bin_id=bin_.id, batch_no=batch,
                                 expiry_date=expiry, qty=qty))
                # Opening receipt: the units in this bin today.
                db.add(StockLedger(store_id=store.id, sku_id=sku.id, bin_id=bin_.id, delta=qty,
                                   reason="receipt", reference="opening-stock", actor="seed",
                                   ts=utcnow() - timedelta(days=8)))
            if history:
                # The units sold in the history arrived in a receipt of their own, tagged like the sales, so the
                # history rows always sum to zero and can be deleted together (scripts/generate_sales.py does).
                db.add(StockLedger(store_id=store.id, sku_id=sku.id, bin_id=home.id, delta=sum(history),
                                   reason="receipt", reference="history", actor="seed",
                                   ts=utcnow() - timedelta(days=8)))
            for days_ago, units in zip(range(len(history), 0, -1), history):
                db.add(StockLedger(store_id=store.id, sku_id=sku.id, bin_id=home.id, delta=-units,
                                   reason="sale", reference="history", actor="seed",
                                   ts=utcnow() - timedelta(days=days_ago)))
    seed_staff(db)
    db.commit()
    serviceability.rebuild_zones(db)


@cache
def _demo_password_hash() -> str:
    """Hashed once per process: scrypt is slow on purpose, and the tests reseed before every test."""
    return hash_password(config.DEMO_PASSWORD)


def seed_staff(db: Session) -> None:
    """Demo logins: picker1, packer1, receiver1, manager1 (and ...2 for store 2), plus city-wide ops and admin.
    They all share config.DEMO_PASSWORD. Does not commit."""
    for store_id in db.scalars(select(Store.id).order_by(Store.id)).all():
        for role in STORE_ROLES:
            db.add(Staff(username=f"{role}{store_id}", password_hash=_demo_password_hash(),
                         role=role, store_id=store_id))
    for role in CITY_ROLES:
        db.add(Staff(username=role, password_hash=_demo_password_hash(), role=role, store_id=None))


def seed_if_empty(db: Session) -> bool:
    if db.scalar(select(func.count()).select_from(Store)) == 0:
        seed(db)
        return True
    if db.scalar(select(func.count()).select_from(Staff)) == 0:
        # A database from before logins existed: add the demo staff without touching its stock.
        seed_staff(db)
        db.commit()
    cell = db.scalar(select(StoreZone.h3_cell).limit(1))
    if cell is None or h3.get_resolution(cell) != config.H3_RESOLUTION:
        # A database from before delivery zones existed, or one built at another H3_RESOLUTION.
        serviceability.rebuild_zones(db)
    return False


def reset() -> None:
    """Wipe the database and load the demo data again."""
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        seed(db)


if __name__ == "__main__":
    reset()
    print("Database reset and demo data loaded.")
