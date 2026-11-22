"""Generate clustered delivery lookups for the network-planning demo (Member 4 guide, task 4.4).

Each cluster is a crowd of customers checking whether a store delivers to them, scattered around a centre.
A lookup inside a zone is served and leaves no trace; a lookup no store serves is saved as a miss, which is
what GET /v1/network-planning/suggestions works from. Two clusters sit outside every zone, so the map has
gaps to find: a big one that should become the first suggestion and a smaller one for the second.

Run it from the repository root (it uses the app's database, DARKSTORE_DB):

    python scripts/generate_demand.py [--seed 7]
"""
import argparse
import math
import random
import sys
from pathlib import Path

if __package__ in (None, ""):          # run as a file: make `import app` work
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy.orm import Session  # noqa: E402

from app.db import SessionLocal, init_db  # noqa: E402
from app.modules.serviceability import service as serviceability  # noqa: E402
from app.seed import seed_if_empty  # noqa: E402

KM_PER_DEGREE_LAT = 111.32
CLUSTERS = [
    {"name": "Around DS-01 Central", "lat": 12.975, "lng": 77.600, "spread_km": 1.0, "lookups": 60},
    {"name": "Around DS-02 North", "lat": 13.030, "lng": 77.596, "spread_km": 1.0, "lookups": 40},
    {"name": "South-east, no store", "lat": 12.905, "lng": 77.650, "spread_km": 0.6, "lookups": 50},
    {"name": "West, no store", "lat": 12.960, "lng": 77.500, "spread_km": 0.6, "lookups": 15},
]


def look_up(db: Session, clusters: list[dict], seed: int = 7) -> dict:
    """Check serviceability for `lookups` points scattered `spread_km` (one standard deviation) around each
    cluster centre. Returns how many lookups were made and how many no store could serve."""
    rng = random.Random(seed)
    lookups = misses = 0
    for cluster in clusters:
        km_per_degree_lng = KM_PER_DEGREE_LAT * math.cos(math.radians(cluster["lat"]))
        for _ in range(cluster["lookups"]):
            lat = cluster["lat"] + rng.gauss(0, cluster["spread_km"]) / KM_PER_DEGREE_LAT
            lng = cluster["lng"] + rng.gauss(0, cluster["spread_km"]) / km_per_degree_lng
            lookups += 1
            misses += not serviceability.check(db, lat, lng)["serviceable"]
    return {"lookups": lookups, "misses": misses}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Write clustered delivery lookups into the demo database.")
    parser.add_argument("--seed", type=int, default=7, help="random seed (default: 7)")
    args = parser.parse_args(argv)
    init_db()
    with SessionLocal() as db:
        seed_if_empty(db)
        result = look_up(db, CLUSTERS, args.seed)
    print(f"{result['lookups']} lookups, {result['misses']} could not be served and were saved as misses. "
          "Open /network.html to see them.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
