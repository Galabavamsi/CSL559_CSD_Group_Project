from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ...db import get_db
from . import service

router = APIRouter(tags=["replenishment"])


@router.post("/v1/replenishment/run")
def run(store_id: int, db: Session = Depends(get_db)):
    order = service.run(db, store_id)
    return {"transfer_order": service.order_view(order) if order else None}


@router.get("/v1/transfer-orders")
def list_orders(store_id: int, db: Session = Depends(get_db)):
    return [service.order_view(o) for o in service.list_orders(db, store_id)]


@router.post("/v1/transfer-orders/{transfer_order_id}/dispatch")
def dispatch(transfer_order_id: int, db: Session = Depends(get_db)):
    return service.order_view(service.dispatch(db, transfer_order_id))
