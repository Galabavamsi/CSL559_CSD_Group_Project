"""All tunable settings in one place. Override any of them with environment variables."""
import os

# Database. SQLite keeps the prototype zero-setup; the HLD target is PostgreSQL sharded by store_id.
DATABASE_URL = os.getenv("DARKSTORE_DB", "sqlite:///./darkstore.db")

# Inventory: how long a checkout hold lasts before the sweeper releases it (HLD 9.1).
RESERVATION_TTL_MINUTES = int(os.getenv("RESERVATION_TTL_MINUTES", "10"))

# Replenishment / forecasting (HLD 6.2). The prototype works in days, the HLD in hours.
LEAD_TIME_DAYS = float(os.getenv("LEAD_TIME_DAYS", "1"))        # hub -> store delivery time
SERVICE_LEVEL_Z = float(os.getenv("SERVICE_LEVEL_Z", "1.65"))   # 1.65 = 95% service level
COVER_DAYS = float(os.getenv("COVER_DAYS", "3"))                # days of stock to hold above the reorder point
FORECAST_WINDOW_DAYS = int(os.getenv("FORECAST_WINDOW_DAYS", "7"))

# Fulfilment: a store with more than this many unpacked orders is marked "busy" (HLD 9.2).
BUSY_BACKLOG_THRESHOLD = int(os.getenv("BUSY_BACKLOG_THRESHOLD", "5"))

# Serviceability: simple ETA model = pack time + travel time (+ penalty when the store is busy).
PACK_MINUTES = 2
MINUTES_PER_KM = 3
BUSY_PENALTY_MINUTES = 5
