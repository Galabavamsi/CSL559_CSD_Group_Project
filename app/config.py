"""All tunable settings in one place. Override any of them with environment variables."""
import os

# Database. SQLite keeps local runs zero-setup; set DARKSTORE_DB to a PostgreSQL URL for the HLD's database
# (task 1.7), e.g. postgresql://darkstore:darkstore@localhost:5432/darkstore. Sharding by store_id is design only.


def _database_url(url: str) -> str:
    """Hosted databases hand out postgres://... or postgresql://... URLs, which SQLAlchemy would open with a driver
    this project does not install. Point them at psycopg 3, the one in requirements.txt."""
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url


DATABASE_URL = _database_url(os.getenv("DARKSTORE_DB", "sqlite:///./darkstore.db"))
# Database connections kept open per app process, and how many more may be opened in a burst.
# Keep the sum at 40 or more: the web server answers up to 40 requests at once, each on its own thread and each
# with one connection. With fewer connections than threads, threads wait for a connection while the finished
# requests that would give one back wait for a thread, and everything stalls for 30 s (seen with 200 buyers at once
# in scripts/load_checkout.py). On PostgreSQL also keep the sum x app processes below max_connections (100 by
# default, fewer on the smallest hosted instances).
DB_POOL_SIZE = int(os.getenv("DB_POOL_SIZE", "10"))
DB_POOL_OVERFLOW = int(os.getenv("DB_POOL_OVERFLOW", "40"))

# Login (HLD 10). The default secret is fake and public: always set JWT_SECRET outside local development.
DEFAULT_JWT_SECRET = "dev-only-change-me-not-a-real-secret"
JWT_SECRET = os.getenv("JWT_SECRET", DEFAULT_JWT_SECRET)
TOKEN_MINUTES = int(os.getenv("TOKEN_MINUTES", "30"))
# Password of every seeded demo account (picker1, manager1, admin, ...). The demo screens log in with it.
DEMO_PASSWORD = os.getenv("DEMO_PASSWORD", "demo")
# The shared hosted copy: Reset demo data also writes the 60-day sales history and the delivery lookups that the demo
# script otherwise adds by hand (scripts/generate_sales.py, generate_demand.py). Off by default, so the tests and a
# laptop demo start from the plain seed.
DEMO_HISTORY_ON_RESET = os.getenv("DEMO_HISTORY_ON_RESET", "off") == "on"

# Inventory: how long a checkout hold lasts before the sweeper releases it (HLD 9.1).
RESERVATION_TTL_MINUTES = int(os.getenv("RESERVATION_TTL_MINUTES", "10"))
# The sweeper runs this often (app/background.py). BACKGROUND_JOBS=off stops every timed job (the tests do).
SWEEP_INTERVAL_SECONDS = float(os.getenv("SWEEP_INTERVAL_SECONDS", "30"))
BACKGROUND_JOBS = os.getenv("BACKGROUND_JOBS", "on") == "on"
# ATP cache (HLD 9.2): a store's availability list is reused for this many seconds. 0 turns the cache off.
# Holds never read it, so a stale copy can only cause a failed hold, never an oversell (see app/cache.py).
ATP_CACHE_SECONDS = float(os.getenv("ATP_CACHE_SECONDS", "2"))
# Cycle counts (FR-11, HLD 10): a count whose differences are worth at most this much (|counted - system| x price,
# summed) is applied at once; a bigger one waits for a manager.
COUNT_AUTO_APPROVE_VALUE = float(os.getenv("COUNT_AUTO_APPROVE_VALUE", "500"))
# Expiry (FR-10): expired batches are written off this often, and batches expiring within NEAR_EXPIRY_DAYS are
# flagged with an item.near_expiry event, at most once per batch per day.
EXPIRY_INTERVAL_SECONDS = float(os.getenv("EXPIRY_INTERVAL_SECONDS", "3600"))
NEAR_EXPIRY_DAYS = int(os.getenv("NEAR_EXPIRY_DAYS", "2"))

# Replenishment / forecasting (HLD 6.2). The prototype works in days, the HLD in hours.
LEAD_TIME_DAYS = float(os.getenv("LEAD_TIME_DAYS", "1"))        # hub -> store delivery time
SERVICE_LEVEL_Z = float(os.getenv("SERVICE_LEVEL_Z", "1.65"))   # 1.65 = 95% service level
COVER_DAYS = float(os.getenv("COVER_DAYS", "3"))                # days of stock to hold above the reorder point
# Replenishment runs by itself this often for every open store (app/background.py); 0 or less switches it off.
REPLENISHMENT_INTERVAL_MINUTES = float(os.getenv("REPLENISHMENT_INTERVAL_MINUTES", "15"))
# Receiving (HLD 6.3): a batch arriving with less than this share of its shelf life left is refused at the dock.
MIN_REMAINING_SHELF_LIFE = float(os.getenv("MIN_REMAINING_SHELF_LIFE", "0.5"))
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
# An order being picked with no claim, scan or shelf report for this many minutes is stalled (task 2.5). If nothing
# is in its tote yet it goes back to the queue for another picker; otherwise it is listed for a person to sort out.
PICK_STALL_MINUTES = float(os.getenv("PICK_STALL_MINUTES", "5"))
STALL_CHECK_SECONDS = float(os.getenv("STALL_CHECK_SECONDS", "60"))    # how often the background job looks
# A packed bag waiting longer than this for a rider is listed as needing attention (task 2.5).
RIDER_WAIT_MINUTES = float(os.getenv("RIDER_WAIT_MINUTES", "5"))
# Batch picking at peak (HLD 13.1, task 2.6): with at least BATCH_PICK_BACKLOG orders waiting, a picker takes up to
# BATCH_SIZE of them in one walk, one tote each; with fewer, one order at a time, so nobody waits for a batch to fill.
BATCH_PICK_BACKLOG = int(os.getenv("BATCH_PICK_BACKLOG", "4"))
BATCH_SIZE = int(os.getenv("BATCH_SIZE", "3"))
if not 1 <= BATCH_SIZE <= 26:      # 0 would claim nothing while orders wait; past 26 there are no tote letters left
    raise ValueError("BATCH_SIZE must be 1 to 26: one tote per order, lettered A to Z")

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
