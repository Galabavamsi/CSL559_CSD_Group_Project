"""HTTP endpoints used by the picker / packer handheld app."""
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ...auth import check_store, require_role
from ...db import get_db
from ..fulfilment import service as fulfilment
from . import service

router = APIRouter(tags=["pick & pack"])

# No order line is anywhere near this big; the cap turns a typo or a bad client into a 422 instead of a database error.
MAX_UNITS = 1000


class ScanIn(BaseModel):
    barcode: str
    qty: int = Field(default=1, gt=0, le=MAX_UNITS,
                     description="Units scanned in this call: 1 per beep, or the whole line at once")
    picker_id: str | None = Field(default=None, max_length=40,
                                  description="The handheld's picker; if given, a scan into another picker's order "
                                              "is refused (409 not_your_order)")


class ShortIn(BaseModel):
    found: int | None = Field(default=None, ge=0, le=MAX_UNITS,
                              description="Units that were in the bin; the rest are missing. "
                                          "Leave out to mean the units already scanned")
    picker_id: str | None = Field(default=None, max_length=40, description="As for scans")


class PackedIn(BaseModel):
    crate_slot: str = Field(min_length=1, max_length=20)
    picker_id: str | None = Field(default=None, max_length=40, description="As for scans")


@router.get("/v1/pickers/{picker_id}/next-task")
def next_task(picker_id: str, store_id: int, db: Session = Depends(get_db),
              staff: dict = Depends(require_role("picker", "packer"))):
    check_store(staff, store_id)
    job = service.next_job(db, picker_id, store_id)
    return {"job": fulfilment.job_view(job) if job else None}


@router.get("/v1/pickers/{picker_id}/next-batch", summary="One order off-peak, or a batch picked in one walk at peak")
def next_batch(picker_id: str, store_id: int, db: Session = Depends(get_db),
               staff: dict = Depends(require_role("picker", "packer"))):
    """With at least BATCH_PICK_BACKLOG orders waiting, claims up to BATCH_SIZE; with fewer, one. A picker who still
    has orders being picked gets those back. `totes` says which order goes in which tote; `route` is every line still
    to pick from all of them, in walking order; `jobs` are the orders, as /v1/fulfilment-jobs/{id} shows them."""
    check_store(staff, store_id)
    return service.batch_view(service.next_batch(db, picker_id, store_id))


@router.post("/v1/pick-tasks/{task_id}/scans", summary="Scan units of a line into the tote")
def scan(task_id: int, body: ScanIn, db: Session = Depends(get_db),
         staff: dict = Depends(require_role("picker", "packer"))):
    check_store(staff, service.task_store_id(db, task_id))
    return service.scan(db, task_id, body.barcode, body.qty, picker_id=body.picker_id)


@router.post("/v1/pick-tasks/{task_id}/short", summary="The bin has fewer units than the line needs")
def report_short(task_id: int, body: ShortIn | None = None, db: Session = Depends(get_db),
                 staff: dict = Depends(require_role("picker", "packer"))):
    check_store(staff, service.task_store_id(db, task_id))
    return service.report_short(db, task_id, found=body.found if body else None,
                                picker_id=body.picker_id if body else None)


@router.post("/v1/fulfilment-jobs/{job_id}/packed")
def packed(job_id: int, body: PackedIn, db: Session = Depends(get_db),
           staff: dict = Depends(require_role("picker", "packer"))):
    check_store(staff, fulfilment.get_job(db, job_id).store_id)
    return fulfilment.job_view(service.pack(db, job_id, body.crate_slot, picker_id=body.picker_id))
