"""Serviceability Service (HLD service 1): which store serves this address, and how fast?

Delivery zones are H3 hexagon cells. `rebuild_zones` works out once which store serves each cell;
`check` then turns the customer's location into a cell and looks up that one row, instead of
measuring the distance to every store on every request.
"""
import math

import h3
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ... import config
from ...models import ServiceabilityMiss, Store, StoreZone


def distance_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle (haversine) distance between two points, in kilometres."""
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


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
    db.add(ServiceabilityMiss(h3_cell=cell))
    db.commit()
    # Not serviceable: say how far the nearest store is. This is the rare path, so measuring is fine here.
    stores = db.scalars(select(Store).where(Store.status != "closed")).all()
    ranked = sorted(((distance_km(lat, lng, s.lat, s.lng), s) for s in stores), key=lambda pair: pair[0])
    nearest = ranked[0] if ranked else None
    return {"serviceable": False, "store_id": None, "h3_cell": cell,
            "nearest_store": nearest[1].name if nearest else None,
            "nearest_distance_km": round(nearest[0], 2) if nearest else None}


def list_stores(db: Session) -> list[dict]:
    stores = db.scalars(select(Store).order_by(Store.id)).all()
    return [{"store_id": s.id, "name": s.name, "lat": s.lat, "lng": s.lng, "radius_km": s.radius_km,
             "status": s.status} for s in stores]
