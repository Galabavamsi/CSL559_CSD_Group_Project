"""Network Planning Service (HLD service 10): where are the coverage gaps?

Give it a list of demand points (a location and how many orders came from there). It reports
which points no store covers and suggests one new site: the order-weighted centre of the
uncovered points. Member 4's guide covers doing this properly with H3 cells and real order data.
"""
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...models import Store
from ..serviceability.service import distance_km


def coverage(db: Session, points: list[dict]) -> dict:
    stores = db.scalars(select(Store).where(Store.status != "closed")).all()
    report, uncovered = [], []
    covered_orders = total_orders = 0
    for p in points:
        orders = p.get("orders", 1)
        total_orders += orders
        nearest = min(((distance_km(p["lat"], p["lng"], s.lat, s.lng), s) for s in stores),
                      key=lambda pair: pair[0], default=None)
        is_covered = bool(nearest and nearest[0] <= nearest[1].radius_km)
        if is_covered:
            covered_orders += orders
        else:
            uncovered.append(p)
        report.append({"lat": p["lat"], "lng": p["lng"], "orders": orders, "covered": is_covered,
                       "nearest_store": nearest[1].name if nearest else None,
                       "distance_km": round(nearest[0], 2) if nearest else None})
    suggestion = None
    if uncovered:
        weight = sum(p.get("orders", 1) for p in uncovered)
        suggestion = {
            "lat": round(sum(p["lat"] * p.get("orders", 1) for p in uncovered) / weight, 5),
            "lng": round(sum(p["lng"] * p.get("orders", 1) for p in uncovered) / weight, 5),
            "orders_gained": weight,
        }
    return {
        "covered_order_share": round(covered_orders / total_orders, 3) if total_orders else None,
        "points": report,
        "suggested_site": suggestion,
    }
