"""Farm supply (HLD flow A): a farmer lists produce, the system assigns a hub and a drop slot, and the hub weighs
and grades the lot when it arrives.

Farmers deal in kilograms of an item (Tomato). Customers buy units of it (a 500 g pack), which is what stock is
counted in. The two meet at intake: accepted kilograms are packed into whole units, and what does not fill a unit
is recorded as trim (docs/journal/2026-11-23-fixed-packs.md). Weights are stored in whole grams, so that sum is
exact.

Intake does not put anything on a shelf. It opens a goods receipt with the packed units "on the dock", and the
hub's existing putaway steps (app/modules/inbound) take them to bins, where they become sellable.
"""
from datetime import date, datetime, time, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from ... import clock, config, events
from ...errors import DomainError, not_found
from ...models import (SKU, Bin, Farm, GoodsReceipt, Listing, ProduceItem, QualityCheck, StockItem, Store, User,
                       utcnow)
from ..inbound import service as inbound
from ..serviceability import service as serviceability

GRADES = ("A", "B", "C", "reject")
LOCAL = clock.LOCAL


def kg(grams: int) -> float:
    return round(grams / 1000, 3)


def grams(kilograms: float) -> int:
    return round(kilograms * 1000)


# --------------------------------------------------------------------------- what can be listed

def items(db: Session) -> list[dict]:
    """Every produce item with the units customers buy it in."""
    units: dict[int, list[dict]] = {}
    for sku in db.scalars(select(SKU).where(SKU.item_id.is_not(None)).order_by(SKU.unit_grams, SKU.id)).all():
        units.setdefault(sku.item_id, []).append({"sku_id": sku.id, "name": sku.name, "unit_label": sku.unit_label,
                                                  "unit_grams": sku.unit_grams, "price": sku.price})
    return [{"item_id": item.id, "name": item.name, "family": item.family, "storage_type": item.storage_type,
             "shelf_life_days": item.shelf_life_days, "units": units.get(item.id, [])}
            for item in db.scalars(select(ProduceItem).order_by(ProduceItem.name)).all()]


def get_item(db: Session, item_id: int) -> ProduceItem:
    item = db.get(ProduceItem, item_id)
    if item is None:
        raise not_found("Produce item", item_id)
    return item


# --------------------------------------------------------------------------- farms

def farm_view(db: Session, farm: Farm) -> dict:
    nearest = serviceability.nearest_store(db, farm.lat, farm.lng)
    in_reach = nearest is not None and nearest[1] <= config.HUB_SEARCH_KM
    return {"farm_id": farm.id, "name": farm.name, "lat": farm.lat, "lng": farm.lng, "area_acres": farm.area_acres,
            "nearest_hub": {"store_id": nearest[0].id, "name": nearest[0].name,
                            "distance_km": round(nearest[1], 1)} if in_reach else None,
            **rejection_rate(db, farm.id)}


def create_farm(db: Session, farmer_id: int, name: str, lat: float, lng: float, accuracy_m: float | None,
                area_acres: float | None) -> dict:
    """Register a farm at a location. A location from the phone's GPS is kept only if the phone says it is good to
    FARM_LOCATION_MAX_ACCURACY_M (HLD 16); a pin placed by hand sends no accuracy. Commits."""
    if accuracy_m is not None and accuracy_m > config.FARM_LOCATION_MAX_ACCURACY_M:
        raise DomainError(422, "location_too_rough",
                          f"The phone is sure of this location only to {accuracy_m:.0f} m. Wait for a better fix "
                          f"(under {config.FARM_LOCATION_MAX_ACCURACY_M} m) or place the pin by hand.",
                          {"accuracy_m": accuracy_m, "needed_m": config.FARM_LOCATION_MAX_ACCURACY_M})
    farm = Farm(farmer_id=farmer_id, name=name.strip(), lat=lat, lng=lng, area_acres=area_acres)
    db.add(farm)
    db.commit()
    return farm_view(db, farm)


