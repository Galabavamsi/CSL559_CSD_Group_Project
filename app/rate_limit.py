"""Rate limit on the open customer endpoints (HLD 5: the last gateway duty in the prototype).

Each client, by IP address, may call the endpoints that need no login about RATE_LIMIT_PER_SECOND times a second,
with bursts up to RATE_LIMIT_BURST: a token bucket. Beyond that it gets 429 and a Retry-After header. Staff
endpoints, the demo pages, /health and /metrics are not limited. RATE_LIMIT_PER_SECOND=0 turns the limit off.

shortcut: the buckets live in this process, keyed by the address the connection came from. With several workers,
several copies or a proxy in front, move the limit to the gateway or a shared store (Redis), and take the client's
address from the proxy's X-Forwarded-For. Until then: behind a proxy, or on a Unix socket (no client address),
everyone shares one bucket; a client rotating many addresses (an IPv6 /64) gets a fresh bucket for each, so key
IPv6 on its /64; and 429s show in the metrics under route "other", since they are answered before routing.
"""
import math
import re
import time

from fastapi import Request
from fastapi.responses import JSONResponse

from . import config

# Login, serviceability, the store list, availability, the catalogue and checkout: every route that needs no login,
# except /health and /metrics.
OPEN_PATHS = re.compile(r"/v1/(auth/login|serviceability|stores|skus|stores/[^/]+/availability|reservations(/[^/]+)*)")
MAX_CLIENTS = 10_000
# client -> (tokens left, when they were counted). Kept in the order clients were last seen, oldest first.
_buckets: dict[str, tuple[float, float]] = {}


def wait_for(client: str, now: float) -> float:
    """Take a token from the client's bucket. Returns 0 if the call may go ahead, otherwise the seconds until it may.
    At MAX_CLIENTS the client seen longest ago is forgotten (it starts again with a full bucket), so memory is
    bounded and no call has to scan the table."""
    rate, burst = config.RATE_LIMIT_PER_SECOND, config.RATE_LIMIT_BURST
    tokens, counted = _buckets.pop(client, (burst, now))    # put back below, at the end: the most recently seen
    tokens = min(burst, tokens + (now - counted) * rate)
    if len(_buckets) >= MAX_CLIENTS:
        del _buckets[next(iter(_buckets))]
    if tokens < 1:
        _buckets[client] = (tokens, now)
        return (1 - tokens) / rate
    _buckets[client] = (tokens - 1, now)
    return 0.0


async def limit(request: Request, call_next):
    """HTTP middleware: 429 for a client over its rate on an open endpoint; every other call passes straight on."""
    if config.RATE_LIMIT_PER_SECOND <= 0 or not OPEN_PATHS.fullmatch(request.url.path):
        return await call_next(request)
    wait = wait_for(request.client.host if request.client else "unknown", time.monotonic())
    if wait > 0:
        return JSONResponse(status_code=429, headers={"Retry-After": str(math.ceil(wait))},
                            content={"error": {"code": "rate_limited", "details": {},
                                               "message": "Too many requests from this address; try again shortly"}})
    return await call_next(request)
