"""Rider Handoff Adapter (HLD service 11, task 2.7): the right bag goes to the right rider.

    order.ready_for_pickup  ->  assigned   the rider system sends someone (made up here)
    rider arrives           ->  arrived    told which crate slot holds the bag (optional: a handover to a rider
                                           who never checked in records their arrival at the same moment)
    bag handed over         ->  collected  only if the bag scanned at the desk is this rider's order

Before this, handover was one unchecked call: a rider could leave with someone else's bag.
"""
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ... import events
from ...errors import DomainError, not_found
from ...models import FulfilmentJob, RiderAssignment, utcnow
from . import service as fulfilment

# Stand-in for the external rider system's fleet; a packed order gets one of these.
RIDERS = ("R-11", "R-12", "R-13", "R-14", "R-15")


@events.subscribe("order.ready_for_pickup")
def assign_rider(db: Session, store_id: int | None, payload: dict) -> None:
    """Plays the external rider system: send a made-up rider for every packed order. Runs in the packing
    transaction, so a packed order always has a rider. Does not commit."""
    job = db.get(FulfilmentJob, payload["job_id"])
    if job is None or db.scalar(select(RiderAssignment.id).where(RiderAssignment.job_id == job.id)):
        return
    _assign(db, job, RIDERS[job.id % len(RIDERS)])


def _assign(db: Session, job: FulfilmentJob, rider_id: str) -> RiderAssignment:
    """Give the order to this rider and say so (`rider.assigned`). Does not commit."""
    job.rider = RiderAssignment(rider_id=rider_id)
    db.flush()
    events.publish(db, "rider.assigned", job.store_id,
                   {"job_id": job.id, "order_id": job.order_id, "rider_id": rider_id})
    return job.rider


def job_for_order(db: Session, order_id: str) -> FulfilmentJob:
    job = db.scalar(select(FulfilmentJob).where(FulfilmentJob.order_id == order_id))
    if job is None:
        raise not_found("Order", order_id)
    return job


def _rider_of(db: Session, job: FulfilmentJob, rider_id: str) -> RiderAssignment:
    """This order's rider, or a 409 saying why this rider may not have it. An order packed before riders were assigned
    (an old database) goes to the rider who comes for it, so it can never be stuck packed. Does not commit."""
    assignment = job.rider
    if assignment is None and job.state == "packed":
        assignment = _assign(db, job, rider_id)
    if assignment is None:
        raise DomainError(409, "not_ready", f"Order {job.order_id} is not packed yet, so no rider is assigned")
    if assignment.rider_id != rider_id:
        raise DomainError(409, "wrong_rider",
                          f"Order {job.order_id} is for rider {assignment.rider_id}, not {rider_id}")
    return assignment


def arrive(db: Session, rider_id: str, order_id: str) -> dict:
    """The rider is at the store for this order: say which crate slot holds the bag. Commits."""
    job = job_for_order(db, order_id)
    assignment = _rider_of(db, job, rider_id)
    if assignment.status == "collected":
        raise DomainError(409, "already_collected", f"Order {order_id} has already been collected")
    if assignment.status == "assigned":
        assignment.status = "arrived"
        assignment.arrived_at = utcnow()
        db.commit()
    return {"order_id": job.order_id, "rider_id": rider_id, "crate_slot": job.crate_slot, "status": assignment.status}


def handover(db: Session, job_id: int, rider_id: str, scanned_order_id: str) -> FulfilmentJob:
    """The desk scans the bag the rider is about to take. Only this order's bag, to this order's rider: anything else
    is refused and the order stays packed. Checking in first is not required: a rider handed the bag is plainly at
    the store, so their arrival is recorded then if it was not before. Commits; a retry of a handover that went
    through is safe, and any other call after it is told the bag is gone (`already_collected`)."""
    job = fulfilment.get_job(db, job_id)
    if job.state == "handed_over":
        if job.rider and job.rider.rider_id == rider_id and scanned_order_id == job.order_id:
            return job                                          # safe to retry
        taker = f"rider {job.rider.rider_id}" if job.rider else "its rider"
        raise DomainError(409, "already_collected", f"Order {job.order_id} was already collected by {taker}")
    if job.state != "packed":
        raise DomainError(409, "not_packed", f"Job is {job.state}; only a packed order can be handed to a rider")
    assignment = _rider_of(db, job, rider_id)
    if scanned_order_id != job.order_id:
        db.rollback()                                           # nothing changes, not even a fallback assignment
        raise DomainError(409, "wrong_bag", f"Wrong bag: that is order {scanned_order_id}. Rider {rider_id} is here "
                                            f"for order {job.order_id}, in crate slot {job.crate_slot}.")
    now = utcnow()
    handed = db.execute(                                        # conditional, like every state change
        update(FulfilmentJob)
        .where(FulfilmentJob.id == job.id, FulfilmentJob.state == "packed")
        .values(state="handed_over", handed_at=now)
        .execution_options(synchronize_session=False)
    ).rowcount == 1
    if not handed:
        db.rollback()
        db.refresh(job)
        if job.state == "handed_over":
            return job
        raise DomainError(409, "not_packed", f"Job is {job.state}; only a packed order can be handed to a rider")
    db.refresh(job)
    assignment.status = "collected"
    assignment.arrived_at = assignment.arrived_at or now      # handed over without checking in first
    assignment.collected_at = now
    events.publish(db, "fulfilment.state_changed", job.store_id,
                   {"job_id": job.id, "order_id": job.order_id, "state": "handed_over", "rider_id": rider_id})
    db.commit()
    return job

