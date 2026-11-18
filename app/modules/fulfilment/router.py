"""HTTP endpoints for the Fulfilment Orchestrator and Rider Handoff."""
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ...auth import check_store, current_staff, require_role
from ...db import get_db
from . import service

router = APIRouter(tags=["fulfilment"])


class CancelIn(BaseModel):
    reason: str = Field(min_length=1, max_length=200)


@router.get("/v1/fulfilment-jobs")
def list_jobs(store_id: int, state: str | None = None, db: Session = Depends(get_db),
              staff: dict = Depends(current_staff)):
    check_store(staff, store_id)
    return [service.job_view(job) for job in service.list_jobs(db, store_id, state)]


@router.get("/v1/stores/{store_id}/fulfilment-metrics", summary="Order-to-pack time, fill rate, picker productivity")
def fulfilment_metrics(store_id: int, db: Session = Depends(get_db), staff: dict = Depends(current_staff)):
    check_store(staff, store_id)
    return service.metrics(db, store_id)


@router.get("/v1/stores/{store_id}/attention", summary="Stalled orders and bags waiting too long for a rider")
def attention(store_id: int, db: Session = Depends(get_db), staff: dict = Depends(current_staff)):
    """`stalled`: no claim, scan or shelf report for PICK_STALL_MINUTES (`units_in_tote` > 0 needs a person).
    `waiting_for_rider`: packed more than RIDER_WAIT_MINUTES ago."""
    check_store(staff, store_id)
    return service.attention(db, store_id)


@router.post("/v1/admin/recover-stalled", dependencies=[Depends(require_role("admin"))],
             summary="Hand idle orders back to the queue now (normally every STALL_CHECK_SECONDS)")
def recover_stalled(db: Session = Depends(get_db)):
    return service.recover_stalled(db)


@router.get("/v1/fulfilment-jobs/{job_id}")
def read_job(job_id: int, db: Session = Depends(get_db),
             staff: dict = Depends(current_staff)):
    job = service.get_job(db, job_id)
    check_store(staff, job.store_id)
    return service.job_view(job)


@router.post("/v1/fulfilment-jobs/{job_id}/cancel", summary="Cancel a paid order that is not packed yet")
def cancel(job_id: int, body: CancelIn, db: Session = Depends(get_db),
           staff: dict = Depends(require_role("manager"))):
    """Gives every hold back and publishes `order.cancelled` (the Order service would refund from it).
    A packed order cannot be cancelled: `409 too_late`. Cancelling again returns the cancelled order.
    The store's manager stands in for the Order service, which would make this call in a real system."""
    check_store(staff, service.get_job(db, job_id).store_id)
    return service.job_view(service.cancel(db, job_id, body.reason))


@router.post("/v1/fulfilment-jobs/{job_id}/handover")
def handover(job_id: int, db: Session = Depends(get_db),
             staff: dict = Depends(require_role("picker", "packer"))):
    check_store(staff, service.get_job(db, job_id).store_id)
    return service.job_view(service.handover(db, job_id))
