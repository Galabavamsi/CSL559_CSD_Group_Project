from typing import Annotated

from fastapi import APIRouter, Depends, Path
from sqlalchemy.orm import Session

from ...db import get_db
from . import service

router = APIRouter(tags=["catalogue"])


@router.get("/v1/stores/{store_id}/shop", summary="What a customer sees at this hub")
def shop(store_id: Annotated[int, Path(ge=1, le=2_147_483_647)], db: Session = Depends(get_db)):
    """The hub's availability with what a customer is told about each pack: the use-by date of the batch the next
    order would be picked from and, for a farm lot, its grade, harvest date and farm. `rescue` appears when units
    in their last day can be bought: the lower price, and how many units it applies to. Open, like availability."""
    return service.shop(db, store_id)