def list_farms(db: Session, farmer_id: int) -> list[dict]:
    return [farm_view(db, farm) for farm in db.scalars(select(Farm).where(Farm.farmer_id == farmer_id)
                                                       .order_by(Farm.id)).all()]


def _own_farm(db: Session, farmer_id: int, farm_id: int) -> Farm:
    farm = db.get(Farm, farm_id)
    if farm is None or farm.farmer_id != farmer_id:        # someone else's farm does not exist, as far as you know
        raise not_found("Farm", farm_id)
    return farm


def rejection_rate(db: Session, farm_id: int, days: int = 30) -> dict:
    """Rejected kg / delivered kg over the last `days` days (HLD 10.9). None until the farm has delivered anything."""
    since = utcnow() - timedelta(days=days)
    delivered, rejected = db.execute(
        select(func.coalesce(func.sum(QualityCheck.received_g), 0), func.coalesce(func.sum(QualityCheck.rejected_g), 0))
        .join(Listing, Listing.id == QualityCheck.listing_id)
        .where(Listing.farm_id == farm_id, QualityCheck.checked_at >= since)).one()
    return {"delivered_kg_30d": kg(delivered), "rejected_kg_30d": kg(rejected),
            "rejection_rate_30d": round(rejected / delivered, 3) if delivered else None}


# --------------------------------------------------------------------------- choosing a hub and a slot

def used_capacity_g(db: Session, store_id: int) -> int:
    """Grams of produce the hub holds or has promised to take: stock on its shelves, and lots on their way."""
    in_stock = db.scalar(select(func.coalesce(func.sum(StockItem.qty * SKU.unit_grams), 0))
                         .join(SKU, SKU.id == StockItem.sku_id)
                         .where(StockItem.store_id == store_id, SKU.unit_grams.is_not(None)))
    coming = db.scalar(select(func.coalesce(func.sum(Listing.qty_g), 0))
                       .where(Listing.store_id == store_id, Listing.status == "listed"))
    return int(in_stock) + int(coming)


def choose_hub(db: Session, farm: Farm, item: ProduceItem, qty_g: int) -> tuple[Store, float]:
    """The nearest open hub that can take this lot (HLD 5, flow A step 2): within HUB_SEARCH_KM of the farm, with
    shelves of the item's temperature zone, and with room for the weight. Hubs are tried nearest first, on the
    GiST index. 409 no_hub_with_room, saying why each hub in reach was passed over."""
    point = serviceability.as_point(farm.lat, farm.lng)
    metres = func.ST_Distance(Store.location, point, False)
    nearby = db.execute(select(Store, metres).where(Store.status != "closed",
                                                    func.ST_DWithin(Store.location, point,
                                                                    config.HUB_SEARCH_KM * 1000, False))
                        .order_by(Store.location.op("<->")(point)).limit(config.HUB_CANDIDATES)).all()
    passed_over = []
    for store, distance in nearby:
        if db.scalar(select(Bin.id).where(Bin.store_id == store.id, Bin.zone == item.storage_type).limit(1)) is None:
            passed_over.append({"store": store.name, "reason": f"no {item.storage_type} shelves"})
            continue
        free_g = store.capacity_kg * 1000 - used_capacity_g(db, store.id)
        if free_g < qty_g:
            passed_over.append({"store": store.name, "reason": f"room for {kg(max(free_g, 0))} kg only"})
            continue
        return store, distance / 1000
    reach = f"within {config.HUB_SEARCH_KM:g} km of the farm"
    raise DomainError(409, "no_hub_with_room",
                      f"No hub {reach} can take {kg(qty_g)} kg of {item.name} now" if nearby
                      else f"There is no open hub {reach}", {"hubs": passed_over})


