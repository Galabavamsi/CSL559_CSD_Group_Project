"""HTTP endpoints for the Fulfilment Orchestrator and Rider Handoff."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ...auth import check_store, current_staff, require_role
from ...db import get_db
from . import service

router = APIRouter(tags=["fulfilment"])


@router.get("/v1/fulfilment-jobs")
def list_jobs(store_id: int, state: str | None = None, db: Session = Depends(get_db),
              staff: dict = Depends(current_staff)):
    check_store(staff, store_id)
    return [service.job_view(job) for job in service.list_jobs(db, store_id, state)]


@router.get("/v1/stores/{store_id}/fulfilment-metrics", summary="Order-to-pack time, fill rate, picker productivity")
def fulfilment_metrics(store_id: int, db: Session = Depends(get_db), staff: dict = Depends(current_staff)):
    check_store(staff, store_id)
    return service.metrics(db, store_id)


@router.get("/v1/fulfilment-jobs/{job_id}")
def read_job(job_id: int, db: Session = Depends(get_db),
             staff: dict = Depends(current_staff)):
    job = service.get_job(db, job_id)
    check_store(staff, job.store_id)
    return service.job_view(job)


@router.post("/v1/fulfilment-jobs/{job_id}/handover")
def handover(job_id: int, db: Session = Depends(get_db),
             staff: dict = Depends(require_role("picker", "packer"))):
    check_store(staff, service.get_job(db, job_id).store_id)
    return service.job_view(service.handover(db, job_id))
