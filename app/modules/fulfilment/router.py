"""HTTP endpoints for the Fulfilment Orchestrator and Rider Handoff."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ...db import get_db
from . import service

router = APIRouter(tags=["fulfilment"])


@router.get("/v1/fulfilment-jobs")
def list_jobs(store_id: int, state: str | None = None, db: Session = Depends(get_db)):
    return [service.job_view(job) for job in service.list_jobs(db, store_id, state)]


@router.get("/v1/fulfilment-jobs/{job_id}")
def read_job(job_id: int, db: Session = Depends(get_db)):
    return service.job_view(service.get_job(db, job_id))


@router.post("/v1/fulfilment-jobs/{job_id}/handover")
def handover(job_id: int, db: Session = Depends(get_db)):
    return service.job_view(service.handover(db, job_id))
