from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.orm import Session

from ...auth import check_store, current_staff, require_role
from ...db import get_db
from ...ids import MAX_ID, PathId
from ..inventory.router import MAX_BIN_UNITS
from . import service

router = APIRouter(tags=["replenishment"])


class ReorderSettingsIn(BaseModel):
    """Send one setting or both; one left out keeps its value."""
    model_config = ConfigDict(extra="forbid")      # a field this route does not change is a 422, never ignored
    reorder_stopped: bool | None = None
    # The limits of adding a SKU (issue #63); the service also keeps it below the SKU's target stock.
    reorder_point: int | None = Field(None, ge=1, le=MAX_BIN_UNITS, description="Reorder when stock falls below this")

    @model_validator(mode="after")
    def _something_to_change(self):
        """An empty body was a 422 while reorder_stopped was required, and stays one: a 200 that changes nothing
        would hide a missing or misspelt field."""
        if self.reorder_stopped is None and self.reorder_point is None:
            raise ValueError("send reorder_stopped, reorder_point or both")
        return self


@router.post("/v1/replenishment/run")
def run(store_id: int = Query(ge=1, le=MAX_ID), db: Session = Depends(get_db),
        staff: dict = Depends(require_role("manager"))):
    check_store(staff, store_id)
    result = service.run(db, store_id)
    order = result["transfer_order"]
    return {"transfer_order": service.order_view(order) if order else None, "capped": result["capped"]}


@router.put("/v1/stores/{store_id}/reorder-settings/{sku_id}",
            summary="Stop or restart reordering one SKU in one store, or change its reorder point")
def update_reorder_settings(store_id: PathId, sku_id: PathId, body: ReorderSettingsIn, db: Session = Depends(get_db),
                            staff: dict = Depends(require_role("manager"))):
    """Send reorder_stopped, reorder_point or both; a setting left out keeps its value.

    While stopped, neither the timer nor Run replenishment orders it and it raises no low-stock alert; units
    already on their way still arrive. Send reorder_stopped false to restart.

    reorder_point has the limits it has when the SKU is added: at least 1, and below the SKU's target stock
    (422 bad_reorder_point). Running the forecast sets it again for a SKU that sells."""
    check_store(staff, store_id)
    return service.update_reorder_settings(db, store_id, sku_id, reorder_stopped=body.reorder_stopped,
                                           reorder_point=body.reorder_point)


@router.get("/v1/transfer-orders")
def list_orders(store_id: int = Query(ge=1, le=MAX_ID), db: Session = Depends(get_db),
                staff: dict = Depends(current_staff)):
    check_store(staff, store_id)
    return [service.order_view(o) for o in service.list_orders(db, store_id)]


@router.post("/v1/transfer-orders/{transfer_order_id}/dispatch")
def dispatch(transfer_order_id: PathId, db: Session = Depends(get_db),
             staff: dict = Depends(require_role("manager"))):
    check_store(staff, service.get_order(db, transfer_order_id).store_id)
    return service.order_view(service.dispatch(db, transfer_order_id))


@router.get("/v1/stores/{store_id}/supply-kpis", summary="The five supply KPIs of HLD 12 against their targets")
def supply_kpis(store_id: PathId, db: Session = Depends(get_db), staff: dict = Depends(current_staff)):
    """Stock-out rate, days of cover, wastage rate, on-time replenishment and forecast WAPE. Each has a value
    (a fraction), its HLD target and `met`; both are null when there is nothing to measure yet."""
    check_store(staff, store_id)
    return service.kpis(db, store_id)
