from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ...auth import require_role
from ...db import get_db
from . import service

router = APIRouter(tags=["network planning"])


class DemandPoint(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)
    orders: int = Field(default=1, gt=0)


class CoverageIn(BaseModel):
    points: list[DemandPoint] = Field(min_length=1)


@router.post("/v1/network-planning/coverage", dependencies=[Depends(require_role("ops"))])
def coverage(body: CoverageIn, db: Session = Depends(get_db)):
    return service.coverage(db, [p.model_dump() for p in body.points])


@router.get("/v1/network-planning/heatmap", dependencies=[Depends(require_role("ops"))],
            summary="Paid orders and turned-away lookups per H3 cell")
def heatmap(days: int = Query(30, ge=1, le=365), db: Session = Depends(get_db)):
    return service.heatmap(db, days)


@router.get("/v1/network-planning/suggestions", dependencies=[Depends(require_role("ops"))],
            summary="Where new stores would serve the most turned-away customers")
def suggestions(k: int = Query(3, ge=1, le=10), days: int = Query(30, ge=1, le=365),
                db: Session = Depends(get_db)):
    return service.suggest_sites(db, k, days)
