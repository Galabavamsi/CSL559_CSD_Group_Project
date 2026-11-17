"""HTTP endpoints for the Inventory Service (HLD section 8.1)."""
import h3
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from ... import config
from ...auth import check_store, current_staff, require_role
from ...db import get_db
from . import service

router = APIRouter(tags=["inventory"])


class LineIn(BaseModel):
    sku_id: int
    qty: int = Field(gt=0)


class ReservationIn(BaseModel):
    order_id: str = Field(min_length=1, max_length=60)
    store_id: int
    lines: list[LineIn] = Field(min_length=1)
    h3_cell: str | None = Field(default=None, max_length=16,
                                description="H3 cell of the delivery address, from GET /v1/serviceability")

    @field_validator("h3_cell")
    @classmethod
    def _cell_of_the_zone_size(cls, cell: str | None) -> str | None:
        if cell is not None and not (h3.is_valid_cell(cell) and h3.get_resolution(cell) == config.H3_RESOLUTION):
            raise ValueError(f"must be an H3 cell at resolution {config.H3_RESOLUTION}")
        return cell


class AdjustmentIn(BaseModel):
    store_id: int
    sku_id: int
    delta: int
    reason: str = Field(pattern="^(damage|expiry|theft|count)$")
    bin_id: int | None = None
    actor: str = "manager"


@router.get("/v1/stores/{store_id}/availability")
def get_availability(store_id: int, skus: str | None = Query(None, description="Comma-separated SKU ids; omit for all"),
                     db: Session = Depends(get_db)):
    sku_ids = [int(s) for s in skus.split(",") if s.strip()] if skus else None
    return service.availability(db, store_id, sku_ids)


@router.post("/v1/reservations", status_code=201)
def create_reservation(body: ReservationIn, db: Session = Depends(get_db)):
    res = service.reserve(db, body.order_id, body.store_id, [(line.sku_id, line.qty) for line in body.lines],
                          body.h3_cell)
    return service.reservation_view(res)


@router.get("/v1/reservations/{reservation_id}")
def read_reservation(reservation_id: str, db: Session = Depends(get_db)):
    return service.reservation_view(service.get_reservation(db, reservation_id))


@router.post("/v1/reservations/{reservation_id}/confirm")
def confirm_reservation(reservation_id: str, db: Session = Depends(get_db)):
    return service.reservation_view(service.confirm(db, reservation_id))


@router.delete("/v1/reservations/{reservation_id}")
def release_reservation(reservation_id: str, db: Session = Depends(get_db)):
    return service.reservation_view(service.release(db, reservation_id))


@router.post("/v1/stock-adjustments")
def create_adjustment(body: AdjustmentIn, db: Session = Depends(get_db),
                      staff: dict = Depends(require_role("manager"))):
    check_store(staff, body.store_id)
    return service.adjust(db, body.store_id, body.sku_id, body.delta, body.reason, body.bin_id, body.actor)


@router.get("/v1/stores/{store_id}/stock")
def read_stock_by_bin(store_id: int, db: Session = Depends(get_db),
                      staff: dict = Depends(current_staff)):
    check_store(staff, store_id)
    return service.stock_by_bin(db, store_id)


@router.get("/v1/stores/{store_id}/ledger")
def read_ledger(store_id: int, limit: int = 50, db: Session = Depends(get_db),
                staff: dict = Depends(current_staff)):
    check_store(staff, store_id)
    return service.ledger(db, store_id, limit)


@router.post("/v1/admin/sweep-reservations", dependencies=[Depends(require_role("admin"))])
def sweep(db: Session = Depends(get_db)):
    """Release holds that have run out. In production this runs on a timer (see Member 1 guide)."""
    return {"released": service.sweep_expired(db)}
