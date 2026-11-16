from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ...auth import check_store, current_staff
from ...db import get_db
from . import service

router = APIRouter(tags=["slotting"])


@router.get("/v1/stores/{store_id}/bins")
def bins(store_id: int, db: Session = Depends(get_db),
         staff: dict = Depends(current_staff)):
    check_store(staff, store_id)
    return service.list_bins(db, store_id)


@router.get("/v1/slotting/suggest")
def suggest(store_id: int, sku_id: int, db: Session = Depends(get_db),
            staff: dict = Depends(current_staff)):
    check_store(staff, store_id)
    b = service.suggest_bin(db, store_id, sku_id)
    return {"bin_id": b.id, "code": b.code, "zone": b.zone}
