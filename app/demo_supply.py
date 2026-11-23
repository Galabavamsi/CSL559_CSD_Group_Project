"""Demo farms: lots that arrive without a farmer, so a hosted demo's shops are never empty.

A hub sells only what a farm has brought it, so a hub nobody has delivered to shows an empty shop. For a demo that
is a dead end: the first thing a visitor does is open the shop. `top_up` looks at every hub in a city that has
demo farms and, for each produce item the hub is nearly out of, brings one lot.

The lot is not conjured onto a shelf. It goes through what a real lot goes through: a listing, the hub's weighing
and grading (farms.intake), packing into units, and putaway bin by bin (inbound.put_away). So the stock has a
batch, a farm, a grade, a harvest date and a use-by date like any other, and everything downstream (the shop's
batch facts, the rescue price, picking oldest first, the audit) treats it the same. Only the farmer is missing:
the farms below belong to one account that nobody can sign in to.
"""
import logging
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import clock, config
from .errors import DomainError
from .models import SKU, City, Farm, Listing, ProduceItem, Store, User, utcnow
from .modules.farms import service as farms
from .modules.inbound import service as inbound
from .modules.inventory import service as inventory

log = logging.getLogger("darkstore.demo_supply")

# `.invalid` can never receive mail (RFC 2606), so no sign-in code for this account can ever be read.
DEMO_FARMER_EMAIL = "demo-farms@farm2home.invalid"
ACTOR = "demo-supply"
LOCK = 0x46324844          # "F2HD": one top-up at a time, across app instances

# Farms by city: name, latitude, longitude. Named after the road or village they are near; not real farms.
FARMS: dict[str, list[tuple[str, float, float]]] = {
    "bhilai": [
        ("Patan Road Farm", 21.105, 81.420),
        ("Utai Vegetable Growers", 21.118, 81.381),
        ("Dhamdha Orchard", 21.330, 81.335),
        ("Ahiwara Greens", 21.300, 81.405),
    ],
    "bangalore": [
        ("Devanahalli Fields", 13.230, 77.700),
        ("Hoskote Vegetable Growers", 13.070, 77.790),
        ("Kanakapura Orchard", 12.700, 77.450),
    ],
}

# What a lot of each item looks like: kilograms brought, kilograms the hub turns away, grade, days since harvest.
# Spinach keeps two days and comes a day old, so the shop always has something in its last day at the rescue price.
LOTS: dict[str, tuple[float, float, str, int]] = {
    "Tomato": (12, 0.5, "A", 0),
    "Onion": (15, 0.3, "A", 1),
    "Potato": (15, 0.4, "A", 2),
    "Carrot": (8, 0.2, "A", 0),
    "Cauliflower": (9, 0.5, "B", 0),
    "Okra": (4, 0.1, "A", 0),
    "Brinjal": (6, 0.2, "A", 0),
    "Green chilli": (2, 0.0, "A", 0),
    "Spinach": (4, 0.1, "A", 1),
    "Coriander": (2, 0.0, "A", 0),
    "Banana": (9, 0.6, "A", 0),
    "Guava": (6, 0.3, "B", 0),
}
FARM_SHARE_OF_PRICE = 0.55      # what a demo farm asks per kg, as a share of what a kg sells for


def _farms_for(db: Session, city: City) -> list[Farm]:
    """The city's demo farms, registered the first time they are needed. Does not commit."""
    farmer = db.scalar(select(User).where(User.email == DEMO_FARMER_EMAIL))
    if farmer is None:
        farmer = User(role="farmer", email=DEMO_FARMER_EMAIL, name="Demo farms")
        db.add(farmer)
        db.flush()
    found = []
    for name, lat, lng in FARMS[city.slug]:
        farm = db.scalar(select(Farm).where(Farm.farmer_id == farmer.id, Farm.name == name))
        if farm is None:
            farm = Farm(farmer_id=farmer.id, name=name, lat=lat, lng=lng)
            db.add(farm)
            db.flush()
        found.append(farm)
    return found


