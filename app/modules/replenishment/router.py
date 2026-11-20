from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ...auth import check_store, current_staff, require_role
from ...db import get_db
from . import service

router = APIRouter(tags=["replenishment"])


class ReorderSettingsIn(BaseModel):
    reorder_stopped: bool


@router.post("/v1/replenishment/run")
def run(store_id: int, db: Session = Depends(get_db),
        staff: dict = Depends(require_role("manager"))):
    check_store(staff, store_id)
    result = service.run(db, store_id)
    order = result["transfer_order"]
    return {"transfer_order": service.order_view(order) if order else None, "capped": result["capped"]}


@router.put("/v1/stores/{store_id}/reorder-settings/{sku_id}",
            summary="Stop or restart reordering one SKU in one store, e.g. before dropping it")
def update_reorder_settings(store_id: int, sku_id: int, body: ReorderSettingsIn, db: Session = Depends(get_db),
                            staff: dict = Depends(require_role("manager"))):
    """While stopped, neither the timer nor Run replenishment orders it and it raises no low-stock alert; units
    already on their way still arrive. Send reorder_stopped false to restart."""
    check_store(staff, store_id)
    return service.set_reorder_stopped(db, store_id, sku_id, body.reorder_stopped)


@router.get("/v1/transfer-orders")
def list_orders(store_id: int, db: Session = Depends(get_db),
                staff: dict = Depends(current_staff)):
    check_store(staff, store_id)
    return [service.order_view(o) for o in service.list_orders(db, store_id)]


@router.post("/v1/transfer-orders/{transfer_order_id}/dispatch")
def dispatch(transfer_order_id: int, db: Session = Depends(get_db),
             staff: dict = Depends(require_role("manager"))):
    check_store(staff, service.get_order(db, transfer_order_id).store_id)
    return service.order_view(service.dispatch(db, transfer_order_id))


@router.get("/v1/stores/{store_id}/supply-kpis", summary="The five supply KPIs of HLD 12 against their targets")
def supply_kpis(store_id: int, db: Session = Depends(get_db), staff: dict = Depends(current_staff)):
    """Stock-out rate, days of cover, wastage rate, on-time replenishment and forecast WAPE. Each has a value
    (a fraction), its HLD target and `met`; both are null when there is nothing to measure yet."""
    check_store(staff, store_id)
    return service.kpis(db, store_id)
