"""Reset demo data on the shared hosted copy (DEMO_HISTORY_ON_RESET): the history the demo script adds by hand
(scripts/generate_sales.py, scripts/generate_demand.py) comes back with the demo data, so forecasts and the network
map are not empty after a visitor presses Reset."""
from sqlalchemy import func, select

from app import config
from app.models import ServiceabilityMiss, StockLedger, StockLevel


def skus_with_sales_and_misses(db) -> tuple[int, int]:
    skus = db.scalar(select(func.count(func.distinct(StockLedger.sku_id))).where(
        StockLedger.store_id == 1, StockLedger.reference == "history", StockLedger.reason == "sale"))
    return skus, db.scalar(select(func.count()).select_from(ServiceabilityMiss))


def test_a_plain_reset_keeps_the_small_seeded_history(fresh_data, db):
    assert skus_with_sales_and_misses(db) == (4, 0)      # one week for four SKUs, no delivery lookups


def test_on_the_hosted_copy_a_reset_also_writes_sales_history_and_delivery_lookups(client, db, monkeypatch):
    monkeypatch.setattr(config, "DEMO_HISTORY_ON_RESET", True)

    assert client.post("/v1/admin/reset").status_code == 200

    skus, misses = skus_with_sales_and_misses(db)
    carried = db.scalar(select(func.count()).select_from(StockLevel).where(StockLevel.store_id == 1))
    assert skus == carried and misses > 0
