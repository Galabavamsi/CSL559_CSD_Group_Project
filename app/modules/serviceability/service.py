"""Serviceability Service (HLD service 1): which store serves this address, and how fast?

The prototype measures straight-line distance to each store and compares it with the store's
delivery radius. The HLD design uses H3 hexagon cells instead; Member 4's guide covers the switch.
"""
import math

from sqlalchemy import select
from sqlalchemy.orm import Session

from ... import config
from ...models import Store


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


def check(db: Session, lat: float, lng: float) -> dict:
    """Find the nearest open store whose delivery radius covers the point (FR-1)."""
    stores = db.scalars(select(Store).where(Store.status != "closed")).all()
    ranked = sorted(((distance_km(lat, lng, s.lat, s.lng), s) for s in stores), key=lambda pair: pair[0])
    for km, store in ranked:
        if km <= store.radius_km:
            return {"serviceable": True, "store_id": store.id, "store": store.name, "status": store.status,
                    "distance_km": round(km, 2), "eta_minutes": eta_minutes(store, km)}
    nearest = ranked[0] if ranked else None
    return {"serviceable": False, "store_id": None,
            "nearest_store": nearest[1].name if nearest else None,
            "nearest_distance_km": round(nearest[0], 2) if nearest else None}


def list_stores(db: Session) -> list[dict]:
    stores = db.scalars(select(Store).order_by(Store.id)).all()
    return [{"store_id": s.id, "name": s.name, "lat": s.lat, "lng": s.lng, "radius_km": s.radius_km,
             "status": s.status} for s in stores]
