from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ...auth import check_store, current_staff, require_role
from ...db import get_db
from . import service

router = APIRouter(tags=["forecasting"])


@router.post("/v1/forecasting/run")
def run(store_id: int, window_days: int | None = None, db: Session = Depends(get_db),
        staff: dict = Depends(require_role("manager"))):
    check_store(staff, store_id)
    return service.run(db, store_id, window_days)


@router.get("/v1/forecasts")
def forecasts(store_id: int, db: Session = Depends(get_db),
              staff: dict = Depends(current_staff)):
    check_store(staff, store_id)
    return service.list_forecasts(db, store_id)
