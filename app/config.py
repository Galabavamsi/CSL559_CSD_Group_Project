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

# Serviceability: delivery zones are H3 hexagon cells mapped to stores (HLD service 1).
# Resolution 9 cells have ~0.2 km edges (~0.1 km2), so a zone border is accurate to about 200 m and a
# 3 km zone is ~270 rows. Resolution 8 (~0.53 km edges) would need 7x fewer rows but blur borders by ~500 m.
H3_RESOLUTION = int(os.getenv("H3_RESOLUTION", "9"))
# A busy store serves only cells within this share of its radius (HLD 9.2: "the delivery radius shrinks").
BUSY_RADIUS_FACTOR = float(os.getenv("BUSY_RADIUS_FACTOR", "0.7"))

# Serviceability: simple ETA model = pack time + travel time (+ penalty when the store is busy).
PACK_MINUTES = 2
MINUTES_PER_KM = 3
BUSY_PENALTY_MINUTES = 5
