from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ...db import get_db
from . import service

router = APIRouter(tags=["network planning"])


class DemandPoint(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)
    orders: int = Field(default=1, gt=0)


class CoverageIn(BaseModel):
    points: list[DemandPoint] = Field(min_length=1)


@router.post("/v1/network-planning/coverage")
def coverage(body: CoverageIn, db: Session = Depends(get_db)):
    return service.coverage(db, [p.model_dump() for p in body.points])
