"""Fulfilment Orchestrator (HLD service 4) and Rider Handoff Adapter (service 11).

Turns a paid order into a fulfilment job with pick tasks, and tracks the job until a rider
takes the bag:   created -> picking -> packed -> handed_over   (or cancelled).
"""
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ... import config, events
from ...errors import DomainError, not_found
from ...models import FulfilmentJob, PickTask, Reservation, Store, utcnow
from ..inventory import service as inventory

ACTIVE_STATES = ("created", "picking")


@events.subscribe("order.paid")
def on_order_paid(db: Session, store_id: int | None, payload: dict) -> None:
    reservation = db.get(Reservation, payload["reservation_id"])
    if reservation is not None:
        create_job(db, reservation)


def create_job(db: Session, reservation: Reservation) -> FulfilmentJob:
    """Create the job and its pick tasks for a paid order. Does not commit."""
    existing = db.scalar(select(FulfilmentJob).where(FulfilmentJob.order_id == reservation.order_id))
    if existing is not None:
        return existing
    job = FulfilmentJob(order_id=reservation.order_id, reservation_id=reservation.id,
                        store_id=reservation.store_id, state="created")
    db.add(job)
    db.flush()
    for line in reservation.lines:
        add_pick_tasks(db, job, line.sku_id, line.qty)
    resequence(db, job)
    events.publish(db, "fulfilment.state_changed", job.store_id,
                   {"job_id": job.id, "order_id": job.order_id, "state": job.state})
    refresh_store_load(db, job.store_id)
    return job


def add_pick_tasks(db: Session, job: FulfilmentJob, sku_id: int, qty: int,
                   exclude_item_ids: tuple[int, ...] = ()) -> int:
    """Allocate bins for `qty` units and create one pick task per bin.
    Returns the quantity that could not be found anywhere (recorded as a 'short' task)."""
    picks, shortfall = inventory.allocate(db, job.store_id, sku_id, qty, exclude_item_ids)
    for item, take in picks:
        db.add(PickTask(job_id=job.id, sku_id=sku_id, stock_item_id=item.id, bin_id=item.bin_id,
                        qty=take, status="pending"))
    if shortfall:
        db.add(PickTask(job_id=job.id, sku_id=sku_id, qty=shortfall, status="short"))
        inventory.unreserve(db, job.store_id, sku_id, shortfall)
    db.flush()
    return shortfall


def resequence(db: Session, job: FulfilmentJob) -> None:
    """Number the tasks in walking order (nearest bin first) - the pick path from FR-4."""
    tasks = db.scalars(select(PickTask).where(PickTask.job_id == job.id)).all()
    ordered = sorted(tasks, key=lambda t: (t.bin.walk_seq if t.bin else 10**6, t.id))
    for position, task in enumerate(ordered, start=1):
        task.seq = position
    db.flush()
    db.refresh(job)


def refresh_store_load(db: Session, store_id: int) -> None:
    """Mark the store busy when too many orders are waiting, and open again when the queue clears."""
    store = db.get(Store, store_id)
    if store is None or store.status == "closed":
        return
    backlog = db.scalar(
        select(func.count()).select_from(FulfilmentJob)
        .where(FulfilmentJob.store_id == store_id, FulfilmentJob.state.in_(ACTIVE_STATES))
    )
    new_status = "busy" if backlog > config.BUSY_BACKLOG_THRESHOLD else "open"
    if new_status != store.status:
        store.status = new_status
        events.publish(db, "store.status_changed", store_id, {"status": new_status, "backlog": backlog})


def get_job(db: Session, job_id: int) -> FulfilmentJob:
    job = db.get(FulfilmentJob, job_id)
    if job is None:
        raise not_found("Fulfilment job", job_id)
    return job


def list_jobs(db: Session, store_id: int, state: str | None = None) -> list[FulfilmentJob]:
    query = select(FulfilmentJob).where(FulfilmentJob.store_id == store_id)
    if state:
        query = query.where(FulfilmentJob.state == state)
    return list(db.scalars(query.order_by(FulfilmentJob.id.desc()).limit(50)).all())


def handover(db: Session, job_id: int) -> FulfilmentJob:
    """Rider Handoff: the rider has collected the packed bag."""
    job = get_job(db, job_id)
    if job.state == "handed_over":
        return job
    if job.state != "packed":
        raise DomainError(409, "not_packed", f"Job is {job.state}; only a packed order can be handed to a rider")
    job.state = "handed_over"
    job.handed_at = utcnow()
    events.publish(db, "fulfilment.state_changed", job.store_id,
                   {"job_id": job.id, "order_id": job.order_id, "state": job.state})
    db.commit()
    return job


def job_view(job: FulfilmentJob) -> dict:
    def seconds(start, end):
        return round((end - start).total_seconds(), 1) if start and end else None

    return {
        "job_id": job.id,
        "order_id": job.order_id,
        "store_id": job.store_id,
        "state": job.state,
        "picker_id": job.picker_id,
        "crate_slot": job.crate_slot,
        "created_at": job.created_at.isoformat() + "Z",
        "seconds_to_pack": seconds(job.created_at, job.packed_at),
        "tasks": [
            {
                "task_id": t.id,
                "seq": t.seq,
                "sku_id": t.sku_id,
                "sku": t.sku.name,
                "barcode": t.sku.barcode,
                "bin": t.bin.code if t.bin else None,
                "batch_no": t.stock_item.batch_no if t.stock_item else None,
                "expiry_date": t.stock_item.expiry_date.isoformat() if t.stock_item else None,
                "qty": t.qty,
                "status": t.status,
            }
            for t in sorted(job.tasks, key=lambda t: t.seq)
        ],
    }
