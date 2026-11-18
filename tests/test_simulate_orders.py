"""The timing run (Member 2 guide, task 2.8): a short simulation through the real API, in-process."""
from fastapi.testclient import TestClient

from app.main import app
from scripts.simulate_orders import report, simulate

from .conftest import assert_stock_is_consistent


def test_scripted_pickers_clear_the_queue_and_the_stock_audit_holds(fresh_data):
    result = simulate(lambda: TestClient(app), orders=8, pickers=2, step=0, random_seed=1)

    assert result["orders"] == 8 and result["metrics"]["orders_packed"] == 8
    assert result["metrics"]["fill_rate"] == 1
    assert result["stock_problems"] == []
    assert_stock_is_consistent()
    text = report(result)
    assert "Order to packed (p90)" in text and "Stock audit: clean" in text
    rows = {line.split("  ")[0]: line for line in text.splitlines()}
    # Time-based KPIs are never marked as passing in compressed time; fill rate is judged.
    assert rows["Order to packed (p90)"].endswith("n/a (compressed time)")
    assert rows["Items per picker-hour"].endswith("n/a (compressed time)")
    assert rows["Fill rate"].endswith("yes")


def test_one_order_per_walk_takes_more_walks_than_batches(fresh_data):
    single = simulate(lambda: TestClient(app), orders=6, pickers=1, step=0, batch=False, random_seed=2)

    assert single["walks"] == 6 and single["metrics"]["orders_packed"] == 6


def test_a_broken_stock_record_is_reported(fresh_data, db, sku):
    from sqlalchemy import select

    from app.models import StockLevel
    from scripts.simulate_orders import stock_problems

    level = db.scalar(select(StockLevel).where(StockLevel.store_id == 1, StockLevel.sku_id == sku("Sugar")))
    level.qty_on_hand += 1                                    # on hand no longer matches the bins or the ledger
    db.commit()

    assert len(stock_problems()) == 1
