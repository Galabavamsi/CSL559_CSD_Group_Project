"""Demo data: two hubs in Bangalore, 16 products, and a week of sales history. With DEMO_HUBS on, Bhilai gets hubs too.

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
from .db import SessionLocal, recreate_tables
from .models import SKU, City, ProduceItem, Staff, StockItem, StockLedger, StockLevel, Store, StoreZone, utcnow
from .modules.serviceability import service as serviceability

# slug, name, tier, centre lat, centre lng, built-up radius (km), service radius of a new hub (km).
# A tier-1 and a tier-2 city, to show how the same design is sized for each (HLD 12). Bangalore's hubs sit closer
# together, so each serves a smaller radius; Bhilai uses the 3 km of the Blinkit tier-2 store in HLD 3.
CITIES = [
    ("bangalore", "Bangalore", 1, 12.9716, 77.5946, 18.0, 2.0),
    ("bhilai", "Bhilai", 2, 21.1938, 81.3509, 8.0, 3.0),
]

# name, lat, lng, city slug. Bhilai's hubs come from hub placement, not from this list.
STORES = [
    ("DS-01 Central", 12.9716, 77.5946, "bangalore"),
    ("DS-02 North", 13.0350, 77.5970, "bangalore"),
]

# name, category, storage type, shelf life (days), price (INR). A category is a kind of item a customer would take
# instead of a missing one (substitutes are offered only within it), so rice and atta are not one "Staples" (#62).
SKUS = [
    ("Toned milk 500 ml", "Milk", "chilled", 3, 28),
    ("Curd 400 g", "Curd", "chilled", 7, 35),
    ("Paneer 200 g", "Paneer", "chilled", 10, 90),
    ("White bread 400 g", "Bakery", "ambient", 4, 45),
    ("Eggs (pack of 6)", "Eggs", "ambient", 14, 60),
    ("Bananas (6 pcs)", "Fruits", "ambient", 4, 40),
    ("Basmati rice 1 kg", "Rice", "ambient", 365, 140),
    ("Wheat atta 5 kg", "Flour", "ambient", 120, 245),
    ("Sugar 1 kg", "Sugar", "ambient", 365, 48),
    ("Tea 250 g", "Beverages", "ambient", 365, 130),
    ("Instant noodles (pack of 4)", "Noodles", "ambient", 240, 56),
    ("Potato chips 90 g", "Chips", "ambient", 120, 30),
    ("Sunflower oil 1 L", "Oil", "ambient", 270, 155),
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

# Produce: item, family, storage, shelf life in days from harvest, then its units as (unit label, grams of the item
# one unit takes, price in INR). Shelf lives follow HLD 15 (spinach about 2 days, tomato about 5, onion about 30);
# the prices are made up for the demo. HLD 6 keeps tomato and fruit cool and leafy greens cold; the bins here know
# one such zone, chilled, so both go there.
PRODUCE = [
    ("Tomato", "vegetables", "chilled", 5, [("500 g", 500, 24), ("1 kg", 1000, 45)]),
    ("Onion", "vegetables", "ambient", 30, [("1 kg", 1000, 38)]),
    ("Potato", "vegetables", "ambient", 30, [("1 kg", 1000, 32)]),
    ("Carrot", "vegetables", "chilled", 10, [("500 g", 500, 30)]),
    ("Cauliflower", "vegetables", "chilled", 5, [("1 piece (400-600 g)", 500, 35)]),
    ("Okra", "vegetables", "chilled", 4, [("250 g", 250, 20)]),
    ("Brinjal", "vegetables", "chilled", 6, [("500 g", 500, 28)]),
    ("Green chilli", "vegetables", "chilled", 7, [("100 g", 100, 12)]),
    ("Spinach", "leafy", "chilled", 2, [("250 g", 250, 22)]),
    ("Coriander", "herbs", "chilled", 3, [("1 bunch (about 100 g)", 100, 15)]),
    ("Banana", "fruits", "ambient", 5, [("6 pieces (about 600 g)", 600, 42)]),
    ("Guava", "fruits", "chilled", 5, [("500 g", 500, 48)]),
]

DEFAULT_QTY = 30

STORE_ROLES = ("picker", "packer", "receiver", "manager")   # one login of each per store
CITY_ROLES = ("ops", "admin")                                 # not tied to a store


# Bhilai's first hubs, opened in the demo data when DEMO_HUBS is on: name, lat, lng. Each gets the city's radius
# for a new hub (3 km). Civic Centre, Supela, Nehru Nagar, Smriti Nagar and Durg Station Road are then served;
# Risali and Kumhari are not, which is what the network map is for.
BHILAI_HUBS = [
    ("BH-01 Civic Centre", 21.1938, 81.3509),
    ("BH-02 Nehru Nagar", 21.2090, 81.3260),
    ("BH-03 Durg", 21.1904, 81.2849),
]


def seed(db: Session) -> None:
    today = date.today()
    skus = []
    for n, (name, category, storage, shelf_life, price) in enumerate(SKUS, start=1):
        sku = SKU(name=name, category=category, barcode=f"890{n:010d}", storage_type=storage,
                  shelf_life_days=shelf_life, price=price, case_size=CASE_SIZES.get(name, 1))
        db.add(sku)
        skus.append(sku)
    db.flush()

    cities = {}
    for slug, name, tier, lat, lng, radius_km, hub_radius_km in CITIES:
        cities[slug] = City(slug=slug, name=name, tier=tier, lat=lat, lng=lng, radius_km=radius_km,
                            hub_radius_km=hub_radius_km)
        db.add(cities[slug])
    db.flush()

    for index, (name, lat, lng, city) in enumerate(STORES, start=1):
        store = Store(name=name, lat=lat, lng=lng, radius_km=3.0, city_id=cities[city].id)
        db.add(store)
        db.flush()
        bins = serviceability.make_bins(db, store.id)
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
    if config.DEMO_PRODUCE:
        add_produce(db)
    db.commit()
    serviceability.rebuild_zones(db)
    if config.DEMO_HUBS and add_demo_hubs(db):
        db.commit()


@cache
def _demo_password_hash() -> str:
    """Hashed once per process: scrypt is slow on purpose, and the tests reseed before every test."""
    return hash_password(config.DEMO_PASSWORD)


def add_produce(db: Session) -> int:
    """Add the produce items and the units customers buy them in, unless they are there already. The units start
    with no stock anywhere: stock arrives from farms (app/modules/farms). Returns how many items were added. Does
    not commit."""
    if db.scalar(select(func.count()).select_from(ProduceItem)):
        return 0
    number = 0
    for name, family, storage, shelf_life, units in PRODUCE:
        item = ProduceItem(name=name, family=family, storage_type=storage, shelf_life_days=shelf_life)
        db.add(item)
        db.flush()
        for label, unit_grams, price in units:
            number += 1
            # The item's name is the category: a customer whose 500 g pack is missing is offered its 1 kg pack.
            db.add(SKU(name=f"{name}, {label}", category=name, barcode=f"891{number:010d}", storage_type=storage,
                       shelf_life_days=shelf_life, price=price, case_size=1, item_id=item.id, unit_grams=unit_grams,
                       unit_label=label))
    db.flush()
    return len(PRODUCE)


def add_demo_hubs(db: Session) -> int:
    """Open Bhilai's first hubs, with their demo logins, unless the city already has a hub. Returns how many were
    opened. Does not commit."""
    bhilai = db.scalar(select(City).where(City.slug == "bhilai"))
    if bhilai is None or db.scalar(select(func.count()).select_from(Store).where(Store.city_id == bhilai.id)):
        return 0
    for name, lat, lng in BHILAI_HUBS:
        hub = serviceability.open_store(db, name, lat, lng, city="bhilai", actor="seed")
        add_store_staff(db, hub["store_id"])
    return len(BHILAI_HUBS)


def add_store_staff(db: Session, store_id: int) -> list[str]:
    """The demo logins of one hub: picker<id>, packer<id>, receiver<id>, manager<id>, all with
    config.DEMO_PASSWORD. Returns the usernames. Does not commit."""
    names = [f"{role}{store_id}" for role in STORE_ROLES]
    for role, username in zip(STORE_ROLES, names):
        db.add(Staff(username=username, password_hash=_demo_password_hash(), role=role, store_id=store_id))
    return names


def seed_staff(db: Session) -> None:
    """Demo logins: picker1, packer1, receiver1, manager1 (and ...2 for store 2), plus city-wide ops and admin.
    They all share config.DEMO_PASSWORD. Does not commit."""
    for store_id in db.scalars(select(Store.id).order_by(Store.id)).all():
        add_store_staff(db, store_id)
    for role in CITY_ROLES:
        db.add(Staff(username=role, password_hash=_demo_password_hash(), role=role, store_id=None))


def seed_if_empty(db: Session) -> bool:
    if db.scalar(select(func.count()).select_from(Store)) == 0:
        seed(db)
        return True
    if config.DEMO_PRODUCE and add_produce(db):
        db.commit()            # a hosted copy seeded before produce existed
    if config.DEMO_HUBS and add_demo_hubs(db):
        db.commit()            # a hosted copy seeded before Bhilai had hubs
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
    """Wipe the database and load the demo data again. With DEMO_HISTORY_ON_RESET on (the shared hosted copy), also
    write the sales history and delivery lookups the demo script otherwise adds by hand."""
    recreate_tables()
    with SessionLocal() as db:
        seed(db)
        if config.DEMO_HISTORY_ON_RESET:
            from scripts import generate_demand, generate_sales    # demo tooling; imported here, it imports this module
            for store_id in db.scalars(select(Store.id).order_by(Store.id)).all():
                generate_sales.generate(store_id, db=db)
            generate_demand.look_up(db, generate_demand.clusters_for(db))


if __name__ == "__main__":
    reset()
    print("Database reset and demo data loaded.")
