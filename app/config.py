"""All tunable settings in one place. Override any of them with environment variables."""
import os

# Database. SQLite keeps the prototype zero-setup; the HLD target is PostgreSQL sharded by store_id.
DATABASE_URL = os.getenv("DARKSTORE_DB", "sqlite:///./darkstore.db")

# Login (HLD 10). The default secret is fake and public: always set JWT_SECRET outside local development.
DEFAULT_JWT_SECRET = "dev-only-change-me-not-a-real-secret"
JWT_SECRET = os.getenv("JWT_SECRET", DEFAULT_JWT_SECRET)
TOKEN_MINUTES = int(os.getenv("TOKEN_MINUTES", "30"))
# Password of every seeded demo account (picker1, manager1, admin, ...). The demo screens log in with it.
DEMO_PASSWORD = os.getenv("DEMO_PASSWORD", "demo")

# Inventory: how long a checkout hold lasts before the sweeper releases it (HLD 9.1).
RESERVATION_TTL_MINUTES = int(os.getenv("RESERVATION_TTL_MINUTES", "10"))
# The sweeper runs this often (app/background.py). BACKGROUND_JOBS=off stops every timed job (the tests do).
SWEEP_INTERVAL_SECONDS = float(os.getenv("SWEEP_INTERVAL_SECONDS", "30"))
BACKGROUND_JOBS = os.getenv("BACKGROUND_JOBS", "on") == "on"
# Expiry (FR-10): expired batches are written off this often, and batches expiring within NEAR_EXPIRY_DAYS are
# flagged with an item.near_expiry event, at most once per batch per day.
EXPIRY_INTERVAL_SECONDS = float(os.getenv("EXPIRY_INTERVAL_SECONDS", "3600"))
NEAR_EXPIRY_DAYS = int(os.getenv("NEAR_EXPIRY_DAYS", "2"))

# Replenishment / forecasting (HLD 6.2). The prototype works in days, the HLD in hours.
LEAD_TIME_DAYS = float(os.getenv("LEAD_TIME_DAYS", "1"))        # hub -> store delivery time
SERVICE_LEVEL_Z = float(os.getenv("SERVICE_LEVEL_Z", "1.65"))   # 1.65 = 95% service level
COVER_DAYS = float(os.getenv("COVER_DAYS", "3"))                # days of stock to hold above the reorder point
# Forecasting model used by `run`: moving_average | weekday_average | exp_smoothing. The weekday average won the
# task 3.3 comparison on generated sales (GET /v1/forecasting/compare).
FORECAST_MODEL = os.getenv("FORECAST_MODEL", "weekday_average")
FORECAST_WINDOW_DAYS = int(os.getenv("FORECAST_WINDOW_DAYS", "7"))    # days the moving_average model looks back
# Recent days replayed to measure forecast errors: the backtest's default, and the errors that size safety stock.
FORECAST_TEST_DAYS = int(os.getenv("FORECAST_TEST_DAYS", "14"))

# Supply KPIs (HLD 12). Wastage and on-time deliveries look back this many days.
KPI_WINDOW_DAYS = int(os.getenv("KPI_WINDOW_DAYS", "30"))
# A SKU whose shelf life is at most this many days counts as fresh: its days-of-cover target is 1-2 days, not 3-5.
FRESH_SHELF_LIFE_DAYS = int(os.getenv("FRESH_SHELF_LIFE_DAYS", "7"))

# Fulfilment: a store with more than this many unpacked orders is marked "busy" (HLD 9.2).
BUSY_BACKLOG_THRESHOLD = int(os.getenv("BUSY_BACKLOG_THRESHOLD", "5"))

# Live event feed (HLD 8.2): the relay sends new events to the sinks this often, at most this many per pass.
RELAY_INTERVAL_SECONDS = float(os.getenv("RELAY_INTERVAL_SECONDS", "0.2"))
RELAY_BATCH_SIZE = int(os.getenv("RELAY_BATCH_SIZE", "100"))
# An open WebSocket gets a ping this often, so a viewer that has gone away is noticed and dropped.
LIVE_PING_SECONDS = float(os.getenv("LIVE_PING_SECONDS", "20"))

# Monitoring (HLD 12): when set, GET /metrics answers only 'Authorization: Bearer <METRICS_TOKEN>'. Leave it empty
# for local development; set it anywhere /metrics is reachable from outside.
METRICS_TOKEN = os.getenv("METRICS_TOKEN", "")
# Rate limit on the endpoints anyone may call (HLD 5): calls a second per client, and the burst allowed.
# 0 turns it off; the load test needs that, since it is one client sending hundreds of calls a second.
RATE_LIMIT_PER_SECOND = float(os.getenv("RATE_LIMIT_PER_SECOND", "20"))
RATE_LIMIT_BURST = int(os.getenv("RATE_LIMIT_BURST", "40"))
if not RATE_LIMIT_PER_SECOND >= 0 or RATE_LIMIT_BURST < 1:    # "not >=" also catches nan
    raise ValueError("RATE_LIMIT_PER_SECOND must be 0 (off) or more, and RATE_LIMIT_BURST at least 1")

# Serviceability: delivery zones are H3 hexagon cells mapped to stores (HLD service 1).
# Resolution 9 cells have ~0.2 km edges (~0.1 km2), so a zone border is accurate to about 200 m and a
# 3 km zone is ~270 rows. Resolution 8 (~0.53 km edges) would need 7x fewer rows but blur borders by ~500 m.
H3_RESOLUTION = int(os.getenv("H3_RESOLUTION", "9"))
# A busy store serves only cells within this share of its radius (HLD 9.2: "the delivery radius shrinks").
BUSY_RADIUS_FACTOR = float(os.getenv("BUSY_RADIUS_FACTOR", "0.7"))

# Network planning (FR-12): a suggested new store would serve this radius, like the seeded stores.
NEW_SITE_RADIUS_KM = float(os.getenv("NEW_SITE_RADIUS_KM", "3.0"))
# H3 cells where no store may open, comma-separated. Stands in for the zoning check in HLD 13.2.
NO_GO_CELLS = [cell.strip() for cell in os.getenv("NO_GO_CELLS", "").split(",") if cell.strip()]

# Serviceability: simple ETA model = pack time + travel time (+ penalty when the store is busy).
PACK_MINUTES = 2
MINUTES_PER_KM = 3
BUSY_PENALTY_MINUTES = 5
