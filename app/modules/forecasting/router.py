from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ...db import get_db
from . import service

router = APIRouter(tags=["forecasting"])


@router.post("/v1/forecasting/run")
def run(store_id: int, window_days: int | None = None, db: Session = Depends(get_db)):
    return service.run(db, store_id, window_days)


@router.get("/v1/forecasts")
def forecasts(store_id: int, db: Session = Depends(get_db)):
    return service.list_forecasts(db, store_id)
