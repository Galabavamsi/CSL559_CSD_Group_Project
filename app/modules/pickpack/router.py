"""HTTP endpoints used by the picker / packer handheld app."""
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ...auth import check_store, require_role
from ...db import get_db
from ..fulfilment import service as fulfilment
from . import service

router = APIRouter(tags=["pick & pack"])


class ScanIn(BaseModel):
    barcode: str
    qty: int = Field(gt=0)


class PackedIn(BaseModel):
    crate_slot: str = Field(min_length=1, max_length=20)


@router.get("/v1/pickers/{picker_id}/next-task")
def next_task(picker_id: str, store_id: int, db: Session = Depends(get_db),
              staff: dict = Depends(require_role("picker", "packer"))):
    check_store(staff, store_id)
    job = service.next_job(db, picker_id, store_id)
    return {"job": fulfilment.job_view(job) if job else None}


@router.post("/v1/pick-tasks/{task_id}/scans")
def scan(task_id: int, body: ScanIn, db: Session = Depends(get_db),
         staff: dict = Depends(require_role("picker", "packer"))):
    check_store(staff, service.task_store_id(db, task_id))
    return service.scan(db, task_id, body.barcode, body.qty)


@router.post("/v1/pick-tasks/{task_id}/short")
def report_short(task_id: int, db: Session = Depends(get_db),
                 staff: dict = Depends(require_role("picker", "packer"))):
    check_store(staff, service.task_store_id(db, task_id))
    return service.report_short(db, task_id)


@router.post("/v1/fulfilment-jobs/{job_id}/packed")
def packed(job_id: int, body: PackedIn, db: Session = Depends(get_db),
           staff: dict = Depends(require_role("picker", "packer"))):
    check_store(staff, fulfilment.get_job(db, job_id).store_id)
    return fulfilment.job_view(service.pack(db, job_id, body.crate_slot))
