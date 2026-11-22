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

from ... import config
from ...models import City, ServiceabilityMiss, Store, StoreZone

log = logging.getLogger(__name__)


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


def rebuild_zones(db: Session) -> int:
    """Recalculate which store serves each H3 cell and return the number of cells. Commits.

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
    db.commit()
    return len(nearest)


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
