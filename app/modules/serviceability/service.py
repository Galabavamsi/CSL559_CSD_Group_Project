"""Serviceability Service (HLD service 1): which hub serves this address, and how fast?

Delivery zones are H3 hexagon cells. `rebuild_zones` works out once which hub serves each cell;
`check` then turns the customer's location into a cell and looks up that one row, instead of
measuring the distance to every hub on every request.

Questions about real distance go to PostGIS, on the GiST index over `stores.location` (HLD 8):
`nearest_store` is the nearest-neighbour search and `stores_covering` is ST_DWithin on each hub's own radius.
"""
import logging
import math

import h3
from sqlalchemy import delete, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, aliased

from ... import config, events
from ...errors import DomainError
from ...models import Bin, City, ServiceabilityMiss, Store, StoreZone

log = logging.getLogger(__name__)

# Units one bin holds, per zone: room for the stock a busy SKU needs, so orders are cut only when a zone is full.
BIN_CAPACITY = {"ambient": 200, "chilled": 150, "frozen": 100}


def distance_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle (haversine) distance between two points, in kilometres."""
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def as_point(lat: float, lng: float):
    """The point as PostGIS geography. Longitude comes first in PostGIS."""
    return func.ST_SetSRID(func.ST_MakePoint(lng, lat), 4326).cast(Store.location.type)


def nearest_store(db: Session, lat: float, lng: float, city_id: int | None = None,
                  include_closed: bool = False) -> tuple[Store, float] | None:
    """The hub nearest to a point and its distance in km, or None when there is no hub (HLD 8, query 1).
    `location <-> point` walks the GiST index outwards from the point, so it does not measure every hub."""
    point = as_point(lat, lng)
    query = select(Store, func.ST_Distance(Store.location, point, False)).order_by(Store.location.op("<->")(point))
    if not include_closed:
        query = query.where(Store.status != "closed")
    if city_id is not None:
        query = query.where(Store.city_id == city_id)
    row = db.execute(query.limit(1)).first()
    return (row[0], row[1] / 1000) if row else None


def stores_covering(db: Session, lat: float, lng: float) -> list[tuple[Store, float]]:
    """Open or busy hubs whose service radius reaches this point, nearest first, each with its distance in km
    (HLD 8, query 2: ST_DWithin). Unlike the H3 zones, this measures to the exact point and ignores the busy rule."""
    point = as_point(lat, lng)
    km = func.ST_Distance(Store.location, point, False) / 1000
    # Two conditions on purpose. The radius is each hub's own, and PostGIS cannot use the index when the distance
    # differs per row (the plan is a full scan; see docs/journal/2026-11-23-postgresql-postgis-only.md). The first
    # condition uses one distance for every row, the largest radius any hub has, so the index narrows the hubs
    # down; the second then applies each hub's real radius.
    any_hub = aliased(Store)        # a second name for the table, so the subquery is not tied to the outer row
    widest_km = select(func.max(any_hub.radius_km)).scalar_subquery()
    rows = db.execute(select(Store, km).where(
        Store.status != "closed",
        func.ST_DWithin(Store.location, point, widest_km * 1000, False),
        func.ST_DWithin(Store.location, point, Store.radius_km * 1000, False)).order_by(km)).all()
    return [(store, distance) for store, distance in rows]


def eta_minutes(store: Store, km: float) -> int:
    eta = config.PACK_MINUTES + km * config.MINUTES_PER_KM
    if store.status == "busy":
        eta += config.BUSY_PENALTY_MINUTES
    return math.ceil(eta)


def rebuild_zones(db: Session, commit: bool = True) -> int:
    """Recalculate which store serves each H3 cell and return the number of cells. Commits, unless it is one step
    of a larger change (`commit=False`).

    A store claims every cell whose centre is within its radius; where two stores claim the same
    cell, the nearer one wins. Run it again after adding a store or changing a location or radius.
    """
    edge_km = h3.average_hexagon_edge_length(config.H3_RESOLUTION, unit="km")
    nearest: dict[str, tuple[float, int]] = {}      # cell -> (distance, store id)
    for store in db.scalars(select(Store).order_by(Store.id)).all():
        home = h3.latlng_to_cell(store.lat, store.lng, config.H3_RESOLUTION)
        rings = math.ceil(store.radius_km / edge_km) + 1     # more than enough rings to cover the radius
        for cell in h3.grid_disk(home, rings):
            km = distance_km(store.lat, store.lng, *h3.cell_to_latlng(cell))
            if km <= store.radius_km and (cell not in nearest or km < nearest[cell][0]):
                nearest[cell] = (km, store.id)
    db.execute(delete(StoreZone))
    db.add_all(StoreZone(h3_cell=cell, store_id=store_id, distance_km=km)
               for cell, (km, store_id) in nearest.items())
    if commit:
        db.commit()
    else:
        db.flush()
    return len(nearest)


def make_bins(db: Session, store_id: int) -> dict[str, list[Bin]]:
    """The shelves every hub starts with: 12 ambient bins (3 racks x 4 shelves), 4 chilled, 2 frozen. walk_seq 1 is
    nearest the packing desk. Does not commit."""
    layout = [("ambient", f"A-{rack:02d}-{shelf:02d}") for rack in range(1, 4) for shelf in range(1, 5)]
    layout += [("chilled", f"C-01-{shelf:02d}") for shelf in range(1, 5)]
    layout += [("frozen", f"F-01-{shelf:02d}") for shelf in range(1, 3)]
    bins: dict[str, list[Bin]] = {"ambient": [], "chilled": [], "frozen": []}
    for seq, (zone, code) in enumerate(layout, start=1):
        b = Bin(store_id=store_id, code=code, zone=zone, walk_seq=seq, capacity=BIN_CAPACITY[zone])
        db.add(b)
        bins[zone].append(b)
    db.flush()
    return bins


def city_at(db: Session, lat: float, lng: float) -> tuple[City, float] | None:
    """The city whose centre is nearest to a point, and the distance to that centre in km. None with no cities."""
    point = as_point(lat, lng)
    row = db.execute(select(City, func.ST_Distance(City.location, point, False))
                     .order_by(City.location.op("<->")(point)).limit(1)).first()
    return (row[0], row[1] / 1000) if row else None


def open_store(db: Session, name: str, lat: float, lng: float, city: str | None = None,
               radius_km: float | None = None, capacity_kg: int | None = None, actor: str = "system") -> dict:
    """Open a hub at a site: the hub, its shelves and its delivery zone, in one change. Does not commit.

    The hub belongs to the city named, or else to the city whose centre is nearest; either way the site must lie
    inside that city's built-up area (422 outside_city). Its radius is the city's radius for a new hub unless one is
    given. A site within HUB_MIN_GAP_KM of an existing hub is the same site entered twice (409 hub_too_close), and
    two hubs cannot share a name (409 name_taken). Every delivery zone is recalculated, because the new hub takes
    over the cells it is nearest to. The hub starts empty: stock arrives from farms."""
    name = " ".join(name.split())
    if city is not None:
        home = db.scalar(select(City).where(City.slug == city))
        if home is None:
            raise DomainError(422, "unknown_city", f"There is no city {city!r}.", {"city": city})
        km = distance_km(home.lat, home.lng, lat, lng)
    else:
        found = city_at(db, lat, lng)
        if found is None:
            raise DomainError(422, "outside_city", "There is no city to open a hub in.")
        home, km = found
    if km > home.radius_km:
        raise DomainError(422, "outside_city",
                          f"This site is {km:.1f} km from the centre of {home.name}, outside its {home.radius_km:g} km.",
                          {"city": home.slug, "distance_km": round(km, 1), "city_radius_km": home.radius_km})
    if db.scalar(select(Store.id).where(func.lower(Store.name) == name.lower())) is not None:
        raise DomainError(409, "name_taken", f"There is already a hub called {name}.", {"name": name})
    neighbour = nearest_store(db, lat, lng, include_closed=True)
    if neighbour is not None and neighbour[1] < config.HUB_MIN_GAP_KM:
        raise DomainError(409, "hub_too_close",
                          f"{neighbour[0].name} is {neighbour[1] * 1000:.0f} m from this site: the same site twice?",
                          {"store_id": neighbour[0].id, "name": neighbour[0].name,
                           "distance_m": round(neighbour[1] * 1000)})

    store = Store(name=name, lat=lat, lng=lng, city_id=home.id,
                  radius_km=home.hub_radius_km if radius_km is None else radius_km)
    if capacity_kg is not None:
        store.capacity_kg = capacity_kg
    db.add(store)
    db.flush()
    bins = make_bins(db, store.id)
    rebuild_zones(db, commit=False)
    cells = db.scalar(select(func.count()).select_from(StoreZone).where(StoreZone.store_id == store.id))
    events.publish(db, "store.opened", store.id, {"name": store.name, "city": home.slug, "lat": lat, "lng": lng,
                                                  "radius_km": store.radius_km, "by": actor})
    return {"store_id": store.id, "name": store.name, "city": home.slug, "lat": store.lat, "lng": store.lng,
            "radius_km": store.radius_km, "status": store.status, "capacity_kg": store.capacity_kg,
            "bins": sum(len(zone) for zone in bins.values()), "zone_cells": cells}


def check(db: Session, lat: float, lng: float) -> dict:
    """Find the store that serves this point (FR-1): one lookup of the point's H3 cell.

    A closed store serves nobody, and a busy store serves only the inner part of its zone.
    `distance_km` in the answer is measured to the centre of the cell, not to the exact point.
    The answer carries the cell, which checkout sends back with the order for network planning.
    A point no store serves is saved as a miss (cell and time only) and commits.
    """
    cell = h3.latlng_to_cell(lat, lng, config.H3_RESOLUTION)
    zone = db.get(StoreZone, cell)
    store = db.get(Store, zone.store_id) if zone else None
    if store is not None and store.status != "closed":
        reach_km = store.radius_km * (config.BUSY_RADIUS_FACTOR if store.status == "busy" else 1)
        if zone.distance_km <= reach_km:
            return {"serviceable": True, "store_id": store.id, "store": store.name, "status": store.status,
                    "distance_km": round(zone.distance_km, 2), "eta_minutes": eta_minutes(store, zone.distance_km),
                    "h3_cell": cell}
    # shortcut: any caller can add misses by repeating lookups; rate limiting (task 4.7) is the cure.
    try:
        db.add(ServiceabilityMiss(h3_cell=cell))
        db.commit()
    except SQLAlchemyError:     # a lost miss costs a little planning data; the customer still gets an answer
        db.rollback()
        log.exception("Could not save a serviceability miss")
    # Not serviceable: say how far the nearest hub is.
    nearest = nearest_store(db, lat, lng)
    return {"serviceable": False, "store_id": None, "h3_cell": cell,
            "nearest_store": nearest[0].name if nearest else None,
            "nearest_distance_km": round(nearest[1], 2) if nearest else None}


def list_stores(db: Session, city: str | None = None) -> list[dict]:
    """Every hub with its city, or only one city's hubs when `city` is its slug (an unknown slug gives none)."""
    query = select(Store, City).outerjoin(City, City.id == Store.city_id).order_by(Store.id)
    if city is not None:
        query = query.where(City.slug == city)
    return [{"store_id": s.id, "name": s.name, "lat": s.lat, "lng": s.lng, "radius_km": s.radius_km,
             "status": s.status, "city": c.slug if c else None} for s, c in db.execute(query).all()]


def list_cities(db: Session) -> list[dict]:
    hubs = dict(db.execute(select(Store.city_id, func.count()).group_by(Store.city_id)).all())
    return [{"city": c.slug, "name": c.name, "tier": c.tier, "lat": c.lat, "lng": c.lng, "radius_km": c.radius_km,
             "hub_radius_km": c.hub_radius_km, "hubs": hubs.get(c.id, 0)}
            for c in db.scalars(select(City).order_by(City.id)).all()]
