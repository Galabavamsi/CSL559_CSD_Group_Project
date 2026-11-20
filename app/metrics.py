"""Prometheus metrics (HLD 12, technical monitoring), served at GET /metrics by app/monitoring.py.

Nothing from the app is imported here, so any module can count something without an import cycle.
"""
from prometheus_client import Counter, Gauge, Histogram

REQUEST_SECONDS = Histogram("http_request_duration_seconds", "Time to answer an HTTP request",
                            ["method", "route", "status"])
RESERVATIONS = Counter("reservations", "Checkout holds asked for, by result", ["result"])
EVENTS_PUBLISHED = Counter("events_published", "Events written to the outbox, by type", ["type"])
SCANS = Counter("scans", "Barcode scans at the shelf, by result", ["result"])
ATP_CACHE = Counter("atp_cache_lookups", "Whole-store availability lookups, by hit or miss (HLD 9.2)", ["result"])
HOLDS_IN_PROGRESS = Gauge("holds_in_progress", "Reservations held and not yet paid, released or expired")
OUTBOX_LAG = Gauge("outbox_lag_seconds", "Age of the oldest event the relay has not sent; HLD 12 alerts above 30 s")
STORE_SILENCE = Gauge("store_seconds_since_last_event", "Time since a store last published anything; a store "
                      "that goes quiet in opening hours may be offline", ["store_id"])
