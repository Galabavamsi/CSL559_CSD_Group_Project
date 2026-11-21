"""HTTP endpoints for the Fulfilment Orchestrator and Rider Handoff."""
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ...auth import check_store, current_staff, require_role
from ...db import get_db
from ...ids import MAX_ID, PathId
from . import riders, service

router = APIRouter(tags=["fulfilment"])

StoreQuery = Annotated[int, Query(ge=1, le=MAX_ID)]              # an impossible store id is a 422, not a 500
RiderId = Annotated[str, Path(min_length=1, max_length=40)]      # as wide as the column it is compared with


class CancelIn(BaseModel):
    reason: str = Field(min_length=1, max_length=200)


class ArriveIn(BaseModel):
    order_id: str = Field(min_length=1, max_length=60)


class HandoverIn(BaseModel):
    rider_id: str = Field(min_length=1, max_length=40)
    scanned_order_id: str = Field(min_length=1, max_length=60, description="The order on the bag the desk scanned")


@router.get("/v1/fulfilment-jobs")
def list_jobs(store_id: StoreQuery, state: str | None = Query(None, max_length=12), db: Session = Depends(get_db),
              staff: dict = Depends(current_staff)):
    check_store(staff, store_id)
    return [service.job_view(job) for job in service.list_jobs(db, store_id, state)]


@router.get("/v1/stores/{store_id}/fulfilment-metrics", summary="Order-to-pack time, fill rate, picker productivity")
def fulfilment_metrics(store_id: PathId, db: Session = Depends(get_db), staff: dict = Depends(current_staff)):
    check_store(staff, store_id)
    return service.metrics(db, store_id)


@router.get("/v1/stores/{store_id}/attention", summary="Stalled orders and bags waiting too long for a rider")
def attention(store_id: PathId, db: Session = Depends(get_db), staff: dict = Depends(current_staff)):
    """`stalled`: no claim, scan or shelf report for PICK_STALL_MINUTES (`units_in_tote` > 0 needs a person).
    `waiting_for_rider`: packed more than RIDER_WAIT_MINUTES ago."""
    check_store(staff, store_id)
    return service.attention(db, store_id)


@router.post("/v1/admin/recover-stalled", dependencies=[Depends(require_role("admin"))],
             summary="Hand idle orders back to the queue now (normally every STALL_CHECK_SECONDS)")
def recover_stalled(db: Session = Depends(get_db)):
    return service.recover_stalled(db)


@router.get("/v1/fulfilment-jobs/{job_id}")
def read_job(job_id: PathId, db: Session = Depends(get_db),
             staff: dict = Depends(current_staff)):
    job = service.get_job(db, job_id)
    check_store(staff, job.store_id)
    return service.job_view(job)


@router.post("/v1/fulfilment-jobs/{job_id}/cancel", summary="Cancel a paid order that is not packed yet")
def cancel(job_id: PathId, body: CancelIn, db: Session = Depends(get_db),
           staff: dict = Depends(require_role("manager"))):
    """Gives every hold back and publishes `order.cancelled` (the Order service would refund from it).
    A packed order cannot be cancelled: `409 too_late`. Cancelling again returns the cancelled order.
    The store's manager stands in for the Order service, which would make this call in a real system."""
    check_store(staff, service.get_job(db, job_id).store_id)
    return service.job_view(service.cancel(db, job_id, body.reason))


@router.post("/v1/riders/{rider_id}/arrive", summary="A rider is at the store: which crate slot holds the bag")
def rider_arrives(rider_id: RiderId, body: ArriveIn, db: Session = Depends(get_db),
                  staff: dict = Depends(require_role("picker", "packer"))):
    """The desk checks the rider in for one order. `409 wrong_rider` if the order is someone else's, `409 not_ready`
    if it is not packed yet."""
    check_store(staff, riders.job_for_order(db, body.order_id).store_id)
    return riders.arrive(db, rider_id, body.order_id)


@router.post("/v1/fulfilment-jobs/{job_id}/handover", summary="Hand the bag to its rider, after scanning it")
def handover(job_id: PathId, body: HandoverIn, db: Session = Depends(get_db),
             staff: dict = Depends(require_role("picker", "packer"))):
    """`scanned_order_id` is the order on the bag the desk just scanned. Refused with `409 wrong_bag` (wrong bag) or
    `409 wrong_rider` (not this order's rider); the order stays packed."""
    check_store(staff, service.get_job(db, job_id).store_id)
    return service.job_view(riders.handover(db, job_id, body.rider_id, body.scanned_order_id))
