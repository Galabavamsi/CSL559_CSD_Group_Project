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


@router.get("/v1/stores/{store_id}/assortment/recommendations",
            summary="What to add, what to drop, and the shelf room left in each zone")
def recommendations(store_id: int, db: Session = Depends(get_db), staff: dict = Depends(current_staff)):
    check_store(staff, store_id)
    return service.recommendations(db, store_id)


@router.delete("/v1/stores/{store_id}/assortment/{sku_id}",
               summary="Stop carrying a SKU: only with nothing on the shelf, held or on its way")
def drop_from_assortment(store_id: int, sku_id: int, db: Session = Depends(get_db),
                         staff: dict = Depends(require_role("manager"))):
    check_store(staff, store_id)
    return service.drop_sku(db, store_id, sku_id)