def _bring(db: Session, store: Store, farm: Farm, item: ProduceItem, units: list[SKU]) -> int:
    """One lot of `item` from `farm`, taken in and put away at `store`. Returns the units now on its shelves from
    it. Does not commit."""
    brought_kg, turned_away_kg, grade, age_days = LOTS[item.name]
    unit = min(units, key=lambda sku: sku.unit_grams)
    now = utcnow()
    listing = Listing(farm_id=farm.id, item_id=item.id, store_id=store.id, qty_g=farms.grams(brought_kg),
                      price_per_kg=round(unit.price / unit.unit_grams * 1000 * FARM_SHARE_OF_PRICE),
                      harvest_date=clock.today() - timedelta(days=age_days), status="listed", drop_from=now,
                      drop_until=now + timedelta(hours=config.INTAKE_HOURS), created_at=now)
    db.add(listing)
    db.flush()
    receipt = farms.intake(db, listing, brought_kg, turned_away_kg, grade, None, None, ACTOR)["receipt"]
    if receipt is None:
        return 0
    shelved = 0
    for _ in range(50):         # one portion at a time: each putaway changes where the next one fits
        task = next((t for t in inbound.putaway_tasks(db, receipt["receipt_id"]) if t["bin_code"]), None)
        if task is None:
            break
        inbound.put_away(db, receipt["receipt_id"], task["sku_id"], task["batch_no"], task["bin_code"], task["qty"],
                         actor=ACTOR, commit=False)
        shelved += task["qty"]
    inbound.close_receipt(db, receipt["receipt_id"], send_back=True, commit=False)      # no room: back on the truck
    return shelved


def top_up(db: Session) -> list[dict]:
    """Bring a lot of every produce item a hub is nearly out of, at every open hub of a city with demo farms.
    Returns what arrived: [{store, item, farm, units}]. Commits once, at the end.

    One top-up runs at a time: a second caller, here or in another app instance, returns [] at once. A lot that
    cannot be taken in or shelved (no shelves of its temperature zone, no room) is skipped and logged; the others
    still arrive."""
    if not db.scalar(select(func.pg_try_advisory_xact_lock(LOCK))):
        db.rollback()
        return []
    items = db.scalars(select(ProduceItem).order_by(ProduceItem.id)).all()
    units_of: dict[int, list[SKU]] = {}
    for sku in db.scalars(select(SKU).where(SKU.item_id.is_not(None), SKU.unit_grams.is_not(None))).all():
        units_of.setdefault(sku.item_id, []).append(sku)
    unit_ids = [sku.id for units in units_of.values() for sku in units]
    arrived = []
    for city in db.scalars(select(City).where(City.slug.in_(FARMS)).order_by(City.id)).all():
        stores = db.scalars(select(Store).where(Store.city_id == city.id, Store.status != "closed")
                            .order_by(Store.id)).all()
        if not stores or not unit_ids:
            continue
        city_farms = _farms_for(db, city)
        for store in stores:
            # Asked for by unit, which reads the database and not the cached list a shop is shown.
            on_sale = {row["sku_id"]: row["atp"] for row in inventory.availability(db, store.id, unit_ids)}
            for n, item in enumerate(items):
                units = units_of.get(item.id)
                if item.name not in LOTS or not units:
                    continue
                if sum(on_sale.get(sku.id, 0) for sku in units) >= config.DEMO_SUPPLY_MIN_UNITS:
                    continue
                farm = city_farms[(store.id + n) % len(city_farms)]
                try:
                    with db.begin_nested():             # a lot that fails is undone alone
                        shelved = _bring(db, store, farm, item, units)
                except DomainError as error:
                    log.warning("demo lot of %s for %s skipped: %s", item.name, store.name, error.message)
                    continue
                if shelved:
                    arrived.append({"store": store.name, "item": item.name, "farm": farm.name, "units": shelved})
    db.commit()
    return arrived