def next_drop_slot(now: datetime, not_before: date) -> tuple[datetime, datetime]:
    """The next intake window (hubs take produce in the morning: HLD 11) that has not started yet and is not before
    `not_before`, the harvest date. `now` and the result are UTC; the window is in the cities' own time."""
    local_now = now + LOCAL
    day = local_now.date() if local_now.time() < time(config.INTAKE_START_HOUR) else local_now.date() + timedelta(days=1)
    start = datetime.combine(max(day, not_before), time(config.INTAKE_START_HOUR)) - LOCAL
    return start, start + timedelta(hours=config.INTAKE_HOURS)


# --------------------------------------------------------------------------- listings

def listing_view(db: Session, listing: Listing) -> dict:
    check = db.scalar(select(QualityCheck).where(QualityCheck.listing_id == listing.id))
    return {"listing_id": listing.id, "farm_id": listing.farm_id, "farm": listing.farm.name,
            "item_id": listing.item_id, "item": listing.item.name, "qty_kg": kg(listing.qty_g),
            "price_per_kg": listing.price_per_kg, "harvest_date": listing.harvest_date.isoformat(),
            "status": listing.status, "store_id": listing.store_id, "hub": db.get(Store, listing.store_id).name,
            "drop_from": listing.drop_from.isoformat() + "Z", "drop_until": listing.drop_until.isoformat() + "Z",
            "quality_check": check_view(check) if check else None}


def check_view(check: QualityCheck) -> dict:
    return {"grade": check.grade, "received_kg": kg(check.received_g), "accepted_kg": kg(check.accepted_g),
            "rejected_kg": kg(check.rejected_g), "trim_kg": kg(check.trim_g), "remarks": check.remarks,
            "batch_no": check.batch_no, "receipt_id": check.receipt_id, "checked_by": check.checked_by,
            "checked_at": check.checked_at.isoformat() + "Z"}


def create_listing(db: Session, farmer_id: int, farm_id: int, item_id: int, qty_kg: float, price_per_kg: float,
                   harvest_date: date) -> dict:
    """List produce for a hub (HLD flow A, steps 1 to 3). The answer names the hub and the drop slot. Does not
    commit: the router does, with the Idempotency-Key, so a retried request lists once.

    Refused: produce that would reach the hub with less than MIN_REMAINING_SHELF_LIFE of its shelf life left (422
    too_old: it would be turned away at the dock anyway), a harvest more than LISTING_MAX_DAYS_AHEAD days away (422
    too_far_ahead), and a lot no hub in reach can take (409 no_hub_with_room)."""
    farm = _own_farm(db, farmer_id, farm_id)
    item = get_item(db, item_id)
    now = utcnow()
    today = (now + LOCAL).date()
    if harvest_date > today + timedelta(days=config.LISTING_MAX_DAYS_AHEAD):
        raise DomainError(422, "too_far_ahead",
                          f"List produce at most {config.LISTING_MAX_DAYS_AHEAD} days before its harvest")
    drop_from, drop_until = next_drop_slot(now, harvest_date)
    days_left = item.shelf_life_days - ((drop_from + LOCAL).date() - harvest_date).days
    if days_left < config.MIN_REMAINING_SHELF_LIFE * item.shelf_life_days:
        raise DomainError(422, "too_old",
                          f"{item.name} keeps {item.shelf_life_days} days from harvest. Harvested on "
                          f"{harvest_date.isoformat()}, it would reach the hub with {max(days_left, 0)} left, and "
                          f"a hub takes produce with at least {config.MIN_REMAINING_SHELF_LIFE:.0%} of its life left.",
                          {"days_left_at_drop": days_left, "shelf_life_days": item.shelf_life_days})
    qty_g = grams(qty_kg)
    store, distance_km = choose_hub(db, farm, item, qty_g)
    listing = Listing(farm_id=farm.id, farm=farm, item_id=item.id, item=item, store_id=store.id, qty_g=qty_g,
                      price_per_kg=price_per_kg, harvest_date=harvest_date, status="listed", drop_from=drop_from,
                      drop_until=drop_until, created_at=now)
    db.add(listing)
    db.flush()
    events.publish(db, "listing.created", store.id, {"listing_id": listing.id, "item": item.name,
                                                     "qty_kg": kg(qty_g), "farm": farm.name,
                                                     "drop_from": drop_from.isoformat() + "Z"})
    return {**listing_view(db, listing), "hub_distance_km": round(distance_km, 1)}


