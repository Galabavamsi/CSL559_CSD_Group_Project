"""HTTP endpoints for the Inventory Service (HLD section 8.1)."""
import h3
from fastapi import APIRouter, Depends, Header, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from ... import config
from ...idempotency import run_once
from ...auth import check_store, current_staff, require_role
from ...db import get_db
from . import counts, service

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
        return None if cell is None else h3.int_to_str(h3.str_to_int(cell))   # one spelling, so counts add up


class StockSettingsIn(BaseModel):
    safety_buffer: int = Field(ge=0, le=1000, description="Units hidden from customers to absorb small count errors")


class AdjustmentIn(BaseModel):
    store_id: int
    sku_id: int
    delta: int
    reason: str = Field(pattern="^(damage|expiry|theft|count)$")
    bin_id: int | None = None
    actor: str = "manager"


@router.put("/v1/stores/{store_id}/stock-settings/{sku_id}",
            summary="Set the safety buffer for one SKU in one store")
def update_stock_settings(store_id: int, sku_id: int, body: StockSettingsIn, db: Session = Depends(get_db),
                          staff: dict = Depends(require_role("manager"))):
    """ATP becomes on hand - reserved - safety buffer. Existing holds are not affected."""
    check_store(staff, store_id)
    return service.set_safety_buffer(db, store_id, sku_id, body.safety_buffer)


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
                      staff: dict = Depends(require_role("manager")),
                      idempotency_key: str | None = Header(
                          None, min_length=1, max_length=80,
                          description="Any unique string. A retry with the same key does not change stock again; "
                                      "it returns the first answer.")):
    """Correct the count. Send an Idempotency-Key so a double-click or a network retry writes off only once."""
    check_store(staff, body.store_id)
    return run_once(db, "stock-adjustment", idempotency_key, body.model_dump(),
                    lambda: service.adjust(db, body.store_id, body.sku_id, body.delta, body.reason, body.bin_id,
                                           body.actor, commit=False))


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


@router.post("/v1/admin/expire-stock", dependencies=[Depends(require_role("admin"))],
             summary="Write off every batch past its expiry date")
def expire_stock(store_id: int | None = Query(None, description="Omit for every store"),
                 db: Session = Depends(get_db)):
    """Also runs on its own every EXPIRY_INTERVAL_SECONDS (an hour by default)."""
    return {"units_written_off": service.expire_stock(db, store_id)}


@router.get("/v1/stores/{store_id}/near-expiry", summary="Batches that expire within the next few days")
def read_near_expiry(store_id: int, days: int = Query(2, ge=0, le=30, description="0 means expiring today"),
                     db: Session = Depends(get_db), staff: dict = Depends(current_staff)):
    check_store(staff, store_id)
    return service.near_expiry(db, store_id, days)


# --------------------------------------------------------------------------- cycle counts (task 1.5, FR-11)


class CountStartIn(BaseModel):
    store_id: int
    bin_id: int


class CountedLineIn(BaseModel):
    sku_id: int
    counted_qty: int = Field(ge=0)


class CountSubmitIn(BaseModel):
    lines: list[CountedLineIn] = Field(min_length=1)

    @field_validator("lines")
    @classmethod
    def _one_line_per_sku(cls, lines: list[CountedLineIn]) -> list[CountedLineIn]:
        if len({line.sku_id for line in lines}) != len(lines):
            raise ValueError("give each SKU once")
        return lines


COUNTERS = ("picker", "receiver", "manager")


def _count_in_my_store(db: Session, count_id: int, staff: dict):
    count = counts.get_count(db, count_id)
    check_store(staff, count.store_id)
    return count


@router.post("/v1/cycle-counts", status_code=201, summary="Start a blind count of one bin")
def start_count(body: CountStartIn, db: Session = Depends(get_db), staff: dict = Depends(require_role(*COUNTERS))):
    """Returns the SKUs to look for, without quantities. A bin already being counted returns that count."""
    check_store(staff, body.store_id)
    return counts.count_view(counts.start(db, body.store_id, body.bin_id, created_by=staff["sub"]))


@router.get("/v1/cycle-counts/{count_id}", summary="Read a count (no quantities while it is open)")
def read_count(count_id: int, db: Session = Depends(get_db), staff: dict = Depends(current_staff)):
    return counts.count_view(_count_in_my_store(db, count_id, staff))


@router.post("/v1/cycle-counts/{count_id}/submit", summary="Hand in what was counted")
def submit_count(count_id: int, body: CountSubmitIn, db: Session = Depends(get_db),
                 staff: dict = Depends(require_role(*COUNTERS))):
    """Small differences (worth at most COUNT_AUTO_APPROVE_VALUE) are applied at once; bigger ones wait for a
    manager."""
    _count_in_my_store(db, count_id, staff)
    counted = {line.sku_id: line.counted_qty for line in body.lines}
    return counts.count_view(counts.submit(db, count_id, counted, submitted_by=staff["sub"]))


@router.post("/v1/cycle-counts/{count_id}/approve", summary="Apply a count's differences to stock")
def approve_count(count_id: int, db: Session = Depends(get_db), staff: dict = Depends(require_role("manager"))):
    """A manager may not approve a count they submitted themselves (an admin may)."""
    _count_in_my_store(db, count_id, staff)
    return counts.count_view(counts.approve(db, count_id, decided_by=staff["sub"],
                                            may_approve_own=staff["role"] == "admin"))


@router.post("/v1/cycle-counts/{count_id}/reject", summary="Leave stock as it is")
def reject_count(count_id: int, db: Session = Depends(get_db), staff: dict = Depends(require_role("manager"))):
    _count_in_my_store(db, count_id, staff)
    return counts.count_view(counts.reject(db, count_id, decided_by=staff["sub"]))


@router.get("/v1/stores/{store_id}/cycle-counts", summary="A store's counts, newest first")
def list_counts(store_id: int, status: str | None = Query(None, pattern="^(open|submitted|approved|rejected)$",
                                                           description="submitted = waiting for a manager"),
                db: Session = Depends(get_db), staff: dict = Depends(require_role("manager"))):
    check_store(staff, store_id)
    return [counts.count_view(count) for count in counts.list_counts(db, store_id, status)]


@router.get("/v1/stores/{store_id}/inventory-accuracy",
            summary="Share of counted lines that matched the records (HLD 12 target: 99.5%)")
def read_inventory_accuracy(store_id: int, db: Session = Depends(get_db), staff: dict = Depends(current_staff)):
    check_store(staff, store_id)
    service.get_store(db, store_id)
    return counts.inventory_accuracy(db, store_id)

