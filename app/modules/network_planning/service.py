"""Network Planning Service (HLD service 10, FR-12): where should the next dark store go?

Demand is recorded by H3 cell, never as a name, phone number or exact location (HLD 10): a paid order
carries the cell of its delivery address, and a lookup no store could serve is saved as a miss.
`heatmap` counts both per cell; `suggest_sites` picks new sites that would serve the most turned-away
customers. `coverage` is the older check of demand points handed in by the caller.
"""
from datetime import timedelta

import h3
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ... import config
from ...models import Reservation, ServiceabilityMiss, Store, utcnow
from ..serviceability.service import distance_km

PAID = ("confirmed", "fulfilled")


def _per_cell(db: Session, cell_column, *conditions) -> dict[str, int]:
    return dict(db.execute(select(cell_column, func.count()).where(*conditions).group_by(cell_column)).all())


def _misses_per_cell(db: Session, days: int) -> dict[str, int]:
    return _per_cell(db, ServiceabilityMiss.h3_cell, ServiceabilityMiss.ts >= utcnow() - timedelta(days=days))


def heatmap(db: Session, days: int = 30) -> list[dict]:
    """Paid orders and misses per H3 cell over the last `days` days, with each cell's outline for a map."""
    since = utcnow() - timedelta(days=days)
    orders = _per_cell(db, Reservation.h3_cell, Reservation.h3_cell.is_not(None),
                       Reservation.status.in_(PAID), Reservation.created_at >= since)
    misses = _misses_per_cell(db, days)
    rows = []
    for cell in sorted(orders.keys() | misses.keys()):
        lat, lng = h3.cell_to_latlng(cell)
        rows.append({"h3_cell": cell, "lat": round(lat, 6), "lng": round(lng, 6),
                     "boundary": [[round(a, 6), round(b, 6)] for a, b in h3.cell_to_boundary(cell)],
                     "orders": orders.get(cell, 0), "misses": misses.get(cell, 0)})
    return rows


def suggest_sites(db: Session, k: int = 3, days: int = 30) -> list[dict]:
    """Up to `k` new store sites by greedy maximum coverage of unmet demand (misses in the last `days` days).

    Candidates are the cells with misses, except NO_GO_CELLS. Each round picks the candidate whose radius
    covers the most demand still unmet (ties go to the most central one), then removes that demand. Stops
    early when no candidate would gain anything, so it may return fewer than `k` sites.
    """
    unmet = _misses_per_cell(db, days)
    centre = {cell: h3.cell_to_latlng(cell) for cell in unmet}
    candidates = sorted(centre.keys() - set(config.NO_GO_CELLS))
    radius = config.NEW_SITE_RADIUS_KM
    sites = []
    # shortcut: compares every candidate with every demand cell, cells^2 per round; fine for a few thousand
    # cells, beyond that look up only the cells in h3.grid_disk around each candidate.
    for _ in range(k):
        best_key, best = None, None
        for site in candidates:
            reach = {cell: distance_km(*centre[site], *centre[cell]) for cell in unmet}
            covered = [cell for cell, km in reach.items() if km <= radius]
            gain = sum(unmet[cell] for cell in covered)
            spread = sum(unmet[cell] * reach[cell] for cell in covered)
            if gain and (best_key is None or (gain, -spread) > best_key):
                best_key, best = (gain, -spread), (site, covered)
        if best is None:
            break
        site, covered = best
        lat, lng = centre[site]
        sites.append({"h3_cell": site, "lat": round(lat, 6), "lng": round(lng, 6), "radius_km": radius,
                      "demand_gained": best_key[0]})
        for cell in covered:
            del unmet[cell]
    return sites


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