def list_listings(db: Session, farmer_id: int) -> list[dict]:
    rows = db.scalars(select(Listing).join(Farm, Farm.id == Listing.farm_id).where(Farm.farmer_id == farmer_id)
                      .order_by(Listing.id.desc())).all()
    return [listing_view(db, listing) for listing in rows]


def cancel_listing(db: Session, farmer_id: int, listing_id: int) -> dict:
    """Withdraw a listing that has not been dropped yet, which gives the hub its room back. Commits.
    409 not_cancellable once the hub has received it."""
    listing = db.get(Listing, listing_id)
    if listing is None or listing.farm.farmer_id != farmer_id:
        raise not_found("Listing", listing_id)
    cancelled = db.execute(update(Listing).where(Listing.id == listing_id, Listing.status == "listed")
                           .values(status="cancelled").execution_options(synchronize_session=False)).rowcount
    db.commit()
    db.refresh(listing)
    if not cancelled and listing.status != "cancelled":
        raise DomainError(409, "not_cancellable", f"Listing {listing_id} is already {listing.status}")
    return listing_view(db, listing)


# --------------------------------------------------------------------------- at the hub

def get_listing(db: Session, listing_id: int) -> Listing:
    listing = db.get(Listing, listing_id)
    if listing is None:
        raise not_found("Listing", listing_id)
    return listing


def expected_drops(db: Session, store_id: int) -> list[dict]:
    """Lots on their way to this hub, soonest slot first, with who is bringing them."""
    rows = db.execute(select(Listing, User).join(Farm, Farm.id == Listing.farm_id)
                      .join(User, User.id == Farm.farmer_id)
                      .where(Listing.store_id == store_id, Listing.status == "listed")
                      .order_by(Listing.drop_from, Listing.id)).all()
    return [{**listing_view(db, listing), "farmer": farmer.name or farmer.email, "farmer_phone": farmer.phone,
             **rejection_rate(db, listing.farm_id)} for listing, farmer in rows]


def lots_on_dock(db: Session, store_id: int) -> list[dict]:
    """Lots weighed at this hub whose packs still wait on the dock: their goods receipt is open. A receiver who was
    interrupted finds the lot here and carries on putting it away."""
    lots = db.scalars(select(Listing).join(QualityCheck, QualityCheck.listing_id == Listing.id)
                      .join(GoodsReceipt, GoodsReceipt.id == QualityCheck.receipt_id)
                      .where(Listing.store_id == store_id, GoodsReceipt.status == "open")
                      .order_by(Listing.id)).all()
    return [listing_view(db, lot) for lot in lots]


