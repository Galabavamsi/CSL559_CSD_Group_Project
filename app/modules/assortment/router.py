from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ...auth import check_store, current_staff, require_role
from ...db import get_db
from . import service

router = APIRouter(tags=["assortment"])


class AssortmentIn(BaseModel):
    sku_id: int
    reorder_point: int = 10
    target_stock: int = 40


@router.get("/v1/skus")
def skus(db: Session = Depends(get_db)):
    return service.catalogue(db)


@router.get("/v1/stores/{store_id}/assortment")
def assortment(store_id: int, db: Session = Depends(get_db),
               staff: dict = Depends(current_staff)):
    check_store(staff, store_id)
    return service.list_assortment(db, store_id)


@router.post("/v1/stores/{store_id}/assortment", status_code=201)
def add_to_assortment(store_id: int, body: AssortmentIn, db: Session = Depends(get_db),
                      staff: dict = Depends(require_role("manager"))):
    check_store(staff, store_id)
    return service.add_sku(db, store_id, body.sku_id, body.reorder_point, body.target_stock)
