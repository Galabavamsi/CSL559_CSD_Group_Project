from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ... import config
from ...auth import check_store, current_staff, require_role
from ...db import get_db
from ...ids import MAX_ID
from . import service

router = APIRouter(tags=["forecasting"])


@router.post("/v1/forecasting/run", summary="Recalculate forecasts and reorder points with the model in use")
def run(store_id: int = Query(ge=1, le=MAX_ID), db: Session = Depends(get_db),
        staff: dict = Depends(require_role("manager"))):
    check_store(staff, store_id)
    return service.run(db, store_id)


@router.get("/v1/forecasts")
def forecasts(store_id: int = Query(ge=1, le=MAX_ID), db: Session = Depends(get_db),
              staff: dict = Depends(current_staff)):
    check_store(staff, store_id)
    return service.list_forecasts(db, store_id)


@router.get("/v1/forecasting/backtest", summary="Measure forecast accuracy (WAPE) on recent days")
def backtest(store_id: int = Query(ge=1, le=MAX_ID),
             test_days: int = Query(config.FORECAST_TEST_DAYS, ge=1, le=90),
             model: str | None = Query(None, description="moving_average, weekday_average or exp_smoothing; "
                                                          "default: the model in use (FORECAST_MODEL)"),
             db: Session = Depends(get_db), staff: dict = Depends(current_staff)):
    """Replay the last `test_days` days with one model and report WAPE for the store and per SKU. HLD 12 target:
    30% or lower. The demo data has one week of sales: run `python scripts/generate_sales.py` first."""
    check_store(staff, store_id)
    return service.backtest(db, store_id, test_days, model)


@router.get("/v1/forecasting/compare", summary="Compare the forecast models by WAPE")
def compare(store_id: int = Query(ge=1, le=MAX_ID),
            test_days: int = Query(config.FORECAST_TEST_DAYS, ge=1, le=90),
            db: Session = Depends(get_db), staff: dict = Depends(current_staff)):
    """Backtest every model over the same days: the WAPE of each, the best one, and the one in use."""
    check_store(staff, store_id)
    return service.compare_models(db, store_id, test_days)
