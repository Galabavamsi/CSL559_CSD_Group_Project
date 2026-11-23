from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ...auth import require_role
from ...db import get_db
from . import service

router = APIRouter(tags=["serviceability"])


@router.get("/v1/serviceability")
def serviceability(lat: float = Query(ge=-90, le=90), lng: float = Query(ge=-180, le=180),
                   db: Session = Depends(get_db)):
    return service.check(db, lat, lng)


@router.post("/v1/admin/rebuild-zones", summary="Recalculate which store serves each H3 cell",
             dependencies=[Depends(require_role("admin"))])
def rebuild_zones(db: Session = Depends(get_db)):
    """Run this after adding a store or changing a store's location or radius."""
    return {"cells": service.rebuild_zones(db)}


@router.get("/v1/stores")
def stores(city: str | None = Query(default=None, description="A city's slug, e.g. bhilai, to list only its hubs"),
           db: Session = Depends(get_db)):
    return service.list_stores(db, city)


@router.get("/v1/cities", summary="The cities the service runs in, with how many hubs each has")
def cities(db: Session = Depends(get_db)):
    return service.list_cities(db)