def _units(db: Session, item: ProduceItem, accepted_g: int, packs: list[dict] | None) -> list[tuple[SKU, int]]:
    """How the accepted weight is packed: the units asked for, or all of it into the item's smallest unit."""
    skus = db.scalars(select(SKU).where(SKU.item_id == item.id).order_by(SKU.unit_grams, SKU.id)).all()
    if not skus:
        raise DomainError(409, "no_unit", f"{item.name} has no unit to pack it into yet")
    if packs is None:
        return [(skus[0], accepted_g // skus[0].unit_grams)]
    by_id = {sku.id: sku for sku in skus}
    plan: dict[int, int] = {}
    for pack in packs:
        if pack["sku_id"] not in by_id:
            raise DomainError(422, "wrong_unit", f"SKU {pack['sku_id']} is not a unit of {item.name}")
        plan[pack["sku_id"]] = plan.get(pack["sku_id"], 0) + pack["units"]
    used_g = sum(by_id[sku_id].unit_grams * units for sku_id, units in plan.items())
    if used_g > accepted_g:
        raise DomainError(422, "packs_exceed_weight",
                          f"These packs take {kg(used_g)} kg but only {kg(accepted_g)} kg was accepted",
                          {"packs_kg": kg(used_g), "accepted_kg": kg(accepted_g)})
    return [(by_id[sku_id], units) for sku_id, units in plan.items()]


def intake(db: Session, listing: Listing, received_kg: float, rejected_kg: float, grade: str, remarks: str | None,
           packs: list[dict] | None, actor: str) -> dict:
    """Weigh and grade a lot as it arrives (HLD flow A, step 4), and pack what was accepted.

    Accepted kg = received - rejected; grade `reject` turns the whole lot away. The accepted weight becomes whole
    units, which go on a new goods receipt, on the dock, as batch L<listing id> with expiry = harvest date + the
    item's shelf life. Units the receipt refuses for too little shelf life are counted as rejected there. Does not
    commit (the router does, with the Idempotency-Key). 409 not_listed for a lot already received or cancelled;
    two receivers taking in the same lot at once take turns, and the second gets that 409."""
    taken = db.execute(update(Listing).where(Listing.id == listing.id, Listing.status == "listed")
                       .values(status="received").execution_options(synchronize_session=False)).rowcount
    if not taken:
        db.refresh(listing)
        raise DomainError(409, "not_listed", f"Listing {listing.id} is already {listing.status}")
    received_g, rejected_g = grams(received_kg), grams(rejected_kg)
    if received_g > listing.qty_g * (1 + config.INTAKE_OVER_TOLERANCE):
        raise DomainError(422, "more_than_listed",
                          f"{kg(received_g)} kg is more than the {kg(listing.qty_g)} kg listed (a little over is "
                          "fine). Ask the farmer to list the rest.")
    if grade == "reject":
        rejected_g = received_g
    if rejected_g > received_g:
        raise DomainError(422, "bad_weights", "Rejected weight cannot be more than the weight received")
    accepted_g = received_g - rejected_g
    if grade != "reject" and accepted_g == 0:
        raise DomainError(422, "bad_weights", "Nothing was accepted: grade the lot 'reject'")

    item = listing.item
    batch_no = f"L{listing.id}"
    plan = [] if grade == "reject" else [(sku, units) for sku, units in _units(db, item, accepted_g, packs) if units]
    trim_g = accepted_g - sum(sku.unit_grams * units for sku, units in plan)
    receipt = None
    if plan:
        receipt = inbound.open_receipt(db, listing.store_id, commit=False)
        expiry = listing.harvest_date + timedelta(days=item.shelf_life_days)
        for sku, units in plan:
            receipt = inbound.scan(db, receipt["receipt_id"], sku.barcode, units, batch_no=batch_no,
                                   expiry_date=expiry, commit=False)
        receipt.pop("scan", None)
    check = QualityCheck(listing_id=listing.id, store_id=listing.store_id, batch_no=batch_no, grade=grade,
                         received_g=received_g, accepted_g=accepted_g, rejected_g=rejected_g, trim_g=trim_g,
                         remarks=(remarks or "").strip() or None, checked_by=actor, checked_at=utcnow(),
                         receipt_id=receipt["receipt_id"] if receipt else None)
    db.add(check)
    db.flush()
    db.refresh(listing)
    events.publish(db, "listing.received", listing.store_id,
                   {"listing_id": listing.id, "item": item.name, "grade": grade, "accepted_kg": kg(accepted_g),
                    "rejected_kg": kg(rejected_g), "receipt_id": check.receipt_id})
    return {**listing_view(db, listing), "shortfall_kg": kg(max(listing.qty_g - received_g, 0)),
            "packed": [{"sku_id": sku.id, "sku": sku.name, "units": units} for sku, units in plan],
            "receipt": receipt}
