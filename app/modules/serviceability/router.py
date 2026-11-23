from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ... import seed
from ...auth import require_role
from ...db import get_db
from ...idempotency import run_once
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


class OpenStoreIn(BaseModel):
    name: str = Field(min_length=3, max_length=80, pattern=r"\S")
    lat: float = Field(ge=-90, le=90, allow_inf_nan=False)
    lng: float = Field(ge=-180, le=180, allow_inf_nan=False)
    city: str | None = Field(default=None, max_length=40,
                             description="A city's slug. Left out: the city whose centre is nearest.")
    radius_km: float | None = Field(default=None, ge=0.5, le=10, allow_inf_nan=False,
                                    description="Left out: the city's radius for a new hub.")
    capacity_kg: int | None = Field(default=None, ge=100, le=100_000)


@router.post("/v1/admin/stores", status_code=201, summary="Open a hub at a site")
def open_store(body: OpenStoreIn,
               idempotency_key: Annotated[str | None, Header(min_length=1, max_length=80)] = None,
               db: Session = Depends(get_db), staff: dict = Depends(require_role("admin"))):
    """Creates the hub, its shelves and its delivery zone together, and the hub's four demo logins
    (`picker<id>`, `packer<id>`, `receiver<id>`, `manager<id>`). The hub starts with no stock. Every zone is
    recalculated: the new hub takes over the cells it is nearest to. The site must be inside a city
    (`422 outside_city`), not on top of another hub (`409 hub_too_close`), and its name must be new
    (`409 name_taken`)."""
    def action() -> dict:
        hub = service.open_store(db, body.name, body.lat, body.lng, body.city, body.radius_km, body.capacity_kg,
                                 actor=staff["sub"])
        return {**hub, "logins": seed.add_store_staff(db, hub["store_id"])}
    return run_once(db, "store-open", idempotency_key, body.model_dump(), action)


@router.get("/v1/stores")
def stores(city: str | None = Query(default=None, description="A city's slug, e.g. bhilai, to list only its hubs"),
           db: Session = Depends(get_db)):
    return service.list_stores(db, city)


@router.get("/v1/cities", summary="The cities the service runs in, with how many hubs each has")
def cities(db: Session = Depends(get_db)):
    return service.list_cities(db)
