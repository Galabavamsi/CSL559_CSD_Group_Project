from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ...db import get_db
from . import service

router = APIRouter(tags=["serviceability"])


@router.get("/v1/serviceability")
def serviceability(lat: float = Query(ge=-90, le=90), lng: float = Query(ge=-180, le=180),
                   db: Session = Depends(get_db)):
    return service.check(db, lat, lng)


@router.get("/v1/stores")
def stores(db: Session = Depends(get_db)):
    return service.list_stores(db)
