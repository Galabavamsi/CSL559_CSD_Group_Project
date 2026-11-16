from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ...db import get_db
from . import service

router = APIRouter(tags=["dashboard"])


@router.get("/v1/stores/{store_id}/dashboard")
def dashboard(store_id: int, db: Session = Depends(get_db)):
    return service.store_dashboard(db, store_id)


@router.get("/v1/events")
def events(store_id: int | None = None, limit: int = 20, db: Session = Depends(get_db)):
    return service.recent_events(db, store_id, limit)
