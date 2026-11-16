"""Sales history (guide task 3.1)."""
from sqlalchemy import delete

from app.models import StockLedger

from .conftest import assert_stock_is_consistent


def test_seed_history_rows_balance_on_their_own(db):
    db.execute(delete(StockLedger).where(StockLedger.reference == "history"))
    db.commit()
    assert_stock_is_consistent()
